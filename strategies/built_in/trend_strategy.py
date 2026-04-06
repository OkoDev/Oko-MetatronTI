"""
TrendFollowingStrategy — стратегия следования тренду (ARCH-09).

Принимает: TREND_SIGNAL, MTF_BIAS, SMC_STRUCTURE, CONFLUENCE.
Требует ≥ min_signals совпадающих подтверждений (по умолчанию 2).

Ключевое отличие от ReversalStrategy:
- Confidence включает signal_count_factor (штраф за 1 подтверждение, бонус за 3+).
  Трендовые сигналы сильнее при конфлюэнции нескольких ТФ.
- Бонус за MTF alignment (если есть MTF_BIAS — добавляет +0.05 к confidence).
- Широкий SL: ATR × 2.0 (тренд должен дышать).

Параметры config.yaml (под ключом trading.strategies.trend_following):
  min_signals:       int   = 2     — минимум подтверждающих сигналов
  min_strength:      int   = 55    — порог силы сигнала
  min_confidence:    float = 0.55  — минимальная итоговая confidence
  conflict_threshold float = 0.25  — порог конфликта
  tp_rr:             float = 3.0   — Risk/Reward для TP
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

from core.signal_models import (
    MarketContext,
    SignalData,
    SignalDirection,
    SignalType,
    TradingRecommendation,
)
from strategies.base import BaseStrategy
from strategies.registry import register_strategy

logger = logging.getLogger(__name__)

_TREND_TYPES = frozenset({
    SignalType.TREND_SIGNAL,
    SignalType.MTF_BIAS,
    SignalType.SMC_STRUCTURE,
    SignalType.CONFLUENCE,
})


@register_strategy("trend_following")
class TrendFollowingStrategy(BaseStrategy):
    """
    Стратегия следования тренду: ≥2 совпадающих трендовых подтверждения.

    Confidence с signal_count_factor — требует конфлюэнции нескольких ТФ.
    """

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.logger = logging.getLogger(__name__)
        cfg = config or {}
        self.min_signals       = int(cfg.get("min_signals",       2))
        self.min_strength      = int(cfg.get("min_strength",      55))
        self.min_confidence    = float(cfg.get("min_confidence",  0.55))
        self.conflict_threshold = float(cfg.get("conflict_threshold", 0.25))
        self.tp_rr             = float(cfg.get("tp_rr",           3.0))
        self.logger.info(
            "TrendFollowingStrategy: min_signals=%d min_strength=%d tp_rr=%.1f",
            self.min_signals, self.min_strength, self.tp_rr,
        )

    # ── analyze ──────────────────────────────────────────────────────────────

    def analyze(
        self,
        signals: List[SignalData],
        market_context: MarketContext,
    ) -> Optional[TradingRecommendation]:
        """
        Ищет трендовые подтверждения. Требует ≥ min_signals в одном направлении.
        """
        if not signals:
            return None

        trend_sigs = [
            s for s in signals
            if s.signal_type in _TREND_TYPES and s.strength >= self.min_strength
        ]
        if not trend_sigs:
            return None

        long_sigs  = [s for s in trend_sigs if s.direction == SignalDirection.LONG]
        short_sigs = [s for s in trend_sigs if s.direction == SignalDirection.SHORT]

        # Нужно минимум min_signals в одном направлении
        if len(long_sigs) >= self.min_signals and len(long_sigs) >= len(short_sigs):
            direction      = SignalDirection.LONG
            supporting     = long_sigs
            conflicting    = short_sigs
        elif len(short_sigs) >= self.min_signals:
            direction      = SignalDirection.SHORT
            supporting     = short_sigs
            conflicting    = long_sigs
        else:
            logger.debug(
                "[trend] %s: недостаточно сигналов LONG=%d SHORT=%d (min=%d)",
                market_context.symbol, len(long_sigs), len(short_sigs), self.min_signals,
            )
            return None

        # Проверяем конфликт
        long_str  = sum(s.strength for s in long_sigs)
        short_str = sum(s.strength for s in short_sigs)
        total_str = long_str + short_str
        if total_str > 0:
            conflict_ratio = abs(long_str - short_str) / total_str
            if conflict_ratio < self.conflict_threshold:
                logger.debug(
                    "[trend] %s: конфликт ratio=%.2f < %.2f — skip",
                    market_context.symbol, conflict_ratio, self.conflict_threshold,
                )
                return None

        confidence = _trend_confidence(supporting, conflicting, market_context, self.min_signals)
        if confidence < self.min_confidence:
            logger.debug(
                "[trend] %s: conf=%.2f < %.2f — skip",
                market_context.symbol, confidence, self.min_confidence,
            )
            return None

        # Взвешенная сила по всем поддерживающим сигналам
        avg_strength = int(np.mean([s.strength for s in supporting]))

        action = "BUY" if direction == SignalDirection.LONG else "SELL"
        entry  = market_context.current_price
        sl, tp, _ = self.calculate_sl_tp(entry, direction.value, market_context.atr, market_context)

        signal_names = ", ".join(sorted({s.signal_type.value for s in supporting}))
        reasoning = [
            f"TrendFollowing {direction.value}: {len(supporting)} сигналов ({signal_names})",
            f"Avg strength={avg_strength}, Confidence={confidence:.2f}",
        ]
        # MTF alignment бонус
        has_mtf = any(s.signal_type == SignalType.MTF_BIAS for s in supporting)
        if has_mtf:
            reasoning.append("MTF alignment bonus: MTF_BIAS подтверждает направление")

        return TradingRecommendation(
            symbol=market_context.symbol,
            action=action,
            direction=direction,
            overall_strength=avg_strength,
            confidence=confidence,
            risk_level=self._risk_level(len(supporting)),
            signals_count=len(supporting),
            supporting_signals=supporting,
            conflicting_signals=conflicting,
            market_context=market_context,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            sl_source="atr_2.0",
            tp_source=f"atr_rr_{self.tp_rr:.1f}",
            reasoning=reasoning,
            metadata={"strategy_type": "trend_following"},
        )

    # ── calculate_sl_tp ───────────────────────────────────────────────────────

    def calculate_sl_tp(
        self,
        entry_price: float,
        direction: str,
        atr: Optional[float],
        market_context: MarketContext,
    ) -> Tuple[float, float, float]:
        """
        Широкий SL для тренда: ATR × 2.0.
        TP = SL × tp_rr (по умолчанию 3.0 → RR 1:3).
        """
        if not atr or atr <= 0:
            atr = (entry_price or 1.0) * 0.02
        sl_dist = atr * 2.0
        tp_dist = sl_dist * self.tp_rr
        is_long = direction.upper() == "LONG"
        sl = (entry_price - sl_dist) if is_long else (entry_price + sl_dist)
        tp = (entry_price + tp_dist) if is_long else (entry_price - tp_dist)
        return sl, tp, 1.0

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _risk_level(signal_count: int) -> str:
        if signal_count >= 3:
            return "LOW"
        if signal_count == 2:
            return "MEDIUM"
        return "HIGH"


def _trend_confidence(
    supporting: List[SignalData],
    conflicting: List[SignalData],
    ctx: MarketContext,
    min_signals: int = 2,
) -> float:
    """
    Confidence с signal_count_factor — требует конфлюэнции нескольких ТФ.

    count_factor = count / min_signals:
      count < min_signals → < 1.0 (штраф)
      count == min_signals → 1.0 (нейтрально)
      count > min_signals → > 1.0 (бонус, max 1.5)
    """
    if not supporting:
        return 0.5

    base = float(np.mean([s.confidence for s in supporting]))

    # Штраф за конфликты
    total = len(supporting) + len(conflicting)
    if total > 0 and conflicting:
        conflict_penalty = len(conflicting) / total
        base *= (1.0 - 0.5 * conflict_penalty)

    # MTF alignment бонус
    has_mtf = any(s.signal_type == SignalType.MTF_BIAS for s in supporting)
    if has_mtf:
        base = min(base * 1.05, 1.0)

    # Контекстный фактор
    ctx_factor = 1.0
    if ctx.volatility and ctx.volatility > 10:
        ctx_factor *= 0.9
    if abs(ctx.price_change_24h or 0) > 5:
        ctx_factor = min(ctx_factor * 1.1, 1.5)

    # signal_count_factor: нейтральный при min_signals, штраф ниже, бонус выше
    count_factor = min(len(supporting) / max(min_signals, 1), 1.5)
    ctx_factor *= count_factor

    conf = base * ctx_factor

    # ARCH-17: SMC бонусы для трендовых сигналов
    smc = getattr(ctx, "smc_context", None)
    if smc is not None:
        # BOS = подтверждение тренда → усиливает trend following
        if smc.has_bos:
            conf = min(conf + 0.04, 1.0)
        # OTE зона → оптимальный откат внутри тренда
        if smc.price_in_ote:
            conf = min(conf + 0.05, 1.0)
        # OB + FVG суперсетап в направлении тренда
        is_long = supporting[0].direction == SignalDirection.LONG if supporting else True
        if is_long and smc.has_bullish_ob_with_fvg:
            conf = min(conf + 0.06, 1.0)
        elif not is_long and smc.has_bearish_ob_with_fvg:
            conf = min(conf + 0.06, 1.0)

    return round(min(conf, 1.0), 4)
