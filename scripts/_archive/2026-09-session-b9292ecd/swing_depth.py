# -*- coding: utf-8 -*-
"""ЭКСТРЕМУМ КАК ВХОД, СЛЕДУЮЩИЙ КАК ВЫХОД + ГЛУБИНА ПО СЛОЯМ (Егор, 09.09.2026).

Прямое следствие вложенности: один экстремум существует сразу на нескольких слоях
(точки совпадают на 95% при R≥0.85). Значит у него есть ГЛУБИНА — до какого слоя
лестницы он дотянулся.

  вход  = экстремум (swing) на слое
  выход = СЛЕДУЮЩИЙ экстремум того же слоя
  ось   = глубина: на скольких слоях лестницы этот же экстремум подтверждён

Каузальность: swing подтверждается через `length` баров своего слоя — это лаг детектора,
он честно учитывается (вход по цене на баре ПОДТВЕРЖДЕНИЯ, не на баре экстремума).
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
BASE_TF = 3                 # слой входа
TOL_MIN = 30                # допуск совпадения экстремумов между слоями, мин
NSYM = 40
COST = 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | вход на {BASE_TF}m | лестница {TFS}\n", flush=True)


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
        sw[tf] = dict(
            conf_t=np.array([d.index.values[c] for c, _, _, _ in out]),
            pt_t=np.array([d.index.values[i] for _, i, _, _ in out]),
            px=np.array([p for _, _, p, _ in out]),
            top=np.array([t for _, _, _, t in out]),
            d=d)
    if BASE_TF not in sw:
        continue
    A = sw[BASE_TF]
    dA = A["d"]
    close = dA["close"].values
    tol = np.timedelta64(TOL_MIN, "m")
    for k in range(len(A["pt_t"]) - 1):
        # глубина: на скольких ДРУГИХ слоях есть экстремум той же стороны рядом
        depth = 0
        for tf in TFS:
            if tf == BASE_TF or tf not in sw:
                continue
            B = sw[tf]
            m = (B["top"] == A["top"][k]) & (np.abs(B["pt_t"] - A["pt_t"][k]) <= tol)
            if m.any():
                depth += 1
        # вход на баре ПОДТВЕРЖДЕНИЯ, выход на подтверждении СЛЕДУЮЩЕГО экстремума
        i_in = int(np.searchsorted(dA.index.values, A["conf_t"][k]))
        i_out = int(np.searchsorted(dA.index.values, A["conf_t"][k + 1]))
        if i_in >= len(close) or i_out >= len(close) or i_out <= i_in:
            continue
        side = -1 if A["top"][k] else 1        # низ → лонг, верх → шорт
        e, x = close[i_in], close[i_out]
        rows.append((sym, side, depth, (x - e) / e * 100 * side,
                     i_out - i_in, int(k >= len(A["pt_t"]) // 2)))
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "side", "depth", "pnl", "bars", "half"])
R["net"] = R.pnl - COST
R.to_pickle(D + r"\swing_depth.pkl")
print(f"\nсделок: {len(R):,}\n")

print("=== ГЛУБИНА ЭКСТРЕМУМА → ХОД ДО СЛЕДУЮЩЕГО ЭКСТРЕМУМА ===")
print(f"{'глубина':>8} {'стор':>6} {'n':>8} {'доля':>7} {'ход %':>9} {'мед':>9} "
      f"{'нетто':>9} {'WR':>6} {'баров':>7} {'IS→OOS':>8} {'монет+':>8}")
for depth in sorted(R.depth.unique()):
    for side, nm in [(1, "long"), (-1, "short")]:
        g = R[(R.depth == depth) & (R.side == side)]
        if len(g) < 200:
            continue
        i_, o_ = g[g.half == 0].net, g[g.half == 1].net
        tag = "✓" if len(i_) > 50 and len(o_) > 50 and i_.mean() * o_.mean() > 0 \
            and i_.mean() > 0 else "✗"
        per = g.groupby("sym").net.mean()
        print(f"{depth:>8} {nm:>6} {len(g):>8,} {len(g)/len(R)*100:6.1f}% "
              f"{g.pnl.mean():+8.3f}% {g.pnl.median():+8.3f}% {g.net.mean():+8.3f}% "
              f"{(g.net > 0).mean()*100:5.1f}% {g.bars.median():7.0f} {tag:>8} "
              f"{int((per>0).sum())}/{len(per)}")
    print()

print("=== СУММАРНО ПО ГЛУБИНЕ (обе стороны) ===")
print(f"{'глубина':>8} {'n':>8} {'ход %':>9} {'мед':>9} {'|ход|':>9} {'баров':>7}")
for depth in sorted(R.depth.unique()):
    g = R[R.depth == depth]
    if len(g) < 300:
        continue
    print(f"{depth:>8} {len(g):>8,} {g.pnl.mean():+8.3f}% {g.pnl.median():+8.3f}% "
          f"{g.pnl.abs().median():8.3f}% {g.bars.median():7.0f}")
print("\n🔑 |ход| — медиана модуля движения: растёт ли размах с глубиной экстремума")
