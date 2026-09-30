"""ARCH-101 гигиена (30.09.2026): шина честно показывает, что в ней происходит.

- EventBus считает публикации по типам (принято / отбито паузой пары или очередью);
- самопроверка ребра «детекторы→EventBus» смотрит на эти счётчики, а не на флаг конфига;
- роутер публикует POSITION_DROPPED и на раннем выходе «пара на паузе после отказа биржи».
"""
import asyncio
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from core.context.event_bus import EventBus
from core.selftest_cube import ACTIVE, MISSING, SHADOW, _edge_detectors_to_eventbus


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_event_bus_counts_accepted_and_rejected_by_type():
    eb = EventBus()
    assert _run(eb.publish("A/USDT:USDT", "pivot_reversal", priority=2)) is True
    # та же пара уже в очереди, приоритет не выше → отбито
    assert _run(eb.publish("A/USDT:USDT", "mtf_alert", priority=4)) is False
    # пара на паузе → отбито
    eb._cooldowns["B/USDT:USDT"] = datetime.now(timezone.utc)
    assert _run(eb.publish("B/USDT:USDT", "fvg_touch", priority=2)) is False
    st = eb.stats()
    assert st["accepted_by_type"] == {"pivot_reversal": 1}
    assert st["rejected_by_type"] == {"mtf_alert": 1, "fvg_touch": 1}


def _bot_with(eb):
    return SimpleNamespace(event_bus=eb, config=None)


def test_edge_missing_without_event_bus():
    assert _edge_detectors_to_eventbus(_bot_with(None)).status == MISSING


def test_edge_shadow_when_nothing_published():
    # раньше здесь было ACTIVE по одному флагу enabled
    assert _edge_detectors_to_eventbus(_bot_with(EventBus())).status == SHADOW


def test_edge_ignores_trade_closed_and_goes_active_on_detector_publish():
    eb = EventBus()
    _run(eb.publish("A/USDT:USDT", "trade_closed", priority=5))
    assert _edge_detectors_to_eventbus(_bot_with(eb)).status == SHADOW
    _run(eb.publish("B/USDT:USDT", "smc_choch_detected", priority=1))
    res = _edge_detectors_to_eventbus(_bot_with(eb))
    assert res.status == ACTIVE and "smc_choch_detected=1" in res.detail


def test_router_early_offline_exit_publishes_dropped():
    from core.context.pair_context import SphereEvent
    from core.trading.trade_router import TradeRouter

    published = []
    bus = SimpleNamespace(publish=lambda sym, ev, data: published.append((sym, ev, data)))
    bot = SimpleNamespace(config={}, pair_context=bus)
    router = TradeRouter(bot)
    router._symbol_cooldown["X/USDT:USDT"] = time.time() + 600
    rec = SimpleNamespace(symbol="X/USDT:USDT", direction=SimpleNamespace(value="LONG"),
                          overall_strength=70)
    res = _run(router.submit(rec, source="impulse_fib"))
    assert res.trade_id is None and res.hard_drops[0][0] == "symbol_offline_cooldown"
    assert len(published) == 1
    sym, ev, data = published[0]
    assert sym == "X/USDT:USDT" and ev == SphereEvent.POSITION_DROPPED
    assert data["source"] == "impulse_fib" and data["side"] == "LONG" and data["strength"] == 70
    assert data["hard_drops"] == [{"gate": "symbol_offline_cooldown", "reason": "пара недоступна на бирже"}]
