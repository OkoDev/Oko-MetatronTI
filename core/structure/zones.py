# -*- coding: utf-8 -*-
"""Зоны: блоки заявок, равные уровни, разрывы справедливой цены.

Спецификация: docs/STRUCTURE_KERNEL_SPEC.md → «Фаза 2». Функции чистые, без IO.

Причинность полей: бары происхождения и слома известны сразу; бар, на котором зона перестала
действовать (`gone_bar`, `filled_bar`), по построению смотрит вперёд. Его можно использовать
как границу «зона жива до N», но не как признак на барах ≤ N.
"""
from __future__ import annotations

from typing import NamedTuple, Optional

import numpy as np
import pandas as pd

from core.structure.levels import LevelBreak, column
from core.structure.pivots import two_sided_pivots


class Block(NamedTuple):
    origin_bar: int     # свеча блока
    top: float
    bottom: float
    bullish: bool       # блок под сломом вверх (поддержка) / вниз (сопротивление)
    break_bar: int      # слом, породивший блок
    gone_bar: int       # закрытие за дальней границей; -1 — блок действует
    flipped: bool       # блок пробит и сменил роль


class EqualPair(NamedTuple):
    first_bar: int
    first_price: float
    second_bar: int
    second_price: float
    highs: bool         # пара вершин (ликвидность сверху) / впадин


class Gap(NamedTuple):
    left_bar: int       # первая из трёх свечей
    top: float
    bottom: float
    bullish: bool
    bar: int            # третья свеча — разрыв известен на ней
    filled_bar: int     # закрытие за дальней границей; -1 — не закрыт


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    """ATR Уайлдера: истинный диапазон, сглаженный с alpha = 1/length."""
    prev_close = np.concatenate(([np.nan], close[:-1]))
    true_range = np.fmax(high - low, np.fmax(np.abs(high - prev_close), np.abs(low - prev_close)))
    return pd.Series(true_range).ewm(alpha=1.0 / length, adjust=False).mean().to_numpy()


def first_close_beyond(close: np.ndarray, start: int, level: float, below: bool) -> int:
    """Первый бар ≥ start, где закрытие ниже (below) или выше уровня; -1, если такого нет."""
    n, step = len(close), 256
    while start < n:
        stop = min(n, start + step)
        chunk = close[start:stop]
        hits = np.flatnonzero(chunk < level if below else chunk > level)
        if hits.size:
            return start + int(hits[0])
        start, step = stop, min(step * 2, 65536)
    return -1


def order_blocks(df: pd.DataFrame, breaks: list[LevelBreak], atr_len: int = 200) -> list[Block]:
    """Блок для каждого слома: крайняя спокойная свеча на отрезке от уровня до слома."""
    high, low, close = column(df, "high"), column(df, "low"), column(df, "close")
    atr = wilder_atr(high, low, close, atr_len)
    limit = np.where(np.isnan(atr), np.inf, 2 * atr)

    blocks: list[Block] = []
    for brk in breaks:
        anchor = brk.level_bar if brk.level_bar >= 0 else brk.bar
        a, z = min(anchor, brk.bar), max(anchor, brk.bar)
        if z - a < 1:
            continue
        span = slice(a, z + 1)
        calm = (high[span] - low[span]) < limit[span]
        if not calm.any():
            continue
        if brk.bullish:
            pick = a + int(np.argmin(np.where(calm, low[span], np.inf)))
        else:
            pick = a + int(np.argmax(np.where(calm, high[span], -np.inf)))
        top, bottom = float(high[pick]), float(low[pick])
        gone = (first_close_beyond(close, brk.bar + 1, bottom, below=True) if brk.bullish
                else first_close_beyond(close, brk.bar + 1, top, below=False))
        blocks.append(Block(pick, top, bottom, brk.bullish, brk.bar, gone, gone != -1))
    return blocks


def equal_levels(df: pd.DataFrame, window: int = 3, tolerance: float = 0.1,
                 atr_len: int = 200) -> list[EqualPair]:
    """Соседние опорные точки одного вида, отличающиеся меньше чем на tolerance·ATR."""
    high, low, close = column(df, "high"), column(df, "low"), column(df, "close")
    atr = wilder_atr(high, low, close, atr_len)
    pairs: list[EqualPair] = []
    for highs in (True, False):
        points = two_sided_pivots(high if highs else low, window, highs)
        for (b1, p1), (b2, p2) in zip(points, points[1:]):
            allowed = tolerance * atr[b2] if not np.isnan(atr[b2]) else 0.0
            if abs(p2 - p1) < allowed:
                pairs.append(EqualPair(b1, p1, b2, p2, highs))
    return pairs


def fair_value_gaps(df: pd.DataFrame, threshold: Optional[float] = None) -> list[Gap]:
    """Трёхсвечные разрывы крупнее порога (явного или причинного удвоенного среднего)."""
    high, low, close = column(df, "high"), column(df, "low"), column(df, "close")
    n = len(close)
    if n < 3:
        return []

    up = np.zeros(n, dtype=bool)
    down = np.zeros(n, dtype=bool)
    up[2:] = (low[2:] > high[:-2]) & (close[1:-1] > high[:-2])
    down[2:] = (high[2:] < low[:-2]) & (close[1:-1] < low[:-2]) & ~up[2:]

    size = np.full(n, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        size[2:] = np.where(up[2:], (low[2:] - high[:-2]) / high[:-2] * 100,
                            (low[:-2] - high[2:]) / high[2:] * 100)

    if threshold is None:
        span = np.zeros(n)
        span[2:] = np.maximum(0.0, np.maximum(low[2:] - high[:-2], low[:-2] - high[2:]))
        pct = np.zeros(n)
        nz = close != 0
        pct[nz] = span[nz] / close[nz] * 100
        pct[:2] = 0.0
        bar_limit = np.cumsum(pct) / np.maximum(np.arange(n) - 1, 1) * 2.0
    else:
        bar_limit = np.full(n, float(threshold))

    gaps: list[Gap] = []
    for t in np.flatnonzero(up | down):
        t = int(t)
        if size[t] <= bar_limit[t]:
            continue
        if up[t]:
            top, bottom = float(low[t]), float(high[t - 2])
            filled = first_close_beyond(close, t + 1, bottom, below=True)
        else:
            top, bottom = float(low[t - 2]), float(high[t])
            filled = first_close_beyond(close, t + 1, top, below=False)
        gaps.append(Gap(t - 2, top, bottom, bool(up[t]), t, filled))
    return gaps
