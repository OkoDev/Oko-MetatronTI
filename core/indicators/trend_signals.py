import logging
from core.indicators.indicators import calculate_trend, calculate_wt, get_zone
from core.infra.config_loader import config as _cfg_ts
_TS_ATR_P = int(_cfg_ts.get("analysis.indicators.trend.atr_period", 43))
_TS_FACTOR = float(_cfg_ts.get("analysis.indicators.trend.factor", 1.0))

logger = logging.getLogger(__name__)


async def check_trend_following_signal(symbol, data_collector, divergence_detector=None, pivot_calculator=None):
    """
    Проверяет сигналы работы по тренду (Trend Following).
    
    Логика:
    1. Определяем основной тренд на старшем ТФ (1h, 4h)
    2. Ищем откат на младшем ТФ (15m, 5m)
    3. Подтверждение: зона перепроданности/перекупленности
    4. Вход: при развороте младшего ТФ в направлении тренда
    5. НОВОЕ: Проверяем наличие дивергенции для усиления сигнала
    6. НОВОЕ: Проверяем близость к пивотным уровням для усиления сигнала
    
    Args:
        symbol: торговая пара
        data_collector: коллектор данных
        divergence_detector: детектор дивергенций (опционально)
        pivot_calculator: калькулятор пивотов (опционально) - для усиления сигналов
    
    Возвращает: (True/False, dict с деталями сигнала)
    """
    try:
        # === 1. Определяем тренд на 4h ===
        df_4h = await data_collector.get_ohlcv(symbol, "4h", limit=150)
        if df_4h is None or df_4h.empty:
            return False, None
        
        # D-063: ARCH-18 — reuse pre-computed если есть
        if "trend" not in df_4h.columns:
            df_4h = calculate_trend(df_4h, atr_period=_TS_ATR_P, factor=_TS_FACTOR)
        if "wt1" not in df_4h.columns:
            df_4h = calculate_wt(df_4h)
        trend_4h = df_4h["trend"].iloc[-1]
        
        # Нужен четкий тренд
        if trend_4h == 0:
            return False, None
        
        # === 2. Проверяем тренд на 1h (подтверждение) ===
        df_1h = await data_collector.get_ohlcv(symbol, "1h", limit=150)
        if df_1h is None or df_1h.empty:
            return False, None
        
        # D-063: ARCH-18 reuse
        if "trend" not in df_1h.columns:
            df_1h = calculate_trend(df_1h, atr_period=_TS_ATR_P, factor=_TS_FACTOR)
        if "wt1" not in df_1h.columns:
            df_1h = calculate_wt(df_1h)
        trend_1h = df_1h["trend"].iloc[-1]
        wt1_1h = df_1h["wt1"].iloc[-1]
        zone_1h = get_zone(wt1_1h)
        
        # 1h должен совпадать с 4h (сильный тренд)
        if trend_1h != trend_4h:
            return False, None
        
        # === 3. Ищем откат на 15m ===
        from core.infra.entry_config import get_primary_entry_tf
        df_15m = await data_collector.get_ohlcv(symbol, get_primary_entry_tf(), limit=150)
        if df_15m is None or df_15m.empty:
            return False, None
        
        # D-063: ARCH-18 reuse
        if "trend" not in df_15m.columns:
            df_15m = calculate_trend(df_15m, atr_period=_TS_ATR_P, factor=_TS_FACTOR)
        if "wt1" not in df_15m.columns:
            df_15m = calculate_wt(df_15m)
        trend_15m = df_15m["trend"].iloc[-1]
        wt1_15m = df_15m["wt1"].iloc[-1]
        wt2_15m = df_15m["wt2"].iloc[-1]
        zone_15m = get_zone(wt1_15m)
        
        # Проверяем кросс WT на 15m
        wt1_15m_prev = df_15m["wt1"].iloc[-2]
        wt2_15m_prev = df_15m["wt2"].iloc[-2]
        cross_up_15m = wt1_15m_prev < wt2_15m_prev and wt1_15m > wt2_15m
        cross_down_15m = wt1_15m_prev > wt2_15m_prev and wt1_15m < wt2_15m
        
        # === 4. Проверяем 5m для точного входа ===
        df_5m = await data_collector.get_ohlcv(symbol, "5m", limit=150)
        if df_5m is None or df_5m.empty:
            return False, None
        
        # D-063: ARCH-18 reuse
        if "trend" not in df_5m.columns:
            df_5m = calculate_trend(df_5m, atr_period=_TS_ATR_P, factor=_TS_FACTOR)
        if "wt1" not in df_5m.columns:
            df_5m = calculate_wt(df_5m)
        trend_5m = df_5m["trend"].iloc[-1]
        wt1_5m = df_5m["wt1"].iloc[-1]
        zone_5m = get_zone(wt1_5m)
        
        # === LONG SETUP (Тренд вверх) ===
        if trend_4h == 1 and trend_1h == 1:
            # Вариант 1: Классический откат
            # 15m в зоне перепроданности + разворот вверх
            if zone_15m == "OS" and cross_up_15m and trend_5m == 1:
                logger.debug("[%s] trend_following LONG: классический откат (15m OS + cross_up + 5m UP)", symbol)
                signal_info = {
                    "symbol": symbol,
                    "type": "TREND_LONG",
                    "pattern": "Классический откат",
                    "trend_4h": "UP",
                    "trend_1h": "UP",
                    "trend_15m": "UP" if trend_15m == 1 else "DOWN",
                    "trend_5m": "UP",
                    "wt_15m": f"{wt1_15m:.1f}/{wt2_15m:.1f}",
                    "zone_15m": zone_15m,
                    "zone_5m": zone_5m,
                    "confidence": "HIGH",
                    "entry_price": df_5m["close"].iloc[-1],
                    "stop_loss": df_15m["low"].iloc[-5:].min(),
                    "take_profit_1": df_5m["close"].iloc[-1] * 1.02,
                    "take_profit_2": df_5m["close"].iloc[-1] * 1.04,
                }
                # Усиливаем сигнал пивотами, если доступен калькулятор
                if pivot_calculator:
                    signal_info = await _enhance_signal_with_pivots(
                        signal_info, symbol, df_5m["close"].iloc[-1], pivot_calculator, data_collector
                    )
                return True, signal_info
            
            # Вариант 2: Агрессивный вход
            # 1h в зоне OS, 15m разворачивается, 5m уже в тренде
            if zone_1h == "OS" and trend_15m == 1 and trend_5m == 1 and zone_5m != "OB":
                signal_info = {
                    "symbol": symbol,
                    "type": "TREND_LONG",
                    "pattern": "Агрессивный вход",
                    "trend_4h": "UP",
                    "trend_1h": "UP",
                    "trend_15m": "UP",
                    "trend_5m": "UP",
                    "wt_15m": f"{wt1_15m:.1f}/{wt2_15m:.1f}",
                    "zone_15m": zone_15m,
                    "zone_5m": zone_5m,
                    "confidence": "MEDIUM",
                    "entry_price": df_5m["close"].iloc[-1],
                    "stop_loss": df_15m["low"].iloc[-5:].min(),
                    "take_profit_1": df_5m["close"].iloc[-1] * 1.015,
                    "take_profit_2": df_5m["close"].iloc[-1] * 1.03,
                }
                if pivot_calculator:
                    signal_info = await _enhance_signal_with_pivots(
                        signal_info, symbol, df_5m["close"].iloc[-1], pivot_calculator, data_collector
                    )
                return True, signal_info
            
            # Вариант 3: Консервативный (все ТФ вверх + 5m из OS)
            if trend_15m == 1 and trend_5m == 1 and zone_5m == "OS":
                signal_info = {
                    "symbol": symbol,
                    "type": "TREND_LONG",
                    "pattern": "Консервативный",
                    "trend_4h": "UP",
                    "trend_1h": "UP",
                    "trend_15m": "UP",
                    "trend_5m": "UP",
                    "wt_15m": f"{wt1_15m:.1f}/{wt2_15m:.1f}",
                    "zone_15m": zone_15m,
                    "zone_5m": zone_5m,
                    "confidence": "VERY_HIGH",
                    "entry_price": df_5m["close"].iloc[-1],
                    "stop_loss": df_5m["low"].iloc[-10:].min(),
                    "take_profit_1": df_5m["close"].iloc[-1] * 1.025,
                    "take_profit_2": df_5m["close"].iloc[-1] * 1.05,
                }
                if pivot_calculator:
                    signal_info = await _enhance_signal_with_pivots(
                        signal_info, symbol, df_5m["close"].iloc[-1], pivot_calculator, data_collector
                    )
                return True, signal_info
        
        # === SHORT SETUP (Тренд вниз) ===
        elif trend_4h == -1 and trend_1h == -1:
            # Вариант 1: Классический откат
            if zone_15m == "OB" and cross_down_15m and trend_5m == -1:
                signal_info = {
                    "symbol": symbol,
                    "type": "TREND_SHORT",
                    "pattern": "Классический откат",
                    "trend_4h": "DOWN",
                    "trend_1h": "DOWN",
                    "trend_15m": "DOWN" if trend_15m == -1 else "UP",
                    "trend_5m": "DOWN",
                    "wt_15m": f"{wt1_15m:.1f}/{wt2_15m:.1f}",
                    "zone_15m": zone_15m,
                    "zone_5m": zone_5m,
                    "confidence": "HIGH",
                    "entry_price": df_5m["close"].iloc[-1],
                    "stop_loss": df_15m["high"].iloc[-5:].max(),
                    "take_profit_1": df_5m["close"].iloc[-1] * 0.98,
                    "take_profit_2": df_5m["close"].iloc[-1] * 0.96,
                }
                if pivot_calculator:
                    signal_info = await _enhance_signal_with_pivots(
                        signal_info, symbol, df_5m["close"].iloc[-1], pivot_calculator, data_collector
                    )
                return True, signal_info
            
            # Вариант 2: Агрессивный вход
            if zone_1h == "OB" and trend_15m == -1 and trend_5m == -1 and zone_5m != "OS":
                signal_info = {
                    "symbol": symbol,
                    "type": "TREND_SHORT",
                    "pattern": "Агрессивный вход",
                    "trend_4h": "DOWN",
                    "trend_1h": "DOWN",
                    "trend_15m": "DOWN",
                    "trend_5m": "DOWN",
                    "wt_15m": f"{wt1_15m:.1f}/{wt2_15m:.1f}",
                    "zone_15m": zone_15m,
                    "zone_5m": zone_5m,
                    "confidence": "MEDIUM",
                    "entry_price": df_5m["close"].iloc[-1],
                    "stop_loss": df_15m["high"].iloc[-5:].max(),
                    "take_profit_1": df_5m["close"].iloc[-1] * 0.985,
                    "take_profit_2": df_5m["close"].iloc[-1] * 0.97,
                }
                if pivot_calculator:
                    signal_info = await _enhance_signal_with_pivots(
                        signal_info, symbol, df_5m["close"].iloc[-1], pivot_calculator, data_collector
                    )
                return True, signal_info
            
            # Вариант 3: Консервативный
            if trend_15m == -1 and trend_5m == -1 and zone_5m == "OB":
                signal_info = {
                    "symbol": symbol,
                    "type": "TREND_SHORT",
                    "pattern": "Консервативный",
                    "trend_4h": "DOWN",
                    "trend_1h": "DOWN",
                    "trend_15m": "DOWN",
                    "trend_5m": "DOWN",
                    "wt_15m": f"{wt1_15m:.1f}/{wt2_15m:.1f}",
                    "zone_15m": zone_15m,
                    "zone_5m": zone_5m,
                    "confidence": "VERY_HIGH",
                    "entry_price": df_5m["close"].iloc[-1],
                    "stop_loss": df_5m["high"].iloc[-10:].max(),
                    "take_profit_1": df_5m["close"].iloc[-1] * 0.975,
                    "take_profit_2": df_5m["close"].iloc[-1] * 0.95,
                }
                if pivot_calculator:
                    signal_info = await _enhance_signal_with_pivots(
                        signal_info, symbol, df_5m["close"].iloc[-1], pivot_calculator, data_collector
                    )
                return True, signal_info
        
        return False, None
        
    except Exception:
        logger.exception(f"Ошибка check_trend_following_signal для {symbol}")
        return False, None


async def _enhance_signal_with_pivots(signal_info: dict, symbol: str, current_price: float, 
                                     pivot_calculator, data_collector) -> dict:
    """
    Усиливает тренд-сигнал информацией о пивотных уровнях
    
    Args:
        signal_info: информация о сигнале
        symbol: торговая пара
        current_price: текущая цена
        pivot_calculator: калькулятор пивотов
        data_collector: коллектор данных
    
    Returns:
        Обновленный словарь с информацией о сигнале
    """
    if not pivot_calculator:
        return signal_info
    
    try:
        # Получаем пивоты
        pivots_data = await pivot_calculator.get_multi_timeframe_pivots(symbol, data_collector)
        
        if not pivots_data or '1W' not in pivots_data:
            return signal_info
        
        weekly_pivots = pivots_data['1W']
        
        # Проверяем близость к уровню (1% порог)
        near_level = pivot_calculator.is_near_level(current_price, weekly_pivots, threshold_percent=1.0)
        
        if near_level:
            signal_info['pivot_level'] = near_level['level']
            signal_info['pivot_type'] = near_level['level_type']
            signal_info['pivot_distance'] = near_level['distance_percent']
            signal_info['pivot_price'] = near_level['price']
            
            # Усиливаем уверенность, если цена у пивотного уровня
            if signal_info.get('confidence') == 'HIGH':
                signal_info['confidence'] = 'VERY_HIGH'
            elif signal_info.get('confidence') == 'MEDIUM':
                signal_info['confidence'] = 'HIGH'
            
            # Добавляем информацию о пивоте в сообщение
            signal_info['pivot_info'] = f"Цена у {near_level['level']} ({near_level['level_type']})"
        
        # Проверяем конфлюэнции
        if 'confluence' in pivots_data and pivots_data['confluence']:
            signal_info['has_confluence'] = True
            signal_info['confluence_count'] = len(pivots_data['confluence'])
            if signal_info.get('confidence') != 'VERY_HIGH':
                signal_info['confidence'] = 'VERY_HIGH'
        
    except Exception:
        # Игнорируем ошибки при проверке пивотов - это не критично
        pass
    
    return signal_info


def trend_signal_message(symbol: str, info: dict) -> str:
    """
    Форматирует сообщение о тренд-сигнале с красивым оформлением
    """
    from core.ui.message_builder import tv_link
    from datetime import datetime
    
    is_long = "LONG" in info.get("type", "")
    emoji = "🟢" if is_long else "🔴"
    
    # Эмодзи для уровня уверенности
    confidence = info.get("confidence", "MEDIUM")
    if confidence == "VERY_HIGH":
        conf_emoji = "🔥🔥🔥"
        conf_text = "Очень высокая"
    elif confidence == "HIGH":
        conf_emoji = "🔥🔥"
        conf_text = "Высокая"
    elif confidence == "MEDIUM":
        conf_emoji = "🔥"
        conf_text = "Средняя"
    else:
        conf_emoji = "⚠️"
        conf_text = "Низкая"
    
    parts = [
        f"{emoji} <b>ТРЕНД-СИГНАЛ</b> {emoji}",
        f"Пара: {tv_link(symbol, interval=5)}",
        f"Тип: <b>{info.get('type')}</b>",
        f"Паттерн: {info.get('pattern')}",
        "",
        f"{conf_emoji} <b>Уверенность:</b> {conf_text}",
    ]
    
    # НОВОЕ: Показываем информацию о дивергенции
    divergence = info.get("divergence")
    if divergence:
        div_type = divergence.get("type", "")
        div_strength = divergence.get("strength", 0)
        
        if div_strength >= 70:
            div_emoji = "💎"
        elif div_strength >= 50:
            div_emoji = "⭐"
        else:
            div_emoji = "✨"
        
        parts.append("")
        parts.append(f"{div_emoji} <b>ОБНАРУЖЕНА ДИВЕРГЕНЦИЯ!</b>")
        parts.append(f"Тип: {divergence.get('description', 'N/A')}")
        parts.append(f"Сила: {div_strength}/100")
        parts.append("➡️ Сигнал усилен дивергенцией!")
    
    parts.extend([
        "",
        "<b>📊 Анализ таймфреймов:</b>",
        f"4h:  📈 {info.get('trend_4h')}",
        f"1h:  📈 {info.get('trend_1h')} | Zone: {info.get('zone_1h', 'N/A')}",
        f"15m: 📈 {info.get('trend_15m')} | WT: {info.get('wt_15m')} | Zone: {info.get('zone_15m')}",
        f"5m:  📈 {info.get('trend_5m')} | Zone: {info.get('zone_5m')}",
        "",
        "<b>🎯 Торговый план:</b>"
    ])
    
    entry = info.get("entry_price", 0)
    sl = info.get("stop_loss", 0)
    tp1 = info.get("take_profit_1", 0)
    tp2 = info.get("take_profit_2", 0)
    
    if entry and entry > 0:
        parts.append(f"📍 Вход: {entry:.6f}")
    
    if sl and sl > 0:
        risk_percent = abs((entry - sl) / entry * 100) if entry else 0
        parts.append(f"🛡️ Стоп: {sl:.6f} ({risk_percent:.2f}%)")
    
    if tp1 and tp1 > 0:
        profit1 = abs((tp1 - entry) / entry * 100) if entry else 0
        parts.append(f"🎯 TP1: {tp1:.6f} (+{profit1:.2f}%)")
    
    if tp2 and tp2 > 0:
        profit2 = abs((tp2 - entry) / entry * 100) if entry else 0
        parts.append(f"🎯 TP2: {tp2:.6f} (+{profit2:.2f}%)")
    
    # R:R расчет
    if entry and sl and tp2:
        risk = abs(entry - sl)
        reward = abs(tp2 - entry)
        rr_ratio = reward / risk if risk > 0 else 0
        parts.append(f"⚖️ R:R = 1:{rr_ratio:.2f}")
    
    parts.append("")
    parts.append("<b>💡 Рекомендации:</b>")
    
    # Рекомендации с учетом дивергенции
    if divergence and divergence.get("strength", 0) >= 70:
        parts.append("  • 💎 СИЛЬНАЯ ДИВЕРГЕНЦИЯ - отличная точка входа!")
        parts.append("  • Можно использовать увеличенный объем")
        parts.append("  • Высокая вероятность отработки")
    elif confidence == "VERY_HIGH":
        parts.append("  • Сильный сигнал - можно входить полным объемом")
        parts.append("  • Рекомендуется частичная фиксация на TP1")
        parts.append("  • Перенос стопа в безубыток после TP1")
    elif confidence == "HIGH":
        parts.append("  • Хороший сигнал - стандартный объем")
        parts.append("  • Зафиксировать 50% на TP1")
        parts.append("  • Остальное держать до TP2")
    else:
        parts.append("  • Умеренный сигнал - уменьшенный объем")
        parts.append("  • Строго следовать стоп-лоссу")
        parts.append("  • Фиксация на первых признаках разворота")
    
    parts.append("")
    parts.append(f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return "\n".join(parts)