"""ADR-003 шаг 3: факт внешней сферы → сделка через роутер, с защитами.

Главное, что проверяем: спутник НЕ отдаёт команду, он публикует факт; решает роутер бота.
Вне белого списка — только лог. Без геометрии — не регистрируем. Свои факты обратно не принимаем.
"""
import asyncio
from types import SimpleNamespace

import pytest

from core.context.cube_inbox import CubeInbox
from core.context.pair_context import PairContextBus, SphereEvent

SYM = "GRT/USDT:USDT"


def _fact(signal_type="breakout", producer="oko-sm-watch", **over):
    data = {"signal_type": signal_type, "direction": "LONG", "strength": 60, "tf": "4h",
            "price": 0.1, "entry": 0.1, "sl": 0.095, "tp": 0.11}
    data.update(over)
    return {"id": 7, "producer": producer, "symbol": SYM, "event": "signal_detected", "data": data}


class _Router:
    def __init__(self, trade_id=101):
        self.calls = []
        self._tid = trade_id

    async def submit(self, rec, *, source, extra_features=None):
        self.calls.append((rec, source, extra_features))
        return SimpleNamespace(trade_id=self._tid, hard_drops=[], exchange_order_id=None)


def _bot(router=None):
    return SimpleNamespace(trade_router=router, pair_context=PairContextBus())


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def test_whitelisted_fact_becomes_trade_via_router():
    r = _Router()
    bot = _bot(r)
    inbox = CubeInbox(bot, allow=["breakout"])
    assert _run(inbox.handle(_fact())) is True
    rec, source, extra = r.calls[0]
    assert source == "breakout" and rec.symbol == SYM and rec.direction.value == "LONG"
    assert rec.entry_price == 0.1 and rec.stop_loss == 0.095 and rec.take_profit == 0.11
    assert extra["external_producer"] == "oko-sm-watch" and extra["cube_fact_id"] == 7
    assert inbox.registered == 1
    # сферы бота видят внешний сигнал тем же событием
    st = bot.pair_context.get(SYM)
    assert st.last_signal_type == "breakout" and st.last_signal_direction == "LONG"


def test_source_outside_whitelist_is_only_logged():
    r = _Router()
    inbox = CubeInbox(_bot(r), allow=["breakout"])
    assert _run(inbox.handle(_fact(signal_type="чужой_источник"))) is False
    assert r.calls == [] and inbox.rejected == 1


def test_empty_whitelist_never_trades():
    r = _Router()
    inbox = CubeInbox(_bot(r), allow=[])
    assert _run(inbox.handle(_fact())) is False
    assert r.calls == []


def test_fact_without_geometry_is_not_registered():
    r = _Router()
    inbox = CubeInbox(_bot(r), allow=["breakout"])
    assert _run(inbox.handle(_fact(sl=None, tp=None))) is False
    assert r.calls == []


def test_dedup_blocks_repeat_within_window():
    r = _Router()
    inbox = CubeInbox(_bot(r), allow=["breakout"], dedup_min=60)
    assert _run(inbox.handle(_fact())) is True
    assert _run(inbox.handle(_fact())) is False          # тот же источник/пара/сторона
    assert len(r.calls) == 1
    assert _run(inbox.handle(_fact(direction="SHORT"))) is True   # другая сторона — не дубль
    assert len(r.calls) == 2


def test_gate_drop_is_not_a_trade():
    class _Drop(_Router):
        async def submit(self, rec, *, source, extra_features=None):
            self.calls.append((rec, source, extra_features))
            return SimpleNamespace(trade_id=None, hard_drops=[("min_sl_dist", "близко")])
    r = _Drop()
    inbox = CubeInbox(_bot(r), allow=["breakout"])
    assert _run(inbox.handle(_fact())) is False
    assert inbox.accepted == 1 and inbox.registered == 0   # факт принят, сделки нет — решил роутер


def test_router_exception_does_not_break_bridge():
    class _Boom(_Router):
        async def submit(self, rec, *, source, extra_features=None):
            raise RuntimeError("роутер упал")
    inbox = CubeInbox(_bot(_Boom()), allow=["breakout"])
    assert _run(inbox.handle(_fact())) is False


def test_own_facts_are_not_consumed_back(monkeypatch):
    """Факты самого бота мост игнорирует — иначе петля: публикация → приём → публикация."""
    r = _Router()
    inbox = CubeInbox(_bot(r), allow=["breakout"])
    from core.context import cube_client as cc
    rows = [_fact(producer="oko-bot"), _fact(producer="oko-sm-watch")]
    monkeypatch.setattr(cc, "facts", lambda *a, **k: rows if a[0] else [rows[0]])

    async def one_pass():
        task = asyncio.create_task(inbox.run())
        await asyncio.sleep(0.05)
        inbox.poll = 0.01
        await asyncio.sleep(0.2)
        task.cancel()
    _run(one_pass())
    assert all(src == "breakout" for _, src, _ in r.calls)
    assert all(e["external_producer"] == "oko-sm-watch" for _, _, e in r.calls)


# ── шаг 4: неторговые факты (вахты) ──

def _watch_fact(key="drift_zone", state="IN", prev="OUT"):
    return {"id": 11, "producer": "watch", "symbol": "*MARKET*", "event": "watch_state_changed",
            "data": {"key": key, "state": state, "prev": prev, "title": "Зона дрейфа",
                     "text": "зона открылась", "detail": "гейт пропускает"}}


def test_watch_fact_goes_to_local_bus_and_never_trades():
    """Смена вахты — рыночный факт: сферы его видят, но сделки он не создаёт."""
    r = _Router()
    bot = _bot(r)
    inbox = CubeInbox(bot, allow=["breakout"])
    assert _run(inbox.handle_any(_watch_fact())) is True
    assert r.calls == []                                  # ни одного обращения к роутеру
    assert inbox.watch_events == 1
    log = bot.pair_context.get_event_log(limit=5)
    assert any(e["event"] == SphereEvent.WATCH_STATE_CHANGED for e in log)


def test_signal_fact_still_routed_through_handle_any():
    r = _Router()
    inbox = CubeInbox(_bot(r), allow=["breakout"])
    assert _run(inbox.handle_any(_fact())) is True
    assert len(r.calls) == 1


def test_unknown_fact_type_is_ignored_safely():
    r = _Router()
    inbox = CubeInbox(_bot(r), allow=["breakout"])
    f = dict(_fact(), event="оплата_подписки")
    assert _run(inbox.handle_any(f)) is False
    assert r.calls == []
