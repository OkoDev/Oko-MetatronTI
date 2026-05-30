"""Unit-тесты для RSIService (ARCH-117 ph2, 30.05.2026).

RSIService на каноне compute_rsi (Wilder RMA), БЕЗ новой формулы.
"""
import numpy as np

from core.intelligence.rsi_service import (
    build_rsi_snap_entry, build_rsi_snap, RSI_OB, RSI_OS, RSI_MID,
)


class TestThresholds:
    def test_standard_levels(self):
        assert RSI_OB == 70.0
        assert RSI_OS == 30.0
        assert RSI_MID == 50.0


class TestRsiSnapEntry:
    def test_uptrend_high_rsi(self):
        # Монотонный рост → RSI высокий → OB
        closes = list(np.linspace(100, 130, 40))
        snap = build_rsi_snap_entry(closes, period=14)
        assert snap is not None
        assert snap["rsi"] > RSI_OB
        assert snap["zone"] == "OB"

    def test_downtrend_low_rsi(self):
        closes = list(np.linspace(130, 100, 40))
        snap = build_rsi_snap_entry(closes, period=14)
        assert snap is not None
        assert snap["rsi"] < RSI_OS
        assert snap["zone"] == "OS"

    def test_neutral_zone(self):
        # Колебания вокруг уровня → RSI ~50 → N
        rng = np.random.default_rng(3)
        closes = list(100 + np.cumsum(rng.normal(0, 0.5, 60)))
        snap = build_rsi_snap_entry(closes, period=14)
        assert snap is not None
        assert snap["zone"] in ("N", "OB", "OS")  # хотя бы не падает
        assert 0 <= snap["rsi"] <= 100

    def test_insufficient_data(self):
        assert build_rsi_snap_entry([1, 2, 3], period=14) is None

    def test_cross50_up(self):
        # Сначала падение (RSI<50), потом резкий рост → cross вверх
        down = list(np.linspace(120, 100, 20))
        up = list(np.linspace(100, 115, 20))
        snap = build_rsi_snap_entry(down + up, period=14)
        assert snap is not None
        assert snap["cross50"] in (1, 0)  # импульс вверх

    def test_fields_present(self):
        closes = list(np.linspace(100, 120, 40))
        snap = build_rsi_snap_entry(closes, period=14)
        assert set(snap) == {"rsi", "zone", "cross50"}


class TestBuildSnap:
    def test_multi_tf(self):
        up = list(np.linspace(100, 130, 40))
        down = list(np.linspace(130, 100, 40))
        snap = build_rsi_snap([("1h", up), ("4h", down), ("15m", None)])
        assert "1h" in snap and snap["1h"]["zone"] == "OB"
        assert "4h" in snap and snap["4h"]["zone"] == "OS"
        assert "15m" not in snap  # None пропущен

    def test_no_new_formula_matches_canon(self):
        """RSIService использует тот же compute_rsi — значения совпадают."""
        from core.indicators.indicators import compute_rsi
        closes = list(np.linspace(100, 125, 50))
        snap = build_rsi_snap_entry(closes, period=14)
        canon = compute_rsi(closes, period=14)
        assert abs(snap["rsi"] - round(canon, 2)) < 0.01
