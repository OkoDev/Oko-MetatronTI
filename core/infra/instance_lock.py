# -*- coding: utf-8 -*-
"""Single-instance бота на блокировке ОС (17.10.2026).

Было (в oko_mtf.py): файл с PID + «забрать, если владелец мёртв». 15.10 в 06:32:30.996 и 06:32:31.000 два
экземпляра оба признали lock осиротевшим, каждый удалил его и создал свой — два бота работали 45 часов (23 ГБ).
Замок ОС атомарно достаётся ровно одному и снимается сам со смертью процесса (kill, BSOD) — ни гонки, ни
сирот-файлов. Замок стоит на байте далеко за текстом PID, поэтому сам PID остаётся читаемым снаружи.

Ожидание (wait_s > 0) — для запуска под pm2: каждый выход экземпляра с кодом 1 pm2 7 превращает в лишний спавн
(God.handleExit рестартует ТЕКУЩУЮ запись приложения, даже если умер устаревший контейнер), а старый
экземпляр при рестарте доживает секунды. Ждать дешевле, чем выйти.
"""
from __future__ import annotations

import logging
import os
import sys
import time

logger = logging.getLogger(__name__)

_held: dict[str, int] = {}     # путь → открытый хэндл; не закрываем до смерти процесса


def _try_os_lock(fd: int) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 1 << 20, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def acquire(lock_path: str, wait_s: float = 0) -> bool:
    """True — замок наш до конца жизни процесса, в файле записан наш PID. False — занят дольше wait_s."""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
    deadline = time.monotonic() + wait_s
    waited = False
    while not _try_os_lock(fd):
        if time.monotonic() >= deadline:
            os.close(fd)
            return False
        if not waited:
            waited = True
            logger.warning("Замок занят (PID %s) — жду до %.0f с: старый экземпляр завершается?",
                           holder_pid(lock_path), wait_s)
        time.sleep(1)
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    _held[lock_path] = fd
    return True


def holder_pid(lock_path: str) -> int:
    """PID держателя из файла (0 — пусто/нет файла). Сам факт владения определяет замок ОС, не этот текст."""
    try:
        with open(lock_path, encoding="utf-8") as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0
