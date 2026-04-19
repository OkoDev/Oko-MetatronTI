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

# DEV-85: Wide OTE only [0.705–0.786] — tight [0.618–0.705] исключён (бэктест WR=18.2%)
_OTE_FULL_LOW  = 0.618   # граница полной OTE зоны (для fib_ratio логирования)
_WIDE_OTE_MIN  = 0.705   # минимальный retrace для wide зоны (только этот диапазон торгуется)


def detect_ote_signal(
    df_trigger: pd.DataFrame,
    symbol: str,
    smc_contexts: Dict[str, SMCContext],
    trigger_tf: str = "15m",
    max_bars_lookback: int = 5,
    shadow_mode: bool = True,
    zone_tf_priority: Optional[List[Tuple[str, int]]] = None,
    df_trend_ref: Optional[pd.DataFrame] = None,
    ote_zone_min_fib: float = _WIDE_OTE_MIN,
    require_wt_in_obos: bool = False,
) -> Optional[SignalData]:
    """
    Детектирует MTF OTE сигнал.

    Args:
        df_trigger:   OHLCV trigger TF (15m) с cross_up/cross_down (calculate_wt применён).
        symbol:       торговая пара.
        smc_contexts: dict {tf: SMCContext} — min {"1h": ...}, опц. "4h", "1d".
                      Вычисляются один раз в ARCH-51+OTE блоке trading_intelligence.
        df_trend_ref: (DEV-85) DataFrame с "trend" колонкой (1h df, calculate_trend применён).
                      Используется для ATR-trend direction gate. Если None — gate пропускается.
        trigger_tf:   имя trigger TF (для логирования).
        max_bars_lookback: окно поиска WT cross в зоне (trigger TF барах).
        shadow_mode:  True → только logging, SignalData не возвращается.
        ote_zone_min_fib: нижняя граница retrace в долях (0.705=wide, 0.618=golden, 0.5=mid).
                          Зона входа: [ote_bottom(0.786), этот уровень].
                          Меньшее значение = шире зона = выше цена при откате.
        require_wt_in_obos: если True — WT cross должен происходить когда wt2 в OS (LONG)
                            или OB (SHORT). Фильтрует случайные кресты в нейтральной зоне.

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

    # ── DEV-85: вычислить impulse ПЕРЕД проверкой зоны (нужен для wide gate) ──
    impulse = primary_zone.impulse_high - primary_zone.impulse_low
    if impulse <= 0:
        return None

    # Граница зоны по параметру ote_zone_min_fib (верхняя по откату = меньший retrace)
    # LONG: цена <= impulse_high - impulse * fib (глубже в откат)
    # SHORT: цена >= impulse_low + impulse * fib (глубже в откат)
    if direction == SignalDirection.LONG:
        _zone_boundary = primary_zone.impulse_high - impulse * ote_zone_min_fib
    else:
        _zone_boundary = primary_zone.impulse_low + impulse * ote_zone_min_fib

    # ── WT cross на trigger TF (15m) в зоне СТАРШЕГО подтверждающего TF ──
    cross_col = "cross_up" if direction == SignalDirection.LONG else "cross_down"
    if cross_col not in df_trigger.columns:
        return None

    tail        = df_trigger.tail(max_bars_lookback)
    cross_vals  = tail[cross_col].values
    close_vals  = tail["close"].values
    wt2_vals    = tail["wt2"].values if "wt2" in tail.columns else None

    if direction == SignalDirection.LONG:
        has_cross_in_zone = any(
            not np.isnan(v)
            and primary_zone.ote_bottom <= close_vals[i] <= _zone_boundary
            for i, v in enumerate(cross_vals)
        )
    else:
        has_cross_in_zone = any(
            not np.isnan(v)
            and _zone_boundary <= close_vals[i] <= primary_zone.ote_top
            for i, v in enumerate(cross_vals)
        )
    if not has_cross_in_zone:
        return None

    # ── WT в OB/OS фильтр (require_wt_in_obos) ───────────────────────────
    # Логика: cross_up = WT УЖЕ разворачивается из OS → в момент кросса wt2 может быть выше -60.
    # Правильно: проверять что в последних max_bars_lookback*3 барах ДО current был wt2 < -60
    # (т.е. разворот произошёл ИЗ OS, а не в нейтральной зоне).
    if require_wt_in_obos and wt2_vals is not None:
        needed_zone = "OS" if direction == SignalDirection.LONG else "OB"
        # Расширенное окно: ищем экстремум за последние 15 баров (3× lookback)
        wt2_extended = df_trigger["wt2"].tail(max_bars_lookback * 3).values if "wt2" in df_trigger.columns else wt2_vals
        has_obos = any(
            not np.isnan(v) and (
                (needed_zone == "OS" and v <= -60) or
                (needed_zone == "OB" and v >= 60)
            )
            for v in wt2_extended
        )
        if not has_obos:
            logger.debug(
                "[%s] OTE %s отклонён: WT2 не разворачивался из %s за последние %d баров (min/max=%.1f)",
                symbol, direction.value, needed_zone, max_bars_lookback * 3,
                float(np.nanmin(wt2_extended) if needed_zone == "OS" else np.nanmax(wt2_extended)),
            )
            return None

    # ── DEV-85: ATR-trend direction gate (1h df) ──────────────────────────
    # Требуем совпадение тренда на старшем TF. Если 1h тренд против — зона stale или
    # импульс не валиден. Пропускаем если trend колонки нет (graceful degradation).
    if df_trend_ref is not None and "trend" in df_trend_ref.columns and len(df_trend_ref) > 0:
        ref_trend = df_trend_ref["trend"].iloc[-1]
        expected  = 1 if direction == SignalDirection.LONG else -1
        if ref_trend == -expected:   # тренд ПРОТИВ сигнала → отклонить
            logger.debug(
                "[%s] OTE %s отклонён: 1h trend=%s против направления", symbol, direction.value, ref_trend
            )
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

    # fib_ratio для логирования (tight бонус убран — DEV-85)
    cur       = float(df_trigger["close"].iloc[-1])
    fib_ratio: Optional[float] = None
    if direction == SignalDirection.LONG:
        fib_ratio = (primary_zone.impulse_high - cur) / impulse
    else:
        fib_ratio = (cur - primary_zone.impulse_low) / impulse

    strength   = min(strength, 100)
    confidence = round(strength / 100.0, 2)

    # ── Logging ───────────────────────────────────────────────────────────
    tfs_str = "+".join(confirmed_tfs)
    logger.info(
        "[%s] OTE %s [%s→%s]: zone=%.5g–%.5g(fib=%.3f) str=%d bos=%s ratio=%s obos=%s shadow=%s",
        symbol, direction.value, tfs_str, trigger_tf,
        primary_zone.ote_bottom, _zone_boundary, ote_zone_min_fib,
        strength, is_bos,
        f"{fib_ratio:.3f}" if fib_ratio is not None else "?",
        require_wt_in_obos,
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
            "fib_ratio":        round(fib_ratio, 4) if fib_ratio is not None else None,
            "ote_zone_min_fib": ote_zone_min_fib,   # граница зоны (0.705/0.618/0.5)
            "origin_break":     ob.break_type.value if ob is not None else "unknown",
            "is_bos":           is_bos,
            "confirmed_tfs":    confirmed_tfs,
            "primary_tf":       primary_tf,
            "trigger_tf":       trigger_tf,
            "wt_in_obos":       require_wt_in_obos,
        },
        description=(
            f"OTE {'LONG' if direction == SignalDirection.LONG else 'SHORT'} "
            f"[{tfs_str}→{trigger_tf}]: зона {primary_zone.ote_bottom:.5g}–{_zone_boundary:.5g}"
            f" [ratio={fib_ratio:.3f}]" if fib_ratio else ""
        ),
        interpretation=(
            f"MTF конфлюенция OTE: {tfs_str}. "
            f"Wide зона отката 70.5–78.6% от {primary_tf} импульса после "
            f"{'BOS' if is_bos else 'CHoCH'}. "
            f"WT cross на {trigger_tf} подтверждает оптимальный вход."
        ),
    )
