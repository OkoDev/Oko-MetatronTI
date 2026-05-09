"""
Интеграция пивотных уровней с MTF анализом
"""
import logging
from typing import Dict, Optional, List, Tuple
from core.pivot_calculator import PivotCalculator
from core.mtf.mtf_checker import collect_mtf_data
from core.ui.message_builder import tv_link

logger = logging.getLogger(__name__)


class MTFPivotAnalyzer:
    """Комплексный анализ с MTF + пивотами"""
    
    def __init__(self):
        self.pivot_calc = PivotCalculator()
    
    async def analyze_with_pivots(
        self,
        symbol: str,
        data_collector,
        mtf_timeframes: List[str] = None,
        pivot_timeframes: List[str] = None
    ) -> Optional[Dict]:
        """
        Полный анализ с MTF и пивотами
        
        Args:
            symbol: торговая пара
            data_collector: коллектор данных
            mtf_timeframes: таймфреймы для MTF анализа
            pivot_timeframes: таймфреймы для пивотов
            
        Returns:
            словарь с результатами анализа
        """
        if mtf_timeframes is None:
            mtf_timeframes = ["3m", "5m", "15m", "45m", "1h", "4h"]
        
        if pivot_timeframes is None:
            pivot_timeframes = ["1h", "4h"]
        
        try:
            # 1. Получаем MTF данные
            mtf_snapshot = await collect_mtf_data(symbol, data_collector, mtf_timeframes)
            
            if not mtf_snapshot:
                logger.debug(f"Нет MTF данных для {symbol}")
                return None
            
            # 2. Получаем пивоты
            mtf_pivots = await self.pivot_calc.get_mtf_pivots(
                symbol,
                data_collector,
                pivot_timeframes,
                method="standard"
            )
            
            if not mtf_pivots:
                logger.debug(f"Нет пивотов для {symbol}")
                # Можем вернуть только MTF данные
                return {'mtf': mtf_snapshot, 'pivots': None}
            
            # 3. Получаем текущую цену
            df = await data_collector.get_ohlcv(symbol, "1m", limit=1)
            if df is None or df.empty:
                current_price = None
            else:
                current_price = df.iloc[-1]['close']
            
            # 4. Находим конфлюэнции пивотов
            confluences = self.pivot_calc.find_confluences(mtf_pivots, tolerance_percent=0.5)
            
            # 5. Определяем ближайшие уровни
            nearest_levels = None
            if current_price and mtf_pivots:
                first_pivots = list(mtf_pivots.values())[0]
                nearest_levels = self.pivot_calc.get_nearest_levels(
                    current_price,
                    first_pivots,
                    count=3
                )
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'mtf': mtf_snapshot,
                'pivots': mtf_pivots,
                'confluences': confluences,
                'nearest_levels': nearest_levels
            }
            
        except Exception:
            logger.exception(f"Ошибка анализа {symbol}")
            return None
    
    def check_pivot_mtf_signal(self, analysis: Dict) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Проверяет комбинированный сигнал: MTF + близость к пивоту
        
        Args:
            analysis: результат analyze_with_pivots
            
        Returns:
            (есть_сигнал, тип_сигнала, информация)
        """
        if not analysis or not analysis.get('mtf') or not analysis.get('nearest_levels'):
            return False, None, None
        
        mtf = analysis['mtf']
        nearest = analysis['nearest_levels']
        current_price = analysis.get('current_price')
        
        # Проверяем MTF условия для LONG
        long_conditions = self._check_long_mtf(mtf)
        short_conditions = self._check_short_mtf(mtf)
        
        # Проверяем близость к пивотным уровням
        near_support = any(dist < 1.0 for _, _, dist in nearest['support'][:2])
        near_resistance = any(dist < 1.0 for _, _, dist in nearest['resistance'][:2])
        
        # LONG сигнал: MTF разворот вверх + цена у поддержки
        if long_conditions and near_support:
            closest_support = nearest['support'][0] if nearest['support'] else None
            info = {
                'type': 'LONG',
                'reason': 'MTF разворот + пивот поддержка',
                'mtf_strength': self._calculate_mtf_strength(mtf, 'LONG'),
                'pivot_level': closest_support[1] if closest_support else None,
                'pivot_name': closest_support[0] if closest_support else None,
                'distance_to_pivot': closest_support[2] if closest_support else None
            }
            return True, 'LONG', info
        
        # SHORT сигнал: MTF разворот вниз + цена у сопротивления
        if short_conditions and near_resistance:
            closest_resistance = nearest['resistance'][0] if nearest['resistance'] else None
            info = {
                'type': 'SHORT',
                'reason': 'MTF разворот + пивот сопротивление',
                'mtf_strength': self._calculate_mtf_strength(mtf, 'SHORT'),
                'pivot_level': closest_resistance[1] if closest_resistance else None,
                'pivot_name': closest_resistance[0] if closest_resistance else None,
                'distance_to_pivot': closest_resistance[2] if closest_resistance else None
            }
            return True, 'SHORT', info
        
        return False, None, None
    
    def _check_long_mtf(self, mtf: Dict) -> bool:
        """Проверка MTF условий для LONG"""
        # Старшие таймфреймы в OS
        os_count = sum(
            1 for tf in ["1h", "4h", "45m", "15m"]
            if mtf.get(tf, {}).get('zone') == 'OS'
        )
        
        # Младшие разворачиваются вверх
        small_tf_up = (
            mtf.get("5m", {}).get('trend') == 'UP' or
            mtf.get("3m", {}).get('trend') == 'UP'
        )
        
        return os_count >= 2 and small_tf_up
    
    def _check_short_mtf(self, mtf: Dict) -> bool:
        """Проверка MTF условий для SHORT"""
        # Старшие таймфреймы в OB
        ob_count = sum(
            1 for tf in ["1h", "4h", "45m", "15m"]
            if mtf.get(tf, {}).get('zone') == 'OB'
        )
        
        # Младшие разворачиваются вниз
        small_tf_down = (
            mtf.get("5m", {}).get('trend') == 'DOWN' or
            mtf.get("3m", {}).get('trend') == 'DOWN'
        )
        
        return ob_count >= 2 and small_tf_down
    
    def _calculate_mtf_strength(self, mtf: Dict, signal_type: str) -> int:
        """Рассчитывает силу MTF сигнала (0-100)"""
        score = 0
        
        if signal_type == 'LONG':
            # Зоны OS
            for tf, weight in [("4h", 25), ("1h", 20), ("45m", 15), ("15m", 10)]:
                if mtf.get(tf, {}).get('zone') == 'OS':
                    score += weight
            
            # Развороты вверх
            if mtf.get("5m", {}).get('trend') == 'UP':
                score += 15
            if mtf.get("3m", {}).get('trend') == 'UP':
                score += 15
        
        elif signal_type == 'SHORT':
            # Зоны OB
            for tf, weight in [("4h", 25), ("1h", 20), ("45m", 15), ("15m", 10)]:
                if mtf.get(tf, {}).get('zone') == 'OB':
                    score += weight
            
            # Развороты вниз
            if mtf.get("5m", {}).get('trend') == 'DOWN':
                score += 15
            if mtf.get("3m", {}).get('trend') == 'DOWN':
                score += 15
        
        return min(score, 100)


def format_pivot_signal_message(symbol: str, analysis: Dict, signal_info: Dict) -> str:
    """
    Форматирует сообщение о сигнале с пивотами
    
    Args:
        symbol: торговая пара
        analysis: результат analyze_with_pivots
        signal_info: информация о сигнале
        
    Returns:
        отформатированное HTML сообщение
    """
    emoji = "🟢" if signal_info['type'] == 'LONG' else "🔴"
    
    parts = [
        f"{emoji} <b>MTF + ПИВОТ СИГНАЛ</b> {emoji}",
        f"Пара: {tv_link(symbol, interval=3)}",
        f"Тип: <b>{signal_info['type']}</b>",
        f"Причина: {signal_info['reason']}",
        ""
    ]
    
    # Информация о силе сигнала
    strength = signal_info.get('mtf_strength', 0)
    if strength >= 70:
        strength_text = "🔥🔥🔥 Очень высокая"
    elif strength >= 50:
        strength_text = "🔥🔥 Высокая"
    elif strength >= 30:
        strength_text = "🔥 Средняя"
    else:
        strength_text = "⚠️ Низкая"
    
    parts.append(f"Сила MTF: {strength}/100 ({strength_text})")
    
    # Пивотный уровень
    if signal_info.get('pivot_level'):
        parts.append("")
        parts.append("<b>🎯 Пивотный уровень:</b>")
        parts.append(f"  {signal_info['pivot_name']}: {signal_info['pivot_level']:.4f}")
        parts.append(f"  Расстояние: {signal_info['distance_to_pivot']:.2f}%")
    
    # MTF состояние (ключевые таймфреймы)
    mtf = analysis.get('mtf', {})
    if mtf:
        parts.append("")
        parts.append("<b>📊 MTF состояние:</b>")
        
        key_timeframes = ["1h", "45m", "15m", "5m", "3m"]
        for tf in key_timeframes:
            if tf in mtf:
                data = mtf[tf]
                trend_emoji = "📈" if data['trend'] == 'UP' else "📉"
                zone_emoji = "🔴" if data['zone'] == 'OB' else "🟢" if data['zone'] == 'OS' else "⚪"
                
                parts.append(
                    f"{tf:>4}: {trend_emoji} {data['trend']} | "
                    f"WT({data['wt1']:.1f}/{data['wt2']:.1f}) | "
                    f"{zone_emoji} {data['zone']}"
                )
    
    # Торговые рекомендации
    parts.append("")
    parts.append("<b>💡 Рекомендации:</b>")
    
    if signal_info['type'] == 'LONG':
        parts.append("📈 <b>Вход в LONG:</b>")
        if strength >= 70:
            parts.append("  • Сильный сигнал - агрессивный вход")
            parts.append("  • Вход по рынку или лимитом у пивота")
        else:
            parts.append("  • Средний сигнал - ждать подтверждения")
            parts.append("  • Вход после пробоя локального максимума")
        
        if signal_info.get('pivot_level'):
            parts.append(f"  • 🛡️ Стоп: под {signal_info['pivot_name']} ({signal_info['pivot_level']:.4f})")
        else:
            parts.append("  • 🛡️ Стоп: под последний минимум 5m")
        
        parts.append("  • 🎯 Цель 1: ближайшее сопротивление")
        parts.append("  • 🎯 Цель 2: R1/R2 пивоты")
    
    else:  # SHORT
        parts.append("📉 <b>Вход в SHORT:</b>")
        if strength >= 70:
            parts.append("  • Сильный сигнал - агрессивный вход")
            parts.append("  • Вход по рынку или лимитом у пивота")
        else:
            parts.append("  • Средний сигнал - ждать подтверждения")
            parts.append("  • Вход после пробоя локального минимума")
        
        if signal_info.get('pivot_level'):
            parts.append(f"  • 🛡️ Стоп: над {signal_info['pivot_name']} ({signal_info['pivot_level']:.4f})")
        else:
            parts.append("  • 🛡️ Стоп: над последний максимум 5m")
        
        parts.append("  • 🎯 Цель 1: ближайшая поддержка")
        parts.append("  • 🎯 Цель 2: S1/S2 пивоты")
    
    # Конфлюэнции
    confluences = analysis.get('confluences', [])
    if confluences:
        parts.append("")
        parts.append(f"<b>🎯 Конфлюэнции пивотов ({len(confluences)}):</b>")
        for i, conf in enumerate(confluences[:3], 1):
            parts.append(
                f"{i}. {conf['value']:.4f} "
                f"(сила: {conf['strength']}, TF: {', '.join(conf['timeframes'])})"
            )
    
    # Риск-менеджмент
    parts.append("")
    parts.append("<b>⚠️ Управление рисками:</b>")
    if strength >= 70:
        parts.append("  • Можно использовать увеличенный объем")
        parts.append("  • Риск: 1-2% от депозита")
    elif strength >= 50:
        parts.append("  • Стандартный объем позиции")
        parts.append("  • Риск: 0.5-1% от депозита")
    else:
        parts.append("  • Минимальный объем позиции")
        parts.append("  • Риск: не более 0.5% от депозита")
    
    return "\n".join(parts)


def format_pivot_levels_message(symbol: str, analysis: Dict) -> str:
    """
    Форматирует сообщение с пивотными уровнями
    
    Returns:
        отформатированное сообщение для Telegram
    """
    parts = [
        f"📊 <b>ПИВОТНЫЕ УРОВНИ</b>",
        f"Пара: {tv_link(symbol, interval=15)}",
        ""
    ]
    
    if not analysis or not analysis.get('pivots'):
        parts.append("⚠️ Нет данных о пивотах")
        return "\n".join(parts)
    
    current_price = analysis.get('current_price')
    if current_price:
        parts.append(f"💰 Текущая цена: {current_price:.6f}")
        parts.append("")
    
    # Выводим пивоты по таймфреймам
    pivots = analysis['pivots']
    for tf, pivot_data in pivots.items():
        parts.append(f"<b>⏱ {tf.upper()}</b>")
        
        calculator = PivotCalculator()
        formatted = calculator.format_pivot_levels(pivot_data)
        parts.append(formatted)
        parts.append("")
    
    # Конфлюэнции
    confluences = analysis.get('confluences', [])
    if confluences:
        parts.append(f"<b>🎯 Конфлюэнции ({len(confluences)}):</b>")
        for i, conf in enumerate(confluences[:5], 1):
            distance = ""
            if current_price:
                dist_pct = abs(current_price - conf['value']) / current_price * 100
                distance = f" ({dist_pct:.2f}% от цены)"
            
            parts.append(
                f"{i}. {conf['value']:.4f}{distance}\n"
                f"   Сила: {conf['strength']} | TF: {', '.join(conf['timeframes'])}"
            )
    
    # Ближайшие уровни
    nearest = analysis.get('nearest_levels')
    if nearest and current_price:
        parts.append("")
        parts.append("<b>🔴 Ближайшие сопротивления:</b>")
        for name, level, distance in nearest['resistance'][:3]:
            parts.append(f"  {name}: {level:.4f} (+{distance:.2f}%)")
        
        parts.append("")
        parts.append("<b>🟢 Ближайшие поддержки:</b>")
        for name, level, distance in nearest['support'][:3]:
            parts.append(f"  {name}: {level:.4f} (-{distance:.2f}%)")
    
    return "\n".join(parts)