# -*- coding: utf-8 -*-
"""ПЕРВОЕ ДОСТИЖЕНИЕ ПОЛЮСА (продолжение графа, 09.09.2026).

Траектория ▼×7 → ▲×7 стоит 14% цены и длится 81 час. Начало пути известно В МОМЕНТЕ
(попадание в полюс фиксируется сразу), конец — нет. Ставим каузально:

  вход  = момент попадания в полюс (первый бар в ячейке ▼×7 или ▲×7)
  исход = что случится раньше: противоположный полюс или возврат в свой
  плюс   форвард на горизонте, СОРАЗМЕРНОМ пути (85 часов), а не 4 часа

🔴 Контроль: случайный бар той же монеты, тот же квинтиль ATR, тот же горизонт.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube50_fix.npz", allow_pickle=True)
T, SY = z["T"], z["SY"]
L = T.shape[1]
RNG = np.random.default_rng(20260909)
HOR = [400, 850, 1700, 3400]          # баров 3m: 20ч · 42ч · 85ч · 170ч
COST = 0.35

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

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
FULL_UP, FULL_DN = 3**L - 1, 0
atr = pd.Series((HI - LO) / CL).rolling(200, min_periods=60).mean().values * 100
q = np.zeros(len(T), np.int8)
bnd = {}
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    bnd[int(s)] = (int(m[0]), int(m[-1]))
    v = atr[m]; ok = ~np.isnan(v)
    if ok.sum() > 100:
        q[m[ok]] = np.digitize(v[ok], np.nanpercentile(v[ok], [20, 40, 60, 80])) + 1

# моменты ПОПАДАНИЯ в полюс (первый бар в ячейке)
entries = {FULL_DN: [], FULL_UP: []}
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    c = code[m]
    for pole in (FULL_DN, FULL_UP):
        hit = (c == pole)
        first = np.where(hit & ~np.concatenate([[False], hit[:-1]]))[0]
        entries[pole] += [int(m[i]) for i in first]
print(f"попаданий в ▼×7: {len(entries[FULL_DN]):,} | в ▲×7: {len(entries[FULL_UP]):,}\n")

print("=== ПЕРВОЕ ДОСТИЖЕНИЕ: что раньше — противоположный полюс или возврат в свой ===")
print(f"{'из':>6} {'n':>7} {'дошли до др.':>13} {'вернулись':>11} {'ни то ни то':>12} "
      f"{'ход при дох.':>13} {'ход при возвр.':>15}")
for pole, nm, side in [(FULL_DN, "▼×7", 1), (FULL_UP, "▲×7", -1)]:
    opp = FULL_UP if pole == FULL_DN else FULL_DN
    reach = ret = none = 0
    mr, mv = [], []
    for i in entries[pole]:
        hi_b = bnd[int(SY[i])][1]
        e = CL[i]
        left = False
        res = None
        for b in range(i + 1, min(i + 6000, hi_b + 1)):
            if not left:
                if code[b] != pole:
                    left = True
                continue
            if code[b] == opp:
                res = ("reach", (CL[b] - e) / e * 100 * side); break
            if code[b] == pole:
                res = ("ret", (CL[b] - e) / e * 100 * side); break
        if res is None:
            none += 1
        elif res[0] == "reach":
            reach += 1; mr.append(res[1])
        else:
            ret += 1; mv.append(res[1])
    tot = reach + ret + none
    if tot == 0:
        continue
    print(f"{nm:>6} {tot:>7,} {reach/tot*100:12.1f}% {ret/tot*100:10.1f}% "
          f"{none/tot*100:11.1f}% {np.median(mr) if mr else np.nan:+12.2f}% "
          f"{np.median(mv) if mv else np.nan:+14.2f}%")

print("\n=== ФОРВАРД ИЗ ПОЛЮСА НА ГОРИЗОНТЕ, СОРАЗМЕРНОМ ПУТИ ===")
print(f"{'из':>6} {'горизонт':>9} {'n':>7} {'ход':>9} {'мед':>9} {'контроль':>10} "
      f"{'разница':>9} {'монет+':>8}")
for pole, nm, side in [(FULL_DN, "▼×7", 1), (FULL_UP, "▲×7", -1)]:
    for h in HOR:
        vals, ctls, syms = [], [], []
        for i in entries[pole]:
            hi_b = bnd[int(SY[i])][1]
            if i + h > hi_b:
                continue
            vals.append((CL[i + h] - CL[i]) / CL[i] * 100 * side)
            syms.append(int(SY[i]))
            pl = np.where((SY == SY[i]) & (q == q[i]))[0]
            pl = pl[(pl > 10) & (pl + h <= hi_b)]
            if len(pl):
                j = int(RNG.choice(pl))
                ctls.append((CL[j + h] - CL[j]) / CL[j] * 100 * side)
        if len(vals) < 100:
            continue
        v = np.array(vals); c_ = np.array(ctls)
        dfp = pd.DataFrame({"s": syms, "v": v})
        per = dfp.groupby("s").v.mean()
        print(f"{nm:>6} {h*3/60:8.0f}ч {len(v):>7,} {v.mean():+8.3f}% "
              f"{np.median(v):+8.3f}% {c_.mean():+9.3f}% {v.mean()-c_.mean():+8.3f}% "
              f"{int((per>0).sum())}/{len(per)}")
