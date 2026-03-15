"""
Regression-тест ARCH-05: Strategy Pattern интеграция в TradingIntelligence.

Проверяет:
1. Все стратегии регистрируются и загружаются из реестра
2. Каждая стратегия реализует BaseStrategy (analyze / calculate_sl_tp)
3. TradingIntelligence загружает стратегии из конфига (active_strategy / active_strategies)
4. _run_strategy() делегирует в стратегию и возвращает TradingRecommendation
5. _run_all_strategies() запускает несколько стратегий параллельно
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from core.signal_models import (
    MarketContext,
    SignalData,
    SignalDirection,
    SignalType,
    TradingRecommendation,
)
from strategies import BaseStrategy, get_strategy, list_strategies


# ── helpers ───────────────────────────────────────────────────────────────────


def _ctx(**kw) -> MarketContext:
    base = dict(
        symbol="BTC/USDT",
        current_price=45_000.0,
        volume_24h=5_000_000_000,
        volume_change_24h=10.0,
        price_change_24h=2.5,
        volatility=15.0,
        atr=450.0,
    )
    base.update(kw)
    return MarketContext(**base)


def _sig(sig_type, direction, strength=70, conf=0.80) -> SignalData:
    return SignalData(
        symbol="BTC/USDT",
        signal_type=sig_type,
        direction=direction,
        strength=strength,
        confidence=conf,
        timestamp=datetime.utcnow(),
        data={},
    )


class _FakeCfg:
    """ConfigLoader-like: поддерживает dot-нотацию."""

    _data = {
        "strategy_name": "confluence",
        "trading": {
            "active_strategy": "confluence_scanner",
            "active_strategies": ["confluence_scanner", "confluence"],
            "strategies": {
                "confluence_scanner": {"min_strength": 60},
                "confluence": {"min_signals": 2},
            },
        },
    }

    def get(self, key, default=None):
        keys = key.split(".")
        v = self._data
        try:
            for k in keys:
                v = v[k]
            return v
        except (KeyError, TypeError):
            return default


class _MockCollector:
    async def get_ohlcv(self, *a, **kw):
        return None

    async def get_ticker(self, *a, **kw):
        return None


# ── реестр стратегий ──────────────────────────────────────────────────────────


class TestStrategyRegistry:
    def test_all_built_in_strategies_registered(self):
        strats = list_strategies()
        for expected in ("confluence", "confluence_scanner", "conservative", "mtf_bias", "pivot_reversal"):
            assert expected in strats, f"{expected!r} отсутствует в реестре"

    def test_get_strategy_returns_base_strategy(self):
        for name in list_strategies():
            s = get_strategy(name)
            assert isinstance(s, BaseStrategy)

    def test_get_strategy_unknown_raises(self):
        with pytest.raises(ValueError):
            get_strategy("non_existent_strategy_xyz")


# ── ConfluenceStrategy ────────────────────────────────────────────────────────


class TestConfluenceStrategy:
    ctx = _ctx()

    def test_empty_signals_returns_none(self):
        s = get_strategy("confluence")
        assert s.analyze([], self.ctx) is None

    def test_single_signal_returns_none(self):
        s = get_strategy("confluence")
        sigs = [_sig(SignalType.MTF_SIGNAL, SignalDirection.LONG)]
        assert s.analyze(sigs, self.ctx) is None

    def test_two_long_signals_returns_buy(self):
        s = get_strategy("confluence")
        sigs = [
            _sig(SignalType.MTF_SIGNAL, SignalDirection.LONG, 70, 0.8),
            _sig(SignalType.WT_SIGNAL,  SignalDirection.LONG, 60, 0.75),
        ]
        rec = s.analyze(sigs, self.ctx)
        assert rec is not None
        assert rec.action == "BUY"
        assert rec.direction == SignalDirection.LONG

    def test_two_short_signals_returns_sell(self):
        s = get_strategy("confluence")
        sigs = [
            _sig(SignalType.MTF_SIGNAL, SignalDirection.SHORT, 72, 0.8),
            _sig(SignalType.WT_SIGNAL,  SignalDirection.SHORT, 65, 0.75),
        ]
        rec = s.analyze(sigs, self.ctx)
        assert rec is not None
        assert rec.action == "SELL"

    def test_conflicting_signals_returns_none(self):
        s = get_strategy("confluence")
        sigs = [
            _sig(SignalType.MTF_SIGNAL, SignalDirection.LONG,  50, 0.8),
            _sig(SignalType.WT_SIGNAL,  SignalDirection.SHORT, 48, 0.8),
        ]
        assert s.analyze(sigs, self.ctx) is None

    def test_calculate_sl_tp_long(self):
        s = get_strategy("confluence")
        sl, tp, size = s.calculate_sl_tp(45_000.0, "LONG", 450.0, self.ctx)
        assert sl < 45_000.0
        assert tp > 45_000.0
        assert size > 0

    def test_calculate_sl_tp_short(self):
        s = get_strategy("confluence")
        sl, tp, size = s.calculate_sl_tp(45_000.0, "SHORT", 450.0, self.ctx)
        assert sl > 45_000.0
        assert tp < 45_000.0
        assert size > 0


# ── ConservativeStrategy ──────────────────────────────────────────────────────


class TestConservativeStrategy:
    ctx_low_vol = _ctx(volatility=5.0)

    def test_two_signals_insufficient(self):
        s = get_strategy("conservative")
        sigs = [
            _sig(SignalType.MTF_SIGNAL, SignalDirection.LONG, 75, 0.9),
            _sig(SignalType.WT_SIGNAL,  SignalDirection.LONG, 70, 0.85),
        ]
        assert s.analyze(sigs, self.ctx_low_vol) is None

    def test_three_strong_signals_returns_buy(self):
        s = get_strategy("conservative")
        sigs = [
            _sig(SignalType.MTF_SIGNAL, SignalDirection.LONG, 75, 0.9),
            _sig(SignalType.WT_SIGNAL,  SignalDirection.LONG, 70, 0.85),
            _sig(SignalType.DIVERGENCE, SignalDirection.LONG, 75, 0.88),
        ]
        rec = s.analyze(sigs, self.ctx_low_vol)
        assert rec is not None
        assert rec.action == "BUY"


# ── MTFBiasStrategy ───────────────────────────────────────────────────────────


class TestMTFBiasStrategy:
    ctx = _ctx()

    def test_non_mtf_signals_returns_none(self):
        s = get_strategy("mtf_bias")
        sigs = [_sig(SignalType.ANOMALY, SignalDirection.LONG, 70, 0.8)]
        assert s.analyze(sigs, self.ctx) is None

    def test_mtf_bias_signal_returns_buy(self):
        s = get_strategy("mtf_bias")
        sigs = [_sig(SignalType.MTF_BIAS, SignalDirection.LONG, 70, 0.8)]
        rec = s.analyze(sigs, self.ctx)
        assert rec is not None
        assert rec.action == "BUY"


# ── ConfluenceScannerStrategy ─────────────────────────────────────────────────


class TestConfluenceScannerStrategy:
    ctx = _ctx()

    def test_no_confluence_signal_returns_none(self):
        s = get_strategy("confluence_scanner")
        sigs = [_sig(SignalType.MTF_SIGNAL, SignalDirection.LONG, 70, 0.8)]
        assert s.analyze(sigs, self.ctx) is None

    def test_confluence_long_signal_returns_buy(self):
        s = get_strategy("confluence_scanner")
        sigs = [_sig(SignalType.CONFLUENCE, SignalDirection.LONG, 75, 0.85)]
        rec = s.analyze(sigs, self.ctx)
        assert rec is not None
        assert rec.action == "BUY"
        assert rec.stop_loss < 45_000.0
        assert rec.take_profit > 45_000.0

    def test_confluence_below_min_strength_returns_none(self):
        s = get_strategy("confluence_scanner", {"min_strength": 80})
        sigs = [_sig(SignalType.CONFLUENCE, SignalDirection.LONG, 70, 0.85)]
        assert s.analyze(sigs, self.ctx) is None


# ── TradingIntelligence интеграция ────────────────────────────────────────────


class TestTradingIntelligenceStrategyPattern:
    """Регрессия ARCH-05: TI загружает стратегии и делегирует analyze."""

    def _make_ti(self):
        from core.trading_intelligence import TradingIntelligence
        return TradingIntelligence(
            _MockCollector(), config=_FakeCfg(), db_path="/tmp/test_arch05_ti.db"
        )

    def test_self_strategy_is_not_none(self):
        ti = self._make_ti()
        assert ti.strategy is not None

    def test_active_strategy_name(self):
        ti = self._make_ti()
        assert ti.active_strategy_name == "confluence_scanner"

    def test_strategies_dict_contains_active_strategies(self):
        ti = self._make_ti()
        assert "confluence_scanner" in ti.strategies
        assert "confluence" in ti.strategies

    def test_run_strategy_returns_recommendation(self):
        ti = self._make_ti()
        ctx = _ctx()
        conf_sig = [_sig(SignalType.CONFLUENCE, SignalDirection.LONG, 75, 0.85)]
        rec = asyncio.get_event_loop().run_until_complete(
            ti._run_strategy("BTC/USDT", conf_sig, ctx)
        )
        assert rec is not None
        assert rec.action == "BUY"

    def test_run_all_strategies_returns_dict(self):
        ti = self._make_ti()
        ctx = _ctx()
        conf_sig = [_sig(SignalType.CONFLUENCE, SignalDirection.LONG, 75, 0.85)]
        all_recs = asyncio.get_event_loop().run_until_complete(
            ti._run_all_strategies("BTC/USDT", conf_sig, ctx)
        )
        # confluence_scanner должна выдать результат (есть CONFLUENCE-сигнал)
        assert "confluence_scanner" in all_recs
        assert all_recs["confluence_scanner"].action == "BUY"

    def test_run_strategy_returns_none_on_no_signal(self):
        ti = self._make_ti()
        ctx = _ctx()
        # MTF_SIGNAL — не CONFLUENCE, confluence_scanner вернёт None
        non_conf_sigs = [_sig(SignalType.MTF_SIGNAL, SignalDirection.LONG, 70, 0.8)]
        rec = asyncio.get_event_loop().run_until_complete(
            ti._run_strategy("BTC/USDT", non_conf_sigs, ctx)
        )
        assert rec is None
