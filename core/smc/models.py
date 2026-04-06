"""
SMCContext — единый контекст Smart Money Concepts.

Объединяет результаты всех SMC-модулей в один объект.
Аналог MTFContext — это КОНТЕКСТ, не сигнал.

Говорит "где структура" и "что делают институционалы", не "входи".

analyze_smc(df) — единая точка входа, вызывает все модули.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from core.smc.swing_points import SwingAnalysis, StructureTrend, detect_swing_points
from core.smc.structure import StructureAnalysis, StructureBreak, BreakType, detect_structure
from core.smc.fvg import FVGAnalysis, FVG, detect_fvg
from core.smc.order_blocks import OBAnalysis, OrderBlock, detect_order_blocks
from core.smc.liquidity import LiquidityAnalysis, LiquidityZone, detect_liquidity
from core.smc.fibonacci import FibAnalysis, FibZone, detect_fibonacci

logger = logging.getLogger(__name__)


@dataclass
class SMCContext:
    """
    Полный SMC-контекст для символа на одном таймфрейме.

    Это АНАЛИТИЧЕСКИЙ КОНТЕКСТ, не торговый сигнал.
    Используется стратегиями для принятия решений:
      - OB + FVG = суперсетап (двойное подтверждение зоны)
      - Цена в OTE = оптимальный откат
      - CHoCH + OB = разворот с зоной входа
      - Liquidity swept + BOS = импульс после сбора стопов

    Пример использования в стратегии:
      ctx = analyze_smc(df_15m)
      if ctx.has_bullish_ob_with_fvg and ctx.price_in_ote:
          strength_bonus += 25  # суперсетап
    """
    # Структура
    structure: StructureAnalysis = field(default_factory=lambda: StructureAnalysis(
        swing_analysis=SwingAnalysis(swings=[])
    ))
    trend: StructureTrend = StructureTrend.NEUTRAL

    # FVG
    fvg: FVGAnalysis = field(default_factory=FVGAnalysis)

    # Order Blocks
    order_blocks: OBAnalysis = field(default_factory=OBAnalysis)

    # Liquidity
    liquidity: LiquidityAnalysis = field(default_factory=LiquidityAnalysis)

    # Fibonacci / OTE
    fibonacci: FibAnalysis = field(default_factory=FibAnalysis)

    # Мета
    current_price: float = 0.0
    bars_analyzed: int = 0

    # ----- Derived properties (вычисляемые) -----

    @property
    def last_break(self) -> Optional[StructureBreak]:
        return self.structure.last_break

    @property
    def has_choch(self) -> bool:
        """Был ли CHoCH (разворот) среди пробоев?"""
        return any(b.is_choch for b in self.structure.breaks)

    @property
    def has_bos(self) -> bool:
        return any(b.is_bos for b in self.structure.breaks)

    # DEV-96: направленные флаги (bullish = LONG, bearish = SHORT)
    @property
    def has_bullish_bos(self) -> bool:
        return any(b.break_type == BreakType.BULLISH_BOS for b in self.structure.breaks)

    @property
    def has_bearish_bos(self) -> bool:
        return any(b.break_type == BreakType.BEARISH_BOS for b in self.structure.breaks)

    @property
    def has_bullish_choch(self) -> bool:
        return any(b.break_type == BreakType.BULLISH_CHOCH for b in self.structure.breaks)

    @property
    def has_bearish_choch(self) -> bool:
        return any(b.break_type == BreakType.BEARISH_CHOCH for b in self.structure.breaks)

    @property
    def active_resistance(self) -> Optional[float]:
        return self.structure.active_resistance

    @property
    def active_support(self) -> Optional[float]:
        return self.structure.active_support

    @property
    def nearest_bull_ob(self) -> Optional[OrderBlock]:
        return self.order_blocks.nearest_bull

    @property
    def nearest_bear_ob(self) -> Optional[OrderBlock]:
        return self.order_blocks.nearest_bear

    @property
    def nearest_bull_fvg(self) -> Optional[FVG]:
        return self.fvg.nearest_bull

    @property
    def nearest_bear_fvg(self) -> Optional[FVG]:
        return self.fvg.nearest_bear

    @property
    def price_in_ote(self) -> bool:
        return self.fibonacci.active_ote is not None

    @property
    def has_bullish_ob_with_fvg(self) -> bool:
        """Суперсетап: бычий OB + бычий FVG перекрываются."""
        ob = self.nearest_bull_ob
        fvg = self.nearest_bull_fvg
        if not ob or not fvg:
            return False
        # Перекрытие зон
        return ob.bottom <= fvg.top and ob.top >= fvg.bottom

    @property
    def has_bearish_ob_with_fvg(self) -> bool:
        ob = self.nearest_bear_ob
        fvg = self.nearest_bear_fvg
        if not ob or not fvg:
            return False
        return ob.bottom <= fvg.top and ob.top >= fvg.bottom

    @property
    def nearest_buy_liquidity(self) -> Optional[LiquidityZone]:
        return self.liquidity.nearest_buy

    @property
    def nearest_sell_liquidity(self) -> Optional[LiquidityZone]:
        return self.liquidity.nearest_sell

    def to_features(self) -> Dict[str, object]:
        """
        Конвертирует SMCContext в плоский dict для features_json.
        Используется для ML обучения.
        """
        lb = self.last_break
        fib = self.fibonacci.active_ote

        return {
            "smc_trend": self.trend.value,
            "smc_has_choch": self.has_choch,
            "smc_has_bos": self.has_bos,
            # DEV-96: направленные флаги (backward-compat: старые остаются)
            "smc_has_bullish_bos":   self.has_bullish_bos,
            "smc_has_bearish_bos":   self.has_bearish_bos,
            "smc_has_bullish_choch": self.has_bullish_choch,
            "smc_has_bearish_choch": self.has_bearish_choch,
            "smc_last_break_type": lb.break_type.value if lb else None,
            "smc_last_break_strength": lb.strength if lb else 0,
            "smc_active_resistance": self.active_resistance,
            "smc_active_support": self.active_support,
            "smc_active_bull_fvg_count": len(self.fvg.active_bull),
            "smc_active_bear_fvg_count": len(self.fvg.active_bear),
            "smc_active_bull_ob_count": len(self.order_blocks.active_bull),
            "smc_active_bear_ob_count": len(self.order_blocks.active_bear),
            "smc_bull_ob_fvg_overlap": self.has_bullish_ob_with_fvg,
            "smc_bear_ob_fvg_overlap": self.has_bearish_ob_with_fvg,
            "smc_price_in_ote": self.price_in_ote,
            "smc_ote_direction": fib.direction if fib else None,
            "smc_buy_liq_count": len([z for z in self.liquidity.buy_side if z.is_active]),
            "smc_sell_liq_count": len([z for z in self.liquidity.sell_side if z.is_active]),
            "smc_nearest_buy_liq_strength": self.nearest_buy_liquidity.strength if self.nearest_buy_liquidity else 0,
            "smc_nearest_sell_liq_strength": self.nearest_sell_liquidity.strength if self.nearest_sell_liquidity else 0,
        }

    def summary(self) -> str:
        """Краткая строковая сводка для логирования."""
        parts = [f"trend={self.trend.value}"]
        if self.last_break:
            parts.append(f"last={self.last_break.break_type.value}")
        parts.append(f"fvg_bull={len(self.fvg.active_bull)}")
        parts.append(f"fvg_bear={len(self.fvg.active_bear)}")
        parts.append(f"ob_bull={len(self.order_blocks.active_bull)}")
        parts.append(f"ob_bear={len(self.order_blocks.active_bear)}")
        if self.price_in_ote:
            parts.append("IN_OTE")
        if self.has_bullish_ob_with_fvg:
            parts.append("BULL_SUPER")
        if self.has_bearish_ob_with_fvg:
            parts.append("BEAR_SUPER")
        return f"SMC({', '.join(parts)})"


# ---------------------------------------------------------------------------
# Единая точка входа
# ---------------------------------------------------------------------------

def analyze_smc(
    df: pd.DataFrame,
    swing_period: int = 5,
    fvg_min_size_pct: float = 0.05,
    cluster_tolerance_pct: float = 0.3,
) -> SMCContext:
    """
    Полный SMC-анализ для одного DataFrame (один символ, один таймфрейм).

    Вызывает все модули последовательно:
      swing_points → structure → fvg → order_blocks → liquidity → fibonacci

    Args:
        df: OHLCV DataFrame (минимум 30 баров).
        swing_period: период для swing points.
        fvg_min_size_pct: минимальный размер FVG.
        cluster_tolerance_pct: допуск кластеризации ликвидности.

    Returns:
        SMCContext — полный контекст SMC.

    Пример:
        >>> ctx = analyze_smc(df_15m, swing_period=5)
        >>> print(ctx.summary())
        SMC(trend=BULLISH, last=BULLISH_BOS, fvg_bull=2, ob_bull=1, IN_OTE)
    """
    empty = SMCContext()

    if df is None or len(df) < 30:
        return empty

    try:
        current_price = float(df["close"].iloc[-1])

        # 1. Structure (включает swing_points)
        structure = detect_structure(df, swing_period=swing_period)

        # 2. FVG
        fvg = detect_fvg(df, min_size_pct=fvg_min_size_pct)

        # 3. Order Blocks (зависит от structure)
        order_blocks = detect_order_blocks(df, structure)

        # 4. Liquidity (зависит от swing_analysis)
        liquidity = detect_liquidity(
            df, structure.swing_analysis,
            cluster_tolerance_pct=cluster_tolerance_pct,
        )

        # 5. Fibonacci (зависит от structure)
        fibonacci = detect_fibonacci(df, structure)

        # 6. OB + FVG overlap (помечаем OB у которых есть совпадающий FVG)
        _mark_fvg_overlap(order_blocks, fvg)

        return SMCContext(
            structure=structure,
            trend=structure.trend,
            fvg=fvg,
            order_blocks=order_blocks,
            liquidity=liquidity,
            fibonacci=fibonacci,
            current_price=current_price,
            bars_analyzed=len(df),
        )

    except Exception as e:
        logger.debug("analyze_smc error: %s", e, exc_info=True)
        return empty


def _mark_fvg_overlap(ob_analysis: OBAnalysis, fvg_analysis: FVGAnalysis) -> None:
    """Помечает Order Blocks у которых есть перекрытие с FVG."""
    for ob in ob_analysis.all_obs:
        fvg_list = fvg_analysis.active_bull if ob.ob_type.value == "BULLISH" else fvg_analysis.active_bear
        for fvg in fvg_list:
            if ob.bottom <= fvg.top and ob.top >= fvg.bottom:
                ob.has_fvg_overlap = True
                break


def build_mtf_smc_snapshot(
    smc_ctx: SMCContext,
    current_price: float,
    proximity_pct: float = 1.5,
) -> "MTFSMCSnapshot":
    """
    ARCH-51: Строит лёгкий торговый срез SMC для одного старшего TF.

    Args:
        smc_ctx: полный SMCContext старшего TF (4h или 1d).
        current_price: текущая цена (из младшего TF или тикера).
        proximity_pct: % расстояния до OB для признания «рядом» (default 1.5%).

    Returns:
        MTFSMCSnapshot — только торгово-значимые факты.
    """
    from core.signals.signal_models import MTFSMCSnapshot

    snap = MTFSMCSnapshot()
    if current_price <= 0:
        return snap

    prox = proximity_pct / 100.0

    # Bull OB рядом → поддержка для LONG
    for ob in smc_ctx.order_blocks.active_bull:
        if abs(ob.midpoint - current_price) / current_price <= prox:
            snap.bull_ob_nearby = True
            snap.ob_proximity_pct = abs(ob.midpoint - current_price) / current_price * 100
            break

    # Bear OB рядом → сопротивление для LONG
    for ob in smc_ctx.order_blocks.active_bear:
        if abs(ob.midpoint - current_price) / current_price <= prox:
            snap.bear_ob_nearby = True
            break

    # Bull FVG ПОД ценой → магнит/поддержка
    for fvg in smc_ctx.fvg.active_bull:
        if fvg.top < current_price:
            snap.fvg_support = True
            break

    # Bear FVG НАД ценой → магнит/сопротивление
    for fvg in smc_ctx.fvg.active_bear:
        if fvg.bottom > current_price:
            snap.fvg_resistance = True
            break

    # Последний структурный слом (CHoCH / BOS)
    if smc_ctx.structure and smc_ctx.structure.breaks:
        last_brk = smc_ctx.structure.breaks[-1]
        direction = "bullish" if last_brk.direction == "LONG" else "bearish"
        if last_brk.is_choch:
            snap.choch_direction = direction
        elif last_brk.is_bos:
            snap.bos_direction = direction

    return snap
