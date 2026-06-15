"""
Замер #8 SIM-edge: сдвиг весов при фильтрации execution_mode='VST'.

Сравнивает:
  A (ТЕКУЩЕЕ): все сделки (SIM + VST) → avg_R → factor → weight
  B (ПОСЛЕ): только VST (AND execution_mode='VST') → avg_R → factor → weight

Выводит таблицу до/после по каждому signal_type.
"""

import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "subscriptions.db")

# Функция factor→weight (как в update_signal_weights)
BASE_WEIGHTS = {
    "ote_nested": 0.1,
    "arch104": 0.1,
    "atr_change": 0.1,
    "wt_b_signal": 0.1,
    "pivot_reversal": 0.1,
    "confluence": 0.1,
    "watch_list_breach": 0.1,
    "trend_signal": 0.1,
    "wt_signal": 0.1,
    "anomaly": 0.1,
    "divergence": 0.1,
    "mtf_bias": 0.1,
}

# Копия SQL_IS_WIN_CASE из effective_status.py
SQL_IS_WIN_CASE = """
    CASE
        WHEN status = 'TP' THEN 1
        WHEN status = 'TSL' THEN 1
        WHEN status = 'SL' AND tsl_activated = 1 AND R_multiple > 0.10 THEN 1
        ELSE 0
    END
"""

MIN_TRADES = 20
FACTOR_FN = lambda avg_r: max(0.5, min(2.0, 1.0 + avg_r * 0.4))


def query_signal_stats(conn, vst_only: bool):
    """Возвращает {signal_type: {total, wins, losses, avg_r, avg_profit_pct}}."""
    extra = "AND execution_mode = 'VST'" if vst_only else ""
    sql = f"""
        SELECT
            signal_type,
            COUNT(*) AS total,
            SUM(CASE WHEN status='TP'  THEN 1 ELSE 0 END) AS tp_count,
            SUM(CASE WHEN status='TSL' THEN 1 ELSE 0 END) AS tsl_count,
            SUM(CASE WHEN status='SL'  THEN 1 ELSE 0 END) AS sl_count,
            SUM({SQL_IS_WIN_CASE}) AS eff_wins,
            AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN R_multiple END) AS avg_r,
            AVG(CASE WHEN status IN ('TP','SL','TSL','EXPIRED') THEN profit_pct END) AS avg_profit_pct
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED')
          AND R_multiple IS NOT NULL
          {extra}
        GROUP BY signal_type
        ORDER BY total DESC
    """
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    result = {}
    for r in rows:
        d = dict(r)
        tp = d["tp_count"] or 0
        tsl = d["tsl_count"] or 0
        sl = d["sl_count"] or 0
        eff_wins = d["eff_wins"] or 0
        closed = tp + tsl + sl
        d["wins"] = eff_wins
        d["losses"] = closed - eff_wins
        d["win_rate"] = round(eff_wins / closed * 100, 1) if closed else None
        if d["avg_r"] is not None:
            d["avg_r"] = round(d["avg_r"], 3)
        if d["avg_profit_pct"] is not None:
            d["avg_profit_pct"] = round(d["avg_profit_pct"], 3)
        result[d["signal_type"] or "unknown"] = d
    return result


# Также EMA-версия (как в by_signal_type_ema, но sqlite-уровень)
def query_signal_ema(conn, vst_only: bool, half_life: float = 50.0, data_era: str = "post_fix"):
    """Возвращает EMA avg_R по signal_type (как PerformanceEngine.by_signal_type_ema)."""
    extra = "AND execution_mode = 'VST'" if vst_only else ""
    alpha = 1.0 - 0.5 ** (1.0 / half_life)
    
    sql = f"""
        SELECT signal_type, status, R_multiple, profit_pct, tsl_activated
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED')
          AND R_multiple IS NOT NULL
          AND json_extract(features_json, '$.data_era') = ?
          {extra}
        ORDER BY closed_at ASC
    """
    cur = conn.cursor()
    cur.execute(sql, (data_era,))
    rows = cur.fetchall()
    
    agg = {}
    for r in rows:
        st = r["signal_type"] or "unknown"
        status = r["status"]
        rmult = float(r["R_multiple"]) if r["R_multiple"] is not None else 0.0
        pnl = float(r["profit_pct"]) if r["profit_pct"] is not None else 0.0
        tsl_act = r["tsl_activated"]
        
        a = agg.setdefault(st, {
            "total": 0, "wins": 0, "losses": 0,
            "tp_count": 0, "tsl_count": 0, "sl_count": 0,
            "ema_r": 0.0, "ema_pnl": 0.0, "initialized": False,
        })
        a["total"] += 1
        if status == "TP":
            a["tp_count"] += 1
            a["wins"] += 1
        elif status == "TSL":
            a["tsl_count"] += 1
            a["wins"] += 1
        elif status == "SL":
            a["sl_count"] += 1
            if tsl_act == 1 and rmult > 0.10:
                a["wins"] += 1
            else:
                a["losses"] += 1
        elif status == "EXPIRED":
            a["losses"] += 1
        
        # EMA обновление
        if not a["initialized"]:
            a["ema_r"] = rmult
            a["ema_pnl"] = pnl
            a["initialized"] = True
        else:
            a["ema_r"] = alpha * rmult + (1 - alpha) * a["ema_r"]
            a["ema_pnl"] = alpha * pnl + (1 - alpha) * a["ema_pnl"]
    
    result = {}
    for st, a in agg.items():
        closed = a["tp_count"] + a["tsl_count"] + a["sl_count"]
        result[st] = {
            "signal_type": st,
            "total": a["total"],
            "wins": a["wins"],
            "losses": a["losses"],
            "tp_count": a["tp_count"],
            "tsl_count": a["tsl_count"],
            "sl_count": a["sl_count"],
            "win_rate": round(a["wins"] / closed * 100, 1) if closed else None,
            "avg_r": round(a["ema_r"], 3),
            "avg_profit_pct": round(a["ema_pnl"], 3),
        }
    return result


def main():
    db = DB_PATH
    if not os.path.exists(db):
        print(f"БД не найдена: {db}")
        sys.exit(1)
    
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    
    # 1. Full-history AVG
    print("=" * 110)
    print("[A] FULL-HISTORY AVG (by_signal_type)")
    print("=" * 110)
    
    all_stats = query_signal_stats(conn, vst_only=False)
    vst_stats = query_signal_stats(conn, vst_only=True)
    
    all_signal_types = sorted(set(list(all_stats.keys()) + list(vst_stats.keys())))
    
    print(f"{'signal_type':<20} {'ALL n':>6} {'ALL avgR':>8} {'VST n':>6} {'VST avgR':>8} {'Δ avgR':>8} {'ALL w':>7} {'VST w':>7} {'Δ w':>7}")
    print("-" * 110)
    
    for st in all_signal_types:
        a = all_stats.get(st, {})
        v = vst_stats.get(st, {})
        a_n = a.get("total", 0)
        a_r = a.get("avg_r") or 0.0
        v_n = v.get("total", 0)
        v_r = v.get("avg_r") or 0.0
        dr = v_r - a_r
        
        base = BASE_WEIGHTS.get(st, 0.1)
        a_w = round(base * FACTOR_FN(a_r), 4)
        v_w = round(base * FACTOR_FN(v_r), 4)
        dw = v_w - a_w
        
        warn = " !" if abs(dw) > 0.005 else ""
        
        print(f"{st:<20} {a_n:>6} {a_r:>+8.3f} {v_n:>6} {v_r:>+8.3f} {dr:>+8.3f} {a_w:>7.4f} {v_w:>7.4f} {dw:>+7.4f}{warn}")
    
    # 2. EMA (post_fix, half-life=50)
    print()
    print("=" * 110)
    print("[B] EMA avg_R (by_signal_type_ema, data_era='post_fix', hl=50)")
    print("=" * 110)
    
    all_ema = query_signal_ema(conn, vst_only=False)
    vst_ema = query_signal_ema(conn, vst_only=True)
    
    all_signal_types_ema = sorted(set(list(all_ema.keys()) + list(vst_ema.keys())))
    
    print(f"{'signal_type':<20} {'ALL n':>6} {'ALL EMAr':>8} {'VST n':>6} {'VST EMAr':>8} {'Δ EMAr':>8} {'ALL w':>7} {'VST w':>7} {'Δ w':>7}")
    print("-" * 110)
    
    for st in all_signal_types_ema:
        a = all_ema.get(st, {})
        v = vst_ema.get(st, {})
        a_n = a.get("total", 0)
        a_r = a.get("avg_r") or 0.0
        v_n = v.get("total", 0)
        v_r = v.get("avg_r") or 0.0
        dr = v_r - a_r
        
        base = BASE_WEIGHTS.get(st, 0.1)
        a_w = round(base * FACTOR_FN(a_r), 4)
        v_w = round(base * FACTOR_FN(v_r), 4)
        dw = v_w - a_w
        
        warn = " !" if abs(dw) > 0.005 else ""
        
        print(f"{st:<20} {a_n:>6} {a_r:>+8.3f} {v_n:>6} {v_r:>+8.3f} {dr:>+8.3f} {a_w:>7.4f} {v_w:>7.4f} {dw:>+7.4f}{warn}")
    
    # 3. Сводка: какие signal_type меняют вес значимо (Δ > 0.005)
    print()
    print("=" * 80)
    print("СВОДКА: signal_type со значимым сдвигом веса (|Δ w| > 0.005)")
    print("=" * 80)
    print(f"{'signal_type':<20} {'ALL EMAr':>8} {'VST EMAr':>8} {'Δ EMAr':>8} {'ALL w':>7} {'VST w':>7} {'Δ w':>7} {'Вердикт'}")
    print("-" * 80)
    
    significant = []
    for st in sorted(all_signal_types_ema):
        a = all_ema.get(st, {})
        v = vst_ema.get(st, {})
        a_r = a.get("avg_r") or 0.0
        v_r = v.get("avg_r") or 0.0
        base = BASE_WEIGHTS.get(st, 0.1)
        a_w = round(base * FACTOR_FN(a_r), 4)
        v_w = round(base * FACTOR_FN(v_r), 4)
        dw = v_w - a_w
        
        if abs(dw) > 0.005 or st in ("ote_nested", "arch104", "atr_change"):
            dr = v_r - a_r
            verdict = ""
            if abs(dw) > 0.01:
                verdict = "[!] ЗНАЧИМО"
                significant.append(st)
            elif abs(dw) > 0.005:
                verdict = "[~] УМЕРЕННО"
                significant.append(st)
            else:
                verdict = "[OK] без изменений"
            print(f"{st:<20} {a_r:>+8.3f} {v_r:>+8.3f} {dr:>+8.3f} {a_w:>7.4f} {v_w:>7.4f} {dw:>+7.4f} {verdict}")
    
    if significant:
        print(f"\n[!] Значимо меняются ({len(significant)}): {', '.join(significant)}")
    else:
        print("\n[OK] Ни один signal_type не меняется значимо.")
    
    conn.close()


if __name__ == "__main__":
    main()
