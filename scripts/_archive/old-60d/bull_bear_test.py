"""Тест LONG на бычьих/медвежьих периодах (BTC, ETH, SOL)."""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from pathlib import Path
from core.indicators.indicators import calculate_wt, calculate_trend

WT_N1, WT_N2 = 10, 21
LOOKBACK = 35
DIV_MIN, DIV_MAX = 3.0, 20.0
OS_FLOOR, OB_FLOOR = -30.0, 30.0

# Period definitions (BTC-driven)
PERIODS = {
    "BULL 2024 Q1": ("2024-01-01", "2024-03-15"),
    "BEAR 2024 Q2-Q3": ("2024-04-01", "2024-09-15"),
    "BULL 2024 Q4": ("2024-09-16", "2024-12-31"),
    "BULL 2025 Q1": ("2025-01-01", "2025-02-15"),
    "BEAR 2025 Q1-Q2": ("2025-02-16", "2025-06-01"),
    "BEAR 2026 Q2": ("2026-04-01", "2026-06-15"),
}

def _bullish_div(wt1_vals, os_):
    half = len(wt1_vals) // 2
    if half < 5: return {"found": False}
    os1 = [v for v in wt1_vals[:half] if v < os_]
    os2 = [v for v in wt1_vals[half:] if v < os_]
    if not os1 or not os2: return {"found": False}
    min1, min2 = min(os1), min(os2)
    if min2 <= min1: return {"found": False}
    return {"found": True, "div_strength": round(min2 - min1, 2)}

def _bearish_div(wt1_vals, ob):
    half = len(wt1_vals) // 2
    if half < 5: return {"found": False}
    ob1 = [v for v in wt1_vals[:half] if v > ob]
    ob2 = [v for v in wt1_vals[half:] if v > ob]
    if not ob1 or not ob2: return {"found": False}
    max1, max2 = max(ob1), max(ob2)
    if max2 >= max1: return {"found": False}
    return {"found": True, "div_strength": round(max1 - max2, 2)}

def simulate(df, entry_i, direction, rr=4.0, max_bars=300):
    """Упрощённая симуляция: TP на RR, SL на ATR, TSL после 1R."""
    entry = float(df['close'].iloc[entry_i])
    atr = (df['high'] - df['low']).tail(20).mean()
    sl_dist = atr * 1.5
    if direction == "LONG":
        sl, tp = entry - sl_dist, entry * (1 + 0.02 * rr)
    else:
        sl, tp = entry + sl_dist, entry * (1 - 0.02 * rr)
    tsl_active, tsl_price = False, sl
    for j in range(entry_i + 1, min(entry_i + max_bars, len(df))):
        h, l, c = float(df['high'].iloc[j]), float(df['low'].iloc[j]), float(df['close'].iloc[j])
        if direction == "LONG":
            if l <= sl: return -1.0
            if h >= tp: return rr
            if c >= entry * 1.02 and not tsl_active:
                tsl_active = True
                tsl_price = entry
            if tsl_active:
                tsl_price = max(tsl_price, entry + (c - entry) * 0.5)
                if l <= tsl_price: return (tsl_price - entry) / (entry - sl)
        else:
            if h >= sl: return -1.0
            if l <= tp: return rr
            if c <= entry * 0.98 and not tsl_active:
                tsl_active = True
                tsl_price = entry
            if tsl_active:
                tsl_price = min(tsl_price, entry - (entry - c) * 0.5)
                if h >= tsl_price: return (entry - tsl_price) / (sl - entry)
    return 0.0


def analyze_symbol(sym):
    p = Path(f"data/history/1h/{sym}.parquet")
    if not p.exists(): return []
    df = pd.read_parquet(p)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz:
        df.index = df.index.tz_localize(None)
    df.columns = [c.lower() for c in df.columns]
    df_wt = calculate_wt(df.copy(), n1=WT_N1, n2=WT_N2)
    if "wt1" not in df_wt.columns: return []
    df_wt.index = df.index
    wt1 = df_wt["wt1"].values
    wt2 = df_wt["wt2"].values

    results = []
    for i in range(LOOKBACK + 1, len(df_wt) - 50):
        ts = df.index[i]
        cross_up = wt1[i-1] < wt2[i-1] and wt1[i] > wt2[i]
        cross_down = wt1[i-1] > wt2[i-1] and wt1[i] < wt2[i]
        os_ = min(float(np.percentile(wt1[max(0,i-200):i+1], 10)), OS_FLOOR)
        ob_ = max(float(np.percentile(wt1[max(0,i-200):i+1], 90)), OB_FLOOR)

        if cross_up and wt1[i] < os_:
            window = list(wt1[i - LOOKBACK:i])
            d = _bullish_div(window, os_)
            if d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX:
                R = simulate(df, i, "LONG")
                results.append({"ts": ts, "dir": "LONG", "R": R, "div_str": d["div_strength"]})

        if cross_down and wt1[i] > ob_:
            window = list(wt1[i - LOOKBACK:i])
            d = _bearish_div(window, ob_)
            if d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX:
                R = simulate(df, i, "SHORT")
                results.append({"ts": ts, "dir": "SHORT", "R": R, "div_str": d["div_strength"]})

    return results


# Run
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
all_rows = []
for sym in SYMS:
    rows = analyze_symbol(sym)
    all_rows += [{"sym": sym, **r} for r in rows]

df = pd.DataFrame(all_rows)
print(f"Total signals: {len(df)} (LONG={len(df[df['dir']=='LONG'])}, SHORT={len(df[df['dir']=='SHORT'])})")

# By period and direction
for pname, (t0, t1) in PERIODS.items():
    sub = df[(df['ts'] >= t0) & (df['ts'] <= t1)]
    if len(sub) < 5: continue
    long_sub = sub[sub['dir'] == 'LONG']
    short_sub = sub[sub['dir'] == 'SHORT']
    la = long_sub['R'].mean() if len(long_sub) else 0
    sa = short_sub['R'].mean() if len(short_sub) else 0
    lw = (long_sub['R'] > 0).mean() * 100 if len(long_sub) else 0
    sw = (short_sub['R'] > 0).mean() * 100 if len(short_sub) else 0
    delta = la - sa
    verdict = ""
    if len(long_sub) >= 5 and len(short_sub) >= 5:
        if la > 0.1 and sa > 0.1:
            verdict = "BOTH OK"
        elif la > 0.1 and sa < 0:
            verdict = "LONG WINS"
        elif sa > 0.1 and la < 0:
            verdict = "SHORT WINS"
        elif la < 0 and sa < 0:
            verdict = "BOTH LOSS"
    print(f"\n{pname}: n={len(sub)}")
    print(f"  LONG : n={len(long_sub):>3d} avgR={la:>+7.3f} WR={lw:>5.0f}%")
    print(f"  SHORT: n={len(short_sub):>3d} avgR={sa:>+7.3f} WR={sw:>5.0f}%")
    if verdict:
        print(f"  VERDICT: {verdict}")

# Summary by market type
print("\n=== AGGREGATE ===")
for label, periods in [("BULL", ["BULL 2024 Q1", "BULL 2024 Q4", "BULL 2025 Q1"]),
                         ("BEAR", ["BEAR 2024 Q2-Q3", "BEAR 2025 Q1-Q2", "BEAR 2026 Q2"])]:
    mask = pd.Series(False, index=df.index)
    for pname in periods:
        t0, t1 = PERIODS[pname]
        mask |= (df['ts'] >= t0) & (df['ts'] <= t1)
    sub = df[mask]
    long_sub = sub[sub['dir'] == 'LONG']
    short_sub = sub[sub['dir'] == 'SHORT']
    la = long_sub['R'].mean() if len(long_sub) else 0
    sa = short_sub['R'].mean() if len(short_sub) else 0
    print(f"{label}: LONG n={len(long_sub)} avgR={la:+.3f} | SHORT n={len(short_sub)} avgR={sa:+.3f}")
