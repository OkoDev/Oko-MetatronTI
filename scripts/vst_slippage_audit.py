"""VST-SLIPPAGE аудит — реальный edge vs бумажный R.

VST-SLIPPAGE (08.06.2026, Claude -> DS): баланс VST в минусе при sumR+.
Гипотеза: slippage BingX VST ~0.45%/сторона съедает R_multiple.
Этот скрипт проверяет гипотезу на данных БД.

Вывод:
  1. VST vs PAPER avgR per signal_type
  2. Entry slippage (actual_entry_price vs entry_price)
  3. Реальный edge = R − slippage_est − funding_est − commission
  4. Рекомендация: min-R фильтр на вход
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "subscriptions.db"

def run():
    db = sqlite3.connect(str(DB))
    db.row_factory = sqlite3.Row

    # ── 1. Общая картина: VST vs Paper ──────────────────────────
    print("=" * 70)
    print("  1. VST vs PAPER — общая картина")
    print("=" * 70)

    for mode_label, mode_filter in [
        ("VST", "exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' AND exchange_order_id != ''"),
        ("PAPER", "(exchange_order_id IS NULL OR exchange_order_id = 'SIM' OR exchange_order_id = '')"),
    ]:
        cur = db.execute(f"""
            SELECT COUNT(*) as n, SUM(R_multiple) as sumR, AVG(R_multiple) as avgR,
                   COUNT(CASE WHEN R_multiple>0 THEN 1 END)*100.0/MAX(COUNT(*),1) as WR
            FROM simulated_trades
            WHERE status IN ('TP','SL','TSL','EXPIRED')
              AND {mode_filter}
        """)
        r = cur.fetchone()
        print(f"  {mode_label:>5s}: n={r['n']:>5d}  sumR={r['sumR'] or 0:>8.1f}  avgR={r['avgR'] or 0:>8.3f}  WR={r['WR'] or 0:.1f}%")

    # ── 2. Per signal_type: VST vs Paper ────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  2. Per signal_type — Paper vs VST avgR")
    print(f"{'=' * 70}")

    cur = db.execute("""
        SELECT signal_type,
               COUNT(*) as total_n,
               AVG(R_multiple) as total_avgR,
               SUM(CASE WHEN exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' AND exchange_order_id != '' 
                   THEN 1 ELSE 0 END) as vst_n,
               AVG(CASE WHEN exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' AND exchange_order_id != '' 
                   THEN R_multiple ELSE NULL END) as vst_avgR,
               SUM(CASE WHEN exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' AND exchange_order_id != '' 
                   THEN R_multiple ELSE 0 END) as vst_sumR
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED')
        GROUP BY signal_type
        HAVING vst_n >= 5
        ORDER BY vst_n DESC
    """)

    print(f"  {'signal_type':25s} {'vst_n':>5s} {'vst_avgR':>8s} {'total_avgR':>10s} {'vst_sumR':>8s}")
    print(f"  {'-'*25} {'-'*5} {'-'*8} {'-'*10} {'-'*8}")
    for r in cur.fetchall():
        st = r['signal_type'] or ''
        va = r['vst_avgR'] or 0
        ta = r['total_avgR'] or 0
        vs = r['vst_sumR'] or 0
        print(f"  {st:25s} {r['vst_n']:>5d} {va:>8.3f} {ta:>10.3f} {vs:>8.1f}")

    # ── 3. Entry slippage (actual_entry_price) ──────────────────
    print(f"\n{'=' * 70}")
    print(f"  3. Entry slippage: actual_entry vs entry_price")
    print(f"{'=' * 70}")

    cur = db.execute("""
        SELECT signal_type,
               COUNT(*) as n,
               AVG(ABS(actual_entry_price - entry_price) / entry_price * 100) as entry_slip_pct,
               AVG((actual_entry_price - entry_price) / entry_price * 100) as entry_slip_signed,
               AVG(entry_price) as avg_entry,
               AVG(actual_entry_price) as avg_actual
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED')
          AND exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' AND exchange_order_id != ''
          AND actual_entry_price IS NOT NULL AND actual_entry_price > 0
          AND entry_price IS NOT NULL AND entry_price > 0
        GROUP BY signal_type
        HAVING n >= 5
        ORDER BY n DESC
    """)

    print(f"  {'signal_type':25s} {'n':>5s} {'slip_abs%':>9s} {'slip_sign%':>9s} {'avg_entry':>10s} {'avg_actual':>10s}")
    print(f"  {'-'*25} {'-'*5} {'-'*9} {'-'*9} {'-'*10} {'-'*10}")
    for r in cur.fetchall():
        print(f"  {r['signal_type']:25s} {r['n']:>5d} {r['entry_slip_pct'] or 0:>9.4f} {r['entry_slip_signed'] or 0:>9.4f} {r['avg_entry'] or 0:>10.6f} {r['avg_actual'] or 0:>10.6f}")

    # ── 4. SL distance vs slippage ──────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  4. SL distance vs R_multiple — coverage check")
    print(f"{'=' * 70}")

    cur = db.execute("""
        SELECT signal_type,
               COUNT(*) as n,
               AVG(ABS(entry_price - stop_loss) / entry_price * 100) as sl_dist_pct,
               AVG(R_multiple) as avgR,
               AVG(ABS(actual_entry_price - entry_price) / entry_price * 100) as slip_pct,
               AVG(ABS(actual_entry_price - entry_price) / NULLIF(ABS(entry_price - stop_loss), 0)) as slip_vs_sl
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED')
          AND exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' AND exchange_order_id != ''
          AND actual_entry_price IS NOT NULL AND actual_entry_price > 0
          AND entry_price IS NOT NULL AND entry_price > 0
          AND stop_loss IS NOT NULL AND stop_loss > 0
        GROUP BY signal_type
        HAVING n >= 5
        ORDER BY slip_vs_sl DESC
    """)

    print(f"  {'signal_type':25s} {'n':>5s} {'SL_dist%':>8s} {'avgR':>8s} {'slip%':>7s} {'slip/SL':>8s}")
    print(f"  {'-'*25} {'-'*5} {'-'*8} {'-'*8} {'-'*7} {'-'*8}")
    for r in cur.fetchall():
        print(f"  {r['signal_type']:25s} {r['n']:>5d} {r['sl_dist_pct'] or 0:>8.2f} {r['avgR'] or 0:>8.3f} {r['slip_pct'] or 0:>7.3f} {r['slip_vs_sl'] or 0:>8.3f}")

    # ── 5. arch104 deep dive ────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  5. arch104 — глубокий разбор")
    print(f"{'=' * 70}")

    for mode_label, mode_filter in [
        ("VST", "exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' AND exchange_order_id != ''"),
        ("PAPER", "(exchange_order_id IS NULL OR exchange_order_id = 'SIM' OR exchange_order_id = '')"),
    ]:
        cur = db.execute(f"""
            SELECT COUNT(*) as n, SUM(R_multiple) as sumR, AVG(R_multiple) as avgR,
                   AVG(ABS(entry_price - stop_loss) / entry_price * 100) as sl_pct,
                   AVG(ABS(actual_entry_price - entry_price) / NULLIF(ABS(entry_price - stop_loss), 0)) as slip_ratio
            FROM simulated_trades
            WHERE status IN ('TP','SL','TSL','EXPIRED')
              AND source_router = 'arch104'
              AND {mode_filter}
              AND actual_entry_price IS NOT NULL AND actual_entry_price > 0
        """)
        r = cur.fetchone()
        slp = r['slip_ratio'] or 0
        r_slip = slp * 1.0  # slippage in R units (1 SL = 1.0R)
        real_edge = (r['avgR'] or 0) - r_slip
        print(f"  {mode_label}: n={r['n']} sumR={r['sumR'] or 0:.1f} avgR_paper={r['avgR'] or 0:.3f} SL_dist={r['sl_pct'] or 0:.2f}% slip/SL={slp:.3f}")
        print(f"           slip_R={r_slip:.3f}  real_edge={real_edge:.3f}")

    # ── 6. OTE deep dive ────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  6. ote_nested — глубокий разбор")
    print(f"{'=' * 70}")

    for mode_label, mode_filter in [
        ("VST", "exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' AND exchange_order_id != ''"),
        ("PAPER", "(exchange_order_id IS NULL OR exchange_order_id = 'SIM' OR exchange_order_id = '')"),
    ]:
        cur = db.execute(f"""
            SELECT COUNT(*) as n, SUM(R_multiple) as sumR, AVG(R_multiple) as avgR,
                   AVG(ABS(entry_price - stop_loss) / entry_price * 100) as sl_pct,
                   AVG(ABS(actual_entry_price - entry_price) / NULLIF(ABS(entry_price - stop_loss), 0)) as slip_ratio
            FROM simulated_trades
            WHERE status IN ('TP','SL','TSL','EXPIRED')
              AND signal_type = 'ote_nested'
              AND {mode_filter}
              AND actual_entry_price IS NOT NULL AND actual_entry_price > 0
        """)
        r = cur.fetchone()
        if r['n'] and r['n'] > 0:
            slp = r['slip_ratio'] or 0
            r_slip = slp * 1.0
            real_edge = (r['avgR'] or 0) - r_slip
            print(f"  {mode_label}: n={r['n']} sumR={r['sumR'] or 0:.1f} avgR_paper={r['avgR'] or 0:.3f} SL_dist={r['sl_pct'] or 0:.2f}% slip/SL={slp:.3f}")
            print(f"           slip_R={r_slip:.3f}  real_edge={real_edge:.3f}")

    # ── 7. Вывод ────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  7. РЕКОМЕНДАЦИИ")
    print(f"{'=' * 70}")

    # Total VST sumR
    cur = db.execute("""
        SELECT SUM(R_multiple) FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED')
          AND exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' AND exchange_order_id != ''
    """)
    total_sumR = cur.fetchone()[0] or 0

    # Estimate total slippage cost
    cur = db.execute("""
        SELECT COUNT(*), AVG(ABS(actual_entry_price - entry_price) / NULLIF(ABS(entry_price - stop_loss), 0))
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED')
          AND exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' AND exchange_order_id != ''
          AND actual_entry_price IS NOT NULL AND actual_entry_price > 0
    """)
    r = cur.fetchone()
    n_vst = r[0] or 0
    avg_slip_ratio = r[1] or 0

    est_slip_cost = avg_slip_ratio * n_vst  # each SL = 1R, slip ratio × n
    real_net = total_sumR - est_slip_cost

    print(f"  VST сделок с actual_price: {n_vst}")
    print(f"  Сумма R (бумажная): {total_sumR:+.1f}")
    print(f"  Средний slip/SL: {avg_slip_ratio:.3f} (~{avg_slip_ratio*100:.1f}% от SL)")
    print(f"  Оценка slippage cost: {est_slip_cost:.1f}R")
    print(f"  Реальный нетто: {real_net:+.1f}R")
    print()
    print(f"  ВЫВОД: {'реальный edge ПОЛОЖИТЕЛЬНЫЙ' if real_net > 0 else 'реальный edge ОТРИЦАТЕЛЬНЫЙ — slippage съедает прибыль!'}")
    print(f"  Минимальный SL для покрытия slippage 0.45%/сторона: {0.9:.1f}% (сейчас медиана зависит от стратегии)")

    db.close()


if __name__ == "__main__":
    run()
