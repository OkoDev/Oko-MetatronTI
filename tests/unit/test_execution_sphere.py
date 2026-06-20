"""Тесты ExecutionSphere (Ф4) — оркестратор. Полный offline-прогон через FakeAdapter.

Проверяем: open (SIM/VST/guard), on_event (fill→store+ledger, pa=0→CloseIntent+shadow/callback),
полный жизненный цикл с классификацией exit, close/adjust_sl делегирование, cold_start,
reconcile-watchdog (store-open vs exchange-flat).
"""
import pytest

from core.execution.adapter import ExchangeAdapter
from core.execution.domain import (
    CloseResult, ExecMode, Fill, FillEvent, OrderRequest, OrderResult,
    Position, PositionEvent, LedgerEntry, LedgerEvent,
)
from core.execution.position_store import PositionStore
from core.execution.sphere import ExecutionSphere, CloseIntent

SYM = "XLM/USDT:USDT"


class FakeAdapter(ExchangeAdapter):
    """In-memory адаптер: пишет вызовы, отдаёт канонические данные."""
    name = "fake"

    def __init__(self):
        self.calls = []
        self.positions_by_account = {}      # account → list[Position]
        self.filled_orders = []             # для _resolve_exit_via_rest (гонка fill↔pa=0)

    async def place_bracket(self, req):
        self.calls.append(("place_bracket", req.symbol, req.direction, req.account))
        return OrderResult(success=True, symbol=req.symbol, direction=req.direction,
                           qty=req.qty, entry_price=req.entry_price, sl=req.sl, tp=req.tp,
                           account=req.account or 1, mode=req.mode, order_id="ord-1",
                           position_id="pid-1", leverage=req.leverage or 5,
                           notional_usdt=req.qty * req.entry_price)

    async def place_sl(self, symbol, side, sl, qty, account, position_id=None):
        self.calls.append(("place_sl", symbol, side, sl, account, position_id))
        return "sl-oid-1"

    async def place_tp(self, symbol, side, tp, qty, account, position_id=None):
        self.calls.append(("place_tp", symbol, side, tp, account))
        return "tp-oid-1"

    async def cancel(self, symbol, order_id, account):
        self.calls.append(("cancel", symbol, order_id, account))
        return True

    async def close_reduce_only(self, symbol, side, qty, account, position_id=None):
        self.calls.append(("close_reduce_only", symbol, side, qty, account, position_id))
        return CloseResult(success=True, symbol=symbol, position_id=position_id, status="MANUAL")

    async def set_leverage(self, symbol, side, leverage, account):
        return leverage

    async def get_max_leverage(self, symbol, side, account):
        return 20

    async def set_margin_mode(self, symbol, mode, account):
        return True

    async def get_positions(self, account):
        return list(self.positions_by_account.get(account, []))

    async def get_filled(self, symbol, account, limit=50):
        self.calls.append(("get_filled", symbol, account))
        return list(self.filled_orders)

    async def balances(self, account):
        return {"equity": 500.0, "available": 480.0, "used_margin": 20.0, "unrealized_pnl": 0.0}

    async def open_user_stream(self, account, on_event):
        return None

    def normalize_event(self, raw, account):
        return []


class FakeLedger:
    def __init__(self):
        self.fills = []
        self.ledgers = []
        self.initial = {}

    def on_fill_event(self, ev): self.fills.append(ev)
    def on_ledger_event(self, ev): self.ledgers.append(ev)
    def set_initial_equity(self, acc, eq): self.initial[acc] = eq


def _req(mode=ExecMode.VST, qty=100.0, sl=0.49, account=None):
    return OrderRequest(symbol=SYM, direction="LONG", entry_price=0.5, sl=sl, tp=0.6,
                        qty=qty, mode=mode, account=account, source="ote_nested")


def _open_fill(account=1):
    return FillEvent(account, Fill(symbol=SYM, side="BUY", pos_side="LONG", order_id="ord-1",
                                   order_type="MARKET", status="FILLED", is_reduce_only=False,
                                   avg_price=0.5, last_qty=100, total_qty=100, position_id="pid-1"))


def _close_fill(account=1, otype="STOP_MARKET", ap=0.49, rp=-1.0):
    return FillEvent(account, Fill(symbol=SYM, side="SELL", pos_side="LONG", order_id="ord-2",
                                   order_type=otype, status="FILLED", is_reduce_only=True,
                                   avg_price=ap, last_qty=100, total_qty=100,
                                   realized_pnl=rp, position_id="pid-1"))


def _pos_ev(account, pa, side="LONG"):
    return PositionEvent(account, Position(symbol=SYM, side=side, qty=abs(pa), account=account,
                                           entry=0.5))


@pytest.fixture
def sphere():
    return ExecutionSphere(FakeAdapter(), PositionStore(), ledger=FakeLedger())


# ── OPEN ──────────────────────────────────────────────────────────────────────
class TestOpen:
    @pytest.mark.asyncio
    async def test_sim_no_exchange(self):
        sp = ExecutionSphere(FakeAdapter(), PositionStore())
        res = await sp.open(_req(mode=ExecMode.SIM))
        assert res.success and res.order_id is None and res.mode == ExecMode.SIM
        assert sp._adapter.calls == []      # биржу не трогали

    @pytest.mark.asyncio
    async def test_vst_places_bracket(self, sphere):
        res = await sphere.open(_req(mode=ExecMode.VST))
        assert res.success and res.order_id == "ord-1"
        assert ("place_bracket", SYM, "LONG", 1) in sphere._adapter.calls

    @pytest.mark.asyncio
    async def test_guard_blocks_bad_sl(self, sphere):
        # SL выше входа для LONG → guard fail, биржа не вызвана
        res = await sphere.open(_req(sl=0.55))
        assert not res.success and "direction" in res.error
        assert sphere._adapter.calls == []


# ── on_event ────────────────────────────────────────────────────────────────
class TestOnEvent:
    @pytest.mark.asyncio
    async def test_open_fill_updates_store_and_ledger(self, sphere):
        await sphere.on_event(1, _open_fill())
        assert sphere.state(1) and sphere.state(1)[0].position_id == "pid-1"
        assert len(sphere._ledger.fills) == 1

    @pytest.mark.asyncio
    async def test_flat_returns_intent_shadow(self):
        # on_close=None → SHADOW (intent возвращается, но колбэк не зовётся)
        sp = ExecutionSphere(FakeAdapter(), PositionStore())
        await sp.on_event(1, _pos_ev(1, 100))
        intent = await sp.on_event(1, _pos_ev(1, 0))
        assert isinstance(intent, CloseIntent) and intent.reason == "ws_pa0"

    @pytest.mark.asyncio
    async def test_flat_fires_on_close_callback(self):
        fired = []
        async def cb(intent): fired.append(intent)
        sp = ExecutionSphere(FakeAdapter(), PositionStore(), on_close=cb)
        await sp.on_event(1, _pos_ev(1, 100))
        await sp.on_event(1, _pos_ev(1, 0))
        assert len(fired) == 1 and fired[0].symbol == SYM

    @pytest.mark.asyncio
    async def test_full_lifecycle_exit_classified(self, sphere):
        # открытие → close-fill (SL) застешен → pa=0 → intent несёт exit=SL@0.49
        await sphere.on_event(1, _open_fill())
        await sphere.on_event(1, _close_fill(otype="STOP_MARKET", ap=0.49, rp=-1.0))
        intent = await sphere.on_event(1, _pos_ev(1, 0))
        assert intent.exit is not None
        assert intent.exit.status == "SL" and intent.exit.exit_price == 0.49
        assert intent.exit.realized_pnl == -1.0

    @pytest.mark.asyncio
    async def test_funding_to_ledger(self, sphere):
        ev = LedgerEvent(1, LedgerEntry(account=1, ts=0, kind="FUNDING_FEE", amount=-0.5))
        await sphere.on_event(1, ev)
        assert len(sphere._ledger.ledgers) == 1

    @pytest.mark.asyncio
    async def test_flat_untracked_no_intent(self, sphere):
        # pa=0 без открытия → нет ложного close
        assert await sphere.on_event(1, _pos_ev(1, 0)) is None

    @pytest.mark.asyncio
    async def test_race_fill_after_pa0_rest_fallback(self, sphere):
        # ГОНКА: pa=0 приходит БЕЗ застешенного close-fill → дотянуть exit из REST по positionId
        await sphere.on_event(1, _open_fill())   # store знает pid-1
        sphere._adapter.filled_orders = [
            {"orderId": "c1", "positionID": "pid-1", "side": "SELL", "type": "TAKE_PROFIT_MARKET",
             "avgPrice": "0.62", "updateTime": 200, "profit": "2.5"}]
        intent = await sphere.on_event(1, _pos_ev(1, 0))   # pa=0 без stash
        assert intent is not None and intent.exit is not None
        assert intent.exit.exit_price == 0.62 and intent.exit.status == "TP"
        assert ("get_filled", SYM, 1) in sphere._adapter.calls

    @pytest.mark.asyncio
    async def test_race_no_match_exit_stays_none(self, sphere):
        # REST не нашёл закрывающий fill (чужой positionId) → exit None (db_writer НЕ закроет)
        await sphere.on_event(1, _open_fill())
        sphere._adapter.filled_orders = [
            {"orderId": "c2", "positionID": "OTHER", "side": "SELL", "type": "STOP_MARKET",
             "avgPrice": "0.49", "updateTime": 200}]
        intent = await sphere.on_event(1, _pos_ev(1, 0))
        assert intent is not None and intent.exit is None

    @pytest.mark.asyncio
    async def test_race_no_pid_no_guess(self, sphere):
        # CUTOVER pid-fix (б): позиция БЕЗ positionId → REST НЕ угадывает по symbol+side
        # (иначе хватает ЧУЖОЙ close-ордер → инверсия TP↔SL, fake-R класс). exit остаётся None.
        await sphere.on_event(1, _pos_ev(1, 100))   # позиция без position_id (seed через pa>0)
        sphere._adapter.filled_orders = [
            {"orderId": "x1", "positionID": "SOMEONE_ELSE", "side": "SELL", "type": "STOP_MARKET",
             "avgPrice": "0.49", "updateTime": 200}]
        intent = await sphere.on_event(1, _pos_ev(1, 0))
        assert intent is not None and intent.exit is None

    @pytest.mark.asyncio
    async def test_stash_takes_priority_over_rest(self, sphere):
        # Если close-fill УСПЕЛ застешиться (нет гонки) — REST не зовём
        await sphere.on_event(1, _open_fill())
        await sphere.on_event(1, _close_fill(otype="STOP_MARKET", ap=0.49, rp=-1.0))
        sphere._adapter.calls.clear()
        intent = await sphere.on_event(1, _pos_ev(1, 0))
        assert intent.exit.exit_price == 0.49        # из stash
        assert not any(c[0] == "get_filled" for c in sphere._adapter.calls)   # REST не звали


# ── close / adjust_sl ─────────────────────────────────────────────────────────
class TestCommands:
    @pytest.mark.asyncio
    async def test_close_delegates(self, sphere):
        await sphere.on_event(1, _open_fill())
        res = await sphere.close("pid-1", reason="manual")
        assert res.success
        assert any(c[0] == "close_reduce_only" and c[5] == "pid-1" for c in sphere._adapter.calls)

    @pytest.mark.asyncio
    async def test_close_unknown_position(self, sphere):
        res = await sphere.close("nope")
        assert not res.success and "not found" in res.error

    @pytest.mark.asyncio
    async def test_adjust_sl(self, sphere):
        await sphere.on_event(1, _open_fill())
        ok = await sphere.adjust_sl("pid-1", 0.48)
        assert ok and any(c[0] == "place_sl" for c in sphere._adapter.calls)


# ── cold_start / reconcile ─────────────────────────────────────────────────────
class TestColdStartReconcile:
    @pytest.mark.asyncio
    async def test_cold_start_seeds_store_and_equity(self, sphere):
        sphere._adapter.positions_by_account[1] = [
            Position(symbol=SYM, side="LONG", qty=100, account=1, entry=0.5)]
        out = await sphere.cold_start(1)
        assert len(out) == 1 and sphere.state(1)
        assert sphere.equity(1) == 500.0 and sphere._ledger.initial[1] == 500.0

    @pytest.mark.asyncio
    async def test_reconcile_flags_ws_drop(self, sphere):
        # Store думает OPEN, биржа пустая → кандидат на close (WS-drop)
        await sphere.on_event(1, _open_fill())
        sphere._adapter.positions_by_account[1] = []   # биржа флэт
        intents = await sphere.reconcile_account(1)
        assert len(intents) == 1 and intents[0].reason == "reconcile_ws_drop"
        assert intents[0].symbol == SYM

    @pytest.mark.asyncio
    async def test_reconcile_no_false_positive(self, sphere):
        await sphere.on_event(1, _open_fill())
        sphere._adapter.positions_by_account[1] = [
            Position(symbol=SYM, side="LONG", qty=100, account=1)]   # биржа подтверждает
        assert await sphere.reconcile_account(1) == []


class TestReconcileWatchdog:
    @pytest.mark.asyncio
    async def test_transient_flat_no_escalate(self, sphere):
        # 1 цикл флэта (<min_cycles=2) → НЕ эскалируем (транзиент/WS-лаг)
        await sphere.on_event(1, _open_fill())
        sphere._adapter.positions_by_account[1] = []          # биржа флэт
        esc = await sphere.reconcile_watchdog(1, min_cycles=2)
        assert esc == []
        assert sphere._store.is_open(1, SYM, "LONG")          # ещё в store (ждём подтверждения)

    @pytest.mark.asyncio
    async def test_escalates_after_n_cycles_with_rest_exit(self, sphere):
        # 2 цикла флэта подряд → escalate + дотянуть exit из REST + снять из store
        await sphere.on_event(1, _open_fill())
        sphere._adapter.positions_by_account[1] = []
        sphere._adapter.filled_orders = [
            {"orderId": "x", "positionID": "pid-1", "side": "SELL", "type": "STOP_MARKET",
             "avgPrice": "0.49", "updateTime": 100}]
        assert await sphere.reconcile_watchdog(1, min_cycles=2) == []   # 1-й цикл
        esc = await sphere.reconcile_watchdog(1, min_cycles=2)          # 2-й → escalate
        assert len(esc) == 1
        assert esc[0].exit is not None and esc[0].exit.exit_price == 0.49 and esc[0].exit.status == "SL"
        assert not sphere._store.is_open(1, SYM, "LONG")               # снят из store

    @pytest.mark.asyncio
    async def test_streak_resets_when_back_on_exchange(self, sphere):
        # флэт 1 цикл → потом биржа снова показывает позицию → счётчик сброшен (не эскалирует)
        await sphere.on_event(1, _open_fill())
        sphere._adapter.positions_by_account[1] = []
        await sphere.reconcile_watchdog(1, min_cycles=2)               # streak=1
        sphere._adapter.positions_by_account[1] = [
            Position(symbol=SYM, side="LONG", qty=100, account=1)]     # вернулась
        await sphere.reconcile_watchdog(1, min_cycles=2)              # сброс
        sphere._adapter.positions_by_account[1] = []                  # снова флэт
        esc = await sphere.reconcile_watchdog(1, min_cycles=2)        # streak=1 опять
        assert esc == []                                              # не эскалирует (сброшен)

    @pytest.mark.asyncio
    async def test_escalate_no_fill_exit_none(self, sphere):
        # биржа-флэт N циклов, но REST не нашёл fill → escalate с exit=None (db_writer не закроет)
        await sphere.on_event(1, _open_fill())
        sphere._adapter.positions_by_account[1] = []
        sphere._adapter.filled_orders = []
        await sphere.reconcile_watchdog(1, min_cycles=2)
        esc = await sphere.reconcile_watchdog(1, min_cycles=2)
        assert len(esc) == 1 and esc[0].exit is None
