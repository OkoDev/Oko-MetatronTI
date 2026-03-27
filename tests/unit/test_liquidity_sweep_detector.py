"""
Smoke-тесты для detect_liquidity_sweep (DEV-82).

Проверяют:
  - пропуск при нехватке баров
  - пропуск если нет sweep паттерна
  - пропуск если WT не в OS/OB зоне
  - генерацию LONG/SHORT сигнала при правильных условиях
  - pivot bonus при совпадении с Weekly уровнем
"""
import numpy as np
import pandas as pd
import pytest

from core.signals.liquidity_sweep_detector import detect_liquidity_sweep
from core.signals.signal_models import SignalType, SignalDirection


def _make_sinusoid_df(n: int = 50, amplitude: float = 0.02) -> pd.DataFrame:
    """
    Создаёт синусоидальный OHLCV DataFrame — содержит реальные swing highs/lows,
    которые корректно определяются detect_swing_points(period=5).
    """
    x = np.linspace(0, 4 * np.pi, n)
    prices = 1.0 + amplitude * np.sin(x)
    lows   = prices - 0.001
    highs  = prices + 0.001
    return pd.DataFrame({
        "open":   prices * 0.999,
        "high":   highs,
        "low":    lows,
        "close":  prices,
        "volume": np.ones(n) * 5000.0,
    })


def _make_sweep_long_df(n: int = 50) -> pd.DataFrame:
    """
    LONG sweep: синусоидальный df, последний бар пробивает ближайший swing_low
    (≈ 0.979 при amplitude=0.02) снизу но закрывается выше.
    WT1 в OS зоне (<-40).
    """
    df = _make_sinusoid_df(n=n)
    # Узнаём swing_low уровень из detect_swing_points
    from core.smc.swing_points import detect_swing_points
    sa = detect_swing_points(df.iloc[:-1], period=5)
    if not sa.lows:
        # fallback — форсируем уровень
        swing_lvl = 0.979
    else:
        swing_lvl = sorted(sa.lows, key=lambda x: x.index, reverse=True)[0].value

    # Последний бар: low ниже swing_lvl, close выше
    df.loc[n - 1, "low"]   = swing_lvl * 0.99   # пробой
    df.loc[n - 1, "close"] = swing_lvl * 1.005   # recovery
    df.loc[n - 1, "high"]  = swing_lvl * 1.01

    # WT в OS зоне
    df["wt1"] = -50.0
    df["wt2"] = -45.0
    return df


def _make_sweep_short_df(n: int = 50) -> pd.DataFrame:
    """
    SHORT sweep: последний бар пробивает ближайший swing_high сверху
    но закрывается ниже. WT1 в OB зоне (>+40).
    """
    df = _make_sinusoid_df(n=n)
    from core.smc.swing_points import detect_swing_points
    sa = detect_swing_points(df.iloc[:-1], period=5)
    if not sa.highs:
        swing_lvl = 1.021
    else:
        swing_lvl = sorted(sa.highs, key=lambda x: x.index, reverse=True)[0].value

    # Последний бар: high выше swing_lvl, close ниже
    df.loc[n - 1, "high"]  = swing_lvl * 1.01   # пробой
    df.loc[n - 1, "close"] = swing_lvl * 0.995   # rejection
    df.loc[n - 1, "low"]   = swing_lvl * 0.99

    # WT в OB зоне
    df["wt1"] = 50.0
    df["wt2"] = 45.0
    return df


class TestLiquiditySweepFilters:
    def test_none_if_df_too_short(self):
        """Менее 30 баров → None."""
        df = _make_sinusoid_df(n=20)
        result = detect_liquidity_sweep("TEST/USDT", df)
        assert result is None

    def test_none_if_no_sweep_pattern(self):
        """Нет sweep паттерна (нет пробоя+возврата) → None."""
        df = _make_sinusoid_df(n=50)
        # WT в OS но без sweep на последнем баре
        df["wt1"] = -50.0
        df["wt2"] = -45.0
        result = detect_liquidity_sweep("TEST/USDT", df)
        assert result is None

    def test_none_if_wt_not_in_zone_for_long(self):
        """Есть sweep LONG но WT не в OS зоне (wt1 > -40) → None."""
        df = _make_sweep_long_df(n=50)
        df["wt1"] = -10.0  # не в OS
        result = detect_liquidity_sweep("TEST/USDT", df)
        assert result is None


class TestLiquiditySweepSignal:
    def test_long_signal_on_sweep_long(self):
        """LONG sweep + WT в OS → LONG сигнал."""
        df = _make_sweep_long_df(n=50)
        result = detect_liquidity_sweep("TEST/USDT", df)
        assert result is not None
        assert result.signal_type == SignalType.LIQUIDITY_SWEEP
        assert result.direction == SignalDirection.LONG
        assert result.strength >= 55
        assert result.strength <= 95

    def test_short_signal_on_sweep_short(self):
        """SHORT sweep + WT в OB → SHORT сигнал."""
        df = _make_sweep_short_df(n=50)
        result = detect_liquidity_sweep("TEST/USDT", df)
        assert result is not None
        assert result.direction == SignalDirection.SHORT

    def test_pivot_bonus_applied(self):
        """Совпадение sweep уровня с W:S1 → pivot_bonus=True и strength выше."""
        df = _make_sweep_long_df(n=50)

        # Узнаём реальный swing_low уровень чтобы настроить pivot_cache
        from core.smc.swing_points import detect_swing_points
        sa = detect_swing_points(df.iloc[:-1], period=5)
        swing_lvl = sorted(sa.lows, key=lambda x: x.index, reverse=True)[0].value if sa.lows else 0.979

        pivot_cache = {"TEST/USDT": {"W:S1": swing_lvl}}

        result_no_bonus = detect_liquidity_sweep("TEST/USDT", df, pivot_cache={})
        result_bonus    = detect_liquidity_sweep("TEST/USDT", df, pivot_cache=pivot_cache)

        assert result_no_bonus is not None and result_bonus is not None
        assert result_bonus.data.get("pivot_bonus") is True
        assert result_bonus.strength >= result_no_bonus.strength

    def test_data_fields_present(self):
        """Сигнал содержит обязательные поля в data."""
        df = _make_sweep_long_df(n=50)
        result = detect_liquidity_sweep("LONG/USDT", df)
        assert result is not None
        assert "sweep_level" in result.data
        assert "sweep_depth_pct" in result.data
        assert "wt1" in result.data

    def test_symbol_and_timeframe(self):
        """Сигнал содержит правильный символ и timeframe='15m'."""
        df = _make_sweep_long_df(n=50)
        result = detect_liquidity_sweep("BTC/USDT", df)
        assert result is not None
        assert result.symbol == "BTC/USDT"
        assert result.timeframe == "15m"
