import logging
from core.indicators import detect_fvg, calculate_trend, calculate_wt, get_zone
from core.pivot_levels import PivotLevels

logger = logging.getLogger(__name__)


async def check_pivot_level_signal(symbol, data_collector, pivot_calculator):
    """
    Проверяет сигналы ОТ УРОВНЕЙ недельных пивотов
    
    ПРАВИЛЬНАЯ СТРАТЕГИЯ:
    1. Цена рядом с недельным уровнем (S1, S2, R1, R2, PP)
    2. WT сигнал на 15m (кросс в нужном направлении)
    3. Смена тренда на младших ТФ (5m, 3m)
    4. БОНУС: FVG на 3m для усиления
    5. Стоп: ТАЙТОВЫЙ за локальный минимум/максимум
    6. TP: Следующие пивоты (R1→R2→R3 или S1→S2→S3)
    
    Пример LONG:
    - Цена у S1 (43,100)
    - WT кросс вверх на 15m + зона OS
    - Тренд 5m развернулся UP
    - FVG BULL на 3m (жирный плюс!)
    - Стоп: 43,080 (за локальный минимум) - всего 20 пунктов!
    - TP1: PP (43,250) = +150 пунктов
    - TP2: R1 (43,400) = +300 пунктов
    - R:R = 1:15 🔥🔥🔥
    
    Returns:
        (True/False, dict с деталями сигнала)
    """
    try:
        # === 1. Получаем недельные пивоты ===
        # Используем правильный порядок аргументов: (symbol, data_collector) для PivotCalculatorFixed
        # Если это старый PivotLevels, порядок будет (data_collector, symbol)
        try:
            # Пробуем новый порядок (PivotCalculatorFixed)
            pivots_data = await pivot_calculator.get_multi_timeframe_pivots(symbol, data_collector)
        except TypeError:
            # Если не подошел, пробуем старый порядок (PivotLevels)
            pivots_data = await pivot_calculator.get_multi_timeframe_pivots(data_collector, symbol)
        
        if '1W' not in pivots_data:
            return False, None
        
        weekly_pivots = pivots_data['1W']
        daily_pivots = pivots_data.get('1D')
        confluence = pivots_data.get('confluence', [])
        
        # === 2. Получаем текущую цену ===
        df_1m = await data_collector.get_ohlcv(symbol, "1m", limit=2)
        if df_1m is None or len(df_1m) < 1:
            return False, None
        
        current_price = df_1m['close'].iloc[-1]
        
        # === 3. Проверяем близость к недельному уровню (0.5%) ===
        near_level = pivot_calculator.is_near_level(
            current_price, weekly_pivots, threshold_percent=0.5
        )
        
        if not near_level:
            return False, None  # Цена не у уровня - выходим
        
        level_type = near_level['level_type']  # 'support', 'resistance', 'pivot'
        level_name = near_level['level']  # 'S1', 'R1', 'PP' и т.д.
        level_price = near_level['price']
        
        # === 4. Проверяем WT сигнал на 15m ===
        df_15m = await data_collector.get_ohlcv(symbol, "15m", limit=150)
        if df_15m is None or len(df_15m) < 3:
            return False, None
        
        df_15m = calculate_wt(df_15m)
        
        wt1_curr = df_15m['wt1'].iloc[-1]
        wt2_curr = df_15m['wt2'].iloc[-1]
        wt1_prev = df_15m['wt1'].iloc[-2]
        wt2_prev = df_15m['wt2'].iloc[-2]
        
        zone_15m = get_zone(wt1_curr)
        
        # Проверяем кроссы WT
        cross_up = (wt1_prev < wt2_prev) and (wt1_curr > wt2_curr)
        cross_down = (wt1_prev > wt2_prev) and (wt1_curr < wt2_curr)
        
        # === 5. Проверяем тренд на 5m ===
        df_5m = await data_collector.get_ohlcv(symbol, "5m", limit=150)
        if df_5m is None or len(df_5m) < 3:
            return False, None
        
        df_5m = calculate_trend(df_5m, atr_period=43, factor=1.0)
        trend_5m = df_5m['trend'].iloc[-1]
        trend_5m_prev = df_5m['trend'].iloc[-2]
        
        # Смена тренда?
        trend_changed = trend_5m != trend_5m_prev
        
        # === 6. Проверяем FVG на 3m (БОНУС) ===
        df_3m = await data_collector.get_ohlcv(symbol, "3m", limit=20)
        fvg_type = None
        fvg_entry = None
        has_fvg = False
        
        if df_3m is not None and len(df_3m) >= 3:
            fvg_type, fvg_entry = detect_fvg(df_3m)
            has_fvg = fvg_type is not None
        
        # === 7. Рассчитываем локальный стоп (ТАЙТОВЫЙ) ===
        local_min = df_3m['low'].iloc[-10:].min() if df_3m is not None else current_price * 0.998
        local_max = df_3m['high'].iloc[-10:].max() if df_3m is not None else current_price * 1.002
        
        # === СЦЕНАРИЙ LONG: у поддержки ===
        if level_type in ['support', 'pivot']:
            # Нужны условия:
            # 1. WT кросс вверх в зоне OS (или около)
            # 2. Тренд 5m = UP (или только что развернулся)
            # 3. БОНУС: FVG BULL
            
            wt_ok = cross_up and zone_15m in ['OS', 'N']
            trend_ok = trend_5m == 1
            fvg_ok = fvg_type == "BULL" if has_fvg else True  # Если нет FVG, не блокируем
            
            if wt_ok and trend_ok:
                # Определяем целевые уровни
                tp_levels = []
                
                # Если у S1/S2/S3 - цели PP, R1, R2, R3
                # Если у PP - цели R1, R2, R3
                target_levels = ['PP', 'R1', 'R2', 'R3'] if 'S' in level_name else ['R1', 'R2', 'R3']
                
                for tgt in target_levels:
                    if tgt in weekly_pivots and weekly_pivots[tgt] > current_price:
                        profit_pct = ((weekly_pivots[tgt] - current_price) / current_price) * 100
                        tp_levels.append({
                            'level': tgt,
                            'price': weekly_pivots[tgt],
                            'profit_percent': profit_pct,
                            'timeframe': '1W'
                        })
                
                # Проверяем конфлюэнцию
                has_confluence = any(c['weekly_level'] == level_name for c in confluence)
                
                # Рассчитываем R:R
                stop_distance = abs(current_price - local_min)
                tp_distance = abs(tp_levels[0]['price'] - current_price) if tp_levels else 0
                rr_ratio = tp_distance / stop_distance if stop_distance > 0 else 0
                
                return True, {
                    'symbol': symbol,
                    'type': 'PIVOT_LEVEL_LONG',
                    'strategy': f'Вход от недельного {level_name}',
                    'level': level_name,
                    'level_type': level_type,
                    'level_price': level_price,
                    'current_price': current_price,
                    'distance_to_level': near_level['distance_percent'],
                    
                    # Сигналы
                    'wt_signal': f"WT кросс вверх на 15m (WT1={wt1_curr:.1f})",
                    'wt_zone': zone_15m,
                    'trend_5m': 'UP',
                    'trend_changed': trend_changed,
                    
                    # FVG
                    'has_fvg': has_fvg and fvg_ok,
                    'fvg_type': fvg_type,
                    'fvg_entry': fvg_entry,
                    
                    # Конфлюэнция
                    'has_confluence': has_confluence,
                    'confluence_info': [c for c in confluence if c['weekly_level'] == level_name],
                    
                    # Торговый план
                    'entry_price': current_price,
                    'stop_loss': local_min,
                    'stop_distance_pct': (stop_distance / current_price) * 100,
                    'take_profits': tp_levels,
                    'rr_ratio': rr_ratio,
                    
                    # Уверенность
                    'confidence': 'VERY_HIGH' if (has_confluence and has_fvg and fvg_ok) else 'HIGH',
                    'weekly_pivots': weekly_pivots
                }
        
        # === СЦЕНАРИЙ SHORT: у сопротивления ===
        elif level_type in ['resistance', 'pivot']:
            # Нужны условия:
            # 1. WT кросс вниз в зоне OB (или около)
            # 2. Тренд 5m = DOWN (или только что развернулся)
            # 3. БОНУС: FVG BEAR
            
            wt_ok = cross_down and zone_15m in ['OB', 'N']
            trend_ok = trend_5m == -1
            fvg_ok = fvg_type == "BEAR" if has_fvg else True
            
            if wt_ok and trend_ok:
                # Определяем целевые уровни
                tp_levels = []
                
                # Если у R1/R2/R3 - цели PP, S1, S2, S3
                # Если у PP - цели S1, S2, S3
                target_levels = ['PP', 'S1', 'S2', 'S3'] if 'R' in level_name else ['S1', 'S2', 'S3']
                
                for tgt in target_levels:
                    if tgt in weekly_pivots and weekly_pivots[tgt] < current_price:
                        profit_pct = ((current_price - weekly_pivots[tgt]) / current_price) * 100
                        tp_levels.append({
                            'level': tgt,
                            'price': weekly_pivots[tgt],
                            'profit_percent': profit_pct,
                            'timeframe': '1W'
                        })
                
                has_confluence = any(c['weekly_level'] == level_name for c in confluence)
                
                stop_distance = abs(local_max - current_price)
                tp_distance = abs(current_price - tp_levels[0]['price']) if tp_levels else 0
                rr_ratio = tp_distance / stop_distance if stop_distance > 0 else 0
                
                return True, {
                    'symbol': symbol,
                    'type': 'PIVOT_LEVEL_SHORT',
                    'strategy': f'Вход от недельного {level_name}',
                    'level': level_name,
                    'level_type': level_type,
                    'level_price': level_price,
                    'current_price': current_price,
                    'distance_to_level': near_level['distance_percent'],
                    
                    # Сигналы
                    'wt_signal': f"WT кросс вниз на 15m (WT1={wt1_curr:.1f})",
                    'wt_zone': zone_15m,
                    'trend_5m': 'DOWN',
                    'trend_changed': trend_changed,
                    
                    # FVG
                    'has_fvg': has_fvg and fvg_ok,
                    'fvg_type': fvg_type,
                    'fvg_entry': fvg_entry,
                    
                    # Конфлюэнция
                    'has_confluence': has_confluence,
                    'confluence_info': [c for c in confluence if c['weekly_level'] == level_name],
                    
                    # Торговый план
                    'entry_price': current_price,
                    'stop_loss': local_max,
                    'stop_distance_pct': (stop_distance / current_price) * 100,
                    'take_profits': tp_levels,
                    'rr_ratio': rr_ratio,
                    
                    # Уверенность
                    'confidence': 'VERY_HIGH' if (has_confluence and has_fvg and fvg_ok) else 'HIGH',
                    'weekly_pivots': weekly_pivots
                }
        
        return False, None
        
    except Exception:
        logger.exception(f"Ошибка check_pivot_level_signal для {symbol}")
        return False, None


def pivot_level_signal_message(symbol: str, info: dict) -> str:
    """Форматирует сообщение о входе от уровня"""
    from core.message_builder import tv_link
    from datetime import datetime
    
    is_long = "LONG" in info.get("type", "")
    emoji = "🟢" if is_long else "🔴"
    
    confidence = info.get("confidence", "HIGH")
    conf_emoji = "🔥🔥🔥" if confidence == "VERY_HIGH" else "🔥🔥"
    
    parts = [
        f"{emoji} <b>ВХОД ОТ НЕДЕЛЬНОГО УРОВНЯ</b> {emoji}",
        f"Пара: {tv_link(symbol, interval=3)}",
        f"Стратегия: <b>{info.get('strategy')}</b>",
        "",
        f"{conf_emoji} <b>Уверенность:</b> {confidence}",
    ]
    
    # Информация об уровне
    level = info.get('level')
    level_price = info.get('level_price', 0)
    distance = info.get('distance_to_level', 0)
    
    parts.append("")
    parts.append(f"📊 <b>Уровень: {level}</b>")
    parts.append(f"Цена уровня: {level_price:.6f}")
    parts.append(f"Расстояние: {distance:.3f}%")
    
    # Сигналы
    parts.append("")
    parts.append("<b>✅ Подтверждения:</b>")
    parts.append(f"  • {info.get('wt_signal')} [{info.get('wt_zone')}]")
    
    if info.get('trend_changed'):
        parts.append(f"  • Разворот тренда 5m → {info.get('trend_5m')}")
    else:
        parts.append(f"  • Тренд 5m: {info.get('trend_5m')}")
    
    # FVG
    if info.get('has_fvg'):
        parts.append(f"  • 💎 FVG {info.get('fvg_type')} на 3m!")
        if info.get('fvg_entry'):
            parts.append(f"    Entry: {info.get('fvg_entry'):.6f}")
    
    # Конфлюэнция
    if info.get('has_confluence'):
        conf = info.get('confluence_info', [])
        if conf:
            c = conf[0]
            parts.append(f"  • ⭐ КОНФЛЮЭНЦИЯ: 1W {c['weekly_level']} ≈ 1D {c['daily_level']}")
    
    # Торговый план
    parts.append("")
    parts.append("<b>🎯 Торговый план:</b>")
    
    entry = info.get('entry_price', 0)
    sl = info.get('stop_loss', 0)
    stop_pct = info.get('stop_distance_pct', 0)
    tp_levels = info.get('take_profits', [])
    rr = info.get('rr_ratio', 0)
    
    parts.append(f"📍 Вход: {entry:.6f}")
    parts.append(f"🛡️ Стоп: {sl:.6f} ({stop_pct:.2f}%) [Локальный мин/макс]")
    
    for i, tp in enumerate(tp_levels[:3], 1):
        parts.append(f"🎯 TP{i}: {tp['price']:.6f} (+{tp['profit_percent']:.2f}%) [1W {tp['level']}]")
    
    if rr > 0:
        parts.append(f"⚖️ R:R = 1:{rr:.1f} {'🔥🔥🔥' if rr >= 5 else '🔥🔥' if rr >= 3 else '🔥'}")
    
    # Рекомендации
    parts.append("")
    parts.append("<b>💡 Рекомендации:</b>")
    
    if confidence == "VERY_HIGH" and rr >= 5:
        parts.append("  • 🔥🔥🔥 ОТЛИЧНЫЙ SETUP!")
        parts.append("  • Уровень + WT + тренд + FVG + конфлюэнция")
        parts.append("  • R:R превосходный!")
        parts.append("  • Увеличенный объем позиции")
    elif rr >= 3:
        parts.append("  • 🔥 Хороший setup от недельного уровня")
        parts.append("  • Тайтовый стоп, отличный R:R")
        parts.append("  • Стандартный объем")
    else:
        parts.append("  • Сигнал от уровня")
        parts.append("  • Стандартный риск-менеджмент")
    
    parts.append("  • Частичная фиксация: 33%/33%/34%")
    parts.append("  • Стоп в безубыток после TP1")
    
    parts.append("")
    parts.append(f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return "\n".join(parts)