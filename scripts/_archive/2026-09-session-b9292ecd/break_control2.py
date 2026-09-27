# -*- coding: utf-8 -*-
"""КОНТРОЛЬ НА ВОЛАТИЛЬНОСТЬ (быстрая версия): пулы предвычислены, не сканируем массив
на каждое событие. Вопрос тот же: разворот структуры на большом окне — это слом или
просто «здесь была свеча покрупнее»?"""
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

tr_all = []
for f in sorted(glob.glob(r"C:\oko_history\1m\*.parquet")):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    r = d1.resample("3min", label="left", closed="left")
    c = pd.DataFrame({"high": r["high"].max(), "low": r["low"].min(),
                      "close": r["close"].last()}).dropna()
    tr_all.append(((c["high"] - c["low"]) / c["close"])
                  .rolling(200, min_periods=50).mean().values[2200:])
ATR = np.concatenate(tr_all)
assert len(ATR) == len(T)

qa = np.zeros(len(T), np.int8)
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    v = ATR[m]; ok = ~np.isnan(v)
    if ok.sum() > 100:
        qa[m[ok]] = np.digitize(v[ok], np.nanpercentile(v[ok], [20, 40, 60, 80])) + 1

# пулы: (символ, квинтиль) -> индексы, где форвард известен
f4 = F[:, 1]
valid = ~np.isnan(f4)
key = SY.astype(np.int64) * 8 + qa
order = np.argsort(key[valid], kind="stable")
vidx = np.where(valid)[0][order]
vkey = key[vidx]
uk, starts = np.unique(vkey, return_index=True)
ends = np.append(starts[1:], len(vkey))
pool = {int(k): (int(a), int(b)) for k, a, b in zip(uk, starts, ends)}
print(f"пулов (символ × квинтиль ATR): {len(pool)}\n")

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


def control(ii, reps=5):
    out = []
    kk = key[ii]
    for _ in range(reps):
        pick = np.empty(len(ii), np.int64)
        for j, k in enumerate(kk):
            a, b = pool.get(int(k), (0, len(vidx)))
            pick[j] = vidx[RNG.integers(a, b)] if b > a else ii[j]
        out.append(np.nanmean(f4[pick]))
    return float(np.mean(out)), float(np.std(out))


print("=== РАЗВОРОТ СТАРШЕГО СЛОЯ vs КОНТРОЛЬ (матч: монета + квинтиль ATR) ===")
print(f"{'слой':>5} {'окно':>6} {'стор':>6} {'n':>7} {'событие':>10} {'контроль':>10} "
      f"{'разница':>9} {'эфф.n':>7} {'t':>7}")
for k in (3, 4, 5):
    for side, nm in [(1, "вверх"), (-1, "вниз")]:
        m = (Tf[:, k] != Tt[:, k]) & (Tt[:, k] == side)
        ii = EV[m]
        if len(ii) < 150:
            continue
        v = f4[ii]; vv = v[~np.isnan(v)]
        c, cs = control(ii)
        g = np.diff(np.sort(ii)); g = g[g > 0]
        eff = len(ii) * min(1.0, (np.median(g) / 80 if len(g) else 1))
        t = (np.nanmean(vv) - c) / (np.nanstd(vv) / np.sqrt(max(eff, 1)))
        print(f"{k:>5} {W[k]:>6} {nm:>6} {len(ii):>7,} {np.nanmean(vv):+9.4f}% "
              f"{c:+9.4f}% {np.nanmean(vv)-c:+8.4f}% {eff:7.0f} {t:7.2f}")

print("\n=== КЛАСТЕРНОСТЬ: сидят ли события в немногих днях ===")
day = (np.arange(len(T)) * 0)  # день внутри монеты по индексу: 480 баров 3m = сутки
for k in (3, 4, 5):
    m = (Tf[:, k] != Tt[:, k])
    ii = EV[m]
    d = (ii // 480)
    vc = pd.Series(d).value_counts()
    top = vc.head(max(1, len(vc) // 10)).sum() / len(ii) * 100
    sv = pd.Series(SY[ii]).value_counts()
    print(f"  слой {k} ({W[k]:>5} мин): n={len(ii):>7,} | суток {len(vc):>5} | "
          f"верхние 10% суток держат {top:5.1f}% | монет {len(sv)} | "
          f"максимум на монету {sv.iloc[0]/len(ii)*100:.1f}%")

print("\n=== РАЗРЕЗ ПО ПОЛОВИНАМ ИСТОРИИ И ПО СТОРОНАМ ===")
for k in (3, 4, 5):
    for side, nm in [(1, "вверх"), (-1, "вниз")]:
        m = (Tf[:, k] != Tt[:, k]) & (Tt[:, k] == side)
        ii = EV[m]
        if len(ii) < 150:
            continue
        h = np.zeros(len(ii), bool)
        for s in np.unique(SY[ii]):
            w = np.where(SY[ii] == s)[0]
            h[w[len(w) // 2:]] = True
        a, b = np.nanmean(f4[ii[~h]]), np.nanmean(f4[ii[h]])
        print(f"  слой {k} {nm:>5}: 1-я половина {a:+.4f}% | 2-я {b:+.4f}% | "
              f"{'устойчиво' if a*b > 0 else 'ЗНАК МЕНЯЕТСЯ'}")
