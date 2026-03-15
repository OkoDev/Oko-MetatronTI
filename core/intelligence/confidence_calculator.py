"""
Расчёт уверенности (confidence) на основе поддерживающих / конфликтующих сигналов.
Извлечено из TradingIntelligence._calculate_advanced_confidence.
"""
import numpy as np
from typing import List

from core.signal_models import SignalData, MarketContext, SignalType


def calculate_advanced_confidence(
    supporting_signals: List[SignalData],
    conflicting_signals: List[SignalData],
    market_context: MarketContext,
) -> float:
    """
    Уверенность по поддерживающим сигналам и штраф за конфликт.
    Не усредняем по всем (long+short) — иначе при 2 LONG 0.9 и 2 SHORT 0.9 получали бы 0.9.
    """
    total = len(supporting_signals) + len(conflicting_signals)
    if total == 0:
        return 0.5

    if supporting_signals:
        signal_confidence = float(np.mean([s.confidence for s in supporting_signals]))
    else:
        signal_confidence = 0.5

    conflict_penalty = len(conflicting_signals) / total
    signal_confidence *= (1.0 - 0.5 * conflict_penalty)

    context_factor = 1.0
    if market_context.volume_24h > 0:
        volume_factor = min(market_context.volume_24h / 1000000, 2.0)
        context_factor *= (0.8 + 0.2 * volume_factor)
    if market_context.volatility and market_context.volatility > 10:
        context_factor *= 0.9
    if abs(market_context.price_change_24h) > 5:
        context_factor *= 1.1

    # CONFLUENCE сигналы содержат N факторов — каждый засчитывается отдельно
    effective_count = total
    for sig in supporting_signals + conflicting_signals:
        if getattr(sig, "signal_type", None) == SignalType.CONFLUENCE:
            n_factors = len((sig.data or {}).get("factors", []))
            if n_factors > 1:
                effective_count += n_factors - 1
    # Минимум 0.5 при 1 сигнале — не убиваем confidence одиночных качественных сигналов (WT_B, CONFLUENCE)
    # При 5 сигналах = 1.0, при 7+ = 1.5 (бонус за сильную конфлюэнцию)
    signal_count_factor = min(0.5 + effective_count / 10.0, 1.5)
    context_factor *= signal_count_factor

    return min(signal_confidence * context_factor, 1.0)
