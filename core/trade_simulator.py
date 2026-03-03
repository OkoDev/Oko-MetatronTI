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

    def register_trade(self, recommendation: Any) -> Optional[int]:
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

            stop_loss = _get_recommendation_value(recommendation, "stop_loss")
            take_profit = _get_recommendation_value(recommendation, "take_profit")
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
            features = {}
            if ctx:
                features["volume_24h"] = getattr(ctx, "volume_24h", None)
                features["price_change_24h"] = getattr(ctx, "price_change_24h", None)
                features["volatility"] = getattr(ctx, "volatility", None)
            features_json = json.dumps(features) if features else None

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO simulated_trades
                    (symbol, timeframe, signal_type, direction, entry_price, stop_loss, take_profit,
                     strength, confidence, regime, status, features_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        DEFAULT_TIMEFRAME,
                        signal_type,
                        _direction_str(direction),
                        float(entry),
                        float(stop_loss) if stop_loss is not None else None,
                        float(take_profit) if take_profit is not None else None,
                        int(strength) if strength is not None else None,
                        float(confidence) if confidence is not None else None,
                        None,  # regime — позже
                        STATUS_OPEN,
                        features_json,
                        ts.isoformat(),
                    ),
                )
                trade_id = cursor.lastrowid
                conn.commit()
            logger.info(f"TradeSimulator: зарегистрирована сделка id={trade_id} {symbol} {_direction_str(direction)}")
            return trade_id
        except Exception as e:
            logger.exception(f"TradeSimulator: ошибка регистрации сделки — {e}")
            return None

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
        if status not in (STATUS_TP, STATUS_SL, STATUS_EXPIRED):
            return False
        closed_at = closed_at or datetime.now(timezone.utc)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT entry_price, stop_loss, take_profit, direction, created_at FROM simulated_trades WHERE id = ? AND status = ?",
                    (trade_id, STATUS_OPEN),
                )
                row = cursor.fetchone()
                if not row:
                    return False
                entry, sl, tp, direction, created_at = row
                entry = float(entry)
                sl = float(sl) if sl is not None else None
                tp = float(tp) if tp is not None else None

                # profit_pct
                if str(direction).upper() == "LONG":
                    profit_pct = (exit_price - entry) / entry * 100.0
                else:
                    profit_pct = (entry - exit_price) / entry * 100.0

                # R-multiple: 1R = |entry - stop_loss|
                if sl is not None and sl != entry:
                    one_r = abs(entry - sl)
                    if str(direction).upper() == "LONG":
                        r_multiple = (exit_price - entry) / one_r
                    else:
                        r_multiple = (entry - exit_price) / one_r
                else:
                    r_multiple = None

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
                    SET status = ?, exit_price = ?, profit_pct = ?, R_multiple = ?, closed_at = ?, duration_minutes = ?
                    WHERE id = ?
                    """,
                    (status, exit_price, profit_pct, r_multiple, closed_at.isoformat(), duration_minutes, trade_id),
                )
                conn.commit()
            logger.info(f"TradeSimulator: закрыта сделка id={trade_id} {status} exit={exit_price:.4f} R={r_multiple}")
            return True
        except Exception as e:
            logger.exception(f"TradeSimulator: ошибка close_trade {trade_id} — {e}")
            return False

    async def check_open_trades(self, data_collector: Any) -> int:
        """
        Проверяет открытые сделки по OHLC: hit SL, hit TP или EXPIRED.
        data_collector должен иметь метод get_ohlcv(symbol, timeframe, limit).
        Возвращает количество закрытых сделок.
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
            if sl is not None:
                sl = float(sl)
            if tp is not None:
                tp = float(tp)
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

            exit_status = None
            exit_price_val = None
            for _, row in df.iterrows():
                high = float(row.get("high", 0) or 0)
                low = float(row.get("low", 0) or 0)
                open_ = float(row.get("open", 0) or 0)
                if direction == "LONG":
                    hit_sl = sl is not None and low <= sl
                    hit_tp = tp is not None and high >= tp
                    if hit_sl and hit_tp:
                        # Оба в одной свече — какой ближе к open
                        if open_ - sl <= tp - open_:
                            exit_status, exit_price_val = STATUS_SL, sl
                        else:
                            exit_status, exit_price_val = STATUS_TP, tp
                    elif hit_sl:
                        exit_status, exit_price_val = STATUS_SL, sl
                    elif hit_tp:
                        exit_status, exit_price_val = STATUS_TP, tp
                else:  # SHORT
                    hit_sl = sl is not None and high >= sl
                    hit_tp = tp is not None and low <= tp
                    if hit_sl and hit_tp:
                        if sl - open_ <= open_ - tp:
                            exit_status, exit_price_val = STATUS_SL, sl
                        else:
                            exit_status, exit_price_val = STATUS_TP, tp
                    elif hit_sl:
                        exit_status, exit_price_val = STATUS_SL, sl
                    elif hit_tp:
                        exit_status, exit_price_val = STATUS_TP, tp
                if exit_status:
                    break

            if exit_status and exit_price_val is not None:
                if self.close_trade(trade_id, exit_status, exit_price_val):
                    closed_count += 1
        return closed_count
