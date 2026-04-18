"""ARCH-91: unit-тесты classify_lost_reason и _extract_past_outcome_line."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from core.trading.post_trade_analyser import PostTradeAnalyser


classify = PostTradeAnalyser.classify_lost_reason


def test_tp_returns_none():
    assert classify("TP", 2.0) is None


def test_expired_is_timeout():
    assert classify("EXPIRED", -0.5) == "TIMEOUT"


def test_sl_gapped():
    assert classify("SL", -2.5) == "SL_GAPPED"
    assert classify("SL", -3.1) == "SL_GAPPED"


def test_tsl_late():
    assert classify("SL", -0.9, max_r_possible=1.5) == "TSL_LATE"
    # TSL_LATE только при status=SL, не TSL
    assert classify("TSL", -0.9, max_r_possible=2.0) != "TSL_LATE"


def test_bad_entry():
    assert classify("SL", -1.0, max_r_possible=0.3, tp1_hit=False) == "BAD_ENTRY"
    assert classify("SL", -0.95, tp1_hit=False) == "BAD_ENTRY"
    # tp1_hit=True → не BAD_ENTRY
    result = classify("SL", -1.0, max_r_possible=0.3, tp1_hit=True)
    assert result == "SL_STANDARD"


def test_sl_standard():
    assert classify("SL", -1.5) == "SL_STANDARD"
    assert classify("SL", -0.5) == "SL_STANDARD"


def test_extract_past_outcome_line_none_if_no_state():
    from core.intelligence.narrative_builder import _extract_past_outcome_line
    assert _extract_past_outcome_line(None) is None


def test_extract_past_outcome_line_fresh():
    from core.intelligence.narrative_builder import _extract_past_outcome_line
    ps = SimpleNamespace(last_narrative_outcome={
        "status": "SL",
        "R": -1.0,
        "lost_reason": "BAD_ENTRY",
        "closed_at": datetime.now(timezone.utc).isoformat(),
    })
    line = _extract_past_outcome_line(ps)
    assert line is not None
    assert "SL" in line
    assert "BAD_ENTRY" in line
    assert "R=-1.0" in line


def test_extract_past_outcome_line_stale():
    from core.intelligence.narrative_builder import _extract_past_outcome_line
    old_time = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    ps = SimpleNamespace(last_narrative_outcome={
        "status": "TP", "R": 2.0, "lost_reason": None, "closed_at": old_time,
    })
    assert _extract_past_outcome_line(ps) is None


def test_extract_past_outcome_line_no_outcome():
    from core.intelligence.narrative_builder import _extract_past_outcome_line
    ps = SimpleNamespace(last_narrative_outcome=None)
    assert _extract_past_outcome_line(ps) is None
