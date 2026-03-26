import logging
from core.indicators import calculate_wt, get_zone
from core.message_builder import tv_link  # Добавили импорт

logger = logging.getLogger(__name__)

async def collect_mtf_data(symbol, data_collector, timeframes=None):
    """
    Собирает Trend, WT и Zone по нескольким ТФ.
    Возвращает dict вида {tf: {trend, wt1, wt2, zone}}
    """
    if timeframes is None:
        timeframes = ["3m", "5m", "15m", "1h", "4h", "1d"]  # ARCH-18: убран нестандартный 45m

    results = {}
    for tf in timeframes:
        try:
            df = await data_collector.get_ohlcv(symbol, tf, 150)
            if df is None or df.empty:
                continue

            wt_df = calculate_wt(df.copy())
            wt1, wt2 = wt_df["wt1"].iloc[-1], wt_df["wt2"].iloc[-1]

            # WT momentum: wt1 > wt2 = бычий импульс, иначе медвежий.
            # Заменяет ATR trailing stop — для MTF alignment нужен моментум, не TSL.
            trend = "UP" if wt1 > wt2 else "DOWN"

            zone = get_zone(wt1)

            # WT cross на последних двух закрытых барах (-2 и -1)
            wt_cross = 0
            if len(wt_df) >= 2:
                p_wt1, p_wt2 = wt_df["wt1"].iloc[-2], wt_df["wt2"].iloc[-2]
                if p_wt1 <= p_wt2 and wt1 > wt2:
                    wt_cross = 1   # кросс UP
                elif p_wt1 >= p_wt2 and wt1 < wt2:
                    wt_cross = -1  # кросс DOWN

            results[tf] = {
                "trend": trend,
                "wt1": round(wt1, 2),
                "wt2": round(wt2, 2),
                "zone": zone,
                "wt_cross": wt_cross,
            }
        except Exception:
            logger.exception(f"Ошибка MTF для {symbol} {tf}")

    return results


def check_mtf_alert(snapshot: dict) -> tuple[bool, str]:
    """
    Примеры правил алертов для точек разворота.
    Возвращает (True, "LONG"/"SHORT") или (False, None).
    """
    try:
        # === LONG SETUP ===
        # Пример 1: 1h/45m/15m в OS и 5m тренд UP (классический разворот)
        if (
            snapshot.get("1h", {}).get("zone") == "OS" and
            snapshot.get("45m", {}).get("zone") == "OS" and
            snapshot.get("15m", {}).get("zone") == "OS" and
            snapshot.get("5m", {}).get("trend") == "UP"
        ):
            logger.debug("MTF alert LONG: классический разворот (1h/45m/15m OS + 5m UP)")
            return True, "LONG"

        # Пример 2: Агрессивный LONG - достаточно 2 ТФ в OS + разворот на 3m
        os_count = sum(1 for tf in ["1h", "45m", "15m", "5m"]
                       if snapshot.get(tf, {}).get("zone") == "OS")
        if os_count >= 2 and snapshot.get("3m", {}).get("trend") == "UP":
            logger.debug("MTF alert LONG: агрессивный (os_count=%d + 3m UP)", os_count)
            return True, "LONG"

        # === SHORT SETUP ===
        # Пример 1: Старшие тренды DOWN + младшие в OB
        if (
            snapshot.get("1h", {}).get("trend") == "DOWN" and
            snapshot.get("4h", {}).get("trend") == "DOWN" and
            snapshot.get("15m", {}).get("zone") == "OB" and
            snapshot.get("5m", {}).get("zone") == "OB"
        ):
            logger.debug("MTF alert SHORT: 4h+1h DOWN + 15m/5m OB")
            return True, "SHORT"

        # Пример 2: Агрессивный SHORT
        ob_count = sum(1 for tf in ["1h", "45m", "15m", "5m"]
                       if snapshot.get(tf, {}).get("zone") == "OB")
        if ob_count >= 2 and snapshot.get("3m", {}).get("trend") == "DOWN":
            logger.debug("MTF alert SHORT: агрессивный (ob_count=%d + 3m DOWN)", ob_count)
            return True, "SHORT"

        # === КОНСЕРВАТИВНЫЕ ВАРИАНТЫ ===
        # LONG: ВСЕ старшие в OS + ВСЕ младшие разворот вверх
        if (
            snapshot.get("4h", {}).get("zone") == "OS" and
            snapshot.get("1h", {}).get("zone") == "OS" and
            snapshot.get("45m", {}).get("zone") == "OS" and
            snapshot.get("15m", {}).get("zone") == "OS" and
            snapshot.get("5m", {}).get("trend") == "UP" and
            snapshot.get("3m", {}).get("trend") == "UP"
        ):
            logger.debug("MTF alert LONG: консервативный (все ТФ OS + 5m/3m UP)")
            return True, "LONG"

        # SHORT: аналогично
        if (
            snapshot.get("4h", {}).get("zone") == "OB" and
            snapshot.get("1h", {}).get("zone") == "OB" and
            snapshot.get("45m", {}).get("zone") == "OB" and
            snapshot.get("15m", {}).get("zone") == "OB" and
            snapshot.get("5m", {}).get("trend") == "DOWN" and
            snapshot.get("3m", {}).get("trend") == "DOWN"
        ):
            logger.debug("MTF alert SHORT: консервативный (все ТФ OB + 5m/3m DOWN)")
            return True, "SHORT"

        return False, None
        
    except Exception:
        logger.exception("check_mtf_alert error")
        return False, None


def mtf_alert_message(symbol: str, snapshot: dict, signal_type: str) -> str:
    """
    Форматирует красивое сообщение о MTF точке разворота с TradingView ссылкой
    """
    emoji = "🟢" if signal_type == "LONG" else "🔴"
    
    # Определяем интервал по младшему активному ТФ
    interval = 3 if "3m" in snapshot else 5
    
    # Оцениваем силу сигнала
    strength = analyze_mtf_strength(snapshot, signal_type)
    recommendations = get_entry_recommendations(snapshot, signal_type)
    
    # Эмодзи для силы сигнала
    if strength >= 80:
        strength_emoji = "🔥🔥🔥"
        strength_text = "Очень высокая"
    elif strength >= 60:
        strength_emoji = "🔥🔥"
        strength_text = "Высокая"
    elif strength >= 40:
        strength_emoji = "🔥"
        strength_text = "Средняя"
    else:
        strength_emoji = "⚠️"
        strength_text = "Низкая"
    
    # Эмодзи для уровня риска
    risk_level = recommendations["risk_level"]
    if risk_level == "Low":
        risk_emoji = "🟢"
        risk_text = "Низкий"
    elif risk_level == "Medium":
        risk_emoji = "🟡"
        risk_text = "Средний"
    else:
        risk_emoji = "🔴"
        risk_text = "Высокий"
    
    parts = [
        f"{emoji} <b>MTF ТОЧКА РАЗВОРОТА</b> {emoji}",
        f"Пара: {tv_link(symbol, interval=interval)}",
        f"Сигнал: <b>{signal_type}</b>",
        "",
        f"{strength_emoji} <b>Сила сигнала: {strength}/100</b> ({strength_text})",
        f"{risk_emoji} <b>Уровень риска:</b> {risk_text}",
        "",
        "<b>📊 Состояние по таймфреймам:</b>"
    ]
    
    # Сортируем таймфреймы от старших к младшим
    tf_order = ["1d", "4h", "1h", "45m", "15m", "5m", "3m"]
    sorted_tfs = [tf for tf in tf_order if tf in snapshot]
    
    for tf in sorted_tfs:
        vals = snapshot[tf]
        trend_emoji = "📈" if vals['trend'] == "UP" else "📉"
        zone_emoji = "🔴" if vals['zone'] == "OB" else "🟢" if vals['zone'] == "OS" else "⚪"
        
        parts.append(
            f"{tf:>4}: {trend_emoji} {vals['trend']:>4} | "
            f"WT({vals['wt1']:>6.1f}/{vals['wt2']:>6.1f}) | "
            f"{zone_emoji} {vals['zone']}"
        )
    
    # Добавляем рекомендации в зависимости от силы и риска
    parts.append("")
    parts.append("<b>💡 Торговые рекомендации:</b>")
    
    if signal_type == "LONG":
        parts.append("📈 <b>Вход в LONG:</b>")
        
        if strength >= 70:
            parts.append("  • Сильный сигнал - можно входить агрессивно")
            parts.append("  • Рассмотреть вход по рынку на 3m-5m")
        elif strength >= 50:
            parts.append("  • Средний сигнал - ждать подтверждения")
            parts.append("  • Вход после пробоя локального максимума")
        else:
            parts.append("  • Слабый сигнал - высокий риск")
            parts.append("  • Ждать дополнительного подтверждения")
        
        parts.append("  • 🛡️ Стоп: под последний минимум 5m/3m")
        parts.append("  • 🎯 Цель 1: ближайшее сопротивление")
        parts.append("  • 🎯 Цель 2: зона OB на 1h-4h")
        
    else:  # SHORT
        parts.append("📉 <b>Вход в SHORT:</b>")
        
        if strength >= 70:
            parts.append("  • Сильный сигнал - можно входить агрессивно")
            parts.append("  • Рассмотреть вход по рынку на 3m-5m")
        elif strength >= 50:
            parts.append("  • Средний сигнал - ждать подтверждения")
            parts.append("  • Вход после пробоя локального минимума")
        else:
            parts.append("  • Слабый сигнал - высокий риск")
            parts.append("  • Ждать дополнительного подтверждения")
        
        parts.append("  • 🛡️ Стоп: над последний максимум 5m/3m")
        parts.append("  • 🎯 Цель 1: ближайшая поддержка")
        parts.append("  • 🎯 Цель 2: зона OS на 1h-4h")
    
    # Добавляем общие советы
    parts.append("")
    parts.append("⚠️ <b>Управление рисками:</b>")
    if risk_level == "Low":
        parts.append("  • Можно использовать увеличенный объем")
        parts.append("  • Риск: 1-2% от депозита")
    elif risk_level == "Medium":
        parts.append("  • Стандартный объем позиции")
        parts.append("  • Риск: 0.5-1% от депозита")
    else:
        parts.append("  • Минимальный объем позиции")
        parts.append("  • Риск: не более 0.5% от депозита")
    
    return "\n".join(parts)


# === ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ АНАЛИЗА ===

def analyze_mtf_strength(snapshot: dict, signal_type: str) -> int:
    """
    Оценивает силу MTF сигнала от 0 до 100
    Чем больше совпадений условий - тем сильнее сигнал
    """
    score = 0
    max_score = 0
    
    if signal_type == "LONG":
        # 1. Зоны перепроданности (максимум 35 баллов)
        for tf, weight in [("4h", 10), ("1h", 8), ("45m", 7), ("15m", 6), ("5m", 4)]:
            max_score += weight
            if snapshot.get(tf, {}).get("zone") == "OS":
                score += weight
        
        # 2. Развороты трендов на младших ТФ (максимум 30 баллов)
        max_score += 15
        if snapshot.get("5m", {}).get("trend") == "UP":
            score += 15
        max_score += 15
        if snapshot.get("3m", {}).get("trend") == "UP":
            score += 15
        
        # 3. Старшие ТФ в DOWN (предпосылка разворота) (максимум 20 баллов)
        max_score += 10
        if snapshot.get("4h", {}).get("trend") == "DOWN":
            score += 10
        max_score += 10
        if snapshot.get("1h", {}).get("trend") == "DOWN":
            score += 10
        
        # 4. Глубина перепроданности по WT (бонус 15 баллов)
        max_score += 15
        wt_bonus = 0
        for tf in ["1h", "45m", "15m"]:
            wt1 = snapshot.get(tf, {}).get("wt1", 0)
            if wt1 < -70:  # Экстремальная перепроданность
                wt_bonus += 5
        score += min(wt_bonus, 15)
        
    elif signal_type == "SHORT":
        # 1. Зоны перекупленности (максимум 35 баллов)
        for tf, weight in [("4h", 10), ("1h", 8), ("45m", 7), ("15m", 6), ("5m", 4)]:
            max_score += weight
            if snapshot.get(tf, {}).get("zone") == "OB":
                score += weight
        
        # 2. Развороты трендов вниз (максимум 30 баллов)
        max_score += 15
        if snapshot.get("5m", {}).get("trend") == "DOWN":
            score += 15
        max_score += 15
        if snapshot.get("3m", {}).get("trend") == "DOWN":
            score += 15
        
        # 3. Старшие ТФ в UP (максимум 20 баллов)
        max_score += 10
        if snapshot.get("4h", {}).get("trend") == "UP":
            score += 10
        max_score += 10
        if snapshot.get("1h", {}).get("trend") == "UP":
            score += 10
        
        # 4. Глубина перекупленности (бонус 15 баллов)
        max_score += 15
        wt_bonus = 0
        for tf in ["1h", "45m", "15m"]:
            wt1 = snapshot.get(tf, {}).get("wt1", 0)
            if wt1 > 70:  # Экстремальная перекупленность
                wt_bonus += 5
        score += min(wt_bonus, 15)
    
    # Нормализуем к 100
    if max_score > 0:
        normalized_score = int((score / max_score) * 100)
    else:
        normalized_score = 0
    
    return min(normalized_score, 100)


def get_entry_recommendations(snapshot: dict, signal_type: str) -> dict:
    """
    Возвращает рекомендации по входу в сделку
    """
    recommendations = {
        "confidence": analyze_mtf_strength(snapshot, signal_type),
        "timeframe": "3m",  # Рекомендуемый ТФ для входа
        "risk_level": "Medium"
    }
    
    # Определяем уровень риска
    if recommendations["confidence"] >= 70:
        recommendations["risk_level"] = "Low"
    elif recommendations["confidence"] <= 40:
        recommendations["risk_level"] = "High"
    
    return recommendations