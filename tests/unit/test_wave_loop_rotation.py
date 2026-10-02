# -*- coding: utf-8 -*-
"""Окно волнового лупа обязано ЕХАТЬ по кругу, а не стоять на первых 120 парах.

Повод (02.10.2026): `wave_loop` брал `all_symbols()[:MAX_SYMBOLS]`, а порядок ключей шины
стабилен — поэтому волновую разметку получали всегда одни и те же 120 пар из 584, а остальные
~464 не получали её никогда (в логе «в шине 118» не рос между проходами, хотя тень считает 588
монет своим процессом).

Почему именно ротация, а не больше пар за проход — замер 02.10: расчёт 49 мс/пару
(584 пары = 29 с CPU), но проход идёт 450-490 с на 119 пар, потому что время уходит в получение
свечей. На 584 парах проход занял бы ~2250 с против интервала 900 с.

Тест проверяет арифметику окна в отрыве от бота: ту же формулу, что в цикле.
"""
from __future__ import annotations

import pytest

from bot.loops.wave_loop import MAX_SYMBOLS


def _window(allsym: list[str], offset: int, take: int) -> tuple[list[str], int]:
    """Копия арифметики окна из `wave_loop` (цикл while True)."""
    n_all = len(allsym)
    if not n_all:
        return [], offset
    offset %= n_all
    take = min(take, n_all)
    syms = [allsym[(offset + i) % n_all] for i in range(take)]
    return syms, (offset + take) % n_all


def test_passes_cover_whole_universe():
    """За ceil(584/120) проходов каждая пара получает разметку хотя бы раз."""
    universe = [f"C{i}/USDT:USDT" for i in range(584)]
    seen: set[str] = set()
    offset = 0
    passes = 0
    while len(seen) < len(universe):
        syms, offset = _window(universe, offset, MAX_SYMBOLS)
        seen.update(syms)
        passes += 1
        assert passes <= 10, "вселенная не покрылась за 10 проходов — окно не едет"
    assert seen == set(universe)
    assert passes == -(-len(universe) // MAX_SYMBOLS)   # ровно ceil, без холостых проходов


def test_second_pass_takes_different_pairs():
    """Главный регресс: второй проход НЕ повторяет первый."""
    universe = [f"C{i}" for i in range(584)]
    first, off = _window(universe, 0, MAX_SYMBOLS)
    second, _ = _window(universe, off, MAX_SYMBOLS)
    assert first != second
    assert not (set(first) & set(second)), "окна пересеклись — часть пар опрашивается дважды"


def test_window_wraps_around_the_end():
    """На стыке окно переходит через конец списка, а не обрезается."""
    universe = [f"C{i}" for i in range(10)]
    syms, off = _window(universe, 8, 4)
    assert syms == ["C8", "C9", "C0", "C1"]
    assert off == 2


def test_universe_smaller_than_window():
    """Шина меньше окна — берём всех по одному разу, без дублей."""
    universe = ["A", "B", "C"]
    syms, off = _window(universe, 0, MAX_SYMBOLS)
    assert syms == universe and len(set(syms)) == 3
    assert off == 0


def test_empty_bus_is_safe():
    assert _window([], 0, MAX_SYMBOLS) == ([], 0)


@pytest.mark.parametrize("n_all", [1, 7, 119, 120, 121, 584, 1000])
def test_offset_stays_in_range(n_all: int):
    """Смещение не выходит за пределы шины при любом её размере — иначе IndexError в бою."""
    universe = [f"C{i}" for i in range(n_all)]
    offset = 0
    for _ in range(12):
        syms, offset = _window(universe, offset, MAX_SYMBOLS)
        assert 0 <= offset < n_all
        assert len(syms) == min(MAX_SYMBOLS, n_all)
        assert len(set(syms)) == len(syms), "пара попала в одно окно дважды"
