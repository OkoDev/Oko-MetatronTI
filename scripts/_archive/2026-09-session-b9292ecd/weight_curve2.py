# -*- coding: utf-8 -*-
"""КРИВАЯ ВЕСА ОТ ОКНА, С РАЗДЕЛЕНИЕМ ТИПА СОБЫТИЯ.

Повод: два моих замера разошлись в 40 раз. В кубе событием была СМЕНА ТРЕНДА слоя
(то есть только CHoCH — BOS тренд не переключает), а в первой кривой я взял ВСЕ
swing-события, смешав BOS и CHoCH примерно поровну.

Здесь оба типа считаются раздельно и вместе. Горизонт форварда один для всех окон
(4 часа), контроль — случайный бар той же монеты в том же квинтиле ATR.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure

LEN = 10
TFS = [3, 5, 8, 12, 18, 28, 42, 64, 100, 150, 220, 340, 500]
NSYM = 24
HOLD_MIN = 240
RNG = np.random.default_rng(20260909)
KINDS = ("CHoCH", "BOS", "ALL")

files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | окна: {[t*LEN for t in TFS]}\n", flush=True)

acc = {(tf, k, s): [0, 0.0, 0.0] for tf in TFS for k in KINDS for s in (1, -1)}
per = {(tf, k): [] for tf in TFS for k in KINDS}


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


for fi, f in enumerate(files, 1):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 400:
            continue
        h = max(1, HOLD_MIN // tf)
        c = d["close"].values
        n = len(c)
        fwd = np.full(n, np.nan)
        fwd[:-h] = (c[h:] - c[:-h]) / c[:-h] * 100
        atr = ((d["high"] - d["low"]) / d["close"]).rolling(100, min_periods=30).mean().values
        ok = ~np.isnan(fwd) & ~np.isnan(atr)
        if ok.sum() < 200:
            continue
        q = np.zeros(n, np.int8)
        q[ok] = np.digitize(atr[ok], np.nanpercentile(atr[ok], [20, 40, 60, 80]))
        pools = {b: np.where(ok & (q == b))[0] for b in range(5)}
        st = run_structure(d.reset_index(drop=True), swing_len=LEN, internal_len=3)
        ev = [(e.i, 1 if e.bull else -1, e.kind) for e in st.events if not e.internal]
        for kind in KINDS:
            for side in (1, -1):
                ii = np.array([i for i, s_, kd in ev
                               if s_ == side and ok[i] and (kind == "ALL" or kd == kind)],
                              dtype=int)
                if len(ii) < 25:
                    continue
                v = float(np.nanmean(fwd[ii]) * side)
                cs = []
                for _ in range(3):
                    pick = np.array([pools[q[i]][RNG.integers(len(pools[q[i]]))]
                                     if len(pools[q[i]]) else i for i in ii])
                    cs.append(float(np.nanmean(fwd[pick]) * side))
                cm = float(np.mean(cs))
                a = acc[(tf, kind, side)]
                a[0] += len(ii); a[1] += v * len(ii); a[2] += cm * len(ii)
                per[(tf, kind)].append(v - cm)
    if fi % 6 == 0:
        print(f"  [{fi}/{len(files)}]", flush=True)

print(f"\n{'тип':>6} {'окно':>7} {'n':>8} {'событие':>10} {'контроль':>10} "
      f"{'сила':>9} {'монет+':>8}")
curve = {k: [] for k in KINDS}
for kind in KINDS:
    for tf in TFS:
        tot = sum(acc[(tf, kind, s)][0] for s in (1, -1))
        if tot < 200:
            continue
        ev_ = sum(acc[(tf, kind, s)][1] for s in (1, -1)) / tot
        ct = sum(acc[(tf, kind, s)][2] for s in (1, -1)) / tot
        ps = per[(tf, kind)]
        good = sum(1 for x in ps if x > 0)
        print(f"{kind:>6} {tf*LEN:>7} {tot:>8,} {ev_:+9.4f}% {ct:+9.4f}% "
              f"{ev_-ct:+8.4f}% {good:>4}/{len(ps)}")
        curve[kind].append((tf * LEN, ev_ - ct, tot))
    print()

print("=== ПОКАЗАТЕЛЬ СТЕПЕНИ ПО ТИПАМ ===")
for kind in KINDS:
    P = [(w, s) for w, s, n in curve[kind] if s > 0.01]
    if len(P) < 3:
        print(f"  {kind}: положительных точек {len(P)} — недостаточно")
        continue
    x = np.log([w for w, _ in P]); y = np.log([s for _, s in P])
    a, b = np.polyfit(x, y, 1)
    r2 = np.corrcoef(x, y)[0, 1] ** 2
    print(f"  {kind:>6}: сила ∝ окно^{a:.3f}  (R²={r2:.3f}, точек {len(P)}, "
          f"от {min(w for w,_ in P)} до {max(w for w,_ in P)} мин)")

print("\n=== ВЕС ПО ОКНУ (нормировка: окно 180 мин = 4) ===")
P = [(w, s) for w, s, n in curve["CHoCH"] if s > 0.01]
if len(P) >= 3:
    x = np.log([w for w, _ in P]); y = np.log([s for _, s in P])
    a, b = np.polyfit(x, y, 1)
    k = 4.0 / (np.exp(b) * 180 ** a)
    print(f"{'окно':>7} {'измерено':>10} {'вес':>8}")
    for w, s, n in curve["CHoCH"]:
        print(f"{w:>7} {s:+9.4f}% {max(0.0, k*np.exp(b)*w**a) if s > 0 else 0.0:7.1f}")
