# -*- coding: utf-8 -*-
"""Волновая разметка обязана ВЫХОДИТЬ из шины, а не только лежать в ней.

Повод (02.10.2026): `WaveService` публикует разметку с 02.09, волновой контекст аналитика
(дневные ноги + 4h-пятёрка ЯДРА) — с 15.09, а `get_full_state` не отдавал ни одного из этих
полей. Снаружи — терминал, дашборд, DS — видели пусто: опрос 80 случайных пар живой шины
дал 0 с волновыми полями при логе «разметка по 119 парам».

Это ТРЕТИЙ случай того же класса в одном файле: так же молча терялись `smc_snap`/`pivot_snap`
(25.07) и оборот (29.09). Поэтому тест не про одно поле, а про ПРАВИЛО: всё, что сервис кладёт
в шину, читатель должен получить обратно.
"""
from __future__ import annotations

import pytest

from core.context.pair_context import PairContextBus

SYM = "BTC/USDT:USDT"

# Поля Сферы 20, которые публикуются в шину боевым кодом:
#   bot/loops/wave_loop.py → WaveService.compute_and_publish (elliott_*/wave_*),
#   current_leg (leg_*), wave_analyst.wave_bus_context (wave_leg_*/wave5_setup).
WAVE_FIELDS = [
    "elliott_n_down", "elliott_n_up", "elliott_phase", "elliott_conf",
    "wave_snap", "wave_recounts", "wave_recount_ts", "wave_updated_at",
    "leg_dir", "leg_span_bars", "leg_age_origin", "leg_pos", "leg_retr",
    "leg_minor_breaks", "leg_tf", "leg_updated_at",
    "wave_leg_up", "wave_leg_dn", "wave5_setup", "wave_ctx_updated_at",
]


@pytest.fixture()
def bus() -> PairContextBus:
    return PairContextBus()


@pytest.mark.parametrize("field", WAVE_FIELDS)
def test_field_is_exported(bus: PairContextBus, field: str):
    """Каждое волновое поле присутствует в снимке — иначе внешний читатель его не увидит."""
    assert field in bus.get_full_state(SYM), f"{field} не экспортируется get_full_state"


def test_core_of_wave_survives_roundtrip(bus: PairContextBus):
    """ЯДРО волн доезжает до читателя целиком: на `core_full` стоит измеренный эдж."""
    setup = {"side": "LONG", "top_time": "2026-10-02 04:00", "p0": 100.0, "p4": 118.0,
             "p5": 125.0, "imp_pct": 25.0, "core": True, "core_full": True}
    bus.update(SYM, wave5_setup=setup, elliott_phase="wave5_final", leg_dir=1, leg_pos=0.94)
    st = bus.get_full_state(SYM)
    assert st["wave5_setup"] == setup
    assert st["wave5_setup"]["core_full"] is True
    assert st["elliott_phase"] == "wave5_final"
    assert st["leg_dir"] == 1 and st["leg_pos"] == pytest.approx(0.94)


def test_untouched_pair_reports_empty_not_missing(bus: PairContextBus):
    """У непосчитанной пары поля есть, но пустые — читатель отличает «нет разметки» от «нет поля»."""
    st = bus.get_full_state("ETH/USDT:USDT")
    assert st["wave5_setup"] is None
    assert st["wave_ctx_updated_at"] is None
    assert st["elliott_n_down"] == 0
