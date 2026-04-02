"""
cascade_tsl.py — ARCH-62 Шаг 1: логика каскадного TSL, вынесенная из trade_simulator.

Содержит gate-функции:
  - get_cascade_cap_tf()      — ARCH-62: cap_tf="1h" после tp1_hit, не эскалировать до 4h
  - should_skip_degradation() — DEV-123: anti-degradation gate для ракет R >= N
  - check_r_gradient_drop()   — DEV-91: R-gradient drop как реальный триггер де-эскалации
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_cascade_cap_tf(tp1_hit: bool, cfg=None) -> Optional[str]:
    """
    ARCH-62 Шаг 1: при tp1_hit=True ограничиваем каскад сверху на "1h".

    После фиксации TP1 (70% позиции) остаток под TSL.
    До tp1_hit: 15m → 1h → 4h (обычная эскалация).
    После tp1_hit: max = 1h (4h слишком широкий → cap 32% вместо 55%).

    Данные: DUAL_TP TSL tp1_hit → cap=32% avg_maxR=6.5R
            После cap_1h ожидаем ~55% (аналог DUAL_TSL tp1_hit).
    """
    if not tp1_hit:
        return None  # нет ограничения — обычный каскад до 4h
    cap = "1h"
    if cfg is not None:
        try:
            cap = cfg.get("trading.cascade_tsl_opts.cap_tf_after_tp1", "1h")
        except Exception:
            pass
    return cap


def should_skip_degradation(
    current_r: float,
    max_r_achieved: float,
    direction: str,
    wt1_1h: Optional[float],
    wt1_4h: Optional[float],
    cfg=None,
) -> bool:
    """
    DEV-123: anti-degradation gate для ракет.

    Если сделка сильная (current_r >= no_degrade_above_r) —
    НЕ деградируем TSL даже при кратком касании WT OB/OS.
    WT касание при тренде = консолидация, не разворот.

    Данные: B3 (degraded=None) → 74% cap.
            Все с degraded=True → 32-41% cap при потенциале 20-42R.
            335 сделок, ~500R упущено из-за преждевременной деградации.
    """
    no_degrade_r = 5.0
    if cfg is not None:
        try:
            no_degrade_r = float(cfg.get("trading.cascade_tsl_opts.no_degrade_above_r", 5.0))
        except Exception:
            pass

    if current_r < no_degrade_r:
        return False  # обычная логика деградации

    # Сделка сильная — деградируем только при явном развороте тренда,
    # не при касании OB/OS (это признак консолидации в сильном тренде)
    logger.info(
        "[cascade_tsl] DEV-123: R=%.1f >= %.1f → skip degradation gate "
        "(WT1_1h=%s WT1_4h=%s direction=%s)",
        current_r, no_degrade_r,
        f"{wt1_1h:.1f}" if wt1_1h is not None else "?",
        f"{wt1_4h:.1f}" if wt1_4h is not None else "?",
        direction,
    )
    return True


def check_r_gradient_drop(
    current_r: float,
    max_r_achieved: float,
    cfg=None,
) -> bool:
    """
    DEV-91: R-gradient drop — реальный триггер де-эскалации TSL.

    Условие: пик >= peak_min_r AND текущий R откатил > rollback_pct от пика.
    Это реальный сигнал ослабления импульса, в отличие от WT касания OB/OS.

    Было: shadow mode (только лог, не действовал).
    Стало: реальный gate де-эскалации.

    Данные: r_gradient_drop_logged=None у всех 60 ракет →
            shadow логирование не работало (баг в логе), gate тоже не работал.
    """
    peak_min_r = 3.0
    rollback_pct = 0.85  # если откатил до < 85% от пика → деградируем
    if cfg is not None:
        try:
            peak_min_r = float(cfg.get("trading.cascade_tsl_opts.r_gradient_peak_min_r", 3.0))
            rollback_pct = float(cfg.get("trading.cascade_tsl_opts.r_gradient_rollback_pct", 0.85))
        except Exception:
            pass

    if max_r_achieved < peak_min_r:
        return False
    if current_r <= 0:
        return False

    drop_triggered = current_r < max_r_achieved * rollback_pct
    if drop_triggered:
        logger.info(
            "[cascade_tsl] DEV-91: R-gradient drop peak=%.1fR cur=%.1fR "
            "(%.0f%% от пика < %.0f%%) → де-эскалация",
            max_r_achieved, current_r,
            current_r / max_r_achieved * 100 if max_r_achieved > 0 else 0,
            rollback_pct * 100,
        )
    return drop_triggered
