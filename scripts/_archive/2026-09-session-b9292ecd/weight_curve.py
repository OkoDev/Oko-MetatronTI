# -*- coding: utf-8 -*-
"""КРИВАЯ ВЕСА ОТ ОКНА (запрос Егора 09.09.2026): «вес соразмерно пересчитывать».

Веса в боте заданы для трёх ТФ (15m/1h/4h). После углубления до 1m лестница непрерывна,
нужна ФУНКЦИЯ w(окно), а не таблица. Плотная сетка окон → сила разворота структуры на
каждом → порог включения + показатель степени.

🔴 Горизонт форварда ОДИН для всех окон (4ч), иначе рост силы спутается с ростом
диффузии на длинном горизонте. Контроль: случайный бар той же монеты, тот же квинтиль ATR.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure

LEN = 10
# плотная сетка ТФ → окно = ТФ×10: 30 50 80 120 180 280 420 640 1000 1500 2200 3400 5000
TFS = [3, 5, 8, 12, 18, 28, 42, 64, 100, 150, 220, 340, 500]
NSYM = 24
HOLD_MIN = 240                      # горизонт форварда ОДИН для всех: 4 часа
RNG = np.random.default_rng(20260909)
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | окна: {[t*LEN for t in TFS]}\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


acc = {tf: {1: [0, 0.0, 0.0], -1: [0, 0.0, 0.0]} for tf in TFS}   # n, сумма ev, сумма ctl
per_sym = {tf: {1: [], -1: []} for tf in TFS}
for fi, f in enumerate(files, 1):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 400:
            continue
        h = max(1, HOLD_MIN // tf)
        c = d["close"].values
        n = len(c)
        fwd = np.full(n, np.nan)
        fwd[:-h] = (c[h:] - c[:-h]) / c[:-h] * 100
        atr = ((d["high"] - d["low"]) / d["close"]).rolling(100, min_periods=30).mean().values
        ok = ~np.isnan(fwd) & ~np.isnan(atr)
        if ok.sum() < 200:
            continue
        q = np.zeros(n, np.int8)
        q[ok] = np.digitize(atr[ok], np.nanpercentile(atr[ok], [20, 40, 60, 80]))
        pools = {b: np.where(ok & (q == b))[0] for b in range(5)}
        st = run_structure(d.reset_index(drop=True), swing_len=LEN, internal_len=3)
        ev = [(e.i, 1 if e.bull else -1) for e in st.events if not e.internal]
        for side in (1, -1):
            ii = np.array([i for i, s in ev if s == side and ok[i]], dtype=int)
            if len(ii) < 25:
                continue
            v = np.nanmean(fwd[ii]) * side
            cs = []
            for _ in range(3):
                pick = np.array([pools[q[i]][RNG.integers(len(pools[q[i]]))]
                                 if len(pools[q[i]]) else i for i in ii])
                cs.append(np.nanmean(fwd[pick]) * side)
            d_ = v - float(np.mean(cs))
            a = acc[tf][side]
            a[0] += len(ii); a[1] += v * len(ii); a[2] += float(np.mean(cs)) * len(ii)
            per_sym[tf][side].append(d_)
    if fi % 6 == 0:
        print(f"  [{fi}/{len(files)}]", flush=True)

print(f"\n{'окно':>7} {'ТФ':>5} {'n':>8} {'событие':>10} {'контроль':>10} "
      f"{'сила':>9} {'монет+':>8}")
pts = []
for tf in TFS:
    tot = sum(acc[tf][s][0] for s in (1, -1))
    if tot < 200:
        continue
    ev = sum(acc[tf][s][1] for s in (1, -1)) / tot
    ct = sum(acc[tf][s][2] for s in (1, -1)) / tot
    ps = per_sym[tf][1] + per_sym[tf][-1]
    good = sum(1 for x in ps if x > 0)
    print(f"{tf*LEN:>7} {tf:>4}m {tot:>8,} {ev:+9.4f}% {ct:+9.4f}% {ev-ct:+8.4f}% "
          f"{good:>4}/{len(ps)}")
    pts.append((tf * LEN, ev - ct, tot))

print("\n=== ПОКАЗАТЕЛЬ СТЕПЕНИ (по точкам с положительной силой) ===")
P = [(w, s) for w, s, n in pts if s > 0.02]
if len(P) >= 3:
    x = np.log([w for w, _ in P]); y = np.log([s for _, s in P])
    a, b = np.polyfit(x, y, 1)
    print(f"  сила ≈ {np.exp(b):.5f} × окно^{a:.3f}   (0.5 = случайное блуждание)")
    print(f"  R² = {np.corrcoef(x, y)[0,1]**2:.3f}")
    print(f"\n{'окно':>7} {'измерено':>10} {'формула':>10} {'вес (180=4)':>12}")
    k = 4.0 / (180 ** a)
    for w, s, n in pts:
        f_ = np.exp(b) * w ** a
        print(f"{w:>7} {s:+9.4f}% {f_:+9.4f}% {max(0, k * w**a):11.1f}")
neg = [(w, s) for w, s, n in pts if s <= 0.02]
if neg:
    print(f"\n  порог включения: между {max(w for w,_ in neg)} и "
          f"{min(w for w,_ in P) if P else '?'} мин")
