"""Unit-тесты для core.exchange.position_parser (создан 27.05.2026)."""
from core.exchange.position_parser import (
    parse_position, parse_positions, by_symbol_side, by_symbol, ParsedPosition,
)


def _make_pos(symbol="BTC-USDT", qty=0.5, side="LONG", avg=70000.0, mark=69500.0,
              leverage=10, margin=350.0, pnl=-25.0):
    return {
        "symbol": symbol,
        "positionAmt": str(qty),
        "positionSide": side,
        "avgPrice": str(avg),
        "markPrice": str(mark),
        "leverage": str(leverage),
        "margin": str(margin),
        "unrealizedProfit": str(pnl),
    }


class TestParsePosition:
    def test_long_basic(self):
        pp = parse_position(_make_pos())
        assert pp is not None
        assert pp.symbol_bx == "BTC-USDT"
        assert pp.symbol_our == "BTC/USDT:USDT"
        assert pp.side == "LONG"
        assert pp.qty == 0.5
        assert pp.entry == 70000.0
        assert pp.mark == 69500.0
        assert pp.leverage == 10
        assert pp.margin == 350.0
        assert pp.notional == 0.5 * 69500.0

    def test_hedge_short_positive_amt(self):
        # КРИТИЧНО: в hedge mode SHORT имеет positionAmt > 0
        # Старый код "side = LONG if qty>0 else SHORT" давал ЛОЖНЫЙ LONG.
        # Новый — должен взять positionSide=SHORT.
        pp = parse_position(_make_pos(side="SHORT", qty=2.5))
        assert pp.side == "SHORT"
        assert pp.qty == 2.5

    def test_empty_position_returns_none(self):
        assert parse_position(_make_pos(qty=0)) is None

    def test_missing_symbol_returns_none(self):
        assert parse_position(_make_pos(symbol="")) is None

    def test_one_way_mode_fallback(self):
        # positionSide пустой (one-way mode) → fallback на знак qty
        p = _make_pos(side="")
        p["positionSide"] = ""
        pp = parse_position(p)
        assert pp.side == "LONG"  # qty=0.5 > 0

    def test_one_way_negative_qty_is_short(self):
        p = _make_pos(side="")
        p["positionSide"] = ""
        p["positionAmt"] = "-0.5"
        pp = parse_position(p)
        assert pp.side == "SHORT"
        assert pp.qty == 0.5  # abs

    def test_margin_estimated_when_missing(self):
        p = _make_pos(margin=0)
        del p["margin"]
        pp = parse_position(p)
        # margin = qty * entry / leverage = 0.5 * 70000 / 10 = 3500
        assert pp.margin == 3500.0


class TestByIndexHelpers:
    def test_by_symbol_side_hedge_independent(self):
        # LONG и SHORT по одной паре — две независимые записи
        pos_long  = parse_position(_make_pos(side="LONG", qty=0.3))
        pos_short = parse_position(_make_pos(side="SHORT", qty=0.7))
        idx = by_symbol_side([pos_long, pos_short])
        assert len(idx) == 2
        assert idx[("BTC/USDT:USDT", "LONG")].qty == 0.3
        assert idx[("BTC/USDT:USDT", "SHORT")].qty == 0.7

    def test_by_symbol_hedge_overwrites_last(self):
        # by_symbol теряет одну из позиций в hedge — это известное legacy поведение
        pos_long  = parse_position(_make_pos(side="LONG"))
        pos_short = parse_position(_make_pos(side="SHORT"))
        idx = by_symbol([pos_long, pos_short])
        assert len(idx) == 1


class TestParsePositionsRobustness:
    def test_empty_list(self):
        assert parse_positions([]) == []

    def test_filter_invalid(self):
        items = parse_positions([
            _make_pos(),
            _make_pos(qty=0),         # filtered
            _make_pos(symbol=""),     # filtered
        ])
        assert len(items) == 1
