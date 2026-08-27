# -*- coding: utf-8 -*-
"""КАРТА, БЛОК 5 (07.08) — добиваем остаток:
  #FIR  Кросс-секционный РАЗБРОС funding как режим (единственная живая идея роя, не проверена).
        FIR = средний funding верхнего дециля / нижнего. Высокий разброс = поляризация толпы.
  #3m   BIG-FLUSH на 3m (42 символа 2022-2026) — держится ли закон размера ещё на ТФ ниже.
Причинно, ликвидная половина, косты 0.25 и 0.35."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")
DB = "ohlcv_cache.db"


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def wt(df, n1=10, n2=21):
    hlc = (df.high + df.low + df.close) / 3
    esa = hlc.ewm(span=n1).mean(); d = (hlc - esa).abs().ewm(span=n1).mean()
    return ((hlc - esa) / (0.015 * d.replace(0, np.nan))).ewm(span=n2).mean().fillna(0).values


def atrt(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().values
    up = hl2 - factor * atr; dn = hl2 + factor * atr
    tu = up.copy(); td = dn.copy(); tr_ = np.ones(len(hl2))
    for i in range(1, len(hl2)):
        tu[i] = max(up[i], tu[i - 1]) if hl2[i - 1] > tu[i - 1] else up[i]
        td[i] = min(dn[i], td[i - 1]) if hl2[i - 1] < td[i - 1] else dn[i]
        tr_[i] = 1 if hl2[i] > td[i - 1] else (-1 if hl2[i] < tu[i - 1] else tr_[i - 1])
    return tr_


def raw(i, H, L, C, sl, ttl):
    e = C[i]; tp = e + (e - sl); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl: return (sl - e) / e * 100
        if H[j] >= tp: return (tp - e) / e * 100
    return (C[end] - e) / e * 100


def rep(name, rows, cost, months=29.0):
    if len(rows) < 25:
        print(f"    {name:30} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 15 else "  ?  "
    fr = len(r) / len(coins) / months
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:30} n={len(r):5} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:2}/{len(coins):2} {fr:5.2f}сд/мес "
          f"24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)

# ══════════ FIR: кросс-секционный разброс funding ══════════
print("═══ FIR: кросс-секционный разброс funding как режим ═══")
c = sqlite3.connect(DB)
fsyms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM funding_rates WHERE time>=? "
                                 "GROUP BY symbol HAVING n>2000 ORDER BY n DESC LIMIT 120", (t0,)).fetchall()]
fp = {}
for s in fsyms:
    f = pd.read_sql("SELECT time,rate FROM funding_rates WHERE symbol=? AND time>=? ORDER BY time",
                    c, params=(s, t0))
    if len(f) > 500:
        fp[s] = pd.Series(f.rate.values, index=f.time.values)
c.close()
fpan = pd.DataFrame(fp).sort_index().ffill(limit=3)
print(f"  панель funding: {fpan.shape[1]} монет × {fpan.shape[0]} точек")
q_hi = fpan.quantile(0.9, axis=1); q_lo = fpan.quantile(0.1, axis=1)
fir = (q_hi - q_lo).shift(1)          # ПРИЧИННО: разброс по прошлой точке
fir = fir.dropna()
print(f"  FIR (дециль90 − дециль10): медиана {fir.median():.5f}, "
      f"терцили {fir.quantile(0.33):.5f} / {fir.quantile(0.67):.5f}")
FIR_LO, FIR_HI = fir.quantile(0.33), fir.quantile(0.67)
firdf = pd.DataFrame({"time": fir.index.values, "v": fir.values})

c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' "
                                "AND time>=? GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT 40",
                                (t0,)).fetchall()]
c.close()
turn = {}; DATA = {}
for s in syms:
    d = load(s, "15m", t0)
    if len(d) >= 5000:
        DATA[s] = d; turn[s] = float(np.nanmedian((d.close * d.volume).values))
mt = np.nanmedian(list(turn.values()))
FB = defaultdict(list)
for s, d in DATA.items():
    if turn[s] < mt:
        continue
    w = wt(d); a = atrt(d)
    H = d.high.values; L = d.low.values; C = d.close.values; T = d.time.values
    yr = pd.to_datetime(d.time, unit="ms").dt.year.values
    fv = pd.merge_asof(pd.DataFrame({"time": T}), firdf, on="time", direction="backward")["v"].values
    for i in range(120, len(d) - 1):
        if not (a[i] > 0 and w[i] < -60 and w[i] > w[i - 1]):
            continue
        e = C[i]; sl = L[max(0, i - 3):i + 1].min() * 0.997
        if not (sl < e and (e - sl) / e * 100 > 4.0):
            continue
        p = raw(i, H, L, C, sl, 24); y = int(yr[i]); rec = (y, p, s)
        FB["ВСЕ"].append(rec)
        if np.isnan(fv[i]):
            continue
        k = ("FIR низкий (толпа едина)" if fv[i] <= FIR_LO else
             ("FIR высокий (поляризация)" if fv[i] >= FIR_HI else "FIR середина"))
        FB[k].append(rec)
for cost in (0.25, 0.35):
    print(f"\n  ── косты {cost}% ──")
    for k in ("ВСЕ", "FIR низкий (толпа едина)", "FIR середина", "FIR высокий (поляризация)"):
        rep(k, FB.get(k, []), cost)

# ══════════ 3m: держится ли закон размера ещё ниже ══════════
print("\n\n═══ 3m BIG-FLUSH — держится ли закон размера на ТФ ниже 5m ═══")
c = sqlite3.connect(DB)
s3 = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='3m' "
                              "AND time>=? GROUP BY symbol HAVING n>100000 ORDER BY n DESC LIMIT 25",
                              (t0,)).fetchall()]
c.close()
turn3 = {}; D3 = {}
for s in s3:
    d = load(s, "3m", t0)
    if len(d) >= 20000:
        D3[s] = d; turn3[s] = float(np.nanmedian((d.close * d.volume).values))
if D3:
    mt3 = np.nanmedian(list(turn3.values()))
    print(f"  монет 3m: {len(D3)}, ликвидных {sum(1 for s in D3 if turn3[s] >= mt3)}")
    B3 = defaultdict(list)
    for s, d in D3.items():
        if turn3[s] < mt3:
            continue
        w = wt(d); a = atrt(d)
        H = d.high.values; L = d.low.values; C = d.close.values
        yr = pd.to_datetime(d.time, unit="ms").dt.year.values
        for i in range(120, len(d) - 1):
            if not (a[i] > 0 and w[i] < -60 and w[i] > w[i - 1]):
                continue
            e = C[i]; sl = L[max(0, i - 3):i + 1].min() * 0.997
            if sl >= e:
                continue
            dist = (e - sl) / e * 100
            p = raw(i, H, L, C, sl, 40); y = int(yr[i]); rec = (y, p, s)
            k = ("стоп<1%" if dist < 1 else ("1-2%" if dist < 2 else
                 ("2-4%" if dist < 4 else ("4-6%" if dist < 6 else ">6%"))))
            B3[k].append(rec); B3["ВСЕ"].append(rec)
    for cost in (0.25, 0.35):
        print(f"\n  ── косты {cost}% ──")
        for k in ("ВСЕ", "стоп<1%", "1-2%", "2-4%", "4-6%", ">6%"):
            rep(k, B3.get(k, []), cost)
else:
    print("  3m данных не хватило")
