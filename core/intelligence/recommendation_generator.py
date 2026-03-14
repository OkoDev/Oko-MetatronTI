"""
Генерация торговых рекомендаций: уровень риска, обоснование, SL/TP уровни.
Извлечено из TradingIntelligence._generate_recommendation, _determine_risk_level,
_generate_reasoning и _calculate_levels.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.signal_models import (
    SignalData, SignalDirection, SignalType,
    MarketContext, TradingRecommendation,
)

logger = logging.getLogger(__name__)


def determine_risk_level(
    strength: int,
    confidence: float,
    market_context: MarketContext,
) -> str:
    """Определяет уровень риска: LOW / MEDIUM / HIGH."""
    risk_score = 0
    if strength < 40:
        risk_score += 2
    elif strength < 60:
        risk_score += 1
    if confidence < 0.6:
        risk_score += 2
    elif confidence < 0.8:
        risk_score += 1
    if market_context.volatility and market_context.volatility > 15:
        risk_score += 1
    if market_context.price_change_24h and abs(market_context.price_change_24h) > 10:
        risk_score += 1
    if risk_score >= 4:
        return "HIGH"
    if risk_score >= 2:
        return "MEDIUM"
    return "LOW"


def generate_reasoning(
    signals: List[SignalData],
    analysis: Dict[str, Any],
    market_context: MarketContext,
) -> List[str]:
    """Генерирует текстовое обоснование рекомендации."""
    reasoning = []
    if analysis["supporting_signals"]:
        signal_types = [s.signal_type.value for s in analysis["supporting_signals"]]
        reasoning.append(f"Поддерживающие сигналы: {', '.join(set(signal_types))}")
    if analysis["conflicting_signals"]:
        signal_types = [s.signal_type.value for s in analysis["conflicting_signals"]]
        reasoning.append(f"Конфликтующие сигналы: {', '.join(set(signal_types))}")
    if market_context.volume_24h > 0:
        reasoning.append(f"Объем 24ч: {market_context.volume_24h:,.0f}")
    if market_context.price_change_24h:
        reasoning.append(f"Изменение цены 24ч: {market_context.price_change_24h:+.2f}%")
    reasoning.append(f"Общая сила: {analysis['strength']}/100")
    reasoning.append(f"Уверенность: {analysis['confidence']:.2f}")
    return reasoning


def calculate_levels(
    symbol: str,
    direction: SignalDirection,
    market_context: MarketContext,
    signals: List[SignalData],
    config: Dict,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], str, str]:
    """
    Рассчитывает уровни входа, SL и TP.

    SL (приоритет):
      1. Swing SL (структурный экстремум)
      2. TSL-линия индикатора
      3. Пивот-уровень из PIVOT_REVERSAL сигналов
      4. ATR(14) × динамический множитель / волатильность / фиксированный 2%

    Returns:
        (entry_price, stop_loss, take_profit, tp1_price, sl_source, tp_source)
    """
    current_price = market_context.current_price
    if current_price == 0:
        return None, None, None, None, "", ""

    entry_price = current_price
    sl_cfg     = config.get("trading", {}).get("sl_tp", {})
    atr_mult   = sl_cfg.get("atr_multiplier", 1.2)
    sl_min     = sl_cfg.get("sl_min_pct", 0.8)
    sl_max     = sl_cfg.get("sl_max_pct", 3.0)
    atr_dyn    = sl_cfg.get("atr_dynamic", True)
    atr_exp    = sl_cfg.get("atr_expand_threshold", 1.3)
    atr_con    = sl_cfg.get("atr_contract_threshold", 0.8)
    struct_buf = sl_cfg.get("struct_sl_buffer_pct", 0.3)
    struct_max = sl_cfg.get("struct_sl_max_dist", 3.0)

    is_long  = direction == SignalDirection.LONG
    is_short = direction == SignalDirection.SHORT

    # ATR динамика
    if atr_dyn and market_context.atr and market_context.atr_slow:
        ratio = market_context.atr / market_context.atr_slow
        if ratio > atr_exp:
            atr_mult = round(atr_mult * 0.85, 3)
        elif ratio < atr_con:
            atr_mult = round(min(atr_mult * 1.1, 1.5), 3)

    # ATR / волатильность baseline
    if market_context.atr and entry_price > 0:
        atr_pct   = market_context.atr / entry_price * 100
        sl_pct    = max(sl_min, min(atr_mult * atr_pct, sl_max))
        sl_source = f"atr_14:{atr_pct:.2f}%"
    elif market_context.volatility:
        sl_pct    = max(sl_min, min(market_context.volatility, sl_max))
        sl_source = f"volatility:{market_context.volatility:.2f}%"
    else:
        sl_pct    = 2.0
        sl_source = "fallback:2.0%"

    if direction not in (SignalDirection.LONG, SignalDirection.SHORT):
        return entry_price, None, None, None, "", ""

    # ── 1. SWING — структурный экстремум ──────────────────────────────────
    swing    = market_context.swing_low if is_long else market_context.swing_high
    _tsl_ref = market_context.tsl_trendup if is_long else market_context.tsl_trenddown
    _tsl_dist_ref = (
        abs(entry_price - _tsl_ref) / entry_price * 100
        if _tsl_ref and _tsl_ref > 0 and entry_price > 0 else 0.0
    )
    _swing_min = max(sl_min, _tsl_dist_ref)

    if swing and swing > 0:
        if is_long and swing < entry_price:
            swing_pct = (entry_price - swing) / entry_price * 100 + struct_buf
            if _swing_min <= swing_pct <= struct_max:
                sl_pct    = swing_pct
                sl_source = "swing_low"
        elif is_short and swing > entry_price:
            swing_pct = (swing - entry_price) / entry_price * 100 + struct_buf
            if _swing_min <= swing_pct <= struct_max:
                sl_pct    = swing_pct
                sl_source = "swing_high"

    # ── 2. TSL-линия — если swing недоступен ──────────────────────────────
    if "swing" not in sl_source:
        tsl_line = market_context.tsl_trendup if is_long else market_context.tsl_trenddown
        if tsl_line and tsl_line > 0:
            if is_long and tsl_line < entry_price:
                tsl_dist_pct = (entry_price - tsl_line) / entry_price * 100
                tsl_sl_pct   = tsl_dist_pct + struct_buf
                if tsl_sl_pct <= struct_max:
                    sl_pct    = tsl_sl_pct
                    sl_source = "tsl_line:trendup"
            elif is_short and tsl_line > entry_price:
                tsl_dist_pct = (tsl_line - entry_price) / entry_price * 100
                tsl_sl_pct   = tsl_dist_pct + struct_buf
                if tsl_sl_pct <= struct_max:
                    sl_pct    = tsl_sl_pct
                    sl_source = "tsl_line:trenddown"

    # ── 3. Пивот-уровень как резервный структурный SL ─────────────────────
    if "swing" not in sl_source and "tsl_line" not in sl_source:
        pivot_type    = "support" if is_long else "resistance"
        struct_levels = [
            s.data["level"]
            for s in signals
            if s.signal_type == SignalType.PIVOT_REVERSAL
            and s.data.get("pivot_type") == pivot_type
            and (s.data.get("level", 0) < entry_price if is_long
                 else s.data.get("level", 0) > entry_price)
        ]
        if struct_levels:
            nearest      = max(struct_levels) if is_long else min(struct_levels)
            pivot_sl_pct = abs(entry_price - nearest) / entry_price * 100 + struct_buf
            if sl_min <= pivot_sl_pct <= struct_max and pivot_sl_pct < sl_pct:
                sl_pct    = pivot_sl_pct
                sl_source = f"structural:{pivot_type}:{nearest:.6g}"

    # ── TP1: фиксированный 3R ─────────────────────────────────────────────
    tp1_pct = sl_pct * 3.0
    if is_long:
        stop_loss  = entry_price * (1 - sl_pct / 100)
        tp1_price  = entry_price * (1 + tp1_pct / 100)
    else:
        stop_loss  = entry_price * (1 + sl_pct / 100)
        tp1_price  = entry_price * (1 - tp1_pct / 100)

    take_profit = tp1_price
    tp_source   = f"atr_rr_3.0:{tp1_pct:.2f}%"

    return entry_price, stop_loss, take_profit, tp1_price, sl_source, tp_source


def generate_recommendation(
    symbol: str,
    signals: List[SignalData],
    analysis: Dict[str, Any],
    market_context: MarketContext,
    thresholds: Dict,
    config: Dict,
) -> TradingRecommendation:
    """
    Генерирует финальную торговую рекомендацию из словаря анализа.

    Args:
        symbol: торговая пара
        signals: все сигналы (для расчёта уровней)
        analysis: словарь от analyze_signals_advanced + enhance_analysis_with_ml
        market_context: контекст рынка
        thresholds: пороги (min_strength, min_confidence, ...)
        config: полный конфиг бота (для calculate_levels)
    Returns:
        TradingRecommendation
    """
    strength           = analysis["strength"]
    confidence         = analysis["confidence"]
    direction          = analysis["direction"]
    supporting_signals = analysis["supporting_signals"]
    conflicting_signals = analysis["conflicting_signals"]

    # Действие
    if strength >= thresholds["min_strength"] and confidence >= thresholds["min_confidence"]:
        if direction == SignalDirection.LONG:
            action = "BUY"
        elif direction == SignalDirection.SHORT:
            action = "SELL"
        else:
            action = "HOLD"
    elif strength >= 10:
        action = "WATCH"
    else:
        action = "HOLD"

    risk_level = determine_risk_level(strength, confidence, market_context)
    reasoning  = generate_reasoning(signals, analysis, market_context)
    entry_price, stop_loss, take_profit, tp1_price, sl_source, tp_source = calculate_levels(
        symbol, direction, market_context, signals, config
    )

    return TradingRecommendation(
        symbol=symbol,
        action=action,
        direction=direction,
        overall_strength=strength,
        confidence=confidence,
        risk_level=risk_level,
        signals_count=len(signals),
        supporting_signals=supporting_signals,
        conflicting_signals=conflicting_signals,
        market_context=market_context,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        tp1_price=tp1_price,
        sl_source=sl_source,
        tp_source=tp_source,
        reasoning=reasoning,
        timestamp=datetime.now(),
    )
