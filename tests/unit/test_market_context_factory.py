"""Оборот в сигнале собирается ОДИН раз — в шине, а не в каждом лупе.

Повод (Егор, 29.09): «почему 6 лупов обороты заполняют? почему не один источник? у нас ведь
сфера для этого была?». Была: каталог шины обещал `TICK_PRICE: {price, volume_24h}`, но `PairState`
поля не имел, обработчик оборот выбрасывал, а `MarketContext.volume_24h` был обязательным — и
шесть лупов затыкали его нулём. Итог: 0.0 во всех 922 боевых сделках.

Тесты держат три двери: шина хранит оборот, фабрика его отдаёт, кэш тикера подхватывается
без сети и оседает в шине.
"""
from __future__ import annotations

import pytest

from core.context.context_factory import build_market_context
from core.context.pair_context import PairContextBus, SphereEvent
from core.signals.signal_models import MarketContext

SYM = "BTC/USDT:USDT"


class _DC:
    """Двойник DataCollector: отдаёт ТОЛЬКО кэш, сеть недоступна by design."""

    def __init__(self, ticker=None):
        self._t = ticker
        self.calls = 0

    def get_cached_ticker(self, symbol):
        self.calls += 1
        return self._t


class _Bot:
    def __init__(self, bus=None, dc=None):
        self.pair_context = bus
        self.data_collector = dc


# ── шина хранит то, что обещает каталог ──────────────────────────────────────

def test_bus_keeps_volume_from_tick_event():
    bus = PairContextBus()
    bus.publish(SYM, SphereEvent.TICK_PRICE, {"price": 100.0, "volume_24h": 5_000_000.0,
                                              "price_change_24h": -3.5})
    st = bus.get(SYM)
    assert st.tick_price == 100.0
    assert st.volume_24h == 5_000_000.0, "оборот выброшен, как было до 29.09"
    assert st.price_change_24h == -3.5
    assert st.volume_24h_time is not None


def test_bus_snapshot_exports_volume():
    """Данные, живущие в шине, но не экспортируемые, — уже пройденная дыра (25.07)."""
    bus = PairContextBus()
    bus.publish(SYM, SphereEvent.TICK_PRICE, {"price": 1.0, "volume_24h": 42.0})
    assert bus.get_full_state(SYM)["volume_24h"] == 42.0


def test_tick_without_volume_does_not_erase_known_value():
    """Тик без оборота (WsFeed шлёт только цену) не должен обнулять то, что уже знаем."""
    bus = PairContextBus()
    bus.publish(SYM, SphereEvent.TICK_PRICE, {"price": 1.0, "volume_24h": 777.0})
    bus.publish(SYM, SphereEvent.TICK_PRICE, {"price": 1.5})
    assert bus.get(SYM).volume_24h == 777.0


# ── фабрика ───────────────────────────────────────────────────────────────────

def test_factory_takes_volume_from_bus():
    bus = PairContextBus()
    bus.publish(SYM, SphereEvent.TICK_PRICE, {"price": 100.0, "volume_24h": 1_234.0})
    dc = _DC()
    ctx = build_market_context(_Bot(bus, dc), SYM, current_price=99.0)
    assert ctx.volume_24h == 1_234.0
    assert ctx.current_price == 99.0, "явная цена лупа должна побеждать тик"
    assert dc.calls == 0, "оборот был в шине — кэш тикера дёргать незачем"


def test_factory_falls_back_to_ticker_cache_and_backfills_bus():
    bus = PairContextBus()
    dc = _DC({"quoteVolume": 88_000.0, "percentage": 2.5})
    ctx = build_market_context(_Bot(bus, dc), SYM, current_price=10.0)
    assert ctx.volume_24h == 88_000.0
    assert ctx.price_change_24h == 2.5
    assert bus.get(SYM).volume_24h == 88_000.0, "прочитанное не осело в шине — след. вызов снова пойдёт в кэш"


def test_factory_prefers_quote_volume_over_base():
    """Порог `min_volume_usd` в долларах — сравнивать с baseVolume нельзя."""
    dc = _DC({"baseVolume": 5.0, "quoteVolume": 500_000.0})
    ctx = build_market_context(_Bot(PairContextBus(), dc), SYM, current_price=1.0)
    assert ctx.volume_24h == 500_000.0


def test_factory_survives_without_bus_and_collector():
    ctx = build_market_context(_Bot(None, None), SYM, current_price=7.0)
    assert isinstance(ctx, MarketContext)
    assert (ctx.current_price, ctx.volume_24h) == (7.0, 0.0)


def test_factory_passes_extra_fields():
    ctx = build_market_context(_Bot(PairContextBus(), _DC()), SYM, current_price=1.0,
                               volatility=0.0, regime="RANGE")
    assert ctx.volatility == 0.0 and ctx.regime == "RANGE"


# ── сигнатура модели ──────────────────────────────────────────────────────────

def test_market_context_no_longer_forces_zero():
    """Пока поля были обязательными, луп был ВЫНУЖДЕН передать 0.0 — отсюда и пошла дыра."""
    ctx = MarketContext(symbol=SYM, current_price=1.0)
    assert ctx.volume_24h == 0.0 and ctx.price_change_24h == 0.0


@pytest.mark.parametrize("bad", [{}, {"quoteVolume": 0}, {"quoteVolume": None}])
def test_empty_ticker_gives_honest_zero(bad):
    ctx = build_market_context(_Bot(PairContextBus(), _DC(bad)), SYM, current_price=1.0)
    assert ctx.volume_24h == 0.0
