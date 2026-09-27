# -*- coding: utf-8 -*-
"""🛡️ СТОП ПОД ПРОСАДКУ ВНУТРИ СДЕЛКИ (11.09.2026).

Кандидат без стопа: медиана MAE −5.42%, худшие 5% — до −24.63%. Для боя так нельзя.
По закону размера стопа ожидание: узкий стоп убьёт схему (он выбивает раньше хода),
широкий отрежет только катастрофы. Проверяем сетку на версии БЕЗ перекрытия.

Стопы: нет · ATR(15m) 3/5/8/12/16 · фиксированный % 5/8/12/16/20 ·
       структурный — под минимумом разрешения на часовике минус 0.5·ATR(1h).
Метрика: доход на сделку · эквити на монету · безтоп10% · просадка · монет+ · годы.
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
TIMEOUT, COST, LIFE = 400, 0.35, 12
CONFS = [(70.0, 60.0), (75.0, 70.0)]
STOPS = [("нет", None), ("ATR×3", ("a", 3)), ("ATR×5", ("a", 5)), ("ATR×8", ("a", 8)),
         ("ATR×12", ("a", 12)), ("ATR×16", ("a", 16)), ("5%", ("p", 5)), ("8%", ("p", 8)),
         ("12%", ("p", 12)), ("16%", ("p", 16)), ("20%", ("p", 20)), ("структ 1h", ("s", 0))]
RG = {2022: "МЕДВ", 2023: "БЫК", 2024: "нейтр", 2025: "МЕДВ", 2026: "МЕДВ"}
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:300]


def atr_pct(h, l, c, p=14):
    prev = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    return pd.Series(np.where(c > 0, tr / c * 100, np.nan)).rolling(
        p, min_periods=5).mean().to_numpy(float)


rows = []
for fi, sym in enumerate(syms, 1):
    d = pd.read_sql("select time,open,high,low,close from ohlcv_cache "
                    "where symbol=? and timeframe='15m' order by time",
                    con, params=(sym,))
    if len(d) < 50000:
        continue
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    di = d.drop_duplicates("ts").set_index("ts")
    dc = di.resample("60min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(dc) < 500:
        continue
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    nc = len(c1)
    ccu = np.zeros(nc, bool); ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ct_c = (dc.index + pd.Timedelta(minutes=60)).values
    A1 = atr_pct(dc.high.values, dc.low.values, dc.close.values)
    wi = calculate_wt(di.reset_index(drop=True))
    w1, w2 = wi["wt1"].values, wi["wt2"].values
    n = len(w1)
    cu = np.zeros(n, bool); cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    hi, lo, cl, op = di.high.values, di.low.values, di.close.values, di.open.values
    A = atr_pct(hi, lo, cl)
    ct_i = (di.index + pd.Timedelta(minutes=15)).values
    yr = di.index.year.values
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
                # структурный уровень: минимум часовика от кросса назад на 12 баров
                slo = float(dc.low.values[max(0, k - LIFE):k + 1].min())
                ents.append((i0 + int(ins[0]) + 1, slo, float(A1[k])))
        ents = sorted({e[0]: e for e in ents if e[0] < n - 5}.values())
        for sname, spec in STOPS:
            busy = -1
            for ii, slo, a1 in ents:
                if ii <= busy:
                    continue
                e = op[ii]
                lim = min(ii + TIMEOUT, n - 1)
                j = np.where(zone[ii + 1:lim + 1])[0]
                jx = ii + 1 + int(j[0]) if len(j) else lim
                sp = None
                if spec is not None:
                    kind, m = spec
                    if kind == "a" and np.isfinite(A[ii - 1]):
                        sp = e * (1 - m * A[ii - 1] / 100)
                    elif kind == "p":
                        sp = e * (1 - m / 100)
                    elif kind == "s" and np.isfinite(a1):
                        sp = slo * (1 - 0.5 * a1 / 100)
                        if sp >= e:
                            sp = None
                how = "zone" if len(j) else "timeout"
                pnl = (cl[jx] - e) / e * 100 - COST
                if sp is not None:
                    hit = np.where(lo[ii:jx + 1] <= sp)[0]
                    if len(hit):
                        jx = ii + int(hit[0]); how = "stop"
                        pnl = (sp - e) / e * 100 - COST
                busy = jx
                rows.append((sym, IZ, EZ, sname, pnl, jx - ii, how, int(yr[ii]),
                             (e - sp) / e * 100 if sp is not None else np.nan))
    if fi % 60 == 0:
        print(f"  [{fi}/{len(syms)}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "iz", "ez", "stop", "pnl", "bars", "how", "year",
                                "stop_pct"])
R.to_pickle(D + r"\eq_stops.pkl")
print(f"\nзаписей {len(R):,} · монет {R.sym.nunique()}\n")

for IZ, EZ in CONFS:
    print(f"=== вход ±{IZ:.0f} / выход +{EZ:.0f} — СЕТКА СТОПОВ (без перекрытия) ===")
    print(f"{'стоп':>10} {'n':>6} {'стоп%мед':>9} {'на сделку':>10} {'мед':>8} {'WR':>6} "
          f"{'выбито':>7} {'безтоп10':>9} {'эквити/мон':>11} {'мед DD':>8} {'монет+':>8} "
          f"{'лет+':>5}")
    for sname, _ in STOPS:
        g = R[(R["iz"] == IZ) & (R["ez"] == EZ) & (R["stop"] == sname)]
        if len(g) < 100:
            continue
        v = np.sort(g.pnl.values)[::-1]
        per = g.groupby("sym").pnl.sum()
        yrs = g.groupby("year").pnl.mean()
        dds = []
        for s_, gs in g.groupby("sym"):
            cv = np.cumsum(gs.pnl.values)
            dds.append((cv - np.maximum.accumulate(cv)).min())
        print(f"{sname:>10} {len(g):>6,} {g.stop_pct.median():>8.2f}% {g.pnl.mean():+9.3f}% "
              f"{g.pnl.median():+7.3f}% {(g.pnl>0).mean()*100:5.1f}% "
              f"{(g.how=='stop').mean()*100:6.1f}% {v[int(len(v)*.1):].mean():+8.3f}% "
              f"{per.mean():+10.1f}% {np.median(dds):+7.1f}% "
              f"{int((per>0).sum())}/{len(per)} {int((yrs>0).sum())}/{len(yrs)}")
    print()

print("=== ЛУЧШИЙ СТОП ПО ГОДАМ (каждая конфигурация) ===")
for IZ, EZ in CONFS:
    sub = R[(R["iz"] == IZ) & (R["ez"] == EZ)]
    best = sub.groupby("stop").pnl.apply(
        lambda s: np.sort(s.values)[::-1][int(len(s)*.1):].mean()).idxmax()
    g0 = sub[sub["stop"] == best]
    parts = []
    for y in sorted(g0.year.unique()):
        g = g0[g0.year == y]
        if len(g) >= 30:
            parts.append(f"{y} {RG.get(y,'?')} {g.pnl.mean():+.3f}% (n={len(g)})")
    print(f"  ±{IZ:.0f}/+{EZ:.0f}, стоп «{best}» (лучший по безтоп10%): " + " · ".join(parts))
