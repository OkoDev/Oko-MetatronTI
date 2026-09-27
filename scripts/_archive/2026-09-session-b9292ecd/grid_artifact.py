# -*- coding: utf-8 -*-
"""Проверка на артефакт + переход от СВИНГОВ к СОБЫТИЯМ.

A. Не объясняется ли плато плотностью младшего слоя (мелкая сетка ловит всё подряд)?
B. Достаточно ли n в парах-победителях (крупные окна = единицы свингов)?
C. ГЛАВНОЕ: совпадают ли СОБЫТИЯ (CHoCH/BOS с направлением), а не только точки?
"""
import os, sys, sqlite3
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import _swings, run_structure

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
df = pd.read_pickle(D + r"\grid_nest.pkl").dropna(subset=["real", "ctl"])
df["lift"] = df.real - df.ctl

print("=== A. ПЛОТНОСТЬ МЛАДШЕГО СЛОЯ vs совпадение ===")
# плотность младшего слоя ~ 1/окно_lo (реже свинги при большом окне)
df["dens_lo"] = 1.0 / df.Wl
sub = df[df.R.between(1.0, 4.0)]          # только плато
q = pd.qcut(sub.Wl, 5, duplicates="drop")
g = sub.groupby(q, observed=True).agg(real=("real", "mean"), n=("real", "size"),
                                      Rm=("R", "mean"))
print(f"{'окно младшего, мин':>22} {'real':>7} {'R сред':>7} {'пар':>7}")
for k, r in g.iterrows():
    print(f"{str(k):>22} {r.real*100:6.1f}% {r.Rm:7.2f} {int(r.n):7,}")
print("  → если плато держится при ЛЮБОМ окне младшего, плотность его не объясняет")

print("\n=== B. n свингов в парах-победителях ===")
k = (df.groupby(["tfh", "Lh", "tfl", "Ll"])
       .agg(real=("real", "mean"), n=("n", "mean"), R=("R", "first"),
            m=("sym", "nunique")).reset_index())
k = k[k.m >= 8].sort_values("real", ascending=False)
print(f"{'пара':>26} {'R':>5} {'real':>7} {'n свингов старшего':>20}")
for _, r in k.head(8).iterrows():
    print(f"{int(r.tfh):>6}m×{int(r.Lh):<3}→{int(r.tfl):>5}m×{int(r.Ll):<3} "
          f"{r.R:5.2f} {r.real*100:6.1f}% {r.n:20.0f}")
big = k[k.n >= 100]
print(f"  пар с n≥100: {len(big)} | среднее real у них: {big.real.mean()*100:.1f}%")

print("\n=== C. СОБЫТИЯ (CHoCH/BOS), а не точки ===")
cn = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in cn.execute(
    "SELECT symbol FROM ohlcv_cache WHERE timeframe='5m' AND symbol NOT LIKE 'binance:%' "
    "GROUP BY symbol HAVING COUNT(*)>100000 ORDER BY COUNT(*) DESC LIMIT 8")]
a = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1000)
b = int(pd.Timestamp("2026-05-31", tz="UTC").timestamp() * 1000)


def ev_frame(d, sl, il):
    st = run_structure(d, swing_len=sl, internal_len=il)
    rows = [(d.index[e.i], e.kind, e.bull, e.internal) for e in st.events]
    return pd.DataFrame(rows, columns=["ts", "kind", "bull", "internal"])


def ev_match(A, B, tol_min):
    """Доля событий A, у которых в B есть событие ТОГО ЖЕ вида и направления в допуске."""
    if len(A) == 0 or len(B) == 0:
        return np.nan
    tol = pd.Timedelta(minutes=tol_min)
    hit = 0
    for (kind, bull), grp in A.groupby(["kind", "bull"]):
        cand = B[(B.kind == kind) & (B.bull == bull)]["ts"].values
        if len(cand) == 0:
            continue
        lo = np.searchsorted(cand, (grp.ts - tol).values, "left")
        hi = np.searchsorted(cand, (grp.ts + tol).values, "right")
        hit += int((hi > lo).sum())
    return hit / len(A)


# пары: (ТФ_hi, ТФ_lo) с R≈1 по конструкции слоёв int(5) / swing(50)
PAIRS = [(60, 5), (240, 15), (60, 15), (240, 60), (15, 5), (120, 10), (180, 15)]
res = []
for sym in syms:
    d5 = pd.read_sql("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe='5m' AND time>=? AND time<? ORDER BY time",
                     cn, params=(sym, a, b))
    if len(d5) < 40000:
        continue
    d5.index = pd.to_datetime(d5["time"], unit="ms", utc=True)
    d5 = d5[["open", "high", "low", "close"]]
    cache = {}
    for tf in sorted({t for p in PAIRS for t in p}):
        if tf == 5:
            cache[tf] = d5
        else:
            r = d5.resample(f"{tf}min", label="left", closed="left")
            cache[tf] = pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                                      "low": r["low"].min(),
                                      "close": r["close"].last()}).dropna()
    for tfh, tfl in PAIRS:
        Eh = ev_frame(cache[tfh].reset_index(drop=True), 50, 5)
        Eh["ts"] = [cache[tfh].index[i] for i in
                    [e.i for e in run_structure(cache[tfh].reset_index(drop=True), 50, 5).events]]
        El = ev_frame(cache[tfl].reset_index(drop=True), 50, 5)
        El["ts"] = [cache[tfl].index[i] for i in
                    [e.i for e in run_structure(cache[tfl].reset_index(drop=True), 50, 5).events]]
        Eh = Eh.sort_values("ts"); El = El.sort_values("ts")
        # int старшего против swing младшего — та самая пара
        A = Eh[Eh.internal]; B = El[~El.internal]
        r_real = ev_match(A, B, tfh * 1.5)
        Bs = B.copy(); Bs["ts"] = Bs["ts"] + pd.Timedelta(minutes=tfh * 37)
        r_ctl = ev_match(A, Bs, tfh * 1.5)
        res.append(dict(sym=sym, tfh=tfh, tfl=tfl, R=(tfh * 5) / (tfl * 50),
                        nA=len(A), real=r_real, ctl=r_ctl))
    print(f"  {sym} ok", flush=True)

E = pd.DataFrame(res)
g = E.groupby(["tfh", "tfl"]).agg(R=("R", "first"), real=("real", "mean"),
                                  ctl=("ctl", "mean"), nA=("nA", "mean")).reset_index()
print(f"\n{'старший':>8} {'младший':>8} {'R':>6} {'событий':>9} "
      f"{'совпало':>8} {'контроль':>9}")
for _, r in g.sort_values("R").iterrows():
    print(f"{int(r.tfh):>7}m {int(r.tfl):>7}m {r.R:6.2f} {r.nA:9.0f} "
          f"{r.real*100:7.1f}% {r.ctl*100:8.1f}%")
print("\n🔑 сравнить с совпадением СВИНГОВ (95-97% на плато): если события совпадают")
print("   заметно хуже — признаки НЕ дублируются, дублируются только точки.")
