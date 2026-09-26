# -*- coding: utf-8 -*-
"""Опорные точки — экстремумы, не превзойдённые следующими `window` барами.

Спецификация: docs/STRUCTURE_KERNEL_SPEC.md → «Опорная точка». Кратко:
вершина на баре j, если high[j] строго выше high[j+1 … j+window]; впадина — зеркально по low;
подтверждение на баре j+window; фиксируется только смена вида; при двух условиях сразу — вершина;
до первой точки считаем, что последней была вершина.
"""
from __future__ import annotations

from typing import NamedTuple

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


class Pivot(NamedTuple):
    bar: int            # бар экстремума
    confirmed_at: int   # бар, на котором точка стала известна (bar + window)
    price: float
    is_high: bool       # True — вершина, False — впадина


_HIGH, _LOW = 1, -1


def confirmed_pivots(high, low, window: int) -> list[Pivot]:
    """Чередующиеся опорные точки ряда в порядке подтверждения."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    span = len(h) - window                      # столько баров имеют полное правое окно
    if window < 1 or span < 1:
        return []

    right_max = sliding_window_view(h[1:], window).max(axis=1)[:span]
    right_min = sliding_window_view(l[1:], window).min(axis=1)[:span]
    kind = np.where(h[:span] > right_max, _HIGH,
                    np.where(l[:span] < right_min, _LOW, 0))

    pivots: list[Pivot] = []
    previous = _HIGH                            # начальное соглашение: последней была вершина
    for bar in np.flatnonzero(kind):
        k = int(kind[bar])
        if k == previous:
            continue
        previous = k
        is_high = k == _HIGH
        price = h[bar] if is_high else l[bar]
        pivots.append(Pivot(int(bar), int(bar) + window, float(price), is_high))
    return pivots


def two_sided_pivots(values, window: int, highs: bool = True) -> list[tuple[int, float]]:
    """Точки с окном `window` с обеих сторон: слева значения строго хуже, справа — не лучше.

    «Хуже» для вершин — ниже, для впадин — выше. Точка на баре c известна на баре c + window.
    Возвращает [(бар, цена)] по возрастанию бара.
    """
    v = np.asarray(values, dtype=float)
    if window < 1 or len(v) < 2 * window + 1:
        return []
    centers = np.arange(window, len(v) - window)
    frames = sliding_window_view(v, window)
    left, right, value = frames[centers - window], frames[centers + 1], v[centers]
    if highs:
        keep = (left.max(axis=1) < value) & (right.max(axis=1) <= value)
    else:
        keep = (left.min(axis=1) > value) & (right.min(axis=1) >= value)
    return [(int(c), float(v[c])) for c in centers[keep]]
