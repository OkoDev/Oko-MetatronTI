# -*- coding: utf-8 -*-
"""СЕРЕДИННАЯ СОГЛАСОВАННОСТЬ И МОМЕНТ ПЕРЕХОДА (Егор, 09.09.2026).

Гипотеза: разворот — это не состояние, а МОМЕНТ, когда согласованность лестницы проходит
через середину. На эталоне HYPE в точке дна было ▼▼▼▲▲▲▼ — сумма знаков −1, слои
разделены пополам.

S(t) = сумма знаков слоёв. Меряем:
  A. частота разворотов цены при разных |S| — правда ли развороты у середины;
  B. форвард после ПЕРЕСЕЧЕНИЯ S через ноль (момент перехода), по направлению перехода;
  C. то же с разделением по фазе рынка — режим это или структура.

Куб 1h, 4 года, 80 монет, состояние по ЗАКРЫТЫМ барам.
"""
import os, sys
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\regime_cube.npz", allow_pickle=True)
T, F, SY, IS_BULL = z["T"], z["F"], z["SY"], z["is_bull"]
L = T.shape[1]
S = T.sum(1).astype(np.int8)
ok = ~np.isnan(F)
print(f"баров 1h: {len(T):,} | слоёв: {L} | S ∈ [{S.min()}, {S.max()}]\n")

print("=== A. РАСПРЕДЕЛЕНИЕ |S| И ФОРВАРД (24ч) ===")
print(f"{'|S|':>5} {'n':>10} {'доля':>7} {'ход':>9} {'|ход|':>8} {'σ хода':>8}")
for a in range(0, L + 1):
    m = (np.abs(S) == a) & ok
    if m.sum() < 5000:
        continue
    print(f"{a:>5} {m.sum():>10,} {m.mean()*100:6.2f}% {np.nanmean(F[m]):+8.4f}% "
          f"{np.nanmean(np.abs(F[m])):7.4f}% {np.nanstd(F[m]):7.3f}%")

print("\n=== B. ПЕРЕСЕЧЕНИЕ S ЧЕРЕЗ НОЛЬ — момент переворота лестницы ===")
cross_up, cross_dn = [], []
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    v = S[m]
    for i in range(1, len(v)):
        if v[i - 1] <= 0 < v[i]:
            cross_up.append(int(m[i]))
        elif v[i - 1] >= 0 > v[i]:
            cross_dn.append(int(m[i]))
cu = np.array(cross_up); cd = np.array(cross_dn)
print(f"  пересечений вверх: {len(cu):,} · вниз: {len(cd):,}")
base = np.nanmean(F[ok])
print(f"  база (все бары): {base:+.4f}%\n")
print(f"{'событие':>18} {'n':>9} {'ход':>9} {'по знаку':>10} {'мед':>9} "
      f"{'сверх базы':>11} {'WR':>7} {'монет+':>9}")
for nm, idx, sgn in [("S: вверх через 0", cu, 1), ("S: вниз через 0", cd, -1)]:
    idx = idx[ok[idx]]
    if len(idx) < 500:
        continue
    v = F[idx] * sgn
    per = []
    for s in np.unique(SY[idx]):
        mm = idx[SY[idx] == s]
        if len(mm) > 30:
            per.append(np.nanmean(F[mm] * sgn))
    print(f"{nm:>18} {len(idx):>9,} {np.nanmean(F[idx]):+8.4f}% {v.mean():+9.4f}% "
          f"{np.median(v):+8.4f}% {v.mean()-abs(base):+10.4f}% {(v>0).mean()*100:6.1f}% "
          f"{sum(1 for x in per if x>0)}/{len(per)}")

print("\n=== ВЕЛИЧИНА СКАЧКА: |ΔS| при пересечении → сила хода ===")
print(f"{'|ΔS|':>6} {'n':>9} {'по знаку':>10} {'мед':>9} {'WR':>7}")
allc = np.concatenate([cu, cd])
allsgn = np.concatenate([np.ones(len(cu), np.int8), -np.ones(len(cd), np.int8)])
prevS = np.array([S[i - 1] for i in allc])
dS = np.abs(S[allc] - prevS)
for d_ in sorted(np.unique(dS)):
    m = (dS == d_) & ok[allc]
    if m.sum() < 500:
        continue
    v = F[allc[m]] * allsgn[m]
    print(f"{d_:>6} {m.sum():>9,} {v.mean():+9.4f}% {np.median(v):+8.4f}% "
          f"{(v>0).mean()*100:6.1f}%")

print("\n=== C. РАЗДЕЛЕНИЕ ПО ФАЗЕ: режим или структура ===")
print(f"{'событие':>18} {'фаза':>9} {'n':>9} {'по знаку':>10} {'база фазы':>11} "
      f"{'сверх':>9} {'монет+':>9}")
for nm, idx, sgn in [("S: вверх через 0", cu, 1), ("S: вниз через 0", cd, -1)]:
    idx = idx[ok[idx]]
    for ph, pn in [(True, "БЫК"), (False, "медведь")]:
        sel = idx[IS_BULL[idx] == ph]
        if len(sel) < 300:
            continue
        bph = np.nanmean(F[(IS_BULL == ph) & ok])
        v = F[sel] * sgn
        per = []
        for s in np.unique(SY[sel]):
            mm = sel[SY[sel] == s]
            if len(mm) > 20:
                per.append(np.nanmean(F[mm] * sgn))
        print(f"{nm:>18} {pn:>9} {len(sel):>9,} {v.mean():+9.4f}% {bph*sgn:+10.4f}% "
              f"{v.mean()-bph*sgn:+8.4f}% {sum(1 for x in per if x>0)}/{len(per)}")
