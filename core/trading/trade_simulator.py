"""
Trade Simulator — отслеживание исходов симулированных сделок по SL/TP.
Этап 1 ROADMAP: closed-loop основа для адаптации весов и ML.
"""
import sqlite3
import pandas as pd
import logging
import json
import time
import asyncio  # OPS-05
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from core.trading.regime_strategy import apply_regime_to_strategy, get_regime_params

logger = logging.getLogger(__name__)

# Статусы сделки
STATUS_OPEN = "OPEN"
STATUS_TP = "TP"
STATUS_SL = "SL"
STATUS_TSL = "TSL"
STATUS_EXPIRED = "EXPIRED"

# Дефолты — entry TF из core.entry_config
from core.infra.entry_config import get_primary_entry_tf, get_cascade_tfs, get_tsl_tf
DEFAULT_TIMEFRAME = get_primary_entry_tf()  # из config.yaml → trading.entry_timeframe


def _get_recommendation_value(rec: Any, attr: str, default=None):
    """Безопасное получение атрибута рекомендации (без жёсткой зависимости от типа)."""
    return getattr(rec, attr, default) if rec else default


def _direction_str(direction) -> str:
    """Legacy wrapper над core.signals.signal_models.to_direction (DRY 27.05.2026).
    Сохранён для обратной совместимости — внешние модули могут импортировать."""
    from core.signals.signal_models import to_direction
    return to_direction(direction)


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

    def __init__(self, db_path: str = "subscriptions.db"):
        self.db_path = db_path
        self._bot_ref = None  # weakref на bot (для confirmation_aggregator)
        self.init_database()
        # DEV-15: LLM-анализатор SL-сделок (инициализируется лениво при первом SL)
        self._trade_analyzer = None
        self._trade_analyzer_init = False
        # DEV-39: скользящее окно SL для Market Event Marker
        self._sl_timestamps: List[datetime] = []
        # DEV-92 / TR-010: Post-TSL очередь для OTE Re-entry мониторинга
        self._post_tsl_queue: dict = {}
        # DEV-94: callback от PostTradeAnalyser (устанавливается при старте бота)
        self._post_trade_callback = None
        # SSE broadcast: async callback(trade_id) для дашборда (устанавливается из dashboard_server)
        self._sse_trade_closed = None
        # DEV-222: TG reply callback — async(trade_id, status, symbol, direction, r_multiple, tsl_activated, max_r_possible)
        self._tg_close_callback = None
        # DEV-223: TG алерт при активации TSL — async(trade_id, symbol, direction, current_r, tsl_tf)
        self._tg_tsl_alert_callback = None
        # DEV-89: общий PivotCalculatorFixed — создаётся один раз, не на каждую сделку
        self._pivot_calc: object = None
        # DEV-148: защита от concurrent close одной сделки (database is locked cascade)
        self._close_in_progress: set = set()
        # DEV-168: cooldown для LIVE-GUARD логов (не спамить каждую минуту)
        self._live_guard_logged: dict = {}  # trade_id → datetime последнего WARNING
        # OPS-06: таймаут LIVE-GUARD. trade_id → datetime ПЕРВОГО детекта exit (для force-close по таймауту)
        self._live_guard_first_detect: dict = {}
        # DEV-227: throttle для force REST (stale-guard). trade_id → ts последнего force-refresh.
        self._force_rest_ts: dict = {}
        # DS-322: throttle REPAIR-SL для старых SIM-сделок. trade_id → ts последней проверки.
        self._repair_checked: dict = {}
        # SIM-DEPRIO: throttle sim-only check (не биржевые) — освобождает semaphore-бюджет для реальных.
        self._sim_checked: dict = {}  # trade_id → monotonic ts последней проверки

    def set_bot_ref(self, bot) -> None:
        """27.05: weakref на bot для shadow_signal_quality (нужен ConfirmationAggregator)."""
        import weakref
        self._bot_ref = weakref.ref(bot)

    def set_post_trade_callback(self, cb) -> None:
        """DEV-94: регистрирует PostTradeAnalyser.on_trade_closed как callback."""
        self._post_trade_callback = cb

    def set_sse_trade_closed(self, cb) -> None:
        """Регистрирует async callback(trade_id) для SSE broadcast при закрытии сделки."""
        self._sse_trade_closed = cb

    def set_tg_close_callback(self, cb) -> None:
        """DEV-222: TG reply при закрытии — async(trade_id, status, symbol, direction, r_multiple, tsl_activated, max_r_possible)."""
        self._tg_close_callback = cb

    def set_tg_tsl_alert_callback(self, cb) -> None:
        """DEV-223: TG алерт при первой активации TSL — async(trade_id, symbol, direction, current_r, tsl_tf)."""
        self._tg_tsl_alert_callback = cb

    def _db_connect(self, timeout: int = 30):
        """DEV-148: единое место для настройки соединения — WAL + busy_timeout на каждом connect."""
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _write_trade_features(self, trade_id: int, snapshot: dict) -> None:
        """ARCH-118 Шаг 5b: записать единый снимок признаков в таблицу trade_features (1:1, FK).

        Архивный слой Куба. Горячие поля (schema_version/source/entry_tf) — top-level колонки,
        полный снимок — features_json. Не критично к торговле (try/except у вызывающего).
        """
        meta = snapshot.get("meta") or {}
        with self._db_connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO trade_features "
                "(trade_id, schema_version, source, entry_tf, snapshot_ts, n_true, n_total, features_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(trade_id),
                    int(snapshot.get("schema_version", 2)),
                    meta.get("source"),
                    meta.get("entry_tf"),
                    meta.get("snapshot_ts"),
                    meta.get("n_true"),
                    meta.get("n_total"),
                    json.dumps(snapshot, separators=(",", ":")),
                ),
            )
            conn.commit()

    def init_database(self):
        """Создает таблицу simulated_trades в базе данных"""
        with self._db_connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")   # параллельные читатели не блокируют запись
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
                    strategy_type TEXT DEFAULT 'SINGLE',
                    exchange_order_id TEXT,
                    exchange_sl_order_id TEXT,
                    qty REAL,
                    original_sl REAL,
                    magnet_tp_price REAL,
                    magnet_tp_rr REAL,
                    magnet_tp_src TEXT,
                    regime_v2 TEXT
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
                ("exchange_order_id", "TEXT"),    # DEV-136: ID ордера на бирже (VST/LIVE)
                ("exchange_sl_order_id", "TEXT"), # DEV-136: ID SL-ордера на бирже (для cancel+replace TSL)
                ("exchange_tp_order_id", "TEXT"), # ARCH-94: ID TP-ордера на бирже (аудит рассинхрона)
                ("qty", "REAL"),                  # DEV-136: qty позиции (для TSL updater)
                ("actual_entry_price", "REAL"),   # Реальная цена исполнения с биржи (vs entry_price из сигнала)
                ("original_sl", "REAL"),          # SL при регистрации (не изменяется TSL'ом)
                ("magnet_tp_price", "REAL"),      # ARCH-122 P2 shadow: gravity-магнит цена (не закрывает)
                ("magnet_tp_rr", "REAL"),         # ARCH-122 P2 shadow: RR магнита от entry
                ("magnet_tp_src", "TEXT"),        # ARCH-122 P2 shadow: метка кластера (ob+eqh+fvg@price)
                ("regime_v2", "TEXT"),            # ARCH-124 shadow: HTF-доминантная метка режима (vs regime v1)
            ]:
                try:
                    cursor.execute(f"ALTER TABLE simulated_trades ADD COLUMN {col} {coldef}")
                except Exception:
                    pass  # колонка уже существует
            conn.commit()

        # DEV-178: backfill data_era в features_json для существующих сделок
        # Запускается при каждом старте — пропускает уже размеченные (has data_era).
        self._backfill_data_era()

    def _backfill_data_era(self) -> None:
        """
        DEV-178: помечает существующие сделки полем data_era в features_json.
        Идемпотентно — пропускает уже размеченные строки.
        """
        MICRO_SL_PCT = 0.1
        ERA_DATES = [
            ("post_fix",  "2026-04-15"),
            ("post_157",  "2026-03-15"),
        ]
        try:
            with self._db_connect() as conn:
                rows = conn.execute(
                    "SELECT id, created_at, entry_price, stop_loss, features_json "
                    "FROM simulated_trades "
                    "WHERE features_json NOT LIKE '%\"data_era\"%' OR features_json IS NULL"
                ).fetchall()
                if not rows:
                    return
                updated = 0
                for row in rows:
                    fj: dict = {}
                    raw = row[4]
                    if raw:
                        try:
                            fj = json.loads(raw)
                        except Exception:
                            pass
                    if "data_era" in fj:
                        continue
                    # micro-SL check
                    try:
                        ep = float(row[2] or 0)
                        sl = float(row[3] or 0)
                        is_micro = ep > 0 and sl > 0 and abs(ep - sl) / ep * 100 < MICRO_SL_PCT
                    except Exception:
                        is_micro = False
                    if is_micro:
                        fj["data_era"] = "micro_sl_artifact"
                        fj["is_micro_sl"] = True
                    else:
                        created = row[1] or ""
                        era = "pre_157"
                        for era_name, era_date in ERA_DATES:
                            if created >= era_date:
                                era = era_name
                                break
                        fj["data_era"] = era
                    conn.execute(
                        "UPDATE simulated_trades SET features_json = ? WHERE id = ?",
                        (json.dumps(fj, ensure_ascii=False), row[0]),
                    )
                    updated += 1
                if updated:
                    logger.info("TradeSimulator: DEV-178 backfill data_era — %d сделок размечено", updated)
        except Exception as e:
            logger.warning("TradeSimulator: _backfill_data_era ошибка — %s", e)

    def register_trade(
        self, recommendation: Any, regime: Optional[str] = None,
        extra_features: Optional[dict] = None,
        _reason_out: Optional[list] = None,
        regime_v2: Optional[str] = None,
    ) -> Optional[int]:
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
                if _reason_out is not None: _reason_out.append("input:no_entry_price")
                return None

            direction = _get_recommendation_value(recommendation, "direction")
            if _direction_str(direction) not in ("LONG", "SHORT"):
                logger.debug("TradeSimulator: пропуск регистрации — направление NEUTRAL")
                if _reason_out is not None: _reason_out.append("input:neutral_direction")
                return None

            stop_loss  = _get_recommendation_value(recommendation, "stop_loss")
            take_profit = _get_recommendation_value(recommendation, "take_profit")
            tp1_price  = _get_recommendation_value(recommendation, "tp1_price")
            if stop_loss is None and take_profit is None:
                logger.debug("TradeSimulator: пропуск регистрации — нет SL и TP")
                if _reason_out is not None: _reason_out.append("input:no_sl_no_tp")
                return None

            symbol = _get_recommendation_value(recommendation, "symbol") or ""

            # Dedup открытых позиций: блокируем если по символу уже есть открытая сделка
            # ARCH-15: при bounce_mode допускаем 2 сделки с разным trade_mode (SWING + SCALP)
            # 27.05.2026 (hedge fix): дубли считаем ТОЛЬКО при совпадении direction.
            # На бирже LONG и SHORT по одной паре в hedge mode — независимые позиции.
            # До фикса: confluence LONG TRB блокировался если adopted SHORT TRB уже OPEN.
            trade_mode = ""
            if extra_features:
                trade_mode = extra_features.get("trade_mode", "")
            _dir_dedup = _direction_str(direction)
            if symbol:
                try:
                    with self._db_connect() as _c:
                        existing_rows = _c.execute(
                            "SELECT id, direction, features_json FROM simulated_trades "
                            "WHERE symbol=? AND status=? AND direction=? LIMIT 5",
                            (symbol, STATUS_OPEN, _dir_dedup),
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
                                        _dir_dedup, symbol, row[0], row[1], ex_mode,
                                    )
                                    if _reason_out is not None: _reason_out.append(f"dedup:same_mode:{ex_mode}")
                                    return None
                            # Разные trade_mode → допускаем (SWING + SCALP)
                            logger.info(
                                "TradeSimulator: [bounce] допускаем %s %s mode=%s — есть открытая с другим mode",
                                _dir_dedup, symbol, trade_mode,
                            )
                        else:
                            # Без trade_mode → старая логика: блокируем (но уже только same direction)
                            logger.info(
                                "TradeSimulator: [dedup] пропуск %s %s — уже открыта #%d (%s)",
                                _dir_dedup, symbol, existing_rows[0][0], existing_rows[0][1],
                            )
                            if _reason_out is not None: _reason_out.append(f"dedup:no_mode:open_id={existing_rows[0][0]}")
                            return None
                except Exception as _e:
                    logger.debug("TradeSimulator: [dedup] ошибка проверки — %s", _e)

            # DEV-14: Correlation Guard — лимит открытых позиций по направлению.
            # 27.05.2026: hard guard деактивирован (default=0). Защита от концентрированной
            # экспозиции теперь обеспечивается: circuit_breaker, RiskIntelligenceV1, ARCH-88
            # Loss Memory, per-source min_strength, TSL+BE. Soft penalty в gates/correlation_guard.py
            # остаётся (штрафует strength при превышении, но не блокирует).
            try:
                from core.infra.config_loader import config as _cfg_cg
                _max_per_dir = int(_cfg_cg.get("trading.max_positions_per_direction", 0))
                _dir_str = _direction_str(direction)
                if _max_per_dir > 0 and _dir_str in ("LONG", "SHORT") and "__SELFTEST__" not in str(symbol):
                    with self._db_connect() as _c:
                        # 27.05.2026: исключаем adopted_orphan — это позиции, открытые НЕ ботом,
                        # а захваченные через scripts/adopt_orphans.py. Считать их в лимит = терять трафик.
                        _open_count = _c.execute(
                            "SELECT COUNT(*) FROM simulated_trades "
                            "WHERE status=? AND direction=? "
                            "AND (strategy_name IS NULL OR strategy_name != 'adopted_orphan')",
                            (STATUS_OPEN, _dir_str),
                        ).fetchone()[0]
                    if _open_count >= _max_per_dir:
                        logger.info(
                            "TradeSimulator: [corr_guard] пропуск %s %s — открыто %d/%d %s позиций",
                            _dir_str, symbol, _open_count, _max_per_dir, _dir_str,
                        )
                        if _reason_out is not None: _reason_out.append(f"DEV-14:corr_guard:{_dir_str}:{_open_count}/{_max_per_dir}")
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
                from core.infra.config_loader import config as _cfg
                MIN_RR = float(_cfg.get("trading.min_rr_ratio", 2.0))
            except Exception:
                MIN_RR = 2.0
            # DEV-164: guard вынесен ДО проверки take_profit — не зависит от наличия TP
            # DEV-157: guard аномально малого SL (ASR R=-450 при sl_dist=0.002%)
            if stop_loss is not None and entry is not None and entry > 0:
                _sl_dist_raw = abs(float(entry) - float(stop_loss))
                # OTE-RBUG (14.06): валидация СТОРОНЫ SL до проверки расстояния.
                # Инвертный SL (LONG sl>=entry / SHORT sl<=entry) → R/position_size взрыв.
                _dir_s = _direction_str(direction).upper()
                _ef = float(entry); _slf = float(stop_loss)
                if (_dir_s in ("LONG", "BUY") and _slf >= _ef) or (_dir_s in ("SHORT", "SELL") and _slf <= _ef):
                    logger.warning(
                        "TradeSimulator: [OTE-RBUG] пропуск %s %s — SL на неверной стороне (entry=%.6f SL=%.6f)",
                        _dir_s, symbol, _ef, _slf,
                    )
                    if _reason_out is not None: _reason_out.append(f"OTE-RBUG:sl_wrong_side:entry={_ef:.6f},sl={_slf:.6f}")
                    return None
                if _sl_dist_raw > 0:
                    try:
                        from core.infra.config_loader import config as _cfg_sl
                        MIN_SL_DIST_PCT = float(_cfg_sl.get("trading.min_sl_dist_pct", 0.5))
                    except Exception:
                        MIN_SL_DIST_PCT = 0.5
                    _sl_dist_pct = _sl_dist_raw / float(entry) * 100
                    if _sl_dist_pct < MIN_SL_DIST_PCT:
                        logger.warning(
                            "TradeSimulator: [DEV-157/164] пропуск %s %s — SL слишком близко: %.4f%% < %.2f%% (entry=%.6f SL=%.6f)",
                            _direction_str(direction), symbol, _sl_dist_pct, MIN_SL_DIST_PCT, float(entry), float(stop_loss),
                        )
                        if _reason_out is not None: _reason_out.append(f"DEV-157/164:sl_too_close:{_sl_dist_pct:.3f}%<{MIN_SL_DIST_PCT}%")
                        return None

            # RR-фильтр: требует и SL и TP
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
                        if _reason_out is not None: _reason_out.append(f"rr_filter:rr={actual_rr:.2f}<{MIN_RR}")
                        return None

            signal_type = _signal_type_from_recommendation(recommendation)
            if extra_features and extra_features.get("signal_type_override"):
                signal_type = extra_features["signal_type_override"]
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
            from core.infra.entry_config import ENTRY_TO_TSL_TF
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
            # DEV-188 (shadow): pivot_reversal качество входа — real_touch + volume_z.
            # Источник: signal_checkers.check_pivot_signals → sig.data.
            # Цель: после 50+ SHORT TREND_DOWN сделок сравнить WR(real_touch=1) vs WR(0).
            # Не блокирует, только пишет в features_json для shadow-анализа.
            for _sig in supporting:
                _stype = getattr(getattr(_sig, "signal_type", None), "value", "")
                _pdata = getattr(_sig, "data", None) or {}
                if _stype == "pivot_reversal":
                    if "real_touch" in _pdata:
                        features["pivot_real_touch"] = _pdata.get("real_touch")
                        features["pivot_close_rejection"] = _pdata.get("close_rejection")
                        features["pivot_volume_z"] = _pdata.get("volume_z")
                        features["pivot_level"] = _pdata.get("level")
                        features["pivot_type"] = _pdata.get("pivot_type")
                        features["pivot_trend_changed"] = _pdata.get("trend_changed")
                elif _stype == "wt_b_signal":
                    if "div_strength" in _pdata:
                        features["wt_b_div_strength"] = _pdata.get("div_strength")
                        features["wt_b_depth"] = _pdata.get("depth")
                        features["wt_b_wt1"] = _pdata.get("wt1")
                        features["wt_b_zone"] = _pdata.get("zone")
                        features["wt_b_os_adaptive"] = _pdata.get("os_adaptive")
                        features["wt_b_ob_adaptive"] = _pdata.get("ob_adaptive")
            if ctx:
                features["volume_24h"] = getattr(ctx, "volume_24h", None)
                features["price_change_24h"] = getattr(ctx, "price_change_24h", None)
                features["volatility"] = getattr(ctx, "volatility", None)
            if extra_features:
                features.update(extra_features)
            # ARCH-113 shadow: переносим tp_selector_shadow из recommendation.metadata
            try:
                _rec_meta = getattr(recommendation, "metadata", None) or {}
                _tps_shadow = _rec_meta.get("tp_selector_shadow")
                if _tps_shadow:
                    for _k, _v in _tps_shadow.items():
                        features[f"tp_selector_{_k}"] = _v
            except Exception as _shadow_e:
                logger.debug("[ARCH-113 shadow] write to features_json failed: %s", _shadow_e)
            # 27.05: signal_quality shadow (4 правки роя) — pivot real_touch/volume,
            # wt confirmation aggregation, confluence divergence, scan timing.
            try:
                _bot_ref = self._bot_ref() if self._bot_ref else None
                if _bot_ref is not None:
                    from core.observability.shadow_signal_quality import compute_shadow_flags
                    # df_15m из ApiEngine кеша (sync, без REST)
                    _df_15m = None
                    try:
                        _sym_for_df = getattr(recommendation, "symbol", "") or ""
                        if _sym_for_df and data_collector is not None and hasattr(data_collector, "_engine"):
                            _df_15m = data_collector._engine._cache.get_stale((_sym_for_df, "15m"), limit=30)
                    except Exception:
                        pass
                    _scan_dur = (extra_features or {}).get("scan_loop_duration_sec")
                    _shadow = compute_shadow_flags(
                        _bot_ref, recommendation,
                        df_15m=_df_15m,
                        scan_loop_duration_sec=_scan_dur,
                    )
                    if _shadow:
                        features.update(_shadow)
            except Exception as _sq_e:
                logger.debug("[shadow_signal_quality] error: %s (%s)", _sq_e, type(_sq_e).__name__)
            # ML-CONTEXT: entry quality metrics (TF-agnostic)
            _entry_tf_val = _get_recommendation_value(recommendation, "timeframe")
            features["entry_tf"] = str(_entry_tf_val) if isinstance(_entry_tf_val, str) else DEFAULT_TIMEFRAME
            # RR при входе (actual_rr вычислен выше в RR-фильтре)
            try:
                features["rr_at_entry"] = round(actual_rr, 2)
            except NameError:
                pass
            # SL в единицах ATR (TF-agnostic качество стопа)
            _atr_ctx = getattr(ctx, "atr", None) if ctx else None
            if isinstance(_atr_ctx, (int, float)) and _atr_ctx > 0 and entry and stop_loss:
                _sl_abs = abs(float(entry) - float(stop_loss))
                features["sl_atr_ratio"] = round(_sl_abs / _atr_ctx, 2)
            # DEV-149: distance_to_sl_pct — запас до SL в % при открытии
            if entry and stop_loss and float(entry) > 0:
                features["distance_to_sl_pct"] = round(
                    abs(float(entry) - float(stop_loss)) / float(entry) * 100, 4
                )
            # Торговая сессия по UTC (контекст времени входа)
            _h = datetime.now(timezone.utc).hour
            features["session"] = (
                "ASIA"   if  0 <= _h <  8 else
                "LONDON" if  8 <= _h < 13 else
                "NY"     if 13 <= _h < 22 else "OFF"
            )
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
            # DEV-138: wt_snap для MTFWTSpecialist (7 TF × {wt1,wt2,zone,wt_cross,trend})
            wt_snap = metadata.get("wt_snap") if metadata else None
            if wt_snap and isinstance(wt_snap, dict):
                features["wt_snap"] = wt_snap
            # DEV-139: smc_snap для MTFSMCSpecialist (4 TF × 9 признаков)
            smc_snap = metadata.get("smc_snap") if metadata else None
            if smc_snap and isinstance(smc_snap, dict):
                features["smc_snap"] = smc_snap
            # DEV-137: reversal_mode shadow
            rev_mode = metadata.get("reversal_mode") if metadata else None
            if rev_mode:
                features["reversal_mode"] = rev_mode

            # ARCH-90: Narrative SMC-факторы + 4 плоских поля из state.smc_snap
            _narr_meta = metadata.get("narrative") if metadata else None
            if _narr_meta and isinstance(_narr_meta, dict):
                _smc_factors = _narr_meta.get("smc_factors") or []
                if _smc_factors:
                    features.setdefault("narrative", {})["smc_factors"] = list(_smc_factors)
                _smc_flat = _narr_meta.get("smc_flat") or {}
                if _smc_flat:
                    features["nearest_ob_strength"] = _smc_flat.get("nearest_ob_strength")
                    features["price_in_ote"] = int(bool(_smc_flat.get("price_in_ote", False)))
                    features["current_retracement"] = _smc_flat.get("current_retracement")
                    features["last_bos_direction"] = _smc_flat.get("last_bos_direction")
                    # DEV-209 (12.05): направление OTE impulse + TF — нужно для DEV-208 аудита
                    if _smc_flat.get("ote_direction") is not None:
                        features["ote_direction"] = _smc_flat.get("ote_direction")
                    if _smc_flat.get("ote_tf") is not None:
                        features["ote_tf"] = _smc_flat.get("ote_tf")

            # DEV-178: data_era — маркер эры данных для фильтрации в ML
            # post_fix (>= 15.04.2026) = чистые данные (DEV-157 + DEV-174 + DEV-175 применены)
            # Micro-SL guard: если SL слишком близко — артефакт, помечаем отдельно
            try:
                from datetime import date as _date
                _now_date = _date.today()
                _ep = float(entry) if entry else 0
                _sl = float(stop_loss) if stop_loss else 0
                _sl_dist_pct = abs(_ep - _sl) / _ep * 100 if _ep > 0 and _sl > 0 else 99.0
                from core.infra.config_loader import config as _cfg_era
                _min_sl = float(_cfg_era.get("trading.min_sl_dist_pct", 0.1))
                if _sl_dist_pct < _min_sl:
                    features["data_era"] = "micro_sl_artifact"
                    features["is_micro_sl"] = True
                elif _now_date >= _date(2026, 4, 15):
                    features["data_era"] = "post_fix"
                elif _now_date >= _date(2026, 3, 15):
                    features["data_era"] = "post_157"
                else:
                    features["data_era"] = "pre_157"
            except Exception:
                pass

            # ARCH-95 H1: entry timing shadow (лаг детекции → регистрация)
            # detector_ts = время создания рекомендации (когда TradingIntelligence увидел сигнал)
            # register_ts = время записи в БД (сейчас)
            # entry_lag_seconds = задержка — ключевая метрика гипотезы H1
            # detector_price = close бара при детекции; entry_price_lag_pct = slippage
            try:
                _det_ts = getattr(recommendation, "timestamp", None)
                if _det_ts is not None:
                    if getattr(_det_ts, "tzinfo", None) is None:
                        _det_ts = _det_ts.replace(tzinfo=timezone.utc)
                    _reg_ts = datetime.now(timezone.utc)
                    features["detector_ts"] = _det_ts.isoformat()
                    features["register_ts"] = _reg_ts.isoformat()
                    features["entry_lag_seconds"] = round(
                        (_reg_ts - _det_ts).total_seconds(), 1
                    )
                _det_price = (metadata or {}).get("detector_price") if metadata else None
                if _det_price and entry and float(entry) > 0:
                    features["detector_price"] = float(_det_price)
                    features["entry_price_lag_pct"] = round(
                        (float(entry) - float(_det_price)) / float(_det_price) * 100, 4
                    )
            except Exception:
                pass

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
            _atr_entry_raw = _get_recommendation_value(recommendation, "atr_entry_tf")
            atr_entry = _atr_entry_raw if isinstance(_atr_entry_raw, (int, float)) else None
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
                        from core.infra.config_loader import config as _cfg64a
                        _sl_tp_64a = (_cfg64a.get("trading") or {}).get("sl_management") or {}
                        _max_rr_64a = float(
                            _sl_tp_64a.get("max_rr_range" if regime == "RANGE" else "max_rr", 3.0)
                        )
                    except Exception:
                        _max_rr_64a = 3.0
                    # ARCH-128: OTE исключён из RR-cap. runner = HTF-target (далёкий),
                    # частичный TP1=1R фиксирует 50%, остаток бежит до цели + TSL. Cap до 3R
                    # при компактном SL (0.2-0.3%) давал мизерный TP в % → срезал прибыль cont.
                    _is_ote_64a = bool(extra_features and
                                       extra_features.get("signal_type_override") == "ote_nested")
                    if rr > _max_rr_64a and not _is_ote_64a:
                        take_profit = float(entry) + sign * sl_dist * _max_rr_64a
                        tp_dist = abs(float(take_profit) - float(entry))
                        rr = _max_rr_64a
                        logger.info(
                            "[DEV-64A] %s R:R cap → %.1fx (regime=%s)", symbol, _max_rr_64a, regime or "?"
                        )
                    # TRIPLE_TP_TSL убран 30.03.2026 — только SINGLE / DUAL_TP / DUAL_TSL
                    if rr >= 2.0:
                        # Проверяем dual_tp.enabled из конфига
                        _dual_tp_enabled = True
                        try:
                            from core.infra.config_loader import config as _cfg_dtp
                            _dual_tp_enabled = bool(
                                (_cfg_dtp.get("trading.dual_tp") or {}).get("enabled", True)
                            )
                        except Exception:
                            pass
                        if _dual_tp_enabled:
                            # Базовый тип DUAL_TP; apply_regime_to_strategy() поднимет до DUAL_TSL для TREND
                            strategy_type = "DUAL_TP"
                            # TP1 = первый пивот = take_profit
                            tp1_price = float(take_profit)
                            tp2_price = None

                    # TRADER: DUAL_TP в RANGE убыточен (avg_R=-0.942) → деактивируем
                    if strategy_type == "DUAL_TP" and regime == "RANGE":
                        strategy_type = "SINGLE"
                        tp1_price = None
                        tp2_price = None
                        logger.info("[DUAL_TP] %s RANGE → downgrade DUAL_TP к SINGLE", symbol)

            # Адаптируем strategy_type и TP1 на основе режима рынка (ARCH-04)
            if regime and stop_loss is not None and take_profit is not None and entry is not None:
                try:
                    from core.infra.config_loader import config as _cfg_rs  # DEV-70: cfg для risk_management.regime_strategy
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
                    # Пересчитываем уровни после apply_regime
                    if strategy_type in ("DUAL_TP", "DUAL_TSL"):
                        # TP1 = первый пивот (take_profit)
                        tp1_price = float(take_profit)
                        # TP2: для DUAL_TP = следующий пивот (заполняется в async)
                        #      для DUAL_TSL = None (закрывается по TSL)
                        tp2_price = None
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

            # ═══ ARCH-128: OTE живёт по TSL (без частичного TP1) ═══
            # DEV-124: SINGLE +1866R vs DUAL_TP/TSL -88.5R. Компактный SL → 1R=свеча,
            # частичный фикс убивает идею. Вся позиция под TSL: активируется после +1R
            # (BE@0.5R защищает раньше), ведёт до конца. take_profit=runner (далёкий потолок).
            if extra_features and extra_features.get("signal_type_override") == "ote_nested":
                strategy_type = "SINGLE"
                tp1_price = None
                tp2_price = None
                tp3_price = None

            # ═══ ARCH-122 Phase 2 SHADOW: ExitManager — магнит как ТЕНЬ (не закрывает) ═══
            # Сюда сходятся ВСЕ источники (atr_change/wl_breach/pivot/intelligence).
            # ИЗМЕРИТЕЛЬНАЯ ФАЗА: магнит НЕ перетирает take_profit (живое закрытие = TP
            # канала, проверенный pivot/atr). Магнит пишется в shadow-поля. Постфактум
            # по max_R_possible (peak excursion): дошла ли цена до магнита/pivot, и
            # развернулась ли У МАГНИТА не дойдя до pivot → доказываем порог по данным.
            _magnet_tp_price = None
            _magnet_tp_rr = None
            _magnet_tp_src = None
            try:
                from core.infra.config_loader import config as _cfg_em
                _em_en = bool((_cfg_em.get("sl_tp_engine") or {}).get("tp_selector_enabled", False))
                _cur_src = str(tp_source or "")
                if (_em_en and "@" not in _cur_src
                        and entry and stop_loss is not None and take_profit is not None):
                    from core.trading.exit_manager import resolve_magnet_tp
                    _mag = resolve_magnet_tp(
                        symbol, float(entry), float(stop_loss), dir_str,
                        getattr(self, "_pair_context_bus", None), self._pivot_calc, _cfg_em,
                    )
                    if _mag is not None:
                        _mtp, _mlbl = _mag
                        _sld = max(abs(float(entry) - float(stop_loss)), 1e-9)
                        _magnet_tp_price = float(_mtp)
                        _magnet_tp_rr = round(abs(_mtp - float(entry)) / _sld, 3)
                        _magnet_tp_src = _mlbl
                        # RR прежнего TP канала — для сравнения в логе (магнит дальше/ближе?)
                        _cur_tp_rr = abs(float(take_profit) - float(entry)) / _sld
                        _rel = "дальше" if _magnet_tp_rr > _cur_tp_rr else "ближе"
                        logger.info(
                            "[ExitManager P2 shadow] %s магнит=%.6g RR=%.2f (%s pivot RR=%.2f) src=%s канал=%s — TP канала сохранён",
                            symbol, _mtp, _magnet_tp_rr, _rel, _cur_tp_rr, _mlbl, signal_type,
                        )
            except Exception as _em_e:
                logger.debug("[ExitManager P2 shadow] %s resolve failed: %s", symbol, _em_e)

            # ARCH-122 Phase 1a: TP2 из TPSelector магнитов (вместо pivot-иерархии async).
            # Когда tp_selector_enabled и рекомендация несёт tp2_price (gravity-кластер
            # HTF 1-3R) — используем его. Не None → async-заполнение pivot пропускается
            # (trade_simulator:1172). Только DUAL_TP (DUAL_TSL остаток идёт по TSL).
            if strategy_type == "DUAL_TP" and tp2_price is None:
                try:
                    from core.infra.config_loader import config as _cfg_tp2
                    _tps_en = bool((_cfg_tp2.get("sl_tp_engine") or {}).get("tp_selector_enabled", False))
                    if _tps_en:
                        _rec_tp2 = _get_recommendation_value(recommendation, "tp2_price")
                        if isinstance(_rec_tp2, (int, float)) and _rec_tp2 > 0:
                            tp2_price = float(_rec_tp2)
                            _rec_tp2_src = _get_recommendation_value(recommendation, "tp2_source")
                            logger.info("[ARCH-122] %s TP2 из магнитов=%.6g src=%s (не pivot)",
                                        symbol, tp2_price, _rec_tp2_src or "?")
                except Exception as _tp2e:
                    logger.debug("[ARCH-122] tp2 from magnets failed: %s", _tp2e)

            # TradeRouter Этап 1.Б: source_router из extra_features
            _source_router = (extra_features or {}).get("source_router")

            with self._db_connect() as conn:
                cursor = conn.cursor()
                # ARCH-DB-V2 Ф1: разметка сделки — account_id (routing по symbol).
                # execution_mode = ФАКТ исполнения (юзер 12.06): на момент register order_id ещё
                # нет → 'SIM' (симуляция). UPDATE на VST/LIVE при записи exchange_order_id
                # (trade_router/exec_ws). Shadow-сделки (order_id NULL) остаются SIM.
                _acc_row = conn.execute(
                    "SELECT account_id FROM account_routing WHERE symbol=? LIMIT 1", (symbol,)
                ).fetchone()
                _account_id = _acc_row[0] if _acc_row else 1
                _exec_mode = "SIM"
                cursor.execute(
                    """
                    INSERT INTO simulated_trades
                    (symbol, timeframe, signal_type, direction, entry_price, stop_loss, take_profit,
                     tp1_price, tp2_price, tp3_price, strategy_type,
                     strength, confidence, regime, status, features_json, created_at,
                     sl_source, tp_source, strategy_name, tsl_tf, decision_trace_json,
                     original_sl, source_router,
                     magnet_tp_price, magnet_tp_rr, magnet_tp_src, regime_v2,
                     account_id, execution_mode, exchange, total_fee)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        float(stop_loss) if stop_loss is not None else None,  # original_sl — не меняется после регистрации
                        _source_router,
                        _magnet_tp_price,
                        _magnet_tp_rr,
                        _magnet_tp_src,
                        regime_v2,
                        _account_id,    # ARCH-DB-V2 Ф1
                        _exec_mode,     # SIM/VST/LIVE (режим бота на момент создания)
                        "bingx",        # Ф2 нормализует в exchange_id
                        0.0,            # total_fee: заполняется при close_trade (qty×entry×0.1%)
                    ),
                )
                trade_id = cursor.lastrowid
                conn.commit()
            logger.info(f"TradeSimulator: зарегистрирована сделка id={trade_id} {symbol} {_direction_str(direction)}")
            return trade_id
        except Exception as e:
            logger.exception(f"TradeSimulator: ошибка регистрации сделки — {e}")
            if _reason_out is not None: _reason_out.append(f"exception:{type(e).__name__}:{str(e)[:80]}")
            return None

    async def register_trade_async(
        self,
        recommendation: Any,
        data_collector: Any = None,
        extra_features: Optional[dict] = None,
        _reason_out: Optional[list] = None,
    ) -> Optional[int]:
        """
        Async-обёртка над register_trade: получает OHLCV, определяет режим рынка,
        затем сохраняет сделку. Если data_collector недоступен — пишет regime=None.
        extra_features — доп. признаки (напр. distance_to_pivot_pct) для features_json.
        """
        # DEV-170: Time-of-day gate — блокируем входы вне торговых сессий
        # Данные: 09:00–18:00 UTC = avgR+, 23:00–06:00 UTC = avgR-0.3 (худшие)
        # TRADER (14.04): wt_signal override 04:00–18:00 (азиатская ночь прибыльна)
        try:
            from core.infra.config_loader import config as _cfg_170
            if _cfg_170:
                _tg = (_cfg_170.get("signal_quality") or {}).get("time_gate") or {}
                if _tg.get("enabled", False):
                    _hour_utc = datetime.now(timezone.utc).hour
                    _sig_170  = str(_get_recommendation_value(recommendation, "signal_type") or "")
                    _overrides = _tg.get("overrides") or {}
                    _tg_sig   = _overrides.get(_sig_170) or {}
                    _start_h  = int(_tg_sig.get("start_hour_utc", _tg.get("start_hour_utc", 9)))
                    _end_h    = int(_tg_sig.get("end_hour_utc",   _tg.get("end_hour_utc", 18)))
                    _in_window = _start_h <= _hour_utc < _end_h
                    if not _in_window:
                        _sym_170 = _get_recommendation_value(recommendation, "symbol") or ""
                        logger.info("[DEV-170] %s БЛОК time_gate(%s): hour=%d вне [%d, %d) UTC",
                                    _sym_170, _sig_170 or "default", _hour_utc, _start_h, _end_h)
                        if _reason_out is not None: _reason_out.append("DEV-170:time_gate")
                        return None
        except Exception as _e170:
            logger.debug("[DEV-170] time_gate error: %s", _e170)

        # ARCH-42: Market Stress Gate — блок входов при массовых SL (shadow mode)
        try:
            from core.infra.config_loader import config as _cfg_msg
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
                        if _reason_out is not None: _reason_out.append("ARCH-42:market_stress")
                        return None
                    else:
                        logger.info("[ARCH-42] shadow %s: %d SL за %d мин (gate disabled)",
                                    _sym_msg, len(_recent_sl), _window_min)
        except Exception as _e_msg:
            logger.debug("[ARCH-42] stress gate error: %s", _e_msg)

        # DEV-38: Correlation Guard — блок если по коррелированному активу уже открыта сделка
        try:
            from core.infra.config_loader import config as _cfg_cg38
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
                            if _reason_out is not None: _reason_out.append("DEV-38:correlation_guard")
                            return None
        except Exception as _e:
            logger.debug("[DEV-38] Correlation Guard error: %s", _e)

        regime: Optional[str] = None
        _regime_v2: Optional[str] = None   # ARCH-124 shadow: HTF-доминантная метка
        if data_collector is not None:
            symbol = _get_recommendation_value(recommendation, "symbol") or ""
            if symbol:
                try:
                    from core.indicators.market_regime import MarketRegimeClassifier
                    ohlcv = await data_collector.get_ohlcv(symbol, DEFAULT_TIMEFRAME, 50)
                    if ohlcv is not None and not ohlcv.empty:
                        regime = MarketRegimeClassifier().classify_from_ohlcv(ohlcv)
                        logger.debug("MarketRegime для %s: %s", symbol, regime)
                        # DEV-90 / ARCH-59: shadow logging classify_v2 (сравниваем с текущим)
                        try:
                            from core.infra.config_loader import config as _cfg90
                            _use_v2 = _cfg90.get("market_regime.use_v2", False) if _cfg90 else False
                            _clf90 = MarketRegimeClassifier()
                            _df_1h90 = await data_collector.get_ohlcv(symbol, "1h", 50)
                            # ARCH-124: HTF-доминантному v2 нужен 4h (60 баров > atr_period=43)
                            _df_4h90 = await data_collector.get_ohlcv(symbol, "4h", 60)
                            _v2 = _clf90.classify_v2(ohlcv, _df_1h90, _df_4h90)
                            _regime_v2 = _v2
                            if _use_v2:
                                regime = _v2
                                logger.debug("[regime_v2] %s: v2=%s (production)", symbol, _v2)
                            else:
                                logger.debug("[regime_v2][SHADOW] %s: old=%s new=%s",
                                             symbol, regime, _v2)
                        except Exception as _e90:
                            logger.debug("[regime_v2] %s: shadow error — %s", symbol, _e90)
                except Exception as e:
                    logger.debug("MarketRegime: не удалось определить для %s — %s", symbol, e)

        # DEV-169: atr_trend_1h_bias — UP/DOWN/FLAT на основе ATR Trend 1h
        # Записывается в features_json для накопления данных. Логики блокировки нет.
        _atr_1h_bias: Optional[str] = None
        if data_collector is not None and symbol:
            try:
                from core.indicators.indicators import calculate_trend
                _df_1h_bias = await data_collector.get_ohlcv(symbol, "1h", 55)
                if _df_1h_bias is not None and not _df_1h_bias.empty and len(_df_1h_bias) >= 44:
                    _df_1h_bias = calculate_trend(_df_1h_bias)
                    _last_trend = _df_1h_bias["trend"].iloc[-1]
                    _atr_1h_bias = "UP" if _last_trend == 1 else "DOWN"
                    logger.debug("[DEV-169] %s atr_trend_1h_bias=%s", symbol, _atr_1h_bias)
            except Exception as _e169:
                logger.debug("[DEV-169] atr_trend_1h_bias error %s: %s", symbol, _e169)

        if _atr_1h_bias:
            if extra_features is None:
                extra_features = {}
            extra_features["atr_trend_1h_bias"] = _atr_1h_bias

        # ARCH-78 / DEV-172: Entry Priority Matrix — shadow mode
        # Пишет entry_priority (1/2/3/None) в features_json. Не блокирует входы.
        try:
            from core.intelligence.entry_matrix import evaluate_entry_priority as _eval_ep
            _ep_dir = _direction_str(_get_recommendation_value(recommendation, "direction"))
            _ep_wt_snap = (recommendation.metadata or {}).get("wt_snap") if hasattr(recommendation, "metadata") else None
            _ep_result = _eval_ep(
                direction=_ep_dir or "",
                wt_snap=_ep_wt_snap,
                atr_trend_1h_bias=_atr_1h_bias,
            )
            _ep_priority = _ep_result.get("priority")
            if extra_features is None:
                extra_features = {}
            extra_features["entry_priority"] = _ep_priority
            extra_features["entry_priority_reason"] = _ep_result.get("reason")
            logger.debug("[DEV-172] %s entry_priority=%s reason=%s bias=%s zone=%s trigger=%s",
                         symbol, _ep_priority,
                         _ep_result.get("reason"), _ep_result.get("bias_ok"),
                         _ep_result.get("zone_ok"), _ep_result.get("trigger"))
        except Exception as _e172:
            logger.debug("[DEV-172] entry_matrix error %s: %s", symbol, _e172)

        # DEV-44 (ARCH-39 fix): Safety gate — второй рубеж, использует свежевычисленный regime
        # Теперь работает для ВСЕХ code-paths (analyze_symbol + WL breach + будущие)
        if regime:
            try:
                from core.infra.config_loader import config as _cfg_44
                if _cfg_44:
                    _sym_44 = _get_recommendation_value(recommendation, "symbol") or ""
                    _dir_44 = _direction_str(_get_recommendation_value(recommendation, "direction"))
                    _sig_type_44 = str(_get_recommendation_value(recommendation, "signal_type") or "")
                    # 27.05.2026: fallback на signal_type_override из extra_features.
                    # TradingRecommendation не имеет поля signal_type → DEV-222 exception
                    # blocked_regimes_exceptions=[arch104] не срабатывал и arch104 валился
                    # в HIGH_VOL. То же для будущих источников через override (как в DEV-155).
                    if extra_features and extra_features.get("signal_type_override"):
                        _sig_type_44 = str(extra_features["signal_type_override"])
                    # Guard 1: blocked_regimes (DEV-33 fallback)
                    _br_exceptions = _cfg_44.get("trading.blocked_regimes_exceptions") or []
                    if regime in (_cfg_44.get("trading.blocked_regimes") or []) and _sig_type_44 not in _br_exceptions:
                        logger.info("[DEV-44] %s БЛОК blocked_regime: %s", _sym_44, regime)
                        if _reason_out is not None: _reason_out.append(f"DEV-44:blocked_regime:{regime}")
                        return None
                    # Guard 2: regime_direction_block (DEV-32 fallback)
                    _rdb = _cfg_44.get("trading.regime_direction_block") or {}
                    if _rdb.get("enabled") and _rdb.get(regime) == _dir_44:
                        logger.info("[DEV-44] %s БЛОК regime_direction: %s/%s", _sym_44, regime, _dir_44)
                        if _reason_out is not None: _reason_out.append(f"DEV-44:regime_direction:{regime}/{_dir_44}")
                        return None
                    # Guard 3: signal_regime_block (DEV-64B) — блок мёртвых signal_type × regime комбинаций
                    _srb = _cfg_44.get("signal_quality.signal_regime_block") or {}
                    if _srb:
                        _srb_sig = _srb.get(_sig_type_44) or {}
                        # Guard 3A: blocked_regimes (legacy — без направления)
                        if regime in (_srb_sig.get("blocked_regimes") or []):
                            logger.info(
                                "[DEV-64B] %s БЛОК signal_regime_block: %s/%s", _sym_44, _sig_type_44, regime
                            )
                            if _reason_out is not None: _reason_out.append(f"DEV-64B:signal_regime_block:{_sig_type_44}/{regime}")
                            return None
                        # Guard 3B: blocked_combos (DEV-133) — direction × regime, хирургические блоки
                        for _combo in (_srb_sig.get("blocked_combos") or []):
                            if regime == _combo.get("regime") and _dir_44 == _combo.get("direction"):
                                logger.info(
                                    "[DEV-133] %s БЛОК combo: %s/%s/%s", _sym_44, _sig_type_44, _dir_44, regime
                                )
                                if _reason_out is not None: _reason_out.append(f"DEV-133:blocked_combo:{_sig_type_44}/{_dir_44}/{regime}")
                                return None
            except Exception as _e44:
                logger.debug("[DEV-44] Safety gate error: %s", _e44)

        # DEV-155: Guard — min_strength по режиму/направлению (HIGH_VOL=85, LONG_RANGE=75)
        # TradeRouter Этап 1.Б (15.05.2026): для signal_type='atr_change' используем
        # min_strength_atr_change (=15), т.к. base avgR положительный по бэктесту A1.
        # Cleanup Этап 1.Е перенесёт всю эту логику в core/trading/gates/.
        if regime:
            try:
                from core.infra.config_loader import config as _cfg_155
                if _cfg_155:
                    _str155 = int(_get_recommendation_value(recommendation, "overall_strength") or
                                  getattr(recommendation, "overall_strength", 0) or 0)
                    _sym155 = _get_recommendation_value(recommendation, "symbol") or symbol
                    _dir155 = _direction_str(_get_recommendation_value(recommendation, "direction"))
                    # Per-signal_type override для atr_change (с signal_type_override extra_features)
                    _sig_type_155 = str(_get_recommendation_value(recommendation, "signal_type") or "")
                    if extra_features and extra_features.get("signal_type_override"):
                        _sig_type_155 = str(extra_features["signal_type_override"])
                    # direction+regime ключ: "LONG_HIGH_VOL" / "LONG_RANGE" / "SHORT_HIGH_VOL" / etc.
                    _dir_regime_key = f"{_dir155}_{regime}"
                    _by_dir_regime = (_cfg_155.get("signal_quality.min_strength_by_direction_regime") or {})
                    _by_regime = (_cfg_155.get("signal_quality.min_strength_by_regime") or {})
                    if _sig_type_155 == "atr_change":
                        _base_min = int(_cfg_155.get("signal_quality.min_strength_atr_change", 15))
                    else:
                        _base_min = int(_cfg_155.get("signal_quality.min_strength_register", 50))
                    _eff_min = _by_dir_regime.get(_dir_regime_key,
                               _by_regime.get(regime, _base_min))
                    if _str155 < _eff_min:
                        logger.info(
                            "[DEV-155] %s БЛОК %s/%s/%s strength=%d < %d",
                            _sym155, _dir155, regime, _sig_type_155 or "?", _str155, _eff_min,
                        )
                        if _reason_out is not None: _reason_out.append(f"DEV-155:min_strength:{regime}/{_dir155}:{_str155}<{_eff_min}")
                        return None
            except Exception as _e155:
                logger.debug("[DEV-155] gate error: %s", _e155)

        # DEV-98: Guard 4 — pivot_reversal strength≥80 → skip
        # Находка 2 (ARCH 29.03.2026): WR=4.5% avgR=−0.735R при strength≥80; чем выше strength → хуже
        # Порог: signal_quality.pivot_reversal_max_strength (default 79 = блок ≥80)
        try:
            from core.infra.config_loader import config as _cfg_98
            if _cfg_98:
                _pms = int(_cfg_98.get("signal_quality.pivot_reversal_max_strength", 100))
                _sig98 = str(_get_recommendation_value(recommendation, "signal_type") or "")
                _str98 = int(_get_recommendation_value(recommendation, "overall_strength") or
                             getattr(recommendation, "overall_strength", 0) or 0)
                if _sig98 == "pivot_reversal" and _pms < 100 and _str98 >= _pms:
                    _sym98 = _get_recommendation_value(recommendation, "symbol") or symbol
                    logger.info("[DEV-98] %s БЛОК pivot_reversal strength=%d >= %d", _sym98, _str98, _pms)
                    if _reason_out is not None: _reason_out.append(f"DEV-98:pivot_reversal_strength:{_str98}>={_pms}")
                    return None
        except Exception as _e98:
            logger.debug("[DEV-98] gate error: %s", _e98)

        # DEV-52: L3 Портфельный лимит (условие 6) — shadow mode
        try:
            from core.infra.config_loader import config as _cfg_52
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
                        if _reason_out is not None: _reason_out.append(f"DEV-52:portfolio_limit:{_blocked_52}")
                        return None
                    else:
                        logger.info("[DEV-52] shadow %s: портфельный лимит %s (gate disabled)",
                                    _sym_52, _blocked_52)

                # EXEC-SIM-SPLIT кирпич №1 (17.06): риск-экспозиция % депозита PER-ACCOUNT (VST).
                # Мерка = Σ(qty×|entry−sl|) открытых VST ЭТОГО аккаунта / equity_account — НЕ количество
                # (узкий стоп взрывает notional при том же risk%) и НЕ суммарно (acc размывает acc:
                # shadow 17.06 показал acc1 2.2% vs acc2 8.0% при суммарных 5.3%).
                # База = реальный equity per-account из balance_snapshots (единый источник истины,
                # ARCH-DB-V2; config.deposit_usdt — лишь SIM-номинал, не отражает реальность/мульти-акк).
                # Вклад новой = risk_pct% (qty ещё не посчитан здесь; risk-based sizing → +risk_pct%).
                # Старт SHADOW (risk_gate_shadow=true): лог без блокировки → распределение → потолок по
                # данным. Circuit Breaker by design: только новые входы, открытые ведутся по TSL/SL.
                # Общий lookup для обоих кирпичей: account_id новой сделки (routing по symbol, как
                # register_trade ниже) + последний balance_snapshots (equity + available) per-account.
                # balance_snapshots = единый источник истины (ARCH-DB-V2); та же БД (self._db_connect)
                # → тестируемо на копии.
                _max_risk_pct = _l3.get("max_total_risk_pct")
                _min_avail    = _l3.get("min_available_usdt")
                if _max_risk_pct or _min_avail:
                    _trd_52 = _cfg_52.get("trading", {}) or {}
                    _risk_pct_52 = float(_trd_52.get("risk_pct", 1.0))
                    _acc_52 = 1
                    _snap52 = None
                    try:
                        with self._db_connect() as _cacc52:
                            _rr52 = _cacc52.execute(
                                "SELECT account_id FROM account_routing WHERE symbol=? LIMIT 1",
                                (_sym_52,),
                            ).fetchone()
                            if _rr52 and _rr52[0]:
                                _acc_52 = int(_rr52[0])
                            _snap52 = _cacc52.execute(
                                "SELECT equity, available FROM balance_snapshots WHERE account_id=? "
                                "ORDER BY timestamp DESC LIMIT 1", (_acc_52,),
                            ).fetchone()
                    except Exception as _eacc52:
                        logger.debug("[DEV-52] acc/balance lookup err: %s", _eacc52)
                    _equity_52 = float(_snap52[0]) if (_snap52 and _snap52[0]) else 0.0
                    if _equity_52 <= 0:  # нет снапшота → config-номинал (fallback)
                        _equity_52 = float(_trd_52.get("deposit_usdt", 1000.0)) or 1000.0
                    _avail_52 = float(_snap52[1]) if (_snap52 and _snap52[1] is not None) else None

                    # ── Кирпич №1: риск-экспозиция по стопам (% equity per-account) ──
                    # Мерка Σ(qty×|entry−sl|) VST этого acc / equity_account — НЕ количество (узкий
                    # стоп взрывает notional) и НЕ суммарно (acc размывает acc). Вклад новой = risk_pct%
                    # (qty ещё не посчитан здесь). Старт SHADOW → распределение → потолок по данным.
                    if _max_risk_pct:
                        _cur_risk_usdt = 0.0
                        for _t52 in _open_52:
                            if _t52.get("execution_mode") != "VST":
                                continue  # только реальный капитал; sim депозит не трогает
                            if int(_t52.get("account_id") or 1) != _acc_52:
                                continue  # риск считаем В РАМКАХ аккаунта новой сделки
                            _q52 = _t52.get("qty"); _e52e = _t52.get("entry_price"); _sl52 = _t52.get("stop_loss")
                            if _q52 and _e52e and _sl52:
                                _cur_risk_usdt += float(_q52) * abs(float(_e52e) - float(_sl52))
                        _cur_risk_pct = _cur_risk_usdt / _equity_52 * 100.0
                        _proj_risk_pct = _cur_risk_pct + _risk_pct_52
                        _risk_shadow = _l3.get("risk_gate_shadow", True)
                        if _proj_risk_pct > float(_max_risk_pct):
                            _rb52 = (f"acc{_acc_52} {_cur_risk_pct:.1f}%+{_risk_pct_52:.1f}%="
                                     f"{_proj_risk_pct:.1f}% > {_max_risk_pct}% (eq={_equity_52:.0f})")
                            if _l3.get("enabled") and not _risk_shadow:
                                logger.info("[DEV-52][RISK] %s БЛОК риск-экспозиция %s", _sym_52, _rb52)
                                if _reason_out is not None:
                                    _reason_out.append(f"DEV-52:risk_exposure:{_rb52}")
                                return None
                            else:
                                logger.info("[DEV-52][RISK] shadow %s would_block %s", _sym_52, _rb52)
                        else:
                            logger.info("[DEV-52][RISK] %s acc%d exposure=%.1f%% (+new %.1f%% → %.1f%%, cap %s%%, eq=%.0f)",
                                        _sym_52, _acc_52, _cur_risk_pct, _risk_pct_52, _proj_risk_pct, _max_risk_pct, _equity_52)

                    # ── Кирпич №2: margin pre-check (доступная маржа per-account) ──
                    # Корень фантомов (17.06): register создаёт SIM-запись ДО placement; если open_bracket
                    # падает по марже (available исчерпан, used 87%) → запись остаётся SIM = фантом. Ловим
                    # ДО register: available_per_account < порог → не плодить + защита от наращивания при
                    # занятой марже (риск ликвидации). Shadow-first: лог available → порог по данным.
                    if _min_avail and _avail_52 is not None:
                        _margin_shadow = _l3.get("margin_gate_shadow", True)
                        if _avail_52 < float(_min_avail):
                            _mb52 = f"acc{_acc_52} avail={_avail_52:.1f} < {_min_avail} USDT (eq={_equity_52:.0f})"
                            if _l3.get("enabled") and not _margin_shadow:
                                logger.info("[DEV-52][MARGIN] %s БЛОК низкая маржа %s", _sym_52, _mb52)
                                if _reason_out is not None:
                                    _reason_out.append(f"DEV-52:low_margin:{_mb52}")
                                return None
                            else:
                                logger.info("[DEV-52][MARGIN] shadow %s would_block %s", _sym_52, _mb52)
                        else:
                            logger.info("[DEV-52][MARGIN] %s acc%d available=%.1f USDT (min %s, eq=%.0f)",
                                        _sym_52, _acc_52, _avail_52, _min_avail, _equity_52)
        except Exception as _e52:
            logger.debug("[DEV-52] portfolio gate error: %s", _e52)

        # DEV-110 / ARCH-66: RANGE BOUNCE — переопределяем SL/TP от пивотов
        # Активируется только: RANGE + confluence/watch_list_breach + 15m + entry у края (≤2%)
        try:
            from core.infra.config_loader import config as _cfg_rb
            from core.trading.exit_manager import magnet_tp_locked
            _rb_cfg = (_cfg_rb.get("trading", {}) or {}).get("range_bounce", {})
            # ARCH-122 ч.1b (ExitManager): магнит важнее range_bounce-pivot.
            # ARCH-124: RANGE 78% мислейбл тренда → range_bounce на неверной метке.
            if (_rb_cfg.get("enabled", False) and regime == "RANGE"
                    and not magnet_tp_locked(recommendation, _cfg_rb)):
                _rb_sig = str(_get_recommendation_value(recommendation, "signal_type") or "")
                _rb_tf  = str(_get_recommendation_value(recommendation, "timeframe") or "")
                if _rb_sig in ("confluence", "watch_list_breach", "pivot_reversal") and _rb_tf == "15m":
                    _rb_sym = str(_get_recommendation_value(recommendation, "symbol") or "")
                    _rb_dir = _direction_str(_get_recommendation_value(recommendation, "direction"))
                    _rb_entry = float(_get_recommendation_value(recommendation, "entry_price") or 0)
                    if _rb_entry > 0:
                        # Инициализируем pivot_calc и загружаем пивоты для символа
                        if self._pivot_calc is None:
                            from core.pivots.pivot_calculator_fixed import PivotCalculatorFixed as _PCF_rb
                            self._pivot_calc = _PCF_rb(db_path=self.db_path)
                        if data_collector is not None:
                            await self._pivot_calc.get_daily_pivots(_rb_sym, data_collector)
                            await self._pivot_calc.get_weekly_pivots(_rb_sym, data_collector)
                        from core.smc.sl_tp_calculator import calc_range_bounce_sl_tp
                        _rb_sl, _rb_tp, _rb_r, _rb_reject = calc_range_bounce_sl_tp(
                            direction=_rb_dir,
                            entry=_rb_entry,
                            pivot_cache=self._pivot_calc.pivot_cache,
                            symbol=_rb_sym,
                            sl_buffer_pct=float(_rb_cfg.get("sl_buffer_pct", 0.003)),
                            min_tp_r=float(_rb_cfg.get("min_tp_r", 3.5)),
                            max_sl_dist_pct=float(_rb_cfg.get("max_sl_dist_pct", 0.02)),
                        )
                        if not _rb_reject:
                            # Применяем RANGE BOUNCE SL/TP
                            try:
                                recommendation.stop_loss   = _rb_sl
                                recommendation.take_profit = _rb_tp
                                recommendation.sl_source   = "range_bounce_pivot"
                                recommendation.tp_source   = "range_bounce_pivot"
                            except AttributeError:
                                pass
                            logger.info(
                                "[DEV-110] %s RANGE BOUNCE %s: sl=%.5f tp=%.5f R=%.1f",
                                _rb_sym, _rb_dir, _rb_sl, _rb_tp, _rb_r,
                            )
                        else:
                            logger.info("[DEV-110] %s пропущен: %s", _rb_sym, _rb_reject)
        except Exception as _e_rb:
            logger.warning("[DEV-110] RANGE BOUNCE error: %s", _e_rb)

        # ARCH-118: единый снимок признаков (вариант B — live=бэктест ОДНИМ калькулятором
        # combinator_v2.compute_flags). На вход НЕ влияет. Здесь (после гейтов) — только для
        # реально регистрируемых сделок, без лишних fetch на заблокированных.
        #   write_table=true  → снимок в таблицу trade_features (Шаг 5b, prod).
        #   shadow_enabled=true → дубль в features_json.arch118_snapshot (legacy; пропускаем
        #                         если write_table, чтобы не дублировать данные).
        _a118_snap = None
        _a118_write_table = False
        try:
            from core.infra.config_loader import config as _cfg_a118
            _a118_write_table = bool(_cfg_a118 and _cfg_a118.get("arch118.write_table", False))
            _a118_shadow = bool(_cfg_a118 and _cfg_a118.get("arch118.shadow_enabled", False))
            if (_a118_write_table or _a118_shadow) and data_collector is not None and symbol:
                from core.intelligence.feature_snapshot import build_df_by_tf, snapshot_features
                _df_by_tf = await build_df_by_tf(data_collector, symbol)
                if _df_by_tf:
                    _a118_tf = str(_get_recommendation_value(recommendation, "timeframe")
                                   or DEFAULT_TIMEFRAME)
                    _a118_sig = {
                        "signal_type": str(_get_recommendation_value(recommendation, "signal_type") or ""),
                    }
                    _a118_snap = snapshot_features(_df_by_tf, entry_tf=_a118_tf, signal=_a118_sig)
                    if _a118_shadow and not _a118_write_table:
                        if extra_features is None:
                            extra_features = {}
                        extra_features["arch118_snapshot"] = _a118_snap  # legacy shadow в features_json
                    logger.debug("[ARCH-118] %s снимок: %d/%d флагов, TF=%s (table=%s)",
                                 symbol, _a118_snap["meta"]["n_true"],
                                 _a118_snap["meta"]["n_total"], _a118_snap["meta"]["tfs"],
                                 _a118_write_table)
        except Exception as _e_a118:
            logger.debug("[ARCH-118] snapshot error %s: %s",
                         locals().get("symbol", "?"), _e_a118)

        trade_id = self.register_trade(recommendation, regime=regime, extra_features=extra_features, _reason_out=_reason_out, regime_v2=_regime_v2)

        # ARCH-118 Шаг 5b: снимок в таблицу trade_features (FK), когда есть trade_id.
        if trade_id and _a118_write_table and _a118_snap is not None:
            try:
                self._write_trade_features(trade_id, _a118_snap)
            except Exception as _e_tf:
                logger.debug("[ARCH-118] _write_trade_features #%s error: %s", trade_id, _e_tf)

        # DUAL_TP: рассчитываем TP2 = следующий пивот после TP1 (30.03.2026)
        if trade_id and data_collector is not None:
            try:
                from core.infra.config_loader import config as _cfg_dtp2
                _dual_enabled = bool(
                    (_cfg_dtp2.get("trading.dual_tp") or {}).get("enabled", True)
                )
                if _dual_enabled:
                    with __import__("sqlite3").connect(self.db_path) as _conn:
                        _conn.row_factory = __import__("sqlite3").Row
                        _row = _conn.execute(
                            "SELECT strategy_type, tp1_price, tp2_price, entry_price, stop_loss, direction, symbol FROM simulated_trades WHERE id=?",
                            (trade_id,)
                        ).fetchone()
                    if _row and _row["strategy_type"] == "DUAL_TP" and _row["tp2_price"] is None and _row["tp1_price"]:
                        _sym_dtp = _row["symbol"]
                        _dir_dtp = str(_row["direction"] or "").upper()
                        _entry_dtp = float(_row["entry_price"])
                        _sl_dtp = float(_row["stop_loss"]) if _row["stop_loss"] else None
                        _tp1_dtp = float(_row["tp1_price"])
                        # Прогреваем кеш пивотов
                        from core.pivots.pivot_calculator_fixed import PivotCalculatorFixed as _PCF_dtp
                        if self._pivot_calc is None:
                            self._pivot_calc = _PCF_dtp(db_path=self.db_path)
                        await self._pivot_calc.get_weekly_pivots(_sym_dtp, data_collector)
                        await self._pivot_calc.get_monthly_pivots(_sym_dtp, data_collector)
                        await self._pivot_calc.get_daily_pivots(_sym_dtp, data_collector)
                        _tp2_result = self._pivot_calc.get_next_tp_by_hierarchy(
                            tp1_price=_tp1_dtp,
                            direction=_dir_dtp,
                            entry_price=_entry_dtp,
                            symbol=_sym_dtp,
                            stop_loss=_sl_dtp,
                            min_r=1.0,
                        )
                        if _tp2_result:
                            _tp2_price, _tp2_src = _tp2_result
                            with __import__("sqlite3").connect(self.db_path) as _conn:
                                _conn.execute(
                                    "UPDATE simulated_trades SET tp2_price=? WHERE id=?",
                                    (float(_tp2_price), trade_id)
                                )
                                _conn.commit()
                            logger.info(
                                "[DUAL_TP] %s id=%d TP2=%.6f (%s)", _sym_dtp, trade_id, _tp2_price, _tp2_src
                            )
                        else:
                            logger.info("[DUAL_TP] %s id=%d TP2 пивот не найден → остаётся None", _sym_dtp, trade_id)
            except Exception as _e_dtp:
                logger.debug("[DUAL_TP] async tp2 calc error: %s", _e_dtp)

        return trade_id

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Возвращает список открытых сделок."""
        try:
            with self._db_connect() as conn:
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

    def set_exchange_sl_order_id(self, trade_id: int, sl_order_id: str) -> None:
        """Сохраняет orderId SL-ордера на бирже для последующего cancel+replace при TSL."""
        try:
            with self._db_connect() as conn:
                conn.execute(
                    "UPDATE simulated_trades SET exchange_sl_order_id = ? WHERE id = ?",
                    (str(sl_order_id), trade_id),
                )
            logger.debug("TradeSimulator: trade #%d → exchange_sl_order_id=%s", trade_id, sl_order_id)
        except Exception as e:
            logger.warning("TradeSimulator: set_exchange_sl_order_id #%d: %s", trade_id, e)

    def set_exchange_tp_order_id(self, trade_id: int, tp_order_id: str) -> None:
        """Сохраняет orderId TP-ордера на бирже. ARCH-94: аудит рассинхрона TP."""
        try:
            with self._db_connect() as conn:
                conn.execute(
                    "UPDATE simulated_trades SET exchange_tp_order_id = ? WHERE id = ?",
                    (str(tp_order_id), trade_id),
                )
            logger.debug("TradeSimulator: trade #%d → exchange_tp_order_id=%s", trade_id, tp_order_id)
        except Exception as e:
            logger.warning("TradeSimulator: set_exchange_tp_order_id #%d: %s", trade_id, e)

    def set_position_id(self, trade_id: int, position_id: str) -> None:
        """Сохраняет positionID позиции на бирже (fake-R фикс, 19.06).

        positionID неизменен через всю жизнь позиции (вход + SL + TP + перевыставленные SL),
        поэтому в _resolve_exit он — надёжный якорь exit'а: устойчив к cancel+replace SL
        (лечит протухший exchange_sl_order_id), повторным входам и старым ордерам по символу.
        [[bug_phantom_exit_resolve]]
        """
        try:
            with self._db_connect() as conn:
                conn.execute(
                    "UPDATE simulated_trades SET position_id = ? WHERE id = ?",
                    (str(position_id), trade_id),
                )
            logger.debug("TradeSimulator: trade #%d → position_id=%s", trade_id, position_id)
        except Exception as e:
            logger.warning("TradeSimulator: set_position_id #%d: %s", trade_id, e)

    def set_exchange_order_id(
        self, trade_id: int, order_id: str, qty: float = 0.0,
        actual_entry_price: float = 0.0,
    ) -> None:
        """Привязывает реальный exchange_order_id к симуляторной сделке.
        Только такие сделки будут синхронизироваться с биржей в VST/LIVE режиме.
        qty — размер позиции, нужен для TSL cancel+replace.
        actual_entry_price — реальная цена исполнения с биржи (avg_price из ордера).
        """
        try:
            with self._db_connect() as conn:
                if qty > 0 and actual_entry_price > 0:
                    conn.execute(
                        "UPDATE simulated_trades SET exchange_order_id = ?, qty = ?, actual_entry_price = ? WHERE id = ?",
                        (str(order_id), qty, actual_entry_price, trade_id),
                    )
                elif qty > 0:
                    conn.execute(
                        "UPDATE simulated_trades SET exchange_order_id = ?, qty = ? WHERE id = ?",
                        (str(order_id), qty, trade_id),
                    )
                elif actual_entry_price > 0:
                    conn.execute(
                        "UPDATE simulated_trades SET exchange_order_id = ?, actual_entry_price = ? WHERE id = ?",
                        (str(order_id), actual_entry_price, trade_id),
                    )
                else:
                    conn.execute(
                        "UPDATE simulated_trades SET exchange_order_id = ? WHERE id = ?",
                        (str(order_id), trade_id),
                    )
            logger.debug(
                "TradeSimulator: trade #%d → exchange_order_id=%s qty=%.6f actual_entry=%.6f",
                trade_id, order_id, qty, actual_entry_price,
            )
        except Exception as e:
            logger.warning("TradeSimulator: set_exchange_order_id #%d: %s", trade_id, e)

    def _get_trade_analyzer(self):
        """DEV-15: Ленивая инициализация TradeAnalyzer (только если API ключ доступен)."""
        if not self._trade_analyzer_init:
            self._trade_analyzer_init = True
            try:
                from core.infra.config_loader import config as _cfg
                if _cfg.get("anthropic.enabled", True):
                    from core.trading.trade_analyzer import TradeAnalyzer
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
        # DEV-148: защита от concurrent close одной сделки → database is locked cascade
        if trade_id in self._close_in_progress:
            logger.debug("[TradeSimulator] close_trade %d уже в процессе — пропуск", trade_id)
            return False
        self._close_in_progress.add(trade_id)
        closed_at = closed_at or datetime.now(timezone.utc)
        try:
            with self._db_connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT entry_price, stop_loss, take_profit, tp1_price, tp1_hit_at, direction, created_at, max_price, min_price, symbol, tsl_tf, strategy_type, original_sl, qty FROM simulated_trades WHERE id = ? AND status = ?",
                    (trade_id, STATUS_OPEN),
                )
                row = cursor.fetchone()
                if not row:
                    return False
                entry, sl, tp, tp1_price_db, tp1_hit_at_db, direction, created_at, max_price_db, min_price_db, symbol, entry_tf_db, strategy_type_db, original_sl_db, qty_db = row
                strategy_type_db = str(strategy_type_db or "SINGLE")
                entry = float(entry)
                sl = float(sl) if sl is not None else None
                tp = float(tp) if tp is not None else None
                tp1_price_db = float(tp1_price_db) if tp1_price_db is not None else None
                max_price_db = float(max_price_db) if max_price_db is not None else None
                min_price_db = float(min_price_db) if min_price_db is not None else None
                dir_up = str(direction).upper()

                # SANITY exit_price (18.06): инвариант — цена закрытия не могла быть вне реального
                # ценового диапазона [min_price, max_price], который сделка прошла по тикам. Фантомный
                # exit (чужой filled-ордер из _resolve_exit) даёт R >> MFE (STG R=264 при MFE=1.3).
                # Clamp в точный наблюдённый диапазон → гарантирует R_multiple <= max_R_possible
                # (без допуска: при узких стопах ote one_r≈0.5%, любой % допуска раздувает R на >0.3R).
                if (exit_price and max_price_db and min_price_db
                        and max_price_db >= min_price_db):
                    if exit_price > max_price_db or exit_price < min_price_db:
                        _exit_bad = exit_price
                        exit_price = min(max(float(exit_price), min_price_db), max_price_db)
                        logger.warning(
                            "[close_trade] #%s %s: phantom exit %.8g вне [%.8g, %.8g] → clamp %.8g",
                            trade_id, symbol, _exit_bad, min_price_db, max_price_db, exit_price,
                        )

                # R-multiple: вся математика через core.trading.r_math (27.05.2026).
                # 1R = |entry - original_sl| (исходный риск), fallback на текущий sl.
                from core.trading.r_math import compute_one_r, compute_r, clamp_r, clamp_r_smart
                one_r, _r_src = compute_one_r(entry, original_sl_db, fallback_sl=sl)
                r_multiple = None

                # profit_pct и R с учётом частичного TP1 (tp1_fix_pct% позиции)
                if tp1_hit_at_db and tp1_price_db and one_r:
                    _tp1_fix = 0.7
                    try:
                        from core.infra.config_loader import config as _cfg_fix
                        _tp1_fix = float(
                            (_cfg_fix.get("trading.dual_tp") or {}).get("tp1_fix_pct", 70)
                        ) / 100.0
                    except Exception:
                        pass
                    _tp2_fix = 1.0 - _tp1_fix
                    r_tp1  = compute_r(dir_up, entry, tp1_price_db, one_r) or 0.0
                    r_exit = compute_r(dir_up, entry, exit_price,    one_r) or 0.0
                    if dir_up == "LONG":
                        pct_tp1  = (tp1_price_db - entry) / entry * 100.0
                        pct_exit = (exit_price    - entry) / entry * 100.0
                    else:
                        pct_tp1  = (entry - tp1_price_db) / entry * 100.0
                        pct_exit = (entry - exit_price)    / entry * 100.0
                    r_multiple = round(_tp1_fix * r_tp1 + _tp2_fix * r_exit, 3)
                    profit_pct = round(_tp1_fix * pct_tp1 + _tp2_fix * pct_exit, 4)
                else:
                    # Обычный выход без частичного TP
                    if dir_up == "LONG":
                        profit_pct = (exit_price - entry) / entry * 100.0
                    else:
                        profit_pct = (entry - exit_price) / entry * 100.0
                    if one_r:
                        r_multiple = compute_r(dir_up, entry, exit_price, one_r)

                # Умный clamp по ПРИЧИНЕ (sl_dist), не величине: раннеры (sl_dist>=0.3%) дышат
                # без потолка, артефакт sl_dist≈0 (ASR R=-450) клампится. Логируем срабатывание.
                if r_multiple is not None:
                    _clamped = clamp_r_smart(r_multiple, entry, one_r)
                    if _clamped != r_multiple:
                        logger.warning(
                            "R_multiple clamp: id=%s %s R=%.2f → %.2f (sl_dist≈0 артефакт, src=%s)",
                            trade_id, dir_up, r_multiple, _clamped, _r_src,
                        )
                    r_multiple = round(_clamped, 3)

                # MFE: максимально достижимый R и % захваченного потенциала
                # one_r от original_sl → корректный масштаб
                max_R_possible = None
                captured_R_pct = None
                if one_r and one_r > 0:
                    _peak = max_price_db if dir_up == "LONG" else min_price_db
                    if _peak:
                        _mfe = compute_r(dir_up, entry, _peak, one_r)
                        max_R_possible = round(clamp_r_smart(_mfe, entry, one_r), 3) if _mfe is not None else None
                    if max_R_possible and max_R_possible > 0 and r_multiple is not None:
                        # #6 BACKLOG (DATA-AUDIT-2: avg -14.3% сломан): captured = % захвата
                        # ПОЛОЖИТЕЛЬНОГО потенциала, clamp [0,100]. realized<0 → 0 (упустили весь,
                        # вышли в минус); realized>max_R (clamp_r_smart артефакт раннера) → 100.
                        _cap_raw = (r_multiple / max_R_possible) * 100.0
                        captured_R_pct = round(max(0.0, min(100.0, _cap_raw)), 1)

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

                # комиссия round-trip: qty × entry × 0.1% (только VST-сделки с реальным qty)
                total_fee = round(float(qty_db) * entry * 0.001, 4) if qty_db else 0.0

                cursor.execute(
                    """
                    UPDATE simulated_trades
                    SET status = ?, exit_price = ?, profit_pct = ?, R_multiple = ?,
                        closed_at = ?, duration_minutes = ?, max_R_possible = ?, captured_R_pct = ?,
                        total_fee = ?
                    WHERE id = ?
                    """,
                    (status, exit_price, profit_pct, r_multiple,
                     closed_at.isoformat(), duration_minutes,
                     max_R_possible, captured_R_pct, total_fee, trade_id),
                )
                conn.commit()
            logger.info(f"TradeSimulator: закрыта сделка id={trade_id} {status} exit={exit_price:.4f} R={r_multiple}")

            # DEV-39: Market Event Marker — скользящее окно SL
            if status == STATUS_SL:
                try:
                    from core.infra.config_loader import config as _cfg
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

            # DEV-92 / TR-010: Post-TSL очередь для OTE Re-entry мониторинга
            if status == STATUS_TSL and symbol:
                _dir92 = str(direction).upper() if direction else None
                self._post_tsl_queue[symbol] = {
                    "direction":    _dir92,
                    "exit_price":   exit_price,
                    "impulse_high": max_price_db,
                    "impulse_low":  min_price_db,
                    "exit_time":    datetime.now(timezone.utc),
                    "ttl_hours":    8,
                }
                logger.info(
                    "[POST_TSL_QUEUE] %s: добавлен direction=%s impulse=[%.4f, %.4f]",
                    symbol, _dir92,
                    min_price_db or 0, max_price_db or 0,
                )

            # Куб: Сфера 10 (Exit Manager) → bus: POSITION_CLOSED
            _pcb = getattr(self, "_pair_context_bus", None)
            if _pcb is not None and symbol:
                try:
                    from core.context.pair_context import SphereEvent
                    _pcb.publish(symbol, SphereEvent.POSITION_CLOSED, {
                        "trade_id": trade_id,
                        "status": status,
                        "r_multiple": round(r_multiple, 3) if r_multiple is not None else 0.0,
                        "direction": str(direction).upper() if direction else "LONG",
                        "exit_price": exit_price,
                    })
                except Exception as _epc:
                    logger.debug("[Cube] POSITION_CLOSED publish error: %s", _epc)

            # DEV-94: callback для PostTradeAnalyser (async, не блокируем)
            if self._post_trade_callback and symbol:
                try:
                    import asyncio as _asyncio
                    _r = r_multiple if r_multiple is not None else 0.0
                    _sl_dist = abs(entry - (sl or entry))
                    _asyncio.create_task(self._post_trade_callback(
                        trade_id=trade_id,
                        status=status,
                        symbol=symbol,
                        direction=str(direction).upper() if direction else "LONG",
                        r_multiple=_r,
                        entry_price=entry,
                        sl_dist=_sl_dist,
                        max_price=max_price_db,
                        min_price=min_price_db,
                        entry_tf=entry_tf_db or "15m",
                    ))
                except Exception as _ecb:
                    logger.debug("[DEV-94] post_trade_callback error: %s", _ecb)

            # SSE broadcast: уведомляем дашборд о закрытой сделке
            if self._sse_trade_closed:
                try:
                    import asyncio as _aio_sse
                    _aio_sse.create_task(self._sse_trade_closed(trade_id))
                except Exception as _esse:
                    logger.debug("[SSE] sse_trade_closed callback error: %s", _esse)

            # DEV-222: TG reply при закрытии (reply на сообщение об открытии)
            if self._tg_close_callback:
                try:
                    import asyncio as _aio_tg
                    # Читаем tsl_activated из БД (обновлён в check_open_trades)
                    _tsl_act = 0
                    try:
                        with self._db_connect() as _tg_conn:
                            _tg_row = _tg_conn.execute(
                                "SELECT tsl_activated FROM simulated_trades WHERE id=?", (trade_id,)
                            ).fetchone()
                            _tsl_act = int(_tg_row[0]) if _tg_row else 0
                    except Exception:
                        pass
                    _aio_tg.create_task(self._tg_close_callback(
                        trade_id=trade_id,
                        status=status,
                        symbol=symbol,
                        direction=str(direction).upper() if direction else "LONG",
                        r_multiple=r_multiple if r_multiple is not None else 0.0,
                        tsl_activated=_tsl_act,
                        max_r_possible=max_R_possible,
                    ))
                except Exception as _etg:
                    logger.debug("[DEV-222] tg_close_callback error: %s", _etg)

            return True
        except Exception as e:
            logger.exception(f"TradeSimulator: ошибка close_trade {trade_id} — {e}")
            return False
        finally:
            self._close_in_progress.discard(trade_id)

    def _mark_market_event_in_window(self, window_start: datetime) -> None:
        """DEV-39: ретроактивно помечает SL-сделки в окне как market_event=true."""
        try:
            ws_str = window_start.isoformat()
            with self._db_connect() as conn:
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
    ) -> tuple:
        """
        Проверяет открытые сделки с поддержкой TSL (Trailing Stop Loss).
        TSL активируется после достижения tsl_activation_r прибыли.
        Безубыток активируется после достижения breakeven_activation_r (до TSL).

        Args:
            data_collector: Источник OHLCV данных
            use_tsl: Включить TSL логику
            tsl_activation_r: После скольки R активировать TSL (1.0 = после +1R)

        Returns:
            tuple(closed_count: int, tsl_moved: list[dict])
            tsl_moved — список сделок где TSL активен и цена TSL изменилась:
              {trade_id, symbol, direction, qty, new_sl_price, old_sl_price,
               exchange_sl_order_id, exchange_order_id}
        """
        open_trades = self.get_open_trades()
        # Оперативка из ШИНЫ (dashboard /api/open): цикл и так грузит открытые сделки —
        # публикуем лёгкий снапшот в шину, чтобы /api/open читал из неё, а не бил синхронный
        # SQL (29K, лок с этим же горячим циклом → ~20с-таймаут). Пусто тоже публикуем
        # (все закрылись → дашборд очищается). Цена/R обогащаются из шины на каждый запрос.
        _pcb = getattr(self, "_pair_context_bus", None)
        if _pcb is not None:
            try:
                _pcb.set_open_trades(open_trades)
            except Exception:
                pass
        if not open_trades:
            return 0, []

        # DEV-92: инвалидация _post_tsl_queue по TTL и пробою impulse
        _now92 = datetime.now(timezone.utc)
        _to_del92 = []
        for _sym92, _q92 in self._post_tsl_queue.items():
            _age_h = (_now92 - _q92["exit_time"]).total_seconds() / 3600
            if _age_h > _q92.get("ttl_hours", 8):
                _to_del92.append(_sym92)
        for _sym92 in _to_del92:
            logger.debug("[POST_TSL_QUEUE] %s: удалён по TTL", _sym92)
            del self._post_tsl_queue[_sym92]

        closed_count = 0
        tsl_moved: list = []   # сделки где TSL активен и SL-цена изменилась
        # OPS-05: параллелизация check_open (gather+Semaphore) — лечит saturation
        from core.infra.config_loader import config as _ops05_cfg
        _sem_n = int(_ops05_cfg.get('performance.check_open_semaphore', 15)) if _ops05_cfg else 15
        _sem = asyncio.Semaphore(_sem_n)
        if getattr(self, '_ops05_piv_lock', None) is None:
            self._ops05_piv_lock = asyncio.Lock()
        # SIM-DEPRIO: throttle интервал из config (default 60с = без изменений; 300с = экономия 80%)
        _sim_iv = int(_ops05_cfg.get("performance.sim_check_interval_sec", 60)) if _ops05_cfg else 60
        # SIM-TIME-EXIT (анти-орфан): закрыть sim-only EXPIRED если висит > N часов и не TP/SL.
        # Корень копления орфанов: sim-сделки закрывались ТОЛЬКО по TP/SL → при боковике висели вечно.
        _sim_te_h = float(_ops05_cfg.get("performance.sim_time_exit_hours", 48)) if _ops05_cfg else 48.0

        async def _proc(trade):
            _ops05c = 0
            _ops05tsl = []
            # SIM-DEPRIO: пропустить sim-only сделки если не истёк throttle-интервал.
            # Биржевые (exchange_order_id реальный) — всегда проверять (деньги).
            _exch_id_pre = trade.get("exchange_order_id")
            _is_sim_only = not (bool(_exch_id_pre) and _exch_id_pre != "SIM")
            if _is_sim_only:
                # SIM-TIME-EXIT (анти-орфан): закрыть EXPIRED если висит > N часов и не TP/SL.
                # Биржевые НЕ трогаем (закрываются биржей). Устраняет КОРЕНЬ копления sim-орфанов.
                if _sim_te_h > 0:
                    _created = trade.get("created_at")
                    if _created:
                        try:
                            _ct = datetime.fromisoformat(str(_created).replace("Z", "+00:00"))
                            if _ct.tzinfo is None:
                                _ct = _ct.replace(tzinfo=timezone.utc)
                            _age_h = (datetime.now(timezone.utc) - _ct).total_seconds() / 3600.0
                            if _age_h > _sim_te_h:
                                _px = await data_collector.get_current_price(trade["symbol"])
                                _px = float(_px) if _px else float(trade["entry_price"])
                                self.close_trade(trade["id"], STATUS_EXPIRED, _px)
                                logger.info("[SIM-TIME-EXIT] #%d %s EXPIRED (age %.0fh > %.0fh)",
                                            trade["id"], trade["symbol"], _age_h, _sim_te_h)
                                return
                        except Exception as _tee:
                            logger.debug("[SIM-TIME-EXIT] %s: %s", trade.get("symbol"), _tee)
                import time as _t_sim
                _now_sim = _t_sim.monotonic()
                _tid_sim = trade["id"]
                if _now_sim - self._sim_checked.get(_tid_sim, 0) < _sim_iv:
                    return
                self._sim_checked[_tid_sim] = _now_sim
            async with _sem:
                trade_id = trade["id"]
                symbol = trade["symbol"]
                direction = (trade["direction"] or "").upper()
                # Системный фикс sim_only режима: order_manager возвращает "SIM" как
                # exchange_order_id для sim-сделок. Без этой проверки LIVE-GUARD считал
                # их биржевыми и блокировал close → 200+ stuck OPEN в strip-боте.
                # vst/live: _exch_id — реальный order_id, поведение не меняется.
                _exch_id = trade.get("exchange_order_id")
                _exchange_managed_trade = bool(_exch_id) and _exch_id != "SIM"
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

                # DS-322: throttle REPAIR-SL — старые SIM-сделки без exchange SL не чинятся,
                # только жрут OHLCV. Проверяем раз в час, не каждый цикл.
                _exch_sl = trade.get("exchange_sl_order_id")
                _now_ts = time.time()
                if (not trade.get("tsl_activated") and not _exch_sl and age_minutes > 60):
                    _last_check = self._repair_checked.get(trade_id, 0)
                    if _now_ts - _last_check < 3600:
                        return (_ops05c, _ops05tsl)  # throttle: проверяли < 1ч назад

                tf = trade.get("timeframe") or DEFAULT_TIMEFRAME

                # WS pre-filter: если WsFeed даёт цену — проверим, нужен ли вообще REST
                # Пропускаем OHLCV-fetch если цена далеко от всех уровней (экономим REST)
                _sl_level  = trade.get("stop_loss")
                _tp_level  = trade.get("take_profit")
                _tsl_level = trade.get("tsl_price")
                _dir       = trade.get("direction", "LONG")
                _ws_price  = None
                if hasattr(data_collector, "get_current_price"):
                    try:
                        _ws_price = await data_collector.get_current_price(symbol)
                    except Exception:
                        pass
                # DEV-TSL-PREFILTER: TSL-активированные сделки ВСЕГДА проверяем —
                # TSL нужно двигать когда цена уходит В ПРОФИТ (прочь от стопа), а не к нему.
                # Старый фильтр "пропускаем если далеко от SL/TP" глушил TSL-трекинг.
                _tsl_active_pre = bool(trade.get("tsl_activated"))
                if _ws_price and _sl_level and _tp_level and not _tsl_active_pre:
                    _sl_f, _tp_f = float(_sl_level), float(_tp_level)
                    _tsl_f = float(_tsl_level) if _tsl_level else None
                    # Буфер 0.5% — если цена далеко от всех уровней, пропускаем тяжёлый REST
                    _buf = _ws_price * 0.005
                    _near_sl  = abs(_ws_price - _sl_f) <= _buf
                    _near_tp  = abs(_ws_price - _tp_f) <= _buf
                    _near_tsl = _tsl_f is not None and abs(_ws_price - _tsl_f) <= _buf
                    # Для LONG: SL пробит если цена НИЖЕ SL
                    _sl_hit_ws = (_dir == "LONG" and _ws_price <= _sl_f + _buf) or \
                                 (_dir == "SHORT" and _ws_price >= _sl_f - _buf)
                    _tp_hit_ws = (_dir == "LONG" and _ws_price >= _tp_f - _buf) or \
                                 (_dir == "SHORT" and _ws_price <= _tp_f + _buf)
                    # DEV-226: НЕ пропускать сделку, уже достигшую порога ранней активации.
                    # TSL/BE/MTF-220 триггерят от 0.3R (см. early-MTF gate ниже: max(act_r*0.5, 0.3)).
                    # Без этого сделка в глубоком профите, но далеко от SL и TP ("мёртвая зона"
                    # фильтра), навсегда остаётся tsl_activated=0 — pre-filter каждый цикл делает
                    # continue ДО блока активации. Инцидент: UNI +2.25R / BERA +2.58R с tsl=0.
                    _early_r_ws = None
                    _osl_pre = trade.get("original_sl")
                    _osl_pre_v = float(_osl_pre) if _osl_pre is not None else _sl_f
                    if _osl_pre_v and _osl_pre_v != entry:
                        _one_r_pre = abs(entry - _osl_pre_v)
                        if _one_r_pre > 0:
                            _early_r_ws = ((_ws_price - entry) if _dir == "LONG"
                                           else (entry - _ws_price)) / _one_r_pre
                    _profit_for_activation = _early_r_ws is not None and _early_r_ws >= 0.3
                    if not (_near_sl or _near_tp or _near_tsl or _sl_hit_ws or _tp_hit_ws
                            or _profit_for_activation):
                        logger.debug("[WS-skip] %s price=%.4f далеко от SL/TP/TSL — пропуск REST",
                                     symbol, _ws_price)
                        return (_ops05c, _ops05tsl)  # цена далеко — этот цикл пропускаем, следующий догонит

                try:
                    df = await data_collector.get_ohlcv(symbol, timeframe=tf, limit=200)
                except Exception as e:
                    logger.debug(f"TradeSimulator: get_ohlcv {symbol} — {e}")
                    df = None

                # DEV-227 stale-guard: WS-кэш может быть ОТРАВЛЕН — последний бар имеет свежий
                # timestamp (текущий формирующийся бар), но цены в нём устаревшие, т.к. WS-обновление
                # символа умерло (UNI/BERA: ohlcv timeout). Детект по возрасту бара бесполезен (бар
                # «свежий» по времени). current_r считается по stale цене → TSL/BE не активируются
                # (UNI: бот видит +0.41R при реальных +2.29R). Решение: для НЕ-активированных OPEN
                # периодически (throttle 150с/сделку) форсим реальный REST в обход кэша+circuit breaker.
                # Если df пуст/None — форсим всегда. Активированные идут обычным путём (TSL уже трекается).
                _now_ts = datetime.now(timezone.utc).timestamp()
                _need_force = df is None or len(df) == 0
                if not _need_force and not bool(trade.get("tsl_activated")):
                    if (_now_ts - self._force_rest_ts.get(trade_id, 0.0)) > 150:
                        _need_force = True
                if _need_force:
                    self._force_rest_ts[trade_id] = _now_ts
                    try:
                        _df_fresh = await data_collector.get_ohlcv(symbol, timeframe=tf, limit=200, force_refresh=True)
                        if _df_fresh is not None and len(_df_fresh) > 0:
                            df = _df_fresh
                            logger.info("[DEV-227] %s id=%d force REST refresh (stale-guard)", symbol, trade_id)
                    except Exception as _e227:
                        logger.debug("[DEV-227] %s force_refresh error: %s", symbol, _e227)

                if df is None or len(df) == 0:
                    return (_ops05c, _ops05tsl)

                # Оставляем только свечи после created_at
                if "time" in df.columns:
                    df = df.copy()
                    df["time"] = pd.to_numeric(df["time"], errors="coerce")
                    try:
                        created_ms = created_dt.timestamp() * 1000
                        # OPS-01b анти-#1910 (КОРЕНЬ, 10.06): created_at пишется СИСТЕМНЫМИ часами
                        # хоста (Windows, datetime.now при register), а df["time"] — БИРЖЕВОЕ время
                        # свечей. Если часы хоста ушли ВПЕРЁД, created_ms оказывается «в будущем»
                        # относительно реальных биржевых баров → фильтр пуст → SL не проверяется
                        # (#1910, APR −9.74R). Биржевое время последнего бара = источник правды
                        # (уже лежит в df["time"], без лишнего fetch_time). Детектим рассинхрон,
                        # клампим created_ms к биржевой шкале — SL проверится по реальным свечам.
                        _exch_last_ms = float(df["time"].iloc[-1])
                        if created_ms > _exch_last_ms:
                            _skew_min = (created_ms - _exch_last_ms) / 60000.0
                            logger.warning(
                                "[OPS-01b/#1910] trade %d: created_at (%s) ОПЕРЕЖАЕТ биржевое время "
                                "на %.1f мин — часы хоста сбиты ВПЕРЁД. Клампим к биржевой шкале "
                                "(SL-чек по текущей свече, биржа=правда).",
                                trade_id, created_at, _skew_min,
                            )
                            created_ms = _exch_last_ms  # биржевое время = источник правды
                        df_filtered = df[df["time"] >= created_ms].copy()
                        # OPS-01a анти-#1910 (аудит 09.06): пустой фильтр = часы хоста сбиты вперёд?
                        # РАНЬШЕ слепой continue → SL НЕ проверялся → APR висела -9.74R вместо -1R.
                        # ТЕПЕРЬ sanity: проверяем SL по ПОСЛЕДНЕЙ свече (текущая рыночная цена, не
                        # pre-entry бары) — стоп сработает даже при сбитых системных часах.
                        if len(df_filtered) == 0:
                            logger.warning(
                                "[OPS-01a/#1910] trade %d: 0 баров после created_at (%s) — sanity-чек SL "
                                "по текущей свече (НЕ слепой пропуск). Проверь часы хоста!",
                                trade_id, created_at,
                            )
                            df = df.tail(1).copy()   # текущая свеча = рыночная цена сейчас
                        else:
                            df = df_filtered
                    except Exception:
                        pass
                if len(df) == 0:
                    return (_ops05c, _ops05tsl)

                # Расчет текущего R-multiple для проверки активации TSL
                current_price = df.iloc[-1]["close"]

                # DEV-92: инвалидация _post_tsl_queue по пробою impulse
                _q92 = self._post_tsl_queue.get(symbol)
                if _q92:
                    _imp_h92 = _q92.get("impulse_high")
                    _imp_l92 = _q92.get("impulse_low")
                    if _q92["direction"] == "SHORT" and _imp_h92 and current_price > _imp_h92:
                        logger.debug("[POST_TSL_QUEUE] %s: удалён — пробой impulse_high %.4f",
                                     symbol, _imp_h92)
                        del self._post_tsl_queue[symbol]
                    elif _q92["direction"] == "LONG" and _imp_l92 and current_price < _imp_l92:
                        logger.debug("[POST_TSL_QUEUE] %s: удалён — пробой impulse_low %.4f",
                                     symbol, _imp_l92)
                        del self._post_tsl_queue[symbol]
                # DEV-TSL-R: current_r всегда от original_sl (не от TSL'нутого stop_loss).
                # Иначе после подтяжки SL к BE one_r→0, current_r→∞ → нестабильный гейт активации.
                current_r = None
                _orig_sl_val = trade.get("original_sl")
                _sl_for_r = float(_orig_sl_val) if _orig_sl_val is not None else sl
                if _sl_for_r is not None and _sl_for_r != entry:
                    one_r = abs(entry - _sl_for_r)
                    if direction == "LONG":
                        current_r = (current_price - entry) / one_r
                    else:
                        current_r = (entry - current_price) / one_r
                    # DEV-226 слой 2: cross-source R — защита от stale 15m OHLCV-кэша.
                    # При сбоях WS OHLCV-обновления (UNI/BERA: Connection timeout) fetch_ohlcv
                    # отдаёт протухший df → current_r по df.close занижен (UNI: stale +0.41R при
                    # реальных +2.15R) → триггеры gate TSL/BE/cascade не срабатывают. _ws_price
                    # (get_current_price: WS ticker / 1m кэш) — отдельный, более свежий источник.
                    # Корректируем заниженный R вверх (профит реален → защита включается вовремя).
                    # Экзиты SL/TP не затрагиваются — они идут отдельно по свече (current_price).
                    if _ws_price and one_r > 0:
                        _r_ws_gate = ((_ws_price - entry) if direction == "LONG"
                                      else (entry - _ws_price)) / one_r
                        if current_r is None or _r_ws_gate > current_r:
                            current_r = _r_ws_gate

                # DEV-40: Безубыток — перенести SL в entry ± 0.1% после достижения breakeven_activation_r
                # use_be_after_tp1: альтернативный триггер — BE при хите TP1 (независимо от R)
                be_activated = bool(trade.get("be_activated"))
                _be_trigger_r = (use_breakeven and not be_activated and current_r is not None and current_r >= breakeven_activation_r)
                _be_trigger_tp1 = (use_be_after_tp1 and not be_activated and tp1_hit_at is not None)
                if (_be_trigger_r or _be_trigger_tp1) and sl is not None:
                    from core.trading.tsl_engine import breakeven_sl as _be_calc
                    be_sl = _be_calc(direction, entry)
                    should_move = (
                        (direction == "LONG" and sl < be_sl) or
                        (direction == "SHORT" and sl > be_sl)
                    )
                    if should_move:
                        try:
                            with self._db_connect() as _c:
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
                # DEV-122: RANGE — активируем TSL раньше (tsl_activation_r_range=0.7)
                _trade_regime = trade.get("regime", "")
                _tsl_act_r = tsl_activation_r
                try:
                    from core.infra.config_loader import config as _cfg_tsl
                    if _trade_regime == "RANGE":
                        _tsl_act_r = float(_cfg_tsl.get("trading.tsl_activation_r_range", tsl_activation_r))
                    # Рой-консенсус: per-strategy пороги (pivot=0.5R, wt_b=0.8R, wt_signal=1.0R, atr_change=1.5R)
                    _sig_type_trade = trade.get("signal_type", "")
                    _per_strategy_tsl = _cfg_tsl.get("trading.tsl_activation_r_per_strategy", {})
                    if _sig_type_trade and isinstance(_per_strategy_tsl, dict) and _sig_type_trade in _per_strategy_tsl:
                        _tsl_act_r = float(_per_strategy_tsl[_sig_type_trade])
                except Exception:
                    pass
                _tsl_gate = (current_r is not None and current_r >= _tsl_act_r)
                # DEV-220: MTF событийная активация — при R >= порог*0.5 + 1h ATR-trend подтверждает
                # Рой-консенсус: не ждём жёсткий +R, а смотрим на структуру старшего ТФ
                if use_tsl and not _tsl_gate and current_r is not None and current_r >= max(_tsl_act_r * 0.5, 0.3):
                    try:
                        from core.indicators.indicators import calculate_trend as _calc_trend_mtf
                        from core.infra.config_loader import config as _cfg_mtf220
                        _mtf220_atr_p = int(_cfg_mtf220.get("analysis.indicators.trend.atr_period", 43))
                        _mtf220_factor = float(_cfg_mtf220.get("analysis.indicators.trend.factor", 1.0))
                        _df_1h_mtf = await data_collector.get_ohlcv(symbol, "1h", limit=55)
                        if _df_1h_mtf is not None and len(_df_1h_mtf) >= 50:
                            _df_1h_tr = _calc_trend_mtf(_df_1h_mtf, atr_period=_mtf220_atr_p, factor=_mtf220_factor)
                            _1h_trend_now = int(_df_1h_tr["trend"].iloc[-1])
                            _1h_trend_prev = int(_df_1h_tr["trend"].iloc[-2]) if len(_df_1h_tr) >= 2 else _1h_trend_now
                            _1h_flip = (_1h_trend_now != _1h_trend_prev)
                            _1h_align = (
                                (direction == "LONG" and _1h_trend_now == 1) or
                                (direction == "SHORT" and _1h_trend_now == -1)
                            )
                            if _1h_align:
                                _tsl_gate = True
                                logger.info(
                                    "[DEV-220] %s id=%d MTF early TSL: R=%.2f>=%.2f*0.5 + 1h %s%s",
                                    symbol, trade_id, current_r, _tsl_act_r,
                                    "trend align", " (flip!)" if _1h_flip else "",
                                )
                    except Exception:
                        pass
                if use_tsl and _tsl_gate:
                    # Активируем TSL после достижения прибыли — помечаем в БД
                    _tsl_just_activated = False
                    try:
                        with self._db_connect() as _c:
                            _cur = _c.execute(
                                "UPDATE simulated_trades SET tsl_activated=1 WHERE id=? AND tsl_activated=0",
                                (trade_id,),
                            )
                            _c.commit()
                            _tsl_just_activated = _cur.rowcount > 0
                    except Exception:
                        pass

                    # DEV-223: TG алерт при первой активации TSL
                    if _tsl_just_activated and self._tg_tsl_alert_callback:
                        try:
                            import asyncio as _aio_tsl
                            _aio_tsl.create_task(self._tg_tsl_alert_callback(
                                trade_id=trade_id,
                                symbol=symbol,
                                direction=direction,
                                current_r=current_r,
                                tsl_tf=tf,
                            ))
                        except Exception as _etsl:
                            logger.debug("[DEV-223] tg_tsl_alert error: %s", _etsl)

                    try:
                        from core.indicators.indicators import calculate_trend, get_trend_info
                        from core.infra.config_loader import config as _cfg_trend
                        _tsl_atr_p = int(_cfg_trend.get("analysis.indicators.trend.atr_period", 43))
                        _tsl_factor = float(_cfg_trend.get("analysis.indicators.trend.factor", 1.0))

                        df_tsl = None
                        tsl_tf_used = tf
                        _ob_force_close = False  # DEV-221: OB return при де-эскалации
                        # DS-321: гибрид включён?
                        _use_hybrid = bool(_cfg_trend.get("sl_tp_engine.tsl_hybrid_enabled", False))

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
                                # ARCH-62 Шаг 1: cap_tf после tp1_hit — не эскалировать выше "1h"
                                from core.trading.cascade_tsl import get_cascade_cap_tf
                                _tp1_hit_now = bool(trade.get("tp1_hit_at"))
                                _cap_tf = get_cascade_cap_tf(_tp1_hit_now, _cfg_trend)
                                _cascade_tfs_capped = (
                                    [t for t in _CASCADE_TFS if _CASCADE_TFS.index(t) <= _CASCADE_TFS.index(_cap_tf)]
                                    if _cap_tf and _cap_tf in _CASCADE_TFS else _CASCADE_TFS
                                )

                                # Нормальная эскалация: самый старший ТФ где тренд совпадает.
                                for _ctf in _cascade_tfs_capped:
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
                                    from core.infra.config_loader import config as _cfg_ts
                                    _de_esc_r = float(_cfg_ts.get("trading.cascade_tsl_deescalation_r", 5.0))
                                    _wt_ob = float(_cfg_ts.get("analysis.indicators.wavetrend.ob_threshold", 60.0))
                                    _wt_os = float(_cfg_ts.get("analysis.indicators.wavetrend.os_threshold", -60.0))
                                except Exception:
                                    _de_esc_r, _wt_ob, _wt_os = 5.0, 60.0, -60.0

                                # ── DEV-106: Pivot Touch Fast Exit → force 15m TSL ──────
                                # Weekly OR Monthly pivot touch + R >= 2.0 → прыжок на 15m напрямую.
                                # Анализ 512 TSL сделок: pivot touch захватывал 58% пика (avg 4.1R из 7.8R max).
                                # При force 15m: +2.44R avg на 181 сделке (лучше 165, хуже только 16).
                                # 1M R1/R2/R3 исключены — они пробойные, не разворотные (данные).
                                _pivot_tsl_already = _feat_js.get("pivot_tsl_15m", False)
                                if (best_tsl_tf is not None and current_r is not None and
                                        current_r >= 2.0 and not _pivot_tsl_already and
                                        best_tsl_tf != "15m"):
                                    _near_w106 = False
                                    _near_m106 = False
                                    try:
                                        from core.pivots.pivot_calculator_fixed import PivotCalculatorFixed as _PCF106
                                        if self._pivot_calc is None:
                                            self._pivot_calc = _PCF106(db_path=self.db_path)
                                        def _pw106(lvl, price=current_price, pct=0.02):
                                            return bool(lvl and price and abs(price - float(lvl)) / price <= pct)
                                        # Weekly touch
                                        _wp106 = await self._pivot_calc.get_weekly_pivots(symbol, data_collector)
                                        if _wp106:
                                            if direction == "SHORT":
                                                _near_w106 = any(_pw106(_wp106.get(k)) for k in ("S1","S2","S3","PP"))
                                            else:
                                                _near_w106 = any(_pw106(_wp106.get(k)) for k in ("R1","R2","R3","PP"))
                                        # Monthly touch (1M R1/R2/R3 для LONG исключены — пробойные)
                                        _mp106 = await self._pivot_calc.get_monthly_pivots(symbol, data_collector)
                                        if _mp106:
                                            if direction == "SHORT":
                                                _near_m106 = any(_pw106(_mp106.get(k)) for k in ("S1","S2","S3","PP"))
                                            else:
                                                _near_m106 = _pw106(_mp106.get("PP"))
                                    except Exception as _e106:
                                        logger.debug("[DEV-106] pivot check: %s", _e106)

                                    if _near_w106 or _near_m106:
                                        _touch_lbl = ("1W+1M" if (_near_w106 and _near_m106)
                                                      else ("1W" if _near_w106 else "1M"))
                                        try:
                                            _df_15m_106 = await data_collector.get_ohlcv(
                                                symbol, timeframe="15m", limit=100
                                            )
                                            if _df_15m_106 is not None and len(_df_15m_106) >= 50:
                                                _df_15m_tr = calculate_trend(_df_15m_106, atr_period=_tsl_atr_p, factor=_tsl_factor)
                                                _inf_15m = get_trend_info(_df_15m_tr)
                                                _inf_cur = get_trend_info(df_tsl)
                                                if (_inf_15m and _inf_cur and
                                                        _inf_15m["tsl"] > 0 and _inf_cur["tsl"] > 0):
                                                    logger.info(
                                                        "[DEV-106] %s: %s touch R=%.1fR → force 15m TSL "
                                                        "(%.4f → %.4f)",
                                                        symbol, _touch_lbl, current_r,
                                                        _inf_cur["tsl"], _inf_15m["tsl"],
                                                    )
                                                    best_tsl_tf = "15m"
                                                    df_tsl = _df_15m_tr
                                                    _feat_js["pivot_tsl_15m"] = True
                                                    _feat_js["tsl_degraded"] = True
                                        except Exception as _e106b:
                                            logger.debug("[DEV-106] 15m apply: %s", _e106b)

                                if (best_tsl_tf is not None and current_r is not None and
                                        current_r >= _de_esc_r and best_tsl_tf in _CASCADE_TFS):
                                    _cas_idx = _CASCADE_TFS.index(best_tsl_tf)  # DEV-107 fix: was df_tsl (DataFrame)
                                    if _cas_idx > 0:
                                        # DEV-89: OR логика — 4h WT ИЛИ 1h WT (фикс бага: 1h WT игнорировался)
                                        _wt_exhausted = False
                                        _wt1_4h = None
                                        _wt1_1h = None
                                        try:
                                            from core.indicators.indicators import calculate_wt
                                            # 4h WT (текущий df_tsl)
                                            _df_wt_chk = calculate_wt(df_tsl)
                                            _wt1_4h = float(_df_wt_chk["wt1"].iloc[-1])
                                            # 1h WT (фетч)
                                            _df_1h_wt89 = await data_collector.get_ohlcv(symbol, "1h", limit=50)
                                            if _df_1h_wt89 is not None and len(_df_1h_wt89) >= 20:
                                                _df_1h_wt89 = calculate_wt(_df_1h_wt89)
                                                _wt1_1h = float(_df_1h_wt89["wt1"].iloc[-1])
                                            # OR: истощён если 4h ИЛИ 1h
                                            _wt_4h_exh = (
                                                (direction == "SHORT" and _wt1_4h is not None and _wt1_4h < _wt_os) or
                                                (direction == "LONG"  and _wt1_4h is not None and _wt1_4h > _wt_ob)
                                            )
                                            _wt_1h_exh = (
                                                (direction == "SHORT" and _wt1_1h is not None and _wt1_1h < _wt_os) or
                                                (direction == "LONG"  and _wt1_1h is not None and _wt1_1h > _wt_ob)
                                            )
                                            _wt_exhausted = _wt_4h_exh or _wt_1h_exh
                                        except Exception:
                                            pass

                                        # DEV-89: weekly pivot touch — де-эскалировать у W_S/R уровней
                                        _near_weekly = False
                                        try:
                                            from core.pivots.pivot_calculator_fixed import PivotCalculatorFixed as _PCF89
                                            if self._pivot_calc is None:
                                                self._pivot_calc = _PCF89(db_path=self.db_path)
                                            _wp89 = await self._pivot_calc.get_weekly_pivots(symbol, data_collector)
                                            if _wp89 and current_price:
                                                def _w89(lvl, pct=0.015):
                                                    return lvl and abs(current_price - float(lvl)) / current_price <= pct
                                                if direction == "SHORT":
                                                    _near_weekly = any(_w89(_wp89.get(k)) for k in ("S1","S2","S3","PP"))
                                                else:
                                                    _near_weekly = any(_w89(_wp89.get(k)) for k in ("R1","R2","R3","PP"))
                                        except Exception as _e89w:
                                            logger.debug("[DEV-89] weekly pivot: %s", _e89w)

                                        # DEV-91: R-gradient drop — реальный триггер де-эскалации (убран shadow mode)
                                        _r_gradient_drop = False
                                        _max_r_achieved = 0.0
                                        try:
                                            from core.trading.cascade_tsl import check_r_gradient_drop
                                            _mp_grad = trade.get("max_price")
                                            _lp_grad = trade.get("min_price")
                                            _sl_dist_grad = abs(entry - sl) if sl and sl > 0 else 0.0
                                            if _sl_dist_grad > 0:
                                                if direction == "LONG" and _mp_grad:
                                                    _max_r_achieved = (float(_mp_grad) - entry) / _sl_dist_grad
                                                elif direction == "SHORT" and _lp_grad:
                                                    _max_r_achieved = (entry - float(_lp_grad)) / _sl_dist_grad
                                            if current_r is not None:
                                                _r_gradient_drop = check_r_gradient_drop(
                                                    current_r, _max_r_achieved, _cfg_ts
                                                )
                                        except Exception as _e91:
                                            logger.debug("[DEV-91] r_gradient: %s", _e91)

                                        # DEV-221: если r_gradient_drop И цена в OB → force close
                                        if _r_gradient_drop and df_tsl is not None and current_price:
                                            try:
                                                from core.trading.cascade_tsl import is_price_in_adverse_ob
                                                if is_price_in_adverse_ob(df_tsl, direction, current_price):
                                                    _ob_force_close = True
                                            except Exception:
                                                pass

                                        # DEV-123: anti-degradation gate для ракет
                                        _skip_degrade = False
                                        try:
                                            from core.trading.cascade_tsl import should_skip_degradation
                                            if current_r is not None:
                                                _skip_degrade = should_skip_degradation(
                                                    current_r, _max_r_achieved, direction,
                                                    _wt1_1h, _wt1_4h, _cfg_ts
                                                )
                                        except Exception as _e123:
                                            logger.debug("[DEV-123] skip_degrade: %s", _e123)

                                        if not _skip_degrade and (_wt_exhausted or _near_weekly or _r_gradient_drop):
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
                                                        from core.trading.tsl_engine import is_tighter as _tsl_is_tighter
                                                        _is_tighter = _tsl_is_tighter(direction, _lower_tsl, _curr_tsl)
                                                        if _is_tighter:
                                                            logger.info(
                                                                "[cascade_tsl] %s: de-escalate %s → %s "
                                                                "(R=%.1fR, WT4h=%s 1h=%s near_w=%s, TSL %.4f → %.4f тесней)",
                                                                symbol, best_tsl_tf, lower_tf,
                                                                current_r,
                                                                f"{_wt1_4h:.1f}" if _wt1_4h is not None else "?",
                                                                f"{_wt1_1h:.1f}" if _wt1_1h is not None else "?",
                                                            
                                                                _near_weekly, _curr_tsl, _lower_tsl,
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
                                # DS-321: append hybrid gear for dashboard visibility
                                if _use_hybrid and current_r is not None:
                                    _gear = 3 if current_r >= 4.0 else (2 if current_r >= 2.0 else 1)
                                    tsl_tf_used = f"hybrid_gear{_gear}_mfe{current_r:.1f}r"
                                if best_tsl_tf != prev_tsl_tf:
                                    action_label = "de-escalate" if _feat_js.get("tsl_degraded") and not _tsl_degraded else "trend confirmed"
                                    logger.info(
                                        "[cascade_tsl] %s: TSL %s → %s (%s)",
                                        symbol, prev_tsl_tf, best_tsl_tf, action_label,
                                    )
                                    try:
                                        with self._db_connect() as _c:
                                            _c.execute(
                                                "UPDATE simulated_trades SET tsl_tf=?, features_json=? WHERE id=?",
                                                (tsl_tf_used, json.dumps(_feat_js), trade_id),
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
                            # DEV-TSL-DIRGUARD: fallback на entry-TF только если тренд совпадает с direction.
                            # Противоположный тренд даёт TSL по другую сторону цены → мгновенное срабатывание.
                            _df_fb = calculate_trend(df, atr_period=_tsl_atr_p, factor=_tsl_factor)
                            if len(_df_fb) > 0:
                                _fb_trend = int(_df_fb["trend"].iloc[-1])
                                if (direction == "LONG" and _fb_trend == 1) or \
                                   (direction == "SHORT" and _fb_trend == -1):
                                    df_tsl = _df_fb
                                else:
                                    logger.debug(
                                        "[TSL-DIRGUARD] %s %s: все TF против тренда → TSL пропущен",
                                        symbol, direction,
                                    )

                        trend_info = get_trend_info(df_tsl) if df_tsl is not None else None

                        if trend_info and trend_info["tsl"] > 0:
                            # DEV-191: брать trendup/trenddown по direction, не tsl.
                            # trend_info["tsl"] = trendup если trend=1, trenddown если trend=-1.
                            # При флипе тренда против позиции tsl возвращает неправильную линию
                            # → raw_tsl инвертирован → floor вынужден его исправлять каждый цикл.
                            _raw_tsl = (
                                trend_info["trendup"] if direction == "LONG"
                                else trend_info["trenddown"]
                            )
                            # DS-321: _use_hybrid defined at top of try block
                            # DS-321: гибридная коробка передач (откат через config)
                            _use_hybrid = bool(_cfg_trend.get("sl_tp_engine.tsl_hybrid_enabled", False))
                            if _use_hybrid:
                                from core.trading.tsl_engine import compute_hybrid_tsl as _compute_hybrid, TSL_PROFILES
                                _orig_sl = float(trade.get("original_sl", entry))
                                _age_m = (datetime.now(timezone.utc) - created_dt).total_seconds() / 60.0 if created_dt else 0
                                # TSL-PROFILE: per-strategy Gear-пороги
                                _sig_type = str(trade.get("signal_type", ""))
                                _profile = TSL_PROFILES.get(_sig_type, TSL_PROFILES["default"])
                                _decision = _compute_hybrid(
                                    direction,
                                    entry=entry,
                                    current_price=current_price,
                                    original_sl=_orig_sl,
                                    duration_minutes=_age_m,
                                    profile=_profile,
                                )
                            else:
                                _decision = _compute_tsl(
                                    direction,
                                    entry=entry,
                                    current_price=current_price,
                                    raw_tsl=_raw_tsl,
                                )
                            tsl_price = _decision.new_sl
                            tsl_triggered = _decision.triggered
                            # DS-321: пишем гибридный gear в tsl_tf для дашборда
                            if _use_hybrid and _decision.new_sl is not None:
                                tsl_tf_used = _decision.reason  # hybrid_gear1_mfe0.5atr

                            # DEV-221: OB return при де-эскалации → принудительное закрытие
                            if _ob_force_close and not tsl_triggered:
                                tsl_triggered = True
                                tsl_price = current_price
                                logger.info(
                                    "[DEV-221] %s #%d %s: OB return + gradient drop R=%.2f → force TSL close",
                                    symbol, trade_id, direction, current_r or 0,
                                )

                            # DEV-191: логируем инверсию raw_tsl (floored=True означает
                            # что trenddown/trendup оказался на неправильной стороне от цены)
                            if _decision.floored:
                                logger.warning(
                                    "[TSL-FLOOR] %s #%d %s: raw_tsl=%.6f floored -> sl=%.6f "
                                    "entry=%.6f current=%.6f reason=%s tf=%s",
                                    symbol, trade_id, direction,
                                    trend_info["tsl"], tsl_price,
                                    entry, current_price, _decision.reason,
                                    tsl_tf_used,
                                )

                            if tsl_triggered:
                                logger.info(
                                    f"TradeSimulator: TSL сработал для {symbol} {direction} "
                                    f"entry={entry:.4f} current={current_price:.4f} "
                                    f"tsl={tsl_price:.4f} [tf={tsl_tf_used}]"
                                )
                                if _exchange_managed_trade:
                                    _lg_key = f"{trade_id}_tsl"
                                    _lg_last = self._live_guard_logged.get(_lg_key)
                                    if _lg_last is None or (now - _lg_last).total_seconds() > 3600:
                                        logger.warning(
                                            "[TradeSimulator][LIVE-GUARD] %s #%d: TSL hit detected by simulator, "
                                            "but trade is exchange-managed — waiting for exchange confirmation",
                                            symbol, trade_id,
                                        )
                                        self._live_guard_logged[_lg_key] = now
                                    return (_ops05c, _ops05tsl)
                                if self.close_trade(trade_id, STATUS_TSL, current_price):
                                    _ops05c += 1
                                return (_ops05c, _ops05tsl)
                            else:
                                # TSL активен, не сработал — фиксируем движение SL.
                                # DEV-189 (12.05.2026): UPDATE stop_loss выполняется ВСЕГДА при
                                # реальном движении (≥0.15%), не только для биржевых сделок.
                                # До фикса: _is_real_move требовал exchange_order_id → SIM сделки
                                # не апдейтили БД (~80% случаев) → SL читался старый при следующем
                                # check_open_trades → закрытие по застывшему SL вместо реального TSL.
                                # Эффект на 12.05: wt_sideways sim avgR=-0.63 vs exchange +0.67 (Δ240R).
                                _exch_sl_id = trade.get("exchange_sl_order_id")
                                _old_sl = float(trade.get("stop_loss") or 0)
                                _exch_order_id = trade.get("exchange_order_id")
                                # Фильтр ≥0.15% — устраняет float-equality "движения" и повторный cancel+replace
                                # DEV-TSL-ONESIDED: TSL двигается только тесней (LONG: вверх, SHORT: вниз).
                                # Без is_tighter floor=current*1.003 поднимал SL вверх для SHORT при цене
                                # против позиции → stop_loss > entry → выход с гарантированным убытком.
                                _min_move = 0.15  # %
                                from core.trading.tsl_engine import is_tighter as _tsl_is_tighter_upd
                                _tighter = _old_sl <= 0 or _tsl_is_tighter_upd(direction, tsl_price, _old_sl)
                                _sl_changed = bool(
                                    tsl_price and _old_sl > 0
                                    and abs(tsl_price - _old_sl) / _old_sl * 100 >= _min_move
                                    and _tighter
                                )
                                # Биржевой cancel+replace только если есть биржевой ордер
                                _needs_exchange_update = _sl_changed and bool(_exch_order_id)

                                if _sl_changed:
                                    # 1) UPDATE stop_loss в БД — для SIM и для exchange (DEV-189 fix)
                                    try:
                                        with self._db_connect() as _tsl_conn:
                                            _tsl_conn.execute(
                                                "UPDATE simulated_trades SET stop_loss=? WHERE id=? AND status='OPEN'",
                                                (tsl_price, trade_id),
                                            )
                                            _tsl_conn.commit()
                                    except Exception as _ue:
                                        logger.debug("TSL: stop_loss update #%d: %s", trade_id, _ue)

                                    # 2) Publish TSL_MOVED — для аналитики (обе venue)
                                    _pcb = getattr(self, "_pair_context_bus", None)
                                    if _pcb is not None:
                                        try:
                                            from core.context.pair_context import SphereEvent
                                            _pcb.publish(symbol, SphereEvent.TSL_MOVED, {
                                                "trade_id": trade_id,
                                                "old_sl": _old_sl,
                                                "new_sl": tsl_price,
                                                "tf": tsl_tf or "15m",
                                            })
                                        except Exception:
                                            pass

                                if _needs_exchange_update:
                                    # 3) Биржевой cancel+replace SL-ордера (только для exchange-managed)
                                    _qty = float(trade.get("qty") or 0)
                                    _ops05tsl.append({
                                        "trade_id":            trade_id,
                                        "symbol":              symbol,
                                        "direction":           direction,
                                        "qty":                 _qty,
                                        "new_sl_price":        tsl_price,
                                        "old_sl_price":        _old_sl,
                                        "exchange_sl_order_id": _exch_sl_id,
                                        "exchange_order_id":   _exch_order_id,
                                    })

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
                # DEV-149: Для exchange-managed (VST) сделок всегда по wick (low/high),
                # т.к. биржевой STOP_MARKET срабатывает на wick, не на close.
                _sl_src = (trade.get("sl_source") or "").lower()
                _sl_check_close = (
                    (_sl_src.startswith("tsl_line") or _sl_src.startswith("wl_pivot_tsl"))
                    and not _exchange_managed_trade  # VST → wick, SIM → close
                )
                _tsl_is_active = bool(trade.get("tsl_activated"))

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
                                with self._db_connect() as _c:
                                    _c.execute(
                                        "UPDATE simulated_trades SET tp1_hit_at=? WHERE id=? AND status=?",
                                        (tp1_hit_at, trade_id, STATUS_OPEN),
                                    )
                                    _c.commit()
                            except Exception:
                                pass
                            logger.info("TradeSimulator: TP1 hit %s id=%d tp1=%.6f", symbol, trade_id, tp1_price)
                            # Куб: Сфера 10 → bus: TP1_HIT
                            _pcb = getattr(self, "_pair_context_bus", None)
                            if _pcb is not None:
                                try:
                                    from core.context.pair_context import SphereEvent
                                    _r_at_tp1 = (tp1_price - entry) / abs(entry - sl) if sl and entry != sl else 0
                                    _pcb.publish(symbol, SphereEvent.TP1_HIT, {
                                        "trade_id": trade_id, "r_at_tp1": round(abs(_r_at_tp1), 2),
                                    })
                                except Exception:
                                    pass
                        # TP2 — финальный выход для DUAL_TP (30.03.2026: добавлен exit_status)
                        if tp2_price and tp2_hit_at is None and tp1_hit_at and high >= tp2_price:
                            tp2_hit_at = datetime.now(timezone.utc).isoformat()
                            try:
                                with self._db_connect() as _c:
                                    _c.execute(
                                        "UPDATE simulated_trades SET tp2_hit_at=? WHERE id=? AND status=?",
                                        (tp2_hit_at, trade_id, STATUS_OPEN),
                                    )
                                    _c.commit()
                            except Exception:
                                pass
                            logger.info("TradeSimulator: TP2 hit %s id=%d tp2=%.6f", symbol, trade_id, tp2_price)
                            exit_status, exit_price_val = STATUS_TP, tp2_price
                        # Обычный TP (SINGLE — tp1/tp2 не используются)
                        # DEV-TSL-SUPREMACY: если TSL уже активен — фиксированный TP не режет ракету.
                        # TSL сам закроет сделку при развороте тренда.
                        hit_tp = (not _tsl_is_active and tp is not None and tp2_price is None and tp1_price is None and high >= tp)
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
                                with self._db_connect() as _c:
                                    _c.execute(
                                        "UPDATE simulated_trades SET tp1_hit_at=? WHERE id=? AND status=?",
                                        (tp1_hit_at, trade_id, STATUS_OPEN),
                                    )
                                    _c.commit()
                            except Exception:
                                pass
                            logger.info("TradeSimulator: TP1 hit %s id=%d tp1=%.6f", symbol, trade_id, tp1_price)
                        # TP2 — финальный выход для DUAL_TP (30.03.2026: добавлен exit_status)
                        if tp2_price and tp2_hit_at is None and tp1_hit_at and low <= tp2_price:
                            tp2_hit_at = datetime.now(timezone.utc).isoformat()
                            try:
                                with self._db_connect() as _c:
                                    _c.execute(
                                        "UPDATE simulated_trades SET tp2_hit_at=? WHERE id=? AND status=?",
                                        (tp2_hit_at, trade_id, STATUS_OPEN),
                                    )
                                    _c.commit()
                            except Exception:
                                pass
                            logger.info("TradeSimulator: TP2 hit %s id=%d tp2=%.6f", symbol, trade_id, tp2_price)
                            exit_status, exit_price_val = STATUS_TP, tp2_price
                        # DEV-TSL-SUPREMACY: если TSL уже активен — фиксированный TP не режет ракету.
                        hit_tp = (not _tsl_is_active and tp is not None and tp2_price is None and tp1_price is None and low <= tp)
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
                # DS-322: fallback — если OHLCV не дал данных, используем WS-цену
                if new_max is None and _ws_price is not None:
                    if direction == "LONG" and _ws_price > entry:
                        new_max = _ws_price
                    elif direction == "SHORT" and _ws_price < entry:
                        new_min = _ws_price

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
                        with self._db_connect() as conn:
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
                            # DS-322: запомнить что проверили эту сделку
                            self._repair_checked[trade_id] = _now_ts
                    except Exception as e:
                        logger.debug(f"TradeSimulator: MFE update error {trade_id} — {e}")


                if exit_status and exit_price_val is not None:
                    # Переклассификация SL→TSL ОБЩАЯ (до exchange-managed И SIM): SL после движения
                    # TSL = TSL-exit (SL сдвинут выше entry). Критерий: original_sl != stop_loss.
                    # Без неё прибыльные TSL-выходы (R>0) маскируются под SL — в т.ч. при force-close.
                    if exit_status == STATUS_SL:
                        _orig_sl_classify = trade.get("original_sl")
                        _curr_sl_classify = float(trade.get("stop_loss") or 0)
                        _sl_moved = (
                            _orig_sl_classify is not None
                            and _curr_sl_classify > 0
                            and abs(_curr_sl_classify - float(_orig_sl_classify)) / float(_orig_sl_classify) > 0.0001
                        )
                        if _sl_moved:
                            exit_status = STATUS_TSL
                            logger.info(
                                "[TSL-SIM] #%d %s %s: SL→TSL (orig_sl=%.6f → curr_sl=%.6f)",
                                trade_id, symbol, direction,
                                float(_orig_sl_classify), _curr_sl_classify,
                            )
                    if _exchange_managed_trade:
                        _lg_key = f"{trade_id}_exit"
                        # OPS-06: симулятор детектит exit, но сделка exchange-managed. НЕ закрываем БД
                        # сами — force-close в симуляторе создаёт orphan, если биржа держит позицию
                        # (симулятор не знает состояния биржи). Разбор orphan-зависания перенесён в
                        # position_sync (есть open_on_exchange → различить «биржа закрыла» vs «держит»:
                        # закрыла→close БД; держит→emergency close позиции + close БД). Здесь — только
                        # трекинг времени детекта + лог для диагностики/position_sync.
                        _first = self._live_guard_first_detect.get(_lg_key)
                        if _first is None:
                            self._live_guard_first_detect[_lg_key] = now
                            _first = now
                        _waited_s = (now - _first).total_seconds()
                        _lg_last = self._live_guard_logged.get(_lg_key)
                        if _lg_last is None or (now - _lg_last).total_seconds() > 3600:
                            logger.warning(
                                "[TradeSimulator][LIVE-GUARD] %s #%d: %s detected @ %.6f, exchange-managed "
                                "— ждём sync/биржу (%.0f мин), разбор в position_sync",
                                symbol, trade_id, exit_status, exit_price_val, _waited_s / 60,
                            )
                            self._live_guard_logged[_lg_key] = now
                        return (_ops05c, _ops05tsl)
                    if self.close_trade(trade_id, exit_status, exit_price_val):
                        _ops05c += 1
                        # DEV-15: LLM-разбор для SL-сделок
                        if exit_status == STATUS_SL:
                            analyzer = self._get_trade_analyzer()
                            if analyzer is not None:
                                import asyncio
                                asyncio.create_task(analyzer.analyze_sl_trade(trade_id))

                return (_ops05c, _ops05tsl)

        _results = await asyncio.gather(*[_proc(t) for t in open_trades], return_exceptions=True)
        for _r in _results:
            if isinstance(_r, tuple):
                closed_count += _r[0]; tsl_moved.extend(_r[1])
            elif isinstance(_r, Exception):
                logger.error('[OPS-05] _proc error: %s', _r)
        return closed_count, tsl_moved
