"""
Точка входа Oko MTF Bot.
Бизнес-логика и инициализация — в bot/core/bot.py.
"""
import logging
import logging.handlers
import platform
import sys
import os
import atexit

# ── Monkey-patch: aiohttp 3.9+ убрал loop=, ccxt всё ещё передаёт ──
import aiohttp.connector as _aiohttp_connector
_original_init = _aiohttp_connector.TCPConnector.__init__
def _patched_init(self, *args, **kwargs):
    kwargs.pop('loop', None)
    _original_init(self, *args, **kwargs)
_aiohttp_connector.TCPConnector.__init__ = _patched_init
import asyncio
import shutil
import glob
import sqlite3          # 11.08: online-backup API вместо небезопасной файловой копии
import time             # 11.08: возраст последней копии (пропуск частых бэкапов)
from datetime import datetime

from core.infra.config_loader import config

# ==============================
# Логирование
# ==============================
logging.basicConfig(
    level=getattr(logging, config.get("logging.level", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            "logs/crypto_bot.log", encoding="utf-8",
            maxBytes=50 * 1024 * 1024,  # 50 MB
            backupCount=10,             # хранить 10 архивов
        ),
        logging.StreamHandler(sys.stdout),
    ],
)

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="ignore")
except Exception:
    pass

# ==============================
# Single-instance lock
# ==============================
_LOCK_FILE = os.path.join(os.path.dirname(__file__) or ".", "bot_instance.lock")


def _lock_owner_alive(lock_path: str) -> bool:
    """PID из lock-файла жив И это python-процесс. После BSOD/kill atexit не срабатывает —
    lock сиротеет, и автозапуск упирался в мёртвый файл (Егор удалял руками, 08.07)."""
    import subprocess
    try:
        pid = int(open(lock_path, encoding="utf-8").read().strip() or 0)
    except Exception:
        return False                                  # пустой/битый lock = сирота
    if pid <= 0:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10).stdout
        return "python" in (out or "").lower()        # жив и питон → настоящий бот
    except Exception:
        return True                                   # проверить не смогли → lock не забираем


def _acquire_single_instance_lock(lock_path: str = _LOCK_FILE) -> bool:
    for attempt in (1, 2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))

            def _cleanup():
                try:
                    if os.path.exists(lock_path):
                        os.remove(lock_path)
                except Exception:
                    pass

            atexit.register(_cleanup)
            return True
        except FileExistsError:
            if attempt == 1 and not _lock_owner_alive(lock_path):
                logging.warning("Lock-файл ОСИРОТЕЛ (владелец мёртв — BSOD/kill?) — забираю и стартую.")
                try:
                    os.remove(lock_path)
                    continue                          # второй заход возьмёт lock
                except Exception:
                    pass
            return False
        except Exception:
            logging.warning("Не удалось создать lock-файл. Продолжаю без блокировки.")
            return True
    return False


def _start_pm2_parent_watchdog(lock_path: str = _LOCK_FILE) -> None:
    """Сторож родителя под pm2 (15.09.2026, цикл рестартов 22 и 43 за вечер).

    Под pm2 бот — потомок node-обёртки scripts/bot_pm2.js. На Windows pm2 stop/restart завершает обёртку безусловно
    (обработчики сигналов node не срабатывают), а python-потомок оставался СИРОТОЙ с bot_instance.lock: новый
    экземпляр видел живой lock и выходил, pm2 поднимал его снова — по кругу. Обёртка передаёт свой PID в
    OKO_PM2_WRAPPER_PID; держим хэндл её процесса (PID не переиспользуется) и ждём её завершения — тогда снимаем
    lock и выходим сами. Вне pm2 (запуск из терминала) переменной нет — сторож не запускается."""
    ppid = int(os.environ.get("OKO_PM2_WRAPPER_PID") or 0)
    if ppid <= 0 or platform.system() != "Windows":
        return
    import ctypes
    import threading
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # 🔴 типы обязательны: по умолчанию ctypes режет HANDLE до 32 бит → WaitForSingleObject сразу WAIT_FAILED (проверено 15.09)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    handle = k32.OpenProcess(0x00100000, False, ppid)          # SYNCHRONIZE
    if not handle:
        logging.warning("[pm2-watch] не удалось открыть процесс обёртки pid=%s — сторож не запущен", ppid)
        return

    def _watch():
        rc = k32.WaitForSingleObject(handle, 0xFFFFFFFF)        # INFINITE: ждём завершения обёртки
        if rc != 0:                                             # не WAIT_OBJECT_0 — ожидание сломалось, НЕ выходим вслепую
            logging.error("[pm2-watch] ожидание обёртки вернуло %s (ошибка %s) — сторож остановлен", rc, ctypes.get_last_error())
            return
        logging.critical("[pm2-watch] обёртка pm2 (pid=%s) завершилась — выхожу, чтобы не остаться сиротой с lock", ppid)
        try:
            if open(lock_path, encoding="utf-8").read().strip() == str(os.getpid()):
                os.remove(lock_path)
        except Exception:
            pass
        os._exit(3)

    threading.Thread(target=_watch, daemon=True, name="pm2-parent-watch").start()
    logging.info("[pm2-watch] сторож обёртки pm2 запущен (pid обёртки %s)", ppid)


# ==============================
# Windows fix
# ==============================
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _backup_database(db_path: str = "subscriptions.db", backup_dir: str = "backups",
                     keep: int = 7, min_age_h: float = 24.0):
    """Локальный снимок БД при старте — «на всякий случай перед рестартом».

    11.08.2026, две правки после разбора рестартов:
    1. ЧАСТОТА. Копия делалась на КАЖДОМ старте. Вотчдог рестартил бота по одному
       просроченному пульсу ([[bug_watchdog_restarts_healthy_bot]]) — вышло 4 копии по
       937 МБ за вечер, 6.4 ГБ на ровном месте. Теперь пропускаем, если свежая копия
       моложе `min_age_h`.
    2. БЕЗОПАСНОСТЬ. Был `shutil.copy2` — файловая копия ЖИВОЙ базы может поймать её
       на середине записи и дать битый снимок. Теперь SQLite online-backup API
       (тот же метод, что в `scripts/backup_dbs.py::_hot_backup`).

    Это НЕ основной бэкап: основной делает pm2-крон `backup-dbs` (04:10, на ДРУГОЙ
    физический диск F:, gzip, ротация 14 дней + 8 недель). Здесь — локальная страховка.
    """
    if not os.path.exists(db_path):
        return
    os.makedirs(backup_dir, exist_ok=True)
    existing = sorted(glob.glob(os.path.join(backup_dir, "subscriptions_*.db")))
    if existing:
        age_h = (time.time() - os.path.getmtime(existing[-1])) / 3600
        if age_h < min_age_h:
            logging.info("DB backup: пропуск — свежая копия %.1fч назад (порог %.0fч)",
                         age_h, min_age_h)
            return
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    dst = os.path.join(backup_dir, f"subscriptions_{stamp}.db")
    try:
        src_con = sqlite3.connect(db_path, timeout=30)
        try:
            dst_con = sqlite3.connect(dst)
            try:
                src_con.backup(dst_con)        # атомарный снимок, безопасен при записи
            finally:
                dst_con.close()
        finally:
            src_con.close()
        logging.info("DB backup: %s (%.1f MB)", dst, os.path.getsize(dst) / 1e6)
    except Exception as e:
        logging.warning("DB backup failed: %s", e)
        try:
            os.path.exists(dst) and os.remove(dst)      # не оставлять огрызок
        except Exception:
            pass
        return
    old = sorted(glob.glob(os.path.join(backup_dir, "subscriptions_*.db")))
    while len(old) > keep:
        try:
            os.remove(old.pop(0))
        except Exception:
            pass


def _spawn_llm_background_jobs():
    """Fire-and-forget запуск Gemini-скриптов: trade review, log digest, post-mortem.

    Скрипты сами проверяют свежесть (--max-age-hours=18) — лишний рестарт бота не
    приведёт к лишним вызовам Gemini. Stdout/stderr пишутся в logs/llm_hooks.log.
    """
    import subprocess
    py = sys.executable
    log_dir = os.path.join(os.path.dirname(__file__) or ".", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "llm_hooks.log")
    jobs = [
        # daily trade review (разбор последних 24ч)
        [py, "tools/daily_trade_review.py", "--quiet", "--max-age-hours", "18"],
        # log digest (сжатие WARN/ERROR из последних 50MB лога)
        [py, "tools/daily_log_digest.py", "--quiet", "--max-age-hours", "18"],
        # post-mortem на R<-2 за 24ч (только новых, существующие не трогает)
        [py, "tools/trade_postmortem.py", "--quiet", "--hours", "24",
         "--threshold", "-2.0", "--limit", "5"],
        # session brief (если SessionStart hook не успел)
        [py, "tools/context_brief.py", "--quiet", "--max-age-hours", "6"],
        # Obsidian daily pipeline — ежедневный хаб Sessions/YYYY-MM-DD.md
        [py, "tools/daily_pipeline.py", "--quiet"],
        # Obsidian weekly digest — обновляем каждый запуск (идемпотентно)
        [py, "tools/weekly_digest.py", "--quiet"],
        # Obsidian indexer — пересобирает Index/TIMELINE.md
        [py, "tools/obsidian_indexer.py", "--quiet"],
        # Task linker — связывает задачи со сделками по signal_type+дате
        [py, "tools/task_linker.py", "--quiet"],
    ]
    try:
        with open(log_file, "a", encoding="utf-8") as fout:
            fout.write(f"\n=== {datetime.now().isoformat()} bot startup ===\n")
            for cmd in jobs:
                try:
                    # Detached: бот стартует не дожидаясь
                    creationflags = 0
                    if platform.system() == "Windows":
                        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
                    subprocess.Popen(
                        cmd, stdout=fout, stderr=fout,
                        cwd=os.path.dirname(__file__) or ".",
                        creationflags=creationflags,
                    )
                    logging.info("LLM hook spawned: %s", " ".join(cmd[1:]))
                except Exception as e:
                    logging.warning("LLM hook failed to spawn %s: %s", cmd, e)
    except Exception as e:
        logging.warning("LLM hooks setup failed: %s", e)


if __name__ == "__main__":
    # Гарантируем запуск из директории проекта (чтобы subscriptions.db был единым)
    _project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(_project_dir)

    # 🔴 15.09: lock — ПЕРВЫМ. Раньше бэкап БД и LLM-хуки шли до проверки, и каждый отбитый дубль в цикле рестартов
    # заново спаунил daily_pipeline/weekly_digest/obsidian_indexer/task_linker.
    if not _acquire_single_instance_lock():
        print("⚠️ Бот уже запущен (обнаружен lock-файл). Закрываю второй экземпляр.")
        sys.exit(1)
    _start_pm2_parent_watchdog()

    _backup_database()
    _spawn_llm_background_jobs()

    from bot.core.bot import TradingAlertBot
    TradingAlertBot().run()
