"""
Structure — BOS (Break of Structure) и CHoCH (Change of Character).

Концепции SMC:
  BOS  — пробой в НАПРАВЛЕНИИ текущего тренда (подтверждение продолжения).
          Бычий BOS: цена пробивает предыдущий Swing High в восходящем тренде.
          Медвежий BOS: цена пробивает предыдущий Swing Low в нисходящем тренде.

  CHoCH — пробой ПРОТИВ текущего тренда (первый сигнал разворота).
          Бычий CHoCH: в нисходящем тренде цена пробивает Swing High.
          Медвежий CHoCH: в восходящем тренде цена пробивает Swing Low.

  Breaker Block — свинг, который был пробит (BOS или CHoCH).
                  Уровень пробоя часто ретестируется как поддержка/сопротивление.

Multi-bar confirmation: пробой фиксируется не по фитилю одного бара,
а по close (тело закрывается за уровнем) — уменьшает ложные пробои.

Зависит от: swing_points.py (detect_swing_points, SwingPoint).
Используется: order_blocks.py, models.py (SMCContext).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import pandas as pd

from core.smc.swing_points import (
    SwingAnalysis,
    SwingLabel,
    SwingPoint,
    SwingType,
    StructureTrend,
    detect_swing_points,
)

logger = logging.getLogger(__name__)

_MIN_BARS = 30


class BreakType(str, Enum):
    BULLISH_BOS = "BULLISH_BOS"
    BEARISH_BOS = "BEARISH_BOS"
    BULLISH_CHOCH = "BULLISH_CHOCH"
    BEARISH_CHOCH = "BEARISH_CHOCH"


@dataclass
class StructureBreak:
    """Одно структурное событие (BOS или CHoCH)."""
    break_type: BreakType
    level: float                # пробитый уровень (value свинга)
    broken_swing: SwingPoint    # какой свинг пробит
    break_index: int            # индекс бара, на котором произошёл пробой
    break_price: float          # close бара пробоя
    confirmed: bool = True      # close за уровнем (не только фитиль)
    strength: int = 0           # 0-100

    @property
    def direction(self) -> str:
        """LONG или SHORT."""
        if self.break_type in (BreakType.BULLISH_BOS, BreakType.BULLISH_CHOCH):
            return "LONG"
        return "SHORT"

    @property
    def is_bos(self) -> bool:
        return self.break_type in (BreakType.BULLISH_BOS, BreakType.BEARISH_BOS)

    @property
    def is_choch(self) -> bool:
        return self.break_type in (BreakType.BULLISH_CHOCH, BreakType.BEARISH_CHOCH)

    def __repr__(self) -> str:
        return (
            f"{self.break_type.value}("
            f"lvl={self.level:.6g}, "
            f"str={self.strength}@{self.break_index})"
        )


@dataclass
class BreakerBlock:
    """
    Breaker Block — пробитый уровень, который часто ретестируется.

    После BOS/CHoCH: пробитый Swing High/Low становится зоной поддержки
    (для бычьего пробоя) или сопротивления (для медвежьего).
    """
    level: float
    direction: str       # "LONG" — уровень как поддержка, "SHORT" — как сопротивление
    origin: StructureBreak
    retested: bool = False
    retest_index: Optional[int] = None


@dataclass
class StructureAnalysis:
    """Результат анализа структуры."""
    swing_analysis: SwingAnalysis
    breaks: List[StructureBreak] = field(default_factory=list)
    breaker_blocks: List[BreakerBlock] = field(default_factory=list)
    last_break: Optional[StructureBreak] = None
    trend: StructureTrend = StructureTrend.NEUTRAL
    # Актуальные непробитые уровни
    active_resistance: Optional[float] = None  # ближайший Swing High
    active_support: Optional[float] = None     # ближайший Swing Low


# ---------------------------------------------------------------------------
# Определение тренда для BOS/CHoCH классификации
# ---------------------------------------------------------------------------

def _infer_local_trend(
    swings: List[SwingPoint],
    up_to_index: int,
) -> Optional[StructureTrend]:
    """
    Определяет локальный тренд по свингам ДО указанного индекса.
    Нужно для различения BOS (продолжение) от CHoCH (разворот).
    """
    relevant = [s for s in swings if s.index < up_to_index]
    if len(relevant) < 3:
        return None

    # Последние 2 пары HH/HL или LH/LL
    last_h = None
    last_l = None
    for s in reversed(relevant):
        if s.swing_type == SwingType.HIGH and last_h is None:
            last_h = s
        elif s.swing_type == SwingType.LOW and last_l is None:
            last_l = s
        if last_h and last_l:
            break

    if not last_h or not last_l:
        return None

    if last_h.label in (SwingLabel.HH, SwingLabel.FIRST) and last_l.label in (SwingLabel.HL, SwingLabel.FIRST):
        return StructureTrend.BULLISH
    if last_h.label in (SwingLabel.LH,) and last_l.label in (SwingLabel.LL,):
        return StructureTrend.BEARISH

    return StructureTrend.NEUTRAL


# ---------------------------------------------------------------------------
# Детекция пробоев
# ---------------------------------------------------------------------------

def _detect_breaks(
    df: pd.DataFrame,
    swing_analysis: SwingAnalysis,
    use_close: bool = True,
    min_distance_bars: int = 3,
) -> List[StructureBreak]:
    """
    Ищет пробои Swing High / Swing Low.

    Args:
        df: OHLCV DataFrame.
        swing_analysis: результат detect_swing_points.
        use_close: True = подтверждение по close (надёжнее),
                   False = по high/low (фитиль, чувствительнее).
        min_distance_bars: минимальное расстояние от свинга до бара пробоя
                           (защита от слишком свежих пробоев).
    """
    breaks: List[StructureBreak] = []
    n = len(df)

    swings = swing_analysis.swings
    if not swings:
        return breaks

    # Для каждого свинга проверяем: пробит ли он последующими барами?
    for swing in swings:
        # Ищем первый бар после свинга, который пробивает его уровень
        search_start = swing.index + min_distance_bars
        if search_start >= n:
            continue

        for bar_idx in range(search_start, n):
            bar_close = float(df["close"].iloc[bar_idx])
            bar_high = float(df["high"].iloc[bar_idx])
            bar_low = float(df["low"].iloc[bar_idx])

            broken = False
            confirmed = False

            if swing.swing_type == SwingType.HIGH:
                # Пробой Swing High вверх
                if use_close:
                    if bar_close > swing.value:
                        broken = True
                        confirmed = True
                else:
                    if bar_high > swing.value:
                        broken = True
                        confirmed = bar_close > swing.value

            else:  # SwingType.LOW
                # Пробой Swing Low вниз
                if use_close:
                    if bar_close < swing.value:
                        broken = True
                        confirmed = True
                else:
                    if bar_low < swing.value:
                        broken = True
                        confirmed = bar_close < swing.value

            if broken:
                # Определяем тип: BOS или CHoCH
                local_trend = _infer_local_trend(swings, swing.index)

                if swing.swing_type == SwingType.HIGH:
                    # Пробой HIGH вверх
                    if local_trend == StructureTrend.BULLISH:
                        btype = BreakType.BULLISH_BOS  # продолжение бычьего тренда
                    else:
                        btype = BreakType.BULLISH_CHOCH  # разворот с медвежьего
                else:
                    # Пробой LOW вниз
                    if local_trend == StructureTrend.BEARISH:
                        btype = BreakType.BEARISH_BOS
                    else:
                        btype = BreakType.BEARISH_CHOCH

                # Strength: BOS > CHoCH, confirmed > wick
                strength = 70 if btype in (BreakType.BULLISH_BOS, BreakType.BEARISH_BOS) else 55
                if confirmed:
                    strength += 10
                # Бонус за количество баров до пробоя (давнее сопротивление сильнее)
                distance = bar_idx - swing.index
                if distance >= 20:
                    strength += 10
                elif distance >= 10:
                    strength += 5
                strength = min(100, strength)

                breaks.append(StructureBreak(
                    break_type=btype,
                    level=swing.value,
                    broken_swing=swing,
                    break_index=bar_idx,
                    break_price=bar_close,
                    confirmed=confirmed,
                    strength=strength,
                ))
                break  # один пробой на свинг

    return breaks


# ---------------------------------------------------------------------------
# Breaker Blocks
# ---------------------------------------------------------------------------

def _build_breaker_blocks(
    breaks: List[StructureBreak],
    df: pd.DataFrame,
) -> List[BreakerBlock]:
    """
    Создаёт Breaker Blocks из пробитых уровней.
    Проверяет ретест: цена вернулась к пробитому уровню (±0.2%).
    """
    blockers: List[BreakerBlock] = []
    n = len(df)

    for brk in breaks:
        bb = BreakerBlock(
            level=brk.level,
            direction=brk.direction,
            origin=brk,
        )

        # Проверяем ретест после пробоя
        retest_start = brk.break_index + 1
        tolerance = brk.level * 0.002  # 0.2%

        for j in range(retest_start, n):
            bar_low = float(df["low"].iloc[j])
            bar_high = float(df["high"].iloc[j])

            if brk.direction == "LONG":
                # Бычий пробой: уровень стал поддержкой
                # Ретест = цена опустилась к уровню
                if bar_low <= brk.level + tolerance:
                    bb.retested = True
                    bb.retest_index = j
                    break
            else:
                # Медвежий пробой: уровень стал сопротивлением
                if bar_high >= brk.level - tolerance:
                    bb.retested = True
                    bb.retest_index = j
                    break

        blockers.append(bb)

    return blockers


# ---------------------------------------------------------------------------
# Active levels
# ---------------------------------------------------------------------------

def _find_active_levels(
    swing_analysis: SwingAnalysis,
    breaks: List[StructureBreak],
    current_price: float,
) -> tuple:
    """
    Находит ближайшие непробитые Swing High (resistance) и Swing Low (support).
    """
    broken_indices = {b.broken_swing.index for b in breaks}

    active_highs = [
        s for s in swing_analysis.highs
        if s.index not in broken_indices and s.value > current_price
    ]
    active_lows = [
        s for s in swing_analysis.lows
        if s.index not in broken_indices and s.value < current_price
    ]

    resistance = min(active_highs, key=lambda s: s.value).value if active_highs else None
    support = max(active_lows, key=lambda s: s.value).value if active_lows else None

    return resistance, support


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

def detect_structure(
    df: pd.DataFrame,
    swing_period: int = 5,
    use_close: bool = True,
    min_distance_bars: int = 3,
    trend_lookback: int = 6,
) -> StructureAnalysis:
    """
    Полный анализ структуры рынка: свинги + BOS/CHoCH + Breaker Blocks.

    Args:
        df: OHLCV DataFrame (минимум 30 баров).
        swing_period: период для определения swing points.
        use_close: подтверждение пробоя по close (True) или по high/low (False).
        min_distance_bars: минимальное расстояние от свинга до пробоя.
        trend_lookback: сколько свингов учитывать для определения тренда.

    Returns:
        StructureAnalysis со свингами, пробоями, breaker blocks и трендом.

    Пример:
        >>> result = detect_structure(df_15m, swing_period=5)
        >>> if result.last_break and result.last_break.is_choch:
        ...     print(f"CHoCH! Разворот → {result.last_break.direction}")
        >>> print(f"Support: {result.active_support}, Resistance: {result.active_resistance}")
    """
    empty_swings = SwingAnalysis(swings=[])
    empty = StructureAnalysis(swing_analysis=empty_swings)

    if df is None or len(df) < _MIN_BARS:
        return empty

    try:
        # 1. Swing Points
        swing_analysis = detect_swing_points(df, period=swing_period, trend_lookback=trend_lookback)
        if not swing_analysis.swings:
            return StructureAnalysis(swing_analysis=swing_analysis)

        # 2. Structure Breaks (BOS/CHoCH)
        breaks = _detect_breaks(df, swing_analysis, use_close=use_close, min_distance_bars=min_distance_bars)

        # 3. Breaker Blocks
        breaker_blocks = _build_breaker_blocks(breaks, df)

        # 4. Active levels
        current_price = float(df["close"].iloc[-1])
        resistance, support = _find_active_levels(swing_analysis, breaks, current_price)

        # 5. Last break (самый свежий)
        last_break = breaks[-1] if breaks else None

        return StructureAnalysis(
            swing_analysis=swing_analysis,
            breaks=breaks,
            breaker_blocks=breaker_blocks,
            last_break=last_break,
            trend=swing_analysis.trend,
            active_resistance=resistance,
            active_support=support,
        )

    except Exception as e:
        logger.debug("detect_structure error: %s", e, exc_info=True)
        return empty
