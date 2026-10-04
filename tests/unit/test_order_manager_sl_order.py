"""N7: порядок замены стопа в update_sl — окно, в котором позиция остаётся без стопа.

Прежний порядок (снять все SL → поставить новый) оставляет позицию голой, если
постановка не прошла: таймаут, 429, обрыв. Флаг `trading.sl_place_before_cancel`
переставляет шаги местами. Тесты фиксируют оба поведения, чтобы включение флага
было осознанным переключением, а не сюрпризом.
"""
from types import SimpleNamespace

import pytest

from core.exchange.order_manager import OrderManager

SYM, SIDE = "GRT/USDT:USDT", "LONG"


class _Cfg:
    def __init__(self, place_first=False):
        self._d = {
            "trading.execution_mode": "live",
            "trading.sl_place_before_cancel": place_first,
        }

    def get(self, key, default=None):
        return self._d.get(key, default)


def _om(place_first=False, *, place_result="NEW1", orders=None):
    om = OrderManager(_Cfg(place_first))
    om.calls = []

    async def _orders(symbol, force=False):
        return orders if orders is not None else [
            {"orderId": "OLD1", "type": "STOP_MARKET", "positionSide": "LONG"},
            {"orderId": "OLD2", "type": "STOP", "positionSide": "LONG"},
            {"orderId": "OTHER", "type": "STOP_MARKET", "positionSide": "SHORT"},
        ]

    async def _cancel(symbol, order_id):
        om.calls.append(("cancel", str(order_id)))
        return True

    async def _place(symbol, pos_side, price, qty, limit_buffer_pct=None):
        om.calls.append(("place", price))
        return place_result

    om.is_live = lambda: True
    om._get_open_orders_cached = _orders
    om.cancel_order = _cancel
    om.place_sl_order = _place
    return om


@pytest.mark.asyncio
async def test_legacy_order_cancels_before_placing():
    """Прежнее поведение сохранено как есть — флаг выключен по умолчанию."""
    om = _om(place_first=False)
    new_id = await om.update_sl(SYM, SIDE, "OLD1", 1.10, 10, old_sl_price=1.00)
    assert new_id == "NEW1"
    assert [c[0] for c in om.calls] == ["cancel", "cancel", "place"]


@pytest.mark.asyncio
async def test_place_first_puts_new_stop_before_removing_old():
    om = _om(place_first=True)
    new_id = await om.update_sl(SYM, SIDE, "OLD1", 1.10, 10, old_sl_price=1.00)
    assert new_id == "NEW1"
    # сначала постановка, только потом снятие — позиция ни мгновения не без стопа
    assert om.calls[0] == ("place", 1.10)
    assert [c[1] for c in om.calls[1:]] == ["OLD1", "OLD2"]


@pytest.mark.asyncio
async def test_place_first_keeps_old_stop_when_new_fails():
    """Главное, ради чего правка: биржа не приняла новый стоп — старый остаётся."""
    om = _om(place_first=True, place_result=None)
    new_id = await om.update_sl(SYM, SIDE, "OLD1", 1.10, 10, old_sl_price=1.00)
    assert new_id is None
    assert om.calls == [("place", 1.10)]          # ни одной отмены


@pytest.mark.asyncio
async def test_place_first_does_not_cancel_the_new_stop():
    """Новый ордер попал в список открытых — снять его было бы катастрофой."""
    om = _om(place_first=True, orders=[
        {"orderId": "OLD1", "type": "STOP_MARKET", "positionSide": "LONG"},
        {"orderId": "NEW1", "type": "STOP_MARKET", "positionSide": "LONG"},
    ])
    await om.update_sl(SYM, SIDE, "OLD1", 1.10, 10, old_sl_price=1.00)
    cancelled = [c[1] for c in om.calls if c[0] == "cancel"]
    assert cancelled == ["OLD1"] and "NEW1" not in cancelled


@pytest.mark.asyncio
async def test_other_side_stops_untouched():
    om = _om(place_first=True)
    await om.update_sl(SYM, SIDE, "OLD1", 1.10, 10, old_sl_price=1.00)
    assert "OTHER" not in [c[1] for c in om.calls if c[0] == "cancel"]


@pytest.mark.asyncio
async def test_tsl_rollback_guard_still_works():
    """DEV-160: SL не двигается «за цену» — ни в одном из режимов."""
    for flag in (False, True):
        om = _om(place_first=flag)
        assert await om.update_sl(SYM, SIDE, "OLD1", 0.90, 10, old_sl_price=1.00) is None
        assert om.calls == []


@pytest.mark.asyncio
async def test_min_move_guard_still_works():
    for flag in (False, True):
        om = _om(place_first=flag)
        assert await om.update_sl(SYM, SIDE, "OLD1", 1.0005, 10,
                                  old_sl_price=1.00, min_move_pct=0.1) is None
        assert om.calls == []
