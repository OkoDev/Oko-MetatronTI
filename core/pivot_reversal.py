import logging
from core.indicators import detect_fvg, calculate_trend, calculate_wt, get_zone, compute_atr

logger = logging.getLogger(__name__)


async def check_pivot_level_signal(symbol, data_collector, pivot_calculator):
    """
    Проверяет сигналы ОТ УРОВНЕЙ недельных пивотов.

    Стратегия:
    1. Цена рядом с недельным уровнем (S1, S2, R1, R2, PP) ± 0.5%
    2. WT кросс на 15m в нужном направлении
    3. Тренд на 15m соответствует направлению
    4. БОНУС: FVG на 3m для усиления confidence
    5. SL: ATR(14) × 1.5, зажат в [1%, 4%] от цены
    6. TP: следующие пивоты (R1→R2→R3 для LONG, S1→S2→S3 для SHORT)

    Данные 15m берутся из кеша (уже загружены scan_one) — нет лишних API-вызовов.

    Returns:
        (True/False, dict с деталями сигнала)
    """
    try:
        # === 1. Недельные пивоты ===
        try:
            pivots_data = await pivot_calculator.get_multi_timeframe_pivots(symbol, data_collector)
        except TypeError:
            pivots_data = await pivot_calculator.get_multi_timeframe_pivots(data_collector, symbol)

        if '1W' not in pivots_data:
            return False, None

        weekly_pivots = pivots_data['1W']
        confluence = pivots_data.get('confluence', [])

        # === 2. 15m данные из кеша (загружены scan_one — нет API-запроса) ===
        df_15m = await data_collector.get_ohlcv(symbol, "15m", limit=150)
        if df_15m is None or len(df_15m) < 30:
            return False, None

        # Текущая цена = последняя закрытая свеча 15m (не нужен 1m)
        current_price = float(df_15m['close'].iloc[-1])
        if current_price <= 0:
            return False, None

        # === 3. Близость к уровню ===
        near_level = pivot_calculator.is_near_level(
            current_price, weekly_pivots, threshold_percent=0.5
        )
        if not near_level:
            prev_weekly = pivots_data.get('1W_prev')
            if prev_weekly:
                near_level = pivot_calculator.is_near_level(
                    current_price, prev_weekly, threshold_percent=0.5
                )
                if near_level:
                    near_level["is_prev_period"] = True
        if not near_level:
            return False, None

        level_type = near_level['level_type']
        level_name = near_level['level']
        level_price = near_level['price']

        # === 4. WT + Trend из одного df_15m (не нужен 5m) ===
        df_15m = calculate_wt(df_15m)
        df_15m = calculate_trend(df_15m, atr_period=43, factor=1.0)

        wt1_curr = float(df_15m['wt1'].iloc[-1])
        wt2_curr = float(df_15m['wt2'].iloc[-1])
        wt1_prev = float(df_15m['wt1'].iloc[-2])
        wt2_prev = float(df_15m['wt2'].iloc[-2])
        zone_15m = get_zone(wt1_curr)

        cross_up   = (wt1_prev < wt2_prev) and (wt1_curr > wt2_curr)
        cross_down = (wt1_prev > wt2_prev) and (wt1_curr < wt2_curr)

        trend_15m      = int(df_15m['trend'].iloc[-1])
        trend_15m_prev = int(df_15m['trend'].iloc[-2])
        trend_changed  = (trend_15m != trend_15m_prev)

        # === 5. ATR из 15m → SL (вместо локального min/max 3m) ===
        try:
            atr_series = compute_atr(df_15m, period=14)
            atr_val = float(atr_series.iloc[-1]) if atr_series is not None and len(atr_series) > 0 else None
        except Exception:
            atr_val = None

        if atr_val and atr_val > 0:
            sl_dist = max(
                min(atr_val * 1.5, current_price * 0.04),  # max 4%
                current_price * 0.01,                       # min 1%
            )
        else:
            sl_dist = current_price * 0.02  # 2% fallback

        # === 6. FVG на 3m — только бонус, не блокирует ===
        df_3m = await data_collector.get_ohlcv(symbol, "3m", limit=20)
        fvg_type = None
        fvg_entry = None
        has_fvg = False
        if df_3m is not None and len(df_3m) >= 3:
            try:
                fvg_type, fvg_entry = detect_fvg(df_3m)
                has_fvg = fvg_type is not None
            except Exception:
                pass

        # === Вспомогательные функции ===
        def _strength(wt_ok, trend_changed, has_fvg, fvg_ok, has_confluence):
            s = 60
            if wt_ok:                  s += 10
            if trend_changed:          s += 10
            if has_fvg and fvg_ok:     s += 10
            if has_confluence:         s += 10
            return min(s, 100)

        def _build_result(type_str, direction_label, wt_label, trend_label,
                          stop_loss, tp_levels, has_confluence):
            fvg_ok = (fvg_type == ("BULL" if "LONG" in type_str else "BEAR")) if has_fvg else True
            wt_ok = cross_up if "LONG" in type_str else cross_down
            tp_distance = abs(tp_levels[0]['price'] - current_price) if tp_levels else 0
            rr_ratio = tp_distance / sl_dist if sl_dist > 0 else 0
            strength = _strength(wt_ok, trend_changed, has_fvg, fvg_ok, has_confluence)
            return {
                'symbol': symbol,
                'type': type_str,
                'strategy': f'Вход от недельного {level_name}',
                'level': level_name,
                'level_type': level_type,
                'level_price': level_price,
                'current_price': current_price,
                'distance_to_level': near_level['distance_percent'],
                'wt_signal': f"WT кросс {direction_label} на 15m (WT1={wt1_curr:.1f})",
                'wt_zone': zone_15m,
                'trend_15m': trend_label,
                'trend_changed': trend_changed,
                'has_fvg': has_fvg and fvg_ok,
                'fvg_type': fvg_type,
                'fvg_entry': fvg_entry,
                'has_confluence': has_confluence,
                'confluence_info': [c for c in confluence if c['weekly_level'] == level_name],
                'entry_price': current_price,
                'stop_loss': stop_loss,
                'stop_distance_pct': sl_dist / current_price * 100,
                'atr': atr_val,
                'sl_source': 'atr_14',
                'take_profits': tp_levels,
                'rr_ratio': rr_ratio,
                'strength': strength,
                'confidence': 'VERY_HIGH' if (has_confluence and has_fvg and fvg_ok) else 'HIGH',
                'weekly_pivots': weekly_pivots,
            }

        # === LONG: у поддержки ===
        if level_type in ['support', 'pivot']:
            wt_ok   = cross_up and zone_15m in ['OS', 'N']
            trend_ok = (trend_15m == 1)

            if wt_ok and trend_ok:
                target_levels = ['PP', 'R1', 'R2', 'R3'] if 'S' in level_name else ['R1', 'R2', 'R3']
                tp_levels = [
                    {'level': t, 'price': weekly_pivots[t],
                     'profit_percent': (weekly_pivots[t] - current_price) / current_price * 100,
                     'timeframe': '1W'}
                    for t in target_levels
                    if t in weekly_pivots and weekly_pivots[t] > current_price
                ]
                has_confluence = any(c['weekly_level'] == level_name for c in confluence)
                return True, _build_result(
                    'PIVOT_LEVEL_LONG', 'вверх', 'UP', 'вверх',
                    current_price - sl_dist, tp_levels, has_confluence
                )

        # === SHORT: у сопротивления ===
        elif level_type in ['resistance', 'pivot']:
            wt_ok   = cross_down and zone_15m in ['OB', 'N']
            trend_ok = (trend_15m == -1)

            if wt_ok and trend_ok:
                target_levels = ['PP', 'S1', 'S2', 'S3'] if 'R' in level_name else ['S1', 'S2', 'S3']
                tp_levels = [
                    {'level': t, 'price': weekly_pivots[t],
                     'profit_percent': (current_price - weekly_pivots[t]) / current_price * 100,
                     'timeframe': '1W'}
                    for t in target_levels
                    if t in weekly_pivots and weekly_pivots[t] < current_price
                ]
                has_confluence = any(c['weekly_level'] == level_name for c in confluence)
                return True, _build_result(
                    'PIVOT_LEVEL_SHORT', 'вниз', 'DOWN', 'вниз',
                    current_price + sl_dist, tp_levels, has_confluence
                )

        return False, None

    except Exception:
        logger.exception("Ошибка check_pivot_level_signal для %s", symbol)
        return False, None


def pivot_level_signal_message(symbol: str, info: dict) -> str:
    """Форматирует сообщение о входе от уровня."""
    from core.message_builder import tv_link
    from datetime import datetime

    is_long = "LONG" in info.get("type", "")
    emoji = "🟢" if is_long else "🔴"

    confidence = info.get("confidence", "HIGH")
    conf_emoji = "🔥🔥🔥" if confidence == "VERY_HIGH" else "🔥🔥"
    strength = info.get("strength", 65)

    parts = [
        f"{emoji} <b>ВХОД ОТ НЕДЕЛЬНОГО УРОВНЯ</b> {emoji}",
        f"Пара: {tv_link(symbol, interval=3)}",
        f"Стратегия: <b>{info.get('strategy')}</b>",
        "",
        f"{conf_emoji} <b>Сила:</b> {strength}/100  <b>Уверенность:</b> {confidence}",
    ]

    level = info.get('level')
    level_price = info.get('level_price', 0)
    distance = info.get('distance_to_level', 0)

    parts.append("")
    parts.append(f"📊 <b>Уровень: {level}</b>")
    parts.append(f"Цена уровня: {level_price:.6f}")
    parts.append(f"Расстояние: {distance:.3f}%")

    parts.append("")
    parts.append("<b>✅ Подтверждения:</b>")
    parts.append(f"  • {info.get('wt_signal')} [{info.get('wt_zone')}]")

    trend_15m = info.get('trend_15m', '')
    if info.get('trend_changed'):
        parts.append(f"  • Разворот тренда 15m → {trend_15m}")
    else:
        parts.append(f"  • Тренд 15m: {trend_15m}")

    if info.get('has_fvg'):
        parts.append(f"  • 💎 FVG {info.get('fvg_type')} на 3m!")
        if info.get('fvg_entry'):
            parts.append(f"    Entry: {info.get('fvg_entry'):.6f}")

    if info.get('has_confluence'):
        conf = info.get('confluence_info', [])
        if conf:
            c = conf[0]
            parts.append(f"  • ⭐ КОНФЛЮЭНЦИЯ: 1W {c['weekly_level']} ≈ 1D {c['daily_level']}")

    parts.append("")
    parts.append("<b>🎯 Торговый план:</b>")

    entry = info.get('entry_price', 0)
    sl = info.get('stop_loss', 0)
    stop_pct = info.get('stop_distance_pct', 0)
    tp_levels = info.get('take_profits', [])
    rr = info.get('rr_ratio', 0)
    atr = info.get('atr')

    parts.append(f"📍 Вход: {entry:.6f}")
    atr_str = f"  ATR×1.5={atr * 1.5:.6f}" if atr else ""
    parts.append(f"🛡️ Стоп: {sl:.6f} ({stop_pct:.2f}%) [ATR×1.5]{atr_str}")

    for i, tp in enumerate(tp_levels[:3], 1):
        parts.append(f"🎯 TP{i}: {tp['price']:.6f} (+{tp['profit_percent']:.2f}%) [1W {tp['level']}]")

    if rr > 0:
        parts.append(f"⚖️ R:R = 1:{rr:.1f} {'🔥🔥🔥' if rr >= 5 else '🔥🔥' if rr >= 3 else '🔥'}")

    parts.append("")
    parts.append("<b>💡 Рекомендации:</b>")

    if confidence == "VERY_HIGH" and rr >= 5:
        parts.append("  • 🔥🔥🔥 ОТЛИЧНЫЙ SETUP!")
        parts.append("  • Уровень + WT + тренд + FVG + конфлюэнция")
        parts.append("  • R:R превосходный!")
    elif rr >= 3:
        parts.append("  • 🔥 Хороший setup от недельного уровня")
        parts.append("  • ATR-стоп, отличный R:R")
    else:
        parts.append("  • Сигнал от уровня")
        parts.append("  • Стандартный риск-менеджмент")

    parts.append("  • Частичная фиксация: 33%/33%/34%")
    parts.append("  • Стоп в безубыток после TP1")

    parts.append("")
    parts.append(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return "\n".join(parts)
