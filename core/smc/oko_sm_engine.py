# -*- coding: utf-8 -*-
"""OKO-SM ENGINE — прежний вход к структуре OKO поверх структурного ядра `core/structure`.

С 26.09.2026 (фаза 4 чистой переписки, docs/STRUCTURE_KERNEL_SPEC.md) вычисления делает
`core.structure.trace_structure`; модуль сохраняет прежний интерфейс для 58 вызывающих мест:
`run_structure` → SMState (направления, последние точки, экстремумы ноги, сломы, ноги по барам),
`current_leg` → нога для OTE, `pivot_points` → опорные точки. Поведение совпадает с прежним
побитово (scripts/structure_migration_check.py). Чистые функции, без IO.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from core.structure import MINOR, Mark, ScaleState, StructureTrace, active_leg, confirmed_pivots, trace_structure


@dataclass
class SMEvent:
    i: int              # индекс бара события (подтверждение слома)
    kind: str           # 'CHoCH' | 'BOS'
    bull: bool          # бычий (пробой вверх) / медвежий
    level: float        # сломанный уровень (цена опорной точки)
    internal: bool      # младший масштаб или старший
    level_i: Optional[int] = None   # бар опорной точки уровня


@dataclass
class SMState:
    trend: int = 0                          # старший масштаб: 1 вверх / -1 вниз / 0 не определено
    minor_trend: int = 0                    # младший масштаб
    last_high: Optional[float] = None       # последняя вершина старшего масштаба
    last_high_bar: Optional[int] = None
    last_low: Optional[float] = None        # последняя впадина старшего масштаба
    last_low_bar: Optional[int] = None
    leg_top: Optional[float] = None         # верх ноги (бегущий экстремум)
    leg_top_bar: Optional[int] = None
    leg_bottom: Optional[float] = None      # низ ноги
    leg_bottom_bar: Optional[int] = None
    events: list = field(default_factory=list)
    leg_history: list = field(default_factory=list)   # нога после каждого бара (record_legs=True)


def _price_bar(mark: Optional[Mark]):
    return (mark.price, mark.bar) if mark is not None else (None, None)


def run_structure(df: pd.DataFrame, swing_len: int = 50, internal_len: int = 5,
                  record_legs: bool = False) -> SMState:
    """Структура на двух масштабах (старший swing_len, младший internal_len).
    record_legs=True → st.leg_history[t] = нога после бара t (решение на баре t+1)."""
    tr = trace_structure(df, major=swing_len, minor=internal_len, keep_legs=record_legs)
    st = SMState(trend=tr.major.direction, minor_trend=tr.minor.direction)
    st.last_high, st.last_high_bar = _price_bar(tr.major.high)
    st.last_low, st.last_low_bar = _price_bar(tr.major.low)
    st.leg_top, st.leg_top_bar = _price_bar(tr.leg_high)
    st.leg_bottom, st.leg_bottom_bar = _price_bar(tr.leg_low)
    st.events = [SMEvent(b.bar, b.kind, b.bullish, b.level, b.scale == MINOR, b.level_bar) for b in tr.breaks]
    st.leg_history = tr.legs if record_legs else []
    return st


def current_leg(st: SMState) -> Optional[dict]:
    """Нога для OTE по состоянию: от последней точки старшего масштаба против направления до экстремума ноги."""
    mark = lambda p, b: Mark(p, b) if p is not None else None
    tr = StructureTrace(major=ScaleState(direction=st.trend, high=mark(st.last_high, st.last_high_bar),
                                         low=mark(st.last_low, st.last_low_bar)),
                        leg_high=mark(st.leg_top, st.leg_top_bar),
                        leg_low=mark(st.leg_bottom, st.leg_bottom_bar))
    return active_leg(tr)


def pivot_points(high: pd.Series, low: pd.Series, length: int) -> list:
    """Опорные точки окна length: [(бар_подтверждения, бар_точки, цена, вершина?)]."""
    return [(p.confirmed_at, p.bar, p.price, p.is_high) for p in confirmed_pivots(high, low, length)]
