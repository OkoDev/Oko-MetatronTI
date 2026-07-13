"""TSL режимы: парный бэктест на ote_nested сигналах из истории.
4 режима на ОДНИХ И ТЕХ ЖЕ точках входа. Честное сравнение.
"""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from pathlib import Path

from core.indicators.indicators import calculate_wt, find_swing_highs, find_swing_lows, calculate_n_down
from core.smc.smc_engine import build_ote, detect_structure_breaks

WT_N1, WT_N2 = 10, 21
LOOKBACK = 35
OS_FLOOR, OB_FLOOR = -30.0, 30.0
DIV_MIN, DIV_MAX = 3.0, 20.0
HIST_1H = Path("data/history/1h")

# ═══════════════════════════════════════════════════════
# Дивергенция (как в ote_signal_generator / wt_b)
# ═══════════════════════════════════════════════════════
def div_bullish(wt1_vals, os_):
    half = len(wt1_vals) // 2
    if half < 5: return {"found": False}
    os1 = [v for v in wt1_vals[:half] if v < os_]
    os2 = [v for v in wt1_vals[half:] if v < os_]
    if not os1 or not os2: return {"found": False}
    min1, min2 = min(os1), min(os2)
    if min2 <= min1: return {"found": False}
    return {"found": True, "div_strength": round(min2 - min1, 2)}

def div_bearish(wt1_vals, ob):
    half = len(wt1_vals) // 2
    if half < 5: return {"found": False}
    ob1 = [v for v in wt1_vals[:half] if v > ob]
    ob2 = [v for v in wt1_vals[half:] if v > ob]
    if not ob1 or not ob2: return {"found": False}
    max1, max2 = max(ob1), max(ob2)
    if max2 >= max1: return {"found": False}
    return {"found": True, "div_strength": round(max1 - max2, 2)}


# ═══════════════════════════════════════════════════════
# Симуляция: БЕЗ TSL (только SL + структурный TP)
# ═══════════════════════════════════════════════════════
def simulate_no_tsl(df, entry_i, direction, sl_price, tp_price, max_bars=300):
    entry = float(df['close'].iloc[entry_i])
    sl_dist = abs(entry - sl_price)
    if sl_dist < entry * 0.003: return 0.0

    for j in range(entry_i + 1, min(entry_i + max_bars, len(df))):
        h, l = float(df['high'].iloc[j]), float(df['low'].iloc[j])
        if direction == 'LONG':
            if l <= sl_price: return -1.0
            if tp_price and h >= tp_price: return abs(tp_price - entry) / sl_dist
        else:
            if h >= sl_price: return -1.0
            if tp_price and l <= tp_price: return abs(entry - tp_price) / sl_dist
    return 0.0


# ═══════════════════════════════════════════════════════
# Симуляция: С TSL (gear-based, DS-321 hybrid)
# ═══════════════════════════════════════════════════════
def simulate_with_tsl(df, entry_i, direction, sl_price, tp_price,
                       gear1_r=1.0, gear2_r=2.0, gear3_r=4.0, max_bars=300):
    entry = float(df['close'].iloc[entry_i])
    sl_dist = abs(entry - sl_price)
    if sl_dist < entry * 0.003: return 0.0

    tsl_price = sl_price
    gear = 0
    mfe_high = entry if direction == 'LONG' else entry  # max favorable excursion

    for j in range(entry_i + 1, min(entry_i + max_bars, len(df))):
        h, l, c = float(df['high'].iloc[j]), float(df['low'].iloc[j]), float(df['close'].iloc[j])

        if direction == 'LONG':
            # Update MFE
            if h > mfe_high: mfe_high = h
            mfe_r = (mfe_high - entry) / sl_dist if sl_dist > 0 else 0

            # Gear escalation
            if gear == 0 and mfe_r >= gear1_r: gear = 1
            if gear == 1 and mfe_r >= gear2_r: gear = 2
            if gear == 2 and mfe_r >= gear3_r: gear = 3

            # TSL logic
            if gear >= 1:
                tsl_price = max(tsl_price, entry + (c - entry) * (0.3 if gear == 1 else 0.5 if gear == 2 else 0.7))
            if l <= tsl_price:
                return (tsl_price - entry) / sl_dist
            # SL
            if l <= sl_price: return -1.0
            # TP
            if tp_price and h >= tp_price:
                return (tp_price - entry) / sl_dist
        else:
            if l < mfe_high: mfe_high = l
            mfe_r = (entry - mfe_high) / sl_dist if sl_dist > 0 else 0

            if gear == 0 and mfe_r >= gear1_r: gear = 1
            if gear == 1 and mfe_r >= gear2_r: gear = 2
            if gear == 2 and mfe_r >= gear3_r: gear = 3

            if gear >= 1:
                tsl_price = min(tsl_price, entry - (entry - c) * (0.3 if gear == 1 else 0.5 if gear == 2 else 0.7))
            if h >= tsl_price:
                return (entry - tsl_price) / sl_dist
            if h >= sl_price: return -1.0
            if tp_price and l <= tp_price:
                return (entry - tp_price) / sl_dist

    return 0.0


# ═══════════════════════════════════════════════════════
# Поиск OTE сетапов как в ote_signal_generator
# ═══════════════════════════════════════════════════════
def find_ote_signals(df1h):
    """Сканирует 1h на WT divergence + OTE zone. Возвращает список сигналов."""
    if len(df1h) < 80: return []
    df_wt = calculate_wt(df1h.copy(), n1=WT_N1, n2=WT_N2)
    if "wt1" not in df_wt.columns: return []
    df_wt.index = df1h.index
    wt1, wt2 = df_wt["wt1"].values, df_wt["wt2"].values
    signals = []

    for i in range(LOOKBACK + 1, len(df_wt) - 50):
        cross_up = wt1[i-1] < wt2[i-1] and wt1[i] > wt2[i]
        cross_down = wt1[i-1] > wt2[i-1] and wt1[i] < wt2[i]
        os_ = min(float(np.percentile(wt1[max(0, i-200):i+1], 10)), OS_FLOOR)
        ob_ = max(float(np.percentile(wt1[max(0, i-200):i+1], 90)), OB_FLOOR)

        # LONG
        if cross_up and wt1[i] < os_:
            window = list(wt1[i - LOOKBACK:i])
            d = div_bullish(window, os_)
            if not (d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX): continue
            # SL = swing low (как в ote)
            sl_df = df1h.iloc[max(0, i-40):i+1]
            swing_lows = find_swing_lows(sl_df['low'], period=5)
            if not swing_lows: continue
            sl_price = swing_lows[-1]['value']
            entry = float(df1h['close'].iloc[i])
            sl_dist = entry - sl_price
            if sl_dist < entry * 0.005: continue  # min SL 0.5%
            tp_price = entry + sl_dist * 3.0  # структурный TP proxy (RR=3)
            signals.append({"ts": df1h.index[i], "dir": "LONG", "entry": entry, "sl": sl_price, "tp": tp_price})

        # SHORT
        if cross_down and wt1[i] > ob_:
            window = list(wt1[i - LOOKBACK:i])
            d = div_bearish(window, ob_)
            if not (d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX): continue
            sl_df = df1h.iloc[max(0, i-40):i+1]
            swing_highs = find_swing_highs(sl_df['high'], period=5)
            if not swing_highs: continue
            sl_price = swing_highs[-1]['value']
            entry = float(df1h['close'].iloc[i])
            sl_dist = sl_price - entry
            if sl_dist < entry * 0.005: continue
            tp_price = entry - sl_dist * 3.0
            signals.append({"ts": df1h.index[i], "dir": "SHORT", "entry": entry, "sl": sl_price, "tp": tp_price})

    return signals


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════
def run(n_symbols=15):
    syms = sorted({p.stem for p in HIST_1H.glob("*.parquet")})[:n_symbols]
    all_signals = []

    for sym in syms:
        p = HIST_1H / f"{sym}.parquet"
        if not p.exists(): continue
        df = pd.read_parquet(p)
        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz:
            df.index = df.index.tz_localize(None)
        df.columns = [c.lower() for c in df.columns]
        signals = find_ote_signals(df)
        for s in signals:
            s["sym"] = sym
            s["df"] = df
        all_signals += signals

    print(f"OTE signals: {len(all_signals)} (LONG={sum(1 for s in all_signals if s['dir']=='LONG')}, SHORT={sum(1 for s in all_signals if s['dir']=='SHORT')})")

    # 4 режима TSL на ОДНИХ И ТЕХ ЖЕ сигналах
    configs = {
        "NO_TSL":       {"tsl": False, "g1": 0, "g2": 0, "g3": 0},
        "TSL_1_2_4":    {"tsl": True,  "g1": 1.0, "g2": 2.0, "g3": 4.0},
        "TSL_3_5_8":    {"tsl": True,  "g1": 3.0, "g2": 5.0, "g3": 8.0},
        "TSL_GEAR3":    {"tsl": True,  "g1": 9.0, "g2": 9.0, "g3": 3.0},  # только gear3
    }

    results = {}
    for name, cfg in configs.items():
        R_list = []
        for s in all_signals:
            df = s["df"]
            bar_i = df.index.get_loc(s["ts"])
            if cfg["tsl"]:
                R = simulate_with_tsl(df, bar_i, s["dir"], s["sl"], s["tp"],
                                       gear1_r=cfg["g1"], gear2_r=cfg["g2"], gear3_r=cfg["g3"])
            else:
                R = simulate_no_tsl(df, bar_i, s["dir"], s["sl"], s["tp"])
            R_list.append(R)
        arr = np.array(R_list)
        results[name] = {"avgR": np.mean(arr), "WR": (arr > 0).mean() * 100, "sumR": np.sum(arr),
                         "medR": np.median(arr), "n": len(arr)}
        print(f"  {name:15s}: n={len(arr):>4d} avgR={np.mean(arr):>+7.3f} WR={(arr>0).mean()*100:>5.1f}% sumR={np.sum(arr):>+8.1f}")

    # PAIRED: TSL_1_2_4 vs NO_TSL
    no_arr = np.array([results["NO_TSL"]["avgR"]] * len(all_signals))
    tsl_arr = np.array([simulate_with_tsl(s["df"], s["df"].index.get_loc(s["ts"]), s["dir"], s["sl"], s["tp"]) for s in all_signals])
    
    print(f"\n=== PAIRED (TSL_1_2_4 vs NO_TSL) ===")
    delta = tsl_arr - np.array([simulate_no_tsl(s["df"], s["df"].index.get_loc(s["ts"]), s["dir"], s["sl"], s["tp"]) for s in all_signals])
    better = (delta > 0).sum()
    worse = (delta < 0).sum()
    same = (delta == 0).sum()
    print(f"  TSL better: {better}  worse: {worse}  same: {same}")
    print(f"  Avg delta: {np.mean(delta):+.3f}R")
    
    # By R outcome
    print(f"\n=== By outcome with NO_TSL ===")
    no_R = np.array([simulate_no_tsl(s["df"], s["df"].index.get_loc(s["ts"]), s["dir"], s["sl"], s["tp"]) for s in all_signals])
    for lo, hi, label in [(-999, -0.5, "LOSS <-0.5R"), (-0.5, 0, "small loss"), (0, 1, "0-1R"), (1, 3, "1-3R"), (3, 5, "3-5R"), (5, 999, "5R+ ROCKET")]:
        mask = (no_R > lo) & (no_R <= hi)
        if mask.sum() < 3: continue
        delta_sub = delta[mask]
        print(f"  {label:15s}: n={mask.sum():>3d} TSL_delta={np.mean(delta_sub):>+7.3f} better={sum(delta_sub>0)} worse={sum(delta_sub<0)}")


if __name__ == "__main__":
    run(n_symbols=15)
