"""
Точка входа Oko MTF Bot.
Бизнес-логика и инициализация — в bot/core/bot.py.
"""
import logging
import platform
import sys
import os
import atexit
import asyncio
import shutil
import glob
from datetime import datetime

from core.config_loader import config

# ==============================
# Логирование
# ==============================
logging.basicConfig(
    level=getattr(logging, config.get("logging.level", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("crypto_bot.log", encoding="utf-8"),
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


def _acquire_single_instance_lock(lock_path: str = _LOCK_FILE) -> bool:
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
        return False
    except Exception:
        logging.warning("Не удалось создать lock-файл. Продолжаю без блокировки.")
        return True


# ==============================
# Windows fix
# ==============================
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _backup_database(db_path: str = "subscriptions.db", backup_dir: str = "backups", keep: int = 7):
    """Автоматический бэкап БД при старте. Хранит последние `keep` копий."""
    if not os.path.exists(db_path):
        return
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    dst = os.path.join(backup_dir, f"subscriptions_{stamp}.db")
    try:
        shutil.copy2(db_path, dst)
        logging.info("DB backup: %s (%.1f MB)", dst, os.path.getsize(dst) / 1e6)
    except Exception as e:
        logging.warning("DB backup failed: %s", e)
        return
    old = sorted(glob.glob(os.path.join(backup_dir, "subscriptions_*.db")))
    while len(old) > keep:
        try:
            os.remove(old.pop(0))
        except Exception:
            pass


if __name__ == "__main__":
    # Гарантируем запуск из директории проекта (чтобы subscriptions.db был единым)
    _project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(_project_dir)

    _backup_database()

    if not _acquire_single_instance_lock():
        print("⚠️ Бот уже запущен (обнаружен lock-файл). Закрываю второй экземпляр.")
        sys.exit(1)

    from bot.core.bot import TradingAlertBot
    TradingAlertBot().run()
