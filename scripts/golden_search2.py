# -*- coding: utf-8 -*-
"""GOLDEN SEARCH v2 (Егор 30.07, полная автономия) — неарбитражированные семейства, ПРИЧИННО.
Прокурор: % net с костами · МЕДИАНА не среднее · хрупкость (топ-3) · OOS-сплит. Выход по касанию.
Семейства: breakout, pivot-bounce, vol-spike, range-fade, mean-rev-quickTP. Все HTF-фильтры causal."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0, "."); sys.stdout.reconfigure(encoding="utf-8")
DB = "ohlcv_cache.db"; COST = 0.10

def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",
                     c, params=(sym, tf, t0)); c.close(); return df

def wt(df, n1=10, n2=21):
    hlc = (df.high + df.low + df.close) / 3
    esa = hlc.ewm(span=n1).mean(); d = (hlc - esa).abs().ewm(span=n1).mean()
    ci = (hlc - esa) / (0.015 * d.replace(0, np.nan)); return ci.ewm(span=n2).mean().fillna(0)

def atrtrend(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close; hl2 = (h + l) / 2
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean(); up = (hl2 - factor * atr).values; dn = (hl2 + factor * atr).values
    hv = hl2.values; tuv = up.copy(); tdv = dn.copy(); tr_ = np.ones(len(df))
    for i in range(1, len(df)):
        tuv[i] = max(up[i], tuv[i - 1]) if hv[i - 1] > tuv[i - 1] else up[i]
        tdv[i] = min(dn[i], tdv[i - 1]) if hv[i - 1] < tdv[i - 1] else dn[i]
        tr_[i] = 1 if hv[i] > tdv[i - 1] else (-1 if hv[i] < tuv[i - 1] else tr_[i - 1])
    return tr_

def sim(idx, df, side, sls, tps, ttl):
    H = df.high.values; L = df.low.values; C = df.close.values; n = len(df); out = []
    for i, sl, tp in zip(idx, sls, tps):
        e = C[i]; end = min(i + ttl, n - 1); r = None
        for j in range(i + 1, end + 1):
            if side > 0:
                if L[j] <= sl: r = (sl - e) / e; break
                if H[j] >= tp: r = (tp - e) / e; break
            else:
                if H[j] >= sl: r = (e - sl) / e; break
                if L[j] <= tp: r = (e - tp) / e; break
        if r is None: r = side * (C[end] - e) / e
        out.append(r * 100 - COST)
    return out

def rep(name, r):
    if len(r) < 30: return
    r = np.array(r); srt = np.sort(r); frag = srt[:-3].sum()
    med = np.median(r); avg = r.mean(); wr = 100 * (r > 0).mean()
    flag = "🟢🟢" if (med > 0.05 and frag > 0 and avg > 0) else ("🟡" if avg > 0 else "🔴")
    print(f"  {name:30} n={len(r):4} WR{wr:2.0f}% avg{avg:+.3f}% МЕД{med:+.3f}% сум{r.sum():+.0f}% безтоп3{frag:+.0f}% {flag}")

t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
split = int(dt.datetime(2025, 7, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>10000 ORDER BY n DESC LIMIT 60", (t0,)).fetchall()]
c.close()
print(f"монет {len(syms)} · 1h вход · 2024-2026 · OOS 2025-07")

fams = ["breakout_L", "breakout_S", "pivbounce_L", "pivbounce_S", "volspike_L", "rangefade_L", "rangefade_S", "mrev_qtp_L"]
IS = {k: [] for k in fams}; OOS = {k: [] for k in fams}

for sym in syms:
    d1 = load(sym, "1h", t0)
    if len(d1) < 800: continue
    d1 = d1.reset_index(drop=True)
    w = wt(d1); at1 = atrtrend(d1)
    # causal daily pivot (из прошлого дня)
    d1["day"] = pd.to_datetime(d1.time, unit="ms").dt.floor("D")
    dg = d1.groupby("day").agg(H=("high", "max"), L=("low", "min"), C=("close", "last"))
    dg["PP"] = (dg.H + dg.L + dg.C) / 3; dg["S1"] = 2 * dg.PP - dg.H; dg["R1"] = 2 * dg.PP - dg.L
    dg = dg.shift(1)  # прошлый день → causal
    piv = d1["day"].map(dg.PP); s1 = d1["day"].map(dg.S1); r1 = d1["day"].map(dg.R1)
    C = d1.close.values; L = d1.low.values; Hh = d1.high.values; V = d1.volume.values; T = d1.time.values
    volavg = pd.Series(V).rolling(48).mean().values
    hi20 = pd.Series(Hh).rolling(20).max().shift(1).values  # прошлый макс (causal)
    lo20 = pd.Series(L).rolling(20).min().shift(1).values
    wv = w.values; s1v = s1.values; r1v = r1.values; ppv = piv.values
    for i in range(60, len(d1) - 1):
        D = OOS if T[i] >= split else IS
        e = C[i]
        # breakout: закрытие выше макс20 (пробой+хол), SL под макс20, TP 2R
        if hi20[i] and C[i] > hi20[i] and C[i - 1] <= hi20[i]:
            sl = hi20[i] * 0.995; D["breakout_L"].append((i, 1, sl, e + 2 * (e - sl)))
        if lo20[i] and C[i] < lo20[i] and C[i - 1] >= lo20[i]:
            sl = lo20[i] * 1.005; D["breakout_S"].append((i, -1, sl, e - 2 * (sl - e)))
        # pivot bounce: касание S1 снизу + WT перепродан, TP=PP
        if s1v[i] and L[i] <= s1v[i] and C[i] > s1v[i] and wv[i] < -30 and ppv[i] and ppv[i] > e:
            sl = s1v[i] * 0.99; D["pivbounce_L"].append((i, 1, sl, min(ppv[i], e + 2 * (e - sl))))
        if r1v[i] and Hh[i] >= r1v[i] and C[i] < r1v[i] and wv[i] > 30 and ppv[i] and ppv[i] < e:
            sl = r1v[i] * 1.01; D["pivbounce_S"].append((i, -1, sl, max(ppv[i], e - 2 * (sl - e))))
        # vol spike: объём>3×avg + зелёная, momentum long, SL под баром, TP 2R
        if volavg[i] and V[i] > 3 * volavg[i] and C[i] > C[i - 1]:
            sl = L[i] * 0.995; D["volspike_L"].append((i, 1, sl, e + 2 * (e - sl)))
        # range fade: at1 болтается (флэт: смен знака много) — фейд WT экстремумов, TP 1R
        if at1[i] > 0 and wv[i] < -60:
            sl = L[i - 3:i + 1].min() * 0.997; D["rangefade_L"].append((i, 1, sl, e + 1 * (e - sl)))
        if at1[i] < 0 and wv[i] > 60:
            sl = Hh[i - 3:i + 1].max() * 1.003; D["rangefade_S"].append((i, -1, sl, e - 1 * (sl - e)))
        # mean-rev quick TP: WT<-55, быстрый выход 0.6R (высокий WR?)
        if wv[i] < -55:
            sl = L[i - 5:i + 1].min() * 0.997; D["mrev_qtp_L"].append((i, 1, sl, e + 0.6 * (e - sl)))
    # симуляция накопленных для ЭТОГО sym
    for store in (IS, OOS):
        for k in fams:
            pend = [x for x in store[k] if isinstance(x, tuple) and len(x) == 4]
            store[k] = [v for v in store[k] if not (isinstance(v, tuple) and len(v) == 4)]  # уже симулированные -> float
            if pend:
                idx = [x[0] for x in pend]; sd = pend[0][1]; sls = [x[2] for x in pend]; tps = [x[3] for x in pend]
                ttl = 24 if "qtp" in k or "fade" in k or "bounce" in k else 48
                store[k] += sim(idx, d1, sd, sls, tps, ttl)

print("\n=== IN-SAMPLE (2024..2025-06) ===")
for k in fams: rep(k, IS[k])
print("\n=== OUT-OF-SAMPLE (2025-07..2026) ===")
for k in fams: rep(k, OOS[k])
