# -*- coding: utf-8 -*-
"""ГИБРИД-ВЫХОД на BIG-FLUSH — решающая проверка (07.08).
На 4h-ядре гибрид был АРТЕФАКТОМ 2024 (2025-26 хуже базы) — не внедрили.
На big-flush он дал медиану +2.634% против +1.187% у TP1R. Вопрос: это снова один год?
Разрез по годам + стресс костами + разные k трейла. 40 монет, ликвидная половина."""
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


def atr_s(df, n=14):
    h, l, c = df.high, df.low, df.close
    return pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1).rolling(n).mean().values


def raw_tp1r(i, H, L, C, sl, ttl=24):
    e = C[i]; tp = e + (e - sl); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl: return (sl - e) / e * 100
        if H[j] >= tp: return (tp - e) / e * 100
    return (C[end] - e) / e * 100


def raw_hybrid(i, H, L, C, A, sl, k, ttl=96):
    e = C[i]; R = e - sl; tp = e + R; end = min(i + ttl, len(C) - 1)
    half1 = None; peak = e; trail = sl
    for j in range(i + 1, end + 1):
        if half1 is None and L[j] <= sl:
            return (sl - e) / e * 100
        if half1 is None and H[j] >= tp:
            half1 = (tp - e) / e * 100; peak = max(peak, H[j]); trail = max(trail, e)
            continue
        if half1 is not None:
            peak = max(peak, H[j])
            a = A[j] if not np.isnan(A[j]) else R
            trail = max(trail, peak - k * a)
            if L[j] <= trail:
                return (half1 + (trail - e) / e * 100) / 2
    if half1 is None:
        return (C[end] - e) / e * 100
    return (half1 + (C[end] - e) / e * 100) / 2


def rep(name, rows, cost):
    if len(rows) < 25:
        print(f"    {name:26} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 15 else "  ?  "
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:26} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:2}/{len(coins):2} | "
          f"24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
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
print(f"монет {len(DATA)}, ликвидных {sum(1 for s in DATA if turn[s] >= mt)}\n")
R = defaultdict(list)
for s, d in DATA.items():
    if turn[s] < mt:
        continue
    w = wt(d); a = atrt(d); A = atr_s(d)
    H = d.high.values; L = d.low.values; C = d.close.values
    yr = pd.to_datetime(d.time, unit="ms").dt.year.values
    for i in range(120, len(d) - 1):
        if not (a[i] > 0 and w[i] < -60 and w[i] > w[i - 1]):
            continue
        e = C[i]; sl = L[max(0, i - 3):i + 1].min() * 0.997
        if not (sl < e and (e - sl) / e * 100 > 4.0):
            continue
        y = int(yr[i])
        R["TP1R"].append((y, raw_tp1r(i, H, L, C, sl), s))
        for k in (1.5, 2.0, 3.0):
            R[f"ГИБРИД k={k}"].append((y, raw_hybrid(i, H, L, C, A, sl, k), s))
for cost in (0.25, 0.35):
    print(f"═══ КОСТЫ {cost}% ═══")
    for k in ("TP1R", "ГИБРИД k=1.5", "ГИБРИД k=2.0", "ГИБРИД k=3.0"):
        rep(k, R.get(k, []), cost)
    print()
