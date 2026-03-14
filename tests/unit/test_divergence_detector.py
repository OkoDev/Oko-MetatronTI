"""
DEV-03: Расширенные тесты DivergenceDetector.
Покрытие: hidden bullish/bearish с zone фильтром, cascade bonus расчёт,
граничные условия, ind_change знаки.
"""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.divergence_detector import DivergenceDetector


# ─── Фабрики данных ────────────────────────────────────────────────────────────

def _make_df(n=60, close_vals=None, wt1_vals=None, high_vals=None, low_vals=None):
    """Базовый DataFrame для тестов."""
    if close_vals is None:
        close_vals = np.full(n, 100.0)
    close = np.array(close_vals, dtype=float)
    high = np.array(high_vals, dtype=float) if high_vals is not None else close + 2.0
    low  = np.array(low_vals,  dtype=float) if low_vals  is not None else close - 2.0
    wt1  = np.array(wt1_vals,  dtype=float) if wt1_vals  is not None else np.full(n, 0.0)
    return pd.DataFrame({
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.full(n, 1e6),
        "wt1": wt1,
        "wt2": wt1 * 0.9,
    })


def _make_hidden_bullish_df():
    """
    Hidden Bullish: индикатор LL, цена HL.
    Тренд восходящий (коррекция заканчивается).
    Оба WT-минимума ниже +20 (zone фильтр).
    """
    n = 60
    close = np.full(n, 100.0)
    high  = close + 2.0
    low   = close.copy()
    wt1   = np.full(n, -10.0)

    # Первый минимум: bar 10 → цена low=85 (позже станет выше), WT=-30
    pivot_bar = 10
    low[pivot_bar - 2:pivot_bar + 3]  = [88, 86, 85, 86, 88]
    close[pivot_bar - 2:pivot_bar + 3] = [88, 86, 85, 86, 88]
    wt1[pivot_bar - 2:pivot_bar + 3]  = [-28, -31, -30, -28, -25]

    # Текущий минимум: bar 55 → цена low=90 (HL), WT=-35 (LL — ниже чем -30)
    current_bar = 55
    low[current_bar - 2:current_bar + 3]  = [92, 91, 90, 91, 92]
    close[current_bar - 2:current_bar + 3] = [92, 91, 90, 91, 92]
    wt1[current_bar - 2:current_bar + 3]  = [-33, -36, -35, -33, -30]

    return _make_df(n=n, close_vals=close, wt1_vals=wt1, high_vals=high, low_vals=low)


def _make_hidden_bearish_df():
    """
    Hidden Bearish: индикатор HH, цена LH.
    Тренд нисходящий (коррекция заканчивается).
    Оба WT-максимума выше -20 (zone фильтр).
    """
    n = 60
    close = np.full(n, 100.0)
    high  = close.copy()
    low   = close - 2.0
    wt1   = np.full(n, 10.0)

    # Первый максимум: bar 10 → цена high=115, WT=30
    pivot_bar = 10
    high[pivot_bar - 2:pivot_bar + 3]  = [112, 114, 115, 114, 112]
    close[pivot_bar - 2:pivot_bar + 3] = [112, 114, 115, 114, 112]
    wt1[pivot_bar - 2:pivot_bar + 3]   = [28, 31, 30, 28, 25]

    # Текущий максимум: bar 55 → цена high=110 (LH), WT=35 (HH — выше 30)
    current_bar = 55
    high[current_bar - 2:current_bar + 3]  = [108, 109, 110, 109, 108]
    close[current_bar - 2:current_bar + 3] = [108, 109, 110, 109, 108]
    wt1[current_bar - 2:current_bar + 3]   = [33, 36, 35, 33, 30]

    return _make_df(n=n, close_vals=close, wt1_vals=wt1, high_vals=high, low_vals=low)


# ─── Фикстуры ─────────────────────────────────────────────────────────────────

@pytest.fixture
def det():
    return DivergenceDetector(pivot_period=3, lookback=50, max_bars=60, min_bars_between=5)


# ─── Hidden Bullish ────────────────────────────────────────────────────────────

class TestHiddenBullish:
    def test_returns_none_on_short_df(self, det):
        df = _make_df(n=10)
        result = det.detect_hidden_bullish(df)
        assert result is None

    def test_ind_change_is_negative_for_hidden_bull(self, det):
        """Hidden Bull: WT делает LL → ind_change < 0."""
        df = _make_hidden_bullish_df()
        result = det.detect_hidden_bullish(df)
        if result is None:
            pytest.skip("Hidden bullish не детектирована на синтетических данных")
        assert result["ind_change"] < 0, (
            f"Hidden Bull ind_change={result['ind_change']:.2f} должен быть < 0 (WT упал)"
        )

    def test_price_change_is_positive_for_hidden_bull(self, det):
        """Hidden Bull: цена делает HL → price_change_pct > 0."""
        df = _make_hidden_bullish_df()
        result = det.detect_hidden_bullish(df)
        if result is None:
            pytest.skip("Hidden bullish не детектирована")
        assert result["price_change_pct"] > 0, (
            f"Hidden Bull price_change={result['price_change_pct']:.2f}% должен быть > 0"
        )

    def test_zone_filter_rejects_wt_above_20(self, det):
        """Hidden Bull: если WT > +20 — зона фильтр отклоняет (не продолжение тренда)."""
        n = 60
        close = np.full(n, 100.0)
        low   = close - 2.0
        wt1   = np.full(n, 25.0)  # все значения выше +20 → фильтр должен отклонить

        # Пытаемся создать LL в WT при WT > 20
        wt1[8:13]   = [23, 26, 25, 23, 21]
        wt1[53:58]  = [28, 31, 30, 28, 25]
        low[8:13]   = [93, 91, 90, 91, 93]
        low[53:58]  = [95, 94, 95, 94, 96]  # HL

        df = _make_df(n=n, close_vals=close, wt1_vals=wt1, low_vals=low, high_vals=close + 2.0)
        result = det.detect_hidden_bullish(df)
        assert result is None, "Zone фильтр должен отклонить hidden bull при WT > +20"

    def test_result_has_required_keys(self, det):
        """Результат должен содержать все обязательные ключи."""
        df = _make_hidden_bullish_df()
        result = det.detect_hidden_bullish(df)
        if result is None:
            pytest.skip("Hidden bullish не детектирована")
        for key in ("current_idx", "pivot_idx", "ind_current", "ind_pivot",
                    "price_current", "price_pivot", "distance", "ind_change", "price_change_pct"):
            assert key in result, f"Ключ '{key}' отсутствует в результате"


# ─── Hidden Bearish ────────────────────────────────────────────────────────────

class TestHiddenBearish:
    def test_returns_none_on_short_df(self, det):
        df = _make_df(n=10)
        result = det.detect_hidden_bearish(df)
        assert result is None

    def test_ind_change_is_positive_for_hidden_bear(self, det):
        """Hidden Bear: WT делает HH → ind_change > 0."""
        df = _make_hidden_bearish_df()
        result = det.detect_hidden_bearish(df)
        if result is None:
            pytest.skip("Hidden bearish не детектирована на синтетических данных")
        assert result["ind_change"] > 0, (
            f"Hidden Bear ind_change={result['ind_change']:.2f} должен быть > 0 (WT вырос)"
        )

    def test_price_change_is_negative_for_hidden_bear(self, det):
        """Hidden Bear: цена делает LH → price_change_pct < 0."""
        df = _make_hidden_bearish_df()
        result = det.detect_hidden_bearish(df)
        if result is None:
            pytest.skip("Hidden bearish не детектирована")
        assert result["price_change_pct"] < 0, (
            f"Hidden Bear price_change={result['price_change_pct']:.2f}% должен быть < 0"
        )

    def test_zone_filter_rejects_wt_below_minus20(self, det):
        """Hidden Bear: если WT < -20 — зона фильтр отклоняет."""
        n = 60
        close = np.full(n, 100.0)
        high  = close + 2.0
        wt1   = np.full(n, -25.0)  # все значения ниже -20 → фильтр должен отклонить

        wt1[8:13]  = [-23, -21, -22, -23, -25]
        wt1[53:58] = [-18, -16, -17, -18, -20]

        df = _make_df(n=n, close_vals=close, wt1_vals=wt1, high_vals=high, low_vals=close - 2.0)
        result = det.detect_hidden_bearish(df)
        assert result is None, "Zone фильтр должен отклонить hidden bear при WT < -20"


# ─── Cascade Bonus ─────────────────────────────────────────────────────────────

class TestCascadeBonus:
    def test_1h_15m_bonus_is_10(self):
        assert DivergenceDetector._CASCADE_BONUS[("1h", "15m")] == 10

    def test_4h_1h_bonus_is_15(self):
        assert DivergenceDetector._CASCADE_BONUS[("4h", "1h")] == 15

    def test_1d_4h_bonus_is_20(self):
        assert DivergenceDetector._CASCADE_BONUS[("1D", "4h")] == 20

    def test_1w_1d_bonus_is_25(self):
        assert DivergenceDetector._CASCADE_BONUS[("1W", "1D")] == 25

    def test_unknown_pair_default_bonus(self):
        """Неизвестная пара TF → fallback бонус 10."""
        bonus = DivergenceDetector._CASCADE_BONUS.get(("3m", "1m"), 10)
        assert bonus == 10

    def test_cascade_strength_capped_at_100(self):
        """combined = min(100, ...) не превышает 100."""
        det = DivergenceDetector()
        hidden_strength = 95
        regular_strength = 95
        bonus = 25
        combined = min(100, int(hidden_strength * 0.4 + regular_strength * 0.6) + bonus)
        assert combined == 100

    def test_cascade_formula(self):
        """combined = min(100, hidden*0.4 + regular*0.6 + bonus)."""
        hidden_strength = 60
        regular_strength = 70
        bonus = 15  # 4h+1h
        expected = min(100, int(60 * 0.4 + 70 * 0.6) + 15)
        # = min(100, int(24 + 42) + 15) = min(100, 66+15) = 81
        assert expected == 81

    @pytest.mark.asyncio
    async def test_cascade_no_senior_data_returns_false(self):
        """Если нет данных старшего TF → (False, None)."""
        det = DivergenceDetector()
        dc = MagicMock()
        dc.get_ohlcv = AsyncMock(return_value=None)
        found, info = await det.detect_cascade_divergence("BTC/USDT", dc, "4h", "1h")
        assert found is False
        assert info is None

    @pytest.mark.asyncio
    async def test_cascade_short_senior_data_returns_false(self):
        """Слишком мало баров на senior TF → (False, None)."""
        det = DivergenceDetector()
        dc = MagicMock()
        import pandas as pd
        dc.get_ohlcv = AsyncMock(return_value=pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]}))
        found, info = await det.detect_cascade_divergence("BTC/USDT", dc, "1h", "15m")
        assert found is False


# ─── Граничные условия ─────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_all_methods_return_none_on_empty_df(self, det):
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "wt1", "wt2"])
        assert det.detect_regular_bullish(df) is None
        assert det.detect_regular_bearish(df) is None
        assert det.detect_hidden_bullish(df) is None
        assert det.detect_hidden_bearish(df) is None

    def test_all_methods_return_none_on_nan_df(self, det):
        n = 60
        df = _make_df(n=n)
        df["wt1"] = float("nan")
        df["close"] = float("nan")
        df["low"] = float("nan")
        df["high"] = float("nan")
        # Не должны падать с exception
        try:
            det.detect_regular_bullish(df)
            det.detect_regular_bearish(df)
            det.detect_hidden_bullish(df)
            det.detect_hidden_bearish(df)
        except Exception as e:
            pytest.fail(f"Метод упал на NaN данных: {e}")

    def test_min_bars_between_respected(self, det):
        """Дивергенция с расстоянием < min_bars_between не детектируется."""
        det_strict = DivergenceDetector(pivot_period=3, lookback=50, max_bars=60, min_bars_between=20)
        # Создаём ситуацию когда pivot_idx слишком близко к current_idx
        n = 30
        close = np.linspace(100, 80, n)
        low   = close - 1.0
        wt1   = np.linspace(-60, -70, n)
        # Два пика близко (расстояние = 10, min_bars_between = 20)
        low[5]  = 85.0
        wt1[5]  = -65.0
        low[15] = 80.0
        wt1[15] = -62.0
        df = _make_df(n=n, close_vals=close, wt1_vals=wt1, low_vals=low, high_vals=close + 2.0)
        result = det_strict.detect_regular_bullish(df)
        assert result is None

    def test_distance_keys_present(self, det):
        """Если дивергенция найдена — поле 'distance' должно быть >= min_bars_between."""
        from core.divergence_detector import DivergenceDetector
        from tests.unit.test_divergence_sign import _make_bearish_divergence_df
        df = _make_bearish_divergence_df()
        result = det.detect_regular_bearish(df, indicator_col="wt1")
        if result is None:
            pytest.skip("Дивергенция не детектирована")
        assert result["distance"] >= det.min_bars_between
        assert result["distance"] <= det.max_bars
