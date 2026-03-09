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
    "BUY":   "BUY",
    "SELL":  "SELL",
    "HOLD":  "HOLD",
    "WATCH": "WATCH",
}
_DIRECTION_LABEL = {
    "LONG":    "LONG ↑",
    "SHORT":   "SHORT ↓",
    "NEUTRAL": "NEUTRAL",
}
_SIGNAL_TYPE_RU = {
    "trend_signal":    "Тренд EMA",
    "wt_signal":       "WaveTrend",
    "anomaly":         "Аномалия объёма",
    "divergence":      "Дивергенция",
    "mtf_divergence":  "MTF-дивергенция",
    "pivot_reversal":  "Разворот от пивота",
    "mtf_alert":       "MTF-разворот",
    "confluence":      "Confluence",
    "composite":       "Комплексный",
}
_RISK_RU = {"LOW": "Низкий", "MEDIUM": "Средний", "HIGH": "Высокий"}

# Источники SL/TP — короткие метки
_SL_SHORT = {
    "tsl_line":   "TSL",
    "swing_low":  "Свинг",
    "swing_high": "Свинг",
    "structural": "Структура",
    "atr_14":     "ATR(14)",
    "volatility": "Волатильность",
    "fallback":   "Фикс",
}
_TP_TF = {
    "pivot_1M": "1M",
    "pivot_1W": "1W",
    "pivot_1D": "1D",
    "atr_rr":   "ATR RR",
}

_SEP = "─" * 18


def _sl_short(sl_source: str) -> str:
    if not sl_source:
        return ""
    for k, v in _SL_SHORT.items():
        if sl_source.startswith(k):
            return v
    return ""


def _tp_short(tp_source: str) -> str:
    if not tp_source:
        return ""
    for k, v in _TP_TF.items():
        if tp_source.startswith(k):
            lv = tp_source.split(":")[-1] if ":" in tp_source else ""
            return f"{v} {lv}".strip()
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


def _strength_label(strength: int) -> tuple[str, str]:
    if strength >= 80:
        return "🔥🔥🔥", "Очень высокая"
    elif strength >= 60:
        return "🔥🔥", "Высокая"
    elif strength >= 40:
        return "🔥", "Средняя"
    return "⚡", "Низкая"


def _entry_advice(strength: int) -> str:
    if strength >= 75:
        return "Стандартный объём · дождаться закрытия свечи"
    elif strength >= 60:
        return "Стандартный объём · желательно подтверждение 5m"
    elif strength >= 40:
        return "½ объёма · нужно подтверждение на младшем TF"
    return "Пропустить — сила сигнала недостаточна"


async def format_intelligence_message(recommendation: TradingRecommendation) -> str:
    """Async: может запрашивать Claude haiku для интерпретации новых типов сигналов."""
    action = recommendation.action
    emoji = _ACTION_EMOJI.get(action, "❓")
    action_label = _ACTION_LABEL.get(action, action)
    strength = round(recommendation.overall_strength)
    direction_val = getattr(recommendation.direction, "value", str(recommendation.direction))
    direction_label = _DIRECTION_LABEL.get(direction_val, direction_val)
    strength_emoji, strength_text = _strength_label(strength)

    # Строка 1: действие · пара · направление
    link = tv_link(recommendation.symbol)
    header = f"{emoji} <b>{action_label} · {link} · {direction_label}</b>"

    # Строка 2: сила · риск
    risk_ru = _RISK_RU.get(recommendation.risk_level, recommendation.risk_level)
    sub = f"{strength_emoji} <b>{strength}/100</b> {strength_text}  ·  Риск: {risk_ru}"

    parts = ["\n", header, sub, ""]

    # При WATCH/HOLD или NEUTRAL — упрощённый вид
    is_tradeable = action in ("BUY", "SELL") and direction_val != "NEUTRAL"

    if not is_tradeable:
        ctx = recommendation.market_context
        parts += [
            "<b>📊 Рынок</b>",
            f"  Цена: <code>{_fmt_price(ctx.current_price)}</code>",
        ]
        if ctx.price_change_24h:
            ch_emoji = "📈" if ctx.price_change_24h > 0 else "📉"
            parts.append(f"  {ch_emoji} За 24ч: {ctx.price_change_24h:+.2f}%")
        parts += [
            "",
            "Направление не определено — нет позиции",
            f"\n⏰ {recommendation.timestamp.strftime('%d.%m %H:%M')}",
            "\n",
        ]
        return "\n".join(parts)

    # Торговые уровни
    entry = recommendation.entry_price
    sl = recommendation.stop_loss
    tp = recommendation.take_profit

    if entry:
        parts.append("<b>💰 Сделка</b>")
        parts.append(f"  Вход:  <code>{_fmt_price(entry)}</code>")
        if sl:
            sl_lbl = _sl_short(recommendation.sl_source)
            parts.append(
                f"  Стоп:  <code>{_fmt_price(sl)}</code>  <i>({_pct(entry, sl)}"
                + (f"  {sl_lbl}" if sl_lbl else "") + "</i>)"
            )
        if tp:
            tp_lbl = _tp_short(recommendation.tp_source)
            parts.append(
                f"  Цель:  <code>{_fmt_price(tp)}</code>  <i>({_pct(entry, tp)}"
                + (f"  {tp_lbl}" if tp_lbl else "") + "</i>)"
            )
        if sl and tp:
            risk_pts = abs(entry - sl)
            rw_pts = abs(tp - entry)
            if risk_pts > 0:
                rr = rw_pts / risk_pts
                rr_q = "🟢" if rr >= 2.0 else "🟡" if rr >= 1.5 else "🔴"
                parts.append(f"  R:R    {rr_q} 1:{rr:.1f}")
        parts.append("")

    # Сигналы-подтверждения
    support_types = list(dict.fromkeys(
        s.signal_type.value for s in recommendation.supporting_signals
    ))
    conflict_types = list(dict.fromkeys(
        s.signal_type.value for s in recommendation.conflicting_signals
    ))
    support_ru = [_SIGNAL_TYPE_RU.get(t, t) for t in support_types]
    conflict_ru = [_SIGNAL_TYPE_RU.get(t, t) for t in conflict_types]

    if support_ru or conflict_ru:
        parts.append("<b>📋 Сигналы</b>")
        for t in support_ru[:5]:
            parts.append(f"  ✅ {t}")
        for t in conflict_ru[:3]:
            parts.append(f"  ❌ {t}")
        parts.append("")

    # Интерпретация — через MessageComposer (детектор / AI / fallback)
    composer = get_composer()
    interp_lines = []
    for sig in recommendation.supporting_signals[:2]:
        sig_type = sig.signal_type.value
        text = await composer.interpret(
            signal_type=sig_type,
            direction=direction_val,
            description=sig.description,
            signal_interpretation=sig.interpretation,
        )
        if text:
            interp_lines.append(f"  {text}")

    if interp_lines:
        parts.append("<b>💡 Что произошло</b>")
        parts.extend(interp_lines)
        parts.append("")

    # Совет по входу — одна строка
    parts.append(f"<i>📌 {_entry_advice(strength)}</i>")

    # Рынок — компактно
    ctx = recommendation.market_context
    mkt_parts = [f"<code>{_fmt_price(ctx.current_price)}</code>"]
    if ctx.price_change_24h:
        ch_emoji = "📈" if ctx.price_change_24h > 0 else "📉"
        mkt_parts.append(f"{ch_emoji}{ctx.price_change_24h:+.1f}%")
    if ctx.volume_24h > 0:
        v = ctx.volume_24h
        vol_str = (f"${v/1e9:.1f}B" if v >= 1e9 else
                   f"${v/1e6:.1f}M" if v >= 1e6 else f"${v:,.0f}")
        mkt_parts.append(vol_str)
    parts += ["", f"<b>📊</b> {' · '.join(mkt_parts)}"]

    # Время + разделитель
    parts += [
        f"⏰ {recommendation.timestamp.strftime('%d.%m %H:%M')}",
        "\n",
    ]

    return "\n".join(parts)
