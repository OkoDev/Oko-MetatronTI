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
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logger = logging.getLogger(__name__)

_BATCH: list = []
# 🔴 01.09 БЫЛ asyncio.Lock — И ЭТО КОРЕНЬ «ТИШИНЫ» ЗАПИСИ.
# В процессе НЕСКОЛЬКО event loop'ов: главный (asyncio.run), TradingLoop в отдельном потоке
# (core/infra/trading_loop.py), market_ws. asyncio.Lock привязывается к тому loop'у, где его
# впервые взяли: record_drop зовётся из торгового контура, flush_periodically крутится в
# главном — второй ждёт лок чужого loop'а и не записывает НИЧЕГО, молча, без исключения.
# Симптом 01.09: гейты отбрасывают сигналы (в логе `router dropped` идут), а в signal_drops
# последняя запись 12:09:32 и дальше пусто.
# Тот же приём, что уже применён в GlobalRateLimiter: threading.Lock = loop-agnostic.
# Под ним НЕТ await — только работа со списком (микросекунды), запись идёт вне лока.
_BATCH_LOCK = threading.Lock()
_DB_PATH: Optional[str] = None
# потолок очереди при недоступной БД (01.09): 200 батчей по 50 — держит ~1.5ч простоя записи
_BATCH_MAX: int = 10000

# 🔴 01.09 СВОЙ ОДНОПОТОЧНЫЙ EXECUTOR. Запись шла через `run_in_executor(None, ...)` =
# ДЕФОЛТНЫЙ пул, который в этом боте делят 26 мест: генерация сигналов, ML, рендер графиков,
# наблюдатели. Когда пул насыщен, задача трейса просто СТОИТ В ОЧЕРЕДИ — без ошибки, без лога.
# Симптом 01.09: запись дропов оборвалась в 11:33:44 и не возобновилась ни через 3 часа, ни
# после рестарта, при том что гейты продолжали отбрасывать сигналы (1121 упоминание в логе).
# Отдельный пул на 1 поток: очередь трейса больше ни с кем не конкурирует, а порядок записи
# сохраняется (один поток = FIFO).
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dtrace")
_WRITE_TIMEOUT_SEC: float = 60.0


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
    with _BATCH_LOCK:
        _BATCH.append(row)
        need_flush = len(_BATCH) >= 50
    if need_flush:
        await _flush()


async def _flush() -> None:
    """Записывает накопленный батч в БД.

    Сам берёт _BATCH_LOCK (threading) на изъятие батча — await под локом НЕТ.
    """
    global _BATCH
    if _DB_PATH is None:
        return
    with _BATCH_LOCK:
        if not _BATCH:
            return
        batch = _BATCH[:]
        _BATCH = []

    def _write() -> None:
        # 🔴 01.09 busy_timeout был 5000 при том, что connect(timeout=10) уже дал 10с —
        # PRAGMA его СНИЖАЛА. Замер того же дня: write-lock свободен 99% времени, то есть
        # ловить BUSY на 5-секундном ожидании было нечего — упирались в редкие короткие окна.
        with sqlite3.connect(_DB_PATH, timeout=30) as conn:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.executemany(
                """INSERT INTO signal_drops
                   (symbol, signal_type, direction, strength, gate_name, drop_reason, features_json)
                   VALUES (:symbol, :signal_type, :direction, :strength, :gate_name, :drop_reason, :features_json)""",
                batch,
            )

    try:
        loop = asyncio.get_event_loop()
        # wait_for: зависшая запись обязана стать ВИДИМОЙ ошибкой, а не тихой тишиной
        await asyncio.wait_for(loop.run_in_executor(_EXECUTOR, _write),
                               timeout=_WRITE_TIMEOUT_SEC)
        logger.debug("[DecisionTrace] flushed %d rows to signal_drops", len(batch))
    except Exception as e:
        # 🔴 01.09 БАТЧ ТЕРЯЛСЯ НАВСЕГДА. `_BATCH` очищается ДО записи, и при `database is
        # locked` строки просто пропадали — за 01.09 это 142 неудачных flush, до 7100
        # потерянных решений. Наблюдаемость молча врала: «дропов нет» означало «запись упала».
        # Возвращаем батч в очередь (в начало — хронология сохраняется), следующий flush
        # через 30с повторит. Кэп защищает память, если БД недоступна долго.
        with _BATCH_LOCK:
            _BATCH = (batch + _BATCH)[-_BATCH_MAX:]
        logger.warning("[DecisionTrace] flush error: %s — %d строк возвращены в очередь (всего %d)",
                       e, len(batch), len(_BATCH))


async def flush_periodically(interval_s: int = 30) -> None:
    """Фоновый таск — записывает батч каждые N секунд.

    Запускать через asyncio.create_task(flush_periodically(30)).
    """
    tick = 0
    logger.info("[DecisionTrace] flush_periodically запущен (interval=%ds)", interval_s)
    while True:
        await asyncio.sleep(interval_s)
        tick += 1
        try:
            # ПРИБОР (01.09): раз в 10 тиков печатаем, что таск ЖИВ и сколько в очереди.
            # Без этого «записей нет» неотличимо от «таск умер» — именно на этой развилке
            # сегодня потерялся день: писали, что запись сломана, хотя очередь была пуста
            # (или наоборот). Пусть состояние очереди будет видно в логе всегда.
            if tick % 10 == 0:
                logger.info("[DecisionTrace] alive · очередь=%d строк", len(_BATCH))
            await _flush()          # лок берёт сам _flush (threading, без await под ним)
        except Exception as e:      # таск обязан пережить любую ошибку — иначе тихо умрёт
            logger.warning("[DecisionTrace] flush_periodically: %s", e)


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
