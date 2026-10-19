# -*- coding: utf-8 -*-
"""
Замер DEV-244: единое правило `finalize_limit_entry` даёт ровно тот исход, что давали
разъехавшиеся копии в лупах. Таблица истинности по (источник × есть ли биржевой ордер).

Источники берём РЕАЛЬНЫЕ из конфига (не мок политики), чтобы проверялась и связка с
`source_registry.trades_on_exchange`:
    impulse_fib      → live  (биржа ВКЛ)
    impulse_fib_15m  → off   (биржа ВЫКЛ, пауза)
"""
import sqlite3

import pytest

from core.execution.limit_lifecycle import finalize_limit_entry
from core.trading.source_registry import trades_on_exchange


class _Res:
    """Минимальный двойник SubmitResult."""
    def __init__(self, trade_id, exchange_order_id=None):
        self.trade_id = trade_id
        self.exchange_order_id = exchange_order_id


def _db(tmp_path):
    db = str(tmp_path / "ll.db")
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE simulated_trades(
        id INTEGER PRIMARY KEY, status TEXT, exchange_order_id TEXT,
        actual_entry_price REAL, original_sl REAL, stop_loss REAL, tsl_activated INTEGER)""")
    c.commit(); c.close()
    return db


def _ins(db, tid, oid=None, stop_loss=10.0, original_sl=10.0, actual=None):
    c = sqlite3.connect(db)
    c.execute("INSERT INTO simulated_trades(id,status,exchange_order_id,actual_entry_price,"
              "original_sl,stop_loss,tsl_activated) VALUES(?,?,?,?,?,?,0)",
              (tid, "OPEN", oid, actual, original_sl, stop_loss))
    c.commit(); c.close()


def _status(db, tid):
    c = sqlite3.connect(db)
    r = c.execute("SELECT status FROM simulated_trades WHERE id=?", (tid,)).fetchone()
    c.close()
    return r[0] if r else None


# Предусловие замера: режимы источников те, на которых строится таблица.
def test_source_modes_assumed():
    assert trades_on_exchange("impulse_fib") is True
    assert trades_on_exchange("impulse_fib_15m") is False


def test_no_trade_id_does_nothing(tmp_path):
    db = _db(tmp_path)
    assert finalize_limit_entry(db, _Res(None), "impulse_fib", tag="T") == "none"


def test_live_no_oid_cancelled(tmp_path):
    """Биржа ВКЛ, ордер не ушёл → CANCELLED (защита TSL, ARB #58349) — как старая копия."""
    db = _db(tmp_path); _ins(db, 1, oid=None)
    assert finalize_limit_entry(db, _Res(1, None), "impulse_fib", tag="T") == "cancelled"
    assert _status(db, 1) == "CANCELLED"


def test_live_with_oid_pending(tmp_path):
    """Биржа ВКЛ, ордер есть → PENDING (ждём биржевой fill)."""
    db = _db(tmp_path); _ins(db, 1, oid="EX123")
    assert finalize_limit_entry(db, _Res(1, "EX123"), "impulse_fib", tag="T") == "pending"
    assert _status(db, 1) == "PENDING_ENTRY"


def test_off_no_oid_pending_sim(tmp_path):
    """Биржа ВЫКЛ (пауза), oid пуст ПО ЗАМЫСЛУ → PENDING-sim (судит свеча) — ядро DEV-243."""
    db = _db(tmp_path); _ins(db, 1, oid=None)
    assert finalize_limit_entry(db, _Res(1, None), "impulse_fib_15m", tag="T") == "pending_sim"
    assert _status(db, 1) == "PENDING_ENTRY"


def test_off_does_not_cancel(tmp_path):
    """Ключ DEV-243: off-источник НИКОГДА не уходит в CANCELLED из-за пустого oid."""
    db = _db(tmp_path); _ins(db, 1, oid=None)
    out = finalize_limit_entry(db, _Res(1, None), "impulse_fib_15m", tag="T")
    assert out != "cancelled"
    assert _status(db, 1) != "CANCELLED"


def test_race_restore_stop_from_original(tmp_path):
    """Окно гонки: TSL сдвинул стоп до перевода в PENDING → восстановить из original_sl."""
    db = _db(tmp_path)
    _ins(db, 1, oid="EX1", stop_loss=11.5, original_sl=10.0, actual=None)  # стоп испорчен TSL
    finalize_limit_entry(db, _Res(1, "EX1"), "impulse_fib", tag="T")
    c = sqlite3.connect(db)
    sl, tsl = c.execute("SELECT stop_loss, tsl_activated FROM simulated_trades WHERE id=1").fetchone()
    c.close()
    assert sl == 10.0 and tsl == 0


def test_filled_row_not_touched(tmp_path):
    """Реальную позицию (actual_entry заполнен) не трогаем ни стопом, ни статусом."""
    db = _db(tmp_path)
    _ins(db, 1, oid="EX1", stop_loss=11.5, original_sl=10.0, actual=10.2)
    finalize_limit_entry(db, _Res(1, "EX1"), "impulse_fib", tag="T")
    c = sqlite3.connect(db)
    sl = c.execute("SELECT stop_loss FROM simulated_trades WHERE id=1").fetchone()[0]
    c.close()
    assert sl == 11.5  # original_sl-restore не сработал — позиция живая
