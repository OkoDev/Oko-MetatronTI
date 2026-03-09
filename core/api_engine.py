"""
API Engine — транспортный слой над ccxt.

Предоставляет: TTL-кеш с LRU eviction, in-flight deduplication,
retry с exponential backoff, circuit breaker, централизованный семафор.

Используется исключительно через RealTimeData (data_collector.py).
Публичный интерфейс data_collector НЕ меняется.
"""

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Optional

import ccxt.async_support as ccxt
import pandas as pd

logger = logging.getLogger(__name__)

# TTL (сек) совпадает с data_collector._CACHE_TTL
_CACHE_TTL: dict[str, float] = {
    "1m": 15, "3m": 30, "5m": 45,
    "15m": 60, "45m": 120,
    "1h": 180, "4h": 300, "1d": 600, "1w": 3600,
}
_DEFAULT_TTL: float = 60.0


class OhlcvCache:
    """TTL-кеш с LRU eviction.

    При 600 парах × 8 TF без eviction кеш растёт бесконтрольно.
    maxsize=5000 ≈ 600 пар × 8 TF × запас на разные limit-запросы.
    """

    def __init__(self, maxsize: int = 5000):
        self._data: OrderedDict = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: tuple, limit: int, ttl: float) -> Optional[pd.DataFrame]:
        """Возвращает копию DataFrame если кеш актуален и limit достаточен."""
        entry = self._data.get(key)
        if entry is None:
            return None
        if (time.monotonic() - entry["ts"]) >= ttl:
            return None
        if entry["limit"] < limit:
            return None
        # LRU: обновляем позицию при попадании
        self._data.move_to_end(key)
        return entry["df"].copy()

    def set(self, key: tuple, df: pd.DataFrame, limit: int) -> None:
        """Записывает запись в кеш, вытесняя старейшую при переполнении."""
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = {"df": df, "ts": time.monotonic(), "limit": limit}
        # Evict oldest entries
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)


class CircuitBreaker:
    """Автоматический выключатель для защиты от каскадных сбоев.

    Состояния:
    - CLOSED (норма): запросы проходят
    - OPEN (сбой): после threshold ошибок — fast-fail на timeout сек
    - HALF_OPEN (восстановление): один пробный запрос; успех → CLOSED
    """

    _CLOSED = "closed"
    _OPEN = "open"
    _HALF_OPEN = "half_open"

    def __init__(self, threshold: int = 10, timeout: float = 30.0):
        self._state = self._CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._threshold = threshold
        self._timeout = timeout

    @property
    def state(self) -> str:
        return self._state

    def is_open(self) -> bool:
        """True = запрос нужно отклонить (fast-fail)."""
        if self._state == self._OPEN:
            if time.monotonic() - self._opened_at >= self._timeout:
                self._state = self._HALF_OPEN
                logger.info("CircuitBreaker HALF_OPEN — пробный запрос")
                return False  # пропускаем один пробный запрос
            return True
        return False

    def record_success(self) -> None:
        if self._state != self._CLOSED:
            logger.info("CircuitBreaker CLOSED — API восстановлен")
        self._failures = 0
        self._state = self._CLOSED

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold and self._state == self._CLOSED:
            self._state = self._OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "CircuitBreaker OPEN — %d ошибок подряд, fast-fail на %.0f сек",
                self._failures, self._timeout,
            )


class ApiEngine:
    """Транспортный слой над ccxt.

    Для каждого get_ohlcv-вызова порядок проверок:
    1. TTL-кеш (LRU, с учётом limit)
    2. Circuit breaker fast-fail
    3. In-flight deduplication (одинаковый key → один API-вызов)
    4. Retry с exponential backoff (NetworkError: 3×, RateLimitExceeded: 3×)
    5. Запись в кеш при успехе
    """

    def __init__(self, exchange, semaphore_size: int = 20):
        self._exchange = exchange
        self._cache = OhlcvCache(maxsize=5000)
        self._cb = CircuitBreaker(threshold=10, timeout=30.0)
        # Централизованный семафор — единственная точка ограничения параллельных API-вызовов
        self._sem = asyncio.Semaphore(semaphore_size)
        # In-flight dedup: (symbol, timeframe, limit) → asyncio.Future
        self._in_flight: dict[tuple, asyncio.Future] = {}

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        since: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        """Основной метод получения OHLCV. Thread-safe для asyncio."""
        cache_key = (symbol, timeframe)
        dedup_key = (symbol, timeframe, limit)
        ttl = _CACHE_TTL.get(timeframe, _DEFAULT_TTL)

        # 1. Кеш
        cached = self._cache.get(cache_key, limit, ttl)
        if cached is not None:
            return cached

        # 2. Circuit breaker
        if self._cb.is_open():
            return None

        # 3. In-flight deduplication
        if dedup_key in self._in_flight:
            fut = self._in_flight[dedup_key]
            try:
                df = await asyncio.shield(fut)
                return df.copy() if df is not None else None
            except Exception:
                return None

        # 4. Создаём Future для этого запроса (другие корутины будут его ждать)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._in_flight[dedup_key] = fut

        try:
            result = await self._fetch_with_retry(symbol, timeframe, limit, since)
            # Любой ответ от API (даже пустой) = API доступен → success
            self._cb.record_success()
            if result is not None:
                self._cache.set(cache_key, result, limit)
            if not fut.done():
                fut.set_result(result)
            return result.copy() if result is not None else None
        except Exception as exc:
            # Только реальные сбои сети/rate-limit после всех retry → failure
            self._cb.record_failure()
            if not fut.done():
                fut.set_exception(exc)
            return None
        finally:
            self._in_flight.pop(dedup_key, None)

    async def _fetch_with_retry(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        since: Optional[int],
    ) -> Optional[pd.DataFrame]:
        """3 попытки с exponential backoff. Различает постоянные и временные ошибки."""
        last_exc = None
        for attempt in range(3):
            try:
                async with self._sem:
                    candles = await self._exchange.fetch_ohlcv(
                        symbol, timeframe=timeframe, limit=limit, since=since
                    )
                if not candles:
                    return None
                df = pd.DataFrame(
                    candles, columns=["time", "open", "high", "low", "close", "volume"]
                )
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                return df

            except ccxt.RateLimitExceeded as exc:
                wait = 5.0 * (2 ** attempt)
                logger.warning(
                    "RateLimitExceeded %s %s — пауза %.1f сек (попытка %d/3)",
                    symbol, timeframe, wait, attempt + 1,
                )
                await asyncio.sleep(wait)
                last_exc = exc

            except ccxt.NetworkError as exc:
                wait = 1.0 * (2 ** attempt)
                logger.debug(
                    "NetworkError %s %s — retry через %.1f сек", symbol, timeframe, wait
                )
                await asyncio.sleep(wait)
                last_exc = exc

            except (ccxt.ExchangeError, ccxt.BadSymbol) as exc:
                # Постоянная ошибка (неверный символ, недоступный инструмент) — не ретраить
                logger.debug("ExchangeError %s %s: %s (без retry)", symbol, timeframe, exc)
                return None

            except Exception as exc:
                logger.debug("fetch_ohlcv unexpected error %s %s: %s", symbol, timeframe, exc)
                last_exc = exc
                break

        # Retry исчерпаны — бросаем исключение, чтобы fetch_ohlcv вызвал record_failure()
        if last_exc is not None:
            logger.debug(
                "fetch_ohlcv %s %s: все попытки исчерпаны: %s", symbol, timeframe, last_exc
            )
            raise last_exc
        return None

    async def fetch_ticker(self, symbol: str) -> Optional[dict]:
        """Тикер — без кеша, с circuit breaker и одной retry."""
        if self._cb.is_open():
            return None
        for attempt in range(2):
            try:
                async with self._sem:
                    result = await self._exchange.fetch_ticker(symbol)
                self._cb.record_success()
                return result
            except ccxt.RateLimitExceeded:
                await asyncio.sleep(3.0 * (2 ** attempt))
            except Exception as exc:
                logger.debug("fetch_ticker %s: %s", symbol, exc)
                return None
        return None

    def cache_stats(self) -> dict:
        """Диагностика: размер кеша, состояние circuit breaker, in-flight запросы."""
        return {
            "cache_size": len(self._cache),
            "cb_state": self._cb.state,
            "in_flight": len(self._in_flight),
        }
