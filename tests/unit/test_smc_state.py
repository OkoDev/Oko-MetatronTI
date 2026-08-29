"""
Регрессия семьи SMC-СОСТОЯНИЕ в матрице (29.08.2026).

Повод: инвентаризация показала, что 13 из 69 SMC-признаков матрицы — КОНСТАНТА 0.
`bull_ob` помечал 4 бара из 19 851 (0.020%), `bear_ob_near` — ноль. При этом ДЕТЕКТОРЫ
исправны все: `detect_order_blocks` находит 126 блоков, `detect_swings` — 2983 события,
`detect_sponsored_candle` — 318. Ломался мост детектор→признак
([[smc_in_matrix_is_dead_weight]]).

Тесты охраняют три вещи, каждая из которых уже подводила в этом проекте:
  · причинность (два вида: усечение будущего И глобальная нормировка порога);
  · «оживлённость» — признак не должен снова выродиться в константу;
  · лаг подтверждения — событие нельзя учитывать раньше, чем о нём можно узнать.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from matrix_full import (MAJOR_LEN, SMC_LAG, _zone_state,      # noqa: E402
                         smc_state_features)


def _series(n=3000, seed=29):
    rng = np.random.default_rng(seed)
    drift = np.concatenate([np.full(n // 3, 0.05), np.full(n // 3, -0.05),
                            np.full(n - 2 * (n // 3), 0.0)])
    close = 100 + np.cumsum(rng.normal(0, 0.4, n) + drift)
    wick = np.abs(rng.normal(0, 0.5, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": close, "close": close,
                         "high": close + wick, "low": close - wick,
                         "volume": rng.uniform(50, 200, n)}, index=idx)


def test_no_constant_columns():
    """
    🔴 ГЛАВНЫЙ: ради этого семья и переписана — старые SMC-флаги были константой 0.

    Проверяются только те группы, где детектор РЕАЛЬНО что-то нашёл: на коротком
    синтетическом ряду редкие события (breaker, sponsored candle, EQH/EQL) могут не
    встретиться ни разу, и пустой признак тогда — свойство ряда, а не дефект развёртки.
    Различать это обязательно, иначе тест начнёт врать в обе стороны.
    """
    E = smc_state_features(_series(), "15m")
    assert len(E.columns) >= 40, f"семья схлопнулась до {len(E.columns)} признаков"

    groups: dict[str, list[str]] = {}
    for c in E.columns:
        base = c.replace("in_", "").replace("near_", "")
        for suf in ("_dist_atr_15m", "_age_15m", "_active_15m", "_15m"):
            if base.endswith(suf):
                base = base[: -len(suf)]
                break
        groups.setdefault(base, []).append(c)

    checked = const = 0
    skipped = []
    for base, cols in groups.items():
        act = next((c for c in cols if c.endswith("_active_15m")), None)
        if act is not None and float(np.nansum(E[act].values)) == 0.0:
            skipped.append(base)          # детектор не нашёл событий на этом ряду
            continue
        for c in cols:
            checked += 1
            if E[c].dropna().nunique() <= 1:
                const += 1
                assert False, f"вырожденный признак при живом детекторе: {c}"
    assert checked >= 20, f"проверено всего {checked} признаков — тест ничего не охраняет"


def test_causal_future_does_not_leak():
    """
    🔴 Усечение будущего не меняет прошлое.

    Первая версия ЭТОТ ТЕСТ ПРОВАЛИЛА: `detect_fvg(threshold=None)` считает порог
    значимости по ВСЕМУ ряду (средний |Δ%| × 2), и набор FVG зависел от будущих баров —
    8 признаков расходились, до 1590 баров. Порог теперь фиксируется по первым 2000 барам.
    """
    df = _series()
    cut = 2000
    full, trunc = smc_state_features(df, "15m"), smc_state_features(df.iloc[:cut], "15m")
    edge = cut - MAJOR_LEN * 4
    bad = []
    for c in trunc.columns:
        a, b = full[c].iloc[:edge].values, trunc[c].iloc[:edge].values
        if (~((np.isnan(a) & np.isnan(b)) | np.isclose(a, b, equal_nan=True))).any():
            bad.append(c)
    assert not bad, f"look-ahead в SMC-состоянии: {bad}"


def test_shifted_by_one_bar():
    """Состояние берётся с ЗАКРЫТОГО бара — первая строка пуста."""
    E = smc_state_features(_series(), "15m")
    assert E.iloc[0].isna().all() or (E.iloc[0].fillna(0) == 0).all()


def test_zone_state_respects_lifetime():
    """Зона живёт на [known_from, dead_from) — ни раньше, ни позже."""
    n = 50
    c = np.full(n, 10.0)
    atr = np.full(n, 1.0)
    st = _zone_state(n, c, atr, [(10, 12.0, 11.0, 30)])
    assert np.isnan(st["dist_atr"][9]), "зона учтена ДО появления"
    assert not np.isnan(st["dist_atr"][10]), "зона не учтена в момент появления"
    assert not np.isnan(st["dist_atr"][29]), "зона умерла раньше срока"
    assert np.isnan(st["dist_atr"][30]), "зона учтена ПОСЛЕ смерти"


def test_zone_state_inside_and_distance():
    """`inside` и знак расстояния должны соответствовать положению цены."""
    n = 5
    atr = np.full(n, 1.0)
    c = np.array([9.0, 11.5, 13.0, 11.0, 12.0])       # ниже / внутри / выше / внутри
    st = _zone_state(n, c, atr, [(0, 12.0, 11.0, -1)])
    assert st["dist_atr"][0] < 0 and st["inside"][0] == 0.0
    assert st["dist_atr"][1] == 0.0 and st["inside"][1] == 1.0
    assert st["dist_atr"][2] > 0 and st["inside"][2] == 0.0


def test_active_window_bounded():
    """
    🔴 Точечные уровни (свинги, EQ, SC) не умирают сами. Без окна их список рос до тысяч,
    и развёртка превращалась в O(n²): 29 с на символ против 3.5 с с окном.
    """
    n = 500
    c = np.full(n, 10.0)
    atr = np.full(n, 1.0)
    zones = [(i, 10.0 + i * 0.01, 10.0 + i * 0.01, -1) for i in range(300)]
    st = _zone_state(n, c, atr, zones, max_active=20)
    assert st["active"].max() <= 20, f"окно активных не соблюдено: {st['active'].max()}"


def test_lag_table_is_not_all_zero():
    """
    🔴 Лаг подтверждения обязан быть НЕнулевым там, где детектор ждёт баров:
    свинг подтверждается через `length`, SC — через `confirm_bars`, EQH/EQL — через `eq_len`.
    Нулевой лаг у них означал бы, что признак знает событие раньше, чем оно видно.
    """
    assert SMC_LAG["swing_major"] == MAJOR_LEN
    assert SMC_LAG["swing_minor"] > 0
    assert SMC_LAG["sc"] > 0 and SMC_LAG["eq"] > 0


def test_detectors_are_alive_not_the_features():
    """
    🔑 Фиксируем причину проблемы: детекторы ИСПРАВНЫ, мёртв был признак.
    Если этот тест однажды упадёт — сломался детектор, и чинить надо не матрицу.
    """
    from core.smc.smc_engine import (detect_order_blocks, detect_structure_breaks,
                                     detect_swings)
    df = _series()
    br = detect_structure_breaks(df, length=MAJOR_LEN)
    assert len(br) > 0, "detect_structure_breaks не находит сломов"
    assert len(detect_order_blocks(df, br)) > 0, "detect_order_blocks не находит блоков"
    assert len(detect_swings(df)) > 0, "detect_swings не находит свингов"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
