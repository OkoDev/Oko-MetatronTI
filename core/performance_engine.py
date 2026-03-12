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
        """Общая сводка: всего сделок, win-rate, avg R, avg profit_pct.

        Win Rate: TP + TSL считаются победами (TSL активируется после +1R, R всегда > 0).
        avg_r_loss: только SL (TSL — не потеря).
        """
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='OPEN'    THEN 1 ELSE 0 END) AS open_count,
                        SUM(CASE WHEN status='TP'      THEN 1 ELSE 0 END) AS tp_count,
                        SUM(CASE WHEN status='SL'      THEN 1 ELSE 0 END) AS sl_count,
                        SUM(CASE WHEN status='TSL'     THEN 1 ELSE 0 END) AS tsl_count,
                        SUM(CASE WHEN status='EXPIRED' THEN 1 ELSE 0 END) AS expired_count,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN profit_pct END) AS avg_profit_pct,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN R_multiple END) AS avg_r,
                        AVG(CASE WHEN status IN ('TP','TSL') THEN R_multiple END) AS avg_r_win,
                        AVG(CASE WHEN status='SL' THEN R_multiple END) AS avg_r_loss,
                        AVG(CASE WHEN status='TSL' THEN R_multiple END) AS avg_r_tsl,
                        MIN(created_at) AS first_trade_at,
                        MAX(created_at) AS last_trade_at
                    FROM simulated_trades
                """)
                row = dict(cur.fetchone())
                tp = row["tp_count"] or 0
                sl = row["sl_count"] or 0
                tsl = row["tsl_count"] or 0
                closed = tp + sl + tsl
                # TSL = Win (активируется только после +1R)
                row["win_rate"] = round((tp + tsl) / closed * 100, 1) if closed else None
                row["win_rate_tp_only"] = round(tp / closed * 100, 1) if closed else None
                row["closed_count"] = closed
                for k in ("avg_profit_pct", "avg_r", "avg_r_win", "avg_r_loss", "avg_r_tsl"):
                    if row[k] is not None:
                        row[k] = round(row[k], 3)
                # Активных дней и сделок в день (по закрытым)
                try:
                    from datetime import datetime as _dt
                    if row.get("first_trade_at") and row.get("last_trade_at"):
                        t0 = _dt.fromisoformat(row["first_trade_at"])
                        t1 = _dt.fromisoformat(row["last_trade_at"])
                        days = max((t1 - t0).days, 1)
                        row["days_active"] = days
                        row["closed_per_day"] = round(closed / days, 1) if closed else 0
                    else:
                        row["days_active"] = None
                        row["closed_per_day"] = None
                except Exception:
                    row["days_active"] = None
                    row["closed_per_day"] = None
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
                        SUM(CASE WHEN status='TP'  THEN 1 ELSE 0 END) AS tp_count,
                        SUM(CASE WHEN status='TSL' THEN 1 ELSE 0 END) AS tsl_count,
                        SUM(CASE WHEN status='SL'  THEN 1 ELSE 0 END) AS sl_count,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN profit_pct END) AS avg_profit_pct,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN R_multiple END) AS avg_r
                    FROM simulated_trades
                    GROUP BY signal_type
                    ORDER BY total DESC
                """)
                rows = cur.fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    tp = d["tp_count"] or 0
                    tsl = d["tsl_count"] or 0
                    sl = d["sl_count"] or 0
                    closed = tp + tsl + sl
                    d["wins"] = tp + tsl
                    d["losses"] = sl
                    d["win_rate"] = round((tp + tsl) / closed * 100, 1) if closed else None
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
                        SUM(CASE WHEN status='TP'  THEN 1 ELSE 0 END) AS tp_count,
                        SUM(CASE WHEN status='TSL' THEN 1 ELSE 0 END) AS tsl_count,
                        SUM(CASE WHEN status='SL'  THEN 1 ELSE 0 END) AS sl_count,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN profit_pct END) AS avg_profit_pct,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN R_multiple END) AS avg_r
                    FROM simulated_trades
                    GROUP BY direction
                """)
                rows = cur.fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    tp = d["tp_count"] or 0
                    tsl = d["tsl_count"] or 0
                    sl = d["sl_count"] or 0
                    closed = tp + tsl + sl
                    d["wins"] = tp + tsl
                    d["losses"] = sl
                    d["win_rate"] = round((tp + tsl) / closed * 100, 1) if closed else None
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
                        SUM(CASE WHEN status='TP'  THEN 1 ELSE 0 END) AS tp_count,
                        SUM(CASE WHEN status='TSL' THEN 1 ELSE 0 END) AS tsl_count,
                        SUM(CASE WHEN status='SL'  THEN 1 ELSE 0 END) AS sl_count,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN profit_pct END) AS avg_profit_pct,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN R_multiple END) AS avg_r
                    FROM simulated_trades
                    GROUP BY regime
                    ORDER BY total DESC
                """)
                rows = cur.fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    tp = d["tp_count"] or 0
                    tsl = d["tsl_count"] or 0
                    sl = d["sl_count"] or 0
                    closed = tp + tsl + sl
                    d["wins"] = tp + tsl
                    d["losses"] = sl
                    d["win_rate"] = round((tp + tsl) / closed * 100, 1) if closed else None
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
                           status, created_at, closed_at, duration_minutes,
                           max_R_possible, captured_R_pct,
                           sl_source, tp_source
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
                           strength, confidence, created_at,
                           tsl_activated,
                           tp1_price, tp1_hit_at,
                           tp2_price, tp2_hit_at,
                           tp3_price, tp3_hit_at
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
    # Статистика за период (для еженедельного отчёта)
    # ------------------------------------------------------------------
    def weekly_summary(self, days_back: int = 7) -> Dict[str, Any]:
        """Статистика за последние N дней.
        Фикс: win_rate делится на closed (TP+TSL+SL), не на total (включал OPEN).
        TSL = Win.
        """
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cutoff = f"datetime('now', '-{days_back} days')"
                row = cur.execute(f"""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status='TP'  THEN 1 ELSE 0 END) as tp_count,
                        SUM(CASE WHEN status='TSL' THEN 1 ELSE 0 END) as tsl_count,
                        SUM(CASE WHEN status='SL'  THEN 1 ELSE 0 END) as sl_count,
                        AVG(CASE WHEN status IN ('TP','SL','TSL') THEN R_multiple END) as avg_r,
                        MAX(CASE WHEN status IN ('TP','SL','TSL') THEN R_multiple END) as best_r
                    FROM simulated_trades WHERE closed_at >= {cutoff}
                """).fetchone()
                by_type = cur.execute(f"""
                    SELECT signal_type,
                           COUNT(*) as cnt,
                           SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END) as wins,
                           AVG(CASE WHEN status IN ('TP','SL','TSL') THEN R_multiple END) as avg_r
                    FROM simulated_trades WHERE closed_at >= {cutoff}
                    GROUP BY signal_type ORDER BY avg_r DESC
                """).fetchall()
                tp = row[1] or 0
                tsl = row[2] or 0
                sl = row[3] or 0
                closed = tp + tsl + sl
                return {
                    "total": row[0] or 0,
                    "wins": tp + tsl,
                    "losses": sl,
                    "tsl_count": tsl,
                    "closed": closed,
                    "win_rate": round((tp + tsl) / closed * 100, 1) if closed else 0,
                    "avg_r": round(row[4] or 0, 2),
                    "best_r": round(row[5] or 0, 2),
                    "by_signal_type": [
                        {"signal_type": r[0], "cnt": r[1], "wins": r[2], "avg_r": round(r[3] or 0, 2)}
                        for r in by_type
                    ],
                }
        except Exception as e:
            logger.exception("PerformanceEngine.weekly_summary: %s", e)
            return {"total": 0, "wins": 0, "losses": 0, "tsl_count": 0, "closed": 0, "win_rate": 0, "avg_r": 0, "best_r": 0, "by_signal_type": []}

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
