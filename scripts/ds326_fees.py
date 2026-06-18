"""DS-326: комиссия и PnL для базы 1h→15m ADX<25.
Комиссия в R = round_trip_fee / sl_dist_pct (не зависит от плеча, только от ширины SL).
BingX taker 0.05% → round-trip 0.10%. Risk-based sizing: 1R = risk_pct% equity (const $).
"""
import sys, os, warnings, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")
import numpy as np
from pathlib import Path

import backtest_wt_b_ltf_entry as bt
from backtest_wt_b_ltf_entry import simulate_trade

RT_TAKER = 0.0010      # 0.10% round-trip (taker вход + taker выход) — консервативно
RT_MIXED = 0.0007      # 0.07% (taker вход 0.05% + maker выход 0.02%) — если TP лимиткой
SLIP_RT = 0.0004       # 0.04% round-trip проскальзывание (0.02% × 2), оценка
RR = 3.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-sl", type=float, default=None, help="патч MIN_SL_PCT (прод=0.005)")
    ap.add_argument("--max-sl", type=float, default=None, help="патч MAX_SL_PCT (прод=0.02)")
    a = ap.parse_args()
    if a.min_sl is not None:
        bt.MIN_SL_PCT = a.min_sl
    if a.max_sl is not None:
        bt.MAX_SL_PCT = a.max_sl
    print(f"SL-границы: MIN={bt.MIN_SL_PCT*100:.2f}% MAX={bt.MAX_SL_PCT*100:.2f}%\n")

    from ds326_edge_levers import collect_entries  # импорт после возможного патча констант
    syms = sorted(set(p.stem for p in Path("data/history/1h").glob("*.parquet")) &
                  set(p.stem for p in Path("data/history/15m").glob("*.parquet")))[:45]
    ents = []
    for s in syms:
        ents += collect_entries(s)
    print(f"Сделок ADX<25 (1h→15m): {len(ents)}\n")

    recs = []
    for e in ents:
        gross = simulate_trade(e["df15m"], e["entry_ts"], e["entry"], e["sl"], e["direction"], RR, use_tsl=True)
        sl_dist = abs(e["entry"] - e["sl"]) / e["entry"]
        recs.append({"dir": e["direction"], "div": e["div"], "gross": gross, "sl_dist": sl_dist,
                     "comm_taker": RT_TAKER / sl_dist, "comm_mixed": RT_MIXED / sl_dist,
                     "slip": SLIP_RT / sl_dist,
                     "comm_floor": RT_TAKER / max(sl_dist, 0.005)})  # прод SL-floor 0.5%

    def agg(rows, label):
        if not rows:
            print(f"{label}: n=0"); return
        g = np.array([r["gross"] for r in rows])
        ct = np.array([r["comm_taker"] for r in rows])
        cm = np.array([r["comm_mixed"] for r in rows])
        sl = np.array([r["slip"] for r in rows])
        sd = np.array([r["sl_dist"] for r in rows]) * 100
        cf = np.array([r["comm_floor"] for r in rows])
        net_t = g - ct
        net_m = g - cm
        net_ts = g - ct - sl
        net_floor = g - cf
        print(f"── {label} (n={len(rows)}) ──")
        print(f"  ср. SL-дистанция:        {sd.mean():.2f}%  (медиана {np.median(sd):.2f}%)")
        print(f"  комиссия/сделку (R):     taker {ct.mean():+.3f}R | mixed {cm.mean():+.3f}R | +slip {(ct+sl).mean():+.3f}R")
        print(f"  GROSS avgR:              {g.mean():+.3f}  WR {(g>0).mean()*100:.1f}%")
        print(f"  NET avgR (taker 0.10%):  {net_t.mean():+.3f}  WR {(net_t>0).mean()*100:.1f}%")
        print(f"  NET avgR (mixed 0.07%):  {net_m.mean():+.3f}")
        print(f"  NET avgR (SL-floor 0.5%):{net_floor.mean():+.3f}  (прод min_sl, комиссия only)")
        print(f"  NET avgR (taker+slip):   {net_ts.mean():+.3f}")
        return net_t.mean(), net_m.mean(), len(rows)

    all_net = agg(recs, "ALL")
    print()
    short_net = agg([r for r in recs if r["dir"] == "SHORT"], "SHORT")
    print()
    agg([r for r in recs if r["dir"] == "SHORT" and 5 < r["div"] <= 12], "COMBO SHORT+div5-12")

    # ── PnL в $ ──
    print("\n── PnL ($), risk-based: 1R = risk_pct% equity ──")
    n_all = all_net[2]
    for eq, tag in ((710.0, "deposit_usdt"), (316.0, "реальный equity")):
        risk = eq * 0.01  # risk_pct=1%
        print(f"  equity ${eq:.0f} ({tag}), risk 1% = ${risk:.2f}/сделку (1R):")
        for lbl, net in (("GROSS", np.mean([r['gross'] for r in recs])),
                         ("NET taker", all_net[0]), ("NET mixed", all_net[1])):
            pnl_total = net * n_all * risk
            print(f"     {lbl:10s}: {net:+.3f}R/сделку → ${net*risk:+.2f}/сделку → ${pnl_total:+.1f} за {n_all} сделок (2.5 года)")


if __name__ == "__main__":
    main()
