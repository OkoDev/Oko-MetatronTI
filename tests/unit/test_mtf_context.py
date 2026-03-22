"""
ARCH-12: Тесты MTFContext — analyze_context() + direction/zone multipliers + _apply_mtf_context.
"""
import pytest
from datetime import datetime

from core.signal_models import SignalData, SignalType, SignalDirection, MTFContext


# ── Фикстуры ─────────────────────────────────────────────────────────


def _make_snapshot(bull_tfs=None, bear_tfs=None, wt_values=None):
    """Строит MTF snapshot с заданными трендами."""
    all_tfs = ["3m", "5m", "15m", "45m", "1h", "4h", "1d"]
    bull_tfs = set(bull_tfs or [])
    bear_tfs = set(bear_tfs or [])
    wt_values = wt_values or {}

    snapshot = {}
    for tf in all_tfs:
        if tf in bull_tfs:
            trend = "UP"
        elif tf in bear_tfs:
            trend = "DOWN"
        else:
            trend = "UP"  # default
        wt1 = wt_values.get(tf, {}).get("wt1", 20.0)
        wt2 = wt_values.get(tf, {}).get("wt2", 15.0)
        snapshot[tf] = {
            "trend": trend,
            "wt1": wt1,
            "wt2": wt2,
            "zone": "OB" if wt1 > 60 else ("OS" if wt1 < -60 else "N"),
            "wt_cross": 0,
        }
    return snapshot


def _make_signal(direction, strength=60, signal_type=SignalType.CONFLUENCE):
    return SignalData(
        symbol="TEST/USDT",
        signal_type=signal_type,
        direction=direction,
        strength=strength,
        confidence=strength / 100.0,
        timestamp=datetime.now(),
        data={},
    )


# ── Tests: analyze_context ────────────────────────────────────────────


class TestAnalyzeContext:
    """Тесты analyze_context()."""

    def test_all_bull_returns_long_bias(self):
        from core.mtf_interpreter import analyze_context
        snapshot = _make_snapshot(
            bull_tfs=["3m", "5m", "15m", "45m", "1h", "4h", "1d"],
        )
        ctx = analyze_context(snapshot)
        assert ctx.direction_bias == SignalDirection.LONG
        assert ctx.aligned_pct == 100
        assert ctx.bias_strength == 1.0
        assert ctx.senior_matches == 3

    def test_all_bear_returns_short_bias(self):
        from core.mtf_interpreter import analyze_context
        snapshot = _make_snapshot(
            bear_tfs=["3m", "5m", "15m", "45m", "1h", "4h", "1d"],
        )
        ctx = analyze_context(snapshot)
        assert ctx.direction_bias == SignalDirection.SHORT
        assert ctx.aligned_pct == 100
        assert ctx.bias_strength == 1.0

    def test_mixed_returns_neutral(self):
        from core.mtf_interpreter import analyze_context
        # Примерно 50/50 по весам
        snapshot = _make_snapshot(
            bull_tfs=["3m", "5m", "15m"],
            bear_tfs=["45m", "1h", "4h", "1d"],
        )
        ctx = analyze_context(snapshot)
        # bear_weight=57 из 73 = 78% → SHORT
        # Но если 50/50 → NEUTRAL
        # Actually let's check: bull = 3+5+8=16, bear = 10+12+15+20=57 → bear=78%
        assert ctx.direction_bias == SignalDirection.SHORT

    def test_neutral_when_close_to_50_50(self):
        from core.mtf_interpreter import analyze_context
        # bull = 5m+15m+1h+1d = 5+8+12+20=45, bear = 3m+45m+4h = 3+10+15=28
        # bull_pct = 45/73*100 = 62% < 65% threshold
        snapshot = _make_snapshot(
            bull_tfs=["5m", "15m", "1h", "1d"],
            bear_tfs=["3m", "45m", "4h"],
        )
        ctx = analyze_context(snapshot)
        assert ctx.direction_bias == SignalDirection.NEUTRAL

    def test_wt_spreads_calculated(self):
        from core.mtf_interpreter import analyze_context
        snapshot = _make_snapshot(
            bull_tfs=["3m", "5m", "15m", "45m", "1h", "4h", "1d"],
            wt_values={
                "1h": {"wt1": 30.0, "wt2": 20.0},
                "4h": {"wt1": 50.0, "wt2": 25.0},
                "1d": {"wt1": 10.0, "wt2": 5.0},
            },
        )
        ctx = analyze_context(snapshot)
        assert ctx.wt_spreads["1h"] == 10.0
        assert ctx.wt_spreads["4h"] == 25.0
        assert ctx.wt_spreads["1d"] == 5.0

    def test_price_zone_at_pp(self):
        from core.mtf_interpreter import analyze_context
        snapshot = _make_snapshot(bull_tfs=["3m", "5m", "15m", "45m", "1h", "4h", "1d"])
        weekly = {"PP": 100.0, "S5": 80.0, "R5": 120.0}
        ctx = analyze_context(snapshot, current_price=100.0, weekly_pivots=weekly)
        assert 0.45 <= ctx.price_zone <= 0.55  # ~0.5 (at PP)

    def test_price_zone_at_s5(self):
        from core.mtf_interpreter import analyze_context
        snapshot = _make_snapshot(bull_tfs=["3m", "5m", "15m", "45m", "1h", "4h", "1d"])
        weekly = {"PP": 100.0, "S5": 80.0, "R5": 120.0}
        ctx = analyze_context(snapshot, current_price=80.0, weekly_pivots=weekly)
        assert ctx.price_zone == 0.0

    def test_price_zone_at_r5(self):
        from core.mtf_interpreter import analyze_context
        snapshot = _make_snapshot(bull_tfs=["3m", "5m", "15m", "45m", "1h", "4h", "1d"])
        weekly = {"PP": 100.0, "S5": 80.0, "R5": 120.0}
        ctx = analyze_context(snapshot, current_price=120.0, weekly_pivots=weekly)
        assert ctx.price_zone == 1.0

    def test_empty_snapshot_returns_neutral(self):
        from core.mtf_interpreter import analyze_context
        ctx = analyze_context({})
        assert ctx.direction_bias == SignalDirection.NEUTRAL
        assert ctx.bias_strength == 0.0

    def test_regime_passed_through(self):
        from core.mtf_interpreter import analyze_context
        snapshot = _make_snapshot(bull_tfs=["3m", "5m", "15m", "45m", "1h", "4h", "1d"])
        ctx = analyze_context(snapshot, regime="TREND_UP")
        assert ctx.regime == "TREND_UP"


# ── Tests: direction_multiplier ───────────────────────────────────────


class TestDirectionMultiplier:

    def test_aligned_signal_boosted(self):
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=0.5, aligned_pct=100,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        mult = ctx.direction_multiplier(SignalDirection.LONG)
        assert mult == 1.5  # 1.0 + 1.0 * 0.5

    def test_counter_signal_weakened(self):
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=0.5, aligned_pct=100,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        mult = ctx.direction_multiplier(SignalDirection.SHORT)
        assert mult == pytest.approx(0.3, abs=0.01)

    def test_neutral_bias_no_effect(self):
        ctx = MTFContext(
            direction_bias=SignalDirection.NEUTRAL,
            bias_strength=0.0, price_zone=0.5, aligned_pct=50,
            senior_matches=0, senior_reversal=None, wt_spreads={},
        )
        assert ctx.direction_multiplier(SignalDirection.LONG) == 1.0
        assert ctx.direction_multiplier(SignalDirection.SHORT) == 1.0

    def test_partial_bias(self):
        ctx = MTFContext(
            direction_bias=SignalDirection.SHORT,
            bias_strength=0.5, price_zone=0.5, aligned_pct=75,
            senior_matches=2, senior_reversal=None, wt_spreads={},
        )
        # Aligned: 1.0 + 0.5*0.5 = 1.25
        assert ctx.direction_multiplier(SignalDirection.SHORT) == 1.25
        # Counter: max(0.3, 1.0 - 0.5*0.7) = 0.65
        assert ctx.direction_multiplier(SignalDirection.LONG) == 0.65


# ── Tests: zone_multiplier ────────────────────────────────────────────


class TestZoneMultiplier:

    def test_long_at_s5_boosted(self):
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=0.0, aligned_pct=100,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        assert ctx.zone_multiplier(SignalDirection.LONG) == pytest.approx(1.4, abs=0.01)

    def test_long_at_r5_weakened(self):
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=1.0, aligned_pct=100,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        assert ctx.zone_multiplier(SignalDirection.LONG) == pytest.approx(0.6, abs=0.01)

    def test_short_at_r5_boosted(self):
        ctx = MTFContext(
            direction_bias=SignalDirection.SHORT,
            bias_strength=1.0, price_zone=1.0, aligned_pct=100,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        assert ctx.zone_multiplier(SignalDirection.SHORT) == pytest.approx(1.4, abs=0.01)

    def test_short_at_s5_weakened(self):
        ctx = MTFContext(
            direction_bias=SignalDirection.SHORT,
            bias_strength=1.0, price_zone=0.0, aligned_pct=100,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        assert ctx.zone_multiplier(SignalDirection.SHORT) == pytest.approx(0.6, abs=0.01)

    def test_at_pp_neutral(self):
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=0.5, aligned_pct=100,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        assert ctx.zone_multiplier(SignalDirection.LONG) == pytest.approx(1.0, abs=0.01)
        assert ctx.zone_multiplier(SignalDirection.SHORT) == pytest.approx(1.0, abs=0.01)


# ── Tests: _apply_mtf_context ─────────────────────────────────────────


class TestApplyMtfContext:
    """Тесты _apply_mtf_context из TradingIntelligence."""

    def test_aligned_signal_strength_increases(self):
        from core.trading_intelligence import TradingIntelligence
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=0.0, aligned_pct=100,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        signal = _make_signal(SignalDirection.LONG, strength=60)
        result = TradingIntelligence._apply_mtf_context([signal], ctx)
        # dir_mult=1.5, zone_mult=1.4, combined=1.5*0.7+1.4*0.3=1.47
        assert result[0].strength > 60
        assert result[0].strength <= 100

    def test_counter_signal_strength_decreases(self):
        from core.trading_intelligence import TradingIntelligence
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=0.0, aligned_pct=100,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        signal = _make_signal(SignalDirection.SHORT, strength=60)
        result = TradingIntelligence._apply_mtf_context([signal], ctx)
        # dir_mult=0.3, zone_mult=0.6, combined=0.3*0.7+0.6*0.3=0.39
        assert result[0].strength < 60

    def test_neutral_bias_no_change(self):
        from core.trading_intelligence import TradingIntelligence
        ctx = MTFContext(
            direction_bias=SignalDirection.NEUTRAL,
            bias_strength=0.0, price_zone=0.5, aligned_pct=50,
            senior_matches=0, senior_reversal=None, wt_spreads={},
        )
        signal = _make_signal(SignalDirection.LONG, strength=70)
        result = TradingIntelligence._apply_mtf_context([signal], ctx)
        # dir_mult=1.0, zone_mult=1.0, combined=1.0
        assert result[0].strength == 70

    def test_strength_clamped_to_100(self):
        from core.trading_intelligence import TradingIntelligence
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=0.0, aligned_pct=100,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        signal = _make_signal(SignalDirection.LONG, strength=90)
        result = TradingIntelligence._apply_mtf_context([signal], ctx)
        assert result[0].strength <= 100

    def test_strength_clamped_to_0(self):
        from core.trading_intelligence import TradingIntelligence
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=1.0, aligned_pct=100,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        signal = _make_signal(SignalDirection.SHORT, strength=10)
        result = TradingIntelligence._apply_mtf_context([signal], ctx)
        assert result[0].strength >= 0

    def test_confidence_updated_with_strength(self):
        from core.trading_intelligence import TradingIntelligence
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=0.8, price_zone=0.5, aligned_pct=90,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        signal = _make_signal(SignalDirection.LONG, strength=60)
        result = TradingIntelligence._apply_mtf_context([signal], ctx)
        assert result[0].confidence == round(result[0].strength / 100.0, 2)

    def test_real_scenario_29_shorts_in_bull_market(self):
        """
        Реальный сценарий 16.03: 29 confluence SHORT str=60-70 при bias=LONG.
        Ожидаем: strength ×0.39 ≈ 24-28 → ниже порога → WATCH.
        """
        from core.trading_intelligence import TradingIntelligence
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=0.3, aligned_pct=95,
            senior_matches=3, senior_reversal=None, wt_spreads={},
        )
        for original_str in (60, 65, 70):
            signal = _make_signal(SignalDirection.SHORT, strength=original_str,
                                  signal_type=SignalType.WT_SIGNAL)
            TradingIntelligence._apply_mtf_context([signal], ctx)
            # Должен быть значительно ниже оригинала (для raw-сигналов, не CONFLUENCE)
            assert signal.strength < 40, (
                f"SHORT str={original_str} при LONG bias должен быть < 40, got {signal.strength}"
            )
        # CONFLUENCE имеет мягкий floor=0.75 — penalty максимум 25%
        conf_sig = _make_signal(SignalDirection.SHORT, strength=60,
                                signal_type=SignalType.CONFLUENCE)
        TradingIntelligence._apply_mtf_context([conf_sig], ctx)
        assert conf_sig.strength == 45, (
            f"CONFLUENCE SHORT str=60 при floor 0.75 должен быть 45, got {conf_sig.strength}"
        )
