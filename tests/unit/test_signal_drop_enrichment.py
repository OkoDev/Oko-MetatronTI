"""02.10 (дата-долг L1): запись отказа несёт цену и волатильность из шины.

Без них журнал `signal_drops` (905 тыс. строк) нечем мерить: не посчитать форвард сигнала и не
построить контроль той же волатильности (скилл research-verdict §0, §2A).
"""
import asyncio
import sqlite3

import pytest

from core.context.pair_context import PairContextBus, SphereEvent
from core.observability import decision_trace as dt


def _db(tmp_path) -> str:
    p = str(tmp_path / "d.db")
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE signal_drops (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, "
                  "signal_type TEXT, direction TEXT, strength INTEGER, gate_name TEXT, drop_reason TEXT, "
                  "features_json TEXT, dropped_at TEXT DEFAULT (datetime('now')), price REAL, "
                  "atr_pct REAL, tf TEXT, source TEXT)")
    return p


@pytest.fixture(autouse=True)
def _reset():
    dt._BATCH.clear()
    yield
    dt._BATCH.clear()
    dt._DB_PATH, dt._BUS = None, None


def _row(p):
    with sqlite3.connect(p) as c:
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM signal_drops ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None


def test_drop_carries_price_atr_tf_from_bus(tmp_path):
    bus = PairContextBus()
    sym = "BTC/USDT:USDT"
    bus.publish(sym, SphereEvent.OHLCV_UPDATED, {"tf": "15m", "rows": 200, "close": 50000.0,
                                                 "volume_24h": 1e9, "atr_pct": 0.84})
    dt.configure(_db(tmp_path), bus=bus)
    asyncio.new_event_loop().run_until_complete(
        dt.record_drop(symbol=sym, gate_name="min_sl_dist", drop_reason="слишком близко",
                       signal_type="radar_pump", direction="SHORT", strength=70,
                       features={"source": "radar"}))
    asyncio.new_event_loop().run_until_complete(dt._flush())
    r = _row(dt._DB_PATH)
    assert r["price"] == 50000.0 and r["atr_pct"] == 0.84 and r["tf"] == "15m"
    assert r["source"] == "radar" and r["gate_name"] == "min_sl_dist"


def test_drop_without_bus_still_records(tmp_path):
    """Шина не подключена — отказ всё равно пишется, поля пустые (не теряем строку)."""
    dt.configure(_db(tmp_path), bus=None)
    asyncio.new_event_loop().run_until_complete(
        dt.record_drop(symbol="ETH/USDT:USDT", gate_name="dedup", drop_reason="дубль"))
    asyncio.new_event_loop().run_until_complete(dt._flush())
    r = _row(dt._DB_PATH)
    assert r["symbol"] == "ETH/USDT:USDT" and r["price"] is None and r["atr_pct"] is None


def test_broken_bus_does_not_break_recording(tmp_path):
    """Сбой шины не роняет скан и не теряет запись."""
    class _Bad:
        def get(self, s):
            raise RuntimeError("шина недоступна")
    dt.configure(_db(tmp_path), bus=_Bad())
    asyncio.new_event_loop().run_until_complete(
        dt.record_drop(symbol="SOL/USDT:USDT", gate_name="rr_filter", drop_reason="rr<1"))
    asyncio.new_event_loop().run_until_complete(dt._flush())
    assert _row(dt._DB_PATH)["symbol"] == "SOL/USDT:USDT"


def test_bus_fills_atr_from_ohlcv_event():
    """ATR% доезжает в состояние пары и экспортируется наружу (иначе хаб и терминал его не увидят)."""
    bus = PairContextBus()
    sym = "ARB/USDT:USDT"
    bus.publish(sym, SphereEvent.OHLCV_UPDATED, {"tf": "15m", "rows": 100, "close": 1.5, "atr_pct": 1.23})
    assert bus.get(sym).atr_pct == 1.23
    assert bus.get_full_state(sym)["atr_pct"] == 1.23
