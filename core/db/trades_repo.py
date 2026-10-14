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
    status: Optional[str] = None,
) -> dict:
    """Агрегаты: n, sumR, avgR, WR + net% по фильтру.

    status: конкретный закрытый статус (TP/SL/TSL/EXPIRED) → агрегат ТОЛЬКО по нему,
            чтобы шапка терминала совпадала с активной вкладкой таблицы (дашборд-когезия:
            шапка и таблица = один WHERE). None → по всем закрытым (как было).

    🔴 NET% (13.10): R не вычитает издержки, а по реальному счёту комиссии были 57% убытка и
    на трёх монетах из десяти меняли ЗНАК результата. Ядро весов уже считает в `pct_net`
    (`trading_intelligence.py:275`), витрина отставала — эти поля закрывают расхождение.

    🔑 Считаем net ТОЛЬКО по строкам с записанным костом (`costs_pct > 0`). Замер 13.10:
    costs_pct = 0 у 44 230 из 57 499 закрытых, и ненулевые — практически только в чистой эре
    (SIM 12 020 из 12 022 с 11.07.2026; до эры 55 строк из 44 282). Поэтому net по всей базе
    был бы фикцией: 77% строк вернули бы profit_pct без костов. `nNet` отдаём рядом, чтобы
    покрытие было видно в UI, а не домысливалось. Старые поля (n/sumR/avgR/WR) НЕ меняем —
    их читает ещё и старый дашборд `web/static/index.html`.

    `avgRNet` — средний R по ТЕМ ЖЕ строкам, что и net%: без него `avgR` (вся база) и
    `avgNetPct` (только с костом) встают в UI рядом как сравнимые, хотя это разные выборки."""
    _CLOSED = ("TP", "SL", "TSL", "EXPIRED")
    params: list = []
    if status in _CLOSED:
        where = "status=? AND R_multiple IS NOT NULL"
        params.append(status)
    else:
        where = "status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL"
    _net_row = "costs_pct > 0 AND profit_pct IS NOT NULL"
    sql = f"""SELECT COUNT(*) n, SUM(R_multiple) sumR, AVG(R_multiple) avgR,
             100.0 * SUM(CASE WHEN R_multiple > 0 THEN 1 ELSE 0 END) / COUNT(*) WR,
             SUM(CASE WHEN {_net_row} THEN 1 ELSE 0 END) nNet,
             AVG(CASE WHEN {_net_row} THEN R_multiple END) avgRNet,
             AVG(CASE WHEN {_net_row} THEN profit_pct - costs_pct END) avgNetPct,
             SUM(CASE WHEN {_net_row} THEN profit_pct - costs_pct END) sumNetPct,
             100.0 * SUM(CASE WHEN {_net_row} AND profit_pct - costs_pct > 0 THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN {_net_row} THEN 1 ELSE 0 END), 0) wrNet
             FROM simulated_trades
             WHERE {where}"""
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
    """По символу возвращает account_id из account_routing. Default=1.

    🔴 04.10: таблицу создаёт только `AccountRouter._ensure_table()`, то есть она
    появляется лишь при включённом мультиаккаунте. На свежей базе (и в тестах)
    её нет, и запрос падал OperationalError, роняя вызывающего. Отсутствие
    маршрутизации — это «аккаунт по умолчанию», а не ошибка.
    """
    with _connect() as db:
        try:
            r = db.execute(
                "SELECT account_id FROM account_routing WHERE symbol=? LIMIT 1",
                (symbol,),
            ).fetchone()
        except sqlite3.OperationalError:
            return 1
        return r["account_id"] if r else 1
