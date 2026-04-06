"""
Fibonacci — OTE (Optimal Trade Entry) зона.

OTE зона = 0.618–0.786 уровни Фибоначчи от последнего импульса.
Это зона наиболее вероятного отката перед продолжением тренда.

Расчёт:
  Бычий импульс (после BOS/CHoCH вверх):
    high = точка пробоя (Swing High)
    low  = последний Swing Low перед импульсом
    OTE top    = high - (high - low) × 0.618
    OTE bottom = high - (high - low) × 0.786
    → цена в этой зоне = оптимальный вход в LONG

  Медвежий импульс:
    low  = точка пробоя (Swing Low)
    high = последний Swing High перед импульсом
    OTE top    = low + (high - low) × 0.786
    OTE bottom = low + (high - low) × 0.618
    → цена в этой зоне = оптимальный вход в SHORT

Стандартные уровни Fibonacci:
  0.236, 0.382, 0.500, 0.618, 0.786, 0.886

Зависит от: structure.py (StructureBreak).
Используется: models.py (SMCContext).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from core.smc.structure import StructureAnalysis, StructureBreak, BreakType

logger = logging.getLogger(__name__)

# Стандартные уровни Fibonacci
FIB_LEVELS = (0.236, 0.382, 0.500, 0.618, 0.786, 0.886)

# OTE зона
OTE_TOP = 0.618
OTE_BOTTOM = 0.786


@dataclass
class FibLevel:
    """Один уровень Fibonacci."""
    ratio: float
    price: float
    label: str   # "0.618", "0.786" и т.д.


@dataclass
class FibZone:
    """OTE зона + полный набор уровней Fibonacci для одного импульса."""
    direction: str          # "LONG" (бычий импульс) или "SHORT" (медвежий)
    impulse_high: float     # верхняя точка импульса
    impulse_low: float      # нижняя точка импульса
    ote_top: float          # верхняя граница OTE (0.618)
    ote_bottom: float       # нижняя граница OTE (0.786)
    ote_midpoint: float     # середина OTE зоны
    levels: List[FibLevel] = field(default_factory=list)
    origin_break: Optional[StructureBreak] = None
    price_in_ote: bool = False  # текущая цена в OTE зоне?

    @property
    def ote_size_pct(self) -> float:
        """Размер OTE зоны в % от цены."""
        mid = self.ote_midpoint
        if mid <= 0:
            return 0.0
        return abs(self.ote_top - self.ote_bottom) / mid * 100.0

    def __repr__(self) -> str:
        in_ote = " *IN_OTE*" if self.price_in_ote else ""
        return (
            f"FIB_{self.direction}("
            f"OTE={self.ote_bottom:.6g}–{self.ote_top:.6g}, "
            f"{self.ote_size_pct:.2f}%{in_ote})"
        )


@dataclass
class FibAnalysis:
    """Результат анализа Fibonacci."""
    zones: List[FibZone] = field(default_factory=list)
    active_ote: Optional[FibZone] = None   # последняя OTE зона, где цена рядом


# ---------------------------------------------------------------------------
# Расчёт уровней Fibonacci
# ---------------------------------------------------------------------------

def _calc_fib_levels(
    impulse_high: float,
    impulse_low: float,
    direction: str,
) -> List[FibLevel]:
    """
    Рассчитывает уровни Fibonacci для импульса.

    Бычий импульс: ретрейсмент от high вниз.
    Медвежий: ретрейсмент от low вверх.
    """
    diff = impulse_high - impulse_low
    if diff <= 0:
        return []

    levels: List[FibLevel] = []
    for ratio in FIB_LEVELS:
        if direction == "LONG":
            # Бычий: откат от high вниз
            price = impulse_high - diff * ratio
        else:
            # Медвежий: откат от low вверх
            price = impulse_low + diff * ratio

        levels.append(FibLevel(
            ratio=ratio,
            price=price,
            label=f"{ratio:.3f}",
        ))

    return levels


def _calc_ote(
    impulse_high: float,
    impulse_low: float,
    direction: str,
) -> tuple:
    """Рассчитывает OTE зону (0.618–0.786)."""
    diff = impulse_high - impulse_low
    if diff <= 0:
        return 0.0, 0.0

    if direction == "LONG":
        ote_top = impulse_high - diff * OTE_TOP       # 0.618
        ote_bottom = impulse_high - diff * OTE_BOTTOM  # 0.786
    else:
        ote_bottom = impulse_low + diff * OTE_TOP      # 0.618
        ote_top = impulse_low + diff * OTE_BOTTOM      # 0.786

    return ote_top, ote_bottom


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

def detect_fibonacci(
    df: pd.DataFrame,
    structure: StructureAnalysis,
    max_zones: int = 3,
) -> FibAnalysis:
    """
    Рассчитывает OTE зоны Fibonacci для последних структурных пробоев.

    Args:
        df: OHLCV DataFrame.
        structure: результат detect_structure().
        max_zones: максимальное количество зон (последние N пробоев).

    Returns:
        FibAnalysis с OTE зонами и уровнями Fibonacci.

    Пример:
        >>> from core.smc.structure import detect_structure
        >>> struct = detect_structure(df_15m)
        >>> fib = detect_fibonacci(df_15m, struct)
        >>> if fib.active_ote:
        ...     print(f"Цена в OTE! {fib.active_ote.ote_bottom:.4f}–{fib.active_ote.ote_top:.4f}")
    """
    empty = FibAnalysis()

    if not structure.breaks:
        return empty

    try:
        current_price = float(df["close"].iloc[-1]) if df is not None and len(df) > 0 else 0.0

        # Берём последние max_zones пробоев
        recent_breaks = structure.breaks[-max_zones:]
        zones: List[FibZone] = []

        for brk in recent_breaks:
            swing = brk.broken_swing
            sa = structure.swing_analysis

            is_bullish = brk.break_type in (BreakType.BULLISH_BOS, BreakType.BULLISH_CHOCH)
            direction = "LONG" if is_bullish else "SHORT"

            if is_bullish:
                # Бычий: high = пробитый Swing High, low = последний Swing Low перед ним
                impulse_high = swing.value
                # Ищем последний Swing Low с index < swing.index
                prev_lows = [s for s in sa.lows if s.index < swing.index]
                if not prev_lows:
                    continue
                impulse_low = prev_lows[-1].value
            else:
                # Медвежий: low = пробитый Swing Low, high = последний Swing High перед ним
                impulse_low = swing.value
                prev_highs = [s for s in sa.highs if s.index < swing.index]
                if not prev_highs:
                    continue
                impulse_high = prev_highs[-1].value

            if impulse_high <= impulse_low:
                continue

            # Уровни
            levels = _calc_fib_levels(impulse_high, impulse_low, direction)
            ote_top, ote_bottom = _calc_ote(impulse_high, impulse_low, direction)
            ote_mid = (ote_top + ote_bottom) / 2.0

            # DEV-85 Step 0: price-invalidation (ARCH spec) — структурный BOS провалился?
            # LONG: если цена упала ниже impulse_low → BOS вверх недействителен → зона stale
            # SHORT: если цена выросла выше impulse_high → BOS вниз недействителен → зона stale
            structure_valid = True
            if direction == "LONG" and current_price < impulse_low:
                structure_valid = False
            elif direction == "SHORT" and current_price > impulse_high:
                structure_valid = False

            # Цена в OTE? (только если структура валидна)
            price_in_ote = (
                (ote_bottom <= current_price <= ote_top if ote_top > ote_bottom else False)
                if structure_valid else False
            )

            zones.append(FibZone(
                direction=direction,
                impulse_high=impulse_high,
                impulse_low=impulse_low,
                ote_top=ote_top,
                ote_bottom=ote_bottom,
                ote_midpoint=ote_mid,
                levels=levels,
                origin_break=brk,
                price_in_ote=price_in_ote,
            ))

        # Active OTE: последняя зона где цена в OTE
        active_ote = None
        for z in reversed(zones):
            if z.price_in_ote:
                active_ote = z
                break

        return FibAnalysis(zones=zones, active_ote=active_ote)

    except Exception as e:
        logger.debug("detect_fibonacci error: %s", e, exc_info=True)
        return empty
