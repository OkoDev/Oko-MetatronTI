"""Copy-DB тест close-path (Ф4.1 EXECUTION-REBUILD) — ОБЯЗАТЕЛЕН перед активацией (§9).

Правило эпика: close-path не трогать без теста на копии БД (инцидент 2026-04-07 ложного
закрытия). Здесь — реальная схема (SubscriptionManager) + реальный trade_simulator.close_trade
на временной БД. Проверяем: маппинг статусов, lookup OPEN биржевой сделки, идемпотентность,
полный путь ExecutionSphere → on_close → close_trade с реальным R.
"""
import sqlite3
from datetime import datetime, timezone

import pytest

from core.db.subscription_manager import SubscriptionManager
from core.trading.trade_simulator import TradeSimulator
from core.execution.db_writer import (
    build_close_applier, find_open_exchange_trade, intent_to_close_args,
)
from core.execution.domain import ExecMode, Fill, FillEvent, Position, PositionEvent
from core.execution.position_store import ExitInfo, PositionStore
from core.execution.sphere import CloseIntent, ExecutionSphere

SYM = "XLM/USDT:USDT"


def _intent(status="SL", price=0.49, rp=-1.0, exit_present=True, reason="ws_pa0"):
    ex = ExitInfo(symbol=SYM, side="LONG", account=1, exit_price=price, realized_pnl=rp,
                  status=status, order_type="STOP_MARKET", position_id="pid-1") if exit_present else None
    return CloseIntent(account=1, symbol=SYM, side="LONG", position_id="pid-1", exit=ex, reason=reason)


# ── 1. Маппинг статусов (чистая логика) ───────────────────────────────────────
class TestIntentMapping:
    def test_sl_passthrough(self):
        assert intent_to_close_args(_intent("SL", 0.49)) == ("SL", 0.49)

    def test_tp_passthrough(self):
        assert intent_to_close_args(_intent("TP", 0.6, rp=2.0)) == ("TP", 0.6)

    def test_tsl_passthrough(self):
        assert intent_to_close_args(_intent("TSL", 0.55, rp=1.0)) == ("TSL", 0.55)

    def test_liquidation_to_sl(self):
        # close_trade не знает LIQUIDATION → SL
        assert intent_to_close_args(_intent("LIQUIDATION", 0.40, rp=-5.0)) == ("SL", 0.40)

    def test_manual_by_pnl(self):
        assert intent_to_close_args(_intent("MANUAL", 0.52, rp=1.0))[0] == "TP"
        assert intent_to_close_args(_intent("MANUAL", 0.48, rp=-1.0))[0] == "SL"

    def test_none_when_no_exit(self):
        assert intent_to_close_args(_intent(exit_present=False)) is None

    def test_none_when_zero_price(self):
        assert intent_to_close_args(_intent("SL", 0.0)) is None


# ── 2. Copy-DB: реальная схема + реальный close_trade ─────────────────────────
@pytest.fixture
def db_with_open_trade(tmp_path):
    """Временная БД (реальная схема) с одной OPEN биржевой VST-сделкой."""
    db_path = str(tmp_path / "closepath.db")
    SubscriptionManager(db_path)   # создаёт таблицы
    TradeSimulator(db_path)        # догоняет ALTER-миграции (qty/position_id/execution_mode...)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO simulated_trades
               (symbol, direction, entry_price, stop_loss, take_profit, status,
                execution_mode, exchange_order_id, position_id, qty, original_sl,
                created_at, max_price, min_price)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (SYM, "LONG", 0.5, 0.49, 0.6, "OPEN",
             "VST", "ord-1", "pid-1", 100.0, 0.49, now, 0.55, 0.48),
        )
        conn.commit()
    return db_path


def _status_of(db_path, trade_id):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT status, exit_price, r_multiple FROM simulated_trades WHERE id=?",
                            (trade_id,)).fetchone()


class TestCloseApplierOnRealSchema:
    def test_find_open_exchange_trade(self, db_with_open_trade):
        tid = find_open_exchange_trade(db_with_open_trade, SYM, "LONG")
        assert tid == 1

    def test_find_skips_sim_only(self, tmp_path):
        db_path = str(tmp_path / "sim.db")
        SubscriptionManager(db_path)
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO simulated_trades (symbol, direction, entry_price, status, execution_mode, created_at) "
                "VALUES (?,?,?,?,?,?)", (SYM, "LONG", 0.5, "OPEN", "SIM", now))
            conn.commit()
        assert find_open_exchange_trade(db_path, SYM, "LONG") is None

    @pytest.mark.asyncio
    async def test_applier_closes_with_real_r(self, db_with_open_trade):
        sim = TradeSimulator(db_with_open_trade)
        on_close = build_close_applier(sim)
        await on_close(_intent("SL", 0.49, rp=-1.0))
        status, exit_price, r = _status_of(db_with_open_trade, 1)
        assert status == "SL"
        assert abs(exit_price - 0.49) < 1e-9
        # LONG R = (0.49-0.5)/|0.5-0.49| = -1.0
        assert abs(r - (-1.0)) < 1e-6

    @pytest.mark.asyncio
    async def test_applier_idempotent_no_open(self, db_with_open_trade):
        sim = TradeSimulator(db_with_open_trade)
        on_close = build_close_applier(sim)
        await on_close(_intent("SL", 0.49))           # закрыли
        await on_close(_intent("SL", 0.49))           # повтор — no-op (OPEN-строки уже нет)
        status, _, _ = _status_of(db_with_open_trade, 1)
        assert status == "SL"                          # не сломалось, осталось SL

    @pytest.mark.asyncio
    async def test_no_exit_does_not_close(self, db_with_open_trade):
        sim = TradeSimulator(db_with_open_trade)
        on_close = build_close_applier(sim)
        await on_close(_intent(exit_present=False, reason="reconcile_ws_drop"))
        status, _, _ = _status_of(db_with_open_trade, 1)
        assert status == "OPEN"                         # без exit НЕ закрываем (не угадываем)


# ── 3. Полный путь: ExecutionSphere → on_close → close_trade (на копии БД) ─────
class TestSphereToDbIntegration:
    @pytest.mark.asyncio
    async def test_pa0_closes_db_via_sphere(self, db_with_open_trade):
        from tests.unit.test_execution_sphere import FakeAdapter
        sim = TradeSimulator(db_with_open_trade)
        sp = ExecutionSphere(FakeAdapter(), PositionStore(),
                             on_close=build_close_applier(sim))
        # открытие (store знает позицию) → close-fill (stash SL@0.49) → pa=0 → close в БД
        await sp.on_event(1, FillEvent(1, Fill(symbol=SYM, side="BUY", pos_side="LONG",
            order_id="ord-1", order_type="MARKET", status="FILLED", is_reduce_only=False,
            avg_price=0.5, last_qty=100, total_qty=100, position_id="pid-1")))
        await sp.on_event(1, FillEvent(1, Fill(symbol=SYM, side="SELL", pos_side="LONG",
            order_id="ord-2", order_type="STOP_MARKET", status="FILLED", is_reduce_only=True,
            avg_price=0.49, last_qty=100, total_qty=100, realized_pnl=-1.0, position_id="pid-1")))
        await sp.on_event(1, PositionEvent(1, Position(symbol=SYM, side="LONG", qty=0, account=1)))
        status, exit_price, r = _status_of(db_with_open_trade, 1)
        assert status == "SL" and abs(exit_price - 0.49) < 1e-9 and abs(r + 1.0) < 1e-6
