"""
Регрессия FIX-STOPS (28.08.2026): `repair_missing_sl` не должен стирать
`exchange_sl_order_id` у сделки, чей стоп УЖЕ СРАБОТАЛ.

Повод — MOVR #58528. По логу: 06:18:06 стоп ...785 TRIGGERED и позиция закрылась,
06:18:27 `repair_missing_sl` записал в БД пустой ID («на бирже SL отсутствует»).
Сделка навсегда осталась в базе как «открытая без биржевого стопа». Из таких
записей и складывалась метрика «22% позиций без стопа», на которой строился
вывод «вся математика PF фикция».

Ключевой негативный тест — case 2: позиции на бирже НЕТ → ID сохраняется.
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.exchange.tsl_updater import repair_missing_sl   # noqa: E402


class FakeSim:
    def __init__(self, trades):
        self._trades = trades
        self.sl_writes = []          # (trade_id, value) — что реально записано в БД

    def get_open_trades(self):
        return self._trades

    def set_exchange_sl_order_id(self, trade_id, sl_order_id):
        self.sl_writes.append((trade_id, sl_order_id))


class FakeOM:
    def __init__(self, *, live_sl=None, qty=0.0, place_result="NEW-SL-1"):
        self._live_sl = live_sl
        self._qty = qty
        self._place_result = place_result
        self.place_calls = []

    async def get_sl_order_id(self, symbol, pos_side):
        return self._live_sl

    async def get_position_qty(self, symbol, pos_side):
        return self._qty

    async def place_sl_order(self, symbol, pos_side, sl_price, qty):
        self.place_calls.append((symbol, pos_side, sl_price, qty))
        return self._place_result


class FakeDC:
    def __init__(self, price):
        self._price = price

    async def get_current_price(self, symbol):
        return self._price


class FakeBot:
    def __init__(self, om, sim, price):
        self.order_executor = om
        self.trade_simulator = sim
        self.data_collector = FakeDC(price)


def _trade(**over):
    t = {"id": 58528, "symbol": "MOVR/USDT:USDT", "direction": "SHORT",
         "stop_loss": 0.7247, "exchange_order_id": "2092725484489019392",
         "exchange_sl_order_id": "2092761844636278785"}
    t.update(over)
    return t


def _run(om, sim, price=0.70):
    asyncio.run(repair_missing_sl(FakeBot(om, sim, price)))


def test_sl_alive_on_exchange_syncs_id():
    """SL на бирже есть, ID разошёлся → синхронизируем, стопа не трогаем."""
    sim = FakeSim([_trade(exchange_sl_order_id="OLD")])
    om = FakeOM(live_sl="LIVE-777", qty=100.0)
    _run(om, sim)
    assert sim.sl_writes == [(58528, "LIVE-777")]
    assert om.place_calls == []


def test_stop_triggered_position_gone_keeps_id():
    """🔴 ГЛАВНЫЙ НЕГАТИВНЫЙ ТЕСТ: стоп сработал, позиции нет → ID НЕ стирается."""
    sim = FakeSim([_trade()])
    om = FakeOM(live_sl=None, qty=0.0)
    _run(om, sim)
    assert sim.sl_writes == [], f"история стопа затёрта: {sim.sl_writes}"
    assert om.place_calls == [], "стоп ставится на несуществующую позицию"


def test_live_position_without_stop_is_repaired():
    """Позиция жива, стопа на бирже нет → stale чистится и ставится новый."""
    sim = FakeSim([_trade()])
    om = FakeOM(live_sl=None, qty=389.98)
    _run(om, sim)
    assert (58528, "") in sim.sl_writes, "stale ID не вычищен на живой позиции"
    assert (58528, "NEW-SL-1") in sim.sl_writes, "новый SL не записан"
    assert om.place_calls and om.place_calls[0][3] == 389.98


def test_sl_on_wrong_side_is_not_placed():
    """SHORT со стопом НИЖЕ цены — биржа отвергнет, ордер не шлём."""
    sim = FakeSim([_trade(stop_loss=0.60)])       # SHORT, стоп ниже цены 0.70
    om = FakeOM(live_sl=None, qty=389.98)
    _run(om, sim, price=0.70)
    assert om.place_calls == [], "перевёрнутый стоп ушёл на биржу"


def test_sim_only_trade_is_skipped():
    """SIM-сделка без биржевого ордера не трогается вовсе."""
    sim = FakeSim([_trade(exchange_order_id="")])
    om = FakeOM(live_sl=None, qty=0.0)
    _run(om, sim)
    assert sim.sl_writes == [] and om.place_calls == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
