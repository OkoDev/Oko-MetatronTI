# -*- coding: utf-8 -*-
"""Харнесс берёт данные из того хранилища, которое выбрано (ARCH-147.11, правило 8 паспорта данных).

13.10.2026: хранилищ три, и у каждого своя работа — онлайн для боя, лабораторные паркеты для замеров,
старый общий кэш. Харнесс читал третье, поэтому замеры на 3m/5m шли по данным апреля и мая. Теперь
первичный источник — лабораторные паркеты, переключатель `OKO_HARNESS_SOURCE=cache` оставлен для сверки
старых выводов. Эти тесты закрепляют: имена символов, чтение, отбор вселенной и предупреждение о свежести.
"""
from __future__ import annotations

import pandas as pd
import pytest

import scripts.research_harness as h


# ── имена символов ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("sym, expect", [
    ("BTC/USDT:USDT", "BTCUSDT"),
    ("BTC/USDT", "BTCUSDT"),
    ("1000000BOB/USDT", "1000000BOBUSDT"),
    ("BTCUSDT", "BTCUSDT"),
])
def test_symbol_to_parquet_name(sym, expect):
    assert h._lab_sym(sym) == expect


def test_parquet_path_includes_timeframe():
    p = h._lab_path("BTC/USDT:USDT", "15m")
    assert p.name == "BTCUSDT.parquet" and p.parent.name == "15m"


# ── чтение ───────────────────────────────────────────────────────────────────

def _write(tmp_path, sym: str, tf: str, n: int = 100, start="2026-01-01", tz=None):
    d = pd.DataFrame({"open": 1.0, "high": 1.5, "low": 0.5, "close": 1.2, "volume": 10.0},
                     index=pd.date_range(start, periods=n, freq="15min", tz=tz))
    p = tmp_path / tf
    p.mkdir(parents=True, exist_ok=True)
    d.to_parquet(p / f"{sym}.parquet")
    return d


def test_load_reads_parquet_and_returns_utc(monkeypatch, tmp_path):
    _write(tmp_path, "BTCUSDT", "15m")
    monkeypatch.setattr(h, "SOURCE", "lab")
    monkeypatch.setattr(h, "LAB_TF", tmp_path)
    d = h.load("BTC/USDT", "15m")
    assert len(d) == 100
    assert str(d.index.tz) == "UTC", "наружу индекс обязан быть с зоной UTC: на диске он без зоны"
    assert list(d.columns) == ["open", "high", "low", "close", "volume"]


def test_load_returns_empty_when_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "SOURCE", "lab")
    monkeypatch.setattr(h, "LAB_TF", tmp_path)
    assert h.load("NOSUCH/USDT", "15m").empty


# ── отбор вселенной ──────────────────────────────────────────────────────────

def test_universe_filters_by_bar_count(monkeypatch, tmp_path):
    _write(tmp_path, "BIGUSDT", "15m", n=300)
    _write(tmp_path, "SMALLUSDT", "15m", n=50)
    monkeypatch.setattr(h, "SOURCE", "lab")
    monkeypatch.setattr(h, "LAB_TF", tmp_path)
    monkeypatch.setattr(h, "warn_if_stale", lambda tf: None)
    monkeypatch.setattr("core.smc.impulse_fib.is_junk", lambda s: False, raising=False)
    out = h.universe("15m", min_bars=100, n=10)
    assert out == ["BIG/USDT"], "монета короче порога во вселенную не попадает"


def test_core_universe_requires_full_window(monkeypatch, tmp_path):
    """Балансированная панель: монета обязана существовать на ВСЁМ окне, иначе годы несравнимы."""
    _write(tmp_path, "FULLUSDT", "15m", n=400, start="2026-01-01")
    _write(tmp_path, "LATEUSDT", "15m", n=400, start="2026-03-01")
    monkeypatch.setattr(h, "SOURCE", "lab")
    monkeypatch.setattr(h, "LAB_TF", tmp_path)
    monkeypatch.setattr(h, "warn_if_stale", lambda tf: None)
    monkeypatch.setattr("core.smc.impulse_fib.is_junk", lambda s: False, raising=False)
    out = h.core_universe("15m", since="2026-01-02", until="2026-01-03", min_bars=100)
    assert out == ["FULL/USDT"], "монета, появившаяся позже начала окна, в панель не входит"


def test_core_universe_refuses_empty_result(monkeypatch, tmp_path):
    """Пустая вселенная — это отказ, а не тихий ноль: иначе замер «не нашёл ничего» и промолчит."""
    _write(tmp_path, "FULLUSDT", "15m", n=200, start="2026-01-01")
    monkeypatch.setattr(h, "SOURCE", "lab")
    monkeypatch.setattr(h, "LAB_TF", tmp_path)
    monkeypatch.setattr(h, "warn_if_stale", lambda tf: None)
    with pytest.raises(RuntimeError, match="НОЛЬ монет"):
        h.core_universe("15m", since="2020-01-01", until="2020-02-01", min_bars=10)


# ── свежесть ─────────────────────────────────────────────────────────────────

def test_age_is_measured_on_the_chosen_source(monkeypatch, tmp_path):
    _write(tmp_path, "BTCUSDT", "15m", n=10, start=pd.Timestamp.utcnow().floor("D") - pd.Timedelta(days=10))
    monkeypatch.setattr(h, "SOURCE", "lab")
    monkeypatch.setattr(h, "LAB_TF", tmp_path)
    age = h.data_age_days("15m")
    assert age is not None and 9 < age < 11


def test_stale_data_warns_once(monkeypatch, tmp_path, capsys):
    _write(tmp_path, "BTCUSDT", "15m", n=10, start=pd.Timestamp.utcnow().floor("D") - pd.Timedelta(days=30))
    monkeypatch.setattr(h, "SOURCE", "lab")
    monkeypatch.setattr(h, "LAB_TF", tmp_path)
    monkeypatch.setattr(h, "_FRESH_SAID", set())
    h.warn_if_stale("15m")
    h.warn_if_stale("15m")
    out = capsys.readouterr().out
    assert out.count("отстаёт") == 1, "предупреждение одно на таймфрейм за запуск"


def test_fresh_data_is_silent(monkeypatch, tmp_path, capsys):
    _write(tmp_path, "BTCUSDT", "15m", n=10, start=pd.Timestamp.utcnow().floor("h") - pd.Timedelta(hours=2))
    monkeypatch.setattr(h, "SOURCE", "lab")
    monkeypatch.setattr(h, "LAB_TF", tmp_path)
    monkeypatch.setattr(h, "_FRESH_SAID", set())
    h.warn_if_stale("15m")
    assert "отстаёт" not in capsys.readouterr().out
