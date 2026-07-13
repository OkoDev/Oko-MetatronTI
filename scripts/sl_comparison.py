"""SL comparison: Trendline vs ATR on wt_b signals."""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from pathlib import Path
from core.indicators.indicators import calculate_wt, calculate_trend

WT_N1, WT_N2 = 10, 21
LOOKBACK = 35
OS_FLOOR, OB_FLOOR = -30.0, 30.0
DIV_MIN, DIV_MAX = 3.0, 20.0
ATR_PERIOD = 43
ATR_FACTOR = 1.25

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

def sl_trendline(df, bar_i, direction):
    start = max(0, bar_i - ATR_PERIOD * 3)
    sub = df.iloc[start:bar_i + 1].copy()
    tr = calculate_trend(sub, atr_period=ATR_PERIOD, factor=ATR_FACTOR)
    if len(tr) < 2: return None
    return float(tr['trenddown'].iloc[-1]) if direction == 'LONG' else float(tr['trendup'].iloc[-1])

def sl_atr_fixed(df, bar_i, direction, mult=1.3):
    entry = float(df['close'].iloc[bar_i])
    atr = (df['high'] - df['low']).iloc[max(0, bar_i - 20):bar_i + 1].mean()
    sl_dist = atr * mult
    return entry - sl_dist if direction == 'LONG' else entry + sl_dist

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

# Run
SYMS = [p.stem for p in Path("data/history/1h").glob("*.parquet")][:10]
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
            for sl_name, sl_fn in [("trendline", sl_trendline), ("atr1.0", lambda df,i,d: sl_atr_fixed(df,i,d,1.0)),
                                    ("atr1.3", lambda df,i,d: sl_atr_fixed(df,i,d,1.3)), ("atr1.5", lambda df,i,d: sl_atr_fixed(df,i,d,1.5))]:
                sl = sl_fn(df, i, 'LONG')
                R = simulate(df, i, 'LONG', sl)
                results.append({"sym": sym, "SL": sl_name, "R": R})

        if cross_down and wt1[i] > ob_:
            window = list(wt1[i - LOOKBACK:i])
            d = _bearish_div(window, ob_)
            if not (d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX): continue
            for sl_name, sl_fn in [("trendline", sl_trendline), ("atr1.0", lambda df,i,d: sl_atr_fixed(df,i,d,1.0)),
                                    ("atr1.3", lambda df,i,d: sl_atr_fixed(df,i,d,1.3)), ("atr1.5", lambda df,i,d: sl_atr_fixed(df,i,d,1.5))]:
                sl = sl_fn(df, i, 'SHORT')
                R = simulate(df, i, 'SHORT', sl)
                results.append({"sym": sym, "SL": sl_name, "R": R})

dfr = pd.DataFrame(results)
print(f"Signals: {len(dfr) // 4} x 4 SL types")
for sl_name in ["trendline", "atr1.0", "atr1.3", "atr1.5"]:
    sub = dfr[dfr["SL"] == sl_name]["R"]
    a, w, s = sub.mean(), (sub > 0).mean() * 100, sub.sum()
    print(f"  SL={sl_name:10s}: n={len(sub)} avgR={a:>+7.3f} WR={w:>5.0f}% sumR={s:>+7.1f}")
