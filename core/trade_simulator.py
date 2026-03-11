"""
Trade Simulator — отслеживание исходов симулированных сделок по SL/TP.
Этап 1 ROADMAP: closed-loop основа для адаптации весов и ML.
"""
import sqlite3
import pandas as pd
import logging
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Статусы сделки
STATUS_OPEN = "OPEN"
STATUS_TP = "TP"
STATUS_SL = "SL"
STATUS_TSL = "TSL"
STATUS_EXPIRED = "EXPIRED"

# Дефолты
DEFAULT_TIMEFRAME = "15m"
MAX_DURATION_MINUTES = 48 * 60  # 48 часов — затем EXPIRED


def _get_recommendation_value(rec: Any, attr: str, default=None):
    """Безопасное получение атрибута рекомендации (без жёсткой зависимости от типа)."""
    return getattr(rec, attr, default) if rec else default


def _direction_str(direction) -> str:
    if hasattr(direction, "value"):
        return str(direction.value)
    return str(direction) if direction else "NEUTRAL"


def _signal_type_from_recommendation(rec: Any) -> str:
    """Доминирующий тип сигнала из supporting_signals или 'composite'."""
    supporting = _get_recommendation_value(rec, "supporting_signals") or []
    if not supporting:
        return "composite"
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
                    captured_R_pct REAL
                )
            """)
            # Миграция для существующих БД
            for col, coldef in [("tp1_price", "REAL"), ("tp1_hit_at", "TIMESTAMP")]:
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
            strength = _get_recommendation_value(recommendation, "overall_strength")
            confidence = _get_recommendation_value(recommendation, "confidence")
            ts = _get_recommendation_value(recommendation, "timestamp") or datetime.now(timezone.utc)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            signal_type = _signal_type_from_recommendation(recommendation)
            sl_source = _get_recommendation_value(recommendation, "sl_source") or None
            tp_source = _get_recommendation_value(recommendation, "tp_source") or None
            # Сохраняем ВСЕ поддерживающие типы сигналов
            supporting = _get_recommendation_value(recommendation, "supporting_signals") or []
            all_signal_types = list(dict.fromkeys(
                s.signal_type.value for s in supporting
                if hasattr(s, "signal_type") and hasattr(s.signal_type, "value")
            ))
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
            features_json = json.dumps(features) if features else None

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO simulated_trades
                    (symbol, timeframe, signal_type, direction, entry_price, stop_loss, take_profit,
                     tp1_price, strength, confidence, regime, status, features_json, created_at,
                     sl_source, tp_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        DEFAULT_TIMEFRAME,
                        signal_type,
                        _direction_str(direction),
                        float(entry),
                        float(stop_loss) if stop_loss is not None else None,
                        float(take_profit) if take_profit is not None else None,
                        float(tp1_price) if tp1_price is not None else None,
                        int(strength) if strength is not None else None,
                        float(confidence) if confidence is not None else None,
                        regime,
                        STATUS_OPEN,
                        features_json,
                        ts.isoformat(),
                        sl_source,
                        tp_source,
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
        regime: Optional[str] = None
        if data_collector is not None:
            symbol = _get_recommendation_value(recommendation, "symbol") or ""
            if symbol:
                try:
                    from core.market_regime import MarketRegimeClassifier
                    ohlcv = await data_collector.get_ohlcv(symbol, DEFAULT_TIMEFRAME, 50)
                    if ohlcv:
                        regime = MarketRegimeClassifier().classify_from_ohlcv(ohlcv)
                        logger.debug("MarketRegime для %s: %s", symbol, regime)
                except Exception as e:
                    logger.debug("MarketRegime: не удалось определить для %s — %s", symbol, e)
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

                # duration_minutes
                try:
                    if isinstance(created_at, str):
                        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    else:
                        created_dt = created_at
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    duration_minutes = (closed_at - created_dt).total_seconds() / 60.0
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
            return True
        except Exception as e:
            logger.exception(f"TradeSimulator: ошибка close_trade {trade_id} — {e}")
            return False

    async def check_open_trades_with_tsl(self, data_collector: Any, use_tsl: bool = True, tsl_activation_r: float = 1.0) -> int:
        """
        Проверяет открытые сделки с поддержкой TSL (Trailing Stop Loss).
        TSL активируется после достижения tsl_activation_r прибыли.

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
            tp1_price = trade.get("tp1_price")
            tp1_hit_at = trade.get("tp1_hit_at")
            if sl is not None:
                sl = float(sl)
            if tp is not None:
                tp = float(tp)
            if tp1_price is not None:
                tp1_price = float(tp1_price)

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
            if age_minutes >= self.max_duration_minutes:
                # EXPIRED — закрываем по текущей цене
                try:
                    ticker = await data_collector.get_ticker(symbol)
                    if ticker:
                        last = float(ticker.get("last") or ticker.get("close") or entry)
                        if self.close_trade(trade_id, STATUS_EXPIRED, last):
                            closed_count += 1
                except Exception as e:
                    logger.debug(f"TradeSimulator: EXPIRED get_ticker {symbol} — {e}")
                continue

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
                    df = df[df["time"] >= ts_sec * 1000].copy()
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

            # TSL логика
            tsl_triggered = False
            tsl_price = None

            if use_tsl and current_r is not None and current_r >= tsl_activation_r:
                # Активируем TSL после достижения прибыли
                try:
                    from core.indicators import calculate_trend, get_trend_info
                    df_with_trend = calculate_trend(df)
                    trend_info = get_trend_info(df_with_trend)

                    if trend_info and trend_info["tsl"] > 0:
                        tsl_price = trend_info["tsl"]

                        # Проверка срабатывания TSL
                        if direction == "LONG" and current_price <= tsl_price:
                            tsl_triggered = True
                        elif direction == "SHORT" and current_price >= tsl_price:
                            tsl_triggered = True

                        if tsl_triggered:
                            logger.info(f"TradeSimulator: TSL сработал для {symbol} {direction} "
                                      f"entry={entry:.4f} current={current_price:.4f} tsl={tsl_price:.4f}")
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

            for _, row in df.iterrows():
                high = float(row.get("high", 0) or 0)
                low  = float(row.get("low",  0) or 0)
                open_ = float(row.get("open", 0) or 0)

                if high > 0:
                    max_high = max(max_high, high)
                if low > 0:
                    min_low = min(min_low, low)

                if direction == "LONG":
                    hit_sl  = sl  is not None and low  <= sl
                    # TP1 фиксирует 50% — только если ещё не сработал
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
                        logger.info("TradeSimulator: TP1 hit (50%%) %s id=%d tp1=%.6f", symbol, trade_id, tp1_price)
                    # После TP1: только SL (TSL уже обработан выше)
                    hit_tp = (tp is not None and tp1_hit_at is None and high >= tp)
                    if hit_sl and hit_tp:
                        exit_status, exit_price_val = (STATUS_SL, sl) if (open_ - sl <= tp - open_) else (STATUS_TP, tp)
                    elif hit_sl:
                        exit_status, exit_price_val = STATUS_SL, sl
                    elif hit_tp:
                        exit_status, exit_price_val = STATUS_TP, tp
                else:  # SHORT
                    hit_sl  = sl is not None and high >= sl
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
                        logger.info("TradeSimulator: TP1 hit (50%%) %s id=%d tp1=%.6f", symbol, trade_id, tp1_price)
                    hit_tp = (tp is not None and tp1_hit_at is None and low <= tp)
                    if hit_sl and hit_tp:
                        exit_status, exit_price_val = (STATUS_SL, sl) if (sl - open_ <= open_ - tp) else (STATUS_TP, tp)
                    elif hit_sl:
                        exit_status, exit_price_val = STATUS_SL, sl
                    elif hit_tp:
                        exit_status, exit_price_val = STATUS_TP, tp
                if exit_status:
                    break

            # Обновляем MFE экстремумы для открытой сделки
            new_max = max_high if max_high > 0 else None
            new_min = min_low if min_low < float("inf") else None
            if new_max is not None or new_min is not None:
                try:
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute(
                            "UPDATE simulated_trades SET max_price=?, min_price=? WHERE id=? AND status=?",
                            (new_max, new_min, trade_id, STATUS_OPEN),
                        )
                        conn.commit()
                except Exception as e:
                    logger.debug(f"TradeSimulator: MFE update error {trade_id} — {e}")

            if exit_status and exit_price_val is not None:
                if self.close_trade(trade_id, exit_status, exit_price_val):
                    closed_count += 1

        return closed_count
