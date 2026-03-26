"""
Indicators Layer — технические индикаторы.

Модули:
  indicators          — WT, RSI, ATR, EMA, ADX, trend, swing H/L
  divergence_detector — регулярные и скрытые дивергенции + MTF cascade
  trend_signals       — сигналы тренда (EMA cross, ADX, slope)
  market_regime       — MarketRegimeClassifier (TREND_UP/DOWN/RANGE/HIGH_VOL)
  anomaly_model       — модель аномалий объёма
  bounce_detector     — детектор bounce от уровней
  dynamic_thresholds  — адаптивные пороги по волатильности

Использование:
  from core.indicators import calculate_wt, calculate_trend
  from core.indicators.market_regime import MarketRegimeClassifier
  from core.indicators.divergence_detector import DivergenceDetector
"""
# Re-export публичного API из indicators.py — сохраняет совместимость
# с кодом который делает: from core.indicators import calculate_wt
from core.indicators.indicators import (  # noqa: F401
    calculate_wt, calculate_trend, get_zone, detect_fvg,
    calculate_trend_strength, get_trend_info,
    compute_atr_values, compute_atr, compute_ema_values, compute_ema,
    compute_sma, compute_volatility, compute_adx, compute_rsi,
    compute_volume_ratio, find_swing_highs, find_swing_lows,
    calculate_pivot_points,
)
from core.indicators.market_regime import MarketRegimeClassifier  # noqa: F401

__all__ = [
    "calculate_wt", "calculate_trend", "get_zone", "detect_fvg",
    "calculate_trend_strength", "get_trend_info",
    "compute_atr_values", "compute_atr", "compute_ema_values", "compute_ema",
    "compute_sma", "compute_volatility", "compute_adx", "compute_rsi",
    "compute_volume_ratio", "find_swing_highs", "find_swing_lows",
    "calculate_pivot_points", "MarketRegimeClassifier",
]
