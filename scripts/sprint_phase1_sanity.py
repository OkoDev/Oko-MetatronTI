"""
Sanity check для Sprint Phase 1+2 (DEV-184/185/186/187).
Запускать через ~24ч после рестарта 26.04.2026.

Использование:
    python scripts/sprint_phase1_sanity.py
    python scripts/sprint_phase1_sanity.py --since "2026-04-26 12:00"
"""
import sqlite3
import sys
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path


def open_db_with_retry(db_path, retries=10, delay=3):
    """Бот активно пишет в БД — нужны ретраи на disk I/O."""
    last_err = None
    for attempt in range(retries):
        try:
            conn = sqlite3.connect(str(db_path), timeout=15)
            conn.execute("PRAGMA busy_timeout=15000")
            # пробуем простой SELECT для проверки
            conn.execute("SELECT 1").fetchone()
            return conn
        except sqlite3.OperationalError as e:
            last_err = e
            if attempt < retries - 1:
                print(f"  [retry {attempt+1}/{retries}] DB busy: {e}, wait {delay}s...")
                time.sleep(delay)
    raise RuntimeError(f"Не удалось открыть БД после {retries} попыток: {last_err}")

# ВАЖНО: формат ISO с 'T' между датой и временем — БД пишет именно так.
# Лексикографическое сравнение требует одинакового формата.
DEFAULT_RESTART = "2026-04-26T17:30"
DB = Path(__file__).parent.parent / "subscriptions.db"


def parse_args():
    since = DEFAULT_RESTART
    for i, arg in enumerate(sys.argv):
        if arg == "--since" and i + 1 < len(sys.argv):
            since = sys.argv[i + 1]
    return since


def main():
    since = parse_args()
    print(f"=== SPRINT PHASE 1+2 SANITY CHECK ===")
    print(f"Restart cutoff: {since}")
    print(f"Time now: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    conn = open_db_with_retry(DB)
    cur = conn.cursor()

    flags = {"GREEN": [], "YELLOW": [], "RED": []}

    # ---- DEV-184: DUAL_TSL отключение ----
    print("--- DEV-184: DUAL_TSL distribution ---")
    cur.execute("""
        SELECT COALESCE(strategy_type, 'NULL'), COUNT(*)
        FROM simulated_trades
        WHERE created_at >= ?
        GROUP BY strategy_type ORDER BY 2 DESC
    """, (since,))
    rows = cur.fetchall()
    dual_tsl_n = 0
    for st, n in rows:
        print(f"  {st:12s}  n={n}")
        if st == "DUAL_TSL":
            dual_tsl_n = n
    if dual_tsl_n == 0:
        flags["GREEN"].append("DEV-184: 0 DUAL_TSL сделок post-restart")
    else:
        flags["RED"].append(f"DEV-184 ПРОБОЙ: {dual_tsl_n} DUAL_TSL сделок post-restart (config не применился?)")
    print()

    # ---- DEV-186: wt_signal SHORT в TREND_UP/HIGH_VOL ----
    print("--- DEV-186: wt_signal SHORT в TREND_UP/HIGH_VOL ---")
    cur.execute("""
        SELECT regime, COUNT(*)
        FROM simulated_trades
        WHERE signal_type='wt_signal' AND direction='SHORT'
          AND regime IN ('TREND_UP','HIGH_VOL')
          AND created_at >= ?
        GROUP BY regime
    """, (since,))
    rows = cur.fetchall()
    blocked_count = 0
    for reg, n in rows:
        print(f"  {reg:12s}  n={n}")
        blocked_count += n
    if blocked_count == 0:
        flags["GREEN"].append("DEV-186: 0 wt_signal SHORT в TREND_UP/HIGH_VOL post-restart")
    else:
        flags["YELLOW"].append(f"DEV-186 НЕ работает: {blocked_count} сделок прошли gate")
    print()

    # ---- DEV-187: wt_b сделки и их wt1_1h ----
    print("--- DEV-187: wt_b сделки post-restart (проверка floor) ---")
    cur.execute("""
        SELECT id, direction, regime, R_multiple, features_json
        FROM simulated_trades
        WHERE signal_type='wt_b_signal'
          AND created_at >= ?
        ORDER BY id DESC LIMIT 20
    """, (since,))
    rows = cur.fetchall()
    print(f"  Всего wt_b post-restart: {len(rows)}")
    in_floor_zone = 0
    for r in rows:
        try:
            f = json.loads(r[4]) if r[4] else {}
            wt1_1h = f.get("htf_wt1_1h")
            if wt1_1h is None:
                continue
            direction = r[1]
            if direction == "LONG" and wt1_1h > -30:
                in_floor_zone += 1
                print(f"  ⚠️  #{r[0]} LONG wt1_1h={wt1_1h:.1f} > -30 (floor должен был блокировать!)")
            elif direction == "SHORT" and wt1_1h < 30:
                in_floor_zone += 1
                print(f"  ⚠️  #{r[0]} SHORT wt1_1h={wt1_1h:.1f} < +30 (floor должен был блокировать!)")
        except Exception:
            pass
    if in_floor_zone == 0:
        flags["GREEN"].append(f"DEV-187: floor работает ({len(rows)} wt_b сделок, все за порогом)")
    else:
        flags["YELLOW"].append(f"DEV-187: {in_floor_zone}/{len(rows)} сделок прошли floor — проверить config/код")
    print()

    # ---- DEV-185: STOP-LIMIT distribution + overshoot ----
    print("--- DEV-185: VST SL сделки post-restart ---")
    cur.execute("""
        SELECT id, symbol, direction, entry_price, stop_loss, exit_price, R_multiple
        FROM simulated_trades
        WHERE status='SL'
          AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
          AND created_at >= ?
        ORDER BY id DESC
    """, (since,))
    rows = cur.fetchall()
    print(f"  Всего VST SL post-restart: {len(rows)}")

    if rows:
        overshoots = []
        for r in rows:
            tid, sym, dirn, entry, sl, exit_p, rmul = r
            if not (entry and sl and exit_p):
                continue
            if dirn == "LONG":
                ov = (sl - exit_p) / entry * 100
            else:
                ov = (exit_p - sl) / entry * 100
            overshoots.append((tid, sym, ov, rmul or 0))

        # Buckets
        buckets = {"0-0.5%": 0, "0.5-1%": 0, "1-2%": 0, "2-5%": 0, "5-10%": 0, "10%+": 0}
        for _, _, ov, _ in overshoots:
            if ov < 0.5: buckets["0-0.5%"] += 1
            elif ov < 1: buckets["0.5-1%"] += 1
            elif ov < 2: buckets["1-2%"] += 1
            elif ov < 5: buckets["2-5%"] += 1
            elif ov < 10: buckets["5-10%"] += 1
            else: buckets["10%+"] += 1
        print("  Distribution overshoot:")
        for b, n in buckets.items():
            print(f"    {b:8s}  n={n}")

        # p90
        ovs_sorted = sorted([o[2] for o in overshoots])
        p90 = ovs_sorted[int(len(ovs_sorted) * 0.9)] if ovs_sorted else 0
        avg_r = sum(o[3] for o in overshoots) / len(overshoots) if overshoots else 0
        print(f"  p90 overshoot = {p90:.2f}% (pre-fix: 3.93%)")
        print(f"  avgR VST SL  = {avg_r:.2f} (pre-fix: -2.24)")

        catastrophic = [o for o in overshoots if o[2] >= 5]
        if catastrophic:
            print(f"  ⚠️  Catastrophic overshoot ≥5% ({len(catastrophic)} сделок):")
            for tid, sym, ov, rmul in catastrophic[:5]:
                print(f"    #{tid} {sym} overshoot={ov:.1f}% R={rmul:.2f}")

        if len(rows) >= 5:
            if p90 < 2.0:
                flags["GREEN"].append(f"DEV-185: p90 overshoot {p90:.2f}% (pre-fix 3.93%) — buffer работает")
            elif p90 < 3.0:
                flags["YELLOW"].append(f"DEV-185: p90 overshoot {p90:.2f}% — улучшение есть, но осталось > 2%")
            else:
                flags["RED"].append(f"DEV-185: p90 overshoot {p90:.2f}% — buffer не работает или config не применился")
    else:
        print("  (мало данных для distribution overshoot — нужно >=5 SL)")
        flags["YELLOW"].append(f"DEV-185: только {len(rows)} VST SL сделок — недостаточно для оценки overshoot")
    print()

    # ---- Cumulative R ----
    print("--- Cumulative R post-restart ---")
    cur.execute("""
        SELECT
            COUNT(*) total,
            SUM(CASE WHEN status!='OPEN' THEN 1 ELSE 0 END) closed,
            ROUND(SUM(CASE WHEN status!='OPEN' THEN R_multiple END),1) sum_R,
            ROUND(AVG(CASE WHEN status!='OPEN' THEN R_multiple END),3) avg_R,
            SUM(CASE WHEN status!='OPEN' AND R_multiple > 0 THEN 1 ELSE 0 END) wins
        FROM simulated_trades
        WHERE created_at >= ?
    """, (since,))
    r = cur.fetchone()
    closed = r[1] or 0
    print(f"  total={r[0]}, closed={closed}, sum_R={r[2] or 0}, avgR={r[3] or 0}")
    if closed > 0:
        wr = (r[4] or 0) / closed * 100
        print(f"  WR={wr:.1f}% (target ≥30%)")
    print()

    # ---- ИТОГ ----
    print("=" * 60)
    if flags["RED"]:
        overall = "🔴 RED"
    elif flags["YELLOW"]:
        overall = "🟡 YELLOW"
    else:
        overall = "🟢 GREEN"
    print(f"FLAG: {overall}")
    print()
    for level in ["RED", "YELLOW", "GREEN"]:
        for msg in flags[level]:
            print(f"  [{level}] {msg}")

    conn.close()
    return 0 if not flags["RED"] else 1


if __name__ == "__main__":
    sys.exit(main())
