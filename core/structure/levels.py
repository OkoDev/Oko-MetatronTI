# -*- coding: utf-8 -*-
"""Уровни одного масштаба: сломы с объёмом, подписи точек, зоны диапазона.

Спецификация: docs/STRUCTURE_KERNEL_SPEC.md → «Фаза 2». Функции чистые, без IO.
Колонки df — open/high/low/close[/volume] в любом регистре.
"""
from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd

from core.structure.pivots import confirmed_pivots


class LevelBreak(NamedTuple):
    bar: int            # бар закрытия за уровнем
    bullish: bool
    reversal: bool      # против направления (CHoCH) или по нему (BOS)
    level: float
    level_bar: int      # бар опорной точки уровня
    heavy_volume: bool  # объём бара выше среднего × vol_mult

    @property
    def kind(self) -> str:
        return "CHoCH" if self.reversal else "BOS"


def column(df: pd.DataFrame, name: str) -> np.ndarray:
    """Колонка df по имени без учёта регистра, как массив float."""
    for c in df.columns:
        if str(c).lower() == name:
            return df[c].to_numpy(dtype=float)
    raise KeyError(name)


def _has_column(df: pd.DataFrame, name: str) -> bool:
    return any(str(c).lower() == name for c in df.columns)


def _enough_history(n: int, window: int) -> bool:
    return n >= 2 * window + 2


def level_breaks(df: pd.DataFrame, window: int = 50, vol_len: int = 20,
                 vol_mult: float = 1.2) -> list[LevelBreak]:
    """Сломы одного масштаба: закрытие за взведённым уровнем, не больше одного слома за бар."""
    n = len(df)
    if not _enough_history(n, window):
        return []
    high, low, close = column(df, "high"), column(df, "low"), column(df, "close")
    heavy = np.zeros(n, dtype=bool)
    if _has_column(df, "volume"):
        volume = column(df, "volume")
        heavy = volume > pd.Series(volume).rolling(vol_len).mean().to_numpy() * vol_mult

    arrivals: dict[int, list] = {}
    for p in confirmed_pivots(high, low, window):
        arrivals.setdefault(p.confirmed_at, []).append(p)

    found: list[LevelBreak] = []
    direction = 0
    upper = lower = None
    upper_live = lower_live = False
    for t in range(n):
        for p in arrivals.get(t, ()):
            if p.is_high:
                upper, upper_live = p, True
            else:
                lower, lower_live = p, True
        if upper_live and close[t] > upper.price:
            found.append(LevelBreak(t, True, direction < 0, upper.price, upper.bar, bool(heavy[t])))
            upper_live, direction = False, 1
        elif lower_live and close[t] < lower.price:
            found.append(LevelBreak(t, False, direction > 0, lower.price, lower.bar, bool(heavy[t])))
            lower_live, direction = False, -1
    return found


def label_swings(df: pd.DataFrame, window: int = 50) -> list[tuple[int, float, str]]:
    """Подписи опорных точек HH/LH/LL/HL относительно предыдущей точки того же вида."""
    if not _enough_history(len(df), window):
        return []
    labelled = []
    last = {True: None, False: None}
    for p in confirmed_pivots(column(df, "high"), column(df, "low"), window):
        prev = last[p.is_high]
        if p.is_high:
            tag = "LH" if prev is not None and not p.price > prev else "HH"
        else:
            tag = "HL" if prev is not None and not p.price < prev else "LL"
        last[p.is_high] = p.price
        labelled.append((p.bar, p.price, tag))
    return labelled


def range_zones(top: float, bottom: float, band: float = 0.05) -> dict:
    """Полосы диапазона: верхние и нижние `band` доли и равновесие ±band/2 вокруг середины."""
    half = band / 2
    return {
        "upper": (top * (1 - band) + bottom * band, top),
        "middle": (top * (0.5 - half) + bottom * (0.5 + half), top * (0.5 + half) + bottom * (0.5 - half)),
        "lower": (bottom, bottom * (1 - band) + top * band),
        "mid": (top + bottom) / 2,
    }
