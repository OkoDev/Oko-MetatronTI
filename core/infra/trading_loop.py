"""⚡ PERF-LOOP-DRIFT шаг B (13.06): выделенный asyncio event loop для торговли
в отдельном daemon-потоке.

Зачем: торговые REST-запросы (sync_time/get_positions/place/cancel) в главном loop
тонут среди сотен scan/observer корутин (scheduler starvation) → rtt 9-16с →
timestamp invalid → рассинхрон БД↔биржа (DRIFT). Отдельный loop даёт торговле
СОБСТВЕННУЮ ready-очередь → callbacks планируются мгновенно, независимо от scan-нагрузки.

Шаг 1 = ТОЛЬКО инфраструктура за флагом `trading.dedicated_loop` (default false).
При off — loop не стартует, торговля как раньше (нулевой риск, мёртвый код).
Подключение торговых вызовов — шаги 2+.

Prerequisite: шаг 0 (GlobalRateLimiter на threading.Lock — loop-agnostic, коммит 4248df1),
иначе cross-loop acquire() крашнется. План: docs/PLAN_PERF_LOOP_DRIFT_B.md.

ВАЖНО (deadlock-аудит DS): торговый loop = ТОЛЬКО REST. DB-записи (6 точек) остаются
в main loop через очередь (call_soon_threadsafe) — sqlite3 write-lock cross-loop = deadlock.
"""
import asyncio
import concurrent.futures
import logging
import threading
from typing import Any, Coroutine, Optional

logger = logging.getLogger(__name__)


class TradingLoop:
    """Выделенный asyncio event loop в daemon-потоке для торговых операций."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    def start(self) -> None:
        """Запускает поток с собственным event loop. Идемпотентно."""
        if self._thread is not None:
            return

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            self._ready.set()
            logger.info("[TradingLoop] запущен в отдельном потоке (tid=%s)", threading.get_ident())
            try:
                loop.run_forever()
            finally:
                loop.close()
                logger.info("[TradingLoop] остановлен")

        self._thread = threading.Thread(target=_runner, name="TradingLoop", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            logger.error("[TradingLoop] не успел стартовать за 5с")

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        return self._loop

    @property
    def running(self) -> bool:
        return self._loop is not None and self._loop.is_running()

    def submit(self, coro: Coroutine) -> "concurrent.futures.Future":
        """Запустить coroutine в торговом loop из ЛЮБОГО потока. Возвращает concurrent.futures.Future.
        Для sync-контекста: fut.result(timeout=...). Для async — см. call()."""
        if not self.running:
            raise RuntimeError("TradingLoop не запущен")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def call(self, coro: Coroutine) -> Any:
        """Вызвать coroutine в торговом loop и дождаться результата БЕЗ блокировки
        вызывающего (main) loop. wrap_future пробрасывает оригинальный exception+traceback."""
        return await asyncio.wrap_future(self.submit(coro))

    def stop(self) -> None:
        """Graceful shutdown (для тестов/перезапуска; в проде daemon умирает с процессом)."""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None
        self._loop = None
        self._ready.clear()


_trading_loop: Optional[TradingLoop] = None


def get_trading_loop() -> Optional[TradingLoop]:
    """Синглтон торгового loop. None если не инициализирован/выключен флагом."""
    return _trading_loop


def init_trading_loop(enabled: bool) -> Optional[TradingLoop]:
    """Инициализирует и запускает торговый loop, если enabled. Идемпотентно.
    Вызывается из bot.run() при старте. При enabled=false → None (старое поведение)."""
    global _trading_loop
    if not enabled:
        return None
    if _trading_loop is None:
        _trading_loop = TradingLoop()
        _trading_loop.start()
    return _trading_loop
