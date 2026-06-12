"""Тонкий db-слой: баланс и снапшоты. НЕ ORM — raw SQL в одном месте."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent.parent / "subscriptions.db"


def _connect() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


# ═══════════════════════════════════════════════════════════════
# balance_snapshots
# ═══════════════════════════════════════════════════════════════

def save_snapshot(
    account_id: int,
    equity: float,
    exchange: str = "bingx",
    available: Optional[float] = None,
    used_margin: Optional[float] = None,
    unrealized_pnl: Optional[float] = None,
    source: str = "poll",
    timestamp: Optional[str] = None,
) -> int:
    """Сохраняет снапшот баланса. Возвращает id."""
    from datetime import datetime, timezone
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        c = db.execute(
            """INSERT INTO balance_snapshots
               (account_id, exchange, timestamp, equity, available, used_margin, unrealized_pnl, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, exchange, ts, equity, available, used_margin, unrealized_pnl, source),
        )
        db.commit()
        return c.lastrowid


def get_equity_series(
    account_id: int,
    since: Optional[str] = None,
    exchange: str = "bingx",
    limit: int = 500,
) -> list[dict]:
    """Возвращает ряд equity (timestamp, equity) для графика."""
    params = [account_id, exchange]
    sql = """SELECT timestamp, equity, available, used_margin, unrealized_pnl
             FROM balance_snapshots
             WHERE account_id=? AND exchange=?"""
    if since:
        sql += " AND timestamp >= ?"
        params.append(since)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with _connect() as db:
        return [dict(r) for r in db.execute(sql, params).fetchall()]


def get_latest_snapshot(account_id: int, exchange: str = "bingx") -> Optional[dict]:
    """Последний снапшот баланса."""
    with _connect() as db:
        r = db.execute(
            """SELECT * FROM balance_snapshots
               WHERE account_id=? AND exchange=?
               ORDER BY timestamp DESC LIMIT 1""",
            (account_id, exchange),
        ).fetchone()
        return dict(r) if r else None
