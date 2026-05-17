"""Watch List periodic loop — запускает daily_trade_review.py каждые 4 часа."""
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_INTERVAL_SECONDS = 4 * 3600   # 4 часа


async def watchlist_loop(_bot) -> None:
    """Каждые 4ч запускает Watch List review (composite PNG + Gemini Vision → TG).

    Первый запуск через 4ч — startup уже сделал первый запуск через
    _spawn_llm_background_jobs() при старте oko_mtf.py.
    """
    logger.info("[watchlist_loop] запланирован через %.0f ч", _INTERVAL_SECONDS / 3600)
    while True:
        await asyncio.sleep(_INTERVAL_SECONDS)
        logger.info("[watchlist_loop] старт Watch List review")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "tools/daily_trade_review.py", "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            if proc.returncode != 0:
                logger.warning(
                    "[watchlist_loop] exit=%d stderr=%s",
                    proc.returncode,
                    stderr.decode("utf-8", errors="replace")[:400],
                )
            else:
                first_line = stderr.decode("utf-8", errors="replace").splitlines()[0] if stderr else "OK"
                logger.info("[watchlist_loop] OK — %s", first_line)
        except asyncio.TimeoutError:
            logger.warning("[watchlist_loop] timeout 300s")
        except Exception as e:
            logger.warning("[watchlist_loop] error: %s", e)
