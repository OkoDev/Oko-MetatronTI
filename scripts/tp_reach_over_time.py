# -*- coding: utf-8 -*-
"""
TP Reach Rate как функция времени удержания.

Вопрос: через сколько часов уровень достигается?
Тест: reach_rate(t) для t = 12h, 24h, 48h, 72h, 120h, 168h, 336h, 504h (3w)

Также: cumulative reach curve — % кластеров которые достигнуты к времени T.
Это даёт оптимальный time exit параметр.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path("E:/MTF BOT/CURSOR/crypto_volume_bot/data/history")

PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "AAVEUSDT", "ARBUSDT", "ATOMUSDT", "INJUSDT", "NEARUSDT",
    "OPUSDT", "SUIUSDT", "TIAUSDT", "TRXUSDT", "UNIUSDT",
]

LOOKAHEAD_MAX_H = 504   # 3 недели максимум
VP_LOOKBACK_H = 480
VP_BINS = 100
ATR_PERIOD = 14
TIMEPOINTS = [12, 24, 48, 72, 120, 168, 336, 504]  # часы


def atr_daily_pct(df1d, period=ATR_PERIOD):
    hi = df1d["high"].values
    lo = df1d["low"].values
    cl = df1d["close"].values
    prev_cl = np.roll(cl, 1); prev_cl[0] = cl[0]
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - prev_cl), np.abs(lo - prev_cl)))
    atr = pd.Series(tr).ewm(span=period, adjust=False).mean().values
    return atr / cl * 100


def standard_pivots_up(h, l, c):
    pp = (h + l + c) / 3
    return [(2*pp - l, 3, "std_r1"), (pp + (h-l), 2, "std_r2")]


def compute_vp_poc(bars):
    hi_a, lo_a, vo_a = bars["high"].values, bars["low"].values, bars["volume"].values
    hi, lo = hi_a.max(), lo_a.min()
    if hi <= lo or vo_a.sum() == 0: return None
    bins = np.linspace(lo, hi, VP_BINS + 1)
    vp = np.zeros(VP_BINS)
    for b in range(VP_BINS):
        ov = np.maximum(np.minimum(hi_a, bins[b+1]) - np.maximum(lo_a, bins[b]), 0)
        vp[b] = (vo_a * ov / np.maximum(hi_a - lo_a, 1e-9)).sum()
    poc_idx = np.argmax(vp)
    return (bins[poc_idx] + bins[poc_idx+1]) / 2


def psycho_up(price):
    mag = 10 ** int(np.log10(price))
    lvls = set()
    for step in [mag, mag/2, mag/5, mag/10]:
        above = np.ceil(price / step) * step
        if above > price * 1.001: lvls.add(round(above, 8))
    return sorted(lvls)[:4]


def find_bear_fvg_active(H, L, C, cur, lookback=150):
    entry = C[cur]; out = []
    for i in range(max(2, cur-lookback), cur):
        if H[i] < L[i-2]:
            mid = (H[i] + L[i-2]) / 2
            if mid <= entry: continue
            if H[i+1:cur+1].max() >= H[i]: continue
            out.append((mid, cur - i))
    return out


def test_pair(symbol):
    p = BASE / "1h" / f"{symbol}.parquet"
    if not p.exists(): return None
    df1h = pd.read_parquet(p)
    df1d = df1h.resample("1D").agg(
        high=("high","max"), low=("low","min"),
        close=("close","last"), volume=("volume","sum")).dropna()
    df1w = df1h.resample("W-MON").agg(high=("high","max")).dropna()

    H1, L1, C1 = df1h["high"].values, df1h["low"].values, df1h["close"].values
    dates_1h, dates_1d = df1h.index, df1d.index
    atr_pct = atr_daily_pct(df1d)

    rows = []
    for i_d in range(VP_LOOKBACK_H//24 + 2, len(dates_1d) - 3):
        today_ts = dates_1d[i_d]
        prev_d = df1d.iloc[i_d - 1]
        atr = atr_pct[i_d - 1]
        if atr <= 0: continue

        i_1h = np.searchsorted(dates_1h, today_ts)
        if i_1h >= len(H1) - LOOKAHEAD_MAX_H - 5: continue

        entry = C1[i_1h]
        # Максимальное high за каждый период
        future_highs = {}
        for t in TIMEPOINTS:
            end = min(i_1h + 1 + t, len(H1))
            future_highs[t] = H1[i_1h+1:end].max() if end > i_1h+1 else entry

        def add_level(name, lvl, weight, age=None):
            if lvl <= entry * 1.001: return
            dist_pct = (lvl - entry) / entry * 100
            if dist_pct <= 0 or dist_pct > 20: return
            dist_atr = dist_pct / atr
            # Когда первый раз достигнут
            first_hit = None
            for t in TIMEPOINTS:
                if future_highs[t] >= lvl:
                    first_hit = t
                    break
            row = dict(name=name, weight=weight, dist_pct=dist_pct,
                       dist_atr=dist_atr, atr=atr, first_hit=first_hit)
            if age is not None: row["age"] = age
            for t in TIMEPOINTS:
                row[f"reach_{t}h"] = int(future_highs[t] >= lvl)
            rows.append(row)

        # Уровни
        for lvl, w, n in standard_pivots_up(prev_d["high"], prev_d["low"], prev_d["close"]):
            add_level(n, lvl, w)

        add_level("pdh", prev_d["high"], 3)

        pw_mask = df1w.index < today_ts
        if pw_mask.sum() >= 1:
            add_level("pwh", df1w[pw_mask]["high"].iloc[-1], 4)

        for lvl in psycho_up(entry):
            add_level("psycho", lvl, 2)

        vp_bars = df1h[dates_1h < today_ts].iloc[-VP_LOOKBACK_H:]
        if len(vp_bars) >= 48:
            poc = compute_vp_poc(vp_bars)
            if poc: add_level("vp_poc", poc, 3)

        step4 = i_1h // 4
        if step4 > 10:
            H4, L4, C4 = H1[::4][:step4+1], L1[::4][:step4+1], C1[::4][:step4+1]
            for mid, age in find_bear_fvg_active(H4, L4, C4, len(C4)-1, 50):
                add_level("fvg_4h", mid, 3, age)

        for mid, age in find_bear_fvg_active(H1, L1, C1, i_1h, 200):
            add_level("fvg_1h", mid, 2, age)

    return pd.DataFrame(rows) if rows else None


# ─────────────────────────────────────────────────────────────────────
print("=" * 90)
print("TP REACH OVER TIME — reach_rate(t) для разных горизонтов удержания")
print(f"Timepoints: {TIMEPOINTS} часов | Pairs: {len(PAIRS)}")
print("=" * 90)

all_dfs = []
for sym in PAIRS:
    df = test_pair(sym)
    if df is not None and len(df) > 0:
        all_dfs.append(df); sys.stdout.write(f"  ✓ {sym}\n")
    else:
        sys.stdout.write(f"  ✗ {sym}\n")
    sys.stdout.flush()

combined = pd.concat(all_dfs, ignore_index=True)
print(f"\nВсего уровней: {len(combined)}\n")

SOURCES = ["std_r1", "pdh", "pwh", "psycho", "vp_poc", "fvg_4h", "fvg_1h"]

# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 1: Reach rate(t) по источникам — ВСЕ дистанции
# ─────────────────────────────────────────────────────────────────────
print("=" * 90)
print("CUMULATIVE REACH RATE(t) — все дистанции (% уровней достигнутых к времени T)")
print(f"  {'':>10}", end="")
for t in TIMEPOINTS:
    print(f"  {t}h", end="")
print()
print("-" * 90)

for src in SOURCES:
    sub = combined[combined["name"] == src]
    if len(sub) < 20: continue
    print(f"  {src:<10}", end="")
    for t in TIMEPOINTS:
        r = sub[f"reach_{t}h"].mean() * 100
        print(f"  {r:>5.1f}%", end="")
    print(f"  (n={len(sub)})")

# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 2: По дистанции в ATR — 0.5-1R (реальный TP диапазон 4h)
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 90)
print("CUMULATIVE REACH: dist 0.5-1R дневного ATR (TP для 4h сделок ~3.5-7% от entry)")
real = combined[(combined["dist_atr"] >= 0.5) & (combined["dist_atr"] < 1.0)]
print(f"  {'':>10}", end="")
for t in TIMEPOINTS: print(f"  {t}h", end="")
print()
print("-" * 90)
for src in SOURCES:
    sub = real[real["name"] == src]
    if len(sub) < 20: continue
    print(f"  {src:<10}", end="")
    for t in TIMEPOINTS:
        r = sub[f"reach_{t}h"].mean() * 100
        print(f"  {r:>5.1f}%", end="")
    print(f"  (n={len(sub)})")

# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 3: dist 1-2R (амбициозный TP, 7-14%)
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 90)
print("CUMULATIVE REACH: dist 1-2R (амбициозный TP ~7-14% от entry)")
amb = combined[(combined["dist_atr"] >= 1.0) & (combined["dist_atr"] < 2.0)]
print(f"  {'':>10}", end="")
for t in TIMEPOINTS: print(f"  {t}h", end="")
print()
print("-" * 90)
for src in SOURCES:
    sub = amb[amb["name"] == src]
    if len(sub) < 20: continue
    print(f"  {src:<10}", end="")
    for t in TIMEPOINTS:
        r = sub[f"reach_{t}h"].mean() * 100
        print(f"  {r:>5.1f}%", end="")
    print(f"  (n={len(sub)})")

# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 4: Распределение времени до достижения (когда первый hit?)
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 90)
print("КОГДА первый раз достигается уровень? (только для тех что достигнуты за 3 недели)")
sub_hit = combined[combined["first_hit"].notna()]
print(f"  {'':>10}", end="")
for t in TIMEPOINTS: print(f"  {t}h", end="")
print("  (% от всех достигнутых)")
print("-" * 90)
for src in SOURCES:
    sub = sub_hit[sub_hit["name"] == src]
    if len(sub) < 20: continue
    print(f"  {src:<10}", end="")
    cumulative = 0
    for t in TIMEPOINTS:
        first_at_t = (sub["first_hit"] == t).sum()
        cumulative += first_at_t
        pct = cumulative / len(sub) * 100
        print(f"  {pct:>5.1f}%", end="")
    print(f"  (n={len(sub)} hit)")

# ─────────────────────────────────────────────────────────────────────
# ФИНАЛ: Оптимальный time exit
# ─────────────────────────────────────────────────────────────────────
print()
print("=" * 90)
print("ОПТИМАЛЬНЫЙ TIME EXIT: marginal reach (сколько новых % за следующий период)")
print("(Если marginal reach < 2% — смысла ждать дальше нет)")
print()
print(f"  {'':>10}", end="")
for i, t in enumerate(TIMEPOINTS):
    if i == 0: print(f"  0-{t}h", end="")
    else: print(f"  {TIMEPOINTS[i-1]}-{t}h", end="")
print()
print("-" * 90)

for src in SOURCES:
    sub = combined[combined["name"] == src]
    if len(sub) < 20: continue
    print(f"  {src:<10}", end="")
    prev_r = 0
    for i, t in enumerate(TIMEPOINTS):
        r = sub[f"reach_{t}h"].mean() * 100
        marginal = r - prev_r
        marker = " ←STOP" if marginal < 2.0 and i > 1 else ""
        print(f"  {marginal:>+5.1f}%{marker[:6]}", end="")
        prev_r = r
    print()

print()
print("ВЫВОД: оптимальный time exit = точка где marginal_reach < 2% для большинства источников")
