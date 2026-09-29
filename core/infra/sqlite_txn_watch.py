# -*- coding: utf-8 -*-
"""N16 диагностика: КТО держит транзакцию записи subscriptions.db.

Включается только переменной окружения OKO_SQLITE_TXN_WATCH=1 (вызов `install()` при старте).
Подменяет sqlite3.connect: соединения к базе (по подстроке имени файла) создаются подклассом,
который запоминает стек места создания. Фоновый поток раз в секунду смотрит `in_transaction`
каждого живого соединения; транзакция старше HOLD_SEC → в лог стек создания + поток-владелец.
Одно сообщение на транзакцию; по её завершении — строка с итоговой длительностью.

Зачем: 29.09 зонд handle.exe показал, что во время многоминутных блокировок базу держат открытой
только процессы бота и dc_agent (запись в WAL стоит) — держатель внутри бота, а статический
разбор кода его не нашёл.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
import traceback
import weakref

logger = logging.getLogger(__name__)

HOLD_SEC = float(os.environ.get("OKO_SQLITE_TXN_HOLD_SEC", "5"))
_MATCH = os.environ.get("OKO_SQLITE_TXN_MATCH", "subscriptions.db")
_orig_connect = sqlite3.connect
_live: "weakref.WeakSet[_TracedConnection]" = weakref.WeakSet()
_installed = False


class _TracedConnection(sqlite3.Connection):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._born = "".join(traceback.format_list(traceback.extract_stack(limit=9)[:-2]))
        self._born_thread = threading.current_thread().name
        self._txn_since = None
        self._reported = False


def _connect(database, *a, **k):
    if "factory" not in k and _MATCH in str(database):
        conn = _orig_connect(database, *a, factory=_TracedConnection, **k)
        _live.add(conn)
        return conn
    return _orig_connect(database, *a, **k)


def _watch() -> None:
    while True:
        time.sleep(1.0)
        now = time.monotonic()
        for conn in list(_live):
            try:
                busy = conn.in_transaction
            except Exception:  # соединение закрыто
                busy = False
            if busy:
                if conn._txn_since is None:
                    conn._txn_since = now
                elif not conn._reported and now - conn._txn_since >= HOLD_SEC:
                    conn._reported = True
                    logger.warning("[TXN-WATCH] транзакция записи открыта %.0f с · поток создания %s · "
                                   "создано здесь:\n%s", now - conn._txn_since, conn._born_thread, conn._born)
            elif conn._txn_since is not None:
                if conn._reported:
                    logger.warning("[TXN-WATCH] транзакция закрыта через %.0f с (поток создания %s)",
                                   now - conn._txn_since, conn._born_thread)
                conn._txn_since, conn._reported = None, False


def install() -> bool:
    """Ставит перехват, если OKO_SQLITE_TXN_WATCH=1. Возвращает True, если включено."""
    global _installed
    if _installed or os.environ.get("OKO_SQLITE_TXN_WATCH") != "1":
        return _installed
    sqlite3.connect = _connect
    threading.Thread(target=_watch, name="txn-watch", daemon=True).start()
    _installed = True
    logger.warning("[TXN-WATCH] включён: порог %.0f с, база *%s*", HOLD_SEC, _MATCH)
    return True
