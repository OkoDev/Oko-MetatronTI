"""
Order Blocks (OB) — зоны институциональных ордеров.

Order Block — последняя противотрендовая свеча ПЕРЕД импульсным движением
(Break of Structure). Институциональные игроки часто размещают свои ордера
на этих уровнях, и цена возвращается к ним при откате.

Типы:
  Bullish OB: последняя медвежья свеча перед бычьим BOS/CHoCH.
              Зона: [low, high] этой свечи → зона покупки при откате.
  Bearish OB: последняя бычья свеча перед медвежьим BOS/CHoCH.
              Зона: [low, high] этой свечи → зона продажи при откате.

Дополнительные свойства:
  - Volume filter: OB с аномальным объёмом (> 1.5× MA) сильнее
  - Breaker lifecycle: OB из CHoCH > OB из BOS (разворот > продолжение)
  - Mitigation: OB "отработан" когда цена полностью проходит через зону
  - Overlap с FVG: OB + FVG = суперсетап (двойное подтверждение)

Зависит от: structure.py (StructureBreak), swing_points.py.
Используется: models.py (SMCContext).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import numpy as np
import pandas as pd

from core.smc.structure import StructureAnalysis, StructureBreak, BreakType

logger = logging.getLogger(__name__)


class OBType(str, Enum):
    BULLISH = "BULLISH"   # зона покупки (последняя медвежья свеча перед BOS вверх)
    BEARISH = "BEARISH"   # зона продажи (последняя бычья свеча перед BOS вниз)


@dataclass
class OrderBlock:
    """Один Order Block."""
    ob_type: OBType
    top: float             # high свечи OB
    bottom: float          # low свечи OB
    midpoint: float        # (top + bottom) / 2 — зона входа
    index: int             # индекс свечи OB в DataFrame
    origin_break: StructureBreak   # какой BOS/CHoCH создал этот OB
    volume_ratio: float = 1.0      # volume / MA(20) — > 1.5 = сильный OB
    mitigated: bool = False
    mitigation_pct: float = 0.0    # 0.0–1.0
    mitigation_index: Optional[int] = None
    has_fvg_overlap: bool = False   # совпадает с FVG

    @property
    def is_active(self) -> bool:
        return not self.mitigated

    @property
    def strength(self) -> int:
        """Сила OB: 0-100."""
        base = 60
        # CHoCH-based OB сильнее (разворот)
        if self.origin_break.is_choch:
            base += 15
        # Аномальный объём
        if self.volume_ratio >= 2.0:
            base += 15
        elif self.volume_ratio >= 1.5:
            base += 10
        # FVG overlap
        if self.has_fvg_overlap:
            base += 10
        return min(100, base)

    def __repr__(self) -> str:
        status = "MIT" if self.mitigated else "ACTIVE"
        return (
            f"{self.ob_type.value}_OB("
            f"{self.bottom:.6g}–{self.top:.6g}, "
            f"vol={self.volume_ratio:.1f}x, "
            f"str={self.strength}, {status}@{self.index})"
        )


@dataclass
class OBAnalysis:
    """Результат анализа Order Blocks."""
    all_obs: List[OrderBlock] = field(default_factory=list)
    active_bull: List[OrderBlock] = field(default_factory=list)
    active_bear: List[OrderBlock] = field(default_factory=list)
    nearest_bull: Optional[OrderBlock] = None
    nearest_bear: Optional[OrderBlock] = None


# ---------------------------------------------------------------------------
# Определение Order Block свечи
# ---------------------------------------------------------------------------

def _find_ob_candle(
    df: pd.DataFrame,
    brk: StructureBreak,
    lookback: int = 10,
) -> Optional[int]:
    """
    Находит последнюю ПРОТИВОТРЕНДОВУЮ свечу перед импульсом.

    Для бычьего пробоя: ищем последнюю медвежью свечу (close < open)
    перед баром пробоя (от свинга до пробоя).

    Для медвежьего пробоя: ищем последнюю бычью свечу (close > open).
    """
    # Зона поиска: от свинга до бара пробоя (не включая сам бар пробоя)
    search_end = brk.break_index
    search_start = max(0, brk.broken_swing.index)

    # Ограничиваем lookback
    search_start = max(search_start, search_end - lookback)

    is_bullish_break = brk.break_type in (BreakType.BULLISH_BOS, BreakType.BULLISH_CHOCH)

    # Идём назад от бара пробоя, ищем противотрендовую свечу
    for i in range(search_end - 1, search_start - 1, -1):
        bar_open = float(df["open"].iloc[i])
        bar_close = float(df["close"].iloc[i])

        if is_bullish_break:
            # Ищем медвежью свечу (close < open)
            if bar_close < bar_open:
                return i
        else:
            # Ищем бычью свечу (close > open)
            if bar_close > bar_open:
                return i

    return None


# ---------------------------------------------------------------------------
# Volume ratio
# ---------------------------------------------------------------------------

def _compute_volume_ratio(
    df: pd.DataFrame,
    ob_index: int,
    ma_period: int = 20,
) -> float:
    """Объём OB-свечи / MA(20) объёма."""
    if "volume" not in df.columns:
        return 1.0

    ob_vol = float(df["volume"].iloc[ob_index])
    if ob_vol <= 0:
        return 1.0

    start = max(0, ob_index - ma_period)
    vol_slice = df["volume"].iloc[start:ob_index]
    if len(vol_slice) == 0:
        return 1.0

    ma = float(vol_slice.mean())
    return ob_vol / ma if ma > 0 else 1.0


# ---------------------------------------------------------------------------
# Mitigation tracking
# ---------------------------------------------------------------------------

def _track_ob_mitigation(
    obs: List[OrderBlock],
    df: pd.DataFrame,
) -> List[OrderBlock]:
    """
    Проверяет mitigation Order Blocks.

    Bullish OB mitigated: цена опускается НИЖЕ bottom OB (зона пробита).
    Bearish OB mitigated: цена поднимается ВЫШЕ top OB.
    """
    n = len(df)

    for ob in obs:
        gap_size = ob.top - ob.bottom
        if gap_size <= 0:
            ob.mitigated = True
            ob.mitigation_pct = 1.0
            continue

        start = ob.index + 1
        for j in range(start, n):
            bar_low = float(df["low"].iloc[j])
            bar_high = float(df["high"].iloc[j])

            if ob.ob_type == OBType.BULLISH:
                # Bullish OB invalidated если цена ушла ниже зоны
                if bar_low <= ob.top:
                    penetration = ob.top - bar_low
                    pct = min(1.0, penetration / gap_size)
                    if pct > ob.mitigation_pct:
                        ob.mitigation_pct = pct
                        ob.mitigation_index = j
                    if bar_low <= ob.bottom:
                        ob.mitigated = True
                        ob.mitigation_pct = 1.0
                        break
            else:
                # Bearish OB invalidated если цена ушла выше зоны
                if bar_high >= ob.bottom:
                    penetration = bar_high - ob.bottom
                    pct = min(1.0, penetration / gap_size)
                    if pct > ob.mitigation_pct:
                        ob.mitigation_pct = pct
                        ob.mitigation_index = j
                    if bar_high >= ob.top:
                        ob.mitigated = True
                        ob.mitigation_pct = 1.0
                        break

    return obs


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

def detect_order_blocks(
    df: pd.DataFrame,
    structure: StructureAnalysis,
    volume_ma_period: int = 20,
    ob_lookback: int = 10,
    track_mitigation: bool = True,
) -> OBAnalysis:
    """
    Детектирует Order Blocks на основе структурных пробоев.

    Args:
        df: OHLCV DataFrame.
        structure: результат detect_structure().
        volume_ma_period: период MA для расчёта volume_ratio.
        ob_lookback: максимальный lookback для поиска OB-свечи.
        track_mitigation: отслеживать mitigation.

    Returns:
        OBAnalysis с active/mitigated Order Blocks.

    Пример:
        >>> from core.smc.structure import detect_structure
        >>> struct = detect_structure(df_15m)
        >>> obs = detect_order_blocks(df_15m, struct)
        >>> for ob in obs.active_bull:
        ...     print(f"Bullish OB: {ob.bottom:.4f}–{ob.top:.4f} (str={ob.strength})")
    """
    empty = OBAnalysis()

    if not structure.breaks:
        return empty

    try:
        obs: List[OrderBlock] = []

        for brk in structure.breaks:
            ob_idx = _find_ob_candle(df, brk, lookback=ob_lookback)
            if ob_idx is None:
                continue

            ob_high = float(df["high"].iloc[ob_idx])
            ob_low = float(df["low"].iloc[ob_idx])
            mid = (ob_high + ob_low) / 2.0

            is_bullish = brk.break_type in (BreakType.BULLISH_BOS, BreakType.BULLISH_CHOCH)
            ob_type = OBType.BULLISH if is_bullish else OBType.BEARISH

            vol_ratio = _compute_volume_ratio(df, ob_idx, ma_period=volume_ma_period)

            obs.append(OrderBlock(
                ob_type=ob_type,
                top=ob_high,
                bottom=ob_low,
                midpoint=mid,
                index=ob_idx,
                origin_break=brk,
                volume_ratio=vol_ratio,
            ))

        if not obs:
            return empty

        # Mitigation
        if track_mitigation:
            obs = _track_ob_mitigation(obs, df)

        # Разделение
        active_bull = [ob for ob in obs if ob.ob_type == OBType.BULLISH and ob.is_active]
        active_bear = [ob for ob in obs if ob.ob_type == OBType.BEARISH and ob.is_active]

        # Nearest
        current_price = float(df["close"].iloc[-1])
        nearest_bull = min(active_bull, key=lambda o: abs(o.midpoint - current_price)) if active_bull else None
        nearest_bear = min(active_bear, key=lambda o: abs(o.midpoint - current_price)) if active_bear else None

        return OBAnalysis(
            all_obs=obs,
            active_bull=active_bull,
            active_bear=active_bear,
            nearest_bull=nearest_bull,
            nearest_bear=nearest_bear,
        )

    except Exception as e:
        logger.debug("detect_order_blocks error: %s", e, exc_info=True)
        return empty
