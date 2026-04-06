"""
Тесты MarketRegimeClassifier.
"""
import pytest
from core.market_regime import MarketRegimeClassifier, _ema, _atr, _adx


def make_ohlcv_list(closes, spread=0.5):
    """Создаёт список [ts, o, h, l, c, v] из списка close-цен."""
    result = []
    for i, c in enumerate(closes):
        result.append([
            1_700_000_000_000 + i * 60_000,
            c - spread * 0.3,
            c + spread,
            c - spread,
            c,
            10_000.0,
        ])
    return result


class TestHelpers:
    def test_ema_basic(self):
        prices = [float(i) for i in range(1, 21)]
        result = _ema(prices, 5)
        assert len(result) > 0
        assert result[-1] > result[0]  # растущий ряд → EMA растёт

    def test_ema_too_short(self):
        assert _ema([1.0, 2.0], 5) == []

    def test_atr_basic(self):
        n = 30
        highs = [100.0 + i * 0.1 + 0.5 for i in range(n)]
        lows  = [100.0 + i * 0.1 - 0.5 for i in range(n)]
        closes = [100.0 + i * 0.1 for i in range(n)]
        result = _atr(highs, lows, closes, 14)
        assert len(result) > 0
        assert all(v > 0 for v in result)

    def test_adx_not_none(self):
        n = 50
        highs  = [100.0 + i * 0.1 + 0.5 for i in range(n)]
        lows   = [100.0 + i * 0.1 - 0.5 for i in range(n)]
        closes = [100.0 + i * 0.1 for i in range(n)]
        result = _adx(highs, lows, closes, 14)
        assert result is not None
        assert 0 <= result <= 100

    def test_adx_too_short(self):
        result = _adx([1.0] * 10, [0.9] * 10, [0.95] * 10, 14)
        assert result is None


class TestMarketRegimeClassifier:
    def setup_method(self):
        self.clf = MarketRegimeClassifier()

    def test_none_on_empty(self):
        assert self.clf.classify_from_ohlcv([]) is None

    def test_none_on_too_few_candles(self):
        ohlcv = make_ohlcv_list([100.0] * 10)
        assert self.clf.classify_from_ohlcv(ohlcv) is None

    def test_returns_string(self):
        ohlcv = make_ohlcv_list([100.0 + i * 0.01 for i in range(50)])
        result = self.clf.classify_from_ohlcv(ohlcv)
        assert result in ("TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL", None)

    def test_uptrend_detected(self):
        """Резкий восходящий тренд должен дать TREND_UP."""
        closes = [100.0 + i * 0.5 for i in range(80)]  # +40% за 80 свечей
        ohlcv = make_ohlcv_list(closes, spread=0.2)
        result = self.clf.classify_from_ohlcv(ohlcv)
        assert result == "TREND_UP"

    def test_downtrend_detected(self):
        """Резкий нисходящий тренд должен дать TREND_DOWN."""
        closes = [200.0 - i * 0.5 for i in range(80)]  # −40% за 80 свечей
        ohlcv = make_ohlcv_list(closes, spread=0.2)
        result = self.clf.classify_from_ohlcv(ohlcv)
        assert result == "TREND_DOWN"

    def test_range_detected(self):
        """Боковик (белый шум без тренда) должен дать RANGE."""
        import random
        rng = random.Random(42)
        # Стационарный шум: ADX < 25 → RANGE
        closes = [100.0 + rng.uniform(-0.3, 0.3) for _ in range(80)]
        ohlcv = make_ohlcv_list(closes, spread=0.1)
        result = self.clf.classify_from_ohlcv(ohlcv)
        assert result == "RANGE"

    def test_high_vol_detected(self):
        """Резкий скачок волатильности → HIGH_VOL."""
        import random
        random.seed(0)
        # Первые 60 свечей спокойные, последние 10 — огромные свечи
        closes = [100.0 + random.uniform(-0.1, 0.1) for _ in range(60)]
        closes += [100.0 + random.uniform(-15, 15) for _ in range(10)]
        ohlcv = make_ohlcv_list(closes, spread=0.05)
        # Заменяем spread на реальный для последних свечей
        for i in range(60, len(ohlcv)):
            ohlcv[i][2] = closes[i] + 10  # high
            ohlcv[i][3] = closes[i] - 10  # low
        result = self.clf.classify_from_ohlcv(ohlcv)
        assert result == "HIGH_VOL"

    def test_invalid_data_returns_none(self):
        """Некорректные данные не должны ронять классификатор."""
        bad = [["x", "y", "z", "w", "q", 0] for _ in range(50)]
        result = self.clf.classify_from_ohlcv(bad)
        assert result is None
