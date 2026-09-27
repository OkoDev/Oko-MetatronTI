# -*- coding: utf-8 -*-
"""ГРАФ ГИПЕРКУБА, ГЛУБЖЕ (продолжение от «граф на честном кубе стал чище»).

86% переходов меняют один слой — это механика лестницы. Смотрим то, что ею не
объясняется:
  A. СИНХРОННЫЕ переходы: 2+ слоя переключились разом. Редки по определению.
  B. РЕДКОСТЬ перехода как признак: p(в|из) низкая = аномалия.
  C. ТРАЕКТОРИИ между полюсами ▼×7 → ▲×7: длина пути, время, ход цены.
Всё — чистая структура, признаков нет. Куб пересчитан без утечки.
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
W = [int(x) for x in z["windows"]]; L = T.shape[1]
RNG = np.random.default_rng(20260909)

px = []
for f in sorted(glob.glob(r"C:\oko_history\1m\*.parquet")):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    r = d1.resample("3min", label="left", closed="left")
    c = pd.DataFrame({"close": r["close"].last()}).dropna()
    px.append(c.values[2200:])
CL = np.vstack(px)[:, 0]
assert len(CL) == len(T)

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
nch = (Tf != Tt).sum(1)                       # сколько слоёв сменилось за переход
f4, f24 = F[EV, 1], F[EV, 3]
base4 = np.nanmean(f4)
half = np.zeros(len(EV), np.int8)
for s in np.unique(SY):
    w = np.where(SY[EV] == s)[0]
    half[w[len(w) // 2:]] = 1
# направление: знак суммы изменений
dsum = (Tt.sum(1) - Tf.sum(1))
print(f"переходов: {len(EV):,} | база +4ч {base4:+.4f}%\n")

print("=== A. СИНХРОННЫЕ ПЕРЕХОДЫ: сколько слоёв сменилось разом ===")
print(f"{'слоёв':>6} {'n':>9} {'доля':>7} {'+4ч':>9} {'мед':>9} {'+24ч':>9} "
      f"{'по знаку':>10} {'IS→OOS':>8}")
for k in range(1, L + 1):
    m = nch == k
    if m.sum() < 200:
        continue
    # направленно: форвард × знак суммарного сдвига
    sm = m & (dsum != 0)
    dirf = f4[sm] * np.sign(dsum[sm])
    i_, o_ = dirf[half[sm] == 0], dirf[half[sm] == 1]
    tag = "—"
    if len(i_) > 60 and len(o_) > 60:
        tag = "✓" if np.nanmean(i_) * np.nanmean(o_) > 0 and np.nanmean(i_) > 0 else "✗"
    print(f"{k:>6} {m.sum():>9,} {m.mean()*100:6.2f}% {np.nanmean(f4[m]):+8.4f}% "
          f"{np.nanmedian(f4[m]):+8.4f}% {np.nanmean(f24[m]):+8.4f}% "
          f"{np.nanmean(dirf):+9.4f}% {tag:>8}")

print("\n=== B. РЕДКОСТЬ ПЕРЕХОДА: p(в|из) → форвард ===")
key = Tf @ (3 ** np.arange(L)[::-1]) * 3**L + Tt @ (3 ** np.arange(L)[::-1])
uf = Tf @ (3 ** np.arange(L)[::-1])
pk = {}
for u in np.unique(uf):
    m = uf == u
    ks, cs = np.unique(key[m], return_counts=True)
    for k_, c_ in zip(ks, cs):
        pk[int(k_)] = c_ / m.sum()
p = np.array([pk[int(k_)] for k_ in key])
print(f"{'p(в|из)':>12} {'n':>9} {'+4ч':>9} {'по знаку':>10} {'мед':>9}")
for lo, hi in [(0, .02), (.02, .05), (.05, .10), (.10, .20), (.20, .40), (.40, 1.01)]:
    m = (p >= lo) & (p < hi)
    if m.sum() < 300:
        continue
    sm = m & (dsum != 0)
    dirf = f4[sm] * np.sign(dsum[sm])
    print(f"{lo:.2f}-{hi:<7.2f} {m.sum():>9,} {np.nanmean(f4[m]):+8.4f}% "
          f"{np.nanmean(dirf):+9.4f}% {np.nanmedian(dirf):+8.4f}%")

print("\n=== C. ТРАЕКТОРИИ МЕЖДУ ПОЛЮСАМИ ▼×7 → ▲×7 ===")
FULL_UP, FULL_DN = 3**L - 1, 0
runs = []
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    c = code[m]
    pos_up = np.where(c == FULL_UP)[0]
    pos_dn = np.where(c == FULL_DN)[0]
    if len(pos_up) == 0 or len(pos_dn) == 0:
        continue
    marks = np.concatenate([pos_dn, pos_up])
    lab = np.concatenate([np.full(len(pos_dn), -1), np.full(len(pos_up), 1)])
    o = np.argsort(marks); marks, lab = marks[o], lab[o]
    prev_i, prev_l = marks[0], lab[0]
    for i, l in zip(marks[1:], lab[1:]):
        if l != prev_l:
            # переход между полюсами
            seg = c[prev_i:i + 1]
            nstates = len(np.unique(seg))
            bars = i - prev_i
            move = (CL[m[i]] - CL[m[prev_i]]) / CL[m[prev_i]] * 100 * l
            runs.append((l, bars, nstates, move))
            prev_i, prev_l = i, l
        else:
            prev_i = i
RU = pd.DataFrame(runs, columns=["dir", "bars", "states", "move"])
print(f"  найдено переходов между полюсами: {len(RU):,}")
for d_, nm in [(1, "▼×7 → ▲×7"), (-1, "▲×7 → ▼×7")]:
    g = RU[RU.dir == d_]
    if len(g) < 30:
        continue
    print(f"  {nm}: n={len(g):>5,} | баров 3m медиана {g.bars.median():.0f} "
          f"({g.bars.median()*3/60:.1f} ч) | уникальных ячеек по пути "
          f"{g.states.median():.0f} | ход цены медиана {g.move.median():+.2f}% "
          f"| среднее {g.move.mean():+.2f}%")
print("\n  🔑 ход цены здесь — ЗА ВЕСЬ путь между полюсами (ретроспектива).")
print("     Торгуемо только если известен момент старта — см. A и B выше.")
