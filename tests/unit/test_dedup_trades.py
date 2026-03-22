"""
Тесты dedup открытых позиций (ARCH-11 TODO).

Проверяем что register_trade() блокирует новую сделку если по символу
уже есть открытая — независимо от направления.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.trade_simulator import TradeSimulator, STATUS_OPEN


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_recommendation(
    symbol: str = "BTCUSDT",
    direction: str = "LONG",
    entry: float = 50_000.0,
    sl: float = 49_000.0,
    tp: float = 53_000.0,
) -> Any:
    """Минимальная заглушка TradingRecommendation."""
    from core.signal_models import SignalDirection
    rec = MagicMock()
    rec.symbol = symbol
    rec.entry_price = entry
    rec.stop_loss = sl
    rec.take_profit = tp
    rec.tp1_price = None
    rec.direction = MagicMock()
    rec.direction.value = direction
    rec.overall_strength = 75
    rec.confidence = 0.75
    rec.timestamp = datetime.now(timezone.utc)
    rec.market_context = None
    rec.supporting_signals = []
    rec.sl_source = "atr"
    rec.tp_source = "pivot"
    rec.metadata = {"strategy_name": "reversal"}
    return rec


def _insert_open(db_path: str, symbol: str, direction: str) -> int:
    """Вставляет открытую сделку напрямую в БД."""
    created = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO simulated_trades
               (symbol, timeframe, signal_type, direction,
                entry_price, stop_loss, take_profit,
                strength, confidence, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (symbol, "15m", "wt_signal", direction,
             50_000.0, 49_000.0, 53_000.0,
             75, 0.75, STATUS_OPEN, created),
        )
        trade_id = cursor.lastrowid
        conn.commit()
    return trade_id


@pytest.fixture()
def sim(tmp_path):
    db_path = str(tmp_path / "test.db")
    return TradeSimulator(db_path=db_path)


# ── тесты ────────────────────────────────────────────────────────────────────

def test_dedup_blocks_opposite_direction(sim):
    """[01] LONG открыт → SHORT для той же пары блокируется."""
    _insert_open(sim.db_path, "BTCUSDT", "LONG")

    rec = _make_recommendation("BTCUSDT", "SHORT", sl=51_000.0, tp=47_000.0)
    result = sim.register_trade(rec)

    assert result is None, "SHORT должен быть заблокирован — открыт LONG"


def test_dedup_blocks_same_direction(sim):
    """[02] LONG открыт → второй LONG для той же пары блокируется."""
    _insert_open(sim.db_path, "BTCUSDT", "LONG")

    rec = _make_recommendation("BTCUSDT", "LONG")
    result = sim.register_trade(rec)

    assert result is None, "Дублирующий LONG должен быть заблокирован"


def test_dedup_allows_different_symbol(sim):
    """[03] LONG BTCUSDT открыт → LONG ETHUSDT проходит."""
    _insert_open(sim.db_path, "BTCUSDT", "LONG")

    rec = _make_recommendation("ETHUSDT", "LONG")
    result = sim.register_trade(rec)

    assert result is not None, "Другой символ должен проходить"


def test_dedup_allows_after_close(sim):
    """[04] После закрытия сделки — новая по тому же символу проходит."""
    trade_id = _insert_open(sim.db_path, "BTCUSDT", "LONG")
    sim.close_trade(trade_id, "TP", 53_000.0)

    rec = _make_recommendation("BTCUSDT", "SHORT", sl=51_000.0, tp=47_000.0)
    result = sim.register_trade(rec)

    assert result is not None, "После закрытия должна пройти новая сделка"


def test_dedup_first_trade_registers(sim):
    """[05] Первая сделка по символу всегда регистрируется."""
    rec = _make_recommendation("BTCUSDT", "LONG")
    result = sim.register_trade(rec)

    assert result is not None, "Первая сделка должна зарегистрироваться"


def test_dedup_short_blocks_long(sim):
    """[06] SHORT открыт → LONG блокируется."""
    _insert_open(sim.db_path, "SOLUSDT", "SHORT")

    rec = _make_recommendation("SOLUSDT", "LONG", sl=89_000.0, tp=105_000.0)
    result = sim.register_trade(rec)

    assert result is None, "LONG должен быть заблокирован — открыт SHORT"


def test_dedup_multiple_symbols_independent(sim):
    """[07] Каждый символ проверяется независимо."""
    _insert_open(sim.db_path, "BTCUSDT", "LONG")
    _insert_open(sim.db_path, "ETHUSDT", "SHORT")

    # Новый символ проходит
    rec_xrp = _make_recommendation("XRPUSDT", "LONG",
                                   entry=0.5, sl=0.48, tp=0.56)
    assert sim.register_trade(rec_xrp) is not None

    # Существующие символы блокируются
    rec_btc = _make_recommendation("BTCUSDT", "SHORT", sl=51_000.0, tp=47_000.0)
    assert sim.register_trade(rec_btc) is None

    rec_eth = _make_recommendation("ETHUSDT", "LONG",
                                   entry=3_000.0, sl=2_900.0, tp=3_300.0)
    assert sim.register_trade(rec_eth) is None
