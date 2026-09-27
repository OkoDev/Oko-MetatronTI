# -*- coding: utf-8 -*-
"""ТРИ ЭТАПА НА ГОТОВОМ ГИПЕРКУБЕ (Егор: «у нас собран гиперкуб», 09.09.2026).

  1. ГИПОТЕЗА  — предполагаемое завершение импульса. Масштаб якоря — ОСЬ, не константа:
                 нога ≥ K·ATR за M баров, экстремум не обновлялся 2 бара; M перебирается.
  2. ПОДТВЕРЖДЕНИЯ — состояние 7 слоёв ГОТОВОГО куба (hypercube50_fix, без look-ahead):
                 сколько слоёв смотрит ПРОТИВ импульса.
  3. ФАКТ    — обновится ли экстремум за CONFIRM баров: завершение или пауза.

Куб построен на сетке 3m, окна слоёв 10·20·50·180·600·2000·6600 мин.
Порог K проверяется на чувствительность (2 / 3 / 5).
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
BASE = 3                                  # сетка куба, мин
MS = [20, 60, 200, 800]                   # масштаб якоря в барах 3m: 1ч · 3ч · 10ч · 40ч
K_LIST = [95, 98, 99]        # ПЕРЦЕНТИЛЬ размаха окна: импульс = выброс, а не «выше среднего»
CONFIRM_MULT = 2.0                        # ждём обновления экстремума M×2 баров
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
assert len(PX) == len(T), (len(PX), len(T))
bnd = {int(s): (int(np.where(SY == s)[0][0]), int(np.where(SY == s)[0][-1]))
       for s in np.unique(SY)}
print(f"баров куба: {len(T):,} | монет: {len(bnd)} | слои: {W}\n", flush=True)

# 🔴 ПОРОГ В ЕДИНИЦАХ ОКНА: размах за M баров сравнивается с ТИПИЧНЫМ размахом
# за те же M баров (медиана по истории монеты), а не с ATR одного бара.
# Прежняя версия сравнивала с ATR бара — за 800 баров порог срабатывал всегда
# (122 млн якорей вместо тысяч).
def span_thresholds(M, qs):
    """Порог размаха окна как ПЕРЦЕНТИЛЬ по истории монеты: импульс — выброс.
    Медиана (K=1.0) давала 69% баров — событием это назвать нельзя."""
    hi_r = pd.Series(HI).rolling(M, min_periods=M // 2).max().values
    lo_r = pd.Series(LO).rolling(M, min_periods=M // 2).min().values
    rel = (hi_r - lo_r) / CL
    out = {q: np.full(len(rel), np.nan) for q in qs}
    for s_ in np.unique(SY):
        a_, b_ = bnd[int(s_)]
        v = rel[a_:b_ + 1]
        v = v[~np.isnan(v)]
        if len(v) > 500:
            for q in qs:
                out[q][a_:b_ + 1] = np.percentile(v, q)
    return out

rows = []
for M in MS:
    CONF = int(M * CONFIRM_MULT)
    thr_map = span_thresholds(M, K_LIST)
    for K in K_LIST:
        norm = thr_map[K]
        for s in np.unique(SY):
            a0, a1 = bnd[int(s)]
            for t in range(a0 + M + 5, a1 - CONF - 500):
                nrm = norm[t]
                if np.isnan(nrm) or nrm <= 0 or np.isnan(F[t, 3]):
                    continue
                st = t - M
                side = 0
                # нога от начала окна до экстремума, в единицах ТИПИЧНОГО размаха окна
                up = (HI[st:t + 1].max() - LO[st]) / LO[st]
                dn = (HI[st] - LO[st:t + 1].min()) / HI[st]
                if up >= nrm and HI[t - 1:t + 1].max() < HI[st:t].max():
                    side = 1
                elif dn >= nrm and LO[t - 1:t + 1].min() > LO[st:t].min():
                    side = -1
                if side == 0:
                    continue
                if side == 1:
                    peak = HI[st:t + 1].max()
                    ended = int(HI[t + 1:t + 1 + CONF].max() < peak)
                else:
                    tro = LO[st:t + 1].min()
                    ended = int(LO[t + 1:t + 1 + CONF].min() > tro)
                against = int((T[t] == -side).sum())
                rows.append((M, K, int(s), side, ended, against,
                             float(F[t, 3] * -side), int(t > (a0 + a1) // 2)))
        print(f"  M={M} K={K}: якорей {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["M", "K", "sym", "side", "ended", "against",
                                "fwd", "half"])
R.to_pickle(D + r"\impulse_on_cube.pkl")
print(f"\nвсего якорей: {len(R):,}\n")

print("=== ЭТАП 1+3: доля НАСТОЯЩИХ завершений по масштабу якоря и порогу ===")
print(f"{'M баров':>8} {'часов':>7} {'K':>5} {'n':>9} {'доля завершений':>17}")
for M in MS:
    for K in K_LIST:
        g = R[(R.M == M) & (R.K == K)]
        if len(g) < 500:
            continue
        print(f"{M:>8} {M*BASE/60:6.1f}ч {K:>5.0f} {len(g):>9,} "
              f"{g.ended.mean()*100:16.1f}%")

print("\n=== ЭТАП 2: РАЗЛИЧАЕТ ЛИ КУБ завершение от паузы ===")
print(f"{'M':>6} {'K':>5} {'слоёв против':>13} {'n':>8} {'доля заверш.':>14} "
      f"{'lift':>7} {'форвард':>10} {'нетто':>9}")
for M in MS:
    for K in [98]:
        sub = R[(R.M == M) & (R.K == K)]
        if len(sub) < 1000:
            continue
        b0 = sub.ended.mean()
        for a in range(0, L + 1):
            g = sub[sub.against == a]
            if len(g) < 300:
                continue
            print(f"{M:>6} {K:>5.0f} {a:>13} {len(g):>8,} {g.ended.mean()*100:13.1f}% "
                  f"{g.ended.mean()/b0:7.2f} {g.fwd.mean():+9.3f}% "
                  f"{g.fwd.mean()-COST:+8.3f}%")
        print()

print("=== ЗЕРКАЛЬНОСТЬ И ПЕРЕНОС (слоёв против ≥5) ===")
print(f"{'M':>6} {'сторона':>8} {'n':>8} {'доля заверш.':>14} {'форвард':>10} "
      f"{'мед':>9} {'IS':>9} {'OOS':>9} {'перенос':>8} {'монет+':>8}")
for M in MS:
    for side, nm in [(1, "вверх"), (-1, "вниз")]:
        g = R[(R.M == M) & (R.K == 98) & (R.against >= 5) & (R.side == side)]
        if len(g) < 200:
            continue
        i_, o_ = g[g.half == 0].fwd, g[g.half == 1].fwd
        tag = "✓" if len(i_) > 50 and len(o_) > 50 and i_.mean() * o_.mean() > 0 \
            and i_.mean() > 0 else "✗"
        per = g.groupby("sym").fwd.mean()
        print(f"{M:>6} {nm:>8} {len(g):>8,} {g.ended.mean()*100:13.1f}% "
              f"{g.fwd.mean():+9.3f}% {g.fwd.median():+8.3f}% {i_.mean():+8.3f}% "
              f"{o_.mean():+8.3f}% {tag:>8} {int((per>0).sum())}/{len(per)}")
    print()

print("=== ФОРВАРД ПО ФАКТУ ИСХОДА (проверка, что классификация вообще важна) ===")
for M in MS:
    sub = R[(R.M == M) & (R.K == 98)]
    if len(sub) < 1000:
        continue
    e1 = sub[sub.ended == 1]; e0 = sub[sub.ended == 0]
    print(f"  M={M:>4} ({M*BASE/60:4.1f}ч): завершение n={len(e1):>7,} "
          f"форвард {e1.fwd.mean():+.3f}% | пауза n={len(e0):>7,} "
          f"форвард {e0.fwd.mean():+.3f}% | разница {e1.fwd.mean()-e0.fwd.mean():+.3f}%")
