# -*- coding: utf-8 -*-
"""КОНТРОЛЬ НА ВОЛАТИЛЬНОСТЬ для «разворот структуры на большом окне».

🔴 Разворот случается на движении, а движение само даёт больший форвард. Без матчинга
по волатильности замер меряет «здесь была свеча покрупнее», а не слом.

Контроль: случайный бар ТОЙ ЖЕ монеты, в том же квинтиле ATR слоя, ±30 суток.
Плюс: перекрытие наблюдений — считаем эффективное n через среднее расстояние событий.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube50.npz", allow_pickle=True)
T, F, SY = z["T"], z["F"], z["SY"]
W = [int(x) for x in z["windows"]]; L = T.shape[1]
RNG = np.random.default_rng(20260909)

# ATR базовой сетки 3m (для матчинга) — из тех же файлов, тот же порядок и прогрев
tr_all = []
for f in sorted(glob.glob(r"C:\oko_history\1m\*.parquet")):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    r = d1.resample("3min", label="left", closed="left")
    c = pd.DataFrame({"high": r["high"].max(), "low": r["low"].min(),
                      "close": r["close"].last()}).dropna()
    tr = ((c["high"] - c["low"]) / c["close"]).rolling(200, min_periods=50).mean()
    tr_all.append(tr.values[6600 // 3:])
ATR = np.concatenate(tr_all)
assert len(ATR) == len(T), (len(ATR), len(T))

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

# квинтиль ATR внутри монеты
qa = np.zeros(len(T), np.int8)
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    v = ATR[m]
    ok = ~np.isnan(v)
    if ok.sum() > 100:
        qa[m[ok]] = np.digitize(v[ok], np.nanpercentile(v[ok], [20, 40, 60, 80]))

print(f"=== РАЗВОРОТ СТАРШЕГО СЛОЯ против КОНТРОЛЯ, матч по монете + квинтилю ATR ===")
print(f"{'слой':>5} {'окно':>6} {'стор':>6} {'n':>7} {'событие':>10} {'контроль':>10} "
      f"{'разница':>9} {'t':>7} {'эфф.n':>7}")
for k in (3, 4, 5):
    for side, nm in [(1, "вверх"), (-1, "вниз")]:
        m = (Tf[:, k] != Tt[:, k]) & (Tt[:, k] == side)
        ii = EV[m]
        if len(ii) < 150:
            continue
        v = F[ii, 1]
        v = v[~np.isnan(v)]
        # контроль: тот же символ, тот же квинтиль ATR
        ctl = []
        for _ in range(3):
            pick = []
            for i in ii:
                s, q = SY[i], qa[i]
                cand = np.where((SY == s) & (qa == q))[0]
                if len(cand):
                    pick.append(int(RNG.choice(cand)))
            cv = F[np.array(pick), 1]
            ctl.append(np.nanmean(cv))
        c = float(np.mean(ctl))
        # эффективное n: события перекрыты, форвард 80 баров
        gaps = np.diff(np.sort(ii))
        eff = len(ii) * min(1.0, np.median(gaps) / 80) if len(gaps) else len(ii)
        t = (np.nanmean(v) - c) / (np.nanstd(v) / np.sqrt(max(eff, 1)))
        print(f"{k:>5} {W[k]:>6} {nm:>6} {len(ii):>7,} {np.nanmean(v):+9.4f}% "
              f"{c:+9.4f}% {np.nanmean(v)-c:+8.4f}% {t:7.2f} {eff:7.0f}")

print("\n=== ПЕРЕКРЫТИЕ: медианный интервал между событиями (баров 3m; форвард=80) ===")
for k in (3, 4, 5):
    m = (Tf[:, k] != Tt[:, k])
    ii = np.sort(EV[m])
    g = np.diff(ii)
    g = g[g > 0]
    print(f"  слой {k} (окно {W[k]}): медиана {np.median(g):.0f} баров "
          f"({np.median(g)*3/60:.1f} ч) | доля интервалов < 80 баров: {(g < 80).mean()*100:.0f}%")
