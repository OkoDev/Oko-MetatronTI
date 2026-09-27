# -*- coding: utf-8 -*-
"""ГДЕ происходит каскад относительно экстремума: сколько хода уже упущено.

Вопрос Егора: «нужны пики и впадины для входов?» Ответ зависит от того, насколько
далеко от экстремума срабатывает подтверждение старшего слоя.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube.npz", allow_pickle=True)
T, F, SY = z["T"], z["F"], z["SY"]
W = list(z["windows"]); L = T.shape[1]

# восстановим цену базовой сетки 3m по тем же монетам и тому же прогреву
SRC = r"C:\oko_history\1m"
files = sorted(glob.glob(SRC + r"\*.parquet"))
warm = 6600 // 3
px, syms = [], []
fi = 0
for f in files:
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    fi += 1
    r = d1.resample("3min", label="left", closed="left")
    c = pd.DataFrame({"high": r["high"].max(), "low": r["low"].min(),
                      "close": r["close"].last()}).dropna()
    px.append(c.values[warm:]); syms.append(np.full(len(c) - warm, fi, np.int16))
PX = np.vstack(px); SS = np.concatenate(syms)
assert len(PX) == len(T), (len(PX), len(T))
HI, LO, CL = PX[:, 0], PX[:, 1], PX[:, 2]
print(f"цена сопоставлена: {len(PX):,} баров 3m\n")

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
ev = []
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    ch = np.where(np.diff(code[m]) != 0)[0] + 1
    for k in ch:
        ev.append(int(m[k]))
EV = np.array(ev)
Tf, Tt = T[EV - 1], T[EV]
f4 = F[EV, 1]

LOOK = {3: 400, 4: 800}     # сколько баров 3m назад искать экстремум (≈ 2-3 окна слоя)
print("=== ГДЕ КАСКАД ОТНОСИТЕЛЬНО ЭКСТРЕМУМА ===")
print(f"{'слой':>5} {'сторона':>8} {'n':>6} {'от экстр.':>10} {'баров':>7} "
      f"{'ход до':>9} {'ход после 4ч':>13} {'доля хода взята':>16}")
for k in (3, 4):
    look = LOOK[k]
    for side, nm in [(1, "лонг"), (-1, "шорт")]:
        m = (Tf[:, k] != Tt[:, k]) & (Tt[:, k] == side) & np.all(Tt[:, :k] == side, axis=1)
        ii = EV[m]
        ii = ii[ii > look]
        if len(ii) < 100:
            continue
        dist, bars, before = [], [], []
        for i in ii:
            seg_lo = LO[i - look:i + 1]; seg_hi = HI[i - look:i + 1]
            if side == 1:
                j = int(np.argmin(seg_lo)); ext = seg_lo[j]
                dist.append((CL[i] - ext) / ext * 100)
            else:
                j = int(np.argmax(seg_hi)); ext = seg_hi[j]
                dist.append((ext - CL[i]) / ext * 100)
            bars.append(look - j)
        dist = np.array(dist); bars = np.array(bars)
        after = np.abs(np.nanmean(f4[m][:len(ii)])) if m.sum() else np.nan
        med_d = np.median(dist)
        share = med_d / (med_d + abs(np.nanmedian(f4[m]))) * 100
        print(f"{k:>5} {nm:>8} {len(ii):>6,} {med_d:9.2f}% {np.median(bars):7.0f} "
              f"{med_d:8.2f}% {np.nanmedian(f4[m]):+12.2f}% {share:15.0f}%")

print("\n=== ЕСЛИ ВХОДИТЬ РАНЬШЕ: каскад на слое k, но БЕЗ ожидания старшего ===")
print("  (уже измерено: слой1 −0.05%, слой2 −0.03% — ранний вход не платит)")

print("\n=== СКОЛЬКО ЖИВЁТ ХОД ПОСЛЕ КАСКАДА (медиана |движения| по горизонтам) ===")
hor = {"1ч": 0, "4ч": 1, "12ч": 2, "24ч": 3}
print(f"{'слой':>5} {'сторона':>8} " + " ".join(f"{h:>9}" for h in hor))
for k in (3, 4):
    for side, nm in [(1, "лонг"), (-1, "шорт")]:
        m = (Tf[:, k] != Tt[:, k]) & (Tt[:, k] == side) & np.all(Tt[:, :k] == side, axis=1)
        if m.sum() < 100:
            continue
        vals = [np.nanmedian(F[EV[m], j]) * side for j in hor.values()]
        print(f"{k:>5} {nm:>8} " + " ".join(f"{v:+8.3f}%" for v in vals))

print("\n=== MFE/MAE ПОСЛЕ КАСКАДА (4 часа = 80 баров 3m) ===")
print(f"{'слой':>5} {'сторона':>8} {'MFE мед':>9} {'MAE мед':>9} {'MFE/MAE':>8} "
      f"{'доля MFE>0.5%':>14}")
for k in (3, 4):
    for side, nm in [(1, "лонг"), (-1, "шорт")]:
        m = (Tf[:, k] != Tt[:, k]) & (Tt[:, k] == side) & np.all(Tt[:, :k] == side, axis=1)
        ii = EV[m]; ii = ii[ii < len(CL) - 80]
        if len(ii) < 100:
            continue
        mfe, mae = [], []
        for i in ii:
            e = CL[i]
            h = HI[i + 1:i + 81]; l = LO[i + 1:i + 81]
            if side == 1:
                mfe.append((h.max() - e) / e * 100); mae.append((l.min() - e) / e * 100)
            else:
                mfe.append((e - l.min()) / e * 100); mae.append((e - h.max()) / e * 100)
        mfe = np.array(mfe); mae = np.array(mae)
        print(f"{k:>5} {nm:>8} {np.median(mfe):+8.3f}% {np.median(mae):+8.3f}% "
              f"{abs(np.median(mfe)/np.median(mae)):8.2f} {(mfe > 0.5).mean()*100:13.1f}%")
