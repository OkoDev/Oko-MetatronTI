"""
Базовый интерфейс для всех торговых стратегий.
Каждая стратегия должна реализовать методы analyze и calculate_sl_tp.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
from core.signal_models import SignalData, TradingRecommendation, MarketContext, SignalDirection


class BaseStrategy(ABC):
    """
    Интерфейс для торговой стратегии.
    
    Методы:
    - analyze(): принимает сигналы → генерирует рекомендацию (BUY/SELL/HOLD)
    - calculate_sl_tp(): рассчитывает Stop Loss, Take Profit и размер позиции
    - backtest(): тестирует стратегию на исторических данных
    """
    
    def __init__(self, config: Dict = None):
        """
        Инициализация стратегии.
        
        Args:
            config: Конфигурация стратегии из config.yaml
        """
        self.config = config or {}
        self.name = self.__class__.__name__
        self.logger = None  # будет установлено в __init__ через logging.getLogger
        self.backtest_results = None
    
    @abstractmethod
    def analyze(self, signals: List[SignalData], 
                market_context: MarketContext) -> Optional[TradingRecommendation]:
        """
        Главный метод анализа: сигналы → рекомендация.
        
        Args:
            signals: Список найденных сигналов
            market_context: Контекст рынка (цена, объем, волатильность и т.д.)
        
        Returns:
            TradingRecommendation если стратегия генерирует решение,
            None если нет достаточных условий для входа
        """
        pass
    
    @abstractmethod
    def calculate_sl_tp(self, entry_price: float, direction: str, 
                       atr: Optional[float], market_context: MarketContext) -> Tuple[float, float, float]:
        """
        Расчет Stop Loss, Take Profit и размера позиции.
        
        Args:
            entry_price: Цена входа
            direction: "LONG" или "SHORT"
            atr: Average True Range (опционально)
            market_context: Контекст рынка
        
        Returns:
            Кортеж (stop_loss_price, take_profit_price, position_size)
        """
        pass
    
    def backtest(self, ohlcv_data: Dict, pairs: List[str]) -> Dict[str, Any]:
        """
        Тестирование стратегии на исторических данных.
        Может быть переопределено в подклассах.
        
        Args:
            ohlcv_data: Исторические OHLCV данные
            pairs: Список пар для тестирования
        
        Returns:
            Результаты бэктестирования: {symbol: {win_rate, avg_r, trades_count, ...}}
        """
        return {"status": "not_implemented"}
    
    def get_info(self) -> Dict[str, Any]:
        """Возвращает информацию о стратегии."""
        return {
            "name": self.name,
            "config": self.config,
            "backtest_results": self.backtest_results
        }
