# -*- coding: utf-8 -*-
"""Собственные слои OKO поверх структурного ядра (фаза 5, docs/STRUCTURE_KERNEL_SPEC.md).

  · OTE на ноге — зона и уровни канона проекта (core/smc/fibonacci.py: OTE_ZONE, OTE_LEVELS);
  · цель по пивотам Егора — классические пивоты прошлого дня (calculate_pivot_points) и два правила:
    «логика Егора» (первый из R1…R5 / S1…S5 за ценой) и «второй пивот» (как боевой impulse_fib 1h);
  · ноги Directional Change — порог в ATR (core/smc/dc_legs.py), второй источник ног.

Каждый слой берёт формулы из их единственного места в проекте; импорты ленивые, потому что
пакет core.smc сам импортирует core.structure.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

PIVOT_ORDER = ("S5", "S4", "S3", "S2", "S1", "PP", "R1", "R2", "R3", "R4", "R5")
TARGET_MIN_DIST = 0.003          # цель не ближе 0.3% от цены (как в замере и в боевом impulse_fib)


def ote_on_leg(leg: Optional[dict]) -> Optional[dict]:
    """Зона и уровни OTE на ноге {'trend','origin','extreme',...}: откат от экстремума к началу ноги."""
    if not leg:
        return None
    from core.smc.fibonacci import OTE_LEVELS, OTE_ZONE
    extreme, span = leg["extreme"], leg["extreme"] - leg["origin"]
    price = lambda r: extreme - span * r            # и для лонга, и для шорта (span со знаком)
    near, far = price(OTE_ZONE[0]), price(OTE_ZONE[1])
    return {"trend": leg["trend"], "zone": (max(near, far), min(near, far)),
            "levels": [(r, price(r)) for r in OTE_LEVELS]}


def day_pivots(high: float, low: float, close: float) -> dict:
    """Классические пивоты проекта по дню (H, L, C): PP, S1…S5, R1…R5."""
    from core.indicators.indicators import calculate_pivot_points
    return calculate_pivot_points(high, low, close)


def pivot_target(pivots: dict, entry: float, is_long: bool, mode: str = "egor",
                 min_dist: float = TARGET_MIN_DIST) -> Optional[tuple[str, float]]:
    """Цель по пивотам: (имя уровня, цена) или None, если за ценой в сторону сделки уровней нет.

    mode="egor"   — внутри S1–R1 → R1/S1, за R1/S1 → R2/S2, дальше следующий уровень;
    mode="second" — второй из всех уровней за ценой (боевой impulse_fib 1h с 22.09).
    """
    beyond = (lambda x: x > entry * (1 + min_dist)) if is_long else (lambda x: x < entry * (1 - min_dist))
    if mode == "egor":
        for name in (("R1", "R2", "R3", "R4", "R5") if is_long else ("S1", "S2", "S3", "S4", "S5")):
            if pivots.get(name) == pivots.get(name) and beyond(pivots[name]):
                return name, pivots[name]
        return None
    if mode == "second":
        found = sorted(((p, n) for n, p in pivots.items() if p == p and beyond(p)), reverse=not is_long)
        return (found[1][1], found[1][0]) if len(found) >= 2 else None
    raise ValueError(f"mode: {mode}")


def dc_swings(df: pd.DataFrame, atr_mult: float = 3.0, atr_len: int = 43) -> list[tuple[int, float, int, bool]]:
    """Ноги Directional Change: [(бар экстремума, цена, бар подтверждения, нога вверх?)].
    Порог по умолчанию — масштаб импульса боевой механики (dc_legs.origin_floor: 3.0 × ATR 43)."""
    from core.smc.dc_legs import enforce_alternation, find_legs
    return [(lg.ext_i, lg.ext_price, lg.conf_i, lg.up)
            for lg in enforce_alternation(find_legs(df, atr_mult=atr_mult, atr_len=atr_len))]
