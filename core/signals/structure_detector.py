"""
Structure Detector — Smart Money Concepts (SMC).

Детектирует:
- Swing Highs / Swing Lows (пики и впадины структуры)
- CHoCH (Change of Character) — первый сигнал разворота
- BOS (Break of Structure) — подтверждение смены тренда

Используется как дополнительный сигнал в signal_checkers.py.
Единый источник свинг-пивотов делегирует в core/indicators.py.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd

from core.indicators import find_swing_highs, find_swing_lows

logger = logging.getLogger(__name__)

# Минимальное количество баров для надёжной детекции
_MIN_BARS = 30


def detect_swing_highs_lows(
    df: pd.DataFrame,
    period: int = 5,
) -> dict:
    """
    Находит структурные пики и впадины.

    Args:
        df: OHLCV DataFrame
        period: количество баров с каждой стороны для подтверждения pivot

    Returns:
        {
            "highs": [{"index": int, "value": float}, ...],  # от старых к новым
            "lows":  [{"index": int, "value": float}, ...],
        }
    """
    if df is None or len(df) < _MIN_BARS:
        return {"highs": [], "lows": []}
    try:
        highs = find_swing_highs(df["high"], period=period)
        lows  = find_swing_lows(df["low"],  period=period)
        return {"highs": highs, "lows": lows}
    except Exception as e:
        logger.debug("structure_detector.detect_swing_highs_lows error: %s", e)
        return {"highs": [], "lows": []}


def detect_choch(
    df: pd.DataFrame,
    period: int = 5,
) -> Optional[dict]:
    """
    Change of Character (CHoCH) — первый признак разворота тренда.

    Логика SMC:
    - Бычий CHoCH: цена пробивает вниз последний значимый Swing Low
      (структура перестаёт делать HH/HL → LH/LL появляется)
    - Медвежий CHoCH: цена пробивает вверх последний значимый Swing High

    Проверяем только последнюю свечу против предпоследнего пика/впадины.

    Returns:
        {
            "type": "BULLISH_CHOCH" | "BEARISH_CHOCH",
            "direction": "LONG" | "SHORT",
            "level": float,           # пробитый уровень
            "broken_index": int,      # индекс пробитого пивота в df
            "current_price": float,
        }
        или None если CHoCH не обнаружен.
    """
    if df is None or len(df) < _MIN_BARS:
        return None
    try:
        swings = detect_swing_highs_lows(df, period=period)
        highs = swings["highs"]
        lows  = swings["lows"]

        last_close = float(df["close"].iloc[-1])
        last_low   = float(df["low"].iloc[-1])
        last_high  = float(df["high"].iloc[-1])

        # Медвежий CHoCH: последний Swing High пробит вверх
        # (в нисходящем тренде это смена на бычий)
        if highs:
            last_sh = highs[-1]
            # Убеждаемся что пивот не слишком свежий (нужен отступ ≥ period+1)
            if len(df) - 1 - last_sh["index"] > period:
                if last_high > last_sh["value"]:
                    return {
                        "type": "BULLISH_CHOCH",
                        "direction": "LONG",
                        "level": last_sh["value"],
                        "broken_index": last_sh["index"],
                        "current_price": last_close,
                    }

        # Бычий CHoCH: последний Swing Low пробит вниз
        # (в восходящем тренде это смена на медвежий)
        if lows:
            last_sl = lows[-1]
            if len(df) - 1 - last_sl["index"] > period:
                if last_low < last_sl["value"]:
                    return {
                        "type": "BEARISH_CHOCH",
                        "direction": "SHORT",
                        "level": last_sl["value"],
                        "broken_index": last_sl["index"],
                        "current_price": last_close,
                    }

        return None
    except Exception as e:
        logger.debug("structure_detector.detect_choch error: %s", e)
        return None


def detect_bos(
    df: pd.DataFrame,
    period: int = 5,
    lookback: int = 3,
) -> Optional[dict]:
    """
    Break of Structure (BOS) — подтверждение продолжения тренда.

    Логика SMC:
    - Бычий BOS: в восходящем тренде свеча пробивает предыдущий Swing High
      (HH подтверждён — тренд продолжается вверх)
    - Медвежий BOS: в нисходящем тренде свеча пробивает предыдущий Swing Low
      (LL подтверждён — тренд продолжается вниз)

    Отличие от CHoCH: BOS = продолжение, CHoCH = разворот.
    Для BOS проверяем несколько последних пивотов (lookback).

    Returns:
        {
            "type": "BULLISH_BOS" | "BEARISH_BOS",
            "direction": "LONG" | "SHORT",
            "level": float,
            "broken_index": int,
            "current_price": float,
            "trend": "UP" | "DOWN",   # тренд ДО пробоя
        }
        или None.
    """
    if df is None or len(df) < _MIN_BARS:
        return None
    try:
        swings = detect_swing_highs_lows(df, period=period)
        highs = swings["highs"]
        lows  = swings["lows"]

        last_close = float(df["close"].iloc[-1])
        last_high  = float(df["high"].iloc[-1])
        last_low   = float(df["low"].iloc[-1])
        n = len(df)

        # Бычий BOS: пробой одного из последних Swing Highs
        # (подтверждаем восходящий тренд)
        for sh in reversed(highs[-lookback:]):
            gap = n - 1 - sh["index"]
            if gap <= period:
                continue  # пивот слишком свежий
            if last_high > sh["value"]:
                return {
                    "type": "BULLISH_BOS",
                    "direction": "LONG",
                    "level": sh["value"],
                    "broken_index": sh["index"],
                    "current_price": last_close,
                    "trend": "UP",
                }

        # Медвежий BOS: пробой одного из последних Swing Lows
        for sl in reversed(lows[-lookback:]):
            gap = n - 1 - sl["index"]
            if gap <= period:
                continue
            if last_low < sl["value"]:
                return {
                    "type": "BEARISH_BOS",
                    "direction": "SHORT",
                    "level": sl["value"],
                    "broken_index": sl["index"],
                    "current_price": last_close,
                    "trend": "DOWN",
                }

        return None
    except Exception as e:
        logger.debug("structure_detector.detect_bos error: %s", e)
        return None


def detect_structure(
    df: pd.DataFrame,
    period: int = 5,
    lookback: int = 3,
) -> dict:
    """
    Полный анализ структуры: swings + CHoCH + BOS.
    Удобная обёртка для вызова из signal_checkers.py.

    Returns:
        {
            "swings": {"highs": [...], "lows": [...]},
            "choch": dict | None,
            "bos": dict | None,
            "signal": "LONG" | "SHORT" | None,   # итоговый сигнал
            "signal_type": "BOS" | "CHOCH" | None,
            "strength": int,  # 0-100
        }
    """
    result = {
        "swings": {"highs": [], "lows": []},
        "choch": None,
        "bos": None,
        "signal": None,
        "signal_type": None,
        "strength": 0,
    }

    if df is None or len(df) < _MIN_BARS:
        return result

    result["swings"] = detect_swing_highs_lows(df, period=period)
    result["choch"]  = detect_choch(df, period=period)
    result["bos"]    = detect_bos(df, period=period, lookback=lookback)

    # BOS приоритетнее CHoCH (подтверждение > первый сигнал)
    if result["bos"]:
        result["signal"]      = result["bos"]["direction"]
        result["signal_type"] = "BOS"
        result["strength"]    = 65  # BOS менее сильный — нужно подтверждение
    elif result["choch"]:
        result["signal"]      = result["choch"]["direction"]
        result["signal_type"] = "CHOCH"
        result["strength"]    = 55  # CHoCH первый сигнал — осторожно

    return result


def detect_structural_regime(
    df: pd.DataFrame,
    period: int = 5,
) -> str:
    """
    DEV-90 / ARCH-59: Определяет текущий структурный режим по паттерну HH/HL или LH/LL.

    В отличие от detect_bos()/detect_choch() (event-based — только последний бар),
    эта функция смотрит на последовательность swing-points → persistent режим.

    Args:
        df:     OHLCV DataFrame (мин. _MIN_BARS баров)
        period: период для detect_swing_highs_lows()

    Returns:
        "TREND_UP"   — HH + HL (последние 2 пика и 2 впадины растут)
        "TREND_DOWN" — LH + LL (последние 2 пика и 2 впадины падают)
        "RANGE"      — смешанная структура или недостаточно данных
    """
    if df is None or len(df) < _MIN_BARS:
        return "RANGE"

    try:
        swings = detect_swing_highs_lows(df, period=period)
        highs = swings["highs"]
        lows  = swings["lows"]

        hh = len(highs) >= 2 and highs[-1]["value"] > highs[-2]["value"]
        hl = len(lows)  >= 2 and lows[-1]["value"]  > lows[-2]["value"]
        ll = len(lows)  >= 2 and lows[-1]["value"]  < lows[-2]["value"]
        lh = len(highs) >= 2 and highs[-1]["value"] < highs[-2]["value"]

        if hh and hl:
            return "TREND_UP"
        if ll and lh:
            return "TREND_DOWN"
        return "RANGE"
    except Exception as e:
        logger.warning("[detect_structural_regime] error: %s", e)
        return "RANGE"
