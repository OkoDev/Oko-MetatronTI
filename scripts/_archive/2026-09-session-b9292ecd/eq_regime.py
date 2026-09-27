# -*- coding: utf-8 -*-
"""🧭 РЕЖИМ BTC · ЛИКВИДНОСТЬ · КЛАСТЕР для кандидата (11.09.2026).

Кандидат (без перекрытия): лонг от кросса WT вверх при wt1 < −IZ на 1h → первый кросс вверх
на 15m в окне 12 баров → выход wt1 ≥ +EZ на 15m.
Слабое место: 2022 МЕДВ −2.136% и 2023 БЫК −0.153% при +1.2…+2.3% в 2024-26.
Вопрос: это ГОД или РЕЖИМ? (закон проекта: «год или состав» — тест перед годовым сравнением)

Оси:
  РЕЖИМ BTC  — доходность BTC за 30 дней ДО входа (каузально): падение / флэт / рост
  ТРЕНД МОНЕТЫ — доходность самой монеты за 30 дней до входа
  ЛИКВИДНОСТЬ — медианный оборот монеты (close·volume за бар 15m), терцили
  КЛАСТЕР    — сколько монет дали вход в тот же день (массовая перепроданность против одиночной)
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
LOOK = 30 * 96          # 30 дней в барах 15m
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:300]
btc_sym = next((s for s in syms if s.upper().startswith("BTC")), None)
print(f"символов {len(syms)} · BTC = {btc_sym}\n", flush=True)
b = pd.read_sql("select time,close from ohlcv_cache where symbol=? and timeframe='15m' "
                "order by time", con, params=(btc_sym,))
b["ts"] = pd.to_datetime(b.time, unit="ms")
b = b.drop_duplicates("ts").set_index("ts").close
btc_ret = (b / b.shift(LOOK) - 1) * 100          # доходность BTC за 30 дней до бара

rows = []
for fi, sym in enumerate(syms, 1):
    d = pd.read_sql("select time,open,high,low,close,volume from ohlcv_cache "
                    "where symbol=? and timeframe='15m' order by time",
                    con, params=(sym,))
    if len(d) < 50000:
        continue
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    di = d.drop_duplicates("ts").set_index("ts")
    turn = float(np.nanmedian(di.close.values * di.volume.values))
    dc = di.resample("60min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(dc) < 500:
        continue
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    nc = len(c1)
    ccu = np.zeros(nc, bool); ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ct_c = (dc.index + pd.Timedelta(minutes=60)).values
    wi = calculate_wt(di.reset_index(drop=True))
    w1, w2 = wi["wt1"].values, wi["wt2"].values
    n = len(w1)
    cu = np.zeros(n, bool); cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cl, op = di.close.values, di.open.values
    ct_i = (di.index + pd.Timedelta(minutes=15)).values
    own_ret = (pd.Series(cl) / pd.Series(cl).shift(LOOK) - 1).to_numpy() * 100
    btc_at = btc_ret.reindex(di.index, method="ffill").to_numpy()
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
        busy = -1
        for ii in sorted(set(e for e in ents if e < n - 5)):
            if ii <= busy:
                continue
            lim = min(ii + TIMEOUT, n - 1)
            j = np.where(zone[ii + 1:lim + 1])[0]
            jx = ii + 1 + int(j[0]) if len(j) else lim
            busy = jx
            rows.append((sym, IZ, EZ, (cl[jx] - op[ii]) / op[ii] * 100 - COST,
                         di.index[ii], int(di.index[ii].year),
                         float(btc_at[ii - 1]), float(own_ret[ii - 1]), turn))
    if fi % 60 == 0:
        print(f"  [{fi}/{len(syms)}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "iz", "ez", "pnl", "ts", "year", "btc30", "own30",
                                "turn"])
R.to_pickle(D + r"\eq_regime.pkl")
R["day"] = R.ts.dt.normalize()
print(f"\nсделок {len(R):,} · монет {R.sym.nunique()}\n")


def line(g, lbl):
    if len(g) < 60:
        return
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    print(f"  {lbl:>28}: n={len(g):>6,} · {g.pnl.mean():+7.3f}% · мед {g.pnl.median():+7.3f}% "
          f"· WR {(g.pnl>0).mean()*100:5.1f}% · безтоп10 {v[int(len(v)*.1):].mean():+7.3f}% "
          f"· монет+ {int((per>0).sum())}/{len(per)}")


for IZ, EZ in CONFS:
    G = R[(R["iz"] == IZ) & (R["ez"] == EZ)].dropna(subset=["btc30"])
    print(f"=== вход ±{IZ:.0f} / выход +{EZ:.0f} ===")
    print(" РЕЖИМ BTC (доходность BTC за 30 дней до входа):")
    for lbl, cond in [("BTC упал > 10%", G.btc30 < -10), ("BTC −10…0%", G.btc30.between(-10, 0)),
                      ("BTC 0…+10%", G.btc30.between(0, 10)), ("BTC вырос > 10%", G.btc30 > 10)]:
        line(G[cond], lbl)
    print(" ТРЕНД САМОЙ МОНЕТЫ за 30 дней:")
    for lbl, cond in [("монета −30% и хуже", G.own30 < -30), ("монета −30…−10%", G.own30.between(-30, -10)),
                      ("монета −10…+10%", G.own30.between(-10, 10)), ("монета +10% и выше", G.own30 > 10)]:
        line(G[cond], lbl)
    print(" ЛИКВИДНОСТЬ (оборот за бар 15m, терцили):")
    q = G.turn.quantile([1 / 3, 2 / 3]).values
    for lbl, cond in [("низкая", G.turn <= q[0]), ("средняя", (G.turn > q[0]) & (G.turn <= q[1])),
                      ("высокая", G.turn > q[1])]:
        line(G[cond], lbl)
    cnt = G.groupby("day").sym.nunique().rename("k")
    G2 = G.join(cnt, on="day")
    print(" КЛАСТЕР (монет с входом в тот же день):")
    for lbl, cond in [("одиночка k=1", G2.k == 1), ("2-4", G2.k.between(2, 4)),
                      ("5-14", G2.k.between(5, 14)), ("15+", G2.k >= 15)]:
        line(G2[cond], lbl)
    print(" ГОД × РЕЖИМ BTC (главное: 2023 провален из-за года или из-за режима?):")
    for y in sorted(G.year.unique()):
        for lbl, cond in [("BTC падал", G.btc30 < 0), ("BTC рос", G.btc30 >= 0)]:
            line(G[(G.year == y) & cond], f"{y} {lbl}")
    print()
