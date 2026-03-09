"""
Тесты для PivotCalculatorFixed.get_pivot_tp — Этап 6: Динамический TP.
"""
import pytest
from core.pivot_calculator_fixed import PivotCalculatorFixed


def _calc_with_cache(symbol: str, pivot_prices: list) -> PivotCalculatorFixed:
    """Создаёт экземпляр с предзаполненным кешем без API-запросов."""
    calc = PivotCalculatorFixed.__new__(PivotCalculatorFixed)
    calc.pivot_cache = {}
    calc.logger = __import__("logging").getLogger("test")
    # Кладём уровни сразу в 1D, чтобы get_pivot_tp их нашёл
    pivots = {}
    keys = ["PP"] + [f"S{i}" for i in range(1, 6)] + [f"R{i}" for i in range(1, 6)]
    for i, price in enumerate(pivot_prices):
        if i < len(keys):
            pivots[keys[i]] = price
    calc.pivot_cache[f"{symbol}_1D"] = pivots
    return calc


class TestGetPivotTP:
    # ──── LONG ────

    def test_long_nearest_above(self):
        # entry=100, sl=95 (sl_dist=5), min_r=1.5 → нужен TP >= 100+7.5 = 107.5
        # Уровни выше: 102, 108, 115
        calc = _calc_with_cache("BTC/USDT", [90, 85, 80, 102, 108, 115])
        tp = calc.get_pivot_tp("LONG", 100.0, "BTC/USDT", stop_loss=95.0, min_r=1.5)
        assert tp is not None
        assert tp >= 107.5
        # Должен вернуть первый подходящий — 108
        assert tp == 108.0

    def test_long_no_level_above(self):
        # Все уровни ниже entry
        calc = _calc_with_cache("BTC/USDT", [90, 85, 80, 75])
        tp = calc.get_pivot_tp("LONG", 100.0, "BTC/USDT", stop_loss=95.0)
        assert tp is None

    def test_long_without_sl_returns_nearest_above(self):
        # Без SL — возвращает ближайший уровень выше
        calc = _calc_with_cache("ETH/USDT", [90, 95, 105, 110])
        tp = calc.get_pivot_tp("LONG", 100.0, "ETH/USDT", stop_loss=None)
        assert tp == 105.0

    def test_long_min_r_filters_close_levels(self):
        # entry=100, sl=98 (sl_dist=2), min_r=2.0 → нужен TP >= 104
        # Уровни: 101.5, 103, 105 → первый подходящий 105
        calc = _calc_with_cache("BTC/USDT", [95, 101.5, 103.0, 105.0])
        tp = calc.get_pivot_tp("LONG", 100.0, "BTC/USDT", stop_loss=98.0, min_r=2.0)
        assert tp == 105.0

    # ──── SHORT ────

    def test_short_nearest_below(self):
        # entry=100, sl=105 (sl_dist=5), min_r=1.5 → нужен TP <= 100-7.5 = 92.5
        # Уровни ниже: 98, 92, 85
        calc = _calc_with_cache("BTC/USDT", [85, 92, 98, 105, 110])
        tp = calc.get_pivot_tp("SHORT", 100.0, "BTC/USDT", stop_loss=105.0, min_r=1.5)
        assert tp is not None
        assert tp <= 92.5
        assert tp == 92.0

    def test_short_no_level_below(self):
        calc = _calc_with_cache("BTC/USDT", [105, 110, 115])
        tp = calc.get_pivot_tp("SHORT", 100.0, "BTC/USDT", stop_loss=105.0)
        assert tp is None

    def test_short_without_sl_returns_nearest_below(self):
        calc = _calc_with_cache("ETH/USDT", [85, 90, 95, 105])
        tp = calc.get_pivot_tp("SHORT", 100.0, "ETH/USDT", stop_loss=None)
        assert tp == 95.0

    # ──── Граничные случаи ────

    def test_empty_cache_returns_none(self):
        calc = PivotCalculatorFixed.__new__(PivotCalculatorFixed)
        calc.pivot_cache = {}
        calc.logger = __import__("logging").getLogger("test")
        tp = calc.get_pivot_tp("LONG", 100.0, "BTC/USDT")
        assert tp is None

    def test_zero_entry_price_returns_none(self):
        calc = _calc_with_cache("BTC/USDT", [90, 110])
        tp = calc.get_pivot_tp("LONG", 0.0, "BTC/USDT")
        assert tp is None

    def test_unknown_direction_returns_none(self):
        calc = _calc_with_cache("BTC/USDT", [90, 110])
        tp = calc.get_pivot_tp("NEUTRAL", 100.0, "BTC/USDT")
        assert tp is None

    def test_multiple_timeframes_merged(self):
        """Уровни из 1M, 1W, 1D объединяются."""
        calc = PivotCalculatorFixed.__new__(PivotCalculatorFixed)
        calc.pivot_cache = {}
        calc.logger = __import__("logging").getLogger("test")
        # 1M имеет только R1=120, 1D имеет R1=108
        calc.pivot_cache["SYM_1M"] = {"PP": 100.0, "R1": 120.0}
        calc.pivot_cache["SYM_1D"] = {"PP": 99.0, "R1": 108.0}
        # entry=100, sl=95 → sl_dist=5, min_r=1.5 → нужен >=107.5
        tp = calc.get_pivot_tp("LONG", 100.0, "SYM", stop_loss=95.0, min_r=1.5)
        assert tp == 108.0  # ближайший уровень с R >= 1.5 из объединённого списка
