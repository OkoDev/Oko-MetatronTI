# -*- coding: utf-8 -*-
"""ГИПОТЕЗА ЕГОРА: CHoCH не переносится через масштаб не потому что сломан, а потому что
МЕНЯЕТ ТИП — на старшем слое тот же момент размечается как BOS (структура выраженнее,
тренд устойчивее, идут продолжения вместо смен характера).

Проверка: 1) соотношение BOS/CHoCH по слоям;
          2) совпадение CHoCH младшего с CHoCH старшего ПРОТИВ совпадения с ЛЮБЫМ событием.
Если второе резко выше — гипотеза верна и признак не сломан, а меняет имя.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure

TFS = [3, 10, 30, 90, 240]
NSYM = 10
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


ratio = {tf: [0, 0] for tf in TFS}          # [BOS, CHoCH] по swing-слою
ev_store = []
for f in files:
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    per = {}
    for tf in TFS:
        d = resample(d1, tf)
        st = run_structure(d.reset_index(drop=True), swing_len=10, internal_len=3)
        rows = [(d.index[e.i], e.kind, e.bull, e.internal) for e in st.events]
        E = pd.DataFrame(rows, columns=["ts", "kind", "bull", "internal"]).sort_values("ts")
        sw = E[~E.internal]
        ratio[tf][0] += int((sw.kind == "BOS").sum())
        ratio[tf][1] += int((sw.kind == "CHoCH").sum())
        per[tf] = E
    ev_store.append(per)
    print(f"  {os.path.basename(f)[:-8]} ok", flush=True)

print("\n=== 1. СООТНОШЕНИЕ ТИПОВ ПО СЛОЯМ (swing-слой, len=10) ===")
print(f"{'ТФ':>6} {'окно':>7} {'BOS':>8} {'CHoCH':>8} {'доля BOS':>10}")
for tf in TFS:
    b, c = ratio[tf]
    if b + c:
        print(f"{tf:>5}m {tf*10:>6}м {b:>8,} {c:>8,} {b/(b+c)*100:9.1f}%")

print("\n=== 2. ПЕРЕНОС СОБЫТИЯ НА СОСЕДНИЙ СЛОЙ ===")
print("  (событие младшего → есть ли в допуске событие старшего)")
print(f"{'пара':>14} {'тип младшего':>14} {'тот же тип':>12} {'ЛЮБОЙ тип':>11} "
      f"{'то же напр.':>12}")
for a, b in zip(TFS[:-1], TFS[1:]):
    for kind in ("CHoCH", "BOS"):
        same = anyk = dirs = tot = 0
        for per in ev_store:
            if a not in per or b not in per:
                continue
            A = per[a]; B = per[b]
            A = A[(~A.internal) & (A.kind == kind)]
            Bs = B[~B.internal]
            if len(A) == 0 or len(Bs) == 0:
                continue
            tol = pd.Timedelta(minutes=b * 1.5)
            bts = Bs["ts"].values
            lo = np.searchsorted(bts, (A["ts"] - tol).values, "left")
            hi = np.searchsorted(bts, (A["ts"] + tol).values, "right")
            bk = Bs["kind"].values; bb = Bs["bull"].values
            for j, (l, h_, ab) in enumerate(zip(lo, hi, A["bull"].values)):
                tot += 1
                if h_ > l:
                    anyk += 1
                    if (bk[l:h_] == kind).any():
                        same += 1
                    if (bb[l:h_] == ab).any():
                        dirs += 1
        if tot:
            print(f"{a:>4}m→{b:<4}m {kind:>14} {same/tot*100:11.1f}% "
                  f"{anyk/tot*100:10.1f}% {dirs/tot*100:11.1f}%")

print("\n🔑 если «ЛЮБОЙ тип» много выше «тот же тип» — событие переносится,")
print("   но переименовывается при смене масштаба (гипотеза Егора).")
