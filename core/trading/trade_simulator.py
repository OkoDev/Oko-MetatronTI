"""
Trade Simulator — отслеживание исходов симулированных сделок по SL/TP.
Этап 1 ROADMAP: closed-loop основа для адаптации весов и ML.
"""
import sqlite3
import pandas as pd
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from core.regime_strategy import apply_regime_to_strategy, get_regime_params

logger = logging.getLogger(__name__)

# Статусы сделки
STATUS_OPEN = "OPEN"
STATUS_TP = "TP"
STATUS_SL = "SL"
STATUS_TSL = "TSL"
STATUS_EXPIRED = "EXPIRED"

# Дефолты — entry TF из core.entry_config
from core.entry_config import get_primary_entry_tf, get_cascade_tfs, get_tsl_tf
DEFAULT_TIMEFRAME = get_primary_entry_tf()  # из config.yaml → trading.entry_timeframe
MAX_DURATION_MINUTES = 48 * 60  # 48 часов — затем EXPIRED


def _get_recommendation_value(rec: Any, attr: str, default=None):
    """Безопасное получение атрибута рекомендации (без жёсткой зависимости от типа)."""
    return getattr(rec, attr, default) if rec else default


def _direction_str(direction) -> str:
    if hasattr(direction, "value"):
        return str(direction.value)
    return str(direction) if direction else "NEUTRAL"


def _signal_type_from_recommendation(rec: Any) -> str:
    """Доминирующий тип сигнала из supporting_signals или 'composite'.

    Приоритет от высшего к низшему — отражает качество/редкость сигнала:
      wt_b_signal      WR=85% на бэктесте — самый редкий и качественный
      mtf_bias         главное WT-ядро (7 TF, вес 0.50)
      confluence       производный сложный паттерн (state machine)
      pivot_reversal   разворот у ключевого уровня
      smc_structure    BOS/CHoCH — структура рынка
      wt_signal        базовый WT crossover в OS/OB
      divergence       дивергенция
      trend_signal     смена тренда
      anomaly          всплеск объёма (частый, низкий вес)
    """
    _PRIORITY = [
        "wt_b_signal",
        "mtf_bias",
        "confluence",
        "pivot_reversal",
        "smc_structure",
        "wt_signal",
        "divergence",
        "trend_signal",
        "anomaly",
    ]
    supporting = _get_recommendation_value(rec, "supporting_signals") or []
    if not supporting:
        return "composite"
    present = {
        getattr(s.signal_type, "value", None)
        for s in supporting
        if hasattr(s, "signal_type")
    }
    for stype in _PRIORITY:
        if stype in present:
            return stype
    # Fallback: первый сигнал
    first = supporting[0]
    if hasattr(first, "signal_type") and hasattr(first.signal_type, "value"):
        return first.signal_type.value
    return "composite"


class TradeSimulator:
    """
    Регистрация рекомендаций как симулированных сделок и проверка исходов
    по OHLC (hit SL / hit TP / EXPIRED).
    """

    def __init__(self, db_path: str = "subscriptions.db", max_duration_minutes: float = MAX_DURATION_MINUTES):
        self.db_path = db_path
        self.max_duration_minutes = max_duration_minutes
        self.init_database()
        # DEV-15: LLM-анализатор SL-сделок (инициализируется лениво при первом SL)
        self._trade_analyzer = None
        self._trade_analyzer_init = False
        # DEV-39: скользящее окно SL для Market Event Marker
        self._sl_timestamps: List[datetime] = []

    def init_database(self):
        """Создает таблицу simulated_trades в базе данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS simulated_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL DEFAULT '1h',
                    signal_type TEXT,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    tp1_price REAL,
                    tp1_hit_at TIMESTAMP,
                    strength INTEGER,
                    confidence REAL,
                    regime TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    exit_price REAL,
                    profit_pct REAL,
                    R_multiple REAL,
                    closed_at TIMESTAMP,
                    duration_minutes REAL,
                    features_json TEXT,
                    max_price REAL,
                    min_price REAL,
                    max_R_possible REAL,
                    captured_R_pct REAL,
                    tsl_activated INTEGER DEFAULT 0,
                    be_activated INTEGER DEFAULT 0,
                    sl_source TEXT,
                    tp_source TEXT,
                    strategy_name TEXT,
                    tsl_tf TEXT DEFAULT '15m',
                    tp2_price REAL,
                    tp2_hit_at TIMESTAMP,
                    tp3_price REAL,
                    tp3_hit_at TIMESTAMP,
                    strategy_type TEXT DEFAULT 'SINGLE'
                )
            """)
            # Миграция для существующих БД
            for col, coldef in [
                ("tp1_price", "REAL"), ("tp1_hit_at", "TIMESTAMP"),
                ("tsl_activated", "INTEGER DEFAULT 0"),
                ("be_activated", "INTEGER DEFAULT 0"),
                ("sl_source", "TEXT"), ("tp_source", "TEXT"),
                ("strategy_name", "TEXT"), ("tsl_tf", "TEXT DEFAULT '15m'"),
                ("tp2_price", "REAL"), ("tp2_hit_at", "TIMESTAMP"),
                ("tp3_price", "REAL"), ("tp3_hit_at", "TIMESTAMP"),
                ("strategy_type", "TEXT DEFAULT 'SINGLE'"),
                ("first_profit_r", "REAL"),    # первое наблюдение R > 0 (цена впервые пошла в прибыль)
                ("first_drawdown_r", "REAL"),  # первое наблюдение R < 0 (первый откат ниже entry)
                ("decision_trace_json", "TEXT"),  # DEV-12: полный аудит решения
            ]:
                try:
                    cursor.execute(f"ALTER TABLE simulated_trades ADD COLUMN {col} {coldef}")
                except Exception:
                    pass  # колонка уже существует
            conn.commit()

    def register_trade(self, recommendation: Any, regime: Optional[str] = None, extra_features: Optional[dict] = None) -> Optional[int]:
        """
        Сохраняет сделку в БД при выдаче рекомендации.
        Возвращает id записи или None при ошибке / пропуске.
        """
        try:
            entry = _get_recommendation_value(recommendation, "entry_price")
            ctx = _get_recommendation_value(recommendation, "market_context")
            if entry is None and ctx:
                entry = getattr(ctx, "current_price", None)
            if entry is None or entry <= 0:
                logger.debug("TradeSimulator: пропуск регистрации — нет entry_price")
                return None

            direction = _get_recommendation_value(recommendation, "direction")
            if _direction_str(direction) not in ("LONG", "SHORT"):
                logger.debug("TradeSimulator: пропуск регистрации — направление NEUTRAL")
                return None

            stop_loss  = _get_recommendation_value(recommendation, "stop_loss")
            take_profit = _get_recommendation_value(recommendation, "take_profit")
            tp1_price  = _get_recommendation_value(recommendation, "tp1_price")
            if stop_loss is None and take_profit is None:
                logger.debug("TradeSimulator: пропуск регистрации — нет SL и TP")
                return None

            symbol = _get_recommendation_value(recommendation, "symbol") or ""

            # Dedup открытых позиций: блокируем если по символу уже есть открытая сделка
            # ARCH-15: при bounce_mode допускаем 2 сделки с разным trade_mode (SWING + SCALP)
            trade_mode = ""
            if extra_features:
                trade_mode = extra_features.get("trade_mode", "")
            if symbol:
                try:
                    with sqlite3.connect(self.db_path) as _c:
                        existing_rows = _c.execute(
                            "SELECT id, direction, features_json FROM simulated_trades "
                            "WHERE symbol=? AND status=? LIMIT 5",
                            (symbol, STATUS_OPEN),
                        ).fetchall()
                    if existing_rows:
                        # Если есть trade_mode — проверяем совместимость
                        if trade_mode:
                            for row in existing_rows:
                                ex_features = {}
                                try:
                                    ex_features = json.loads(row[2]) if row[2] else {}
                                except Exception:
                                    pass
                                ex_mode = ex_features.get("trade_mode", "swing")
                                if ex_mode == trade_mode:
                                    # Тот же trade_mode → дубль
                                    logger.info(
                                        "TradeSimulator: [dedup] пропуск %s %s — уже открыта #%d (%s, mode=%s)",
                                        _direction_str(direction), symbol, row[0], row[1], ex_mode,
                                    )
                                    return None
                            # Разные trade_mode → допускаем (SWING + SCALP)
                            logger.info(
                                "TradeSimulator: [bounce] допускаем %s %s mode=%s — есть открытая с другим mode",
                                _direction_str(direction), symbol, trade_mode,
                            )
                        else:
                            # Без trade_mode → старая логика: блокируем
                            logger.info(
                                "TradeSimulator: [dedup] пропуск %s %s — уже открыта #%d (%s)",
                                _direction_str(direction), symbol, existing_rows[0][0], existing_rows[0][1],
                            )
                            return None
                except Exception as _e:
                    logger.debug("TradeSimulator: [dedup] ошибка проверки — %s", _e)

            # DEV-14: Correlation Guard — лимит открытых позиций по направлению
            try:
                from core.config_loader import config as _cfg_cg
                _max_per_dir = int(_cfg_cg.get("trading.max_positions_per_direction", 5))
                _dir_str = _direction_str(direction)
                if _max_per_dir > 0 and _dir_str in ("LONG", "SHORT") and "__SELFTEST__" not in str(symbol):
                    with sqlite3.connect(self.db_path) as _c:
                        _open_count = _c.execute(
                            "SELECT COUNT(*) FROM simulated_trades WHERE status=? AND direction=?",
                            (STATUS_OPEN, _dir_str),
                        ).fetchone()[0]
                    if _open_count >= _max_per_dir:
                        logger.info(
                            "TradeSimulator: [corr_guard] пропуск %s %s — открыто %d/%d %s позиций",
                            _dir_str, symbol, _open_count, _max_per_dir, _dir_str,
                        )
                        return None
            except Exception as _cg_e:
                logger.debug("TradeSimulator: [corr_guard] ошибка — %s", _cg_e)

            strength = _get_recommendation_value(recommendation, "overall_strength")
            confidence = _get_recommendation_value(recommendation, "confidence")
            ts = _get_recommendation_value(recommendation, "timestamp") or datetime.now(timezone.utc)
            if ts.tzinfo is None:
                # DEV-49: astimezone конвертирует из локального в UTC (replace только клеит метку)
                ts = ts.astimezone(timezone.utc)

            # RR-фильтр: при WR=40% нужен RR≥2.0 для положительного EV
            try:
                from core.config_loader import config as _cfg
                MIN_RR = float(_cfg.get("trading.min_rr_ratio", 2.0))
            except Exception:
                MIN_RR = 2.0
            if stop_loss is not None and take_profit is not None and entry is not None and entry > 0:
                sl_dist = abs(float(entry) - float(stop_loss))
                tp_dist = abs(float(take_profit) - float(entry))
                if sl_dist > 0:
                    actual_rr = tp_dist / sl_dist
                    if actual_rr < MIN_RR:
                        logger.info(
                            f"TradeSimulator: пропуск {_direction_str(direction)} {_get_recommendation_value(recommendation,'symbol')} "
                            f"— RR={actual_rr:.2f} < {MIN_RR} (SL={stop_loss:.4f}, TP={take_profit:.4f}, entry={entry:.4f})"
                        )
                        return None

            signal_type = _signal_type_from_recommendation(recommendation)
            sl_source = _get_recommendation_value(recommendation, "sl_source") or None
            tp_source = _get_recommendation_value(recommendation, "tp_source") or None
            metadata = _get_recommendation_value(recommendation, "metadata") or {}
            strategy_name = metadata.get("strategy_name") or None
            # Сохраняем ВСЕ поддерживающие типы сигналов
            supporting = _get_recommendation_value(recommendation, "supporting_signals") or []
            all_signal_types = list(dict.fromkeys(
                s.signal_type.value for s in supporting
                if hasattr(s, "signal_type") and hasattr(s.signal_type, "value")
            ))
            # tsl_tf: для MTF_BIAS сигналов берём старший TF для trailing
            from core.entry_config import ENTRY_TO_TSL_TF
            tsl_tf = DEFAULT_TIMEFRAME
            for _sig in supporting:
                if getattr(getattr(_sig, "signal_type", None), "value", "") == "mtf_bias":
                    _entry_tf = (_sig.data or {}).get("entry_tf", DEFAULT_TIMEFRAME)
                    tsl_tf = ENTRY_TO_TSL_TF.get(_entry_tf, "1h")
                    break
            features = {}
            if all_signal_types:
                features["all_signal_types"] = all_signal_types
                features["n_supporting"] = len(supporting)
            if ctx:
                features["volume_24h"] = getattr(ctx, "volume_24h", None)
                features["price_change_24h"] = getattr(ctx, "price_change_24h", None)
                features["volatility"] = getattr(ctx, "volatility", None)
            if extra_features:
                features.update(extra_features)
            # ARCH-12: MTF Context фичи для ML
            mtf_ctx = metadata.get("mtf_context") if metadata else None
            if mtf_ctx and isinstance(mtf_ctx, dict):
                features["mtf_direction_bias"] = mtf_ctx.get("direction_bias")
                features["mtf_bias_strength"] = mtf_ctx.get("bias_strength")
                features["mtf_price_zone"] = mtf_ctx.get("price_zone")
                features["mtf_aligned_pct"] = mtf_ctx.get("aligned_pct")
                features["mtf_senior_matches"] = mtf_ctx.get("senior_matches")
                features["mtf_regime"] = mtf_ctx.get("regime")
                # DEV-13: использовать regime из MTFContext если не передан явно
                if regime is None:
                    regime = mtf_ctx.get("regime")
                features["mtf_bull_pct"] = mtf_ctx.get("bull_pct")
                features["mtf_bear_pct"] = mtf_ctx.get("bear_pct")
                # WT spreads по старшим ТФ
                wt_sp = mtf_ctx.get("wt_spreads", {})
                for tf in ("1h", "4h", "1d"):
                    features[f"mtf_wt_spread_{tf}"] = wt_sp.get(tf)
                # Senior reversal
                sr = mtf_ctx.get("senior_reversal")
                if sr:
                    features["mtf_sr_direction"] = sr.get("direction")
                    features["mtf_sr_tf"] = sr.get("tf")
                    features["mtf_sr_strength"] = sr.get("strength")
            # ARCH-17: SMC Context фичи для ML
            smc_ctx = metadata.get("smc_context") if metadata else None
            if smc_ctx and isinstance(smc_ctx, dict):
                features.update(smc_ctx)
            features_json = json.dumps(features) if features else None

            # DEV-12: Decision Trace
            decision_trace_json = None
            dt_data = metadata.get("decision_trace") if metadata else None
            if dt_data:
                try:
                    decision_trace_json = json.dumps(dt_data, ensure_ascii=False, default=str)
                except Exception:
                    pass

            # Определяем strategy_type и рассчитываем TP-уровни
            dir_str = _direction_str(direction)
            tp2_price = None
            tp3_price = None
            strategy_type = "SINGLE"
            # DEV-40: ATR-based TP1 (из TradingRecommendation.atr_entry_tf)
            atr_entry = _get_recommendation_value(recommendation, "atr_entry_tf")
            _TP1_REGIME_MULT = {"TREND_UP": 2.0, "TREND_DOWN": 2.0, "RANGE": 1.0}
            _tp1_regime_mult = _TP1_REGIME_MULT.get(regime, 1.5)
            if stop_loss is not None and take_profit is not None and entry is not None and entry > 0:
                sl_dist = abs(float(entry) - float(stop_loss))
                tp_dist = abs(float(take_profit) - float(entry))
                if sl_dist > 0:
                    rr = tp_dist / sl_dist
                    sign = 1.0 if dir_str == "LONG" else -1.0
                    # DEV-64A: global max_rr cap в register_trade (основной путь)
                    try:
                        from core.config_loader import config as _cfg64a
                        _sl_tp_64a = (_cfg64a.get("trading") or {}).get("sl_management") or {}
                        _max_rr_64a = float(
                            _sl_tp_64a.get("max_rr_range" if regime == "RANGE" else "max_rr", 3.0)
                        )
                    except Exception:
                        _max_rr_64a = 3.0
                    if rr > _max_rr_64a:
                        take_profit = float(entry) + sign * sl_dist * _max_rr_64a
                        tp_dist = abs(float(take_profit) - float(entry))
                        rr = _max_rr_64a
                        logger.info(
                            "[DEV-64A] %s R:R cap → %.1fx (regime=%s)", symbol, _max_rr_64a, regime or "?"
                        )
                    if rr >= 3.0:
                        strategy_type = "TRIPLE_TP_TSL"
                        # tp1: ATR-based если доступен, иначе 1/3 tp_dist
                        if tp1_price is None:
                            if atr_entry and atr_entry > 0:
                                tp1_price = float(entry) + sign * atr_entry * _tp1_regime_mult
                            else:
                                tp1_price = float(entry) + sign * tp_dist * (1.0 / 3.0)
                        tp2_price = float(entry) + sign * tp_dist * (2.0 / 3.0)
                        tp3_price = float(take_profit)
                    elif rr >= 2.0:
                        strategy_type = "DUAL_TP"
                        # tp1: ATR-based если доступен, иначе 1/2 tp_dist
                        if tp1_price is None:
                            if atr_entry and atr_entry > 0:
                                tp1_price = float(entry) + sign * atr_entry * _tp1_regime_mult
                            else:
                                tp1_price = float(entry) + sign * tp_dist * 0.5
                        tp2_price = float(take_profit)

                    # TRADER: DUAL_TP в RANGE убыточен (avg_R=-0.942) → деактивируем
                    if strategy_type == "DUAL_TP" and regime == "RANGE":
                        strategy_type = "SINGLE"
                        tp1_price = None
                        tp2_price = None
                        logger.info("[DUAL_TP] %s RANGE → downgrade DUAL_TP к SINGLE", symbol)

            # Адаптируем strategy_type и TP1 на основе режима рынка (ARCH-04)
            if regime and stop_loss is not None and take_profit is not None and entry is not None:
                try:
                    from core.config_loader import config as _cfg_rs  # DEV-70: cfg для risk_management.regime_strategy
                    strategy_type, tp1_price = apply_regime_to_strategy(
                        strategy_type=strategy_type,
                        entry=float(entry),
                        stop_loss=float(stop_loss),
                        take_profit=float(take_profit),
                        tp1_price=tp1_price,
                        direction=dir_str,
                        regime=regime,
                        cfg=_cfg_rs,
                    )
                    # Пересчитываем TP2/TP3 если strategy_type изменился
                    sl_dist_f = abs(float(entry) - float(stop_loss))
                    tp_dist_f = abs(float(take_profit) - float(entry))
                    sign_f = 1.0 if dir_str == "LONG" else -1.0
                    if strategy_type == "TRIPLE_TP_TSL":
                        tp2_price = float(entry) + sign_f * tp_dist_f * (2.0 / 3.0)
                        tp3_price = float(take_profit)
                    elif strategy_type == "DUAL_TP":
                        tp2_price = float(take_profit)
                        tp3_price = None
                    else:
                        tp2_price = None
                        tp3_price = None
                    # ARCH-04 fix: regime_params не определён в этом scope → вызываем get_regime_params
                    from core.trading.regime_strategy import get_regime_params as _grp_412
                    _rp_412 = _grp_412(regime, cfg=_cfg_rs)
                    if _rp_412.position_size_multiplier != 1.0:
                        if features is None:
                            features = {}
                        features["position_size_multiplier"] = _rp_412.position_size_multiplier
                        features_json = json.dumps(features)
                        logger.info(
                            "[regime_strategy] %s %s: position_size×%.2f",
                            symbol, regime, _rp_412.position_size_multiplier,
                        )
                except Exception as _re:
                    logger.debug("[regime_strategy] Ошибка применения: %s", _re)

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO simulated_trades
                    (symbol, timeframe, signal_type, direction, entry_price, stop_loss, take_profit,
                     tp1_price, tp2_price, tp3_price, strategy_type,
                     strength, confidence, regime, status, features_json, created_at,
                     sl_source, tp_source, strategy_name, tsl_tf, decision_trace_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        DEFAULT_TIMEFRAME,
                        signal_type,
                        dir_str,
                        float(entry),
                        float(stop_loss) if stop_loss is not None else None,
                        float(take_profit) if take_profit is not None else None,
                        float(tp1_price) if tp1_price is not None else None,
                        float(tp2_price) if tp2_price is not None else None,
                        float(tp3_price) if tp3_price is not None else None,
                        strategy_type,
                        int(strength) if strength is not None else None,
                        float(confidence) if confidence is not None else None,
                        regime,
                        STATUS_OPEN,
                        features_json,
                        ts.isoformat(),
                        sl_source if isinstance(sl_source, str) else None,
                        tp_source if isinstance(tp_source, str) else None,
                        strategy_name if isinstance(strategy_name, str) else None,
                        tsl_tf,
                        decision_trace_json,
                    ),
                )
                trade_id = cursor.lastrowid
                conn.commit()
            logger.info(f"TradeSimulator: зарегистрирована сделка id={trade_id} {symbol} {_direction_str(direction)}")
            return trade_id
        except Exception as e:
            logger.exception(f"TradeSimulator: ошибка регистрации сделки — {e}")
            return None

    async def register_trade_async(
        self,
        recommendation: Any,
        data_collector: Any = None,
        extra_features: Optional[dict] = None,
    ) -> Optional[int]:
        """
        Async-обёртка над register_trade: получает OHLCV, определяет режим рынка,
        затем сохраняет сделку. Если data_collector недоступен — пишет regime=None.
        extra_features — доп. признаки (напр. distance_to_pivot_pct) для features_json.
        """
        # ARCH-42: Market Stress Gate — блок входов при массовых SL (shadow mode)
        try:
            from core.config_loader import config as _cfg_msg
            _msg = (_cfg_msg.get("trading", {}) or {}).get("market_stress_gate", {}) if _cfg_msg else {}
            if _msg:
                _threshold = int(_msg.get("sl_threshold", 5))
                _window_min = int(_msg.get("window_minutes", 30))
                _now_msg = datetime.now(timezone.utc)
                _window_start_msg = _now_msg - timedelta(minutes=_window_min)
                _recent_sl = [t for t in self._sl_timestamps if t >= _window_start_msg]
                if len(_recent_sl) >= _threshold:
                    _sym_msg = _get_recommendation_value(recommendation, "symbol") or ""
                    if _msg.get("enabled"):
                        logger.info("[ARCH-42] %s БЛОК market_stress: %d SL за %d мин",
                                    _sym_msg, len(_recent_sl), _window_min)
                        return None
                    else:
                        logger.info("[ARCH-42] shadow %s: %d SL за %d мин (gate disabled)",
                                    _sym_msg, len(_recent_sl), _window_min)
        except Exception as _e_msg:
            logger.debug("[ARCH-42] stress gate error: %s", _e_msg)

        # DEV-38: Correlation Guard — блок если по коррелированному активу уже открыта сделка
        try:
            from core.config_loader import config as _cfg_cg38
            _corr_groups = (_cfg_cg38.get("trading", {}).get("correlation_groups", [])
                            if _cfg_cg38 else [])
            if _corr_groups:
                _new_sym = _get_recommendation_value(recommendation, "symbol") or ""
                _new_base = _new_sym.split("/")[0]
                _open_bases = {t["symbol"].split("/")[0] for t in self.get_open_trades()}
                for _group in _corr_groups:
                    if _new_base in _group:
                        _conflict = _open_bases & set(_group) - {_new_base}
                        if _conflict:
                            logger.info(
                                "[DEV-38] Correlation Guard: блок %s — уже открыта %s из той же группы",
                                _new_sym, _conflict,
                            )
                            return None
        except Exception as _e:
            logger.debug("[DEV-38] Correlation Guard error: %s", _e)

        regime: Optional[str] = None
        if data_collector is not None:
            symbol = _get_recommendation_value(recommendation, "symbol") or ""
            if symbol:
                try:
                    from core.market_regime import MarketRegimeClassifier
                    ohlcv = await data_collector.get_ohlcv(symbol, DEFAULT_TIMEFRAME, 50)
                    if ohlcv is not None and not ohlcv.empty:
                        regime = MarketRegimeClassifier().classify_from_ohlcv(ohlcv)
                        logger.debug("MarketRegime для %s: %s", symbol, regime)
                except Exception as e:
                    logger.debug("MarketRegime: не удалось определить для %s — %s", symbol, e)

        # DEV-44 (ARCH-39 fix): Safety gate — второй рубеж, использует свежевычисленный regime
        # Теперь работает для ВСЕХ code-paths (analyze_symbol + WL breach + будущие)
        if regime:
            try:
                from core.config_loader import config as _cfg_44
                if _cfg_44:
                    _sym_44 = _get_recommendation_value(recommendation, "symbol") or ""
                    _dir_44 = _direction_str(_get_recommendation_value(recommendation, "direction"))
                    # Guard 1: blocked_regimes (DEV-33 fallback)
                    if regime in (_cfg_44.get("trading.blocked_regimes") or []):
                        logger.info("[DEV-44] %s БЛОК blocked_regime: %s", _sym_44, regime)
                        return None
                    # Guard 2: regime_direction_block (DEV-32 fallback)
                    _rdb = _cfg_44.get("trading.regime_direction_block") or {}
                    if _rdb.get("enabled") and _rdb.get(regime) == _dir_44:
                        logger.info("[DEV-44] %s БЛОК regime_direction: %s/%s", _sym_44, regime, _dir_44)
                        return None
                    # Guard 3: signal_regime_block (DEV-64B) — блок мёртвых signal_type × regime комбинаций
                    _srb = _cfg_44.get("signal_quality.signal_regime_block") or {}
                    if _srb:
                        _sig_type_44 = str(_get_recommendation_value(recommendation, "signal_type") or "")
                        _srb_sig = _srb.get(_sig_type_44) or {}
                        if regime in (_srb_sig.get("blocked_regimes") or []):
                            logger.info(
                                "[DEV-64B] %s БЛОК signal_regime_block: %s/%s", _sym_44, _sig_type_44, regime
                            )
                            return None
            except Exception as _e44:
                logger.debug("[DEV-44] Safety gate error: %s", _e44)

        # DEV-52: L3 Портфельный лимит (условие 6) — shadow mode
        try:
            from core.config_loader import config as _cfg_52
            _l3 = (_cfg_52.get("trading", {}) or {}).get("l3_checker", {}) if _cfg_52 else {}
            if _l3:
                _max_long  = _l3.get("max_open_long", 2)
                _max_short = _l3.get("max_open_short", 2)
                _max_total = _l3.get("max_open_total", 4)
                _dir_52    = _direction_str(_get_recommendation_value(recommendation, "direction"))
                _sym_52    = _get_recommendation_value(recommendation, "symbol") or symbol
                _open_52   = self.get_open_trades()
                _n_long    = sum(1 for t in _open_52 if t.get("direction") == "LONG")
                _n_short   = sum(1 for t in _open_52 if t.get("direction") == "SHORT")
                _n_total   = len(_open_52)
                _blocked_52 = None
                if _dir_52 == "LONG" and _n_long >= _max_long:
                    _blocked_52 = f"LONG {_n_long}/{_max_long}"
                elif _dir_52 == "SHORT" and _n_short >= _max_short:
                    _blocked_52 = f"SHORT {_n_short}/{_max_short}"
                elif _n_total >= _max_total:
                    _blocked_52 = f"TOTAL {_n_total}/{_max_total}"
                if _blocked_52:
                    if _l3.get("enabled"):
                        logger.info("[DEV-52] %s: портфельный лимит %s", _sym_52, _blocked_52)
                        return None
                    else:
                        logger.info("[DEV-52] shadow %s: портфельный лимит %s (gate disabled)",
                                    _sym_52, _blocked_52)
        except Exception as _e52:
            logger.debug("[DEV-52] portfolio gate error: %s", _e52)

        return self.register_trade(recommendation, regime=regime, extra_features=extra_features)

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Возвращает список открытых сделок."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM simulated_trades WHERE status = ? ORDER BY created_at ASC",
                    (STATUS_OPEN,),
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.exception(f"TradeSimulator: ошибка get_open_trades — {e}")
            return []

    def _get_trade_analyzer(self):
        """DEV-15: Ленивая инициализация TradeAnalyzer (только если API ключ доступен)."""
        if not self._trade_analyzer_init:
            self._trade_analyzer_init = True
            try:
                from core.config_loader import config as _cfg
                if _cfg.get("anthropic.enabled", True):
                    from core.trade_analyzer import TradeAnalyzer
                    self._trade_analyzer = TradeAnalyzer(self.db_path)
                    if not self._trade_analyzer._enabled:
                        self._trade_analyzer = None
            except Exception as e:
                logger.debug("TradeSimulator: TradeAnalyzer не инициализирован — %s", e)
        return self._trade_analyzer

    def close_trade(
        self,
        trade_id: int,
        status: str,
        exit_price: float,
        closed_at: Optional[datetime] = None,
    ) -> bool:
        """Закрывает сделку, считает profit_pct и R_multiple."""
        if status not in (STATUS_TP, STATUS_SL, STATUS_TSL, STATUS_EXPIRED):
            return False
        closed_at = closed_at or datetime.now(timezone.utc)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT entry_price, stop_loss, take_profit, tp1_price, tp1_hit_at, direction, created_at, max_price, min_price FROM simulated_trades WHERE id = ? AND status = ?",
                    (trade_id, STATUS_OPEN),
                )
                row = cursor.fetchone()
                if not row:
                    return False
                entry, sl, tp, tp1_price_db, tp1_hit_at_db, direction, created_at, max_price_db, min_price_db = row
                entry = float(entry)
                sl = float(sl) if sl is not None else None
                tp = float(tp) if tp is not None else None
                tp1_price_db = float(tp1_price_db) if tp1_price_db is not None else None
                max_price_db = float(max_price_db) if max_price_db is not None else None
                min_price_db = float(min_price_db) if min_price_db is not None else None
                dir_up = str(direction).upper()

                # R-multiple: 1R = |entry - stop_loss|
                one_r = None
                r_multiple = None
                if sl is not None and sl != entry:
                    one_r = abs(entry - sl)

                # profit_pct и R с учётом частичного TP1 (50% позиции)
                if tp1_hit_at_db and tp1_price_db and one_r:
                    # TP1 был взят (50% при ~3R), остаток закрывается сейчас
                    if dir_up == "LONG":
                        r_tp1  = (tp1_price_db - entry) / one_r
                        r_exit = (exit_price - entry) / one_r
                        pct_tp1  = (tp1_price_db - entry) / entry * 100.0
                        pct_exit = (exit_price - entry) / entry * 100.0
                    else:
                        r_tp1  = (entry - tp1_price_db) / one_r
                        r_exit = (entry - exit_price) / one_r
                        pct_tp1  = (entry - tp1_price_db) / entry * 100.0
                        pct_exit = (entry - exit_price) / entry * 100.0
                    r_multiple  = round(0.5 * r_tp1  + 0.5 * r_exit, 3)
                    profit_pct  = round(0.5 * pct_tp1 + 0.5 * pct_exit, 4)
                else:
                    # Обычный выход без частичного TP
                    if dir_up == "LONG":
                        profit_pct = (exit_price - entry) / entry * 100.0
                    else:
                        profit_pct = (entry - exit_price) / entry * 100.0
                    if one_r:
                        if dir_up == "LONG":
                            r_multiple = (exit_price - entry) / one_r
                        else:
                            r_multiple = (entry - exit_price) / one_r

                # MFE: максимально достижимый R и % захваченного потенциала
                max_R_possible = None
                captured_R_pct = None
                if one_r and one_r > 0:
                    if str(direction).upper() == "LONG" and max_price_db:
                        max_R_possible = round((max_price_db - entry) / one_r, 3)
                    elif str(direction).upper() == "SHORT" and min_price_db:
                        max_R_possible = round((entry - min_price_db) / one_r, 3)
                    if max_R_possible and max_R_possible > 0 and r_multiple is not None:
                        captured_R_pct = round((r_multiple / max_R_possible) * 100.0, 1)

                # duration_minutes (оба timestamp должны быть aware UTC)
                try:
                    if isinstance(created_at, str):
                        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    else:
                        created_dt = created_at
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    _closed_utc = closed_at if closed_at.tzinfo else closed_at.replace(tzinfo=timezone.utc)
                    duration_minutes = (_closed_utc - created_dt).total_seconds() / 60.0
                    if duration_minutes < 0:
                        duration_minutes = abs(duration_minutes)
                        logger.warning("[trade %d] negative duration corrected: created=%s closed=%s",
                                       trade_id, created_at, closed_at)
                except Exception:
                    duration_minutes = None

                cursor.execute(
                    """
                    UPDATE simulated_trades
                    SET status = ?, exit_price = ?, profit_pct = ?, R_multiple = ?,
                        closed_at = ?, duration_minutes = ?, max_R_possible = ?, captured_R_pct = ?
                    WHERE id = ?
                    """,
                    (status, exit_price, profit_pct, r_multiple,
                     closed_at.isoformat(), duration_minutes,
                     max_R_possible, captured_R_pct, trade_id),
                )
                conn.commit()
            logger.info(f"TradeSimulator: закрыта сделка id={trade_id} {status} exit={exit_price:.4f} R={r_multiple}")

            # DEV-39: Market Event Marker — скользящее окно SL
            if status == STATUS_SL:
                try:
                    from core.config_loader import config as _cfg
                    _me = _cfg.get("trading", {}).get("market_event_marker", {}) if _cfg else {}
                    if _me.get("enabled", True):
                        _sl_count_thr = int(_me.get("sl_count", 5))
                        _window_min   = int(_me.get("window_minutes", 30))
                        _now = datetime.now(timezone.utc)
                        self._sl_timestamps.append(_now)
                        _window_start = _now - timedelta(minutes=_window_min)
                        self._sl_timestamps = [t for t in self._sl_timestamps if t >= _window_start]
                        if len(self._sl_timestamps) >= _sl_count_thr:
                            logger.warning(
                                "[DEV-39] Market Event: %d SL за %d мин → маркируем сделки в окне",
                                len(self._sl_timestamps), _window_min,
                            )
                            self._mark_market_event_in_window(_window_start)
                except Exception as _e:
                    logger.debug("[DEV-39] Market Event Marker error: %s", _e)

            return True
        except Exception as e:
            logger.exception(f"TradeSimulator: ошибка close_trade {trade_id} — {e}")
            return False

    def _mark_market_event_in_window(self, window_start: datetime) -> None:
        """DEV-39: ретроактивно помечает SL-сделки в окне как market_event=true."""
        try:
            ws_str = window_start.isoformat()
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT id, features_json FROM simulated_trades "
                    "WHERE status = ? AND closed_at >= ?",
                    (STATUS_SL, ws_str),
                ).fetchall()
                updated = 0
                for row_id, feat_js in rows:
                    try:
                        feat = json.loads(feat_js) if feat_js else {}
                    except Exception:
                        feat = {}
                    if feat.get("market_event"):
                        continue  # уже помечена
                    feat["market_event"] = True
                    conn.execute(
                        "UPDATE simulated_trades SET features_json = ? WHERE id = ?",
                        (json.dumps(feat, ensure_ascii=False), row_id),
                    )
                    updated += 1
                conn.commit()
            if updated:
                logger.info("[DEV-39] _mark_market_event_in_window: помечено %d сделок", updated)
        except Exception as e:
            logger.debug("[DEV-39] _mark_market_event_in_window error: %s", e)

    async def check_open_trades_with_tsl(
        self,
        data_collector: Any,
        use_tsl: bool = True,
        tsl_activation_r: float = 1.0,
        use_breakeven: bool = True,
        breakeven_activation_r: float = 0.5,
        use_be_after_tp1: bool = False,
        cascade_tsl: bool = True,
    ) -> int:
        """
        Проверяет открытые сделки с поддержкой TSL (Trailing Stop Loss).
        TSL активируется после достижения tsl_activation_r прибыли.
        Безубыток активируется после достижения breakeven_activation_r (до TSL).

        Args:
            data_collector: Источник OHLCV данных
            use_tsl: Включить TSL логику
            tsl_activation_r: После скольки R активировать TSL (1.0 = после +1R)

        Returns:
            Количество закрытых сделок
        """
        open_trades = self.get_open_trades()
        if not open_trades:
            return 0

        closed_count = 0
        for trade in open_trades:
            trade_id = trade["id"]
            symbol = trade["symbol"]
            direction = (trade["direction"] or "").upper()
            entry = float(trade["entry_price"])
            sl = trade["stop_loss"]
            tp = trade["take_profit"]
            tp1_price  = trade.get("tp1_price")
            tp1_hit_at = trade.get("tp1_hit_at")
            tp2_price  = trade.get("tp2_price")
            tp2_hit_at = trade.get("tp2_hit_at")
            tp3_price  = trade.get("tp3_price")
            tp3_hit_at = trade.get("tp3_hit_at")
            if sl is not None:
                sl = float(sl)
            if tp is not None:
                tp = float(tp)
            if tp1_price is not None:
                tp1_price = float(tp1_price)
            if tp2_price is not None:
                tp2_price = float(tp2_price)
            if tp3_price is not None:
                tp3_price = float(tp3_price)

            created_at = trade["created_at"]
            try:
                if isinstance(created_at, str):
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                else:
                    created_dt = created_at
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
            except Exception:
                created_dt = datetime.now(timezone.utc)

            now = datetime.now(timezone.utc)
            age_minutes = (now - created_dt).total_seconds() / 60.0
            try:
                from core.config_loader import config as _cfg
                _max_dur = float(_cfg.get("trading.max_trade_duration_hours", 48)) * 60
            except Exception:
                _max_dur = self.max_duration_minutes
            _is_expired = age_minutes >= _max_dur

            tf = trade.get("timeframe") or DEFAULT_TIMEFRAME
            try:
                df = await data_collector.get_ohlcv(symbol, timeframe=tf, limit=200)
            except Exception as e:
                logger.debug(f"TradeSimulator: get_ohlcv {symbol} — {e}")
                continue

            if df is None or len(df) == 0:
                continue

            # Оставляем только свечи после created_at
            if "time" in df.columns:
                df = df.copy()
                df["time"] = pd.to_numeric(df["time"], errors="coerce")
                try:
                    ts_sec = created_dt.timestamp()
                    df_filtered = df[df["time"] >= ts_sec * 1000].copy()
                    # DEV-49: при пустом фильтре — пропускаем чек (не используем pre-entry бары)
                    if len(df_filtered) == 0:
                        logger.warning(
                            "[trade %d] нет баров после created_at (%s) — пропуск чека SL/TP",
                            trade_id, created_at,
                        )
                        continue
                    df = df_filtered
                except Exception:
                    pass
            if len(df) == 0:
                continue

            # Расчет текущего R-multiple для проверки активации TSL
            current_price = df.iloc[-1]["close"]
            current_r = None
            if sl is not None and sl != entry:
                one_r = abs(entry - sl)
                if direction == "LONG":
                    current_r = (current_price - entry) / one_r
                else:
                    current_r = (entry - current_price) / one_r

            # DEV-40: Безубыток — перенести SL в entry ± 0.1% после достижения breakeven_activation_r
            # use_be_after_tp1: альтернативный триггер — BE при хите TP1 (независимо от R)
            be_activated = bool(trade.get("be_activated"))
            _be_trigger_r = (use_breakeven and not be_activated and current_r is not None and current_r >= breakeven_activation_r)
            _be_trigger_tp1 = (use_be_after_tp1 and not be_activated and tp1_hit_at is not None)
            if (_be_trigger_r or _be_trigger_tp1) and sl is not None:
                be_sl = entry * (1.001 if direction == "LONG" else 0.999)
                should_move = (
                    (direction == "LONG" and sl < be_sl) or
                    (direction == "SHORT" and sl > be_sl)
                )
                if should_move:
                    try:
                        with sqlite3.connect(self.db_path) as _c:
                            _c.execute(
                                "UPDATE simulated_trades SET stop_loss=?, be_activated=1 WHERE id=? AND status=?",
                                (be_sl, trade_id, STATUS_OPEN),
                            )
                            _c.commit()
                        sl = be_sl
                        be_activated = True
                        logger.info("[DEV-40] Breakeven %s id=%d sl→%.6f (R=%.2f)", symbol, trade_id, be_sl, current_r)
                    except Exception as _be_e:
                        logger.debug("[DEV-40] breakeven update error: %s", _be_e)

            # TSL логика
            tsl_triggered = False
            tsl_price = None

            # DEV-73: TSL активируется по current_r для ВСЕХ стратегий (был баг: DUAL/TRIPLE ждали tp1_hit_at)
            _strategy_type = trade.get("strategy_type", "SINGLE")
            _is_multi_tp = _strategy_type in ("DUAL_TP", "TRIPLE_TP_TSL")
            _tsl_gate = (current_r is not None and current_r >= tsl_activation_r)
            if use_tsl and _tsl_gate:
                # Активируем TSL после достижения прибыли — помечаем в БД
                try:
                    with sqlite3.connect(self.db_path) as _c:
                        _c.execute(
                            "UPDATE simulated_trades SET tsl_activated=1 WHERE id=? AND tsl_activated=0",
                            (trade_id,),
                        )
                        _c.commit()
                except Exception:
                    pass

                try:
                    from core.indicators import calculate_trend, get_trend_info
                    from core.config_loader import config as _cfg_trend
                    _tsl_atr_p = int(_cfg_trend.get("analysis.indicators.trend.atr_period", 43))
                    _tsl_factor = float(_cfg_trend.get("analysis.indicators.trend.factor", 1.0))

                    df_tsl = None
                    tsl_tf_used = tf

                    if cascade_tsl:
                        # Каскадный TSL (ARCH-10 + DEV-28): двунаправленный каскад.
                        # Эскалация: 15m → 1h → 4h при подтверждении тренда.
                        # Де-эскалация: 4h → 1h при R>=N и истощении WT (DEV-28).
                        _CASCADE_TFS = get_cascade_tfs(DEFAULT_TIMEFRAME)
                        prev_tsl_tf = trade.get("tsl_tf") or DEFAULT_TIMEFRAME
                        best_tsl_tf = None

                        # Читаем флаг де-эскалации из features_json
                        _feat_js: dict = {}
                        try:
                            _feat_js = json.loads(trade.get("features_json") or "{}")
                        except Exception:
                            pass
                        _tsl_degraded = bool(_feat_js.get("tsl_degraded", False))

                        if _tsl_degraded:
                            # После де-эскалации — используем сохранённый ТФ, не повышаем.
                            _ctf = prev_tsl_tf
                            try:
                                df_c = await data_collector.get_ohlcv(symbol, timeframe=_ctf, limit=100)
                                if df_c is not None and len(df_c) >= 50:
                                    df_c_trend = calculate_trend(df_c, atr_period=_tsl_atr_p, factor=_tsl_factor)
                                    trend_val = int(df_c_trend["trend"].iloc[-1])
                                    if (direction == "LONG" and trend_val == 1) or \
                                       (direction == "SHORT" and trend_val == -1):
                                        best_tsl_tf = _ctf
                                        df_tsl = df_c_trend
                            except Exception:
                                pass
                        else:
                            # Нормальная эскалация: самый старший ТФ где тренд совпадает.
                            for _ctf in _CASCADE_TFS:
                                try:
                                    df_c = await data_collector.get_ohlcv(symbol, timeframe=_ctf, limit=100)
                                    if df_c is not None and len(df_c) >= 50:
                                        df_c_trend = calculate_trend(df_c, atr_period=_tsl_atr_p, factor=_tsl_factor)
                                        trend_val = int(df_c_trend["trend"].iloc[-1])
                                        if (direction == "LONG" and trend_val == 1) or \
                                           (direction == "SHORT" and trend_val == -1):
                                            best_tsl_tf = _ctf
                                            df_tsl = df_c_trend
                                except Exception:
                                    pass

                            # ── DEV-28: Де-эскалация при истощении импульса ──────────
                            # Условия: R >= порога AND WT на текущем ТФ исчерпан
                            # AND младший ТФ даёт более тесный TSL.
                            try:
                                from core.config_loader import config as _cfg_ts
                                _de_esc_r = float(_cfg_ts.get("trading.cascade_tsl_deescalation_r", 5.0))
                                _wt_ob = float(_cfg_ts.get("analysis.indicators.wavetrend.ob_threshold", 60.0))
                                _wt_os = float(_cfg_ts.get("analysis.indicators.wavetrend.os_threshold", -60.0))
                            except Exception:
                                _de_esc_r, _wt_ob, _wt_os = 5.0, 60.0, -60.0

                            if (best_tsl_tf is not None and current_r is not None and
                                    current_r >= _de_esc_r and best_tsl_tf in _CASCADE_TFS):
                                _cas_idx = _CASCADE_TFS.index(best_tsl_tf)
                                if _cas_idx > 0:
                                    _wt_exhausted = False
                                    _wt1_last = None
                                    try:
                                        from core.indicators import calculate_wt
                                        _df_wt_chk = calculate_wt(df_tsl)
                                        _wt1_last = float(_df_wt_chk["wt1"].iloc[-1])
                                        if direction == "SHORT" and _wt1_last < _wt_os:
                                            _wt_exhausted = True
                                        elif direction == "LONG" and _wt1_last > _wt_ob:
                                            _wt_exhausted = True
                                    except Exception:
                                        pass

                                    if _wt_exhausted:
                                        lower_tf = _CASCADE_TFS[_cas_idx - 1]
                                        try:
                                            df_lower = await data_collector.get_ohlcv(
                                                symbol, timeframe=lower_tf, limit=100
                                            )
                                            if df_lower is not None and len(df_lower) >= 50:
                                                df_lower_trend = calculate_trend(df_lower, atr_period=_tsl_atr_p, factor=_tsl_factor)
                                                _lower_info = get_trend_info(df_lower_trend)
                                                _curr_info = get_trend_info(df_tsl)
                                                if (_lower_info and _curr_info and
                                                        _lower_info["tsl"] > 0 and _curr_info["tsl"] > 0):
                                                    _lower_tsl = _lower_info["tsl"]
                                                    _curr_tsl = _curr_info["tsl"]
                                                    # SHORT: тесней = trendup ниже (ближе к цене сверху)
                                                    # LONG:  тесней = trenddown выше (ближе к цене снизу)
                                                    _is_tighter = (
                                                        (direction == "SHORT" and _lower_tsl < _curr_tsl) or
                                                        (direction == "LONG" and _lower_tsl > _curr_tsl)
                                                    )
                                                    if _is_tighter:
                                                        logger.info(
                                                            "[cascade_tsl] %s: de-escalate %s → %s "
                                                            "(R=%.1fR, WT=%.1f, TSL %.4f → %.4f тесней)",
                                                            symbol, best_tsl_tf, lower_tf,
                                                            current_r, _wt1_last, _curr_tsl, _lower_tsl,
                                                        )
                                                        best_tsl_tf = lower_tf
                                                        df_tsl = df_lower_trend
                                                        _feat_js["tsl_degraded"] = True
                                        except Exception:
                                            pass

                        if not best_tsl_tf and _tsl_degraded:
                            logger.info(
                                "[cascade_tsl] %s: degraded TF %s потерял тренд → fallback entry TF",
                                symbol, prev_tsl_tf,
                            )
                            # DEV-67: cascade TSL fallback при развороте тренда
                            if df_tsl is None and prev_tsl_tf != DEFAULT_TIMEFRAME:
                                try:
                                    df_fallback = await data_collector.get_ohlcv(
                                        symbol, timeframe=prev_tsl_tf, limit=100
                                    )
                                    if df_fallback is not None and len(df_fallback) >= 50:
                                        df_tsl = calculate_trend(df_fallback, atr_period=_tsl_atr_p, factor=_tsl_factor)
                                        tsl_tf_used = prev_tsl_tf
                                        logger.info(
                                            "[cascade_tsl] %s: trend reversed, fallback to prev_tsl_tf=%s",
                                            symbol, prev_tsl_tf,
                                        )
                                except Exception:
                                    pass

                        if best_tsl_tf:
                            tsl_tf_used = best_tsl_tf
                            if best_tsl_tf != prev_tsl_tf:
                                action_label = "de-escalate" if _feat_js.get("tsl_degraded") and not _tsl_degraded else "trend confirmed"
                                logger.info(
                                    "[cascade_tsl] %s: TSL %s → %s (%s)",
                                    symbol, prev_tsl_tf, best_tsl_tf, action_label,
                                )
                                try:
                                    with sqlite3.connect(self.db_path) as _c:
                                        _c.execute(
                                            "UPDATE simulated_trades SET tsl_tf=?, features_json=? WHERE id=?",
                                            (best_tsl_tf, json.dumps(_feat_js), trade_id),
                                        )
                                        _c.commit()
                                except Exception:
                                    pass
                    else:
                        # Классический TSL: один предпочтительный TF
                        preferred_tsl_tf = trade.get("tsl_tf") or DEFAULT_TIMEFRAME
                        for _tsl_try in ([preferred_tsl_tf] if preferred_tsl_tf != tf else ["1h"]):
                            try:
                                df_senior = await data_collector.get_ohlcv(symbol, timeframe=_tsl_try, limit=100)
                                if df_senior is not None and len(df_senior) >= 50:
                                    df_senior_trend = calculate_trend(df_senior, atr_period=_tsl_atr_p, factor=_tsl_factor)
                                    trend_val = int(df_senior_trend["trend"].iloc[-1])
                                    if (direction == "LONG" and trend_val == 1) or \
                                       (direction == "SHORT" and trend_val == -1):
                                        df_tsl = df_senior_trend
                                        tsl_tf_used = _tsl_try
                            except Exception:
                                pass
                            if df_tsl is not None:
                                break

                    if df_tsl is None:
                        df_tsl = calculate_trend(df, atr_period=_tsl_atr_p, factor=_tsl_factor)

                    trend_info = get_trend_info(df_tsl)

                    if trend_info and trend_info["tsl"] > 0:
                        tsl_price = trend_info["tsl"]

                        # Проверка срабатывания TSL
                        if direction == "LONG" and current_price <= tsl_price:
                            tsl_triggered = True
                        elif direction == "SHORT" and current_price >= tsl_price:
                            tsl_triggered = True

                        if tsl_triggered:
                            logger.info(
                                f"TradeSimulator: TSL сработал для {symbol} {direction} "
                                f"entry={entry:.4f} current={current_price:.4f} "
                                f"tsl={tsl_price:.4f} [tf={tsl_tf_used}]"
                            )
                            if self.close_trade(trade_id, STATUS_TSL, current_price):
                                closed_count += 1
                            continue

                except Exception as e:
                    logger.debug(f"TradeSimulator: TSL calculation error {symbol} — {e}")

            # Стандартная проверка SL/TP1/TP (если TSL не сработал)
            exit_status = None
            exit_price_val = None
            max_high = 0.0
            min_low = float("inf")

            # DEV-88: SL по CLOSE (не LOW) для источников на основе TSL-линии.
            # TSL линия — индикаторный уровень, свечной фитиль через неё не = выход.
            # Реальный выход подтверждается закрытием ниже (LONG) / выше (SHORT).
            _sl_src = (trade.get("sl_source") or "").lower()
            _sl_check_close = _sl_src.startswith("tsl_line") or _sl_src.startswith("wl_pivot_tsl")

            for _, row in df.iterrows():
                high  = float(row.get("high",  0) or 0)
                low   = float(row.get("low",   0) or 0)
                close = float(row.get("close", 0) or 0)
                open_ = float(row.get("open",  0) or 0)

                if high > 0:
                    max_high = max(max_high, high)
                if low > 0:
                    min_low = min(min_low, low)

                if direction == "LONG":
                    hit_sl = sl is not None and (close <= sl if _sl_check_close else low <= sl)
                    # TP1 фиксирует часть — только если ещё не сработал
                    if tp1_price and tp1_hit_at is None and high >= tp1_price:
                        tp1_hit_at = datetime.now(timezone.utc).isoformat()
                        try:
                            with sqlite3.connect(self.db_path) as _c:
                                _c.execute(
                                    "UPDATE simulated_trades SET tp1_hit_at=? WHERE id=? AND status=?",
                                    (tp1_hit_at, trade_id, STATUS_OPEN),
                                )
                                _c.commit()
                        except Exception:
                            pass
                        logger.info("TradeSimulator: TP1 hit %s id=%d tp1=%.6f", symbol, trade_id, tp1_price)
                    # TP2
                    if tp2_price and tp2_hit_at is None and tp1_hit_at and high >= tp2_price:
                        tp2_hit_at = datetime.now(timezone.utc).isoformat()
                        try:
                            with sqlite3.connect(self.db_path) as _c:
                                _c.execute(
                                    "UPDATE simulated_trades SET tp2_hit_at=? WHERE id=? AND status=?",
                                    (tp2_hit_at, trade_id, STATUS_OPEN),
                                )
                                _c.commit()
                        except Exception:
                            pass
                        logger.info("TradeSimulator: TP2 hit %s id=%d tp2=%.6f", symbol, trade_id, tp2_price)
                    # TP3 (финальный выход для TRIPLE)
                    if tp3_price and tp3_hit_at is None and tp2_hit_at and high >= tp3_price:
                        tp3_hit_at = datetime.now(timezone.utc).isoformat()
                        exit_status, exit_price_val = STATUS_TP, tp3_price
                    # Обычный TP (SINGLE/DUAL — tp == take_profit)
                    hit_tp = (tp is not None and tp2_hit_at is None and tp1_hit_at is None and high >= tp)
                    if not exit_status:
                        if hit_sl and hit_tp:
                            exit_status, exit_price_val = (STATUS_SL, sl) if (open_ - sl <= tp - open_) else (STATUS_TP, tp)
                        elif hit_sl:
                            exit_status, exit_price_val = STATUS_SL, sl
                        elif hit_tp:
                            exit_status, exit_price_val = STATUS_TP, tp
                else:  # SHORT
                    hit_sl = sl is not None and (close >= sl if _sl_check_close else high >= sl)
                    if tp1_price and tp1_hit_at is None and low <= tp1_price:
                        tp1_hit_at = datetime.now(timezone.utc).isoformat()
                        try:
                            with sqlite3.connect(self.db_path) as _c:
                                _c.execute(
                                    "UPDATE simulated_trades SET tp1_hit_at=? WHERE id=? AND status=?",
                                    (tp1_hit_at, trade_id, STATUS_OPEN),
                                )
                                _c.commit()
                        except Exception:
                            pass
                        logger.info("TradeSimulator: TP1 hit %s id=%d tp1=%.6f", symbol, trade_id, tp1_price)
                    # TP2
                    if tp2_price and tp2_hit_at is None and tp1_hit_at and low <= tp2_price:
                        tp2_hit_at = datetime.now(timezone.utc).isoformat()
                        try:
                            with sqlite3.connect(self.db_path) as _c:
                                _c.execute(
                                    "UPDATE simulated_trades SET tp2_hit_at=? WHERE id=? AND status=?",
                                    (tp2_hit_at, trade_id, STATUS_OPEN),
                                )
                                _c.commit()
                        except Exception:
                            pass
                        logger.info("TradeSimulator: TP2 hit %s id=%d tp2=%.6f", symbol, trade_id, tp2_price)
                    # TP3 (финальный для TRIPLE)
                    if tp3_price and tp3_hit_at is None and tp2_hit_at and low <= tp3_price:
                        tp3_hit_at = datetime.now(timezone.utc).isoformat()
                        exit_status, exit_price_val = STATUS_TP, tp3_price
                    hit_tp = (tp is not None and tp2_hit_at is None and tp1_hit_at is None and low <= tp)
                    if not exit_status:
                        if hit_sl and hit_tp:
                            exit_status, exit_price_val = (STATUS_SL, sl) if (sl - open_ <= open_ - tp) else (STATUS_TP, tp)
                        elif hit_sl:
                            exit_status, exit_price_val = STATUS_SL, sl
                        elif hit_tp:
                            exit_status, exit_price_val = STATUS_TP, tp
                if exit_status:
                    break

            # Обновляем MFE экстремумы + first_profit_r / first_drawdown_r
            new_max = max_high if max_high > 0 else None
            new_min = min_low if min_low < float("inf") else None

            # first_profit_r / first_drawdown_r — заполняем один раз (первое наблюдение)
            fp_r = trade.get("first_profit_r")   # None = ещё не фиксировали
            fd_r = trade.get("first_drawdown_r")
            new_fp_r = new_fd_r = None
            if current_r is not None:  # значит one_r вычислен и sl != entry
                if fp_r is None and current_r > 0.1:
                    new_fp_r = round(current_r, 3)
                if fd_r is None and current_r < -0.1:
                    new_fd_r = round(current_r, 3)

            if new_max is not None or new_min is not None or new_fp_r is not None or new_fd_r is not None:
                try:
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute(
                            """UPDATE simulated_trades
                               SET max_price=?, min_price=?,
                                   first_profit_r  = CASE WHEN first_profit_r  IS NULL AND ? IS NOT NULL THEN ? ELSE first_profit_r  END,
                                   first_drawdown_r= CASE WHEN first_drawdown_r IS NULL AND ? IS NOT NULL THEN ? ELSE first_drawdown_r END
                               WHERE id=? AND status=?""",
                            (new_max, new_min,
                             new_fp_r, new_fp_r,
                             new_fd_r, new_fd_r,
                             trade_id, STATUS_OPEN),
                        )
                        conn.commit()
                except Exception as e:
                    logger.debug(f"TradeSimulator: MFE update error {trade_id} — {e}")

            # EXPIRED: проверяем только если TP/SL/TSL не сработал за время жизни сделки
            if not exit_status and _is_expired:
                try:
                    ticker = await data_collector.get_ticker(symbol)
                    if ticker:
                        last = float(ticker.get("last") or ticker.get("close") or entry)
                        if self.close_trade(trade_id, STATUS_EXPIRED, last):
                            closed_count += 1
                            logger.info(
                                "TradeSimulator: EXPIRED %s %s age=%.0fh price=%.6f",
                                symbol, direction, age_minutes / 60, last,
                            )
                except Exception as e:
                    logger.debug(f"TradeSimulator: EXPIRED get_ticker {symbol} — {e}")
                continue

            if exit_status and exit_price_val is not None:
                if self.close_trade(trade_id, exit_status, exit_price_val):
                    closed_count += 1
                    # DEV-15: LLM-разбор для SL-сделок
                    if exit_status == STATUS_SL:
                        analyzer = self._get_trade_analyzer()
                        if analyzer is not None:
                            import asyncio
                            asyncio.create_task(analyzer.analyze_sl_trade(trade_id))

        return closed_count
