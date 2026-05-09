"""
PositionManager — DEV-78.

Отслеживает открытые позиции через таблицу live_orders.
Поддерживает sync_with_exchange() при рестарте для восстановления состояния.

Таблица live_orders:
    id, sim_trade_id, exchange_order_id, symbol, side, qty,
    sl_order_id, tp_order_id, status, slip_pct, created_at, updated_at
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from core.infra.data_collector import RealTimeData

logger = logging.getLogger(__name__)

STATUS_OPEN    = "OPEN"
STATUS_CLOSED  = "CLOSED"
STATUS_ORPHAN  = "ORPHAN"


class LiveOrder:
    """Запись в live_orders."""
    __slots__ = (
        "id", "sim_trade_id", "exchange_order_id", "symbol", "side",
        "qty", "sl_order_id", "tp_order_id", "status", "slip_pct",
        "created_at", "updated_at",
    )

    def __init__(self, row):
        (self.id, self.sim_trade_id, self.exchange_order_id,
         self.symbol, self.side, self.qty,
         self.sl_order_id, self.tp_order_id, self.status, self.slip_pct,
         self.created_at, self.updated_at) = row


class PositionManager:
    """
    Менеджер открытых позиций.

    Читает/пишет таблицу live_orders.
    sync_with_exchange() — сверяет с реальными позициями при рестарте.
    """

    def __init__(self, db_path: str = "subscriptions.db") -> None:
        self._db = db_path
        self._init_table()

    # ─────────────────────── DB ────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_table(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS live_orders (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    sim_trade_id       INTEGER,
                    exchange_order_id  TEXT,
                    symbol             TEXT NOT NULL,
                    side               TEXT NOT NULL,
                    qty                REAL NOT NULL,
                    sl_order_id        TEXT,
                    tp_order_id        TEXT,
                    status             TEXT NOT NULL DEFAULT 'OPEN',
                    slip_pct           REAL DEFAULT 0.0,
                    created_at         TEXT,
                    updated_at         TEXT
                )
            """)
            # Миграция: добавить колонку если таблица уже существовала без неё
            try:
                conn.execute("ALTER TABLE live_orders ADD COLUMN slip_pct REAL DEFAULT 0.0")
            except sqlite3.OperationalError:
                pass

    # ─────────────────────── CRUD ──────────────────────────────────────────

    def register(
        self,
        symbol:             str,
        side:               str,
        qty:                float,
        sim_trade_id:       Optional[int]  = None,
        exchange_order_id:  Optional[str]  = None,
        sl_order_id:        Optional[str]  = None,
        tp_order_id:        Optional[str]  = None,
        slip_pct:           float          = 0.0,
    ) -> int:
        """Зарегистрировать новую открытую позицию. Возвращает live_order.id."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO live_orders
                   (sim_trade_id, exchange_order_id, symbol, side, qty,
                    sl_order_id, tp_order_id, status, slip_pct, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (sim_trade_id, exchange_order_id, symbol, side, qty,
                 sl_order_id, tp_order_id, STATUS_OPEN, slip_pct, now, now),
            )
            return cur.lastrowid

    def close(self, live_order_id: int, slip_pct: float = 0.0) -> None:
        """Пометить позицию как закрытую."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE live_orders SET status=?, slip_pct=?, updated_at=? WHERE id=?",
                (STATUS_CLOSED, slip_pct, now, live_order_id),
            )

    def mark_orphan(self, live_order_id: int) -> None:
        """Позиция не найдена на бирже — помечаем как ORPHAN для ревью."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE live_orders SET status=?, updated_at=? WHERE id=?",
                (STATUS_ORPHAN, now, live_order_id),
            )

    # ─────────────────────── Queries ───────────────────────────────────────

    def has_open_position(self, symbol: str) -> bool:
        """True если есть открытая позиция по символу."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM live_orders WHERE symbol=? AND status=?",
                (symbol, STATUS_OPEN),
            ).fetchone()
            return (row[0] if row else 0) > 0

    def get_open_positions(self) -> List[LiveOrder]:
        """Все открытые позиции."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM live_orders WHERE status=? ORDER BY created_at DESC",
                (STATUS_OPEN,),
            ).fetchall()
            return [LiveOrder(tuple(r)) for r in rows]

    def get_by_symbol(self, symbol: str, status: str = STATUS_OPEN) -> Optional[LiveOrder]:
        """Первая позиция по символу с данным статусом."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM live_orders WHERE symbol=? AND status=? ORDER BY created_at DESC LIMIT 1",
                (symbol, status),
            ).fetchone()
            return LiveOrder(tuple(row)) if row else None

    def get_orphans(self) -> List[LiveOrder]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM live_orders WHERE status=?", (STATUS_ORPHAN,)
            ).fetchall()
            return [LiveOrder(tuple(r)) for r in rows]

    # ─────────────────────── Sync ──────────────────────────────────────────

    async def sync_with_exchange(self, order_manager) -> dict:
        """
        Сверяет live_orders с реальными позициями на бирже при старте бота.

        DEV-145: использует BingXClient через OrderManager (не ccxt).
        Для каждой OPEN записи в live_orders:
          - Если позиция есть на бирже → OK, статус актуален
          - Если позиции нет на бирже → CLOSED (закрылась пока бот был offline)

        Не угадываем статус — помечаем CLOSED (live_orders не хранит SL/TP цен,
        реальный статус SL/TP обновляется через position_sync в симуляторе).

        Returns:
            {"ok": N, "closed": M}
        """
        open_positions = self.get_open_positions()
        if not open_positions:
            return {"ok": 0, "closed": 0}

        stats = {"ok": 0, "closed": 0}
        try:
            # DEV-154: _get_client_synced() гарантирует синхронизацию времени
            # чтобы избежать 109400 timestamp invalid при старте бота
            client = await order_manager._get_client_synced()
            exchange_positions = await client.get_positions()
            # BingX символ: "BTC-USDT", наш: "BTC/USDT:USDT"
            open_syms: set = set()
            for p in exchange_positions:
                qty = float(p.get("positionAmt") or p.get("availableAmt") or 0)
                if qty != 0:
                    bx_sym = p.get("symbol", "")
                    our_sym = bx_sym.replace("-", "/") + ":USDT"
                    open_syms.add(our_sym)
        except Exception as e:
            logger.warning("[PositionManager] sync: не удалось получить позиции с биржи: %s", e)
            return stats

        for pos in open_positions:
            if pos.symbol in open_syms:
                stats["ok"] += 1
                logger.debug("[PositionManager] sync OK %s", pos.symbol)
            else:
                # Позиция закрылась пока бот не работал — закрываем запись
                self.close(pos.id)
                stats["closed"] += 1
                logger.info("[PositionManager] sync CLOSED %s id=%d — нет на бирже",
                            pos.symbol, pos.id)

        logger.info("[PositionManager] sync завершён: ok=%d closed=%d", stats["ok"], stats["closed"])
        return stats
