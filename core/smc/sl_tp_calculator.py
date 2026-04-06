"""
DEV-110 / ARCH-66: RANGE BOUNCE SL/TP Calculator (04.04.2026)

Вычисляет SL/TP для RANGE режима на основе ближайших пивотных уровней.
Используется только когда:
  - regime == "RANGE"
  - signal_type in ("confluence", "watch_list_breach")
  - timeframe == "15m"
  - entry ≤ max_sl_dist_pct от ближайшего противоположного пивота
  - TP_R ≥ min_tp_r
"""
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def calc_range_bounce_sl_tp(
    direction: str,
    entry: float,
    pivot_cache: dict,
    symbol: str,
    sl_buffer_pct: float = 0.003,
    min_tp_r: float = 3.5,
    max_sl_dist_pct: float = 0.02,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[str]]:
    """
    Рассчитывает SL и TP для RANGE BOUNCE стратегии.

    Args:
        direction: "LONG" или "SHORT"
        entry: цена входа
        pivot_cache: словарь {f"{symbol}_1D": {PP, R1, R2, S1, S2,...}, f"{symbol}_1W": {...}}
        symbol: тикер (для поиска в pivot_cache)
        sl_buffer_pct: буфер за пивотом для SL (0.3% по умолчанию)
        min_tp_r: минимальный RR для принятия сигнала (3.5 по умолчанию)
        max_sl_dist_pct: максимальное расстояние до SL пивота (2% = entry у края)

    Returns:
        (sl, tp, tp_r, reject_reason)
        reject_reason=None означает успех
    """
    if not entry or entry <= 0:
        return None, None, None, "entry=0"

    levels = []
    for tf in ("1D", "1W"):
        piv = pivot_cache.get(f"{symbol}_{tf}")
        if not piv:
            continue
        for lk in ("PP", "R1", "R2", "R3", "S1", "S2", "S3"):
            price = piv.get(lk)
            if price and price > 0:
                levels.append(price)

    if not levels:
        return None, None, None, "no pivot levels"

    is_long = direction.upper() == "LONG"

    if is_long:
        # SL = ближайший пивот НИЖЕ entry
        supports = [p for p in levels if p < entry]
        if not supports:
            return None, None, None, "no support below entry"
        nearest_support = max(supports)
        sl = nearest_support * (1.0 - sl_buffer_pct)

        # Проверка: entry не слишком далеко от поддержки (вход у края)
        dist_to_sl = (entry - sl) / entry
        if dist_to_sl > max_sl_dist_pct:
            return None, None, None, f"entry too far from support ({dist_to_sl:.1%} > {max_sl_dist_pct:.1%})"

        # TP = ближайший пивот ВЫШЕ entry
        resistances = [p for p in levels if p > entry]
        if not resistances:
            return None, None, None, "no resistance above entry"
        tp = min(resistances)

    else:  # SHORT
        # SL = ближайший пивот ВЫШЕ entry
        resistances = [p for p in levels if p > entry]
        if not resistances:
            return None, None, None, "no resistance above entry"
        nearest_resistance = min(resistances)
        sl = nearest_resistance * (1.0 + sl_buffer_pct)

        # Проверка: entry не слишком далеко от сопротивления
        dist_to_sl = (sl - entry) / entry
        if dist_to_sl > max_sl_dist_pct:
            return None, None, None, f"entry too far from resistance ({dist_to_sl:.1%} > {max_sl_dist_pct:.1%})"

        # TP = ближайший пивот НИЖЕ entry
        supports = [p for p in levels if p < entry]
        if not supports:
            return None, None, None, "no support below entry"
        tp = max(supports)

    # Считаем RR
    sl_dist = abs(entry - sl)
    tp_dist = abs(tp - entry)
    if sl_dist <= 0:
        return None, None, None, "sl_dist=0"

    tp_r = tp_dist / sl_dist
    if tp_r < min_tp_r:
        return None, None, None, f"RR={tp_r:.1f} < min {min_tp_r:.1f}"

    return sl, tp, tp_r, None
