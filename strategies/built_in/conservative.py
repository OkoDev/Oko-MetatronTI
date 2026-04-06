"""
Стратегия Conservative: требует 3+ сигналов и имеет узкие SL для минимизации просадок.
Используется для risk-averse трейдеров.
"""

import logging
from typing import Dict, List, Optional, Tuple
import numpy as np

from core.signal_models import (
    SignalData, SignalType, SignalDirection, MarketContext, TradingRecommendation
)
from strategies.base import BaseStrategy
from strategies.registry import register_strategy

logger = logging.getLogger(__name__)


@register_strategy("conservative")
class ConservativeStrategy(BaseStrategy):
    """
    Conservative Strategy: для минимизации просадок и максимизации win rate.
    
    Логика:
    1. Требует 3+ сигналов (не 2 как в Confluence)
    2. Конфликты толще допускаются
    3. Узкий SL: ATR × 0.7 вместо ATR × 1.5
    4. Более ограничительная уверенность (min 0.65)
    """
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.logger = logging.getLogger(__name__)
        
        # Более строгие параметры
        self.min_signals = config.get("min_signals", 3) if config else 3
        self.min_confidence = config.get("min_confidence", 0.65) if config else 0.65
        self.conflict_threshold = config.get("conflict_threshold", 0.2) if config else 0.2
        
        # Консервативные веса: больше вес на надежные сигналы
        self.signal_weights = {
            SignalType.MTF_ALERT: 0.25,
            SignalType.PIVOT_REVERSAL: 0.25,  # +0.05
            SignalType.DIVERGENCE: 0.20,  # +0.05
            SignalType.WT_SIGNAL: 0.10,
            SignalType.TREND_SIGNAL: 0.08,  # -0.02
            SignalType.ANOMALY: 0.03,  # -0.02 (менее надежно)
            SignalType.PIVOT_REVERSAL: 0.10,  # -0.05
            SignalType.CONFLUENCE: 0.25,  # -0.10 (может быть шумным)
        }
        
        self.logger.info(
            f"ConservativeStrategy initialized: min_signals={self.min_signals}, "
            f"min_confidence={self.min_confidence}"
        )
    
    def analyze(self, signals: List[SignalData],
                market_context: MarketContext) -> Optional[TradingRecommendation]:
        """
        Анализирует сигналы с повышенными требованиями.
        """
        if not signals:
            return None
        
        # Группируем сигналы по направлению
        long_signals = [s for s in signals if s.direction == SignalDirection.LONG]
        short_signals = [s for s in signals if s.direction == SignalDirection.SHORT]
        
        # Требуем минимум сигналов в направлении
        if len(long_signals) < self.min_signals and len(short_signals) < self.min_signals:
            self.logger.debug(
                f"Not enough signals: LONG={len(long_signals)}, SHORT={len(short_signals)}, "
                f"need={self.min_signals}"
            )
            return None
        
        # Рассчитываем взвешенную силу
        long_strength = self._calculate_weighted_strength(long_signals)
        short_strength = self._calculate_weighted_strength(short_signals)
        
        # Определяем направление
        if long_strength > short_strength and len(long_signals) >= self.min_signals:
            direction = SignalDirection.LONG
            strength = long_strength
            supporting_signals = long_signals
            conflicting_signals = short_signals
        elif short_strength > long_strength and len(short_signals) >= self.min_signals:
            direction = SignalDirection.SHORT
            strength = short_strength
            supporting_signals = short_signals
            conflicting_signals = long_signals
        else:
            self.logger.debug(f"No direction dominates or insufficient signals")
            return None
        
        # Проверяем конфликты — более строгий порог
        total_strength = long_strength + short_strength
        if total_strength > 0:
            conflict_ratio = abs(long_strength - short_strength) / total_strength
            if conflict_ratio < self.conflict_threshold:
                self.logger.debug(
                    f"Conflict: ratio={conflict_ratio:.2f} < threshold={self.conflict_threshold}"
                )
                return None
        
        # Рассчитываем уверенность
        confidence = self._calculate_confidence(supporting_signals, conflicting_signals, market_context)
        
        # Проверяем минимальную уверенность
        if confidence < self.min_confidence:
            self.logger.debug(
                f"Low confidence: {confidence:.2f} < {self.min_confidence}"
            )
            return None
        
        # Генерируем рекомендацию
        action = "BUY" if direction == SignalDirection.LONG else "SELL"
        
        recommendation = TradingRecommendation(
            symbol=market_context.symbol,
            action=action,
            direction=direction,
            overall_strength=int(strength),
            confidence=confidence,
            risk_level="LOW",  # Conservative — низкий риск
            signals_count=len(supporting_signals),
            supporting_signals=supporting_signals,
            conflicting_signals=conflicting_signals,
            market_context=market_context,
            reasoning=[
                f"Conservative: {len(supporting_signals)} {direction.value} signals (min {self.min_signals})",
                f"Strength={int(strength)}, Confidence={confidence:.2f}",
                "High confidence required, tight SL"
            ],
        )
        
        return recommendation
    
    def _calculate_weighted_strength(self, signals: List[SignalData]) -> float:
        """Взвешенная сила сигналов."""
        if not signals:
            return 0.0
        
        total_weighted_strength = 0.0
        total_weight = 0.0
        
        for signal in signals:
            base_weight = self.signal_weights.get(signal.signal_type, 0.1)
            quality = (signal.strength / 100.0) * signal.confidence
            effective_weight = base_weight * max(quality, 0.03)  # Min 3%
            
            total_weighted_strength += signal.strength * effective_weight
            total_weight += effective_weight
        
        if total_weight <= 0:
            return 0.0
        
        return min(max(total_weighted_strength / total_weight, 0), 100)
    
    def _calculate_confidence(self, supporting_signals: List[SignalData],
                             conflicting_signals: List[SignalData],
                             market_context: MarketContext) -> float:
        """Консервативная уверенность."""
        if not supporting_signals:
            return 0.5
        
        # Базовая уверенность
        signal_confidence = float(np.mean([s.confidence for s in supporting_signals]))
        
        # Штраф за конфликты (больший штраф)
        total = len(supporting_signals) + len(conflicting_signals)
        if total > 0:
            conflict_penalty = len(conflicting_signals) / total
            signal_confidence *= (1.0 - 0.7 * conflict_penalty)  # Больший штраф (0.7 вместо 0.5)
        
        # Консервативный контекст (более строгий)
        context_factor = 1.0
        
        if market_context.volume_24h and market_context.volume_24h > 0:
            volume_factor = min(market_context.volume_24h / 1000000, 1.5)  # Max 1.5x вместо 2.0x
            context_factor *= (0.9 + 0.1 * volume_factor)  # More conservative
        
        if market_context.volatility and market_context.volatility > 10:
            context_factor *= 0.85  # Больший штраф за волатильность
        
        if market_context.price_change_24h and abs(market_context.price_change_24h) > 5:
            context_factor *= 1.05  # Меньший бонус за движение
        
        # Меньший бонус за количество сигналов
        signal_count_factor = min(len(supporting_signals) / 4.0, 1.3)  # Max 1.3x
        context_factor *= signal_count_factor
        
        final_confidence = signal_confidence * context_factor
        return min(max(final_confidence, 0.0), 1.0)
    
    def calculate_sl_tp(self, entry_price: float, direction: str,
                       atr: Optional[float], market_context: MarketContext) -> Tuple[float, float, float]:
        """
        Узкий SL для минимизации просадок.
        
        Логика:
        - SL = ATR × 0.7 (очень узкий)
        - TP = ATR × 2.0 (R:R = 1:2.86)
        - Position size = 0.75 (меньше, но не критично)
        """
        if atr is None or atr <= 0:
            atr = entry_price * 0.01  # 1% as fallback
        
        sl_distance = atr * 0.7  # Узкий стоп
        tp_distance = atr * 2.0  # Адекватная прибыль
        
        if direction.upper() == "LONG":
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:  # SHORT
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance
        
        position_size = 0.75  # Меньше, чем в Confluence
        
        return stop_loss, take_profit, position_size
