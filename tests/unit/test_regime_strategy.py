"""
Тесты для core/regime_strategy.py (ARCH-04).
"""
import pytest
from core.regime_strategy import (
    get_regime_params,
    apply_regime_to_strategy,
    RegimeParams,
    _STRATEGY_ORDER,
)


# ── get_regime_params ─────────────────────────────────────────────────────────

class TestGetRegimeParams:
    def test_none_regime_returns_fallback(self):
        p = get_regime_params(None)
        assert p.sl_factor == 1.0
        assert p.min_strategy_type is None
        assert p.position_size_multiplier == 1.0

    def test_unknown_regime_returns_fallback(self):
        p = get_regime_params("UNKNOWN_XYZ")
        assert p.sl_factor == 1.0

    def test_trend_up_params(self):
        p = get_regime_params("TREND_UP")
        assert p.sl_factor < 1.0           # тёсный SL
        assert p.min_strategy_type == "TRIPLE_TP_TSL"
        assert p.position_size_multiplier == 1.0

    def test_trend_down_params(self):
        p = get_regime_params("TREND_DOWN")
        assert p.sl_factor < 1.0
        assert p.min_strategy_type == "TRIPLE_TP_TSL"

    def test_range_params(self):
        p = get_regime_params("RANGE")
        assert p.sl_factor > 1.0           # широкий SL
        assert p.max_strategy_type == "DUAL_TP"
        assert p.min_strategy_type is None

    def test_high_vol_params(self):
        p = get_regime_params("HIGH_VOL")
        assert p.position_size_multiplier == 0.5
        assert p.tp1_r is not None and p.tp1_r > 0
        assert p.max_strategy_type == "DUAL_TP"

    def test_disabled_via_cfg(self):
        class FakeCfg:
            def get(self, key, default=None):
                if key == "risk_management.regime_strategy.enabled":
                    return False
                return default
        p = get_regime_params("TREND_UP", cfg=FakeCfg())
        assert p.sl_factor == 1.0          # fallback

    def test_cfg_overrides_trend_sl_factor(self):
        class FakeCfg:
            def get(self, key, default=None):
                mapping = {
                    "risk_management.regime_strategy.enabled": True,
                    "risk_management.regime_strategy.trend_sl_factor": 0.70,
                    "risk_management.regime_strategy.trend_strategy_type": "TRIPLE_TP_TSL",
                    "risk_management.regime_strategy.trend_position_multiplier": 1.0,
                }
                return mapping.get(key, default)
        p = get_regime_params("TREND_UP", cfg=FakeCfg())
        assert p.sl_factor == pytest.approx(0.70)

    def test_cfg_overrides_high_vol_multiplier(self):
        class FakeCfg:
            def get(self, key, default=None):
                mapping = {
                    "risk_management.regime_strategy.enabled": True,
                    "risk_management.regime_strategy.high_vol_sl_factor": 1.0,
                    "risk_management.regime_strategy.high_vol_strategy_type": "DUAL_TP",
                    "risk_management.regime_strategy.high_vol_position_multiplier": 0.3,
                    "risk_management.regime_strategy.high_vol_tp1_r": 0.5,
                }
                return mapping.get(key, default)
        p = get_regime_params("HIGH_VOL", cfg=FakeCfg())
        assert p.position_size_multiplier == pytest.approx(0.3)


# ── apply_regime_to_strategy ──────────────────────────────────────────────────

class TestApplyRegimeToStrategy:
    # Базовые параметры сделки (LONG, entry=100, SL=97, TP=106 → RR=2)
    BASE = dict(entry=100.0, stop_loss=97.0, take_profit=106.0,
                tp1_price=None, direction="LONG")

    def test_no_regime_no_change(self):
        st, tp1 = apply_regime_to_strategy(
            strategy_type="DUAL_TP", regime=None, **self.BASE
        )
        assert st == "DUAL_TP"

    def test_trend_upgrades_single_to_triple(self):
        """TREND_UP должен поднять SINGLE → TRIPLE_TP_TSL (min_strategy_type)."""
        st, tp1 = apply_regime_to_strategy(
            strategy_type="SINGLE", regime="TREND_UP", **self.BASE
        )
        assert st == "TRIPLE_TP_TSL"
        assert tp1 is not None

    def test_trend_upgrades_dual_to_triple(self):
        st, tp1 = apply_regime_to_strategy(
            strategy_type="DUAL_TP", regime="TREND_UP", **self.BASE
        )
        assert st == "TRIPLE_TP_TSL"

    def test_triple_stays_triple_in_trend(self):
        st, _ = apply_regime_to_strategy(
            strategy_type="TRIPLE_TP_TSL", regime="TREND_UP", **self.BASE
        )
        assert st == "TRIPLE_TP_TSL"

    def test_range_downgrades_triple_to_dual(self):
        """RANGE ограничивает максимум на DUAL_TP."""
        st, tp1 = apply_regime_to_strategy(
            strategy_type="TRIPLE_TP_TSL", regime="RANGE", **self.BASE
        )
        assert st == "DUAL_TP"
        assert tp1 is not None

    def test_range_keeps_dual(self):
        st, _ = apply_regime_to_strategy(
            strategy_type="DUAL_TP", regime="RANGE", **self.BASE
        )
        assert st == "DUAL_TP"

    def test_range_keeps_single(self):
        """RANGE не повышает SINGLE — нет min_strategy_type."""
        st, _ = apply_regime_to_strategy(
            strategy_type="SINGLE", regime="RANGE", **self.BASE
        )
        assert st == "SINGLE"

    def test_high_vol_forces_tp1_at_half_r(self):
        """HIGH_VOL форсирует TP1 при 0.5×R от SL-дистанции."""
        st, tp1 = apply_regime_to_strategy(
            strategy_type="DUAL_TP", regime="HIGH_VOL", **self.BASE
        )
        # SL dist = 3.0, tp1 должен быть entry + 0.5×3 = 101.5
        assert tp1 == pytest.approx(101.5, abs=0.01)

    def test_high_vol_limits_to_dual(self):
        st, _ = apply_regime_to_strategy(
            strategy_type="TRIPLE_TP_TSL", regime="HIGH_VOL", **self.BASE
        )
        assert st == "DUAL_TP"

    def test_short_direction_tp1_below_entry(self):
        """SHORT: TP1 должен быть НИЖЕ entry."""
        st, tp1 = apply_regime_to_strategy(
            strategy_type="SINGLE",
            entry=100.0, stop_loss=103.0, take_profit=94.0,
            tp1_price=None, direction="SHORT",
            regime="TREND_DOWN",
        )
        assert st == "TRIPLE_TP_TSL"
        assert tp1 < 100.0   # TP1 ниже entry для SHORT

    def test_tp1_not_overwritten_if_already_set(self):
        """Если tp1_price уже задан, apply не трогает при trend-upgrade."""
        existing_tp1 = 102.0
        st, tp1 = apply_regime_to_strategy(
            strategy_type="DUAL_TP",
            entry=100.0, stop_loss=97.0, take_profit=106.0,
            tp1_price=existing_tp1, direction="LONG",
            regime="TREND_UP",
        )
        # После апгрейда в TRIPLE_TP_TSL tp1 пересчитывается
        assert st == "TRIPLE_TP_TSL"
        # tp1 должен быть ~102 (1/3 × 6 = 2, entry + 2 = 102)
        assert tp1 == pytest.approx(102.0, abs=0.01)

    def test_high_vol_tp1_overrides_existing(self):
        """HIGH_VOL всегда форсирует tp1 независимо от заданного значения."""
        _, tp1 = apply_regime_to_strategy(
            strategy_type="DUAL_TP",
            entry=100.0, stop_loss=97.0, take_profit=106.0,
            tp1_price=105.0,   # хотели TP1 высоко
            direction="LONG",
            regime="HIGH_VOL",
        )
        # HIGH_VOL tp1_r=0.5, SL_dist=3 → tp1=101.5
        assert tp1 == pytest.approx(101.5, abs=0.01)

    def test_strategy_order_coverage(self):
        """Все стратегии в _STRATEGY_ORDER должны корректно обрабатываться."""
        for st in _STRATEGY_ORDER:
            result, _ = apply_regime_to_strategy(
                strategy_type=st,
                entry=100.0, stop_loss=97.0, take_profit=106.0,
                tp1_price=None, direction="LONG",
                regime="RANGE",
            )
            assert result in _STRATEGY_ORDER
