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


R_CLAMP_MIN: float = -15.0   # защита от sl_dist≈0 баг (R=-450); loss физически ~-1R (закрытие на SL)
R_CLAMP_MAX: float = 50.0    # FALLBACK-потолок только для АРТЕФАКТОВ (sl_dist≈0). Легитимные раннеры
                             # (sl_dist >= 0.3%) НЕ режутся — см. clamp_r_smart (09.06: умный clamp по
                             # причине, не по величине → раннеры дышат без потолка, баг ловится sl_dist'ом).
MIN_SL_DIST_PCT: float = 0.003  # 0.3% (DEV-157): sl_dist ниже = артефакт sl_dist≈0 (R взрывается)


def clamp_r_smart(
    r: Optional[float],
    entry: Optional[float],
    one_r: Optional[float],
) -> Optional[float]:
    """Умный sanity-clamp по ПРИЧИНЕ (sl_dist), а не по величине R.

    - Loss (R<0): физически ~-1R (закрытие на SL); R<-15 = всегда артефакт → жёсткий MIN.
    - Раннер (R>0): если sl_dist >= 0.3% (SL реально далеко) — R честный, БЕЗ потолка
      (раннер +112R легитимен: 50% движения / 0.45% риск). Если sl_dist < 0.3% — баг → clamp.

    Зачем: тупой clamp@50 резал реальный edge раннеров (OTE до HTF-target). Корень бага +8103/-450
    не в величине, а в sl_dist≈0 — его и проверяем. Раннеры дышат, артефакт ловится причиной.
    """
    if r is None:
        return None
    if r < 0:
        return clamp_r(r)               # loss: жёсткий MIN -15 (защита от -450)
    if entry and one_r and entry > 0 and (one_r / entry) >= MIN_SL_DIST_PCT:
        return r                        # SL достаточно далеко → раннер реален, без потолка
    return clamp_r(r)                   # sl_dist≈0 артефакт или нет данных → fallback MAX 50


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
    return clamp_r_smart(r, float(entry), one_r) if clamp else r
