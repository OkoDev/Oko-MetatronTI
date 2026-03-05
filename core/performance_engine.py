"""
Performance Engine — агрегирует статистику из simulated_trades для дашборда.
Читает только из БД, не пишет ничего.
"""
import sqlite3
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _row_to_dict(cursor: sqlite3.Cursor, rows) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


class PerformanceEngine:
    def __init__(self, db_path: str = "subscriptions.db"):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Сводная статистика
    # ------------------------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        """Общая сводка: всего сделок, win-rate, avg R, avg profit_pct."""
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='OPEN'    THEN 1 ELSE 0 END) AS open_count,
                        SUM(CASE WHEN status='TP'      THEN 1 ELSE 0 END) AS tp_count,
                        SUM(CASE WHEN status='SL'      THEN 1 ELSE 0 END) AS sl_count,
                        SUM(CASE WHEN status='EXPIRED' THEN 1 ELSE 0 END) AS expired_count,
                        AVG(CASE WHEN status IN ('TP','SL','EXPIRED') THEN profit_pct END) AS avg_profit_pct,
                        AVG(CASE WHEN status IN ('TP','SL','EXPIRED') THEN R_multiple END) AS avg_r,
                        AVG(CASE WHEN status='TP' THEN R_multiple END) AS avg_r_win,
                        AVG(CASE WHEN status='SL' THEN R_multiple END) AS avg_r_loss
                    FROM simulated_trades
                """)
                row = dict(cur.fetchone())
                closed = (row["tp_count"] or 0) + (row["sl_count"] or 0)
                row["win_rate"] = round(row["tp_count"] / closed * 100, 1) if closed else None
                row["closed_count"] = closed
                for k in ("avg_profit_pct", "avg_r", "avg_r_win", "avg_r_loss"):
                    if row[k] is not None:
                        row[k] = round(row[k], 3)
                return row
        except Exception as e:
            logger.exception("PerformanceEngine.summary: %s", e)
            return {}

    # ------------------------------------------------------------------
    # По типу сигнала
    # ------------------------------------------------------------------
    def by_signal_type(self) -> List[Dict[str, Any]]:
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT
                        signal_type,
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='TP' THEN 1 ELSE 0 END) AS wins,
                        SUM(CASE WHEN status='SL' THEN 1 ELSE 0 END) AS losses,
                        AVG(CASE WHEN status IN ('TP','SL','EXPIRED') THEN profit_pct END) AS avg_profit_pct,
                        AVG(CASE WHEN status IN ('TP','SL','EXPIRED') THEN R_multiple END) AS avg_r
                    FROM simulated_trades
                    GROUP BY signal_type
                    ORDER BY total DESC
                """)
                rows = cur.fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    closed = (d["wins"] or 0) + (d["losses"] or 0)
                    d["win_rate"] = round(d["wins"] / closed * 100, 1) if closed else None
                    if d["avg_profit_pct"] is not None:
                        d["avg_profit_pct"] = round(d["avg_profit_pct"], 3)
                    if d["avg_r"] is not None:
                        d["avg_r"] = round(d["avg_r"], 3)
                    result.append(d)
                return result
        except Exception as e:
            logger.exception("PerformanceEngine.by_signal_type: %s", e)
            return []

    # ------------------------------------------------------------------
    # По направлению (LONG / SHORT)
    # ------------------------------------------------------------------
    def by_direction(self) -> List[Dict[str, Any]]:
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT
                        direction,
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='TP' THEN 1 ELSE 0 END) AS wins,
                        SUM(CASE WHEN status='SL' THEN 1 ELSE 0 END) AS losses,
                        AVG(CASE WHEN status IN ('TP','SL','EXPIRED') THEN profit_pct END) AS avg_profit_pct,
                        AVG(CASE WHEN status IN ('TP','SL','EXPIRED') THEN R_multiple END) AS avg_r
                    FROM simulated_trades
                    GROUP BY direction
                """)
                rows = cur.fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    closed = (d["wins"] or 0) + (d["losses"] or 0)
                    d["win_rate"] = round(d["wins"] / closed * 100, 1) if closed else None
                    if d["avg_profit_pct"] is not None:
                        d["avg_profit_pct"] = round(d["avg_profit_pct"], 3)
                    if d["avg_r"] is not None:
                        d["avg_r"] = round(d["avg_r"], 3)
                    result.append(d)
                return result
        except Exception as e:
            logger.exception("PerformanceEngine.by_direction: %s", e)
            return []

    # ------------------------------------------------------------------
    # По режиму рынка (если заполнен)
    # ------------------------------------------------------------------
    def by_regime(self) -> List[Dict[str, Any]]:
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT
                        COALESCE(regime, 'unknown') AS regime,
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='TP' THEN 1 ELSE 0 END) AS wins,
                        SUM(CASE WHEN status='SL' THEN 1 ELSE 0 END) AS losses,
                        AVG(CASE WHEN status IN ('TP','SL','EXPIRED') THEN profit_pct END) AS avg_profit_pct,
                        AVG(CASE WHEN status IN ('TP','SL','EXPIRED') THEN R_multiple END) AS avg_r
                    FROM simulated_trades
                    GROUP BY regime
                    ORDER BY total DESC
                """)
                rows = cur.fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    closed = (d["wins"] or 0) + (d["losses"] or 0)
                    d["win_rate"] = round(d["wins"] / closed * 100, 1) if closed else None
                    if d["avg_profit_pct"] is not None:
                        d["avg_profit_pct"] = round(d["avg_profit_pct"], 3)
                    if d["avg_r"] is not None:
                        d["avg_r"] = round(d["avg_r"], 3)
                    result.append(d)
                return result
        except Exception as e:
            logger.exception("PerformanceEngine.by_regime: %s", e)
            return []

    # ------------------------------------------------------------------
    # Последние N закрытых сделок
    # ------------------------------------------------------------------
    def recent_closed(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, symbol, direction, signal_type, regime,
                           entry_price, exit_price, profit_pct, R_multiple,
                           status, created_at, closed_at, duration_minutes
                    FROM simulated_trades
                    WHERE status != 'OPEN'
                    ORDER BY closed_at DESC
                    LIMIT ?
                """, (limit,))
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.exception("PerformanceEngine.recent_closed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Открытые сделки
    # ------------------------------------------------------------------
    def open_trades(self) -> List[Dict[str, Any]]:
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, symbol, direction, signal_type, regime,
                           entry_price, stop_loss, take_profit,
                           strength, confidence, created_at
                    FROM simulated_trades
                    WHERE status = 'OPEN'
                    ORDER BY created_at DESC
                """)
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.exception("PerformanceEngine.open_trades: %s", e)
            return []

    # ------------------------------------------------------------------
    # История по конкретному символу
    # ------------------------------------------------------------------
    def pair_history(self, symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Последние закрытые сделки по символу."""
        try:
            with self._conn() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("""
                    SELECT signal_type, direction, status, R_multiple, profit_pct, closed_at
                    FROM simulated_trades
                    WHERE symbol = ? AND status != 'OPEN'
                    ORDER BY closed_at DESC
                    LIMIT ?
                """, (symbol, limit))
                return [dict(r) for r in cur.fetchall()]
        except Exception:
            logger.exception("pair_history %s", symbol)
            return []

    # ------------------------------------------------------------------
    # Всё одним вызовом (для /api/stats)
    # ------------------------------------------------------------------
    def full_stats(self) -> Dict[str, Any]:
        return {
            "summary": self.summary(),
            "by_signal_type": self.by_signal_type(),
            "by_direction": self.by_direction(),
            "by_regime": self.by_regime(),
            "recent_closed": self.recent_closed(20),
            "open_trades": self.open_trades(),
        }
