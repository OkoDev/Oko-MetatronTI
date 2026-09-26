# -*- coding: utf-8 -*-
"""Трасса структуры: уровни, сломы, экстремумы ноги и нога на двух масштабах.

Спецификация: docs/STRUCTURE_KERNEL_SPEC.md → «Масштабы», «Слом», «Экстремумы ноги», «Нога»,
«Порядок внутри бара». Функции чистые, без IO; df — open/high/low/close c RangeIndex.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple, Optional

import pandas as pd

from core.structure.pivots import confirmed_pivots

MAJOR, MINOR = "major", "minor"


class Mark(NamedTuple):
    price: float
    bar: int


class Break(NamedTuple):
    bar: int            # бар закрытия за уровнем
    bullish: bool       # слом вверх / вниз
    reversal: bool      # против направления масштаба (CHoCH) или по нему (BOS)
    level: float        # сломанный уровень
    level_bar: int      # бар опорной точки уровня
    scale: str          # MAJOR | MINOR

    @property
    def kind(self) -> str:
        return "CHoCH" if self.reversal else "BOS"


@dataclass
class ScaleState:
    direction: int = 0                  # 1 вверх · -1 вниз · 0 не определено
    high: Optional[Mark] = None         # последняя вершина масштаба
    low: Optional[Mark] = None          # последняя впадина масштаба
    high_armed: bool = False
    low_armed: bool = False


@dataclass
class StructureTrace:
    major: ScaleState = field(default_factory=ScaleState)
    minor: ScaleState = field(default_factory=ScaleState)
    leg_high: Optional[Mark] = None     # верх ноги старшего масштаба
    leg_low: Optional[Mark] = None      # низ ноги старшего масштаба
    breaks: list = field(default_factory=list)
    legs: Optional[list] = None         # нога после каждого бара (keep_legs=True)


def trace_structure(df: pd.DataFrame, major: int = 50, minor: int = 5,
                    keep_legs: bool = False) -> StructureTrace:
    """Прогон ряда. keep_legs=True → trace.legs[t] = нога после бара t (решение на t+1)."""
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)

    arrivals: dict[int, list] = {}
    for scale, window in ((MAJOR, major), (MINOR, minor)):
        for p in confirmed_pivots(high, low, window):
            arrivals.setdefault(p.confirmed_at, []).append((scale, p))

    tr = StructureTrace(legs=[] if keep_legs else None)
    by_name = {MAJOR: tr.major, MINOR: tr.minor}

    for t in range(len(close)):
        for scale, p in arrivals.get(t, ()):
            state, mark = by_name[scale], Mark(p.price, p.bar)
            if p.is_high:
                state.high, state.high_armed = mark, True
                if scale == MAJOR:
                    tr.leg_high = mark
            else:
                state.low, state.low_armed = mark, True
                if scale == MAJOR:
                    tr.leg_low = mark

        if tr.leg_high is None or high[t] > tr.leg_high.price:
            tr.leg_high = Mark(float(high[t]), t)
        if tr.leg_low is None or low[t] < tr.leg_low.price:
            tr.leg_low = Mark(float(low[t]), t)

        if t > 0:
            before, now = close[t - 1], close[t]
            _record_breaks(tr, tr.minor, MINOR, t, before, now, senior=tr.major)
            _record_breaks(tr, tr.major, MAJOR, t, before, now, senior=None)

        if keep_legs:
            tr.legs.append(active_leg(tr) if t > 0 else None)
    return tr


def _record_breaks(tr: StructureTrace, state: ScaleState, scale: str, t: int,
                   before: float, now: float, senior: Optional[ScaleState]) -> None:
    """Сломы масштаба на баре t. senior — старший масштаб: совпавший с ним уровень принадлежит ему."""
    up = state.high
    if (state.high_armed and before <= up.price < now
            and (senior is None or senior.high is None or senior.high.price != up.price)):
        tr.breaks.append(Break(t, True, state.direction < 0, up.price, up.bar, scale))
        state.high_armed, state.direction = False, 1

    down = state.low
    if (state.low_armed and before >= down.price > now
            and (senior is None or senior.low is None or senior.low.price != down.price)):
        tr.breaks.append(Break(t, False, state.direction > 0, down.price, down.bar, scale))
        state.low_armed, state.direction = False, -1


def active_leg(tr: StructureTrace) -> Optional[dict]:
    """Нога для OTE: от последней точки старшего масштаба против направления до экстремума ноги."""
    direction = tr.major.direction
    if direction == 1 and tr.leg_high is not None:
        origin = tr.major.low if tr.major.low is not None else tr.leg_low
        if origin is None or origin.price >= tr.leg_high.price:
            return None
        return {"trend": "long", "origin": origin.price, "origin_i": origin.bar,
                "extreme": tr.leg_high.price, "extreme_i": tr.leg_high.bar}
    if direction == -1 and tr.leg_low is not None:
        origin = tr.major.high if tr.major.high is not None else tr.leg_high
        if origin is None or origin.price <= tr.leg_low.price:
            return None
        return {"trend": "short", "origin": origin.price, "origin_i": origin.bar,
                "extreme": tr.leg_low.price, "extreme_i": tr.leg_low.bar}
    return None
