"""DS-326: WT-B LTF 3 фильтра — дополнение к backtest_wt_b_ltf_entry.py.

Запуск: python scripts/ds326_wtb_filters.py [--symbols 20]
"""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")

import pandas as pd, numpy as np, argparse
from pathlib import Path
from core.indicators.indicators import (calculate_wt, calculate_trend, calculate_n_down,
    calculate_n_up, find_swing_highs, find_swing_lows)
from core.smc.smc_engine import detect_structure_breaks

# ── Import existing script functions ──
from backtest_wt_b_ltf_entry import (
    WT_N1, WT_N2, LOOKBACK_1H, DIV_MIN, DIV_MAX, OS_FLOOR, OB_FLOOR,
    LTF_WINDOW, ATR_PERIOD, ATR_FACTOR, MIN_SL_PCT, MAX_SL_PCT,
    RR_TARGET, TSL_ACTIVATE, MAX_BARS_SIM, HTF_OS_FLOOR, HTF_OB_FLOOR,
    _sl_from_trend, _bullish_div, _bearish_div, htf_in_zone, build_4h_wt,
    scan_1h_signals, find_ltf_entry, simulate_trade, stats,
    HIST_1H, HIST_15M,
)


# ═══════════════════════════════════════════════════════════════
# ФИЛЬТР 1: Elliott n_down/n_up
# ═══════════════════════════════════════════════════════════════

def filter_elliott(df1h: pd.DataFrame, signal_ts, direction: str) -> bool:
    """SHORT: n_down in (3,4). LONG: n_down == 0."""
    try:
        bar_idx = df1h.index.get_loc(signal_ts)
    except KeyError:
        return False
    sl = df1h.iloc[max(0, bar_idx - 200):bar_idx + 1]
    if len(sl) < 30:
        return False
    sh = find_swing_highs(sl['high'], period=5)
    sl_sw = find_swing_lows(sl['low'], period=5)
    nd = calculate_n_down(sh) if len(sh) > 1 else 0
    nu = calculate_n_up(sl_sw) if len(sl_sw) > 1 else 0

    if direction == "SHORT":
        return nd in (3, 4)
    else:
        return nd == 0


# ═══════════════════════════════════════════════════════════════
# ФИЛЬТР 2: CHoCH 15m
# ═══════════════════════════════════════════════════════════════

def filter_choch(df15m: pd.DataFrame, signal_ts, ltf_ts, direction: str) -> bool:
    """CHoCH в 15m окне перед LTF-входом (расширенное окно: 30 баров 15m)."""
    # Расширенное окно: 30 баров 15m перед ltf_ts
    window = df15m[df15m.index <= ltf_ts].tail(30)
    if len(window) < 10:
        return False
    breaks = detect_structure_breaks(window, length=5)
    dir_map = {"LONG": "bull", "SHORT": "bear"}
    target_dir = dir_map.get(direction, "")
    for b in breaks:
        if b.kind == "CHoCH" and b.direction == target_dir:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# ФИЛЬТР 3: LTF вход в OTE
# ═══════════════════════════════════════════════════════════════

def filter_ote(df1h: pd.DataFrame, df15m: pd.DataFrame, signal_ts, direction: str) -> bool:
    """LTF 15m close в OTE-зоне (0.618-0.786) последнего 1h свинга."""
    try:
        bar_idx = df1h.index.get_loc(signal_ts)
    except KeyError:
        return False
    sl = df1h.iloc[max(0, bar_idx - 200):bar_idx + 1]
    if len(sl) < 30:
        return False
    sh = find_swing_highs(sl['high'], period=5)
    sl_sw = find_swing_lows(sl['low'], period=5)

    if len(sh) < 1 or len(sl_sw) < 1:
        return False
    swing_high = sh[-1]['value']
    swing_low = sl_sw[-1]['value']
    if swing_high <= swing_low:
        return False
    range_ = swing_high - swing_low
    ote_low = swing_low + range_ * 0.618
    ote_high = swing_low + range_ * 0.786

    try:
        ltf_idx = df15m.index.get_indexer([signal_ts], method='ffill')[0]
    except Exception:
        return False
    if ltf_idx < 0 or ltf_idx >= len(df15m):
        return False
    close = float(df15m['close'].iloc[ltf_idx])

    if direction == "LONG":
        return ote_low <= close <= ote_high
    else:
        return ote_low <= close <= ote_high  # SHORT OTE тоже от свинга


# ═══════════════════════════════════════════════════════════════
# Модифицированный run_symbol с 3 фильтрами
# ═══════════════════════════════════════════════════════════════

def run_symbol_v2(symbol: str, rr: float, ltf_window: int) -> list:
    path1h = HIST_1H / f"{symbol}.parquet"
    path15m = HIST_15M / f"{symbol}.parquet"
    if not path1h.exists() or not path15m.exists():
        return []

    df1h = pd.read_parquet(path1h)
    df15m = pd.read_parquet(path15m)
    wt4 = build_4h_wt(df1h)

    signals = scan_1h_signals(df1h, wt4)
    rows = []
    for sig in signals:
        ts, direction, kind = sig["ts"], sig["direction"], sig["kind"]

        # baseline (cross)
        if kind == "cross":
            r = simulate_trade(df15m, ts, sig["entry_1h"], sig["sl_1h"], direction, rr)
            rows.append({
                "symbol": symbol, "ts": ts, "direction": direction,
                "kind": "baseline", "div_strength": sig["div_strength"], "R": r,
            })
            continue

        # LTF entry
        ltf = find_ltf_entry(df15m, ts, direction, sig["os_"], sig["ob"], ltf_window)
        if not ltf:
            continue
        r = simulate_trade(df15m, ltf["ts"], ltf["entry"], ltf["sl"], direction, rr)
        rows.append({
            "symbol": symbol, "ts": ts, "direction": direction,
            "kind": "ltf_all", "div_strength": sig["div_strength"], "R": r,
        })
        if sig["htf_ok"]:
            rows.append({
                "symbol": symbol, "ts": ts, "direction": direction,
                "kind": "ltf_4h", "div_strength": sig["div_strength"], "R": r,
            })

        # ── DS-326: 3 новых фильтра ──
        
        # Фильтр 1: Elliott n_down
        if filter_elliott(df1h, ts, direction):
            rows.append({
                "symbol": symbol, "ts": ts, "direction": direction,
                "kind": "ltf_ndown", "div_strength": sig["div_strength"], "R": r,
            })

        # Фильтр 2: CHoCH 15m
        if filter_choch(df15m, ts, ltf["ts"], direction):
            rows.append({
                "symbol": symbol, "ts": ts, "direction": direction,
                "kind": "ltf_choch", "div_strength": sig["div_strength"], "R": r,
            })

        # Фильтр 3: OTE-зона
        if filter_ote(df1h, df15m, ts, direction):
            rows.append({
                "symbol": symbol, "ts": ts, "direction": direction,
                "kind": "ltf_ote", "div_strength": sig["div_strength"], "R": r,
            })

    return rows


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=int, default=20)
    parser.add_argument("--rr", type=float, default=3.0)
    parser.add_argument("--window", type=int, default=20)
    args = parser.parse_args()

    syms_1h = {p.stem for p in HIST_1H.glob("*.parquet")}
    syms_15m = {p.stem for p in HIST_15M.glob("*.parquet")}
    symbols = sorted(syms_1h & syms_15m)[:args.symbols]

    print(f"DS-326: WT-B LTF 3 фильтра. {len(symbols)} пар, RR={args.rr}, window={args.window}")
    all_rows = []
    for sym in symbols:
        rows = run_symbol_v2(sym, args.rr, args.window)
        n_b = sum(1 for r in rows if r["kind"] == "baseline")
        n_l = sum(1 for r in rows if r["kind"] == "ltf_all")
        n_nd = sum(1 for r in rows if r["kind"] == "ltf_ndown")
        n_ch = sum(1 for r in rows if r["kind"] == "ltf_choch")
        n_ot = sum(1 for r in rows if r["kind"] == "ltf_ote")
        if n_b + n_l > 0:
            print(f"  {sym:<25} base={n_b:>3} ltf={n_l:>3} nd={n_nd:>3} choch={n_ch:>3} ote={n_ot:>3}")
        all_rows += rows

    df = pd.DataFrame(all_rows)
    print(f"\n=== РЕЗУЛЬТАТЫ ({len(df)} сделок) ===\n")
    kinds = ["baseline", "ltf_all", "ltf_4h", "ltf_ndown", "ltf_choch", "ltf_ote"]
    for k in kinds:
        r_list = df[df["kind"] == k]["R"].tolist()
        stats(r_list, k)

    # Комбо: два фильтра
    df['id'] = df['symbol'] + '|' + df['ts'].astype(str) + '|' + df['direction']
    ndown_ids = set(df[df['kind'] == 'ltf_ndown']['id'])
    choch_ids = set(df[df['kind'] == 'ltf_choch']['id'])
    ote_ids = set(df[df['kind'] == 'ltf_ote']['id'])
    
    combo_nd_ch = [r for _, r in df.iterrows() if r['id'] in ndown_ids and r['id'] in choch_ids and r['kind'] == 'ltf_all']
    combo_all3 = [r for _, r in df.iterrows() if r['id'] in ndown_ids and r['id'] in choch_ids and r['id'] in ote_ids and r['kind'] == 'ltf_all']
    
    if combo_nd_ch:
        stats([x['R'] for x in combo_nd_ch], "COMBO ndown+choch")
    if combo_all3:
        stats([x['R'] for x in combo_all3], "COMBO all 3")


if __name__ == "__main__":
    main()
