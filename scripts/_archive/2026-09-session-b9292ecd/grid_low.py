# -*- coding: utf-8 -*-
"""НИЖНЯЯ ТРЕТЬ ЛЕСТНИЦЫ: 1m/2m/3m и далее. Тот же протокол, что и в верхней сетке.

Вопрос: продолжается ли кривая совпадения от R вниз, на окнах в единицы минут,
или на минутках она ломается (микроструктура, спред, дискретность цены).
Источник — parquet с Binance Vision (ресемпл вниз из 5m невозможен).
"""
import os, sys, glob, itertools
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import _swings

SRC = r"C:\oko_history\1m"
OUT = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
       r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19"
       r"\scratchpad\grid_low.pkl")
TFS = [1, 2, 3, 5, 8, 10, 15, 20, 30, 60]
LENS = [3, 5, 8, 13, 21, 34, 55]
RMIN, RMAX = 0.25, 4.0


def resample(d1, tf):
    if tf == 1:
        return d1
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def swings_of(d, length):
    out = _swings(d["high"], d["low"], length)
    if len(out) < 10:
        return None
    return pd.DataFrame({"ts": [d.index[i] for _, i, _, _ in out],
                         "px": [p for _, _, p, _ in out],
                         "top": [t for _, _, _, t in out]}).sort_values("ts").reset_index(drop=True)


def match_rate(a, b, tol_min, tol_pct, shift_min=0.0):
    if a is None or b is None or len(a) == 0 or len(b) == 0:
        return np.nan
    tol = pd.Timedelta(minutes=tol_min)
    hit = 0
    for is_top in (True, False):
        aa = a[a.top == is_top]; bb = b[b.top == is_top]
        if len(aa) == 0 or len(bb) == 0:
            continue
        bts = bb["ts"].values
        if shift_min:
            bts = bts + np.timedelta64(int(shift_min * 60), "s")
        bpx = bb["px"].values
        lo = np.searchsorted(bts, (aa["ts"] - tol).values, "left")
        hi = np.searchsorted(bts, (aa["ts"] + tol).values, "right")
        apx = aa["px"].values
        for k in range(len(aa)):
            if hi[k] > lo[k] and np.min(np.abs(bpx[lo[k]:hi[k]] - apx[k])) / apx[k] <= tol_pct:
                hit += 1
    return hit / len(a)


files = sorted(glob.glob(SRC + r"\*.parquet"))
print(f"файлов 1m: {len(files)}", flush=True)
rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        print(f"  {sym}: мало баров ({len(d1)}), пропуск", flush=True)
        continue
    layers = {}
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 500:
            continue
        for L in LENS:
            s = swings_of(d, L)
            if s is not None:
                layers[(tf, L)] = s
    keys = sorted(layers)
    for (tfh, Lh), (tfl, Ll) in itertools.product(keys, keys):
        if tfh <= tfl:
            continue
        Wh, Wl = tfh * Lh, tfl * Ll
        R = Wh / Wl
        if not (RMIN <= R <= RMAX):
            continue
        tol = max(tfh * 1.5, 1.5)
        real = match_rate(layers[(tfh, Lh)], layers[(tfl, Ll)], tol, 0.0015)
        ctl = match_rate(layers[(tfh, Lh)], layers[(tfl, Ll)], tol, 0.0015, shift_min=tfh * 37.0)
        rows.append(dict(sym=sym, tfh=tfh, Lh=Lh, tfl=tfl, Ll=Ll, Wh=Wh, Wl=Wl, R=R,
                         tfr=tfh / tfl, n=len(layers[(tfh, Lh)]), real=real, ctl=ctl))
    print(f"[{fi}/{len(files)}] {sym}: баров {len(d1):,}, слоёв {len(layers)}, "
          f"пар {len(rows):,}", flush=True)

df = pd.DataFrame(rows).dropna(subset=["real", "ctl"])
df.to_pickle(OUT)
print(f"\nсохранено: {len(df):,} пар\n", flush=True)

# --- разбор ---
df["lift"] = df.real - df.ctl
bins = [0.25, 0.4, 0.55, 0.7, 0.85, 1.0, 1.2, 1.45, 1.75, 2.1, 2.6, 3.2, 4.0]
g = df[df.n >= 100].groupby(pd.cut(df[df.n >= 100].R, bins), observed=True).agg(
    real=("real", "mean"), ctl=("ctl", "mean"), n=("real", "size"))
print("=== КРИВАЯ ПО R (только n>=100) — сравнить с верхней сеткой ===")
print(f"{'R':>14} {'real':>7} {'контроль':>9} {'пар':>7}")
for k, r in g.iterrows():
    print(f"{str(k):>14} {r.real*100:6.1f}% {r.ctl*100:8.1f}% {int(r.n):7,}")

print("\n=== ПО ОКНУ СТАРШЕГО СЛОЯ (ломается ли на единицах минут?) ===")
s = df[(df.R >= 0.85) & (df.n >= 100)]
q = pd.cut(s.Wh, [0, 5, 10, 20, 40, 80, 160, 320, 700, 1500, 4000])
g2 = s.groupby(q, observed=True).agg(real=("real", "mean"), ctl=("ctl", "mean"),
                                     n=("real", "size"))
print(f"{'окно старшего, мин':>22} {'real':>7} {'контроль':>9} {'пар':>7}")
for k, r in g2.iterrows():
    print(f"{str(k):>22} {r.real*100:6.1f}% {r.ctl*100:8.1f}% {int(r.n):7,}")

print("\n=== ПАРЫ С УЧАСТИЕМ 1m / 2m / 3m (n>=100, R>=0.85) ===")
k = (df[(df.n >= 100) & (df.R >= 0.85) & ((df.tfl <= 3) | (df.tfh <= 3))]
     .groupby(["tfh", "Lh", "tfl", "Ll"])
     .agg(real=("real", "mean"), ctl=("ctl", "mean"), R=("R", "first"),
          n=("n", "mean"), m=("sym", "nunique")).reset_index())
k = k[k.m >= 3].sort_values("real", ascending=False)
print(f"  таких пар: {len(k)}")
for _, r in k.head(15).iterrows():
    print(f"   {int(r.tfh):>3}m x{int(r.Lh):<3} -> {int(r.tfl):>3}m x{int(r.Ll):<3} | "
          f"окна {int(r.tfh*r.Lh):>5}/{int(r.tfl*r.Ll):<5} | R={r.R:5.2f} | "
          f"{r.real*100:5.1f}% (ctl {r.ctl*100:4.1f}%) | n={r.n:.0f}")
