# -*- coding: utf-8 -*-
"""HYP-3: КРОСС-МОНЕТНЫЙ КУБ — ячейка ВСЕГО РЫНКА (10.09.2026).

Текущий куб описывает одну монету. Но в проекте уже измерено, что «одиночка не платит,
платит кластер» — а кластерности в кубе нет вообще.

Здесь состояние — не конфигурация слоёв ОДНОЙ монеты, а РАСПРЕДЕЛЕНИЕ монет по
состояниям в один момент времени:
    breadth_k = доля монет, у которых слой k смотрит вверх
Это market-wide величина, известная в моменте, и её в матрице проекта не было.

Меряем:
  A. I(рыночное состояние ; знак движения ОТДЕЛЬНОЙ монеты) — добавляет ли рынок
     к тому, что уже знает собственный куб монеты
  B. синергия: I(своя ячейка + рынок) против суммы по отдельности
  C. крайние состояния рынка (все монеты вниз / вверх) — что после них
🔴 Всё каузально: breadth считается по тем же барам, форвард — вперёд.
"""
import os, sys
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube50_fix.npz", allow_pickle=True)
T, F, SY = z["T"], z["F"], z["SY"]
W = [int(x) for x in z["windows"]]; L = T.shape[1]
RNG = np.random.default_rng(20260910)

# ── общая ось времени: у монет разные диапазоны, нужен единый индекс бара
import glob
lens, tss = [], []
for f in sorted(glob.glob(r"C:\oko_history\1m\*.parquet")):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    r = d1.resample("3min", label="left", closed="left")
    c = pd.DataFrame({"close": r["close"].last()}).dropna()
    tss.append(c.index.values[2200:])
TS = np.concatenate(tss)
assert len(TS) == len(T), (len(TS), len(T))
uts, tidx = np.unique(TS, return_inverse=True)
NT = len(uts)
print(f"баров {len(T):,} · уникальных моментов {NT:,} · монет {len(np.unique(SY))}\n")

# ── breadth по каждому слою: доля монет «вверх» в каждый момент
breadth = np.full((NT, L), np.nan, np.float32)
cnt = np.bincount(tidx, minlength=NT).astype(float)
for k in range(L):
    up = np.bincount(tidx, weights=(T[:, k] == 1).astype(float), minlength=NT)
    with np.errstate(invalid="ignore", divide="ignore"):
        breadth[:, k] = np.where(cnt >= 20, up / np.maximum(cnt, 1), np.nan)
valid_t = ~np.isnan(breadth).any(1)
print(f"моментов с ≥20 монетами: {valid_t.sum():,} ({valid_t.mean()*100:.1f}%)")
print(f"средняя ширина рынка по слоям: "
      + " · ".join(f"{W[k]}м:{np.nanmean(breadth[:,k])*100:.0f}%" for k in range(L)))

y_raw = F[:, 3]
ok = ~np.isnan(y_raw) & valid_t[tidx]
y = np.where(ok, (y_raw > 0).astype(int), -1)


def mi(x, yy, nx, ny=2):
    m = (x >= 0) & (yy >= 0)
    a, b = x[m], yy[m]
    n = len(a)
    j = np.bincount(a * ny + b, minlength=nx * ny).reshape(nx, ny) / n
    px = j.sum(1, keepdims=True); py = j.sum(0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = j * np.log2(j / (px * py))
    return float(np.nansum(t))


code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
_, cinv = np.unique(code, return_inverse=True)
NC = cinv.max() + 1

print("\n=== A. ИНФОРМАЦИЯ РЫНОЧНОЙ ШИРИНЫ ПО СЛОЯМ ===")
print(f"{'слой':>7} {'корзин':>7} {'I(breadth; знак)':>18} {'контроль':>10} {'сверх':>9}")
bcodes = {}
for k in range(L):
    b = breadth[tidx, k]
    q = np.full(len(b), -1, int)
    m = ~np.isnan(b) & ok
    q[m] = np.digitize(b[m], np.percentile(b[m], [10, 25, 50, 75, 90]))
    bcodes[k] = q
    I = mi(q, y, 6)
    yp = y.copy(); v = yp[ok]; RNG.shuffle(v); yp[ok] = v
    print(f"{W[k]:>7} {6:>7} {I:18.5f} {mi(q, yp, 6):10.5f} {I - mi(q, yp, 6):+9.5f}")

print("\n=== B. СИНЕРГИЯ: своя ячейка + рынок ===")
own = mi(cinv, y, NC)
print(f"  только своя ячейка (228):        {own:.5f} бит")
best_k = max(range(L), key=lambda k: mi(bcodes[k], y, 6))
mk = mi(bcodes[best_k], y, 6)
print(f"  только рынок (слой {W[best_k]}, 6 корзин): {mk:.5f} бит")
comb = cinv * 6 + np.maximum(bcodes[best_k], 0)
comb = np.where((cinv >= 0) & (bcodes[best_k] >= 0), comb, -1)
both = mi(comb, y, NC * 6)
print(f"  вместе:                          {both:.5f} бит")
print(f"  сумма по отдельности:            {own + mk:.5f} бит")
print(f"  🔑 синергия: {both - own - mk:+.5f} бит "
      f"({'рынок ДОБАВЛЯЕТ' if both > own + mk*0.5 else 'рынок дублирует своё'})")

print("\n=== C. КРАЙНИЕ СОСТОЯНИЯ РЫНКА (слой с максимальной информацией) ===")
b = breadth[tidx, best_k]
print(f"  слой {W[best_k]} мин")
print(f"{'ширина рынка':>16} {'n':>10} {'ход 24ч':>10} {'мед':>9} {'доля>0':>8}")
for lo, hi, lbl in [(0.0, 0.15, "почти все вниз"), (0.15, 0.35, "вниз"),
                    (0.35, 0.65, "смешанно"), (0.65, 0.85, "вверх"),
                    (0.85, 1.01, "почти все вверх")]:
    m = ok & (b >= lo) & (b < hi)
    if m.sum() < 5000:
        continue
    v = y_raw[m]
    print(f"{lbl:>16} {m.sum():>10,} {np.nanmean(v):+9.3f}% "
          f"{np.nanmedian(v):+8.3f}% {(v > 0).mean()*100:7.1f}%")

print("\n=== D. ЗЕРКАЛЬНОСТЬ КРАЙНИХ СОСТОЯНИЙ ===")
lo_m = ok & (b < 0.15)
hi_m = ok & (b >= 0.85)
if lo_m.sum() > 5000 and hi_m.sum() > 5000:
    print(f"  почти все вниз  → ход {np.nanmean(y_raw[lo_m]):+.3f}% "
          f"(n={lo_m.sum():,})")
    print(f"  почти все вверх → ход {np.nanmean(y_raw[hi_m]):+.3f}% "
          f"(n={hi_m.sum():,})")
    print(f"  разность: {np.nanmean(y_raw[hi_m]) - np.nanmean(y_raw[lo_m]):+.3f} п.п.")
