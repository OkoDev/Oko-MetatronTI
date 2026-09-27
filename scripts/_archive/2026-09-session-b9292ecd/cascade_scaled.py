# -*- coding: utf-8 -*-
"""ГОРИЗОНТ В ЕДИНИЦАХ ОКНА СЛОЯ (поправка Егора 09.09.2026).

Ошибка: MFE мерился фиксированными 4 часами для ВСЕХ слоёв. Но слой с окном 600 мин
живёт в масштабе 10 часов — четыре часа это меньше половины его такта. Горизонт обязан
масштабироваться вместе со слоем, как и всё остальное в гиперкубе.

Здесь: MFE/MAE и итог на горизонтах 2 · 5 · 10 · 25 · 50 ОКОН слоя.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube.npz", allow_pickle=True)
T, SY = z["T"], z["SY"]
W = [int(x) for x in z["windows"]]; L = T.shape[1]
BASE = 3                       # сетка моментов, мин
MULT = [2, 5, 10, 25, 50]      # горизонт в ОКНАХ слоя

px = []
for f in sorted(glob.glob(r"C:\oko_history\1m\*.parquet")):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    r = d1.resample("3min", label="left", closed="left")
    c = pd.DataFrame({"high": r["high"].max(), "low": r["low"].min(),
                      "close": r["close"].last()}).dropna()
    px.append(c.values[6600 // BASE:])
PX = np.vstack(px)
HI, LO, CL = PX[:, 0], PX[:, 1], PX[:, 2]

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
ev = []
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    for k in np.where(np.diff(code[m]) != 0)[0] + 1:
        ev.append(int(m[k]))
EV = np.array(ev)
Tf, Tt = T[EV - 1], T[EV]
# границы монет, чтобы горизонт не перелезал в другую монету
bnd = {}
for s in np.unique(SY):
    w = np.where(SY == s)[0]
    bnd[s] = (w[0], w[-1])


def casc(k, side):
    m = (Tf[:, k] != Tt[:, k]) & (Tt[:, k] == side) & np.all(Tt[:, :k] == side, axis=1)
    return EV[m]


print("=== MFE / MAE НА ГОРИЗОНТЕ В ЕДИНИЦАХ ОКНА СЛОЯ ===")
print("(медианы; hold = N × окно слоя; горизонт обрезан границей монеты)\n")
for k in (3, 4, 5):
    for side, nm in [(1, "лонг"), (-1, "шорт")]:
        ii = casc(k, side)
        if len(ii) < 80:
            continue
        print(f"слой {k} · окно {W[k]} мин · {nm} · n={len(ii):,}")
        print(f"{'горизонт':>10} {'часов':>8} {'MFE мед':>9} {'MAE мед':>9} "
              f"{'MFE/MAE':>8} {'итог мед':>9} {'MFE>2%':>8} {'MFE>5%':>8}")
        for mult in MULT:
            hold = int(mult * W[k] / BASE)
            mfe, mae, fin = [], [], []
            for i in ii:
                hi_b = bnd[SY[i]][1]
                j1 = min(i + hold, hi_b)
                if j1 - i < hold * 0.5:
                    continue
                e = CL[i]
                h = HI[i + 1:j1 + 1]; l = LO[i + 1:j1 + 1]
                if len(h) == 0:
                    continue
                if side == 1:
                    mfe.append((h.max() - e) / e * 100); mae.append((l.min() - e) / e * 100)
                else:
                    mfe.append((e - l.min()) / e * 100); mae.append((e - h.max()) / e * 100)
                fin.append((CL[j1] - e) / e * 100 * side)
            if len(mfe) < 60:
                continue
            mfe = np.array(mfe); mae = np.array(mae); fin = np.array(fin)
            print(f"{mult:>7} окон {hold*BASE/60:8.0f} {np.median(mfe):+8.2f}% "
                  f"{np.median(mae):+8.2f}% {abs(np.median(mfe)/np.median(mae)):8.2f} "
                  f"{np.median(fin):+8.2f}% {(mfe > 2).mean()*100:7.0f}% "
                  f"{(mfe > 5).mean()*100:7.0f}%")
        print()
