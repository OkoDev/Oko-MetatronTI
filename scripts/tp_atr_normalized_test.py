# -*- coding: utf-8 -*-
"""
TP Levels Test — нормировка через ATR.

Правильная метрика: dist_in_atr = dist_pct / atr_daily_pct.
Реальный TP для крипто:
  - LONG 15m: минимум 1.5R = TP >= 1.5 × ATR (daily)
  - Хороший TP: 2-4R
  - Дальний TP: 4-8R

Тест: reach_rate при dist_in_atr = [0.5-1, 1-2, 2-3, 3-5, 5+]
для каждого источника уровней.

Также: decay-фактор для FVG — новые (≤10 bars) vs старые (>30 bars).
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

LOOKAHEAD_H = 48
VP_LOOKBACK_H = 480
VP_BINS = 100
ATR_PERIOD = 14  # дней


def atr_daily(df1d, period=ATR_PERIOD):
    """ATR14 дневной как % от close."""
    hi = df1d["high"].values
    lo = df1d["low"].values
    cl = df1d["close"].values
    prev_cl = np.roll(cl, 1)
    prev_cl[0] = cl[0]
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - prev_cl), np.abs(lo - prev_cl)))
    atr = pd.Series(tr).ewm(span=period, adjust=False).mean().values
    return atr / cl * 100  # ATR as % of close


def standard_pivots_up(h, l, c):
    pp = (h + l + c) / 3
    return [(2*pp - l, 3, "std_r1"), (pp + (h-l), 2, "std_r2")]


def compute_vp_poc_vah(bars):
    hi_arr, lo_arr, vol_arr = bars["high"].values, bars["low"].values, bars["volume"].values
    hi, lo = hi_arr.max(), lo_arr.min()
    if hi <= lo or vol_arr.sum() == 0:
        return None, None
    bins = np.linspace(lo, hi, VP_BINS + 1)
    vp = np.zeros(VP_BINS)
    for b in range(VP_BINS):
        ov = np.minimum(hi_arr, bins[b+1]) - np.maximum(lo_arr, bins[b])
        ov = np.maximum(ov, 0)
        br = np.maximum(hi_arr - lo_arr, 1e-9)
        vp[b] = (vol_arr * ov / br).sum()
    poc_idx = np.argmax(vp)
    poc = (bins[poc_idx] + bins[poc_idx+1]) / 2
    target = vp.sum() * 0.70
    lo_i = hi_i = poc_idx
    acc = vp[poc_idx]
    while acc < target:
        up = hi_i + 1 < VP_BINS
        dn = lo_i - 1 >= 0
        if not up and not dn: break
        if (vp[hi_i+1] if up else -1) >= (vp[lo_i-1] if dn else -1):
            hi_i += 1; acc += vp[hi_i]
        else:
            lo_i -= 1; acc += vp[lo_i]
    vah = (bins[hi_i] + bins[hi_i+1]) / 2
    return poc, vah


def psycho_levels_up(price, n=5):
    mag = 10 ** int(np.log10(price))
    steps = [mag, mag/2, mag/5, mag/10]
    levels = set()
    for step in steps:
        above = np.ceil(price / step) * step
        if above > price * 1.001:
            levels.add(round(above, 8))
    return sorted(levels)[:n]


def find_bear_fvg_with_age(H, L, C, cur, lookback=200):
    """Возвращает (mid, age_bars) для активных Bear FVG выше C[cur]."""
    entry = C[cur]
    out = []
    for i in range(max(2, cur-lookback), cur):
        if H[i] < L[i-2]:
            mid = (H[i] + L[i-2]) / 2
            if mid <= entry: continue
            if H[i+1:cur+1].max() >= H[i]: continue  # заполнен
            age = cur - i
            out.append((mid, age))
    return out


def load_pair(symbol):
    p = BASE / "1h" / f"{symbol}.parquet"
    if not p.exists(): return None
    df1h = pd.read_parquet(p)
    df1d = df1h.resample("1D").agg(
        high=("high","max"), low=("low","min"),
        close=("close","last"), volume=("volume","sum")).dropna()
    df1w = df1h.resample("W-MON").agg(high=("high","max")).dropna()
    return df1h, df1d, df1w


def test_pair(symbol):
    result = load_pair(symbol)
    if result is None: return None
    df1h, df1d, df1w = result

    H1 = df1h["high"].values
    L1 = df1h["low"].values
    C1 = df1h["close"].values
    dates_1h = df1h.index
    dates_1d = df1d.index

    atr_pct = atr_daily(df1d)

    rows = []
    for i_d in range(VP_LOOKBACK_H//24 + 2, len(dates_1d) - 2):
        today_ts = dates_1d[i_d]
        prev_d = df1d.iloc[i_d - 1]
        atr = atr_pct[i_d - 1]  # ATR вчера как % close
        if atr <= 0: continue

        i_1h = np.searchsorted(dates_1h, today_ts)
        if i_1h >= len(H1) - LOOKAHEAD_H - 5: continue

        entry = C1[i_1h]
        future_high = H1[i_1h+1:i_1h+LOOKAHEAD_H+1].max()

        # Собираем уровни с dist_in_atr
        def make_row(name, lvl, weight, extra=None):
            if lvl <= entry: return None
            dist_pct = (lvl - entry) / entry * 100
            if dist_pct <= 0 or dist_pct > 15: return None
            dist_atr = dist_pct / atr
            reached = int(future_high >= lvl)
            r = dict(name=name, weight=weight, dist_pct=dist_pct,
                     dist_atr=dist_atr, reached=reached, atr_pct=atr)
            if extra: r.update(extra)
            return r

        # Пивоты
        for lvl, w, n in standard_pivots_up(prev_d["high"], prev_d["low"], prev_d["close"]):
            r = make_row(n, lvl, w);
            if r: rows.append(r)

        # PDH
        r = make_row("pdh", prev_d["high"], 3)
        if r: rows.append(r)

        # PWH
        pw_mask = df1w.index < today_ts
        if pw_mask.sum() >= 1:
            pwh = df1w[pw_mask]["high"].iloc[-1]
            r = make_row("pwh", pwh, 4)
            if r: rows.append(r)

        # Psycho
        for lvl in psycho_levels_up(entry, 4):
            r = make_row("psycho", lvl, 2)
            if r: rows.append(r)

        # VP
        vp_bars = df1h[dates_1h < today_ts].iloc[-VP_LOOKBACK_H:]
        if len(vp_bars) >= 48:
            poc, vah = compute_vp_poc_vah(vp_bars)
            if poc:
                r = make_row("vp_poc", poc, 3)
                if r: rows.append(r)
            if vah:
                r = make_row("vp_vah", vah, 2)
                if r: rows.append(r)

        # Bear FVG 4h
        step4 = i_1h // 4
        if step4 > 10:
            H4 = H1[::4][:step4+1]
            L4 = L1[::4][:step4+1]
            C4 = C1[::4][:step4+1]
            for mid, age in find_bear_fvg_with_age(H4, L4, C4, len(C4)-1, 50):
                r = make_row("fvg_4h", mid, 3, {"age_bars": age})
                if r: rows.append(r)

        # Bear FVG 1h
        for mid, age in find_bear_fvg_with_age(H1, L1, C1, i_1h, 200):
            r = make_row("fvg_1h", mid, 2, {"age_bars": age})
            if r: rows.append(r)

    return pd.DataFrame(rows) if rows else None


# ─────────────────────────────────────────────────────────────────────
print("=" * 80)
print("TP LEVELS TEST — ATR-нормированная дистанция")
print(f"Lookahead: {LOOKAHEAD_H}h | ATR period: {ATR_PERIOD}d")
print("=" * 80)

all_dfs = []
for sym in PAIRS:
    df = test_pair(sym)
    if df is not None and len(df) > 0:
        all_dfs.append(df)
        sys.stdout.write(f"  ✓ {sym:<15} {len(df)} levels\n")
    else:
        sys.stdout.write(f"  ✗ {sym:<15}\n")
    sys.stdout.flush()

combined = pd.concat(all_dfs, ignore_index=True)
N = len(combined)
print(f"\nВсего уровней: {N}\n")

# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 1: Reach rate по dist_in_atr бинам для каждого источника
# ─────────────────────────────────────────────────────────────────────

ATR_BINS = [(0.0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 99)]
ATR_LABELS = ["<0.5R", "0.5-1R", "1-1.5R", "1.5-2R", "2-3R", "3-5R", ">5R"]

sources = ["std_r1", "std_r2", "pdh", "pwh", "psycho", "vp_poc", "vp_vah", "fvg_4h", "fvg_1h"]

print("=" * 110)
print("REACH RATE по дистанции в ATR (реальные R-множители от entry)")
print(f"  {'':>10}", end="")
for lbl in ATR_LABELS:
    print(f"  {lbl:>12}", end="")
print()
print("-" * 110)

for src in sources:
    sub = combined[combined["name"] == src]
    if len(sub) < 20:
        continue
    print(f"  {src:<10}", end="")
    for (lo_r, hi_r), lbl in zip(ATR_BINS, ATR_LABELS):
        band = sub[(sub["dist_atr"] >= lo_r) & (sub["dist_atr"] < hi_r)]
        if len(band) < 10:
            print(f"  {'  -':>12}", end="")
        else:
            r = band["reached"].mean() * 100
            n = len(band)
            print(f"  {r:>8.0f}%({n:4})", end="")
    print()

# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 2: Decay для FVG (новые vs старые)
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 80)
print("FVG DECAY: Reach rate по возрасту FVG (в барах TF)")
print()

for fvg_name in ["fvg_4h", "fvg_1h"]:
    sub = combined[combined["name"] == fvg_name].dropna(subset=["age_bars"])
    if len(sub) < 20:
        continue
    print(f"  {fvg_name}:")
    age_bins = [(0, 5), (5, 15), (15, 30), (30, 60), (60, 200)]
    age_labels = ["0-5 bars", "5-15", "15-30", "30-60", "60+"]
    for (lo_a, hi_a), lbl in zip(age_bins, age_labels):
        band = sub[(sub["age_bars"] >= lo_a) & (sub["age_bars"] < hi_a)]
        if len(band) < 5:
            continue
        reach = band["reached"].mean() * 100
        avg_dist = band["dist_atr"].mean()
        print(f"    {lbl:<12}: Reach={reach:>5.1f}%, dist_atr={avg_dist:.2f}R, n={len(band)}")
    print()

# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 3: Лучшие источники при "реальном" TP (dist_atr 1.5-3R)
# ─────────────────────────────────────────────────────────────────────

print("=" * 80)
print("РЕАЛЬНЫЙ TP ДИАПАЗОН (dist 1.5-3R от entry)")
print(f"  {'Источник':<12} {'N':>7}  {'Reach%':>8}  {'AvgDist_atr':>12}  {'Weight':>8}")
print("-" * 55)

real_tp = combined[(combined["dist_atr"] >= 1.5) & (combined["dist_atr"] < 3.0)]
for src in sources:
    sub = real_tp[real_tp["name"] == src]
    if len(sub) < 20:
        continue
    reach = sub["reached"].mean() * 100
    avg_dist = sub["dist_atr"].mean()
    avg_w = sub["weight"].mean()
    print(f"  {src:<12} {len(sub):>7}  {reach:>7.1f}%  {avg_dist:>11.2f}R  {avg_w:>8.1f}")

# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 4: ATR статистика по парам (масштаб задачи)
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 80)
print("ATR СТАТИСТИКА: насколько велик дневной ATR по парам")
print(f"  {'Пара':<15} {'AvgATR%':>9}  {'MedianATR%':>11}  {'MinATR%':>9}  {'MaxATR%':>9}")
print("-" * 60)

for sym_df in all_dfs:
    sym = sym_df["name"].iloc[0] if False else None  # нет символа в df

# Считаем ATR по combined
atr_stats = combined.groupby("name")["atr_pct"].mean()
# Лучше по парам — но у нас нет symbol column, пропустим
print("  (Среднее по всем парам)")
print(f"  AvgATR:    {combined['atr_pct'].mean():.2f}%")
print(f"  MedianATR: {combined['atr_pct'].median():.2f}%")
print(f"  5th pct:   {combined['atr_pct'].quantile(0.05):.2f}%")
print(f"  95th pct:  {combined['atr_pct'].quantile(0.95):.2f}%")

print()
print("=" * 80)
print("ИТОГ: Для реального TP в 1.5-3R от entry — лучший источник?")
best = real_tp.groupby("name").agg(n=("reached","count"), reach=("reached","mean")).reset_index()
best["reach_pct"] = best["reach"] * 100
best = best[best["n"] >= 50].sort_values("reach_pct", ascending=False)
print()
for _, row in best.iterrows():
    bar = "█" * int(row["reach_pct"] / 3)
    print(f"  {row['name']:<12} Reach={row['reach_pct']:.1f}%  n={row['n']}  {bar}")
