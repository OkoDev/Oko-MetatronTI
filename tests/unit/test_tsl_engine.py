"""
Unit-тесты для core/trading/tsl_engine.py.

Покрывают симметрию LONG/SHORT, floor guard, side validation, breakeven,
и регрессию REAL #7264 (SHORT TSL ниже entry → биржа отвергала ордер).
"""
import pytest

from core.trading.tsl_engine import (
    TSLDecision,
    apply_floor,
    breakeven_sl,
    compute_tsl,
    get_entry_sl,
    is_side_valid,
    is_tighter,
    is_tsl_triggered,
    should_update,
)


# ═══════════════════════════════════════════════════════════════════════
# apply_floor — симметричный guard для LONG/SHORT
# ═══════════════════════════════════════════════════════════════════════

class TestApplyFloor:
    def test_long_raw_tighter_than_floor_passthrough(self):
        """LONG: raw_sl=99.8 выше floor=99.7 — max выбирает raw (держим тесней)."""
        sl, floored = apply_floor("LONG", entry=100.0, raw_sl=99.8)
        assert sl == 99.8
        assert floored is False

    def test_long_raw_far_below_entry_pulled_up(self):
        """LONG: raw_sl=98 далеко ниже entry — floor подтягивает к 99.7 (тесней SL)."""
        sl, floored = apply_floor("LONG", entry=100.0, raw_sl=98.0)
        assert sl == pytest.approx(99.7, rel=1e-9)
        assert floored is True

    def test_long_raw_above_entry_passthrough(self):
        """LONG: raw_sl выше entry (прибыль залочена) — max держит raw."""
        sl, floored = apply_floor("LONG", entry=100.0, raw_sl=103.0)
        assert sl == 103.0
        assert floored is False

    def test_short_raw_tighter_than_floor_passthrough(self):
        """SHORT: raw_sl=100.2 между entry и floor — max выбирает floor 100.3."""
        sl, floored = apply_floor("SHORT", entry=100.0, raw_sl=100.2)
        assert sl == pytest.approx(100.3, rel=1e-9)
        assert floored is True

    def test_short_raw_above_floor_passthrough(self):
        """SHORT: raw_sl=102 выше floor=100.3 — max держит raw (тесней SL для SHORT?
        Нет: для SHORT тесней = НИЖЕ, но max даёт выше. Это "далёкий SL стоит далеко")."""
        sl, floored = apply_floor("SHORT", entry=100.0, raw_sl=102.0)
        assert sl == 102.0
        assert floored is False

    def test_short_raw_below_entry_pulled_up(self):
        """SHORT: raw_sl=98 (инвертированный, ниже entry) — floor подтягивает до 100.3."""
        sl, floored = apply_floor("SHORT", entry=100.0, raw_sl=98.0)
        assert sl == pytest.approx(100.3, rel=1e-9)
        assert floored is True

    def test_short_real_7264_regression(self):
        """REAL #7264: SHORT SL=0.070349 < entry=0.07209 — floor обязан поднять."""
        entry = 0.07209
        raw_sl = 0.070349  # из логов: SL ниже entry — перевёрнутый
        sl, floored = apply_floor("SHORT", entry=entry, raw_sl=raw_sl)
        expected_floor = entry * 1.003  # 0.07230627
        assert sl == pytest.approx(expected_floor, rel=1e-9)
        assert floored is True
        assert sl > entry, f"SHORT SL {sl} должен быть выше entry {entry}"

    def test_short_wick_guard(self):
        """SHORT: wick до entry*1.001 не выбивает позицию (floor 1.003)."""
        entry = 100.0
        sl, _ = apply_floor("SHORT", entry=entry, raw_sl=99.0)  # сломанный raw
        wick = entry * 1.001
        assert wick < sl

    def test_short_large_profit_floor_from_current_price(self):
        """DEV-191: SHORT entry=100, current=70 (большой профит).
        Floor должен быть от current_price (70.21), не от entry (100.3)."""
        sl, floored = apply_floor("SHORT", entry=100.0, raw_sl=68.0, current_price=70.0)
        assert sl == pytest.approx(70.0 * 1.003, rel=1e-9)
        assert floored is True
        assert sl < 75.0, "SL не должен застрять у entry 100"

    def test_short_large_profit_tsl_free_above_floor(self):
        """DEV-191: trenddown=72 уже выше floor=70.21 — raw_tsl проходит без изменений."""
        sl, floored = apply_floor("SHORT", entry=100.0, raw_sl=72.0, current_price=70.0)
        assert sl == 72.0
        assert floored is False

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError):
            apply_floor("invalid", entry=100.0, raw_sl=99.0)


# ═══════════════════════════════════════════════════════════════════════
# breakeven_sl
# ═══════════════════════════════════════════════════════════════════════

class TestBreakevenSl:
    def test_long_be_above_entry(self):
        assert breakeven_sl("LONG", entry=100.0) == 100.1

    def test_short_be_below_entry(self):
        assert breakeven_sl("SHORT", entry=100.0) == pytest.approx(99.9, rel=1e-9)

    def test_custom_buffer(self):
        assert breakeven_sl("LONG", entry=100.0, buffer_pct=0.005) == pytest.approx(100.5, rel=1e-9)


# ═══════════════════════════════════════════════════════════════════════
# is_side_valid — guard перед отправкой на биржу
# ═══════════════════════════════════════════════════════════════════════

class TestIsSideValid:
    def test_long_valid(self):
        assert is_side_valid("LONG", sl=98.0, reference_price=100.0) is True

    def test_long_invalid_sl_above_price(self):
        assert is_side_valid("LONG", sl=101.0, reference_price=100.0) is False

    def test_short_valid(self):
        assert is_side_valid("SHORT", sl=102.0, reference_price=100.0) is True

    def test_short_invalid_sl_below_price(self):
        """REAL #7264 симптом: SHORT + SL ниже цены — биржа отвергнет."""
        assert is_side_valid("SHORT", sl=99.0, reference_price=100.0) is False

    def test_zero_sl_invalid(self):
        assert is_side_valid("LONG", sl=0, reference_price=100.0) is False

    def test_none_sl_invalid(self):
        assert is_side_valid("LONG", sl=None, reference_price=100.0) is False


# ═══════════════════════════════════════════════════════════════════════
# is_tsl_triggered
# ═══════════════════════════════════════════════════════════════════════

class TestIsTslTriggered:
    def test_long_triggered_on_cross_down(self):
        assert is_tsl_triggered("LONG", current_price=97.0, sl=98.0) is True

    def test_long_not_triggered(self):
        assert is_tsl_triggered("LONG", current_price=99.0, sl=98.0) is False

    def test_short_triggered_on_cross_up(self):
        assert is_tsl_triggered("SHORT", current_price=103.0, sl=102.0) is True

    def test_short_not_triggered(self):
        assert is_tsl_triggered("SHORT", current_price=101.0, sl=102.0) is False


# ═══════════════════════════════════════════════════════════════════════
# is_tighter — сравнение кандидата и текущего TSL
# ═══════════════════════════════════════════════════════════════════════

class TestIsTighter:
    def test_long_tighter_higher(self):
        """LONG: тесней = ближе к цене снизу = ВЫШЕ."""
        assert is_tighter("LONG", candidate_sl=99.0, current_sl=98.0) is True

    def test_long_not_tighter(self):
        assert is_tighter("LONG", candidate_sl=97.0, current_sl=98.0) is False

    def test_short_tighter_lower(self):
        """SHORT: тесней = ближе к цене сверху = НИЖЕ."""
        assert is_tighter("SHORT", candidate_sl=101.0, current_sl=102.0) is True

    def test_short_not_tighter(self):
        assert is_tighter("SHORT", candidate_sl=103.0, current_sl=102.0) is False


# ═══════════════════════════════════════════════════════════════════════
# should_update — min_move_pct фильтр
# ═══════════════════════════════════════════════════════════════════════

class TestShouldUpdate:
    def test_below_threshold_skip(self):
        assert should_update(old_sl=100.0, new_sl=100.10) is False

    def test_at_threshold_accept(self):
        assert should_update(old_sl=100.0, new_sl=100.15) is True

    def test_above_threshold_accept(self):
        assert should_update(old_sl=100.0, new_sl=100.50) is True

    def test_no_move_skip(self):
        assert should_update(old_sl=100.0, new_sl=100.0) is False

    def test_zero_old_skip(self):
        assert should_update(old_sl=0, new_sl=100.0) is False


# ═══════════════════════════════════════════════════════════════════════
# compute_tsl — главная функция
# ═══════════════════════════════════════════════════════════════════════

class TestComputeTsl:
    def test_long_normal(self):
        d = compute_tsl("LONG", entry=100.0, current_price=105.0, raw_tsl=103.0)
        assert d.new_sl == 103.0
        assert d.triggered is False
        assert d.floored is False
        assert d.side_valid is True
        assert d.reason == "ok"

    def test_short_normal(self):
        """SHORT: raw_tsl выше entry и выше current — нормальная ситуация."""
        d = compute_tsl("SHORT", entry=100.0, current_price=95.0, raw_tsl=102.0)
        assert d.new_sl == 102.0
        assert d.triggered is False
        assert d.side_valid is True
        assert d.floored is False

    def test_no_raw_tsl(self):
        d = compute_tsl("LONG", entry=100.0, current_price=105.0, raw_tsl=None)
        assert d.new_sl is None
        assert d.reason == "no_raw_tsl"

    def test_short_real_7264_regression(self):
        """REAL #7264 + DEV-191: raw_tsl ниже entry для SHORT.
        DEV-191: floor привязан к current_price (0.071), не к entry (0.07209).
        Биржа принимает SL т.к. new_sl > current_price — это главное."""
        d = compute_tsl(
            "SHORT",
            entry=0.07209,
            current_price=0.071,
            raw_tsl=0.070349,
        )
        assert d.floored is True
        assert d.new_sl == pytest.approx(0.071 * 1.003, rel=1e-9)
        # SL выше current_price — биржа не отвергнет (суть REAL #7264 fix)
        assert d.new_sl > 0.071
        assert d.side_valid is True

    def test_long_tsl_triggered(self):
        """LONG: цена упала ниже SL → triggered."""
        d = compute_tsl("LONG", entry=100.0, current_price=97.0, raw_tsl=98.0)
        assert d.triggered is True

    def test_short_large_profit_tsl_follows_price(self):
        """DEV-191: SHORT entry=100, current=70 — TSL следует за ценой, не застрял у entry."""
        d = compute_tsl("SHORT", entry=100.0, current_price=70.0, raw_tsl=68.0)
        assert d.new_sl < 75.0, "SL застрял у entry — DEV-191 регрессия"
        assert d.new_sl > 70.0
        assert d.side_valid is True
        assert d.floored is True


# ═══════════════════════════════════════════════════════════════════════
# get_entry_sl — используется стратегиями
# ═══════════════════════════════════════════════════════════════════════

class TestGetEntrySl:
    def test_long_tsl_line_valid(self):
        sl, src = get_entry_sl("LONG", entry=100.0, tsl_line=98.0, buffer_pct=0.001)
        assert sl == pytest.approx(98.0 * 0.999, rel=1e-9)
        assert src == "tsl_line"

    def test_long_tsl_line_invalid_fallback(self):
        """tsl_line выше entry для LONG — невалидно, идём в fallback."""
        sl, src = get_entry_sl(
            "LONG", entry=100.0, tsl_line=102.0, fallback_pct=0.015,
        )
        assert sl == pytest.approx(98.5, rel=1e-9)
        assert src == "fallback_pct"

    def test_short_wick_guard_on_close_raw(self):
        """SHORT: tsl_line только чуть выше entry — buffer даёт зазор."""
        sl, src = get_entry_sl("SHORT", entry=100.0, tsl_line=100.5, buffer_pct=0.002)
        assert sl == pytest.approx(100.5 * 1.002, rel=1e-9)
        assert src == "tsl_line"

    def test_short_tsl_line_valid(self):
        sl, src = get_entry_sl("SHORT", entry=100.0, tsl_line=102.0, buffer_pct=0.001)
        assert sl == pytest.approx(102.0 * 1.001, rel=1e-9)
        assert src == "tsl_line"

    def test_short_tsl_line_invalid_fallback(self):
        sl, src = get_entry_sl(
            "SHORT", entry=100.0, tsl_line=98.0, fallback_pct=0.015,
        )
        assert sl == pytest.approx(101.5, rel=1e-9)
        assert src == "fallback_pct"

    def test_no_tsl_line_fallback(self):
        sl, src = get_entry_sl("LONG", entry=100.0, tsl_line=None, fallback_pct=0.02)
        assert sl == 98.0
        assert src == "fallback_pct"
