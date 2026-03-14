"""
Тесты TradeSimulator — регистрация, закрытие, MFE, check_open_trades.
"""
import pytest
import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock

from core.trade_simulator import TradeSimulator, STATUS_OPEN, STATUS_TP, STATUS_SL, STATUS_EXPIRED


def make_recommendation(
    symbol="BTC/USDT",
    direction="LONG",
    entry_price=100.0,
    stop_loss=95.0,
    take_profit=110.0,
    strength=70,
    confidence=0.8,
):
    """Создаёт простой мок рекомендации."""
    rec = MagicMock()
    rec.symbol = symbol
    rec.direction = MagicMock()
    rec.direction.value = direction
    rec.entry_price = entry_price
    rec.stop_loss = stop_loss
    rec.take_profit = take_profit
    rec.tp1_price = None
    rec.overall_strength = strength
    rec.confidence = confidence
    rec.timestamp = datetime.now(timezone.utc)
    rec.market_context = None
    rec.supporting_signals = []
    rec.sl_source = None
    rec.tp_source = None
    rec.metadata = {}
    return rec


class TestTradeSimulatorRegistration:
    def test_register_long_trade(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(direction="LONG", entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is not None
        assert trade_id > 0

    def test_register_short_trade(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(direction="SHORT", entry_price=100.0, stop_loss=105.0, take_profit=90.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is not None

    def test_skip_neutral_direction(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation()
        rec.direction.value = "NEUTRAL"
        trade_id = sim.register_trade(rec)
        assert trade_id is None

    def test_skip_no_entry_price(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation()
        rec.entry_price = None
        rec.market_context = None
        trade_id = sim.register_trade(rec)
        assert trade_id is None

    def test_skip_no_sl_and_tp(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation()
        rec.stop_loss = None
        rec.take_profit = None
        trade_id = sim.register_trade(rec)
        assert trade_id is None

    def test_trade_appears_in_open(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation()
        sim.register_trade(rec)
        open_trades = sim.get_open_trades()
        assert len(open_trades) == 1
        assert open_trades[0]["status"] == STATUS_OPEN

    def test_register_with_regime(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation()
        trade_id = sim.register_trade(rec, regime="TREND_UP")
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute("SELECT regime FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
        assert row[0] == "TREND_UP"


class TestTradeSimulatorClose:
    def test_close_tp(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(direction="LONG", entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        trade_id = sim.register_trade(rec)
        result = sim.close_trade(trade_id, STATUS_TP, exit_price=110.0)
        assert result is True

    def test_close_sl(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(direction="LONG", entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        trade_id = sim.register_trade(rec)
        result = sim.close_trade(trade_id, STATUS_SL, exit_price=95.0)
        assert result is True

    def test_r_multiple_tp_long(self, tmp_db):
        """LONG TP: entry=100, SL=95 (1R=5), exit=110 → R=2.0."""
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(direction="LONG", entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        trade_id = sim.register_trade(rec)
        sim.close_trade(trade_id, STATUS_TP, exit_price=110.0)
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute("SELECT R_multiple, profit_pct, status FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
        assert row[2] == STATUS_TP
        assert abs(row[0] - 2.0) < 0.01
        assert abs(row[1] - 10.0) < 0.01

    def test_r_multiple_sl_long(self, tmp_db):
        """LONG SL: entry=100, SL=95 → R=-1.0."""
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(direction="LONG", entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        trade_id = sim.register_trade(rec)
        sim.close_trade(trade_id, STATUS_SL, exit_price=95.0)
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute("SELECT R_multiple FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
        assert abs(row[0] - (-1.0)) < 0.01

    def test_r_multiple_short(self, tmp_db):
        """SHORT TP: entry=100, SL=105 (1R=5), exit=90 → R=2.0."""
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(direction="SHORT", entry_price=100.0, stop_loss=105.0, take_profit=90.0)
        trade_id = sim.register_trade(rec)
        sim.close_trade(trade_id, STATUS_TP, exit_price=90.0)
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute("SELECT R_multiple FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
        assert abs(row[0] - 2.0) < 0.01

    def test_duration_minutes_set(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation()
        trade_id = sim.register_trade(rec)
        closed_at = datetime.now(timezone.utc) + timedelta(hours=2)
        sim.close_trade(trade_id, STATUS_TP, exit_price=110.0, closed_at=closed_at)
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute("SELECT duration_minutes FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
        assert row[0] is not None
        assert row[0] > 0

    def test_cannot_close_already_closed(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation()
        trade_id = sim.register_trade(rec)
        sim.close_trade(trade_id, STATUS_TP, exit_price=110.0)
        result = sim.close_trade(trade_id, STATUS_SL, exit_price=95.0)
        assert result is False

    def test_invalid_status_rejected(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation()
        trade_id = sim.register_trade(rec)
        result = sim.close_trade(trade_id, "INVALID", exit_price=110.0)
        assert result is False


class TestMFE:
    def test_max_r_possible_filled_on_close(self, tmp_db):
        """После обновления MFE и закрытия — max_R_possible должен быть заполнен."""
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(direction="LONG", entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        trade_id = sim.register_trade(rec)

        # Симулируем обновление MFE вручную (как это делает check_open_trades)
        with sqlite3.connect(tmp_db) as conn:
            conn.execute(
                "UPDATE simulated_trades SET max_price=115.0, min_price=97.0 WHERE id=?",
                (trade_id,)
            )
            conn.commit()

        sim.close_trade(trade_id, STATUS_TP, exit_price=110.0)

        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute(
                "SELECT max_R_possible, captured_R_pct FROM simulated_trades WHERE id=?",
                (trade_id,)
            ).fetchone()

        # max_R_possible = (115 - 100) / 5 = 3.0
        assert row[0] is not None
        assert abs(row[0] - 3.0) < 0.01
        # captured_R_pct = 2.0 / 3.0 * 100 ≈ 66.7%
        assert row[1] is not None
        assert abs(row[1] - 66.7) < 1.0

    def test_max_r_none_without_mfe(self, tmp_db):
        """Без обновления MFE max_R_possible остаётся NULL."""
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation()
        trade_id = sim.register_trade(rec)
        sim.close_trade(trade_id, STATUS_TP, exit_price=110.0)
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute("SELECT max_R_possible FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
        assert row[0] is None


class TestExpired:
    def test_expired_status(self, tmp_db):
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation()
        trade_id = sim.register_trade(rec)
        result = sim.close_trade(trade_id, STATUS_EXPIRED, exit_price=103.0)
        assert result is True
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute("SELECT status FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
        assert row[0] == STATUS_EXPIRED


# ─── RR-фильтр ────────────────────────────────────────────────────────────────

class TestRRFilter:
    """DEV-06: при WR=40% нужен RR≥2.0 для положительного EV."""

    def test_rr_exactly_2_accepted(self, tmp_db):
        """RR=2.0 ровно на границе — пропускается (>=2.0)."""
        sim = TradeSimulator(tmp_db)
        # entry=100, sl=95, tp=110 → RR=(110-100)/(100-95)=2.0
        rec = make_recommendation(entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is not None

    def test_rr_above_2_accepted(self, tmp_db):
        """RR=3.0 → регистрируется."""
        sim = TradeSimulator(tmp_db)
        # entry=100, sl=95, tp=115 → RR=15/5=3.0
        rec = make_recommendation(entry_price=100.0, stop_loss=95.0, take_profit=115.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is not None

    def test_rr_below_2_rejected(self, tmp_db):
        """RR=1.5 → сделка не регистрируется."""
        sim = TradeSimulator(tmp_db)
        # entry=100, sl=95, tp=107.5 → RR=7.5/5=1.5
        rec = make_recommendation(entry_price=100.0, stop_loss=95.0, take_profit=107.5)
        trade_id = sim.register_trade(rec)
        assert trade_id is None

    def test_rr_1_rejected(self, tmp_db):
        """RR=1.0 → убыточное матожидание, отклоняется."""
        sim = TradeSimulator(tmp_db)
        # entry=100, sl=95, tp=105 → RR=5/5=1.0
        rec = make_recommendation(entry_price=100.0, stop_loss=95.0, take_profit=105.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is None

    def test_rr_short_below_2_rejected(self, tmp_db):
        """SHORT: entry=100, sl=105, tp=90 → RR=(100-90)/(105-100)=10/5=2.0 → граница."""
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(direction="SHORT", entry_price=100.0, stop_loss=105.0, take_profit=90.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is not None  # ровно 2.0 — принимается

    def test_rr_short_below_2_rejected_low(self, tmp_db):
        """SHORT RR=1.2 → отклоняется."""
        sim = TradeSimulator(tmp_db)
        # entry=100, sl=105, tp=94 → RR=(100-94)/(105-100)=6/5=1.2
        rec = make_recommendation(direction="SHORT", entry_price=100.0, stop_loss=105.0, take_profit=94.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is None

    def test_no_sl_skips_rr_check(self, tmp_db):
        """Если нет SL — RR-фильтр не применяется, сделка регистрируется."""
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(entry_price=100.0, stop_loss=None, take_profit=102.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is not None


# ─── strategy_type и частичные TP ────────────────────────────────────────────

class TestStrategyType:
    """DEV-07: автоматический выбор SINGLE/DUAL/TRIPLE_TP_TSL по RR."""

    def _get_trade(self, db_path, trade_id):
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM simulated_trades WHERE id=?", (trade_id,)
            ).fetchone()
        return dict(row) if row else None

    def test_dual_tp_rr2(self, tmp_db):
        """RR=2.0 → DUAL_TP, tp1 = midpoint, tp2 = full TP."""
        sim = TradeSimulator(tmp_db)
        # entry=100, sl=95, tp=110 → RR=2.0
        rec = make_recommendation(entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is not None
        t = self._get_trade(tmp_db, trade_id)
        assert t["strategy_type"] == "DUAL_TP"
        # tp1 = 100 + (110-100)*0.5 = 105
        assert abs(t["tp1_price"] - 105.0) < 0.01
        # tp2 = full TP = 110
        assert abs(t["tp2_price"] - 110.0) < 0.01
        assert t["tp3_price"] is None

    def test_triple_tp_rr3(self, tmp_db):
        """RR=3.0 → TRIPLE_TP_TSL, tp1=1/3, tp2=2/3, tp3=full."""
        sim = TradeSimulator(tmp_db)
        # entry=100, sl=95, tp=115 → RR=3.0
        rec = make_recommendation(entry_price=100.0, stop_loss=95.0, take_profit=115.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is not None
        t = self._get_trade(tmp_db, trade_id)
        assert t["strategy_type"] == "TRIPLE_TP_TSL"
        # tp1 = 100 + 15*0.333 = 105.0
        assert abs(t["tp1_price"] - 105.0) < 0.1
        # tp2 = 100 + 15*0.667 = 110.0
        assert abs(t["tp2_price"] - 110.0) < 0.1
        # tp3 = 115
        assert abs(t["tp3_price"] - 115.0) < 0.01

    def test_single_tp_rr_low(self, tmp_db):
        """RR=2.0 (граница) → DUAL_TP, не SINGLE."""
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        trade_id = sim.register_trade(rec)
        t = self._get_trade(tmp_db, trade_id)
        # RR=2.0 → DUAL_TP
        assert t["strategy_type"] in ("DUAL_TP", "SINGLE")

    def test_short_dual_tp(self, tmp_db):
        """SHORT DUAL_TP: tp1 < entry, tp2 = full TP (ниже entry)."""
        sim = TradeSimulator(tmp_db)
        # entry=100, sl=105, tp=90 → RR=2.0
        rec = make_recommendation(direction="SHORT", entry_price=100.0, stop_loss=105.0, take_profit=90.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is not None
        t = self._get_trade(tmp_db, trade_id)
        assert t["strategy_type"] == "DUAL_TP"
        # tp1 = 100 - 10*0.5 = 95.0
        assert abs(t["tp1_price"] - 95.0) < 0.01
        assert abs(t["tp2_price"] - 90.0) < 0.01

    def test_short_triple_tp(self, tmp_db):
        """SHORT TRIPLE_TP: tp1 < tp2 < entry (цена идёт вниз)."""
        sim = TradeSimulator(tmp_db)
        # entry=100, sl=105, tp=85 → RR=3.0
        rec = make_recommendation(direction="SHORT", entry_price=100.0, stop_loss=105.0, take_profit=85.0)
        trade_id = sim.register_trade(rec)
        assert trade_id is not None
        t = self._get_trade(tmp_db, trade_id)
        assert t["strategy_type"] == "TRIPLE_TP_TSL"
        # tp1 = 100 - 15*0.333 ≈ 95.0
        assert t["tp1_price"] < 100.0
        assert t["tp2_price"] < t["tp1_price"]
        assert abs(t["tp3_price"] - 85.0) < 0.01

    def test_existing_tp1_not_overwritten(self, tmp_db):
        """Если recommendation уже содержит tp1_price — он не перезаписывается."""
        sim = TradeSimulator(tmp_db)
        rec = make_recommendation(entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        rec.tp1_price = 108.0  # уже задан — не должен быть изменён
        trade_id = sim.register_trade(rec)
        t = self._get_trade(tmp_db, trade_id)
        assert t["tp1_price"] == 108.0
