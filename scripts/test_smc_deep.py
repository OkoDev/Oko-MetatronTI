# -*- coding: utf-8 -*-
"""SMC v2 (карта #2): ГЛУБОКОЕ окно. v1 провалился — при флеше цена уже пробила ближние
бычьи зоны, поэтому «цена у OB» почти не совпадало. Правильный вопрос: падает ли цена
В более глубокую HTF-зону спроса. Меряем ДИСТАНЦИЮ до ближайшей зоны снизу."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.structure import detect_structure
from core.smc.order_blocks import detect_order_blocks
from core.smc.fvg import detect_fvg
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


def sim(i, H, L, C, sl, ttl=24):
    e = C[i]; tp = e + (e - sl); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl: return (sl - e) / e * 100 - COST
        if H[j] >= tp: return (tp - e) / e * 100 - COST
    return (C[end] - e) / e * 100 - COST


def zones(df_slice, price):
    """Дистанция до ближайшей бычьей зоны СНИЗУ (%). None если нет."""
    best = None
    try:
        st = detect_structure(df_slice)
        obs = detect_order_blocks(df_slice, st)
        for ob in (getattr(obs, "active_bull", None) or []):
            if ob.top <= price:
                d = (price - ob.top) / price * 100
                best = d if best is None else min(best, d)
    except Exception:
        pass
    try:
        fv = detect_fvg(df_slice)
        for g in (getattr(fv, "active_bull", None) or []):
            t = getattr(g, "top", None)
            if t and t <= price:
                d = (price - t) / price * 100
                best = d if best is None else min(best, d)
    except Exception:
        pass
    return best


def rep(name, rows):
    if len(rows) < 25:
        print(f"    {name:36} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]); srt = np.sort(r); cut = max(1, len(r) // 10)
    med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = set(x[2] for x in rows)
    pos = sum(1 for cn in coins if np.median([x[1] for x in rows if x[2] == cn]) > 0)
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:36} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:2}/{len(coins):2} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' "
                                "AND time>=? GROUP BY symbol HAVING n>25000 ORDER BY n DESC LIMIT 18",
                                (t0,)).fetchall()]
c.close()
print(f"монет {len(syms)} · SMC ГЛУБОКОЕ окно: 1h 600 баров (25д), 4h 400 баров (66д)\n")
B = {}
for si, sym in enumerate(syms):
    d15 = load(sym, "15m", t0); d1 = load(sym, "1h", t0); d4 = load(sym, "4h", t0)
    if len(d15) < 3000 or len(d1) < 800 or len(d4) < 300:
        continue
    w = wt(d15); a = atrt(d15)
    H = d15.high.values; L = d15.low.values; C = d15.close.values; T = d15.time.values
    t1 = d1.time.values; t4 = d4.time.values; n = 0
    for i in range(80, len(d15) - 1):
        if not (a[i] > 0 and w[i] < -60 and w[i] > w[i - 1]):
            continue
        e = C[i]; sl = L[max(0, i - 3):i + 1].min() * 0.997
        if not (sl < e and (e - sl) / e * 100 > 4.0):
            continue
        p = sim(i, H, L, C, sl); n += 1; rec = (0, p, sym)
        j1 = int(np.searchsorted(t1, T[i])) - 1
        j4 = int(np.searchsorted(t4, T[i])) - 1
        d1z = zones(d1.iloc[max(0, j1 - 600):j1 + 1], e) if j1 > 100 else None
        d4z = zones(d4.iloc[max(0, j4 - 400):j4 + 1], e) if j4 > 100 else None
        best = min([x for x in (d1z, d4z) if x is not None], default=None)
        B.setdefault("ВСЕ", []).append(rec)
        k = ("зоны нет" if best is None else
             ("зона <1% ниже" if best < 1 else
              ("1-3% ниже" if best < 3 else ("3-6% ниже" if best < 6 else ">6% ниже"))))
        B.setdefault(k, []).append(rec)
        B.setdefault("зона 1h есть" if d1z is not None else "зоны 1h нет", []).append(rec)
        B.setdefault("зона 4h есть" if d4z is not None else "зоны 4h нет", []).append(rec)
    print(f"  [{si+1}/{len(syms)}] {sym.split('/')[0]:10} сигналов={n}")
print("\n═══ ДИСТАНЦИЯ ДО БЛИЖАЙШЕЙ ЗОНЫ СПРОСА СНИЗУ ═══")
rep("ВСЕ", B.get("ВСЕ", []))
for k in ("зона <1% ниже", "1-3% ниже", "3-6% ниже", ">6% ниже", "зоны нет"):
    rep(k, B.get(k, []))
print("\n═══ НАЛИЧИЕ ЗОНЫ ПО ТФ ═══")
for k in ("зона 1h есть", "зоны 1h нет", "зона 4h есть", "зоны 4h нет"):
    rep(k, B.get(k, []))
