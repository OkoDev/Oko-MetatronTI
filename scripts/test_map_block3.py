# -*- coding: utf-8 -*-
"""КАРТА, БЛОК 3 (05.08): за один проход по свечам —
  #21 СЕССИИ для 4h/1h сиблингов (для 15m измерено: ASIA PF5.49, LONDON 0.45 — работает ли на старших?)
  #6  ДНЕВНЫЕ и МЕСЯЧНЫЕ пивоты (пробовали только недельные, и те слегка вредили)
  #26 VWAP-reversion (новый класс: отклонение от VWAP как фильтр к фейду)
  #7  ФОРМА СВЕЧИ входа (позиция close в диапазоне бара — прокси пин-бара/поглощения)
Причинно, ликвидная половина, косты 0.25."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")
DB = "ohlcv_cache.db"; COST = 0.25


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
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


def sim(i, H, L, C, sl, ttl):
    e = C[i]; tp = e + (e - sl); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl: return (sl - e) / e * 100 - COST
        if H[j] >= tp: return (tp - e) / e * 100 - COST
    return (C[end] - e) / e * 100 - COST


def piv(df, rule):
    """Пивоты предыдущего периода (D/M), причинно: доступны со следующего периода."""
    s = df.set_index(pd.to_datetime(df.time, unit="ms"))
    g = s.resample(rule, label="left", closed="left").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    pp = (g.high + g.low + g.close) / 3
    s1 = 2 * pp - g.high; s2 = pp - (g.high - g.low)
    off = pd.Timedelta(days=1) if rule == "1D" else pd.Timedelta(days=31)
    av = g.index + off
    return pd.DataFrame({"time": (av.astype("int64") // 10 ** 6).values,
                         "pp": pp.values, "s1": s1.values, "s2": s2.values})


def sess(ms):
    h = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).hour
    return "ASIA" if h < 8 else ("LONDON" if h < 14 else ("NY" if h < 21 else "OFF"))


def rep(name, rows):
    if len(rows) < 25:
        print(f"    {name:34} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]); srt = np.sort(r); cut = max(1, len(r) // 10)
    med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = set(x[2] for x in rows)
    pos = sum(1 for cn in coins if np.median([x[1] for x in rows if x[2] == cn]) > 0)
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:34} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:2}/{len(coins):2} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>2500 ORDER BY n DESC LIMIT 40",
                                (t0,)).fetchall()]
c.close()
turn = {}; D4 = {}; D1 = {}
for s in syms:
    d4 = load(s, "4h", t0); d1 = load(s, "1h", t0)
    if len(d4) >= 1500 and len(d1) >= 6000:
        D4[s] = d4; D1[s] = d1
        turn[s] = float(np.nanmedian((d4.close * d4.volume).values))
mt = np.nanmedian(list(turn.values()))
print(f"монет {len(D4)}, ликвидных {sum(1 for s in D4 if turn[s] >= mt)}\n")
S4 = defaultdict(list); S1 = defaultdict(list)
PD = defaultdict(list); PM = defaultdict(list)
VW = defaultdict(list); SH = defaultdict(list)
for s in D4:
    if turn[s] < mt:
        continue
    for tf, d, thr, ttl, store in (("4h", D4[s], -60, 18, S4), ("1h", D1[s], -70, 18, S1)):
        w = wt(d); a = atrt(d)
        H = d.high.values; L = d.low.values; C = d.close.values
        O = d.open.values; T = d.time.values; V = d.volume.values
        pd_ = pd.merge_asof(pd.DataFrame({"time": T}), piv(D1[s], "1D"), on="time", direction="backward")
        pm_ = pd.merge_asof(pd.DataFrame({"time": T}), piv(D1[s], "MS"), on="time", direction="backward")
        tp_ = (H + L + C) / 3
        vwap = (pd.Series(tp_ * V).rolling(96 if tf == "1h" else 42).sum() /
                pd.Series(V).rolling(96 if tf == "1h" else 42).sum()).values
        for i in range(60, len(d) - 1):
            if not (a[i] > 0 and w[i] < thr and w[i] > w[i - 1]):
                continue
            e = C[i]; sl = L[max(0, i - 3):i + 1].min() * 0.997
            if not (sl < e):
                continue
            p = sim(i, H, L, C, sl, ttl); rec = (0, p, s)
            store[sess(T[i])].append(rec)
            if tf != "4h":
                continue
            # дальше — только на 4h-сетапе, чтобы не смешивать
            for nm, row, box in (("D", pd_.iloc[i], PD), ("M", pm_.iloc[i], PM)):
                near = None
                for lv in ("pp", "s1", "s2"):
                    v = row.get(lv)
                    if v and v > 0 and abs(e - v) / e * 100 < 1.5:
                        near = lv; break
                box[f"{nm}: у {near}" if near else f"{nm}: далеко"].append(rec)
            if not np.isnan(vwap[i]) and vwap[i] > 0:
                dv = (e - vwap[i]) / vwap[i] * 100
                VW[("ниже VWAP >3%" if dv < -3 else ("ниже 1-3%" if dv < -1 else
                    ("около ±1%" if dv < 1 else "выше VWAP")))].append(rec)
            rng = H[i] - L[i]
            if rng > 0:
                pos_c = (C[i] - L[i]) / rng
                SH[("закрытие в НИЗУ бара (<0.3)" if pos_c < 0.3 else
                    ("середина 0.3-0.7" if pos_c < 0.7 else "закрытие ВВЕРХУ (>0.7)"))].append(rec)
print("═══ #21 СЕССИИ для 4h-сиблинга (на 15m: ASIA PF5.49 / LONDON 0.45) ═══")
for k in ("ASIA", "LONDON", "NY", "OFF"):
    rep(f"4h · {k}", S4.get(k, []))
print("\n  ── и для 1h-сиблинга ──")
for k in ("ASIA", "LONDON", "NY", "OFF"):
    rep(f"1h · {k}", S1.get(k, []))
print("\n═══ #6 ДНЕВНЫЕ пивоты (4h-сетап) ═══")
for k in sorted(PD, key=lambda x: -len(PD[x])):
    rep(k, PD[k])
print("\n═══ #6 МЕСЯЧНЫЕ пивоты ═══")
for k in sorted(PM, key=lambda x: -len(PM[x])):
    rep(k, PM[k])
print("\n═══ #26 VWAP-отклонение ═══")
for k in ("ниже VWAP >3%", "ниже 1-3%", "около ±1%", "выше VWAP"):
    rep(k, VW.get(k, []))
print("\n═══ #7 ФОРМА СВЕЧИ входа ═══")
for k in ("закрытие в НИЗУ бара (<0.3)", "середина 0.3-0.7", "закрытие ВВЕРХУ (>0.7)"):
    rep(k, SH.get(k, []))
