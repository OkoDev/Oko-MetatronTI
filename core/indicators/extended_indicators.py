"""
DEV-214 + DEV-214b + DEV-214b1-4 + DEV-214c: Extended indicators для combinator.

Добавляет к существующим ~90 flags:
  - Bollinger Bands (squeeze, bandwidth, %B)
  - Stochastic (overbought/oversold zones, crosses)
  - MACD (cross, histogram momentum)
  - Ichimoku Cloud (price vs cloud, TK cross)
  - VWAP (deviation, regress to mean signals)
  - ADX/DI+/DI- (trending vs ranging)
  - WT расширенный (3 OS/OB уровня, wt_cross_in_zone, wt1-wt2 spread)
  - WT/RSI/MFI divergences (regular + hidden × bull/bear)
  - Momentum continuous (pct_change_3b/5b/10b, acceleration, consecutive_count)

Все детекторы numpy-vectorized для max performance.
Возвращают dict[flag_name → bool/float numpy array].
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────
# Bollinger Bands
# ─────────────────────────────────────────────────────────────────────────

def detect_bollinger(df: pd.DataFrame, period: int = 20, std_mult: float = 2.0,
                    tf_label: str = "1h") -> dict:
    close = df["close"].values
    sma = pd.Series(close).rolling(period).mean().values
    std = pd.Series(close).rolling(period).std().values
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    bandwidth = (upper - lower) / sma * 100  # %
    pct_b = (close - lower) / (upper - lower)  # 0=lower, 1=upper

    # Squeeze: bandwidth < median(bandwidth) * 0.7 (готовится взрыв)
    bw_median = pd.Series(bandwidth).rolling(period * 2).median().values
    squeeze = bandwidth < bw_median * 0.7
    above_upper = close > upper
    below_lower = close < lower

    return {
        f"bb_squeeze_{tf_label}": squeeze,
        f"bb_above_upper_{tf_label}": above_upper,
        f"bb_below_lower_{tf_label}": below_lower,
        f"bb_pct_b_{tf_label}": pct_b,           # continuous
        f"bb_bandwidth_{tf_label}": bandwidth,    # continuous
    }


# ─────────────────────────────────────────────────────────────────────────
# Stochastic
# ─────────────────────────────────────────────────────────────────────────

def detect_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3,
                      tf_label: str = "1h") -> dict:
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    lowest = pd.Series(low).rolling(k_period).min().values
    highest = pd.Series(high).rolling(k_period).max().values
    k_raw = (close - lowest) / (highest - lowest + 1e-10) * 100
    k = pd.Series(k_raw).rolling(d_period).mean().values
    d = pd.Series(k).rolling(d_period).mean().values

    stoch_os = k < 20
    stoch_ob = k > 80
    n = len(df)
    cross_up = np.zeros(n, dtype=bool)
    cross_down = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
            if k[i-1] < d[i-1] and k[i] >= d[i]:
                cross_up[i] = True
            if k[i-1] >= d[i-1] and k[i] < d[i]:
                cross_down[i] = True

    return {
        f"stoch_os_{tf_label}": stoch_os,
        f"stoch_ob_{tf_label}": stoch_ob,
        f"stoch_cross_up_{tf_label}": cross_up,
        f"stoch_cross_down_{tf_label}": cross_down,
        f"stoch_k_{tf_label}": k,  # continuous
    }


# ─────────────────────────────────────────────────────────────────────────
# MACD
# ─────────────────────────────────────────────────────────────────────────

def detect_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9,
               tf_label: str = "1h") -> dict:
    close = pd.Series(df["close"].values)
    ema_fast = close.ewm(span=fast, adjust=False).mean().values
    ema_slow = close.ewm(span=slow, adjust=False).mean().values
    macd = ema_fast - ema_slow
    sig = pd.Series(macd).ewm(span=signal, adjust=False).mean().values
    hist = macd - sig

    n = len(df)
    cross_up = np.zeros(n, dtype=bool)
    cross_down = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if macd[i-1] < sig[i-1] and macd[i] >= sig[i]:
            cross_up[i] = True
        if macd[i-1] >= sig[i-1] and macd[i] < sig[i]:
            cross_down[i] = True

    macd_above_zero = macd > 0
    hist_rising = np.zeros(n, dtype=bool)
    hist_falling = np.zeros(n, dtype=bool)
    for i in range(2, n):
        if hist[i] > hist[i-1] > hist[i-2]:
            hist_rising[i] = True
        if hist[i] < hist[i-1] < hist[i-2]:
            hist_falling[i] = True

    return {
        f"macd_cross_up_{tf_label}": cross_up,
        f"macd_cross_down_{tf_label}": cross_down,
        f"macd_above_zero_{tf_label}": macd_above_zero,
        f"macd_hist_rising_{tf_label}": hist_rising,
        f"macd_hist_falling_{tf_label}": hist_falling,
        f"macd_hist_{tf_label}": hist,  # continuous
    }


# ─────────────────────────────────────────────────────────────────────────
# Ichimoku Cloud (упрощённо)
# ─────────────────────────────────────────────────────────────────────────

def detect_ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52,
                   tf_label: str = "1h") -> dict:
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    tenkan_line = (pd.Series(high).rolling(tenkan).max() + pd.Series(low).rolling(tenkan).min()).values / 2
    kijun_line = (pd.Series(high).rolling(kijun).max() + pd.Series(low).rolling(kijun).min()).values / 2
    senkou_a = (tenkan_line + kijun_line) / 2
    senkou_b_line = (pd.Series(high).rolling(senkou_b).max() + pd.Series(low).rolling(senkou_b).min()).values / 2
    # Сдвигаем cloud в будущее на kijun periods — но для backtesting используем то что было kijun назад
    senkou_a_shifted = np.concatenate([np.full(kijun, np.nan), senkou_a[:-kijun]])
    senkou_b_shifted = np.concatenate([np.full(kijun, np.nan), senkou_b_line[:-kijun]])

    cloud_top = np.maximum(senkou_a_shifted, senkou_b_shifted)
    cloud_bot = np.minimum(senkou_a_shifted, senkou_b_shifted)

    above_cloud = close > cloud_top
    below_cloud = close < cloud_bot
    in_cloud = (close >= cloud_bot) & (close <= cloud_top)
    cloud_bullish = senkou_a_shifted > senkou_b_shifted

    # TK cross
    n = len(df)
    tk_cross_up = np.zeros(n, dtype=bool)
    tk_cross_down = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(tenkan_line[i-1]) and not np.isnan(kijun_line[i-1]):
            if tenkan_line[i-1] < kijun_line[i-1] and tenkan_line[i] >= kijun_line[i]:
                tk_cross_up[i] = True
            if tenkan_line[i-1] >= kijun_line[i-1] and tenkan_line[i] < kijun_line[i]:
                tk_cross_down[i] = True

    return {
        f"ichi_above_cloud_{tf_label}": above_cloud,
        f"ichi_below_cloud_{tf_label}": below_cloud,
        f"ichi_in_cloud_{tf_label}": in_cloud,
        f"ichi_cloud_bullish_{tf_label}": cloud_bullish,
        f"ichi_tk_cross_up_{tf_label}": tk_cross_up,
        f"ichi_tk_cross_down_{tf_label}": tk_cross_down,
    }


# ─────────────────────────────────────────────────────────────────────────
# VWAP (anchored daily)
# ─────────────────────────────────────────────────────────────────────────

def detect_vwap(df: pd.DataFrame, tf_label: str = "1h") -> dict:
    """Daily-anchored VWAP."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    volume = df["volume"].values if "volume" in df.columns else np.ones(len(df))

    tp = (high + low + close) / 3
    pv = tp * volume

    # Daily anchor — reset на новый день
    idx = df.index
    day_change = np.zeros(len(df), dtype=bool)
    if hasattr(idx, "date"):
        prev_date = None
        for i, ts in enumerate(idx):
            current_date = ts.date()
            if current_date != prev_date:
                day_change[i] = True
                prev_date = current_date

    cum_pv = np.zeros(len(df))
    cum_v = np.zeros(len(df))
    running_pv = 0.0
    running_v = 0.0
    for i in range(len(df)):
        if day_change[i]:
            running_pv = 0.0
            running_v = 0.0
        running_pv += pv[i]
        running_v += volume[i]
        cum_pv[i] = running_pv
        cum_v[i] = running_v

    vwap = cum_pv / np.where(cum_v > 0, cum_v, 1)
    vwap_dev_pct = (close - vwap) / vwap * 100

    return {
        f"above_vwap_{tf_label}": close > vwap,
        f"below_vwap_{tf_label}": close < vwap,
        f"vwap_dev_pct_{tf_label}": vwap_dev_pct,  # continuous
        f"vwap_extreme_above_{tf_label}": vwap_dev_pct > 2.0,    # >2% over VWAP
        f"vwap_extreme_below_{tf_label}": vwap_dev_pct < -2.0,
    }


# ─────────────────────────────────────────────────────────────────────────
# ADX / DI+ / DI-
# ─────────────────────────────────────────────────────────────────────────

def detect_adx(df: pd.DataFrame, period: int = 14, tf_label: str = "1h") -> dict:
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    # +DM / -DM
    up_move = np.diff(high, prepend=high[0])
    down_move = -np.diff(low, prepend=low[0])
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    # TR
    tr1 = high - low
    tr2 = np.abs(high - np.roll(close, 1))
    tr3 = np.abs(low - np.roll(close, 1))
    tr = np.maximum(np.maximum(tr1, tr2), tr3)
    tr[0] = tr1[0]

    # Smoothed
    atr = pd.Series(tr).ewm(span=period, adjust=False).mean().values
    plus_di = 100 * pd.Series(plus_dm).ewm(span=period, adjust=False).mean().values / (atr + 1e-10)
    minus_di = 100 * pd.Series(minus_dm).ewm(span=period, adjust=False).mean().values / (atr + 1e-10)

    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = pd.Series(dx).ewm(span=period, adjust=False).mean().values

    return {
        f"adx_strong_trend_{tf_label}": adx > 25,
        f"adx_very_strong_trend_{tf_label}": adx > 40,
        f"adx_range_{tf_label}": adx < 20,
        f"di_plus_dominant_{tf_label}": plus_di > minus_di,
        f"di_minus_dominant_{tf_label}": minus_di > plus_di,
        f"adx_value_{tf_label}": adx,  # continuous
    }


# ─────────────────────────────────────────────────────────────────────────
# WT расширенный (3 уровня OS/OB + spread)
# ─────────────────────────────────────────────────────────────────────────

def detect_wt_extended(df: pd.DataFrame, n1: int = 10, n2: int = 21,
                      tf_label: str = "1h") -> dict:
    """Расширенный WT — три уровня OS/OB + cross_in_zone + spread."""
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    esa = hlc3.ewm(span=n1, adjust=False).mean()
    d = (hlc3 - esa).abs().ewm(span=n1, adjust=False).mean()
    ci = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ci.ewm(span=n2, adjust=False).mean().values
    wt2 = pd.Series(wt1).ewm(span=4, adjust=False).mean().values

    # Три уровня
    wt_extreme_os = wt1 < -80
    wt_deep_os = (wt1 >= -80) & (wt1 < -60)
    wt_mild_os = (wt1 >= -60) & (wt1 < -30)
    wt_extreme_ob = wt1 > 80
    wt_deep_ob = (wt1 <= 80) & (wt1 > 60)
    wt_mild_ob = (wt1 <= 60) & (wt1 > 30)

    # WT cross
    n = len(df)
    wt_cross_up = np.zeros(n, dtype=bool)
    wt_cross_down = np.zeros(n, dtype=bool)
    wt_cross_in_os = np.zeros(n, dtype=bool)
    wt_cross_in_ob = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if wt1[i-1] < wt2[i-1] and wt1[i] >= wt2[i]:
            wt_cross_up[i] = True
            if wt1[i] < -50:
                wt_cross_in_os[i] = True
        if wt1[i-1] >= wt2[i-1] and wt1[i] < wt2[i]:
            wt_cross_down[i] = True
            if wt1[i] > 50:
                wt_cross_in_ob[i] = True

    wt_spread = wt1 - wt2

    return {
        f"wt_extreme_os_{tf_label}": wt_extreme_os,
        f"wt_deep_os_{tf_label}": wt_deep_os,
        f"wt_mild_os_{tf_label}": wt_mild_os,
        f"wt_extreme_ob_{tf_label}": wt_extreme_ob,
        f"wt_deep_ob_{tf_label}": wt_deep_ob,
        f"wt_mild_ob_{tf_label}": wt_mild_ob,
        f"wt_cross_in_os_{tf_label}": wt_cross_in_os,
        f"wt_cross_in_ob_{tf_label}": wt_cross_in_ob,
        f"wt1_value_{tf_label}": wt1,  # continuous
        f"wt_spread_{tf_label}": wt_spread,  # continuous
    }


# ─────────────────────────────────────────────────────────────────────────
# Divergences (regular + hidden × bull/bear) for any oscillator
# ─────────────────────────────────────────────────────────────────────────

def detect_divergences(close: np.ndarray, oscillator: np.ndarray, lookback: int = 20,
                      indicator_name: str = "wt", tf_label: str = "1h") -> dict:
    """4 типа divergence × indicator."""
    n = len(close)
    regular_bull = np.zeros(n, dtype=bool)
    regular_bear = np.zeros(n, dtype=bool)
    hidden_bull = np.zeros(n, dtype=bool)
    hidden_bear = np.zeros(n, dtype=bool)

    for i in range(lookback + 5, n):
        # Найдём 2 swing lows и 2 swing highs в окне
        win_close = close[i-lookback:i+1]
        win_osc = oscillator[i-lookback:i+1]
        if np.isnan(win_osc).any():
            continue

        # Swing low indices (local min)
        idx_low_global = int(np.argmin(win_close))
        idx_high_global = int(np.argmax(win_close))

        # Текущий бар = "вторая" точка дивергенции
        # Сравнить с найденной первой
        if idx_low_global < lookback - 5:
            # Regular bull: price LL, indicator HL
            if close[i] < win_close[idx_low_global] and oscillator[i] > win_osc[idx_low_global]:
                regular_bull[i] = True
            # Hidden bull: price HL, indicator LL
            if close[i] > win_close[idx_low_global] and oscillator[i] < win_osc[idx_low_global]:
                hidden_bull[i] = True

        if idx_high_global < lookback - 5:
            # Regular bear: price HH, indicator LH
            if close[i] > win_close[idx_high_global] and oscillator[i] < win_osc[idx_high_global]:
                regular_bear[i] = True
            # Hidden bear: price LH, indicator HH
            if close[i] < win_close[idx_high_global] and oscillator[i] > win_osc[idx_high_global]:
                hidden_bear[i] = True

    return {
        f"{indicator_name}_div_bull_regular_{tf_label}": regular_bull,
        f"{indicator_name}_div_bear_regular_{tf_label}": regular_bear,
        f"{indicator_name}_div_bull_hidden_{tf_label}": hidden_bull,
        f"{indicator_name}_div_bear_hidden_{tf_label}": hidden_bear,
    }


# ─────────────────────────────────────────────────────────────────────────
# Momentum continuous
# ─────────────────────────────────────────────────────────────────────────

def detect_momentum_extended(df: pd.DataFrame, tf_label: str = "1h") -> dict:
    close = df["close"].values
    volume = df["volume"].values if "volume" in df.columns else np.ones(len(close))

    n = len(df)
    # pct_change_3b, 5b, 10b
    pct_3 = np.full(n, np.nan)
    pct_5 = np.full(n, np.nan)
    pct_10 = np.full(n, np.nan)
    for i in range(3, n):
        pct_3[i] = (close[i] - close[i-3]) / close[i-3] * 100
    for i in range(5, n):
        pct_5[i] = (close[i] - close[i-5]) / close[i-5] * 100
    for i in range(10, n):
        pct_10[i] = (close[i] - close[i-10]) / close[i-10] * 100

    # Acceleration (вторая производная)
    accel = np.full(n, np.nan)
    for i in range(6, n):
        accel[i] = pct_3[i] - pct_3[i-3] if not np.isnan(pct_3[i-3]) else np.nan

    # Consecutive count
    up_count = np.zeros(n, dtype=np.int32)
    down_count = np.zeros(n, dtype=np.int32)
    for i in range(1, n):
        if close[i] > close[i-1]:
            up_count[i] = up_count[i-1] + 1
        if close[i] < close[i-1]:
            down_count[i] = down_count[i-1] + 1

    # 5 of 8
    bull_5of8 = np.zeros(n, dtype=bool)
    bear_5of8 = np.zeros(n, dtype=bool)
    for i in range(8, n):
        up = sum(1 for j in range(i-8, i) if close[j+1] > close[j])
        if up >= 5: bull_5of8[i] = True
        if up <= 3: bear_5of8[i] = True

    # Momentum-volume divergence
    vol_sma = pd.Series(volume).rolling(20).mean().values
    mom_vol_div = np.zeros(n, dtype=bool)
    for i in range(20, n):
        if pct_5[i] > 1.0 and volume[i] < vol_sma[i] * 0.8:
            mom_vol_div[i] = True  # цена растёт, объём падает

    return {
        f"pct_3b_{tf_label}": pct_3,  # continuous
        f"pct_5b_{tf_label}": pct_5,
        f"pct_10b_{tf_label}": pct_10,
        f"mom_acceleration_{tf_label}": accel,
        f"up_count_{tf_label}": up_count.astype(np.float32),
        f"down_count_{tf_label}": down_count.astype(np.float32),
        f"bull_5of8_{tf_label}": bull_5of8,
        f"bear_5of8_{tf_label}": bear_5of8,
        f"mom_vol_div_{tf_label}": mom_vol_div,
    }


# ─────────────────────────────────────────────────────────────────────────
# Полный комбайн
# ─────────────────────────────────────────────────────────────────────────

def detect_all_extended(df: pd.DataFrame, tf_label: str = "1h") -> dict:
    """Все расширенные индикаторы — для интеграции в combinator."""
    result = {}
    result.update(detect_bollinger(df, tf_label=tf_label))
    result.update(detect_stochastic(df, tf_label=tf_label))
    result.update(detect_macd(df, tf_label=tf_label))
    result.update(detect_ichimoku(df, tf_label=tf_label))
    result.update(detect_vwap(df, tf_label=tf_label))
    result.update(detect_adx(df, tf_label=tf_label))
    result.update(detect_wt_extended(df, tf_label=tf_label))
    result.update(detect_momentum_extended(df, tf_label=tf_label))

    # WT/RSI/MFI divergences
    close = df["close"].values
    # WT
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    esa = hlc3.ewm(span=10, adjust=False).mean()
    d_ = (hlc3 - esa).abs().ewm(span=10, adjust=False).mean()
    ci = (hlc3 - esa) / (0.015 * d_.replace(0, np.nan))
    wt1 = ci.ewm(span=21, adjust=False).mean().values
    result.update(detect_divergences(close, wt1, indicator_name="wt", tf_label=tf_label))

    # RSI
    delta = pd.Series(close).diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - 100 / (1 + rs)).values
    result.update(detect_divergences(close, rsi, indicator_name="rsi_v2", tf_label=tf_label))

    # MFI (Money Flow Index — RSI с volume)
    if "volume" in df.columns:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        mf = tp * df["volume"]
        mf_diff = tp.diff()
        pos_mf = mf.where(mf_diff > 0, 0).rolling(14).sum()
        neg_mf = mf.where(mf_diff < 0, 0).rolling(14).sum()
        mfi = 100 - 100 / (1 + pos_mf / neg_mf.replace(0, np.nan))
        result.update(detect_divergences(close, mfi.values, indicator_name="mfi", tf_label=tf_label))

    return result


# Self-test
if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass
    from pathlib import Path
    import time

    PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
    path = PROJECT_ROOT / "data" / "history" / "1h" / "BTCUSDT.parquet"
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
        df = df.set_index("ts")
    df = df[["open","high","low","close","volume"]].dropna().tail(5000)
    print(f"Test on BTC 1h, {len(df)} bars")

    t0 = time.time()
    flags = detect_all_extended(df)
    print(f"Total flags: {len(flags)} in {time.time()-t0:.1f}s")

    # Count активаций каждого bool flag
    print("\nFlags summary:")
    for name, arr in flags.items():
        if arr.dtype == bool:
            pct = arr.mean() * 100
            print(f"  {name:<40} {int(arr.sum()):>5} ({pct:>5.1f}%)")

    print("\n✅ Extended indicators OK")
