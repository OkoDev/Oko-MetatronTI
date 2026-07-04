# -*- coding: utf-8 -*-
"""МАТРИЦА METHOD-V2: ТФ × len_big × направление — поиск reversal LONG эджа и лучшего ТФ.
Егор 04.07: «нужны поиски идентичного на len5/len50 в лонг и на разных ТФ».

Гоняет reversal LONG/SHORT + continuation-conf на 15m/1h/4h с адаптивным len_big.
Компактная сводка net/WR по годам. Ликвидные top-N. Интрабар, % net (переиспользует simulate)."""
import argparse
import os
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd

from core.smc.method_v2 import detect_method_v2
from scripts.test_method_v2 import load_df, simulate

CACHE = "ohlcv_cache.db"
# ТФ → len_big (крупная структура ≈ 4-8 дней): 15m×384=4дн, 1h×100=4дн, 4h×30=5дн
TF_LENBIG = {"15m": 200, "1h": 100, "4h": 30}


def liquid_syms(tf: str, topn: int) -> list[str]:
    with sqlite3.connect(CACHE) as c:
        syms = [r[0] for r in c.execute(
            "SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe=?", (tf,))]
    rank = []
    for s in syms:
        try:
            df = load_df(s, tf)
            if len(df) < 300:
                continue
            rank.append(((df["close"] * df["volume"]).median(), s))
        except Exception:
            continue
    rank.sort(reverse=True)
    return [s for _, s in rank[:topn]]


def stat(lst):
    if not lst:
        return "n=0"
    nets = [x["net"] for x in lst]
    wr = sum(1 for v in nets if v > 0) / len(nets) * 100
    return f"n={len(nets):5d} net={sum(nets)/len(nets):+.3f}% WR={wr:.0f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liquid", type=int, default=50)
    ap.add_argument("--tfs", default="15m,1h,4h")
    args = ap.parse_args()

    for tf in args.tfs.split(","):
        lb = TF_LENBIG.get(tf, 100)
        syms = liquid_syms(tf, args.liquid)
        res = []
        for sym in syms:
            try:
                df = load_df(sym, tf)
                if len(df) < 300:
                    continue
                for s in detect_method_v2(df, len_big=lb):
                    r = simulate(df, s)
                    if r:
                        r["conf"] = bool(getattr(s, "conf", False))
                        res.append(r)
            except Exception:
                continue
        print(f"\n{'='*70}\nТФ={tf} len_big={lb} ликвид top-{args.liquid} символов={len(syms)} сделок={len(res)}")
        for kd in ("reversal", "continuation"):
            for d in ("LONG", "SHORT"):
                sub = [x for x in res if x["kind"] == kd and x["dir"] == d]
                if sub:
                    print(f"  {kd:12s} {d}: {stat(sub)}")
                    if kd == "reversal":                 # разворотам — разбивка по годам
                        ys = sorted(set(x["year"] for x in sub))
                        yline = " · ".join(f"{y}:{sum(x['net'] for x in sub if x['year']==y)/max(1,len([x for x in sub if x['year']==y])):+.2f}" for y in ys)
                        print(f"                 годы: {yline}")
                    cf = [x for x in sub if x["conf"]]
                    if len(cf) >= 25:
                        print(f"                 conf=ДА: {stat(cf)}")
                        if kd == "reversal":
                            ys = sorted(set(x["year"] for x in cf))
                            yl = " · ".join(f"{y}:{sum(x['net'] for x in cf if x['year']==y)/max(1,len([x for x in cf if x['year']==y])):+.2f}(n{len([x for x in cf if x['year']==y])})" for y in ys)
                            print(f"                 conf годы: {yl}")


if __name__ == "__main__":
    main()
