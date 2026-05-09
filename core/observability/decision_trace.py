"""Трекинг отброшенных сигналов для анализа gate-эффективности.

DEV-203: DecisionTrace infrastructure.

Архитектура:
- record_drop() — async, добавляет в батч-буфер (не блокирует scan_loop)
- _flush() — записывает батч в SQLite (вызывается при накоплении 50 записей)
- flush_periodically() — фоновый таск, сбрасывает буфер каждые N секунд
- get_top_drops() — синхронный, для dashboard API
"""
import asyncio
import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

_BATCH: list = []
_BATCH_LOCK = asyncio.Lock()
_DB_PATH: Optional[str] = None


def configure(db_path: str) -> None:
    """Устанавливает путь к БД. Вызывать при старте бота."""
    global _DB_PATH
    _DB_PATH = db_path
    logger.info("[DecisionTrace] configured db_path=%s", db_path)


async def record_drop(
    symbol: str,
    gate_name: str,
    drop_reason: str,
    signal_type: Optional[str] = None,
    direction: Optional[str] = None,
    strength: Optional[int] = None,
    features: Optional[dict] = None,
) -> None:
    """Записывает отброшенный сигнал в батч-буфер.

    Не блокирует scan_loop: запись в памяти, flush — асинхронный/фоновый.
    Если _DB_PATH не настроен — тихо игнорирует.
    """
    import json

    global _BATCH
    if _DB_PATH is None:
        return

    row = {
        "symbol": symbol,
        "signal_type": signal_type,
        "direction": direction,
        "strength": strength,
        "gate_name": gate_name,
        "drop_reason": drop_reason,
        "features_json": json.dumps(features, ensure_ascii=False) if features else None,
    }
    async with _BATCH_LOCK:
        _BATCH.append(row)
        if len(_BATCH) >= 50:
            await _flush()


async def _flush() -> None:
    """Записывает накопленный батч в БД.

    Вызывается под _BATCH_LOCK — не требует повторного захвата.
    """
    global _BATCH
    if not _BATCH or _DB_PATH is None:
        return
    batch = _BATCH[:]
    _BATCH = []

    def _write() -> None:
        with sqlite3.connect(_DB_PATH, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executemany(
                """INSERT INTO signal_drops
                   (symbol, signal_type, direction, strength, gate_name, drop_reason, features_json)
                   VALUES (:symbol, :signal_type, :direction, :strength, :gate_name, :drop_reason, :features_json)""",
                batch,
            )

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write)
        logger.debug("[DecisionTrace] flushed %d rows to signal_drops", len(batch))
    except Exception as e:
        logger.warning("[DecisionTrace] flush error: %s", e)


async def flush_periodically(interval_s: int = 30) -> None:
    """Фоновый таск — записывает батч каждые N секунд.

    Запускать через asyncio.create_task(flush_periodically(30)).
    """
    while True:
        await asyncio.sleep(interval_s)
        async with _BATCH_LOCK:
            await _flush()


def get_top_drops(db_path: str, limit: int = 20, hours: int = 24) -> list:
    """Топ gate_name по количеству drops за последние hours часов.

    Синхронный — безопасен для вызова из aiohttp handler через run_in_executor
    или напрямую (не блокирует event loop надолго, т.к. SELECT быстрый).
    """
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            rows = conn.execute(
                """
                SELECT gate_name, COUNT(*) as cnt, COUNT(DISTINCT symbol) as symbols
                FROM signal_drops
                WHERE dropped_at >= datetime('now', ? || ' hours')
                GROUP BY gate_name
                ORDER BY cnt DESC
                LIMIT ?
                """,
                (f"-{hours}", limit),
            ).fetchall()
            return [{"gate": r[0], "count": r[1], "symbols": r[2]} for r in rows]
    except Exception as e:
        logger.warning("[DecisionTrace] get_top_drops error: %s", e)
        return []


def get_recent_drops(db_path: str, limit: int = 100, hours: int = 1) -> list:
    """Последние N drops за hours часов — для детального просмотра в dashboard."""
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, signal_type, direction, strength,
                       gate_name, drop_reason, dropped_at
                FROM signal_drops
                WHERE dropped_at >= datetime('now', ? || ' hours')
                ORDER BY dropped_at DESC
                LIMIT ?
                """,
                (f"-{hours}", limit),
            ).fetchall()
            cols = ["id", "symbol", "signal_type", "direction", "strength",
                    "gate_name", "drop_reason", "dropped_at"]
            return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        logger.warning("[DecisionTrace] get_recent_drops error: %s", e)
        return []
