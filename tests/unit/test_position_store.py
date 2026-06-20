"""Тесты PositionStore — единственный владелец состояния позиций (Ф3.3 EXECUTION-REBUILD).

Проверяем: WS-истина (open/upsert/flat-триггер), exit-stash для классификации close,
hedge-aware ключ, cold-start, staleness-watchdog.
"""
import pytest

from core.execution.domain import Fill, FillEvent, Position, PositionEvent
from core.execution.position_store import PositionStore, classify_exit


def _pos_event(account, sym, side, pa, entry=0.5, mt="isolated"):
    return PositionEvent(account, Position(symbol=sym, side=side, qty=abs(pa), account=account,
                                           entry=entry or None, margin_mode=mt))


def _fill(account, sym, pos_side, *, ro, otype, ap, rp=0.0, pid=None, status="FILLED", qty=100.0):
    return FillEvent(account, Fill(
        symbol=sym, side=("SELL" if ro else "BUY"), pos_side=pos_side, order_id="o1",
        order_type=otype, status=status, is_reduce_only=ro, avg_price=ap,
        last_qty=qty, total_qty=qty, realized_pnl=rp, position_id=pid))


SYM = "XLM/USDT:USDT"


class TestClassifyExit:
    def test_stop_to_sl(self):
        assert classify_exit("STOP_MARKET") == "SL"
        assert classify_exit("STOP") == "SL"

    def test_tp(self):
        assert classify_exit("TAKE_PROFIT_MARKET") == "TP"

    def test_trailing_to_tsl(self):
        assert classify_exit("TRAILING_STOP_MARKET") == "TSL"

    def test_liquidation(self):
        assert classify_exit("LIQUIDATION") == "LIQUIDATION"

    def test_market_by_pnl(self):
        assert classify_exit("MARKET", realized_pnl=5.0) == "TP"
        assert classify_exit("MARKET", realized_pnl=-2.0) == "SL"


class TestStateLifecycle:
    def test_open_upsert(self):
        st = PositionStore()
        assert st.apply_position(_pos_event(1, SYM, "LONG", 100)) is None
        p = st.get(1, SYM, "LONG")
        assert p is not None and p.qty == 100 and not p.is_flat
        assert st.is_open(1, SYM, "LONG")

    def test_flat_returns_closed_position(self):
        st = PositionStore()
        st.apply_position(_pos_event(1, SYM, "LONG", 100))
        closed = st.apply_position(_pos_event(1, SYM, "LONG", 0))
        assert closed is not None and closed.side == "LONG"   # триггер close для Sphere
        assert not st.is_open(1, SYM, "LONG")                 # удалена из состояния

    def test_flat_idempotent_when_untracked(self):
        st = PositionStore()
        # pa=0 по неизвестной позиции → None (не плодим ложный close)
        assert st.apply_position(_pos_event(1, SYM, "LONG", 0)) is None

    def test_hedge_independent_sides(self):
        st = PositionStore()
        st.apply_position(_pos_event(1, SYM, "LONG", 100))
        st.apply_position(_pos_event(1, SYM, "SHORT", 50))
        # закрытие LONG не трогает SHORT
        st.apply_position(_pos_event(1, SYM, "LONG", 0))
        assert not st.is_open(1, SYM, "LONG")
        assert st.is_open(1, SYM, "SHORT")

    def test_account_isolation(self):
        st = PositionStore()
        st.apply_position(_pos_event(1, SYM, "LONG", 100))
        st.apply_position(_pos_event(2, SYM, "LONG", 200))
        assert len(st.positions(1)) == 1 and len(st.positions(2)) == 1
        assert st.get(2, SYM, "LONG").qty == 200


class TestFillEnrichment:
    def test_open_fill_sets_entry_and_pid(self):
        st = PositionStore()
        st.apply_position(_pos_event(1, SYM, "LONG", 100, entry=0.0))
        st.apply_fill(_fill(1, SYM, "LONG", ro=False, otype="MARKET", ap=0.5, pid="pid-1"))
        p = st.get(1, SYM, "LONG")
        assert p.entry == 0.5 and p.position_id == "pid-1"

    def test_open_fill_creates_position_if_absent(self):
        st = PositionStore()
        st.apply_fill(_fill(1, SYM, "LONG", ro=False, otype="MARKET", ap=0.5, pid="pid-1"))
        assert st.is_open(1, SYM, "LONG")

    def test_position_id_preserved_on_upsert(self):
        st = PositionStore()
        st.apply_fill(_fill(1, SYM, "LONG", ro=False, otype="MARKET", ap=0.5, pid="pid-1"))
        # последующий pa-апдейт без positionId не должен стереть известный pid
        st.apply_position(_pos_event(1, SYM, "LONG", 100))
        assert st.get(1, SYM, "LONG").position_id == "pid-1"

    def test_close_fill_stash_and_take(self):
        st = PositionStore()
        st.apply_position(_pos_event(1, SYM, "LONG", 100))
        st.apply_fill(_fill(1, SYM, "LONG", ro=True, otype="STOP_MARKET", ap=0.49, rp=-1.0, pid="pid-1"))
        ex = st.take_exit(1, SYM, "LONG")
        assert ex is not None and ex.status == "SL" and ex.exit_price == 0.49 and ex.realized_pnl == -1.0
        # take извлекает (повторно None)
        assert st.take_exit(1, SYM, "LONG") is None

    def test_hedge_retry_close_stashes_exit_not_open(self):
        # Находка shadow: close со снятым reduceOnly (BUY+SHORT MARKET ro=false) НЕ должен
        # трактоваться как открытие — должен застешить ExitInfo (иначе WOULD CLOSE = "? @ ?").
        st = PositionStore()
        st.apply_position(_pos_event(1, SYM, "SHORT", 100))
        f = FillEvent(1, Fill(symbol=SYM, side="BUY", pos_side="SHORT", order_id="o1",
                              order_type="MARKET", status="FILLED", is_reduce_only=False,
                              avg_price=0.49, last_qty=100, total_qty=100, realized_pnl=2.0,
                              position_id="pid-1"))
        st.apply_fill(f)
        ex = st.take_exit(1, SYM, "SHORT")
        assert ex is not None and ex.exit_price == 0.49      # застешен как close
        assert ex.status == "TP"                              # MARKET + rp>=0 → TP

    def test_by_position_id(self):
        st = PositionStore()
        st.apply_fill(_fill(1, SYM, "LONG", ro=False, otype="MARKET", ap=0.5, pid="pid-9"))
        assert st.by_position_id("pid-9") is not None

    def test_set_position_id_backfill(self):
        # WS open-fill не несёт positionId → backfill из REST-снимка
        st = PositionStore()
        st.apply_position(_pos_event(1, SYM, "LONG", 100))   # pid=None
        assert st.get(1, SYM, "LONG").position_id is None
        assert st.set_position_id(1, SYM, "LONG", "pid-x") is True
        assert st.get(1, SYM, "LONG").position_id == "pid-x"
        # не перезаписывает уже заданный
        assert st.set_position_id(1, SYM, "LONG", "pid-y") is False
        assert st.get(1, SYM, "LONG").position_id == "pid-x"
        # нет позиции → False
        assert st.set_position_id(1, "Q/USDT:USDT", "LONG", "p") is False


class TestColdStartAndStaleness:
    def test_init_account_seeds_open(self):
        st = PositionStore()
        snap = [Position(symbol=SYM, side="LONG", qty=100, account=1, entry=0.5),
                Position(symbol="Q/USDT:USDT", side="SHORT", qty=0, account=1)]  # flat — не сидим
        st.init_account(1, snap)
        assert st.is_open(1, SYM, "LONG")
        assert not st.is_open(1, "Q/USDT:USDT", "SHORT")

    def test_init_account_resets_prev(self):
        st = PositionStore()
        st.apply_position(_pos_event(1, SYM, "LONG", 100))
        st.init_account(1, [])   # cold-start пустой → состояние аккаунта очищено
        assert st.positions(1) == []

    def test_staleness_none_then_value(self):
        st = PositionStore()
        assert st.staleness(1) is None
        st.apply_position(_pos_event(1, SYM, "LONG", 100))
        s = st.staleness(1)
        assert s is not None and s >= 0.0
