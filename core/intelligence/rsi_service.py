"""
RSIService — Сфера RSI / ARCH-117 ph2.

Единый источник RSI: value + zone + cross50. Зеркало WTService.
Строится на каноническом `compute_rsi` (indicators.py, Wilder RMA) — БЕЗ новой
формулы (именно дублирование формул ARCH-117 устраняет).

RSI-дивергенция (LonesomeTheBlue: pivot-close + trendline) уже консолидирована
в combinator_v2._calc_divergence (DEV-233) для бэктеста/arch104. В live RSI-div
пока не сигнал — при необходимости подключается отдельно (тот же алгоритм).

Пороги (стандарт RSI): OB > 70, OS < 30. cross50 = смена импульса.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, Union

import pandas as pd

from core.indicators.indicators import compute_rsi

logger = logging.getLogger("RSIService")

RSI_OB: float = 70.0
RSI_OS: float = 30.0
RSI_MID: float = 50.0


def build_rsi_snap_entry(
    closes: Union[List[float], pd.Series],
    period: int = 14,
) -> Optional[dict[str, Any]]:
    """
    Снап RSI для одной серии закрытий.

    Returns:
        {rsi, zone, cross50} либо None если данных мало.
        rsi     — последнее значение (0-100)
        zone    — "OB" (>70) | "OS" (<30) | "N"
        cross50 — 1 (RSI пересёк 50 вверх) | -1 (вниз) | 0
    """
    if isinstance(closes, pd.Series):
        lst = closes.dropna().tolist()
    else:
        lst = [v for v in closes if v == v]
    if len(lst) < period + 2:
        return None

    rsi_cur = compute_rsi(lst, period)
    rsi_prev = compute_rsi(lst[:-1], period)   # RSI на предыдущем баре (тот же канон)
    if rsi_cur is None:
        return None

    if rsi_cur > RSI_OB:
        zone = "OB"
    elif rsi_cur < RSI_OS:
        zone = "OS"
    else:
        zone = "N"

    cross50 = 0
    if rsi_prev is not None:
        if rsi_prev <= RSI_MID < rsi_cur:
            cross50 = 1
        elif rsi_prev >= RSI_MID > rsi_cur:
            cross50 = -1

    return {
        "rsi":     round(float(rsi_cur), 2),
        "zone":    zone,
        "cross50": cross50,
    }


def build_rsi_snap(
    tf_closes_pairs: list[tuple[str, Union[List[float], pd.Series, None]]],
    period: int = 14,
) -> dict[str, dict]:
    """
    Полный rsi_snap для набора TF.

    Args:
        tf_closes_pairs: [(tf_label, closes), ...]

    Returns:
        {tf: {rsi, zone, cross50}} — только TF с валидными данными.
    """
    snap = {}
    for tf, closes in tf_closes_pairs:
        if closes is None:
            continue
        entry = build_rsi_snap_entry(closes, period)
        if entry is not None:
            snap[tf] = entry
    return snap
