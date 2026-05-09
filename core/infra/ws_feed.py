"""
WsFeed — WebSocket поток real-time данных через ccxt.pro BingX.

Фаза 1 (активна): watch_ticker — батчи по 100 пар, каждый = отдельный WS.
  → trade_tracker получает цену мгновенно (dict lookup), без REST
  → если цена далеко от SL/TP/TSL → REST пропускается полностью

Фаза 2 (активна): watch_ohlcv для пар с открытыми сделками
  → обновляет ApiEngine OHLCV-кеш при закрытии свечи
  → scan_loop читает из кеша — REST не нужен для приоритетных пар

Публичный API:
    await ws_feed.start(pairs, priority_pairs)  — запуск (asyncio.create_task)
    ws_feed.get_price(symbol)                   — real-time цена или None
    ws_feed.update_priority_pairs(pairs)        — добавить OHLCV-подписки
    ws_feed.is_alive()                          — True если есть активные тикеры
    ws_feed.stats()                             — счётчики для мониторинга
"""
import asyncio
import logging
import os
import time
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Пар на один WS-батч. BingX лимит ~200-300 подписок на соединение.
# 100 пар × 1 подписка = безопасный запас. 534 пары → 6 батчей.
_BATCH_SIZE      = 100
_RECONNECT_DELAY = 5.0   # пауза перед reconnect (сек)
_PRICE_TTL       = 60.0  # цена считается устаревшей через N сек
_OHLCV_TF        = "15m" # TF для OHLCV-подписок (фаза 2)


class WsFeed:
    """WebSocket feed: real-time тикеры и OHLCV через ccxt.pro BingX."""

    def __init__(self, ohlcv_cache=None, api_key: str = "", secret: str = ""):
        """
        Args:
            ohlcv_cache: ссылка на ApiEngine._cache — для обновления из WS (фаза 2)
            api_key: BingX API ключ (должен совпадать с execution_mode: VST или LIVE)
            secret:  BingX Secret ключ
        """
        self._ohlcv_cache = ohlcv_cache
        self._api_key = api_key
        self._secret  = secret

        # {symbol: (price, timestamp)} — обновляется при каждом тике
        self._ws_prices: Dict[str, tuple] = {}
        self._active_tickers: Set[str]    = set()
        self._active_ohlcv: Set[str]      = set()  # фаза 2

        self._running     = False
        self._tasks: List[asyncio.Task] = []

        # Счётчики
        self._ticker_updates = 0
        self._ohlcv_updates  = 0
        self._errors         = 0
        self._started_at: Optional[float] = None

    # ── Публичный API ──────────────────────────────

    def get_price(self, symbol: str) -> Optional[float]:
        """Real-time цена. None если нет или устарела (>60 сек)."""
        entry = self._ws_prices.get(symbol)
        if not entry:
            return None
        price, ts = entry
        return price if time.time() - ts <= _PRICE_TTL else None

    def is_alive(self) -> bool:
        return self._running and len(self._active_tickers) > 0

    def stats(self) -> dict:
        return {
            "running":        self._running,
            "active_tickers": len(self._active_tickers),
            "active_ohlcv":   len(self._active_ohlcv),
            "ticker_updates": self._ticker_updates,
            "ohlcv_updates":  self._ohlcv_updates,
            "errors":         self._errors,
            "uptime_sec":     int(time.time() - self._started_at) if self._started_at else 0,
        }

    async def start(self, pairs: List[str], priority_pairs: Optional[List[str]] = None) -> None:
        """Запускает WsFeed. Вызывать через asyncio.create_task."""
        self._running    = True
        self._started_at = time.time()

        # Фаза 1: ticker-батчи по _BATCH_SIZE пар — стартуем с задержкой 2 сек между батчами
        # чтобы не создавать spike соединений на BingX и не throttlить REST API скана
        batches = [pairs[i:i+_BATCH_SIZE] for i in range(0, len(pairs), _BATCH_SIZE)]
        ticker_tasks = []
        for idx, batch in enumerate(batches):
            if idx > 0:
                await asyncio.sleep(2.0)  # 2 сек между батчами
            ticker_tasks.append(asyncio.create_task(self._ticker_batch(batch, idx)))

        # Фаза 2: OHLCV — отключена до отладки (errors=389K за 5 мин → throttle REST)
        # TODO: разобраться с форматом символов для watch_ohlcv на BingX ccxt.pro
        ohlcv_tasks = []
        # if priority_pairs and self._ohlcv_cache is not None:
        #     for sym in priority_pairs[:50]:
        #         ohlcv_tasks.append(asyncio.create_task(self._ohlcv_loop(sym)))

        self._tasks = ticker_tasks + ohlcv_tasks
        logger.info("[WsFeed] Старт: %d пар → %d батчей + %d OHLCV подписок",
                    len(pairs), len(batches), len(ohlcv_tasks))

        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            logger.info("[WsFeed] Остановлен | tickers=%d updates=%d errors=%d",
                        len(self._active_tickers), self._ticker_updates, self._errors)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()

    def update_priority_pairs(self, priority_pairs: List[str]) -> None:
        """Фаза 2: добавить OHLCV-подписки для новых пар (при открытии сделки)."""
        if self._ohlcv_cache is None or not self._running:
            return
        for sym in priority_pairs:
            if sym not in self._active_ohlcv:
                t = asyncio.create_task(self._ohlcv_loop(sym))
                self._tasks.append(t)

    # ── Внутренние методы ─────────────────────────

    def _make_exchange(self):
        """Создаёт отдельный ccxt.pro инстанс для батча (изоляция соединений).

        watch_ticker на BingX — публичный стрим, ключи не нужны и вызывают 100413.
        """
        import ccxt.pro as ccxtpro
        return ccxtpro.bingx({
            "options": {"defaultType": "swap"},
            "enableRateLimit": False,
        })

    async def _ticker_batch(self, batch: List[str], batch_idx: int) -> None:
        """Непрерывный батч-цикл: один exchange на _BATCH_SIZE пар, reconnect при ошибке."""
        exchange = self._make_exchange()
        consecutive_errors = 0

        while self._running:
            try:
                # Все пары батча слушаем параллельно на одном соединении
                await asyncio.gather(
                    *[self._watch_ticker(exchange, sym) for sym in batch],
                    return_exceptions=True,
                )
                consecutive_errors = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                self._errors += 1
                delay = min(_RECONNECT_DELAY * consecutive_errors, 60.0)
                logger.warning("[WsFeed] batch=%d ошибка #%d: %s — reconnect через %.0fs",
                               batch_idx, consecutive_errors, e, delay)
                await asyncio.sleep(delay)

        try:
            await exchange.close()
        except Exception:
            pass

    async def _watch_ticker(self, exchange, symbol: str) -> None:
        """Подписка на тикер одного символа внутри батча."""
        self._active_tickers.add(symbol)
        try:
            while self._running:
                ticker = await asyncio.wait_for(
                    exchange.watch_ticker(symbol),
                    timeout=30.0,
                )
                price = ticker.get("last") or ticker.get("close")
                if price and price > 0:
                    self._ws_prices[symbol] = (float(price), time.time())
                    self._ticker_updates += 1
                    # Куб: Сфера 2 → PairContextBus (tick_price)
                    _pcb = getattr(self, "_pair_context_bus", None)
                    if _pcb is not None and self._ticker_updates % 10 == 0:
                        # Throttle: публикуем каждый 10-й тик (не перегружать bus)
                        try:
                            from core.context.pair_context import SphereEvent
                            _pcb.publish(symbol, SphereEvent.TICK_PRICE, {
                                "price": float(price),
                                "volume_24h": float(ticker.get("quoteVolume", 0) or 0),
                            })
                        except Exception:
                            pass
        except asyncio.TimeoutError:
            logger.debug("[WsFeed] ticker timeout: %s", symbol)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if self._errors < 3:  # первые 3 ошибки — WARNING для диагностики
                logger.warning("[WsFeed] ticker error %s: %s (%s)", symbol, e, type(e).__name__)
            else:
                logger.debug("[WsFeed] ticker error %s: %s", symbol, e)
            self._errors += 1
        finally:
            self._active_tickers.discard(symbol)

    async def _ohlcv_loop(self, symbol: str) -> None:
        """Фаза 2: OHLCV-подписка. Обновляет ApiEngine cache при закрытии свечи."""
        if self._ohlcv_cache is None:
            return
        exchange = self._make_exchange()
        self._active_ohlcv.add(symbol)
        logger.debug("[WsFeed] OHLCV подписка: %s %s", symbol, _OHLCV_TF)

        while self._running:
            try:
                candles = await asyncio.wait_for(
                    exchange.watch_ohlcv(symbol, _OHLCV_TF),
                    timeout=120.0,
                )
                if candles:
                    self._push_ohlcv_to_cache(symbol, candles)
                    self._ohlcv_updates += 1
            except asyncio.TimeoutError:
                logger.debug("[WsFeed] ohlcv timeout: %s", symbol)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("[WsFeed] ohlcv error %s: %s", symbol, e)
                self._errors += 1
                await asyncio.sleep(_RECONNECT_DELAY)

        self._active_ohlcv.discard(symbol)
        try:
            await exchange.close()
        except Exception:
            pass

    def _push_ohlcv_to_cache(self, symbol: str, candles: list) -> None:
        """Конвертирует WS OHLCV → DataFrame и пишет в ApiEngine._cache."""
        try:
            import pandas as pd
            df = pd.DataFrame(
                candles,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            self._ohlcv_cache.set((symbol, _OHLCV_TF), df, limit=len(df))
            logger.debug("[WsFeed] cache updated: %s %s (%d bars)", symbol, _OHLCV_TF, len(df))
        except Exception as e:
            logger.debug("[WsFeed] cache push error %s: %s", symbol, e)
