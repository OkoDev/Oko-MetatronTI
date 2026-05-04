"""
Тесты DEV-11: Future Pivots — проактивное прогнозирование уровней.

Проверяем:
  1. get_future_daily/weekly/monthly_pivots — расчёт PP/S/R из текущего периода
  2. TTL-кеш: повторный вызов возвращает кешированный результат (без API)
  3. check_future_classic_confluence — конфлюэнция Future × Classic
  4. Граничные случаи: пустые данные, нулевая цена, threshold_pct
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from core.pivots.pivot_calculator_fixed import PivotCalculatorFixed
from core.confluence.confluence_scanner import check_future_classic_confluence


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 10, start_ts_ms: int = None) -> pd.DataFrame:
    """Создаёт OHLCV DataFrame с n свечами."""
    if start_ts_ms is None:
        # Начало сегодняшнего дня UTC
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ts_ms = int(day_start.timestamp() * 1000)
    interval_ms = 60 * 60 * 1000  # 1h
    times = [start_ts_ms + i * interval_ms for i in range(n)]
    return pd.DataFrame({
        "time":   times,
        "open":   [100.0] * n,
        "high":   [110.0 + i * 2 for i in range(n)],
        "low":    [90.0 - i * 1 for i in range(n)],
        "close":  [105.0 + i for i in range(n)],
        "volume": [1000.0] * n,
    })


def _make_data_collector(df: Optional[pd.DataFrame]) -> Any:
    """Создаёт мок data_collector.get_ohlcv."""
    dc = MagicMock()
    dc.get_ohlcv = AsyncMock(return_value=df)
    return dc


def _calc() -> PivotCalculatorFixed:
    """Создаёт PivotCalculatorFixed без БД."""
    return PivotCalculatorFixed.__new__(PivotCalculatorFixed)


# ── Future Daily Pivots ───────────────────────────────────────────────────────

class TestFutureDailyPivots:

    def test_returns_pivots_with_correct_keys(self):
        """[01] Возвращает dict с PP, S1-S5, R1-R5."""
        calc = _calc()
        calc.pivot_cache = {}
        dc = _make_data_collector(_make_ohlcv(n=8))

        result = asyncio.get_event_loop().run_until_complete(
            calc.get_future_daily_pivots("BTCUSDT", dc)
        )
        assert result is not None
        assert "PP" in result
        assert "S1" in result
        assert "R1" in result
        assert result["timeframe"] == "future_1D"

    def test_pp_is_average_of_high_low_close(self):
        """[02] PP = (H + L + C) / 3 (Traditional formula)."""
        calc = _calc()
        calc.pivot_cache = {}

        # Одна свеча: H=110, L=90, C=105
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        df = pd.DataFrame({
            "time":   [int(day_start.timestamp() * 1000)],
            "open":   [100.0],
            "high":   [110.0],
            "low":    [90.0],
            "close":  [105.0],
            "volume": [1000.0],
        })
        dc = _make_data_collector(df)

        result = asyncio.get_event_loop().run_until_complete(
            calc.get_future_daily_pivots("BTCUSDT", dc)
        )
        assert result is not None
        expected_pp = (110.0 + 90.0 + 105.0) / 3
        assert abs(result["PP"] - expected_pp) < 0.001

    def test_ttl_cache_hit(self):
        """[03] Повторный вызов с активным TTL → не обращается к API."""
        calc = _calc()
        cache_key = "BTCUSDT_future_1D"
        calc.pivot_cache = {
            cache_key: {
                "PP": 99.9, "S1": 95.0, "R1": 105.0,
                "timeframe": "future_1D",
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
            }
        }
        dc = _make_data_collector(None)  # не должен вызываться

        result = asyncio.get_event_loop().run_until_complete(
            calc.get_future_daily_pivots("BTCUSDT", dc, ttl_sec=60)
        )
        assert result is not None
        assert result["PP"] == 99.9
        dc.get_ohlcv.assert_not_called()

    def test_ttl_cache_expired_refetches(self):
        """[04] Истёкший TTL → пересчитывает."""
        calc = _calc()
        cache_key = "BTCUSDT_future_1D"
        calc.pivot_cache = {
            cache_key: {
                "PP": 99.9,
                "timeframe": "future_1D",
                "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),  # уже истёк
            }
        }
        dc = _make_data_collector(_make_ohlcv(n=5))

        result = asyncio.get_event_loop().run_until_complete(
            calc.get_future_daily_pivots("BTCUSDT", dc, ttl_sec=60)
        )
        assert result is not None
        dc.get_ohlcv.assert_called_once()

    def test_returns_none_on_empty_df(self):
        """[05] Пустой DataFrame → None."""
        calc = _calc()
        calc.pivot_cache = {}
        dc = _make_data_collector(pd.DataFrame())

        result = asyncio.get_event_loop().run_until_complete(
            calc.get_future_daily_pivots("BTCUSDT", dc)
        )
        assert result is None

    def test_returns_none_when_df_is_none(self):
        """[06] None от data_collector → None."""
        calc = _calc()
        calc.pivot_cache = {}
        dc = _make_data_collector(None)

        result = asyncio.get_event_loop().run_until_complete(
            calc.get_future_daily_pivots("BTCUSDT", dc)
        )
        assert result is None

    def test_period_label_contains_live(self):
        """[07] period_label содержит '(live)' — признак future пивота."""
        calc = _calc()
        calc.pivot_cache = {}
        dc = _make_data_collector(_make_ohlcv(n=3))

        result = asyncio.get_event_loop().run_until_complete(
            calc.get_future_daily_pivots("ETHUSDT", dc)
        )
        if result:
            assert "(live)" in result.get("period_label", "")


# ── Future Weekly Pivots ──────────────────────────────────────────────────────

class TestFutureWeeklyPivots:

    def _week_start_ohlcv(self, n: int = 20) -> pd.DataFrame:
        """OHLCV начиная с понедельника текущей недели."""
        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start_ts = int(week_start.timestamp() * 1000)
        interval_ms = 4 * 60 * 60 * 1000  # 4h
        times = [start_ts + i * interval_ms for i in range(n)]
        return pd.DataFrame({
            "time":   times,
            "open":   [200.0] * n,
            "high":   [220.0 + i for i in range(n)],
            "low":    [180.0 - i for i in range(n)],
            "close":  [210.0] * n,
            "volume": [5000.0] * n,
        })

    def test_weekly_returns_pivots(self):
        """[08] get_future_weekly_pivots → dict с PP/S/R."""
        calc = _calc()
        calc.pivot_cache = {}
        dc = _make_data_collector(self._week_start_ohlcv())

        result = asyncio.get_event_loop().run_until_complete(
            calc.get_future_weekly_pivots("BTCUSDT", dc)
        )
        assert result is not None
        assert "PP" in result
        assert result["timeframe"] == "future_1W"

    def test_weekly_cache_hit(self):
        """[09] TTL-кеш 1W работает аналогично 1D."""
        calc = _calc()
        calc.pivot_cache = {
            "BTCUSDT_future_1W": {
                "PP": 300.0, "S1": 280.0, "R1": 320.0,
                "timeframe": "future_1W",
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
            }
        }
        dc = _make_data_collector(None)

        result = asyncio.get_event_loop().run_until_complete(
            calc.get_future_weekly_pivots("BTCUSDT", dc)
        )
        assert result["PP"] == 300.0
        dc.get_ohlcv.assert_not_called()


# ── Future Monthly Pivots ─────────────────────────────────────────────────────

class TestFutureMonthlyPivots:

    def _month_start_ohlcv(self, n: int = 15) -> pd.DataFrame:
        """OHLCV начиная с 1-го числа текущего месяца."""
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_ts = int(month_start.timestamp() * 1000)
        interval_ms = 24 * 60 * 60 * 1000  # 1d
        times = [start_ts + i * interval_ms for i in range(n)]
        return pd.DataFrame({
            "time":   times,
            "open":   [500.0] * n,
            "high":   [530.0 + i * 5 for i in range(n)],
            "low":    [470.0 - i * 2 for i in range(n)],
            "close":  [510.0] * n,
            "volume": [10000.0] * n,
        })

    def test_monthly_returns_pivots(self):
        """[10] get_future_monthly_pivots → dict с PP/S/R."""
        calc = _calc()
        calc.pivot_cache = {}
        dc = _make_data_collector(self._month_start_ohlcv())

        result = asyncio.get_event_loop().run_until_complete(
            calc.get_future_monthly_pivots("BTCUSDT", dc)
        )
        assert result is not None
        assert "PP" in result
        assert result["timeframe"] == "future_1M"

    def test_monthly_cache_hit(self):
        """[11] TTL-кеш 1M."""
        calc = _calc()
        calc.pivot_cache = {
            "ETHUSDT_future_1M": {
                "PP": 1500.0,
                "timeframe": "future_1M",
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=30),
            }
        }
        dc = _make_data_collector(None)

        result = asyncio.get_event_loop().run_until_complete(
            calc.get_future_monthly_pivots("ETHUSDT", dc, ttl_sec=60)
        )
        assert result["PP"] == 1500.0
        dc.get_ohlcv.assert_not_called()


# ── check_future_classic_confluence ──────────────────────────────────────────

class TestFutureClassicConfluence:

    def test_finds_confluence_pp_pp(self):
        """[12] Future PP ≈ Classic PP (в пределах threshold) → конфлюэнция."""
        future  = {"PP": 100.0, "S1": 95.0, "R1": 105.0}
        classic = {"PP": 100.4, "S1": 94.0, "R1": 106.0}  # PP разница 0.4% < 0.5%
        hits = check_future_classic_confluence(future, classic, threshold_pct=0.5)
        assert len(hits) > 0
        pp_hits = [h for h in hits if h["future_level"] == "PP" and h["classic_level"] == "PP"]
        assert len(pp_hits) == 1
        assert pp_hits[0]["strength_bonus"] == 15

    def test_no_confluence_when_too_far(self):
        """[13] Расстояние > threshold_pct → пусто."""
        future  = {"PP": 100.0, "R1": 110.0}
        classic = {"PP": 102.0, "R1": 115.0}  # оба >1%
        hits = check_future_classic_confluence(future, classic, threshold_pct=0.5)
        assert len(hits) == 0

    def test_multiple_confluences(self):
        """[14] Несколько пар уровней в зоне → все найдены."""
        future  = {"PP": 100.0, "S1": 95.0, "R1": 105.0}
        classic = {"PP": 100.3, "S1": 95.1, "R1": 106.0}  # PP и S1 близко
        hits = check_future_classic_confluence(future, classic, threshold_pct=0.5)
        levels = [(h["future_level"], h["classic_level"]) for h in hits]
        assert ("PP", "PP") in levels
        assert ("S1", "S1") in levels

    def test_sorted_by_distance(self):
        """[15] Результаты отсортированы по dist_pct ASC."""
        future  = {"PP": 100.0, "S1": 95.0}
        classic = {"PP": 100.1, "S1": 95.4}  # PP ближе
        hits = check_future_classic_confluence(future, classic, threshold_pct=0.5)
        assert len(hits) >= 2
        assert hits[0]["distance_pct"] <= hits[1]["distance_pct"]

    def test_returns_empty_on_none_inputs(self):
        """[16] None аргументы → пустой список."""
        assert check_future_classic_confluence(None, {"PP": 100.0}) == []
        assert check_future_classic_confluence({"PP": 100.0}, None) == []
        assert check_future_classic_confluence(None, None) == []

    def test_returns_empty_on_empty_dicts(self):
        """[17] Пустые словари → пустой список."""
        assert check_future_classic_confluence({}, {"PP": 100.0}) == []
        assert check_future_classic_confluence({"PP": 100.0}, {}) == []

    def test_label_format(self):
        """[18] label формата 'FUTURE_PP≈CLASSIC_PP'."""
        future  = {"PP": 100.0}
        classic = {"PP": 100.2}
        hits = check_future_classic_confluence(future, classic, threshold_pct=0.5)
        assert len(hits) == 1
        assert hits[0]["label"] == "FUTURE_PP≈CLASSIC_PP"

    def test_avg_price_is_midpoint(self):
        """[19] price = среднее между future и classic уровнем."""
        future  = {"PP": 100.0}
        classic = {"PP": 100.4}
        hits = check_future_classic_confluence(future, classic, threshold_pct=0.5)
        assert abs(hits[0]["price"] - 100.2) < 0.001

    def test_custom_threshold_pct(self):
        """[20] threshold_pct=0.1 → только очень близкие уровни."""
        future  = {"PP": 100.0, "S1": 95.0}
        classic = {"PP": 100.05, "S1": 95.4}  # только PP проходит порог 0.1%
        hits = check_future_classic_confluence(future, classic, threshold_pct=0.1)
        assert all(h["future_level"] == "PP" or h["classic_level"] == "PP" for h in hits
                   if h["distance_pct"] <= 0.1)

    def test_cross_level_confluence(self):
        """[21] Future R1 ≈ Classic S2 → cross-level конфлюэнция тоже ищется."""
        future  = {"R1": 100.0}
        classic = {"S2": 100.3}  # разные ключи, но близко
        hits = check_future_classic_confluence(future, classic, threshold_pct=0.5)
        assert len(hits) == 1
        assert hits[0]["future_level"] == "R1"
        assert hits[0]["classic_level"] == "S2"


# ── _future_cache_valid ───────────────────────────────────────────────────────

class TestFutureCacheValid:

    def test_valid_cache(self):
        """[22] expires_at в будущем → кеш валиден."""
        calc = _calc()
        calc.pivot_cache = {
            "SYM_future_1D": {
                "PP": 100.0,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=30),
            }
        }
        assert calc._future_cache_valid("SYM_future_1D", ttl_sec=60) is True

    def test_expired_cache(self):
        """[23] expires_at в прошлом → кеш невалиден."""
        calc = _calc()
        calc.pivot_cache = {
            "SYM_future_1D": {
                "PP": 100.0,
                "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
            }
        }
        assert calc._future_cache_valid("SYM_future_1D", ttl_sec=60) is False

    def test_missing_key(self):
        """[24] Ключа нет в кеше → False."""
        calc = _calc()
        calc.pivot_cache = {}
        assert calc._future_cache_valid("NOT_EXISTS", ttl_sec=60) is False

    def test_missing_expires_at(self):
        """[25] Нет поля expires_at → False."""
        calc = _calc()
        calc.pivot_cache = {"SYM_future_1D": {"PP": 100.0}}
        assert calc._future_cache_valid("SYM_future_1D") is False
