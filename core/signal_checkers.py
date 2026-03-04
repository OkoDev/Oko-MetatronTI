"""
Проверки отдельных типов сигналов — чистые функции, не зависящие от класса.
Принимают (symbol, df) и возвращают List[SignalData].
"""
import logging
from datetime import datetime
from typing import List

import pandas as pd

from core.signal_models import SignalData, SignalDirection, SignalType

try:
    from core.indicators import calculate_trend, calculate_wt
except ImportError:
    def calculate_trend(df, atr_period=43, factor=1.0):
        df = df.copy()
        df["trend"] = 1
        return df

    def calculate_wt(df, n1=10, n2=21):
        df = df.copy()
        df["wt1"] = 0
        df["wt2"] = 0
        return df

logger = logging.getLogger(__name__)


async def check_anomaly_signals(symbol: str, df: pd.DataFrame) -> List[SignalData]:
    """Проверка аномалий объема."""
    signals = []
    try:
        if df is None or len(df) < 20:
            return signals

        volume_mean = df["volume"].rolling(20).mean().iloc[-1]
        volume_current = df["volume"].iloc[-1]
        volume_ratio = volume_current / volume_mean if volume_mean > 0 else 1

        if volume_ratio > 3.0:
            price_change = (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2] * 100
            direction = SignalDirection.LONG if price_change > 0 else SignalDirection.SHORT
            signals.append(SignalData(
                symbol=symbol,
                signal_type=SignalType.ANOMALY,
                direction=direction,
                strength=min(int(volume_ratio * 10), 100),
                confidence=0.7,
                timestamp=datetime.now(),
                data={"volume_ratio": volume_ratio, "price_change": price_change,
                      "volume_current": volume_current, "volume_mean": volume_mean},
                timeframe="1h",
            ))
    except Exception:
        logger.exception("Ошибка проверки аномалий для %s", symbol)
    return signals


async def check_wt_signals(symbol: str, df: pd.DataFrame) -> List[SignalData]:
    """Проверка Wavetrend сигналов."""
    signals = []
    try:
        if df is None or len(df) < 50:
            return signals

        df_wt = calculate_wt(df)
        if "wt1" not in df_wt.columns or "wt2" not in df_wt.columns:
            return signals

        wt1_last, wt2_last = df_wt["wt1"].iloc[-1], df_wt["wt2"].iloc[-1]
        wt1_prev, wt2_prev = df_wt["wt1"].iloc[-2], df_wt["wt2"].iloc[-2]

        cross_up = wt1_prev < wt2_prev and wt1_last > wt2_last
        cross_down = wt1_prev > wt2_prev and wt1_last < wt2_last

        if cross_up and wt1_last < -50:
            signals.append(SignalData(
                symbol=symbol, signal_type=SignalType.WT_SIGNAL, direction=SignalDirection.LONG,
                strength=70, confidence=0.8, timestamp=datetime.now(),
                data={"wt1": wt1_last, "wt2": wt2_last, "zone": "OS"}, timeframe="15m",
            ))
        elif cross_down and wt1_last > 50:
            signals.append(SignalData(
                symbol=symbol, signal_type=SignalType.WT_SIGNAL, direction=SignalDirection.SHORT,
                strength=70, confidence=0.8, timestamp=datetime.now(),
                data={"wt1": wt1_last, "wt2": wt2_last, "zone": "OB"}, timeframe="15m",
            ))
    except Exception:
        logger.exception("Ошибка проверки WT для %s", symbol)
    return signals


async def check_mtf_signals(
    symbol: str, df_1h: pd.DataFrame, df_15m: pd.DataFrame, df_3m: pd.DataFrame
) -> List[SignalData]:
    """Проверка мультитаймфреймовых сигналов."""
    signals = []
    try:
        if any(x is None for x in (df_1h, df_15m, df_3m)):
            return signals

        df_1h_trend = calculate_trend(df_1h)
        trend_1h = df_1h_trend["trend"].iloc[-1] if "trend" in df_1h_trend.columns else 0

        df_15m_wt = calculate_wt(df_15m)
        if "wt1" not in df_15m_wt.columns or "wt2" not in df_15m_wt.columns:
            return signals

        wt1_15m, wt2_15m = df_15m_wt["wt1"].iloc[-1], df_15m_wt["wt2"].iloc[-1]
        df_3m_wt = calculate_wt(df_3m)
        if "wt1" not in df_3m_wt.columns:
            return signals

        wt1_3m = df_3m_wt["wt1"].iloc[-1]
        common = dict(symbol=symbol, signal_type=SignalType.MTF_SIGNAL, strength=85, confidence=0.9,
                      timestamp=datetime.now(), timeframe="MTF",
                      data={"trend_1h": trend_1h, "wt1_15m": wt1_15m, "wt2_15m": wt2_15m, "wt1_3m": wt1_3m})

        if trend_1h == 1 and wt1_15m > wt2_15m and wt1_3m < -50:
            signals.append(SignalData(direction=SignalDirection.LONG, **common))
        elif trend_1h == -1 and wt1_15m < wt2_15m and wt1_3m > 50:
            signals.append(SignalData(direction=SignalDirection.SHORT, **common))
    except Exception:
        logger.exception("Ошибка проверки MTF для %s", symbol)
    return signals


async def check_trend_signals(symbol: str, df: pd.DataFrame) -> List[SignalData]:
    """Проверка трендовых сигналов."""
    signals = []
    try:
        if df is None or len(df) < 50:
            return signals

        df_trend = calculate_trend(df)
        if "trend" not in df_trend.columns:
            return signals

        trend_current = df_trend["trend"].iloc[-1]
        trend_prev = df_trend["trend"].iloc[-2]

        if trend_current != trend_prev:
            direction = SignalDirection.LONG if trend_current == 1 else SignalDirection.SHORT
            signals.append(SignalData(
                symbol=symbol, signal_type=SignalType.TREND_SIGNAL, direction=direction,
                strength=60, confidence=0.7, timestamp=datetime.now(),
                data={"trend_current": trend_current, "trend_prev": trend_prev}, timeframe="1h",
            ))
    except Exception:
        logger.exception("Ошибка проверки тренда для %s", symbol)
    return signals


async def check_divergence_signals(symbol: str, df: pd.DataFrame) -> List[SignalData]:
    """Проверка дивергенций."""
    signals = []
    try:
        if df is None or len(df) < 100:
            return signals

        df_wt = calculate_wt(df)
        if "wt1" not in df_wt.columns:
            return signals

        price_highs = df["high"].rolling(10, center=True).max()
        price_lows = df["low"].rolling(10, center=True).min()
        wt_highs = df_wt["wt1"].rolling(10, center=True).max()
        wt_lows = df_wt["wt1"].rolling(10, center=True).min()

        recent_price_high = price_highs.iloc[-20:].max()
        recent_price_low = price_lows.iloc[-20:].min()
        recent_wt_high = wt_highs.iloc[-20:].max()
        recent_wt_low = wt_lows.iloc[-20:].min()

        if recent_price_low < df["low"].iloc[-50:].min() and recent_wt_low > df_wt["wt1"].iloc[-50:].min():
            signals.append(SignalData(
                symbol=symbol, signal_type=SignalType.DIVERGENCE, direction=SignalDirection.LONG,
                strength=75, confidence=0.8, timestamp=datetime.now(),
                data={"divergence_type": "bullish", "price_low": recent_price_low, "wt_low": recent_wt_low},
                timeframe="1h",
            ))
        elif recent_price_high > df["high"].iloc[-50:].max() and recent_wt_high < df_wt["wt1"].iloc[-50:].max():
            signals.append(SignalData(
                symbol=symbol, signal_type=SignalType.DIVERGENCE, direction=SignalDirection.SHORT,
                strength=75, confidence=0.8, timestamp=datetime.now(),
                data={"divergence_type": "bearish", "price_high": recent_price_high, "wt_high": recent_wt_high},
                timeframe="1h",
            ))
    except Exception:
        logger.exception("Ошибка проверки дивергенций для %s", symbol)
    return signals


async def check_pivot_signals(symbol: str, df: pd.DataFrame) -> List[SignalData]:
    """Проверка пивотных сигналов."""
    signals = []
    try:
        if df is None or len(df) < 50:
            return signals

        current_price = df["close"].iloc[-1]
        highs = df["high"].rolling(20, center=True).max()
        lows = df["low"].rolling(20, center=True).min()

        resistance_levels = highs[highs == df["high"]].dropna()
        support_levels = lows[lows == df["low"]].dropna()

        for level in resistance_levels.iloc[-10:]:
            distance = abs(current_price - level) / current_price * 100
            if distance < 2.0:
                signals.append(SignalData(
                    symbol=symbol, signal_type=SignalType.PIVOT_REVERSAL, direction=SignalDirection.SHORT,
                    strength=65, confidence=0.7, timestamp=datetime.now(),
                    data={"pivot_type": "resistance", "level": level, "distance": distance}, timeframe="1h",
                ))

        for level in support_levels.iloc[-10:]:
            distance = abs(current_price - level) / current_price * 100
            if distance < 2.0:
                signals.append(SignalData(
                    symbol=symbol, signal_type=SignalType.PIVOT_REVERSAL, direction=SignalDirection.LONG,
                    strength=65, confidence=0.7, timestamp=datetime.now(),
                    data={"pivot_type": "support", "level": level, "distance": distance}, timeframe="1h",
                ))
    except Exception:
        logger.exception("Ошибка проверки пивотов для %s", symbol)
    return signals
