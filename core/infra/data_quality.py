"""
core/data_quality.py
Проверка свежести и полноты OHLCV данных перед сигнальным анализом.

Три проверки:
  1. Глубина — достаточно ли баров для каждого детектора
  2. Свежесть — последняя свеча не старше freshness_mult × TF
  3. Пробелы — доля NaN в close не превышает порог
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Минимальное количество баров для каждого типа детектора
MIN_BARS: dict[str, int] = {
    "divergence": 160,   # detect_divergence: pivot_period×2 + max_bars + буфер
    "wt": 21,            # WaveTrend: n1=10, n2=21 — нужно ≥21
    "trend": 43,         # EMA(43) — самая длинная EMA в trend_signals
    "anomaly": 20,       # история объёма
    "confluence": 40,    # lookback_bars по умолчанию
    "default": 50,       # общий минимум для scan_one
}

# Таймфрейм → длительность в секундах
_TF_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "1d": 86400,
    "1w": 604800,
}


def check_ohlcv_quality(
    df: Optional[pd.DataFrame],
    timeframe: str = "15m",
    min_bars: int = MIN_BARS["default"],
    max_nan_pct: float = 0.05,
    freshness_mult: float = 2.0,
    symbol: str = "",
) -> tuple[bool, str]:
    """
    Проверяет пригодность OHLCV-датафрейма к анализу.

    Args:
        df: датафрейм с колонками open/high/low/close/volume, индекс — datetime
        timeframe: таймфрейм строкой ('15m', '1h', ...)
        min_bars: минимальное число строк
        max_nan_pct: максимально допустимая доля NaN в close [0..1]
        freshness_mult: во сколько TF-интервалов допустим возраст последней свечи
        symbol: для логирования

    Returns:
        (ok: bool, reason: str) — ok=True если данные пригодны.
    """
    # --- базовая проверка ---
    if df is None or df.empty:
        return False, "пустой датафрейм"

    n = len(df)

    # 1. Глубина данных
    if n < min_bars:
        reason = f"мало баров: {n} < {min_bars}"
        logger.info("[data_quality] %s %s: %s", symbol, timeframe, reason)
        return False, reason

    # 2. Свежесть последней свечи
    tf_secs = _TF_SECONDS.get(timeframe, 900)
    max_age = freshness_mult * tf_secs
    try:
        last_ts = df.index[-1]
        # pandas Timestamp → datetime
        if hasattr(last_ts, "to_pydatetime"):
            last_ts = last_ts.to_pydatetime()
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        age_secs = (datetime.now(timezone.utc) - last_ts).total_seconds()
        if age_secs > max_age:
            reason = (
                f"данные устарели: последняя свеча {age_secs / 60:.1f} мин назад "
                f"(лимит {max_age / 60:.0f} мин)"
            )
            logger.info("[data_quality] %s %s: %s", symbol, timeframe, reason)
            return False, reason
    except Exception:
        pass  # если индекс не datetime — пропускаем проверку свежести

    # 3. Пробелы в close
    if "close" in df.columns:
        nan_pct = float(df["close"].isna().mean())
        if nan_pct > max_nan_pct:
            reason = f"пробелы в close: {nan_pct:.1%} > {max_nan_pct:.0%}"
            logger.info("[data_quality] %s %s: %s", symbol, timeframe, reason)
            return False, reason

    return True, "ok"


def bars_ok(
    df: Optional[pd.DataFrame],
    detector: str,
    symbol: str = "",
    timeframe: str = "",
) -> bool:
    """
    Быстрая проверка глубины для конкретного детектора.

    Пример:
        if not bars_ok(df_15m, "divergence", sym, "15m"):
            return []
    """
    needed = MIN_BARS.get(detector, MIN_BARS["default"])
    if df is None or len(df) < needed:
        if df is not None and symbol:
            logger.debug(
                "[data_quality] %s %s: мало баров для %s: %d < %d",
                symbol, timeframe, detector, len(df), needed,
            )
        return False
    return True
