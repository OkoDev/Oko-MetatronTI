# -*- coding: utf-8 -*-
"""Отбор waves_long по ширине стопа в долях импульса (03.10.2026).

Повод: замер 02.10 на 1427 LONG-сделках показал, что настоящая форма закона размера стопа —
доля ИМПУЛЬСА, а не процент цены:
  0-10% импульса → ср +0.52 (WR 16%, безтоп10% −908) · 10-20% → +2.89 · 20-30% → +2.22 ·
  **30-50% → +5.01 (WR 80%, Δr +10.76, Δt +1.63, безтоп +295)**
А бой стоял на медиане 0.129 — то есть в худших корзинах: 0 из 14 сделок попадали в коридор.

🔴 Отбор ОТМЕНЯЕТ прежнее правило «не отбирать заранее, резать результат потом» (17.09),
поэтому пороги живут в config (`trading.waves_long.stop_rel_min/max`) и снимаются одной правкой.
Тест фиксирует: арифметику доли, границы коридора (включая/исключая), поведение без порогов
и отказ считать при неизвестном импульсе — молчаливого нуля быть не должно.
"""
from __future__ import annotations

import pytest

from bot.loops.waves_long_loop import _stop_rel


def test_arithmetic_matches_measurement_units():
    """Стоп 12% цены при импульсе 40% = 0.30 импульса — нижняя граница коридора."""
    assert _stop_rel(100.0, 88.0, 40.0) == pytest.approx(0.30)
    # Медианный бой до правки: стоп 4.5% цены при импульсе 37.2% → 0.121 импульса.
    # (Поэлементная медиана по 14 сделкам БД — 0.129; отношение медиан ей не равно, это разные
    #  величины — здесь проверяется именно арифметика одной сделки.)
    assert _stop_rel(100.0, 95.5, 37.2) == pytest.approx(0.1210, abs=1e-4)


def test_direction_does_not_matter_for_width():
    """Берём модуль: ширина стопа не зависит от того, выше или ниже он входа."""
    assert _stop_rel(100.0, 90.0, 50.0) == _stop_rel(100.0, 110.0, 50.0)


@pytest.mark.parametrize("imp", [None, 0, 0.0, "", "нет"])
def test_unknown_impulse_returns_none_not_zero(imp):
    """Без импульса величина НЕИЗВЕСТНА. Ноль здесь означал бы «вне коридора» и тихо
    отбрасывал бы сигналы по несуществующей причине."""
    assert _stop_rel(100.0, 94.0, imp) is None


@pytest.mark.parametrize("entry", [0, -1, None, "abc"])
def test_bad_entry_returns_none(entry):
    assert _stop_rel(entry, 94.0, 40.0) is None


def _passes(rel, lo, hi):
    """Та же проверка границ, что в цикле: [lo; hi)."""
    if lo is None and hi is None:
        return True
    if rel is None:
        return False
    return not ((lo is not None and rel < float(lo)) or (hi is not None and rel >= float(hi)))


@pytest.mark.parametrize("rel,expect", [
    (0.129, False),   # медиана боя до правки — отсекается
    (0.299, False),
    (0.30, True),     # нижняя граница ВКЛЮЧЕНА
    (0.42, True),
    (0.499, True),
    (0.50, False),    # верхняя ИСКЛЮЧЕНА: корзина 30-50% мерилась как [0.3; 0.5)
    (0.80, False),
])
def test_corridor_boundaries(rel, expect):
    assert _passes(rel, 0.30, 0.50) is expect


def test_no_thresholds_means_no_gate():
    """Удалить ключи из конфига = вернуть прежний поток, включая узкие стопы."""
    assert _passes(0.05, None, None) is True
    assert _passes(None, None, None) is True


def test_one_sided_threshold_works():
    """Только нижний порог — коридор без верхней границы (вариант «стоп≥30% импульса»:
    n=54, ср +5.41, WR 83%)."""
    assert _passes(0.95, 0.30, None) is True
    assert _passes(0.20, 0.30, None) is False
