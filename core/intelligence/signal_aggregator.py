"""
Агрегация и взвешивание сигналов.
Извлечено из TradingIntelligence._analyze_signals_advanced и _calculate_adaptive_weighted_strength.
"""
import logging
from typing import Dict, List, Any

from core.signal_models import SignalData, SignalDirection, SignalType, MarketContext

logger = logging.getLogger(__name__)


def calculate_adaptive_weighted_strength(
    signals: List[SignalData],
    signal_weights: Dict,
) -> int:
    """
    Взвешенная сила: вклад сигнала = weight по quality_score (strength * confidence).
    Слабые сигналы учитываются, но с меньшим весом.
    """
    if not signals:
        return 0

    total_weighted_strength = 0.0
    total_weight = 0.0

    for signal in signals:
        base_weight = signal_weights.get(signal.signal_type, 0.1)
        quality = (signal.strength / 100.0) * signal.confidence
        effective_weight = base_weight * max(quality, 0.05)
        total_weighted_strength += signal.strength * effective_weight
        total_weight += effective_weight

    if total_weight <= 0:
        return 0
    return min(int(round(total_weighted_strength / total_weight)), 100)


def analyze_signals_advanced(
    signals: List[SignalData],
    market_context: MarketContext,
    signal_weights: Dict,
    thresholds: Dict,
    confidence_fn,
) -> Dict[str, Any]:
    """
    Продвинутый анализ сигналов с учётом исторической производительности.

    Args:
        signals: список сигналов от всех детекторов
        market_context: контекст рынка
        signal_weights: веса по типу сигнала (адаптивные)
        thresholds: пороги из конфига (conflict_threshold, ...)
        confidence_fn: callable(supporting, conflicting, context) → float
    Returns:
        dict: strength, confidence, direction, supporting_signals, conflicting_signals, total_signals
    """
    if not signals:
        return {
            "strength": 0, "confidence": 0, "direction": SignalDirection.NEUTRAL,
            "supporting_signals": [], "conflicting_signals": [], "total_signals": 0,
        }

    long_signals = [s for s in signals if s.direction == SignalDirection.LONG]
    short_signals = [s for s in signals if s.direction == SignalDirection.SHORT]

    long_strength  = calculate_adaptive_weighted_strength(long_signals,  signal_weights)
    short_strength = calculate_adaptive_weighted_strength(short_signals, signal_weights)

    conflict_threshold = thresholds.get("conflict_threshold", 0.3)
    dominant = max(long_strength, short_strength)
    conflict_ratio = (abs(long_strength - short_strength) / dominant) if dominant > 0 else 1.0

    if long_strength > short_strength:
        direction          = SignalDirection.LONG
        strength           = long_strength
        supporting_signals = long_signals
        conflicting_signals = short_signals
    elif short_strength > long_strength:
        direction          = SignalDirection.SHORT
        strength           = short_strength
        supporting_signals = short_signals
        conflicting_signals = long_signals
    else:
        direction           = SignalDirection.NEUTRAL
        strength            = max(long_strength, short_strength)
        supporting_signals  = []
        conflicting_signals = signals

    # ── MTF_BIAS tie-breaker ────────────────────────────────────────────────
    _bias_sigs = [
        s for s in signals
        if s.signal_type == SignalType.MTF_BIAS
        and s.direction != SignalDirection.NEUTRAL
        and s.strength >= 70
    ]
    if _bias_sigs and (direction == SignalDirection.NEUTRAL or (dominant > 0 and conflict_ratio < conflict_threshold)):
        _bias_dir = _bias_sigs[0].direction
        direction          = _bias_dir
        supporting_signals = [s for s in signals if s.direction == _bias_dir]
        conflicting_signals = [s for s in signals if s.direction not in (_bias_dir, SignalDirection.NEUTRAL)]
        logger.debug("[%s] MTF_BIAS override → %s str=%d (conflict_ratio=%.2f)",
                     signals[0].symbol if signals else "?",
                     _bias_dir.value, _bias_sigs[0].strength, conflict_ratio)
        long_str  = sum(s.strength for s in signals if s.direction == SignalDirection.LONG)
        short_str = sum(s.strength for s in signals if s.direction == SignalDirection.SHORT)
        dominant      = max(long_str, short_str)
        conflict_ratio = (abs(long_str - short_str) / dominant) if dominant > 0 else 1.0

    # Плавный конфликт
    if dominant > 0 and conflict_ratio < 0.05:
        direction           = SignalDirection.NEUTRAL
        supporting_signals  = []
        conflicting_signals = signals
    elif dominant > 0 and conflict_ratio < conflict_threshold:
        pass  # direction сохраняется, штраф confidence ниже

    confidence = confidence_fn(supporting_signals, conflicting_signals, market_context)
    if dominant > 0 and conflict_ratio < 0.05:
        confidence *= 0.5
    elif dominant > 0 and conflict_ratio < conflict_threshold:
        confidence *= (0.6 + conflict_ratio)

    return {
        "strength":           strength,
        "confidence":         confidence,
        "direction":          direction,
        "supporting_signals": supporting_signals,
        "conflicting_signals": conflicting_signals,
        "total_signals":      len(signals),
    }
