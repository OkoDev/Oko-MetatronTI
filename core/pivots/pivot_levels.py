import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from core.indicators.indicators import calculate_pivot_points as _calculate_pivot_points

logger = logging.getLogger(__name__)


class PivotLevels:
    """
    Расчет уровней поддержки и сопротивления (Traditional Pivot Points)
    
    На основе Pine Script алгоритма из документа.
    Рассчитывает PP (Pivot Point), S1-S5, R1-R5
    """
    
    def __init__(self):
        self.max_levels = 5  # Максимум уровней поддержки/сопротивления
        
    def calculate_traditional_pivots(self, prev_high, prev_low, prev_close):
        """Traditional Pivot Points — делегирует в calculate_pivot_points из core/indicators.py."""
        return _calculate_pivot_points(prev_high, prev_low, prev_close)
    
    async def get_pivot_levels(self, data_collector, symbol, timeframe='1D'):
        """
        Получает уровни пивотов для указанного таймфрейма
        
        Args:
            data_collector: экземпляр RealTimeData
            symbol: символ пары
            timeframe: таймфрейм ('1D', '1W', '1M')
        
        Returns:
            dict с уровнями PP, S1-S5, R1-R5
        """
        try:
            # Получаем данные предыдущего периода
            # Для недельных нужно больше данных
            limit = 10 if timeframe == '1W' else 5
            
            df = await data_collector.get_ohlcv(symbol, timeframe=timeframe, limit=limit)
            
            if df is None or len(df) < 2:
                logger.warning(f"Недостаточно данных для {symbol} {timeframe}")
                return None
            
            # Берем предыдущую свечу (индекс -2)
            prev_high = float(df['high'].iloc[-2])
            prev_low = float(df['low'].iloc[-2])
            prev_close = float(df['close'].iloc[-2])
            
            # Рассчитываем пивоты
            pivots = self.calculate_traditional_pivots(prev_high, prev_low, prev_close)
            pivots['timeframe'] = timeframe
            pivots['timestamp'] = datetime.now()
            
            return pivots
            
        except Exception as e:
            logger.exception(f"Ошибка расчета pivot levels для {symbol} {timeframe}: {e}")
            return None
    
    async def get_multi_timeframe_pivots(self, data_collector, symbol):
        """
        Получает пивоты для нескольких таймфреймов
        ПРИОРИТЕТ: Недельные пивоты (1W)
        
        Returns:
            dict {'1W': {...}, '1D': {...}, 'confluence': [...]}
        """
        try:
            timeframes = ['1W', '1D']  # ПРИОРИТЕТ: недельные!
            results = {}
            
            for tf in timeframes:
                pivots = await self.get_pivot_levels(data_collector, symbol, tf)
                if pivots:
                    results[tf] = pivots
                else:
                    logger.warning(f"Не удалось получить пивоты {tf} для {symbol}")
            
            # Проверяем что хотя бы недельные получены
            if '1W' not in results:
                logger.error(f"Не удалось получить недельные пивоты для {symbol}")
                return {}
            
            # Конфлюэнции: рассчитываются через PivotCalculatorFixed._find_all_confluences()
            # PivotLevels не используется в production — see bot.pivot_calculator (ARCH-25)
            results['confluence'] = []
            
            return results
            
        except Exception as e:
            logger.exception(f"Ошибка get_multi_timeframe_pivots для {symbol}: {e}")
            return {}
    
    def get_nearest_level(self, current_price, pivots, direction='both'):
        """
        Находит ближайший уровень к текущей цене
        
        Args:
            current_price: текущая цена
            pivots: dict с уровнями
            direction: 'support', 'resistance' или 'both'
        
        Returns:
            dict с информацией о ближайшем уровне
        """
        if not pivots:
            return None
        
        nearest = {
            'support': None,
            'resistance': None,
            'distance_support': float('inf'),
            'distance_resistance': float('inf')
        }
        
        # Проверяем уровни поддержки
        if direction in ['support', 'both']:
            for i in range(1, self.max_levels + 1):
                level_key = f'S{i}'
                if level_key in pivots:
                    level_price = pivots[level_key]
                    if level_price < current_price:
                        distance = current_price - level_price
                        if distance < nearest['distance_support']:
                            nearest['support'] = {
                                'level': level_key,
                                'price': level_price,
                                'distance': distance,
                                'distance_percent': (distance / current_price) * 100
                            }
        
        # Проверяем уровни сопротивления
        if direction in ['resistance', 'both']:
            for i in range(1, self.max_levels + 1):
                level_key = f'R{i}'
                if level_key in pivots:
                    level_price = pivots[level_key]
                    if level_price > current_price:
                        distance = level_price - current_price
                        if distance < nearest['distance_resistance']:
                            nearest['resistance'] = {
                                'level': level_key,
                                'price': level_price,
                                'distance': distance,
                                'distance_percent': (distance / current_price) * 100
                            }
        
        return nearest
    
    def is_near_level(self, current_price, pivots, threshold_percent=0.5):
        """
        Проверяет находится ли цена рядом с каким-либо уровнем
        
        Args:
            current_price: текущая цена
            pivots: dict с уровнями
            threshold_percent: порог близости в процентах (default 0.5%)
        
        Returns:
            dict с информацией или None
        """
        if not pivots:
            return None
        
        # Проверяем все уровни
        all_levels = ['PP'] + [f'S{i}' for i in range(1, 6)] + [f'R{i}' for i in range(1, 6)]
        
        for level_key in all_levels:
            if level_key not in pivots:
                continue
            
            level_price = pivots[level_key]
            distance_percent = abs((current_price - level_price) / current_price * 100)
            
            if distance_percent <= threshold_percent:
                level_type = 'pivot' if level_key == 'PP' else ('support' if 'S' in level_key else 'resistance')
                
                return {
                    'near_level': True,
                    'level': level_key,
                    'level_type': level_type,
                    'price': level_price,
                    'distance_percent': distance_percent,
                    'timeframe': pivots.get('timeframe', 'N/A')
                }
        
        return None
    
    def get_take_profit_levels(self, entry_price, pivots, direction='LONG', max_levels=3):
        """
        Определяет уровни для тейк-профитов на основе пивотов
        
        Args:
            entry_price: цена входа
            pivots: dict с уровнями
            direction: 'LONG' или 'SHORT'
            max_levels: максимум уровней для TP
        
        Returns:
            list с уровнями TP
        """
        if not pivots:
            return []
        
        tp_levels = []
        
        if direction == 'LONG':
            # Для LONG берем уровни сопротивления выше входа
            for i in range(1, self.max_levels + 1):
                level_key = f'R{i}'
                if level_key in pivots:
                    level_price = pivots[level_key]
                    if level_price > entry_price:
                        profit_percent = ((level_price - entry_price) / entry_price) * 100
                        tp_levels.append({
                            'level': level_key,
                            'price': level_price,
                            'profit_percent': profit_percent
                        })
                        if len(tp_levels) >= max_levels:
                            break
        
        elif direction == 'SHORT':
            # Для SHORT берем уровни поддержки ниже входа
            for i in range(1, self.max_levels + 1):
                level_key = f'S{i}'
                if level_key in pivots:
                    level_price = pivots[level_key]
                    if level_price < entry_price:
                        profit_percent = ((entry_price - level_price) / entry_price) * 100
                        tp_levels.append({
                            'level': level_key,
                            'price': level_price,
                            'profit_percent': profit_percent
                        })
                        if len(tp_levels) >= max_levels:
                            break
        
        return tp_levels
    
    def check_pivot_bounce(self, current_price, pivots, direction='both', tolerance_percent=0.5):
        """
        Проверяет отбой цены от уровня пивота
        
        Args:
            current_price: текущая цена
            pivots: dict с недельными пивотами
            direction: 'long' (от поддержки) или 'short' (от сопротивления)
            tolerance_percent: расстояние до уровня
        
        Returns:
            dict с информацией об отбое или None
        """
        if not pivots:
            return None
        
        # Для LONG: ищем отбой от поддержки (S1-S3) или PP
        if direction in ['long', 'both']:
            support_levels = ['PP', 'S1', 'S2', 'S3']
            
            for level in support_levels:
                if level not in pivots:
                    continue
                
                level_price = pivots[level]
                
                # Проверяем что цена чуть выше уровня (отбой произошел)
                if current_price > level_price:
                    distance_percent = ((current_price - level_price) / level_price) * 100
                    
                    # Цена должна быть близко к уровню (недавний отбой)
                    if 0 < distance_percent <= tolerance_percent:
                        return {
                            'type': 'BOUNCE_LONG',
                            'level': level,
                            'level_price': level_price,
                            'current_price': current_price,
                            'distance_percent': distance_percent,
                            'description': f'Отбой от {level} вверх',
                            'strength': 'STRONG' if level in ['S1', 'PP'] else 'MEDIUM'
                        }
        
        # Для SHORT: ищем отбой от сопротивления (R1-R3) или PP
        if direction in ['short', 'both']:
            resistance_levels = ['PP', 'R1', 'R2', 'R3']
            
            for level in resistance_levels:
                if level not in pivots:
                    continue
                
                level_price = pivots[level]
                
                # Проверяем что цена чуть ниже уровня (отбой произошел)
                if current_price < level_price:
                    distance_percent = ((level_price - current_price) / level_price) * 100
                    
                    if 0 < distance_percent <= tolerance_percent:
                        return {
                            'type': 'BOUNCE_SHORT',
                            'level': level,
                            'level_price': level_price,
                            'current_price': current_price,
                            'distance_percent': distance_percent,
                            'description': f'Отбой от {level} вниз',
                            'strength': 'STRONG' if level in ['R1', 'PP'] else 'MEDIUM'
                        }
        
        return None
    
    def check_pivot_breakout(self, current_price, prev_price, pivots, direction='both'):
        """
        Проверяет пробой и закрепление над/под пивотом
        
        Args:
            current_price: текущая цена
            prev_price: предыдущая цена
            pivots: dict с пивотами
            direction: 'long' (закрепление выше) или 'short' (закрепление ниже)
        
        Returns:
            dict с информацией о пробое или None
        """
        if not pivots or not prev_price:
            return None
        
        # LONG: пробой и закрепление ВЫШЕ PP
        if direction in ['long', 'both']:
            if 'PP' in pivots:
                pp_price = pivots['PP']
                
                # Проверяем: была ниже, теперь выше (пробой)
                if prev_price <= pp_price < current_price:
                    return {
                        'type': 'BREAKOUT_LONG',
                        'level': 'PP',
                        'level_price': pp_price,
                        'current_price': current_price,
                        'prev_price': prev_price,
                        'distance_percent': ((current_price - pp_price) / pp_price) * 100,
                        'description': 'Пробой и закрепление выше PP',
                        'strength': 'VERY_STRONG'
                    }
        
        # SHORT: пробой и закрепление НИЖЕ PP
        if direction in ['short', 'both']:
            if 'PP' in pivots:
                pp_price = pivots['PP']
                
                # Проверяем: была выше, теперь ниже (пробой)
                if prev_price >= pp_price > current_price:
                    return {
                        'type': 'BREAKOUT_SHORT',
                        'level': 'PP',
                        'level_price': pp_price,
                        'current_price': current_price,
                        'prev_price': prev_price,
                        'distance_percent': ((pp_price - current_price) / pp_price) * 100,
                        'description': 'Пробой и закрепление ниже PP',
                        'strength': 'VERY_STRONG'
                    }
        
        return None
        """
        Определяет уровень стоп-лосса на основе ближайшего пивота
        
        Args:
            entry_price: цена входа
            pivots: dict с уровнями
            direction: 'LONG' или 'SHORT'
        
        Returns:
            dict с уровнем SL или None
        """
        if not pivots:
            return None
        
        if direction == 'LONG':
            # Для LONG стоп за ближайшей поддержкой
            nearest_support = None
            min_distance = float('inf')
            
            for i in range(1, self.max_levels + 1):
                level_key = f'S{i}'
                if level_key in pivots:
                    level_price = pivots[level_key]
                    if level_price < entry_price:
                        distance = entry_price - level_price
                        if distance < min_distance:
                            min_distance = distance
                            nearest_support = {
                                'level': level_key,
                                'price': level_price,
                                'distance_percent': (distance / entry_price) * 100
                            }
            
            return nearest_support
        
        elif direction == 'SHORT':
            # Для SHORT стоп за ближайшим сопротивлением
            nearest_resistance = None
            min_distance = float('inf')
            
            for i in range(1, self.max_levels + 1):
                level_key = f'R{i}'
                if level_key in pivots:
                    level_price = pivots[level_key]
                    if level_price > entry_price:
                        distance = level_price - entry_price
                        if distance < min_distance:
                            min_distance = distance
                            nearest_resistance = {
                                'level': level_key,
                                'price': level_price,
                                'distance_percent': (distance / entry_price) * 100
                            }
            
            return nearest_resistance
        
        return None


def pivot_message(symbol: str, pivots: dict, current_price: float) -> str:
    """Форматирует сообщение об уровнях пивотов"""
    from core.ui.message_builder import tv_link
    
    if not pivots:
        return "Нет данных о пивотах"
    
    timeframe = pivots.get('timeframe', 'N/A')
    
    # Определяем интервал для TV
    tf_map = {'1D': 1440, '1W': 10080, '1M': 43200}
    interval = tf_map.get(timeframe, 1440)
    
    parts = [
        "📊 <b>УРОВНИ ПОДДЕРЖКИ/СОПРОТИВЛЕНИЯ</b>",
        f"Пара: {tv_link(symbol, interval=interval)}",
        f"Таймфрейм: {timeframe}",
        f"Текущая цена: {current_price:.6f}",
        "",
        "<b>🔴 Сопротивления:</b>"
    ]
    
    # Показываем сопротивления (от R5 до R1)
    for i in range(5, 0, -1):
        key = f'R{i}'
        if key in pivots:
            level_price = pivots[key]
            if level_price > current_price:
                distance = ((level_price - current_price) / current_price) * 100
                parts.append(f"  {key}: {level_price:.6f} (+{distance:.2f}%)")
    
    # Pivot Point
    pp = pivots.get('PP', 0)
    if pp:
        distance = ((pp - current_price) / current_price) * 100
        parts.append(f"\n<b>⚪ PP: {pp:.6f} ({distance:+.2f}%)</b>\n")
    
    # Показываем поддержки (от S1 до S5)
    parts.append("<b>🟢 Поддержки:</b>")
    for i in range(1, 6):
        key = f'S{i}'
        if key in pivots:
            level_price = pivots[key]
            if level_price < current_price:
                distance = ((current_price - level_price) / current_price) * 100
                parts.append(f"  {key}: {level_price:.6f} (-{distance:.2f}%)")
    
    # Проверяем близость к уровням
    pivot_calc = PivotLevels()
    near_level = pivot_calc.is_near_level(current_price, pivots, threshold_percent=0.5)
    
    if near_level:
        parts.append("")
        parts.append(f"⚠️ <b>ЦЕНА РЯДОМ С УРОВНЕМ!</b>")
        parts.append(f"Уровень: {near_level['level']} ({near_level['level_type']})")
        parts.append(f"Цена уровня: {near_level['price']:.6f}")
        parts.append(f"Расстояние: {near_level['distance_percent']:.3f}%")
    
    parts.append("")
    parts.append(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return "\n".join(parts)