import sqlite3
import numpy as np
import pandas as pd

DB = 'e:/MTF BOT/CURSOR/crypto_volume_bot/ohlcv_cache.db'
CORE = ['ADA/USDT','AVAX/USDT','BNB/USDT','CFX/USDT','DOGE/USDT','ETH/USDT',
        'ICP/USDT','NEAR/USDT','SOL/USDT','TRX/USDT','XLM/USDT','XMR/USDT','XRP/USDT']
COST_PCT = 0.35  # % round-trip flat cost, subtracted from pnl_pct

def load(symbol, tf):
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT time, open, high, low, close FROM ohlcv_cache WHERE timeframe=? AND symbol=? ORDER BY time",
        conn, params=(tf, symbol))
    conn.close()
    df['dt'] = pd.to_datetime(df['time'], unit='ms')
    df['year'] = df['dt'].dt.year
    return df

def atr14(df):
    high = df['high'].values; low = df['low'].values; close = df['close'].values
    prev_close = np.roll(close, 1); prev_close[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = pd.Series(tr).ewm(alpha=1/14, adjust=False).mean().values
    return atr

def btc_regime(tf):
    """SMA100 regime on BTC/USDT for given tf: 1=up(close>sma100), -1=down. Returns df dt,regime."""
    df = load('BTC/USDT', tf)
    sma = df['close'].rolling(100, min_periods=50).mean()
    df['regime'] = np.where(df['close'] > sma, 1, -1)
    return df[['dt', 'regime']].dropna()

def detect_impulses(df, atr, K, M):
    """Independent ATR-threshold swing/impulse detector (NOT detect_elliott_impulse/zigzag_atr).
    Directional move >= K*ATR confirmed with <=0.5 retracement while forming, span<=M bars.
    Returns list of dicts: start_idx,start_price,extreme_idx,extreme_price,confirm_idx,dir(1/-1)
    confirm_idx = bar where we FIRST learn the leg ended (retr>0.5) -> avoids lookahead;
    trading logic must act at confirm_idx, not extreme_idx."""
    high = df['high'].tolist(); low = df['low'].tolist(); close = df['close'].tolist()
    atr_l = atr.tolist()
    n = len(close)
    out = []
    direction = 0
    leg_start_idx = 0; leg_start_price = close[0]
    run_max = high[0]; run_max_idx = 0
    run_min = low[0]; run_min_idx = 0
    extreme_price = close[0]; extreme_idx = 0
    atr_leg = atr_l[0]
    for t in range(1, n):
        if direction == 0:
            if high[t] > run_max: run_max, run_max_idx = high[t], t
            if low[t] < run_min: run_min, run_min_idx = low[t], t
            a = atr_l[t]
            if a and run_max - leg_start_price >= K * a:
                direction = 1; extreme_price, extreme_idx = run_max, run_max_idx
                atr_leg = atr_l[leg_start_idx] or a
            elif a and leg_start_price - run_min >= K * a:
                direction = -1; extreme_price, extreme_idx = run_min, run_min_idx
                atr_leg = atr_l[leg_start_idx] or a
            continue
        if direction == 1:
            if high[t] > extreme_price:
                extreme_price, extreme_idx = high[t], t
            leg_len = extreme_price - leg_start_price
            retr = (extreme_price - low[t]) / leg_len if leg_len > 0 else 0.0
            if retr > 0.5:
                span = extreme_idx - leg_start_idx
                if span <= M and leg_len >= K * atr_leg:
                    out.append(dict(start_idx=leg_start_idx, start_price=leg_start_price,
                                     extreme_idx=extreme_idx, extreme_price=extreme_price,
                                     confirm_idx=t, dir=1))
                direction = -1
                leg_start_idx, leg_start_price = extreme_idx, extreme_price
                extreme_price, extreme_idx = low[t], t
                atr_leg = atr_l[leg_start_idx]
        else:
            if low[t] < extreme_price:
                extreme_price, extreme_idx = low[t], t
            leg_len = leg_start_price - extreme_price
            retr = (high[t] - extreme_price) / leg_len if leg_len > 0 else 0.0
            if retr > 0.5:
                span = extreme_idx - leg_start_idx
                if span <= M and leg_len >= K * atr_leg:
                    out.append(dict(start_idx=leg_start_idx, start_price=leg_start_price,
                                     extreme_idx=extreme_idx, extreme_price=extreme_price,
                                     confirm_idx=t, dir=-1))
                direction = 1
                leg_start_idx, leg_start_price = extreme_idx, extreme_price
                extreme_price, extreme_idx = high[t], t
                atr_leg = atr_l[leg_start_idx]
    return out

def simulate(high, low, entry_idx, side, entry_price, stop, target, max_hold):
    """side: 1=long,-1=short. First-touch, SL priority if both hit same bar (conservative)."""
    n = len(high)
    end = min(entry_idx + max_hold, n - 1)
    for t in range(entry_idx + 1, end + 1):
        h, l = high[t], low[t]
        if side == 1:
            hit_sl = l <= stop
            hit_tp = h >= target
        else:
            hit_sl = h >= stop
            hit_tp = l <= target
        if hit_sl and hit_tp:
            return stop, 'SL', t
        if hit_sl:
            return stop, 'SL', t
        if hit_tp:
            return target, 'TP', t
    return None, 'EXPIRED', end

def pnl_pct(side, entry, exitp):
    if side == 1:
        raw = (exitp - entry) / entry * 100
    else:
        raw = (entry - exitp) / entry * 100
    return raw - COST_PCT
