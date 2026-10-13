# -*- coding: utf-8 -*-
"""Паспорт данных, правило 1: одна свеча — один формат (docs/DATA_CONTRACT.md, ARCH-147).

Закрепляет: время последней свечи берётся только из `core.infra.candles.last_bar_time`, номер строки временем
не считается; `violations` называет каждое нарушение формы своим кодом; наблюдатель считает и не мешает.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from core.infra import candles as cd
from tests.conftest import make_ohlcv
from tests.factories import TF_MS, bot_bars, shifted

T0 = 1_760_000_000_000 // TF_MS["15m"] * TF_MS["15m"]          # отметка на сетке 15m
NOW = datetime.fromtimestamp(T0 / 1000, tz=timezone.utc) + timedelta(minutes=5)


# ── время последней свечи ────────────────────────────────────────────────────

def test_last_bar_time_reads_time_column_not_row_number():
    df = bot_bars(last_open_ms=T0)
    assert df.index[-1] == len(df) - 1, "заготовка должна повторять формат бота"
    assert cd.last_bar_time(df) == datetime.fromtimestamp(T0 / 1000, tz=timezone.utc)


def test_same_row_numbers_different_time():
    """Суть ошибки 13.10: окно сдвинулось, номера строк те же — время обязано отличаться."""
    a = bot_bars(last_open_ms=T0)
    b = shifted(a, 3)
    assert list(a.index) == list(b.index)
    assert cd.last_bar_time(b) - cd.last_bar_time(a) == timedelta(minutes=45)


def test_last_bar_time_seconds_and_datetime_index():
    df = bot_bars(last_open_ms=T0, time_unit="s")
    assert cd.last_bar_time(df) == datetime.fromtimestamp(T0 / 1000, tz=timezone.utc)
    di = bot_bars(last_open_ms=T0)
    di = di.set_index(pd.to_datetime(di["time"], unit="ms", utc=True)).drop(columns=["time"])
    assert cd.last_bar_time(di) == datetime.fromtimestamp(T0 / 1000, tz=timezone.utc)


@pytest.mark.parametrize("df", [None, pd.DataFrame(), bot_bars(last_open_ms=T0).drop(columns=["time"])])
def test_last_bar_time_none_when_no_time(df):
    assert cd.last_bar_time(df) is None, "номер строки не должен выдаваться за время"


# ── проверка формы ───────────────────────────────────────────────────────────

def test_clean_bars_have_no_violations():
    assert cd.violations(bot_bars(last_open_ms=T0), "15m", now=NOW) == []


def test_shared_fixture_obeys_the_contract():
    """Общая заготовка тестов сама обязана проходить паспорт (её шаг — минута)."""
    assert cd.violations(make_ohlcv(120), "1m") == []


def _broken(kind: str) -> pd.DataFrame:
    df = bot_bars(last_open_ms=T0)
    t = df["time"].to_numpy().copy()
    if kind == "time_duplicate":
        t[-1] = t[-2]
    elif kind == "time_not_sorted":
        t[-1], t[-2] = t[-2], t[-1]
    elif kind == "gap":
        t[:100] -= 5 * TF_MS["15m"]
    elif kind == "step_off_grid":
        t[-1] += 60_000
    elif kind == "time_in_future":
        t += 10 * TF_MS["15m"]
    df["time"] = t
    if kind == "time_not_ms":
        df["time"] = df["time"] // 1000
    if kind == "ohlc_nan":
        df.loc[df.index[-1], "close"] = np.nan
    return df


@pytest.mark.parametrize("kind", ["time_duplicate", "time_not_sorted", "gap", "step_off_grid", "time_in_future",
                                  "time_not_ms", "ohlc_nan"])
def test_each_violation_is_named(kind):
    assert kind in cd.violations(_broken(kind), "15m", now=NOW)


def test_missing_column_and_empty():
    assert cd.violations(bot_bars(last_open_ms=T0).drop(columns=["volume"]), "15m") == ["no_column:volume"]
    assert cd.violations(None, "15m") == ["empty"]
    assert cd.violations(pd.DataFrame(), "15m") == ["empty"]


def test_datetime_index_frame_is_not_bot_format():
    di = bot_bars(last_open_ms=T0)
    di = di.set_index(pd.to_datetime(di["time"], unit="ms", utc=True)).drop(columns=["time"])
    assert cd.violations(di, "15m") == ["no_column:time"]


# ── наблюдатель ──────────────────────────────────────────────────────────────

def test_watch_counts_and_does_not_raise():
    w = cd.CandleWatch()
    w.observe(bot_bars(last_open_ms=T0), "15m", "BTC/USDT:USDT")
    w.observe(_broken("time_duplicate"), "15m", "ETH/USDT:USDT")
    w.observe(_broken("gap"), "15m", "SOL/USDT:USDT")
    w.observe(object(), "15m", "BAD")                       # мусор на входе — наблюдатель не падает
    rep = w.report()
    assert rep["checked"] == 4 and rep["bad"] == 3
    assert rep["kinds"]["time_duplicate"] == 1 and rep["kinds"]["gap"] == 1
    assert rep["examples"]["time_duplicate"] == "ETH/USDT:USDT 15m"
    assert w.report()["checked"] == 0, "отчёт обязан сбрасывать счётчики"


def test_report_line_separates_form_errors_from_gaps():
    line = cd.report_line({"checked": 10, "bad": 3, "kinds": {"gap": 2, "time_duplicate": 1},
                           "examples": {"time_duplicate": "ETH/USDT:USDT 15m"}})
    assert "проверено 10" in line and "с нарушением формы 1" in line and "с пропусками 2" in line
    assert "time_duplicate×1 (ETH/USDT:USDT 15m)" in line
