# -*- coding: utf-8 -*-
"""📏 ПОРОГ ДАМПА ОТНОСИТЕЛЬНО САМОЙ МОНЕТЫ (Егор: «ниже −75 редко что спускается … типа BCH»).

Фиксированный −75 видит дамп только у волатильных монет; у спокойной (BCH) настоящий дамп
разворачивается около −57…−60 и не попадает в выборку. Идея: порог = нижний перцентиль
СОБСТВЕННЫХ значений wt1 монеты на ТФ контекста за последние 90 дней (каузально: только прошлое).

Схемы (одна позиция на монету, выход — wt1 ТФ входа ≥ +60, таймаут 400 баров):
  4h→1h   контекст 4h: кросс wt1×wt2 вверх при wt1 < порога → вход 1h, первый кросс вверх в 12 барах 4h
  1h→15m  контекст 1h → вход 15m
Пороги контекста:
  ФИКС   −60 · −70 · −75
  ОТН    wt1 < перцентиль q собственных wt1 за 90 дней: q = 3% · 5% · 10% · 15%
Контроль — случайный вход без перекрытия, та же политика выхода. 291 монета, 2022-2026.
"""
import sys, os, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = os.path.dirname(os.path.abspath(__file__))
LIFE, TIMEOUT, COST, EZ = 12, 400, 0.35, 60.0
SCHEMES = [(240, 60, "4h→1h"), (60, 15, "1h→15m")]
FIX = [60.0, 70.0, 75.0]
QS = [3, 5, 10, 15]
RNG = np.random.default_rng(575)
YR = {2022: "МЕДВ", 2023: "БЫК", 2024: "нейтр", 2025: "МЕДВ", 2026: "МЕДВ"}
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:300]


def rs(d, tf):
    if tf == 15:
        return d
    return d.resample(f"{tf}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def wt(d):
    w = calculate_wt(d.reset_index(drop=True))
    w1, w2 = w.wt1.values, w.wt2.values
    cu = np.concatenate(([False], (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])))
    return w1, cu


rows, thr_rows = [], []
for fi, sym in enumerate(syms, 1):
    d15 = pd.read_sql("select time,open,high,low,close from ohlcv_cache where symbol=? "
                      "and timeframe='15m' order by time", con, params=(sym,))
    d15["ts"] = pd.to_datetime(d15.time, unit="ms")
    d15 = d15.drop_duplicates("ts").set_index("ts")[["open", "high", "low", "close"]]
    if len(d15) < 50000:
        continue
    for ctx_tf, in_tf, nm in SCHEMES:
        dc, di = rs(d15, ctx_tf), rs(d15, in_tf)
        if len(dc) < 1000 or len(di) < 2000:
            continue
        c1, ccu = wt(dc)
        w1, cu = wt(di)
        nc, n = len(c1), len(w1)
        win = int(90 * 24 * 60 / ctx_tf)
        s1 = pd.Series(c1)
        rel = {q: s1.shift(1).rolling(win, min_periods=win // 2).quantile(q / 100).values
               for q in QS}
        ctc = (dc.index + pd.Timedelta(minutes=ctx_tf)).values
        cti = (di.index + pd.Timedelta(minutes=in_tf)).values
        op, cl = di.open.values, di.close.values
        yr = di.index.year.values
        zone = w1 >= EZ
        thr_rows.append((sym, nm, float(np.nanmedian(rel[5]))))

        def exit_at(ii):
            lim = min(ii + TIMEOUT, n - 1)
            j = np.where(zone[ii + 1:lim + 1])[0]
            return ii + 1 + int(j[0]) if len(j) else lim

        variants = [(f"фикс −{int(z)}", ccu & (c1 < -z)) for z in FIX] + \
                   [(f"отн {q}%", ccu & (c1 < rel[q])) for q in QS]
        for vname, mask in variants:
            ents = []
            for k in np.where(mask)[0]:
                if k < 300 or k + LIFE >= nc:
                    continue
                i0 = int(np.searchsorted(cti, ctc[k], "left"))
                i1 = int(np.searchsorted(cti, ctc[k + LIFE], "right")) - 1
                if i0 < 60 or i1 >= n - 3 or i1 <= i0:
                    continue
                ins = np.where(cu[i0:i1 + 1])[0]
                if len(ins):
                    ents.append((i0 + int(ins[0]) + 1, float(c1[k])))
            busy, taken = -1, 0
            for ii, cw in sorted(ents):
                if ii <= busy or ii >= n - 3:
                    continue
                jx = exit_at(ii); busy = jx; taken += 1
                rows.append((sym, nm, vname, "sig", (cl[jx] - op[ii]) / op[ii] * 100 - COST,
                             jx - ii, int(yr[ii]), cw, di.index[ii]))
            cb, cn = -1, 0
            for ii in np.sort(RNG.integers(300, max(301, n - TIMEOUT - 3), size=max(taken, 1) * 3)):
                if cn >= taken:
                    break
                if ii <= cb:
                    continue
                jx = exit_at(int(ii)); cb = jx; cn += 1
                rows.append((sym, nm, vname, "ctl", (cl[jx] - op[ii]) / op[ii] * 100 - COST,
                             jx - ii, int(yr[ii]), np.nan, di.index[int(ii)]))
    if fi % 50 == 0:
        print(f"  [{fi}/{len(syms)}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "scheme", "var", "k", "pnl", "bars", "year", "ctx_wt", "ts"])
TH = pd.DataFrame(thr_rows, columns=["sym", "scheme", "p5"])
R.to_pickle(os.path.join(D, "rel_threshold.pkl"))
span = (R.ts.max() - R.ts.min()).days / 365.25
print(f"\nзаписей {len(R):,} · монет {R.sym.nunique()} · лет {span:.1f}\n")

print("=== ГДЕ ЛЕЖИТ ОТНОСИТЕЛЬНЫЙ ПОРОГ 5% (медиана за 90 дней) ===")
for nm in TH.scheme.unique():
    t = TH[TH.scheme == nm].p5
    print(f"  {nm}: по монетам — 10% {t.quantile(.1):+.1f} · медиана {t.median():+.1f} · 90% {t.quantile(.9):+.1f}")
    for s in ["BCH/USDT", "BTC/USDT", "ETH/USDT", "ZEC/USDT", "HYPE/USDT"]:
        v = TH[(TH.scheme == nm) & (TH.sym == s)].p5
        if len(v):
            print(f"     {s:>10}: {v.iloc[0]:+.1f}")
print()
print(f"{'схема':>7} {'порог':>9} {'сделок/год':>11} {'на монету/год':>14} {'нетто':>9} {'контр':>8} {'НАД':>8} "
      f"{'мед':>8} {'WR':>6} {'безтоп10':>9} {'монет+':>9} {'лет+':>5}  ср. глубина входа")
for nm in [s[2] for s in SCHEMES]:
    for vname in [f"фикс −{int(z)}" for z in FIX] + [f"отн {q}%" for q in QS]:
        g = R[(R.scheme == nm) & (R["var"] == vname) & (R.k == "sig")]
        c = R[(R.scheme == nm) & (R["var"] == vname) & (R.k == "ctl")]
        if len(g) < 100:
            continue
        v = np.sort(g.pnl.values)[::-1]
        per = g.groupby("sym").pnl.mean(); yrs = g.groupby("year").pnl.mean()
        print(f"{nm:>7} {vname:>9} {len(g)/span:>11.0f} {g.groupby('sym').size().median()/span:>14.1f} "
              f"{g.pnl.mean():+8.3f}% {c.pnl.mean():+7.3f}% {g.pnl.mean()-c.pnl.mean():+7.3f}% "
              f"{g.pnl.median():+7.3f}% {(g.pnl>0).mean()*100:5.1f}% {v[int(len(v)*.1):].mean():+8.3f}% "
              f"{int((per>0).sum())}/{len(per)} {int((yrs>0).sum())}/{len(yrs)}  {g.ctx_wt.median():+.1f}")
    print()

print("=== ПО ГОДАМ ===")
for nm in [s[2] for s in SCHEMES]:
    for vname in ["фикс −75", "отн 5%", "отн 10%"]:
        g = R[(R.scheme == nm) & (R["var"] == vname) & (R.k == "sig")]
        if len(g) < 100:
            continue
        print(f"  {nm:>7} {vname:>9}: " + " · ".join(
            f"{y} {YR.get(y,'?')} {g[g.year==y].pnl.mean():+.2f}% (n={int((g.year==y).sum())})"
            for y in sorted(g.year.unique())))

print("\n=== BCH отдельно ===")
for nm in [s[2] for s in SCHEMES]:
    for vname in [f"фикс −{int(z)}" for z in FIX] + [f"отн {q}%" for q in QS]:
        g = R[(R.scheme == nm) & (R["var"] == vname) & (R.k == "sig") & (R.sym == "BCH/USDT")]
        if len(g):
            print(f"  {nm:>7} {vname:>9}: n={len(g):>3} · {g.pnl.mean():+.2f}%/сделка · сумма {g.pnl.sum():+.1f}%")
