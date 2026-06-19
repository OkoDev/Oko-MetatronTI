"""Тест shadow-врезки (Ф4.1): сырой WS-msg → BingXAdapter.normalize → Sphere.on_event.

Повторяет ЭКВИВАЛЕНТ кода в exec_ws_integration.on_event (SPHERE-SHADOW feed):
    for ev in adapter.normalize_event(msg, acc): await sphere.on_event(acc, ev)
Доказывает: новый pipeline на СЫРЫХ WS-dict (реальный вход) корректно ведёт состояние и
выдаёт would-close. on_close=callback тут для проверки (в бою None → лог).
"""
import pytest

from core.execution.bingx_adapter import BingXAdapter
from core.execution.position_store import PositionStore
from core.execution.sphere import ExecutionSphere
from tests.unit.test_bingx_adapter_normalize import _StubOM


async def _feed(adapter, sphere, raw, account=1):
    intents = []
    for ev in adapter.normalize_event(raw, account):
        it = await sphere.on_event(account, ev)
        if it is not None:
            intents.append(it)
    return intents


@pytest.mark.asyncio
async def test_raw_ws_lifecycle_to_would_close():
    fired = []
    async def on_close(intent):
        fired.append(intent)

    adapter = BingXAdapter(_StubOM())
    store = PositionStore()
    sphere = ExecutionSphere(adapter, store, on_close=on_close)

    # 1) сырой open-fill (MARKET FILLED, не reduceOnly)
    await _feed(adapter, sphere, {"e": "ORDER_TRADE_UPDATE", "o": {
        "s": "XLM-USDT", "i": "1", "S": "BUY", "ps": "LONG", "o": "MARKET",
        "X": "FILLED", "z": "100", "ap": "0.5", "ro": False, "positionID": "pid-1"}})
    assert store.is_open(1, "XLM/USDT:USDT", "LONG")
    assert store.get(1, "XLM/USDT:USDT", "LONG").entry == 0.5

    # 2) сырой close-fill (STOP reduceOnly) → застешить exit
    await _feed(adapter, sphere, {"o": {
        "s": "XLM-USDT", "i": "2", "S": "SELL", "ps": "LONG", "o": "STOP_MARKET",
        "X": "FILLED", "z": "100", "ap": "0.49", "rp": "-1.0", "ro": True, "positionID": "pid-1"}})

    # 3) сырой ACCOUNT_UPDATE pa=0 → would-close с реальным exit
    intents = await _feed(adapter, sphere, {"e": "ACCOUNT_UPDATE", "a": {
        "P": [{"s": "XLM-USDT", "ps": "LONG", "pa": "0", "mt": "isolated"}]}})

    assert len(fired) == 1
    intent = fired[0]
    assert intent.reason == "ws_pa0"
    assert intent.exit is not None
    assert intent.exit.status == "SL" and intent.exit.exit_price == 0.49
    assert not store.is_open(1, "XLM/USDT:USDT", "LONG")   # снято из состояния


@pytest.mark.asyncio
async def test_raw_ws_open_only_no_close():
    adapter = BingXAdapter(_StubOM())
    sphere = ExecutionSphere(adapter, PositionStore())   # on_close=None → shadow
    intents = await _feed(adapter, sphere, {"o": {
        "s": "Q-USDT", "i": "9", "S": "BUY", "ps": "SHORT", "o": "MARKET",
        "X": "FILLED", "z": "50", "ap": "1.0", "ro": False}})
    assert intents == []                                  # открытие не порождает close
    assert sphere.state(1)                                # но состояние ведётся
