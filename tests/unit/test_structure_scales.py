"""
Регрессия семьи ДВУХ СТРУКТУР в матрице (28.08.2026).

Повод: три прогона полной матрицы подряд дали ноль находок (P(шум) = 0.500).
Причина оказалась не в признаках, а в наборе — вся структурная семья
`combinator_core` строится ОДНИМ масштабом (`arch104.choch_length` = 50), то есть
матрица знала направление старшей структуры и не имела НИ ОДНОГО признака момента
входа ([[method_egor_two_scale_entry]]).

Тесты охраняют три свойства, каждое из которых уже подводило в этом проекте:
  · причинность (класс look-ahead №1 — детектор, видящий будущее);
  · масштабы РАЗЛИЧНЫ (иначе «две структуры» — это одна, посчитанная дважды);
  · признаки не вырождены в константу (молчаливый отказ: колонка есть, толку нет).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from matrix_full import (            # noqa: E402
    MAJOR_LEN, MINOR_LEN, _break_arrays, structure_scales_features)


def _series(n=4000, seed=11):
    """Ряд с трендовыми участками и пилой — чтобы сломы были обоих видов."""
    rng = np.random.default_rng(seed)
    drift = np.concatenate([
        np.full(n // 4, 0.05), np.full(n // 4, -0.05),
        np.full(n // 4, 0.0), np.full(n - 3 * (n // 4), 0.03)])
    close = 100 + np.cumsum(rng.normal(0, 0.4, n) + drift)
    wick = np.abs(rng.normal(0, 0.5, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": close, "close": close,
                         "high": close + wick, "low": close - wick,
                         "volume": rng.uniform(50, 200, n)}, index=idx)


def test_scales_are_actually_different():
    """🔴 ГЛАВНЫЙ: младший масштаб обязан ломаться ЧАЩЕ старшего.

    Если частоты сойдутся — «вторая структура» окажется первой, посчитанной
    дважды, и весь класс признаков превратится в дубль, который отбор ещё и
    примет за подтверждение.
    """
    df = _series()
    mn = _break_arrays(df, MINOR_LEN)["hits"].sum()
    mj = _break_arrays(df, MAJOR_LEN)["hits"].sum()
    assert mn > mj * 2, (
        f"младшая шкала ({mn} сломов) не отличается от старшей ({mj}) — "
        "масштабы выбраны так, что признаки согласования вырождены")


def test_causal_future_does_not_leak():
    """🔴 Усечение будущего не меняет уже посчитанное прошлое."""
    df = _series()
    cut = 2500
    full = structure_scales_features(df, "15m")
    trunc = structure_scales_features(df.iloc[:cut], "15m")
    edge = cut - MAJOR_LEN * 2          # у края свинги ещё не подтверждены
    bad = []
    for c in trunc.columns:
        a, b = full[c].iloc[:edge].values, trunc[c].iloc[:edge].values
        if (~((np.isnan(a) & np.isnan(b)) | np.isclose(a, b, equal_nan=True))).any():
            bad.append(c)
    assert not bad, f"look-ahead в признаках: {bad}"


def test_shifted_by_one_bar():
    """Состояние берётся с ЗАКРЫТОГО бара — первая строка обязана быть пустой."""
    E = structure_scales_features(_series(), "15m")
    assert E.iloc[0].isna().all(), "нет сдвига на бар — признак знает свой же бар"


def test_no_constant_columns():
    """Молчаливый отказ: колонка посчиталась, но не несёт информации."""
    E = structure_scales_features(_series(), "15m")
    assert len(E.columns) >= 15, f"семья схлопнулась до {len(E.columns)} признаков"
    const = [c for c in E.columns if E[c].dropna().nunique() <= 1]
    assert not const, f"константные признаки: {const}"


def test_minor_leg_counter_resets_on_major_break():
    """
    Номер младшей ноги обязан ОБНУЛЯТЬСЯ на старшем сломе, иначе это просто
    счётчик младших сломов от начала истории, а не «где мы внутри старшей ноги».
    """
    df = _series()
    E = structure_scales_features(df, "15m")
    col = E["sc_minor_since_major_15m"].dropna()
    assert col.min() <= 1.0, "счётчик ни разу не обнулился — привязки к старшей нет"
    assert col.max() < len(df) / 10, (
        f"счётчик дорос до {col.max():.0f} — похоже, растёт от начала истории")


def test_pullback_and_resume_are_mutually_exclusive():
    """Откат и возобновление — противоположные состояния, вместе быть не могут."""
    E = structure_scales_features(_series(), "15m")
    both = (E["sc_pullback_15m"] == 1.0) & (E["sc_resume_15m"] == 1.0)
    assert not both.any(), f"откат и возобновление совпали на {both.sum()} барах"


def test_agree_matches_directions():
    """sc_agree обязан быть производной от двух dir, а не независимым числом."""
    df = _series()
    E = structure_scales_features(df, "15m")
    m = E[["st5_dir_15m", "st50_dir_15m", "sc_agree_15m"]].dropna()
    assert len(m), "нет ни одного бара с обоими направлениями"
    expected = np.where(m.st5_dir_15m == m.st50_dir_15m, 1.0, -1.0)
    assert np.array_equal(m.sc_agree_15m.values, expected)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
