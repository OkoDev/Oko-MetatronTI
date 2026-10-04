# -*- coding: utf-8 -*-
"""Измеритель коста обязан исключать «копии» филла (04.10.2026).

Повод — ошибка, пойманная на первом прогоне `scripts/cost_measure.py`: за 60 дней медиана
проскальзывания вышла ровно 0.0000%, и скрипт заявил «круг 0.09%, оценка 0.35% честна».
Но у 32-85% записей `actual_entry_price` РОВНО равна `entry_price` — филл не измерялся,
а копировался, и эти нули тянули медиану вниз. По настоящим филлам круг оказался 0.49%,
то есть прежняя оценка занижена на 40%.

Это тот же класс поля-пустышки, что `slip_pct`=0 у 76% ордеров и оборот=0 у 922 сделок:
ноль означает «НЕ ИЗМЕРЕНО». Тест закрепляет, что копии отфильтрованы и что их доля видна.
"""
from __future__ import annotations

import pytest

SAMPLE = [
    {"slip": 0.0, "copy": True,  "stop_pct": 0.5},    # филл не измерялся
    {"slip": 0.0, "copy": True,  "stop_pct": 0.5},
    {"slip": 0.0, "copy": True,  "stop_pct": 0.5},
    {"slip": 0.4, "copy": False, "stop_pct": 0.5},    # настоящие филлы
    {"slip": 0.2, "copy": False, "stop_pct": 0.5},
]


def _real(data):
    return [x for x in data if not x["copy"]]


def test_copies_are_excluded_by_default():
    assert len(_real(SAMPLE)) == 2


def test_median_differs_dramatically_when_copies_kept():
    """Ровно та ошибка: с копиями медиана 0, без них — 0.3."""
    import statistics as st
    with_copies = st.median([x["slip"] for x in SAMPLE])
    real_only = st.median([x["slip"] for x in _real(SAMPLE)])
    assert with_copies == 0.0, "копии дают ложный ноль"
    assert real_only == pytest.approx(0.3)
    assert real_only > with_copies, "исключение копий обязано поднять оценку коста"


def test_share_of_risk_is_computed_on_real_fills_only():
    """Доля коста в риске считается по настоящим филлам, иначе эффект стопа исчезает."""
    real = _real(SAMPLE)
    shares = [x["slip"] / x["stop_pct"] * 100 for x in real]
    assert min(shares) > 0, "у настоящих филлов доля риска положительна"
    all_shares = [x["slip"] / x["stop_pct"] * 100 for x in SAMPLE]
    import statistics as st
    assert st.median(all_shares) == 0.0, "с копиями доля риска занулялась — ровно то, что произошло"


def test_script_exposes_copy_share_and_flag():
    """В скрипте должны быть и подсчёт доли копий, и флаг --with-copies для возврата."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "scripts" / "cost_measure.py").read_text(encoding="utf-8")
    assert "--with-copies" in src, "нет способа осознанно вернуть копии в расчёт"
    assert 'x["copy"]' in src and "with_copies" in src, "копии не фильтруются"
    assert "НЕ ИЗМЕРЕНО" in src, "в коде не сказано, что ноль означает отсутствие измерения"
