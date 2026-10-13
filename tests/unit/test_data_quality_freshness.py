# -*- coding: utf-8 -*-
"""Свежесть свечей проверяется на ФОРМАТЕ БОТА (13.10.2026, находка F02 внешнего аудита).

До правки `check_ohlcv_quality` читал время из `df.index[-1]`. У свечей бота RangeIndex + колонка `time`
(мс эпохи): индекс — номер строки, исключение проглатывалось, и свеча месячной давности возвращала `(True, 'ok')`.
Тесты на DatetimeIndex этого не ловили — поэтому здесь первым идёт формат бота.
"""
from __future__ import annotations


import pandas as pd
import pytest

from core.infra import data_quality as dq


def _bot_bars(last_open_age_sec: float, unit: str = "ms") -> pd.DataFrame:
    """ФОРМАТ БОТА из общей заготовки (паспорт данных, правило 8); последняя свеча открылась столько секунд назад."""
    from tests.factories import bot_bars
    return bot_bars(n=200, tf="15m", last_open_age_sec=last_open_age_sec, time_unit=unit)


def test_bot_format_month_old_candle_is_stale():
    ok, reason = dq.check_ohlcv_quality(_bot_bars(30 * 86400), timeframe="15m", symbol="TEST")
    assert ok is False and "устарели" in reason, "свеча месячной давности на формате бота прошла как свежая (F02)"


def test_bot_format_fresh_candle_passes():
    assert dq.check_ohlcv_quality(_bot_bars(5 * 60), timeframe="15m", symbol="TEST") == (True, "ok")


@pytest.mark.parametrize("age_min, expect_ok", [(29, True), (31, False)])
def test_limit_is_two_timeframes_from_open(age_min, expect_ok):
    """Порог автора не менялся: 2 × ТФ от открытия последней свечи (для 15m — 30 минут)."""
    ok, _ = dq.check_ohlcv_quality(_bot_bars(age_min * 60), timeframe="15m", symbol="TEST")
    assert ok is expect_ok


def test_time_in_seconds_is_understood():
    ok, reason = dq.check_ohlcv_quality(_bot_bars(30 * 86400, unit="s"), timeframe="15m", symbol="TEST")
    assert ok is False and "устарели" in reason


def test_datetime_index_still_works():
    df = _bot_bars(30 * 86400)
    df = df.set_index(pd.to_datetime(df["time"], unit="ms", utc=True)).drop(columns=["time"])
    ok, reason = dq.check_ohlcv_quality(df, timeframe="15m", symbol="TEST")
    assert ok is False and "устарели" in reason


def test_no_time_at_all_is_loud_not_silent(caplog, monkeypatch):
    """Время взять неоткуда: отсечь нельзя (нечем мерить), но молчать тоже нельзя — предупреждение в лог."""
    monkeypatch.setattr(dq, "_warned_no_time", False)
    df = _bot_bars(30 * 86400).drop(columns=["time"])
    with caplog.at_level("WARNING", logger=dq.logger.name):
        ok, _ = dq.check_ohlcv_quality(df, timeframe="15m", symbol="TEST")
    assert ok is True
    assert any("свежесть НЕ проверяется" in r.getMessage() for r in caplog.records)
