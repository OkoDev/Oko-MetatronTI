# -*- coding: utf-8 -*-
"""КАРТА, БЛОК 4 (07.08) на ядре BIG-FLUSH:
  #4  НАСТОЯЩИЙ DivergenceDetector проекта (виртуальные линии + зоны OS + цепочки + сила 0-100).
      Раньше мерил СВОИМ грубым прокси: на 1h помогал, на 4h вредил. Настоящий не тестировался НИ РАЗУ.
  #12 ГИБРИД-ВЫХОД (½ TP1R + ½ ATR-раннер). На 4h-ядре был АРТЕФАКТОМ 2024 — но big-flush это
      эдж ТЕКУЩЕГО режима (2025-26 сильные), значит вопрос открыт заново.
  #9  EQH/EQL — равные хаи/лои как магнит ликвидности (в бэктесте не участвовали).
Причинно, ликвидная половина, косты 0.25."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.indicators.divergence_detector import DivergenceDetector
DB = "ohlcv_cache.db"; COST = 0.25


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def wt_arr(df, n1=10, n2=21):
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


def atr_series(df, n=14):
    h, l, c = df.high, df.low, df.close
    return pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1).rolling(n).mean().values


def e_tp1r(i, H, L, C, sl, ttl=24):
    e = C[i]; tp = e + (e - sl); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl: return (sl - e) / e * 100 - COST
        if H[j] >= tp: return (tp - e) / e * 100 - COST
    return (C[end] - e) / e * 100 - COST


def e_hybrid(i, H, L, C, A, sl, k=2.0, ttl=96):
    """½ на TP1R, ½ раннером: после +1R трейл k*ATR от максимума."""
    e = C[i]; R = e - sl; tp = e + R; end = min(i + ttl, len(C) - 1)
    half1 = None; peak = e; trail = sl
    for j in range(i + 1, end + 1):
        if half1 is None and L[j] <= sl:
            return (sl - e) / e * 100 - COST
        if half1 is None and H[j] >= tp:
            half1 = (tp - e) / e * 100; peak = max(peak, H[j]); trail = max(trail, e)
            continue
        if half1 is not None:
            peak = max(peak, H[j])
            a = A[j] if not np.isnan(A[j]) else R
            trail = max(trail, peak - k * a)
            if L[j] <= trail:
                return (half1 + (trail - e) / e * 100) / 2 - COST
    if half1 is None:
        return (C[end] - e) / e * 100 - COST
    return (half1 + (C[end] - e) / e * 100) / 2 - COST


def eqh_eql(df_slice, price, tol=0.15):
    """Равные лои (EQL) ниже цены — магнит ликвидности. Возвращает (есть_ли, дистанция%)."""
    lows = df_slice["low"].values[-60:]
    if len(lows) < 20:
        return False, None
    piv = [lows[k] for k in range(2, len(lows) - 2)
           if lows[k] == min(lows[k - 2:k + 3])]
    best = None
    for a in range(len(piv)):
        for b in range(a + 1, len(piv)):
            if piv[a] <= 0:
                continue
            if abs(piv[a] - piv[b]) / piv[a] * 100 < tol:      # два примерно равных лоя
                lvl = min(piv[a], piv[b])
                if lvl < price:
                    d = (price - lvl) / price * 100
                    best = d if best is None else min(best, d)
    return (best is not None), best


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
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' "
                                "AND time>=? GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT 22",
                                (t0,)).fetchall()]
c.close()
det = DivergenceDetector(pivot_period=5, max_bars=100, min_bars_between=5)
turn = {}; DATA = {}
for s in syms:
    d = load(s, "15m", t0)
    if len(d) >= 5000:
        DATA[s] = d; turn[s] = float(np.nanmedian((d.close * d.volume).values))
mt = np.nanmedian(list(turn.values()))
print(f"монет {len(DATA)}, ликвидных {sum(1 for s in DATA if turn[s] >= mt)}\n")
DIV = defaultdict(list); HYB = defaultdict(list); EQ = defaultdict(list)
for si, (s, d) in enumerate(DATA.items()):
    if turn[s] < mt:
        continue
    w = wt_arr(d); a = atrt(d); A = atr_series(d)
    H = d.high.values; L = d.low.values; C = d.close.values
    dfw = d.copy(); dfw["wt1"] = w
    n = 0
    for i in range(120, len(d) - 1):
        if not (a[i] > 0 and w[i] < -60 and w[i] > w[i - 1]):
            continue
        e = C[i]; sl = L[max(0, i - 3):i + 1].min() * 0.997
        if not (sl < e and (e - sl) / e * 100 > 4.0):
            continue
        p1 = e_tp1r(i, H, L, C, sl); ph = e_hybrid(i, H, L, C, A, sl)
        rec = (0, p1, s); n += 1
        DIV["ВСЕ"].append(rec); HYB["TP1R (база)"].append(rec); HYB["ГИБРИД"].append((0, ph, s))
        # настоящий детектор на окне до сигнала (причинно)
        sl_ = dfw.iloc[max(0, i - 160):i + 1].reset_index(drop=True)
        try:
            rb = det.detect_regular_bullish(sl_, indicator_col="wt1")
        except Exception:
            rb = None
        if rb:
            st = det._calculate_strength(rb, "REGULAR_BULLISH")
            DIV["дивергенция ЕСТЬ"].append(rec)
            DIV[("сила ≥60" if st >= 60 else "сила <60")].append(rec)
        else:
            DIV["дивергенции нет"].append(rec)
        has, dist = eqh_eql(d.iloc[max(0, i - 80):i + 1], e)
        EQ["EQL ниже есть" if has else "EQL нет"].append(rec)
        if has and dist is not None:
            EQ["EQL <2% ниже" if dist < 2 else "EQL >2% ниже"].append(rec)
    print(f"  [{si+1}] {s.split('/')[0]:10} сигналов={n}")
print("\n═══ #4 НАСТОЯЩИЙ DivergenceDetector (regular bullish, оба дна в OS) ═══")
for k in ("ВСЕ", "дивергенция ЕСТЬ", "дивергенции нет", "сила ≥60", "сила <60"):
    rep(k, DIV.get(k, []))
print("\n═══ #12 ГИБРИД-ВЫХОД на big-flush ═══")
for k in ("TP1R (база)", "ГИБРИД"):
    rep(k, HYB.get(k, []))
print("\n═══ #9 EQH/EQL как магнит ликвидности ═══")
for k in ("EQL ниже есть", "EQL нет", "EQL <2% ниже", "EQL >2% ниже"):
    rep(k, EQ.get(k, []))
