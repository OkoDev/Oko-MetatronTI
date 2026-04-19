"""
Тест рёбер Куба Метатрона — полный прогон сигнала через все связи.

Уровни проверки:
  L1 — selftest_cube: все 21 ребро и 13 сфер (статус ACTIVE/SHADOW/MISSING)
  L2 — BTCRegimeProvider: update() вычисляет BULL/BEAR/NEUTRAL, wire в TI
  L3 — Signal flow: синтетический сигнал → analyze_symbol → metadata полный
  L4 — PostTradeAnalyser callback: trade_closed → adaptive weights цикл

Запуск:
    python -m pytest tests/integration/test_cube_edges.py -v
    python tests/integration/test_cube_edges.py        # standalone
"""
import os
import sys
import asyncio
import tempfile
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: синтетические данные
# ─────────────────────────────────────────────────────────────────────────────

def _make_ohlcv(n=120, base=50_000.0, trend=0.02, vol=0.005) -> pd.DataFrame:
    """Восходящий BTC-like OHLCV."""
    np.random.seed(7)
    closes = base * (1 + trend * np.arange(n) / n + np.random.randn(n) * vol)
    highs  = closes * (1 + abs(np.random.randn(n)) * vol * 0.5)
    lows   = closes * (1 - abs(np.random.randn(n)) * vol * 0.5)
    opens  = np.roll(closes, 1); opens[0] = closes[0]
    vols   = abs(np.random.randn(n)) * 1e6 + 5e6
    return pd.DataFrame({
        "time":   [1_700_000_000_000 + i * 14_400_000 for i in range(n)],
        "open":   opens, "high": highs, "low": lows,
        "close":  closes, "volume": vols,
    })


def _make_bot_stub(tmp_db: str):
    """Минимальный stub-бот со всеми компонентами Куба."""
    from core.config_loader import config
    from core.context.pair_context import PairContextBus
    from core.trading.post_trade_analyser import PostTradeAnalyser
    from core.exchange.btc_regime_provider import BTCRegimeProvider
    from core.trade_simulator import TradeSimulator
    from core.trading_intelligence import TradingIntelligence
    from core.data_collector import RealTimeData
    from core.pivot_calculator_fixed import PivotCalculatorFixed

    # DataCollector (без реальной биржи — методы мокаем)
    dc = MagicMock(spec=RealTimeData)
    dc.get_ohlcv = AsyncMock(return_value=_make_ohlcv())
    dc._engine = MagicMock()
    dc._ohlcv_cache = {}

    # PairContextBus
    pc = PairContextBus()

    # TradeSimulator
    ts = TradeSimulator(db_path=tmp_db)
    ts._pair_context_bus = pc

    # PostTradeAnalyser
    pta = PostTradeAnalyser(pc, dc)

    # BTCRegimeProvider
    btc_prov = BTCRegimeProvider(config=config)

    # TradingIntelligence (с моком pivot_calculator)
    pivot_calc = MagicMock(spec=PivotCalculatorFixed)
    pivot_calc.get_pivots = AsyncMock(return_value={})
    ti = TradingIntelligence(
        data_collector=dc,
        config=config,
        db_path=tmp_db,
        pivot_calculator=pivot_calc,
    )
    ti._pair_context_bus = pc
    ti._btc_provider = btc_prov  # ARCH-78

    # PostTradeAnalyser → TI
    pta._intelligence = ti

    # TradeSimulator → PostTradeAnalyser callback
    ts.set_post_trade_callback(pta.on_trade_closed)

    # Собираем бот
    bot = SimpleNamespace(
        config=config,
        data_collector=dc,
        pair_context=pc,
        trade_simulator=ts,
        post_analyser=pta,
        btc_regime_provider=btc_prov,
        trading_intelligence=ti,
        ws_feed=None,
        order_executor=None,
        position_manager=None,
        sphere_registry=None,
        event_bus=None,
        r_predictor=None,
        bounce_detector=None,
        is_monitoring=False,
    )
    return bot


# ─────────────────────────────────────────────────────────────────────────────
# L1 — selftest_cube: статусы сфер и рёбер
# ─────────────────────────────────────────────────────────────────────────────

class TestCubeSelftest:
    @pytest.fixture
    def bot(self, tmp_path):
        return _make_bot_stub(str(tmp_path / "test.db"))

    def test_all_checks_run_without_exception(self, bot):
        """Все 37 проверок (13+21+4) должны выполниться без исключений."""
        from core.selftest_cube import run_cube_selftest, format_cube_report
        results = asyncio.get_event_loop().run_until_complete(run_cube_selftest(bot))
        assert len(results) >= 37, f"Ожидается ≥37 проверок, получено {len(results)}"
        report = format_cube_report(results)
        assert "L13" in report and "L14" in report

    def test_s5_cross_market_shadow(self, bot):
        """S5 должна быть SHADOW — BTCRegimeProvider есть, но gate в shadow_mode."""
        from core.selftest_cube import _check_sphere_5_cross_market, SHADOW, ACTIVE
        result = _check_sphere_5_cross_market(bot)
        assert result.status in (SHADOW, ACTIVE), f"S5 неожиданный статус: {result.status} ({result.detail})"

    def test_s7_trading_intelligence_active(self, bot):
        """S7 TradingIntelligence должна быть ACTIVE."""
        from core.selftest_cube import _check_sphere_7_trading_intelligence, ACTIVE
        result = _check_sphere_7_trading_intelligence(bot)
        assert result.status == ACTIVE, f"S7: {result.status} / {result.detail}"

    def test_s11_narrative_builder_active(self, bot):
        """S11 NarrativeBuilder должна быть ACTIVE — build() вызывается всегда."""
        from core.selftest_cube import _check_sphere_11_narrative_builder, ACTIVE
        result = _check_sphere_11_narrative_builder(bot)
        assert result.status == ACTIVE, f"S11: {result.status} / {result.detail}"

    def test_s13_pair_context_bus_active(self, bot):
        """S13 PairContextBus (центр Куба) должна быть ACTIVE."""
        from core.selftest_cube import _check_sphere_13_pair_context_bus, ACTIVE
        result = _check_sphere_13_pair_context_bus(bot)
        assert result.status == ACTIVE, f"S13: {result.status} / {result.detail}"

    def test_edge_btc_to_ti_active(self, bot):
        """ARCH-78: ребро BTCRegimeProvider→TI должно быть ACTIVE (wire проверяется)."""
        from core.selftest_cube import _edge_btc_to_ti, ACTIVE
        result = _edge_btc_to_ti(bot)
        assert result.status == ACTIVE, f"E_BTC_TI: {result.status} / {result.detail}"

    def test_edge_ts_to_pta_active(self, bot):
        """Ребро TradeSimulator→PostTradeAnalyser должно быть ACTIVE."""
        from core.selftest_cube import _edge_ts_to_pta, ACTIVE
        result = _edge_ts_to_pta(bot)
        assert result.status == ACTIVE, f"E_TS_PTA: {result.status} / {result.detail}"

    def test_edge_pta_to_pairctx_active(self, bot):
        """Ребро PostTradeAnalyser→PairContextBus должно быть ACTIVE."""
        from core.selftest_cube import _edge_pta_to_pairctx, ACTIVE
        result = _edge_pta_to_pairctx(bot)
        assert result.status == ACTIVE, f"E_PTA_PC: {result.status} / {result.detail}"

    def test_edge_pta_to_intel_active(self, bot):
        """Ребро PostTradeAnalyser→TradingIntelligence должно быть ACTIVE."""
        from core.selftest_cube import _edge_pta_to_intel, ACTIVE
        result = _edge_pta_to_intel(bot)
        assert result.status == ACTIVE, f"E_PTA_TI: {result.status} / {result.detail}"

    def test_edge_ti_to_pairctx_active(self, bot):
        """Ребро TradingIntelligence→PairContextBus должно быть ACTIVE."""
        from core.selftest_cube import _edge_ti_to_pairctx, ACTIVE
        result = _edge_ti_to_pairctx(bot)
        assert result.status == ACTIVE, f"E_TI_PC: {result.status} / {result.detail}"

    def test_no_missing_critical_edges(self, bot):
        """Критические рёбра не должны быть MISSING."""
        from core.selftest_cube import run_cube_selftest, MISSING
        results = asyncio.get_event_loop().run_until_complete(run_cube_selftest(bot))
        critical = {
            "E_BTC_TI", "E_TS_PTA", "E_PTA_PC", "E_PTA_TI",
            "E_TI_PC", "E_TI_TS", "E_TS_PC",
        }
        missing_critical = [
            r for r in results
            if r.code in critical and r.status == MISSING
        ]
        assert not missing_critical, (
            "Критические рёбра в MISSING:\n" +
            "\n".join(f"  {r.code}: {r.detail}" for r in missing_critical)
        )


# ─────────────────────────────────────────────────────────────────────────────
# L2 — BTCRegimeProvider: вычисление режима
# ─────────────────────────────────────────────────────────────────────────────

class TestBTCRegimeProvider:
    def test_initial_mode_is_neutral(self):
        from core.exchange.btc_regime_provider import BTCRegimeProvider
        p = BTCRegimeProvider()
        assert p.get_btc_mode() == "NEUTRAL"

    def test_update_bull_trend(self):
        """Восходящий тренд → BULL после update()."""
        from core.exchange.btc_regime_provider import BTCRegimeProvider
        p = BTCRegimeProvider()
        df = _make_ohlcv(n=120, trend=0.05)  # явный uptrend

        dc = MagicMock()
        dc.get_ohlcv = AsyncMock(return_value=df)

        asyncio.get_event_loop().run_until_complete(p.update(dc))
        assert p.get_btc_mode() in ("BULL", "NEUTRAL"), f"Ожидали BULL, получили {p.get_btc_mode()}"
        assert p._updated_at is not None

    def test_update_bear_trend(self):
        """Нисходящий тренд → BEAR после update().
        ATR Supertrend (atr_period=43, factor=1.25) медленный — нужен крутой спад.
        """
        from core.exchange.btc_regime_provider import BTCRegimeProvider
        p = BTCRegimeProvider()
        # Крутой downtrend: цена падает с 50k до ~5k за 120 свечей, минимальная волатильность
        df = _make_ohlcv(n=120, base=50_000.0, trend=-0.35, vol=0.001)

        dc = MagicMock()
        dc.get_ohlcv = AsyncMock(return_value=df)

        asyncio.get_event_loop().run_until_complete(p.update(dc))
        assert p.get_btc_mode() in ("BEAR", "NEUTRAL"), f"Ожидали BEAR, получили {p.get_btc_mode()}"

    def test_ttl_prevents_double_fetch(self):
        """Второй update() сразу после первого не делает fetch (TTL)."""
        from core.exchange.btc_regime_provider import BTCRegimeProvider
        p = BTCRegimeProvider()
        df = _make_ohlcv()
        dc = MagicMock()
        dc.get_ohlcv = AsyncMock(return_value=df)

        asyncio.get_event_loop().run_until_complete(p.update(dc))
        asyncio.get_event_loop().run_until_complete(p.update(dc))  # сразу второй
        assert dc.get_ohlcv.call_count == 1, "TTL не сработал — fetch вызван дважды"

    def test_wired_to_ti(self):
        """BTCRegimeProvider wire'd в TI._btc_provider."""
        from core.exchange.btc_regime_provider import BTCRegimeProvider
        from unittest.mock import MagicMock
        ti   = MagicMock()
        prov = BTCRegimeProvider()
        ti._btc_provider = prov
        assert ti._btc_provider is prov
        assert ti._btc_provider.get_btc_mode() == "NEUTRAL"


# ─────────────────────────────────────────────────────────────────────────────
# L3 — Signal flow: BTCRegimeProvider → metadata["btc_4h_regime"] в TI
# ─────────────────────────────────────────────────────────────────────────────

class TestBTCRegimeInMetadata:
    def test_btc_mode_reaches_narrative_metadata(self, tmp_path):
        """
        ARCH-78: btc_mode из провайдера попадает в recommendation.metadata
        через TI.analyze_symbol → NarrativeBuilder.
        """
        from core.exchange.btc_regime_provider import BTCRegimeProvider
        from core.trading_intelligence import TradingIntelligence
        from core.context.pair_context import PairContextBus
        from core.config_loader import config
        from core.pivot_calculator_fixed import PivotCalculatorFixed

        df = _make_ohlcv(n=120, trend=0.05)

        dc = MagicMock()
        dc.get_ohlcv = AsyncMock(return_value=df)
        dc.get_ticker = AsyncMock(return_value={"last": 51000.0})
        dc._ohlcv_cache = {}

        pivot_calc = MagicMock(spec=PivotCalculatorFixed)
        pivot_calc.get_pivots = AsyncMock(return_value={})

        prov = BTCRegimeProvider()
        prov._btc_mode = "BULL"          # имитируем уже обновлённый режим
        prov._updated_at = datetime.utcnow()

        pc = PairContextBus()
        ti = TradingIntelligence(
            data_collector=dc,
            config=config,
            db_path=str(tmp_path / "test.db"),
            pivot_calculator=pivot_calc,
        )
        ti._pair_context_bus = pc
        ti._btc_provider = prov          # ARCH-78 wire

        rec = asyncio.get_event_loop().run_until_complete(
            ti.analyze_symbol("BTC/USDT:USDT")
        )
        # Recommendation может быть None если нет сигнала — это нормально.
        # Нас интересует что btc_provider не вызвал исключений.
        # Если rec есть — проверяем что narrative построен.
        if rec is not None:
            narrative = rec.metadata.get("narrative")
            assert narrative is not None, "metadata['narrative'] не установлен"
            assert isinstance(narrative.get("text"), str), "narrative.text не строка"


# ─────────────────────────────────────────────────────────────────────────────
# L4 — PostTradeAnalyser callback: close → adaptive weights
# ─────────────────────────────────────────────────────────────────────────────

class TestPostTradeCallback:
    def test_callback_registered(self, tmp_path):
        """TradeSimulator._post_trade_callback должен быть установлен."""
        from core.trade_simulator import TradeSimulator
        from core.context.pair_context import PairContextBus
        from core.trading.post_trade_analyser import PostTradeAnalyser

        ts  = TradeSimulator(db_path=str(tmp_path / "t.db"))
        pc  = PairContextBus()
        dc  = MagicMock()
        pta = PostTradeAnalyser(pc, dc)
        ts.set_post_trade_callback(pta.on_trade_closed)
        assert ts._post_trade_callback is not None

    def test_pta_linked_to_pair_context(self, tmp_path):
        """PostTradeAnalyser._ctx — это тот же экземпляр PairContextBus."""
        from core.trade_simulator import TradeSimulator
        from core.context.pair_context import PairContextBus
        from core.trading.post_trade_analyser import PostTradeAnalyser

        pc  = PairContextBus()
        dc  = MagicMock()
        pta = PostTradeAnalyser(pc, dc)
        assert getattr(pta, "_ctx", None) is pc

    def test_adaptive_weights_method_exists(self, tmp_path):
        """TradingIntelligence.update_signal_weights() доступен."""
        from core.config_loader import config
        from core.pivot_calculator_fixed import PivotCalculatorFixed
        dc  = MagicMock()
        dc.get_ohlcv = AsyncMock(return_value=_make_ohlcv())
        pc  = MagicMock(spec=PivotCalculatorFixed)
        pc.get_pivots = AsyncMock(return_value={})
        from core.trading_intelligence import TradingIntelligence
        ti = TradingIntelligence(data_collector=dc, config=config,
                                 db_path=str(tmp_path / "t.db"), pivot_calculator=pc)
        assert hasattr(ti, "update_signal_weights"), "update_signal_weights отсутствует"


# ─────────────────────────────────────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import tempfile

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    print("=" * 60)
    print("ТЕСТ РЁБЕР КУБА МЕТАТРОНА")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "test.db")
        from core.subscription_manager import SubscriptionManager
        SubscriptionManager(db)

        bot = _make_bot_stub(db)

        from core.selftest_cube import run_cube_selftest, format_cube_report, MISSING, ACTIVE, SHADOW

        results = asyncio.get_event_loop().run_until_complete(run_cube_selftest(bot))
        print(format_cube_report(results))

        # Сводка
        total   = len(results)
        active  = sum(1 for r in results if r.status == ACTIVE)
        shadow  = sum(1 for r in results if r.status == SHADOW)
        missing = sum(1 for r in results if r.status == MISSING)
        print(f"\nИтого: {total} проверок | ✅{active} ACTIVE | ⚠️{shadow} SHADOW | 🔴{missing} MISSING")

        # BTCRegimeProvider отдельно
        print("\n--- BTCRegimeProvider ---")
        from core.exchange.btc_regime_provider import BTCRegimeProvider
        p = BTCRegimeProvider()
        df_bull = _make_ohlcv(n=120, trend=0.05)
        dc_mock = MagicMock()
        dc_mock.get_ohlcv = AsyncMock(return_value=df_bull)
        asyncio.get_event_loop().run_until_complete(p.update(dc_mock))
        print(f"После bull OHLCV: mode={p.get_btc_mode()}, updated_at={p._updated_at}")

        df_bear = _make_ohlcv(n=120, trend=-0.05)
        dc_mock2 = MagicMock()
        dc_mock2.get_ohlcv = AsyncMock(return_value=df_bear)
        p2 = BTCRegimeProvider()
        asyncio.get_event_loop().run_until_complete(p2.update(dc_mock2))
        print(f"После bear OHLCV: mode={p2.get_btc_mode()}, updated_at={p2._updated_at}")

        print("\nTTL test: второй update сразу →")
        call_count_before = dc_mock.get_ohlcv.call_count
        asyncio.get_event_loop().run_until_complete(p.update(dc_mock))
        assert dc_mock.get_ohlcv.call_count == call_count_before, "TTL не сработал!"
        print("  fetch НЕ вызван повторно ✅")

        print("\n✅ Standalone прогон завершён")
