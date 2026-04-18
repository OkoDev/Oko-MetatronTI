"""ARCH-90: NarrativeBuilder читает state.smc_snap → smc_factors + smc_flat.

3 сценария + graceful при smc_snap=None.
"""
from __future__ import annotations

from types import SimpleNamespace

from core.intelligence.narrative_builder import (
    _extract_smc_narrative,
    build_narrative,
    TradingNarrative,
)


def _make_snap(**overrides):
    base = {
        "timestamp": "2026-04-19T12:00:00",
        "tfs_processed": ["15m", "1h", "4h"],
        "nearest_bull_ob": None,
        "nearest_bear_ob": None,
        "bull_fvg_active": [],
        "bear_fvg_active": [],
        "last_bos": None,
        "last_choch": None,
        "swing_high": None,
        "swing_low": None,
        "fib_levels": {},
        "price_in_ote": False,
        "current_retracement": 0.0,
    }
    base.update(overrides)
    return base


def test_smc_snap_none_graceful():
    factors, flat = _extract_smc_narrative(None, "LONG")
    assert factors == []
    assert flat["price_in_ote"] is False
    assert flat["nearest_ob_strength"] is None
    assert flat["current_retracement"] == 0.0
    assert flat["last_bos_direction"] is None


def test_scenario_ote_plus_bos_long():
    snap = _make_snap(
        price_in_ote=True,
        current_retracement=72.5,
        last_bos={"tf": "1h", "direction": "UP", "age_bars": 5},
        nearest_bull_ob={
            "tf": "1h", "top": 0.45, "bottom": 0.44,
            "strength": 78, "distance_pct": -0.85, "age_bars": 12,
        },
    )
    factors, flat = _extract_smc_narrative(snap, "LONG")
    assert any("OTE" in f for f in factors), factors
    assert any("BOS UP" in f and "✓" in f for f in factors), factors
    assert any("bull OB" in f for f in factors), factors
    assert flat["price_in_ote"] is True
    assert flat["nearest_ob_strength"] == 78
    assert flat["current_retracement"] == 72.5
    assert flat["last_bos_direction"] == "UP"


def test_scenario_bull_ob_close_long():
    snap = _make_snap(
        nearest_bull_ob={
            "tf": "1h", "top": 0.5, "bottom": 0.49,
            "strength": 65, "distance_pct": -0.3, "age_bars": 3,
        },
    )
    factors, flat = _extract_smc_narrative(snap, "LONG")
    assert any("bull OB" in f and "strength=65" in f for f in factors), factors
    assert flat["nearest_ob_strength"] == 65
    assert flat["price_in_ote"] is False


def test_scenario_only_fvg_short_mitigated():
    snap = _make_snap(
        bear_fvg_active=[
            {"tf": "1h", "top": 0.5, "bottom": 0.48, "mitigation_pct": 72.0, "age_bars": 8},
            {"tf": "15m", "top": 0.51, "bottom": 0.50, "mitigation_pct": 40.0, "age_bars": 2},
        ],
    )
    factors, flat = _extract_smc_narrative(snap, "SHORT")
    assert any("FVG mitigated 72%" in f for f in factors), factors
    assert flat["nearest_ob_strength"] is None


def test_choch_against_direction_warning():
    snap = _make_snap(
        last_choch={"tf": "4h", "direction": "DOWN", "age_bars": 2},
    )
    factors, _ = _extract_smc_narrative(snap, "LONG")
    assert any("CHoCH DOWN" in f and "против" in f for f in factors), factors


def test_bos_against_direction_marker():
    snap = _make_snap(
        last_bos={"tf": "1h", "direction": "DOWN", "age_bars": 3},
    )
    factors, flat = _extract_smc_narrative(snap, "LONG")
    assert any("BOS DOWN" in f and "⚠" in f for f in factors), factors
    assert flat["last_bos_direction"] == "DOWN"


def test_build_narrative_full_cycle_with_pair_state():
    """Полный цикл: pair_state.smc_snap → TradingNarrative содержит smc_factors/smc_flat."""
    rec = SimpleNamespace(
        action="BUY", direction="LONG",
        overall_strength=65, confidence=0.7,
        metadata={"strategy_name": "pivot_reversal"},
    )
    pair_state = SimpleNamespace(
        regime="TREND_UP",
        reversal_mode="TREND",
        btc_regime=None,
        wt_snap=None,
        pivot_snap=None,
        tick_price=None,
        cascade_count=0,
        avg_r_cascade=0,
        post_tsl_data=None,
        active_divergence=None,
        anomaly_active=False,
        near_pivot=None,
        tsl_active=False,
        smc_snap={
            "price_in_ote": True,
            "current_retracement": 68.0,
            "last_bos": {"tf": "1h", "direction": "UP", "age_bars": 4},
            "nearest_bull_ob": {
                "tf": "1h", "top": 0.5, "bottom": 0.49,
                "strength": 80, "distance_pct": -1.2, "age_bars": 6,
            },
            "nearest_bear_ob": None,
            "bull_fvg_active": [],
            "bear_fvg_active": [],
            "last_choch": None,
            "swing_high": None,
            "swing_low": None,
            "fib_levels": {},
            "tfs_processed": ["1h"],
            "timestamp": "2026-04-19T12:00:00",
        },
    )
    narr = build_narrative(
        symbol="BTC/USDT:USDT",
        recommendation=rec,
        pair_state=pair_state,
        wt_verdict=None,
        smc_verdict=None,
        reversal_mode="TREND",
    )
    assert isinstance(narr, TradingNarrative)
    assert len(narr.smc_factors) >= 2
    assert narr.smc_flat["price_in_ote"] is True
    assert narr.smc_flat["nearest_ob_strength"] == 80
    assert narr.smc_flat["last_bos_direction"] == "UP"


def test_outcome_predictor_vector_length_27():
    """ARCH-90: _build_feature_vector возвращает 27 элементов."""
    from core.ml.outcome_predictor import _build_feature_vector

    features = {
        "volatility": 1.5,
        "price_change_24h": 2.0,
        "distance_to_sl_pct": 1.2,
        "sl_atr_ratio": 1.8,
        "nearest_ob_strength": 75,
        "price_in_ote": 1,
        "current_retracement": 70.0,
        "last_bos_direction": "UP",
    }
    v = _build_feature_vector(
        signal_type="pivot_reversal",
        direction="LONG",
        strength=70,
        confidence=0.7,
        features_dict=features,
        regime="TREND_UP",
    )
    assert len(v) == 27, f"expected 27 features, got {len(v)}"
    # SMC 24-27: ob_strength=0.75, price_in_ote=1.0, retrace=0.70, bos_aligned=1.0
    assert v[23] == 0.75
    assert v[24] == 1.0
    assert abs(v[25] - 0.70) < 1e-6
    assert v[26] == 1.0


def test_outcome_predictor_vector_length_27_no_smc():
    """Без SMC данных — vector всё равно 27 элементов, SMC-часть = 0.0."""
    from core.ml.outcome_predictor import _build_feature_vector

    v = _build_feature_vector(
        signal_type="wt_signal",
        direction="SHORT",
        strength=60,
        confidence=0.55,
        features_dict={},
        regime="RANGE",
    )
    assert len(v) == 27
    assert v[23] == 0.0  # nearest_ob_strength
    assert v[24] == 0.0  # price_in_ote
    assert v[25] == 0.0  # current_retracement
    assert v[26] == 0.0  # bos_aligned


if __name__ == "__main__":
    import sys
    import traceback

    tests = [
        test_smc_snap_none_graceful,
        test_scenario_ote_plus_bos_long,
        test_scenario_bull_ob_close_long,
        test_scenario_only_fvg_short_mitigated,
        test_choch_against_direction_warning,
        test_bos_against_direction_marker,
        test_build_narrative_full_cycle_with_pair_state,
        test_outcome_predictor_vector_length_27,
        test_outcome_predictor_vector_length_27_no_smc,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} PASS")
    sys.exit(0 if failed == 0 else 1)
