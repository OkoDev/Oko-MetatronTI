# -*- coding: utf-8 -*-
"""Персист волнового контекста и догоняющий прогрев (04.10.2026).

Повод — замер: контекста в шине **0 из 100 пар** через 25 минут после рестарта, хотя каузальный
расчёт сетапы находит; до рестарта было накоплено 497 пар. `wave5_setup` жил только в памяти
процесса, полный прогрев 569 пар занимал ~75 минут, а бот за сутки перезапускался 11 раз —
значит потребители (`wave_zone_for` → features_json сделок) заметную часть времени видели пусто
и считали «импульса нет».

Две правки: снимок контекста на диск после каждого прохода + догоняющий режим (не спать полный
интервал, пока окно не обошло вселенную).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from bot.loops.wave_loop import (CATCHUP_SLEEP_SEC, INTERVAL_SEC, STATE_MAX_AGE_H,
                                 _load_ctx_state, _save_ctx_state)
from core.context.pair_context import PairContextBus

SETUP = {"side": "LONG", "top_time": "2026-10-04 12:00", "p0": 1.0, "p4": 1.18,
         "p5": 1.25, "imp_pct": 25.0, "core": True, "core_full": True}


@pytest.fixture()
def bus_with_ctx(monkeypatch, tmp_path):
    import bot.loops.wave_loop as wl
    monkeypatch.setattr(wl, "STATE_FILE", tmp_path / "wave_ctx_state.json")
    bus = PairContextBus()
    bus.update("BTC/USDT:USDT", wave5_setup=SETUP, leg_dir=1, leg_pos=0.93,
               wave_ctx_updated_at=datetime.now(timezone.utc))
    bus.update("ETH/USDT:USDT", wave5_setup=None, leg_dir=-1,
               wave_ctx_updated_at=datetime.now(timezone.utc))
    bus.update("SOL/USDT:USDT")           # без контекста — в снимок не попадает
    return bus, wl


def test_snapshot_saves_only_pairs_with_context(bus_with_ctx):
    bus, wl = bus_with_ctx
    n = _save_ctx_state(bus)
    assert n == 2, "в снимок должны попасть только пары с посчитанным контекстом"
    data = json.loads(wl.STATE_FILE.read_text(encoding="utf-8"))
    assert set(data) == {"BTC/USDT:USDT", "ETH/USDT:USDT"}
    assert data["BTC/USDT:USDT"]["wave5_setup"]["core_full"] is True


def test_context_survives_restart(bus_with_ctx):
    """Главное: после «рестарта» ЯДРО доступно сразу, а не через 75 минут."""
    bus, wl = bus_with_ctx
    _save_ctx_state(bus)
    fresh = PairContextBus()                                   # как после перезапуска процесса
    assert fresh.get_full_state("BTC/USDT:USDT")["wave5_setup"] is None
    ok, old = _load_ctx_state(fresh)
    assert ok == 2 and old == 0
    st = fresh.get_full_state("BTC/USDT:USDT")
    assert st["wave5_setup"] == SETUP
    assert st["leg_dir"] == 1 and st["leg_pos"] == pytest.approx(0.93)
    assert isinstance(st["wave_ctx_updated_at"], datetime), "метка времени обязана остаться datetime"


def test_stale_context_is_not_restored(bus_with_ctx):
    """Контекст старше порога не поднимаем: лучше пусто, чем древнее, принятое за свежее."""
    bus, wl = bus_with_ctx
    old_ts = datetime.now(timezone.utc) - timedelta(hours=STATE_MAX_AGE_H + 1)
    bus.update("BTC/USDT:USDT", wave_ctx_updated_at=old_ts)
    _save_ctx_state(bus)
    fresh = PairContextBus()
    ok, old = _load_ctx_state(fresh)
    assert old >= 1, "устаревшая запись должна быть пропущена"
    assert fresh.get_full_state("BTC/USDT:USDT")["wave5_setup"] is None


def test_missing_file_is_safe(monkeypatch, tmp_path):
    import bot.loops.wave_loop as wl
    monkeypatch.setattr(wl, "STATE_FILE", tmp_path / "нет-такого.json")
    assert _load_ctx_state(PairContextBus()) == (0, 0)


def test_broken_file_is_safe(monkeypatch, tmp_path):
    """Битый снимок не должен ронять луп на старте."""
    import bot.loops.wave_loop as wl
    p = tmp_path / "wave_ctx_state.json"
    p.write_text("{это не json", encoding="utf-8")
    monkeypatch.setattr(wl, "STATE_FILE", p)
    assert _load_ctx_state(PairContextBus()) == (0, 0)


@pytest.mark.parametrize("n_all,n_touched,expect", [
    (569, 120, CATCHUP_SLEEP_SEC),      # первый круг не завершён → догоняем
    (569, 568, CATCHUP_SLEEP_SEC),      # осталась одна пара → всё ещё догоняем
    (569, 569, INTERVAL_SEC),           # круг закрыт → штатный интервал
    (569, 600, INTERVAL_SEC),           # пар стало меньше, чем обойдено → штатный
])
def test_catchup_sleep_rule(n_all, n_touched, expect):
    """Та же арифметика, что в цикле: спим штатно только после полного обхода вселенной."""
    left = max(0, n_all - n_touched)
    assert (CATCHUP_SLEEP_SEC if left else INTERVAL_SEC) == expect


def test_catchup_is_much_shorter_than_interval():
    """Смысл правки: пауза догоняющего режима на порядок меньше штатной."""
    assert CATCHUP_SLEEP_SEC < INTERVAL_SEC / 10
    assert CATCHUP_SLEEP_SEC > 0, "ноль не годится: сканy нужно дать вдохнуть между проходами"
