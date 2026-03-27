"""
Smoke-тесты для detect_funding_extreme (DEV-81).

Проверяют:
  - пропуск при funding ниже порога
  - пропуск при нехватке баров
  - генерацию сигнала при правильных условиях
  - правильное направление (LONG при neg funding, SHORT при pos)
  - shadow mode флаг в data
"""
import numpy as np
import pandas as pd
import pytest

from core.signals.funding_detector import detect_funding_extreme
from core.signals.signal_models import SignalType, SignalDirection


def _make_df(n: int = 20, wt1_vals=None, wt2_vals=None) -> pd.DataFrame:
    """Создаёт синтетический OHLCV DataFrame с заданными WT значениями."""
    prices = np.linspace(1.0, 1.05, n)
    df = pd.DataFrame({
        "open":   prices * 0.999,
        "high":   prices * 1.002,
        "low":    prices * 0.998,
        "close":  prices,
        "volume": np.ones(n) * 1000.0,
    })
    if wt1_vals is not None:
        df["wt1"] = wt1_vals
    if wt2_vals is not None:
        df["wt2"] = wt2_vals
    return df


def _make_cross_up_os_df(n: int = 10) -> pd.DataFrame:
    """
    WT cross вверх в OS зоне:
      bar[-2]: wt1=-50 < wt2=-45  (wt1 below wt2, в OS)
      bar[-1]: wt1=-38 > wt2=-42  (wt1 above wt2, cross up, ещё в OS диапазоне)
    """
    wt1 = [-55.0] * (n - 2) + [-50.0, -38.0]
    wt2 = [-45.0] * (n - 2) + [-45.0, -42.0]
    return _make_df(n, wt1_vals=wt1, wt2_vals=wt2)


def _make_cross_down_ob_df(n: int = 10) -> pd.DataFrame:
    """
    WT cross вниз в OB зоне:
      bar[-2]: wt1=50 > wt2=45   (wt1 above wt2, в OB)
      bar[-1]: wt1=38 < wt2=42   (wt1 below wt2, cross down)
    """
    wt1 = [55.0] * (n - 2) + [50.0, 38.0]
    wt2 = [45.0] * (n - 2) + [45.0, 42.0]
    return _make_df(n, wt1_vals=wt1, wt2_vals=wt2)


class TestFundingDetectorFilters:
    def test_none_if_funding_below_threshold(self):
        """Funding ниже порога → None."""
        df = _make_cross_up_os_df()
        result = detect_funding_extreme("TEST/USDT", df, funding_rate=0.0001)
        assert result is None

    def test_none_if_funding_is_none(self):
        """Funding=None → None."""
        df = _make_cross_up_os_df()
        result = detect_funding_extreme("TEST/USDT", df, funding_rate=None)
        assert result is None

    def test_none_if_df_too_short(self):
        """Менее 5 баров → None."""
        df = _make_df(n=3)
        result = detect_funding_extreme("TEST/USDT", df, funding_rate=-0.001)
        assert result is None

    def test_none_if_no_wt_cross(self):
        """Нет WT cross → None."""
        wt1 = [-50.0] * 10  # нет кросса
        wt2 = [-45.0] * 10
        df = _make_df(10, wt1_vals=wt1, wt2_vals=wt2)
        result = detect_funding_extreme("TEST/USDT", df, funding_rate=-0.001)
        assert result is None


class TestFundingDetectorSignal:
    def test_long_signal_on_negative_funding_with_cross(self):
        """Neg funding + WT cross up в OS → LONG сигнал."""
        df = _make_cross_up_os_df(n=10)
        result = detect_funding_extreme("TEST/USDT", df, funding_rate=-0.001)
        assert result is not None
        assert result.signal_type == SignalType.FUNDING_EXTREME
        assert result.direction == SignalDirection.LONG
        assert result.strength >= 50
        assert result.strength <= 100

    def test_short_signal_on_positive_funding_with_cross(self):
        """Pos funding + WT cross down в OB → SHORT сигнал."""
        df = _make_cross_down_ob_df(n=10)
        result = detect_funding_extreme("TEST/USDT", df, funding_rate=+0.001)
        assert result is not None
        assert result.direction == SignalDirection.SHORT

    def test_shadow_mode_flag_present(self):
        """Сигнал содержит data['shadow']=True (shadow mode)."""
        df = _make_cross_up_os_df(n=10)
        result = detect_funding_extreme("TEST/USDT", df, funding_rate=-0.001)
        assert result is not None
        assert result.data.get("shadow") is True

    def test_strength_increases_with_extreme_funding(self):
        """Чем экстремальнее funding → тем выше strength."""
        df = _make_cross_up_os_df(n=10)
        r_moderate = detect_funding_extreme("TEST/USDT", df, funding_rate=-0.001)
        r_extreme  = detect_funding_extreme("TEST/USDT", df, funding_rate=-0.005)
        assert r_moderate is not None and r_extreme is not None
        assert r_extreme.strength >= r_moderate.strength

    def test_symbol_and_timeframe(self):
        """Сигнал содержит правильный символ и timeframe='8h'."""
        df = _make_cross_up_os_df(n=10)
        result = detect_funding_extreme("BTC/USDT", df, funding_rate=-0.001)
        assert result is not None
        assert result.symbol == "BTC/USDT"
        assert result.timeframe == "8h"
