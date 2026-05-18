"""
Performance Engine — агрегирует статистику из simulated_trades для дашборда.
Читает только из БД, не пишет ничего.

DEV-190 (26.04.2026): WR/avgR метрики используют effective_status helper.
Скрытые TSL exits (status='SL' + tsl_act=1 + R>0.1, для VST) учитываются как wins.
Без этого VST метрики занижают TSL effectiveness в 30 раз (8/1740 vs 32% реальных).
Совместимость: добавлены *_raw поля со старым расчётом для контроля.
Откат: trading.effective_status_enabled: false (но raw по-прежнему работает).
"""
import sqlite3
import logging
from typing import Any, Dict, List, Optional

from core.trading.effective_status import SQL_IS_WIN_CASE

logger = logging.getLogger(__name__)


def _row_to_dict(cursor: sqlite3.Cursor, rows) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


class PerformanceEngine:
    def __init__(self, db_path: str = "subscriptions.db"):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout=10000")  # DEV-148
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
                # DEV-190: effective_status — скрытые TSL exits VST учитываются как wins
                cur.execute(f"""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='OPEN'    THEN 1 ELSE 0 END) AS open_count,
                        SUM(CASE WHEN status='TP'      THEN 1 ELSE 0 END) AS tp_count,
                        SUM(CASE WHEN status='SL'      THEN 1 ELSE 0 END) AS sl_count,
                        SUM(CASE WHEN status='TSL'     THEN 1 ELSE 0 END) AS tsl_count,
                        SUM(CASE WHEN status='EXPIRED' THEN 1 ELSE 0 END) AS expired_count,
                        SUM(CASE WHEN status='SL' AND tsl_activated=1 AND R_multiple > 0.10 THEN 1 ELSE 0 END) AS tsl_hidden_count,
                        SUM({SQL_IS_WIN_CASE}) AS eff_wins,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN profit_pct END) AS avg_profit_pct,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN R_multiple END) AS avg_r,
                        AVG(CASE WHEN {SQL_IS_WIN_CASE} = 1 THEN R_multiple END) AS avg_r_win,
                        AVG(CASE WHEN status='SL' AND NOT (tsl_activated=1 AND R_multiple > 0.10) THEN R_multiple END) AS avg_r_loss,
                        AVG(CASE WHEN status='TSL' OR (status='SL' AND tsl_activated=1 AND R_multiple > 0.10) THEN R_multiple END) AS avg_r_tsl,
                        MIN(created_at) AS first_trade_at,
                        MAX(created_at) AS last_trade_at
                    FROM simulated_trades
                """)
                row = dict(cur.fetchone())
                tp = row["tp_count"] or 0
                sl = row["sl_count"] or 0
                tsl = row["tsl_count"] or 0
                hidden = row["tsl_hidden_count"] or 0
                eff_wins = row["eff_wins"] or 0
                closed = tp + sl + tsl
                # DEV-190: WR с учётом скрытых TSL exits (главная метрика)
                row["win_rate"] = round(eff_wins / closed * 100, 1) if closed else None
                row["win_rate_raw"] = round((tp + tsl) / closed * 100, 1) if closed else None  # старый расчёт для контроля
                row["win_rate_tp_only"] = round(tp / closed * 100, 1) if closed else None
                row["closed_count"] = closed
                # tsl_count теперь = native + hidden (для дашборда)
                row["tsl_count_effective"] = tsl + hidden
                row["tsl_count_native"] = tsl
                row["tsl_count_hidden"] = hidden
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
        # DEV-190: WR/wins/losses учитывают скрытые TSL exits (status='SL'+tsl_act=1+R>0.1)
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT
                        signal_type,
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='TP'  THEN 1 ELSE 0 END) AS tp_count,
                        SUM(CASE WHEN status='TSL' THEN 1 ELSE 0 END) AS tsl_count,
                        SUM(CASE WHEN status='SL'  THEN 1 ELSE 0 END) AS sl_count,
                        SUM(CASE WHEN status='SL' AND tsl_activated=1 AND R_multiple > 0.10 THEN 1 ELSE 0 END) AS tsl_hidden_count,
                        SUM({SQL_IS_WIN_CASE}) AS eff_wins,
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
                    hidden = d["tsl_hidden_count"] or 0
                    eff_wins = d["eff_wins"] or 0
                    closed = tp + tsl + sl
                    # DEV-190: wins / win_rate с учётом скрытых TSL
                    d["wins"] = eff_wins
                    d["losses"] = closed - eff_wins  # SL_clean + SL_slipped + BE_area (без exit_OK)
                    d["win_rate"] = round(eff_wins / closed * 100, 1) if closed else None
                    d["win_rate_raw"] = round((tp + tsl) / closed * 100, 1) if closed else None
                    d["tsl_hidden_count"] = hidden
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
    # DEV-177: EMA по хронологии закрытия (реактивное обучение весов)
    # ------------------------------------------------------------------
    def by_signal_type_ema(
        self,
        half_life: float = 50.0,
        data_era: Optional[str] = "post_fix",
    ) -> List[Dict[str, Any]]:
        """DEV-177: EMA avg_R по signal_type, хронологически.

        alpha = 1 - 0.5 ** (1 / half_life). При hl=50 ≈ 0.0138.
        Сделка 50-й давности весит 1/2 от сегодняшней, 100-й — 1/4, 200-й — 1/16.

        Формат выхода совместим с ``by_signal_type()`` (drop-in замена в
        ``update_signal_weights``): signal_type, total, wins, losses,
        tp_count, tsl_count, sl_count, win_rate, avg_r, avg_profit_pct.
        Отличие: ``avg_r``/``avg_profit_pct`` — EMA, а не AVG.
        ``total``/``wins``/``losses`` — по отфильтрованным сделкам (не всей истории).

        :param half_life: период полураспада в сделках (30=реактивно, 50=баланс,
            100=консервативно).
        :param data_era: фильтр по ``features_json.data_era`` (``"post_fix"`` >= 15.04).
            ``None`` — все эры (смешивание с pre-fix даст ложный EMA).
        """
        if half_life <= 0:
            half_life = 50.0
        alpha = 1.0 - 0.5 ** (1.0 / float(half_life))

        era_clause = ""
        era_params: tuple = ()
        if data_era:
            era_clause = "AND json_extract(features_json, '$.data_era') = ?"
            era_params = (data_era,)

        # DEV-190: добавлен tsl_activated для классификации скрытых TSL exits
        sql = f"""
            SELECT signal_type, status, R_multiple, profit_pct, tsl_activated
            FROM simulated_trades
            WHERE status IN ('TP','SL','TSL','EXPIRED')
              AND R_multiple IS NOT NULL
              {era_clause}
            ORDER BY closed_at ASC
        """

        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute(sql, era_params)
                rows = cur.fetchall()
        except Exception as e:
            logger.exception("PerformanceEngine.by_signal_type_ema: %s", e)
            return []

        agg: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            st = r["signal_type"] or "unknown"
            status = r["status"]
            rmult = float(r["R_multiple"]) if r["R_multiple"] is not None else 0.0
            pnl = float(r["profit_pct"]) if r["profit_pct"] is not None else 0.0
            tsl_act = r["tsl_activated"]
            a = agg.setdefault(st, {
                "signal_type": st,
                "total": 0, "tp_count": 0, "tsl_count": 0, "sl_count": 0,
                "tsl_hidden_count": 0,
                "ema_r": None, "ema_pnl": None,
            })
            a["total"] += 1
            if status == "TP":
                a["tp_count"] += 1
            elif status == "TSL":
                a["tsl_count"] += 1
            elif status == "SL":
                a["sl_count"] += 1
                # DEV-190: скрытый TSL exit (status='SL' но R>0.1 при активном TSL)
                if tsl_act and rmult > 0.10:
                    a["tsl_hidden_count"] += 1
            # EMA init на первой сделке, иначе инкрементально
            if a["ema_r"] is None:
                a["ema_r"] = rmult
            else:
                a["ema_r"] = alpha * rmult + (1.0 - alpha) * a["ema_r"]
            if a["ema_pnl"] is None:
                a["ema_pnl"] = pnl
            else:
                a["ema_pnl"] = alpha * pnl + (1.0 - alpha) * a["ema_pnl"]

        result: List[Dict[str, Any]] = []
        for a in agg.values():
            tp = a["tp_count"]
            tsl = a["tsl_count"]
            sl = a["sl_count"]
            hidden = a["tsl_hidden_count"]
            closed = tp + tsl + sl
            # DEV-190: wins = TP + TSL_native + TSL_hidden_win
            eff_wins = tp + tsl + hidden
            result.append({
                "signal_type":   a["signal_type"],
                "total":         a["total"],
                "tp_count":      tp,
                "tsl_count":     tsl,
                "sl_count":      sl,
                "tsl_hidden_count": hidden,
                "wins":          eff_wins,
                "losses":        closed - eff_wins,
                "win_rate":      round(eff_wins / closed * 100, 1) if closed else None,
                "win_rate_raw":  round((tp + tsl) / closed * 100, 1) if closed else None,
                "avg_r":         round(a["ema_r"], 3) if a["ema_r"] is not None else None,
                "avg_profit_pct": round(a["ema_pnl"], 3) if a["ema_pnl"] is not None else None,
            })
        result.sort(key=lambda x: -x["total"])
        return result

    # ------------------------------------------------------------------
    # DEV-179: расширенные метрики — median/Sharpe/p90/top20_share
    # ------------------------------------------------------------------
    def by_signal_type_extended(self) -> List[Dict[str, Any]]:
        """DEV-179: полный набор метрик по signal_type.

        Возвращает все поля ``by_signal_type()`` плюс:
          - ``median_r``  — медиана R_multiple
          - ``sharpe``    — mean(R) / std(R) (без аннуализации)
          - ``p90_r``     — 90-й перцентиль R_multiple
          - ``top20_share`` — доля суммарного R, которую дают топ-20 сделок (0..1)
          - ``warnings``  — list[str]: «n<100», «sharpe<0.5», «heavy_tail», «top20_concentrated»
          - ``r_values``  — не включаем (большой список), только агрегаты

        Читает все R_multiple из БД, агрегирует в Python (SQLite не имеет percentile).
        Не затрагивает ``by_signal_type()`` — он используется в адаптивных весах.
        """
        import statistics as _stats

        try:
            with self._conn() as conn:
                cur = conn.cursor()
                # Базовая статистика — идентично by_signal_type()
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
                base_rows = cur.fetchall()

                # Все R значения по типу для percentile/std/top20
                cur.execute("""
                    SELECT signal_type, R_multiple
                    FROM simulated_trades
                    WHERE status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
                    ORDER BY signal_type, R_multiple DESC
                """)
                r_by_type: Dict[str, List[float]] = {}
                for st, r in cur.fetchall():
                    r_by_type.setdefault(st, []).append(float(r))
        except Exception as e:
            logger.exception("PerformanceEngine.by_signal_type_extended: %s", e)
            return []

        result: List[Dict[str, Any]] = []
        for row in base_rows:
            d = dict(row)
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

            st = d["signal_type"]
            rs = r_by_type.get(st, [])  # уже отсортированы DESC в SQL
            rs_asc = list(reversed(rs))   # ascending для percentile

            # Median
            median_r: Optional[float] = None
            if rs_asc:
                n = len(rs_asc)
                if n % 2 == 1:
                    median_r = round(rs_asc[n // 2], 3)
                else:
                    median_r = round((rs_asc[n // 2 - 1] + rs_asc[n // 2]) / 2.0, 3)

            # Sharpe = mean / std (простой, не аннуализированный)
            sharpe: Optional[float] = None
            if len(rs_asc) >= 2:
                try:
                    mean_r = sum(rs_asc) / len(rs_asc)
                    std_r = _stats.stdev(rs_asc)
                    sharpe = round(mean_r / std_r, 3) if std_r > 1e-9 else None
                except Exception:
                    pass

            # p90 — 90th percentile
            p90_r: Optional[float] = None
            if rs_asc:
                idx = int(0.9 * (len(rs_asc) - 1))
                p90_r = round(rs_asc[idx], 3)

            # top20_share — топ-20 сделок дают X% суммарного R (rs уже DESC)
            # None если суммарный R ≤ 0 (концентрация бессмысленна при убыточной стратегии)
            top20_share: Optional[float] = None
            if rs:
                total_sum = sum(rs)
                if total_sum > 0.1:
                    top20_sum = sum(rs[:20])
                    share = top20_sum / total_sum
                    # Если >1 — топ-20 «вытаскивают» суммарно убыточные остальные сделки
                    # Показываем 1.0 как максимум (>100% = «остальные в минусе»)
                    top20_share = round(min(1.0, max(0.0, share)), 3)

            # Warnings
            warnings: List[str] = []
            if closed < 100:
                warnings.append("n<100")
            if sharpe is not None and sharpe < 0.5:
                warnings.append("sharpe<0.5")
            avg_r = d.get("avg_r") or 0.0
            if median_r is not None and avg_r != 0 and abs(avg_r) > 1e-9:
                if abs((avg_r - median_r) / avg_r) > 0.5:
                    warnings.append("heavy_tail")
            if top20_share is not None and top20_share > 0.5:
                warnings.append("top20_concentrated")

            d["median_r"] = median_r
            d["sharpe"] = sharpe
            d["p90_r"] = p90_r
            d["top20_share"] = top20_share
            d["warnings"] = warnings
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # По стратегии (strategy_name)
    # ------------------------------------------------------------------
    def by_strategy(self) -> List[Dict[str, Any]]:
        """WR / avg_R / total по strategy_name — для сравнения стратегий."""
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT
                        COALESCE(strategy_name, '—') AS strategy_name,
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='TP'  THEN 1 ELSE 0 END) AS tp_count,
                        SUM(CASE WHEN status='TSL' THEN 1 ELSE 0 END) AS tsl_count,
                        SUM(CASE WHEN status='SL'  THEN 1 ELSE 0 END) AS sl_count,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN profit_pct END) AS avg_profit_pct,
                        AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN R_multiple END) AS avg_r
                    FROM simulated_trades
                    GROUP BY strategy_name
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
            logger.exception("PerformanceEngine.by_strategy: %s", e)
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
    def recent_closed(self, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, symbol, timeframe, direction, signal_type, regime,
                           entry_price, exit_price, profit_pct, R_multiple,
                           status, created_at, closed_at, duration_minutes,
                           max_R_possible, captured_R_pct,
                           sl_source, tp_source, tsl_tf,
                           features_json
                    FROM simulated_trades
                    WHERE status != 'OPEN'
                    ORDER BY closed_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.exception("PerformanceEngine.recent_closed: %s", e)
            return []

    def closed_trades_count(self) -> int:
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM simulated_trades WHERE status != 'OPEN'")
                return cur.fetchone()[0]
        except Exception:
            return 0

    def mfe_ready_count(self) -> int:
        """DEV-16: Количество закрытых сделок с MFE-данными (max_R_possible IS NOT NULL).
        Нужно >= 3000 для обучения RLExitAgent.
        """
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT COUNT(*) FROM simulated_trades "
                    "WHERE status IN ('TP','SL','TSL') AND max_R_possible IS NOT NULL"
                )
                return cur.fetchone()[0]
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Открытые сделки
    # ------------------------------------------------------------------
    def open_trades(self) -> List[Dict[str, Any]]:
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, symbol, timeframe, direction, signal_type, regime,
                           entry_price, stop_loss, take_profit,
                           strength, confidence, created_at,
                           tsl_activated, tsl_tf,
                           tp_source, sl_source,
                           max_price, min_price, max_R_possible,
                           features_json
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

    def pair_stats(self, symbol: str) -> Dict[str, Any]:
        """Агрегированная статистика по символу (DEV-117)."""
        try:
            with self._conn() as conn:
                conn.row_factory = None
                cur = conn.cursor()
                row = cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END) as wins,
                        AVG(CASE WHEN R_multiple IS NOT NULL THEN R_multiple END) as avg_r,
                        MAX(R_multiple) as best_r,
                        MIN(R_multiple) as worst_r,
                        SUM(CASE WHEN direction='LONG' THEN 1 ELSE 0 END) as longs,
                        SUM(CASE WHEN direction='SHORT' THEN 1 ELSE 0 END) as shorts,
                        MIN(created_at) as first_trade,
                        MAX(closed_at) as last_trade
                    FROM simulated_trades
                    WHERE symbol = ? AND status != 'OPEN'
                """, (symbol,)).fetchone()
                if not row or not row[0]:
                    return {"total": 0, "wr_pct": None, "avg_r": None}
                total, wins = int(row[0]), int(row[1] or 0)
                return {
                    "total":      total,
                    "wins":       wins,
                    "wr_pct":     round(wins / total * 100, 1) if total else None,
                    "avg_r":      round(float(row[2]), 2) if row[2] is not None else None,
                    "best_r":     round(float(row[3]), 2) if row[3] is not None else None,
                    "worst_r":    round(float(row[4]), 2) if row[4] is not None else None,
                    "longs":      int(row[5] or 0),
                    "shorts":     int(row[6] or 0),
                    "first_trade": row[7],
                    "last_trade":  row[8],
                }
        except Exception:
            logger.exception("pair_stats %s", symbol)
            return {}

    def top_pairs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Топ пар по количеству сделок + WR (DEV-117)."""
        try:
            with self._conn() as conn:
                conn.row_factory = None
                cur = conn.cursor()
                rows = cur.execute("""
                    SELECT
                        symbol,
                        COUNT(*) as total,
                        SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END) as wins,
                        AVG(CASE WHEN R_multiple IS NOT NULL THEN R_multiple END) as avg_r
                    FROM simulated_trades
                    WHERE status != 'OPEN'
                    GROUP BY symbol
                    ORDER BY total DESC
                    LIMIT ?
                """, (limit,)).fetchall()
                result = []
                for r in rows:
                    total, wins = int(r[1]), int(r[2] or 0)
                    result.append({
                        "symbol":  r[0],
                        "total":   total,
                        "wins":    wins,
                        "wr_pct":  round(wins / total * 100, 1) if total else None,
                        "avg_r":   round(float(r[3]), 2) if r[3] is not None else None,
                    })
                return result
        except Exception:
            logger.exception("top_pairs")
            return []

    # ------------------------------------------------------------------
    # Разбивка confluence по факторам, direction, strength
    # ------------------------------------------------------------------
    def confluence_breakdown(self) -> Dict[str, Any]:
        """Аналитика WR по confluence-факторам, direction и strength."""
        import json
        try:
            with self._conn() as conn:
                conn.row_factory = None
                cur = conn.cursor()

                # По direction
                cur.execute("""
                    SELECT direction,
                        COUNT(*) total,
                        SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END) wins,
                        ROUND(100.0*SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END)/COUNT(*),1) wr,
                        ROUND(AVG(R_multiple),2) avg_r
                    FROM simulated_trades
                    WHERE signal_type='confluence' AND status IN ('TP','SL','TSL')
                    GROUP BY direction ORDER BY wr DESC
                """)
                by_direction = [
                    {"direction": r[0], "total": r[1], "wins": r[2], "wr": r[3], "avg_r": r[4]}
                    for r in cur.fetchall()
                ]

                # По диапазонам strength
                cur.execute("""
                    SELECT
                        CASE
                            WHEN strength < 50 THEN '<50'
                            WHEN strength < 60 THEN '50-60'
                            WHEN strength < 70 THEN '60-70'
                            WHEN strength < 80 THEN '70-80'
                            ELSE '80+'
                        END rng,
                        COUNT(*) total,
                        SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END) wins,
                        ROUND(100.0*SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END)/COUNT(*),1) wr,
                        ROUND(AVG(R_multiple),2) avg_r
                    FROM simulated_trades
                    WHERE signal_type='confluence' AND status IN ('TP','SL','TSL')
                    GROUP BY rng ORDER BY rng
                """)
                by_strength = [
                    {"range": r[0], "total": r[1], "wins": r[2], "wr": r[3], "avg_r": r[4]}
                    for r in cur.fetchall()
                ]

                # По tp_source
                cur.execute("""
                    SELECT tp_source,
                        COUNT(*) total,
                        ROUND(100.0*SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END)/COUNT(*),1) wr,
                        ROUND(AVG(R_multiple),2) avg_r
                    FROM simulated_trades
                    WHERE signal_type='confluence' AND status IN ('TP','SL','TSL')
                    GROUP BY tp_source ORDER BY total DESC LIMIT 10
                """)
                by_tp_source = [
                    {"source": r[0] or "—", "total": r[1], "wr": r[2], "avg_r": r[3]}
                    for r in cur.fetchall()
                ]

                # По факторам (из features_json → confluence_factors)
                cur.execute("""
                    SELECT features_json, status, R_multiple
                    FROM simulated_trades
                    WHERE signal_type='confluence'
                        AND status IN ('TP','SL','TSL')
                        AND features_json IS NOT NULL
                        AND features_json LIKE '%confluence_factors%'
                """)
                factor_stats: Dict[str, Dict] = {}
                for fj, status, rmult in cur.fetchall():
                    try:
                        factors = json.loads(fj).get("confluence_factors", [])
                    except Exception:
                        factors = []
                    win = 1 if status in ("TP", "TSL") else 0
                    for f in factors:
                        if f not in factor_stats:
                            factor_stats[f] = {"total": 0, "wins": 0, "r_sum": 0.0}
                        factor_stats[f]["total"] += 1
                        factor_stats[f]["wins"] += win
                        factor_stats[f]["r_sum"] += (rmult or 0.0)

                by_factor = sorted([
                    {
                        "factor": k,
                        "total": v["total"],
                        "wr": round(100.0 * v["wins"] / v["total"], 1) if v["total"] else 0,
                        "avg_r": round(v["r_sum"] / v["total"], 2) if v["total"] else 0,
                    }
                    for k, v in factor_stats.items()
                ], key=lambda x: -x["total"])

                return {
                    "by_direction": by_direction,
                    "by_strength": by_strength,
                    "by_tp_source": by_tp_source,
                    "by_factor": by_factor,
                }
        except Exception:
            logger.exception("confluence_breakdown")
            return {"by_direction": [], "by_strength": [], "by_tp_source": [], "by_factor": []}

    # ------------------------------------------------------------------
    # Статистика безубытка
    # ------------------------------------------------------------------
    def breakeven_stats(self) -> Dict[str, Any]:
        """
        Статистика срабатывания безубытка (be_activated=1):
          - total_be: сколько раз сработал
          - be_exit: сколько закрылись по BE (SL у entry)
          - survived: сколько выжили и закрылись TP/TSL
          - avg_r_be_exit: средний R при BE-выходе (должен быть ~0)
          - avg_r_survived: средний R выживших (TP/TSL после BE)
          - be_exit_pct: % сделок закрытых на BE из всех с be_activated
          - without_be: средний R сделок без BE (база сравнения)
          BE-выход определяется как: status=SL + |exit - entry| / entry < 0.5%
        """
        try:
            with self._conn() as conn:
                cur = conn.cursor()

                # Сделки с BE
                cur.execute("""
                    SELECT status, exit_price, entry_price, R_multiple
                    FROM simulated_trades
                    WHERE be_activated=1
                      AND status IN ('TP','SL','TSL')
                      AND exit_price IS NOT NULL AND entry_price > 0
                """)
                rows_be = cur.fetchall()

                # Сделки без BE
                cur.execute("""
                    SELECT AVG(R_multiple), COUNT(*)
                    FROM simulated_trades
                    WHERE be_activated=0
                      AND status IN ('TP','SL','TSL')
                      AND R_multiple IS NOT NULL
                """)
                row_no_be = cur.fetchone()

            be_exit_rows, survived_rows = [], []
            for status, exit_p, entry_p, rmult in rows_be:
                is_be_exit = (
                    status == "SL"
                    and exit_p is not None
                    and abs(exit_p - entry_p) / entry_p < 0.005
                )
                if is_be_exit:
                    be_exit_rows.append(rmult or 0.0)
                else:
                    survived_rows.append(rmult or 0.0)

            total_be   = len(rows_be)
            be_exit_n  = len(be_exit_rows)
            survived_n = len(survived_rows)

            def avg(lst): return round(sum(lst) / len(lst), 3) if lst else None

            return {
                "total_be":      total_be,
                "be_exit":       be_exit_n,
                "survived":      survived_n,
                "be_exit_pct":   round(be_exit_n / total_be * 100) if total_be else 0,
                "avg_r_be_exit": avg(be_exit_rows),
                "avg_r_survived": avg(survived_rows),
                "without_be_avg_r": round(row_no_be[0], 3) if row_no_be and row_no_be[0] else None,
                "without_be_total": row_no_be[1] if row_no_be else 0,
            }
        except Exception:
            logger.exception("breakeven_stats")
            return {}

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
    # DEV-27: Rolling WR degradation detector
    # ------------------------------------------------------------------
    def rolling_win_rate(self, window: int = 50) -> Optional[Dict[str, Any]]:
        """WR по последним N закрытым сделкам (rolling window).

        Returns dict с ключами: win_rate, wins, losses, n, status
        status: "ok" | "warn" | "critical" | "insufficient_data"
        """
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                # DEV-190: учёт скрытых TSL exits через is_win SQL fragment
                cur.execute(f"""
                    SELECT {SQL_IS_WIN_CASE} AS is_win
                    FROM simulated_trades
                    WHERE status IN ('TP', 'SL', 'TSL')
                    ORDER BY closed_at DESC
                    LIMIT ?
                """, (window,))
                rows = [r[0] for r in cur.fetchall()]
            n = len(rows)
            if n < max(10, window // 5):
                return {"win_rate": None, "wins": 0, "losses": 0, "n": n, "status": "insufficient_data"}
            wins = sum(rows)
            losses = n - wins
            wr = round(wins / n * 100, 1)
            if wr < 30.0:
                status = "critical"
            elif wr < 40.0:
                status = "warn"
            else:
                status = "ok"
            return {"win_rate": wr, "wins": wins, "losses": losses, "n": n, "status": status}
        except Exception as e:
            logger.exception("PerformanceEngine.rolling_win_rate: %s", e)
            return None

    def check_wr_degradation(self, window: int = 50, warn_threshold: float = 40.0,
                             critical_threshold: float = 30.0) -> Optional[Dict[str, Any]]:
        """Проверяет деградацию WR по скользящему окну.

        Returns None если данных недостаточно, иначе dict:
          - win_rate, n, status ("ok"|"warn"|"critical"), message
        """
        result = self.rolling_win_rate(window=window)
        if result is None or result.get("status") == "insufficient_data":
            return None
        wr = result["win_rate"]
        if wr < critical_threshold:
            result["message"] = (
                f"🚨 КРИТИЧНО: Rolling WR={wr:.1f}% за {result['n']} сделок "
                f"(порог {critical_threshold:.0f}%). Проверь сигналы немедленно!"
            )
        elif wr < warn_threshold:
            result["message"] = (
                f"⚠️ ПРЕДУПРЕЖДЕНИЕ: Rolling WR={wr:.1f}% за {result['n']} сделок "
                f"(порог {warn_threshold:.0f}%). Возможная деградация."
            )
        else:
            result["message"] = f"✅ Rolling WR={wr:.1f}% за {result['n']} сделок — норма."
        return result

    # ------------------------------------------------------------------
    # Всё одним вызовом (для /api/stats)
    # ------------------------------------------------------------------
    def equity_data(self) -> List[Dict[str, Any]]:
        """Возвращает закрытые сделки для equity curve в дашборде."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT symbol, status, R_multiple, closed_at,
                       entry_price, stop_loss, created_at, direction
                FROM simulated_trades
                WHERE status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
                ORDER BY closed_at ASC
                """
            )
            rows = cursor.fetchall()
        return [
            {
                "symbol": r[0], "status": r[1], "R_multiple": r[2], "closed_at": r[3],
                "entry_price": r[4], "stop_loss": r[5],
                "created_at": r[6], "direction": r[7],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # DEV-116: аналитические данные для графиков
    # ------------------------------------------------------------------

    def by_session(self) -> List[Dict[str, Any]]:
        """WR и avg_R по торговым сессиям из features_json."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT
                    COALESCE(json_extract(features_json, '$.session'), '?') as session,
                    COUNT(*) as n,
                    ROUND(SUM(CASE WHEN R_multiple > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as wr,
                    ROUND(AVG(R_multiple), 3) as avg_r,
                    ROUND(SUM(R_multiple), 1) as total_r
                FROM simulated_trades
                WHERE status NOT IN ('OPEN') AND features_json IS NOT NULL
                GROUP BY session
                ORDER BY avg_r DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def r_distribution(self) -> Dict[str, Any]:
        """Распределение R_multiple по бакетам для гистограммы."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT R_multiple FROM simulated_trades
                WHERE status NOT IN ('OPEN') AND R_multiple IS NOT NULL
            """).fetchall()
        vals = [r[0] for r in rows]
        if not vals:
            return {"buckets": [], "counts": []}
        # Бакеты: от -2 до +8R с шагом 0.5
        import math
        edges = [-3, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 999]
        labels = ["<-2", "-2..-1.5", "-1.5..-1", "-1..-0.5", "-0.5..0",
                  "0..0.5", "0.5..1", "1..1.5", "1.5..2", "2..3", "3..4",
                  "4..5", "5..6", "6..8", ">8"]
        counts = [0] * len(labels)
        for v in vals:
            for i in range(len(edges) - 1):
                if edges[i] <= v < edges[i + 1]:
                    counts[i] += 1
                    break
        return {"buckets": labels, "counts": counts, "total": len(vals)}

    def pnl_calendar(self) -> List[Dict[str, Any]]:
        """P&L по дням: дата, n сделок, avg_R, total_R для heatmap."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT
                    DATE(closed_at) as day,
                    COUNT(*) as n,
                    ROUND(AVG(R_multiple), 3) as avg_r,
                    ROUND(SUM(R_multiple), 2) as total_r,
                    ROUND(SUM(CASE WHEN R_multiple > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 0) as wr
                FROM simulated_trades
                WHERE status NOT IN ('OPEN') AND closed_at IS NOT NULL AND R_multiple IS NOT NULL
                GROUP BY day
                ORDER BY day DESC
                LIMIT 90
            """).fetchall()
            return [dict(r) for r in rows]

    def mfe_scatter(self) -> List[Dict[str, Any]]:
        """MFE vs Exit R scatter: max_R_possible vs R_multiple (последние 500)."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT
                    R_multiple as exit_r,
                    max_R_possible as mfe_r,
                    status,
                    signal_type,
                    regime
                FROM simulated_trades
                WHERE status NOT IN ('OPEN')
                  AND R_multiple IS NOT NULL
                  AND max_R_possible IS NOT NULL
                  AND max_R_possible > 0
                ORDER BY closed_at DESC
                LIMIT 500
            """).fetchall()
            return [dict(r) for r in rows]

    def full_stats(self) -> Dict[str, Any]:
        return {
            "summary": self.summary(),
            "by_signal_type": self.by_signal_type(),
            "by_signal_type_extended": self.by_signal_type_extended(),  # DEV-179
            "by_strategy": self.by_strategy(),
            "by_direction": self.by_direction(),
            "by_regime": self.by_regime(),
            "recent_closed": self.recent_closed(20),
            "open_trades": self.open_trades(),
        }
