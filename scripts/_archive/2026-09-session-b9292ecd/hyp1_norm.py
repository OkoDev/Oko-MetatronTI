# -*- coding: utf-8 -*-
"""HYP-1б: КУБ КАК МНОЖИТЕЛЬ К ТЕКУЩЕЙ ВОЛАТИЛЬНОСТИ (10.09.2026).

Абсолютный прогноз размаха провалился (R² = −0.045): волатильность во второй половине
окна упала (4.6% → 3.3%), и уровни, обученные на первой, завышены по всему полю.
Но ранги ячеек переносятся (корр IS↔OOS +0.398).

Значит мерить надо ОТНОСИТЕЛЬНУЮ величину: |движение| / ATR текущего момента.
Тогда режимный сдвиг волатильности уходит, остаётся вклад самой конфигурации.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube50_fix.npz", allow_pickle=True)
T, F, SY = z["T"], z["F"], z["SY"]
L = T.shape[1]

px = []
for f in sorted(glob.glob(r"C:\oko_history\1m\*.parquet")):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    r = d1.resample("3min", label="left", closed="left")
    c = pd.DataFrame({"high": r["high"].max(), "low": r["low"].min(),
                      "close": r["close"].last()}).dropna()
    px.append(c.values[2200:])
PX = np.vstack(px)
HI, LO, CL = PX[:, 0], PX[:, 1], PX[:, 2]
assert len(PX) == len(T)
# текущая волатильность: ATR(200) на сетке 3m, известна В МОМЕНТ
atr = pd.Series((HI - LO) / CL).rolling(200, min_periods=60).mean().values * 100

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
uniq, cinv = np.unique(code, return_inverse=True)
NC = len(uniq)
half = np.zeros(len(T), np.int8)
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    half[m[len(m) // 2:]] = 1

y = np.abs(F[:, 3])                       # размах за 24ч
ok = ~np.isnan(y) & ~np.isnan(atr) & (atr > 0)
ratio = np.full(len(y), np.nan)
ratio[ok] = y[ok] / atr[ok]               # во сколько раз больше текущей волатильности
print(f"баров с данными: {ok.sum():,}")
print(f"базовое отношение |24ч| / ATR: IS {np.nanmean(ratio[ok & (half==0)]):.3f} · "
      f"OOS {np.nanmean(ratio[ok & (half==1)]):.3f}   ← сдвиг режима должен уйти\n")


def arr(u):
    s = []
    for _ in range(L):
        s.append({0: "▼", 1: "·", 2: "▲"}[int(u % 3)]); u //= 3
    return "".join(s[::-1])


print("=== ПРОГНОЗ ОТНОШЕНИЯ ПО ЯЧЕЙКЕ: IS → OOS ===")
rows = []
for ci in range(NC):
    a = (cinv == ci) & ok & (half == 0)
    b = (cinv == ci) & ok & (half == 1)
    if a.sum() < 300 or b.sum() < 300:
        continue
    rows.append((int(uniq[ci]), a.sum(), np.nanmean(ratio[a]),
                 b.sum(), np.nanmean(ratio[b])))
A = np.array([r[2] for r in rows]); B = np.array([r[4] for r in rows])
Wt = np.array([r[3] for r in rows], float)
print(f"  ячеек: {len(rows)} · корреляция IS↔OOS: {np.corrcoef(A, B)[0,1]:+.3f}")
print(f"  разброс OOS: {B.min():.3f} … {B.max():.3f}  ({B.max()/B.min():.2f}×)")

base_oos = np.average(B, weights=Wt)
hi = [r for r in rows if r[2] >= np.percentile(A, 80)]
lo = [r for r in rows if r[2] <= np.percentile(A, 20)]
hv = np.average([r[4] for r in hi], weights=[r[3] for r in hi])
lv = np.average([r[4] for r in lo], weights=[r[3] for r in lo])
print(f"\n  верхний квинтиль по IS → OOS отношение {hv:.3f}  ({hv/base_oos:.2f}× базы)")
print(f"  нижний  квинтиль по IS → OOS отношение {lv:.3f}  ({lv/base_oos:.2f}× базы)")
print(f"  🔑 разница множителя стопа: {hv/lv:.2f}×")

# качество прогноза в нормированных единицах
pred = np.full(len(y), np.nan)
for c_, _, v, _, _ in rows:
    pred[uniq[cinv] == c_] = v
m = ok & (half == 1) & ~np.isnan(pred)
err_cell = np.abs(ratio[m] - pred[m]).mean()
err_base = np.abs(ratio[m] - np.nanmean(ratio[ok & (half == 0)])).mean()
ss_res = ((ratio[m] - pred[m]) ** 2).sum()
ss_tot = ((ratio[m] - ratio[m].mean()) ** 2).sum()
print(f"\n  OOS баров: {m.sum():,}")
print(f"  ошибка по ячейке:   {err_cell:.4f}")
print(f"  ошибка константой:  {err_base:.4f}")
print(f"  улучшение: {(1-err_cell/err_base)*100:+.2f}%  ·  R² = {1-ss_res/ss_tot:+.4f}")

print(f"\n=== ТОП И НИЗ ПО ОТНОШЕНИЮ (OOS) ===")
rows.sort(key=lambda r: -r[4])
print(f"  {'ячейка':>9} {'n OOS':>9} {'|24ч|/ATR OOS':>15} {'к базе':>8}")
for r in rows[:5] + rows[-5:]:
    print(f"  {arr(r[0]):>9} {r[3]:>9,} {r[4]:14.3f} {r[4]/base_oos:7.2f}×")
