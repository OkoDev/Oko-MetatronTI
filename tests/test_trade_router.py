"""
Юнит-тесты для TradeRouter и Gate pipeline.

Запуск:
  python -m pytest tests/test_trade_router.py -v
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from core.trading.gates.base import GateContext, GateType
from core.trading.gates.validate_inputs import ValidateInputsGate
from core.trading.gates.dedup_open import DedupOpenGate
from core.trading.gates.min_sl_dist import MinSlDistGate
from core.trading.gates.rr_filter import RrFilterGate
from core.trading.gates.strength_threshold import StrengthThresholdGate
from core.trading.gates.regime_safety import RegimeSafetyGate
from core.trading.source_policies import SourcePolicy


# ── Helpers ──────────────────────────────────────────────────────────────
def _mk_rec(
    *, symbol="ENA/USDT:USDT", direction="LONG", entry=1.0, sl=0.95, tp=1.15,
    strength=50, signal_type="atr_change",
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        action="BUY" if direction == "LONG" else "SELL",
        direction=SimpleNamespace(value=direction),
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        overall_strength=strength,
        confidence=0.7,
        signal_type=SimpleNamespace(value=signal_type),
    )


class _MockConfig:
    def __init__(self, **kwargs):
        self._d = kwargs

    def get(self, key, default=None):
        parts = key.split(".")
        cur = self._d
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return cur


class _MockBot:
    def __init__(self, **overrides):
        self.config = _MockConfig(**overrides)


def _mk_ctx(
    *, source="atr_change", direction="LONG", strength=50, signal_type="atr_change",
    rec=None, policy=None, regime=None, open_trades=None, bot=None,
) -> GateContext:
    if rec is None:
        rec = _mk_rec(direction=direction, strength=strength, signal_type=signal_type)
    if policy is None:
        policy = SourcePolicy(source=source, min_strength=15, trade_mode="atr_change")
    if bot is None:
        bot = _MockBot()
    return GateContext(
        rec=rec,
        symbol=rec.symbol,
        direction=direction,
        signal_type=signal_type,
        strength=strength,
        source=source,
        extra_features={},
        policy=policy,
        regime=regime,
        open_trades=open_trades or [],
        bot=bot,
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Tests: validate_inputs ───────────────────────────────────────────────
class TestValidateInputs:
    def test_happy_path(self):
        ctx = _mk_ctx()
        res = _run(ValidateInputsGate().check(ctx))
        assert res.passed
        assert res.gate_type == GateType.HARD

    def test_no_entry(self):
        ctx = _mk_ctx(rec=_mk_rec(entry=0))
        res = _run(ValidateInputsGate().check(ctx))
        assert not res.passed
        assert "no entry_price" in res.reason

    def test_neutral_direction(self):
        ctx = _mk_ctx(direction="NEUTRAL")
        res = _run(ValidateInputsGate().check(ctx))
        assert not res.passed
        assert "direction" in res.reason


# ── Tests: dedup_open ─────────────────────────────────────────────────────
class TestDedupOpen:
    def test_no_open_trades(self):
        ctx = _mk_ctx(open_trades=[])
        res = _run(DedupOpenGate().check(ctx))
        assert res.passed

    def test_different_symbol(self):
        ctx = _mk_ctx(open_trades=[
            {"id": 1, "symbol": "BTC/USDT:USDT", "direction": "LONG", "features_json": "{}"}
        ])
        res = _run(DedupOpenGate().check(ctx))
        assert res.passed

    def test_same_mode_blocks(self):
        """atr_change vs atr_change → блок"""
        ctx = _mk_ctx(open_trades=[
            {"id": 5, "symbol": "ENA/USDT:USDT", "direction": "LONG",
             "features_json": json.dumps({"trade_mode": "atr_change"})}
        ])
        res = _run(DedupOpenGate().check(ctx))
        assert not res.passed
        assert "trade_mode=atr_change" in res.reason

    def test_different_mode_passes(self):
        """atr_change vs sideways → bounce_mode допускает"""
        ctx = _mk_ctx(open_trades=[
            {"id": 5, "symbol": "ENA/USDT:USDT", "direction": "LONG",
             "features_json": json.dumps({"trade_mode": "sideways"})}
        ])
        res = _run(DedupOpenGate().check(ctx))
        assert res.passed


# ── Tests: min_sl_dist ────────────────────────────────────────────────────
class TestMinSlDist:
    def test_normal_distance(self):
        ctx = _mk_ctx(rec=_mk_rec(entry=1.0, sl=0.95))   # 5% — ok
        res = _run(MinSlDistGate().check(ctx))
        assert res.passed
        assert res.features["sl_dist_pct"] == pytest.approx(5.0)

    def test_too_close(self):
        ctx = _mk_ctx(rec=_mk_rec(entry=1.0, sl=0.9995))   # 0.05% — fail
        res = _run(MinSlDistGate().check(ctx))
        assert not res.passed
        assert "SL too close" in res.reason


# ── Tests: rr_filter ─────────────────────────────────────────────────────
class TestRrFilter:
    def test_rr_above_min(self):
        ctx = _mk_ctx(rec=_mk_rec(entry=1.0, sl=0.95, tp=1.15))  # RR=3.0
        res = _run(RrFilterGate().check(ctx))
        assert res.passed
        assert res.features["rr"] == pytest.approx(3.0)

    def test_rr_below_min(self):
        ctx = _mk_ctx(rec=_mk_rec(entry=1.0, sl=0.95, tp=1.07))  # RR=1.4
        res = _run(RrFilterGate().check(ctx))
        assert not res.passed
        assert "RR=" in res.reason


# ── Tests: strength_threshold (SOFT) ─────────────────────────────────────
class TestStrengthThreshold:
    def test_above_min(self):
        ctx = _mk_ctx(strength=25)
        ctx.policy = SourcePolicy(source="atr_change", min_strength=15)
        res = _run(StrengthThresholdGate().check(ctx))
        assert res.passed
        assert res.strength_penalty == 0
        assert res.features.get("below_min_strength") is False

    def test_below_min_soft(self):
        ctx = _mk_ctx(strength=10)
        ctx.policy = SourcePolicy(source="atr_change", min_strength=15)
        res = _run(StrengthThresholdGate().check(ctx))
        assert res.passed   # SOFT — не блокирует
        assert res.features.get("below_min_strength") is True


# ── Tests: regime_safety (SOFT) ──────────────────────────────────────────
class TestRegimeSafety:
    def test_no_regime(self):
        ctx = _mk_ctx(regime=None)
        res = _run(RegimeSafetyGate().check(ctx))
        assert res.passed
        assert res.strength_penalty == 0

    def test_wt_signal_short_trend_up(self):
        bot = _MockBot(**{"signal_router": {"penalties": {"regime_safety": {"wt_signal_short_trend_up": 15}}}})
        ctx = _mk_ctx(
            source="monitoring", direction="SHORT", signal_type="wt_signal", regime="TREND_UP",
            bot=bot,
        )
        res = _run(RegimeSafetyGate().check(ctx))
        assert res.passed   # SOFT
        assert res.strength_penalty == 15

    def test_other_combo_no_penalty(self):
        bot = _MockBot()
        ctx = _mk_ctx(
            source="atr_change", direction="LONG", signal_type="atr_change", regime="TREND_UP",
            bot=bot,
        )
        res = _run(RegimeSafetyGate().check(ctx))
        assert res.passed
        assert res.strength_penalty == 0


# ── Tests: SubmitResult shape ────────────────────────────────────────────
class TestSubmitResultShape:
    """Минимальный shape-тест без реального TradeRouter (нужен полный bot)."""
    def test_dataclass_works(self):
        from core.trading.gates.base import SubmitResult
        sr = SubmitResult(
            trade_id=42, exchange_order_id="abc",
            soft_penalties=[("regime_safety", 15, "wt_signal SHORT в TREND_UP")],
            hard_drops=[],
            final_strength=35,
            is_registered=True,
        )
        assert sr.trade_id == 42
        assert sr.is_registered
        assert len(sr.soft_penalties) == 1
