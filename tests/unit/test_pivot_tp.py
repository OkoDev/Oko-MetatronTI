"""
Тесты для PivotCalculatorFixed.get_pivot_tp — Этап 6: Динамический TP.
"""
import pytest
from core.pivots.pivot_calculator_fixed import PivotCalculatorFixed


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


class TestGetTpByHierarchy:
    """Тесты для ARCH-09п5: TP по иерархии пивотов."""

    def _calc(self, caches: dict) -> PivotCalculatorFixed:
        """Создаёт экземпляр с предзаполненным pivot_cache."""
        calc = PivotCalculatorFixed.__new__(PivotCalculatorFixed)
        calc.pivot_cache = caches
        calc.logger = __import__("logging").getLogger("test")
        return calc

    # ── Конфлюэнции ──────────────────────────────────────────────────────────

    def test_1d_wins_over_confluence_1m_1w(self):
        """[01] DEV-75: 1D-уровень приоритетнее конфлюэнции 1M+1W (avg_R: 1D=+1.536 vs 1M+1W=-0.603)."""
        # entry=100, sl=95 (sl_dist=5), min_r=2.0 → нужен TP >= 110
        # 1M R1=112, 1W R1=112.2 (конфлюэнция ≈112.1)
        # 1D R1=115 (R=3.0 ✓) — должна победить 1D, не конфлюэнция
        calc = self._calc({
            "SYM_1M": {"PP": 100.0, "R1": 112.0},
            "SYM_1W": {"PP": 99.5, "R1": 112.2},
            "SYM_1D": {"PP": 98.0, "R1": 115.0},
        })
        result = calc.get_tp_by_hierarchy("LONG", 100.0, "SYM", stop_loss=95.0, min_r=2.0)
        assert result is not None
        tp, src = result
        assert "pivot_1D" in src
        assert tp == 115.0

    def test_1d_wins_when_only_1w_and_1d(self):
        """[02] DEV-75: при наличии 1W и 1D (без 1M), победит 1D (приоритет выше 1W)."""
        calc = self._calc({
            "SYM_1W": {"PP": 99.0, "R1": 110.0},
            "SYM_1D": {"PP": 98.5, "R1": 110.2},
        })
        # entry=100, sl=95 → sl_dist=5, min_r=2.0 → TP >= 110; 1D R1=110.2, R=2.04 ✓
        result = calc.get_tp_by_hierarchy("LONG", 100.0, "SYM", stop_loss=95.0, min_r=2.0)
        assert result is not None
        tp, src = result
        assert "pivot_1D" in src

    # ── TF-уровни ─────────────────────────────────────────────────────────────

    def test_1m_level_used_when_no_1w_1d(self):
        """[03] DEV-130: только 1M в кеше → возвращает None (1M заблокирован как TP, WR=4%, avg_R=-0.779)."""
        calc = self._calc({
            "SYM_1M": {"PP": 95.0, "R1": 115.0},
        })
        result = calc.get_tp_by_hierarchy("LONG", 100.0, "SYM", stop_loss=95.0, min_r=2.0)
        assert result is None  # DEV-130: 1M TP заблокирован

    def test_1w_fallback_when_no_1m(self):
        """[04] Нет 1M → берём 1W-уровень."""
        calc = self._calc({
            "SYM_1W": {"PP": 99.0, "R1": 114.0},
        })
        result = calc.get_tp_by_hierarchy("LONG", 100.0, "SYM", stop_loss=95.0, min_r=2.0)
        assert result is not None
        tp, src = result
        assert "pivot_1W" in src
        assert tp == 114.0

    def test_1d_fallback_when_no_1m_1w(self):
        """[05] Только 1D → берём 1D-уровень."""
        calc = self._calc({
            "SYM_1D": {"PP": 99.0, "R1": 112.0},
        })
        result = calc.get_tp_by_hierarchy("LONG", 100.0, "SYM", stop_loss=95.0, min_r=2.0)
        assert result is not None
        tp, src = result
        assert "pivot_1D" in src

    # ── SHORT ─────────────────────────────────────────────────────────────────

    def test_short_1w_wins_over_confluence_1m_1w(self):
        """[06] DEV-75 SHORT: 1W-уровень приоритетнее конфлюэнции 1M+1W."""
        calc = self._calc({
            "SYM_1M": {"PP": 100.0, "S1": 88.0},
            "SYM_1W": {"PP": 100.5, "S1": 87.9},
        })
        # entry=100, sl=105 → sl_dist=5, min_r=2.0 → TP <= 90; 1W S1=87.9, R=2.42 ✓
        result = calc.get_tp_by_hierarchy("SHORT", 100.0, "SYM", stop_loss=105.0, min_r=2.0)
        assert result is not None
        tp, src = result
        assert "pivot_1W" in src
        assert tp == 87.9

    def test_short_1w_fallback(self):
        """[07] SHORT без конфлюэнции → 1W-уровень ниже entry."""
        calc = self._calc({
            "SYM_1W": {"PP": 101.0, "S1": 87.0},
        })
        result = calc.get_tp_by_hierarchy("SHORT", 100.0, "SYM", stop_loss=105.0, min_r=2.0)
        assert result is not None
        tp, src = result
        assert "pivot_1W" in src
        assert tp == 87.0

    # ── Граничные случаи ──────────────────────────────────────────────────────

    def test_empty_cache_returns_none(self):
        """[08] Пустой кеш → None."""
        calc = self._calc({})
        result = calc.get_tp_by_hierarchy("LONG", 100.0, "SYM", stop_loss=95.0)
        assert result is None

    def test_zero_entry_returns_none(self):
        """[09] entry_price=0 → None."""
        calc = self._calc({"SYM_1D": {"R1": 110.0}})
        result = calc.get_tp_by_hierarchy("LONG", 0.0, "SYM")
        assert result is None

    def test_no_level_qualifies_min_r_returns_none(self):
        """[10] Все уровни не проходят min_r → None."""
        # entry=100, sl=90 (sl_dist=10), min_r=3.0 → TP >= 130
        # Единственный уровень: 110 (R=1.0, не проходит)
        calc = self._calc({
            "SYM_1D": {"R1": 110.0},
        })
        result = calc.get_tp_by_hierarchy("LONG", 100.0, "SYM", stop_loss=90.0, min_r=3.0)
        assert result is None
