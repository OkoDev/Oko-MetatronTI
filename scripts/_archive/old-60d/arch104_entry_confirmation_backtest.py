"""
ARCH-104 Entry Confirmation Backtest
=====================================
Тестирует гипотезу: arch104 как КОНТЕКСТ + wt_cross / atr_cross как ТОЧКА ВХОДА.

Режимы:
  A  baseline     — входим сразу при active arch104 pattern
  B  +wt_cross    — входим только при pattern + wt_cross_up (WT пересекает 0)
  C  +atr_cross   — входим только при pattern + atr_cross_up (ATR supertrend разворот)
  D  +atr_down    — входим только при pattern + atr_down (ATR смотрит вниз — bias=DOWN proxy)
  E  +wt_os       — входим только при pattern + wt_os на entry TF (WT в OS зоне)

Данные: data/history/{1h,15m}/*.parquet  (46 пар × 2 TF)
Паттерны: config/arch104_patterns.yaml (15 production patterns)
Период: всё что есть в parquet (2024-01 — 2026-05)

Usage:
  python scripts/arch104_entry_confirmation_backtest.py
  python scripts/arch104_entry_confirmation_backtest.py --tf 1h
  python scripts/arch104_entry_confirmation_backtest.py --patterns L1_golden L2_wt_double_fvg
"""
import sys, os, time, argparse
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

# Пути
ROOT = Path(__file__).resolve().parent.parent
HISTORY_1H  = ROOT / "data" / "history" / "1h"
HISTORY_15M = ROOT / "data" / "history" / "15m"
sys.path.insert(0, str(ROOT / "tools" / "pattern_mining"))

# Импортируем combinator_v2 функции
try:
    import combinator_v2 as cb
except ImportError as e:
    print(f"ERROR: combinator_v2 не найден: {e}")
    sys.exit(1)

# Импортируем ARCH104Registry
sys.path.insert(0, str(ROOT))
from core.confirmations.arch104_patterns import ARCH104Registry

# ─── Константы ────────────────────────────────────────────────────────────────
FALLBACK_TP_R    = 2.0   # TP = entry + 2R (по умолчанию для всех паттернов)
TIME_EXIT_BARS_1H = 24   # 24h на 1h TF
TIME_EXIT_BARS_15M = 96  # 24h на 15m TF
SL_LOOKBACK      = 10    # баров для swing_low SL
SL_MIN_PCT       = 0.003 # минимальный SL 0.3%
SL_MAX_PCT       = 0.15  # максимальный SL 15%
DEDUP_COOLDOWN_H = 4     # не входить повторно в пару N часов


# ─── Загрузка и подготовка данных ─────────────────────────────────────────────

def load_df(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_parquet(path)
        df.columns = [c.lower() for c in df.columns]
        if "ts" in df.columns:
            df = df.set_index("ts")
        elif not isinstance(df.index, pd.DatetimeIndex):
            return None
        df.index = pd.to_datetime(df.index, utc=True)
        df = df[["open","high","low","close","volume"]].dropna().sort_index()
        return df if len(df) >= 200 else None
    except Exception as e:
        print(f"  SKIP {path.name}: {e}")
        return None


def prepare_flags(df_1h: pd.DataFrame, det_tf: str = "1h") -> pd.DataFrame | None:
    """Вычисляет combined flags на detection TF с HTF reindex."""
    try:
        df_4h = cb.aggregate_tf(df_1h, "4h")
        df_1d = cb.aggregate_tf(df_1h, "1d")

        f_1h = cb.compute_flags(df_1h, "1h", include_pivots=True)
        f_4h_src = cb.compute_flags(df_4h, "4h") if len(df_4h) >= 30 else None
        f_1d_src = cb.compute_flags(df_1d, "1d") if len(df_1d) >= 30 else None

        def _shift_and_reindex(df_src, hours, target_idx):
            if df_src is None:
                return None
            shifted = df_src.copy()
            shifted.index = shifted.index + pd.Timedelta(hours=hours)
            return shifted.reindex(target_idx, method="ffill", fill_value=False).astype(bool)

        if det_tf == "1h":
            target_idx = df_1h.index
            parts = [f_1h]
            if f_4h_src is not None:
                parts.append(_shift_and_reindex(f_4h_src, 4, target_idx))
            if f_1d_src is not None:
                parts.append(_shift_and_reindex(f_1d_src, 24, target_idx))
            return pd.concat([p for p in parts if p is not None], axis=1).astype(bool)

        return f_1h  # fallback
    except Exception as e:
        return None


def prepare_flags_15m(df_15m: pd.DataFrame, df_1h: pd.DataFrame) -> pd.DataFrame | None:
    try:
        df_4h = cb.aggregate_tf(df_1h, "4h")
        df_1d = cb.aggregate_tf(df_1h, "1d")

        f_15m = cb.compute_flags(df_15m, "15m")
        f_1h_src = cb.compute_flags(df_1h, "1h", include_pivots=True)
        f_4h_src = cb.compute_flags(df_4h, "4h") if len(df_4h) >= 30 else None
        f_1d_src = cb.compute_flags(df_1d, "1d") if len(df_1d) >= 30 else None

        target_idx = df_15m.index

        def _shift_reindex(df_src, hours):
            if df_src is None: return None
            s = df_src.copy()
            s.index = s.index + pd.Timedelta(hours=hours)
            return s.reindex(target_idx, method="ffill", fill_value=False).astype(bool)

        parts = [f_15m,
                 _shift_reindex(f_1h_src, 1),
                 _shift_reindex(f_4h_src, 4) if f_4h_src is not None else None,
                 _shift_reindex(f_1d_src, 24) if f_1d_src is not None else None]
        return pd.concat([p for p in parts if p is not None], axis=1).astype(bool)
    except Exception:
        return None


# ─── Симулятор сделки ─────────────────────────────────────────────────────────

def simulate_trade(df: pd.DataFrame, entry_i: int, direction: str,
                   tp_r: float, time_exit_bars: int, sl_lookback: int = SL_LOOKBACK):
    """Симулирует одну сделку. Возвращает (R_multiple, status, bars_held)."""
    n = len(df)
    if entry_i + 1 >= n:
        return None, "skip", 0

    price = df["close"].iloc[entry_i]
    look_start = max(0, entry_i - sl_lookback)
    sl_long  = df["low"].iloc[look_start:entry_i+1].min() * 0.999
    sl_short = df["high"].iloc[look_start:entry_i+1].max() * 1.001

    if direction == "LONG":
        sl = sl_long
        sl_dist = price - sl
    else:
        sl = sl_short
        sl_dist = sl - price

    if sl_dist <= 0:
        return None, "invalid_sl", 0
    sl_pct = sl_dist / price
    if sl_pct < SL_MIN_PCT or sl_pct > SL_MAX_PCT:
        return None, "sl_out_of_range", 0

    tp = price + tp_r * sl_dist if direction == "LONG" else price - tp_r * sl_dist

    for j in range(entry_i + 1, min(n, entry_i + time_exit_bars + 1)):
        bar_h = df["high"].iloc[j]
        bar_l = df["low"].iloc[j]
        bars_held = j - entry_i

        if direction == "LONG":
            if bar_l <= sl:
                return -1.0, "SL", bars_held
            if bar_h >= tp:
                return tp_r, "TP", bars_held
        else:
            if bar_h >= sl:
                return -1.0, "SL", bars_held
            if bar_l <= tp:
                return tp_r, "TP", bars_held

    # Time exit
    exit_price = df["close"].iloc[min(n-1, entry_i + time_exit_bars)]
    if direction == "LONG":
        r = (exit_price - price) / sl_dist
    else:
        r = (price - exit_price) / sl_dist
    return r, "TIME", time_exit_bars


# ─── Режимы (условия входа) ────────────────────────────────────────────────────

ENTRY_MODES = {
    "A_baseline":   lambda row, det_tf: True,
    "B_wt_cross":   lambda row, det_tf: bool(row.get(f"wt_cross_up_{det_tf}", False)),
    "C_atr_cross":  lambda row, det_tf: bool(row.get(f"atr_cross_up_{det_tf}", False)),
    "D_atr_down":   lambda row, det_tf: bool(row.get(f"atr_down_{det_tf}", False)),
    "E_wt_os":      lambda row, det_tf: bool(row.get(f"wt_os_{det_tf}", False)),
}


# ─── Основной runner ──────────────────────────────────────────────────────────

def run_backtest(registry: ARCH104Registry, symbols: list[str],
                 det_tf: str = "1h", pattern_filter: list[str] | None = None):
    results = {mode: [] for mode in ENTRY_MODES}
    pattern_results = {mode: {} for mode in ENTRY_MODES}
    processed = 0

    for sym in symbols:
        h1_path  = HISTORY_1H  / f"{sym}.parquet"
        h15_path = HISTORY_15M / f"{sym}.parquet"
        if not h1_path.exists():
            continue

        df_1h = load_df(h1_path)
        if df_1h is None:
            continue

        df_det = df_1h
        time_exit_bars = TIME_EXIT_BARS_1H
        flags_label = "1h"

        if det_tf == "15m":
            if not h15_path.exists():
                continue
            df_15m = load_df(h15_path)
            if df_15m is None:
                continue
            flags_df = prepare_flags_15m(df_15m, df_1h)
            df_det = df_15m
            time_exit_bars = TIME_EXIT_BARS_15M
            flags_label = "15m"
        else:
            flags_df = prepare_flags(df_1h, det_tf)

        if flags_df is None or len(flags_df) < 100:
            continue

        # Выравниваем индексы
        common_idx = df_det.index.intersection(flags_df.index)
        if len(common_idx) < 100:
            continue
        df_det   = df_det.loc[common_idx]
        flags_df = flags_df.loc[common_idx]

        n = len(df_det)
        last_entry_bar = {mode: {} for mode in ENTRY_MODES}  # pattern_id → bar_i (cooldown)

        processed += 1

        for i in range(SL_LOOKBACK + 50, n - 5):
            row = flags_df.iloc[i]
            active_flags = set(row[row].index.tolist())
            if not active_flags:
                continue

            matches = registry.find_matching("LONG", active_flags, detection_tf=det_tf)
            if not matches:
                continue

            best = matches[0]
            pid = best.id
            if pattern_filter and pid not in pattern_filter:
                continue

            tp_r = float(best.fallback_tp_r) if best.fallback_tp_r else FALLBACK_TP_R

            for mode, condition_fn in ENTRY_MODES.items():
                if not condition_fn(row, flags_label):
                    continue

                # Dedup cooldown
                cooldown_bars = DEDUP_COOLDOWN_H * (4 if det_tf == "15m" else 1)
                last_b = last_entry_bar[mode].get(pid, -9999)
                if i - last_b < cooldown_bars:
                    continue

                r, status, bars = simulate_trade(df_det, i, "LONG", tp_r, time_exit_bars)
                if r is None:
                    continue

                last_entry_bar[mode][pid] = i
                results[mode].append(r)

                if pid not in pattern_results[mode]:
                    pattern_results[mode][pid] = []
                pattern_results[mode][pid].append(r)

        if processed % 5 == 0:
            print(f"  ... {processed}/{len(symbols)} пар обработано", flush=True)

    return results, pattern_results


# ─── Вывод ────────────────────────────────────────────────────────────────────

def print_report(results: dict, pattern_results: dict, det_tf: str):
    print()
    print("=" * 75)
    print(f"ARCH-104 ENTRY CONFIRMATION BACKTEST  [det_tf={det_tf}]")
    print("=" * 75)
    print(f"{'Режим':<18} {'n':>6} {'avg_R':>8} {'WR%':>7} {'total_R':>9} {'vs A':>8}")
    print("-" * 75)

    base_avg = None
    for mode, rs in results.items():
        if not rs:
            print(f"{mode:<18} {'0':>6}")
            continue
        avg = sum(rs)/len(rs)
        wins = sum(1 for r in rs if r > 0)
        wr = wins/len(rs)*100
        total = sum(rs)
        if mode == "A_baseline":
            base_avg = avg
            vs_a = "  (base)"
        else:
            delta = avg - base_avg if base_avg is not None else 0
            vs_a = f"{delta:>+8.3f}"
        print(f"{mode:<18} {len(rs):>6} {avg:>+8.3f} {wr:>6.0f}% {total:>+9.1f} {vs_a}")

    print()
    print("=== ТОП паттернов по режиму A_baseline ===")
    print(f"{'pattern_id':<32} {'n':>5} {'avg_R':>8} {'WR%':>7}")
    print("-" * 55)
    pats_a = pattern_results.get("A_baseline", {})
    for pid, rs in sorted(pats_a.items(), key=lambda x: -len(x[1])):
        if len(rs) < 3:
            continue
        avg = sum(rs)/len(rs)
        wins = sum(1 for r in rs if r > 0)
        wr = wins/len(rs)*100
        flag = "[OK] " if avg > 0.3 else ("[BAD]" if avg < -0.3 else "[MID]")
        print(f"{flag} {pid:<28} {len(rs):>5} {avg:>+8.3f} {wr:>6.0f}%")

    print()
    print("=== Сравнение по режимам для топ паттернов ===")
    all_pids = set()
    for mode in ENTRY_MODES:
        all_pids.update(pattern_results[mode].keys())

    for pid in sorted(all_pids):
        print(f"\n  {pid}:")
        for mode in ENTRY_MODES:
            rs = pattern_results[mode].get(pid, [])
            if not rs:
                print(f"    {mode:<18}: n=0")
                continue
            avg = sum(rs)/len(rs)
            wins = sum(1 for r in rs if r > 0)
            wr = wins/len(rs)*100
            print(f"    {mode:<18}: n={len(rs):>4}, avg_R={avg:>+7.3f}, WR={wr:>5.0f}%")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h", choices=["1h","15m"], help="Detection timeframe")
    ap.add_argument("--patterns", nargs="*", help="Фильтр по pattern_id (напр. L1_golden L2_wt_double_fvg)")
    ap.add_argument("--symbols", nargs="*", help="Фильтр символов (напр. BTCUSDT ETHUSDT)")
    args = ap.parse_args()

    # Список символов
    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        symbols = sorted([p.stem for p in HISTORY_1H.glob("*.parquet")])

    print(f"Загрузка registry...")
    registry = ARCH104Registry()
    long_pats = registry.list_by_direction("LONG")
    print(f"Паттернов LONG: {len(long_pats)}")
    for p in long_pats:
        print(f"  {p.id:<30} test_n={p.test_n} avgR={p.test_avgR:+.3f} det_tf={p.detection_tf}")

    print(f"\nСимволов: {len(symbols)}, det_tf={args.tf}")
    print(f"Паттерны: {args.patterns or 'все'}")
    print()

    t0 = time.time()
    results, pattern_results = run_backtest(
        registry, symbols,
        det_tf=args.tf,
        pattern_filter=args.patterns,
    )
    elapsed = time.time() - t0

    print_report(results, pattern_results, args.tf)
    print(f"\nВремя: {elapsed:.1f}с  |  Пар: {len(symbols)}")


if __name__ == "__main__":
    main()
