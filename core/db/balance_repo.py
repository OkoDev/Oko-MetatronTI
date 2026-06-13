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


# ═══════════════════════════════════════════════════════════════
# positions (ARCH-DB-V2 Ф2) — current-state открытых позиций
# ═══════════════════════════════════════════════════════════════

def upsert_positions(account_id: int, parsed_positions: list) -> None:
    """Обновляет таблицу positions из parsed_all (ParsedPosition objects)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (account_id, pp.symbol_our, pp.side,
         pp.qty, getattr(pp, 'entry', None), pp.unrealized_pnl, pp.margin, now)
        for pp in parsed_positions
        if pp.margin >= 0.01
    ]
    with _connect() as db:
        # Удаляем старые позиции аккаунта которых нет в текущем снимке
        if rows:
            syms_sides = [(r[1], r[2]) for r in rows]
            placeholders = ",".join("(?,?)" for _ in syms_sides)
            flat = [x for pair in syms_sides for x in pair]
            db.execute(
                f"DELETE FROM positions WHERE account_id=? AND (symbol, side) NOT IN ({placeholders})",
                [account_id] + flat,
            )
        else:
            db.execute("DELETE FROM positions WHERE account_id=?", (account_id,))
        # Upsert активных
        for row in rows:
            db.execute(
                """INSERT INTO positions (account_id, symbol, side, qty, entry_price,
                   unrealized_pnl, margin, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(account_id, symbol, side) DO UPDATE SET
                       qty=excluded.qty, entry_price=excluded.entry_price,
                       unrealized_pnl=excluded.unrealized_pnl, margin=excluded.margin,
                       updated_at=excluded.updated_at""",
                row,
            )
        db.commit()


def get_positions(account_id: Optional[int] = None) -> list[dict]:
    """Текущие открытые позиции (все или по аккаунту)."""
    with _connect() as db:
        if account_id is not None:
            rows = db.execute(
                "SELECT * FROM positions WHERE account_id=? ORDER BY updated_at DESC",
                (account_id,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM positions ORDER BY account_id, updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_accounts() -> list[dict]:
    """Справочник аккаунтов с последним балансом."""
    with _connect() as db:
        rows = db.execute(
            """SELECT a.id, a.name, a.api_env, a.is_active,
                      b.equity, b.available, b.used_margin, b.unrealized_pnl, b.timestamp
               FROM accounts a
               LEFT JOIN balance_snapshots b ON b.account_id = a.id
                   AND b.timestamp = (
                       SELECT MAX(bs2.timestamp) FROM balance_snapshots bs2
                       WHERE bs2.account_id = a.id AND bs2.exchange = 'bingx'
                   )
               WHERE a.is_active = 1
               ORDER BY a.id"""
        ).fetchall()
        return [dict(r) for r in rows]
