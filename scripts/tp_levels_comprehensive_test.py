# -*- coding: utf-8 -*-
"""
Comprehensive TP Levels Test — ARCH-113 TPSelector research.

Тестируем все кандидаты для TP магнитных зон:
  A-уровень (данные есть):
    - PDH/PDL  — Previous Day High/Low (ликвидность)
    - PWH/PWL  — Previous Week High/Low
    - PMH/PML  — Previous Month High/Low
    - Psycho   — Round numbers (X.000, X.500, X.X00)
    - EMA200_1d — Moving average как динамический магнит
  B-уровень (считаем из OHLCV):
    - VP POC   — Volume Profile Point of Control (20d lookback)
    - VP VAH   — Value Area High (70% volume)
    - VP VAL   — Value Area Low
  Baseline (уже в системе):
    - Std R1/R2 1D — стандартные пивоты (benchmark)
    - FVG mid  — (из предыдущего теста: 4h=50%, 1h=59%)

Метрики:
  reach_rate — как часто цена достигает уровня в следующие LOOKAHEAD баров
  avg_dist%  — средняя дистанция от entry до уровня
  precision  — как часто этот уровень = БЛИЖАЙШИЙ сверху/снизу (лучший TP выбор)
  overlap%   — как часто дублирует baseline (Std R1/R2)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path("E:/MTF BOT/CURSOR/crypto_volume_bot/data/history")

# 30 пар — хорошая репрезентативная выборка
PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "AAVEUSDT", "ARBUSDT", "ATOMUSDT", "APTUSDT", "CRVUSDT",
    "ENAUSDT", "INJUSDT", "LTCUSDT", "MATICUSDT", "NEARUSDT",
    "OPUSDT", "SHIBUSDT", "SUIUSDT", "TIAUSDT", "TONUSDT",
    "TRXUSDT", "UNIUSDT", "WIFUSDT", "XMRUSDT", "ZRXUSDT",
]

LOOKAHEAD_H = 24       # 1 день вперёд
VP_LOOKBACK_D = 20     # Volume Profile: последние 20 торговых дней
VP_BINS = 100          # кол-во бинов
VA_PCT = 0.70          # Value Area = 70% объёма
OVERLAP_EPS = 0.005    # ±0.5% для overlap
MIN_DIST_PCT = 0.003   # минимальная дистанция (фильтр "уровень слишком близко")
MAX_DIST_PCT = 0.15    # максимальная дистанция (фильтр "уровень слишком далеко")


# ─────────────────────────────────────────────────────────────────────
# Пивоты (baseline)
# ─────────────────────────────────────────────────────────────────────

def standard_pivots(h, l, c):
    pp = (h + l + c) / 3
    return dict(
        std_pp=pp,
        std_r1=2 * pp - l,
        std_r2=pp + (h - l),
        std_s1=2 * pp - h,
        std_s2=pp - (h - l),
    )


# ─────────────────────────────────────────────────────────────────────
# EMA200 (дневная)
# ─────────────────────────────────────────────────────────────────────

def compute_ema200_daily(df1d):
    return df1d["close"].ewm(span=200, adjust=False).mean()


# ─────────────────────────────────────────────────────────────────────
# Психологические уровни
# ─────────────────────────────────────────────────────────────────────

def psycho_levels_near(price, n_up=5, n_down=5):
    """Ближайшие N психологических уровней выше и ниже price."""
    # Определяем шаг округления по порядку величины
    mag = 10 ** int(np.log10(price))
    steps = [mag, mag / 2, mag / 5, mag / 10]
    levels_up, levels_down = [], []
    for step in steps:
        # Ближайший уровень сверху
        above = np.ceil(price / step) * step
        if above > price * (1 + MIN_DIST_PCT):
            levels_up.append(round(above, 8))
        # Ближайший уровень снизу
        below = np.floor(price / step) * step
        if below < price * (1 - MIN_DIST_PCT):
            levels_down.append(round(below, 8))
    return sorted(set(levels_up)), sorted(set(levels_down), reverse=True)


# ─────────────────────────────────────────────────────────────────────
# Volume Profile
# ─────────────────────────────────────────────────────────────────────

def compute_vp(bars_1h, n_bins=VP_BINS, va_pct=VA_PCT):
    """
    Вычисляет VP POC/VAH/VAL по последним N барам.
    bars_1h: DataFrame с high/low/close/volume
    """
    if len(bars_1h) < 10:
        return None, None, None

    hi = bars_1h["high"].max()
    lo = bars_1h["low"].min()
    if hi <= lo:
        return None, None, None

    bins = np.linspace(lo, hi, n_bins + 1)
    vol_profile = np.zeros(n_bins)

    for _, row in bars_1h.iterrows():
        bar_lo, bar_hi, vol = row["low"], row["high"], row["volume"]
        # Распределяем объём равномерно по бинам которые пересекает бар
        for b in range(n_bins):
            bin_lo, bin_hi = bins[b], bins[b + 1]
            overlap = min(bar_hi, bin_hi) - max(bar_lo, bin_lo)
            if overlap > 0:
                bar_range = bar_hi - bar_lo if bar_hi > bar_lo else 1e-9
                vol_profile[b] += vol * overlap / bar_range

    if vol_profile.sum() == 0:
        return None, None, None

    # POC = бин с максимальным объёмом
    poc_idx = np.argmax(vol_profile)
    poc = (bins[poc_idx] + bins[poc_idx + 1]) / 2

    # Value Area: берём бины вокруг POC пока не наберём va_pct от total
    total_vol = vol_profile.sum()
    target = total_vol * va_pct
    included = {poc_idx}
    accumulated = vol_profile[poc_idx]

    lo_idx, hi_idx = poc_idx, poc_idx
    while accumulated < target:
        # Расширяемся в сторону большего объёма
        expand_up = hi_idx + 1 < n_bins
        expand_down = lo_idx - 1 >= 0
        if not expand_up and not expand_down:
            break
        vol_up = vol_profile[hi_idx + 1] if expand_up else -1
        vol_down = vol_profile[lo_idx - 1] if expand_down else -1
        if vol_up >= vol_down:
            hi_idx += 1
            accumulated += vol_profile[hi_idx]
        else:
            lo_idx -= 1
            accumulated += vol_profile[lo_idx]

    vah = (bins[hi_idx] + bins[hi_idx + 1]) / 2
    val = (bins[lo_idx] + bins[lo_idx + 1]) / 2
    return poc, vah, val


# ─────────────────────────────────────────────────────────────────────
# Загрузка пары
# ─────────────────────────────────────────────────────────────────────

def load_pair(symbol):
    p = BASE / "1h" / f"{symbol}.parquet"
    if not p.exists():
        return None, None, None

    df1h = pd.read_parquet(p)
    df1d = df1h.resample("1D").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum")
    ).dropna()
    df1w = df1h.resample("W-MON").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum")
    ).dropna()
    return df1h, df1d, df1w


# ─────────────────────────────────────────────────────────────────────
# Reach check
# ─────────────────────────────────────────────────────────────────────

def check_reached_above(day_high, level, entry):
    """Уровень выше entry — достигнут если day_high >= level."""
    if level <= entry * (1 + MIN_DIST_PCT):
        return None  # слишком близко или ниже
    if level > entry * (1 + MAX_DIST_PCT):
        return None  # слишком далеко
    return int(day_high >= level)


def check_reached_below(day_low, level, entry):
    """Уровень ниже entry — достигнут если day_low <= level."""
    if level >= entry * (1 - MIN_DIST_PCT):
        return None
    if level < entry * (1 - MAX_DIST_PCT):
        return None
    return int(day_low <= level)


# ─────────────────────────────────────────────────────────────────────
# Основной тест одной пары
# ─────────────────────────────────────────────────────────────────────

def test_pair(symbol):
    df1h, df1d, df1w = load_pair(symbol)
    if df1h is None or len(df1d) < VP_LOOKBACK_D + 5:
        return None

    ema200 = compute_ema200_daily(df1d)
    results = []
    dates_1d = df1d.index
    dates_1h = df1h.index

    for i in range(VP_LOOKBACK_D + 2, len(dates_1d) - 1):
        prev_d = df1d.iloc[i - 1]   # вчера
        prev2_d = df1d.iloc[i - 2]  # позавчера

        # Ищем прошлую неделю
        today_ts = dates_1d[i]
        prev_week_mask = df1w.index < today_ts
        if prev_week_mask.sum() < 2:
            continue
        prev_w = df1w[prev_week_mask].iloc[-1]
        prev2_w = df1w[prev_week_mask].iloc[-2]

        # Прошлый месяц
        prev_month_end = today_ts.replace(day=1) - pd.Timedelta(days=1)
        month_start = prev_month_end.replace(day=1)
        month_bars = df1d[(df1d.index >= month_start) & (df1d.index <= prev_month_end)]

        h1h_today = df1h[(dates_1h >= today_ts) &
                         (dates_1h < today_ts + pd.Timedelta(hours=LOOKAHEAD_H))]
        if len(h1h_today) < 4:
            continue

        entry = h1h_today["close"].iloc[0]
        day_high = h1h_today["high"].max()
        day_low = h1h_today["low"].min()

        # ── Стандартные пивоты (baseline) ──
        std = standard_pivots(prev_d["high"], prev_d["low"], prev_d["close"])

        # ── PDH/PDL ──
        pdh = prev_d["high"]
        pdl = prev_d["low"]

        # ── PWH/PWL ──
        pwh = prev_w["high"]
        pwl = prev_w["low"]

        # ── PMH/PML ──
        pmh = month_bars["high"].max() if len(month_bars) > 0 else None
        pml = month_bars["low"].min() if len(month_bars) > 0 else None

        # ── EMA200 ──
        ema = ema200.iloc[i - 1] if i - 1 < len(ema200) else None

        # ── Volume Profile (последние VP_LOOKBACK_D * 24 баров) ──
        vp_lookback_h = VP_LOOKBACK_D * 24
        vp_bars = df1h[dates_1h < today_ts].iloc[-vp_lookback_h:]
        poc, vah, val = compute_vp(vp_bars)

        # ── Psycho levels ──
        psycho_up, psycho_down = psycho_levels_near(entry)
        nearest_psycho_up = psycho_up[0] if psycho_up else None
        nearest_psycho_down = psycho_down[0] if psycho_down else None

        row = dict(
            symbol=symbol, date=today_ts,
            entry=entry, day_high=day_high, day_low=day_low,
            # Уровни
            std_r1=std["std_r1"], std_r2=std["std_r2"],
            std_s1=std["std_s1"], std_s2=std["std_s2"],
            pdh=pdh, pdl=pdl, pwh=pwh, pwl=pwl,
            pmh=pmh, pml=pml,
            ema200=ema,
            vp_poc=poc, vp_vah=vah, vp_val=val,
            psycho_up=nearest_psycho_up, psycho_down=nearest_psycho_down,
        )

        # ── Reach rates (LONG TP = выше entry) ──
        for key in ["std_r1", "std_r2", "pdh", "pwh", "pmh",
                    "ema200", "vp_vah", "vp_poc", "psycho_up"]:
            lvl = row.get(key)
            if lvl is not None and not (isinstance(lvl, float) and np.isnan(lvl)):
                row[f"reach_up_{key}"] = check_reached_above(day_high, lvl, entry)
                row[f"dist_up_{key}"] = (lvl - entry) / entry * 100 if row[f"reach_up_{key}"] is not None else None
            else:
                row[f"reach_up_{key}"] = None
                row[f"dist_up_{key}"] = None

        # ── Reach rates (SHORT TP = ниже entry) ──
        for key in ["std_s1", "std_s2", "pdl", "pwl", "pml",
                    "ema200", "vp_val", "vp_poc", "psycho_down"]:
            lvl = row.get(key)
            if lvl is not None and not (isinstance(lvl, float) and np.isnan(lvl)):
                row[f"reach_dn_{key}"] = check_reached_below(day_low, lvl, entry)
                row[f"dist_dn_{key}"] = (entry - lvl) / entry * 100 if row[f"reach_dn_{key}"] is not None else None
            else:
                row[f"reach_dn_{key}"] = None
                row[f"dist_dn_{key}"] = None

        results.append(row)

    return pd.DataFrame(results) if results else None


# ─────────────────────────────────────────────────────────────────────
# Запуск по всем парам
# ─────────────────────────────────────────────────────────────────────

print("=" * 80)
print("TP LEVELS COMPREHENSIVE TEST — ARCH-113 TPSelector")
print(f"Lookahead: {LOOKAHEAD_H}h | VP lookback: {VP_LOOKBACK_D}d | Pairs: {len(PAIRS)}")
print("=" * 80)

all_dfs = []
for sym in PAIRS:
    df = test_pair(sym)
    if df is not None:
        all_dfs.append(df)
        sys.stdout.write(f"  ✓ {sym:<15} {len(df)} days\n")
        sys.stdout.flush()
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
# ТАБЛИЦА 1: LONG TP candidates (выше entry)
# ─────────────────────────────────────────────────────────────────────

LONG_CANDIDATES = [
    ("Std R1 [baseline]",  "std_r1"),
    ("Std R2 [baseline]",  "std_r2"),
    ("PDH (prev day H)",   "pdh"),
    ("PWH (prev week H)",  "pwh"),
    ("PMH (prev month H)", "pmh"),
    ("EMA200 1d",          "ema200"),
    ("VP VAH",             "vp_vah"),
    ("VP POC",             "vp_poc"),
    ("Psycho level up",    "psycho_up"),
]

SHORT_CANDIDATES = [
    ("Std S1 [baseline]",  "std_s1"),
    ("Std S2 [baseline]",  "std_s2"),
    ("PDL (prev day L)",   "pdl"),
    ("PWL (prev week L)",  "pwl"),
    ("PML (prev month L)", "pml"),
    ("EMA200 1d",          "ema200"),
    ("VP VAL",             "vp_val"),
    ("VP POC",             "vp_poc"),
    ("Psycho level dn",    "psycho_down"),
]


def summarize_level(df, reach_col, dist_col):
    sub = df[df[reach_col].notna()]
    if len(sub) < 20:
        return None
    n = len(sub)
    reach = sub[reach_col].mean() * 100
    avg_dist = sub[dist_col].dropna().mean()
    # Разбивка по дистанции
    def rr(lo, hi):
        b = sub[(sub[dist_col] >= lo) & (sub[dist_col] < hi)]
        return f"{b[reach_col].mean()*100:.0f}%({len(b)})" if len(b) >= 5 else "-"
    return n, reach, avg_dist, rr(0, 1), rr(1, 2), rr(2, 4), rr(4, 8), rr(8, 99)


print("=" * 100)
print("LONG TP LEVELS — reach rate в следующие 24h")
print(f"  {'Уровень':<22} {'N':>6}  {'Reach%':>7}  {'AvgDist':>7}  {'<1%':>9} {'1-2%':>9} {'2-4%':>9} {'4-8%':>9} {'>8%':>9}")
print("-" * 100)

for name, key in LONG_CANDIDATES:
    r = summarize_level(combined, f"reach_up_{key}", f"dist_up_{key}")
    if r is None:
        print(f"  {name:<22} {'<20 obs':>6}")
        continue
    n, reach, avg_dist, d1, d2, d3, d4, d5 = r
    print(f"  {name:<22} {n:>6}  {reach:>6.1f}%  {avg_dist:>6.2f}%  {d1:>9} {d2:>9} {d3:>9} {d4:>9} {d5:>9}")

print()
print("SHORT TP LEVELS — reach rate в следующие 24h")
print(f"  {'Уровень':<22} {'N':>6}  {'Reach%':>7}  {'AvgDist':>7}  {'<1%':>9} {'1-2%':>9} {'2-4%':>9} {'4-8%':>9} {'>8%':>9}")
print("-" * 100)

for name, key in SHORT_CANDIDATES:
    r = summarize_level(combined, f"reach_dn_{key}", f"dist_dn_{key}")
    if r is None:
        print(f"  {name:<22} {'<20 obs':>6}")
        continue
    n, reach, avg_dist, d1, d2, d3, d4, d5 = r
    print(f"  {name:<22} {n:>6}  {reach:>6.1f}%  {avg_dist:>6.2f}%  {d1:>9} {d2:>9} {d3:>9} {d4:>9} {d5:>9}")


# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 2: Precision — как часто уровень = ближайший к entry
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 100)
print("PRECISION — как часто уровень является БЛИЖАЙШИМ выше/ниже entry (будет выбран TPSelector)")
print("-" * 100)

long_keys = [k for _, k in LONG_CANDIDATES]
short_keys = [k for _, k in SHORT_CANDIDATES]


def precision_analysis(df, keys_with_dir, direction="up"):
    """Для каждого дня: какой уровень ближайший к entry?"""
    prefix = f"dist_{direction}_"
    counts = {k: 0 for k in keys_with_dir}
    total_valid = 0

    for _, row in df.iterrows():
        dists = {}
        for k in keys_with_dir:
            d = row.get(f"{prefix}{k}")
            if d is not None and not (isinstance(d, float) and np.isnan(d)) and d > 0:
                dists[k] = d
        if not dists:
            continue
        total_valid += 1
        nearest = min(dists, key=dists.get)
        counts[nearest] += 1

    return {k: counts[k] / total_valid * 100 if total_valid > 0 else 0 for k in keys_with_dir}, total_valid


prec_up, n_up = precision_analysis(combined, long_keys, "up")
prec_dn, n_dn = precision_analysis(combined, short_keys, "dn")

print(f"\n  LONG precision (n={n_up} days):")
for name, key in LONG_CANDIDATES:
    pct = prec_up.get(key, 0)
    bar = "█" * int(pct / 2)
    print(f"    {name:<22} {pct:>5.1f}%  {bar}")

print(f"\n  SHORT precision (n={n_dn} days):")
for name, key in SHORT_CANDIDATES:
    pct = prec_dn.get(key, 0)
    bar = "█" * int(pct / 2)
    print(f"    {name:<22} {pct:>5.1f}%  {bar}")


# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 3: VP детальный анализ
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 100)
print("VOLUME PROFILE детально: POC как магнит (выше или ниже entry?)")
print("-" * 100)
poc_col = combined["vp_poc"].dropna()
entry_col = combined.loc[poc_col.index, "entry"]
poc_above = (poc_col > entry_col).sum()
poc_below = (poc_col < entry_col).sum()
poc_total = len(poc_col)
print(f"  POC выше entry:  {poc_above/poc_total*100:.1f}%  (потенциальный TP для LONG)")
print(f"  POC ниже entry:  {poc_below/poc_total*100:.1f}%  (потенциальный TP для SHORT)")
print(f"  Итого с VP данными: {poc_total} дней")

# POC reach при разных позициях
sub_above = combined[combined["vp_poc"].notna() & (combined["vp_poc"] > combined["entry"])]
r_poc_above = summarize_level(sub_above, "reach_up_vp_poc", "dist_up_vp_poc")
if r_poc_above:
    n, reach, avg_dist = r_poc_above[:3]
    print(f"  POC выше: reach={reach:.1f}%, avg_dist={avg_dist:.2f}% (n={n})")

sub_below = combined[combined["vp_poc"].notna() & (combined["vp_poc"] < combined["entry"])]
r_poc_below = summarize_level(sub_below, "reach_dn_vp_poc", "dist_dn_vp_poc")
if r_poc_below:
    n, reach, avg_dist = r_poc_below[:3]
    print(f"  POC ниже: reach={reach:.1f}%, avg_dist={avg_dist:.2f}% (n={n})")


# ─────────────────────────────────────────────────────────────────────
# ИТОГОВЫЙ РЕЙТИНГ
# ─────────────────────────────────────────────────────────────────────

print()
print("=" * 100)
print("ИТОГОВЫЙ РЕЙТИНГ TP МАГНИТОВ (по reach_rate × precision)")
print()

scores = []
for name, key in LONG_CANDIDATES:
    r = summarize_level(combined, f"reach_up_{key}", f"dist_up_{key}")
    if r is None:
        continue
    n, reach, avg_dist = r[:3]
    prec = prec_up.get(key, 0)
    # Score = reach_rate × weight_precision (ближе к TP выбору = лучше)
    score = reach * 0.6 + prec * 0.4
    scores.append((name + " (L)", reach, avg_dist, prec, score, n))

for name, key in SHORT_CANDIDATES:
    r = summarize_level(combined, f"reach_dn_{key}", f"dist_dn_{key}")
    if r is None:
        continue
    n, reach, avg_dist = r[:3]
    prec = prec_dn.get(key, 0)
    score = reach * 0.6 + prec * 0.4
    scores.append((name + " (S)", reach, avg_dist, prec, score, n))

scores.sort(key=lambda x: -x[4])
print(f"  {'Уровень':<28} {'Reach%':>7} {'AvgDist':>8} {'Precision':>10} {'Score':>7}")
print("-" * 70)
for name, reach, avg_dist, prec, score, n in scores:
    print(f"  {name:<28} {reach:>6.1f}% {avg_dist:>7.2f}% {prec:>9.1f}% {score:>7.1f}")

print()
print("Score = reach_rate × 0.6 + precision × 0.4")
print("Рекомендуемые слои для TPSelector: Score > 35, Reach > 30%, AvgDist < 5%")
