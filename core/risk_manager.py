"""
Модуль для управления рисками в торговой системе
Обеспечивает контроль рисков, позиционирование и защиту капитала
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class RiskLevel(Enum):
    """Уровни риска"""
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"

class PositionSize(Enum):
    """Размеры позиций"""
    MICRO = "MICRO"      # 0.1% от капитала
    SMALL = "SMALL"      # 0.5% от капитала
    MEDIUM = "MEDIUM"    # 1.0% от капитала
    LARGE = "LARGE"      # 2.0% от капитала
    MAX = "MAX"          # 5.0% от капитала

@dataclass
class RiskProfile:
    """Профиль риска для символа"""
    symbol: str
    volatility: float
    risk_level: RiskLevel
    max_position_size: float
    stop_loss_percent: float
    take_profit_percent: float
    max_daily_loss: float
    max_consecutive_losses: int
    correlation_risk: float
    liquidity_risk: float
    last_updated: datetime

@dataclass
class PositionRisk:
    """Риск конкретной позиции"""
    symbol: str
    entry_price: float
    position_size: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    risk_percent: float
    potential_profit: float
    potential_loss: float
    risk_reward_ratio: float
    max_drawdown: float
    position_value: float

class RiskManager:
    """
    Менеджер рисков для торговой системы
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        
        # Базовые настройки риска
        self.base_capital = self.config.get('base_capital', 10000.0)
        self.max_risk_per_trade = self.config.get('max_risk_per_trade', 0.02)  # 2%
        self.max_daily_risk = self.config.get('max_daily_risk', 0.05)  # 5%
        self.max_portfolio_risk = self.config.get('max_portfolio_risk', 0.20)  # 20%
        
        # Настройки позиционирования
        self.position_sizes = {
            PositionSize.MICRO: 0.001,    # 0.1%
            PositionSize.SMALL: 0.005,    # 0.5%
            PositionSize.MEDIUM: 0.01,    # 1.0%
            PositionSize.LARGE: 0.02,     # 2.0%
            PositionSize.MAX: 0.05        # 5.0%
        }
        
        # Профили риска для символов
        self.risk_profiles: Dict[str, RiskProfile] = {}
        
        # Активные позиции
        self.active_positions: Dict[str, PositionRisk] = {}
        
        # Статистика рисков
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_losses = 0
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0
        
        # Корреляционная матрица
        self.correlation_matrix: Dict[str, Dict[str, float]] = {}
        
        # История рисков
        self.risk_history: List[Dict[str, Any]] = []
    
    def calculate_volatility(self, prices: pd.Series, period: int = 20) -> float:
        """Рассчитывает волатильность"""
        try:
            returns = prices.pct_change().dropna()
            volatility = returns.rolling(period).std().iloc[-1] * math.sqrt(24) * 100  # Годовая волатильность
            return volatility
        except:
            return 10.0  # По умолчанию 10%
    
    def assess_risk_level(self, symbol: str, volatility: float, volume: float, 
                         price_change_24h: float) -> RiskLevel:
        """Оценивает уровень риска для символа"""
        risk_score = 0
        
        # Волатильность (0-40 баллов)
        if volatility < 10:
            risk_score += 0
        elif volatility < 20:
            risk_score += 10
        elif volatility < 30:
            risk_score += 20
        elif volatility < 50:
            risk_score += 30
        else:
            risk_score += 40
        
        # Объем (0-20 баллов)
        if volume > 10000000:  # Высокий объем
            risk_score += 0
        elif volume > 1000000:  # Средний объем
            risk_score += 5
        elif volume > 100000:  # Низкий объем
            risk_score += 15
        else:  # Очень низкий объем
            risk_score += 20
        
        # Изменение цены за 24ч (0-20 баллов)
        abs_change = abs(price_change_24h)
        if abs_change < 2:
            risk_score += 0
        elif abs_change < 5:
            risk_score += 5
        elif abs_change < 10:
            risk_score += 10
        elif abs_change < 20:
            risk_score += 15
        else:
            risk_score += 20
        
        # Корреляционный риск (0-20 баллов)
        correlation_risk = self._calculate_correlation_risk(symbol)
        risk_score += correlation_risk
        
        # Определяем уровень риска
        if risk_score < 20:
            return RiskLevel.VERY_LOW
        elif risk_score < 40:
            return RiskLevel.LOW
        elif risk_score < 60:
            return RiskLevel.MEDIUM
        elif risk_score < 80:
            return RiskLevel.HIGH
        else:
            return RiskLevel.VERY_HIGH
    
    def _calculate_correlation_risk(self, symbol: str) -> float:
        """Рассчитывает корреляционный риск"""
        # Упрощенная версия - в реальной системе нужна корреляционная матрица
        if symbol in self.correlation_matrix:
            correlations = self.correlation_matrix[symbol]
            high_correlations = sum(1 for corr in correlations.values() if abs(corr) > 0.7)
            return min(high_correlations * 5, 20)  # До 20 баллов
        return 5  # Базовый риск
    
    def create_risk_profile(self, symbol: str, volatility: float, volume: float,
                           price_change_24h: float) -> RiskProfile:
        """Создает профиль риска для символа"""
        risk_level = self.assess_risk_level(symbol, volatility, volume, price_change_24h)
        
        # Определяем максимальный размер позиции на основе уровня риска
        if risk_level == RiskLevel.VERY_LOW:
            max_position_size = 0.05  # 5%
            stop_loss_percent = 1.0
            take_profit_percent = 2.0
            max_daily_loss = 0.02  # 2%
            max_consecutive_losses = 10
        elif risk_level == RiskLevel.LOW:
            max_position_size = 0.03  # 3%
            stop_loss_percent = 1.5
            take_profit_percent = 3.0
            max_daily_loss = 0.015  # 1.5%
            max_consecutive_losses = 8
        elif risk_level == RiskLevel.MEDIUM:
            max_position_size = 0.02  # 2%
            stop_loss_percent = 2.0
            take_profit_percent = 4.0
            max_daily_loss = 0.01  # 1%
            max_consecutive_losses = 6
        elif risk_level == RiskLevel.HIGH:
            max_position_size = 0.01  # 1%
            stop_loss_percent = 2.5
            take_profit_percent = 5.0
            max_daily_loss = 0.005  # 0.5%
            max_consecutive_losses = 4
        else:  # VERY_HIGH
            max_position_size = 0.005  # 0.5%
            stop_loss_percent = 3.0
            take_profit_percent = 6.0
            max_daily_loss = 0.002  # 0.2%
            max_consecutive_losses = 2
        
        # Рассчитываем корреляционный и ликвидный риск
        correlation_risk = self._calculate_correlation_risk(symbol)
        liquidity_risk = self._calculate_liquidity_risk(volume)
        
        profile = RiskProfile(
            symbol=symbol,
            volatility=volatility,
            risk_level=risk_level,
            max_position_size=max_position_size,
            stop_loss_percent=stop_loss_percent,
            take_profit_percent=take_profit_percent,
            max_daily_loss=max_daily_loss,
            max_consecutive_losses=max_consecutive_losses,
            correlation_risk=correlation_risk,
            liquidity_risk=liquidity_risk,
            last_updated=datetime.now()
        )
        
        self.risk_profiles[symbol] = profile
        return profile
    
    def _calculate_liquidity_risk(self, volume: float) -> float:
        """Рассчитывает риск ликвидности"""
        if volume > 10000000:
            return 0.0
        elif volume > 1000000:
            return 0.2
        elif volume > 100000:
            return 0.5
        elif volume > 10000:
            return 0.8
        else:
            return 1.0
    
    def calculate_position_size(self, symbol: str, entry_price: float, 
                               stop_loss: float, risk_amount: float = None) -> Tuple[float, PositionSize]:
        """Рассчитывает размер позиции на основе риска"""
        try:
            # Получаем профиль риска
            if symbol not in self.risk_profiles:
                logger.warning(f"Профиль риска для {symbol} не найден")
                return 0.0, PositionSize.MICRO
            
            profile = self.risk_profiles[symbol]
            
            # Рассчитываем риск на сделку
            if risk_amount is None:
                risk_amount = self.base_capital * self.max_risk_per_trade
            
            # Рассчитываем размер позиции
            price_risk = abs(entry_price - stop_loss) / entry_price
            if price_risk == 0:
                return 0.0, PositionSize.MICRO
            
            position_value = risk_amount / price_risk
            position_size = position_value / entry_price
            
            # Ограничиваем размер позиции
            max_position_value = self.base_capital * profile.max_position_size
            max_position_size = max_position_value / entry_price
            
            if position_size > max_position_size:
                position_size = max_position_size
                position_value = position_size * entry_price
            
            # Определяем размер позиции
            position_percent = (position_value / self.base_capital) * 100
            
            if position_percent <= 0.1:
                size_category = PositionSize.MICRO
            elif position_percent <= 0.5:
                size_category = PositionSize.SMALL
            elif position_percent <= 1.0:
                size_category = PositionSize.MEDIUM
            elif position_percent <= 2.0:
                size_category = PositionSize.LARGE
            else:
                size_category = PositionSize.MAX
            
            return position_size, size_category
            
        except Exception as e:
            logger.exception(f"Ошибка расчета размера позиции для {symbol}: {e}")
            return 0.0, PositionSize.MICRO
    
    def calculate_stop_loss_take_profit(self, symbol: str, entry_price: float, 
                                       direction: str) -> Tuple[float, float]:
        """Рассчитывает стоп-лосс и тейк-профит"""
        try:
            if symbol not in self.risk_profiles:
                # Базовые значения по умолчанию
                stop_loss_percent = 2.0
                take_profit_percent = 4.0
            else:
                profile = self.risk_profiles[symbol]
                stop_loss_percent = profile.stop_loss_percent
                take_profit_percent = profile.take_profit_percent
            
            if direction.upper() == "LONG":
                stop_loss = entry_price * (1 - stop_loss_percent / 100)
                take_profit = entry_price * (1 + take_profit_percent / 100)
            else:  # SHORT
                stop_loss = entry_price * (1 + stop_loss_percent / 100)
                take_profit = entry_price * (1 - take_profit_percent / 100)
            
            return stop_loss, take_profit
            
        except Exception as e:
            logger.exception(f"Ошибка расчета уровней для {symbol}: {e}")
            return entry_price * 0.98, entry_price * 1.02  # Базовые значения
    
    def assess_position_risk(self, symbol: str, entry_price: float, 
                            position_size: float, stop_loss: float, 
                            take_profit: float) -> PositionRisk:
        """Оценивает риск позиции"""
        try:
            position_value = position_size * entry_price
            
            # Рассчитываем потенциальную прибыль и убыток
            if entry_price > stop_loss:  # LONG позиция
                potential_loss = (entry_price - stop_loss) * position_size
                potential_profit = (take_profit - entry_price) * position_size
            else:  # SHORT позиция
                potential_loss = (stop_loss - entry_price) * position_size
                potential_profit = (entry_price - take_profit) * position_size
            
            # Рассчитываем риск в процентах
            risk_percent = (potential_loss / self.base_capital) * 100
            
            # Рассчитываем соотношение риск/прибыль
            risk_reward_ratio = potential_profit / potential_loss if potential_loss > 0 else 0
            
            # Рассчитываем максимальную просадку
            max_drawdown = (potential_loss / position_value) * 100
            
            return PositionRisk(
                symbol=symbol,
                entry_price=entry_price,
                position_size=position_size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_amount=potential_loss,
                risk_percent=risk_percent,
                potential_profit=potential_profit,
                potential_loss=potential_loss,
                risk_reward_ratio=risk_reward_ratio,
                max_drawdown=max_drawdown,
                position_value=position_value
            )
            
        except Exception as e:
            logger.exception(f"Ошибка оценки риска позиции для {symbol}: {e}")
            return PositionRisk(
                symbol=symbol, entry_price=entry_price, position_size=position_size,
                stop_loss=stop_loss, take_profit=take_profit, risk_amount=0,
                risk_percent=0, potential_profit=0, potential_loss=0,
                risk_reward_ratio=0, max_drawdown=0, position_value=0
            )
    
    def check_risk_limits(self, symbol: str, position_risk: PositionRisk) -> Tuple[bool, List[str]]:
        """Проверяет соблюдение лимитов риска"""
        warnings = []
        
        try:
            # Проверяем максимальный риск на сделку
            if position_risk.risk_percent > self.max_risk_per_trade * 100:
                warnings.append(f"Превышен максимальный риск на сделку: {position_risk.risk_percent:.2f}%")
            
            # Проверяем дневной риск
            if self.daily_pnl < -self.max_daily_risk * self.base_capital:
                warnings.append(f"Превышен дневной лимит риска: {self.daily_pnl:.2f}")
            
            # Проверяем последовательные убытки
            if self.consecutive_losses >= 5:
                warnings.append(f"Слишком много последовательных убытков: {self.consecutive_losses}")
            
            # Проверяем профиль риска символа
            if symbol in self.risk_profiles:
                profile = self.risk_profiles[symbol]
                
                if position_risk.risk_percent > profile.max_position_size * 100:
                    warnings.append(f"Превышен максимальный размер позиции для {symbol}")
                
                if self.consecutive_losses >= profile.max_consecutive_losses:
                    warnings.append(f"Превышен лимит последовательных убытков для {symbol}")
            
            # Проверяем соотношение риск/прибыль
            if position_risk.risk_reward_ratio < 1.5:
                warnings.append(f"Низкое соотношение риск/прибыль: {position_risk.risk_reward_ratio:.2f}")
            
            # Проверяем максимальную просадку
            if position_risk.max_drawdown > 10:
                warnings.append(f"Высокая максимальная просадка: {position_risk.max_drawdown:.2f}%")
            
            return len(warnings) == 0, warnings
            
        except Exception as e:
            logger.exception(f"Ошибка проверки лимитов риска: {e}")
            return False, [f"Ошибка проверки рисков: {e}"]
    
    def update_daily_stats(self, pnl: float, is_win: bool):
        """Обновляет дневную статистику"""
        self.daily_pnl += pnl
        self.daily_trades += 1
        
        if is_win:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        
        # Обновляем просадку
        if pnl < 0:
            self.current_drawdown += abs(pnl)
            self.max_drawdown = max(self.max_drawdown, self.current_drawdown)
        else:
            self.current_drawdown = max(0, self.current_drawdown - pnl)
    
    def reset_daily_stats(self):
        """Сбрасывает дневную статистику"""
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_losses = 0
        self.current_drawdown = 0.0
    
    def get_risk_summary(self) -> Dict[str, Any]:
        """Возвращает сводку по рискам"""
        total_exposure = sum(pos.position_value for pos in self.active_positions.values())
        total_risk = sum(pos.risk_amount for pos in self.active_positions.values())
        
        return {
            "base_capital": self.base_capital,
            "total_exposure": total_exposure,
            "exposure_percent": (total_exposure / self.base_capital) * 100,
            "total_risk": total_risk,
            "risk_percent": (total_risk / self.base_capital) * 100,
            "daily_pnl": self.daily_pnl,
            "daily_trades": self.daily_trades,
            "consecutive_losses": self.consecutive_losses,
            "max_drawdown": self.max_drawdown,
            "current_drawdown": self.current_drawdown,
            "active_positions": len(self.active_positions),
            "risk_profiles": len(self.risk_profiles)
        }
    
    def get_risk_recommendations(self) -> List[str]:
        """Генерирует рекомендации по управлению рисками"""
        recommendations = []
        
        # Проверяем общий риск портфеля
        total_exposure = sum(pos.position_value for pos in self.active_positions.values())
        exposure_percent = (total_exposure / self.base_capital) * 100
        
        if exposure_percent > 50:
            recommendations.append("Высокое воздействие на портфель. Рассмотрите уменьшение позиций.")
        
        # Проверяем дневной P&L
        if self.daily_pnl < -self.max_daily_risk * self.base_capital:
            recommendations.append("Превышен дневной лимит убытков. Остановите торговлю.")
        
        # Проверяем последовательные убытки
        if self.consecutive_losses >= 3:
            recommendations.append(f"Много последовательных убытков ({self.consecutive_losses}). Сделайте паузу.")
        
        # Проверяем просадку
        if self.current_drawdown > self.max_drawdown * 0.8:
            recommendations.append("Высокая текущая просадка. Уменьшите размеры позиций.")
        
        # Проверяем диверсификацию
        if len(self.active_positions) < 3 and total_exposure > 0:
            recommendations.append("Низкая диверсификация. Рассмотрите добавление позиций в другие активы.")
        
        if not recommendations:
            recommendations.append("Риски находятся в пределах нормы.")
        
        return recommendations
