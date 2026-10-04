"""Публикация тика в шину: порог по СИМВОЛУ и ВРЕМЕНИ, а не по общему счётчику.

Было `self._ticker_updates % 10 == 0` — счётчик общий на все 567 пар, поэтому в шину
уходило каждое десятое событие ИЗ ВСЕГО ПОТОКА: ликвид проскакивал часто, неликвид
почти никогда, и цена в шине жила с медианой 81 с при мгновенном тике в памяти.
"""
from types import SimpleNamespace

import pytest

from core.infra.ws_feed import WsFeed

SYM, OTHER = "GRT/USDT:USDT", "LDO/USDT:USDT"


class _Bus:
    """Шина: собирает публикации и отдаёт состояние пар для приоритета."""

    def __init__(self, states=None):
        self.published = []
        self._states = states or {}

    def publish(self, symbol, event, data):
        self.published.append((symbol, data.get("price")))

    def all_symbols(self):
        return list(self._states)

    def get(self, symbol):
        return self._states.get(symbol, SimpleNamespace(open_trade_id=None, watchlist=None))


def _feed(bus, *, gap=15.0, prio_gap=1.0):
    f = WsFeed()
    f._pair_context_bus = bus
    f._bus_pub_sec = gap
    f._bus_pub_prio_sec = prio_gap
    return f


class _Exchange:
    """Отдаёт заданную последовательность тиков, затем останавливает цикл."""

    def __init__(self, feed, prices):
        self.feed, self.prices, self.i = feed, prices, 0

    async def watch_ticker(self, symbol):
        if self.i >= len(self.prices):
            self.feed._running = False
            return {"last": self.prices[-1]}
        p = self.prices[self.i]
        self.i += 1
        return {"last": p}


async def _pump(feed, symbol, prices, clock):
    """Прогоняет тики через настоящий _watch_ticker с управляемым временем."""
    import core.infra.ws_feed as mod
    feed._running = True
    real_time = mod.time.time
    mod.time.time = clock
    try:
        await feed._watch_ticker(_Exchange(feed, prices), symbol)
    finally:
        mod.time.time = real_time


@pytest.mark.asyncio
async def test_publishes_once_per_window_not_every_tenth_tick():
    """Сто тиков подряд в одну секунду → одна публикация, а не десять."""
    bus = _Bus()
    f = _feed(bus)
    t = [1000.0]
    await _pump(f, SYM, [1.0 + i / 1000 for i in range(100)], lambda: t[0])
    assert len(bus.published) == 1
    assert f._ticker_updates >= 100          # в памяти — каждый тик


@pytest.mark.asyncio
async def test_publishes_again_after_window():
    bus = _Bus()
    f = _feed(bus, gap=15.0)
    t = [1000.0]

    def clock():
        t[0] += 8.0                           # каждый тик — через 8 секунд
        return t[0]

    await _pump(f, SYM, [1.0, 2.0, 3.0, 4.0], clock)
    # окно 15 с: публикации на 1-м тике и дальше примерно через каждые два
    assert 2 <= len(bus.published) <= 3


@pytest.mark.asyncio
async def test_priority_pair_publishes_far_more_often():
    """Пара с открытой сделкой должна попадать в шину на порядок чаще обычной."""
    states = {SYM: SimpleNamespace(open_trade_id=42, watchlist=None),
              OTHER: SimpleNamespace(open_trade_id=None, watchlist=None)}
    t = [1000.0]

    def clock():
        t[0] += 1.0
        return t[0]

    bus_p = _Bus(states)
    fp = _feed(bus_p, gap=15.0, prio_gap=1.0)
    await _pump(fp, SYM, [1.0] * 12, clock)

    t[0] = 1000.0
    bus_o = _Bus(states)
    fo = _feed(bus_o, gap=15.0, prio_gap=1.0)
    await _pump(fo, OTHER, [1.0] * 12, clock)

    assert len(bus_p.published) > len(bus_o.published) * 3


@pytest.mark.asyncio
async def test_watchlist_pair_is_priority_too():
    states = {SYM: SimpleNamespace(open_trade_id=None, watchlist={"waves_long": {}})}
    t = [1000.0]

    def clock():
        t[0] += 1.0
        return t[0]

    bus = _Bus(states)
    f = _feed(bus, gap=60.0, prio_gap=1.0)
    await _pump(f, SYM, [1.0] * 6, clock)
    assert len(bus.published) >= 4


@pytest.mark.asyncio
async def test_price_in_memory_updates_on_every_tick():
    """Троттлинг касается ТОЛЬКО шины: трекер сделок обязан видеть каждый тик."""
    bus = _Bus()
    f = _feed(bus)
    t = [1000.0]
    await _pump(f, SYM, [1.0, 2.0, 3.0], lambda: t[0])
    # get_price смотрит на РЕАЛЬНОЕ время (TTL 60 с), а стенд живёт в 1000.0 —
    # поэтому проверяем сам кэш цен, а не обёртку с протуханием
    assert f._ws_prices[SYM][0] == 3.0
    assert len(bus.published) == 1


@pytest.mark.asyncio
async def test_broken_bus_does_not_stop_the_stream():
    class _Boom(_Bus):
        def publish(self, *a, **k):
            raise RuntimeError("шина упала")

    f = _feed(_Boom())
    t = [1000.0]
    await _pump(f, SYM, [1.0, 2.0], lambda: t[0])
    assert f._ws_prices[SYM][0] == 2.0        # поток цен живёт
