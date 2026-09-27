# -*- coding: utf-8 -*-
"""ВХОД НА ЭКСТРЕМУМЕ МЛАДШЕГО СЛОЯ → ВЫХОД НА ЭКСТРЕМУМЕ СТАРШЕГО (Егор, 09.09.2026).

Прошлый замер держал сделку до следующего свинга ТОГО ЖЕ слоя — 27 минут. Здесь
выход берётся на первом ПРОТИВОПОЛОЖНОМ экстремуме СТАРШЕГО слоя: вход на 1m/3m,
выход на 15m/1h/4h.

Матрица: слой входа × слой выхода, для всех пар (вход младше выхода).
Ось — глубина экстремума входа (на скольких слоях он подтверждён).

Каузально: вход по цене на баре ПОДТВЕРЖДЕНИЯ свинга входа, выход по цене на баре
ПОДТВЕРЖДЕНИЯ свинга выхода. Лаги обоих детекторов учтены.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import _swings

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TFS = [1, 3, 5, 15, 30, 60, 240]
LEN = 10
IN_TFS = [1, 3, 5]
OUT_TFS = [15, 30, 60, 240]
TOL_MIN = 30
NSYM = 40
COST = 0.35
MAXH = 60 * 24 * 14          # предохранитель: 14 суток в минутах
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | вход {IN_TFS} → выход {OUT_TFS}\n", flush=True)


def resample(d1, tf):
    if tf == 1:
        return d1[["open", "high", "low", "close"]]
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    sw = {}
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 300:
            continue
        out = _swings(d["high"], d["low"], LEN)
        if len(out) < 20:
            continue
        sw[tf] = dict(conf=np.array([d.index.values[c] for c, _, _, _ in out]),
                      pt=np.array([d.index.values[i] for _, i, _, _ in out]),
                      top=np.array([t for _, _, _, t in out]), d=d)
    m1_t = d1.index.values; m1_c = d1["close"].values
    tol = np.timedelta64(TOL_MIN, "m")
    for tin in IN_TFS:
        if tin not in sw:
            continue
        A = sw[tin]
        for k in range(len(A["pt"])):
            side = -1 if A["top"][k] else 1
            t_conf = A["conf"][k]
            i_in = int(np.searchsorted(m1_t, t_conf))
            if i_in >= len(m1_c) - 10:
                continue
            depth = 0
            for tf in TFS:
                if tf == tin or tf not in sw:
                    continue
                B = sw[tf]
                if ((B["top"] == A["top"][k]) &
                        (np.abs(B["pt"] - A["pt"][k]) <= tol)).any():
                    depth += 1
            e = m1_c[i_in]
            for tout in OUT_TFS:
                if tout not in sw:
                    continue
                C = sw[tout]
                # первый ПРОТИВОПОЛОЖНЫЙ экстремум старшего слоя, подтверждённый ПОСЛЕ входа
                m = (C["top"] != A["top"][k]) & (C["conf"] > t_conf)
                if not m.any():
                    continue
                t_out = C["conf"][m][0]
                i_out = int(np.searchsorted(m1_t, t_out))
                if i_out >= len(m1_c) or i_out <= i_in:
                    continue
                mins = (i_out - i_in)
                if mins > MAXH:
                    continue
                rows.append((sym, tin, tout, side, depth,
                             (m1_c[i_out] - e) / e * 100 * side, mins,
                             int(k >= len(A["pt"]) // 2)))
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "tin", "tout", "side", "depth", "pnl",
                                "mins", "half"])
R["net"] = R.pnl - COST
R.to_pickle(D + r"\swing_cross.pkl")
print(f"\nсделок: {len(R):,}\n")

print("=== МАТРИЦА: вход на слое → выход на слое (обе стороны) ===")
print(f"{'вход':>6} {'выход':>7} {'n':>8} {'ход %':>9} {'мед':>9} {'нетто':>9} "
      f"{'WR':>6} {'часов':>8} {'IS→OOS':>8} {'монет+':>8}")
for tin in IN_TFS:
    for tout in OUT_TFS:
        g = R[(R.tin == tin) & (R.tout == tout)]
        if len(g) < 300:
            continue
        i_, o_ = g[g.half == 0].net, g[g.half == 1].net
        tag = "✓" if len(i_) > 80 and len(o_) > 80 and i_.mean() * o_.mean() > 0 \
            and i_.mean() > 0 else "✗"
        per = g.groupby("sym").net.mean()
        print(f"{tin:>5}m {tout:>6}m {len(g):>8,} {g.pnl.mean():+8.3f}% "
              f"{g.pnl.median():+8.3f}% {g.net.mean():+8.3f}% "
              f"{(g.net > 0).mean()*100:5.1f}% {g.mins.median()/60:7.1f} {tag:>8} "
              f"{int((per>0).sum())}/{len(per)}")
    print()

print("=== ГЛУБИНА ВХОДА × ВЫХОД НА 60m (обе стороны) ===")
print(f"{'глубина':>8} {'n':>8} {'ход %':>9} {'мед':>9} {'нетто':>9} {'WR':>6} "
      f"{'часов':>8} {'монет+':>8}")
G = R[R.tout == 60]
for depth in sorted(G.depth.unique()):
    g = G[G.depth == depth]
    if len(g) < 300:
        continue
    per = g.groupby("sym").net.mean()
    print(f"{depth:>8} {len(g):>8,} {g.pnl.mean():+8.3f}% {g.pnl.median():+8.3f}% "
          f"{g.net.mean():+8.3f}% {(g.net > 0).mean()*100:5.1f}% "
          f"{g.mins.median()/60:7.1f} {int((per>0).sum())}/{len(per)}")

print("\n=== ПО СТОРОНАМ (выход 60m, глубина ≥4) ===")
G2 = R[(R.tout == 60) & (R.depth >= 4)]
for side, nm in [(1, "long"), (-1, "short")]:
    g = G2[G2.side == side]
    if len(g) < 100:
        continue
    i_, o_ = g[g.half == 0].net, g[g.half == 1].net
    per = g.groupby("sym").net.mean()
    print(f"  {nm:>5}: n={len(g):>6,} ход {g.pnl.mean():+.3f}% мед {g.pnl.median():+.3f}% "
          f"нетто {g.net.mean():+.3f}% | IS {i_.mean():+.3f}% OOS {o_.mean():+.3f}% "
          f"| монет {int((per>0).sum())}/{len(per)}")
