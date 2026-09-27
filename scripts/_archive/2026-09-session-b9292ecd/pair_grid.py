# -*- coding: utf-8 -*-
"""🧩 СЕТКА ПАР «контекст → вход» × ПОРОГ ДАМПА (Егор: «−70 1h→15m, 15m→3m или другие комбинации»).

Правило одно для всех пар:
  КОНТЕКСТ  кросс wt1×wt2 вверх на ТФ контекста при wt1 < −Z (Z = 60 / 70 / 75), жив 12 баров контекста
  ВХОД      первый кросс вверх на ТФ входа в этом окне, по open следующего бара
  ВЫХОД     wt1 на ТФ входа ≥ +60, таймаут 400 баров ТФ входа
  одна позиция на монету · контроль — случайный вход без перекрытия с той же политикой выхода

Режим «cache» — 15m-кэш 2022-2026, 291 монета, пары со входом ≥ 15m.
Режим «1m»    — 1m-паркеты Binance 2025-2026, 50 монет, пары со входом 1m/3m/5m (+ 4h→1h и 1h→15m
                для сверки на той же выборке). Косты 0.35 / 0.15 / 0.08.
"""
import sys, os, sqlite3, glob, warnings
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

MODE = sys.argv[1] if len(sys.argv) > 1 else "cache"
D = os.path.dirname(os.path.abspath(__file__))
LIFE, TIMEOUT, EZ = 12, 400, 60.0
ZS = [60.0, 70.0, 75.0]
COSTS = [0.35, 0.15, 0.08]
RNG = np.random.default_rng(1970)
if MODE == "cache":
    PAIRS = [(240, 60), (120, 30), (60, 15), (240, 15), (120, 15)]
else:
    PAIRS = [(240, 60), (60, 15), (60, 5), (60, 3), (30, 5), (15, 5), (15, 3), (15, 1), (5, 1)]
TFS = sorted({t for p in PAIRS for t in p})


def rs(d, tf, base):
    if tf == base:
        return d
    return d.resample(f"{tf}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def wt(d):
    w = calculate_wt(d.reset_index(drop=True))
    w1, w2 = w.wt1.values, w.wt2.values
    cu = np.concatenate(([False], (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])))
    return w1, cu


def sources():
    if MODE == "cache":
        con = sqlite3.connect("ohlcv_cache.db")
        syms = [r[0] for r in con.execute(
            "select symbol from ohlcv_cache where timeframe='15m' "
            "group by symbol having count(*) > 50000 order by count(*) desc")][:300]
        for sym in syms:
            d = pd.read_sql("select time,open,high,low,close from ohlcv_cache where symbol=? "
                            "and timeframe='15m' order by time", con, params=(sym,))
            d["ts"] = pd.to_datetime(d.time, unit="ms")
            d = d.drop_duplicates("ts").set_index("ts")[["open", "high", "low", "close"]]
            if len(d) >= 50000:
                yield sym, d, 15
    else:
        for f in sorted(glob.glob(r"C:\oko_history\1m\*.parquet")):
            d = pd.read_parquet(f)
            if d.index.tz is not None:
                d.index = d.index.tz_localize(None)
            d = d[~d.index.duplicated()].sort_index()[["open", "high", "low", "close"]]
            if len(d) >= 200000:
                yield os.path.basename(f)[:-8], d, 1


rows = []
for fi, (sym, d0, base) in enumerate(sources(), 1):
    cache = {}
    for tf in TFS:
        dd = rs(d0, tf, base)
        if len(dd) < 800:
            continue
        w1, cu = wt(dd)
        cache[tf] = dict(w1=w1, cu=cu, op=dd.open.values, cl=dd.close.values,
                         ct=(dd.index + pd.Timedelta(minutes=tf)).values,
                         yr=dd.index.year.values)
    for ctx, ent in PAIRS:
        if ctx not in cache or ent not in cache:
            continue
        C_, I_ = cache[ctx], cache[ent]
        nc, n = len(C_["w1"]), len(I_["w1"])
        zone = I_["w1"] >= EZ

        def exit_at(ii):
            lim = min(ii + TIMEOUT, n - 1)
            j = np.where(zone[ii + 1:lim + 1])[0]
            return ii + 1 + int(j[0]) if len(j) else lim

        for Z in ZS:
            ents = []
            for k in np.where(C_["cu"] & (C_["w1"] < -Z))[0]:
                if k < 300 or k + LIFE >= nc:
                    continue
                i0 = int(np.searchsorted(I_["ct"], C_["ct"][k], "left"))
                i1 = int(np.searchsorted(I_["ct"], C_["ct"][k + LIFE], "right")) - 1
                if i0 < 300 or i1 >= n - 3 or i1 <= i0:
                    continue
                ins = np.where(I_["cu"][i0:i1 + 1])[0]
                if len(ins):
                    ents.append(i0 + int(ins[0]) + 1)
            busy, taken = -1, 0
            for ii in sorted(set(ents)):
                if ii <= busy or ii >= n - 3:
                    continue
                jx = exit_at(ii); busy = jx; taken += 1
                rows.append((sym, f"{ctx}→{ent}", Z, "sig",
                             (I_["cl"][jx] - I_["op"][ii]) / I_["op"][ii] * 100,
                             (jx - ii) * ent / 60, int(I_["yr"][ii])))
            cb, cn = -1, 0
            for ii in np.sort(RNG.integers(300, max(301, n - TIMEOUT - 3), size=max(taken, 1) * 3)):
                if cn >= taken:
                    break
                if ii <= cb:
                    continue
                jx = exit_at(int(ii)); cb = jx; cn += 1
                rows.append((sym, f"{ctx}→{ent}", Z, "ctl",
                             (I_["cl"][jx] - I_["op"][ii]) / I_["op"][ii] * 100,
                             (jx - ii) * ent / 60, int(I_["yr"][ii])))
    if fi % 25 == 0:
        print(f"  [{fi}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "pair", "z", "k", "gross", "hold_h", "year"])
R.to_pickle(os.path.join(D, f"pair_grid_{MODE}.pkl"))
years = R.year.nunique()
span = {"cache": 4.6, "1m": 1.6}[MODE]
nm = lambda t: f"{t // 60}h" if t >= 60 else f"{t}m"
print(f"\nрежим {MODE} · записей {len(R):,} · монет {R.sym.nunique()} · ~{span} лет\n")
print(f"{'пара':>10} {'порог':>6} {'сделок/год':>11} {'на мон/год':>11} {'грязн':>8} "
      + " ".join(f"{'нетто@'+format(c,'.2f'):>11}" for c in COSTS)
      + f" {'НАД@0.35':>9} {'безтоп10@0.35':>14} {'удерж ч':>8} {'монет+':>8} {'лет+':>5}")
for pair in [f"{c}→{e}" for c, e in PAIRS]:
    c_, e_ = map(int, pair.split("→"))
    for Z in ZS:
        g = R[(R.pair == pair) & (R.z == Z) & (R.k == "sig")]
        c = R[(R.pair == pair) & (R.z == Z) & (R.k == "ctl")]
        if len(g) < 60:
            continue
        net = g.gross - 0.35
        v = np.sort(net.values)[::-1]
        per = net.groupby(g.sym).mean(); yrs = net.groupby(g.year).mean()
        print(f"{nm(c_)+'→'+nm(e_):>10} {'−'+str(int(Z)):>6} {len(g)/span:>11.0f} "
              f"{g.groupby('sym').size().median()/span:>11.1f} {g.gross.mean():+7.3f}% "
              + " ".join(f"{g.gross.mean()-cc:+10.3f}%" for cc in COSTS)
              + f" {g.gross.mean()-c.gross.mean():+8.3f} {v[int(len(v)*.1):].mean():+13.3f}% "
              f"{g.hold_h.median():>8.1f} {int((per>0).sum())}/{len(per)} {int((yrs>0).sum())}/{len(yrs)}")
    print()
