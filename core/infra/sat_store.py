# -*- coding: utf-8 -*-
"""Базы спутников: ОДИН писатель на базу (BACKLOG N16, 29.09).

subscriptions.db — база бота. Спутник пишет в СВОЮ базу oko_feed/{name}.db, а чужие (бота, других спутников)
подключает через ATTACH только для чтения: таблицы без префикса SQLite ищет сначала в своей базе, потом в
подключённых по порядку — SQL спутника менять почти не нужно, а записать в чужую базу физически нельзя.

🔴 База бота подключается по пути E:\\…\\subscriptions.db, НЕ через resolve()/C:\\oko_data: это симлинк, и -wal/-shm
лежат рядом с путём открытия — другой путь = раздвоенный WAL (память db_symlink_split_wal_hazard).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
FEED = PROJECT / "oko_feed"
BOT_DB = PROJECT / "subscriptions.db"          # без resolve() — см. выше


def path(name: str) -> Path:
    return FEED / f"{name}.db"


def connect(name: str, attach: dict | None = None, timeout: float = 10.0) -> sqlite3.Connection:
    """Своя база спутника (WAL) + чужие только для чтения: attach={"bot": sat_store.BOT_DB, "wp": path("weekly_pivot")}.
    Порядок attach важен: при одинаковых именах таблиц выигрывает подключённая раньше."""
    c = sqlite3.connect(path(name).as_uri(), uri=True, timeout=timeout)
    c.execute("PRAGMA journal_mode=WAL")
    for alias, p in (attach or {}).items():
        c.execute(f"ATTACH DATABASE ? AS {alias}", (Path(p).as_uri() + "?mode=ro",))
    return c
