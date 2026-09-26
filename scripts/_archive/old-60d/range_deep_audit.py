"""
Глубокий аудит RANGE детекции: что реально происходит на истории BTC 1h.
Сравниваем 4 метода определения RANGE и их correlation с будущим движением.
"""
import sys, numpy as np
from pathlib import Path
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

HISTORY_DIR = Path("data/history/1h")

def _ema(s, n): return s.ewm(span=n, adjust=False).mean()
def _atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()

def _adx(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    up   = h.diff(); dn = -l.diff()
    pdm  = up.where((up > dn) & (up > 0), 0.0)
    ndm  = dn.where((dn > up) & (dn > 0), 0.0)
    atr  = _atr(df, n)
    pdi  = 100 * _ema(pdm, n) / atr.replace(0, np.nan)
    ndi  = 100 * _ema(ndm, n) / atr.replace(0, np.nan)
    dx   = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan))
    return _ema(dx, n)

def _wt(df, n1=10, n2=21):
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    esa  = _ema(hlc3, n1)
    d    = _ema((hlc3 - esa).abs(), n1)
    ci   = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1  = _ema(ci, n2)
    return wt1

# ── Загрузка ─────────────────────────────────────────────────────────────────
path = HISTORY_DIR / "BTCUSDT.parquet"
df   = pd.read_parquet(path)
df["atr"]  = _atr(df)
df["adx"]  = _adx(df)
df["ema20"] = _ema(df["close"], 20)
df["ema50"] = _ema(df["close"], 50)
df["wt1"]  = _wt(df)

# Наклон EMA20 (% от цены за 5 баров)
df["ema_slope"] = (df["ema20"] - df["ema20"].shift(5)) / df["close"]

print(f"BTC 1h: {len(df)} баров, {df.index.min():%Y-%m-%d} – {df.index.max():%Y-%m-%d}")

# ── Метод 1: ADX ≤ 25 (текущий classify_from_ohlcv) ─────────────────────────
df["m1_range"] = df["adx"] <= 25

# ── Метод 2: WT span p10/p90 за 40 баров < порог ────────────────────────────
SPAN_W = 40
df["wt_span"] = df["wt1"].rolling(SPAN_W).apply(
    lambda x: np.percentile(x, 90) - np.percentile(x, 10), raw=True
)
df["m2_range_55"] = df["wt_span"] < 55
df["m2_range_65"] = df["wt_span"] < 65
df["m2_range_75"] = df["wt_span"] < 75

# ── Метод 3: Price range за 30 баров < 5% (ценовая боковик) ─────────────────
df["price_range_pct"] = (
    df["high"].rolling(30).max() - df["low"].rolling(30).min()
) / df["close"] * 100
df["m3_range"] = df["price_range_pct"] < 6.0

# ── Метод 4: Комбо (ADX < 25 OR ema_slope < 0.001) + WT span < 70 ───────────
df["m4_range"] = (
    ((df["adx"] <= 25) | (df["ema_slope"].abs() < 0.001)) &
    (df["wt_span"] < 70)
)

# ── Метод 5: "Истинный" RANGE через структуру — HH/LL отсутствуют ────────────
# Proxy: close в пределах rolling(50) high/low channel со стороной < 8%
df["ch_high"] = df["high"].rolling(50).max()
df["ch_low"]  = df["low"].rolling(50).min()
df["ch_width_pct"] = (df["ch_high"] - df["ch_low"]) / df["close"] * 100
df["ch_pos"] = (df["close"] - df["ch_low"]) / (df["ch_high"] - df["ch_low"])  # 0..1
df["m5_range"] = df["ch_width_pct"] < 12.0  # канал уже 12% — боковик

# ── Оценочная метрика: будущее движение за 10 баров ─────────────────────────
# Если RANGE — хорошо если цена не уходит далеко (range < 3%)
# Если TREND — хорошо если цена движется направленно (>2%)
df["future_range_pct"] = (
    df["high"].shift(-10).rolling(10).max() -
    df["low"].shift(-10).rolling(10).min()
) / df["close"] * 100
df["future_directional"] = (df["close"].shift(-10) - df["close"]).abs() / df["close"] * 100

# ── Статистика каждого метода ─────────────────────────────────────────────────
print("\n=== СРАВНЕНИЕ МЕТОДОВ RANGE ДЕТЕКЦИИ ===")
print(f"{'Метод':<35} {'% RANGE':>8} {'fut.range в RANGE':>18} {'fut.range в non-RANGE':>22} {'разница':>8}")
print("-"*100)

methods = {
    "M1: ADX ≤ 25":           "m1_range",
    "M2: WT span < 55":       "m2_range_55",
    "M2: WT span < 65":       "m2_range_65",
    "M2: WT span < 75":       "m2_range_75",
    "M3: price_range < 6%":   "m3_range",
    "M4: (ADX<25|slope<0.001)+span<70": "m4_range",
    "M5: channel < 12%":      "m5_range",
}

valid = df.dropna(subset=["future_range_pct", "wt_span", "adx"])
for label, col in methods.items():
    is_range = valid[col]
    pct_range = is_range.mean() * 100
    fr_range  = valid.loc[is_range,  "future_range_pct"].mean()
    fr_trend  = valid.loc[~is_range, "future_range_pct"].mean()
    diff = fr_trend - fr_range  # хорошо если > 0 (в тренде больше движения)
    flag = " ✅" if diff > 1.0 and 20 < pct_range < 60 else ""
    print(f"  {label:<33} {pct_range:>7.1f}%  {fr_range:>17.2f}%  {fr_trend:>21.2f}%  {diff:>+7.2f}%{flag}")

# ── WT span распределение ─────────────────────────────────────────────────────
print("\n=== WT SPAN РАСПРЕДЕЛЕНИЕ (percentiles) ===")
valid_span = df["wt_span"].dropna()
for p in [10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90]:
    v = np.percentile(valid_span, p)
    print(f"  p{p:<3}: {v:.1f}")

# ── Корреляция span с будущим движением ──────────────────────────────────────
print("\n=== WT SPAN → БУДУЩЕЕ ДВИЖЕНИЕ (bucket анализ) ===")
print(f"{'WT span bucket':<20} {'n':>5} {'fut_range%':>11} {'fut_dir%':>10} {'% от total':>10}")
print("-"*60)
buckets = [(0,30), (30,45), (45,55), (55,65), (65,80), (80,100), (100,200)]
total = len(valid)
for lo, hi in buckets:
    sub = valid[(valid["wt_span"] >= lo) & (valid["wt_span"] < hi)]
    if len(sub) < 10:
        continue
    fr = sub["future_range_pct"].mean()
    fd = sub["future_directional"].mean()
    print(f"  span [{lo:>3}–{hi:<4}):      {len(sub):>5}  {fr:>10.2f}%  {fd:>9.2f}%  {len(sub)/total*100:>9.1f}%")

# ── ADX распределение ─────────────────────────────────────────────────────────
print("\n=== ADX РАСПРЕДЕЛЕНИЕ ===")
valid_adx = df["adx"].dropna()
for p in [10, 25, 50, 75, 90]:
    v = np.percentile(valid_adx, p)
    print(f"  p{p:<3}: {v:.1f}")
print(f"  ADX ≤ 20: {(valid_adx <= 20).mean()*100:.0f}%")
print(f"  ADX ≤ 25: {(valid_adx <= 25).mean()*100:.0f}%")
print(f"  ADX ≤ 30: {(valid_adx <= 30).mean()*100:.0f}%")

# ── Лучший порог ADX для разделения ─────────────────────────────────────────
print("\n=== ОПТИМАЛЬНЫЙ ПОРОГ (какой даёт максимальную разницу fut_range) ===")
best_diff, best_thr, best_method = 0, 0, ""
for thr in range(15, 45, 2):
    is_r = valid["adx"] <= thr
    if is_r.mean() < 0.1 or is_r.mean() > 0.7:
        continue
    diff = valid.loc[~is_r, "future_range_pct"].mean() - valid.loc[is_r, "future_range_pct"].mean()
    if diff > best_diff:
        best_diff, best_thr = diff, thr

print(f"  ADX ≤ {best_thr}: diff = {best_diff:.2f}%")

for thr in range(30, 90, 5):
    is_r = valid["wt_span"] < thr
    if is_r.mean() < 0.1 or is_r.mean() > 0.7:
        continue
    diff = valid.loc[~is_r, "future_range_pct"].mean() - valid.loc[is_r, "future_range_pct"].mean()
    if diff > best_diff:
        best_diff, best_thr = diff, thr
        best_method = "WT span"

print(f"  WT span < {best_thr}: diff = {best_diff:.2f}% ← ЛУЧШИЙ одиночный порог" if best_method else "  ADX лучше чем WT span")

print("\n=== ГОТОВО ===")
