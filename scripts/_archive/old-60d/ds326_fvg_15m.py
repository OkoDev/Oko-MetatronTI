"""DS-326: FVG + 15m-only фильтры — быстрый тест."""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from pathlib import Path

from core.indicators.indicators import calculate_wt, calculate_trend
from backtest_wt_b_ltf_entry import (
    WT_N1, WT_N2, LOOKBACK_1H, DIV_MIN, DIV_MAX, OS_FLOOR, OB_FLOOR,
    _sl_from_trend, _bullish_div, _bearish_div, simulate_trade,
    HIST_1H, HIST_15M,
)

# ═══════════════════════════════════════════════════════════════
# FVG detector
# ═══════════════════════════════════════════════════════════════
def detect_fvg(df: pd.DataFrame, n: int = 50) -> list:
    fvgs = []
    # последние n баров
    sub = df.tail(n)
    for i in range(2, len(sub)):
        c1_h, c1_l = float(sub['high'].iloc[i-2]), float(sub['low'].iloc[i-2])
        c3_h, c3_l = float(sub['high'].iloc[i]), float(sub['low'].iloc[i])
        gap_up = c1_h < c3_l   # цена рванула вверх — для LONG (цена вернётся в gap)
        gap_dn = c1_l > c3_h   # цена рванула вниз — для SHORT
        if gap_up:
            fvgs.append({'lo': c1_h, 'hi': c3_l, 'dir': 'bull', 'age': i})
        elif gap_dn:
            fvgs.append({'lo': c3_h, 'hi': c1_l, 'dir': 'bear', 'age': i})
    return fvgs


# ═══════════════════════════════════════════════════════════════
# 15m-only scanner
# ═══════════════════════════════════════════════════════════════
def scan_15m_direct(df: pd.DataFrame) -> list:
    if len(df) < 80:
        return []
    df_wt = calculate_wt(df.copy(), n1=WT_N1, n2=WT_N2)
    if "wt1" not in df_wt.columns:
        return []
    df_wt.index = df.index
    wt1 = df_wt["wt1"].values; wt2 = df_wt["wt2"].values
    os_ = min(float(np.percentile(wt1, 10)), OS_FLOOR)
    ob  = max(float(np.percentile(wt1, 90)), OB_FLOOR)
    signals = []
    for i in range(LOOKBACK_1H, len(df_wt)):
        cross_up   = wt1[i-1] < wt2[i-1] and wt1[i] > wt2[i]
        cross_down = wt1[i-1] > wt2[i-1] and wt1[i] < wt2[i]
        if not cross_up and not cross_down:
            continue
        if cross_up and wt1[i] < os_:
            window = list(wt1[i - LOOKBACK_1H:i])
            d = _bullish_div(window, os_)
            if d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX:
                entry = float(df["close"].iloc[i])
                sl = _sl_from_trend(df, i, "LONG")
                signals.append({"ts": df.index[i], "direction": "LONG",
                                "entry": entry, "sl": sl, "div_strength": d["div_strength"]})
        if cross_down and wt1[i] > ob:
            window = list(wt1[i - LOOKBACK_1H:i])
            d = _bearish_div(window, ob)
            if d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX:
                entry = float(df["close"].iloc[i])
                sl = _sl_from_trend(df, i, "SHORT")
                signals.append({"ts": df.index[i], "direction": "SHORT",
                                "entry": entry, "sl": sl, "div_strength": d["div_strength"]})
    return signals


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
syms_1h = {p.stem for p in HIST_1H.glob("*.parquet")}
syms_15m = {p.stem for p in HIST_15M.glob("*.parquet")}
symbols = sorted(syms_1h & syms_15m)[:30]
rows15, rows_fvg, rows_base = [], [], []

for sym in symbols:
    p1h = HIST_1H / f"{sym}.parquet"
    p15 = HIST_15M / f"{sym}.parquet"
    if not p1h.exists() or not p15.exists():
        continue
    df15m = pd.read_parquet(p15)
    if isinstance(df15m.index, pd.DatetimeIndex) and df15m.index.tz:
        df15m.index = df15m.index.tz_localize(None)
    df15m.columns = [c.lower() for c in df15m.columns]

    # 15m-only signals
    sigs15 = scan_15m_direct(df15m)
    for s in sigs15:
        r = simulate_trade(df15m, s["ts"], s["entry"], s["sl"], s["direction"], 3.0)
        rows15.append({"kind": "15m_only", "symbol": sym, "R": r})

    # FVG filter on 1h signals (reuse ltf entry)
    df1h = pd.read_parquet(p1h)
    if isinstance(df1h.index, pd.DatetimeIndex) and df1h.index.tz:
        df1h.index = df1h.index.tz_localize(None)
    df1h.columns = [c.lower() for c in df1h.columns]
    from backtest_wt_b_ltf_entry import build_4h_wt, scan_1h_signals, find_ltf_entry
    wt4 = build_4h_wt(df1h)
    sigs1h = scan_1h_signals(df1h, wt4)
    for s in sigs1h:
        if s["kind"] == "cross":
            continue
        ltf = find_ltf_entry(df15m, s["ts"], s["direction"], s["os_"], s["ob"], 20)
        if not ltf:
            continue
        r = simulate_trade(df15m, ltf["ts"], ltf["entry"], ltf["sl"], s["direction"], 3.0)
        rows_base.append({"kind": "ltf_base", "symbol": sym, "R": r})
        # FVG check
        fvgs = detect_fvg(df15m, n=50)
        dir_map = {"LONG": "bull", "SHORT": "bear"}
        target = dir_map.get(s["direction"], "")
        in_fvg = any(f['dir'] == target and f['lo'] <= ltf['entry'] <= f['hi'] for f in fvgs)
        if in_fvg:
            rows_fvg.append({"kind": "ltf_fvg", "symbol": sym, "R": r})

# Results
for label, rows in [("15m-only scan", rows15), ("ltf_base (1h→15m)", rows_base), ("ltf_fvg", rows_fvg)]:
    if not rows:
        print(f"{label}: n=0")
        continue
    arr = np.array([x['R'] for x in rows])
    wr = (arr > 0).mean() * 100
    print(f"{label:<25s}: n={len(arr):>4d} avgR={arr.mean():>+7.3f} WR={wr:>5.1f}% sumR={arr.sum():>+8.1f}")
