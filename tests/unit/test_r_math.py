"""Unit-тесты для core.trading.r_math (создан 27.05.2026)."""
from core.trading.r_math import (
    compute_one_r, compute_r, clamp_r, compute_unrealized_r,
    R_CLAMP_MIN, R_CLAMP_MAX,
)


class TestComputeOneR:
    def test_original_sl_priority(self):
        # original_sl приоритетнее fallback_sl
        one_r, src = compute_one_r(100.0, 95.0, fallback_sl=99.0)
        assert one_r == 5.0
        assert src == "original_sl"

    def test_fallback_used_when_original_null(self):
        one_r, src = compute_one_r(100.0, None, fallback_sl=92.0)
        assert one_r == 8.0
        assert src == "fallback_sl"

    def test_none_when_both_missing(self):
        one_r, src = compute_one_r(100.0, None, fallback_sl=None)
        assert one_r is None
        assert src == "none"

    def test_none_when_sl_equals_entry(self):
        # SL == entry → нулевая дистанция, защищает от деления на ноль
        one_r, src = compute_one_r(100.0, 100.0)
        assert one_r is None

    def test_none_when_entry_invalid(self):
        assert compute_one_r(0, 95.0) == (None, "none")
        assert compute_one_r(None, 95.0) == (None, "none")
        assert compute_one_r(-1, 95.0) == (None, "none")


class TestComputeR:
    def test_long_profit(self):
        # LONG: price > entry → R > 0
        assert compute_r("LONG", 100, 110, 5.0) == 2.0

    def test_long_loss(self):
        assert compute_r("LONG", 100, 95, 5.0) == -1.0

    def test_short_profit(self):
        # SHORT: price < entry → R > 0
        assert compute_r("SHORT", 100, 90, 5.0) == 2.0

    def test_short_loss(self):
        assert compute_r("SHORT", 100, 105, 5.0) == -1.0

    def test_none_when_one_r_zero(self):
        assert compute_r("LONG", 100, 110, 0) is None

    def test_direction_case_insensitive(self):
        assert compute_r("long", 100, 110, 5.0) == 2.0
        assert compute_r("Short", 100, 90, 5.0) == 2.0


class TestClampR:
    def test_passthrough_in_range(self):
        assert clamp_r(5.0) == 5.0
        assert clamp_r(-5.0) == -5.0
        assert clamp_r(0) == 0

    def test_clamp_high(self):
        assert clamp_r(100) == R_CLAMP_MAX
        assert clamp_r(R_CLAMP_MAX) == R_CLAMP_MAX

    def test_clamp_low(self):
        assert clamp_r(-100) == R_CLAMP_MIN

    def test_none(self):
        assert clamp_r(None) is None

    def test_custom_bounds(self):
        assert clamp_r(10, lo=-3, hi=3) == 3


class TestComputeUnrealizedR:
    def test_swarms_scenario_uses_original_sl(self):
        # #15101 SWARMS: stop_loss подтянут TSL'ом к entry, original_sl нормальный.
        # До фикса дашборд использовал текущий stop_loss → +8103R artefact.
        # Теперь через original_sl → разумное ~1.4R.
        r = compute_unrealized_r(
            "SHORT", entry=0.00987, current_price=0.0093,
            original_sl=0.010281,         # initial SL (~4% sl_dist)
            fallback_sl=0.009870074,      # текущий TSL'нутый (sl_dist ~ 0)
        )
        # raw R = (0.00987 - 0.0093) / |0.00987 - 0.010281| ≈ 1.39
        assert r is not None
        assert 1.3 < r < 1.5   # реалистичное R, не +8000

    def test_artefact_when_only_fallback_available(self):
        # Если original_sl=None И fallback_sl близок к entry — теоретически
        # огромный R, но clamp защищает.
        r = compute_unrealized_r(
            "SHORT", entry=0.00987, current_price=0.0093,
            original_sl=None,
            fallback_sl=0.009870074,   # TSL'нутый, sl_dist микро
        )
        # raw R ~ +7700 → clamp до +15
        assert r == R_CLAMP_MAX

    def test_fallback_to_current_sl_when_original_missing(self):
        # Старые сделки без original_sl, fallback_sl нормальный
        r = compute_unrealized_r("LONG", 100, 110, original_sl=None, fallback_sl=95.0)
        assert r == 2.0

    def test_none_when_no_sl_data(self):
        assert compute_unrealized_r("LONG", 100, 110, original_sl=None) is None
