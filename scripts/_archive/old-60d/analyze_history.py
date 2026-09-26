"""
Анализ исторических данных 1h: WT compression, режимные циклы,
atr_change frequency, wt_b на истории.

Использует: data/history/1h/<SYMBOL>.parquet
Запуск: python scripts/analyze_history.py [--symbol BTCUSDT] [--all]
"""
import sys, argparse
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

HISTORY_DIR = Path("data/history/1h")
EXT = ".parquet"

# ─── Индикаторы (из core, или минимальная локальная копия) ───────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def calculate_wt(df: pd.DataFrame, n1: int = 10, n2: int = 21) -> pd.DataFrame:
    """WaveTrend."""
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    esa  = _ema(hlc3, n1)
    d    = _ema((hlc3 - esa).abs(), n1)
    ci   = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1  = _ema(ci, n2)
    wt2  = wt1.rolling(4).mean()
    df = df.copy()
    df["wt1"] = wt1
    df["wt2"] = wt2
    return df

def classify_regime(df: pd.DataFrame, i: int, window: int = 40) -> str:
    """Классификация режима через WT compression на баре i."""
    if i < window + 20:
        return "UNKNOWN"
    wt1_w = df["wt1"].iloc[i - window:i].values
    if len(wt1_w) < window:
        return "UNKNOWN"
    os_p10 = float(np.percentile(wt1_w, 10))
    ob_p90 = float(np.percentile(wt1_w, 90))
    span   = ob_p90 - os_p10
    center = (ob_p90 + os_p10) / 2  # смещение относительно нуля

    # ATR для HIGH_VOL
    atr_vals = df["atr"].iloc[i - window:i]
    med_atr  = atr_vals.median()
    last_atr = df["atr"].iloc[i]
    if med_atr > 0 and last_atr > 1.8 * med_atr:
        return "HIGH_VOL"

    # RANGE: WT сжат, центр близко к нулю
    if span < 55 and abs(center) < 15:
        return "RANGE"

    # TREND: span широкий И смещён
    if span >= 55:
        if center > 10:
            return "TREND_UP"
        if center < -10:
            return "TREND_DOWN"
    # Смещён но span небольшой — слабый тренд
    if center > 20:
        return "TREND_UP"
    if center < -20:
        return "TREND_DOWN"
    return "RANGE"


def atr_change_count(df: pd.DataFrame, i: int, window: int = 30) -> int:
    """Кол-во смен направления ATR за window баров."""
    atr = df["atr"].iloc[max(0, i - window):i].values
    if len(atr) < 3:
        return 0
    return sum(1 for j in range(2, len(atr))
               if (atr[j] > atr[j-1]) != (atr[j-1] > atr[j-2]))


def price_range_pct(df: pd.DataFrame, i: int, window: int = 30) -> float:
    """Ценовой диапазон за window баров в %."""
    highs = df["high"].iloc[max(0, i - window):i]
    lows  = df["low"].iloc[max(0, i - window):i]
    close = df["close"].iloc[i]
    if close == 0 or highs.empty:
        return 0.0
    return float((highs.max() - lows.min()) / close * 100)


def weekly_pp(df: pd.DataFrame, i: int) -> float | None:
    """Недельный PP на баре i (пересчитывается каждые 7 дней)."""
    ts = df.index[i]
    week_start = ts - pd.Timedelta(days=ts.weekday() + 1) - pd.Timedelta(hours=ts.hour)
    prev_week = df[df.index < week_start].tail(7 * 24)
    if len(prev_week) < 10:
        return None
    return float((prev_week["high"].max() + prev_week["low"].min() + prev_week["close"].iloc[-1]) / 3)


# ─── Основной анализ одного символа ─────────────────────────────────────────

def analyze_symbol(symbol: str) -> dict:
    path = HISTORY_DIR / f"{symbol}{EXT}"
    if not path.exists():
        return {"symbol": symbol, "error": "no file"}

    df = pd.read_parquet(path)
    if len(df) < 200:
        return {"symbol": symbol, "error": f"мало баров: {len(df)}"}

    df = calculate_wt(df)
    df["atr"] = _atr(df)

    results = {
        "symbol": symbol,
        "bars": len(df),
        "period": f"{df.index.min():%Y-%m-%d} – {df.index.max():%Y-%m-%d}",

        # Группа 1: WT span статистика
        "wt_span_stats": {},

        # Группа 2: Режимные циклы (WT compression)
        "regime_cycles": [],

        # Группа 3: atr_change frequency в разных режимах
        "atr_freq_by_regime": defaultdict(list),

        # Группа 4: PP bounce rate
        "pp_bounces": {"total": 0, "bounce": 0, "break": 0},

        # Группа 5: wt_b паттерны (дивергенции)
        "wt_b_signals": {"long": 0, "short": 0, "long_wins": 0, "short_wins": 0},
    }

    # --- WT span статистика (Группа 1) ---
    spans = []
    for i in range(60, len(df)):
        wt1_w = df["wt1"].iloc[i - 40:i].values
        spans.append(float(np.percentile(wt1_w, 90) - np.percentile(wt1_w, 10)))
    if spans:
        results["wt_span_stats"] = {
            "mean": np.mean(spans),
            "p25": np.percentile(spans, 25),
            "p50": np.percentile(spans, 50),
            "p75": np.percentile(spans, 75),
            "range_frac": sum(1 for s in spans if s < 55) / len(spans),
        }

    # --- Режимные циклы (Группа 2) ---
    STEP = 5  # каждые 5 баров — не каждый
    prev_regime = None
    cycle_start = 60
    for i in range(60, len(df), STEP):
        reg = classify_regime(df, i)
        if reg == "UNKNOWN":
            continue
        if prev_regime is None:
            prev_regime = reg
            cycle_start = i
            continue
        if reg != prev_regime:
            duration = i - cycle_start
            results["regime_cycles"].append({"regime": prev_regime, "duration_bars": duration})
            prev_regime = reg
            cycle_start = i

        # atr_change frequency (Группа 3)
        atr_cnt = atr_change_count(df, i)
        results["atr_freq_by_regime"][reg].append(atr_cnt)

    # --- PP bounce rate (Группа 4) ---
    NEAR_PCT = 0.015  # 1.5% от PP
    for i in range(200, len(df) - 20, 24):  # раз в сутки
        pp = weekly_pp(df, i)
        if pp is None or pp == 0:
            continue
        close = float(df["close"].iloc[i])
        if abs(close - pp) / pp > NEAR_PCT:
            continue
        results["pp_bounces"]["total"] += 1
        # Смотрим 10 баров вперёд — вернулась ли цена от PP?
        future = df["close"].iloc[i:i+10]
        if len(future) < 5:
            continue
        if close < pp:  # цена ниже PP
            if future.max() > pp * 1.005:
                results["pp_bounces"]["bounce"] += 1
            elif future.min() < close * 0.99:
                results["pp_bounces"]["break"] += 1
        else:  # цена выше PP
            if future.min() < pp * 0.995:
                results["pp_bounces"]["bounce"] += 1
            elif future.max() > close * 1.01:
                results["pp_bounces"]["break"] += 1

    # --- wt_b паттерны (Группа 5) ---
    wt1 = df["wt1"].values
    wt2 = df["wt2"].values
    LOOKBACK = 35
    for i in range(LOOKBACK + 40, len(df) - 5):
        wt1_last, wt2_last = wt1[i], wt2[i]
        wt1_prev, wt2_prev = wt1[i-1], wt2[i-1]
        cross_up   = wt1_prev < wt2_prev and wt1_last > wt2_last
        cross_down = wt1_prev > wt2_prev and wt1_last < wt2_last
        if not cross_up and not cross_down:
            continue
        window_wt1 = wt1[i - LOOKBACK - 1:i - 1]
        os_ = min(float(np.percentile(window_wt1, 10)), -30)
        ob  = max(float(np.percentile(window_wt1, 90)),  30)
        # Проверяем дивергенцию (упрощённо: второй лоу/хай выше/ниже первого)
        half = len(window_wt1) // 2
        if cross_up and wt1_last < os_:
            first_min  = window_wt1[:half].min()
            second_min = window_wt1[half:].min()
            if second_min > first_min:  # bullish div
                div_strength = abs(second_min - first_min)
                if 3 <= div_strength <= 20:
                    results["wt_b_signals"]["long"] += 1
                    # R за 10 баров вперёд
                    entry = df["close"].iloc[i]
                    sl    = df["low"].iloc[i - 5:i].min()
                    future_high = df["high"].iloc[i:i+10].max()
                    if sl < entry and entry > 0:
                        r = (future_high - entry) / (entry - sl)
                        if r > 1.0:
                            results["wt_b_signals"]["long_wins"] += 1
        if cross_down and wt1_last > ob:
            first_max  = window_wt1[:half].max()
            second_max = window_wt1[half:].max()
            if second_max < first_max:  # bearish div
                div_strength = abs(first_max - second_max)
                if 3 <= div_strength <= 20:
                    results["wt_b_signals"]["short"] += 1
                    entry = df["close"].iloc[i]
                    sl    = df["high"].iloc[i - 5:i].max()
                    future_low = df["low"].iloc[i:i+10].min()
                    if sl > entry and entry > 0:
                        r = (entry - future_low) / (sl - entry)
                        if r > 1.0:
                            results["wt_b_signals"]["short_wins"] += 1

    return results


# ─── Агрегация и вывод ───────────────────────────────────────────────────────

def print_summary(all_results: list[dict]) -> None:
    valid = [r for r in all_results if "error" not in r]
    print(f"\n{'='*70}")
    print(f"АНАЛИЗ ИСТОРИЧЕСКИХ ДАННЫХ 1h: {len(valid)} символов")
    print(f"{'='*70}")

    # Группа 1: WT span
    print("\n=== 1. WT SPAN (p10/p90 за 40 баров 1h) ===")
    print(f"{'Символ':<15} {'mean':>7} {'p25':>7} {'p50':>7} {'p75':>7} {'RANGE%':>8}")
    print("-"*55)
    all_spans = []
    for r in sorted(valid, key=lambda x: x["wt_span_stats"].get("p50", 0)):
        s = r["wt_span_stats"]
        if not s:
            continue
        all_spans.extend([s["mean"]])
        flag = " ← сжатый" if s["p50"] < 40 else ""
        print(f"  {r['symbol']:<13} {s['mean']:>7.1f} {s['p25']:>7.1f} {s['p50']:>7.1f} {s['p75']:>7.1f} {s['range_frac']*100:>7.0f}%{flag}")
    if all_spans:
        print(f"\n  Медианный span по всем парам: {np.median(all_spans):.1f}")
        print(f"  Порог 55 — доля баров в 'RANGE' режиме: {np.mean([r['wt_span_stats']['range_frac'] for r in valid if r['wt_span_stats']]) * 100:.0f}%")

    # Группа 2: Режимные циклы
    print("\n=== 2. РЕЖИМНЫЕ ЦИКЛЫ (средняя длительность в барах 1h) ===")
    cycle_dur = defaultdict(list)
    for r in valid:
        for c in r["regime_cycles"]:
            cycle_dur[c["regime"]].append(c["duration_bars"])
    for reg in ["TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL"]:
        vals = cycle_dur[reg]
        if not vals:
            continue
        print(f"  {reg:<12}: n={len(vals):>4}  avg={np.mean(vals):>5.0f}h  med={np.median(vals):>5.0f}h  "
              f"p75={np.percentile(vals, 75):>5.0f}h  max={max(vals):>5.0f}h")

    # Группа 3: atr_change frequency
    print("\n=== 3. ATR CHANGE FREQUENCY ПО РЕЖИМАМ ===")
    atr_by_reg = defaultdict(list)
    for r in valid:
        for reg, vals in r["atr_freq_by_regime"].items():
            atr_by_reg[reg].extend(vals)
    print("  (среднее кол-во смен направления ATR за 30 баров)")
    for reg in ["TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL"]:
        vals = atr_by_reg[reg]
        if not vals:
            continue
        print(f"  {reg:<12}: avg={np.mean(vals):.1f}  med={np.median(vals):.0f}  p90={np.percentile(vals, 90):.0f}")

    # Группа 4: PP bounce rate
    print("\n=== 4. WEEKLY PP BOUNCE RATE ===")
    total_near = sum(r["pp_bounces"]["total"] for r in valid)
    total_bounce = sum(r["pp_bounces"]["bounce"] for r in valid)
    total_break  = sum(r["pp_bounces"]["break"] for r in valid)
    print(f"  Всего случаев ±1.5% от WPP: {total_near}")
    if total_near > 0:
        print(f"  Отскок от PP: {total_bounce} ({total_bounce/total_near*100:.0f}%)")
        print(f"  Пробой PP:    {total_break} ({total_break/total_near*100:.0f}%)")
        print(f"  Нейтрально:  {total_near-total_bounce-total_break}")

    # Группа 5: wt_b
    print("\n=== 5. WT-B НА ИСТОРИЧЕСКИХ ДАННЫХ ===")
    wb_long = sum(r["wt_b_signals"]["long"] for r in valid)
    wb_lwin = sum(r["wt_b_signals"]["long_wins"] for r in valid)
    wb_short = sum(r["wt_b_signals"]["short"] for r in valid)
    wb_swin  = sum(r["wt_b_signals"]["short_wins"] for r in valid)
    print(f"  LONG:  n={wb_long}  WR(>1R за 10 баров)={wb_lwin/wb_long*100:.0f}%" if wb_long else "  LONG: нет сигналов")
    print(f"  SHORT: n={wb_short}  WR(>1R за 10 баров)={wb_swin/wb_short*100:.0f}%" if wb_short else "  SHORT: нет сигналов")


# ─── Точка входа ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", help="Один символ (напр. BTCUSDT)")
    ap.add_argument("--all",    action="store_true", help="Все доступные Parquet")
    args = ap.parse_args()

    if args.symbol:
        sym = args.symbol.upper()
        r = analyze_symbol(sym)
        print_summary([r])
        return

    # Все доступные файлы
    files = sorted(HISTORY_DIR.glob("*.parquet"))
    if not files:
        print(f"Нет файлов в {HISTORY_DIR}. Сначала запусти fetch_history.py --all")
        return

    symbols = [f.stem for f in files]
    print(f"Анализируем {len(symbols)} символов...")
    all_results = []
    for sym in symbols:
        print(f"  {sym}...", end=" ", flush=True)
        r = analyze_symbol(sym)
        all_results.append(r)
        if "error" not in r:
            print(f"✅ {r['bars']} баров")
        else:
            print(f"❌ {r['error']}")

    print_summary(all_results)


if __name__ == "__main__":
    main()
