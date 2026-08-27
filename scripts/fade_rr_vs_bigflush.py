# -*- coding: utf-8 -*-
"""RR против BIGFLUSH15: специфичен ли RR для 4h-fade? (13.08.2026, DS).

Тест роя ([[2026-08-12-рыночная-ли-характеристика-rr-recovery-rate-фон-fa]], консенсус п.3):
«Контроль на bigflush15 (LONG-only) — ключевой тест для отделения рыночного эффекта
от setup-specific. Если RR нейтрален или положителен для всех окон bigflush15 →
рыночный признак. Если меняет знак → специфичен для fade».

Конструкция:
  RR_4h   = медиана RR (окно 200 баров 4h) по ликвидной вселенной в 7-мес окне;
  BIG15   = медиана net% сигналов bigflush15 (15m, ТА ЖЕ механика входа ATRTrend+WT<−60,
            SL=swing3, TP1R, TTL24, косты 0.35%, кулдаун 6ч) в том же окне.

bigflush15 — LONG-only боевая стопка на 15m. Если RR_4h разделяет окна BIG15
(высокие RR → высокая медиана net) — RR рыночен. Если нет — RR специфичен для 4h-fade.

Запуск:  python scripts/fade_rr_vs_bigflush.py
"""
import datetime as dt
import sqlite3
import sys
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

DB = "ohlcv_cache.db"
COST = 0.35
WIN_M, STEP_M = 7.0, 1.0
SINCE_Y = 2024
MS_M = 30.44 * 24 * 3600 * 1000
t0 = int(dt.datetime(SINCE_Y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
LB4, N4 = 200, 40
N15 = 40


def wt(df, n1=10, n2=21):
    hlc = (df.high + df.low + df.close) / 3
    esa = hlc.ewm(span=n1).mean()
    d = (hlc - esa).abs().ewm(span=n1).mean()
    return ((hlc - esa) / (0.015 * d.replace(0, np.nan))).ewm(span=n2).mean().fillna(0).values


def atrt(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean().values
    up = hl2 - factor * atr; dn = hl2 + factor * atr
    n = len(c); cv = c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i-1]) if cv[i-1] > u[i-1] else up[i]
        d_[i] = min(dn[i], d_[i-1]) if cv[i-1] < d_[i-1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i-1] else (-1 if cv[i] < u[i-1] else dirn[i-1])
    return dirn


def ex_tp1r(i, H, L, C, sl, ttl=24):
    e = C[i]; tp = e + (e - sl); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl: return (sl - e) / e * 100
        if H[j] >= tp: return (tp - e) / e * 100
    return (C[end] - e) / e * 100


def rr_feat(r, i, lb):
    w = r[i - lb:i]
    w = w[np.isfinite(w)]
    if len(w) < lb * 0.8:
        return np.nan
    sd = w.std()
    if sd <= 0:
        return np.nan
    shock = np.where(np.abs(w) > 2 * sd)[0]
    shock = shock[shock < len(w) - 12]
    if len(shock) < 5:
        return np.nan
    return float(np.median([w[k + 1:k + 13].sum() for k in shock]) / sd)


# ── 1) RR_4h по окнам (медиана по вселенной) ────────────────────────────────
con = sqlite3.connect(DB)
syms4 = [r[0] for r in con.execute(
    "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? "
    "GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?", (t0, LB4 * 2, N4)).fetchall()]
con.close()
rr_ts = []   # (lo_ms, rr)
for s in syms4:
    c = sqlite3.connect(DB)
    d = pd.read_sql("SELECT time,close FROM ohlcv_cache WHERE timeframe='4h' AND symbol=? AND time>=? "
                    "ORDER BY time", c, params=(s, t0))
    c.close()
    if len(d) < LB4 * 2:
        continue
    C = d.close.values; T = d.time.values
    r = np.concatenate([[np.nan], np.diff(C) / C[:-1] * 100])
    cur = int(d.time.iloc[0]); t_max = int(d.time.iloc[-1])
    while cur + WIN_M * MS_M <= t_max:
        idx = np.where((T >= cur) & (T < cur + WIN_M * MS_M))[0]
        if len(idx) < 100:
            cur += STEP_M * MS_M
            continue
        j = idx[-1]
        rr = rr_feat(r, j, LB4)
        if np.isfinite(rr):
            rr_ts.append((cur, rr))
        cur += STEP_M * MS_M

agg = defaultdict(list)
for lo, rr in rr_ts:
    agg[lo].append(rr)
rr_win = {lo: float(np.median(v)) for lo, v in agg.items() if len(v) >= 10}

# ── 2) bigflush15 сигналы (LONG-only, 15m) ───────────────────────────────────
con = sqlite3.connect(DB)
syms15 = [r[0] for r in con.execute(
    "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? "
    "GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?", (t0, 2920 * 4, N15)).fetchall()]
con.close()
bf = []   # (ts_ms, net)
for s in syms15:
    c = sqlite3.connect(DB)
    d = pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? "
                    "AND timeframe='15m' AND time>=? ORDER BY time", c, params=(s, t0))
    c.close()
    if len(d) < 2920:
        continue
    w = wt(d); tr_ = atrt(d)
    H, L, C, T = d.high.values, d.low.values, d.close.values, d.time.values
    last = -10**18
    for i in range(120, len(d) - 1):
        if T[i] - last < 6 * 3600 * 1000:      # кулдаун 6ч
            continue
        if not (tr_[i] > 0 and w[i] < -60 and w[i] > w[i-1]):
            continue
        sl = L[max(0, i-3):i+1].min() * 0.997
        if sl >= C[i]:
            continue
        dist = (C[i] - sl) / C[i] * 100
        if not (4.0 < dist <= 12.0):
            continue
        last = T[i]
        bf.append((int(T[i]), ex_tp1r(i, H, L, C, sl) - COST))

# ── 3) BIG15 медиана по тем же окнам ────────────────────────────────────────
bf_win = defaultdict(list)
for t, net in bf:
    # ближайшее окно: lo = floor((t - t0) / STEP_M) * STEP_M... используем сетку из rr_win
    for lo in sorted(rr_win):
        if lo <= t < lo + WIN_M * MS_M:
            bf_win[lo].append(net)
            break
rows = []
for lo in sorted(rr_win):
    if len(bf_win.get(lo, [])) >= 20:
        rows.append((lo, rr_win[lo], float(np.median(bf_win[lo])), len(bf_win[lo])))

print("═" * 100)
print("RR_4h против BIGFLUSH15 (LONG-only, 15m): рыночный ли признак?")
print("═" * 100)
print(f"{'окно':<9} {'RR_4h (мед)':>11} {'BIG15 мед':>10} {'n':>5}  знак совпал")
agree = 0
for lo, rr, med, n in rows:
    d0 = dt.datetime.fromtimestamp(lo/1000, dt.timezone.utc).strftime("%Y-%m")
    ok = (rr > 0) == (med > 0)
    agree += ok
    print(f"{d0:<9} {rr:>+11.3f} {med:>+9.3f}% {n:>5}  {'✓' if ok else '✗'}")
if len(rows) >= 6:
    rr_a = np.array([x[1] for x in rows])
    bf_a = np.array([x[2] for x in rows])
    pr = stats.pearsonr(rr_a, bf_a)
    sp = stats.spearmanr(rr_a, bf_a)
    print(f"\nсогласованность знака {agree}/{len(rows)} ({100*agree/len(rows):.0f}%)")
    print(f"Pearson corr(RR_4h, BIG15) = {pr.statistic:+.3f} (p={pr.pvalue:.3f}) · "
          f"Spearman = {sp.statistic:+.3f} (p={sp.pvalue:.3f})")
    print(f"⟹ {'РЫНОЧНЫЙ: RR разделяет окна и другой механики' if pr.statistic > 0.4 and pr.pvalue < 0.05 else 'СПЕЦИФИЧЕН: RR не объясняет доходность bigflush15 по окнам'}")
print(f"\nBIG15 сигналов всего: {len(bf)}")
