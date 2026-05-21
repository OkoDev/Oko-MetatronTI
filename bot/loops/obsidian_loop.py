"""Obsidian daily pipeline — ежедневный запуск в 00:05 UTC."""
import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_SCRIPTS = [
    ["tools/daily_pipeline.py", "--quiet"],
    ["tools/weekly_digest.py", "--quiet"],
    ["tools/obsidian_indexer.py", "--quiet"],
    ["tools/task_linker.py", "--quiet"],
]


async def _run_script(args: list[str]) -> None:
    name = args[0]
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            logger.warning(
                "[obsidian] %s exit=%d stderr=%s",
                name, proc.returncode,
                stderr.decode("utf-8", errors="replace")[:300],
            )
        else:
            logger.info("[obsidian] %s OK", name)
    except asyncio.TimeoutError:
        logger.warning("[obsidian] %s timeout 120s", name)
    except Exception as e:
        logger.warning("[obsidian] %s error: %s", name, e)


def _seconds_until(hour: int, minute: int) -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def obsidian_daily_loop(_bot) -> None:
    """Ежедневно в 00:05 UTC запускает Obsidian pipeline (sequential)."""
    while True:
        wait = _seconds_until(hour=0, minute=5)
        logger.info("[obsidian] следующий запуск через %.0f мин (00:05 UTC)", wait / 60)
        await asyncio.sleep(wait)

        logger.info("[obsidian] daily pipeline start")
        for script in _SCRIPTS:
            await _run_script(script)
        logger.info("[obsidian] daily pipeline done")
