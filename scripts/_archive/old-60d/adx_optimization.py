"""ADX оптимизация + альтернативы + arch104."""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from pathlib import Path
from backtest_wt_b_ltf_entry import HIST_1H, HIST_15M

# ═══════════════════════════════════════════════════════════════
# Trend strength indicators
# ═══════════════════════════════════════════════════════════════

def _adx(df, period=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.Series(np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1)))), index=df.index)
    atr = tr.ewm(span=period).mean()
    up = h.diff(); dn = -l.diff()
    up[up < 0] = 0; dn[dn < 0] = 0
    atr_safe = atr.replace(0, np.nan)
    pdi = (up.ewm(span=period).mean() / atr_safe * 100).fillna(0)
    ndi = (dn.ewm(span=period).mean() / atr_safe * 100).fillna(0)
    dx = abs(pdi - ndi) / (pdi + ndi + 1e-10) * 100
    return float(dx.ewm(span=period).mean().iloc[-1])

def _choppiness(df, period=14):
    """Choppiness Index: 0-100. >61.8 = choppy (боковик). <38.2 = trending."""
    hh = df['high'].rolling(period).max()
    ll = df['low'].rolling(period).min()
    tr = pd.Series(np.maximum(
        df['high'] - df['low'],
        np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1)))
    ), index=df.index)
    atr = tr.rolling(period).mean()
    chop = 100 * np.log10(atr.sum() / (hh - ll + 1e-10).iloc[-1]) / np.log10(period) if (hh - ll + 1e-10).iloc[-1] > 0 else 50
    return float(chop)

def _aroon(df, period=25):
    """Aroon: AroonUp - AroonDown. Positive = uptrend, negative = downtrend. |value| = strength."""
    hh = df['high'].rolling(period).apply(lambda x: x.argmax())
    ll = df['low'].rolling(period).apply(lambda x: x.argmin())
    up = (period - hh.iloc[-1]) / period * 100
    dn = (period - ll.iloc[-1]) / period * 100
    return float(up - dn)

def _std_ratio(df, period=20):
    """StdDev returns / ATR = normalized volatility."""
    ret = df['close'].pct_change()
    return float(ret.tail(period).std() / (df['high'] - df['low']).tail(period).mean() * 100)

# ═══════════════════════════════════════════════════════════════
# Quick indicator test: avgR by indicator zone (on synthetic entries)
# ═══════════════════════════════════════════════════════════════

SYMS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ADAUSDT', 'BNBUSDT']
results = []

for sym in SYMS:
    p1h = HIST_1H / f"{sym}.parquet"
    if not p1h.exists():
        continue
    df = pd.read_parquet(p1h)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz:
        df.index = df.index.tz_localize(None)
    df.columns = [c.lower() for c in df.columns]

    for i in range(200, len(df) - 20, 30):
        entry = float(df['close'].iloc[i])
        sl_window = df.iloc[max(0, i - 80):i + 1]
        ind_window = df.iloc[max(0, i - 60):i + 1]
        if len(ind_window) < 20:
            continue

        adx_val = _adx(ind_window)
        chop_val = _choppiness(ind_window)
        aroon_val = _aroon(ind_window)
        aroon_strength = abs(aroon_val)
        std_val = _std_ratio(ind_window)

        # Forward return (4h)
        fut = float(df['close'].iloc[min(i + 4, len(df) - 1)])
        ret = (fut - entry) / entry * 100  # % return

        results.append({
            'sym': sym, 'adx': round(adx_val, 1), 'chop': round(chop_val, 1),
            'aroon_str': round(aroon_strength, 1), 'std_ratio': round(std_val, 2),
            'ret': round(ret, 3),
        })

dfr = pd.DataFrame(results)
print(f"Samples: {len(dfr)}")

# ═══════════════════════════════════════════════════════════════
# 1. Optimal ADX threshold
# ═══════════════════════════════════════════════════════════════
print("\n=== ADX порог (avgR для ret<max) ===")
for max_adx in [15, 20, 25, 30, 35, 999]:
    sub = dfr[dfr['adx'] < max_adx]
    a = sub['ret'].mean() if len(sub) else 0
    w = (sub['ret'] > 0).mean() * 100 if len(sub) else 0
    print(f"  ADX<{max_adx:>3d}: n={len(sub):>4d} avgRet={a:>+7.3f}% WR={w:>5.1f}%")

# ═══════════════════════════════════════════════════════════════
# 2. Alternatives to ADX
# ═══════════════════════════════════════════════════════════════
print("\n=== АЛЬТЕРНАТИВЫ ADX ===")

# Choppiness
for chop_max in [40, 50, 60, 70]:
    sub = dfr[dfr['chop'] > chop_max]
    a = sub['ret'].mean() if len(sub) else 0
    print(f"  CHOP>{chop_max}: n={len(sub):>4d} avgRet={a:>+7.3f}%")

# Aroon strength
for aroon_max in [30, 50, 70]:
    sub = dfr[dfr['aroon_str'] < aroon_max]
    a = sub['ret'].mean() if len(sub) else 0
    print(f"  AROON_str<{aroon_max}: n={len(sub):>4d} avgRet={a:>+7.3f}%")

# StdDev ratio
for std_max in [0.5, 1.0, 1.5, 2.0]:
    sub = dfr[dfr['std_ratio'] < std_max]
    a = sub['ret'].mean() if len(sub) else 0
    print(f"  STDratio<{std_max}: n={len(sub):>4d} avgRet={a:>+7.3f}%")

# ALL (no filter)
a = dfr['ret'].mean()
print(f"  NO filter: n={len(dfr):>4d} avgRet={a:>+7.3f}%")

# ═══════════════════════════════════════════════════════════════
# 3. ADX + Choppiness combo
# ═══════════════════════════════════════════════════════════════
print("\n=== COMBO ADX + CHOP ===")
for adx_th in [20, 25, 30]:
    for chop_th in [50, 60, 70]:
        sub = dfr[(dfr['adx'] < adx_th) & (dfr['chop'] > chop_th)]
        a = sub['ret'].mean() if len(sub) else 0
        print(f"  ADX<{adx_th}+CHOP>{chop_th}: n={len(sub):>4d} avgRet={a:>+7.3f}%")

# ═══════════════════════════════════════════════════════════════
# 4. Correlation between indicators and forward return
# ═══════════════════════════════════════════════════════════════
print("\n=== CORRELATION with forward return ===")
for col in ['adx', 'chop', 'aroon_str', 'std_ratio']:
    corr = dfr[col].corr(dfr['ret'])
    print(f"  corr(ret, {col}) = {corr:+.3f}")
