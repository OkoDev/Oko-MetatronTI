"""
Форматирование торговой рекомендации в Telegram-сообщение.
Ориентировано на новичка: русские термины, секции Интерпретация/Рекомендации, R:R.

Интерпретация генерируется через MessageComposer (приоритет):
  1. signal.interpretation  — заполнено детектором
  2. Claude haiku           — если ANTHROPIC_API_KEY задан (кеш in-memory)
  3. Static fallback        — хардкоженные тексты в message_composer.py
"""
from typing import Optional
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

    # Режим отображения:
    # BUY/SELL + направление → полный формат с советом по входу
    # WATCH + LONG/SHORT    → полный формат с пометкой "Наблюдение"
    # HOLD / NEUTRAL        → минимальный формат
    is_tradeable = action in ("BUY", "SELL") and direction_val not in ("NEUTRAL", "")
    is_watch_directional = action == "WATCH" and direction_val not in ("NEUTRAL", "")

    if not is_tradeable and not is_watch_directional:
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
    def _sig_label(sig) -> str:
        """Название сигнала с уточнением пивот-уровня если есть."""
        base = _SIGNAL_TYPE_RU.get(sig.signal_type.value, sig.signal_type.value)
        pivot_hit = (sig.data or {}).get("pivot_hit", "")
        if pivot_hit:
            # "1D_S1=25.132" → показываем только метку уровня без цены
            level_label = pivot_hit.split("=")[0]  # "1D_S1"
            return f"{base} ({level_label})"
        return base

    support_sigs = list({s.signal_type.value: s for s in recommendation.supporting_signals}.values())
    conflict_sigs = list({s.signal_type.value: s for s in recommendation.conflicting_signals}.values())

    if support_sigs or conflict_sigs:
        parts.append("<b>📋 Сигналы</b>")
        for s in support_sigs[:5]:
            parts.append(f"  ✅ {_sig_label(s)}")
        for s in conflict_sigs[:3]:
            parts.append(f"  ❌ {_sig_label(s)}")
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

    # MTF контекст — показываем всегда когда есть (ключевая информация для входа)
    ctx_mtf = getattr(recommendation.market_context, "mtf_context", None)
    if ctx_mtf is None:
        ctx_mtf = (recommendation.metadata or {}).get("mtf_context")
    if ctx_mtf:
        _bias_val = getattr(getattr(ctx_mtf, "direction_bias", None), "value",
                            ctx_mtf.get("direction_bias") if isinstance(ctx_mtf, dict) else None)
        _aligned = getattr(ctx_mtf, "aligned_pct", None) or (ctx_mtf.get("aligned_pct") if isinstance(ctx_mtf, dict) else None)
        _regime  = getattr(ctx_mtf, "regime", None) or (ctx_mtf.get("regime") if isinstance(ctx_mtf, dict) else None)
        _bias_icon = {"LONG": "🟢", "SHORT": "🔴"}.get(_bias_val, "⚪")
        _bias_ru   = {"LONG": "БЫЧИЙ", "SHORT": "МЕДВЕЖИЙ", "NEUTRAL": "НЕЙТРАЛЬ"}.get(_bias_val, _bias_val or "?")
        _regime_ru = {"TREND": "тренд", "RANGE": "боковик", "HIGH_VOL": "высок.вол"}.get(_regime or "", _regime or "")
        _aligned_str = f"{_aligned}% ТФ" if _aligned is not None else ""
        _mtf_parts = [p for p in [f"{_bias_icon} {_bias_ru}", _aligned_str, _regime_ru] if p]
        # Предупреждение: сигнал против MTF bias
        _dir_val = direction_val  # "LONG" / "SHORT"
        _counter = (_bias_val == "LONG" and _dir_val == "SHORT") or (_bias_val == "SHORT" and _dir_val == "LONG")
        _warn = "  ⚠️ против тренда" if _counter else ""
        parts.append(f"<i>📡 MTF: {' · '.join(_mtf_parts)}{_warn}</i>")
        parts.append("")

    # DEV-21: SMC контекст — OB+FVG / OTE / CHoCH (только если есть значимые факторы)
    smc_meta = (recommendation.metadata or {}).get("smc_context")
    if smc_meta and isinstance(smc_meta, dict):
        _smc_trend   = smc_meta.get("smc_trend", "")
        _is_long_dir = direction_val == "LONG"
        _ob_fvg      = smc_meta.get("smc_bull_ob_fvg_overlap") if _is_long_dir else smc_meta.get("smc_bear_ob_fvg_overlap")
        _in_ote      = smc_meta.get("smc_price_in_ote", False)
        _has_choch   = smc_meta.get("smc_has_choch", False)
        _has_bos     = smc_meta.get("smc_has_bos", False)
        _smc_details = [p for p in [
            "OB+FVG ✅" if _ob_fvg else "",
            "OTE ✅"    if _in_ote else "",
            "CHoCH ✅"  if _has_choch else ("BOS ✅" if _has_bos else ""),
        ] if p]
        if _smc_details:
            _t_icon = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(_smc_trend, "⬜")
            _smc_line = f"📐 SMC: {_t_icon} {_smc_trend}" + (" | " + " | ".join(_smc_details) if _smc_details else "")
            parts.append(f"<i>{_smc_line}</i>")
            parts.append("")

    # Совет по входу — одна строка
    if is_watch_directional:
        parts.append("<i>👀 Наблюдение · ждём подтверждение на закрытии свечи</i>")
    else:
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


# ---------------------------------------------------------------------------
# DEV-21: Unified TG message formatter for SignalData-based signals
# ---------------------------------------------------------------------------

_SIGNAL_TYPE_ICON: dict[str, str] = {
    "confluence":   "🔥",
    "wt_b_signal":  "🌊",
    "mtf_bias":     "📡",
    "pivot_reversal": "📍",
    "trend_signal": "📈",
    "anomaly":      "⚡",
    "wt_signal":    "🌀",
}

_REVERSAL_FACTOR_EMOJI: dict[str, str] = {
    "RSI_DIV":   "📉",
    "WT_DIV":    "🌀",
    "PIVOT":     "📍",
    "VOLUME":    "📦",
    "MTF":       "🔭",
}


def _fire(strength: float) -> str:
    """Возвращает огни по силе сигнала."""
    if strength >= 85:
        return "🔥🔥🔥"
    if strength >= 70:
        return "🔥🔥"
    if strength >= 55:
        return "🔥"
    return "⚡"


_REVERSAL_FACTOR_INLINE: dict[str, str] = {
    "TSL_CROSS_UP":      "📈 TSL↑",
    "TSL_CROSS_DOWN":    "📉 TSL↓",
    "WT_CROSS_IN_OS":    "⚡ WT✕↑ (OS)",
    "WT_CROSS_IN_OB":    "⚡ WT✕↓ (OB)",
    "WT_CROSS_UP":       "⚡ WT✕↑",
    "WT_CROSS_DOWN":     "⚡ WT✕↓",
    "PIVOT_TOUCH":       "🎯",
    "PIVOT_CONFLUENCE":  "📐 Конфл.",
    "WT_DIVERGENCE":     "🔄 Дивер",
    "WT_HIDDEN_DIV":     "🔄 Дивер↗",
}

_DIV_TYPE_RU: dict[str, str] = {
    "regular_bull": "бычья",
    "regular_bear": "медвежья",
    "hidden_bull":  "скрытая↗",
    "hidden_bear":  "скрытая↘",
}

_TF_ORDER = ["3m", "5m", "15m", "1h", "4h", "1d"]


def _mtf_trend_line(data: dict) -> Optional[str]:
    """Формирует строку MTF-байаса из data dict (обратная совместимость)."""
    bias = data.get("mtf_bias") or data.get("trend_bias")
    if not bias:
        return None
    icon = "🟢" if str(bias).upper() == "LONG" else ("🔴" if str(bias).upper() == "SHORT" else "⬜")
    aligned = data.get("tf_aligned")
    aligned_str = f" {aligned}% ТФ" if aligned is not None else ""
    return f"<i>📡 MTF: {icon} {bias}{aligned_str}</i>"


def _mtf_context_lines(data: dict, is_long: bool) -> list[str]:
    """Строки контекста 4h/1h: тренд + WT + предупреждение против тренда."""
    lines = []
    for tf_key, label in [("mtf_4h", "4h"), ("mtf_1h", "1h")]:
        trend = data.get(f"{tf_key}_trend", "")
        if not trend:
            continue
        wt = data.get(f"{tf_key}_wt")
        zone = data.get(f"{tf_key}_zone", "")
        icon = "🟢" if trend == "UP" else "🔴"
        counter = (is_long and trend == "DOWN") or (not is_long and trend == "UP")
        wt_str = f" WT={wt}" if wt is not None else ""
        zone_str = f" ({zone})" if zone else ""
        warn = " ⚠️ против тренда" if counter else ""
        lines.append(f"  {icon} {label}: {trend}{wt_str}{zone_str}{warn}")
    # fallback: старый ключ mtf_bias/trend_bias
    if not lines:
        line = _mtf_trend_line(data)
        if line:
            lines.append(line)
    return lines


def format_signal_message(
    symbol: str,
    sig: object,
    *,
    signal_type: str = "",
) -> str:
    """DEV-21: Единый форматтер TG-сообщений для SignalData сигналов.

    Структура:
      Заголовок (общий) · Шкала (общая)
      └─ Блок типа (специфичный):
           mtf_bias    → tf_table + entry_tf + senior + alignment
           reversal    → inline факторы + wt_quality
           wt_b_signal → дивергенция %/бары
      └─ MTF контекст 4h/1h (общий, с ⚠️ против тренда)
      └─ Пивот (общий, поддерживает числовой и строковый pivot_hit)
      └─ Дивергенция (общий, с div_desc и div_type_ru)
      └─ Футер (общий)

    Старые mtf_bias_message/reversal_message — thin wrappers.
    """
    data: dict = getattr(sig, "data", {}) or {}
    _dir = getattr(sig, "direction", data.get("direction", ""))
    direction: str = (getattr(_dir, "value", None) or str(_dir)).upper()
    strength: float = float(getattr(sig, "strength", data.get("strength", 0)))
    confidence: float = float(getattr(sig, "confidence", data.get("confidence", 0)))
    timeframe: str = str(getattr(sig, "timeframe", data.get("timeframe", "15m")))
    sig_type: str = signal_type or str(getattr(sig, "signal_type", "")).lower()
    is_long: bool = direction == "LONG"

    dir_icon = "🟢" if is_long else ("🔴" if direction == "SHORT" else "⬜")
    dir_ru = "ЛОНГ" if is_long else ("ШОРТ" if direction == "SHORT" else direction)
    type_icon = _SIGNAL_TYPE_ICON.get(sig_type, "📊")
    fire = _fire(strength)

    # ── Заголовок ──────────────────────────────────────────────────────────
    _tf_interval = int(timeframe.replace("h", "")) * 60 if "h" in timeframe else int(timeframe.replace("m", "")) if timeframe else 15
    parts: list[str] = [
        f"{dir_icon} {tv_link(symbol, interval=_tf_interval)} · {dir_ru} · {timeframe}",
        f"{type_icon} {fire} Сигнал: <b>{round(strength)}%</b>  conf: {confidence:.0%}",
        "",
    ]

    # ── Блок специфичный для типа ──────────────────────────────────────────
    if sig_type in ("confluence", "reversal"):
        factors = data.get("factors") or data.get("confluence_factors") or []
        pivot_hit = data.get("pivot_hit", "")
        pivot_label = pivot_hit.split("=")[0] if pivot_hit else ""
        wt_quality = data.get("wt_cross_quality", "")
        quality_tag = " · ✨ идеальный" if wt_quality == "in_zone" else ""
        if factors:
            inline = []
            for f in factors[:6]:
                label = f if isinstance(f, str) else str(f)
                if label == "PIVOT_TOUCH" and pivot_label:
                    inline.append(f"🎯 {pivot_label}")
                elif label == "WT_HIDDEN_DIV":
                    inline.append("🔄 Дивер↗" if is_long else "🔄 Дивер↘")
                else:
                    inline.append(_REVERSAL_FACTOR_INLINE.get(label, f"• {label}"))
            parts.append(f"  {'  ·  '.join(inline)}{quality_tag}")
            parts.append("")

    elif sig_type == "wt_b_signal":
        div_pct = data.get("div_pct") or data.get("divergence_pct")
        bars = data.get("bars") or data.get("div_bars")
        os_method = data.get("os_method", "fixed")
        wt_line = "🌊 WT-B дивергенция"
        if div_pct is not None:
            wt_line += f" · {div_pct:+.1f}%"
        if bars is not None:
            wt_line += f" · {bars} баров"
        parts.append(wt_line)
        if os_method != "fixed":
            parts.append(f"  <i>порог OB/OS: {os_method}</i>")
        parts.append("")

    elif sig_type == "mtf_bias":
        tf_table = data.get("tf_table", {})
        entry_tf = data.get("entry_tf", "15m")
        aligned_pct = data.get("aligned_pct") or data.get("tf_aligned") or data.get("alignment_pct", 0)
        senior_matches = data.get("senior_matches", "?")
        regime = data.get("regime") or "?"
        if tf_table:
            tf_cells = []
            for tf in _TF_ORDER:
                d = tf_table.get(tf)
                if not d:
                    continue
                arr = "↑" if d.get("trend") == "UP" else "↓"
                zone_mark = ("⚡" if d.get("wt_cross")
                             else ("🔴" if d.get("zone") == "OB"
                                   else ("🟢" if d.get("zone") == "OS" else "")))
                tf_cells.append(f"{tf}{arr}{zone_mark}")
            if tf_cells:
                parts.append(f"  {'  '.join(tf_cells)}")
        parts.append(f"  entry: <code>{entry_tf}</code>  align: <b>{aligned_pct}%</b>"
                     f"  senior: {senior_matches}/3  режим: {regime}")
        parts.append("")

    # ── MTF контекст 4h/1h (пропускаем для mtf_bias — у него своя таблица) ─
    if sig_type != "mtf_bias":
        ctx_lines = _mtf_context_lines(data, is_long)
        if ctx_lines:
            parts.extend(ctx_lines)
            parts.append("")

    # ── Пивот ──────────────────────────────────────────────────────────────
    pivot_hit = data.get("pivot_hit", "")          # "1D_S1=0.12345" — строка
    pivot_level = data.get("pivot_level") or data.get("pivot_price")  # число
    nearby = data.get("nearby_pivots", "")
    if pivot_hit and sig_type not in ("confluence", "reversal"):
        # для reversal pivot_hit уже показан в inline факторах
        parts.append(f"<i>📍 {pivot_hit}</i>")
    elif pivot_level:
        piv_type = data.get("pivot_type", "")
        parts.append(f"<i>📍 Пивот {piv_type}: {pivot_level:.6g}</i>")
    elif nearby:
        parts.append(f"<i>🗺 {nearby}</i>")

    # ── Pivot Confluence (ARCH-27) ───────────────────────────────────────────
    pivot_conf = data.get("pivot_confluence", "")
    if pivot_conf:
        parts.append(f"<i>📐 Конфлюэнция: {pivot_conf}</i>")

    # ── Дивергенция ─────────────────────────────────────────────────────────
    if sig_type != "wt_b_signal":
        div_desc = data.get("div_desc", "")
        div_type = data.get("div_type", "")
        div_type_ru = _DIV_TYPE_RU.get(div_type, "")
        if div_desc:
            arrow = "↗️" if is_long else "↘️"
            type_tag = f" [{div_type_ru}]" if div_type_ru else ""
            parts.append(f"<i>{arrow} Дивер{type_tag}: {div_desc}</i>")
        elif div_type:
            parts.append(f"<i>🔄 Дивер: {div_type_ru or div_type}</i>")

    # ── Цена ────────────────────────────────────────────────────────────────
    price = data.get("current_price")
    if price:
        try:
            parts.append(f"  Цена: <code>{_fmt_price(float(price))}</code>")
        except Exception:
            pass

    # ── Футер ───────────────────────────────────────────────────────────────
    import datetime as _dt
    ts = getattr(sig, "timestamp", None)
    ts_str = ts.strftime("%d.%m %H:%M") if ts else _dt.datetime.utcnow().strftime("%d.%m %H:%M")
    parts += ["", f"⏰ {ts_str}", "\n"]

    return "\n".join(parts)
