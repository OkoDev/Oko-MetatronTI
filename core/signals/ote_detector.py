"""
OTE Detector — Multi-Timeframe Optimal Trade Entry (ICT 0.618–0.786 Fibonacci).

Архитектура MTF OTE:
    zone_tfs (1h / 4h / 1d): каждый TF имеет собственный BOS→impulse→Fib zone.
    trigger_tf (15m):         WT cross-up/down ВНУТРИ зоны старшего TF.

Конфлюенция:
    1h OTE                    → base signal (str=65)
    4h OTE тоже подтверждает  → +15
    1d OTE тоже подтверждает  → +20
    origin_break = BOS        → +10 (продолжение тренда, не разворот)
    tight zone 0.618–0.705    → +10 (ICT "sweet spot")
    max strength              = 100

Зона для WT-проверки:
    Берётся зона НАИБОЛЕЕ СТАРШЕГО подтверждающего TF.
    Если 4h подтверждает — WT cross проверяется внутри 4h зоны.
    Это жёстче, но точнее (1d зона ≈ 2-5%, 1h ≈ 0.5-1%).

Shadow mode (ote_shadow_mode: true в config.yaml):
    Детектор вычисляет, но не возвращает SignalData.
    Только INFO-лог. ARCH ревьюирует через 2 недели.

API оптимизация:
    Вызывающий код передаёт готовые SMCContext (уже вычислены в ARCH-51 блоке).
    Нет повторных fetch/analyze_smc вызовов.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.signals.signal_models import SignalData, SignalDirection, SignalType
from core.smc.models import SMCContext
from core.smc.fibonacci import FibZone

logger = logging.getLogger(__name__)

# Приоритет TF: высший → низший. Первый найденный = primary zone.
# (tf, strength_bonus_if_confirms)
_ZONE_TF_PRIORITY: List[Tuple[str, int]] = [
    ("1d", 20),
    ("4h", 15),
    ("1h",  0),   # минимальный TF для OTE сигнала
]

# Tight OTE "sweet spot" — бонус к strength
_TIGHT_OTE_LOW  = 0.618
_TIGHT_OTE_HIGH = 0.705


def detect_ote_signal(
    df_trigger: pd.DataFrame,
    symbol: str,
    smc_contexts: Dict[str, SMCContext],
    trigger_tf: str = "15m",
    max_bars_lookback: int = 5,
    shadow_mode: bool = True,
    zone_tf_priority: Optional[List[Tuple[str, int]]] = None,
) -> Optional[SignalData]:
    """
    Детектирует MTF OTE сигнал.

    Args:
        df_trigger:   OHLCV trigger TF (15m) с cross_up/cross_down (calculate_wt применён).
        symbol:       торговая пара.
        smc_contexts: dict {tf: SMCContext} — min {"1h": ...}, опц. "4h", "1d".
                      Вычисляются один раз в ARCH-51+OTE блоке trading_intelligence.
        trigger_tf:   имя trigger TF (для логирования).
        max_bars_lookback: окно поиска WT cross в зоне (trigger TF барах).
        shadow_mode:  True → только logging, SignalData не возвращается.

    Returns:
        SignalData или None (всегда None при shadow_mode=True).
    """
    if df_trigger is None or len(df_trigger) < 30:
        return None

    # ── Собираем подтверждающие TF ────────────────────────────────────────
    # confirmed: [(tf, FibZone, bonus)] в порядке убывания приоритета
    confirmed: List[Tuple[str, FibZone, int]] = []

    _priority = zone_tf_priority if zone_tf_priority is not None else _ZONE_TF_PRIORITY
    for tf, bonus in _priority:
        ctx = smc_contexts.get(tf)
        if ctx is None:
            continue
        fib = ctx.fibonacci
        if fib is None or fib.active_ote is None:
            continue
        zone = fib.active_ote
        if not zone.price_in_ote:
            continue
        confirmed.append((tf, zone, bonus))

    if not confirmed:
        return None

    # Минимум: должен быть хоть один стандартный TF (1h, 4h или 1d)
    # В порядке приоритета первый = самый старший
    primary_tf, primary_zone, _ = confirmed[0]
    direction = SignalDirection.LONG if primary_zone.direction == "LONG" else SignalDirection.SHORT

    # ── WT cross на trigger TF (15m) в зоне СТАРШЕГО подтверждающего TF ──
    cross_col = "cross_up" if direction == SignalDirection.LONG else "cross_down"
    if cross_col not in df_trigger.columns:
        return None

    tail        = df_trigger.tail(max_bars_lookback)
    cross_vals  = tail[cross_col].values
    close_vals  = tail["close"].values

    has_cross_in_zone = any(
        not np.isnan(v)
        and primary_zone.ote_bottom <= close_vals[i] <= primary_zone.ote_top
        for i, v in enumerate(cross_vals)
    )
    if not has_cross_in_zone:
        return None

    # ── Strength ──────────────────────────────────────────────────────────
    strength = 65  # base (1h или любой один TF)

    # Конфлюенция: каждый старший TF добавляет бонус
    confirmed_tfs = [tf for tf, _, _ in confirmed]
    for _, _, bonus in confirmed:
        strength += bonus

    # BOS > CHoCH
    ob = primary_zone.origin_break
    is_bos = ob is not None and ob.is_bos
    if is_bos:
        strength += 10

    # Tight OTE
    cur     = float(df_trigger["close"].iloc[-1])
    impulse = primary_zone.impulse_high - primary_zone.impulse_low
    tight_ote  = False
    fib_ratio: Optional[float] = None
    if impulse > 0:
        if direction == SignalDirection.LONG:
            fib_ratio = (primary_zone.impulse_high - cur) / impulse
        else:
            fib_ratio = (cur - primary_zone.impulse_low) / impulse
        tight_ote = _TIGHT_OTE_LOW <= fib_ratio <= _TIGHT_OTE_HIGH
        if tight_ote:
            strength += 10

    strength   = min(strength, 100)
    confidence = round(strength / 100.0, 2)

    # ── Logging ───────────────────────────────────────────────────────────
    tfs_str = "+".join(confirmed_tfs)
    logger.info(
        "[%s] OTE %s [%s→%s]: zone=%.5g–%.5g str=%d bos=%s tight=%s ratio=%s shadow=%s",
        symbol, direction.value, tfs_str, trigger_tf,
        primary_zone.ote_bottom, primary_zone.ote_top,
        strength, is_bos, tight_ote,
        f"{fib_ratio:.3f}" if fib_ratio is not None else "?",
        shadow_mode,
    )

    if shadow_mode:
        return None

    # ── SignalData ─────────────────────────────────────────────────────────
    return SignalData(
        symbol=symbol,
        signal_type=SignalType.OTE_SIGNAL,
        direction=direction,
        strength=strength,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
        data={
            "ote_bottom":    primary_zone.ote_bottom,
            "ote_top":       primary_zone.ote_top,
            "ote_midpoint":  primary_zone.ote_midpoint,
            "impulse_high":  primary_zone.impulse_high,
            "impulse_low":   primary_zone.impulse_low,
            "fib_ratio":     round(fib_ratio, 4) if fib_ratio is not None else None,
            "tight_ote":     tight_ote,
            "origin_break":  ob.break_type.value if ob is not None else "unknown",
            "is_bos":        is_bos,
            "confirmed_tfs": confirmed_tfs,   # ["1d", "4h", "1h"] — какие TF подтвердили
            "primary_tf":    primary_tf,
            "trigger_tf":    trigger_tf,
        },
        description=(
            f"OTE {'LONG' if direction == SignalDirection.LONG else 'SHORT'} "
            f"[{tfs_str}→{trigger_tf}]: зона {primary_zone.ote_bottom:.5g}–{primary_zone.ote_top:.5g}"
            + (" [tight]" if tight_ote else "")
        ),
        interpretation=(
            f"MTF конфлюенция OTE: {tfs_str}. "
            f"Зона отката 61.8–78.6% от {primary_tf} импульса после "
            f"{'BOS' if is_bos else 'CHoCH'}. "
            f"WT cross на {trigger_tf} подтверждает оптимальный вход."
        ),
    )
