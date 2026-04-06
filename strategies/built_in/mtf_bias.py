"""
Стратегия MTF Bias: только MTF сигналы с высокой силой.
Более простая и быстрая, используется для скальпинга на 15m.
"""

import logging
from typing import Dict, List, Optional, Tuple

from core.signal_models import (
    SignalData, SignalType, SignalDirection, MarketContext, TradingRecommendation
)
from strategies.base import BaseStrategy
from strategies.registry import register_strategy

logger = logging.getLogger(__name__)


@register_strategy("mtf_bias")
class MTFBiasStrategy(BaseStrategy):
    """
    MTF Bias Strategy: вход по MTF alerts только с высокой силой.
    
    Логика:
    1. Фильтрует только MTF сигналы
    2. Требует strength >= min_strength
    3. Генерирует простой вход с узким SL для скальпинга
    """
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.logger = logging.getLogger(__name__)
        
        # Параметры
        self.min_strength = config.get("min_strength", 60) if config else 60
        self.require_confluence = config.get("require_confluence", False) if config else False
        
        self.logger.info(
            f"MTFBiasStrategy initialized: min_strength={self.min_strength}, "
            f"require_confluence={self.require_confluence}"
        )
    
    def analyze(self, signals: List[SignalData],
                market_context: MarketContext) -> Optional[TradingRecommendation]:
        """
        Анализирует сигналы: ищет сильные MTF alerts.
        """
        if not signals:
            return None
        
        # Фильтруем только MTF_BIAS сигналы (от автономного интерпретатора 7 TF)
        mtf_signals = [s for s in signals
                       if s.signal_type == SignalType.MTF_BIAS]

        # Если нет MTF_BIAS сигналов, нет торговли
        if not mtf_signals:
            return None
        
        # Если требуем конфлюэнцию, ищем дополнительный сигнал
        if self.require_confluence:
            supporting_signals = [s for s in signals
                                 if s.signal_type != SignalType.MTF_BIAS]
            if not supporting_signals:
                self.logger.debug("No confluence signal found, skipping MTF signal")
                return None
        else:
            supporting_signals = mtf_signals
        
        # Берём самый сильный MTF сигнал
        best_signal = max(mtf_signals, key=lambda s: s.strength)
        
        # Проверяем минимальную силу
        if best_signal.strength < self.min_strength:
            self.logger.debug(
                f"MTF signal too weak: {best_signal.strength} < {self.min_strength}"
            )
            return None
        
        # Проверяем направление
        if best_signal.direction == SignalDirection.NEUTRAL:
            return None
        
        # Генерируем рекомендацию
        action = "BUY" if best_signal.direction == SignalDirection.LONG else "SELL"
        
        recommendation = TradingRecommendation(
            symbol=market_context.symbol,
            action=action,
            direction=best_signal.direction,
            overall_strength=best_signal.strength,
            confidence=best_signal.confidence,
            risk_level="LOW",  # MTFBias — более консервативная стратегия
            signals_count=1,
            supporting_signals=[best_signal],
            conflicting_signals=[],
            market_context=market_context,
            reasoning=[
                "MTF Bias: одиночный сильный MTF сигнал",
                f"Strength={best_signal.strength}, Confidence={best_signal.confidence:.2f}"
            ],
        )
        
        return recommendation
    
    def calculate_sl_tp(self, entry_price: float, direction: str,
                       atr: Optional[float], market_context: MarketContext) -> Tuple[float, float, float]:
        """
        Узкий SL для скальпинга.
        
        Логика:
        - SL = ATR × 0.7 (минимизируем losses)
        - TP = ATR × 1.4 (R:R = 1:2)
        - Position size = 0.5 (меньше, так как расчетный SL выше)
        """
        if atr is None or atr <= 0:
            atr = entry_price * 0.015  # 1.5% as fallback
        
        sl_distance = atr * 0.7
        tp_distance = atr * 1.4
        
        if direction.upper() == "LONG":
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:  # SHORT
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance
        
        position_size = 0.5  # Smaller position for tight stops
        
        return stop_loss, take_profit, position_size
