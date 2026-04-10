"""
Unit tests for detect_liquidity_sweep (DEV-82).
"""
import numpy as np
import pandas as pd

from core.signals.liquidity_sweep_detector import detect_liquidity_sweep
from core.signals.signal_models import SignalDirection, SignalType


def _make_base_df(n: int = 140) -> pd.DataFrame:
    x = np.linspace(0, 8 * np.pi, n)
    close = 1.0 + 0.008 * np.sin(x)
    high = close + 0.004
    low = close - 0.004
    open_ = close.copy()
    volume = np.full(n, 5000.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def _with_wt(df: pd.DataFrame, wt1: float, wt2: float) -> pd.DataFrame:
    out = df.copy()
    out["wt1"] = wt1
    out["wt2"] = wt2
    return out


def _make_cluster_long_df(n: int = 140) -> pd.DataFrame:
    df = _make_base_df(n=n)

    for idx in (40, 90):
        df.loc[idx - 2 : idx + 2, "low"] = 0.972
        df.loc[idx - 2 : idx + 2, "high"] = 0.988
        df.loc[idx - 2 : idx + 2, "open"] = 0.982
        df.loc[idx - 2 : idx + 2, "close"] = 0.984
        df.loc[idx, "low"] = 0.94
        df.loc[idx, "open"] = 0.982
        df.loc[idx, "close"] = 0.983
        df.loc[idx, "high"] = 0.989

    df.loc[n - 1, "low"] = 0.936
    df.loc[n - 1, "open"] = 0.947
    df.loc[n - 1, "close"] = 0.946
    df.loc[n - 1, "high"] = 0.95
    return _with_wt(df, -55.0, -50.0)


def _make_cluster_short_df(n: int = 140) -> pd.DataFrame:
    df = _make_base_df(n=n)

    for idx in (40, 90):
        df.loc[idx - 2 : idx + 2, "low"] = 1.012
        df.loc[idx - 2 : idx + 2, "high"] = 1.028
        df.loc[idx - 2 : idx + 2, "open"] = 1.018
        df.loc[idx - 2 : idx + 2, "close"] = 1.017
        df.loc[idx, "low"] = 1.011
        df.loc[idx, "open"] = 1.018
        df.loc[idx, "close"] = 1.017
        df.loc[idx, "high"] = 1.06

    df.loc[n - 1, "low"] = 1.05
    df.loc[n - 1, "open"] = 1.055
    df.loc[n - 1, "close"] = 1.054
    df.loc[n - 1, "high"] = 1.065
    return _with_wt(df, 55.0, 50.0)


def _make_local_single_swing_df(n: int = 140) -> pd.DataFrame:
    df = _make_base_df(n=n)
    idx = 90
    df.loc[idx - 2 : idx + 2, "low"] = 0.972
    df.loc[idx - 2 : idx + 2, "high"] = 0.988
    df.loc[idx - 2 : idx + 2, "open"] = 0.982
    df.loc[idx - 2 : idx + 2, "close"] = 0.984
    df.loc[idx, "low"] = 0.94
    df.loc[idx, "open"] = 0.982
    df.loc[idx, "close"] = 0.983
    df.loc[idx, "high"] = 0.989

    df.loc[n - 1, "low"] = 0.936
    df.loc[n - 1, "open"] = 0.947
    df.loc[n - 1, "close"] = 0.946
    df.loc[n - 1, "high"] = 0.95
    return _with_wt(df, -55.0, -50.0)


def _make_pivot_only_long_df(n: int = 140) -> pd.DataFrame:
    df = _make_base_df(n=n)
    df.loc[n - 1, "low"] = 0.944
    df.loc[n - 1, "open"] = 0.949
    df.loc[n - 1, "close"] = 0.951
    df.loc[n - 1, "high"] = 0.956
    return _with_wt(df, -55.0, -50.0)


class TestLiquiditySweepFilters:
    def test_none_if_df_too_short(self):
        df = _make_base_df(n=50)
        df = _with_wt(df, -55.0, -50.0)
        assert detect_liquidity_sweep("TEST/USDT", df) is None

    def test_none_if_no_sweep_pattern(self):
        df = _with_wt(_make_base_df(), -55.0, -50.0)
        assert detect_liquidity_sweep("TEST/USDT", df) is None

    def test_none_if_wt_not_in_zone_for_long(self):
        df = _make_cluster_long_df()
        df["wt1"] = -10.0
        assert detect_liquidity_sweep("TEST/USDT", df) is None

    def test_none_for_local_single_swing_noise(self):
        df = _make_local_single_swing_df()
        assert detect_liquidity_sweep("TEST/USDT", df) is None


class TestLiquiditySweepSignal:
    def test_long_signal_on_cluster_sweep(self):
        df = _make_cluster_long_df()
        result = detect_liquidity_sweep("TEST/USDT", df)
        assert result is not None
        assert result.signal_type == SignalType.LIQUIDITY_SWEEP
        assert result.direction == SignalDirection.LONG
        assert 55 <= result.strength <= 95

    def test_short_signal_on_cluster_sweep(self):
        df = _make_cluster_short_df()
        result = detect_liquidity_sweep("TEST/USDT", df)
        assert result is not None
        assert result.direction == SignalDirection.SHORT

    def test_pivot_fallback_still_works(self):
        df = _make_pivot_only_long_df()
        pivot_cache = {"TEST/USDT": {"W:S1": 0.95}}
        result = detect_liquidity_sweep("TEST/USDT", df, pivot_cache=pivot_cache)
        assert result is not None
        assert result.direction == SignalDirection.LONG
        assert result.data.get("pivot_bonus") is True

    def test_pivot_bonus_applied_for_cluster_confluence(self):
        df = _make_cluster_long_df()
        pivot_cache = {"TEST/USDT": {"W:S1": 0.94}}

        result_no_bonus = detect_liquidity_sweep("TEST/USDT", df, pivot_cache={})
        result_bonus = detect_liquidity_sweep("TEST/USDT", df, pivot_cache=pivot_cache)

        assert result_no_bonus is not None
        assert result_bonus is not None
        assert result_bonus.data.get("pivot_bonus") is True
        assert result_bonus.strength >= result_no_bonus.strength

    def test_data_fields_present(self):
        df = _make_cluster_long_df()
        result = detect_liquidity_sweep("LONG/USDT", df)
        assert result is not None
        assert "sweep_level" in result.data
        assert "sweep_depth_pct" in result.data
        assert "wt1" in result.data

    def test_symbol_and_timeframe(self):
        df = _make_cluster_long_df()
        result = detect_liquidity_sweep("BTC/USDT", df)
        assert result is not None
        assert result.symbol == "BTC/USDT"
        assert result.timeframe == "1h"
