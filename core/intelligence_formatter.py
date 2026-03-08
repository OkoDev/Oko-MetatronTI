"""
Форматирование торговой рекомендации в Telegram-сообщение.
Ориентировано на новичка: русские термины, секции Интерпретация/Рекомендации, R:R.

Интерпретация генерируется через MessageComposer (приоритет):
  1. signal.interpretation  — заполнено детектором
  2. Claude haiku           — если ANTHROPIC_API_KEY задан (кеш in-memory)
  3. Static fallback        — хардкоженные тексты в message_composer.py
"""
from core.signal_models import TradingRecommendation
from core.message_builder import tv_link
from core.message_composer import get_composer

_ACTION_EMOJI = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "WATCH": "👀"}
_ACTION_LABEL = {
    "BUY": "BUY — ожидается рост",
    "SELL": "SELL — ожидается падение",
    "HOLD": "HOLD — держать",
    "WATCH": "WATCH — наблюдать",
}
_DIRECTION_LABEL = {
    "LONG": "LONG — рост цены",
    "SHORT": "SHORT — падение цены",
    "NEUTRAL": "NEUTRAL",
}
_SIGNAL_TYPE_RU = {
    "trend_signal": "Тренд EMA",
    "wt_signal": "WaveTrend",
    "anomaly": "Аномалия объёма",
    "divergence": "Дивергенция",
    "mtf_divergence": "MTF-дивергенция (каскад TF)",
    "pivot_reversal": "Разворот от уровня пивота",
    "mtf_alert": "MTF-разворот (4 TF)",
    "composite": "Комплексный анализ",
}
_RISK_RU = {"LOW": "Низкий", "MEDIUM": "Средний", "HIGH": "Высокий"}


def _sl_hint(sl_source: str) -> str:
    """Короткое пояснение источника стоп-лосса."""
    if not sl_source:
        return ""
    if sl_source.startswith("atr_14"):
        return "ATR(14): адаптивный стоп за рыночный шум"
    if sl_source.startswith("volatility"):
        return "волатильность пары"
    return "фиксированный"


def _tp_hint(tp_source: str) -> str:
    """Короткое пояснение источника тейк-профита."""
    if not tp_source:
        return ""
    if tp_source.startswith("pivot_1M"):
        lv = tp_source.split(":")[-1]
        return f"месячный пивот {lv}"
    if tp_source.startswith("pivot_1W"):
        lv = tp_source.split(":")[-1]
        return f"недельный пивот {lv}"
    if tp_source.startswith("pivot_1D"):
        lv = tp_source.split(":")[-1]
        return f"дневной пивот {lv}"
    if tp_source.startswith("atr_rr"):
        return "ATR RR 1:1.5 (нет пивота в кеше)"
    return ""


def _fmt_price(price: float) -> str:
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.4f}"
    elif price >= 0.01:
        return f"{price:.5f}"
    return f"{price:.8f}"


def _pct(entry: float, level: float) -> str:
    if not entry:
        return ""
    return f"{(level - entry) / entry * 100:+.2f}%"


async def format_intelligence_message(recommendation: TradingRecommendation) -> str:
    """Async: может запрашивать Claude haiku для интерпретации новых типов сигналов."""
    action = recommendation.action
    emoji = _ACTION_EMOJI.get(action, "❓")
    action_label = _ACTION_LABEL.get(action, action)
    strength = round(recommendation.overall_strength)
    direction_val = getattr(recommendation.direction, "value", str(recommendation.direction))
    direction_label = _DIRECTION_LABEL.get(direction_val, direction_val)

    if strength >= 80:
        strength_emoji, strength_text = "🔥🔥🔥", "Очень высокая"
    elif strength >= 60:
        strength_emoji, strength_text = "🔥🔥", "Высокая"
    elif strength >= 40:
        strength_emoji, strength_text = "🔥", "Средняя"
    else:
        strength_emoji, strength_text = "⚡", "Низкая"

    parts = [
        f"{emoji} <b>{action_label}</b>",
        f"Пара: {tv_link(recommendation.symbol)}",
        f"Направление: <b>{direction_label}</b>",
        "",
        f"{strength_emoji} Сила сигнала: <b>{strength}/100</b> — {strength_text}",
        f"Риск сделки: {_RISK_RU.get(recommendation.risk_level, recommendation.risk_level)}",
    ]

    # При WATCH/HOLD или NEUTRAL — нет торгового решения, показываем упрощённый вид
    is_tradeable = action in ("BUY", "SELL") and direction_val != "NEUTRAL"

    if not is_tradeable:
        parts += [
            "",
            "<b>💡 Ситуация:</b>",
            "  • Сигналы присутствуют, но направление не определено",
            "  • Конфликт между поддерживающими и противоречивыми сигналами",
            "",
            "<b>⚠️ Рекомендации:</b>",
            "  • Ждите появления чёткого сигнала BUY или SELL",
            "  • Не открывайте позицию при неопределённости",
        ]
        ctx = recommendation.market_context
        parts += ["", "<b>📊 Рынок:</b>",
                  f"  Цена: <code>{_fmt_price(ctx.current_price)}</code>"]
        if ctx.price_change_24h:
            ch_emoji = "📈" if ctx.price_change_24h > 0 else "📉"
            parts.append(f"  {ch_emoji} За 24ч: {ctx.price_change_24h:+.2f}%")
        parts.append(f"\n⏰ {recommendation.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        return "\n".join(parts)

    # Торговые уровни (только для BUY/SELL)
    entry = recommendation.entry_price
    sl = recommendation.stop_loss
    tp = recommendation.take_profit

    if entry:
        parts += ["", "<b>🎯 Точки входа:</b>",
                  f"  Вход:        <code>{_fmt_price(entry)}</code>"]
        if sl:
            sl_hint = _sl_hint(recommendation.sl_source)
            parts.append(f"  Стоп-лосс:   <code>{_fmt_price(sl)}</code>  ({_pct(entry, sl)})  <i>{sl_hint}</i>")
        if tp:
            tp_hint = _tp_hint(recommendation.tp_source)
            parts.append(f"  Тейк-профит: <code>{_fmt_price(tp)}</code>  ({_pct(entry, tp)})  <i>{tp_hint}</i>")
        if sl and tp:
            risk_pts = abs(entry - sl)
            rw_pts = abs(tp - entry)
            if risk_pts > 0:
                rr = rw_pts / risk_pts
                rr_quality = "🟢 отлично" if rr >= 2.0 else "🟡 приемлемо" if rr >= 1.5 else "🔴 слабо"
                parts.append(f"  Риск/Прибыль: 1:{rr:.1f}  {rr_quality}")

    # Анализ сигналов — что за и против
    support_types = list(dict.fromkeys(
        s.signal_type.value for s in recommendation.supporting_signals
    ))
    conflict_types = list(dict.fromkeys(
        s.signal_type.value for s in recommendation.conflicting_signals
    ))
    support_ru = [_SIGNAL_TYPE_RU.get(t, t) for t in support_types]
    conflict_ru = [_SIGNAL_TYPE_RU.get(t, t) for t in conflict_types]

    if support_ru or conflict_ru:
        parts += ["", "<b>📋 Анализ сигналов:</b>"]
        for t in support_ru[:5]:
            parts.append(f"  ✅ {t}")
        for t in conflict_ru[:3]:
            parts.append(f"  ❌ {t} (против)")

    # Интерпретация — через MessageComposer (детектор / AI / fallback)
    composer = get_composer()
    interp_lines = []
    for sig in recommendation.supporting_signals[:3]:
        sig_type = sig.signal_type.value
        text = await composer.interpret(
            signal_type=sig_type,
            direction=direction_val,
            description=sig.description,
            signal_interpretation=sig.interpretation,
        )
        if text:
            interp_lines.append(f"  • {text}")

    if interp_lines:
        parts += ["", "<b>💡 Что произошло:</b>"]
        parts.extend(interp_lines)

    # Рекомендации — конкретные действия на основе силы
    parts += ["", "<b>⚠️ Рекомендации:</b>"]
    if strength >= 75:
        parts.append("  • Отличный сигнал — можно входить стандартным объёмом")
        parts.append("  • Дождитесь закрытия свечи для подтверждения")
    elif strength >= 60:
        parts.append("  • Хороший сигнал — стандартный объём позиции")
        parts.append("  • Желательно подтверждение на 5m/15m")
    elif strength >= 40:
        parts.append("  • Средний сигнал — уменьшите объём вдвое")
        parts.append("  • Обязательно дождитесь подтверждения на младшем TF")
    else:
        parts.append("  • Слабый сигнал — высокий риск, вход не рекомендуется")
        parts.append("  • Дождитесь более сильного сигнала")

    # Контекст рынка
    ctx = recommendation.market_context
    price_str = _fmt_price(ctx.current_price)
    parts += ["", "<b>📊 Рынок:</b>",
              f"  Цена: <code>{price_str}</code>"]

    if ctx.price_change_24h:
        ch_emoji = "📈" if ctx.price_change_24h > 0 else "📉"
        parts.append(f"  {ch_emoji} За 24ч: {ctx.price_change_24h:+.2f}%")

    if ctx.volume_24h > 0:
        v = ctx.volume_24h
        if v >= 1_000_000_000:
            vol_str = f"${v / 1_000_000_000:.1f}B"
        elif v >= 1_000_000:
            vol_str = f"${v / 1_000_000:.1f}M"
        else:
            vol_str = f"${v:,.0f}"
        parts.append(f"  Объём 24ч: {vol_str}")

    parts.append(f"\n⏰ {recommendation.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

    return "\n".join(parts)
