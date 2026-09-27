# -*- coding: utf-8 -*-
"""HYP-2: СУБКУБ ТОЛЬКО ИЗ СТАРШИХ СЛОЁВ (10.09.2026).

Информация распределена крайне неравномерно:
    слой 10 мин:  0.00000 бит      слой 2000 мин: 0.00008
    слой 20:      0.00000          слой 6600:     0.00041   ← ×10 остальных
    слой 50:      0.00004
Младшие слои добавляют РАЗМЕРНОСТЬ без информации, а размерность стоит статистической
мощности: 2187 ячеек против 27 — это на два порядка меньше данных в каждой.

Проверяем: субкуб из 3 старших слоёв информативнее полного семислойного?
Метрика — та же взаимная информация со знаком движения, плюс на КАЖДОМ подмножестве
слоёв (все 127 непустых сочетаний), чтобы найти оптимальный состав.
"""
import os, sys, itertools
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
y_raw = F[:, 3]                      # 24ч
ok = ~np.isnan(y_raw)
y = np.where(ok, (y_raw > 0).astype(int), -1)
half = np.zeros(len(T), np.int8)
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    half[m[len(m) // 2:]] = 1
print(f"баров {len(T):,} · слои {W}\n")


def mi(x, y_, nx, ny=2):
    m = (x >= 0) & (y_ >= 0)
    a, b = x[m], y_[m]
    n = len(a)
    j = np.bincount(a * ny + b, minlength=nx * ny).reshape(nx, ny) / n
    px = j.sum(1, keepdims=True); py = j.sum(0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = j * np.log2(j / (px * py))
    return float(np.nansum(t))


def code_of(layers):
    c = np.zeros(len(T), np.int32)
    for i in layers:
        c = c * 3 + (T[:, i] + 1)
    return c


print("=== ВСЕ СОЧЕТАНИЯ СЛОЁВ: информация против размерности ===")
res = []
for k in range(1, L + 1):
    for comb in itertools.combinations(range(L), k):
        c = code_of(comb)
        u, ci = np.unique(c, return_inverse=True)
        I = mi(ci, y, len(u))
        # контроль: перемешанный таргет
        yp = y.copy(); v = yp[ok]; RNG.shuffle(v); yp[ok] = v
        Ic = mi(ci, yp, len(u))
        res.append((comb, len(u), I, I - Ic))
res.sort(key=lambda r: -r[3])
print(f"{'слои (окна, мин)':>34} {'ячеек':>7} {'I, бит':>9} {'сверх контроля':>15}")
for comb, nu, I, net in res[:12]:
    lbl = "·".join(str(W[i]) for i in comb)
    print(f"{lbl:>34} {nu:>7} {I:9.5f} {net:15.5f}")

print("\n=== ЛУЧШЕЕ ПО КАЖДОМУ РАЗМЕРУ ===")
print(f"{'слоёв':>6} {'лучший состав (окна)':>34} {'ячеек':>7} {'сверх контроля':>15}")
for k in range(1, L + 1):
    sub = [r for r in res if len(r[0]) == k]
    if not sub:
        continue
    best = max(sub, key=lambda r: r[3])
    lbl = "·".join(str(W[i]) for i in best[0])
    print(f"{k:>6} {lbl:>34} {best[1]:>7} {best[3]:15.5f}")

print("\n=== ПОЛНЫЙ КУБ ПРОТИВ ЛУЧШЕГО СУБКУБА ===")
full = [r for r in res if len(r[0]) == L][0]
best = res[0]
print(f"  полный (7 слоёв, {full[1]} ячеек):  {full[3]:.5f} бит")
lbl = "·".join(str(W[i]) for i in best[0])
print(f"  лучший субкуб ({len(best[0])} слоёв, {best[1]} ячеек): {best[3]:.5f} бит  [{lbl}]")
print(f"  выигрыш: {best[3]/max(full[3],1e-9):.2f}×  при размерности в "
      f"{full[1]/best[1]:.1f}× меньше")

print("\n=== УСТОЙЧИВОСТЬ ЛУЧШЕГО СУБКУБА: IS → OOS ===")
c = code_of(best[0])
u, ci = np.unique(c, return_inverse=True)
for lab, m_ in [("IS", half == 0), ("OOS", half == 1)]:
    mm = m_ & ok
    I = mi(ci[mm], y[mm], len(u))
    yp = y[mm].copy(); RNG.shuffle(yp)
    print(f"  {lab:>4}: I = {I:.5f} бит · сверх контроля {I - mi(ci[mm], yp, len(u)):+.5f}")

print("\n=== ЭКВИВАЛЕНТНАЯ ТОЧНОСТЬ ЛУЧШЕГО СУБКУБА ===")
p = (y[ok] == 1).mean()
HY = -(p * np.log2(p) + (1 - p) * np.log2(1 - p))
lo_, hi_ = 0.5, 0.99
for _ in range(40):
    m_ = (lo_ + hi_) / 2
    Hm = -(m_ * np.log2(m_) + (1 - m_) * np.log2(1 - m_))
    if HY - Hm > best[3]:
        hi_ = m_
    else:
        lo_ = m_
print(f"  {(lo_+hi_)/2*100:.2f}%   (полный куб давал 55.55%, нужно 62.90%)")
