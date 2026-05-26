import logging
import pandas as pd
import numpy as np
from core.indicators.indicators import calculate_wt, find_swing_highs, find_swing_lows

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
        """Swing Highs — делегирует в find_swing_highs из core/indicators.py (единый источник)."""
        pivots = find_swing_highs(series, period)
        # Добавляем поле 'price' для обратной совместимости
        for p in pivots:
            p['price'] = p['value']
        return pivots

    def find_pivot_lows(self, series, period):
        """Swing Lows — делегирует в find_swing_lows из core/indicators.py (единый источник)."""
        pivots = find_swing_lows(series, period)
        for p in pivots:
            p['price'] = p['value']
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
                        'ind_change': ind_current - ind_pivot,  # отрицательное: WT упал (LH)
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
            # Zone фильтр: hidden bull при wt > +20 — тренд уже развернулся, поздно
            if ind_current > 20:
                continue
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
            # Zone фильтр: hidden bear при wt < -20 — тренд уже развернулся, поздно
            if ind_current < -20:
                continue
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

            # D-063: ARCH-18 reuse pre-computed WT если есть
            if "wt1" not in df.columns or "wt2" not in df.columns:
                df = calculate_wt(df, n1=10, n2=21)
            
            # Проверяем дивергенции в порядке приоритета
            ind_pivots_low  = self.find_pivot_lows(df['wt1'], self.pivot_period)
            ind_pivots_high = self.find_pivot_highs(df['wt1'], self.pivot_period)

            _COUNT_LABELS = {1: "Обычная", 2: "Двойная", 3: "Тройная"}

            # 1. Regular Bullish (самая сильная для LONG)
            reg_bull = self.detect_regular_bullish(df, indicator_col='wt1')
            if reg_bull:
                div_count = self._count_div_chain_bullish(
                    df, 'wt1', reg_bull['pivot_idx'], reg_bull['ind_pivot'],
                    reg_bull['price_pivot'], ind_pivots_low
                )
                strength = self._calculate_strength(reg_bull, 'REGULAR_BULLISH', div_count)
                label = _COUNT_LABELS.get(div_count, "Тройная+")
                return True, {
                    "type": "REGULAR_BULLISH",
                    "direction": "LONG",
                    "strength": strength,
                    "timeframe": timeframe,
                    "div_count": div_count,
                    "details": reg_bull,
                    "description": f"{label} бычья дивергенция"
                }

            # 2. Regular Bearish (самая сильная для SHORT)
            reg_bear = self.detect_regular_bearish(df, indicator_col='wt1')
            if reg_bear:
                div_count = self._count_div_chain_bearish(
                    df, 'wt1', reg_bear['pivot_idx'], reg_bear['ind_pivot'],
                    reg_bear['price_pivot'], ind_pivots_high
                )
                strength = self._calculate_strength(reg_bear, 'REGULAR_BEARISH', div_count)
                label = _COUNT_LABELS.get(div_count, "Тройная+")
                return True, {
                    "type": "REGULAR_BEARISH",
                    "direction": "SHORT",
                    "strength": strength,
                    "timeframe": timeframe,
                    "div_count": div_count,
                    "details": reg_bear,
                    "description": f"{label} медвежья дивергенция"
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
                    "div_count": 1,
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
                    "div_count": 1,
                    "details": hid_bear,
                    "description": "Скрытая медвежья дивергенция (продолжение тренда)"
                }
            
            return False, None

        except Exception:
            logger.exception(f"Ошибка detect_divergence для {symbol}")
            return False, None

    # Бонус к силе сигнала за уровень иерархии TF (чем выше — тем ценнее)
    _CASCADE_BONUS = {
        ("1W", "1D"): 25,
        ("1D", "4h"): 20,
        ("4h", "1h"): 15,
        ("1h", "15m"): 10,
    }

    async def detect_cascade_divergence(self, symbol, data_collector, senior_tf: str, junior_tf: str):
        """
        Универсальная MTF-конфлюэнция дивергенций:
          - Скрытая на senior_tf  → тренд продолжается, коррекция заканчивается
          - Регулярная на junior_tf в том же направлении → точка входа

        Args:
            senior_tf: старший таймфрейм (напр. "4h", "1h")
            junior_tf: младший таймфрейм (напр. "1h", "15m")

        Returns:
            (bool, dict) — найдена ли конфлюэнция и её детали
        """
        try:
            limit = self.max_bars + self.pivot_period * 2 + 50

            # Шаг 1: скрытая дивергенция на senior_tf
            df_senior = await data_collector.get_ohlcv(symbol, timeframe=senior_tf, limit=limit)
            if df_senior is None or len(df_senior) < limit:
                return False, None

            # D-063: reuse pre-computed WT если есть
            if "wt1" not in df_senior.columns or "wt2" not in df_senior.columns:
                df_senior = calculate_wt(df_senior, n1=10, n2=21)

            hidden_dir = None
            hidden_strength = 0

            hid_bull = self.detect_hidden_bullish(df_senior, indicator_col='wt1')
            if hid_bull:
                hidden_dir = "LONG"
                hidden_strength = self._calculate_strength(hid_bull, 'HIDDEN_BULLISH')
            else:
                hid_bear = self.detect_hidden_bearish(df_senior, indicator_col='wt1')
                if hid_bear:
                    hidden_dir = "SHORT"
                    hidden_strength = self._calculate_strength(hid_bear, 'HIDDEN_BEARISH')

            if not hidden_dir:
                return False, None

            # Шаг 2: регулярная дивергенция на junior_tf в том же направлении
            df_junior = await data_collector.get_ohlcv(symbol, timeframe=junior_tf, limit=limit)
            if df_junior is None or len(df_junior) < limit:
                return False, None

            # D-063: reuse pre-computed WT если есть
            if "wt1" not in df_junior.columns or "wt2" not in df_junior.columns:
                df_junior = calculate_wt(df_junior, n1=10, n2=21)

            bull_str = "бычья" if hidden_dir == "LONG" else "медвежья"
            if hidden_dir == "LONG":
                regular_info = self.detect_regular_bullish(df_junior, indicator_col='wt1')
                regular_type = 'REGULAR_BULLISH'
            else:
                regular_info = self.detect_regular_bearish(df_junior, indicator_col='wt1')
                regular_type = 'REGULAR_BEARISH'

            if not regular_info:
                return False, None

            regular_strength = self._calculate_strength(regular_info, regular_type)
            bonus = self._CASCADE_BONUS.get((senior_tf, junior_tf), 10)
            combined = min(100, int(hidden_strength * 0.4 + regular_strength * 0.6) + bonus)

            tf_label = f"{senior_tf}+{junior_tf}"
            return True, {
                "type": f"MTF_{'BULLISH' if hidden_dir == 'LONG' else 'BEARISH'}",
                "direction": hidden_dir,
                "strength": combined,
                "timeframe": tf_label,
                "senior_tf": senior_tf,
                "junior_tf": junior_tf,
                "hidden_strength": hidden_strength,
                "regular_strength": regular_strength,
                "details": regular_info,
                "description": f"MTF-дивергенция: скрытая {bull_str} ({senior_tf}) + регулярная {bull_str} ({junior_tf})",
            }

        except Exception:
            logger.exception("Ошибка detect_cascade_divergence %s→%s для %s", senior_tf, junior_tf, symbol)
            return False, None

    async def detect_mtf_divergence(self, symbol, data_collector):
        """Обёртка для уровня 1h→15m (обратная совместимость)."""
        return await self.detect_cascade_divergence(symbol, data_collector, "1h", "15m")

    def _count_div_chain_bullish(self, df, indicator_col, first_pivot_idx, first_pivot_wt, first_pivot_price, ind_pivots):
        """
        Считает глубину бычьей дивергентной цепочки, начиная с первого найденного пивота.

        Для каждого следующего (более старого) пивота проверяет:
          - WT пивота < WT текущего пивота (каждый минимум WT ниже = продолжение HL-цепочки)
          - Цена пивота < цена текущего пивота (каждый минимум цены ниже = LL-цепочка)
          - Пивот тоже в зоне OS (< -60)

        Returns:
            int: 1 = одиночная, 2 = двойная, 3 = тройная (максимум)
        """
        count = 1
        cur_idx = first_pivot_idx
        cur_wt = first_pivot_wt
        cur_price = first_pivot_price

        for pivot in reversed(ind_pivots):
            if pivot['index'] >= cur_idx:
                continue
            if cur_idx - pivot['index'] > self.max_bars:
                break
            p_wt = pivot['value']
            p_price = df['low'].iloc[pivot['index']]
            # Следующий (старший) пивот должен быть ниже по WT и по цене, и в OS
            if p_wt < cur_wt and p_price < cur_price and p_wt < -60:
                count += 1
                cur_idx = pivot['index']
                cur_wt = p_wt
                cur_price = p_price
                if count >= 3:
                    break

        return count

    def _count_div_chain_bearish(self, df, indicator_col, first_pivot_idx, first_pivot_wt, first_pivot_price, ind_pivots):
        """
        Считает глубину медвежьей дивергентной цепочки.

        Для каждого более старого пивота:
          - WT пивота > WT текущего пивота (HH-цепочка в WT — WT рос, LH к текущему)
          - Цена пивота > цена текущего пивота (LH в цене ↔ HH-цепочка в прошлом)
          - Пивот в зоне OB (> 60)

        Returns:
            int: 1 = одиночная, 2 = двойная, 3 = тройная
        """
        count = 1
        cur_idx = first_pivot_idx
        cur_wt = first_pivot_wt
        cur_price = first_pivot_price

        for pivot in reversed(ind_pivots):
            if pivot['index'] >= cur_idx:
                continue
            if cur_idx - pivot['index'] > self.max_bars:
                break
            p_wt = pivot['value']
            p_price = df['high'].iloc[pivot['index']]
            if p_wt > cur_wt and p_price > cur_price and p_wt > 60:
                count += 1
                cur_idx = pivot['index']
                cur_wt = p_wt
                cur_price = p_price
                if count >= 3:
                    break

        return count

    def _calculate_strength(self, div_details, div_type, div_count: int = 1):
        """
        Расчет силы дивергенции (0-100).

        Учитывает:
        1. Расстояние между точками (макс 25 баллов)
        2. Величину расхождения индикатора
        3. Величину изменения цены
        4. КРИТИЧНО: нахождение в правильных зонах
        5. Бонус за двойную/тройную дивергенцию
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

        # Бонус за двойную/тройную дивергенцию
        if div_count == 2:
            score += 15
        elif div_count >= 3:
            score += 25

        return min(score, 100)


# Функция для форматирования сообщения (обновленная)
def divergence_message(symbol: str, div_info: dict) -> str:
    """Форматирует сообщение о дивергенции"""
    from core.ui.message_builder import tv_link
    from datetime import datetime
    
    div_type = div_info.get("type", "")
    direction = div_info.get("direction", "")
    strength = div_info.get("strength", 0)
    details = div_info.get("details", {})
    description = div_info.get("description", "")
    timeframe = div_info.get("timeframe", "15m")
    div_count = div_info.get("div_count", 1)

    # Определяем интервал для TradingView
    tf_to_interval = {"3m": 3, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
    interval = tf_to_interval.get(timeframe, 15)

    # Заголовок с множественностью
    _count_prefix = {1: "ДИВЕРГЕНЦИЯ", 2: "ДВОЙНАЯ ДИВЕРГЕНЦИЯ ⚡", 3: "ТРОЙНАЯ ДИВЕРГЕНЦИЯ 🔱"}
    header = _count_prefix.get(div_count, "ТРОЙНАЯ+ ДИВЕРГЕНЦИЯ 🔱")

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
        f"{emoji} <b>{header}</b> {emoji}",
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
        if div_count > 1:
            _chain_labels = {2: "🔁 Двойная цепочка — продавцы/покупатели выдохлись дважды",
                             3: "🔱 Тройная цепочка — экстремальное истощение, высокая вероятность разворота"}
            parts.append(_chain_labels.get(div_count, ""))
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


def mtf_divergence_message(symbol: str, div_info: dict) -> str:
    """Форматирует сообщение о MTF-конфлюэнции дивергенций."""
    from core.ui.message_builder import tv_link
    from datetime import datetime

    direction = div_info.get("direction", "LONG")
    strength = div_info.get("strength", 0)
    description = div_info.get("description", "")
    hidden_strength = div_info.get("hidden_strength", 0)
    regular_strength = div_info.get("regular_strength", 0)
    senior_tf = div_info.get("senior_tf", "1h")
    junior_tf = div_info.get("junior_tf", "15m")

    emoji = "🟢" if direction == "LONG" else "🔴"
    action = "LONG — ожидается рост" if direction == "LONG" else "SHORT — ожидается падение"

    if strength >= 75:
        strength_emoji, strength_text = "🔥🔥🔥", "Очень сильная"
    elif strength >= 60:
        strength_emoji, strength_text = "🔥🔥", "Сильная"
    elif strength >= 40:
        strength_emoji, strength_text = "🔥", "Средняя"
    else:
        strength_emoji, strength_text = "⚡", "Слабая"

    parts = [
        f"{emoji} <b>MTF-ДИВЕРГЕНЦИЯ</b> {emoji}",
        f"Пара: {tv_link(symbol)}",
        f"Направление: <b>{action}</b>",
        "",
        f"{strength_emoji} Сила сигнала: <b>{strength}/100</b> — {strength_text}",
        "",
        "<b>💡 Что произошло:</b>",
        f"  • Скрытая дивергенция ({senior_tf}): продолжение тренда, коррекция завершается (сила: {hidden_strength})",
        f"  • Регулярная дивергенция ({junior_tf}): точка входа по тренду (сила: {regular_strength})",
        f"  • {description}",
        "",
        "<b>⚠️ Рекомендации:</b>",
    ]

    if strength >= 75:
        parts.append("  • Отличная точка входа по тренду — стандартный объём")
        parts.append("  • Стоп ниже/выше уровня регулярной дивергенции на 15m")
    elif strength >= 60:
        parts.append("  • Хорошая точка входа — стандартный объём")
        parts.append("  • Дождитесь закрытия 15m свечи для подтверждения")
    else:
        parts.append("  • Средний сигнал — уменьшите объём вдвое")
        parts.append("  • Обязательно дождитесь подтверждения")

    parts += [
        "",
        f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]

    return "\n".join(parts)