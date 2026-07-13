# -*- coding: utf-8 -*-
"""
Оптимизация alpha для scoring = gravity / dist_pct^alpha.

Для каждого дня сохраняем ВСЕ кластеры (не только лучший).
Тестируем: какой alpha даёт максимальный reach rate при выборе
кластера с max score=gravity/dist^alpha?

Также тестируем: min_dist filter (не брать TP ближе N%),
max_dist filter (не брать TP дальше M%).
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
CLUSTER_EPS = 0.005
VP_LOOKBACK_H = 480
VP_BINS = 100
VA_PCT = 0.70


def standard_pivots(h, l, c):
    pp = (h + l + c) / 3
    return [
        (2*pp - l, 3, "std_r1"),
        (pp + (h-l), 2, "std_r2"),
    ]


def compute_vp(bars):
    hi_arr, lo_arr, vol_arr = bars["high"].values, bars["low"].values, bars["volume"].values
    hi, lo = hi_arr.max(), lo_arr.min()
    if hi <= lo or vol_arr.sum() == 0:
        return None, None
    bins = np.linspace(lo, hi, VP_BINS + 1)
    vol_profile = np.zeros(VP_BINS)
    for b in range(VP_BINS):
        overlap = np.minimum(hi_arr, bins[b+1]) - np.maximum(lo_arr, bins[b])
        overlap = np.maximum(overlap, 0)
        bar_range = np.maximum(hi_arr - lo_arr, 1e-9)
        vol_profile[b] = (vol_arr * overlap / bar_range).sum()
    poc_idx = np.argmax(vol_profile)
    poc = (bins[poc_idx] + bins[poc_idx+1]) / 2
    total_vol = vol_profile.sum()
    target = total_vol * VA_PCT
    lo_idx = hi_idx = poc_idx
    acc = vol_profile[poc_idx]
    while acc < target:
        up = hi_idx + 1 < VP_BINS
        dn = lo_idx - 1 >= 0
        if not up and not dn:
            break
        if (vol_profile[hi_idx+1] if up else -1) >= (vol_profile[lo_idx-1] if dn else -1):
            hi_idx += 1; acc += vol_profile[hi_idx]
        else:
            lo_idx -= 1; acc += vol_profile[lo_idx]
    vah = (bins[hi_idx] + bins[hi_idx+1]) / 2
    return poc, vah


def find_bear_fvg_active(H, L, C, cur, lookback=200):
    entry = C[cur]
    out = []
    for i in range(max(2, cur-lookback), cur):
        if H[i] < L[i-2]:
            mid = (H[i] + L[i-2]) / 2
            if mid <= entry:
                continue
            if H[i+1:cur+1].max() >= H[i]:
                continue
            out.append(mid)
    return out


def psycho_levels_up(price, n=6):
    mag = 10 ** int(np.log10(price))
    steps = [mag, mag/2, mag/5, mag/10]
    levels = set()
    for step in steps:
        above = np.ceil(price / step) * step
        if above > price * 1.001:
            levels.add(round(above, 8))
    return sorted(levels)[:n]


def cluster_levels(raw, eps=CLUSTER_EPS):
    if not raw:
        return []
    raw = sorted(raw, key=lambda x: x[0])
    clusters = []
    group = [raw[0]]
    for item in raw[1:]:
        if abs(item[0] - group[0][0]) / group[0][0] <= eps:
            group.append(item)
        else:
            w_sum = sum(x[1] for x in group)
            center = sum(x[0]*x[1] for x in group) / w_sum
            clusters.append((center, w_sum, len(set(x[2] for x in group))))
            group = [item]
    w_sum = sum(x[1] for x in group)
    center = sum(x[0]*x[1] for x in group) / w_sum
    clusters.append((center, w_sum, len(set(x[2] for x in group))))
    return clusters


def test_pair(symbol):
    p = BASE / "1h" / f"{symbol}.parquet"
    if not p.exists():
        return None
    df1h = pd.read_parquet(p)
    df1d = df1h.resample("1D").agg(high=("high","max"), low=("low","min"),
                                    close=("close","last"), volume=("volume","sum")).dropna()
    df1w = df1h.resample("W-MON").agg(high=("high","max")).dropna()

    H1 = df1h["high"].values
    L1 = df1h["low"].values
    C1 = df1h["close"].values
    dates_1h = df1h.index
    dates_1d = df1d.index

    all_clusters = []  # список всех кластеров всех дней

    for i_d in range(VP_LOOKBACK_H//24 + 2, len(dates_1d) - 2):
        today_ts = dates_1d[i_d]
        prev_d = df1d.iloc[i_d - 1]

        i_1h = np.searchsorted(dates_1h, today_ts)
        if i_1h >= len(H1) - LOOKAHEAD_H - 5:
            continue

        entry = C1[i_1h]
        future_high = H1[i_1h+1:i_1h+LOOKAHEAD_H+1].max()

        # Собираем уровни выше entry
        raw = []

        # Пивоты
        for lvl, w, name in standard_pivots(prev_d["high"], prev_d["low"], prev_d["close"]):
            if entry*1.001 < lvl < entry*1.15:
                raw.append((lvl, w, name))

        # PDH
        pdh = prev_d["high"]
        if entry*1.001 < pdh < entry*1.15:
            raw.append((pdh, 3, "pdh"))

        # PWH
        pw_mask = df1w.index < today_ts
        if pw_mask.sum() >= 1:
            pwh = df1w[pw_mask]["high"].iloc[-1]
            if entry*1.001 < pwh < entry*1.15:
                raw.append((pwh, 4, "pwh"))

        # Psycho
        for lvl in psycho_levels_up(entry, 5):
            if lvl < entry*1.15:
                raw.append((lvl, 2, "psycho"))

        # VP
        vp_bars = df1h[dates_1h < today_ts].iloc[-VP_LOOKBACK_H:]
        if len(vp_bars) >= 48:
            poc, vah = compute_vp(vp_bars)
            if poc and entry*1.001 < poc < entry*1.15:
                raw.append((poc, 3, "vp_poc"))
            if vah and entry*1.001 < vah < entry*1.15:
                raw.append((vah, 2, "vp_vah"))

        # FVG 4h
        step4 = i_1h // 4
        if step4 > 10:
            H4 = H1[::4][:step4+1]
            L4 = L1[::4][:step4+1]
            C4 = C1[::4][:step4+1]
            for mid in find_bear_fvg_active(H4, L4, C4, len(C4)-1, 50):
                if mid < entry*1.15:
                    raw.append((mid, 3, "fvg_4h"))

        # FVG 1h
        for mid in find_bear_fvg_active(H1, L1, C1, i_1h, 200):
            if mid < entry*1.15:
                raw.append((mid, 2, "fvg_1h"))

        if not raw:
            continue

        clusters = cluster_levels(raw)
        clusters_above = [(c, w, ns) for c, w, ns in clusters if c > entry]
        if not clusters_above:
            continue

        for center, gravity, n_src in clusters_above:
            dist_pct = (center - entry) / entry * 100
            if dist_pct <= 0 or dist_pct > 15:
                continue
            reached = int(future_high >= center)
            all_clusters.append(dict(
                entry=entry, center=center, gravity=gravity,
                dist_pct=dist_pct, n_src=n_src, reached=reached,
            ))

    return pd.DataFrame(all_clusters) if all_clusters else None


# ─────────────────────────────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────────────────────────────

print("=" * 80)
print("GRAVITY ALPHA OPTIMIZER — score = gravity / dist_pct^alpha")
print("=" * 80)

all_dfs = []
for sym in PAIRS:
    df = test_pair(sym)
    if df is not None and len(df) > 0:
        all_dfs.append(df)
        sys.stdout.write(f"  ✓ {sym:<15} {len(df)} clusters\n")
    else:
        sys.stdout.write(f"  ✗ {sym:<15}\n")
    sys.stdout.flush()

if not all_dfs:
    sys.exit(1)

# Объединяем все кластеры всех дней и пар
all_clusters = pd.concat(all_dfs, ignore_index=True)
print(f"\nВсего кластеров: {len(all_clusters)}")
print(f"Средняя gravity: {all_clusters['gravity'].mean():.2f}")
print(f"Средняя dist: {all_clusters['dist_pct'].mean():.2f}%")
print(f"Общий reach rate: {all_clusters['reached'].mean()*100:.1f}%\n")


# ─────────────────────────────────────────────────────────────────────
# Симуляция: для каждого дня выбираем кластер по разным scoring
# ─────────────────────────────────────────────────────────────────────
# Нам нужно группировать по (day × pair), но у нас нет этих ключей.
# Используем другой подход: считаем conditional reach rate
# при условии gravity/dist^alpha > threshold.

print("=" * 80)
print("ALPHA CALIBRATION: reach rate при выборе кластеров с max score")
print()

# Подход: для каждого alpha считаем корреляцию score с reached
alphas = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]

print(f"  {'alpha':>6}  {'corr(score,reached)':>20}  {'top25%_reach':>14}  {'top10%_reach':>14}")
print("-" * 65)

df = all_clusters.copy()
for alpha in alphas:
    if alpha == 0:
        df["score"] = df["gravity"]
    else:
        df["score"] = df["gravity"] / (df["dist_pct"] ** alpha)

    corr = df["score"].corr(df["reached"])

    # Reach для топ-25% score
    q75 = df["score"].quantile(0.75)
    top25 = df[df["score"] >= q75]["reached"].mean() * 100

    # Reach для топ-10% score
    q90 = df["score"].quantile(0.90)
    top10 = df[df["score"] >= q90]["reached"].mean() * 100

    print(f"  {alpha:>6.2f}  {corr:>20.4f}  {top25:>13.1f}%  {top10:>13.1f}%")


# ─────────────────────────────────────────────────────────────────────
# Оптимальный alpha — детальная таблица reach vs gravity × dist bins
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 80)
print("REACH BY SCORE QUANTILE (alpha=1.5): gravity / dist^1.5")
df["score_15"] = df["gravity"] / (df["dist_pct"] ** 1.5)

quantile_bins = [0, 0.25, 0.5, 0.75, 0.9, 1.0]
labels_q = ["bottom 25%", "25-50%", "50-75%", "75-90%", "top 10%"]

print(f"\n  {'Quantile':>12}  {'N':>7}  {'Reach%':>8}  {'AvgDist%':>10}  {'AvgGravity':>12}")
print("-" * 60)
for i in range(len(quantile_bins)-1):
    lo_q = df["score_15"].quantile(quantile_bins[i])
    hi_q = df["score_15"].quantile(quantile_bins[i+1])
    sub = df[(df["score_15"] >= lo_q) & (df["score_15"] < hi_q)]
    if len(sub) < 10:
        continue
    reach = sub["reached"].mean() * 100
    avg_dist = sub["dist_pct"].mean()
    avg_g = sub["gravity"].mean()
    print(f"  {labels_q[i]:>12}  {len(sub):>7}  {reach:>7.1f}%  {avg_dist:>9.2f}%  {avg_g:>11.2f}")


# ─────────────────────────────────────────────────────────────────────
# Фильтры дистанции
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 80)
print("DISTANCE FILTERS: reach rate при ограничении max_dist")
print(f"\n  {'max_dist':>9}  {'N':>7}  {'Reach%':>8}  {'Coverage':>10}")
print("-" * 45)

total_n = len(df)
for max_d in [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0]:
    sub = df[df["dist_pct"] <= max_d]
    if len(sub) < 10:
        continue
    reach = sub["reached"].mean() * 100
    coverage = len(sub) / total_n * 100
    print(f"  {max_d:>9.1f}  {len(sub):>7}  {reach:>7.1f}%  {coverage:>9.1f}%")


# ─────────────────────────────────────────────────────────────────────
# Итог: рекомендуемые параметры TPSelector
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 80)
print("РЕКОМЕНДАЦИИ для TPSelector.select_tp():")
print()

# Оптимальный alpha
best_alpha = 1.5
df["score_best"] = df["gravity"] / (df["dist_pct"] ** best_alpha)
corr_best = df["score_best"].corr(df["reached"])
q90 = df["score_best"].quantile(0.90)
top10_reach = df[df["score_best"] >= q90]["reached"].mean() * 100

print(f"  score = gravity / dist_pct^{best_alpha}")
print(f"  corr(score, reached) = {corr_best:.4f}")
print(f"  Top 10% score clusters: reach = {top10_reach:.1f}%")
print()
print("  Фильтры:")

# Минимальный score порог для выбора TP
for score_thresh in [0.5, 1.0, 1.5, 2.0, 3.0]:
    sub = df[df["score_best"] >= score_thresh]
    if len(sub) < 10:
        continue
    reach = sub["reached"].mean() * 100
    cov = len(sub) / total_n * 100
    print(f"    min_score={score_thresh:.1f}: reach={reach:.1f}%, coverage={cov:.0f}%")

print()
print("  Выбор TP: argmax(score) при score >= min_score")
print("  Fallback: std_r1 если нет кластеров с достаточной гравитацией")
