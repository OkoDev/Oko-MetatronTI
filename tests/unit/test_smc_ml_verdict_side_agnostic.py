"""08.10: ML-вердикт SMC — качество сетапа без стороны (p_win модели), а не направление рынка.

Было: метки STRONG_BULL/BEAR_ZONE сравнивались со стороной сделки, и SHORT при p_win<0.35 получал
+2.5 к силе, а SHORT при p_win>0.65 уходил в теневой блок. Теперь обе стороны судятся одинаково.
"""
from types import SimpleNamespace

from core.intelligence.verdict_aggregator import aggregate_verdicts
from core.ml.mtf_smc_specialist import _label_from_proba


def _v(p):
    return SimpleNamespace(label=_label_from_proba(p, {}), confidence=p)


def test_labels_are_setup_quality():
    assert _label_from_proba(0.80, {}) == "STRONG_SETUP"
    assert _label_from_proba(0.20, {}) == "WEAK_SETUP"
    assert _label_from_proba(0.50, {}) == "NEUTRAL"
    assert _label_from_proba(0.40, {}) == "MIXED"
    assert _label_from_proba(0.60, {}) == "MIXED"


def test_strong_setup_boosts_both_sides():
    for side in ("LONG", "SHORT"):
        g = aggregate_verdicts(side, smc_verdict=_v(0.80))
        assert g.strength_delta == 2.5, side
        assert not g.would_block, side


def test_weak_setup_shadow_both_sides_no_boost():
    for side in ("LONG", "SHORT"):
        g = aggregate_verdicts(side, smc_verdict=_v(0.20))
        assert g.strength_delta == 0.0, side
        assert g.would_block and not g.should_block, side


def test_short_weak_setup_no_longer_boosted():
    # ровно тот случай, что был багом: шорт со СЛАБЫМ сетапом получал +2.5
    g = aggregate_verdicts("SHORT", smc_verdict=_v(0.30))
    assert g.strength_delta <= 0.0


def test_middle_no_effect():
    for p in (0.40, 0.50, 0.60):
        g = aggregate_verdicts("LONG", smc_verdict=_v(p))
        assert g.strength_delta == 0.0 and not g.would_block
