# -*- coding: utf-8 -*-
"""📐 ВНУТРИ HTF — ТОРГУЕМО ЛИ LTF? (Егор, 11.09.2026)

Уже измерено: внутри разрешения БЕЗ фильтра серия на 3m (каждый кросс вверх, выход по
встречному) = −5.6% за разрешение; 16.5 сделок платят 5.8% костов и берут грязными столько же,
сколько одна сделка. LTF-цикл несёт 0.3-0.6% хода при косте 0.35%.

НЕ проверено: внутри СИЛЬНОГО окна кандидата (кластер + BTC упал), где ход +4-5% на сделку.

Окно = от входа 15m-сделки кандидата до её выхода (wt1 15m ≥ +60). Внутри окна:
  A  одна сделка (база)
  B  серия LTF: вход по кроссу вверх, выход по встречному кроссу LTF
  C  серия LTF: вход по кроссу вверх, выход по wt1 LTF ≥ +60 (зона LTF)
  D  серия LTF: вход только по кроссу вверх из-под нуля (откат), выход по зоне LTF
LTF = 3m и 5m. Все серии принудительно закрываются по выходу HTF-окна.
Разрез: все окна · окна с фильтром «кластер k≥15 и BTC упал >10% за 30д».
Данные: 1m паркеты (50 монет, 2025-26); дни кластера и BTC — из eq_regime.pkl (291 монета).
"""
import os, sys, glob, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
IZ, EZ, LIFE, TIMEOUT, COST = 70.0, 60.0, 12, 400, 0.35
LTFS = [3, 5]

# ── дни кластера по всему рынку (291 монета) из уже посчитанного разреза
RG = pd.read_pickle(D + r"\eq_regime.pkl")
RG = RG[(RG["iz"] == IZ) & (RG["ez"] == EZ)].copy()
RG["day"] = RG["ts"].dt.normalize()
kday = RG.groupby("day").sym.nunique()
print(f"дней в разрезе {len(kday)} · дней с k≥15: {(kday >= 15).sum()}\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def wt_arrays(d):
    w = calculate_wt(d.reset_index(drop=True))
    w1, w2 = w["wt1"].values, w["wt2"].values
    n = len(w1)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    return w1, cu, cd


files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))
btc = pd.read_parquet(r"C:\oko_history\1m\BTCUSDT.parquet")
if btc.index.tz is not None:
    btc.index = btc.index.tz_localize(None)
bc = btc["close"].resample("15min", label="left", closed="left").last().dropna()
btc30 = (bc / bc.shift(30 * 96) - 1) * 100

rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if d1.index.tz is not None:
        d1.index = d1.index.tz_localize(None)
    if len(d1) < 200000:
        continue
    dc, di = resample(d1, 60), resample(d1, 15)
    c1, ccu, _ = wt_arrays(dc)
    w1, cu, _ = wt_arrays(di)
    n, nc = len(w1), len(c1)
    ct_c = (dc.index + pd.Timedelta(minutes=60)).values
    ct_i = (di.index + pd.Timedelta(minutes=15)).values
    op, cl = di.open.values, di.close.values
    b30 = btc30.reindex(di.index, method="ffill").to_numpy()
    L = {}
    for tf in LTFS:
        dl = resample(d1, tf)
        lw1, lcu, lcd = wt_arrays(dl)
        L[tf] = dict(w1=lw1, cu=lcu, cd=lcd, op=dl.open.values, cl=dl.close.values,
                     t_open=dl.index.values, t_close=(dl.index + pd.Timedelta(minutes=tf)).values)
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
        j = np.where(w1[ii + 1:lim + 1] >= EZ)[0]
        jx = ii + 1 + int(j[0]) if len(j) else lim
        busy = jx
        t_in = di.index.values[ii]                 # OPEN бара входа
        t_out = ct_i[jx]                           # закрытие бара выхода
        base = (cl[jx] - op[ii]) / op[ii] * 100 - COST
        day = pd.Timestamp(di.index[ii]).normalize()
        k_all = int(kday.get(day, 0))
        filt = int(k_all >= 15 and np.isfinite(b30[ii - 1]) and b30[ii - 1] < -10)
        rec = dict(sym=sym, base=base, filt=filt, k=k_all, dur_h=(jx - ii) / 4)
        for tf in LTFS:
            l = L[tf]
            a = int(np.searchsorted(l["t_open"], t_in, "left"))
            z = int(np.searchsorted(l["t_close"], t_out, "right")) - 1
            if z <= a + 2:
                for m in "BCD":
                    rec[f"{m}{tf}"] = np.nan; rec[f"{m}{tf}_n"] = 0
                continue
            for m in "BCD":
                tot, cnt, pos = 0.0, 0, None
                for x in range(a, z + 1):
                    if pos is None:
                        go = l["cu"][x] if m != "D" else (l["cu"][x] and l["w1"][x] < 0)
                        if go and x + 1 <= z:
                            pos = x + 1
                        continue
                    stop = l["cd"][x] if m == "B" else (l["w1"][x] >= EZ)
                    if stop or x == z:
                        e = l["op"][pos]
                        tot += (l["cl"][x] - e) / e * 100 - COST; cnt += 1; pos = None
                rec[f"{m}{tf}"] = tot; rec[f"{m}{tf}_n"] = cnt
        rows.append(rec)
    if fi % 10 == 0:
        print(f"  [{fi}/{len(files)}] окон {len(rows):,}", flush=True)

R = pd.DataFrame(rows)
R.to_pickle(D + r"\ltf_inside.pkl")
print(f"\nокон HTF {len(R):,} · монет {R.sym.nunique()} · с фильтром {R.filt.sum():,}\n")
NM = {"B": "серия, выход встречный кросс", "C": "серия, выход зона LTF",
      "D": "серия, только откаты, выход зона"}
for lbl, G in [("ВСЕ ОКНА КАНДИДАТА", R), ("ОКНА С ФИЛЬТРОМ (кластер + BTC упал)", R[R.filt == 1]),
               ("ОКНА БЕЗ ФИЛЬТРА", R[R.filt == 0])]:
    if len(G) < 20:
        print(f"=== {lbl}: мало окон ({len(G)}) ===\n"); continue
    print(f"=== {lbl} · окон {len(G):,} · медиана длины {G.dur_h.median():.1f} ч ===")
    print(f"{'способ':>38} {'на окно':>9} {'грязн':>8} {'сделок':>7} {'мед':>8} "
          f"{'WR окон':>8} {'лучше базы':>11}")
    print(f"{'A одна сделка 15m (база)':>38} {G.base.mean():+8.3f}% "
          f"{G.base.mean()+COST:+7.3f}% {1:>7.1f} {G.base.median():+7.3f}% "
          f"{(G.base>0).mean()*100:7.1f}% {'—':>11}")
    for tf in LTFS:
        for m in "BCD":
            v = G[f"{m}{tf}"].dropna()
            nn = G.loc[v.index, f"{m}{tf}_n"]
            if len(v) < 20:
                continue
            better = (v > G.loc[v.index, "base"]).mean() * 100
            print(f"{f'{m} {tf}m: ' + NM[m]:>38} {v.mean():+8.3f}% "
                  f"{v.mean()+COST*nn.mean():+7.3f}% {nn.mean():>7.1f} {v.median():+7.3f}% "
                  f"{(v>0).mean()*100:7.1f}% {better:10.1f}%")
    print()
