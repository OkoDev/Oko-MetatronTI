"""
Стратегия Confluence (по умолчанию):
Требует 2+ сигналов различных типов, использует адаптивные веса и ML-коррекции.
Основана на текущей логике trading_intelligence.analyze_symbol().
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

from core.signal_models import (
    SignalData, SignalType, SignalDirection, MarketContext, TradingRecommendation
)
from strategies.base import BaseStrategy
from strategies.registry import register_strategy

logger = logging.getLogger(__name__)


@register_strategy("confluence")
class ConfluenceStrategy(BaseStrategy):
    """
    Confluence Strategy: требует конфлюэнции 2+ сигналов от разных источников.
    
    Логика:
    1. Фильтрует сигналы с низкой уверенностью
    2. Группирует по направлению (LONG/SHORT)
    3. Считает взвешенную силу с учетом исторической производительности
    4. Проверяет конфликты между сигналами
    5. Генерирует рекомендацию с адаптивным SL/TP
    """
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.logger = logging.getLogger(__name__)
        
        # Пороги для анализа
        self.min_signals = config.get("min_signals", 2) if config else 2
        self.conflict_threshold = config.get("conflict_threshold", 0.3) if config else 0.3
        
        # Веса сигналов (из config или дефолты)
        self.signal_weights = self._init_signal_weights(config)
        
        self.logger.info(f"ConfluenceStrategy initialized: min_signals={self.min_signals}")
    
    def _init_signal_weights(self, config: Dict) -> Dict[SignalType, float]:
        """Инициализирует веса сигналов из конфига или использует дефолты."""
        default_weights = {
            SignalType.MTF_SIGNAL: 0.25,
            SignalType.MTF_ALERT: 0.30,
            SignalType.PIVOT_REVERSAL: 0.20,
            SignalType.DIVERGENCE: 0.15,
            SignalType.WT_SIGNAL: 0.10,
            SignalType.TREND_SIGNAL: 0.10,
            SignalType.ANOMALY: 0.05,
            SignalType.PIVOT_ALERT: 0.15,
            SignalType.CONFLUENCE: 0.35,
        }
        
        if config and "signal_weights" in config:
            # Попытка загрузить веса из конфига
            try:
                custom_weights = config["signal_weights"]
                if isinstance(custom_weights, dict):
                    # Преобразуем строки в SignalType enum
                    for key, value in custom_weights.items():
                        try:
                            sig_type = SignalType[key.upper()]
                            default_weights[sig_type] = value
                        except KeyError:
                            pass
            except Exception as e:
                self.logger.warning(f"Failed to load custom weights: {e}")
        
        return default_weights
    
    def analyze(self, signals: List[SignalData], 
                market_context: MarketContext) -> Optional[TradingRecommendation]:
        """
        Анализирует сигналы и генерирует рекомендацию.
        
        Основная логика:
        1. Группирует сигналы по направлению
        2. Вычисляет взвешенную силу
        3. Проверяет конфликты
        4. Возвращает рекомендацию или None
        """
        if not signals:
            return None
        
        # Группируем сигналы по направлению
        long_signals = [s for s in signals if s.direction == SignalDirection.LONG]
        short_signals = [s for s in signals if s.direction == SignalDirection.SHORT]
        
        # Рассчитываем взвешенную силу
        long_strength = self._calculate_weighted_strength(long_signals)
        short_strength = self._calculate_weighted_strength(short_signals)
        
        # Определяем доминирующее направление
        if long_strength > short_strength:
            direction = SignalDirection.LONG
            strength = long_strength
            supporting_signals = long_signals
            conflicting_signals = short_signals
        elif short_strength > long_strength:
            direction = SignalDirection.SHORT
            strength = short_strength
            supporting_signals = short_signals
            conflicting_signals = long_signals
        else:
            return None  # Нет явного доминирования
        
        # Проверяем конфликты (если сигналы почти равны, это конфликт)
        total_strength = long_strength + short_strength
        if total_strength > 0:
            conflict_ratio = abs(long_strength - short_strength) / total_strength
            if conflict_ratio < self.conflict_threshold:
                # Сигналы конфликтуют — не генерируем рекомендацию
                self.logger.debug(
                    f"Conflict detected: LONG={long_strength} vs SHORT={short_strength} "
                    f"(ratio={conflict_ratio:.2f} < {self.conflict_threshold})"
                )
                return None
        
        # Проверяем минимальное количество сигналов
        if len(supporting_signals) < self.min_signals:
            self.logger.debug(
                f"Insufficient signals: {len(supporting_signals)} < {self.min_signals}"
            )
            return None
        
        # Рассчитываем уверенность
        confidence = self._calculate_confidence(
            supporting_signals, conflicting_signals, market_context
        )
        
        # Генерируем рекомендацию
        action = "BUY" if direction == SignalDirection.LONG else "SELL"
        
        recommendation = TradingRecommendation(
            symbol=market_context.symbol,
            action=action,
            direction=direction,
            overall_strength=int(strength),
            confidence=confidence,
            risk_level="MEDIUM",  # Default, может быть переопределён позже
            signals_count=len(signals),
            supporting_signals=supporting_signals,
            conflicting_signals=conflicting_signals,
            market_context=market_context,
            reasoning=[
                f"Confluence: {len(supporting_signals)} {direction.value} signals",
                f"Strength={int(strength)}, Confidence={confidence:.2f}"
            ],
        )
        
        return recommendation
    
    def _calculate_weighted_strength(self, signals: List[SignalData]) -> float:
        """
        Рассчитывает взвешенную силу сигналов.
        Слабые сигналы учитываются с меньшим весом, но не игнорируются.
        """
        if not signals:
            return 0.0
        
        total_weighted_strength = 0.0
        total_weight = 0.0
        
        for signal in signals:
            # Базовый вес по типу сигнала
            base_weight = self.signal_weights.get(signal.signal_type, 0.1)
            
            # Корректируем вес по качеству сигнала
            quality = (signal.strength / 100.0) * signal.confidence
            effective_weight = base_weight * max(quality, 0.05)  # Минимум 5% от базового веса
            
            total_weighted_strength += signal.strength * effective_weight
            total_weight += effective_weight
        
        if total_weight <= 0:
            return 0.0
        
        weighted_average = total_weighted_strength / total_weight
        return min(max(weighted_average, 0), 100)  # Клипуем в [0, 100]
    
    def _calculate_confidence(self, supporting_signals: List[SignalData],
                             conflicting_signals: List[SignalData],
                             market_context: MarketContext) -> float:
        """
        Рассчитывает уверенность на основе поддерживающих сигналов и контекста.
        """
        if not supporting_signals:
            return 0.5
        
        # График уверенность из поддерживающих сигналов
        signal_confidence = float(np.mean([s.confidence for s in supporting_signals]))
        
        # Штраф за конфликтующие сигналы
        total_signals = len(supporting_signals) + len(conflicting_signals)
        if total_signals > 0:
            conflict_penalty = len(conflicting_signals) / total_signals
            signal_confidence *= (1.0 - 0.5 * conflict_penalty)
        
        # Коэффициент контекста
        context_factor = 1.0
        
        if market_context.volume_24h and market_context.volume_24h > 0:
            volume_factor = min(market_context.volume_24h / 1000000, 2.0)
            context_factor *= (0.8 + 0.2 * volume_factor)
        
        if market_context.volatility and market_context.volatility > 10:
            context_factor *= 0.9  # При высокой волатильности снижаем уверенность
        
        if market_context.price_change_24h and abs(market_context.price_change_24h) > 5:
            context_factor *= 1.1  # При большом движении цены повышаем уверенность
        
        # Бонус за количество сигналов
        signal_count_factor = min(len(supporting_signals) / 3.0, 1.5)  # Макс +50%
        context_factor *= signal_count_factor
        
        final_confidence = signal_confidence * context_factor
        return min(max(final_confidence, 0.0), 1.0)
    
    def calculate_sl_tp(self, entry_price: float, direction: str,
                       atr: Optional[float], market_context: MarketContext) -> Tuple[float, float, float]:
        """
        Рассчитывает Stop Loss, Take Profit и размер позиции.
        
        Логика:
        - SL = ATR × 1.5 (защита от случайных спайков)
        - TP = ATR × 3.0 (R:R = 1:2)
        - Position size = 1.0 (standard)
        """
        if atr is None or atr <= 0:
            # Fallback если ATR не доступен
            atr = entry_price * 0.02  # 2% как резерв
        
        sl_distance = atr * 1.5
        tp_distance = atr * 3.0
        
        if direction.upper() == "LONG":
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:  # SHORT
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance
        
        position_size = 1.0  # Standard size
        
        return stop_loss, take_profit, position_size
