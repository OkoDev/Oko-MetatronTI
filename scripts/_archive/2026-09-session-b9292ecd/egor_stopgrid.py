# -*- coding: utf-8 -*-
"""СЕТКА СТОПОВ: отрезать левый хвост, не выбиваясь на шуме (10.09.2026).

Полное окно 2022-2026 дало: превышение над случайным входом +2.5 п.п. во всех
10 клетках год×сторона, медиана +1.8/+3.2%, WR 58-65% — но безтоп10% в минусе.
Значит схема собирает умеренные плюсы и изредка ловит катастрофу: выход
«держать до разворота в зоне или 200 баров» сидит в падении все 200 баров.

Структурный стоп (0.5-1.5%) выбивался в 87% — слишком короткий.
Проверяется СЕТКА: стоп в ATR(14) от входа, от узкого до очень широкого,
плюс таймаут как отдельная ось (200 баров — не слишком ли долго).

🔴 По закону размера ожидание: оптимум в ШИРОКОЙ части. Если лучшая ячейка —
самый узкий стоп, это противоречит трём предыдущим подтверждениям закона,
и тогда подозревать надо тест.
"""
import os, sys, sqlite3, bisect, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
MED_LEN, OS, OB, LIFE, COST, CTX_MULT = 34, -60.0, 60.0, 12, 0.35, 4
STOPS = [None, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 9.0]     # в ATR(14) 1h
TOUTS = [48, 100, 200, 400]                            # таймаут в барах 1h
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='1h' "
    "group by symbol having count(*) > 12000 order by symbol")]
print(f"символов: {len(syms)} · стопы(ATR) {STOPS} · таймауты {TOUTS}\n", flush=True)


def atr_pct(h, l, c, period=14):
    prev = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    return pd.Series(np.where(c > 0, tr / c * 100, np.nan)).rolling(
        period, min_periods=5).mean().to_numpy(float)


rows = []
for fi, sym in enumerate(syms, 1):
    d = pd.read_sql("select time,open,high,low,close from ohlcv_cache "
                    "where symbol=? and timeframe='1h' order by time",
                    con, params=(sym,))
    if len(d) < 12000:
        continue
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    d = d.drop_duplicates("ts").set_index("ts")
    dc = d.resample(f"{CTX_MULT}h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(dc) < 300:
        continue
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    ccu = np.zeros(len(c1), bool); ccd = np.zeros(len(c1), bool)
    ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ccd[1:] = (c1[:-1] >= c2[:-1]) & (c1[1:] < c2[1:])
    ct_c = list(dc.index + pd.Timedelta(hours=CTX_MULT))
    wi = calculate_wt(d.reset_index(drop=True))
    w1, w2 = wi["wt1"].values, wi["wt2"].values
    med = pd.Series(w1).rolling(MED_LEN, min_periods=MED_LEN // 2).mean().values
    n = len(w1)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    zone_up, zone_dn = cd & (w1 > OB), cu & (w1 < OS)
    med_up = np.concatenate(([False], (w1[:-1] <= med[:-1]) & (w1[1:] > med[1:])))
    med_dn = np.concatenate(([False], (w1[:-1] >= med[:-1]) & (w1[1:] < med[1:])))
    hi, lo, cl, op = d.high.values, d.low.values, d.close.values, d.open.values
    A = atr_pct(hi, lo, cl)
    ts = d.index; yr = ts.year.values
    ctx = []
    for arr, sd in ((ccu & (c1 < OS), 1), (ccd & (c1 > OB), -1)):
        for k in np.where(arr)[0]:
            if k + LIFE < len(ct_c):
                ctx.append((ct_c[k], ct_c[k + LIFE], sd))
    if not ctx:
        continue
    ctx.sort(); starts = [x[0] for x in ctx]
    # busy отдельный на каждую комбинацию (стоп × таймаут) × сторона
    busy = {(si, to, sd): -1 for si in range(len(STOPS)) for to in TOUTS
            for sd in (1, -1)}
    for i in range(MED_LEN + 5, n - 5):
        for s_, side in ((med_up[i], 1), (med_dn[i], -1)):
            if not s_:
                continue
            t_now = ts[i] + pd.Timedelta(hours=1)
            p = bisect.bisect_right(starts, t_now) - 1
            if not any(ctx[q][2] == side and ctx[q][0] <= t_now <= ctx[q][1]
                       for q in range(max(0, p - 3), p + 1) if 0 <= q < len(ctx)):
                continue
            ii = i + 1
            if ii >= n - 3:
                continue
            a = A[i]
            if not np.isfinite(a) or a <= 0:
                continue
            e = op[ii]
            zone = zone_up if side == 1 else zone_dn
            for to in TOUTS:
                lim = min(ii + to, n - 1)
                jz = np.where(zone[ii + 1:lim + 1])[0]
                end = ii + 1 + int(jz[0]) if len(jz) else lim
                for si, sm in enumerate(STOPS):
                    if ii <= busy[(si, to, side)]:
                        continue
                    if sm is None:
                        pn = (cl[end] - e) / e * 100 * side - COST
                        hw, bb = ("zone" if len(jz) else "timeout"), end - ii
                    else:
                        sp_pct = sm * a
                        sp = e * (1 - sp_pct / 100) if side == 1 else \
                             e * (1 + sp_pct / 100)
                        kx = None
                        for k in range(ii, end + 1):
                            if (side == 1 and lo[k] <= sp) or \
                               (side == -1 and hi[k] >= sp):
                                kx = k; break
                        if kx is not None:
                            pn = (sp - e) / e * 100 * side - COST
                            hw, bb = "stop", kx - ii
                        else:
                            pn = (cl[end] - e) / e * 100 * side - COST
                            hw, bb = ("zone" if len(jz) else "timeout"), end - ii
                    busy[(si, to, side)] = ii + bb
                    rows.append((sym, side, si, to, pn, bb, hw, int(yr[i]),
                                 float(a)))
    if fi % 20 == 0:
        print(f"  [{fi}/{len(syms)}] записей {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "side", "si", "to", "pnl", "bars", "how",
                                "year", "atr"])
R.to_pickle(D + r"\egor_stopgrid.pkl")
print(f"\nзаписей {len(R):,} · монет {R.sym.nunique()}\n")
RG = {2022: "МЕДВЕДЬ", 2023: "БЫК", 2024: "нейтраль", 2025: "МЕДВЕДЬ",
      2026: "МЕДВЕДЬ"}
R["rg"] = R.year.map(RG)
SL = {i: ("без стопа" if s is None else f"{s:.1f}·ATR") for i, s in enumerate(STOPS)}

print("=== СЕТКА: СТОП × ТАЙМАУТ (нетто на сделку, обе стороны) ===")
hdr = "  " + "".join(f"{f'to={t}':>12}" for t in TOUTS)
for side, sn in [(1, "long"), (-1, "short")]:
    print(f"\n  ── {sn} ──\n{'стоп':>12}{hdr}")
    for si in range(len(STOPS)):
        line = f"{SL[si]:>12}  "
        for to in TOUTS:
            g = R[(R.side == side) & (R.si == si) & (R.to == to)]
            line += f"{g.pnl.mean():+11.3f}%" if len(g) > 200 else f"{'—':>12}"
        print(line)

print("\n=== ТО ЖЕ, БЕЗ ВЕРХНИХ 10% (главный тест на хвост) ===")
for side, sn in [(1, "long"), (-1, "short")]:
    print(f"\n  ── {sn} ──\n{'стоп':>12}{hdr}")
    for si in range(len(STOPS)):
        line = f"{SL[si]:>12}  "
        for to in TOUTS:
            g = R[(R.side == side) & (R.si == si) & (R.to == to)]
            if len(g) > 200:
                v = np.sort(g.pnl.values)[::-1]
                line += f"{v[int(len(v)*.1):].mean():+11.3f}%"
            else:
                line += f"{'—':>12}"
        print(line)

print("\n=== ЛУЧШИЕ ЯЧЕЙКИ ПО КРИТЕРИЮ «безтоп10% > 0» ===")
out = []
for side in (1, -1):
    for si in range(len(STOPS)):
        for to in TOUTS:
            g = R[(R.side == side) & (R.si == si) & (R.to == to)]
            if len(g) < 500:
                continue
            v = np.sort(g.pnl.values)[::-1]
            per = g.groupby("sym").pnl.mean()
            yrs = g.groupby("year").pnl.mean()
            out.append(dict(side=side, si=si, to=to, n=len(g), mean=g.pnl.mean(),
                            med=g.pnl.median(), wr=(g.pnl > 0).mean(),
                            top10=v[int(len(v)*.1):].mean(),
                            top25=v[int(len(v)*.25):].mean(),
                            sym_pos=int((per > 0).sum()), sym_n=len(per),
                            yr_pos=int((yrs > 0).sum()), yr_n=len(yrs),
                            stops=(g.how == "stop").mean()))
O = pd.DataFrame(out).sort_values("top10", ascending=False)
print(f"{'стор':>6} {'стоп':>10} {'to':>5} {'n':>7} {'нетто':>9} {'мед':>9} {'WR':>6} "
      f"{'безтоп10':>9} {'безтоп25':>9} {'стопов':>7} {'монет+':>9} {'лет+':>5}")
for _, r in O.head(12).iterrows():
    print(f"{'long' if r.side==1 else 'short':>6} {SL[int(r.si)]:>10} {int(r.to):>5} "
          f"{int(r.n):>7,} {r['mean']:+8.3f}% {r.med:+8.3f}% {r.wr*100:5.1f}% "
          f"{r.top10:+8.3f}% {r.top25:+8.3f}% {r.stops*100:6.1f}% "
          f"{int(r.sym_pos)}/{int(r.sym_n)} {int(r.yr_pos)}/{int(r.yr_n)}")

print("\n=== ЛУЧШАЯ ЯЧЕЙКА КАЖДОЙ СТОРОНЫ: РАЗРЕЗ ПО ГОДУ И РЕЖИМУ ===")
for side, sn in [(1, "long"), (-1, "short")]:
    sub = O[O.side == side]
    if not len(sub):
        continue
    b = sub.iloc[0]
    g = R[(R.side == side) & (R.si == int(b.si)) & (R.to == int(b.to))]
    print(f"\n  {sn}: стоп {SL[int(b.si)]} · таймаут {int(b.to)} · n={len(g):,}")
    print(f"{'год':>8} {'режим':>10} {'n':>7} {'нетто':>9} {'мед':>9} {'безтоп10':>9} "
          f"{'монет+':>9}")
    for y in sorted(g.year.unique()):
        s = g[g.year == y]
        if len(s) < 50:
            continue
        v = np.sort(s.pnl.values)[::-1]
        per = s.groupby("sym").pnl.mean()
        print(f"{y:>8} {RG.get(y,'?'):>10} {len(s):>7,} {s.pnl.mean():+8.3f}% "
              f"{s.pnl.median():+8.3f}% {v[int(len(v)*.1):].mean():+8.3f}% "
              f"{int((per>0).sum())}/{len(per)}")
