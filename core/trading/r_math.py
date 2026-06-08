"""
r_math.py — единая точка для всех R-multiple вычислений.

Принципы:
  - 1R = |entry - original_sl| (исходный риск трейда, не текущий stop_loss).
    original_sl фиксируется при регистрации и не меняется TSL'ом.
  - Если original_sl недоступен (старые сделки) — fallback на текущий stop_loss
    с явным флагом (вызывающий может предупредить или включить clamp).
  - Pure-функции: без I/O, без БД, без async. Чисто математика.
  - Sanity clamp [-15, +15]: защита от sl_dist≈0 артефактов (ASR R=-450,
    SWARMS R=+8103). Применяется явно через clamp_r().

Использование:
  - trade_simulator.close_trade — расчёт R_multiple при закрытии
  - dashboard_server — live unrealized_r для OPEN
  - position_sync — sanity-check exit_price
"""
from __future__ import annotations

from typing import Optional, Tuple


R_CLAMP_MIN: float = -15.0   # защита от sl_dist≈0 баг (R=-450); loss редко >1R
R_CLAMP_MAX: float = 50.0    # 08.06: 15→50 — раннеры до HTF-target дышат (OTE RR 22-40 режется
                             # на 15!). clamp@15 прятал реальный edge SINGLE+runner. Баг +450 всё
                             # равно клампится (→50), DEV-157 min_sl_dist 0.3% защищает на входе.


def compute_one_r(
    entry: Optional[float],
    original_sl: Optional[float],
    fallback_sl: Optional[float] = None,
) -> Tuple[Optional[float], str]:
    """1R = абсолютная дистанция от entry до initial SL.

    Args:
      entry:       цена входа
      original_sl: SL при регистрации (приоритет — это и есть честный риск)
      fallback_sl: текущий stop_loss (используется только если original_sl NULL)

    Returns:
      (one_r, source). source: 'original_sl' | 'fallback_sl' | 'none'.
      one_r=None → данных нет или entry==SL (нулевая дистанция).
    """
    if entry is None or entry <= 0:
        return None, "none"
    sl = original_sl
    src = "original_sl"
    if sl is None or sl <= 0:
        sl = fallback_sl
        src = "fallback_sl"
    if sl is None or sl <= 0 or sl == entry:
        return None, "none"
    return abs(entry - sl), src


def compute_r(
    direction: str,
    entry: float,
    price: float,
    one_r: float,
) -> Optional[float]:
    """R-multiple для цены price при known one_r.

    LONG:  R > 0 если price > entry. SHORT: R > 0 если price < entry.
    """
    if not one_r or one_r <= 0 or entry is None or price is None:
        return None
    if direction.upper() == "LONG":
        return (price - entry) / one_r
    return (entry - price) / one_r


def clamp_r(r: Optional[float], lo: float = R_CLAMP_MIN, hi: float = R_CLAMP_MAX) -> Optional[float]:
    """Sanity clamp на случай sl_dist≈0 артефактов."""
    if r is None:
        return None
    if r < lo:
        return lo
    if r > hi:
        return hi
    return r


def compute_unrealized_r(
    direction: str,
    entry: Optional[float],
    current_price: Optional[float],
    original_sl: Optional[float],
    fallback_sl: Optional[float] = None,
    clamp: bool = True,
) -> Optional[float]:
    """Удобный wrapper для дашборда: live R для OPEN сделки.

    Если clamp=True (default) — sanity clamp применяется. На дашборде это
    отсекает абсурдные значения; в сырых расчётах close_trade можно clamp
    отключить и применить отдельно для логирования.
    """
    if entry is None or current_price is None:
        return None
    one_r, _ = compute_one_r(entry, original_sl, fallback_sl)
    if one_r is None:
        return None
    r = compute_r(direction, float(entry), float(current_price), one_r)
    return clamp_r(r) if clamp else r
