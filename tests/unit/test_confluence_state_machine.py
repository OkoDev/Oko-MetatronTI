"""
Тесты для ConfluenceStateMachine (ARCH-03).
"""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from core.confluence_state_machine import (
    ConfluenceStateMachine,
    ConfluenceState,
    SymbolDirectionState,
    STATE_TIMEOUT_HOURS,
)


# ── Фабрики фиктивных данных ──────────────────────────────────────────────────

def _make_df(n: int = 100, close: float = 100.0, wt1: float = 0.0, wt2: float = 0.0,
             trend: int = 1) -> pd.DataFrame:
    """Возвращает минимальный OHLCV DataFrame с индикаторами."""
    times = list(range(n))
    df = pd.DataFrame({
        "time":     times,
        "open":     [close] * n,
        "high":     [close * 1.01] * n,
        "low":      [close * 0.99] * n,
        "close":    [close] * n,
        "volume":   [1000.0] * n,
        "wt1":      [wt1] * n,
        "wt2":      [wt2] * n,
        "trend":    [float(trend)] * n,
        "trendup":  [close * 0.98] * n,
        "trenddown":[close * 1.02] * n,
    })
    return df


def _inject_tsl_cross_up(df: pd.DataFrame, at: int) -> pd.DataFrame:
    """Вставляет TSL кросс UP в позицию at (trend: -1 → 1 с close > trenddown)."""
    df = df.copy()
    df.loc[at - 1, "trend"] = -1.0
    df.loc[at - 1, "trenddown"] = df.loc[at, "close"] * 0.99  # prev trenddown ниже close
    df.loc[at, "trend"] = 1.0
    return df


def _inject_tsl_cross_down(df: pd.DataFrame, at: int) -> pd.DataFrame:
    """Вставляет TSL кросс DOWN в позицию at (trend: 1 → -1 с close < trendup)."""
    df = df.copy()
    df.loc[at - 1, "trend"] = 1.0
    df.loc[at - 1, "trendup"] = df.loc[at, "close"] * 1.01  # prev trendup выше close
    df.loc[at, "trend"] = -1.0
    return df


def _inject_wt_cross_up_os(df: pd.DataFrame, at: int, wt_os: float = -60.0) -> pd.DataFrame:
    """Вставляет WT кросс UP из OS зоны."""
    df = df.copy()
    df.loc[at - 1, "wt1"] = wt_os - 5   # был в OS
    df.loc[at - 1, "wt2"] = wt_os - 3
    df.loc[at, "wt1"] = wt_os - 2       # кросс вверх: wt1 > wt2
    df.loc[at, "wt2"] = wt_os - 5
    return df


def _inject_bullish_divergence(df: pd.DataFrame) -> pd.DataFrame:
    """Вставляет бычью дивергенцию WT в окне: price LL, wt HL."""
    df = df.copy()
    n = len(df)
    # Первый трог (trough 1): бар n//3
    i1, i2 = n // 3, n * 2 // 3
    df.loc[i1 - 1, "wt1"] = -50
    df.loc[i1,     "wt1"] = -70   # локальный минимум wt1
    df.loc[i1 + 1, "wt1"] = -55
    df.loc[i1,     "low"]  = df.loc[i1, "close"] * 0.95

    # Второй трог (trough 2): бар 2*n//3 — price ниже, wt выше (дивергенция)
    df.loc[i2 - 1, "wt1"] = -55
    df.loc[i2,     "wt1"] = -60   # wt выше i1 (HL) → дивергенция
    df.loc[i2 + 1, "wt1"] = -40
    df.loc[i2,     "low"]  = df.loc[i1, "low"] * 0.99  # price ниже i1 (LL)
    return df


# ── Тесты SymbolDirectionState ────────────────────────────────────────────────

class TestSymbolDirectionState:
    def test_initial_state_is_idle(self):
        st = SymbolDirectionState(symbol="BTC/USDT", direction="LONG")
        assert st.state == ConfluenceState.IDLE

    def test_not_timed_out_in_idle(self):
        st = SymbolDirectionState(symbol="BTC/USDT", direction="LONG")
        assert not st.is_timed_out()

    def test_timed_out_after_48h(self):
        st = SymbolDirectionState(symbol="BTC/USDT", direction="LONG")
        st.state = ConfluenceState.WT_ZONE
        st.entered_at = datetime.now(tz=timezone.utc) - timedelta(hours=STATE_TIMEOUT_HOURS + 1)
        assert st.is_timed_out()

    def test_not_timed_out_within_48h(self):
        st = SymbolDirectionState(symbol="BTC/USDT", direction="LONG")
        st.state = ConfluenceState.WT_ZONE
        st.entered_at = datetime.now(tz=timezone.utc) - timedelta(hours=STATE_TIMEOUT_HOURS - 1)
        assert not st.is_timed_out()

    def test_reset_clears_state(self):
        st = SymbolDirectionState(symbol="BTC/USDT", direction="LONG")
        st.state = ConfluenceState.NEAR_PIVOT
        st.score = 55
        st.factors = ["WT_OS", "TSL_CROSS_UP"]
        st.entered_at = datetime.now(tz=timezone.utc)
        st.reset()
        assert st.state == ConfluenceState.IDLE
        assert st.score == 0
        assert st.factors == []
        assert st.entered_at is None

    def test_add_factor_deduplication(self):
        st = SymbolDirectionState(symbol="BTC/USDT", direction="LONG")
        st.add_factor("WT_OS", 20)
        st.add_factor("WT_OS", 20)  # дубль — не должен добавить очки снова
        assert st.score == 20
        assert st.factors.count("WT_OS") == 1


# ── Тесты статических методов ─────────────────────────────────────────────────

class TestStaticDetectors:
    def test_detect_tsl_cross_up(self):
        n = 20
        trend = np.ones(n)
        trenddown = np.full(n, np.nan)
        trendup = np.full(n, np.nan)
        close = np.full(n, 100.0)

        trend[n - 3] = -1.0
        trenddown[n - 3] = 95.0   # prev trenddown
        trend[n - 2] = 1.0
        close[n - 2] = 96.0       # close > trenddown → подтверждено

        result = ConfluenceStateMachine._detect_tsl_cross(trend, trenddown, trendup, close, fresh_bars=10)
        assert result == "UP"

    def test_detect_tsl_cross_down(self):
        n = 20
        trend = np.ones(n) * -1
        trenddown = np.full(n, np.nan)
        trendup = np.full(n, np.nan)
        close = np.full(n, 100.0)

        trend[n - 3] = 1.0
        trendup[n - 3] = 105.0    # prev trendup
        trend[n - 2] = -1.0
        close[n - 2] = 104.0      # close < trendup → подтверждено

        result = ConfluenceStateMachine._detect_tsl_cross(trend, trenddown, trendup, close, fresh_bars=10)
        assert result == "DOWN"

    def test_detect_tsl_cross_none_when_no_cross(self):
        n = 20
        trend = np.ones(n)
        trenddown = np.full(n, np.nan)
        trendup = np.full(n, np.nan)
        close = np.full(n, 100.0)
        result = ConfluenceStateMachine._detect_tsl_cross(trend, trenddown, trendup, close, fresh_bars=10)
        assert result is None

    def test_detect_wt_cross_up_in_os(self):
        n = 20
        wt1 = np.full(n, -50.0)
        wt2 = np.full(n, -50.0)
        # Кросс UP в OS (wt1 был < -60)
        wt1[n - 2] = -65.0
        wt2[n - 2] = -62.0
        wt1[n - 1] = -58.0  # wt1 > wt2 после кросса
        wt2[n - 1] = -65.0
        result = ConfluenceStateMachine._detect_wt_cross(wt1, wt2, -60.0, 60.0, fresh_bars=5)
        assert result == "UP"

    def test_detect_wt_cross_down_in_ob(self):
        n = 20
        wt1 = np.full(n, 50.0)
        wt2 = np.full(n, 50.0)
        # Кросс DOWN в OB
        wt1[n - 2] = 65.0
        wt2[n - 2] = 62.0
        wt1[n - 1] = 58.0   # wt1 < wt2 после кросса
        wt2[n - 1] = 65.0
        result = ConfluenceStateMachine._detect_wt_cross(wt1, wt2, -60.0, 60.0, fresh_bars=5)
        assert result == "DOWN"

    def test_detect_wt_cross_not_in_zone(self):
        """Кросс UP но НЕ в OS зоне — не должен засчитываться."""
        n = 20
        wt1 = np.full(n, 0.0)
        wt2 = np.full(n, 0.0)
        wt1[n - 2] = -5.0   # не в OS (> -60)
        wt2[n - 2] = -3.0
        wt1[n - 1] = -2.0
        wt2[n - 1] = -5.0
        result = ConfluenceStateMachine._detect_wt_cross(wt1, wt2, -60.0, 60.0, fresh_bars=5)
        assert result is None


# ── Тесты State Machine ───────────────────────────────────────────────────────

class TestConfluenceStateMachine:
    def setup_method(self):
        self.sm = ConfluenceStateMachine(db_path=None)
        # update() пересчитывает индикаторы через calculate_wt/calculate_trend,
        # что перезаписывает тестовые значения. Мокируем — возвращаем df как есть.
        self._patch_wt = patch(
            "core.confluence_state_machine.calculate_wt",
            side_effect=lambda df, **kw: df,
        )
        self._patch_trend = patch(
            "core.confluence_state_machine.calculate_trend",
            side_effect=lambda df, **kw: df,
        )
        self._patch_wt.start()
        self._patch_trend.start()

    def teardown_method(self):
        self._patch_wt.stop()
        self._patch_trend.stop()

    def test_initial_state_idle(self):
        assert self.sm.get_state("BTC/USDT", "LONG") == ConfluenceState.IDLE

    def test_idle_to_wt_zone_on_os(self):
        """При wt1 < -60 переходим из IDLE в WT_ZONE."""
        df = _make_df(60, wt1=-65.0, wt2=-62.0, trend=1)
        self.sm.update("BTC/USDT", df, None, {})
        assert self.sm.get_state("BTC/USDT", "LONG") == ConfluenceState.WT_ZONE

    def test_idle_stays_idle_when_wt_neutral(self):
        """При wt1 в нейтральной зоне остаёмся в IDLE."""
        df = _make_df(60, wt1=0.0, wt2=0.0, trend=1)
        self.sm.update("BTC/USDT", df, None, {})
        assert self.sm.get_state("BTC/USDT", "LONG") == ConfluenceState.IDLE

    def test_timeout_resets_to_idle(self):
        """Состояние сбрасывается в IDLE при таймауте 48h."""
        st = self.sm._get_state("BTC/USDT", "LONG")
        st.state = ConfluenceState.TSL_CROSS
        st.entered_at = datetime.now(tz=timezone.utc) - timedelta(hours=STATE_TIMEOUT_HOURS + 1)

        df = _make_df(60, wt1=0.0, trend=1)
        self.sm.update("BTC/USDT", df, None, {})
        assert self.sm.get_state("BTC/USDT", "LONG") == ConfluenceState.IDLE

    def test_wt_zone_resets_on_opposite_zone_entry(self):
        """Если в WT_ZONE (LONG) wt1 уходит в OB — сброс в IDLE."""
        st = self.sm._get_state("BTC/USDT", "LONG")
        st.state = ConfluenceState.WT_ZONE
        st.entered_at = datetime.now(tz=timezone.utc)

        df = _make_df(60, wt1=65.0, wt2=62.0, trend=1)  # wt1 в OB
        self.sm.update("BTC/USDT", df, None, {})
        assert self.sm.get_state("BTC/USDT", "LONG") == ConfluenceState.IDLE

    def test_wt_zone_to_tsl_cross(self):
        """WT_ZONE → TSL_CROSS при TSL кроссе UP."""
        st = self.sm._get_state("BTC/USDT", "LONG")
        st.state = ConfluenceState.WT_ZONE
        st.entered_at = datetime.now(tz=timezone.utc)
        st.add_factor("WT_OS", 20, {"wt_min": -65.0})

        df = _make_df(60, wt1=-65.0, wt2=-70.0, trend=1)
        # Вставляем TSL кросс UP в последние 10 баров
        df = _inject_tsl_cross_up(df, at=55)
        self.sm.update("BTC/USDT", df, None, {})
        assert self.sm.get_state("BTC/USDT", "LONG") == ConfluenceState.TSL_CROSS

    def test_get_all_states(self):
        """get_all_states возвращает словарь со всеми символами."""
        self.sm._get_state("BTC/USDT", "LONG").state = ConfluenceState.WT_ZONE
        self.sm._get_state("ETH/USDT", "SHORT").state = ConfluenceState.NEAR_PIVOT
        all_st = self.sm.get_all_states()
        assert all_st["BTC/USDT"]["LONG"] == "WT_ZONE"
        assert all_st["ETH/USDT"]["SHORT"] == "NEAR_PIVOT"

    def test_short_direction_idle_to_wt_zone(self):
        """SHORT: при wt1 > +60 переходим в WT_ZONE."""
        df = _make_df(60, wt1=65.0, wt2=62.0, trend=-1)
        self.sm.update("ETH/USDT", df, None, {})
        assert self.sm.get_state("ETH/USDT", "SHORT") == ConfluenceState.WT_ZONE

    def test_idempotency_same_bar(self):
        """Повторный вызов с тем же bar_time не меняет состояние."""
        df = _make_df(60, wt1=-65.0, wt2=-70.0, trend=1)
        df["time"] = list(range(60))  # явный bar_time
        self.sm.update("BTC/USDT", df, None, {})
        state_after_first = self.sm.get_state("BTC/USDT", "LONG")
        # Второй вызов с тем же df (тот же last bar_time)
        self.sm.update("BTC/USDT", df, None, {})
        assert self.sm.get_state("BTC/USDT", "LONG") == state_after_first

    def test_no_signal_below_min_strength(self):
        """Если score < min_strength после всех шагов — сигнал не выдаётся."""
        # Устанавливаем состояние DIVERGENCE с низким score (< 60)
        st = self.sm._get_state("BTC/USDT", "LONG")
        st.state = ConfluenceState.DIVERGENCE
        st.entered_at = datetime.now(tz=timezone.utc)
        st.score = 20  # намеренно низкий
        st.factors = ["WT_OS", "WT_DIVERGENCE"]

        df = _make_df(60, wt1=-65.0, wt2=-70.0, trend=1)
        df = _inject_wt_cross_up_os(df, at=58)

        # mock _check_near_support чтобы не мешал
        results = self.sm.update("BTC/USDT", df, None, {})
        # score + WT_CROSS_UP (15) = 35 < 60 → нет сигнала
        assert results == []
        assert self.sm.get_state("BTC/USDT", "LONG") == ConfluenceState.IDLE  # reset после попытки

    def test_signal_emitted_resets_state(self):
        """После выдачи сигнала состояние сбрасывается в IDLE."""
        st = self.sm._get_state("SIG/USDT", "LONG")
        st.state = ConfluenceState.DIVERGENCE
        st.entered_at = datetime.now(tz=timezone.utc)
        # Высокий score чтобы пройти порог 60
        st.score = 65
        st.factors = ["WT_OS", "TSL_CROSS_UP", "NEAR_SUPPORT", "WT_DIVERGENCE"]
        st.data = {"wt_min": -65.0, "pivot_hit": "1D_S1=100.0"}

        df = _make_df(60, wt1=-65.0, wt2=-70.0, close=105.0, trend=1)
        df = _inject_wt_cross_up_os(df, at=58)

        pivot_cache = {"SIG/USDT_1D": {"PP": 100.0, "S1": 99.0, "R1": 101.0}}

        with patch("core.confluence_state_machine._check_near_support", return_value=(False, "")), \
             patch("core.confluence_state_machine._check_bullish_divergence_wt", return_value=(False, "")):
            results = self.sm.update("SIG/USDT", df, None, pivot_cache)

        assert len(results) == 1
        assert results[0].signal_type.value == "confluence"
        assert self.sm.get_state("SIG/USDT", "LONG") == ConfluenceState.IDLE

    def test_load_from_db_without_db(self):
        """load_from_db без БД возвращает 0."""
        sm = ConfluenceStateMachine(db_path=None)
        assert sm.load_from_db() == 0


# ── Тесты SQLite persistence ──────────────────────────────────────────────────

class TestSQLitePersistence:
    def test_persist_and_load(self, tmp_path):
        db = str(tmp_path / "test_csm.db")
        sm1 = ConfluenceStateMachine(db_path=db)
        st = sm1._get_state("BTC/USDT", "LONG")
        st.state = ConfluenceState.TSL_CROSS
        st.entered_at = datetime.now(tz=timezone.utc)
        st.score = 40
        st.factors = ["WT_OS", "TSL_CROSS_UP"]
        st.data = {"wt_min": -65.0}
        sm1._persist(st)

        sm2 = ConfluenceStateMachine(db_path=db)
        count = sm2.load_from_db()
        assert count == 1
        loaded = sm2._get_state("BTC/USDT", "LONG")
        assert loaded.state == ConfluenceState.TSL_CROSS
        assert loaded.score == 40
        assert "WT_OS" in loaded.factors

    def test_timed_out_state_reset_on_load(self, tmp_path):
        """Состояние с истёкшим таймаутом сбрасывается при загрузке."""
        db = str(tmp_path / "test_csm2.db")
        sm1 = ConfluenceStateMachine(db_path=db)
        st = sm1._get_state("ETH/USDT", "SHORT")
        st.state = ConfluenceState.NEAR_PIVOT
        st.entered_at = datetime.now(tz=timezone.utc) - timedelta(hours=STATE_TIMEOUT_HOURS + 1)
        sm1._persist(st)

        sm2 = ConfluenceStateMachine(db_path=db)
        sm2.load_from_db()
        loaded = sm2._get_state("ETH/USDT", "SHORT")
        assert loaded.state == ConfluenceState.IDLE
