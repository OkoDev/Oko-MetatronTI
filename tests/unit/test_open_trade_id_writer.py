"""N22: `PairState.open_trade_id` — поле, которое читали все, а писал никто.

Обработчик стоял только на TSL_MOVED, то есть поле заполнялось лишь когда сработает
трейлинг. У сделок без +1R трейлинг не активируется никогда — и поле было пустым
у всех 585 пар при живых позициях. Из-за этого молчали три подписки-заглушки
(дивергенция→выход, закрытие→каскад, пивот→выход) и не работал приоритет живой цены.
"""
import pytest

from core.context.pair_context import PairContextBus, SphereEvent

SYM, OTHER = "GRT/USDT:USDT", "LDO/USDT:USDT"


def _bus():
    return PairContextBus()


def test_position_opened_sets_trade_id():
    bus = _bus()
    bus.publish(SYM, SphereEvent.POSITION_OPENED, {"trade_id": 777, "side": "LONG"})
    assert bus.get(SYM).open_trade_id == 777


def test_position_closed_clears_it():
    bus = _bus()
    bus.publish(SYM, SphereEvent.POSITION_OPENED, {"trade_id": 777})
    bus.publish(SYM, SphereEvent.POSITION_CLOSED, {})
    st = bus.get(SYM)
    assert st.open_trade_id is None and st.tsl_active is False


def test_tsl_moved_still_works():
    """Прежнее поведение не потеряно: трейлинг тоже проставляет id."""
    bus = _bus()
    bus.publish(SYM, SphereEvent.TSL_MOVED, {"trade_id": 42})
    st = bus.get(SYM)
    assert st.open_trade_id == 42 and st.tsl_active is True


# ── сверка по снапшоту: после рестарта события уже не придут ─────────────

def test_snapshot_restores_after_restart():
    """Бот перезапущен, сделка открыта раньше — POSITION_OPENED не придёт никогда."""
    bus = _bus()
    bus.update(SYM, tick_price=1.0)              # пара в шине есть, поля пустые
    assert bus.get(SYM).open_trade_id is None
    bus.set_open_trades([{"id": 555, "symbol": SYM}])
    assert bus.get(SYM).open_trade_id == 555


def test_snapshot_clears_closed_trade():
    bus = _bus()
    bus.publish(SYM, SphereEvent.POSITION_OPENED, {"trade_id": 1})
    bus.publish(OTHER, SphereEvent.POSITION_OPENED, {"trade_id": 2})
    bus.set_open_trades([{"id": 1, "symbol": SYM}])     # вторая закрылась
    assert bus.get(SYM).open_trade_id == 1
    assert bus.get(OTHER).open_trade_id is None


def test_empty_snapshot_clears_everything():
    bus = _bus()
    bus.publish(SYM, SphereEvent.POSITION_OPENED, {"trade_id": 1})
    bus.set_open_trades([])
    assert bus.get(SYM).open_trade_id is None


def test_snapshot_ignores_unknown_pairs_without_crash():
    bus = _bus()
    bus.set_open_trades([{"id": 9, "symbol": "НЕТ/ТАКОЙ:USDT"}, {"id": 10}])
    assert bus.open_trades_snapshot()[0]          # снапшот сохранён, падения нет


def test_snapshot_still_serves_dashboard():
    """Починка поля не должна сломать то, ради чего снапшот существует."""
    bus = _bus()
    bus.set_open_trades([{"id": 1, "symbol": SYM, "direction": "LONG", "qty": 5}])
    rows, ts = bus.open_trades_snapshot()
    assert rows[0]["id"] == 1 and rows[0]["symbol"] == SYM and ts is not None
