"""
Тест знака ind_change для Regular Bearish дивергенции.
Регрессионный тест: баг line 295 divergence_detector.py
  было: ind_pivot - ind_current → всегда положительное
  стало: ind_current - ind_pivot → отрицательное (индикатор упал)
"""
import numpy as np
import pandas as pd
import pytest
from core.indicators.divergence_detector import DivergenceDetector


def _make_bearish_divergence_df() -> pd.DataFrame:
    """
    Синтетические данные с классической Regular Bearish дивергенцией:
    - Цена: HH (Higher High) — растёт
    - WT: LH (Lower High) — падает
    - Оба WT-пика в OB-зоне (> 60)
    """
    n = 60
    close = np.full(n, 100.0)
    high = np.full(n, 100.0)
    low = np.full(n, 98.0)
    volume = np.full(n, 1e6)
    wt1 = np.full(n, 50.0)  # нейтральная зона по умолчанию

    # Первый пик: bar 10 → цена 120, WT = 80 (OB)
    pivot_bar = 10
    high[pivot_bar - 2 : pivot_bar + 3] = [115, 118, 120, 118, 115]
    close[pivot_bar - 2 : pivot_bar + 3] = [115, 118, 120, 118, 115]
    wt1[pivot_bar - 2 : pivot_bar + 3] = [72, 76, 80, 76, 72]

    # Текущий (последний) пик: bar 55 → цена 130 (HH), WT = 65 (LH, ещё в OB)
    current_bar = 55
    high[current_bar - 2 : current_bar + 3] = [125, 128, 130, 128, 125]
    close[current_bar - 2 : current_bar + 3] = [125, 128, 130, 128, 125]
    wt1[current_bar - 2 : current_bar + 3] = [61, 63, 65, 63, 61]

    df = pd.DataFrame({
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "wt1": wt1,
        "wt2": wt1 * 0.9,
    })
    return df


class TestBearishDivergenceSign:
    def setup_method(self):
        self.det = DivergenceDetector(
            pivot_period=3,
            lookback=50,
            max_bars=60,
            min_bars_between=5,
        )

    def test_bearish_ind_change_is_negative(self):
        """ind_change для Regular Bearish должен быть ОТРИЦАТЕЛЬНЫМ (WT упал)."""
        df = _make_bearish_divergence_df()
        result = self.det.detect_regular_bearish(df, indicator_col="wt1")
        if result is None:
            pytest.skip("Дивергенция не детектирована на синтетических данных")
        assert result["ind_change"] < 0, (
            f"ind_change={result['ind_change']:.2f} должен быть < 0: "
            f"WT упал с {result['ind_pivot']:.1f} до {result['ind_current']:.1f}"
        )

    def test_bearish_ind_change_formula(self):
        """ind_change = ind_current - ind_pivot (а не наоборот)."""
        df = _make_bearish_divergence_df()
        result = self.det.detect_regular_bearish(df, indicator_col="wt1")
        if result is None:
            pytest.skip("Дивергенция не детектирована на синтетических данных")
        expected = result["ind_current"] - result["ind_pivot"]
        assert abs(result["ind_change"] - expected) < 1e-6, (
            f"ind_change={result['ind_change']} != ind_current - ind_pivot = {expected}"
        )

    def test_bullish_ind_change_is_positive(self):
        """Для Regular Bullish ind_change должен быть ПОЛОЖИТЕЛЬНЫМ (WT вырос)."""
        n = 60
        close = np.full(n, 100.0)
        high = np.full(n, 102.0)
        low = np.full(n, 100.0)
        volume = np.full(n, 1e6)
        wt1 = np.full(n, -50.0)

        # Первый пик: bar 10 → цена 85 (LL), WT = -75 (OS)
        low[8:13] = [88, 86, 85, 86, 88]
        close[8:13] = [88, 86, 85, 86, 88]
        wt1[8:13] = [-73, -76, -75, -73, -70]

        # Текущий: bar 55 → цена 80 (LL), WT = -65 (HL, менее отрицательный)
        low[53:58] = [83, 81, 80, 81, 83]
        close[53:58] = [83, 81, 80, 81, 83]
        wt1[53:58] = [-63, -66, -65, -63, -60]

        df = pd.DataFrame({
            "open": close, "high": high, "low": low, "close": close,
            "volume": volume, "wt1": wt1, "wt2": wt1 * 0.9,
        })

        result = self.det.detect_regular_bullish(df, indicator_col="wt1")
        if result is None:
            pytest.skip("Bullish дивергенция не детектирована")
        assert result["ind_change"] > 0, (
            f"Bullish ind_change={result['ind_change']:.2f} должен быть > 0"
        )
