"""30.09: SIM-лимитки судит цена по свечам Сферы 1 (раньше филл был только по позиции на бирже → всегда CANCELLED)."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from core.trading import sim_fill

T0 = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)


def _db(tmp_path, **over):
    p = str(tmp_path / "t.db")
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE simulated_trades (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, "
                  "entry_price REAL, stop_loss REAL, original_sl REAL, take_profit REAL, created_at TEXT, "
                  "status TEXT, closed_at TEXT, actual_entry_price REAL, exchange_order_id TEXT, "
                  "execution_mode TEXT, features_json TEXT)")
        row = dict(id=1, symbol="ABC/USDT:USDT", direction="LONG", entry_price=100.0, stop_loss=95.0,
                   original_sl=95.0, take_profit=120.0, created_at=T0.isoformat(), status="PENDING_ENTRY",
                   closed_at=None, actual_entry_price=None, exchange_order_id=None, execution_mode="SIM",
                   features_json=json.dumps({"trade_mode": "impulse_fib_15m"}))
        row.update(over)
        c.execute("INSERT INTO simulated_trades VALUES (:id,:symbol,:direction,:entry_price,:stop_loss,"
                  ":original_sl,:take_profit,:created_at,:status,:closed_at,:actual_entry_price,"
                  ":exchange_order_id,:execution_mode,:features_json)", row)
    return p


def _bars(rows):
    """rows: [(минут от T0, low, high)]"""
    idx = pd.DatetimeIndex([T0 + timedelta(minutes=m) for m, _, _ in rows], tz="UTC")
    return pd.DataFrame({"low": [lo for _, lo, _ in rows], "high": [hi for _, _, hi in rows],
                         "open": [lo for _, lo, _ in rows], "close": [hi for _, _, hi in rows]}, index=idx)


@pytest.fixture
def patch_bars(monkeypatch):
    def use(df):
        monkeypatch.setattr(sim_fill, "_bars", lambda base, tf, since: df)
        monkeypatch.setattr(sim_fill, "_ttl_hours", lambda *_a, **_k: 12.0)
    return use


def _row(p):
    with sqlite3.connect(p) as c:
        c.row_factory = sqlite3.Row
        return dict(c.execute("SELECT * FROM simulated_trades WHERE id=1").fetchone())


def test_price_touches_limit_then_open_with_fill_time(tmp_path, patch_bars):
    patch_bars(_bars([(5, 101, 103), (10, 99.5, 102)]))          # вторая свеча задела 100
    assert sim_fill.resolve_sim_pending(_p := _db(tmp_path), now=T0 + timedelta(hours=1))["fill"] == 1
    r = _row(_p)
    assert r["status"] == "OPEN" and r["actual_entry_price"] == 100.0
    assert json.loads(r["features_json"])["sim_fill_at"].startswith("2026-09-20T10:10")


def test_broken_geometry_stop_before_entry_cancels(tmp_path, patch_bars):
    """При НОРМАЛЬНОЙ геометрии стоп раньше входа недостижим: цена непрерывна и проходит вход первым.
    Ветка ловит вывернутую заявку (для лонга стоп ВЫШЕ входа) — такую не открываем."""
    patch_bars(_bars([(5, 101, 103)]))
    p = _db(tmp_path, stop_loss=102.0, original_sl=102.0)          # стоп 102 > вход 100
    assert sim_fill.resolve_sim_pending(p, now=T0 + timedelta(hours=1))["cancel"] == 1
    assert _row(p)["status"] == "CANCELLED"


def test_entry_and_stop_same_bar_is_fill(tmp_path, patch_bars):
    """Цена непрерывна: сначала вход, стоп отработает симулятор — это убыточная сделка, а не «её не было»."""
    patch_bars(_bars([(5, 94, 103)]))
    p = _db(tmp_path, entry_price=102.0)                           # вход 102 задет той же свечой, что и стоп 95
    assert sim_fill.resolve_sim_pending(p, now=T0 + timedelta(hours=1))["fill"] == 1
    assert _row(p)["status"] == "OPEN"


def test_ttl_expired_cancels_and_waits_until_then(tmp_path, patch_bars):
    patch_bars(_bars([(5, 101, 103)]))                             # цена не дошла
    p = _db(tmp_path)
    assert sim_fill.resolve_sim_pending(p, now=T0 + timedelta(hours=1))["wait"] == 1
    assert _row(p)["status"] == "PENDING_ENTRY"
    assert sim_fill.resolve_sim_pending(p, now=T0 + timedelta(hours=13))["cancel"] == 1
    assert _row(p)["status"] == "CANCELLED"


def test_bars_after_ttl_do_not_fill(tmp_path, patch_bars):
    patch_bars(_bars([(5, 101, 103), (13 * 60, 99, 102)]))         # касание уже за окном TTL
    p = _db(tmp_path)
    assert sim_fill.resolve_sim_pending(p, now=T0 + timedelta(hours=14))["cancel"] == 1


def test_short_side(tmp_path, patch_bars):
    patch_bars(_bars([(5, 97, 99), (10, 98, 101)]))
    p = _db(tmp_path, direction="SHORT", entry_price=100.0, stop_loss=105.0, original_sl=105.0, take_profit=90.0)
    assert sim_fill.resolve_sim_pending(p, now=T0 + timedelta(hours=1))["fill"] == 1


def test_exchange_order_is_not_touched(tmp_path, patch_bars):
    patch_bars(_bars([(5, 99, 103)]))
    p = _db(tmp_path, exchange_order_id="12345", execution_mode="VST")
    assert sim_fill.resolve_sim_pending(p, now=T0 + timedelta(hours=1)) == {"fill": 0, "cancel": 0, "wait": 0, "skip": 0}
    assert _row(p)["status"] == "PENDING_ENTRY"


def test_simulated_fill_does_not_block_live_via_sl_cooldown(tmp_path):
    """Стоп сделки, ОТКРЫТОЙ симуляцией, не запирает боевой вход; обычный SIM-стоп — как раньше."""
    import sqlite3
    from datetime import datetime, timezone
    from types import SimpleNamespace

    import bot.monitoring as mon

    p = str(tmp_path / "c.db")
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE simulated_trades (id INTEGER PRIMARY KEY, symbol TEXT, status TEXT, "
                  "closed_at TEXT, signal_type TEXT, features_json TEXT)")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        c.execute("INSERT INTO simulated_trades VALUES (1,'SIMU/USDT:USDT','SL',?,'impulse_fib_15m',?)",
                  (now, json.dumps({"trade_mode": "impulse_fib_15m", "sim_fill_at": now})))
        c.execute("INSERT INTO simulated_trades VALUES (2,'REAL/USDT:USDT','SL',?,'impulse_fib_15m',?)",
                  (now, json.dumps({"trade_mode": "impulse_fib_15m"})))

    bot = SimpleNamespace(trade_simulator=SimpleNamespace(db_path=p),
                          config=SimpleNamespace(get=lambda k, d=None: {"signal_quality.sl_cooldown_hours": 1.0}.get(k, d)))
    assert mon._is_in_sl_cooldown(bot, "SIMU/USDT:USDT") is False      # симуляция — наблюдение
    assert mon._is_in_sl_cooldown(bot, "REAL/USDT:USDT") is True       # обычный стоп блокирует, как и раньше
