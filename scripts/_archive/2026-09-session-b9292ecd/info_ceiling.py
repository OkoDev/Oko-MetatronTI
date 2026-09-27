# -*- coding: utf-8 -*-
"""ПОТОЛОК ГИПЕРКУБА (ответ на «будем собирать кубик Рубика?», 09.09.2026).

Вместо перебора 2187 ячеек — одно число: сколько информации о БУДУЩЕМ несёт вся
конструкция. I(ячейка; знак форварда) — верхняя граница для ЛЮБОГО правила на этих
слоях. Ни одна комбинация не может дать больше, чем в данных есть.

Считается на исправленном кубе (без look-ahead). Контроль: перемешанный форвард.
Дополнительно — потолок для отдельных слоёв и для пар, чтобы видеть, где информация.
"""
import os, sys
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, itertools

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube50_fix.npz", allow_pickle=True)
T, F, SY = z["T"], z["F"], z["SY"]
W = [int(x) for x in z["windows"]]; L = T.shape[1]
RNG = np.random.default_rng(20260909)
HOR = {"1ч": 0, "4ч": 1, "12ч": 2, "24ч": 3}


def mi(x, y, nx, ny=2):
    """Взаимная информация I(X;Y) в битах."""
    ok = (x >= 0) & (y >= 0)
    x, y = x[ok], y[ok]
    n = len(x)
    joint = np.bincount(x * ny + y, minlength=nx * ny).reshape(nx, ny) / n
    px = joint.sum(1, keepdims=True); py = joint.sum(0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = joint * np.log2(joint / (px * py))
    return float(np.nansum(t))


code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
uniq, cinv = np.unique(code, return_inverse=True)
NC = len(uniq)
print(f"баров: {len(T):,} | занятых ячеек: {NC}\n")

print("=== ПОТОЛОК: I(ячейка ; знак форварда), бит ===")
print(f"{'горизонт':>9} {'I полная':>10} {'контроль':>10} {'сверх':>9} "
      f"{'доля H(Y)':>10} {'экв. точность':>14}")
for nm, j in HOR.items():
    y_raw = F[:, j]
    ok = ~np.isnan(y_raw)
    y = np.where(ok, (y_raw > 0).astype(int), -1)
    I = mi(cinv, y, NC)
    ctl = []
    for _ in range(5):
        yp = y.copy()
        v = yp[ok]; RNG.shuffle(v); yp[ok] = v
        ctl.append(mi(cinv, yp, NC))
    c = float(np.mean(ctl))
    p = (y[ok] == 1).mean()
    HY = -(p * np.log2(p) + (1 - p) * np.log2(1 - p))
    # эквивалентная точность: какой WR даёт такую же информацию
    lo, hi = 0.5, 0.99
    for _ in range(40):
        m_ = (lo + hi) / 2
        Hm = -(m_ * np.log2(m_) + (1 - m_) * np.log2(1 - m_))
        if HY - Hm > I - c:
            hi = m_
        else:
            lo = m_
    print(f"{nm:>9} {I:10.5f} {c:10.5f} {I-c:+9.5f} {(I-c)/HY*100:9.3f}% "
          f"{(lo+hi)/2*100:13.2f}%")

print("\n=== ГДЕ ИНФОРМАЦИЯ: по отдельным слоям (горизонт 4ч) ===")
y_raw = F[:, 1]; ok = ~np.isnan(y_raw)
y = np.where(ok, (y_raw > 0).astype(int), -1)
print(f"{'слой':>5} {'окно':>6} {'I, бит':>10} {'контроль':>10} {'сверх':>9}")
for li in range(L):
    x = T[:, li] + 1
    I = mi(x, y, 3)
    yp = y.copy(); v = yp[ok]; RNG.shuffle(v); yp[ok] = v
    print(f"{li:>5} {W[li]:>6} {I:10.5f} {mi(x, yp, 3):10.5f} {I-mi(x, yp, 3):+9.5f}")

print("\n=== ПАРЫ СЛОЁВ: добавляет ли комбинация сверх суммы одиночек? ===")
print(f"{'пара окон':>16} {'I пары':>9} {'I(a)+I(b)':>11} {'синергия':>10}")
singles = {}
for li in range(L):
    singles[li] = mi(T[:, li] + 1, y, 3)
best = []
for a, b in itertools.combinations(range(L), 2):
    x = (T[:, a] + 1) * 3 + (T[:, b] + 1)
    I = mi(x, y, 9)
    best.append((I - singles[a] - singles[b], I, a, b))
best.sort(reverse=True)
for syn, I, a, b in best[:6]:
    print(f"{W[a]:>7}/{W[b]:<8} {I:9.5f} {singles[a]+singles[b]:11.5f} {syn:+10.5f}")

print("\n=== ЧТО ЭТО ЗНАЧИТ В ДЕНЬГАХ ===")
y_raw = F[:, 1]; ok = ~np.isnan(y_raw)
absm = np.nanmean(np.abs(y_raw[ok]))
print(f"  средний модуль хода за 4ч: {absm:.3f}%  ·  косты 0.35%")
print(f"  чтобы окупить косты, нужна точность выше "
      f"{50 + 0.35/(2*absm)*100:.2f}%")
