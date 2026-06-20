"""Copy-DB тест: close_trade считает R/profit от actual_entry_price (РЕАЛЬНЫЙ филл),
не от сигнальной entry_price (2-й фронт лжи метрик, 20.06 OTE-свод).

Реальная схема (SubscriptionManager+TradeSimulator миграции) + реальный close_trade.
"""
import sqlite3
from datetime import datetime, timezone

import pytest

from core.db.subscription_manager import SubscriptionManager
from core.trading.trade_simulator import TradeSimulator

SYM = "JOTCHUA/USDT:USDT"


def _make_db(tmp_path, *, entry_signal, actual_entry):
    db = str(tmp_path / "aep.db")
    SubscriptionManager(db)
    TradeSimulator(db)   # ALTER-миграции (actual_entry_price/qty/...)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db) as c:
        c.execute(
            """INSERT INTO simulated_trades
               (symbol, direction, entry_price, actual_entry_price, stop_loss, original_sl,
                take_profit, status, execution_mode, exchange_order_id, qty, created_at,
                max_price, min_price)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (SYM, "LONG", entry_signal, actual_entry, 97.0, 97.0, 110.0, "OPEN",
             "VST", "ord-1", 10.0, now, 104.0, 96.0),
        )
        c.commit()
    return db


def _r(db, tid=1):
    with sqlite3.connect(db) as c:
        return c.execute("SELECT status, r_multiple, profit_pct FROM simulated_trades WHERE id=?",
                         (tid,)).fetchone()


class TestActualEntryPriceR:
    def test_r_from_actual_fill_not_signal(self, tmp_path):
        # сигнал entry=100, РЕАЛЬНЫЙ филл=98 (вошли ниже на 2%), SL=97, выход 103
        db = _make_db(tmp_path, entry_signal=100.0, actual_entry=98.0)
        TradeSimulator(db).close_trade(1, "TSL", 103.0)
        status, r, pp = _r(db)
        # от ФАКТА: 1R=|98-97|=1, R=(103-98)/1=+5.0 ; от сигнала было бы +1.0
        assert abs(r - 5.0) < 0.05, f"R={r} — должен быть ~5.0 (от actual 98), не ~1.0 (от сигнала 100)"
        assert abs(pp - (103 - 98) / 98 * 100) < 0.1   # profit% тоже от actual

    def test_fallback_to_signal_when_actual_null(self, tmp_path):
        # actual NULL (исторические/SIM) → R от сигнальной entry=100
        db = _make_db(tmp_path, entry_signal=100.0, actual_entry=None)
        TradeSimulator(db).close_trade(1, "TSL", 103.0)
        status, r, pp = _r(db)
        # от сигнала: 1R=|100-97|=3, R=(103-100)/3=+1.0
        assert abs(r - 1.0) < 0.05, f"R={r} — fallback на сигнал 100 должен дать ~1.0"

    def test_actual_zero_falls_back(self, tmp_path):
        # actual=0 (не захвачен) → fallback на сигнал
        db = _make_db(tmp_path, entry_signal=100.0, actual_entry=0.0)
        TradeSimulator(db).close_trade(1, "TSL", 103.0)
        _, r, _ = _r(db)
        assert abs(r - 1.0) < 0.05
