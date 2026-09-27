# -*- coding: utf-8 -*-
"""🔴 СУРРОГАТ НА ВЕРСИИ БЕЗ ПЕРЕКРЫТИЯ (11.09.2026).

Прошлый суррогат (перцентиль 100%) считался на сделках С ПОВТОРАМИ, а повторы дают
в 3-4 раза больше первых. Здесь метрика — только первые сделки (одна позиция на монету),
на реальных и фазово-рандомизированных рядах, одинаковая конструкция OHLC из 15m close.

Конфигурации: вход ±70 / выход +60 и вход ±75 / выход +70.
Метрики: доход на сделку · превышение над случайным входом без перекрытия.
"""
import os, sys, sqlite3, warnings, time
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TIMEOUT, COST, LIFE = 400, 0.35, 12
CONFS = [(70.0, 60.0), (75.0, 70.0)]
NSYM, NSUR = 80, 20
RNG = np.random.default_rng(31337)
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:NSYM]


def iaaft(x, iters=10):
    n = len(x); xs = np.sort(x); amp = np.abs(np.fft.rfft(x))
    y = RNG.permutation(x)
    for _ in range(iters):
        Y = np.fft.rfft(y)
        y = np.fft.irfft(amp * np.exp(1j * np.angle(Y)), n)
        y = xs[np.argsort(np.argsort(y))]
    return y


def run(close, index):
    """одна позиция на монету; вернуть {conf: (sum_sig, n_sig, sum_ctl, n_ctl)}."""
    s = pd.Series(close, index=index)
    di = pd.DataFrame({"open": s, "high": s, "low": s, "close": s})
    r = s.resample("60min", label="left", closed="left")
    dc = pd.DataFrame({"open": r.first(), "high": r.max(), "low": r.min(),
                       "close": r.last()}).dropna()
    if len(dc) < 500:
        return {}
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    nc = len(c1)
    ccu = np.zeros(nc, bool); ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ct_c = (dc.index + pd.Timedelta(minutes=60)).values
    wi = calculate_wt(di.reset_index(drop=True))
    w1, w2 = wi["wt1"].values, wi["wt2"].values
    n = len(w1)
    cu = np.zeros(n, bool); cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cl = close
    ct_i = (index + pd.Timedelta(minutes=15)).values
    out = {}
    for IZ, EZ in CONFS:
        zone = w1 >= EZ
        ents = []
        for k in np.where(ccu & (c1 < -IZ))[0]:
            if k + LIFE >= nc:
                continue
            i0 = int(np.searchsorted(ct_i, ct_c[k], "left"))
            i1 = int(np.searchsorted(ct_i, ct_c[k + LIFE], "right")) - 1
            if i0 < 60 or i1 >= n - 5 or i1 <= i0:
                continue
            ins = np.where(cu[i0:i1 + 1])[0]
            if len(ins):
                ents.append(i0 + int(ins[0]) + 1)
        ents = sorted(set(e for e in ents if e < n - 5))

        def ex(ii):
            lim = min(ii + TIMEOUT, n - 1)
            j = np.where(zone[ii + 1:lim + 1])[0]
            return (ii + 1 + int(j[0])) if len(j) else lim

        busy, ss, ns = -1, 0.0, 0
        for ii in ents:
            if ii <= busy:
                continue
            jx = ex(ii); ss += (cl[jx] - cl[ii - 1]) / cl[ii - 1] * 100 - COST
            ns += 1; busy = jx
        cb, sc, nct = -1, 0.0, 0
        for ii in np.sort(RNG.integers(60, max(61, n - TIMEOUT - 5), size=max(ns, 1) * 4)):
            if nct >= ns:
                break
            if ii <= cb:
                continue
            jx = ex(int(ii)); sc += (cl[jx] - cl[ii - 1]) / cl[ii - 1] * 100 - COST
            nct += 1; cb = jx
        out[(IZ, EZ)] = (ss, ns, sc, nct)
    return out


data = []
for sym in syms:
    d = pd.read_sql("select time,close from ohlcv_cache where symbol=? and "
                    "timeframe='15m' order by time", con, params=(sym,))
    if len(d) < 50000:
        continue
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    d = d.drop_duplicates("ts").set_index("ts")
    data.append((sym, d.close.to_numpy(float), d.index))
print(f"монет {len(data)} · суррогатов {NSUR} · конфигурации {CONFS}\n", flush=True)


def agg(results):
    tot = {c: [0.0, 0, 0.0, 0] for c in CONFS}
    for r in results:
        for c, v in r.items():
            for k in range(4):
                tot[c][k] += v[k]
    return {c: (v[0] / max(v[1], 1), v[0] / max(v[1], 1) - v[2] / max(v[3], 1), v[1])
            for c, v in tot.items()}


t0 = time.time()
real = agg([run(c, i) for _, c, i in data])
print(f"РЕАЛЬНЫЕ ({time.time()-t0:.0f}с):")
for c, (pt, ov, nn) in real.items():
    print(f"  вход ±{c[0]:.0f}/выход +{c[1]:.0f}: на сделку {pt:+.3f}% · над контролем "
          f"{ov:+.3f} · сделок {nn:,}")
print(flush=True)
sur = {c: ([], []) for c in CONFS}
for s in range(NSUR):
    ts = time.time()
    res = []
    for _, c, i in data:
        lr = np.diff(np.log(c)); y = iaaft(lr)
        cs = np.empty(len(c)); cs[0] = c[0]; cs[1:] = c[0] * np.exp(np.cumsum(y))
        res.append(run(cs, i))
    a = agg(res)
    for c, (pt, ov, nn) in a.items():
        sur[c][0].append(pt); sur[c][1].append(ov)
    print(f"  суррогат {s+1:>2}/{NSUR} ({time.time()-ts:.0f}с): " +
          " · ".join(f"±{c[0]:.0f}: {a[c][0]:+.3f}/{a[c][1]:+.3f} (n={a[c][2]})"
                     for c in CONFS), flush=True)

print("\n=== ВЕРДИКТ СУРРОГАТА БЕЗ ПЕРЕКРЫТИЯ ===")
for c in CONFS:
    for nm, idx in (("на сделку", 0), ("над контролем", 1)):
        a = np.array(sur[c][idx]); rv = real[c][idx]
        p95 = np.percentile(a, 95)
        print(f"  вход ±{c[0]:.0f}/выход +{c[1]:.0f} · {nm}: реальное {rv:+.3f} · суррогаты "
              f"мед {np.median(a):+.3f} [{a.min():+.3f} … {a.max():+.3f}] · 95й {p95:+.3f} · "
              f"перцентиль {(a < rv).mean()*100:.0f}% → "
              f"{'✅ БЬЁТ' if rv > p95 else '🔴 НЕ БЬЁТ'}")
