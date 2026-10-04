"""PriceWS (N21): свой клиент цены вместо ccxt.pro.

Проверяем ровно то, ради чего он написан: разбор обоих каналов BingX, порог
публикации по символу и времени, приоритет торгуемых пар и то, что клиент
совместим по интерфейсу с WsFeed (data_collector зовёт get_price).
"""
import time
from types import SimpleNamespace

import pytest

from core.infra.price_ws import PriceWS

SYM, WS_SYM = "GRT/USDT:USDT", "GRT-USDT"


class _Bus:
    def __init__(self, states=None):
        self.published = []
        self._states = states or {}

    def publish(self, symbol, event, data):
        self.published.append((symbol, data.get("price")))

    def all_symbols(self):
        return list(self._states)

    def get(self, symbol):
        return self._states.get(symbol, SimpleNamespace(open_trade_id=None, watchlist=None))


def _msg(channel="markPrice", price="1.2345"):
    field = "p" if channel == "markPrice" else "c"
    return {"code": 0, "dataType": f"{WS_SYM}@{channel}",
            "data": {"e": f"{channel}Update", "s": WS_SYM, field: price}}


# ── разбор протокола ─────────────────────────────────────────────────────

def test_parses_mark_price():
    f = PriceWS([SYM])
    assert f._parse(_msg("markPrice", "1.5")) == (SYM, 1.5)


def test_parses_last_price_from_other_field():
    """lastPrice кладёт цену в 'c', markPrice — в 'p'. Перепутать значит молча нулить."""
    f = PriceWS([SYM], channel="lastPrice")
    assert f._parse(_msg("lastPrice", "2.5")) == (SYM, 2.5)
    assert f._parse(_msg("markPrice", "2.5")) is None      # чужой канал игнорируем


def test_rejects_garbage():
    f = PriceWS([SYM])
    assert f._parse({"dataType": f"{WS_SYM}@markPrice", "data": {"p": "не число"}}) is None
    assert f._parse({"dataType": f"{WS_SYM}@markPrice", "data": {"p": "0"}}) is None
    assert f._parse({"dataType": f"{WS_SYM}@kline_5m", "data": {}}) is None


def test_unknown_channel_falls_back_to_mark_price():
    assert PriceWS([SYM], channel="чепуха")._channel == "markPrice"


# ── интерфейс потребителя (вместо WsFeed) ────────────────────────────────

def test_get_price_matches_wsfeed_contract():
    f = PriceWS([SYM])
    assert f.get_price(SYM) is None
    f._on_price(SYM, 3.21)
    assert f.get_price(SYM) == 3.21


def test_stale_price_is_not_returned():
    f = PriceWS([SYM])
    f._prices[SYM] = (3.21, time.time() - 120)
    assert f.get_price(SYM) is None


# ── порог публикации в шину ──────────────────────────────────────────────

def test_publishes_once_per_window_per_symbol():
    bus = _Bus()
    f = PriceWS([SYM], bus=bus, pub_sec=15.0)
    for i in range(50):
        f._on_price(SYM, 1.0 + i / 100)
    assert len(bus.published) == 1
    assert f.stats["updates"] == 50          # в памяти — каждое обновление


def test_priority_pair_publishes_more_often():
    states = {SYM: SimpleNamespace(open_trade_id=7, watchlist=None)}
    bus = _Bus(states)
    f = PriceWS([SYM], bus=bus, pub_sec=60.0, pub_prio_sec=0.0)
    for i in range(5):
        f._on_price(SYM, 1.0 + i)
    assert len(bus.published) == 5           # приоритет: порог 0 — публикуем всё

    bus2 = _Bus({SYM: SimpleNamespace(open_trade_id=None, watchlist=None)})
    f2 = PriceWS([SYM], bus=bus2, pub_sec=60.0, pub_prio_sec=0.0)
    for i in range(5):
        f2._on_price(SYM, 1.0 + i)
    assert len(bus2.published) == 1          # обычная пара — одно за окно


def test_watchlist_counts_as_priority():
    bus = _Bus({SYM: SimpleNamespace(open_trade_id=None, watchlist={"waves_long": {}})})
    f = PriceWS([SYM], bus=bus, pub_sec=60.0, pub_prio_sec=0.0)
    for i in range(3):
        f._on_price(SYM, 1.0 + i)
    assert len(bus.published) == 3


def test_broken_bus_does_not_lose_price():
    class _Boom(_Bus):
        def publish(self, *a, **k):
            raise RuntimeError("шина упала")

    f = PriceWS([SYM], bus=_Boom())
    f._on_price(SYM, 9.9)
    assert f.get_price(SYM) == 9.9
    assert f.stats["errors"] == 1


def test_works_without_bus_at_all():
    f = PriceWS([SYM], bus=None)
    f._on_price(SYM, 4.2)
    assert f.get_price(SYM) == 4.2


# ── быстрый канал для торгуемых пар ──────────────────────────────────────

def test_fast_channel_price_wins_over_slow():
    """markPrice не должен затирать свежий lastPrice на паре, где открыта сделка."""
    f = PriceWS([SYM], fast_channel="lastPrice")
    f._on_price(SYM, 10.0, fast=True)
    f._on_price(SYM, 9.0)                       # медленный канал следом
    assert f.get_price(SYM) == 10.0


def test_slow_channel_returns_after_fast_goes_silent():
    """Если быстрый канал замолчал (сделка закрыта), медленный снова ведёт цену."""
    f = PriceWS([SYM], fast_channel="lastPrice")
    f._on_price(SYM, 10.0, fast=True)
    f._fast_at[SYM] = time.time() - 60          # молчит минуту
    f._on_price(SYM, 9.0)
    assert f.get_price(SYM) == 9.0


def test_fast_channel_can_be_disabled():
    f = PriceWS([SYM], fast_channel="")
    assert f._fast_channel == ""
    f._on_price(SYM, 1.0)
    assert f.get_price(SYM) == 1.0


def test_unknown_fast_channel_is_refused():
    assert PriceWS([SYM], fast_channel="чепуха")._fast_channel == ""


def test_priority_provider_wins_over_empty_bus():
    """Поле open_trade_id в шине пусто (никто не пишет) — приоритет берём снаружи."""
    bus = _Bus({SYM: SimpleNamespace(open_trade_id=None, watchlist=None)})
    f = PriceWS([SYM], bus=bus, pub_sec=60.0, pub_prio_sec=0.0,
                priority_provider=lambda: {SYM})
    for i in range(4):
        f._on_price(SYM, 1.0 + i)
    assert len(bus.published) == 4


def test_falls_back_to_bus_when_provider_empty_or_broken():
    bus = _Bus({SYM: SimpleNamespace(open_trade_id=None, watchlist={"s": {}})})
    f = PriceWS([SYM], bus=bus, pub_sec=60.0, pub_prio_sec=0.0,
                priority_provider=lambda: set())
    f._on_price(SYM, 1.0)
    f._on_price(SYM, 2.0)
    assert len(bus.published) == 2        # watchlist из шины подхватился

    def _boom():
        raise RuntimeError("БД недоступна")

    f2 = PriceWS([SYM], bus=bus, pub_sec=60.0, pub_prio_sec=0.0, priority_provider=_boom)
    f2._on_price(SYM, 1.0)
    assert len(bus.published) == 3        # падение поставщика не рушит поток
