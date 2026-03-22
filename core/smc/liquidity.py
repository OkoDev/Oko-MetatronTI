"""
Liquidity — зоны скопления ликвидности (стоп-ордера).

Ликвидность скапливается:
  - Над Swing Highs (стопы шортистов) → buy-side liquidity
  - Под Swing Lows (стопы лонгистов) → sell-side liquidity

Институциональные игроки "охотятся" за этой ликвидностью — цена выносит
стопы (sweep), собирает объём и разворачивается.

Кластеры:
  Несколько свингов на близком уровне (±0.3%) образуют кластер ликвидности.
  Чем больше свингов в кластере — тем больше стопов — тем сильнее зона.

Swept tracking:
  После sweep (цена проходит через уровень) ликвидность "собрана".
  Swept liquidity = зона отработана, новые стопы ещё не накопились.

Зависит от: swing_points.py.
Используется: models.py (SMCContext).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from core.smc.swing_points import SwingAnalysis, SwingPoint, SwingType

logger = logging.getLogger(__name__)


@dataclass
class LiquidityZone:
    """Одна зона ликвидности (кластер свингов)."""
    level: float              # средний уровень кластера
    zone_top: float           # верхняя граница (level + tolerance)
    zone_bottom: float        # нижняя граница (level - tolerance)
    side: str                 # "BUY" (над highs) или "SELL" (под lows)
    swing_count: int          # количество свингов в кластере
    swing_indices: List[int] = field(default_factory=list)
    swept: bool = False       # ликвидность собрана?
    sweep_index: Optional[int] = None  # бар sweep'а

    @property
    def strength(self) -> int:
        """Сила зоны: больше свингов → больше стопов → сильнее."""
        base = min(100, 30 + self.swing_count * 20)
        if self.swept:
            base = max(10, base - 40)  # swept = отработана
        return base

    @property
    def is_active(self) -> bool:
        return not self.swept

    def __repr__(self) -> str:
        status = "SWEPT" if self.swept else "ACTIVE"
        return (
            f"{self.side}_LIQ("
            f"{self.zone_bottom:.6g}–{self.zone_top:.6g}, "
            f"n={self.swing_count}, str={self.strength}, {status})"
        )


@dataclass
class LiquidityAnalysis:
    """Результат анализа ликвидности."""
    buy_side: List[LiquidityZone] = field(default_factory=list)   # над highs
    sell_side: List[LiquidityZone] = field(default_factory=list)  # под lows
    nearest_buy: Optional[LiquidityZone] = None    # ближайшая зона выше цены
    nearest_sell: Optional[LiquidityZone] = None   # ближайшая зона ниже цены


# ---------------------------------------------------------------------------
# Кластеризация свингов
# ---------------------------------------------------------------------------

def _cluster_swings(
    swings: List[SwingPoint],
    tolerance_pct: float = 0.3,
) -> List[LiquidityZone]:
    """
    Группирует свинги в кластеры по близости уровней.

    Два свинга в одном кластере если |a - b| / a < tolerance_pct%.
    """
    if not swings:
        return []

    # Сортируем по value
    sorted_swings = sorted(swings, key=lambda s: s.value)

    clusters: List[List[SwingPoint]] = []
    current_cluster: List[SwingPoint] = [sorted_swings[0]]

    for s in sorted_swings[1:]:
        prev_val = current_cluster[-1].value
        if prev_val > 0 and abs(s.value - prev_val) / prev_val * 100 <= tolerance_pct:
            current_cluster.append(s)
        else:
            clusters.append(current_cluster)
            current_cluster = [s]

    clusters.append(current_cluster)

    # Конвертируем в LiquidityZone
    zones: List[LiquidityZone] = []
    for cluster in clusters:
        values = [s.value for s in cluster]
        level = sum(values) / len(values)
        tolerance = level * tolerance_pct / 100.0

        side = "BUY" if cluster[0].swing_type == SwingType.HIGH else "SELL"

        zones.append(LiquidityZone(
            level=level,
            zone_top=level + tolerance,
            zone_bottom=level - tolerance,
            side=side,
            swing_count=len(cluster),
            swing_indices=[s.index for s in cluster],
        ))

    return zones


# ---------------------------------------------------------------------------
# Sweep tracking
# ---------------------------------------------------------------------------

def _track_sweeps(
    zones: List[LiquidityZone],
    df: pd.DataFrame,
) -> List[LiquidityZone]:
    """
    Проверяет: была ли зона ликвидности swept (цена прошла через неё)?

    BUY-side swept: high бара > zone_top (стопы шортистов сработали).
    SELL-side swept: low бара < zone_bottom (стопы лонгистов сработали).
    """
    n = len(df)

    for zone in zones:
        # Начинаем проверку после последнего свинга в кластере
        start = max(zone.swing_indices) + 1 if zone.swing_indices else 0

        for j in range(start, n):
            bar_high = float(df["high"].iloc[j])
            bar_low = float(df["low"].iloc[j])

            if zone.side == "BUY" and bar_high > zone.zone_top:
                zone.swept = True
                zone.sweep_index = j
                break
            elif zone.side == "SELL" and bar_low < zone.zone_bottom:
                zone.swept = True
                zone.sweep_index = j
                break

    return zones


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

def detect_liquidity(
    df: pd.DataFrame,
    swing_analysis: SwingAnalysis,
    cluster_tolerance_pct: float = 0.3,
    track_sweeps: bool = True,
) -> LiquidityAnalysis:
    """
    Анализ зон ликвидности на основе свингов.

    Args:
        df: OHLCV DataFrame.
        swing_analysis: результат detect_swing_points().
        cluster_tolerance_pct: допуск для кластеризации свингов (%).
        track_sweeps: отслеживать sweep'ы.

    Returns:
        LiquidityAnalysis с buy-side и sell-side зонами.

    Пример:
        >>> from core.smc.swing_points import detect_swing_points
        >>> swings = detect_swing_points(df_15m)
        >>> liq = detect_liquidity(df_15m, swings)
        >>> for zone in liq.buy_side:
        ...     print(f"Buy-side liquidity: {zone.level:.4f} (n={zone.swing_count})")
    """
    empty = LiquidityAnalysis()

    if not swing_analysis.highs and not swing_analysis.lows:
        return empty

    try:
        # 1. Кластеризация highs (buy-side liquidity)
        buy_zones = _cluster_swings(swing_analysis.highs, tolerance_pct=cluster_tolerance_pct)
        for z in buy_zones:
            z.side = "BUY"

        # 2. Кластеризация lows (sell-side liquidity)
        sell_zones = _cluster_swings(swing_analysis.lows, tolerance_pct=cluster_tolerance_pct)
        for z in sell_zones:
            z.side = "SELL"

        # 3. Sweep tracking
        if track_sweeps and df is not None:
            buy_zones = _track_sweeps(buy_zones, df)
            sell_zones = _track_sweeps(sell_zones, df)

        # 4. Nearest (active only)
        current_price = float(df["close"].iloc[-1]) if df is not None and len(df) > 0 else 0.0
        active_buy = [z for z in buy_zones if z.is_active and z.level > current_price]
        active_sell = [z for z in sell_zones if z.is_active and z.level < current_price]

        nearest_buy = min(active_buy, key=lambda z: z.level - current_price) if active_buy else None
        nearest_sell = max(active_sell, key=lambda z: z.level) if active_sell else None

        return LiquidityAnalysis(
            buy_side=buy_zones,
            sell_side=sell_zones,
            nearest_buy=nearest_buy,
            nearest_sell=nearest_sell,
        )

    except Exception as e:
        logger.debug("detect_liquidity error: %s", e, exc_info=True)
        return empty
