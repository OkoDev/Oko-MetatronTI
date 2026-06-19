# -*- coding: utf-8 -*-
"""Честный перепрогон 1D→1H pull через OTESignalGenerator + data_collector (без parquet).
Даат: дать честный net 1D-комбо с прод-SL + прод-fee. БЕЗ pre-computed чисел из ote_setups.yaml.
"""
import asyncio, os, sys, argparse, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd, numpy as np
from core.smc.ote_signal_generator import OTESignalGenerator
from core.infra.data_collector import RealTimeData

FEE_TAKER = 0.0005  # BingX taker


def simulate(fut, entry, sl, tp_runner, direction):
    one_r = abs(entry - sl)
    if one_r <= 0 or len(fut) == 0: return None
    long = direction == "long"
    runner_R = abs(tp_runner - entry) / one_r
    tp1 = entry + one_r if long else entry - one_r
    hit_tp1 = False; be = entry
    for hi, lo in zip(fut["high"].values, fut["low"].values):
        if not hit_tp1:
            if (long and lo <= sl) or (not long and hi >= sl): return -1.0
            if (long and hi >= tp1) or (not long and lo <= tp1): hit_tp1 = True
        else:
            if (long and lo <= be) or (not long and hi >= be): return 0.5
            if (long and hi >= tp_runner) or (not long and lo <= tp_runner): return 0.5 + 0.5 * runner_R
    last = fut["close"].values[-1]
    rr = (last - entry) / one_r if long else (entry - last) / one_r
    return (0.5 + 0.5 * rr) if hit_tp1 else rr


async def load_ohlcv(rt, sym, days):
    dfs = {}
    # 1D � �������� (200 ����� > 50 ������)
    df1d = await rt.get_ohlcv(sym, timeframe="1d", limit=200)
    if df1d is not None and not df1d.empty:
        if not isinstance(df1d.index, pd.DatetimeIndex):
            df1d.index = pd.to_datetime(df1d.index, unit='ms')
        dfs["1d"] = df1d
    # 1H (max 1000)
    df1h = await rt.get_ohlcv(sym, timeframe="1h", limit=1000)
    if df1h is not None and not df1h.empty:
        if not isinstance(df1h.index, pd.DatetimeIndex):
            df1h.index = pd.to_datetime(df1h.index, unit='ms')
        dfs["1h"] = df1h
    # 15m
    df15 = await rt.get_ohlcv(sym, timeframe="15m", limit=1000)
    if df15 is not None and not df15.empty:
        if not isinstance(df15.index, pd.DatetimeIndex):
            df15.index = pd.to_datetime(df15.index, unit='ms')
        dfs["15m"] = df15
    return dfs


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=10)
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    import sqlite3
    db = sqlite3.connect("file:subscriptions.db?mode=ro", uri=True)
    cur = db.cursor()
    cur.execute("SELECT DISTINCT symbol FROM simulated_trades WHERE signal_type='ote_nested' ORDER BY created_at DESC LIMIT 30")
    all_pairs = [r[0] for r in cur.fetchall()]
    db.close()
    seen = set(); pairs = [p for p in all_pairs if not (p in seen or seen.add(p))][:args.pairs]

    print(f"1D->1H честный перепрогон: {len(pairs)} пар, {args.days} дней")
    print()

    rt = RealTimeData()
    gen = OTESignalGenerator()
    all_r = []
    total_fire = 0

    for sym in pairs:
        dfs = await load_ohlcv(rt, sym, args.days)
        if "1d" not in dfs or "1h" not in dfs or "15m" not in dfs:
            continue
        if len(dfs["1h"]) < 50:
            continue

        df1h = dfs["1h"]
        fire_count = 0
        start = 30
        step = 4  # каждый час

        for i in range(start, len(df1h) - 5, step):
            t = df1h.index[i]
            sl_data = {}
            for tf_name, df in dfs.items():
                sl_data[tf_name] = df[df.index <= t].tail(1500)
            if "1h" not in sl_data or len(sl_data["1h"]) < 30:
                continue
            try:
                sigs = gen.generate(sym, sl_data)
            except Exception:
                continue
            for sg in sigs:
                if sg.status != "FIRE":
                    continue
                if sg.htf != "1d" or sg.ltf != "1h":
                    continue
                fut = df1h.iloc[i+1 : min(i+1+48, len(df1h))]
                R = simulate(fut, sg.entry, sg.sl, sg.tp_runner, sg.direction)
                if R is None: continue
                sl_frac = abs(sg.entry - sg.sl) / sg.entry if sg.entry else 0.01
                fee_R = (FEE_TAKER * 2 / sl_frac) if sl_frac > 0 else 1.0
                net = R - fee_R
                all_r.append({"R": R, "net": net, "fee_R": fee_R, "sl%": sl_frac*100})
                fire_count += 1

        print(f"  {sym:20s} FIRE={fire_count}")
        total_fire += fire_count

    await rt.close()

    if not all_r:
        print("НЕТ сделок — 1D→1H не генерит FIRE на живых данных")
        return

    rs = np.array([r["R"] for r in all_r])
    nets = np.array([r["net"] for r in all_r])
    fees = np.array([r["fee_R"] for r in all_r])
    sls = np.array([r["sl%"] for r in all_r])
    n = len(rs)
    wr = np.mean(rs > 0) * 100

    print(f"\n=== 1D→1H ЧЕСТНЫЙ РЕЗУЛЬТАТ ===")
    print(f"Сделок: {n}")
    print(f"GROSS avgR: {np.mean(rs):+.3f}  median: {np.median(rs):+.3f}  WR: {wr:.0f}%")
    print(f"NET  avgR:  {np.mean(nets):+.3f}")
    print(f"FEE  avgR:  {np.mean(fees):+.3f}")
    print(f"SL   median: {np.median(sls):.2f}%")
    print(f"Сравнение: ote_setups.yaml (pre-fake-R): +0.710 vs honest: {np.mean(rs):+.3f}")


if __name__ == "__main__":
    asyncio.run(main())
