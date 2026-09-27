# -*- coding: utf-8 -*-
"""КАСКАД СОГЛАСИЯ КАК КЛАСС: слой k развернулся ТУДА, куда уже смотрят все младшие.

Найден как два отдельных ребра (n=153/469) — это кандидат в подгонку. Здесь тот же
переход проверяется КЛАССОМ: все случаи сразу, большое n, разрез по слою и стороне.
Контроль — переход слоя k ПРОТИВ младших (зеркало той же механики).
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
W = list(z["windows"]); L = T.shape[1]

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)

# переходы
ev = []
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    c = code[m]
    ch = np.where(np.diff(c) != 0)[0] + 1
    half = len(c) // 2
    for k in ch:
        ev.append((int(m[k]), int(c[k - 1]), int(c[k]), 0 if k < half else 1))
EV = np.array(ev, dtype=np.int64)
print(f"переходов: {len(EV):,}")

Tf = T[EV[:, 0] - 1]      # состояние ДО (предыдущий бар)
Tt = T[EV[:, 0]]          # состояние ПОСЛЕ
f4 = F[EV[:, 0], 1]; f24 = F[EV[:, 0], 3]
base4, base24 = np.nanmean(f4), np.nanmean(f24)
print(f"база: +4ч {base4:+.4f}% · +24ч {base24:+.4f}%\n")

print("=== КАСКАД: слой k сменился, младшие УЖЕ смотрели туда же ===")
print(f"{'слой':>6} {'окно':>7} {'сторона':>8} {'n':>8} {'+4ч':>10} {'мед':>9} "
      f"{'+24ч':>10} {'без топ10%':>11}")
res = {}
for k in range(1, L):                       # слой 0 не имеет младших
    ch = Tf[:, k] != Tt[:, k]
    for side, nm in [(1, "вверх"), (-1, "вниз")]:
        newv = Tt[:, k] == side
        younger = np.all(Tt[:, :k] == side, axis=1)    # ВСЕ младшие уже туда
        m = ch & newv & younger
        if m.sum() < 200:
            continue
        v = f4[m]; v = v[~np.isnan(v)]
        srt = np.sort(v)[::-1]
        cut = int(len(srt) * 0.10)
        frag = srt[cut:].sum() / max(len(srt) - cut, 1)
        res[(k, side)] = (m.sum(), np.nanmean(f4[m]), np.nanmedian(f4[m]),
                          np.nanmean(f24[m]), frag, m)
        print(f"{k:>6} {W[k]:>7} {nm:>8} {m.sum():>8,} {np.nanmean(f4[m]):+9.4f}% "
              f"{np.nanmedian(f4[m]):+8.4f}% {np.nanmean(f24[m]):+9.4f}% {frag:+10.4f}%")

print("\n=== КОНТРОЛЬ-ЗЕРКАЛО: слой k сменился ПРОТИВ младших ===")
print(f"{'слой':>6} {'окно':>7} {'сторона':>8} {'n':>8} {'+4ч':>10} {'мед':>9}")
for k in range(1, L):
    ch = Tf[:, k] != Tt[:, k]
    for side, nm in [(1, "вверх"), (-1, "вниз")]:
        newv = Tt[:, k] == side
        against = np.all(Tt[:, :k] == -side, axis=1)
        m = ch & newv & against
        if m.sum() < 200:
            continue
        print(f"{k:>6} {W[k]:>7} {nm:>8} {m.sum():>8,} {np.nanmean(f4[m]):+9.4f}% "
              f"{np.nanmedian(f4[m]):+8.4f}%")

print("\n=== СЛЕПАЯ ПРОВЕРКА КЛАССА: IS (1-я половина) → OOS (2-я) ===")
print(f"{'слой':>6} {'сторона':>8} {'n_IS':>7} {'IS +4ч':>10} {'n_OOS':>7} "
      f"{'OOS +4ч':>10} {'перенос':>8}")
ok_cnt = tot = 0
for (k, side), (n, mean4, med4, m24, frag, m) in sorted(res.items()):
    nm = "вверх" if side == 1 else "вниз"
    isk = m & (EV[:, 3] == 0); oos = m & (EV[:, 3] == 1)
    if isk.sum() < 100 or oos.sum() < 100:
        continue
    a, b = np.nanmean(f4[isk]), np.nanmean(f4[oos])
    good = (a - base4) * (b - base4) > 0
    ok_cnt += good; tot += 1
    print(f"{k:>6} {nm:>8} {isk.sum():>7,} {a:+9.4f}% {oos.sum():>7,} {b:+9.4f}% "
          f"{'✓' if good else '✗':>8}")
print(f"\n  знак сохранился: {ok_cnt} из {tot}")

print("\n=== ОХВАТ МОНЕТ (закон: «плюс на 4 из 10» — не эдж) ===")
for (k, side), (n, mean4, med4, m24, frag, m) in sorted(res.items()):
    if n < 1000:
        continue
    syms = SY[EV[m, 0]]
    per = [np.nanmean(f4[m][syms == s]) for s in np.unique(syms)]
    pos = sum(1 for x in per if x > base4)
    nm = "вверх" if side == 1 else "вниз"
    print(f"  слой {k} ({W[k]:>5} мин) {nm:>6}: лучше базы на {pos} из {len(per)} монет "
          f"| ср {mean4:+.4f}% | без топ10% {frag:+.4f}%")
