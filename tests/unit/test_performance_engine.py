"""
Тесты для PerformanceEngine — статистика по simulated_trades.
Используют in-memory SQLite, чтобы не зависеть от продакшн-БД.
"""
import sqlite3
import pytest
from core.trading.performance_engine import PerformanceEngine


# ──────────────────────────────────────────────────────────────────────────────
# Фикстура: создаём временную БД с нужной схемой и тестовыми данными
# ──────────────────────────────────────────────────────────────────────────────

CREATE_TABLE = """
CREATE TABLE simulated_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT, timeframe TEXT, signal_type TEXT, direction TEXT,
    entry_price REAL, stop_loss REAL, take_profit REAL,
    strength INTEGER, confidence REAL, regime TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'OPEN',
    exit_price REAL, profit_pct REAL, R_multiple REAL, closed_at TEXT,
    duration_minutes INTEGER, features_json TEXT,
    max_price REAL, min_price REAL, max_R_possible REAL, captured_R_pct REAL,
    sl_source TEXT, tp_source TEXT,
    tsl_activated INTEGER DEFAULT 0,
    strategy_name TEXT, tsl_tf TEXT DEFAULT '15m',
    tp1_price REAL, tp2_price REAL, tp3_price REAL,
    tp1_hit_at TEXT, strategy_type TEXT,
    decision_trace_json TEXT, original_sl REAL,
    execution_mode TEXT DEFAULT 'VST'
)
"""


def _make_db(tmp_path, rows):
    """Создаёт SQLite-файл с тестовыми сделками."""
    db = str(tmp_path / "test.db")
    con = sqlite3.connect(db)
    con.execute(CREATE_TABLE)
    for r in rows:
        con.execute(
            """INSERT INTO simulated_trades
               (symbol, signal_type, direction, status, profit_pct, R_multiple,
                closed_at, max_R_possible, regime)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            r,
        )
    con.commit()
    con.close()
    return db


def _recent(days_ago=1):
    """Дата days_ago дней назад (для weekly_summary который фильтрует по дате)."""
    from datetime import datetime, timedelta
    return (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")

SAMPLE_ROWS = [
    # symbol, signal_type, direction, status, profit_pct, R_multiple, closed_at, max_R_possible, regime
    ("BTC/USDT", "wt_signal",       "LONG",  "TP",      5.0,  2.0,  _recent(3), 3.0, "TREND_UP"),
    ("BTC/USDT", "wt_signal",       "SHORT", "SL",     -2.0, -1.0,  _recent(3), 0.5, "TREND_DOWN"),
    ("ETH/USDT", "trend_signal",    "LONG",  "TP",      4.0,  1.5,  _recent(2), 2.0, "RANGE"),
    ("ETH/USDT", "trend_signal",    "SHORT", "SL",     -2.0, -1.0,  _recent(2), 0.8, "RANGE"),
    ("ADA/USDT", "pivot_reversal",  "LONG",  "TP",      8.0,  3.0,  _recent(1), 4.0, "TREND_UP"),
    ("ADA/USDT", "pivot_reversal",  "LONG",  "OPEN",   None, None,  None,       None, None),
]


class TestSummary:
    def test_returns_dict(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        pe = PerformanceEngine(db)
        s = pe.summary()
        assert isinstance(s, dict)

    def test_total_count(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        pe = PerformanceEngine(db)
        s = pe.summary()
        assert s["total"] == 6

    def test_open_count(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        pe = PerformanceEngine(db)
        s = pe.summary()
        assert s["open_count"] == 1

    def test_tp_count(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        pe = PerformanceEngine(db)
        s = pe.summary()
        assert s["tp_count"] == 3

    def test_win_rate(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        pe = PerformanceEngine(db)
        s = pe.summary()
        # 3 TP / (3 TP + 2 SL) = 60%
        assert s["win_rate"] == 60.0

    def test_empty_db(self, tmp_path):
        db = _make_db(tmp_path, [])
        pe = PerformanceEngine(db)
        s = pe.summary()
        assert s.get("total") == 0
        assert s.get("win_rate") is None

    def test_nonexistent_db_returns_empty(self, tmp_path):
        pe = PerformanceEngine(str(tmp_path / "missing.db"))
        s = pe.summary()
        assert isinstance(s, dict)


class TestBySignalType:
    def test_returns_list(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        result = PerformanceEngine(db).by_signal_type()
        assert isinstance(result, list)

    def test_groups_correctly(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        result = PerformanceEngine(db).by_signal_type()
        types = {r["signal_type"] for r in result}
        assert "wt_signal" in types
        assert "trend_signal" in types
        assert "pivot_reversal" in types

    def test_win_rate_per_type(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        result = PerformanceEngine(db).by_signal_type()
        wt = next(r for r in result if r["signal_type"] == "wt_signal")
        # 1 TP, 1 SL → 50%
        assert wt["win_rate"] == 50.0

    def test_pivot_reversal_100pct(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        result = PerformanceEngine(db).by_signal_type()
        pr = next(r for r in result if r["signal_type"] == "pivot_reversal")
        # 1 TP, 0 SL → 100% (OPEN не считается)
        assert pr["win_rate"] == 100.0


class TestWeeklySummary:
    def test_returns_dict(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        s = PerformanceEngine(db).weekly_summary(days_back=30)
        assert isinstance(s, dict)

    def test_total_matches_closed(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        s = PerformanceEngine(db).weekly_summary(days_back=30)
        # 3 TP + 2 SL = 5 закрытых
        assert s["total"] == 5

    def test_wins_count(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        s = PerformanceEngine(db).weekly_summary(days_back=30)
        assert s["wins"] == 3

    def test_win_rate_calculation(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        s = PerformanceEngine(db).weekly_summary(days_back=30)
        assert s["win_rate"] == 60.0

    def test_zero_days_returns_empty(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        s = PerformanceEngine(db).weekly_summary(days_back=0)
        assert s["total"] == 0


class TestPairHistory:
    def test_returns_list(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        result = PerformanceEngine(db).pair_history("BTC/USDT")
        assert isinstance(result, list)

    def test_filters_by_symbol(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        result = PerformanceEngine(db).pair_history("BTC/USDT")
        # pair_history возвращает только закрытые сделки по символу (symbol не в SELECT)
        # BTC/USDT: 1 TP + 1 SL = 2 закрытые
        assert len(result) == 2
        assert all("status" in r for r in result)

    def test_unknown_symbol_empty(self, tmp_path):
        db = _make_db(tmp_path, SAMPLE_ROWS)
        result = PerformanceEngine(db).pair_history("XYZ/USDT")
        assert result == []

    def test_limit_respected(self, tmp_path):
        # Добавляем 5 сделок по одной паре
        rows = [("SOL/USDT", "wt_signal", "LONG", "TP", 2.0, 1.0,
                 "2026-03-01 10:00:00", 2.0, "TREND_UP")] * 5
        db = _make_db(tmp_path, rows)
        result = PerformanceEngine(db).pair_history("SOL/USDT", limit=3)
        assert len(result) <= 3
