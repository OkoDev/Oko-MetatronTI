"""Тесты BingXAdapter.normalize_event — единая точка парсинга WS (Ф3.2 EXECUTION-REBUILD).

normalize_event чистая (не трогает self._router) → тестируем со стаб-OrderManager.
Проверяем: порт существующего парсинга 2a/2b + ДОБАВЛЕННЫЕ поля (o.rp/o.n/LIQUIDATION/
FUNDING_FEE/mt), которые exec_ws_integration сейчас не использует (дизайн §5).
"""
import pytest

from core.execution.bingx_adapter import BingXAdapter
from core.execution.domain import (
    EquityEvent,
    FillEvent,
    LedgerEvent,
    ListenKeyExpiredEvent,
    LiquidationEvent,
    MarginModeEvent,
    PositionEvent,
)


class _StubRouter:
    def route(self, symbol):
        return 1


class _StubOM:
    def _get_router(self):
        return _StubRouter()


@pytest.fixture
def adapter():
    return BingXAdapter(_StubOM())


def _types(events):
    return [type(e).__name__ for e in events]


# ── ORDER_TRADE_UPDATE ────────────────────────────────────────────────────────
class TestOrderFills:
    def test_open_fill(self, adapter):
        raw = {"e": "ORDER_TRADE_UPDATE", "E": 1700000000000, "o": {
            "s": "XLM-USDT", "i": "123", "S": "BUY", "ps": "LONG", "o": "MARKET",
            "X": "FILLED", "x": "TRADE", "q": "100", "z": "100", "l": "100",
            "ap": "0.5", "rp": "0", "n": "0.02", "N": "USDT", "ro": False,
            "positionID": "pid-1"}}
        evs = adapter.normalize_event(raw, account=1)
        assert _types(evs) == ["FillEvent"]
        f = evs[0].fill
        assert f.symbol == "XLM/USDT:USDT"
        assert f.is_open_fill is True
        assert f.avg_price == 0.5 and f.fee == 0.02 and f.position_id == "pid-1"
        assert evs[0].account == 1

    def test_close_fill_realized(self, adapter):
        raw = {"o": {"s": "XLM-USDT", "i": "124", "S": "SELL", "ps": "LONG",
                     "o": "STOP_MARKET", "X": "FILLED", "ro": True, "ap": "0.49",
                     "z": "100", "rp": "-1.0", "n": "0.02", "N": "USDT", "positionID": "pid-1"}}
        evs = adapter.normalize_event(raw, account=2)
        assert _types(evs) == ["FillEvent"]
        f = evs[0].fill
        assert f.is_open_fill is False        # reduceOnly STOP
        assert f.realized_pnl == -1.0 and f.avg_price == 0.49
        assert evs[0].account == 2

    def test_liquidation_emits_two_events(self, adapter):
        raw = {"o": {"s": "POPCAT-USDT", "i": "125", "S": "SELL", "ps": "LONG",
                     "o": "LIQUIDATION", "X": "FILLED", "ap": "0.4", "z": "50"}}
        evs = adapter.normalize_event(raw, account=1)
        assert _types(evs) == ["FillEvent", "LiquidationEvent"]
        assert evs[1].symbol == "POPCAT/USDT:USDT" and evs[1].side == "LONG"

    def test_new_status_no_events(self, adapter):
        # NEW (нет fill) — не должно порождать FillEvent
        raw = {"o": {"s": "X-USDT", "i": "1", "S": "BUY", "ps": "LONG",
                     "o": "LIMIT", "X": "NEW"}}
        assert adapter.normalize_event(raw, account=1) == []

    def test_partially_filled_is_fill(self, adapter):
        raw = {"o": {"s": "X-USDT", "i": "1", "S": "BUY", "ps": "LONG", "o": "MARKET",
                     "X": "PARTIALLY_FILLED", "z": "50", "ap": "1.0", "ro": False}}
        evs = adapter.normalize_event(raw, account=1)
        assert _types(evs) == ["FillEvent"]
        assert evs[0].fill.is_open_fill is False   # частичный — не «полное открытие»


# ── ACCOUNT_UPDATE ────────────────────────────────────────────────────────────
class TestAccountUpdate:
    def test_flat_close(self, adapter):
        raw = {"e": "ACCOUNT_UPDATE", "E": 1700000000000, "a": {
            "m": "ORDER",
            "B": [{"a": "USDT", "wb": "500.5"}],
            "P": [{"s": "XLM-USDT", "ps": "LONG", "pa": "0", "ep": "0", "up": "0", "mt": "isolated"}]}}
        evs = adapter.normalize_event(raw, account=1)
        assert _types(evs) == ["EquityEvent", "PositionEvent", "MarginModeEvent"]
        eq, pe, mm = evs
        assert eq.equity == 500.5
        assert pe.position.is_flat is True and pe.position.qty == 0.0
        assert mm.margin_mode == "isolated"

    def test_open_position(self, adapter):
        raw = {"a": {"m": "ORDER", "B": [{"a": "USDT", "wb": "499.0"}],
                     "P": [{"s": "XLM-USDT", "ps": "LONG", "pa": "100", "ep": "0.5",
                            "up": "3.2", "mt": "isolated"}]}}
        evs = adapter.normalize_event(raw, account=1)
        assert "PositionEvent" in _types(evs)
        pe = [e for e in evs if isinstance(e, PositionEvent)][0]
        assert pe.position.qty == 100.0 and pe.position.entry == 0.5
        assert pe.position.upnl == 3.2 and pe.position.is_flat is False

    def test_funding_fee_ledger(self, adapter):
        raw = {"a": {"m": "FUNDING_FEE",
                     "B": [{"a": "USDT", "wb": "498.5", "bc": "-0.5"}], "P": []}}
        evs = adapter.normalize_event(raw, account=2)
        assert "LedgerEvent" in _types(evs)
        le = [e for e in evs if isinstance(e, LedgerEvent)][0]
        assert le.entry.kind == "FUNDING_FEE" and le.entry.amount == -0.5
        assert le.account == 2

    def test_cross_margin_mode_event(self, adapter):
        raw = {"a": {"P": [{"s": "Q-USDT", "ps": "SHORT", "pa": "10", "mt": "cross"}]}}
        evs = adapter.normalize_event(raw, account=1)
        mm = [e for e in evs if isinstance(e, MarginModeEvent)][0]
        assert mm.margin_mode == "cross" and mm.symbol == "Q/USDT:USDT"

    def test_skip_bad_position(self, adapter):
        # ps пустой → не позиция
        raw = {"a": {"P": [{"s": "X-USDT", "ps": "", "pa": "1"}]}}
        assert adapter.normalize_event(raw, account=1) == []


# ── listenKey / прочее ────────────────────────────────────────────────────────
class TestMisc:
    def test_listen_key_expired(self, adapter):
        raw = {"e": "listenKeyExpired", "listenKey": "abc123"}
        evs = adapter.normalize_event(raw, account=1)
        assert _types(evs) == ["ListenKeyExpiredEvent"]
        assert evs[0].listen_key == "abc123"

    def test_empty_and_garbage(self, adapter):
        assert adapter.normalize_event({}, account=1) == []
        assert adapter.normalize_event(None, account=1) == []
        assert adapter.normalize_event({"e": "SOMETHING_ELSE"}, account=1) == []
