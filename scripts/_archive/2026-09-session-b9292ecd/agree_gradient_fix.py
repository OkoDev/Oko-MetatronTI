# -*- coding: utf-8 -*-
"""ГРАДИЕНТ СОГЛАСИЯ: нужно ли согласие младших вообще?

Контроль оказался ВТРОЕ сильнее каскада (+1.73% против +0.46%). Значит гипотезу надо
переформулировать: возможно, платит сам разворот старшего слоя, а согласие младших —
признак опоздания. Раскладываем по ЧИСЛУ согласных младших: 0, 1, 2, ... k.
Если градиент убывающий — согласие вредит, а не помогает.
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
f4, f24 = F[EV, 1], F[EV, 3]
half = np.zeros(len(EV), np.int8)
for s in np.unique(SY):
    w = np.where(SY[EV] == s)[0]
    half[w[len(w) // 2:]] = 1
base = np.nanmean(f4)
print(f"переходов: {len(EV):,} | база +4ч {base:+.4f}%\n")

print("=== ГРАДИЕНТ: сколько МЛАДШИХ слоёв согласны с разворотом старшего ===")
print(f"{'слой':>5} {'окно':>6} {'стор':>5} {'согл.':>6} {'n':>8} {'+4ч':>10} {'мед':>9} "
      f"{'+24ч':>10} {'IS→OOS':>9} {'монет+':>8}")
for k in (3, 4, 5):
    for side, nm in [(1, "вверх"), (-1, "вниз")]:
        ch = (Tf[:, k] != Tt[:, k]) & (Tt[:, k] == side)
        nagree = (Tt[:, :k] == side).sum(1)
        for a in range(0, k + 1):
            m = ch & (nagree == a)
            if m.sum() < 120:
                continue
            mi, mo = m & (half == 0), m & (half == 1)
            tag = "—"
            if mi.sum() >= 60 and mo.sum() >= 60:
                vi, vo = np.nanmean(f4[mi]), np.nanmean(f4[mo])
                tag = "✓" if (vi - base) * (vo - base) > 0 else "✗"
            syms = SY[EV[m]]
            per = [np.nanmean(f4[m][syms == s]) for s in np.unique(syms)]
            good = sum(1 for x in per if (x - base) * side > 0)
            print(f"{k:>5} {W[k]:>6} {nm:>5} {a:>3}/{k} {m.sum():>8,} "
                  f"{np.nanmean(f4[m]):+9.4f}% {np.nanmedian(f4[m]):+8.4f}% "
                  f"{np.nanmean(f24[m]):+9.4f}% {tag:>9} {good:>4}/{len(per)}")
        print()

print("=== ПРОСТО РАЗВОРОТ СТАРШЕГО, без условий на младших ===")
print(f"{'слой':>5} {'окно':>6} {'стор':>5} {'n':>8} {'+4ч':>10} {'мед':>9} {'+24ч':>10}")
for k in (3, 4, 5):
    for side, nm in [(1, "вверх"), (-1, "вниз")]:
        m = (Tf[:, k] != Tt[:, k]) & (Tt[:, k] == side)
        if m.sum() < 120:
            continue
        print(f"{k:>5} {W[k]:>6} {nm:>5} {m.sum():>8,} {np.nanmean(f4[m]):+9.4f}% "
              f"{np.nanmedian(f4[m]):+8.4f}% {np.nanmean(f24[m]):+9.4f}%")
