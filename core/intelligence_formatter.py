"""
Форматирование торговой рекомендации в Telegram-сообщение.
"""
from core.signal_models import TradingRecommendation


def format_intelligence_message(recommendation: TradingRecommendation) -> str:
    action_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "WATCH": "👀"}
    risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}

    if recommendation.overall_strength >= 80:
        strength_emoji, strength_text = "🔥🔥🔥", "Очень высокая"
    elif recommendation.overall_strength >= 60:
        strength_emoji, strength_text = "🔥🔥", "Высокая"
    elif recommendation.overall_strength >= 40:
        strength_emoji, strength_text = "🔥", "Средняя"
    else:
        strength_emoji, strength_text = "⚠️", "Низкая"

    emoji = action_emoji.get(recommendation.action, "❓")

    parts = [
        f"{emoji} <b>КОМПЛЕКСНАЯ РЕКОМЕНДАЦИЯ</b> {emoji}",
        f"Пара: {recommendation.symbol}",
        f"Действие: <b>{recommendation.action}</b>",
        f"Направление: {recommendation.direction.value}",
        "",
        f"{strength_emoji} <b>Сила сигнала: {recommendation.overall_strength}/100</b> ({strength_text})",
        f"Уверенность: {recommendation.confidence:.2f}",
        f"{risk_emoji.get(recommendation.risk_level, '❓')} <b>Риск:</b> {recommendation.risk_level}",
        "",
        f"📊 <b>Сигналов найдено:</b> {recommendation.signals_count}",
        f"✅ Поддерживающих: {len(recommendation.supporting_signals)}",
        f"⚠️ Конфликтующих: {len(recommendation.conflicting_signals)}",
    ]

    if recommendation.entry_price:
        parts += [
            "", "<b>🎯 Торговые уровни:</b>",
            f"Вход: {recommendation.entry_price:.6f}",
        ]
        if recommendation.stop_loss:
            parts.append(f"Стоп-лосс: {recommendation.stop_loss:.6f}")
        if recommendation.take_profit:
            parts.append(f"Тейк-профит: {recommendation.take_profit:.6f}")

    if recommendation.reasoning:
        parts += ["", "<b>📋 Обоснование:</b>"]
        for reason in recommendation.reasoning[:5]:
            parts.append(f"• {reason}")

    if hasattr(recommendation, "metadata") and recommendation.metadata:
        ml_info = recommendation.metadata.get("ml_enhanced")
        if ml_info:
            parts += ["", "<b>🤖 ML Анализ:</b>", "• Анализ улучшен машинным обучением"]
            ml_predictions = recommendation.metadata.get("ml_predictions_count", 0)
            if ml_predictions > 0:
                parts.append(f"• ML предсказаний: {ml_predictions}")
            strength_adj = recommendation.metadata.get("ml_strength_adjustment", 0)
            if abs(strength_adj) > 0:
                adj_emoji = "📈" if strength_adj > 0 else "📉"
                parts.append(f"• {adj_emoji} Корректировка силы: {strength_adj:+.1f}")

        risk_managed = recommendation.metadata.get("risk_managed")
        if risk_managed:
            parts += ["", "<b>🛡️ Управление рисками:</b>"]
            parts.append(f"• Уровень риска: {recommendation.metadata.get('risk_level', 'UNKNOWN')}")
            position_size = recommendation.metadata.get("position_size", 0)
            if position_size > 0:
                parts.append(f"• Размер позиции: {position_size:.6f}")
            risk_percent = recommendation.metadata.get("risk_percent", 0)
            if risk_percent > 0:
                parts.append(f"• Риск позиции: {risk_percent:.2f}%")
            risk_reward = recommendation.metadata.get("risk_reward_ratio", 0)
            if risk_reward > 0:
                parts.append(f"• Соотношение риск/прибыль: {risk_reward:.2f}")
            risk_warnings = recommendation.metadata.get("risk_warnings", [])
            if risk_warnings:
                parts.append("• ⚠️ Предупреждения о рисках:")
                for warning in risk_warnings[:3]:
                    parts.append(f"  - {warning}")

    parts += [
        "", "<b>📈 Контекст рынка:</b>",
        f"Цена: {recommendation.market_context.current_price:.6f}",
    ]
    if recommendation.market_context.volume_24h > 0:
        parts.append(f"Объем 24ч: {recommendation.market_context.volume_24h:,.0f}")
    if recommendation.market_context.price_change_24h:
        change_emoji = "📈" if recommendation.market_context.price_change_24h > 0 else "📉"
        parts.append(f"{change_emoji} Изменение 24ч: {recommendation.market_context.price_change_24h:+.2f}%")

    parts += ["", f"⏰ Время анализа: {recommendation.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"]

    return "\n".join(parts)
