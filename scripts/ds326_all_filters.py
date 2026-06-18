"""DS-326 расширенный: ВСЕ фильтры для WT-B поиска прибыли.
Формулы: сверены с продакшен (signal_checkers.py:267-407) — идентичны.
"""
import sys, os, warnings, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from pathlib import Path

from core.indicators.indicators import (
    calculate_wt, calculate_trend, calculate_n_down, calculate_n_up,
    find_swing_highs, find_swing_lows,
)
from core.smc.smc_engine import detect_structure_breaks

# Импорт из базового скрипта
from backtest_wt_b_ltf_entry import (
    WT_N1, WT_N2, LOOKBACK_1H, DIV_MIN, DIV_MAX, OS_FLOOR, OB_FLOOR,
    LTF_WINDOW, ATR_PERIOD, ATR_FACTOR, MIN_SL_PCT, MAX_SL_PCT,
    _sl_from_trend, _bullish_div, _bearish_div, build_4h_wt,
    scan_1h_signals, find_ltf_entry, simulate_trade, stats,
    HIST_1H, HIST_15M,
)

# ═══════════════════════════════════════════════════════════════
# ФИЛЬТР 1: ADX < 25 (слабый тренд = mean-reversion работает)
# ═══════════════════════════════════════════════════════════════
def _adx_manual(df: pd.DataFrame, period: int = 14) -> float:
    """ADX без импорта — raw вычисление."""
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.Series(np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1)))), index=df.index)
    atr = tr.ewm(span=period).mean()
    up = h.diff(); dn = -l.diff()
    up[up < 0] = 0; dn[dn < 0] = 0
    atr_safe = atr.replace(0, np.nan)
    pdi = (up.ewm(span=period).mean() / atr_safe * 100).fillna(0)
    ndi = (dn.ewm(span=period).mean() / atr_safe * 100).fillna(0)
    dx = abs(pdi - ndi) / (pdi + ndi + 1e-10) * 100
    adx = dx.ewm(span=period).mean()
    return float(adx.iloc[-1]) if not adx.empty else 999


def adx_value(df1h: pd.DataFrame, signal_ts) -> float:
    """ADX на баре сигнала (только прошлое: срез [..bar_idx])."""
    try:
        bar_idx = df1h.index.get_loc(signal_ts)
    except KeyError:
        return 999.0
    sl = df1h.iloc[max(0, bar_idx - 60):bar_idx + 1]
    if len(sl) < 20:
        return 999.0
    return _adx_manual(sl, period=14)


def filter_adx(df1h: pd.DataFrame, signal_ts, max_adx: float = 25.0) -> bool:
    return adx_value(df1h, signal_ts) < max_adx


# ═══════════════════════════════════════════════════════════════
# ФИЛЬТР 2: Трендовый (EMA50 > EMA200 = запрет SHORT)
# ═══════════════════════════════════════════════════════════════
def filter_trend_ema(df1h: pd.DataFrame, signal_ts, direction: str) -> bool:
    """SHORT только если EMA50 < EMA200 (медвежий). LONG только если EMA50 > EMA200."""
    try:
        bar_idx = df1h.index.get_loc(signal_ts)
    except KeyError:
        return False
    if bar_idx < 200:
        return False
    ema50 = df1h['close'].iloc[max(0, bar_idx-50):bar_idx+1].ewm(span=50).mean().iloc[-1]
    ema200 = df1h['close'].iloc[max(0, bar_idx-200):bar_idx+1].ewm(span=200).mean().iloc[-1]
    if direction == "SHORT":
        return ema50 < ema200
    else:
        return ema50 > ema200


# ═══════════════════════════════════════════════════════════════
# ФИЛЬТР 3: CHoCH 4h (структурный разворот старшего ТФ)
# ═══════════════════════════════════════════════════════════════
def filter_choch_4h(df1h: pd.DataFrame, signal_ts, direction: str) -> bool:
    try:
        bar_idx = df1h.index.get_loc(signal_ts)
    except KeyError:
        return False
    # Resample 1h -> 4h
    sl = df1h.iloc[max(0, bar_idx - 200):bar_idx + 1]
    d4 = sl.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    if len(d4) < 30:
        return False
    breaks = detect_structure_breaks(d4, length=5)
    dir_map = {"LONG": "bull", "SHORT": "bear"}
    target = dir_map.get(direction, "")
    for b in breaks:
        if b.kind == "CHoCH" and b.direction == target:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# ФИЛЬТР 4: n_down 0-2 (импульс не выдохся = mean-reversion ок)
# ═══════════════════════════════════════════════════════════════
def filter_ndown_range(df1h: pd.DataFrame, signal_ts, min_nd: int = 0, max_nd: int = 2) -> bool:
    try:
        bar_idx = df1h.index.get_loc(signal_ts)
    except KeyError:
        return False
    sl = df1h.iloc[max(0, bar_idx - 200):bar_idx + 1]
    if len(sl) < 30:
        return False
    sh = find_swing_highs(sl['high'], period=5)
    nd = calculate_n_down(sh) if len(sh) > 1 else 0
    return min_nd <= nd <= max_nd


# ═══════════════════════════════════════════════════════════════
# Сканер с фильтрами
# ═══════════════════════════════════════════════════════════════

def run_symbol_full(symbol: str, rr: float, ltf_window: int) -> list:
    p1h = HIST_1H / f"{symbol}.parquet"
    p15 = HIST_15M / f"{symbol}.parquet"
    if not p1h.exists() or not p15.exists():
        return []
    df1h = pd.read_parquet(p1h)
    df15m = pd.read_parquet(p15)
    wt4 = build_4h_wt(df1h)
    signals = scan_1h_signals(df1h, wt4)
    rows = []
    for sig in signals:
        ts, direction, kind = sig["ts"], sig["direction"], sig["kind"]
        if kind == "cross":
            r = simulate_trade(df15m, ts, sig["entry_1h"], sig["sl_1h"], direction, rr)
            rows.append({"symbol": symbol, "ts": ts, "direction": direction,
                         "kind": "baseline", "div_strength": sig["div_strength"], "R": r})
            continue
        ltf = find_ltf_entry(df15m, ts, direction, sig["os_"], sig["ob"], ltf_window)
        if not ltf:
            continue
        r = simulate_trade(df15m, ltf["ts"], ltf["entry"], ltf["sl"], direction, rr)
        entry_px = ltf["entry"]

        av = adx_value(df1h, ts)   # считаем ADX один раз на сигнал

        # Базовые
        rows.append({"symbol": symbol, "ts": ts, "direction": direction,
                     "kind": "ltf_all", "div_strength": sig["div_strength"], "R": r, "adx": av})
        if sig["htf_ok"]:
            rows.append({"symbol": symbol, "ts": ts, "direction": direction,
                         "kind": "ltf_4h", "div_strength": sig["div_strength"], "R": r, "adx": av})

        # ── НОВЫЕ ФИЛЬТРЫ ──

        if av < 25:
            rows.append({"symbol": symbol, "ts": ts, "direction": direction,
                         "kind": "ltf_adx", "div_strength": sig["div_strength"], "R": r, "adx": av})

        if filter_trend_ema(df1h, ts, direction):
            rows.append({"symbol": symbol, "ts": ts, "direction": direction,
                         "kind": "ltf_trend", "div_strength": sig["div_strength"], "R": r})

        if filter_choch_4h(df1h, ts, direction):
            rows.append({"symbol": symbol, "ts": ts, "direction": direction,
                         "kind": "ltf_choch4h", "div_strength": sig["div_strength"], "R": r})

        if filter_ndown_range(df1h, ts, min_nd=0, max_nd=2):
            rows.append({"symbol": symbol, "ts": ts, "direction": direction,
                         "kind": "ltf_nd02", "div_strength": sig["div_strength"], "R": r})

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=int, default=45)
    parser.add_argument("--rr", type=float, default=3.0)
    parser.add_argument("--window", type=int, default=20)
    args = parser.parse_args()
    syms_1h = {p.stem for p in HIST_1H.glob("*.parquet")}
    syms_15m = {p.stem for p in HIST_15M.glob("*.parquet")}
    symbols = sorted(syms_1h & syms_15m)[:args.symbols]
    print(f"WT-B ALL FILTERS: {len(symbols)} pairs, RR={args.rr}")
    all_rows = []
    for sym in symbols:
        rows = run_symbol_full(sym, args.rr, args.window)
        all_rows += rows
    df = pd.DataFrame(all_rows)
    kinds = ["baseline", "ltf_all", "ltf_4h", "ltf_adx", "ltf_trend", "ltf_choch4h", "ltf_nd02"]
    print(f"\n{'kind':<20s} {'n':>5s} {'avgR':>8s} {'medR':>8s} {'WR':>6s} {'sharpe':>7s} {'sumR':>8s}")
    print("-" * 70)
    for k in kinds:
        r_list = df[df["kind"] == k]["R"].tolist()
        if not r_list:
            continue
        arr = np.array(r_list)
        wr = (arr > 0).mean() * 100
        sharpe = arr.mean() / arr.std() if arr.std() > 0 else 0.0
        print(f"{k:<20s} {len(arr):>5d} {arr.mean():>+8.3f} {np.median(arr):>+8.3f} {wr:>5.1f}% {sharpe:>+7.3f} {arr.sum():>+8.1f}")

    # ── Скан порога ADX (на ltf_all, где есть колонка adx) ──
    base = df[(df["kind"] == "ltf_all") & df["adx"].notna() & (df["adx"] < 900)]
    if not base.empty:
        print(f"\nADX-threshold scan (на ltf_all, n_total={len(base)})")
        print(f"{'ADX<':<6s} {'n':>5s} {'avgR':>8s} {'WR':>6s} {'sharpe':>7s} {'sumR':>8s}")
        print("-" * 46)
        for thr in [15, 20, 25, 30, 35, 40]:
            arr = base[base["adx"] < thr]["R"].to_numpy()
            if len(arr) == 0:
                continue
            wr = (arr > 0).mean() * 100
            sh = arr.mean() / arr.std() if arr.std() > 0 else 0.0
            print(f"{thr:<6d} {len(arr):>5d} {arr.mean():>+8.3f} {wr:>5.1f}% {sh:>+7.3f} {arr.sum():>+8.1f}")

    # Комбо: лучшие фильтры
    df['id'] = df['symbol'].astype(str) + '|' + df['ts'].astype(str) + '|' + df['direction'].astype(str)
    sets = {k: set(df[df['kind'] == k]['id']) for k in kinds if df[df['kind'] == k].any().any()}
    if 'ltf_adx' in sets and 'ltf_trend' in sets:
        combo = sets['ltf_adx'] & sets['ltf_trend']
        r_combo = [r for _, r in df.iterrows() if r['id'] in combo and r['kind'] == 'ltf_all']
        if r_combo:
            stats([x['R'] for x in r_combo], "COMBO ADX+TREND")
    if 'ltf_adx' in sets and 'ltf_nd02' in sets:
        combo = sets['ltf_adx'] & sets['ltf_nd02']
        r_combo = [r for _, r in df.iterrows() if r['id'] in combo and r['kind'] == 'ltf_all']
        if r_combo:
            stats([x['R'] for x in r_combo], "COMBO ADX+ND02")


if __name__ == "__main__":
    main()
