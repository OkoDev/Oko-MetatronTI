"""
ИСПРАВЛЕННЫЙ модуль расчета НЕДЕЛЬНЫХ и ДНЕВНЫХ пивотов
Решает проблему получения данных с BingX для 1D и 1W таймфреймов
"""
import asyncio
import logging
import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class PivotCalculatorFixed:
    """
    Расчет Traditional Pivot Points для НЕДЕЛЬНЫХ и ДНЕВНЫХ таймфреймов
    
    ИСПРАВЛЕНИЕ: Использует альтернативные методы получения данных
    """
    
    def __init__(self):
        self.pivot_cache = {}
        self.cache_timeout = 3600  # 1 час для недельных, обновляется редко
    
    def calculate_traditional_pivots(self, high: float, low: float, close: float) -> Dict[str, float]:
        """
        Расчет Traditional Pivot Points по формулам из Pine Script
        
        Args:
            high: максимум предыдущего периода
            low: минимум предыдущего периода
            close: закрытие предыдущего периода
            
        Returns:
            Словарь с уровнями PP, S1-S5, R1-R5
        """
        # Pivot Point
        pp = (high + low + close) / 3.0
        
        # Support levels (поддержки)
        s1 = pp * 2.003 - high
        s2 = pp - (high - low)
        s3 = pp * 2 - (2 * high - low)
        s4 = pp * 3 - (3 * high - low)
        s5 = pp * 4 - (4 * high - low)
        
        # Resistance levels (сопротивления)
        r1 = pp * 1.997 - low
        r2 = pp + (high - low)
        r3 = pp * 2 + (high - 2 * low)
        r4 = pp * 3 + (high - 3 * low)
        r5 = pp * 4 + (high - 4 * low)
        
        return {
            'PP': pp,
            'S1': s1, 'S2': s2, 'S3': s3, 'S4': s4, 'S5': s5,
            'R1': r1, 'R2': r2, 'R3': r3, 'R4': r4, 'R5': r5
        }
    
    async def get_weekly_pivots_method1(self, symbol: str, data_collector) -> Optional[Dict]:
        """
        МЕТОД 1: Получение недельных пивотов через меньшие таймфреймы
        Собираем данные за неделю из дневных свечей
        """
        try:
            # Пробуем получить дневные данные
            df = await data_collector.get_ohlcv(symbol, timeframe="1d", limit=10)
            
            if df is None or len(df) < 7:
                logger.debug(f"Недостаточно дневных данных для {symbol}")
                return None
            
            # Берем последние 7 дней (неделя)
            week_data = df.iloc[-7:].copy()
            
            # Вычисляем недельные H/L/C
            high_week = week_data['high'].max()
            low_week = week_data['low'].min()
            close_week = week_data['close'].iloc[-1]  # Последнее закрытие
            
            # Рассчитываем пивоты
            pivots = self.calculate_traditional_pivots(high_week, low_week, close_week)
            pivots['timeframe'] = '1W'
            pivots['method'] = 'aggregated_from_1d'
            pivots['timestamp'] = datetime.now()
            
            logger.info(f"✅ Недельные пивоты для {symbol}: PP={pivots['PP']:.4f}")
            return pivots
            
        except Exception as e:
            logger.debug(f"Метод 1 failed для {symbol}: {e}")
            return None
    
    async def get_weekly_pivots_method2(self, symbol: str, data_collector) -> Optional[Dict]:
        """
        МЕТОД 2: Получение недельных пивотов через 4-часовые свечи
        Собираем 42 свечи по 4h = 7 дней
        """
        try:
            # Получаем 4-часовые свечи за неделю (42 свечи = 7 дней)
            df = await data_collector.get_ohlcv(symbol, timeframe="4h", limit=50)
            
            if df is None or len(df) < 42:
                logger.debug(f"Недостаточно 4h данных для {symbol}")
                return None
            
            # Берем последние 42 свечи (неделя)
            week_data = df.iloc[-42:].copy()
            
            # Вычисляем недельные H/L/C
            high_week = week_data['high'].max()
            low_week = week_data['low'].min()
            close_week = week_data['close'].iloc[-1]
            
            # Рассчитываем пивоты
            pivots = self.calculate_traditional_pivots(high_week, low_week, close_week)
            pivots['timeframe'] = '1W'
            pivots['method'] = 'aggregated_from_4h'
            pivots['timestamp'] = datetime.now()
            
            logger.info(f"✅ Недельные пивоты для {symbol} (метод 2): PP={pivots['PP']:.4f}")
            return pivots
            
        except Exception as e:
            logger.debug(f"Метод 2 failed для {symbol}: {e}")
            return None
    
    async def get_daily_pivots(self, symbol: str, data_collector) -> Optional[Dict]:
        """
        Получение ДНЕВНЫХ пивотов
        
        Args:
            symbol: торговая пара
            data_collector: коллектор данных
            
        Returns:
            Словарь с дневными пивотами или None
        """
        try:
            # Проверяем кэш (для 1D данных это особенно эффективно)
            cache_key = f"{symbol}_1D"
            cached = self.pivot_cache.get(cache_key)
            if cached:
                age = (datetime.now() - cached["timestamp"]).total_seconds()
                # Дневные пивоты можно кэшировать дольше, но оставим общий таймаут
                if age < self.cache_timeout:
                    logger.debug(f"Используем кэш для {symbol} 1D")
                    return cached

            # Пробуем напрямую получить дневные данные
            df = await data_collector.get_ohlcv(symbol, timeframe="1d", limit=5)
            
            if df is not None and len(df) >= 2:
                # Используем предпоследний день
                prev_day = df.iloc[-2]
                
                high_day = prev_day['high']
                low_day = prev_day['low']
                close_day = prev_day['close']
                
                pivots = self.calculate_traditional_pivots(high_day, low_day, close_day)
                pivots['timeframe'] = '1D'
                pivots['method'] = 'direct_1d'
                pivots['timestamp'] = datetime.now()
                
                logger.info(f"✅ Дневные пивоты для {symbol}: PP={pivots['PP']:.4f}")
                self.pivot_cache[cache_key] = pivots
                return pivots
            
            # Если не получилось - агрегируем из часовых
            df_1h = await data_collector.get_ohlcv(symbol, timeframe="1h", limit=30)
            
            if df_1h is None or len(df_1h) < 24:
                logger.debug(f"Недостаточно данных для дневных пивотов {symbol}")
                return None
            
            # Берем последние 24 часа (день)
            day_data = df_1h.iloc[-24:].copy()
            
            high_day = day_data['high'].max()
            low_day = day_data['low'].min()
            close_day = day_data['close'].iloc[-1]
            
            pivots = self.calculate_traditional_pivots(high_day, low_day, close_day)
            pivots['timeframe'] = '1D'
            pivots['method'] = 'aggregated_from_1h'
            pivots['timestamp'] = datetime.now()
            
            logger.info(f"✅ Дневные пивоты для {symbol} (из 1h): PP={pivots['PP']:.4f}")
            self.pivot_cache[cache_key] = pivots
            return pivots
            
        except Exception as e:
            logger.exception(f"Ошибка получения дневных пивотов для {symbol}")
            return None
    
    async def get_weekly_pivots(self, symbol: str, data_collector) -> Optional[Dict]:
        """
        Получение НЕДЕЛЬНЫХ пивотов с использованием нескольких методов
        
        Пробует методы по очереди:
        1. Агрегация из дневных свечей (1d)
        2. Агрегация из 4-часовых свечей (4h)
        
        Returns:
            Словарь с недельными пивотами или None
        """
        # Проверяем кэш
        cache_key = f"{symbol}_1W"
        if cache_key in self.pivot_cache:
            cached = self.pivot_cache[cache_key]
            age = (datetime.now() - cached['timestamp']).total_seconds()
            if age < self.cache_timeout:
                logger.debug(f"Используем кэш для {symbol} 1W")
                return cached
        
        # Метод 1: Из дневных данных
        pivots = await self.get_weekly_pivots_method1(symbol, data_collector)
        if pivots:
            self.pivot_cache[cache_key] = pivots
            return pivots
        
        # Метод 2: Из 4-часовых данных
        pivots = await self.get_weekly_pivots_method2(symbol, data_collector)
        if pivots:
            self.pivot_cache[cache_key] = pivots
            return pivots
        
        logger.warning(f"❌ Не удалось получить недельные пивоты для {symbol}")
        return None
    
    async def get_multi_timeframe_pivots(
        self,
        symbol: str,
        data_collector
    ) -> Dict[str, Dict]:
        """
        Получает НЕДЕЛЬНЫЕ и ДНЕВНЫЕ пивоты
        
        Returns:
            {'1W': {...}, '1D': {...}, 'confluence': [...]}
        """
        results: Dict[str, Dict] = {}
        
        # Параллельно получаем недельные и дневные пивоты,
        # чтобы не ждать их последовательно (ускорение при работе с биржей).
        weekly, daily = await asyncio.gather(
            self.get_weekly_pivots(symbol, data_collector),
            self.get_daily_pivots(symbol, data_collector),
        )
        
        if weekly:
            results['1W'] = weekly
            logger.info(f"✅ Недельные пивоты получены для {symbol}")
        else:
            logger.warning(f"⚠️ Не удалось получить недельные пивоты для {symbol}")
        
        if daily:
            results['1D'] = daily
            logger.info(f"✅ Дневные пивоты получены для {symbol}")
        else:
            logger.warning(f"⚠️ Не удалось получить дневные пивоты для {symbol}")
        
        # Ищем конфлюэнции (совпадения уровней)
        if '1W' in results and '1D' in results:
            confluence = self.find_confluences(results['1W'], results['1D'])
            results['confluence'] = confluence
            if confluence:
                logger.info(f"🎯 Найдено {len(confluence)} конфлюэнций для {symbol}")
        else:
            results['confluence'] = []
        
        return results
    
    def find_confluences(
        self,
        weekly_pivots: Dict,
        daily_pivots: Dict,
        tolerance_percent: float = 0.3
    ) -> List[Dict]:
        """
        Находит конфлюэнции между недельными и дневными пивотами
        
        Args:
            weekly_pivots: недельные уровни
            daily_pivots: дневные уровни
            tolerance_percent: порог совпадения (0.3% = сильная конфлюэнция)
            
        Returns:
            Список конфлюэнций с информацией
        """
        confluences = []
        
        # Все уровни для проверки
        all_levels = ['PP'] + [f'S{i}' for i in range(1, 6)] + [f'R{i}' for i in range(1, 6)]
        
        for w_level in all_levels:
            if w_level not in weekly_pivots:
                continue
            
            w_price = weekly_pivots[w_level]
            
            # Проверяем совпадения с дневными
            for d_level in all_levels:
                if d_level not in daily_pivots:
                    continue
                
                d_price = daily_pivots[d_level]
                
                # Рассчитываем расстояние
                if w_price == 0:
                    continue
                
                distance_percent = abs((w_price - d_price) / w_price * 100)
                
                if distance_percent <= tolerance_percent:
                    confluences.append({
                        'weekly_level': w_level,
                        'weekly_price': w_price,
                        'daily_level': d_level,
                        'daily_price': d_price,
                        'distance_percent': distance_percent,
                        'strength': 'VERY_STRONG' if distance_percent < 0.1 else 'STRONG'
                    })
        
        # Сортируем по силе
        confluences.sort(key=lambda x: x['distance_percent'])
        
        return confluences
    
    def is_near_level(
        self,
        current_price: float,
        pivots: Dict[str, float],
        threshold_percent: float = 0.5
    ) -> Optional[Dict]:
        """
        Проверяет, находится ли цена близко к какому-либо уровню
        
        Args:
            current_price: текущая цена
            pivots: словарь с пивотами
            threshold_percent: порог близости (0.5%)
            
        Returns:
            Информация об уровне или None
        """
        if not pivots or current_price <= 0:
            return None
        
        # Проверяем все уровни
        all_levels = ['PP'] + [f'S{i}' for i in range(1, 6)] + [f'R{i}' for i in range(1, 6)]
        
        for level_key in all_levels:
            if level_key not in pivots:
                continue
            
            level_price = pivots[level_key]
            if level_price <= 0:
                continue
            
            distance_percent = abs((current_price - level_price) / current_price * 100)
            
            if distance_percent <= threshold_percent:
                # Определяем тип уровня
                if level_key == 'PP':
                    level_type = 'pivot'
                elif 'S' in level_key:
                    level_type = 'support'
                else:
                    level_type = 'resistance'
                
                return {
                    'near_level': True,
                    'level': level_key,
                    'level_type': level_type,
                    'price': level_price,
                    'distance_percent': distance_percent,
                    'timeframe': pivots.get('timeframe', 'N/A')
                }
        
        return None
    
    def get_nearest_levels(
        self,
        current_price: float,
        pivots: Dict[str, float],
        count: int = 3
    ) -> Dict[str, List]:
        """
        Находит ближайшие уровни поддержки и сопротивления
        
        Returns:
            {'support': [(name, price, distance_pct)], 
             'resistance': [(name, price, distance_pct)]}
        """
        if not pivots or current_price <= 0:
            return {'support': [], 'resistance': []}
        
        supports = []
        resistances = []
        
        all_levels = ['PP'] + [f'S{i}' for i in range(1, 6)] + [f'R{i}' for i in range(1, 6)]
        
        for level_key in all_levels:
            if level_key not in pivots:
                continue
            
            level_price = pivots[level_key]
            if level_price <= 0:
                continue
            
            distance_pct = abs((current_price - level_price) / current_price * 100)
            
            if level_price < current_price:
                supports.append((level_key, level_price, distance_pct))
            elif level_price > current_price:
                resistances.append((level_key, level_price, distance_pct))
        
        # Сортируем по близости
        supports.sort(key=lambda x: x[2])
        resistances.sort(key=lambda x: x[2])
        
        return {
            'support': supports[:count],
            'resistance': resistances[:count]
        }
    
    def format_pivot_message(
        self,
        symbol: str,
        pivots_data: Dict,
        current_price: float
    ) -> str:
        """
        Форматирует сообщение с пивотными уровнями для Telegram
        """
        from core.message_builder import tv_link
        
        parts = [
            "📊 <b>ПИВОТНЫЕ УРОВНИ</b>",
            f"Пара: {tv_link(symbol, interval=240)}",  # 4h график
            f"💰 Цена: {current_price:.6f}",
            ""
        ]
        
        # Недельные пивоты
        if '1W' in pivots_data:
            weekly = pivots_data['1W']
            method = weekly.get('method', 'unknown')
            
            parts.append("<b>📅 НЕДЕЛЬНЫЕ ПИВОТЫ (1W)</b>")
            parts.append(f"<i>Метод: {method}</i>")
            parts.append("")
            
            # Сопротивления (показываем все, включая R3)
            parts.append("<b>🔴 Сопротивления:</b>")
            for i in range(5, 0, -1):
                key = f'R{i}'
                if key in weekly:
                    if weekly[key] > current_price:
                        dist = ((weekly[key] - current_price) / current_price) * 100
                        parts.append(f"  {key}: {weekly[key]:.6f} (+{dist:.2f}%)")
                    else:
                        dist = ((current_price - weekly[key]) / current_price) * 100
                        parts.append(f"  {key}: {weekly[key]:.6f} (-{dist:.2f}% ниже цены)")
            
            # PP
            if 'PP' in weekly:
                pp = weekly['PP']
                dist = ((pp - current_price) / current_price) * 100
                parts.append(f"\n<b>⚪ PP: {pp:.6f} ({dist:+.2f}%)</b>\n")
            
            # Поддержки (показываем все, включая S3)
            parts.append("<b>🟢 Поддержки:</b>")
            for i in range(1, 6):
                key = f'S{i}'
                if key in weekly:
                    if weekly[key] < current_price:
                        dist = ((current_price - weekly[key]) / current_price) * 100
                        parts.append(f"  {key}: {weekly[key]:.6f} (-{dist:.2f}%)")
                    else:
                        dist = ((weekly[key] - current_price) / current_price) * 100
                        parts.append(f"  {key}: {weekly[key]:.6f} (+{dist:.2f}% выше цены)")
            
            parts.append("")
        
        # Дневные пивоты
        if '1D' in pivots_data:
            daily = pivots_data['1D']
            method = daily.get('method', 'unknown')
            
            parts.append("<b>📅 ДНЕВНЫЕ ПИВОТЫ (1D)</b>")
            parts.append(f"<i>Метод: {method}</i>")
            parts.append("")
            
            # Сопротивления (показываем все, включая R3)
            parts.append("<b>🔴 Сопротивления:</b>")
            for i in range(5, 0, -1):
                key = f'R{i}'
                if key in daily:
                    if daily[key] > current_price:
                        dist = ((daily[key] - current_price) / current_price) * 100
                        parts.append(f"  {key}: {daily[key]:.6f} (+{dist:.2f}%)")
                    else:
                        dist = ((current_price - daily[key]) / current_price) * 100
                        parts.append(f"  {key}: {daily[key]:.6f} (-{dist:.2f}% ниже цены)")
            
            # PP
            if 'PP' in daily:
                pp = daily['PP']
                dist = ((pp - current_price) / current_price) * 100
                parts.append(f"\n<b>⚪ PP: {pp:.6f} ({dist:+.2f}%)</b>\n")
            
            # Поддержки (показываем все, включая S3)
            parts.append("<b>🟢 Поддержки:</b>")
            for i in range(1, 6):
                key = f'S{i}'
                if key in daily:
                    if daily[key] < current_price:
                        dist = ((current_price - daily[key]) / current_price) * 100
                        parts.append(f"  {key}: {daily[key]:.6f} (-{dist:.2f}%)")
                    else:
                        dist = ((daily[key] - current_price) / current_price) * 100
                        parts.append(f"  {key}: {daily[key]:.6f} (+{dist:.2f}% выше цены)")
            
            parts.append("")
        
        # Конфлюэнции
        confluences = pivots_data.get('confluence', [])
        if confluences:
            parts.append(f"<b>🎯 КОНФЛЮЭНЦИИ ({len(confluences)}):</b>")
            for i, conf in enumerate(confluences[:3], 1):
                parts.append(
                    f"{i}. {conf['weekly_level']} (1W) ≈ {conf['daily_level']} (1D)\n"
                    f"   Цена: {conf['weekly_price']:.6f} ({conf['strength']})"
                )
            parts.append("")
        
        # Проверка близости к уровню
        if '1W' in pivots_data:
            near = self.is_near_level(current_price, pivots_data['1W'], 0.5)
            if near:
                parts.append(f"⚠️  <b>ЦЕНА У НЕДЕЛЬНОГО УРОВНЯ!</b>")
                parts.append(f"Уровень: {near['level']} ({near['level_type']})")
                parts.append(f"Расстояние: {near['distance_percent']:.3f}%")
                parts.append("→ Жди подтверждения для входа!")
        
        parts.append("")
        parts.append(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(parts)