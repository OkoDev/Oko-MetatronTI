"""
WTService — Сфера 15 / ARCH-117.

Единственный источник правды для WaveTrend: zone, cross, cross_in_zone, divergence.
Устраняет дублирование формулы в 7+ местах и расхождение определений cross/zone.

Принципы (из аудита 29.05.2026):
  - wt_cross      = сырой кросс wt1×wt2 (обратная совместимость с WTSpecialist)
  - cross_in_zone = кросс ДО которого wt1 был в зоне OS/OB (строгий вариант, ±60)
  - zone          = текущая зона по wt1 (±60, стандарт WaveTrend)
  - Зона ДО кросса: wt1[i-1] < -60 (bull) или wt1[i-1] > +60 (bear)

Принимает готовые DataFrame с wt1/wt2 (calculate_wt уже применён в scan_loop).
Не пересчитывает wt1/wt2 — только производные.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("WTService")

WT_OS: float = -60.0
WT_OB: float =  60.0


def build_wt_snap_entry(df: pd.DataFrame, tf_label: str) -> dict[str, Any] | None:
    """
    Вычисляет snap для одного TF из готового DataFrame (wt1/wt2 уже есть).

    Возвращает словарь совместимый с текущим форматом wt_snap в scan_loop,
    плюс новое поле cross_in_zone.
    """
    if df is None or df.empty or "wt1" not in df.columns or "wt2" not in df.columns:
        return None

    cur = df.iloc[-1]
    wt1_cur = float(cur.get("wt1", 0.0))
    wt2_cur = float(cur.get("wt2", 0.0))

    # zone по текущему wt1
    if wt1_cur > WT_OB:
        zone = "OB"
    elif wt1_cur < WT_OS:
        zone = "OS"
    else:
        zone = "N"

    # wt_cross (сырой) + cross_in_zone (ДО кросса)
    wt_cross = 0
    cross_in_zone = 0  # 1=bull-from-OS, -1=bear-from-OB, 0=нет

    if len(df) >= 2:
        prev = df.iloc[-2]
        wt1_prev = float(prev.get("wt1", 0.0))
        wt2_prev = float(prev.get("wt2", 0.0))

        bull_cross = wt1_prev <= wt2_prev and wt1_cur > wt2_cur
        bear_cross = wt1_prev >= wt2_prev and wt1_cur < wt2_cur

        if bull_cross:
            wt_cross = 1
            if wt1_prev < WT_OS:          # был в OS ДО кросса
                cross_in_zone = 1
        elif bear_cross:
            wt_cross = -1
            if wt1_prev > WT_OB:          # был в OB ДО кросса
                cross_in_zone = -1

    # atr_trend (trend из calculate_trend)
    trend_val = float(cur.get("trend", 0.0))

    return {
        "wt1":           round(wt1_cur, 2),
        "wt2":           round(wt2_cur, 2),
        "zone":          zone,
        "wt_cross":      wt_cross,         # сырой — для WTSpecialist (обратная совместимость)
        "cross_in_zone": cross_in_zone,    # строгий: был в зоне ДО кросса
        "trend":         "UP" if trend_val == 1 else "DOWN",
        "atr_trend":     1 if trend_val == 1 else -1,
    }


def build_wt_snap(tf_df_pairs: list[tuple[str, pd.DataFrame | None]]) -> dict[str, dict]:
    """
    Строит полный wt_snap для набора TF.

    Args:
        tf_df_pairs: [(tf_label, df), ...] — TF и соответствующие DataFrame

    Returns:
        {tf: snap_dict} — только TF с валидными данными
    """
    snap = {}
    for tf, df in tf_df_pairs:
        entry = build_wt_snap_entry(df, tf)
        if entry is not None:
            snap[tf] = entry
    return snap
