"""Селфтест Куба: три сферы, которые до 04.10.2026 работали без присмотра.

Смысл проверок — не «объект существует», а «данные свежие». Поэтому тесты бьют
ровно по тому, ради чего это писалось: встал цикл → отчёт обязан это показать,
а не отрапортовать полный порядок.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.selftest_cube import (
    ACTIVE, MISSING, SHADOW,
    _check_sphere_19_market_data,
    _check_sphere_20_wave_service,
)


def _bus(market=None, states=None):
    return SimpleNamespace(get_market=lambda: market, _states=states or {})


def _bot(**kw):
    return SimpleNamespace(**kw)


def _market(age_min: float, usdt_d=5.1, drift=-1.2):
    return SimpleNamespace(
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=age_min),
        usdt_d=usdt_d, ud_drift30=drift,
    )


# ── S19 Market Data ──────────────────────────────────────────────────────

def test_s19_fresh_market_is_active():
    r = _check_sphere_19_market_data(_bot(pair_context=_bus(_market(2))))
    assert r.code == "S19" and r.status == ACTIVE
    assert "USDT.D" in r.detail and "дрейф30" in r.detail


def test_s19_stale_market_is_shadow():
    """Луп ходит раз в 300 с: молчание дольше трёх интервалов — остановка."""
    r = _check_sphere_19_market_data(_bot(pair_context=_bus(_market(30))))
    assert r.status == SHADOW and "молчит" in r.detail


def test_s19_never_published_is_shadow():
    m = SimpleNamespace(updated_at=None, usdt_d=None, ud_drift30=None)
    r = _check_sphere_19_market_data(_bot(pair_context=_bus(m)))
    assert r.status == SHADOW and "ни разу" in r.detail


def test_s19_without_bus_is_missing():
    r = _check_sphere_19_market_data(_bot(pair_context=None))
    assert r.status == MISSING


def test_s19_survives_broken_bus():
    """Проверка не имеет права ронять селфтест целиком."""
    def boom():
        raise RuntimeError("шина сломана")
    r = _check_sphere_19_market_data(_bot(pair_context=SimpleNamespace(get_market=boom)))
    assert r.status == MISSING and "error" in r.detail


# ── S20 Wave Service ─────────────────────────────────────────────────────

def _pair_with_wave(age_h: float | None):
    ts = None if age_h is None else datetime.now(timezone.utc) - timedelta(hours=age_h)
    return SimpleNamespace(wave_updated_at=ts)


def test_s20_working_is_shadow_by_design():
    """ACTIVE у этой сферы не бывает: она ничего не гейтит по замыслу."""
    states = {"A": _pair_with_wave(0.5), "B": _pair_with_wave(1.0), "C": _pair_with_wave(9.0)}
    r = _check_sphere_20_wave_service(_bot(
        wave_service=object(), pair_context=_bus(states=states),
        wave_started_at=datetime.now(timezone.utc) - timedelta(hours=3),
        wave_last_pass_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
    assert r.status == SHADOW
    assert "разметка у 3 пар" in r.detail and "свежей (<2ч) 2" in r.detail


def test_s20_loop_not_started_is_missing():
    r = _check_sphere_20_wave_service(_bot(wave_service=None, pair_context=_bus(states={})))
    assert r.status == MISSING and "луп не стартовал" in r.detail


def test_s20_started_but_no_marks_is_missing():
    """Главный случай ради которого всё писалось: процесс жив, работы нет."""
    states = {"A": _pair_with_wave(None), "B": _pair_with_wave(None)}
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    r = _check_sphere_20_wave_service(_bot(wave_service=object(), pair_context=_bus(states=states),
                                           wave_started_at=old, wave_last_pass_at=None))
    assert r.status == MISSING and "НЕТ ни одной волновой разметки" in r.detail


def test_s20_warmup_after_restart_is_not_an_alarm():
    """Поймано на живом боте: через 45 с после рестарта разметки ещё нет по определению.
    Прибор, который кричит на каждый рестарт, перестают читать."""
    states = {"A": _pair_with_wave(None)}
    just = datetime.now(timezone.utc) - timedelta(minutes=3)
    r = _check_sphere_20_wave_service(_bot(wave_service=object(), pair_context=_bus(states=states),
                                           wave_started_at=just, wave_last_pass_at=None))
    assert r.status == SHADOW and "прогрев" in r.detail


def test_s20_stuck_loop_is_missing():
    """Луп жив, разметка в шине есть, но проходов нет два интервала — завис."""
    states = {"A": _pair_with_wave(1.0)}
    r = _check_sphere_20_wave_service(_bot(
        wave_service=object(), pair_context=_bus(states=states),
        wave_started_at=datetime.now(timezone.utc) - timedelta(hours=5),
        wave_last_pass_at=datetime.now(timezone.utc) - timedelta(minutes=40)))
    assert r.status == MISSING and "завис" in r.detail


# ── S13_PHASE ────────────────────────────────────────────────────────────

def test_phase_uses_fresh_db(tmp_path, monkeypatch):
    import sqlite3
    import time

    from core.selftest_cube import _check_sphere_13_phase

    db = tmp_path / "phase.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE phase_state (level TEXT, symbol TEXT, phase TEXT, side TEXT, "
              "confidence REAL, concordance TEXT, ts INTEGER)")
    c.execute("INSERT INTO phase_state VALUES ('macro', NULL, 'TREND_UP', 'LONG', 0.7, NULL, ?)",
              (int(time.time()),))
    c.commit(); c.close()

    from core.infra import sat_store
    monkeypatch.setattr(sat_store, "path", lambda _n: db)

    bot = SimpleNamespace(config=SimpleNamespace(get=lambda k, d=None: False))
    r = _check_sphere_13_phase(bot)
    # данные свежие, но гейт выключен — на решения сфера не влияет
    assert r.status == SHADOW and "гейт=выкл" in r.detail and "TREND_UP" in r.detail

    bot_guard = SimpleNamespace(config=SimpleNamespace(get=lambda k, d=None: True))
    assert _check_sphere_13_phase(bot_guard).status == ACTIVE


def test_phase_stale_db_is_flagged(tmp_path, monkeypatch):
    import sqlite3
    import time

    from core.selftest_cube import _check_sphere_13_phase

    db = tmp_path / "phase.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE phase_state (level TEXT, symbol TEXT, phase TEXT, side TEXT, "
              "confidence REAL, concordance TEXT, ts INTEGER)")
    c.execute("INSERT INTO phase_state VALUES ('macro', NULL, 'CHOP', NULL, 0.3, NULL, ?)",
              (int(time.time()) - 5 * 3600,))
    c.commit(); c.close()

    from core.infra import sat_store
    monkeypatch.setattr(sat_store, "path", lambda _n: db)

    bot = SimpleNamespace(config=SimpleNamespace(get=lambda k, d=None: True))
    r = _check_sphere_13_phase(bot)
    assert r.status == SHADOW and "протухли" in r.detail


def test_phase_missing_db(tmp_path, monkeypatch):
    from core.selftest_cube import _check_sphere_13_phase
    from core.infra import sat_store
    monkeypatch.setattr(sat_store, "path", lambda _n: tmp_path / "нет-такой.db")
    bot = SimpleNamespace(config=SimpleNamespace(get=lambda k, d=None: False))
    assert _check_sphere_13_phase(bot).status == MISSING
