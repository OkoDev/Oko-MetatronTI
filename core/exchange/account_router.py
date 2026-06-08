# -*- coding: utf-8 -*-
"""ARCH-96 Ф2: AccountRouter — распределение пар по субаккаунтам BingX.

Вердикт роя 08.06: БД sticky symbol→account (НЕ hashing — сдвиг=разрыв позиций),
слой НАД OrderManager (не поглощает), least-loaded при назначении новой пары.
Все клиенты делят ОДИН GlobalRateLimiter (Ф1, общий IP-бюджет).

🔴 STICKY-ИНВАРИАНТ: одна пара ВСЕГДА на одном субаккаунте (вход+SL+TSL вместе).
Маппинг детерминированный (БД), назначается ОДИН раз → не меняется (иначе позиция
разорвётся: вход на sub1, SL на sub2). Ребаланс — только вручную для пар БЕЗ открытых.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Dict, Optional

from core.exchange.bingx_client import BingXClient, make_client

import logging
logger = logging.getLogger(__name__)


class AccountRouter:
    """Маршрутизатор пар по субаккаунтам. route(symbol)→account_id (sticky из БД)."""

    def __init__(self, mode: str, config, db_path: str, max_accounts: int = 4):
        self._mode = mode
        self._cfg = config
        self._db_path = db_path
        self._lock = threading.Lock()
        # Создаём клиенты для всех аккаунтов с валидными ключами (1=основной, 2+=sub)
        self._clients: Dict[int, BingXClient] = {}
        for acc in range(1, max_accounts + 1):
            cli = make_client(mode, config, account=acc)
            if cli is not None:
                self._clients[acc] = cli
        if not self._clients:
            raise ValueError(f"[AccountRouter] нет валидных клиентов для mode={mode}")
        self._accounts = sorted(self._clients.keys())
        self._ensure_table()
        self._map: Dict[str, int] = self._load_map()
        logger.info("[AccountRouter] mode=%s аккаунтов=%s пар в карте=%d",
                    mode, self._accounts, len(self._map))

    # ── БД sticky symbol→account ───────────────────────────────────────────
    def _ensure_table(self) -> None:
        con = sqlite3.connect(self._db_path)
        try:
            con.execute(
                """CREATE TABLE IF NOT EXISTS account_routing (
                    symbol      TEXT PRIMARY KEY,
                    account_id  INTEGER NOT NULL,
                    mode        TEXT NOT NULL,
                    assigned_at TEXT DEFAULT (datetime('now'))
                )"""
            )
            con.commit()
        finally:
            con.close()

    def _load_map(self) -> Dict[str, int]:
        con = sqlite3.connect(self._db_path)
        try:
            rows = con.execute(
                "SELECT symbol, account_id FROM account_routing WHERE mode=?",
                (self._mode,),
            ).fetchall()
            # фильтр: только аккаунты, для которых есть живой клиент
            return {s: a for s, a in rows if a in self._clients}
        finally:
            con.close()

    def _least_loaded(self) -> int:
        """Аккаунт с наименьшим числом назначенных пар (равномерное распределение)."""
        counts = {a: 0 for a in self._accounts}
        for acc in self._map.values():
            counts[acc] = counts.get(acc, 0) + 1
        return min(self._accounts, key=lambda a: counts[a])

    def _assign(self, symbol: str, account: int) -> None:
        con = sqlite3.connect(self._db_path)
        try:
            con.execute(
                "INSERT OR REPLACE INTO account_routing (symbol, account_id, mode) VALUES (?,?,?)",
                (symbol, account, self._mode),
            )
            con.commit()
        finally:
            con.close()
        self._map[symbol] = account

    # ── Публичный API ──────────────────────────────────────────────────────
    def route(self, symbol: str) -> int:
        """symbol → account_id (sticky). Новая пара → least-loaded + закрепляется в БД."""
        with self._lock:
            acc = self._map.get(symbol)
            if acc is not None:
                return acc
            acc = self._least_loaded()
            self._assign(symbol, acc)
            logger.info("[AccountRouter] %s → account=%d (новая пара, least-loaded)", symbol, acc)
            return acc

    def get_client(self, symbol: str) -> BingXClient:
        """Клиент субаккаунта для пары (sticky)."""
        return self._clients[self.route(symbol)]

    def client_for_account(self, account: int) -> Optional[BingXClient]:
        return self._clients.get(account)

    @property
    def accounts(self):
        return list(self._accounts)

    def distribution(self) -> Dict[int, int]:
        """Сколько пар на каждом аккаунте (для мониторинга нагрузки)."""
        d = {a: 0 for a in self._accounts}
        for acc in self._map.values():
            d[acc] = d.get(acc, 0) + 1
        return d
