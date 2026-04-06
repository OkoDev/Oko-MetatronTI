"""
ReversalStrategy — стратегия разворота (ARCH-09).

Принимает: WT_SIGNAL, WT_B_SIGNAL, PIVOT_REVERSAL, DIVERGENCE.
Достаточно 1 качественного сигнала (strength ≥ min_strength).

Ключевое отличие от ConfluenceStrategy:
- Confidence = signal.confidence напрямую, БЕЗ penalty за "мало подтверждений".
  Разворотные сигналы по природе одиночные — штраф signal_count_factor убивает WR.
- Фильтр конфликта: если LONG и SHORT оба есть и близки по силе → skip.

Параметры config.yaml (под ключом trading.strategies.reversal):
  min_strength:      int   = 70    — минимальная сила сигнала
  min_confidence:    float = 0.60  — минимальная итоговая confidence
  conflict_margin:   float = 0.15  — порог конфликта (|long-short|/max < margin → skip)
  tp_rr:             float = 2.0   — Risk/Reward для TP (TP = entry ± sl_dist × tp_rr)
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

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

_REVERSAL_TYPES = frozenset({
    SignalType.WT_SIGNAL,
    SignalType.WT_B_SIGNAL,
    SignalType.PIVOT_REVERSAL,
    SignalType.DIVERGENCE,
})


@register_strategy("reversal")
class ReversalStrategy(BaseStrategy):
    """
    Стратегия разворота: 1 качественный сигнал (WT_B / PIVOT_REVERSAL / DIVERGENCE / WT).

    Confidence рассчитывается без penalty за количество сигналов,
    потому что разворотные сигналы по природе одиночные.
    """

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.logger = logging.getLogger(__name__)
        cfg = config or {}
        self.min_strength    = int(cfg.get("min_strength",   70))
        self.min_confidence  = float(cfg.get("min_confidence", 0.60))
        self.conflict_margin = float(cfg.get("conflict_margin", 0.15))
        self.tp_rr           = float(cfg.get("tp_rr",         2.0))
        self.logger.info(
            "ReversalStrategy: min_strength=%d min_confidence=%.2f tp_rr=%.1f",
            self.min_strength, self.min_confidence, self.tp_rr,
        )

    # ── analyze ──────────────────────────────────────────────────────────────

    def analyze(
        self,
        signals: List[SignalData],
        market_context: MarketContext,
    ) -> Optional[TradingRecommendation]:
        """
        Ищет разворотные сигналы. Достаточно 1 качественного.
        """
        if not signals:
            return None

        rev_sigs = [
            s for s in signals
            if s.signal_type in _REVERSAL_TYPES and s.strength >= self.min_strength
        ]
        if not rev_sigs:
            return None

        long_sigs  = [s for s in rev_sigs if s.direction == SignalDirection.LONG]
        short_sigs = [s for s in rev_sigs if s.direction == SignalDirection.SHORT]

        # Проверяем конфликт
        long_score  = max((s.strength * s.confidence for s in long_sigs),  default=0.0)
        short_score = max((s.strength * s.confidence for s in short_sigs), default=0.0)

        if long_score > 0 and short_score > 0:
            denom = max(long_score, short_score)
            if abs(long_score - short_score) / denom < self.conflict_margin:
                logger.debug(
                    "[reversal] %s: конфликт LONG=%.1f SHORT=%.1f — skip",
                    market_context.symbol, long_score, short_score,
                )
                return None

        if long_score >= short_score and long_sigs:
            winner_sigs = long_sigs
            direction   = SignalDirection.LONG
        elif short_sigs:
            winner_sigs = short_sigs
            direction   = SignalDirection.SHORT
        else:
            return None

        best = max(winner_sigs, key=lambda s: s.strength * s.confidence)

        # ── Confidence БЕЗ signal_count_factor ───────────────────────────────
        # Используем confidence сигнала напрямую — он уже откалиброван детектором.
        # Лёгкая корректировка контекстом (волатильность), без штрафа за одиночность.
        confidence = _reversal_confidence(best, market_context)
        if confidence < self.min_confidence:
            logger.debug(
                "[reversal] %s: conf=%.2f < %.2f — skip",
                market_context.symbol, confidence, self.min_confidence,
            )
            return None

        action = "BUY" if direction == SignalDirection.LONG else "SELL"
        entry  = market_context.current_price
        sl, tp, _ = self.calculate_sl_tp(entry, direction.value, market_context.atr, market_context)

        conflicting = [s for s in rev_sigs if s.direction != direction]

        reasoning = [
            f"Reversal {direction.value}: {best.signal_type.value} str={best.strength}",
            f"Confidence={confidence:.2f} (direct, no count-penalty)",
        ]
        if len(winner_sigs) > 1:
            extras = [s.signal_type.value for s in winner_sigs if s is not best]
            reasoning.append(f"Дополнительно: {', '.join(extras)}")

        return TradingRecommendation(
            symbol=market_context.symbol,
            action=action,
            direction=direction,
            overall_strength=best.strength,
            confidence=confidence,
            risk_level=self._risk_level(best.strength),
            signals_count=len(winner_sigs),
            supporting_signals=winner_sigs,
            conflicting_signals=conflicting,
            market_context=market_context,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            sl_source="atr_1.5",
            tp_source=f"atr_rr_{self.tp_rr:.1f}",
            reasoning=reasoning,
            metadata={"strategy_type": "reversal"},
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
        SL = ATR × 1.5, TP = SL × tp_rr.
        В production pipeline поверх этого применяется структурный SL
        из recommendation_generator (swing_low/high + FVG).
        """
        if not atr or atr <= 0:
            atr = (entry_price or 1.0) * 0.02
        sl_dist = atr * 1.5
        tp_dist = sl_dist * self.tp_rr
        is_long = direction.upper() == "LONG"
        sl = (entry_price - sl_dist) if is_long else (entry_price + sl_dist)
        tp = (entry_price + tp_dist) if is_long else (entry_price - tp_dist)
        return sl, tp, 1.0

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _risk_level(strength: int) -> str:
        if strength >= 80:
            return "LOW"
        if strength >= 70:
            return "MEDIUM"
        return "HIGH"


def _reversal_confidence(signal: SignalData, ctx: MarketContext) -> float:
    """
    Уверенность разворотного сигнала — без штрафа за количество.
    Только лёгкий контекстный фактор.
    """
    conf = signal.confidence

    # Штраф за высокую волатильность (риск пробоя уровня)
    if ctx.volatility and ctx.volatility > 15:
        conf *= 0.92
    elif ctx.volatility and ctx.volatility > 10:
        conf *= 0.96

    # Бонус за сильное движение (подтверждает давление)
    if abs(ctx.price_change_24h or 0) > 5:
        conf = min(conf * 1.05, 1.0)

    # ARCH-17: SMC бонусы для разворотных сигналов
    smc = getattr(ctx, "smc_context", None)
    if smc is not None:
        # CHoCH = разворот структуры → подтверждает разворотный сигнал
        if smc.has_choch:
            conf = min(conf + 0.05, 1.0)
        # Суперсетап: OB + FVG перекрытие → двойное подтверждение зоны
        is_long = signal.direction == SignalDirection.LONG
        if is_long and smc.has_bullish_ob_with_fvg:
            conf = min(conf + 0.07, 1.0)
        elif not is_long and smc.has_bearish_ob_with_fvg:
            conf = min(conf + 0.07, 1.0)
        # Цена в OTE зоне → оптимальный откат
        if smc.price_in_ote:
            conf = min(conf + 0.04, 1.0)

    return round(min(conf, 1.0), 4)
