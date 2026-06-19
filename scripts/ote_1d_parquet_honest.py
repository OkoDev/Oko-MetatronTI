# -*- coding: utf-8 -*-
"""Честный 1D backtest на data/history/*.parquet (46 пар × 868 1D-баров).
Валидирует edge 1D-сетапов без API, без ограничений.
"""
import os, sys, argparse
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd, numpy as np
from core.smc.ote_signal_generator import OTESignalGenerator

FEE = 0.0005


def simulate(fut, entry, sl, tp_runner, direction):
    one_r = abs(entry - sl)
    if one_r <= 0 or len(fut) == 0: return None
    long = direction == "long"
    rr = abs(tp_runner - entry) / one_r
    tp1 = entry + one_r if long else entry - one_r
    hit = False; be = entry
    for hi, lo in zip(fut["high"].values, fut["low"].values):
        if not hit:
            if (long and lo <= sl) or (not long and hi >= sl): return -1.0
            if (long and hi >= tp1) or (not long and lo <= tp1): hit = True
        else:
            if (long and lo <= be) or (not long and hi >= be): return 0.5
            if (long and hi >= tp_runner) or (not long and lo <= tp_runner): return 0.5 + 0.5 * rr
    last = fut["close"].values[-1]
    r = (last - entry) / one_r if long else (entry - last) / one_r
    return (0.5 + 0.5 * r) if hit else r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=46)
    args = ap.parse_args()

    parquets = sorted(Path("data/history/1h").glob("*.parquet"))[:args.pairs]
    gen = OTESignalGenerator()
    print(f"Честный 1D backtest: {len(parquets)} пар из data/history/")

    all_r = []; total_fire = 0

    for pq in parquets:
        sym = pq.stem
        dfs = {}
        for tf in ["5m", "15m", "1h"]:
            p = Path(f"data/history/{tf}/{sym}.parquet")
            if p.exists():
                dfs[tf] = pd.read_parquet(p)
        if "1h" not in dfs or "15m" not in dfs:
            continue

        # Resample 1h → 1D
        b = dfs["1h"]
        dfs["1d"] = pd.DataFrame({
            "open": b["open"].resample("1D").first(),
            "high": b["high"].resample("1D").max(),
            "low": b["low"].resample("1D").min(),
            "close": b["close"].resample("1D").last()
        }).dropna()

        df1h = dfs["1h"]; step = 24; fire = 0
        for i in range(50, len(df1h) - 5, step):
            t = df1h.index[i]
            sl = {tf: df[df.index <= t].tail(1500) for tf, df in dfs.items()}
            if len(sl.get("1h", [])) < 30:
                continue
            try:
                sigs = gen.generate(sym, sl)
            except Exception:
                continue
            for sg in sigs:
                if sg.status != "FIRE":
                    continue
                if sg.htf != "1d":
                    continue
                fut = df1h.iloc[i+1 : min(i+1+48, len(df1h))]
                R = simulate(fut, sg.entry, sg.sl, sg.tp_runner, sg.direction)
                if R is None:
                    continue
                sf = abs(sg.entry - sg.sl) / sg.entry if sg.entry else 0.01
                fr = (FEE * 2 / sf) if sf > 0 else 1.0
                all_r.append({"R": R, "net": R - fr, "ltf": sg.ltf, "sl%": sf * 100, "sym": sym})
                fire += 1

        if fire > 0:
            print(f"  {sym:15s} FIRE={fire}")
        total_fire += fire

    print(f"\n=== 1D→* честный результат ({len(parquets)} пар) ===")
    if not all_r:
        print("НЕТ сделок — 1D сетапы не фирят даже на 868 барах")
        return

    rs = np.array([r["R"] for r in all_r])
    nets = np.array([r["net"] for r in all_r])
    wr = np.mean(rs > 0) * 100
    sl_med = np.median([r["sl%"] for r in all_r])

    print(f"Всего FIRE: {len(rs)}")
    print(f"GROSS avgR: {np.mean(rs):+.3f}  median: {np.median(rs):+.3f}  WR: {wr:.0f}%")
    print(f"NET  avgR:  {np.mean(nets):+.3f}")
    print(f"SL   median: {sl_med:.2f}%")
    print(f"FEE  avgR:   {np.mean([r['net']-r['R'] for r in all_r]):.3f}")

    # По LTF
    print(f"\nПо LTF:")
    by_ltf = {}
    for r in all_r:
        ltf = r.get("ltf", "?")
        by_ltf.setdefault(ltf, []).append(r)
    for ltf, vals in sorted(by_ltf.items(), key=lambda x: -np.mean([v["R"] for v in x[1]])):
        avg = np.mean([v["R"] for v in vals])
        net = np.mean([v["net"] for v in vals])
        wr_ltf = np.mean([v["R"] for v in vals] > 0) * 100
        print(f"  {ltf}: n={len(vals):4d} GROSS={avg:+.3f}R NET={net:+.3f}R WR={wr_ltf:.0f}%")

    print(f"\nСравнение с ote_setups.yaml (pre-fake-R):")
    print(f"  1d_1h_pull: pre=+0.710  honest={np.mean([r['R'] for r in all_r if r.get('ltf')=='1h']):+.3f}")
    print(f"  1d_15m_pull: pre=+0.701 honest={np.mean([r['R'] for r in all_r if r.get('ltf')=='15m']):+.3f}")


if __name__ == "__main__":
    main()
