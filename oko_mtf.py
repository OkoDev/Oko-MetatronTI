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

from core.infra.config_loader import config

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

    _backup_database()
    _spawn_llm_background_jobs()

    if not _acquire_single_instance_lock():
        print("⚠️ Бот уже запущен (обнаружен lock-файл). Закрываю второй экземпляр.")
        sys.exit(1)

    from bot.core.bot import TradingAlertBot
    TradingAlertBot().run()
