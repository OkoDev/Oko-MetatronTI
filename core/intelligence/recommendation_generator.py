"""
Генерация торговых рекомендаций: уровень риска, обоснование, SL/TP уровни.
Извлечено из TradingIntelligence._generate_recommendation, _determine_risk_level,
_generate_reasoning и _calculate_levels.
"""
import logging
from datetime import datetime, timezone
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
      0. Swing LOW/HIGH — реальная рыночная структура (20 баров) + буфер 0.3%
      1. Под S1/R1 — ближайший пивот поддержки/сопротивления из PIVOT_REVERSAL сигналов
      2. Под FVG — Fair Value Gap midpoint из данных сигналов (если есть)
      3. Под TSL-линией индикатора (trendup/trenddown)
      4. ATR(14) × динамический множитель / волатильность / фиксированный 2%

    Зажим: [sl_min_pct=0.5%, sl_max_pct=3.0%] (config: sl_tp.sl_min_pct / sl_max_pct)

    Returns:
        (entry_price, stop_loss, take_profit, tp1_price, sl_source, tp_source)
    """
    current_price = market_context.current_price
    if current_price == 0:
        return None, None, None, None, "", ""

    entry_price = current_price
    sl_cfg     = config.get("trading", {}).get("sl_tp", {})
    atr_mult   = sl_cfg.get("atr_multiplier", 1.2)
    sl_min     = sl_cfg.get("sl_min_pct", 0.5)   # DEV-05: зажим [0.5%, 3%]
    sl_max     = sl_cfg.get("sl_max_pct", 3.0)
    atr_dyn    = sl_cfg.get("atr_dynamic", True)
    atr_exp    = sl_cfg.get("atr_expand_threshold", 1.3)
    atr_con    = sl_cfg.get("atr_contract_threshold", 0.8)
    struct_buf = sl_cfg.get("struct_sl_buffer_pct", 0.3)

    is_long  = direction == SignalDirection.LONG
    is_short = direction == SignalDirection.SHORT

    # ATR динамика
    if atr_dyn and market_context.atr and market_context.atr_slow:
        ratio = market_context.atr / market_context.atr_slow
        if ratio > atr_exp:
            atr_mult = round(atr_mult * 0.85, 3)
        elif ratio < atr_con:
            atr_mult = round(min(atr_mult * 1.1, 1.5), 3)

    # ATR / волатильность baseline (используется как fallback шаг 4)
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

    # ── -1. RANGE BOUNCE — pivot-based SL/TP для RANGE режима (ARCH-55/DEV-110) ─
    # Имеет наивысший приоритет: если pivot подходит — возвращаем сразу
    _rb_cfg = config.get("trading", {}).get("range_bounce", {})
    if (_rb_cfg.get("enabled", False)
            and getattr(market_context, "regime", "") == "RANGE"
            and getattr(market_context, "pivot_cache_1d_1w", None)):
        try:
            from core.smc.sl_tp_calculator import calc_range_bounce_sl_tp
            rb_sl, rb_tp, rb_r, rb_reject = calc_range_bounce_sl_tp(
                direction="LONG" if is_long else "SHORT",
                entry=entry_price,
                pivot_cache=market_context.pivot_cache_1d_1w,
                symbol=symbol,
                sl_buffer_pct=_rb_cfg.get("sl_buffer_pct", 0.003),
                min_tp_r=_rb_cfg.get("min_tp_r", 3.5),
                max_sl_dist_pct=_rb_cfg.get("max_sl_dist_pct", 0.02),
            )
            if rb_reject is None and rb_sl and rb_tp:
                logger.info("[ARCH-55] %s RANGE BOUNCE SL=%.6g TP=%.6g R=%.1f", symbol, rb_sl, rb_tp, rb_r)
                return entry_price, rb_sl, rb_tp, rb_tp, "range_bounce:pivot", "range_bounce:pivot"
            logger.debug("[ARCH-55] %s RANGE BOUNCE rejected: %s → fallback standard", symbol, rb_reject)
        except Exception as _e55:
            logger.debug("[ARCH-55] range_bounce error: %s", _e55)

    # ── 0. Swing LOW/HIGH — реальная рыночная структура (первый приоритет) ─
    swing_level = market_context.swing_low if is_long else market_context.swing_high
    if swing_level and swing_level > 0:
        if is_long and swing_level < entry_price:
            swing_sl_pct = (entry_price - swing_level) / entry_price * 100 + struct_buf
            if sl_min <= swing_sl_pct <= sl_max:
                sl_pct    = swing_sl_pct
                sl_source = f"swing_low:{swing_level:.6g}"
        elif is_short and swing_level > entry_price:
            swing_sl_pct = (swing_level - entry_price) / entry_price * 100 + struct_buf
            if sl_min <= swing_sl_pct <= sl_max:
                sl_pct    = swing_sl_pct
                sl_source = f"swing_high:{swing_level:.6g}"

    # ── 1. S1/R1 — ближайший пивот поддержки/сопротивления ───────────────
    # Источник: PIVOT_REVERSAL сигналы (data["level"] + data["pivot_type"])
    if "swing_" not in sl_source:
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
            s1_sl_pct    = abs(entry_price - nearest) / entry_price * 100 + struct_buf
            if sl_min <= s1_sl_pct <= sl_max:
                sl_pct    = s1_sl_pct
                sl_source = f"s1:{pivot_type}:{nearest:.6g}"

    # ── 2. FVG — Fair Value Gap midpoint из данных сигналов ───────────────
    # Источник: сигналы с data["has_fvg"]=True и data["fvg_entry"] (PIVOT_REVERSAL)
    if "swing_" not in sl_source and "s1:" not in sl_source:
        for sig in signals:
            if not sig.data.get("has_fvg"):
                continue
            fvg_price = sig.data.get("fvg_entry")
            fvg_type  = sig.data.get("fvg_type", "")
            if not fvg_price:
                continue
            if is_long and fvg_type == "BULL" and fvg_price < entry_price:
                fvg_sl_pct = (entry_price - fvg_price) / entry_price * 100 + struct_buf
                if sl_min <= fvg_sl_pct <= sl_max:
                    sl_pct    = fvg_sl_pct
                    sl_source = f"fvg_bull:{fvg_price:.6g}"
                    break
            elif is_short and fvg_type == "BEAR" and fvg_price > entry_price:
                fvg_sl_pct = (fvg_price - entry_price) / entry_price * 100 + struct_buf
                if sl_min <= fvg_sl_pct <= sl_max:
                    sl_pct    = fvg_sl_pct
                    sl_source = f"fvg_bear:{fvg_price:.6g}"
                    break

    # ── 2.5. SMC Order Block — зона институциональных ордеров (ARCH-17) ──
    if "swing_" not in sl_source and "s1:" not in sl_source and "fvg_" not in sl_source:
        smc = getattr(market_context, "smc_context", None)
        if smc is not None:
            ob = smc.nearest_bull_ob if is_long else smc.nearest_bear_ob
            if ob is not None:
                ob_level = ob.bottom if is_long else ob.top
                if is_long and 0 < ob_level < entry_price:
                    ob_sl_pct = (entry_price - ob_level) / entry_price * 100 + struct_buf
                    if sl_min <= ob_sl_pct <= sl_max:
                        sl_pct    = ob_sl_pct
                        sl_source = f"smc_ob:{ob_level:.6g}"
                elif is_short and ob_level > entry_price:
                    ob_sl_pct = (ob_level - entry_price) / entry_price * 100 + struct_buf
                    if sl_min <= ob_sl_pct <= sl_max:
                        sl_pct    = ob_sl_pct
                        sl_source = f"smc_ob:{ob_level:.6g}"

    # ── 3. TSL-линия — если swing, S1 и FVG недоступны ────────────────────
    if "swing_" not in sl_source and "s1:" not in sl_source and "fvg_" not in sl_source and "smc_ob" not in sl_source:
        tsl_line = market_context.tsl_trendup if is_long else market_context.tsl_trenddown
        if tsl_line and tsl_line > 0:
            if is_long and tsl_line < entry_price:
                tsl_dist_pct = (entry_price - tsl_line) / entry_price * 100
                tsl_sl_pct   = tsl_dist_pct + struct_buf
                if sl_min <= tsl_sl_pct <= sl_max:
                    sl_pct    = tsl_sl_pct
                    sl_source = "tsl_line:trendup"
            elif is_short and tsl_line > entry_price:
                tsl_dist_pct = (tsl_line - entry_price) / entry_price * 100
                tsl_sl_pct   = tsl_dist_pct + struct_buf
                if sl_min <= tsl_sl_pct <= sl_max:
                    sl_pct    = tsl_sl_pct
                    sl_source = "tsl_line:trenddown"

    # ── TP: ATR × fallback_rr (реальный уровень устанавливается постобработкой в monitoring.py)
    fallback_rr = sl_cfg.get("tp_fallback_rr", 3.0)
    tp1_pct = sl_pct * fallback_rr
    if is_long:
        stop_loss  = entry_price * (1 - sl_pct / 100)
        tp1_price  = entry_price * (1 + tp1_pct / 100)
    else:
        stop_loss  = entry_price * (1 + sl_pct / 100)
        tp1_price  = entry_price * (1 - tp1_pct / 100)

    take_profit = tp1_price
    tp_source   = "atr_fallback"  # ARCH-58: явная метка, monitoring.py перезапишет на pivot_*

    # DEV-35: R:R cap — ограничить нереалистичный R:R (PAXG 24x → 6x, CRCLX 32x → 6x)
    max_rr = sl_cfg.get("max_rr", 0)
    if max_rr > 0 and stop_loss and take_profit:
        sl_dist    = max(abs(stop_loss - entry_price), 1e-8)
        actual_rr  = abs(take_profit - entry_price) / sl_dist
        if actual_rr > max_rr:
            take_profit = (entry_price + sl_dist * max_rr) if is_long else (entry_price - sl_dist * max_rr)
            tp1_price   = take_profit  # синхронизируем
            tp_source   = f"{tp_source}|capped_rr_{max_rr:.1f}"

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
        timestamp=datetime.now(timezone.utc),  # DEV-49
    )
