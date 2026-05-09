"""
Тесты для core/wt_15m_reversal_scanner.py и strategies/built_in/reversal_scanner_strategy.py.

Покрывают:
  - scan_wt_15m_reversal: генерация LONG/SHORT сигналов (гейты и очки)
  - ReversalScannerStrategy.analyze: выбор лучшего CONFLUENCE сигнала, SL/TP расчёт
"""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime
from unittest.mock import patch

from core.signals.wt_15m_reversal_scanner import scan_wt_15m_reversal
from core.signals.signal_models import (
    SignalData, SignalType, SignalDirection, MarketContext,
)
from strategies import get_strategy

# Адреса для патчинга (calculate_wt/calculate_trend перезапишут тестовые значения)
_PATCH_WT    = "core.signals.wt_15m_reversal_scanner.calculate_wt"
_PATCH_TREND = "core.signals.wt_15m_reversal_scanner.calculate_trend"


# ─────────────────────────────────────────────────────────────────────────────
# Фабрики тестовых данных
# ─────────────────────────────────────────────────────────────────────────────

def _make_base_df(n: int = 50, close: float = 100.0) -> pd.DataFrame:
    """OHLCV DataFrame с нейтральными индикаторами (wt=0, trend=1)."""
    return pd.DataFrame({
        "time":      list(range(n)),
        "open":      [close] * n,
        "high":      [close * 1.005] * n,
        "low":       [close * 0.995] * n,
        "close":     [close] * n,
        "volume":    [1_000_000.0] * n,
        "wt1":       [0.0] * n,
        "wt2":       [0.0] * n,
        "trend":     [1.0] * n,
        "trendup":   [close * 0.98] * n,
        "trenddown": [close * 1.02] * n,
    })


def _make_long_df_in_zone(n: int = 50, close: float = 100.0) -> pd.DataFrame:
    """
    DataFrame с условиями LONG-сетапа: WT кросс В зоне OS.

    Окно = df.iloc[-9:-1] (строки n-9..n-2, 8 баров).
    Паттерн в window[0→1] (df row n-9 → n-8):
      wt1[0]=-62 (OS) <= wt2[0]=-58, wt1[1]=-55 > wt2[1]=-62
        → WT кросс UP В зоне OS (+25, in_zone=True)
      trend[0]=-1 → trend[1]=1, trenddown[0]=99.0, close[1]=100 > 99
        → TSL кросс UP (+25)
      low[0]=99.80 ≈ S1=99.85 (0.05%): caller передаёт pivot_cache
        → PIVOT_TOUCH (+25) итого score=75
    """
    df = _make_base_df(n, close)
    w0 = n - 9  # window[0]
    w1 = n - 8  # window[1]

    df.loc[w0, "wt1"]      = -62.0
    df.loc[w0, "wt2"]      = -58.0
    df.loc[w0, "trend"]    = -1.0
    df.loc[w0, "trenddown"] = 99.0
    df.loc[w0, "low"]      = 99.80

    df.loc[w1, "wt1"]  = -55.0
    df.loc[w1, "wt2"]  = -62.0
    df.loc[w1, "trend"] = 1.0
    return df


def _make_long_df_out_zone(n: int = 50, close: float = 100.0) -> pd.DataFrame:
    """
    DataFrame с условиями LONG-сетапа: WT кросс ВНЕ зоны OS.

    Окно rows 0..7 (df n-9..n-2), все wt1/wt2 заданы явно чтобы
    избежать ложных кроссов (wt2-default=0 создаёт DOWN-кросс после UP):

      w# | wt1  | wt2  | notes
      0  | -65  | -60  | wt1 в OS (< -60) → wt_was_in_os=True
      1  | -55  | -50  | wt1 < wt2 (pre-cross), TSL=-1
      2  | -45  | -50  | cross UP: wt1[1]<=-50, wt1[2]=-45>wt2[2]=-50 → OUT of zone
                         TSL: trend=-1→1, close=100 > trenddown[1]=99
      3  | -35  | -40  | wt1 > wt2 → нет DOWN-кросса
      4  | -30  | -35  | wt1 > wt2
      5  | -25  | -30  | wt1 > wt2
      6  | -20  | -25  | wt1 > wt2
      7  | -15  | -20  | wt1 > wt2

    Гейты: wt_was_in_os (min=-65<-60) + WT_CROSS_UP + TSL_CROSS_UP
    Score: TSL(25) + WT_CROSS_OUT_ZONE(15) + PIVOT_TOUCH(25) = 65
    Caller передаёт pivot_cache с S1≈low
    """
    df = _make_base_df(n, close)
    b = n - 9  # window[0] = df row n-9

    wt1_vals = [-65, -55, -45, -35, -30, -25, -20, -15]
    wt2_vals = [-60, -50, -50, -40, -35, -30, -25, -20]

    for i, (w1, w2) in enumerate(zip(wt1_vals, wt2_vals)):
        df.loc[b + i, "wt1"] = float(w1)
        df.loc[b + i, "wt2"] = float(w2)

    # TSL кросс UP между window[1] и window[2]
    df.loc[b + 1, "trend"]     = -1.0
    df.loc[b + 1, "trenddown"] = 99.0
    df.loc[b + 2, "trend"]     = 1.0

    # low для pivot touch: window[0] близко к S1=99.85
    df.loc[b + 0, "low"] = 99.80

    return df


def _make_short_df_in_zone(n: int = 50, close: float = 100.0) -> pd.DataFrame:
    """
    DataFrame с условиями SHORT-сетапа: WT кросс В зоне OB.

    window[0→1]:
      wt1[0]=62 (OB) >= wt2[0]=58, wt1[1]=55 < wt2[1]=62
        → WT кросс DOWN В зоне OB (+25, in_zone=True)
      trend[0]=1 → trend[1]=-1, trendup[0]=101, close[1]=100 < 101
        → TSL кросс DOWN (+25)
      high[0]=100.20 ≈ R1=100.15: caller передаёт pivot_cache
        → PIVOT_TOUCH (+25) итого score=75
    """
    df = _make_base_df(n, close)
    w0 = n - 9
    w1 = n - 8

    df.loc[w0, "wt1"]    = 62.0
    df.loc[w0, "wt2"]    = 58.0
    df.loc[w0, "trend"]  = 1.0
    df.loc[w0, "trendup"] = 101.0
    df.loc[w0, "high"]   = 100.20

    df.loc[w1, "wt1"]   = 55.0
    df.loc[w1, "wt2"]   = 62.0
    df.loc[w1, "trend"] = -1.0
    return df


def _confluence_signal(
    direction: SignalDirection = SignalDirection.LONG,
    strength: int = 75,
    symbol: str = "BTC/USDT",
    wt_cross_quality: str = "in_zone",
) -> SignalData:
    """Минимальный CONFLUENCE сигнал для тестов стратегии."""
    return SignalData(
        symbol=symbol,
        signal_type=SignalType.CONFLUENCE,
        direction=direction,
        strength=strength,
        confidence=round(strength / 100.0, 2),
        timestamp=datetime.utcnow(),
        data={
            "factors": ["TSL_CROSS_UP", "WT_CROSS_IN_OS", "PIVOT_TOUCH"],
            "score": strength,
            "wt_cross_quality": wt_cross_quality,
            "current_price": 100.0,
        },
    )


def _ctx(
    close: float = 100.0,
    atr: float = 1.5,
    tsl_trendup: float = None,
    tsl_trenddown: float = None,
) -> MarketContext:
    return MarketContext(
        symbol="BTC/USDT",
        current_price=close,
        volume_24h=5_000_000,
        volume_change_24h=5.0,
        price_change_24h=1.0,
        volatility=10.0,
        atr=atr,
        tsl_trendup=tsl_trendup,
        tsl_trenddown=tsl_trenddown,
    )


# ─────────────────────────────────────────────────────────────────────────────
# scan_wt_15m_reversal
# ─────────────────────────────────────────────────────────────────────────────

class TestScanWt15mReversal:
    """Тесты детектора разворотного сетапа на 15m."""

    def test_returns_empty_on_insufficient_data(self):
        """Меньше 30 строк → нет сигнала."""
        df = _make_base_df(n=20)
        with patch(_PATCH_WT, side_effect=lambda df, **kw: df), \
             patch(_PATCH_TREND, side_effect=lambda df, **kw: df):
            result = scan_wt_15m_reversal("BTC/USDT", df, None, {})
        assert result == []

    def test_returns_empty_on_neutral_data(self):
        """Нейтральные данные — нет зон OS/OB, нет кроссов → нет сигнала."""
        df = _make_base_df(n=50)
        with patch(_PATCH_WT, side_effect=lambda df, **kw: df), \
             patch(_PATCH_TREND, side_effect=lambda df, **kw: df):
            result = scan_wt_15m_reversal("BTC/USDT", df, None, {})
        assert result == []

    def test_returns_empty_when_only_wt_gate_passes(self):
        """wt в OS, но нет WT-кросса и TSL-кросса → нет сигнала."""
        df = _make_base_df(n=50)
        # Только wt1 в OS без кросса
        df.loc[41, "wt1"] = -65.0
        with patch(_PATCH_WT, side_effect=lambda df, **kw: df), \
             patch(_PATCH_TREND, side_effect=lambda df, **kw: df):
            result = scan_wt_15m_reversal("BTC/USDT", df, None, {})
        assert result == []

    # ── LONG ─────────────────────────────────────────────────────────────────

    def test_long_in_zone_with_pivot(self):
        """LONG: WT кросс в OS зоне + TSL кросс + PIVOT_TOUCH → сигнал score=75."""
        df = _make_long_df_in_zone(close=100.0)
        pivot_cache = {"BTC/USDT_1D": {"S1": 99.85, "PP": 101.0, "R1": 102.0}}

        with patch(_PATCH_WT, side_effect=lambda df, **kw: df), \
             patch(_PATCH_TREND, side_effect=lambda df, **kw: df):
            result = scan_wt_15m_reversal("BTC/USDT", df, None, pivot_cache)

        assert len(result) == 1
        sig = result[0]
        assert sig.signal_type == SignalType.CONFLUENCE
        assert sig.direction == SignalDirection.LONG
        assert sig.data["score"] == 75
        assert "TSL_CROSS_UP" in sig.data["factors"]
        assert "WT_CROSS_IN_OS" in sig.data["factors"]
        assert "PIVOT_TOUCH" in sig.data["factors"]
        assert sig.data.get("wt_cross_quality") == "in_zone"

    def test_long_in_zone_no_pivot_score_below_threshold(self):
        """Гейты пройдены, но score=50 < 60 без пивота/дивергенции → нет сигнала."""
        df = _make_long_df_in_zone(close=100.0)

        with patch(_PATCH_WT, side_effect=lambda df, **kw: df), \
             patch(_PATCH_TREND, side_effect=lambda df, **kw: df):
            result = scan_wt_15m_reversal("BTC/USDT", df, None, {})

        assert result == []

    def test_long_out_of_zone_with_pivot(self):
        """LONG: WT кросс ВНЕ зоны OS + TSL кросс + PIVOT_TOUCH → score=65."""
        df = _make_long_df_out_zone(close=100.0)
        pivot_cache = {"BTC/USDT_1D": {"S1": 99.85, "PP": 101.0, "R1": 102.0}}

        with patch(_PATCH_WT, side_effect=lambda df, **kw: df), \
             patch(_PATCH_TREND, side_effect=lambda df, **kw: df):
            result = scan_wt_15m_reversal("BTC/USDT", df, None, pivot_cache)

        assert len(result) == 1
        sig = result[0]
        assert sig.direction == SignalDirection.LONG
        assert sig.data["score"] == 65
        assert sig.data.get("wt_cross_quality") == "out_of_zone"
        assert "WT_CROSS_UP" in sig.data["factors"]   # не WT_CROSS_IN_OS
        assert "TSL_CROSS_UP" in sig.data["factors"]
        assert "PIVOT_TOUCH" in sig.data["factors"]

    # ── SHORT ────────────────────────────────────────────────────────────────

    def test_short_in_zone_with_pivot(self):
        """SHORT: WT кросс в OB зоне + TSL кросс + PIVOT_TOUCH → сигнал score=75."""
        df = _make_short_df_in_zone(close=100.0)
        pivot_cache = {"BTC/USDT_1D": {"R1": 100.15, "PP": 99.0, "S1": 98.0}}

        with patch(_PATCH_WT, side_effect=lambda df, **kw: df), \
             patch(_PATCH_TREND, side_effect=lambda df, **kw: df):
            result = scan_wt_15m_reversal("BTC/USDT", df, None, pivot_cache)

        assert len(result) == 1
        sig = result[0]
        assert sig.signal_type == SignalType.CONFLUENCE
        assert sig.direction == SignalDirection.SHORT
        assert sig.data["score"] == 75
        assert "TSL_CROSS_DOWN" in sig.data["factors"]
        assert "WT_CROSS_IN_OB" in sig.data["factors"]
        assert "PIVOT_TOUCH" in sig.data["factors"]
        assert sig.data.get("wt_cross_quality") == "in_zone"

    # ── Структура сигнала ─────────────────────────────────────────────────────

    def test_signal_required_fields(self):
        """Сигнал содержит все обязательные поля."""
        df = _make_long_df_in_zone(close=100.0)
        pivot_cache = {"BTC/USDT_1D": {"S1": 99.85, "PP": 101.0}}

        with patch(_PATCH_WT, side_effect=lambda df, **kw: df), \
             patch(_PATCH_TREND, side_effect=lambda df, **kw: df):
            result = scan_wt_15m_reversal("BTC/USDT", df, None, pivot_cache)

        assert len(result) == 1
        sig = result[0]
        assert sig.symbol == "BTC/USDT"
        assert sig.strength == sig.data["score"]
        assert sig.confidence == round(sig.data["score"] / 100.0, 2)
        assert sig.data.get("current_price") == 100.0
        assert isinstance(sig.data.get("factors"), list)
        assert len(sig.data["factors"]) > 0

    def test_signal_strength_capped_at_100(self):
        """strength = min(score, 100) — не превышает 100."""
        df = _make_long_df_in_zone(close=100.0)
        # S1 попадает под pivot touch, дивергенция не добавляется → max=75
        pivot_cache = {"BTC/USDT_1D": {"S1": 99.85}}
        with patch(_PATCH_WT, side_effect=lambda df, **kw: df), \
             patch(_PATCH_TREND, side_effect=lambda df, **kw: df):
            result = scan_wt_15m_reversal("BTC/USDT", df, None, pivot_cache)

        assert result[0].strength <= 100


# ─────────────────────────────────────────────────────────────────────────────
# ReversalScannerStrategy
# ─────────────────────────────────────────────────────────────────────────────

class TestReversalScannerStrategy:
    """Тесты стратегии выбора лучшего CONFLUENCE сигнала и расчёта SL/TP."""

    def setup_method(self):
        self.strategy = get_strategy("wt_entry")
        self.ctx = _ctx()

    # ── analyze: выбор сигнала ────────────────────────────────────────────────

    def test_returns_none_on_empty(self):
        assert self.strategy.analyze([], self.ctx) is None

    def test_returns_none_on_non_confluence_signals(self):
        """Сигналы WT/ANOMALY без CONFLUENCE → None."""
        signals = [
            SignalData("BTC/USDT", SignalType.WT_SIGNAL, SignalDirection.LONG,
                       75, 0.8, datetime.utcnow(), {}),
            SignalData("BTC/USDT", SignalType.ANOMALY, SignalDirection.LONG,
                       80, 0.9, datetime.utcnow(), {}),
        ]
        assert self.strategy.analyze(signals, self.ctx) is None

    def test_strength_below_min_returns_none(self):
        """strength=50 < min_strength=60 → отфильтровывается → None."""
        signals = [_confluence_signal(SignalDirection.LONG, strength=50)]
        assert self.strategy.analyze(signals, self.ctx) is None

    def test_long_produces_buy_with_sl_tp(self):
        """CONFLUENCE LONG → BUY с entry, SL < entry, TP > entry."""
        signals = [_confluence_signal(SignalDirection.LONG, strength=75)]
        rec = self.strategy.analyze(signals, self.ctx)

        assert rec is not None
        assert rec.action == "BUY"
        assert rec.entry_price == 100.0
        assert rec.stop_loss < rec.entry_price
        assert rec.take_profit > rec.entry_price
        assert rec.stop_loss is not None
        assert rec.take_profit is not None

    def test_short_produces_sell_with_sl_tp(self):
        """CONFLUENCE SHORT → SELL с SL > entry, TP < entry."""
        signals = [_confluence_signal(SignalDirection.SHORT, strength=70)]
        rec = self.strategy.analyze(signals, self.ctx)

        assert rec is not None
        assert rec.action == "SELL"
        assert rec.stop_loss > rec.entry_price
        assert rec.take_profit < rec.entry_price

    def test_conflict_equal_strength_returns_none(self):
        """LONG==SHORT по силе → конфликт → None."""
        signals = [
            _confluence_signal(SignalDirection.LONG,  strength=75),
            _confluence_signal(SignalDirection.SHORT, strength=75),
        ]
        assert self.strategy.analyze(signals, self.ctx) is None

    def test_conflict_long_wins(self):
        """LONG сильнее SHORT → BUY."""
        signals = [
            _confluence_signal(SignalDirection.LONG,  strength=80),
            _confluence_signal(SignalDirection.SHORT, strength=70),
        ]
        rec = self.strategy.analyze(signals, self.ctx)
        assert rec is not None
        assert rec.action == "BUY"

    def test_conflict_short_wins(self):
        """SHORT сильнее LONG → SELL."""
        signals = [
            _confluence_signal(SignalDirection.LONG,  strength=65),
            _confluence_signal(SignalDirection.SHORT, strength=80),
        ]
        rec = self.strategy.analyze(signals, self.ctx)
        assert rec is not None
        assert rec.action == "SELL"

    # ── SL/TP расчёт ──────────────────────────────────────────────────────────

    def test_sl_uses_tsl_line_when_in_range(self):
        """LONG: tsl_trendup в допустимом диапазоне → SL = trendup × (1 - buffer)."""
        # trendup=97.5, buffer=0.3% → sl=97.207, dist=2.79% ∈ [0.6, 3.0] → TSL
        ctx = _ctx(close=100.0, tsl_trendup=97.5)
        signals = [_confluence_signal(SignalDirection.LONG, strength=75)]
        rec = self.strategy.analyze(signals, ctx)

        assert rec is not None
        assert rec.sl_source == "tsl_line"
        expected_sl = 97.5 * (1 - 0.003)  # buffer_pct=0.3%
        assert abs(rec.stop_loss - expected_sl) < 0.01

    def test_sl_falls_back_to_atr(self):
        """Нет TSL линии → SL от ATR × 1.5."""
        ctx = _ctx(close=100.0, atr=1.5, tsl_trendup=None)
        signals = [_confluence_signal(SignalDirection.LONG, strength=75)]
        rec = self.strategy.analyze(signals, ctx)

        assert rec is not None
        assert rec.sl_source == "atr_14"
        # sl_dist = max(min(1.5*1.5, 3.0), 0.6) = 2.25
        assert abs(rec.stop_loss - (100.0 - 2.25)) < 0.01

    def test_tp_rr_ratio_is_3(self):
        """TP/SL = tp_rr = 3.0."""
        ctx = _ctx(close=100.0, atr=2.0)
        signals = [_confluence_signal(SignalDirection.LONG, strength=75)]
        rec = self.strategy.analyze(signals, ctx)

        assert rec is not None
        sl_dist = rec.entry_price - rec.stop_loss
        tp_dist = rec.take_profit - rec.entry_price
        assert abs(tp_dist / sl_dist - 3.0) < 0.01

    def test_tp1_equals_one_r(self):
        """tp1_price = entry + 1×sl_dist (первая цель = 1R)."""
        ctx = _ctx(close=100.0, atr=2.0)
        signals = [_confluence_signal(SignalDirection.LONG, strength=75)]
        rec = self.strategy.analyze(signals, ctx)

        assert rec is not None
        sl_dist = rec.entry_price - rec.stop_loss
        assert abs(rec.tp1_price - (rec.entry_price + sl_dist)) < 0.01

    def test_short_sl_above_entry(self):
        """SHORT: tsl_trenddown доступна → SL = trenddown × (1 + buffer) > entry."""
        # trenddown=102.5, buffer=0.3% → sl=102.807, dist=2.8% ∈ [0.6, 3.0] → TSL
        ctx = _ctx(close=100.0, tsl_trenddown=102.5)
        signals = [_confluence_signal(SignalDirection.SHORT, strength=75)]
        rec = self.strategy.analyze(signals, ctx)

        assert rec is not None
        assert rec.sl_source == "tsl_line"
        assert rec.stop_loss > rec.entry_price
        expected_sl = 102.5 * (1 + 0.003)
        assert abs(rec.stop_loss - expected_sl) < 0.01

    # ── Дополнительные атрибуты рекомендации ─────────────────────────────────

    def test_recommendation_has_reasoning(self):
        """TradingRecommendation содержит reasoning."""
        signals = [_confluence_signal(SignalDirection.LONG, strength=75)]
        rec = self.strategy.analyze(signals, self.ctx)

        assert rec is not None
        assert isinstance(rec.reasoning, list)
        assert len(rec.reasoning) > 0

    def test_overall_strength_matches_signal(self):
        """overall_strength = strength сигнала-победителя."""
        signals = [_confluence_signal(SignalDirection.LONG, strength=80)]
        rec = self.strategy.analyze(signals, self.ctx)

        assert rec is not None
        assert rec.overall_strength == 80
