# -*- coding: utf-8 -*-
"""Бэктест V2-MTF (фрактальный вход, Егор: волна 3 младшего в волне 1 старшего, 15m слом у дна/вершины).
4h контекст + 15m вход. Исполнение на 15m-барах (интрабар, % net, лестница 40/30/30 + BE)."""
import argparse
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd

from core.smc.method_v2_mtf import detect_v2_mtf
from scripts.test_method_v2 import load_df

CACHE = "ohlcv_cache.db"
COSTS = 0.2
SHARES = (0.4, 0.3, 0.3)
RETEST_BARS = 8       # 15m: вход по рынку/близкий ретест (волна 3 уходит быстро)
TIMEOUT_BARS = 800    # 15m: ~8 дней


def liquid_syms(tf, topn):
    with sqlite3.connect(CACHE) as c:
        syms = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe=?", (tf,))]
    rank = []
    for s in syms:
        try:
            df = load_df(s, tf)
            if len(df) < 500:
                continue
            rank.append(((df["close"] * df["volume"]).median(), s))
        except Exception:
            continue
    rank.sort(reverse=True)
    return [s for _, s in rank[:topn]]


def simulate(dfl, s):
    high, low, close = dfl["high"].values, dfl["low"].values, dfl["close"].values
    idx = dfl.index
    pos = idx.get_indexer([s.entry_ts])
    ei = pos[0] if pos[0] >= 0 else None
    if ei is None:
        return None
    n = len(dfl)
    lng = s.direction == "LONG"
    t1, t2, t3 = s.targets
    # вход по рынку в баре w3 (волна 3 — импульсная, вход сразу)
    entry = s.entry
    sl = s.sl
    rem, pnl = 1.0, 0.0
    hit = [False, False, False]
    tg = [t1, t2, t3]
    for j in range(ei + 1, min(ei + 1 + TIMEOUT_BARS, n)):
        if (low[j] <= sl) if lng else (high[j] >= sl):
            move = (sl - entry) / entry * 100 if lng else (entry - sl) / entry * 100
            pnl += rem * move; rem = 0.0; break
        for k in range(3):
            if hit[k] or rem <= 0:
                continue
            if (high[j] >= tg[k]) if lng else (low[j] <= tg[k]):
                move = (tg[k] - entry) / entry * 100 if lng else (entry - tg[k]) / entry * 100
                pnl += SHARES[k] * move; rem -= SHARES[k]; hit[k] = True
                if k == 0:
                    sl = entry
        if rem <= 1e-9:
            break
    if rem > 1e-9:
        jl = min(ei + 1 + TIMEOUT_BARS, n) - 1
        move = (close[jl] - entry) / entry * 100 if lng else (entry - close[jl]) / entry * 100
        pnl += rem * move
    return {"net": pnl - COSTS, "dir": s.direction, "year": str(s.entry_ts)[:4],
            "t1": hit[0], "t3": hit[2]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liquid", type=int, default=40)
    args = ap.parse_args()
    syms = liquid_syms("15m", args.liquid)
    print(f"символов: {len(syms)} (4h контекст + 15m вход)")
    res = []
    for si, sym in enumerate(syms):
        try:
            d4 = load_df(sym, "4h")
            d15 = load_df(sym, "15m")
            if len(d4) < 100 or len(d15) < 500:
                continue
            for s in detect_v2_mtf(d4, d15):
                r = simulate(d15, s)
                if r:
                    res.append(r)
        except Exception as e:
            print(f"  {sym}: {e}")
        if (si + 1) % 20 == 0:
            print(f"  ...{si+1}/{len(syms)}, сделок {len(res)}", flush=True)

    def stat(lst):
        if not lst:
            return "n=0"
        nets = [x["net"] for x in lst]
        return (f"n={len(nets):5d} net={sum(nets)/len(nets):+.3f}% WR={sum(1 for v in nets if v>0)/len(nets)*100:.0f}% "
                f"t1={sum(1 for x in lst if x['t1'])/len(lst)*100:.0f}% t3={sum(1 for x in lst if x['t3'])/len(lst)*100:.0f}%")

    print(f"\n═══ V2-MTF (волна 3 младшего в волне 1 старшего, 15m слом у дна/вершины) ═══")
    print("  ALL:", stat(res))
    for d in ("LONG", "SHORT"):
        sub = [x for x in res if x["dir"] == d]
        print(f"  {d}:", stat(sub))
        ys = sorted(set(x["year"] for x in sub))
        print("       годы:", " · ".join(f"{y}:{sum(x['net'] for x in sub if x['year']==y)/max(1,len([x for x in sub if x['year']==y])):+.2f}(n{len([x for x in sub if x['year']==y])})" for y in ys))


if __name__ == "__main__":
    main()
