# -*- coding: utf-8 -*-
"""Сфера 1: очередь закрытых баров от WebSocket бота → хранилище (BACKLOG N15, шаг 2).

Бот НЕ пишет паркеты: писатель хранилища один — scripts/market_store_service.py (иначе два процесса
перезаписывают один месячный файл и теряют бары). Бот кладёт закрытый бар в поминутный CSV
{ROOT}/_spool/{YYYYMMDD_HHMM}.csv (UTC-минута записи); сервис забирает ЗАВЕРШЁННЫЕ минуты и удаляет файлы.

Закрытый бар = финальное обновление потока: воркер досылает придержанное прореживанием обновление перед
первым сообщением следующего бара (market_ws_v2, 29.09), иначе close совпадал с биржей у 49.6% баров 15m.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from core.infra.market_store import ROOT, base_of, is_synthetic

logger = logging.getLogger(__name__)

SPOOL = ROOT / "_spool"
FIELDS = ("base", "tf", "time", "open", "high", "low", "close", "volume")
_FLUSH_SEC = 10.0
_buf: list[str] = []
_lock = threading.Lock()
_thread: threading.Thread | None = None


def put(symbol: str, tf: str, bar) -> None:
    """Закрытый бар (dict/Series с time,open,high,low,close,volume) — в буфер. Синтетику не пишем."""
    base = base_of(symbol)
    if is_synthetic(base):
        return
    # float(): repr numpy-числа в numpy 2 — «np.float64(0.323)», CSV так не читается (29.09 первый приём упал)
    o, h, lo, c, v = (float(bar[k]) for k in ("open", "high", "low", "close", "volume"))
    line = f"{base},{tf},{int(bar['time'])},{o!r},{h!r},{lo!r},{c!r},{v!r}\n"
    with _lock:
        _buf.append(line)
    _ensure_thread()


def flush() -> int:
    with _lock:
        lines = _buf[:]
        _buf.clear()
    if not lines:
        return 0
    SPOOL.mkdir(parents=True, exist_ok=True)
    path = SPOOL / time.strftime("%Y%m%d_%H%M.csv", time.gmtime())   # минута ЗАПИСИ — прошлые не трогаем
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError as e:
        logger.warning("[SPOOL] запись %s: %s — %d баров вернул в буфер", path.name, e, len(lines))
        with _lock:
            _buf[:0] = lines
        return 0
    return len(lines)


def _loop() -> None:
    while True:
        time.sleep(_FLUSH_SEC)
        try:
            flush()
        except Exception as e:  # noqa: BLE001 — очередь не должна ронять поток бота
            logger.debug("[SPOOL] flush: %s", e)


def _ensure_thread() -> None:
    global _thread
    if _thread is None:
        with _lock:
            if _thread is None:
                _thread = threading.Thread(target=_loop, name="market-spool", daemon=True)
                _thread.start()
                # 30.09: буфер сбрасывается раз в 10 с — при остановке бота хвост терялся (рестарт 00:10:47:
                # бар 5m 00:05 дошёл у 563 из 584). Штатный выход — дописать остаток.
                import atexit
                atexit.register(flush)


def completed_files(now: float | None = None) -> list[Path]:
    """Файлы прошедших минут (текущую ещё дописывают)."""
    cur = time.strftime("%Y%m%d_%H%M.csv", time.gmtime(now or time.time()))
    return sorted(p for p in SPOOL.glob("*.csv") if p.name < cur) if SPOOL.exists() else []
