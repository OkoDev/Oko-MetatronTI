"""oko_feed.store — единое SQLite-хранилище внешних данных (standalone, stdlib-only)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "external_data.db"


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS dominance (
        asset TEXT NOT NULL, date TEXT NOT NULL, value REAL NOT NULL, source TEXT,
        PRIMARY KEY (asset, date))""")
    c.execute("""CREATE TABLE IF NOT EXISTS onchain_events (
        ts INTEGER NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
        symbol TEXT, amount_usd REAL, direction TEXT, raw TEXT,
        PRIMARY KEY (ts, kind, symbol, amount_usd))""")
    return c


def upsert_dominance(asset: str, date: str, value: float, source: str = "coingecko"):
    c = conn()
    c.execute("INSERT OR REPLACE INTO dominance VALUES (?,?,?,?)", (asset, date, value, source))
    c.commit(); c.close()


def dominance_series(asset: str = "usdt") -> list[tuple[str, float]]:
    c = conn()
    rows = c.execute("SELECT date, value FROM dominance WHERE asset=? ORDER BY date", (asset,)).fetchall()
    c.close()
    return rows


def add_onchain_event(ts: int, kind: str, source: str, symbol: str,
                      amount_usd: float, direction: str | None, raw: str = ""):
    c = conn()
    c.execute("INSERT OR IGNORE INTO onchain_events VALUES (?,?,?,?,?,?,?)",
              (ts, kind, source, symbol, amount_usd, direction, raw[:500]))
    c.commit(); c.close()


def onchain_events(hours: int = 24) -> list[tuple]:
    c = conn()
    rows = c.execute("""SELECT ts, kind, symbol, amount_usd, direction FROM onchain_events
                        WHERE ts > ? ORDER BY ts DESC""",
                     (int(time.time()) - hours * 3600,)).fetchall()
    c.close()
    return rows
