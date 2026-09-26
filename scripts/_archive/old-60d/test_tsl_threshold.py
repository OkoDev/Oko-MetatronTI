"""
Тест снижения TSL-порогов для wt_signal, confluence, atr_change.

Оценивает НЕТТО-эффект от более ранней активации TSL:
  - Сколько SL-сделок было бы СПАСЕНО (достигли порога, но TSL не включился)
  - Сколько TSL-сделок было бы СРЕЗАНО (вышли бы раньше с меньшим R)

Метод (консервативный):
  SL спасённые:  first_profit_r >= threshold, tsl_activated=0
                 → оценка выхода: threshold (TSL защищает минимум столько)
  TSL срезанные: tsl_activated=1, R_multiple > threshold
                 → потеря = R_multiple - threshold (вышли бы раньше)

Запуск: python scripts/test_tsl_threshold.py
"""
import sqlite3
from collections import defaultdict

DB = "subscriptions.db"

# Текущие пороги из config.yaml
CURRENT_THRESHOLDS = {
    "pivot_reversal": 0.5,
    "wt_b": 0.8,
    "wt_signal": 1.0,
    "wt_sideways": 0.8,
    "atr_change": 1.5,
    "confluence": 1.0,
    "ote_nested": 4.0,
}

# Тестируемые пороги для каждого типа (текущий + кандидаты на снижение)
TEST_THRESHOLDS = {
    "wt_signal":    [0.3, 0.5, 0.7, 0.8, 1.0],
    "confluence":   [0.3, 0.5, 0.7, 0.8, 1.0],
    "atr_change":   [0.5, 0.8, 1.0, 1.2, 1.5],
    "pivot_reversal": [0.3, 0.5],  # уже 0.5
    "wt_b":         [0.5, 0.8],    # уже 0.8
}


def analyze(conn, signal_type, threshold):
    """Для одного signal_type и одного порога считаем спасённые SL и срезанные TSL."""
    cur = conn.cursor()

    # ── Спасённые SL: first_profit_r >= threshold, tsl_activated=0, status=SL ──
    cur.execute("""
        SELECT COUNT(*), COALESCE(AVG(R_multiple), 0), COALESCE(SUM(R_multiple), 0)
        FROM simulated_trades
        WHERE signal_type = ?
          AND status = 'SL'
          AND tsl_activated = 0
          AND first_profit_r IS NOT NULL
          AND first_profit_r >= ?
    """, (signal_type, threshold))
    sl_n, sl_avg, sl_sum = cur.fetchone()

    # Оценка выгоды: каждая спасённая SL-сделка вместо −|R| даёт +threshold (TSL защитил)
    # Консервативно: выход ровно на threshold
    sl_saved_r = sl_n * threshold   # сколько R сохранили бы
    sl_actual_loss = abs(sl_sum)     # сколько реально потеряли
    sl_net_gain = sl_saved_r - sl_actual_loss  # улучшение от спасения

    # ── Срезанные TSL: tsl_activated=1, R_multiple > threshold ──
    cur.execute("""
        SELECT COUNT(*), COALESCE(AVG(R_multiple), 0), COALESCE(SUM(R_multiple), 0)
        FROM simulated_trades
        WHERE signal_type = ?
          AND status IN ('TSL', 'TP')
          AND tsl_activated = 1
          AND R_multiple IS NOT NULL
          AND R_multiple > ?
    """, (signal_type, threshold))
    tsl_n, tsl_avg, tsl_sum = cur.fetchone()

    # Потеря: вместо фактического R_multiple получили бы threshold
    tsl_loss = tsl_sum - (tsl_n * threshold) if tsl_n > 0 else 0

    # ── Текущий avgR (для контекста) ──
    cur.execute("""
        SELECT COUNT(*), COALESCE(AVG(R_multiple), 0)
        FROM simulated_trades
        WHERE signal_type = ?
          AND status IN ('SL', 'TSL', 'TP', 'EXPIRED')
          AND R_multiple IS NOT NULL
    """, (signal_type,))
    total_n, total_avg = cur.fetchone()

    return {
        "threshold": threshold,
        "total_n": total_n,
        "total_avgR": total_avg,
        "sl_saved_n": sl_n,
        "sl_saved_r": round(sl_saved_r, 2),
        "sl_actual_loss": round(sl_actual_loss, 2),
        "sl_net_gain": round(sl_net_gain, 2),
        "tsl_cut_n": tsl_n,
        "tsl_loss": round(tsl_loss, 2),
        "tsl_avg": round(tsl_avg, 2),
        "netto": round(sl_net_gain - tsl_loss, 2),
    }


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # Общая статистика по всем закрытым
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM simulated_trades WHERE status != 'OPEN'")
    total_closed = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM simulated_trades WHERE first_profit_r IS NOT NULL AND status != 'OPEN'")
    total_with_fpr = cur.fetchone()[0]
    print(f"=== TSL Threshold Test: early activation ===")
    print(f"Closed: {total_closed} | with timeline: {total_with_fpr}")
    print()

    for sig_type, thresholds in TEST_THRESHOLDS.items():
        current = CURRENT_THRESHOLDS.get(sig_type, 1.0)

        # Проверим есть ли сделки этого типа
        cur.execute("SELECT COUNT(*) FROM simulated_trades WHERE signal_type=? AND status!='OPEN'", (sig_type,))
        n_type = cur.fetchone()[0]
        if n_type < 10:
            continue

        print(f"{'-' * 70}")
        print(f"  {sig_type}  (current: {current}R, total: {n_type})")
        print(f"{'-' * 70}")
        print(f"{'Thr':>6} | {'SL saved':>12} | {'Gain R':>9} | {'TSL cut':>12} | {'Loss R':>9} | {'NETTO':>9} | {'avgR':>9}")
        print(f"{'-' * 70}")

        best_netto = -999
        best_threshold = current

        for t in thresholds:
            r = analyze(conn, sig_type, t)
            marker = " < CURRENT" if t == current else ""
            print(f"{t:>5.1f}R | {r['sl_saved_n']:>8d} ({r['sl_saved_r']:>+6.1f}R) | {r['sl_net_gain']:>+8.1f}R | {r['tsl_cut_n']:>8d} ({r['tsl_avg']:>+5.2f}R) | {r['tsl_loss']:>+8.1f}R | {r['netto']:>+8.1f}R | {r['total_avgR']:>+9.2f}R{marker}")

            if r['netto'] > best_netto:
                best_netto = r['netto']
                best_threshold = t

        print(f"{'-' * 70}")
        if best_netto > 0:
            print(f"  >>> RECOMMEND: lower to {best_threshold}R (NETTO +{best_netto:.1f}R)")
        elif best_threshold != current and best_netto < 0:
            print(f"  >>> All negative. Best: {best_threshold}R (NETTO {best_netto:.1f}R)")
        else:
            print(f"  >>> Current {current}R is optimal (or all negative)")
        print()

    conn.close()


if __name__ == "__main__":
    main()
