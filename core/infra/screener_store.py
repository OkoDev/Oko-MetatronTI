# -*- coding: utf-8 -*-
"""Хранилище скринера OKO-SM (BACKLOG N16, 29.09.2026): отдельный файл вместо таблицы в subscriptions.db.

Пишет только oko-sm-watch (последний снапшот пары), читают терминал :8010 и news-sphere.
Причина: запись screener_state в общую базу бота проваливалась в 97–99% попыток минимум с 23.09
(«database is locked» — в subscriptions.db пишут бот и спутники, ~190 мест со своими соединениями),
и скринер терминала неделю почти не обновлялся. Спутник пишет в своё хранилище, а не в базу бота.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "oko_feed" / "screener.db"


def connect(timeout: float = 10.0) -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=timeout)
    c.execute("PRAGMA journal_mode=WAL")
    return c
