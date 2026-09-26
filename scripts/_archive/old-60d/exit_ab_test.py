"""
scripts/exit_ab_test.py — Full Exit Strategy A/B Test
ARCH-113 research: compare all exit strategies on closed trades.

Strategies tested:
  A. Current (actual R_multiple as-is)
  B. Single TP at fixed R levels (0.5 / 1.0 / 1.5 / 2.0 / 3.0)
  C. Double TP 50/50 combinations
  D. TSL activated vs not (real data split)
  E. Real strategy_type breakdown (SINGLE / DUAL_TP / TRIPLE_TP_TSL / DUAL_TSL)

Segments:
  - regime (RANGE / TREND_UP / TREND_DOWN / HIGH_VOL)
  - signal_type top groups
  - tp_source groups
  - sl_source groups
  - best combinations
"""
import sqlite3
import statistics
import sys
import os

DB = "subscriptions.db"
ERA = "2026-04-15"


def load_trades(conn):
    c = conn.cursor()
    c.execute("""
        SELECT
            id, direction, entry_price, stop_loss,
            max_price, min_price, R_multiple, status,
            tsl_activated, created_at, strategy_name, strategy_type,
            tp_source, sl_source, regime, signal_type, timeframe
        FROM simulated_trades
        WHERE status NOT IN ('OPEN','UNKNOWN')
        AND R_multiple IS NOT NULL
        AND entry_price IS NOT NULL AND stop_loss IS NOT NULL
        AND max_price IS NOT NULL AND min_price IS NOT NULL
        AND ABS(entry_price - stop_loss) > 0
    """)
    rows = c.fetchall()
    trades = []
    for r in rows:
        (tid, direction, entry, sl,
         max_p, min_p, r_mult, status,
         tsl_act, created_at, strat_name, strat_type,
         tp_src, sl_src, regime, sig_type, tf) = r
        sl_dist = abs(entry - sl)
        if sl_dist <= 0:
            continue
        if direction == 'LONG':
            max_r = (max_p - entry) / sl_dist
        else:
            max_r = (entry - min_p) / sl_dist
        trades.append({
            'direction': direction,
            'max_r': max_r,
            'r_actual': r_mult,
            'status': status,
            'tsl_activated': bool(tsl_act),
            'created_at': created_at or '',
            'strategy_type': strat_type or 'UNKNOWN',
            'tp_source': tp_src or '',
            'sl_source': sl_src or '',
            'regime': regime or 'UNKNOWN',
            'signal_type': sig_type or '',
        })
    return trades


def era(trades):
    return [t for t in trades if t['created_at'] >= ERA]


def sim_single_tp(trades, tp_r):
    return [tp_r if t['max_r'] >= tp_r else t['r_actual'] for t in trades]


def sim_double_tp(trades, tp1_r, tp2_r):
    rs = []
    for t in trades:
        if t['max_r'] >= tp1_r:
            h1 = tp1_r * 0.5
            h2 = (tp2_r if t['max_r'] >= tp2_r else t['r_actual']) * 0.5
            rs.append(h1 + h2)
        else:
            rs.append(t['r_actual'])
    return rs


def sim_be_then_tp(trades, be_trigger_r, tp_r):
    """Move SL to BE after be_trigger_r; then close at tp_r or 0 (BE)."""
    rs = []
    for t in trades:
        if t['max_r'] >= be_trigger_r:
            # SL moved to BE=0R
            if t['max_r'] >= tp_r:
                rs.append(tp_r)
            else:
                # Would have been stopped at BE or original exit
                actual = t['r_actual']
                rs.append(max(0.0, actual))
        else:
            rs.append(t['r_actual'])
    return rs


def stats(rs):
    n = len(rs)
    if n < 5:
        return None
    avg = sum(rs) / n
    wins = sum(1 for r in rs if r > 0)
    med = statistics.median(rs)
    return {'n': n, 'avg_R': avg, 'median_R': med, 'WR_pct': wins / n * 100}


def fmt(s, name):
    if s is None:
        return f"  {name:<36s}  n=  <5 — skip"
    return (f"  {name:<36s}  n={s['n']:5d}  "
            f"avg={s['avg_R']:+.3f}R  "
            f"med={s['median_R']:+.3f}R  "
            f"WR={s['WR_pct']:5.1f}%")


def section(title):
    print()
    print("=" * 75)
    print(f"  {title}")
    print("=" * 75)


def reach_table(trades, header=""):
    n = len(trades)
    if n < 5:
        return
    if header:
        print(f"  {header}")
    for r_lvl in [0.3, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0]:
        cnt = sum(1 for t in trades if t['max_r'] >= r_lvl)
        pct = cnt / n * 100
        print(f"    max_R >= {r_lvl:.1f}R:  {pct:5.1f}%  ({cnt}/{n})")


def compare_all_strategies(trades, label=""):
    if label:
        print(f"\n  [{label}]  n={len(trades)}")
    print(fmt(stats([t['r_actual'] for t in trades]), "A. Current (actual)"))
    for tp in [0.5, 1.0, 1.5, 2.0, 3.0]:
        print(fmt(stats(sim_single_tp(trades, tp)), f"B. Single TP={tp:.1f}R"))
    for tp1, tp2 in [(0.5, 2.0), (1.0, 3.0), (1.0, 4.0), (1.5, 4.0)]:
        print(fmt(stats(sim_double_tp(trades, tp1, tp2)), f"C. Double {tp1}/{tp2}R (50/50)"))
    for be, tp in [(0.5, 2.0), (1.0, 3.0)]:
        print(fmt(stats(sim_be_then_tp(trades, be, tp)), f"E. BE@{be}R then TP@{tp}R"))

    tsl_on  = [t['r_actual'] for t in trades if t['tsl_activated']]
    tsl_off = [t['r_actual'] for t in trades if not t['tsl_activated']]
    print(fmt(stats(tsl_on),  "D. TSL activated"))
    print(fmt(stats(tsl_off), "D. TSL NOT activated"))


def run():
    conn = sqlite3.connect(DB)
    all_trades = load_trades(conn)
    era_trades = era(all_trades)

    print(f"Loaded {len(all_trades)} trades total, {len(era_trades)} post-{ERA}")

    # ── 1. Baseline: all vs post-era ─────────────────────────────────────────
    section("1. BASELINE: ALL vs POST-ERA")
    compare_all_strategies(all_trades, f"ALL ({len(all_trades)})")
    compare_all_strategies(era_trades, f"POST-{ERA} ({len(era_trades)})")

    # ── 2. Reach rate ─────────────────────────────────────────────────────────
    section("2. REACH RATE (post-era)")
    reach_table(era_trades)

    # ── 3. Real strategy_type breakdown ──────────────────────────────────────
    section("3. REAL STRATEGY_TYPE (post-era, actual R)")
    from collections import defaultdict
    by_st = defaultdict(list)
    for t in era_trades:
        by_st[t['strategy_type']].append(t)
    for st, grp in sorted(by_st.items(), key=lambda x: -len(x[1])):
        compare_all_strategies(grp, f"strategy_type={st}")

    # ── 4. By regime ─────────────────────────────────────────────────────────
    section("4. BY REGIME (post-era)")
    by_reg = defaultdict(list)
    for t in era_trades:
        by_reg[t['regime']].append(t)
    for reg in ['TREND_UP', 'TREND_DOWN', 'RANGE', 'HIGH_VOL']:
        grp = by_reg.get(reg, [])
        if len(grp) >= 30:
            compare_all_strategies(grp, f"regime={reg}")
            reach_table(grp)

    # ── 5. By signal_type ─────────────────────────────────────────────────────
    section("5. BY SIGNAL_TYPE (post-era)")
    by_sig = defaultdict(list)
    for t in era_trades:
        by_sig[t['signal_type']].append(t)
    for sig, grp in sorted(by_sig.items(), key=lambda x: -len(x[1])):
        if len(grp) >= 50:
            compare_all_strategies(grp, f"signal_type={sig}")

    # ── 6. By tp_source groups ────────────────────────────────────────────────
    section("6. BY TP_SOURCE GROUP (post-era)")
    def tp_group(src):
        if not src:
            return 'unknown'
        if src.startswith('pivot_1D'):
            return 'pivot_1D'
        if src.startswith('pivot_1W') or src.startswith('pivot_1M'):
            return 'pivot_weekly+'
        if 'atr' in src:
            return 'atr_based'
        if src == 'tsl_only':
            return 'tsl_only'
        if src.startswith('rr_'):
            return 'rr_fixed'
        return 'other'

    by_tpg = defaultdict(list)
    for t in era_trades:
        by_tpg[tp_group(t['tp_source'])].append(t)
    for grp_name, grp in sorted(by_tpg.items(), key=lambda x: -len(x[1])):
        if len(grp) >= 30:
            compare_all_strategies(grp, f"tp_source_group={grp_name}")

    # ── 7. By sl_source groups ────────────────────────────────────────────────
    section("7. BY SL_SOURCE GROUP (post-era)")
    def sl_group(src):
        if not src:
            return 'unknown'
        if 'tsl_line' in src or 'wl_pivot_tsl' in src:
            return 'tsl_line'
        if src.startswith('atr_trendline'):
            return 'atr_trendline'
        if 'atr' in src:
            return 'atr_fixed'
        if 'pivot' in src or 'range_bounce' in src:
            return 'pivot_based'
        return 'other'

    by_slg = defaultdict(list)
    for t in era_trades:
        by_slg[sl_group(t['sl_source'])].append(t)
    for grp_name, grp in sorted(by_slg.items(), key=lambda x: -len(x[1])):
        if len(grp) >= 30:
            compare_all_strategies(grp, f"sl_source_group={grp_name}")

    # ── 8. Best combinations (strategy_type × regime) ────────────────────────
    section("8. BEST COMBO: strategy_type x regime (post-era, actual R)")
    combo = defaultdict(list)
    for t in era_trades:
        combo[(t['strategy_type'], t['regime'])].append(t)
    rows = []
    for (st, reg), grp in combo.items():
        s = stats([t['r_actual'] for t in grp])
        if s and s['n'] >= 20:
            rows.append((s['avg_R'], st, reg, s))
    rows.sort(reverse=True)
    for avg_r, st, reg, s in rows[:20]:
        print(fmt(s, f"{st} x {reg}"))

    # ── 9. Signal quality: with vs without FVG magnet proxy ──────────────────
    section("9. TP_SOURCE PIVOT_1D vs ATR_BASED vs RR_FIXED (post-era actual R)")
    grp_labels = {
        'pivot_1D':     [t for t in era_trades if tp_group(t['tp_source']) == 'pivot_1D'],
        'atr_based':    [t for t in era_trades if tp_group(t['tp_source']) == 'atr_based'],
        'rr_fixed':     [t for t in era_trades if tp_group(t['tp_source']) == 'rr_fixed'],
        'tsl_only':     [t for t in era_trades if tp_group(t['tp_source']) == 'tsl_only'],
    }
    for lbl, grp in grp_labels.items():
        s = stats([t['r_actual'] for t in grp])
        print(fmt(s, f"tp_source={lbl}"))
        reach_table(grp)

    # ── 10. Single best config per regime ─────────────────────────────────────
    section("10. BEST SIMULATED EXIT PER REGIME (post-era)")
    strategies_to_test = [
        ("Current",       lambda ts: [t['r_actual'] for t in ts]),
        ("Single_0.5R",   lambda ts: sim_single_tp(ts, 0.5)),
        ("Single_1.0R",   lambda ts: sim_single_tp(ts, 1.0)),
        ("Single_2.0R",   lambda ts: sim_single_tp(ts, 2.0)),
        ("Double_1/3R",   lambda ts: sim_double_tp(ts, 1.0, 3.0)),
        ("Double_1/4R",   lambda ts: sim_double_tp(ts, 1.0, 4.0)),
        ("BE0.5+TP2.0",   lambda ts: sim_be_then_tp(ts, 0.5, 2.0)),
        ("BE1.0+TP3.0",   lambda ts: sim_be_then_tp(ts, 1.0, 3.0)),
    ]
    for reg in ['TREND_UP', 'TREND_DOWN', 'RANGE', 'HIGH_VOL']:
        grp = by_reg.get(reg, [])
        if len(grp) < 30:
            continue
        print(f"\n  regime={reg} (n={len(grp)})")
        results = []
        for name, fn in strategies_to_test:
            s = stats(fn(grp))
            if s:
                results.append((s['avg_R'], name, s))
        results.sort(reverse=True)
        for avg_r, name, s in results:
            marker = " <-- BEST" if avg_r == results[0][0] else ""
            print(fmt(s, name) + marker)

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    run()
