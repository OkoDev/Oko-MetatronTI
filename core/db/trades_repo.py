"""Тонкий db-слой: фильтры сделок. НЕ ORM — raw SQL в одном месте."""
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
# Фильтры сделок
# ═══════════════════════════════════════════════════════════════

def get_trades(
    account_id: Optional[int] = None,
    execution_mode: Optional[str] = None,
    exchange: str = "bingx",
    signal_type: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 500,
) -> list[dict]:
    """Список сделок с фильтрами. Все параметры опциональны."""
    sql = "SELECT * FROM simulated_trades WHERE 1=1"
    params: list = []
    if account_id is not None:
        sql += " AND account_id=?"
        params.append(account_id)
    if execution_mode is not None:
        sql += " AND execution_mode=?"
        params.append(execution_mode)
    if exchange is not None:
        sql += " AND exchange=?"
        params.append(exchange)
    if signal_type is not None:
        sql += " AND signal_type=?"
        params.append(signal_type)
    if status is not None:
        sql += " AND status=?"
        params.append(status)
    if since is not None:
        sql += " AND created_at >= ?"
        params.append(since)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _connect() as db:
        return [dict(r) for r in db.execute(sql, params).fetchall()]


def get_summary(
    account_id: Optional[int] = None,
    execution_mode: Optional[str] = None,
) -> dict:
    """Агрегаты: n, sumR, avgR, WR по фильтру."""
    sql = """SELECT COUNT(*) n, SUM(R_multiple) sumR, AVG(R_multiple) avgR,
             100.0 * SUM(CASE WHEN R_multiple > 0 THEN 1 ELSE 0 END) / COUNT(*) WR
             FROM simulated_trades
             WHERE status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL"""
    params: list = []
    if account_id is not None:
        sql += " AND account_id=?"
        params.append(account_id)
    if execution_mode is not None:
        sql += " AND execution_mode=?"
        params.append(execution_mode)
    with _connect() as db:
        r = db.execute(sql, params).fetchone()
        return dict(r) if r else {}


def get_open_positions(account_id: Optional[int] = None) -> list[dict]:
    """Открытые позиции с фильтром по аккаунту."""
    sql = "SELECT * FROM simulated_trades WHERE status='OPEN'"
    params: list = []
    if account_id is not None:
        sql += " AND account_id=?"
        params.append(account_id)
    sql += " ORDER BY created_at DESC"
    with _connect() as db:
        return [dict(r) for r in db.execute(sql, params).fetchall()]


def resolve_account_id(symbol: str) -> int:
    """По символу возвращает account_id из account_routing. Default=1."""
    with _connect() as db:
        r = db.execute(
            "SELECT account_id FROM account_routing WHERE symbol=? LIMIT 1",
            (symbol,),
        ).fetchone()
        return r["account_id"] if r else 1
