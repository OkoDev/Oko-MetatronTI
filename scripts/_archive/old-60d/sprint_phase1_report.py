"""
Полный отчёт Sprint Phase 1+2 (DEV-184/185/186/187).
Запускать через ~72ч после рестарта 26.04.2026.

Использование:
    python scripts/sprint_phase1_report.py
    python scripts/sprint_phase1_report.py --since "2026-04-26 12:00"
"""
import sqlite3
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone


def open_db_with_retry(db_path, retries=10, delay=3):
    last_err = None
    for attempt in range(retries):
        try:
            conn = sqlite3.connect(str(db_path), timeout=15)
            conn.execute("PRAGMA busy_timeout=15000")
            conn.execute("SELECT 1").fetchone()
            return conn
        except sqlite3.OperationalError as e:
            last_err = e
            if attempt < retries - 1:
                print(f"  [retry {attempt+1}/{retries}] DB busy: {e}, wait {delay}s...")
                time.sleep(delay)
    raise RuntimeError(f"Не удалось открыть БД после {retries} попыток: {last_err}")

DEFAULT_RESTART = "2026-04-26T17:30"
DB = Path(__file__).parent.parent / "subscriptions.db"

# Pre-fix baseline (RE-AUDIT 25.04, post-fix>=2026-04-15 .. 2026-04-25):
PRE_FIX = {
    "SINGLE": -0.19,
    "DUAL_TP": -0.23,
    "DUAL_TSL": -0.61,
    "wt_signal_short_trend_up_avgR": -1.12,
    "wt_b_short_low_zone_avgR": -2.44,
    "p90_overshoot": 3.93,
    "vst_sl_avgR": -2.24,
    "pivot_reversal_avgR": -0.31,
}


def parse_args():
    since = DEFAULT_RESTART
    for i, arg in enumerate(sys.argv):
        if arg == "--since" and i + 1 < len(sys.argv):
            since = sys.argv[i + 1]
    return since


def main():
    since = parse_args()
    print("=" * 70)
    print("SPRINT PHASE 1+2 ПОЛНЫЙ ОТЧЁТ")
    print(f"Restart cutoff: {since}")
    print(f"Now: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)
    print()

    conn = open_db_with_retry(DB)
    cur = conn.cursor()

    # === 1. DEV-184 эффект — strategy_type performance ===
    print("=== 1. DEV-184 эффект (strategy_type post-restart) ===")
    print()
    cur.execute("""
        SELECT COALESCE(strategy_type,'NULL') st,
               COUNT(*) n,
               SUM(CASE WHEN status!='OPEN' THEN 1 ELSE 0 END) closed,
               ROUND(AVG(CASE WHEN status!='OPEN' THEN R_multiple END),3) avgR,
               ROUND(SUM(CASE WHEN R_multiple>0 THEN 1 ELSE 0 END)*100.0/
                     NULLIF(SUM(CASE WHEN status!='OPEN' THEN 1 END),0),1) WR
        FROM simulated_trades WHERE created_at >= ?
        GROUP BY strategy_type ORDER BY n DESC
    """, (since,))
    print("  {:12s} {:>5s} {:>7s} {:>8s} {:>6s}  pre-fix avgR".format(
        'strat', 'n', 'closed', 'avgR', 'WR'))
    for r in cur.fetchall():
        pre = PRE_FIX.get(r[0], "—")
        print("  {:12s} {:>5d} {:>7d} {:>8} {:>5}%  {}".format(
            r[0], r[1], r[2], r[3] or 0, r[4] or 0, pre))
    print()

    # === 2. DEV-186 эффект — wt_signal по regime ===
    print("=== 2. DEV-186 эффект (wt_signal × direction × regime) ===")
    cur.execute("""
        SELECT direction, regime, COUNT(*) n,
               ROUND(AVG(CASE WHEN status!='OPEN' THEN R_multiple END),2) avgR
        FROM simulated_trades
        WHERE signal_type='wt_signal' AND created_at >= ?
        GROUP BY direction, regime ORDER BY 3 DESC
    """, (since,))
    rows = cur.fetchall()
    if rows:
        print("  {:8s} {:14s} {:>5s} {:>7s}".format('dir','regime','n','avgR'))
        short_trend_up = 0
        for r in rows:
            print("  {:8s} {:14s} {:>5d} {:>7}".format(r[0], r[1] or '?', r[2], r[3] or 0))
            if r[0] == 'SHORT' and r[1] in ('TREND_UP', 'HIGH_VOL'):
                short_trend_up += r[2]
        print(f"  → SHORT в TREND_UP/HIGH_VOL: {short_trend_up} (pre-fix: 22+12=34)")
    else:
        print("  (нет wt_signal сделок post-restart)")
    print()

    # === 3. DEV-187 эффект — wt_b распределение по wt1_1h zone ===
    print("=== 3. DEV-187 эффект (wt_b × wt1_1h zone) ===")
    cur.execute("""
        SELECT id, direction, R_multiple, status, features_json
        FROM simulated_trades
        WHERE signal_type='wt_b_signal' AND created_at >= ?
        ORDER BY id DESC LIMIT 100
    """, (since,))
    rows = cur.fetchall()
    if rows:
        long_n = short_n = 0
        long_in_zone = short_in_zone = 0  # должно быть 0 если floor работает
        long_wins = short_wins = 0
        long_closed = short_closed = 0
        for r in rows:
            try:
                f = json.loads(r[4]) if r[4] else {}
                wt1_1h = f.get("htf_wt1_1h")
                if wt1_1h is None: continue
                if r[1] == "LONG":
                    long_n += 1
                    if wt1_1h > -30: long_in_zone += 1
                    if r[3] != 'OPEN':
                        long_closed += 1
                        if (r[2] or 0) > 0: long_wins += 1
                elif r[1] == "SHORT":
                    short_n += 1
                    if wt1_1h < 30: short_in_zone += 1
                    if r[3] != 'OPEN':
                        short_closed += 1
                        if (r[2] or 0) > 0: short_wins += 1
            except Exception: pass
        print(f"  LONG  n={long_n}, в N зоне (wt1_1h>-30): {long_in_zone}, WR={long_wins}/{long_closed}")
        print(f"  SHORT n={short_n}, в N зоне (wt1_1h<+30): {short_in_zone}, WR={short_wins}/{short_closed}")
        print(f"  → должно быть 0 в N зоне после DEV-187 floor")
    else:
        print("  (нет wt_b сделок post-restart)")
    print()

    # === 4. DEV-185 главное — overshoot distribution ===
    print("=== 4. DEV-185 эффект (VST SL overshoot distribution) ===")
    cur.execute("""
        SELECT id, symbol, direction, entry_price, stop_loss, exit_price, R_multiple, sl_source
        FROM simulated_trades
        WHERE status='SL'
          AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
          AND created_at >= ?
        ORDER BY id DESC
    """, (since,))
    rows = cur.fetchall()
    print(f"  Total VST SL post-restart: {len(rows)}")
    if rows:
        ovs = []
        for r in rows:
            tid, sym, dirn, entry, sl, exit_p, rmul, src = r
            if not (entry and sl and exit_p): continue
            if dirn == "LONG":
                ov = (sl - exit_p) / entry * 100
            else:
                ov = (exit_p - sl) / entry * 100
            ovs.append((tid, sym, ov, rmul or 0, src))

        buckets = {"0-0.5%": 0, "0.5-1%": 0, "1-2%": 0, "2-5%": 0, "5-10%": 0, "10%+": 0}
        for _,_, ov, _, _ in ovs:
            if ov < 0.5: buckets["0-0.5%"] += 1
            elif ov < 1: buckets["0.5-1%"] += 1
            elif ov < 2: buckets["1-2%"] += 1
            elif ov < 5: buckets["2-5%"] += 1
            elif ov < 10: buckets["5-10%"] += 1
            else: buckets["10%+"] += 1

        sorted_ovs = sorted([o[2] for o in ovs])
        p50 = sorted_ovs[len(sorted_ovs) // 2] if sorted_ovs else 0
        p90 = sorted_ovs[int(len(sorted_ovs) * 0.9)] if sorted_ovs else 0
        max_ov = max(sorted_ovs) if sorted_ovs else 0
        avg_r = sum(o[3] for o in ovs) / len(ovs) if ovs else 0

        print("  Distribution overshoot:")
        print(f"    {'bucket':12s} {'n':>4s}  baseline (pre-fix)")
        baseline = {"0-0.5%": 227, "0.5-1%": 21, "1-2%": 30, "2-5%": 48, "5-10%": 16, "10%+": 6}
        for b, n in buckets.items():
            print(f"    {b:12s} {n:>4d}  pre-fix: {baseline.get(b,'?')}")
        print(f"  p50={p50:.2f}% (pre 0.18%)  p90={p90:.2f}% (pre 3.93%)  max={max_ov:.2f}% (pre 62.6%)")
        print(f"  avgR VST SL = {avg_r:.2f} (pre-fix: -2.24)")

        catastrophic = [o for o in ovs if o[2] >= 5]
        if catastrophic:
            print(f"\n  ⚠️ Catastrophic ≥5% post-restart: {len(catastrophic)}")
            for tid, sym, ov, rmul, src in catastrophic[:10]:
                print(f"    #{tid} {sym} overshoot={ov:.1f}% R={rmul:.2f} sl_src={src}")
    print()

    # === 5. Cumulative R + WR (effective_status) ===
    print("=== 5. Cumulative R + Effective WR ===")
    cur.execute("""
        SELECT
            COUNT(*) total,
            SUM(CASE WHEN status!='OPEN' THEN 1 ELSE 0 END) closed,
            SUM(CASE WHEN status!='OPEN' THEN R_multiple END) sum_R,
            AVG(CASE WHEN status!='OPEN' THEN R_multiple END) avg_R,
            SUM(CASE WHEN status='TP' OR status='TSL' OR (status='SL' AND tsl_activated=1 AND R_multiple > 0.1) THEN 1 ELSE 0 END) eff_wins
        FROM simulated_trades WHERE created_at >= ?
    """, (since,))
    r = cur.fetchone()
    total, closed, sumR, avgR, eff_wins = r
    closed = closed or 0
    sumR = sumR or 0
    avgR = avgR or 0
    eff_wins = eff_wins or 0
    eff_wr = eff_wins / closed * 100 if closed else 0
    print(f"  total={total}, closed={closed}")
    print(f"  sum_R={sumR:.1f}  avgR={avgR:.3f}  effective_WR={eff_wr:.1f}%")
    print(f"  baseline (pre-fix 10 дней): avgR=-0.27..-0.50, sum_R≈-700R")
    print()

    # === 6. По signal_type — кто выигрывает/проигрывает ===
    print("=== 6. avgR / WR по signal_type post-restart ===")
    cur.execute("""
        SELECT signal_type, COUNT(*) n,
               ROUND(AVG(CASE WHEN status!='OPEN' THEN R_multiple END),2) avgR,
               ROUND(SUM(CASE WHEN R_multiple>0 THEN 1 ELSE 0 END)*100.0/
                     NULLIF(SUM(CASE WHEN status!='OPEN' THEN 1 END),0),1) WR
        FROM simulated_trades WHERE created_at >= ?
        GROUP BY signal_type ORDER BY n DESC LIMIT 10
    """, (since,))
    print("  {:20s} {:>5s} {:>7s} {:>6s}".format('signal_type','n','avgR','WR'))
    for r in cur.fetchall():
        print("  {:20s} {:>5d} {:>7} {:>5}%".format(r[0], r[1], r[2] or 0, r[3] or 0))
    print()

    # === Решения и рекомендации ===
    print("=" * 70)
    print("РЕКОМЕНДАЦИИ К РЕШЕНИЯМ")
    print("=" * 70)
    print()
    print("На основе данных выше — ответить на:")
    print()
    print("  [Q1] avgR pivot_reversal ≥ -0.10 (vs pre-fix -0.31)?")
    print("    → ДА → Фаза 1+2 успешна, переход к ARCH-100 финал")
    print("    → НЕТ → копать что не сработало, пересматривать pivot_reversal SHORT TREND_DOWN")
    print()
    print("  [Q2] p90 overshoot ≤ 2.0% (vs pre-fix 3.93%)?")
    print("    → ДА → можно поднимать buffer 1.0 → 2.0 (DEV-185 шаг 2)")
    print("    → НЕТ → разбираться почему STOP-LIMIT не защищает (формат limit-цены?)")
    print()
    print("  [Q3] есть ли non-execution инциденты (OPEN >24ч после рестарта)?")
    print("    SQL: SELECT id, symbol, created_at FROM simulated_trades")
    print("         WHERE status='OPEN' AND created_at >= ? + interval 24h")
    print("    → если ДА — DEV-185.2 watchdog нужен срочно")
    print()
    print("  [Q4] avgR ≥ +0.10 общий (выход в +)?")
    print("    → ДА → поздравляем, спринт успешен. ARCH-100 финальный re-audit.")
    print("    → НЕТ → Фаза 3 спринта (DEV-188 pivot_reversal SHORT TREND_DOWN gate)")

    conn.close()


if __name__ == "__main__":
    main()
