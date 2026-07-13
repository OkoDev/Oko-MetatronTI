# -*- coding: utf-8 -*-
"""
Gravity Cluster Test — ARCH-113 TPSelector.

Правильная метрика: не "ближайший уровень", а СИЛЬНЕЙШИЙ КЛАСТЕР.

Концепция:
  Для каждого дня собираем ВСЕ уровни выше entry (LONG TP кандидаты).
  Кластеризуем в ±EPS% окна.
  Считаем gravity_score = sum(weights) для каждого кластера.
  Тестируем: reach_rate vs gravity_score.

Гипотеза: кластер с gravity>=6 достигается значительно чаще (>60%),
чем одиночный уровень (30-40%).

Уровни и веса (рабочая гипотеза):
  Std R1 1D        weight=3  (стандартный пивот)
  Std R2 1D        weight=2
  PDH              weight=3  (prev day liquidity)
  PWH              weight=4  (prev week liquidity, HTF)
  Psycho level     weight=2  (round number)
  VP POC           weight=2  (volume concentration)
  VP VAH           weight=2  (value area top)
  Bear FVG mid 4h  weight=3  (из предыдущего теста: 50% reach)
  Bear FVG mid 1h  weight=2
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

LOOKAHEAD_H = 48      # 2 дня вперёд (больше времени для достижения)
CLUSTER_EPS = 0.005   # ±0.5% кластеризация
VP_LOOKBACK_H = 480   # 20 дней
VP_BINS = 100
VA_PCT = 0.70
FVG_LOOKBACK_BARS = 200  # сколько баров назад ищем FVG


# ─────────────────────────────────────────────────────────────────────
# Пивоты
# ─────────────────────────────────────────────────────────────────────

def standard_pivots(h, l, c):
    pp = (h + l + c) / 3
    return {"std_r1": (2 * pp - l, 3), "std_r2": (pp + (h - l), 2),
            "std_s1": (2 * pp - h, 3), "std_s2": (pp - (h - l), 2)}


# ─────────────────────────────────────────────────────────────────────
# Volume Profile (vectorized)
# ─────────────────────────────────────────────────────────────────────

def compute_vp(bars, n_bins=VP_BINS, va_pct=VA_PCT):
    hi_arr = bars["high"].values
    lo_arr = bars["low"].values
    vol_arr = bars["volume"].values
    hi, lo = hi_arr.max(), lo_arr.min()
    if hi <= lo or vol_arr.sum() == 0:
        return None, None, None
    bins = np.linspace(lo, hi, n_bins + 1)
    vol_profile = np.zeros(n_bins)
    for b in range(n_bins):
        overlap = np.minimum(hi_arr, bins[b+1]) - np.maximum(lo_arr, bins[b])
        overlap = np.maximum(overlap, 0)
        bar_range = np.maximum(hi_arr - lo_arr, 1e-9)
        vol_profile[b] = (vol_arr * overlap / bar_range).sum()
    poc_idx = np.argmax(vol_profile)
    poc = (bins[poc_idx] + bins[poc_idx+1]) / 2
    total_vol = vol_profile.sum()
    target = total_vol * va_pct
    lo_idx = hi_idx = poc_idx
    accumulated = vol_profile[poc_idx]
    while accumulated < target:
        up = hi_idx + 1 < n_bins
        dn = lo_idx - 1 >= 0
        if not up and not dn:
            break
        vol_up = vol_profile[hi_idx+1] if up else -1
        vol_dn = vol_profile[lo_idx-1] if dn else -1
        if vol_up >= vol_dn:
            hi_idx += 1; accumulated += vol_profile[hi_idx]
        else:
            lo_idx -= 1; accumulated += vol_profile[lo_idx]
    vah = (bins[hi_idx] + bins[hi_idx+1]) / 2
    val = (bins[lo_idx] + bins[lo_idx+1]) / 2
    return poc, vah, val


# ─────────────────────────────────────────────────────────────────────
# FVG детектор
# ─────────────────────────────────────────────────────────────────────

def find_active_fvg(highs, lows, closes, current_bar, lookback=FVG_LOOKBACK_BARS):
    """Возвращает активные (незаполненные) Bear FVG midpoints выше closes[current_bar]."""
    entry = closes[current_bar]
    results = []
    start = max(2, current_bar - lookback)
    for i in range(start, current_bar):
        if highs[i] < lows[i-2]:  # Bear FVG: gap above
            bot, top = highs[i], lows[i-2]
            mid = (bot + top) / 2
            if mid <= entry:
                continue
            # Проверяем не заполнен ли (high после i не зашёл в gap)
            max_high_after = highs[i+1:current_bar+1].max() if i+1 <= current_bar else 0
            if max_high_after >= bot:  # Заполнен
                continue
            results.append(mid)
    return results  # midpoints незаполненных Bear FVG выше entry


def find_active_bull_fvg(highs, lows, closes, current_bar, lookback=FVG_LOOKBACK_BARS):
    """Активные Bull FVG midpoints НИЖЕ closes[current_bar] (SHORT TP)."""
    entry = closes[current_bar]
    results = []
    start = max(2, current_bar - lookback)
    for i in range(start, current_bar):
        if lows[i] > highs[i-2]:  # Bull FVG: gap below
            bot, top = highs[i-2], lows[i]
            mid = (bot + top) / 2
            if mid >= entry:
                continue
            min_low_after = lows[i+1:current_bar+1].min() if i+1 <= current_bar else 9e9
            if min_low_after <= top:
                continue
            results.append(mid)
    return results


# ─────────────────────────────────────────────────────────────────────
# Психологические уровни
# ─────────────────────────────────────────────────────────────────────

def psycho_levels(price, direction="up", n=8):
    mag = 10 ** int(np.log10(price))
    steps = [mag, mag/2, mag/5, mag/10, mag/20]
    levels = set()
    for step in steps:
        for k in range(-3, 20):
            lvl = round(round(price / step + k) * step, 8)
            if direction == "up" and lvl > price * 1.001:
                levels.add(lvl)
            elif direction == "dn" and lvl < price * 0.999:
                levels.add(lvl)
    if direction == "up":
        return sorted(levels)[:n]
    return sorted(levels, reverse=True)[:n]


# ─────────────────────────────────────────────────────────────────────
# Кластеризация уровней
# ─────────────────────────────────────────────────────────────────────

def cluster_levels(levels_with_weights, eps=CLUSTER_EPS):
    """
    levels_with_weights: list of (price, weight, name)
    Возвращает список кластеров: (center_price, total_weight, [sources])
    """
    if not levels_with_weights:
        return []
    lvls = sorted(levels_with_weights, key=lambda x: x[0])
    clusters = []
    cur_group = [lvls[0]]

    for item in lvls[1:]:
        ref = cur_group[0][0]
        if abs(item[0] - ref) / ref <= eps:
            cur_group.append(item)
        else:
            center = sum(x[0] * x[1] for x in cur_group) / sum(x[1] for x in cur_group)
            total_w = sum(x[1] for x in cur_group)
            sources = [x[2] for x in cur_group]
            clusters.append((center, total_w, sources))
            cur_group = [item]

    center = sum(x[0] * x[1] for x in cur_group) / sum(x[1] for x in cur_group)
    total_w = sum(x[1] for x in cur_group)
    sources = [x[2] for x in cur_group]
    clusters.append((center, total_w, sources))
    return clusters


# ─────────────────────────────────────────────────────────────────────
# Тест одной пары
# ─────────────────────────────────────────────────────────────────────

def test_pair(symbol):
    p = BASE / "1h" / f"{symbol}.parquet"
    if not p.exists():
        return None

    df1h = pd.read_parquet(p)
    df1d = df1h.resample("1D").agg(
        high=("high","max"), low=("low","min"),
        close=("close","last"), volume=("volume","sum")
    ).dropna()
    df1w = df1h.resample("W-MON").agg(
        high=("high","max"), low=("low","min"), close=("close","last")
    ).dropna()

    H1 = df1h["high"].values
    L1 = df1h["low"].values
    C1 = df1h["close"].values
    dates_1h = df1h.index
    dates_1d = df1d.index

    # EMA200 daily
    ema200 = df1d["close"].ewm(span=200, adjust=False).mean().values

    results = []

    for i_d in range(VP_LOOKBACK_H // 24 + 2, len(dates_1d) - 2):
        today_ts = dates_1d[i_d]
        prev_d = df1d.iloc[i_d - 1]
        prev2_d = df1d.iloc[i_d - 2]

        # Найти текущий бар в 1h
        i_1h = np.searchsorted(dates_1h, today_ts)
        if i_1h >= len(dates_1h) - LOOKAHEAD_H - 5:
            continue

        entry = C1[i_1h]
        future_high = H1[i_1h+1:i_1h+LOOKAHEAD_H+1].max() if i_1h+1 < len(H1) else 0
        future_low  = L1[i_1h+1:i_1h+LOOKAHEAD_H+1].min() if i_1h+1 < len(L1) else 9e9

        # ── Собираем все уровни ВЫШЕ entry (LONG TP) ──
        long_levels = []

        # Стандартные пивоты
        std = standard_pivots(prev_d["high"], prev_d["low"], prev_d["close"])
        for name, (lvl, w) in std.items():
            if lvl > entry * 1.001 and lvl < entry * 1.15:
                long_levels.append((lvl, w, name))

        # PDH (weight=3)
        pdh = prev_d["high"]
        if pdh > entry * 1.001 and pdh < entry * 1.15:
            long_levels.append((pdh, 3, "pdh"))

        # PWH (weight=4)
        prev_week_mask = df1w.index < today_ts
        if prev_week_mask.sum() >= 1:
            pwh = df1w[prev_week_mask]["high"].iloc[-1]
            if pwh > entry * 1.001 and pwh < entry * 1.15:
                long_levels.append((pwh, 4, "pwh"))

        # Психологические уровни (weight=2)
        for lvl in psycho_levels(entry, "up", 5):
            if lvl < entry * 1.15:
                long_levels.append((lvl, 2, "psycho"))

        # VP VAH (weight=2)
        vp_bars = df1h[dates_1h < today_ts].iloc[-VP_LOOKBACK_H:]
        if len(vp_bars) >= 48:
            poc, vah, val = compute_vp(vp_bars)
            if vah and vah > entry * 1.001 and vah < entry * 1.15:
                long_levels.append((vah, 2, "vp_vah"))
            if poc and poc > entry * 1.001 and poc < entry * 1.15:
                long_levels.append((poc, 3, "vp_poc"))  # POC весит больше

        # Bear FVG midpoints (weight по TF: 4h→3, 1h→2)
        # 4h FVG из 1h данных (каждые 4 бара)
        step4 = i_1h // 4
        if step4 > 10:
            H4 = H1[::4][:step4+1]
            L4 = L1[::4][:step4+1]
            C4 = C1[::4][:step4+1]
            for mid in find_active_fvg(H4, L4, C4, len(C4)-1, 50):
                if mid < entry * 1.15:
                    long_levels.append((mid, 3, "bear_fvg_4h"))

        # 1h FVG
        for mid in find_active_fvg(H1, L1, C1, i_1h, 200):
            if mid < entry * 1.15:
                long_levels.append((mid, 2, "bear_fvg_1h"))

        if not long_levels:
            continue

        # ── Кластеризация ──
        clusters = cluster_levels(long_levels, CLUSTER_EPS)
        clusters_above = [(c, w, s) for c, w, s in clusters if c > entry]
        if not clusters_above:
            continue

        # Лучший кластер = максимальная гравитация
        best = max(clusters_above, key=lambda x: x[1])
        best_center, best_gravity, best_sources = best

        dist_pct = (best_center - entry) / entry * 100
        reached = int(future_high >= best_center)
        n_sources = len(set(best_sources))

        results.append(dict(
            symbol=symbol,
            date=today_ts,
            entry=entry,
            best_gravity=best_gravity,
            best_dist_pct=dist_pct,
            reached=reached,
            n_sources=n_sources,
            n_clusters=len(clusters_above),
            sources_str="|".join(sorted(set(best_sources))),
        ))

    return pd.DataFrame(results) if results else None


# ─────────────────────────────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────────────────────────────

print("=" * 80)
print("GRAVITY CLUSTER TEST — ARCH-113 TPSelector")
print(f"Lookahead: {LOOKAHEAD_H}h | Cluster EPS: {CLUSTER_EPS*100:.1f}% | Pairs: {len(PAIRS)}")
print("=" * 80)

all_dfs = []
for sym in PAIRS:
    df = test_pair(sym)
    if df is not None and len(df) > 0:
        all_dfs.append(df)
        sys.stdout.write(f"  ✓ {sym:<15} {len(df)} days\n")
    else:
        sys.stdout.write(f"  ✗ {sym:<15} no data\n")
    sys.stdout.flush()

if not all_dfs:
    print("Нет данных!")
    sys.exit(1)

combined = pd.concat(all_dfs, ignore_index=True)
N = len(combined)
print(f"\nВсего: {N} торговых дней × {len(all_dfs)} пар\n")


# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 1: Reach rate по гравитации кластера
# ─────────────────────────────────────────────────────────────────────

print("=" * 80)
print("КЛЮЧЕВОЙ ВОПРОС: Reach rate выбранного TP по силе гравитации")
print("(Всегда берём кластер с максимальной гравитацией)")
print(f"\n  {'Gravity':>9}  {'N':>6}  {'Reach%':>8}  {'AvgDist%':>10}  {'AvgSources':>12}")
print("-" * 60)

gravity_bins = [(1, 2), (2, 3), (3, 5), (5, 7), (7, 10), (10, 99)]
labels = ["=1 (solo)", "2-3", "3-5", "5-7", "7-10", "10+"]

for (lo, hi), label in zip(gravity_bins, labels):
    sub = combined[(combined["best_gravity"] >= lo) & (combined["best_gravity"] < hi)]
    if len(sub) < 10:
        print(f"  Gravity {label:<10}  n<10")
        continue
    reach = sub["reached"].mean() * 100
    avg_dist = sub["best_dist_pct"].mean()
    avg_src = sub["n_sources"].mean()
    bar = "█" * int(reach / 3)
    print(f"  Gravity {label:<10}  {len(sub):>6}  {reach:>7.1f}%  {avg_dist:>9.2f}%  {avg_src:>11.1f}  {bar}")


# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 2: По числу источников в кластере
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 80)
print("CONFLUENCE: Reach rate по числу ИСТОЧНИКОВ в лучшем кластере")
print(f"\n  {'N sources':>10}  {'N':>6}  {'Reach%':>8}  {'AvgDist%':>10}")
print("-" * 50)

for n_src in sorted(combined["n_sources"].unique()):
    sub = combined[combined["n_sources"] == n_src]
    if len(sub) < 10:
        continue
    reach = sub["reached"].mean() * 100
    avg_dist = sub["best_dist_pct"].mean()
    bar = "█" * int(reach / 3)
    print(f"  {n_src:>10}  {len(sub):>6}  {reach:>7.1f}%  {avg_dist:>9.2f}%  {bar}")


# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 3: Какие комбинации источников дают лучший reach?
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 80)
print("ТОП КОМБИНАЦИИ источников в кластере (min 50 cases)")
print(f"\n  {'Источники':<35}  {'N':>6}  {'Reach%':>8}  {'AvgDist%':>10}")
print("-" * 65)

combos = combined.groupby("sources_str").agg(
    n=("reached", "count"),
    reach=("reached", "mean"),
    avg_dist=("best_dist_pct", "mean")
).reset_index()
combos["reach_pct"] = combos["reach"] * 100
combos = combos[combos["n"] >= 50].sort_values("reach_pct", ascending=False)

for _, row in combos.head(20).iterrows():
    src = row["sources_str"][:35]
    print(f"  {src:<35}  {row['n']:>6}  {row['reach_pct']:>7.1f}%  {row['avg_dist']:>9.2f}%")


# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 4: Гравитация vs дистанция (важно для веса в scoring)
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 80)
print("GRAVITY vs DISTANCE: reach rate по ячейкам (gravity × dist%)")
print(f"\n  {'':>12}", end="")
dist_bands = [(0, 2), (2, 4), (4, 7), (7, 15)]
for lo, hi in dist_bands:
    print(f"  dist {lo}-{hi}%", end="")
print()
print("-" * 70)

grav_bands = [(1, 3), (3, 6), (6, 10), (10, 99)]
grav_labels = ["G 1-3", "G 3-6", "G 6-10", "G 10+"]

for (glo, ghi), glabel in zip(grav_bands, grav_labels):
    sub_g = combined[(combined["best_gravity"] >= glo) & (combined["best_gravity"] < ghi)]
    print(f"  {glabel:<12}", end="")
    for dlo, dhi in dist_bands:
        sub = sub_g[(sub_g["best_dist_pct"] >= dlo) & (sub_g["best_dist_pct"] < dhi)]
        if len(sub) < 10:
            print(f"  {'  -':>10}", end="")
        else:
            print(f"  {sub['reached'].mean()*100:>8.0f}%({len(sub)})", end="")
    print()


# ─────────────────────────────────────────────────────────────────────
# ИТОГ
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 80)
print("BASELINE COMPARISON: что было бы если бы выбирали не гравитацию, а ближайший?")
# Берём тот же combined но смотрим на ближайший кластер (min dist) vs max gravity
combined_sorted = combined.copy()

# Для сравнения: берём все кластеры и пересчитываем для "ближайший"
# (у нас нет данных о НЕ-лучшем кластере в записи, так что используем
#  корреляцию гравитации с дистанцией как прокси)

print(f"\n  Стратегия max_gravity:  Reach={combined['reached'].mean()*100:.1f}%  "
      f"AvgDist={combined['best_dist_pct'].mean():.2f}%  N={len(combined)}")

# Solo уровни (gravity=1) как прокси "просто ближайший"
solo = combined[combined["best_gravity"] <= 2]
multi = combined[combined["best_gravity"] > 5]
print(f"  Solo (gravity<=2):       Reach={solo['reached'].mean()*100:.1f}%  "
      f"AvgDist={solo['best_dist_pct'].mean():.2f}%  N={len(solo)}")
print(f"  Strong (gravity>5):      Reach={multi['reached'].mean()*100:.1f}%  "
      f"AvgDist={multi['best_dist_pct'].mean():.2f}%  N={len(multi)}")

print()
print("ВЫВОД: Gravity scoring работает если Reach(strong) >> Reach(solo)")
print("Идеальный разрыв: >15 процентных пунктов")
