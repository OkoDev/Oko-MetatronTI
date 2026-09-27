# -*- coding: utf-8 -*-
"""⬆️ ИЗ 15m В СТАРШИЕ (Егор, 11.09.2026).

Вниз уже измерено: внутри HTF-окна LTF-серии не лучше одной сделки (ход принадлежит окну).
Вверх — два прочтения, оба мерим:

  ЧАСТЬ 1. Вход тот же (1h контекст ±70 → первый кросс вверх на 15m), ВЫХОД по зоне
           СТАРШЕГО ТФ: wt1 ≥ +60 на 15m (база) · 1h · 2h · 4h. Длиннее ли ход, чем берёт 15m?
  ЧАСТЬ 2. Вся конструкция сдвинута вверх, отношение контекст/вход ×4 (закон вложенности):
           1h→15m (база) · 2h→30m · 4h→1h · 8h→2h · 1D→4h. Выход — зона ТФ входа.

Везде: только LONG · одна позиция на монету · косты 0.35% · контроль — случайный вход без
перекрытия с той же политикой выхода · фильтр «кластер k≥K и BTC упал >10% за 30д» отдельно.
Порог кластера масштабируется с частотой сигнала: K=15 для базы, для старших — по перцентилю.
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
IZ, EZ, LIFE, COST = 70.0, 60.0, 12, 0.35
EXIT_TFS = [15, 60, 120, 240]                           # часть 1
PAIRS = [(60, 15), (120, 30), (240, 60), (480, 120), (1440, 240)]   # часть 2
TIMEOUT_MIN = 400 * 15 * 4                               # предохранитель в минутах (~16.7 сут)
RNG = np.random.default_rng(15)
YR = {2022: "МЕДВ", 2023: "БЫК", 2024: "нейтр", 2025: "МЕДВ", 2026: "МЕДВ"}
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:300]
btc_sym = next(s for s in syms if s.upper().startswith("BTC"))


def rs(d, tf):
    if tf == 15:
        return d
    return d.resample(f"{tf}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def wt(d):
    w = calculate_wt(d.reset_index(drop=True))
    w1, w2 = w["wt1"].values, w["wt2"].values
    cu = np.zeros(len(w1), bool); cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    return w1, cu


def load(sym):
    d = pd.read_sql("select time,open,high,low,close from ohlcv_cache where symbol=? "
                    "and timeframe='15m' order by time", con, params=(sym,))
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    return d.drop_duplicates("ts").set_index("ts")[["open", "high", "low", "close"]]


bc = load(btc_sym).close
btc30 = (bc / bc.shift(30 * 96) - 1) * 100

rows = []    # (part, variant, sym, kind, pnl, t_entry, btc30, hold_h)
for fi, sym in enumerate(syms, 1):
    d15 = load(sym)
    if len(d15) < 50000:
        continue
    cache = {}
    for tf in sorted({15, 30, 60, 120, 240, 480, 1440} | set(EXIT_TFS)):
        dd = rs(d15, tf)
        if len(dd) < 300:
            continue
        w1, cu = wt(dd)
        cache[tf] = dict(w1=w1, cu=cu, op=dd.open.values, cl=dd.close.values,
                         t0=dd.index.values, tc=(dd.index + pd.Timedelta(minutes=tf)).values)
    b30 = btc30.reindex(d15.index, method="ffill")

    def entries(ctx_tf, in_tf):
        if ctx_tf not in cache or in_tf not in cache:
            return []
        C_, I_ = cache[ctx_tf], cache[in_tf]
        nc, n = len(C_["w1"]), len(I_["w1"])
        out = []
        for k in np.where(C_["cu"] & (C_["w1"] < -IZ))[0]:
            if k + LIFE >= nc:
                continue
            i0 = int(np.searchsorted(I_["tc"], C_["tc"][k], "left"))
            i1 = int(np.searchsorted(I_["tc"], C_["tc"][k + LIFE], "right")) - 1
            if i0 < 60 or i1 >= n - 3 or i1 <= i0:
                continue
            ins = np.where(I_["cu"][i0:i1 + 1])[0]
            if len(ins):
                out.append(i0 + int(ins[0]) + 1)
        return sorted(set(e for e in out if e < n - 3))

    def run(in_tf, ents, exit_tf, part, var):
        I_, X_ = cache[in_tf], cache.get(exit_tf)
        if X_ is None:
            return
        n = len(I_["w1"])

        def trade(ii):
            t_in = I_["t0"][ii]
            e = I_["op"][ii]
            a = int(np.searchsorted(X_["tc"], I_["tc"][ii], "left"))  # первый закрытый бар ≥ входа
            lim_t = t_in + np.timedelta64(TIMEOUT_MIN, "m")
            b = int(np.searchsorted(X_["tc"], lim_t, "right")) - 1
            b = min(b, len(X_["w1"]) - 1)
            if a >= b:
                return None
            j = np.where(X_["w1"][a:b + 1] >= EZ)[0]
            jx = a + int(j[0]) if len(j) else b
            return (X_["cl"][jx] - e) / e * 100 - COST, t_in, \
                (X_["tc"][jx] - t_in) / np.timedelta64(1, "h"), X_["tc"][jx]

        busy_t = np.datetime64("1970-01-01")
        taken = 0
        for ii in ents:
            if I_["t0"][ii] <= busy_t:
                continue
            r = trade(ii)
            if r is None:
                continue
            busy_t = r[3]; taken += 1
            bb = b30.asof(pd.Timestamp(r[1]))
            rows.append((part, var, sym, "sig", r[0], r[1], float(bb), r[2]))
        busy_t = np.datetime64("1970-01-01"); cn = 0
        for ii in np.sort(RNG.integers(60, max(61, n - 5), size=max(taken, 1) * 4)):
            if cn >= taken:
                break
            if I_["t0"][ii] <= busy_t:
                continue
            r = trade(int(ii))
            if r is None:
                continue
            busy_t = r[3]; cn += 1
            rows.append((part, var, sym, "ctl", r[0], r[1], np.nan, r[2]))

    base = entries(60, 15)
    for etf in EXIT_TFS:
        run(15, base, etf, 1, f"выход {etf}m")
    for ctx_tf, in_tf in PAIRS:
        run(in_tf, entries(ctx_tf, in_tf), in_tf, 2, f"{ctx_tf}m→{in_tf}m")
    if fi % 50 == 0:
        print(f"  [{fi}/{len(syms)}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["part", "var", "sym", "kind", "pnl", "ts", "btc30", "hold_h"])
R["ts"] = pd.to_datetime(R["ts"])
R.to_pickle(D + r"\up_ladder.pkl")
R["day"] = R.ts.dt.normalize(); R["year"] = R.ts.dt.year
print(f"\nзаписей {len(R):,} · монет {R.sym.nunique()}\n")


def st(g):
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.sum()
    return (len(g), g.pnl.mean(), g.pnl.median(), v[int(len(v) * .1):].mean(),
            int((per > 0).sum()), len(per), g.hold_h.median())


for part, title in [(1, "ЧАСТЬ 1: вход 15m, ВЫХОД ПО ЗОНЕ СТАРШЕГО ТФ"),
                    (2, "ЧАСТЬ 2: ВСЯ КОНСТРУКЦИЯ ВВЕРХ ПО ЛЕСТНИЦЕ (×4)")]:
    print(f"{'='*100}\n=== {title} ===\n{'='*100}")
    print(f"{'вариант':>14} {'срез':>16} {'n':>6} {'нетто':>9} {'контр':>8} {'НАД':>8} "
          f"{'мед':>8} {'безтоп10':>9} {'удерж ч':>8} {'монет+':>9} {'лет+':>5}")
    for var in R[R.part == part]["var"].unique():
        S = R[(R.part == part) & (R["var"] == var) & (R.kind == "sig")].copy()
        C = R[(R.part == part) & (R["var"] == var) & (R.kind == "ctl")]
        if len(S) < 50:
            continue
        S = S.join(S.groupby("day").sym.nunique().rename("k"), on="day")
        kq = max(3, int(np.percentile(S.k, 60)))          # кластер: верхние 40% дней
        for lbl, G in [("все", S), (f"кластер k≥{kq}+BTC↓", S[(S.k >= kq) & (S.btc30 < -10)])]:
            if len(G) < 30:
                continue
            s = st(G)
            yrs = G.groupby("year").pnl.mean()
            cm = C.pnl.mean() if lbl == "все" else np.nan
            print(f"{var:>14} {lbl:>16} {s[0]:>6,} {s[1]:+8.3f}% {cm:+7.3f}% "
                  f"{s[1]-cm:+7.3f}% {s[2]:+7.3f}% {s[3]:+8.3f}% {s[6]:>8.1f} "
                  f"{s[4]}/{s[5]} {int((yrs>0).sum())}/{len(yrs)}")
    print()

print("=== ПО ГОДАМ (все входы, без фильтра) ===")
for part in (1, 2):
    for var in R[R.part == part]["var"].unique():
        S = R[(R.part == part) & (R["var"] == var) & (R.kind == "sig")]
        if len(S) < 50:
            continue
        parts = [f"{y} {YR.get(y,'?')} {S[S.year==y].pnl.mean():+.2f}%"
                 for y in sorted(S.year.unique()) if (S.year == y).sum() >= 20]
        print(f"  {var:>14}: " + " · ".join(parts))
