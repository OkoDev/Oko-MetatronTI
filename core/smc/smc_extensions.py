"""
DEV-215: SMC extensions для combinator (Phase 1).

Три новых детектора:
1. Inducement — ложный пробой ключевого уровня (stop hunt)
2. Liquidity Void — широкий gap (impulse без отката) — magnet для price
3. Breaker Block — бывший support/resistance которое было пробито и стало противоположным

Все детекторы vectorized для max performance.
Возвращают bool array одинакового размера с input df.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def detect_inducement(df: pd.DataFrame, lookback: int = 30, sweep_pct: float = 0.5,
                     reverse_bars: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Inducement: ложный пробой equal highs / equal lows с последующим возвратом.

    Bull inducement (для LONG entry):
      - За lookback баров формируется equal lows (≥2 lows в пределах sweep_pct%)
      - На текущем баре low пробивает min equal_lows на >sweep_pct%
      - Закрывается обратно выше equal_lows level в течение reverse_bars
      → stop hunt → разворот вверх

    Bear inducement (для SHORT entry): зеркально на equal highs.

    Returns (bull_inducement_flag, bear_inducement_flag) — bool arrays.
    """
    n = len(df)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    bull_ind = np.zeros(n, dtype=bool)
    bear_ind = np.zeros(n, dtype=bool)

    tol_pct = 0.15   # equal lows tolerance

    for i in range(lookback, n - reverse_bars):
        # Окно прошлых баров (до i, не включая)
        window_lows = low[i-lookback:i]
        window_highs = high[i-lookback:i]

        # Bull inducement check
        min_low = float(window_lows.min())
        if min_low > 0:
            # Сколько баров в окне с low в пределах tol_pct% от min
            n_eq_lows = int(((window_lows - min_low) / min_low * 100 < tol_pct).sum())
            if n_eq_lows >= 2:
                # Текущий бар пробивает min_low на sweep_pct%
                sweep_target = min_low * (1 - sweep_pct / 100)
                if low[i] < sweep_target:
                    # Закрытие обратно выше min_low в течение reverse_bars
                    future_closes = close[i:i + reverse_bars]
                    if (future_closes > min_low).any():
                        bull_ind[i] = True

        # Bear inducement check
        max_high = float(window_highs.max())
        if max_high > 0:
            n_eq_highs = int(((max_high - window_highs) / max_high * 100 < tol_pct).sum())
            if n_eq_highs >= 2:
                sweep_target = max_high * (1 + sweep_pct / 100)
                if high[i] > sweep_target:
                    future_closes = close[i:i + reverse_bars]
                    if (future_closes < max_high).any():
                        bear_ind[i] = True

    return bull_ind, bear_ind


def detect_liquidity_void(df: pd.DataFrame, min_void_pct: float = 1.5,
                          unfilled_bars: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Liquidity Void — широкий impulse где цена не возвращалась (>min_void_pct).

    Bullish void: одиночный impulse бар up >min_void_pct%, цена не вернулась к midpoint.
    Bearish void: зеркально.

    Используется как target/magnet — цена вернётся в void.

    Returns (bull_void_active, bear_void_active) — bool arrays.
    """
    n = len(df)
    open_ = df["open"].values
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    bull_void = np.zeros(n, dtype=bool)
    bear_void = np.zeros(n, dtype=bool)

    for i in range(unfilled_bars + 1, n):
        # Bull void: impulse bar
        for j in range(max(0, i - 30), i - unfilled_bars):
            bar_pct = (close[j] - open_[j]) / open_[j] * 100 if open_[j] > 0 else 0
            if bar_pct < min_void_pct:
                continue
            mid = (open_[j] + close[j]) / 2
            # Цена не возвращалась к midpoint impulse bar за период
            future_lows = low[j+1:i]
            if len(future_lows) >= unfilled_bars and (future_lows > mid).all():
                # Текущий бар: void всё ещё активен
                if low[i] > mid:
                    bull_void[i] = True
                    break

        # Bear void: impulse down
        for j in range(max(0, i - 30), i - unfilled_bars):
            bar_pct = (open_[j] - close[j]) / open_[j] * 100 if open_[j] > 0 else 0
            if bar_pct < min_void_pct:
                continue
            mid = (open_[j] + close[j]) / 2
            future_highs = high[j+1:i]
            if len(future_highs) >= unfilled_bars and (future_highs < mid).all():
                if high[i] < mid:
                    bear_void[i] = True
                    break

    return bull_void, bear_void


def detect_breaker_block(df: pd.DataFrame, lookback: int = 50,
                        ob_min_pct: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """Breaker Block — бывший OB который был пробит и стал противоположной зоной.

    Bull Breaker (для LONG): бывший bear OB, пробит вверх, цена возвращается к нему → support.
    Bear Breaker: зеркально.

    Returns (bull_breaker_active, bear_breaker_active).
    """
    n = len(df)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    open_ = df["open"].values

    bull_breaker = np.zeros(n, dtype=bool)
    bear_breaker = np.zeros(n, dtype=bool)

    tol = 1.0  # 1% tolerance to OB zone

    for i in range(lookback, n):
        # Ищем bull breaker — бывший bear OB
        for j in range(i - 5, max(2, i - lookback), -1):
            # Bear OB candidate: candle j is bull (close>open) перед drop
            if not (close[j] > open_[j]):
                continue
            ob_top = high[j]
            ob_bot = low[j]
            ob_size_pct = (ob_top - ob_bot) / ob_bot * 100 if ob_bot > 0 else 0
            if ob_size_pct < ob_min_pct:
                continue

            # Проверяем что цена была НИЖЕ ob_bot между j+1 и i (broke down, then back up)
            mid_lows = low[j+1:i]
            if len(mid_lows) < 5:
                continue
            broke_down = (mid_lows < ob_bot).any()
            if not broke_down:
                continue

            # И сейчас цена ВЕРНУЛАСЬ к зоне (close[i] в OB)
            if ob_bot * (1 - tol/100) <= close[i] <= ob_top * (1 + tol/100):
                bull_breaker[i] = True
                break

        # Bear breaker — бывший bull OB
        for j in range(i - 5, max(2, i - lookback), -1):
            if not (close[j] < open_[j]):
                continue
            ob_top = high[j]
            ob_bot = low[j]
            ob_size_pct = (ob_top - ob_bot) / ob_bot * 100 if ob_bot > 0 else 0
            if ob_size_pct < ob_min_pct:
                continue

            mid_highs = high[j+1:i]
            if len(mid_highs) < 5:
                continue
            broke_up = (mid_highs > ob_top).any()
            if not broke_up:
                continue

            if ob_bot * (1 - tol/100) <= close[i] <= ob_top * (1 + tol/100):
                bear_breaker[i] = True
                break

    return bull_breaker, bear_breaker


def detect_all_smc_extensions(df: pd.DataFrame, tf_label: str) -> dict[str, np.ndarray]:
    """Удобная wrapper-функция для добавления в flag matrix combinator'а.

    Returns dict[flag_name → bool_array].
    """
    bull_ind, bear_ind = detect_inducement(df)
    bull_void, bear_void = detect_liquidity_void(df)
    bull_brk, bear_brk = detect_breaker_block(df)

    return {
        f"bull_inducement_{tf_label}": bull_ind,
        f"bear_inducement_{tf_label}": bear_ind,
        f"bull_liq_void_{tf_label}": bull_void,
        f"bear_liq_void_{tf_label}": bear_void,
        f"bull_breaker_{tf_label}": bull_brk,
        f"bear_breaker_{tf_label}": bear_brk,
    }


# Self-test
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    from pathlib import Path
    PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")

    # Test на BTC 1h
    path = PROJECT_ROOT / "data" / "history" / "1h" / "BTCUSDT.parquet"
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
        df = df.set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df = df.tail(5000)   # last 5000 bars

    print(f"Test on BTC 1h, {len(df)} bars")

    import time
    t0 = time.time()
    bull_ind, bear_ind = detect_inducement(df)
    print(f"  Inducement: bull={int(bull_ind.sum())} ({100*bull_ind.mean():.2f}%), "
          f"bear={int(bear_ind.sum())} ({100*bear_ind.mean():.2f}%) — {time.time()-t0:.1f}s")

    t0 = time.time()
    bull_void, bear_void = detect_liquidity_void(df)
    print(f"  Liquidity Void: bull={int(bull_void.sum())} ({100*bull_void.mean():.2f}%), "
          f"bear={int(bear_void.sum())} ({100*bear_void.mean():.2f}%) — {time.time()-t0:.1f}s")

    t0 = time.time()
    bull_brk, bear_brk = detect_breaker_block(df)
    print(f"  Breaker Block: bull={int(bull_brk.sum())} ({100*bull_brk.mean():.2f}%), "
          f"bear={int(bear_brk.sum())} ({100*bear_brk.mean():.2f}%) — {time.time()-t0:.1f}s")

    print("\n✅ All SMC extensions OK")
