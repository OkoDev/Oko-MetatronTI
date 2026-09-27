# -*- coding: utf-8 -*-
"""КАУЗАЛЬНАЯ ГЛУБИНА против ПОЛНОЙ (09.09.2026).

Прошлый замер отбирал сделки по глубине экстремума, но свинг слоя tf подтверждается
через LEN*tf минут после экстремума — на 240m это 40 часов, уже ПОСЛЕ закрытия сделки
(держим 15 часов). То есть отбор шёл по информации из будущего.

Здесь считаются ОБЕ глубины одновременно:
    depth_causal — только слои, чей свинг подтверждён СТРОГО ДО момента входа
    depth_full   — как было (любое совпадение экстремума, включая будущие подтверждения)
Разница между колонками и есть размер утечки.
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
IN_TF = 3
OUT_TF = 60
TOL_MIN = 30
NSYM = 40
COST = 0.35
MAXH = 60 * 24 * 14
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | вход {IN_TF}m → выход {OUT_TF}m\n", flush=True)


def resample(d1, tf):
    if tf == 1:
        return d1[["open", "high", "low", "close"]]
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


rows = []
for fi, f in enumerate(files, 1):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    sym = os.path.basename(f)[:-8]
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
                      top=np.array([t for _, _, _, t in out]))
    if IN_TF not in sw or OUT_TF not in sw:
        continue
    A, C = sw[IN_TF], sw[OUT_TF]
    m1_t, m1_c = d1.index.values, d1["close"].values
    tol = np.timedelta64(TOL_MIN, "m")
    for k in range(len(A["pt"])):
        side = -1 if A["top"][k] else 1
        t_conf = A["conf"][k]
        i_in = int(np.searchsorted(m1_t, t_conf))
        if i_in >= len(m1_c) - 10:
            continue
        dc = df_ = 0
        for tf in TFS:
            if tf == IN_TF or tf not in sw:
                continue
            B = sw[tf]
            m_ = (B["top"] == A["top"][k]) & (np.abs(B["pt"] - A["pt"][k]) <= tol)
            if m_.any():
                df_ += 1
                if (B["conf"][m_] <= t_conf).any():
                    dc += 1
        mm = (C["top"] != A["top"][k]) & (C["conf"] > t_conf)
        if not mm.any():
            continue
        i_out = int(np.searchsorted(m1_t, C["conf"][mm][0]))
        if i_out >= len(m1_c) or i_out <= i_in or (i_out - i_in) > MAXH:
            continue
        e = m1_c[i_in]
        rows.append((sym, side, dc, df_, (m1_c[i_out] - e) / e * 100 * side,
                     i_out - i_in, int(k >= len(A["pt"]) // 2)))
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "side", "dc", "df", "pnl", "mins", "half"])
R["net"] = R.pnl - COST
R.to_pickle(D + r"\swing_causal.pkl")
print(f"\nсделок: {len(R):,}\n")

print("=== СРАВНЕНИЕ: КАУЗАЛЬНАЯ глубина против ПОЛНОЙ ===")
print(f"{'глубина':>8} | {'каузальная n':>13} {'нетто':>9} {'WR':>6} {'монет+':>8} "
      f"| {'полная n':>10} {'нетто':>9} {'WR':>6} {'монет+':>8}")
for d_ in range(0, 7):
    a, b = R[R.dc == d_], R[R.df == d_]
    if len(a) < 300 and len(b) < 300:
        continue
    sa = (f"{a.net.mean():+8.3f}% {(a.net>0).mean()*100:5.1f}% "
          f"{int((a.groupby('sym').net.mean()>0).sum()):>3}/{a.sym.nunique():<4}"
          if len(a) >= 300 else f"{'—':>8} {'—':>6} {'—':>8}")
    sb = (f"{b.net.mean():+8.3f}% {(b.net>0).mean()*100:5.1f}% "
          f"{int((b.groupby('sym').net.mean()>0).sum()):>3}/{b.sym.nunique():<4}"
          if len(b) >= 300 else f"{'—':>8} {'—':>6} {'—':>8}")
    print(f"{d_:>8} | {len(a):>13,} {sa} | {len(b):>10,} {sb}")

print("\n=== РАСПРЕДЕЛЕНИЕ: сколько слоёв успевает подтвердиться ДО входа ===")
print(f"  каузальная глубина: " + " · ".join(
    f"{d_}:{(R.dc == d_).mean()*100:.1f}%" for d_ in range(0, 7) if (R.dc == d_).any()))
print(f"  полная глубина:     " + " · ".join(
    f"{d_}:{(R.df == d_).mean()*100:.1f}%" for d_ in range(0, 7) if (R.df == d_).any()))

print("\n=== КАУЗАЛЬНАЯ ГЛУБИНА ПО СТОРОНАМ + IS→OOS ===")
print(f"{'глубина':>8} {'стор':>6} {'n':>8} {'ход':>9} {'мед':>9} {'нетто':>9} "
      f"{'IS':>9} {'OOS':>9} {'перенос':>8} {'монет+':>8}")
for d_ in sorted(R.dc.unique()):
    for side, nm in [(1, "long"), (-1, "short")]:
        g = R[(R.dc == d_) & (R.side == side)]
        if len(g) < 300:
            continue
        i_, o_ = g[g.half == 0].net, g[g.half == 1].net
        tag = "✓" if len(i_) > 80 and len(o_) > 80 and i_.mean() * o_.mean() > 0 \
            and i_.mean() > 0 else "✗"
        per = g.groupby("sym").net.mean()
        print(f"{d_:>8} {nm:>6} {len(g):>8,} {g.pnl.mean():+8.3f}% "
              f"{g.pnl.median():+8.3f}% {g.net.mean():+8.3f}% {i_.mean():+8.3f}% "
              f"{o_.mean():+8.3f}% {tag:>8} {int((per>0).sum())}/{len(per)}")
