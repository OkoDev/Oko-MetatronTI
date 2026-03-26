"""
DEV-23: Динамические пороги OB/OS для WaveTrend.

Standalone модуль: compute_dynamic_thresholds() вычисляет пороги на основе
скользящего среднего и стандартного отклонения WT1.

Shadow mode: используется только для аналитики, не меняет поведение торговли.
Флаг dynamic_os_enabled=False в config.yaml — эксперимент выключен по умолчанию.
"""
from __future__ import annotations

import logging
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)


def compute_dynamic_thresholds(
    wt1_series: np.ndarray,
    k: float = 0.8,
    window: int = 50,
    fixed_os: float = -60.0,
    fixed_ob: float = 60.0,
) -> Tuple[float, float, bool]:
    """
    Вычисляет динамические пороги OS/OB по формуле mean ± k*std.

    Параметры
    ----------
    wt1_series : последние N значений WT1 (без открытой свечи)
    k          : множитель стандартного отклонения (по умолчанию 0.8)
    window     : сколько баров использовать
    fixed_os   : фиксированный порог OS (fallback)
    fixed_ob   : фиксированный порог OB (fallback)

    Возвращает
    ----------
    (dyn_os_thr, dyn_ob_thr, computed) где computed=True если данных достаточно.
    При недостатке данных возвращает фиксированные значения + computed=False.
    """
    hist = wt1_series[-(window + 1):-1] if len(wt1_series) > 1 else wt1_series

    if len(hist) < 20:
        return fixed_os, fixed_ob, False

    wt_mean = float(np.mean(hist))
    wt_std = float(np.std(hist))

    dyn_os = wt_mean - k * wt_std
    dyn_ob = wt_mean + k * wt_std

    return dyn_os, dyn_ob, True


def os_method_label(
    fixed_triggered: bool,
    dyn_triggered: bool,
    dyn_computed: bool,
) -> str:
    """
    Возвращает строку-метку метода определения зоны OS/OB.

    Используется для shadow-mode аналитики (хранится в sig.data["os_method"]).
    """
    if not dyn_computed:
        return "fixed"
    if fixed_triggered and dyn_triggered:
        return "both"
    if dyn_triggered:
        return "dynamic"
    return "fixed"
