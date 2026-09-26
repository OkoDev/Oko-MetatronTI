"""WT-B + OTE HTF zone: проверка что OTE даёт естественно tight SL."""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from pathlib import Path
from core.indicators.indicators import calculate_wt, calculate_trend, find_swing_highs, find_swing_lows

WT_N1, WT_N2 = 10, 21
LOOKBACK = 35
OS_FLOOR, OB_FLOOR = -30.0, 30.0
DIV_MIN, DIV_MAX = 3.0, 20.0
ATR_PERIOD = 43

def _bullish_div(wt1_vals, os_):
    half = len(wt1_vals) // 2
    if half < 5: return {"found": False}
    os1 = [v for v in wt1_vals[:half] if v < os_]; os2 = [v for v in wt1_vals[half:] if v < os_]
    if not os1 or not os2: return {"found": False}
    min1, min2 = min(os1), min(os2)
    if min2 <= min1: return {"found": False}
    return {"found": True, "div_strength": round(min2 - min1, 2)}

def _bearish_div(wt1_vals, ob):
    half = len(wt1_vals) // 2
    if half < 5: return {"found": False}
    ob1 = [v for v in wt1_vals[:half] if v > ob]; ob2 = [v for v in wt1_vals[half:] if v > ob]
    if not ob1 or not ob2: return {"found": False}
    max1, max2 = max(ob1), max(ob2)
    if max2 >= max1: return {"found": False}
    return {"found": True, "div_strength": round(max1 - max2, 2)}

def in_ote_zone(df, bar_i, direction):
    """Проверяет: цена в OTE зоне (0.618-0.786) последнего 4h свинга."""
    sl = df.iloc[max(0, bar_i - 200):bar_i + 1]
    if len(sl) < 30: return False, None, None
    # Resample to 4h for HTF swing
    d4 = sl.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    if len(d4) < 5: return False, None, None
    sh = find_swing_highs(d4['high'], period=3)
    sl_sw = find_swing_lows(d4['low'], period=3)
    if len(sh) < 1 or len(sl_sw) < 1: return False, None, None
    sw_high = sh[-1]['value']
    sw_low = sl_sw[-1]['value']
    if sw_high <= sw_low: return False, None, None
    rng = sw_high - sw_low
    ote_lo = sw_low + rng * 0.618
    ote_hi = sw_low + rng * 0.786
    entry = float(df['close'].iloc[bar_i])
    in_zone = ote_lo <= entry <= ote_hi
    # Nearest swing as SL anchor
    if direction == 'LONG':
        return in_zone, sw_low, ote_lo
    else:
        return in_zone, sw_high, ote_hi

def sl_trendline(df, bar_i, direction):
    start = max(0, bar_i - ATR_PERIOD * 3)
    sub = df.iloc[start:bar_i + 1].copy()
    tr = calculate_trend(sub, atr_period=ATR_PERIOD, factor=1.25)
    if len(tr) < 2: return None
    return float(tr['trenddown'].iloc[-1]) if direction == 'LONG' else float(tr['trendup'].iloc[-1])

def simulate(df, entry_i, direction, sl_price, rr=4.0):
    entry = float(df['close'].iloc[entry_i])
    if sl_price is None: return 0
    if direction == 'LONG' and sl_price >= entry: return 0
    if direction == 'SHORT' and sl_price <= entry: return 0
    sl_dist = abs(entry - sl_price)
    if sl_dist < entry * 0.003: return 0
    tp = entry + sl_dist * rr if direction == 'LONG' else entry - sl_dist * rr
    for j in range(entry_i + 1, min(entry_i + 300, len(df))):
        h, l = float(df['high'].iloc[j]), float(df['low'].iloc[j])
        if direction == 'LONG':
            if l <= sl_price: return -1.0
            if h >= tp: return rr
        else:
            if h >= sl_price: return -1.0
            if l <= tp: return rr
    return 0.0

SYMS = [p.stem for p in Path("data/history/1h").glob("*.parquet")][:15]
results = []

for sym in SYMS:
    p1h = Path(f"data/history/1h/{sym}.parquet")
    if not p1h.exists(): continue
    df = pd.read_parquet(p1h)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz:
        df.index = df.index.tz_localize(None)
    df.columns = [c.lower() for c in df.columns]
    df_wt = calculate_wt(df.copy(), n1=WT_N1, n2=WT_N2)
    if "wt1" not in df_wt.columns: continue
    df_wt.index = df.index
    wt1, wt2 = df_wt["wt1"].values, df_wt["wt2"].values

    for i in range(LOOKBACK + 1, len(df_wt) - 50):
        cross_up = wt1[i-1] < wt2[i-1] and wt1[i] > wt2[i]
        cross_down = wt1[i-1] > wt2[i-1] and wt1[i] < wt2[i]
        os_ = min(float(np.percentile(wt1[max(0, i-200):i+1], 10)), OS_FLOOR)
        ob_ = max(float(np.percentile(wt1[max(0, i-200):i+1], 90)), OB_FLOOR)

        if cross_up and wt1[i] < os_:
            window = list(wt1[i - LOOKBACK:i])
            d = _bullish_div(window, os_)
            if not (d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX): continue
            in_ote, swing_sl, _ = in_ote_zone(df, i, 'LONG')
            sl_t = sl_trendline(df, i, 'LONG')
            R_sl = simulate(df, i, 'LONG', swing_sl) if swing_sl else 0
            R_t = simulate(df, i, 'LONG', sl_t)
            sl_dist = abs(float(df['close'].iloc[i]) - swing_sl) / float(df['close'].iloc[i]) * 100 if swing_sl else 99
            results.append({"sym": sym, "dir": "LONG", "ote": in_ote, "R_swing": R_sl, "R_trend": R_t, "sl_dist_pct": round(sl_dist, 2)})

        if cross_down and wt1[i] > ob_:
            window = list(wt1[i - LOOKBACK:i])
            d = _bearish_div(window, ob_)
            if not (d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX): continue
            in_ote, swing_sl, _ = in_ote_zone(df, i, 'SHORT')
            sl_t = sl_trendline(df, i, 'SHORT')
            R_sl = simulate(df, i, 'SHORT', swing_sl) if swing_sl else 0
            R_t = simulate(df, i, 'SHORT', sl_t)
            sl_dist = abs(float(df['close'].iloc[i]) - swing_sl) / float(df['close'].iloc[i]) * 100 if swing_sl else 99
            results.append({"sym": sym, "dir": "SHORT", "ote": in_ote, "R_swing": R_sl, "R_trend": R_t, "sl_dist_pct": round(sl_dist, 2)})

dfr = pd.DataFrame(results)
print(f"Signals: {len(dfr)},  OTE={dfr['ote'].sum()}  (~OTE={len(dfr)-dfr['ote'].sum()})")

# By OTE zone
for ote_flag, label in [(True, "IN OTE"), (False, "NO OTE")]:
    sub = dfr[dfr["ote"] == ote_flag]
    if len(sub) == 0: continue
    a_s = sub["R_swing"].mean()
    a_t = sub["R_trend"].mean()
    avg_dist = sub["sl_dist_pct"].mean()
    w_s = (sub["R_swing"] > 0).mean() * 100
    w_t = (sub["R_trend"] > 0).mean() * 100
    print(f"\n{label} (n={len(sub)}):")
    print(f"  Avg SL distance (swing): {avg_dist:.2f}%")
    print(f"  Swing SL  : avgR={a_s:>+7.3f} WR={w_s:>5.0f}%")
    print(f"  Trendline SL: avgR={a_t:>+7.3f} WR={w_t:>5.0f}%")

# SL distance vs R
print("\n=== SL distance buckets (swing SL) ===")
for lo, hi in [(0, 1), (1, 2), (2, 3), (3, 5), (5, 99)]:
    sub = dfr[(dfr["sl_dist_pct"] > lo) & (dfr["sl_dist_pct"] <= hi)]
    if len(sub) == 0: continue
    a = sub["R_swing"].mean(); w = (sub["R_swing"] > 0).mean() * 100
    print(f"  SL={lo}-{hi}%: n={len(sub):>3d} avgR={a:>+7.3f} WR={w:>5.0f}%")
