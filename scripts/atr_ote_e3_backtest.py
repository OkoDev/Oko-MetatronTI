"""ATR-OTE-E3: бэктест полной OTE-конверсии vs текущий прямой вход."""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from pathlib import Path

from core.indicators.indicators import calculate_trend, find_swing_highs, find_swing_lows
from core.smc.smc_engine import build_ote, detect_structure_breaks
from core.signals.atr_change_detector import ATRChangeDetector

ATR_PERIOD, ATR_FACTOR = 43, 1.25
R_HIST = Path("data/history")

# ═══════════════════════════════════════════════════════
# Variant A: текущий (entry=price, SL=trendline)
# ═══════════════════════════════════════════════════════
def simulate_A(df, bar_i, direction, ev_price, trendline, rr=3.0, max_bars=300):
    entry = ev_price
    if direction == 'LONG':
        sl = trendline if trendline and trendline < entry else entry * 0.98
    else:
        sl = trendline if trendline and trendline > entry else entry * 1.02
    sl_dist = abs(entry - sl)
    if sl_dist < entry * 0.003: return 0
    tp = entry + sl_dist * rr if direction == 'LONG' else entry - sl_dist * rr
    for j in range(bar_i + 1, min(bar_i + max_bars, len(df))):
        h, l = float(df['high'].iloc[j]), float(df['low'].iloc[j])
        if direction == 'LONG':
            if l <= sl: return -1.0
            if h >= tp: return rr
        else:
            if h >= sl: return -1.0
            if l <= tp: return rr
    return 0.0


# ═══════════════════════════════════════════════════════
# Variant B (Э3): entry=mid-OTE, SL=swing extreme (1.0 нога)
# ═══════════════════════════════════════════════════════
def find_ote_zone(df, bar_i, tf='1h'):
    """Ищет последний значимый CHoCH и строит OTE зону."""
    sl = df.iloc[max(0, bar_i - 200):bar_i + 1]
    if len(sl) < 50: return None

    # Для 4h TF — ресемплим
    if tf == '4h':
        d4 = sl.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
        if len(d4) < 20: return None
        work_df = d4
    else:
        work_df = sl

    # Ищем CHoCH
    breaks = detect_structure_breaks(work_df, length=5)
    choch = [b for b in breaks if b.kind == 'CHoCH']
    if not choch: return None

    last_choch = choch[-1]
    # Найти swing точки до CHoCH
    idx = last_choch.idx
    pre = work_df.iloc[max(0, idx - 40):idx + 1]
    if len(pre) < 10: return None

    sh = find_swing_highs(pre['high'], period=5)
    sl_sw = find_swing_lows(pre['low'], period=5)
    if len(sh) < 1 or len(sl_sw) < 1: return None

    # Направление CHoCH определяет пару swing_a → swing_b
    if last_choch.direction == 'bull':
        swing_a, swing_b = sl_sw[-1]['value'], sh[-1]['value']
    else:
        swing_a, swing_b = sh[-1]['value'], sl_sw[-1]['value']

    if swing_a == swing_b: return None
    ote = build_ote(swing_a, swing_b)
    return ote


def simulate_B(df, bar_i, direction, ote_zone, rr=3.0, max_bars=300):
    """Э3: entry=mid-OTE, SL=swing extreme."""
    ote_lo, ote_hi = ote_zone['ote']
    entry = (ote_lo + ote_hi) / 2  # mid-OTE

    # Проверяем что цена в OTE зоне
    current_price = float(df['close'].iloc[bar_i])
    if not (ote_lo <= current_price <= ote_hi):
        return None  # сигнал вне OTE — не входим

    # SL = за 1.0 ногу (swing extreme = начало импульса)
    levels = ote_zone['levels']
    sl = levels[1.0]  # swing_b = конец импульса = 1.0 fib
    sl_dist = abs(entry - sl)
    if sl_dist < entry * 0.003: return None

    # Проверка направления
    ote_dir = ote_zone['direction']  # 'long' или 'short'
    atr_dir = direction.lower()  # 'LONG' → 'long'
    if ote_dir != atr_dir: return None  # направление OTE не совпадает с atr_change

    tp = entry + sl_dist * rr if atr_dir == 'long' else entry - sl_dist * rr

    # Симулируем от текущего бара
    for j in range(bar_i + 1, min(bar_i + max_bars, len(df))):
        h, l = float(df['high'].iloc[j]), float(df['low'].iloc[j])
        if atr_dir == 'long':
            if l <= sl: return -1.0
            if h >= tp: return rr
        else:
            if h >= sl: return -1.0
            if l <= tp: return rr
    return 0.0


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════
def run(symbols_limit=20):
    syms_1h = {p.stem for p in (R_HIST / "1h").glob("*.parquet")}
    symbols = sorted(syms_1h)[:symbols_limit]

    detector = ATRChangeDetector(atr_period=ATR_PERIOD, factor=ATR_FACTOR)
    results = []

    for sym in symbols:
        p1h = R_HIST / "1h" / f"{sym}.parquet"
        p15m = R_HIST / "15m" / f"{sym}.parquet"
        if not p1h.exists(): continue

        df1h = pd.read_parquet(p1h)
        if isinstance(df1h.index, pd.DatetimeIndex) and df1h.index.tz:
            df1h.index = df1h.index.tz_localize(None)
        df1h.columns = [c.lower() for c in df1h.columns]

        df15m = None
        if p15m.exists():
            df15m = pd.read_parquet(p15m)
            if isinstance(df15m.index, pd.DatetimeIndex) and df15m.index.tz:
                df15m.index = df15m.index.tz_localize(None)
            df15m.columns = [c.lower() for c in df15m.columns]

        # Calculate trend for 1h and 4h (resampled)
        df1h_t = calculate_trend(df1h.copy(), atr_period=ATR_PERIOD, factor=ATR_FACTOR)
        df1h_t.index = df1h.index

        d4 = df1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
        df4h_t = calculate_trend(d4.copy(), atr_period=ATR_PERIOD, factor=ATR_FACTOR)
        df4h_t.index = d4.index

        # Scan 1h and 4h
        for tf, df_t, df_raw in [('1h', df1h_t, df1h), ('4h', df4h_t, d4)]:
            for i in range(50, len(df_raw) - 50):
                ev = detector.detect(sym, tf, df_t.iloc[max(0, i-5):i+1])
                if ev is None: continue

                direction = 'LONG' if ev.side == 'UP' else 'SHORT'
                trendline = ev.trendline

                # Variant A
                R_A = simulate_A(df_raw, i, direction, ev.price, trendline)

                # Variant B (Э3)
                ote = find_ote_zone(df_raw if tf == '1h' else d4, i, tf)
                R_B = simulate_B(df_raw, i, direction, ote) if ote else None

                results.append({
                    'sym': sym, 'tf': tf, 'dir': direction, 'ts': df_raw.index[i],
                    'R_A': R_A, 'R_B': R_B if R_B is not None else 999,  # 999 = no OTE
                })

    dfr = pd.DataFrame(results)
    print(f"Signals: {len(dfr)}")

    # Variant A stats
    a_arr = dfr['R_A'].values
    print(f"\n=== Variant A (current: entry=price, SL=trendline) ===")
    print(f"  n={len(a_arr)} avgR={np.mean(a_arr):+.3f} WR={(a_arr>0).mean()*100:.1f}% sumR={np.sum(a_arr):+.1f}")

    # Variant B (with OTE zone)
    b_mask = dfr['R_B'] != 999
    b_arr = dfr.loc[b_mask, 'R_B'].values
    print(f"\n=== Variant B (OTE entry=mid-OTE, SL=swing extreme) ===")
    print(f"  n={len(b_arr)} avgR={np.mean(b_arr):+.3f} WR={(b_arr>0).mean()*100:.1f}% sumR={np.sum(b_arr):+.1f}")
    print(f"  OTE coverage: {b_mask.sum()}/{len(dfr)} ({b_mask.mean()*100:.0f}%)")

    # By TF
    for tf in ['1h', '4h']:
        sub = dfr[dfr['tf'] == tf]
        print(f"\n  {tf}: A n={len(sub)} avgR={sub['R_A'].mean():+.3f} | B OTE={sum(sub['R_B']!=999)} avgR={sub.loc[sub['R_B']!=999,'R_B'].mean():+.3f}")

    # Both A and B on same trades (where OTE exists)
    both = dfr[b_mask].copy()
    print(f"\n=== Paried comparison (n={len(both)}) ===")
    print(f"  A: avgR={both['R_A'].mean():+.3f} WR={(both['R_A']>0).mean()*100:.1f}% sumR={both['R_A'].sum():+.1f}")
    print(f"  B: avgR={both['R_B'].mean():+.3f} WR={(both['R_B']>0).mean()*100:.1f}% sumR={both['R_B'].sum():+.1f}")
    better = (both['R_B'] > both['R_A']).sum()
    print(f"  B better than A: {better}/{len(both)} ({better/len(both)*100:.0f}%)")


if __name__ == "__main__":
    run(symbols_limit=20)
