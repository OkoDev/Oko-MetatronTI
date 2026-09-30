"""ADR-003 шаг 0–1: каталог классов событий, зеркало бота, хаб шины Куба."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

from core.context.bus_catalog import EVENT_CLASS, event_class, unclassified_events
from core.context.cube_mirror import CubeMirror, pair_state_dict
from core.context.pair_context import PairContextBus, SphereEvent

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import cube_hub  # noqa: E402

SYM = "BTC/USDT:USDT"


# ── шаг 0: контракт ──
def test_every_sphere_event_has_hub_class():
    assert unclassified_events() == []
    assert set(EVENT_CLASS.values()) <= {"state", "fact", "internal"}
    assert event_class("recommendation_built") == "internal"      # несёт объект — наружу не идёт
    assert event_class("не_бывает") == "internal"                  # незнакомое не утекает


# ── зеркало ──
def _mirror(bus, **kw):
    return CubeMirror(bus, "http://127.0.0.1:1", **kw)             # поток-отправщик в тестах не запускаем


def _drain(m):
    out = []
    while not m._q.empty():
        out.append(json.loads(m._q.get_nowait()[1]))
    return out


def test_mirror_fact_goes_immediately_state_on_flush():
    bus = PairContextBus()
    m = _mirror(bus, rolling_per_tick=0)
    bus._mirror = m
    bus.publish(SYM, SphereEvent.SIGNAL_DETECTED, {"signal_type": "wt_signal", "direction": "LONG"})
    bus.publish(SYM, SphereEvent.REGIME_UPDATED, {"regime": "RANGE"})
    bus.publish(SYM, SphereEvent.RECOMMENDATION_BUILT, {"recommendation": object()})
    items = _drain(m)
    assert [i["ev"] for i in items] == ["signal_detected"]          # состояние и internal — не фактом
    assert m.flush_states() == 1
    st = _drain(m)[0]
    assert st["k"] == "s" and st["sym"] == SYM and st["st"]["regime"] == "RANGE"
    # все поля PairState, включая то, чего нет в get_full_state (фандинг)
    assert "funding_rate" in st["st"] and "funding_rate" not in bus.get_full_state(SYM)
    assert st["seq"] > items[0]["seq"]


def test_mirror_marks_direct_update_and_watchlist_dirty_and_canonicalizes():
    bus = PairContextBus()
    m = _mirror(bus, rolling_per_tick=0)
    bus._mirror = m
    bus.update("ETH-USDT", regime="TREND_UP")                        # не канонический формат
    bus.set_watchlist("SOL/USDT:USDT", "impulse_fib", {"direction": "LONG"})
    assert m._dirty == {"ETH/USDT:USDT", "SOL/USDT:USDT"}


def test_mirror_rolling_resync_sends_stale_pairs():
    bus = PairContextBus()
    for s in ("A/USDT:USDT", "B/USDT:USDT", "C/USDT:USDT"):
        bus.get(s).tick_price = 1.0
    m = _mirror(bus, rolling_per_tick=2)
    assert m.flush_states() == 2                                     # ни одна не грязная — досыл двух
    assert m.flush_states() == 2                                     # следующий тик: оставшаяся + самая старая
    assert len(m._sent_at) == 3


def test_mirror_queue_overflow_drops_oldest_and_counts():
    bus = PairContextBus()
    m = _mirror(bus, queue_max=2, rolling_per_tick=0)
    for i in range(4):
        m.on_publish(SYM, "trade_closed", {"i": i})
    assert m.dropped["fact"] == 2
    assert [x["data"]["i"] for x in _drain(m)] == [2, 3]             # свежее сохранено


def test_pair_state_dict_serializable():
    bus = PairContextBus()
    bus.publish(SYM, SphereEvent.OHLCV_UPDATED, {"tf": "15m", "rows": 10, "close": 1.0})
    json.dumps(pair_state_dict(bus.get(SYM)), default=str)


# ── хаб ──
@pytest.fixture
def hub(tmp_path):
    return cube_hub.Hub(tmp_path / "cube.db", retention_days=30)


def _item_s(seq, sym=SYM, **st):
    return {"k": "s", "sym": sym, "st": st, "ts": 1000.0, "seq": seq}


def _item_f(seq, ev="signal_detected", sym=SYM, **data):
    return {"k": "f", "sym": sym, "ev": ev, "data": data, "ts": 1000.0, "seq": seq}


def test_hub_state_and_facts(hub):
    facts = hub.apply("oko-bot", [_item_s(1, regime="RANGE"), _item_f(2, direction="LONG")], recv=1000.5)
    assert len(facts) == 1 and facts[0]["event"] == "signal_detected"
    st = json.loads(hub.state_json("BTC_USDT", now=1010.0))          # любой формат символа
    assert st["regime"] == "RANGE" and st["_age_sec"] == 10.0
    allj = json.loads(hub.all_states_json(now=1010.0))
    assert allj["n"] == 1 and allj["coins"][SYM]["regime"] == "RANGE"
    assert [f["data"]["direction"] for f in hub.facts(0, ["signal_detected"])] == ["LONG"]
    assert hub.facts(0, ["trade_closed"]) == []


def test_hub_counts_seq_gaps_and_restarts(hub):
    hub.apply("oko-bot", [_item_s(1), _item_s(2), _item_s(5)])
    p = hub.producers["oko-bot"]
    assert p["gaps"] == 1 and p["lost"] == 2
    hub.apply("oko-bot", [_item_s(1)])                               # рестарт бота — seq с начала
    assert p["restarts"] == 1 and p["lost"] == 2


def test_hub_survives_restart_from_db(tmp_path):
    h1 = cube_hub.Hub(tmp_path / "cube.db")
    h1.apply("oko-bot", [_item_s(1, regime="RANGE"), _item_f(2)])
    h1.snapshot_to_db()
    h2 = cube_hub.Hub(tmp_path / "cube.db")
    assert json.loads(h2.state_json(SYM))["regime"] == "RANGE"
    assert len(h2.facts()) == 1


def test_hub_purge_old_facts(hub):
    hub.apply("oko-bot", [_item_f(1)], recv=1000.0)
    assert hub.purge(now=1000.0 + 31 * 86400) == 1


def test_hub_bad_item_does_not_break_batch(hub):
    hub.apply("oko-bot", [{"k": "s"}, _item_s(2, regime="X")])
    assert hub.bad_items == 1 and json.loads(hub.state_json(SYM))["regime"] == "X"


# ── HTTP: токен, Origin, чтение, поток ──
def test_hub_http_token_origin_and_ws(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        hub = cube_hub.Hub(tmp_path / "cube.db")
        app = cube_hub.make_app(hub, "tok")
        async with TestClient(TestServer(app)) as cl:
            body = {"producer": "oko-bot", "items": [_item_s(1, regime="RANGE")]}
            assert (await cl.post("/publish", json=body)).status == 401
            r = await cl.post("/publish", json=body, headers={"X-Cube-Token": "tok", "Origin": "http://evil"})
            assert r.status == 403
            assert (await cl.post("/publish", json=body, headers={"X-Cube-Token": "tok"})).status == 200
            assert (await (await cl.get("/state/BTC-USDT")).json())["regime"] == "RANGE"
            assert (await cl.get("/state/NOPE_USDT")).status == 404
            ws = await cl.ws_connect("/ws?types=trade_closed")
            await cl.post("/publish", headers={"X-Cube-Token": "tok"},
                          json={"producer": "oko-bot", "items": [_item_f(2, "signal_detected"),
                                                                 _item_f(3, "trade_closed", r=1)]})
            msg = await asyncio.wait_for(ws.receive_json(), 5)
            assert msg["event"] == "trade_closed"                    # подписка по типам
            await ws.close()
            st = await (await cl.get("/stats")).json()
            assert st["states"] == 1 and st["producers"]["oko-bot"]["items"] == 3

    asyncio.new_event_loop().run_until_complete(run())
