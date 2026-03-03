import logging
import pandas as pd
import numpy as np
from core.indicators import calculate_wt

logger = logging.getLogger(__name__)


class DivergenceDetector:
    """
    Детектор дивергенций по алгоритму из Pine Script (OKO RSI Divergence)
    
    Использует метод виртуальных линий для проверки "чистоты" дивергенции.
    Переведено с TradingView Pine Script v6.
    
    Типы дивергенций:
    1. Regular Bullish - Индикатор HL (higher low), Цена LL (lower low)
    2. Regular Bearish - Индикатор LH (lower high), Цена HH (higher high)
    3. Hidden Bullish - Индикатор LL, Цена HL
    4. Hidden Bearish - Индикатор HH, Цена LH
    """
    
    def __init__(self, 
                 pivot_period=5,
                 max_pivot_points=10,
                 lookback=50,
                 max_bars=100,
                 min_bars_between=5):
        """
        Args:
            pivot_period: период для определения пивотов (default 5)
            max_pivot_points: максимум пивотов для проверки (default 10)
            max_bars: максимальное расстояние между пивотами (default 100)
            min_bars_between: минимальное расстояние (default 5)
        """
        self.pivot_period = pivot_period
        self.max_pivot_points = max_pivot_points
        self.lookback = lookback
        self.max_bars = max_bars
        self.min_bars_between = min_bars_between
    
    def find_pivot_highs(self, series, period):
        """
        Находит pivot highs (аналог ta.pivothigh в Pine Script)
        
        Pivot high = максимум, который выше всех значений 
        на расстоянии 'period' слева и справа
        """
        pivots = []
        
        for i in range(period, len(series) - period):
            current = series.iloc[i]
            
            # Проверяем что текущее значение выше всех в окне
            is_pivot = True
            
            # Проверка слева
            for j in range(i - period, i):
                if series.iloc[j] >= current:
                    is_pivot = False
                    break
            
            # Проверка справа
            if is_pivot:
                for j in range(i + 1, i + period + 1):
                    if series.iloc[j] >= current:
                        is_pivot = False
                        break
            
            if is_pivot:
                pivots.append({
                    'index': i,
                    'value': current,
                    'price': series.iloc[i]
                })
        
        return pivots
    
    def find_pivot_lows(self, series, period):
        """
        Находит pivot lows (аналог ta.pivotlow в Pine Script)
        """
        pivots = []
        
        for i in range(period, len(series) - period):
            current = series.iloc[i]
            
            is_pivot = True
            
            # Проверка слева
            for j in range(i - period, i):
                if series.iloc[j] <= current:
                    is_pivot = False
                    break
            
            # Проверка справа
            if is_pivot:
                for j in range(i + 1, i + period + 1):
                    if series.iloc[j] <= current:
                        is_pivot = False
                        break
            
            if is_pivot:
                pivots.append({
                    'index': i,
                    'value': current,
                    'price': series.iloc[i]
                })
        
        return pivots
    
    def check_virtual_line(self, indicator, price, start_idx, pivot_idx, 
                          check_above_indicator, check_above_price):
        """
        Проверяет что между двумя точками нет пересечений виртуальных линий
        (метод из Pine Script для проверки "чистоты" дивергенции)
        
        Args:
            indicator: серия индикатора (WT1)
            price: серия цены (close)
            start_idx: индекс текущей точки
            pivot_idx: индекс точки пивота
            check_above_indicator: проверять что индикатор выше линии
            check_above_price: проверять что цена выше линии
        
        Returns:
            True если дивергенция "чистая" (нет пересечений)
        """
        length = start_idx - pivot_idx
        
        if length <= self.min_bars_between:
            return False
        
        # Строим виртуальные линии (линейная интерполяция)
        # Линия индикатора
        ind_start = indicator.iloc[start_idx]
        ind_pivot = indicator.iloc[pivot_idx]
        ind_slope = (ind_start - ind_pivot) / length
        
        # Линия цены
        price_start = price.iloc[start_idx]
        price_pivot = price.iloc[pivot_idx]
        price_slope = (price_start - price_pivot) / length
        
        # Проверяем все точки между пивотами
        for i in range(1, length):
            idx = start_idx - i
            
            # Значения на виртуальных линиях
            virtual_ind = ind_start - (ind_slope * i)
            virtual_price = price_start - (price_slope * i)
            
            # Проверка индикатора
            if check_above_indicator:
                if indicator.iloc[idx] < virtual_ind:
                    return False
            else:
                if indicator.iloc[idx] > virtual_ind:
                    return False
            
            # Проверка цены
            if check_above_price:
                if price.iloc[idx] < virtual_price:
                    return False
            else:
                if price.iloc[idx] > virtual_price:
                    return False
        
        return True
    
    def detect_regular_bullish(self, df, indicator_col='wt1'):
        """
        Regular Bullish Divergence (по алгоритму Pine Script)
        
        Условия:
        - Индикатор делает HL (higher low)
        - Цена делает LL (lower low)
        - Виртуальные линии не пересекаются
        - Оба минимума в зоне OS (< -60)
        """
        # Находим pivot lows для индикатора и цены
        ind_pivots = self.find_pivot_lows(df[indicator_col], self.pivot_period)
        price_pivots = self.find_pivot_lows(df['low'], self.pivot_period)
        
        if len(ind_pivots) < 2 or len(price_pivots) < 2:
            return None
        
        # Берем последний пивот индикатора как стартовую точку
        current_idx = len(df) - 1
        
        # Ищем дивергенцию
        for i in range(min(len(ind_pivots), self.max_pivot_points)):
            pivot = ind_pivots[-(i+1)]  # Идем от последнего к первому
            pivot_idx = pivot['index']
            
            # Проверяем расстояние
            distance = current_idx - pivot_idx
            if distance > self.max_bars or distance < self.min_bars_between:
                continue
            
            # Условия Regular Bullish:
            # 1. Индикатор: текущий > пивот (HL - higher low)
            # 2. Цена: текущая < пивот (LL - lower low)
            ind_current = df[indicator_col].iloc[current_idx]
            ind_pivot = pivot['value']
            
            price_current = df['low'].iloc[current_idx]
            price_pivot = df['low'].iloc[pivot_idx]
            
            # КРИТИЧНО: Проверяем зоны OS
            if ind_current >= -60 or ind_pivot >= -60:
                continue  # Хотя бы один не в OS - пропускаем
            
            # Проверяем условия дивергенции
            if ind_current > ind_pivot and price_current < price_pivot:
                # Проверяем виртуальные линии
                is_clean = self.check_virtual_line(
                    df[indicator_col], df['close'],
                    current_idx, pivot_idx,
                    check_above_indicator=True,  # индикатор выше линии
                    check_above_price=True       # цена выше линии
                )
                
                if is_clean:
                    return {
                        'current_idx': current_idx,
                        'pivot_idx': pivot_idx,
                        'ind_current': ind_current,
                        'ind_pivot': ind_pivot,
                        'price_current': price_current,
                        'price_pivot': price_pivot,
                        'distance': distance,
                        'ind_change': ind_current - ind_pivot,
                        'price_change_pct': ((price_current - price_pivot) / price_pivot) * 100
                    }
        
        return None
    
    def detect_regular_bearish(self, df, indicator_col='wt1'):
        """
        Regular Bearish Divergence
        
        Условия:
        - Индикатор делает LH (lower high)
        - Цена делает HH (higher high)
        - Виртуальные линии не пересекаются
        - Оба максимума в зоне OB (> 60)
        """
        ind_pivots = self.find_pivot_highs(df[indicator_col], self.pivot_period)
        price_pivots = self.find_pivot_highs(df['high'], self.pivot_period)
        
        if len(ind_pivots) < 2 or len(price_pivots) < 2:
            return None
        
        current_idx = len(df) - 1
        
        for i in range(min(len(ind_pivots), self.max_pivot_points)):
            pivot = ind_pivots[-(i+1)]
            pivot_idx = pivot['index']
            
            distance = current_idx - pivot_idx
            if distance > self.max_bars or distance < self.min_bars_between:
                continue
            
            ind_current = df[indicator_col].iloc[current_idx]
            ind_pivot = pivot['value']
            
            price_current = df['high'].iloc[current_idx]
            price_pivot = df['high'].iloc[pivot_idx]
            
            # КРИТИЧНО: Проверяем зоны OB
            if ind_current <= 60 or ind_pivot <= 60:
                continue  # Хотя бы один не в OB - пропускаем
            
            # Условия Regular Bearish:
            # 1. Индикатор: текущий < пивот (LH)
            # 2. Цена: текущая > пивот (HH)
            if ind_current < ind_pivot and price_current > price_pivot:
                is_clean = self.check_virtual_line(
                    df[indicator_col], df['close'],
                    current_idx, pivot_idx,
                    check_above_indicator=False,  # индикатор ниже линии
                    check_above_price=False       # цена ниже линии
                )
                
                if is_clean:
                    return {
                        'current_idx': current_idx,
                        'pivot_idx': pivot_idx,
                        'ind_current': ind_current,
                        'ind_pivot': ind_pivot,
                        'price_current': price_current,
                        'price_pivot': price_pivot,
                        'distance': distance,
                        'ind_change': ind_pivot - ind_current,
                        'price_change_pct': ((price_current - price_pivot) / price_pivot) * 100
                    }
        
        return None
    
    def detect_hidden_bullish(self, df, indicator_col='wt1'):
        """
        Hidden Bullish (продолжение восходящего тренда)
        - Индикатор: LL
        - Цена: HL
        """
        ind_pivots = self.find_pivot_lows(df[indicator_col], self.pivot_period)
        price_pivots = self.find_pivot_lows(df['low'], self.pivot_period)
        
        if len(ind_pivots) < 2 or len(price_pivots) < 2:
            return None
        
        current_idx = len(df) - 1
        
        for i in range(min(len(ind_pivots), self.max_pivot_points)):
            pivot = ind_pivots[-(i+1)]
            pivot_idx = pivot['index']
            
            distance = current_idx - pivot_idx
            if distance > self.max_bars or distance < self.min_bars_between:
                continue
            
            ind_current = df[indicator_col].iloc[current_idx]
            ind_pivot = pivot['value']
            price_current = df['low'].iloc[current_idx]
            price_pivot = df['low'].iloc[pivot_idx]
            
            # Hidden Bullish: индикатор LL, цена HL
            if ind_current < ind_pivot and price_current > price_pivot:
                is_clean = self.check_virtual_line(
                    df[indicator_col], df['close'],
                    current_idx, pivot_idx,
                    check_above_indicator=True,
                    check_above_price=True
                )
                
                if is_clean:
                    return {
                        'current_idx': current_idx,
                        'pivot_idx': pivot_idx,
                        'ind_current': ind_current,
                        'ind_pivot': ind_pivot,
                        'price_current': price_current,
                        'price_pivot': price_pivot,
                        'distance': distance,
                        'ind_change': ind_current - ind_pivot,
                        'price_change_pct': ((price_current - price_pivot) / price_pivot) * 100
                    }
        
        return None
    
    def detect_hidden_bearish(self, df, indicator_col='wt1'):
        """
        Hidden Bearish (продолжение нисходящего тренда)
        - Индикатор: HH
        - Цена: LH
        """
        ind_pivots = self.find_pivot_highs(df[indicator_col], self.pivot_period)
        price_pivots = self.find_pivot_highs(df['high'], self.pivot_period)
        
        if len(ind_pivots) < 2 or len(price_pivots) < 2:
            return None
        
        current_idx = len(df) - 1
        
        for i in range(min(len(ind_pivots), self.max_pivot_points)):
            pivot = ind_pivots[-(i+1)]
            pivot_idx = pivot['index']
            
            distance = current_idx - pivot_idx
            if distance > self.max_bars or distance < self.min_bars_between:
                continue
            
            ind_current = df[indicator_col].iloc[current_idx]
            ind_pivot = pivot['value']
            price_current = df['high'].iloc[current_idx]
            price_pivot = df['high'].iloc[pivot_idx]
            
            # Hidden Bearish: индикатор HH, цена LH
            if ind_current > ind_pivot and price_current < price_pivot:
                is_clean = self.check_virtual_line(
                    df[indicator_col], df['close'],
                    current_idx, pivot_idx,
                    check_above_indicator=False,
                    check_above_price=False
                )
                
                if is_clean:
                    return {
                        'current_idx': current_idx,
                        'pivot_idx': pivot_idx,
                        'ind_current': ind_current,
                        'ind_pivot': ind_pivot,
                        'price_current': price_current,
                        'price_pivot': price_pivot,
                        'distance': distance,
                        'ind_change': ind_current - ind_pivot,
                        'price_change_pct': ((price_current - price_pivot) / price_pivot) * 100
                    }
        
        return None
    
    async def detect_divergence(self, symbol, data_collector, timeframe="1h"):
        """
        Основная функция поиска дивергенций
        
        Returns:
            (bool, dict) - найдена ли дивергенция и её детали
        """
        try:
            # Получаем данные с запасом для расчета пивотов
            limit = self.max_bars + self.pivot_period * 2 + 50
            df = await data_collector.get_ohlcv(symbol, timeframe=timeframe, limit=limit)
            
            if df is None or len(df) < limit:
                return False, None
            
            # Рассчитываем WT
            df = calculate_wt(df, n1=10, n2=21)
            
            # Проверяем дивергенции в порядке приоритета
            
            # 1. Regular Bullish (самая сильная для LONG)
            reg_bull = self.detect_regular_bullish(df, indicator_col='wt1')
            if reg_bull:
                strength = self._calculate_strength(reg_bull, 'REGULAR_BULLISH')
                return True, {
                    "type": "REGULAR_BULLISH",
                    "direction": "LONG",
                    "strength": strength,
                    "timeframe": timeframe,
                    "details": reg_bull,
                    "description": "Обычная бычья дивергенция"
                }
            
            # 2. Regular Bearish (самая сильная для SHORT)
            reg_bear = self.detect_regular_bearish(df, indicator_col='wt1')
            if reg_bear:
                strength = self._calculate_strength(reg_bear, 'REGULAR_BEARISH')
                return True, {
                    "type": "REGULAR_BEARISH",
                    "direction": "SHORT",
                    "strength": strength,
                    "timeframe": timeframe,
                    "details": reg_bear,
                    "description": "Обычная медвежья дивергенция"
                }
            
            # 3. Hidden Bullish
            hid_bull = self.detect_hidden_bullish(df, indicator_col='wt1')
            if hid_bull:
                strength = self._calculate_strength(hid_bull, 'HIDDEN_BULLISH')
                return True, {
                    "type": "HIDDEN_BULLISH",
                    "direction": "LONG",
                    "strength": strength,
                    "timeframe": timeframe,
                    "details": hid_bull,
                    "description": "Скрытая бычья дивергенция (продолжение тренда)"
                }
            
            # 4. Hidden Bearish
            hid_bear = self.detect_hidden_bearish(df, indicator_col='wt1')
            if hid_bear:
                strength = self._calculate_strength(hid_bear, 'HIDDEN_BEARISH')
                return True, {
                    "type": "HIDDEN_BEARISH",
                    "direction": "SHORT",
                    "strength": strength,
                    "timeframe": timeframe,
                    "details": hid_bear,
                    "description": "Скрытая медвежья дивергенция (продолжение тренда)"
                }
            
            return False, None
            
        except Exception:
            logger.exception(f"Ошибка detect_divergence для {symbol}")
            return False, None
    
    def _calculate_strength(self, div_details, div_type):
        """
        ИСПРАВЛЕННЫЙ расчет силы дивергенции (0-100)
        
        Учитывает:
        1. Расстояние между точками (больше = лучше)
        2. Величину расхождения индикатора
        3. Величину изменения цены
        4. КРИТИЧНО: Нахождение в правильных зонах!
        """
        if not div_details:
            return 0
        
        score = 0
        
        # 1. Расстояние между точками (макс 25 баллов)
        distance = div_details.get('distance', 0)
        if distance >= 30:
            score += 25
        elif distance >= 20:
            score += 20
        elif distance >= 15:
            score += 15
        elif distance >= 10:
            score += 10
        elif distance >= 5:
            score += 5
        
        # 2. Величина изменения индикатора (макс 25 баллов)
        ind_change = abs(div_details.get('ind_change', 0))
        if ind_change >= 30:
            score += 25
        elif ind_change >= 20:
            score += 20
        elif ind_change >= 15:
            score += 15
        elif ind_change >= 10:
            score += 10
        elif ind_change >= 5:
            score += 5
        
        # 3. Величина изменения цены (макс 20 баллов)
        price_change = abs(div_details.get('price_change_pct', 0))
        if price_change >= 10:
            score += 20
        elif price_change >= 5:
            score += 15
        elif price_change >= 3:
            score += 10
        elif price_change >= 2:
            score += 5
        
        # 4. КРИТИЧНО: Проверка зон (макс 30 баллов!)
        ind_current = div_details.get('ind_current', 0)
        ind_pivot = div_details.get('ind_pivot', 0)
        
        zone_score = 0
        
        if 'BULLISH' in div_type:
            # Для бычьих: оба минимума должны быть в OS (< -60)
            if ind_current < -60 and ind_pivot < -60:
                # Оба глубоко в OS
                if ind_current < -70 or ind_pivot < -70:
                    zone_score = 30  # Экстремальная перепроданность
                else:
                    zone_score = 25  # Оба в OS
            elif ind_current < -60 or ind_pivot < -60:
                zone_score = 10  # Хотя бы один в OS
            else:
                zone_score = 0   # Оба вне OS - СЛАБЫЙ сигнал!
        
        elif 'BEARISH' in div_type:
            # Для медвежьих: оба максимума должны быть в OB (> 60)
            if ind_current > 60 and ind_pivot > 60:
                # Оба глубоко в OB
                if ind_current > 70 or ind_pivot > 70:
                    zone_score = 30  # Экстремальная перекупленность
                else:
                    zone_score = 25  # Оба в OB
            elif ind_current > 60 or ind_pivot > 60:
                zone_score = 10  # Хотя бы один в OB
            else:
                zone_score = 0   # Оба вне OB - СЛАБЫЙ сигнал!
        
        score += zone_score
        
        return min(score, 100)


# Функция для форматирования сообщения (обновленная)
def divergence_message(symbol: str, div_info: dict) -> str:
    """Форматирует сообщение о дивергенции"""
    from core.message_builder import tv_link
    from datetime import datetime
    
    div_type = div_info.get("type", "")
    direction = div_info.get("direction", "")
    strength = div_info.get("strength", 0)
    details = div_info.get("details", {})
    description = div_info.get("description", "")
    timeframe = div_info.get("timeframe", "15m")
    
    # Определяем интервал для TradingView
    tf_to_interval = {"3m": 3, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
    interval = tf_to_interval.get(timeframe, 15)
    
    # Эмодзи по направлению
    emoji = "🟢" if direction == "LONG" else "🔴"
    
    # Эмодзи по силе (ИСПРАВЛЕНО)
    if strength >= 75:
        strength_emoji = "🔥🔥🔥"
        strength_text = "Очень сильная"
    elif strength >= 60:
        strength_emoji = "🔥🔥"
        strength_text = "Сильная"
    elif strength >= 40:
        strength_emoji = "🔥"
        strength_text = "Средняя"
    else:
        strength_emoji = "⚠️"
        strength_text = "Слабая"
    
    # Тип дивергенции
    if "REGULAR" in div_type:
        type_emoji = "🔄"
        type_text = "Обычная (разворот)"
    else:
        type_emoji = "➡️"
        type_text = "Скрытая (продолжение)"
    
    parts = [
        f"{emoji} <b>ДИВЕРГЕНЦИЯ</b> {emoji}",
        f"Пара: {tv_link(symbol, interval=interval)}",
        f"{type_emoji} Тип: <b>{description}</b>",
        f"Направление: <b>{direction}</b>",
        f"Таймфрейм: {timeframe}",
        "",
        f"{strength_emoji} <b>Сила: {strength}/100</b> ({strength_text})",
        "",
        "<b>📊 Анализ точек:</b>"
    ]
    
    if details:
        ind_curr = details.get('ind_current', 0)
        ind_pivot = details.get('ind_pivot', 0)
        price_curr = details.get('price_current', 0)
        price_pivot = details.get('price_pivot', 0)
        distance = details.get('distance', 0)
        price_change = details.get('price_change_pct', 0)
        
        parts.append(f"Точка 1 (пивот {distance} баров назад):")
        parts.append(f"  • Цена: {price_pivot:.6f}")
        parts.append(f"  • WT: {ind_pivot:.1f}")
        parts.append("")
        parts.append(f"Точка 2 (текущая):")
        parts.append(f"  • Цена: {price_curr:.6f}")
        parts.append(f"  • WT: {ind_curr:.1f}")
        parts.append("")
        parts.append(f"📏 Расстояние: {distance} баров")
        parts.append(f"📈 Изменение цены: {price_change:+.2f}%")
        parts.append(f"📊 Изменение WT: {details.get('ind_change', 0):+.1f}")
    
    parts.append("")
    parts.append("<b>💡 Интерпретация:</b>")
    
    if "REGULAR_BULLISH" in div_type:
        parts.append("  • WT растет (HL), но цена падает (LL)")
        parts.append("  • Давление продавцов ослабевает")
        parts.append("  • Вероятен разворот вверх")
        parts.append("  • ✅ Рассмотреть LONG позицию")
    elif "REGULAR_BEARISH" in div_type:
        parts.append("  • WT падает (LH), но цена растет (HH)")
        parts.append("  • Давление покупателей ослабевает")
        parts.append("  • Вероятен разворот вниз")
        parts.append("  • ✅ Рассмотреть SHORT позицию")
    elif "HIDDEN_BULLISH" in div_type:
        parts.append("  • Подтверждение восходящего тренда")
        parts.append("  • Цена делает коррекцию (HL), но тренд силен")
        parts.append("  • Хорошая точка для входа в LONG")
        parts.append("  • ✅ Добавление к LONG позиции")
    elif "HIDDEN_BEARISH" in div_type:
        parts.append("  • Подтверждение нисходящего тренда")
        parts.append("  • Цена делает отскок (LH), но тренд силен")
        parts.append("  • Хорошая точка для входа в SHORT")
        parts.append("  • ✅ Добавление к SHORT позиции")
    
    parts.append("")
    parts.append("<b>⚠️ Рекомендации:</b>")
    
    if strength >= 75:
        parts.append("  • 🔥🔥🔥 ОТЛИЧНЫЙ СИГНАЛ!")
        parts.append("  • Оба пика/впадины в правильных зонах")
        parts.append("  • Можно входить стандартным объемом")
        parts.append("  • Дождитесь подтверждения на младшем ТФ")
    elif strength >= 60:
        parts.append("  • 🔥🔥 Сильный сигнал")
        parts.append("  • Хорошие условия для входа")
        parts.append("  • Используйте стандартный объем")
        parts.append("  • Рекомендуется подтверждение на 15m/5m")
    elif strength >= 40:
        parts.append("  • 🔥 Средний сигнал - требуется осторожность")
        parts.append("  • Уменьшите объем позиции")
        parts.append("  • ОБЯЗАТЕЛЬНО дождитесь подтверждения")
        parts.append("  • Проверьте старшие ТФ")
    else:
        parts.append("  • ⚠️ Слабый сигнал - высокий риск!")
        parts.append("  • Один или оба пика/впадины вне зон OS/OB")
        parts.append("  • НЕ рекомендуется вход")
        parts.append("  • Дождитесь более сильного сигнала")
    
    # Добавляем проверку зон
    if details:
        ind_curr = details.get('ind_current', 0)
        ind_pivot = details.get('ind_pivot', 0)
        
        parts.append("")
        parts.append("<b>🎯 Проверка зон:</b>")
        
        if 'BULLISH' in div_type:
            curr_in_os = ind_curr < -60
            pivot_in_os = ind_pivot < -60
            
            parts.append(f"  • Текущий WT: {ind_curr:.1f} {'✅ в OS' if curr_in_os else '❌ вне OS'}")
            parts.append(f"  • Пивот WT: {ind_pivot:.1f} {'✅ в OS' if pivot_in_os else '❌ вне OS'}")
            
            if curr_in_os and pivot_in_os:
                parts.append("  • 🎉 ОБА в зоне OS - идеально!")
            elif curr_in_os or pivot_in_os:
                parts.append("  • ⚠️ Только один в OS - сигнал слабее")
            else:
                parts.append("  • ❌ Оба вне OS - сигнал ненадежный!")
        
        elif 'BEARISH' in div_type:
            curr_in_ob = ind_curr > 60
            pivot_in_ob = ind_pivot > 60
            
            parts.append(f"  • Текущий WT: {ind_curr:.1f} {'✅ в OB' if curr_in_ob else '❌ вне OB'}")
            parts.append(f"  • Пивот WT: {ind_pivot:.1f} {'✅ в OB' if pivot_in_ob else '❌ вне OB'}")
            
            if curr_in_ob and pivot_in_ob:
                parts.append("  • 🎉 ОБА в зоне OB - идеально!")
            elif curr_in_ob or pivot_in_ob:
                parts.append("  • ⚠️ Только один в OB - сигнал слабее")
            else:
                parts.append("  • ❌ Оба вне OB - сигнал ненадежный!")
    
    parts.append("")
    parts.append(f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return "\n".join(parts)