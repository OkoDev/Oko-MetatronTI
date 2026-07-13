# -*- coding: utf-8 -*-
"""
Сравнительный тест: Standard vs Camarilla vs Woodie пивоты.

Метрики:
1. Reach rate — как часто цена достигает уровня в следующие N баров
2. Overlap rate — как часто Camarilla/Woodie уровень дублирует Standard (±eps)
3. Unique hits — случаи когда Camarilla/Woodie достигается, Standard аналог НЕТ

Вывод: реальная добавленная ценность Camarilla/Woodie как TP магнитов.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path("E:/MTF BOT/CURSOR/crypto_volume_bot/data/history")
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
         "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"]
LOOKAHEAD_BARS_1H = 24   # 1 день вперёд на 1h данных
OVERLAP_EPS = 0.005       # ±0.5% для overlap


# ──────────────────────────────────────────────────────────────────
# Формулы пивотов
# ──────────────────────────────────────────────────────────────────

def standard_pivots(h, l, c):
    pp = (h + l + c) / 3
    r1 = 2 * pp - l
    r2 = pp + (h - l)
    r3 = pp + 2 * (h - l)
    s1 = 2 * pp - h
    s2 = pp - (h - l)
    s3 = pp - 2 * (h - l)
    return dict(std_pp=pp, std_r1=r1, std_r2=r2, std_r3=r3,
                std_s1=s1, std_s2=s2, std_s3=s3)


def camarilla_pivots(h, l, c):
    rng = h - l
    r3 = c + rng * 1.0
    r4 = c + rng * 1.5
    s3 = c - rng * 1.0
    s4 = c - rng * 1.5
    return dict(cam_r3=r3, cam_r4=r4, cam_s3=s3, cam_s4=s4)


def woodie_pivots(h, l, c):
    pp = (h + l + 2 * c) / 4
    r1 = 2 * pp - l
    r2 = pp + (h - l)
    s1 = 2 * pp - h
    s2 = pp - (h - l)
    return dict(woo_pp=pp, woo_r1=r1, woo_r2=r2, woo_s1=s1, woo_s2=s2)


# ──────────────────────────────────────────────────────────────────
# Загрузка данных и ресемплинг до 1D
# ──────────────────────────────────────────────────────────────────

def load_pair(symbol):
    p = BASE / "1h" / f"{symbol}.parquet"
    if not p.exists():
        return None, None
    df1h = pd.read_parquet(p)
    df1d = df1h.resample("1D").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum")
    ).dropna()
    return df1h, df1d


# ──────────────────────────────────────────────────────────────────
# Основной тест
# ──────────────────────────────────────────────────────────────────

def test_pair(symbol):
    df1h, df1d = load_pair(symbol)
    if df1h is None or len(df1d) < 10:
        return None

    results = []
    dates_1d = df1d.index
    dates_1h = df1h.index

    for i in range(2, len(dates_1d) - 1):
        # Вчерашняя свеча → считаем пивоты на сегодня
        prev = df1d.iloc[i - 1]
        h, l, c = prev["high"], prev["low"], prev["close"]

        std = standard_pivots(h, l, c)
        cam = camarilla_pivots(h, l, c)
        woo = woodie_pivots(h, l, c)

        # Сегодняшний диапазон (первые LOOKAHEAD_BARS_1H баров)
        today_start = dates_1d[i]
        today_end_idx = today_start + pd.Timedelta(hours=LOOKAHEAD_BARS_1H)
        mask = (dates_1h >= today_start) & (dates_1h < today_end_idx)
        bars = df1h[mask]
        if len(bars) < 4:
            continue

        day_high = bars["high"].max()
        day_low = bars["low"].min()
        open_price = bars["close"].iloc[0]

        row = dict(date=today_start, open=open_price,
                   day_high=day_high, day_low=day_low)
        row.update(std)
        row.update(cam)
        row.update(woo)

        # Reach: цена достигла уровня сверху (TP для LONG)
        for key in ["std_r1", "std_r2", "std_r3", "cam_r3", "cam_r4", "woo_pp", "woo_r1", "woo_r2"]:
            lvl = row[key]
            if lvl > open_price:  # уровень выше текущей цены → TP для LONG
                row[f"reach_{key}"] = int(day_high >= lvl)
                row[f"dist_pct_{key}"] = (lvl - open_price) / open_price * 100
            else:
                row[f"reach_{key}"] = None
                row[f"dist_pct_{key}"] = None

        # Reach: цена достигла уровня снизу (TP для SHORT)
        for key in ["std_s1", "std_s2", "std_s3", "cam_s3", "cam_s4", "woo_s1", "woo_s2"]:
            lvl = row[key]
            if lvl < open_price:  # уровень ниже → TP для SHORT
                row[f"reach_{key}"] = int(day_low <= lvl)
                row[f"dist_pct_{key}"] = (open_price - lvl) / open_price * 100
            else:
                row[f"reach_{key}"] = None
                row[f"dist_pct_{key}"] = None

        results.append(row)

    return pd.DataFrame(results)


# ──────────────────────────────────────────────────────────────────
# Overlap анализ
# ──────────────────────────────────────────────────────────────────

def overlap_rate(df, cam_key, std_keys):
    """Как часто Camarilla уровень ближе ±eps к любому стандартному."""
    overlap = 0
    total = 0
    for _, row in df.iterrows():
        cam_lvl = row.get(cam_key)
        if cam_lvl is None or pd.isna(cam_lvl):
            continue
        total += 1
        for sk in std_keys:
            std_lvl = row.get(sk)
            if std_lvl and not pd.isna(std_lvl):
                if abs(cam_lvl - std_lvl) / std_lvl <= OVERLAP_EPS:
                    overlap += 1
                    break
    return overlap / total if total > 0 else 0


# ──────────────────────────────────────────────────────────────────
# Запуск по всем парам
# ──────────────────────────────────────────────────────────────────

print(f"Pivot Comparison Test: Standard vs Camarilla vs Woodie")
print(f"Lookahead: {LOOKAHEAD_BARS_1H}h | Overlap eps: {OVERLAP_EPS*100:.1f}%")
print(f"Pairs: {', '.join(PAIRS)}\n")

all_dfs = []
for sym in PAIRS:
    df = test_pair(sym)
    if df is not None:
        df["symbol"] = sym
        all_dfs.append(df)
        sys.stdout.write(f"  {sym}: {len(df)} trading days\n")
    else:
        sys.stdout.write(f"  {sym}: NO DATA\n")

if not all_dfs:
    print("Нет данных!")
    sys.exit(1)

combined = pd.concat(all_dfs, ignore_index=True)
total_days = len(combined)
print(f"\nВсего: {total_days} торговых дней × {len(PAIRS)} пар\n")

# ──────────────────────────────────────────────────────────────────
# ТАБЛИЦА 1: Reach rates всех уровней
# ──────────────────────────────────────────────────────────────────

LONG_LEVELS = [
    ("Std R1",   "std_r1"),
    ("Std R2",   "std_r2"),
    ("Std R3",   "std_r3"),
    ("Cam R3",   "cam_r3"),
    ("Cam R4",   "cam_r4"),
    ("Woo PP",   "woo_pp"),
    ("Woo R1",   "woo_r1"),
    ("Woo R2",   "woo_r2"),
]

SHORT_LEVELS = [
    ("Std S1",   "std_s1"),
    ("Std S2",   "std_s2"),
    ("Std S3",   "std_s3"),
    ("Cam S3",   "cam_s3"),
    ("Cam S4",   "cam_s4"),
    ("Woo S1",   "woo_s1"),
    ("Woo S2",   "woo_s2"),
]

print("=" * 75)
print(f"{'LONG TP levels (above entry)':}")
print(f"  {'Уровень':<12} {'N':<7} {'Reach%':>8} {'AvgDist%':>10} {'Overlap%':>10}")
print("-" * 75)

for name, key in LONG_LEVELS:
    col = f"reach_{key}"
    dist_col = f"dist_pct_{key}"
    sub = combined[combined[col].notna()]
    n = len(sub)
    if n < 10:
        print(f"  {name:<12} n<10")
        continue
    reach_pct = sub[col].mean() * 100
    avg_dist = sub[dist_col].mean()
    # Overlap с другими уровнями из LONG_LEVELS
    others = [k for _, k in LONG_LEVELS if k != key and "cam" not in k and "woo" not in k]
    if "cam" in key or "woo" in key:
        ov = overlap_rate(combined, key, [k for _, k in LONG_LEVELS if "std" in k])
    else:
        ov = 0
    ov_str = f"{ov*100:>9.1f}%" if ov > 0 else "         -"
    print(f"  {name:<12} {n:<7} {reach_pct:>7.1f}% {avg_dist:>9.2f}% {ov_str}")

print()
print(f"{'SHORT TP levels (below entry)':}")
print(f"  {'Уровень':<12} {'N':<7} {'Reach%':>8} {'AvgDist%':>10} {'Overlap%':>10}")
print("-" * 75)

for name, key in SHORT_LEVELS:
    col = f"reach_{key}"
    dist_col = f"dist_pct_{key}"
    sub = combined[combined[col].notna()]
    n = len(sub)
    if n < 10:
        print(f"  {name:<12} n<10")
        continue
    reach_pct = sub[col].mean() * 100
    avg_dist = sub[dist_col].mean()
    if "cam" in key or "woo" in key:
        ov = overlap_rate(combined, key, [k for _, k in SHORT_LEVELS if "std" in k])
    else:
        ov = 0
    ov_str = f"{ov*100:>9.1f}%" if ov > 0 else "         -"
    print(f"  {name:<12} {n:<7} {reach_pct:>7.1f}% {avg_dist:>9.2f}% {ov_str}")

# ──────────────────────────────────────────────────────────────────
# ТАБЛИЦА 2: Unique hits (Camarilla/Woodie достигается, Standard НЕТ)
# ──────────────────────────────────────────────────────────────────

print()
print("=" * 75)
print("UNIQUE HITS — Camarilla/Woodie достигается, ближайший Standard НЕТ")
print(f"  {'Сравнение':<25} {'N cases':>9} {'Unique hit%':>12}")
print("-" * 75)

comparisons = [
    ("Cam R3 vs Std R1",  "cam_r3", "std_r1", "long"),
    ("Cam R4 vs Std R2",  "cam_r4", "std_r2", "long"),
    ("Cam S3 vs Std S1",  "cam_s3", "std_s1", "short"),
    ("Cam S4 vs Std S2",  "cam_s4", "std_s2", "short"),
    ("Woo R1 vs Std R1",  "woo_r1", "std_r1", "long"),
    ("Woo S1 vs Std S1",  "woo_s1", "std_s1", "short"),
]

for desc, cam_key, std_key, direction in comparisons:
    cam_reach = f"reach_{cam_key}"
    std_reach = f"reach_{std_key}"
    sub = combined[combined[cam_reach].notna() & combined[std_reach].notna()]
    if len(sub) < 10:
        continue
    # Unique: cam hit=1, std hit=0
    unique = sub[(sub[cam_reach] == 1) & (sub[std_reach] == 0)]
    n_total = len(sub)
    unique_pct = len(unique) / n_total * 100
    print(f"  {desc:<25} {n_total:>9} {unique_pct:>11.1f}%")

# ──────────────────────────────────────────────────────────────────
# ТАБЛИЦА 3: По дистанции — ближний vs дальний
# ──────────────────────────────────────────────────────────────────

print()
print("=" * 75)
print("ДИСТАНЦИЯ vs REACH (Standard R1/R2 vs Camarilla R3/R4)")
print(f"  {'Уровень':<12} {'<1%':>8} {'1-2%':>8} {'2-3%':>8} {'>3%':>8}")
print("-" * 75)

for name, key in [("Std R1","std_r1"),("Std R2","std_r2"),("Cam R3","cam_r3"),("Cam R4","cam_r4")]:
    rc = f"reach_{key}"
    dc = f"dist_pct_{key}"
    sub = combined[combined[rc].notna() & combined[dc].notna()]
    if len(sub) < 10:
        continue
    def reach_in_band(lo, hi):
        b = sub[(sub[dc] >= lo) & (sub[dc] < hi)]
        if len(b) < 3:
            return "  -"
        return f"{b[rc].mean()*100:5.0f}%"
    print(f"  {name:<12} {reach_in_band(0,1):>8} {reach_in_band(1,2):>8} {reach_in_band(2,3):>8} {reach_in_band(3,999):>8}")

print()
print("=" * 75)
print("ВЫВОД: Camarilla/Woodie добавляют реальную ценность если:")
print("  1. Reach rate ЗНАЧИТЕЛЬНО отличается от Standard аналога")
print("  2. Overlap% < 20% (не дублируют стандартные уровни)")
print("  3. Unique hits% > 15% (есть случаи когда только они работают)")
print()
