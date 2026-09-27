# -*- coding: utf-8 -*-
"""HYP-1: КУБ ДЛЯ РИСКА, А НЕ ДЛЯ НАПРАВЛЕНИЯ (10.09.2026).

Потолок 0.0055 бит посчитан для ЗНАКА движения. Для РАЗМАХА не мерен вовсе.
Основание: редкие конфигурации (с неопределённым слоем, ~1% времени) дают размах
на 30-47% выше обычного — 4.85% против 3.27%.

Считаем:
  A. I(ячейка ; |движение| по квантилям) — потолок для риска, против потолка для знака
  B. предсказуемость размаха: R² и MAE прогноза |движения| по ячейке, против базового
  C. практический выход: разброс ATR-множителя стопа по ячейкам, устойчивость IS→OOS
🔴 Всё на исправленном кубе (без look-ahead), контроль — перемешанный форвард.
"""
import os, sys
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube50_fix.npz", allow_pickle=True)
T, F, SY = z["T"], z["F"], z["SY"]
W = [int(x) for x in z["windows"]]; L = T.shape[1]
RNG = np.random.default_rng(20260910)
HOR = {"1ч": 0, "4ч": 1, "12ч": 2, "24ч": 3}

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
uniq, cinv = np.unique(code, return_inverse=True)
NC = len(uniq)
half = np.zeros(len(T), np.int8)
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    half[m[len(m) // 2:]] = 1
print(f"баров {len(T):,} · ячеек {NC} · слои {W}\n")


def mi(x, y, nx, ny):
    ok = (x >= 0) & (y >= 0)
    x, y = x[ok], y[ok]
    n = len(x)
    j = np.bincount(x * ny + y, minlength=nx * ny).reshape(nx, ny) / n
    px = j.sum(1, keepdims=True); py = j.sum(0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = j * np.log2(j / (px * py))
    return float(np.nansum(t))


print("=== A. ПОТОЛОК ДЛЯ РИСКА против ПОТОЛКА ДЛЯ НАПРАВЛЕНИЯ ===")
print(f"{'горизонт':>9} {'I(знак)':>10} {'I(|размах|)':>13} {'контроль':>10} "
      f"{'во сколько раз':>15}")
for nm, j in HOR.items():
    y = F[:, j]
    ok = ~np.isnan(y)
    # знак
    ys = np.where(ok, (y > 0).astype(int), -1)
    I_sign = mi(cinv, ys, NC, 2)
    # размах: квинтили модуля движения
    a = np.abs(y[ok])
    q = np.percentile(a, [20, 40, 60, 80])
    ya = np.full(len(y), -1, int)
    ya[ok] = np.digitize(a, q)
    I_abs = mi(cinv, ya, NC, 5)
    # контроль для размаха
    ctl = []
    for _ in range(3):
        yp = ya.copy(); v = yp[ok]; RNG.shuffle(v); yp[ok] = v
        ctl.append(mi(cinv, yp, NC, 5))
    c = float(np.mean(ctl))
    print(f"{nm:>9} {I_sign:10.5f} {I_abs:13.5f} {c:10.5f} "
          f"{(I_abs - c) / max(I_sign - 0.00001, 1e-9):14.1f}×")

print("\n=== B. НАСКОЛЬКО ХОРОШО ЯЧЕЙКА ПРЕДСКАЗЫВАЕТ РАЗМАХ (горизонт 24ч) ===")
y = np.abs(F[:, 3]); ok = ~np.isnan(y)
base = np.nanmean(y[ok])
# прогноз = среднее по ячейке, обученное на IS, проверенное на OOS
pred = np.full(len(y), np.nan)
for ci in range(NC):
    m_is = (cinv == ci) & ok & (half == 0)
    if m_is.sum() >= 300:
        pred[cinv == ci] = np.nanmean(y[m_is])
m_oos = ok & (half == 1) & ~np.isnan(pred)
err_cell = np.abs(y[m_oos] - pred[m_oos]).mean()
err_base = np.abs(y[m_oos] - base).mean()
ss_res = ((y[m_oos] - pred[m_oos]) ** 2).sum()
ss_tot = ((y[m_oos] - y[m_oos].mean()) ** 2).sum()
print(f"  OOS баров: {m_oos.sum():,} · базовый |размах| {base:.3f}%")
print(f"  ошибка прогноза по ячейке: {err_cell:.4f}%")
print(f"  ошибка прогноза константой: {err_base:.4f}%")
print(f"  улучшение: {(1 - err_cell / err_base) * 100:+.2f}%   ·   R² = {1 - ss_res/ss_tot:+.4f}")

print("\n=== C. РАЗБРОС ОЖИДАЕМОГО РАЗМАХА ПО ЯЧЕЙКАМ (IS → OOS) ===")
rows = []
for ci in range(NC):
    m_is = (cinv == ci) & ok & (half == 0)
    m_os = (cinv == ci) & ok & (half == 1)
    if m_is.sum() < 300 or m_os.sum() < 300:
        continue
    rows.append((int(uniq[ci]), m_is.sum(), np.nanmean(y[m_is]),
                 m_os.sum(), np.nanmean(y[m_os])))
rows.sort(key=lambda r: -r[2])


def arr(u):
    s = []
    for _ in range(L):
        s.append({0: "▼", 1: "·", 2: "▲"}[int(u % 3)]); u //= 3
    return "".join(s[::-1])


print(f"  ячеек с n≥300 в обеих половинах: {len(rows)}")
print(f"\n  {'ячейка':>9} {'n IS':>8} {'размах IS':>11} {'n OOS':>8} {'размах OOS':>12} "
      f"{'к базе':>8}")
for r in rows[:6] + rows[-6:]:
    print(f"  {arr(r[0]):>9} {r[1]:>8,} {r[2]:10.3f}% {r[3]:>8,} {r[4]:11.3f}% "
          f"{r[4]/base:7.2f}×")
if len(rows) > 10:
    a = np.array([r[2] for r in rows]); b = np.array([r[4] for r in rows])
    print(f"\n  корреляция IS↔OOS по ячейкам: {np.corrcoef(a, b)[0,1]:+.3f}")
    print(f"  разброс OOS: {b.min():.3f}% … {b.max():.3f}%  "
          f"(отношение {b.max()/max(b.min(),1e-9):.2f}×)")
    top = [r for r in rows if r[2] >= np.percentile(a, 80)]
    bot = [r for r in rows if r[2] <= np.percentile(a, 20)]
    tv = np.average([r[4] for r in top], weights=[r[3] for r in top])
    bv = np.average([r[4] for r in bot], weights=[r[3] for r in bot])
    print(f"\n  верхний квинтиль по IS → OOS размах {tv:.3f}%")
    print(f"  нижний  квинтиль по IS → OOS размах {bv:.3f}%")
    print(f"  🔑 отношение {tv/max(bv,1e-9):.2f}× — во столько раз шире должен быть стоп")
