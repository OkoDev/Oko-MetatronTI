"""
Swing Points — структурные пики и впадины с чередованием.

Алгоритм:
  1. Найти все pivot highs и pivot lows (аналог ta.pivothigh/pivotlow)
  2. Обеспечить строгое чередование: H-L-H-L (никогда H-H или L-L подряд)
     При конфликте: из двух подряд H — оставить максимальный,
                    из двух подряд L — оставить минимальный
  3. Классифицировать каждый свинг:
     - HH (Higher High)  — текущий H > предыдущий H
     - LH (Lower High)   — текущий H < предыдущий H
     - HL (Higher Low)    — текущий L > предыдущий L
     - LL (Lower Low)     — текущий L < предыдущий L
  4. Определить структурный тренд:
     - BULLISH: HH + HL (растущие пики и впадины)
     - BEARISH: LH + LL (падающие пики и впадины)
     - NEUTRAL: иначе

Используется: structure.py (BOS/CHoCH), order_blocks.py, liquidity.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

_MIN_BARS = 20


# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------

class SwingType(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class SwingLabel(str, Enum):
    """Классификация свинга относительно предыдущего свинга того же типа."""
    HH = "HH"  # Higher High
    LH = "LH"  # Lower High
    HL = "HL"  # Higher Low
    LL = "LL"  # Lower Low
    FIRST = "FIRST"  # первый свинг данного типа, нет пары для сравнения


class StructureTrend(str, Enum):
    BULLISH = "BULLISH"   # HH + HL
    BEARISH = "BEARISH"   # LH + LL
    NEUTRAL = "NEUTRAL"


@dataclass
class SwingPoint:
    """Одна структурная точка."""
    index: int           # позиция бара в DataFrame
    value: float         # цена (high для HIGH, low для LOW)
    swing_type: SwingType
    label: SwingLabel = SwingLabel.FIRST

    def __repr__(self) -> str:
        return f"{self.label.value}({self.value:.6g}@{self.index})"


@dataclass
class SwingAnalysis:
    """Результат полного анализа свингов."""
    swings: List[SwingPoint]            # чередующаяся последовательность H-L-H-L
    highs: List[SwingPoint] = field(default_factory=list)  # только HIGH
    lows: List[SwingPoint] = field(default_factory=list)   # только LOW
    trend: StructureTrend = StructureTrend.NEUTRAL
    last_high: Optional[SwingPoint] = None
    last_low: Optional[SwingPoint] = None


# ---------------------------------------------------------------------------
# Детекция raw pivot'ов
# ---------------------------------------------------------------------------

def _find_raw_pivots(
    highs: pd.Series,
    lows: pd.Series,
    period: int,
) -> List[Tuple[int, float, SwingType]]:
    """
    Находит все pivot highs и pivot lows, возвращает единый список
    отсортированный по индексу.

    Pivot high: bar[i].high > всех high[i-period..i+period] (кроме себя).
    Pivot low:  bar[i].low  < всех low[i-period..i+period]  (кроме себя).
    """
    n = len(highs)
    pivots: List[Tuple[int, float, SwingType]] = []

    for i in range(period, n - period):
        h = highs.iloc[i]
        is_high = all(
            h > highs.iloc[j]
            for j in range(i - period, i + period + 1)
            if j != i
        )
        if is_high:
            pivots.append((i, float(h), SwingType.HIGH))

        lo = lows.iloc[i]
        is_low = all(
            lo < lows.iloc[j]
            for j in range(i - period, i + period + 1)
            if j != i
        )
        if is_low:
            pivots.append((i, float(lo), SwingType.LOW))

    # Сортировка по индексу (хронологически)
    pivots.sort(key=lambda x: x[0])
    return pivots


# ---------------------------------------------------------------------------
# Чередование (alternation)
# ---------------------------------------------------------------------------

def _enforce_alternation(
    raw: List[Tuple[int, float, SwingType]],
) -> List[Tuple[int, float, SwingType]]:
    """
    Обеспечивает строгое чередование H-L-H-L.

    При двух подряд HIGH — оставляем тот, у которого value выше.
    При двух подряд LOW  — оставляем тот, у которого value ниже.
    При конфликте на одном баре (одновременно H и L) — оставляем оба
    (бар может быть и пиком и впадиной, если соседи позволяют).
    """
    if not raw:
        return []

    result: List[Tuple[int, float, SwingType]] = [raw[0]]

    for item in raw[1:]:
        idx, val, stype = item
        prev_idx, prev_val, prev_type = result[-1]

        if stype == prev_type:
            # Конфликт — два подряд одного типа
            if stype == SwingType.HIGH:
                # Оставляем максимальный
                if val >= prev_val:
                    result[-1] = item
                # иначе — оставляем предыдущий (он выше)
            else:
                # LOW — оставляем минимальный
                if val <= prev_val:
                    result[-1] = item
        else:
            result.append(item)

    return result


# ---------------------------------------------------------------------------
# Классификация HH/HL/LH/LL
# ---------------------------------------------------------------------------

def _classify_swings(
    alternated: List[Tuple[int, float, SwingType]],
) -> List[SwingPoint]:
    """Присваивает каждому свингу метку HH/HL/LH/LL."""
    if not alternated:
        return []

    points: List[SwingPoint] = []
    prev_high_val: Optional[float] = None
    prev_low_val: Optional[float] = None

    for idx, val, stype in alternated:
        if stype == SwingType.HIGH:
            if prev_high_val is None:
                label = SwingLabel.FIRST
            elif val > prev_high_val:
                label = SwingLabel.HH
            elif val < prev_high_val:
                label = SwingLabel.LH
            else:
                # Равны — сохраняем предыдущее направление или FIRST
                label = SwingLabel.HH  # default: не считаем LH при равенстве
            prev_high_val = val
        else:
            if prev_low_val is None:
                label = SwingLabel.FIRST
            elif val > prev_low_val:
                label = SwingLabel.HL
            elif val < prev_low_val:
                label = SwingLabel.LL
            else:
                label = SwingLabel.HL
            prev_low_val = val

        points.append(SwingPoint(index=idx, value=val, swing_type=stype, label=label))

    return points


# ---------------------------------------------------------------------------
# Структурный тренд
# ---------------------------------------------------------------------------

def _determine_trend(points: List[SwingPoint], lookback: int = 4) -> StructureTrend:
    """
    Определяет тренд по последним N свингам.

    BULLISH:  последний HIGH = HH И последний LOW = HL
    BEARISH:  последний HIGH = LH И последний LOW = LL
    Иначе:    NEUTRAL
    """
    if len(points) < 3:
        return StructureTrend.NEUTRAL

    # Берём последние lookback свингов
    recent = points[-lookback:] if len(points) >= lookback else points

    last_high = None
    last_low = None
    for p in reversed(recent):
        if p.swing_type == SwingType.HIGH and last_high is None:
            last_high = p
        elif p.swing_type == SwingType.LOW and last_low is None:
            last_low = p
        if last_high and last_low:
            break

    if not last_high or not last_low:
        return StructureTrend.NEUTRAL

    if last_high.label == SwingLabel.HH and last_low.label == SwingLabel.HL:
        return StructureTrend.BULLISH
    if last_high.label == SwingLabel.LH and last_low.label == SwingLabel.LL:
        return StructureTrend.BEARISH

    return StructureTrend.NEUTRAL


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

_SWINGS_CANON = None


def _use_swings_canon() -> bool:
    """ARCH-137.5: брать пивоты у эталона. Откат: config.yaml → smc.swings_canon: false"""
    global _SWINGS_CANON
    if _SWINGS_CANON is None:
        try:
            import yaml
            from pathlib import Path
            cfg_path = Path(__file__).resolve().parents[2] / "config.yaml"
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            _SWINGS_CANON = bool((cfg.get("smc") or {}).get("swings_canon", True))
        except Exception:
            _SWINGS_CANON = True
    return _SWINGS_CANON


def detect_swing_points(
    df: pd.DataFrame,
    period: int = 5,
    trend_lookback: int = 6,
) -> SwingAnalysis:
    """
    Полный анализ swing-структуры.

    Args:
        df: OHLCV DataFrame (колонки: high, low как минимум).
        period: количество баров с каждой стороны для подтверждения pivot.
                period=5 → свинг подтверждён 5 барами слева и 5 справа.
        trend_lookback: сколько последних свингов учитывать для тренда.

    Returns:
        SwingAnalysis с чередующимися свингами, классификацией и трендом.

    Пример:
        >>> analysis = detect_swing_points(df_15m, period=5)
        >>> print(analysis.trend)        # BULLISH / BEARISH / NEUTRAL
        >>> print(analysis.last_high)    # HH(1.2345@142)
        >>> print(analysis.swings[-4:])  # последние 4 точки
    """
    empty = SwingAnalysis(swings=[])

    if df is None or len(df) < _MIN_BARS:
        return empty

    try:
        # 1. Raw pivots — ARCH-137.5: источник пивотов из ЭТАЛОНА.
        #    Причина: сломы в StructureAnalysis уже берутся у эталона, а свинги
        #    оставались от здешнего _find_raw_pivots — и fibonacci.py:190-191 брал
        #    ПРОБИТЫЙ свинг у эталона, а предыдущие экстремумы отсюда, то есть строил
        #    диапазон между точками разных детекторов.
        #    Сверка 02.09 (12 пар, 1h/400): major(50) эталона здесь находились на 89%,
        #    minor(5) — на 59%; при том что _swings_luxalgo даёт 63 пивота против 52.
        #    Дальше по конвейеру всё прежнее: чередование, классификация, тренд.
        #    Откат: config.yaml → smc.swings_canon: false
        raw = None
        if _use_swings_canon():
            try:
                from core.smc.smc_engine import _swings_luxalgo
                raw = [
                    (int(i), float(p), SwingType.HIGH if k == "H" else SwingType.LOW)
                    for i, p, k in (_swings_luxalgo(df, period) or [])
                ]
            except Exception as e:
                logger.debug("swings canon error: %s", e, exc_info=True)
                raw = None
        if not raw:
            raw = _find_raw_pivots(df["high"], df["low"], period)
        if not raw:
            return empty

        # 2. Чередование
        alternated = _enforce_alternation(raw)
        if not alternated:
            return empty

        # 3. Классификация
        points = _classify_swings(alternated)

        # 4. Разделение на highs/lows
        highs = [p for p in points if p.swing_type == SwingType.HIGH]
        lows = [p for p in points if p.swing_type == SwingType.LOW]

        # 5. Тренд
        trend = _determine_trend(points, lookback=trend_lookback)

        return SwingAnalysis(
            swings=points,
            highs=highs,
            lows=lows,
            trend=trend,
            last_high=highs[-1] if highs else None,
            last_low=lows[-1] if lows else None,
        )

    except Exception as e:
        logger.debug("detect_swing_points error: %s", e, exc_info=True)
        return empty
