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
# D-066 STABLE (25.05 21:15): rollback к Phase D — 1 instance × ≤120 пар.
# Phase F (1×240) дал плато scan_loop 750s — нелинейный overhead в ccxt.pro.
_OHLCV_BATCH_SIZE = 120
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

        # D-066 Phase E: multi-instance OHLCV + dynamic add.
        # {batch_idx: {"exchange": ccxt, "pairs": Set[str], "tasks": dict[symbol, Task]}}
        self._ohlcv_batches: Dict[int, dict] = {}
        self._ohlcv_batch_seq = 0   # счётчик idx для новых батчей
        self._ohlcv_lock: Optional[asyncio.Lock] = None   # создаётся в start() (требует loop)

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
        if self._ohlcv_lock is None:
            self._ohlcv_lock = asyncio.Lock()

        # Фаза 1: ticker-батчи по _BATCH_SIZE пар — стартуем с задержкой 2 сек между батчами
        # чтобы не создавать spike соединений на BingX и не throttlить REST API скана
        batches = [pairs[i:i+_BATCH_SIZE] for i in range(0, len(pairs), _BATCH_SIZE)]
        ticker_tasks = []
        for idx, batch in enumerate(batches):
            if idx > 0:
                await asyncio.sleep(2.0)  # 2 сек между батчами
            ticker_tasks.append(asyncio.create_task(self._ticker_batch(batch, idx)))

        # D-066 Phase E: multi-instance OHLCV — все priority_pairs распределяются
        # по N батчам ≤ _OHLCV_BATCH_SIZE. Каждый batch = свой ccxt instance.
        # 240 пар × 100 = 3 батча (3 WS connection). Dynamic add через
        # update_priority_pairs → новые пары попадают в свободный слот или
        # создаётся новый batch автоматически.
        ohlcv_tasks = []
        if priority_pairs and self._ohlcv_cache is not None:
            _ohlcv_pairs = list(priority_pairs)
            ohlcv_batches = [
                _ohlcv_pairs[i:i+_OHLCV_BATCH_SIZE]
                for i in range(0, len(_ohlcv_pairs), _OHLCV_BATCH_SIZE)
            ]
            logger.info(
                "[WsFeed][D-066 PhE] OHLCV multi-instance: %d пар → %d батча × ~%d",
                len(_ohlcv_pairs), len(ohlcv_batches), _OHLCV_BATCH_SIZE,
            )
            for idx, batch in enumerate(ohlcv_batches):
                if idx > 0:
                    await asyncio.sleep(2.0)  # spacing connections (как у tickers)
                self._ohlcv_batch_seq = max(self._ohlcv_batch_seq, idx + 1)
                ohlcv_tasks.append(asyncio.create_task(
                    self._ohlcv_batch_loop(batch, batch_idx=idx)
                ))

        self._tasks = ticker_tasks + ohlcv_tasks
        logger.info("[WsFeed] Старт: %d пар → %d ticker батчей + %d OHLCV батчей",
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

    def reset(self) -> None:
        """D-053: сброс состояния для чистого перезапуска через start()."""
        self._running = False
        self._tasks = []
        self._ws_prices = {}
        self._active_tickers = set()
        self._active_ohlcv = set()
        self._ohlcv_batches = {}
        self._ohlcv_batch_seq = 0
        self._ohlcv_lock = None  # пересоздаётся в start()

    def update_priority_pairs(self, priority_pairs: List[str]) -> None:
        """Фаза 2 (D-066 Phase E): dynamic add OHLCV-подписок при открытии сделки.

        Стратегия:
          - Для каждой новой пары: найти batch с len(pairs) < _OHLCV_BATCH_SIZE
          - Если найден → добавить task в существующий instance
          - Если все batches полные → создать новый batch_loop (новый WS connection)
        """
        if self._ohlcv_cache is None or not self._running:
            return
        new_pairs = [s for s in priority_pairs if s not in self._active_ohlcv]
        if not new_pairs:
            return
        # schedule async add (метод не async — вызывается из sync кода)
        asyncio.create_task(self._add_pairs_async(new_pairs))

    async def _add_pairs_async(self, new_pairs: List[str]) -> None:
        """Добавление пар в существующие батчи или создание новых."""
        async with self._ohlcv_lock:
            added_to_existing = 0
            overflow: List[str] = []
            for sym in new_pairs:
                if sym in self._active_ohlcv:
                    continue
                # Найти batch с местом
                target_batch = None
                for idx, info in self._ohlcv_batches.items():
                    if len(info["pairs"]) < _OHLCV_BATCH_SIZE:
                        target_batch = (idx, info)
                        break
                if target_batch is None:
                    overflow.append(sym)
                    continue
                idx, info = target_batch
                info["pairs"].add(sym)
                info["tasks"][sym] = asyncio.create_task(
                    self._watch_ohlcv_single(info["exchange"], sym)
                )
                added_to_existing += 1

            if added_to_existing:
                logger.info(
                    "[WsFeed][D-066 PhE] dynamic add: %d пар → существующие батчи",
                    added_to_existing,
                )

            # Overflow → создать новый batch
            while overflow:
                chunk = overflow[:_OHLCV_BATCH_SIZE]
                overflow = overflow[_OHLCV_BATCH_SIZE:]
                new_idx = self._ohlcv_batch_seq
                self._ohlcv_batch_seq += 1
                logger.info(
                    "[WsFeed][D-066 PhE] dynamic NEW batch=%d создан для %d пар",
                    new_idx, len(chunk),
                )
                task = asyncio.create_task(
                    self._ohlcv_batch_loop(chunk, batch_idx=new_idx)
                )
                self._tasks.append(task)

    # ── Внутренние методы ─────────────────────────

    def _make_exchange(self):
        """Создаёт отдельный ccxt.pro инстанс для батча (изоляция соединений).

        watch_ticker на BingX — публичный стрим, ключи не нужны и вызывают 100413.
        """
        import ccxt.pro as ccxtpro
        return ccxtpro.bingx({
            "options": {
                "defaultType": "swap",
                # D-071 Quick Win #1: запрет автоматического market reload (раз в час)
                "fetchMarketsThrottle": 3600 * 1000,
            },
            "enableRateLimit": False,
            "timeout": 30000,   # D-071 Quick Win #2: 10s → 30s
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

    async def _ohlcv_batch_loop(self, initial_pairs: List[str], batch_idx: int) -> None:
        """D-066 Phase E: multi-instance OHLCV с dynamic add.

        Каждый batch держит свой ccxt instance + dict per-symbol tasks
        (НЕ gather — чтобы можно было добавлять/убирать пары на лету).
        Health-check loop: при массовых ошибках (>50% tasks dead) reconnect.

        State хранится в self._ohlcv_batches[batch_idx]:
            {"exchange": ex, "pairs": Set[str], "tasks": dict[symbol, Task]}
        """
        if self._ohlcv_cache is None:
            return
        consecutive_reconnects = 0
        while self._running:
            exchange = self._make_exchange()
            info = {
                "exchange": exchange,
                "pairs": set(initial_pairs),
                "tasks": {},
            }
            self._ohlcv_batches[batch_idx] = info
            logger.info(
                "[WsFeed][D-066 PhE] batch=%d START: %d пар на 1 instance",
                batch_idx, len(initial_pairs),
            )
            # Создаём task на каждую пару
            for sym in initial_pairs:
                info["tasks"][sym] = asyncio.create_task(
                    self._watch_ohlcv_single(exchange, sym)
                )

            try:
                # Health-check: периодически проверяем что tasks живы.
                # При массовом fail (>50% мертвы) → reconnect всего instance.
                while self._running:
                    await asyncio.sleep(30.0)
                    tasks = info["tasks"]
                    if not tasks:
                        continue
                    dead = sum(1 for t in tasks.values() if t.done())
                    if dead >= max(2, len(tasks) // 2):
                        raise RuntimeError(
                            f"batch={batch_idx} unhealthy: {dead}/{len(tasks)} tasks dead"
                        )
                consecutive_reconnects = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_reconnects += 1
                self._errors += 1
                delay = min(_RECONNECT_DELAY * consecutive_reconnects, 60.0)
                logger.warning(
                    "[WsFeed][D-066 PhE] batch=%d reconnect #%d: %s (%s) — через %.0fs",
                    batch_idx, consecutive_reconnects, e, type(e).__name__, delay,
                )
                # initial_pairs для recreate = текущий snapshot pairs из info
                initial_pairs = list(info["pairs"])
                await asyncio.sleep(delay)
            finally:
                # Cancel all per-symbol tasks
                for t in list(info["tasks"].values()):
                    if not t.done():
                        t.cancel()
                try:
                    await exchange.close()
                except Exception:
                    pass
                self._ohlcv_batches.pop(batch_idx, None)

    async def _watch_ohlcv_single(self, exchange, symbol: str) -> None:
        """Подписка watch_ohlcv для одного символа на shared exchange instance.

        D-066 Phase C+trace: добавлен per-call timing для диагностики
        — где зависает event loop (внутри await? между ними?).
        """
        self._active_ohlcv.add(symbol)
        first_update = False
        loop_errors = 0
        loop_window_start = time.time()
        call_count = 0
        logger.debug("[WsFeed][D-066] OHLCV START symbol='%s' tf=%s", symbol, _OHLCV_TF)
        try:
            while self._running:
                try:
                    t_call = time.monotonic()
                    candles = await exchange.watch_ohlcv(symbol, _OHLCV_TF)
                    elapsed = time.monotonic() - t_call
                    call_count += 1
                    # D-066: SLOW warning только если > 60s (реальная подозрительная пауза).
                    # 5-30s для 15m TF = нормальное ожидание между WS updates.
                    if elapsed > 60.0:
                        logger.warning(
                            "[WsFeed][D-066] %s SLOW await %.1fs",
                            symbol, elapsed,
                        )
                    if candles:
                        self._push_ohlcv_to_cache(symbol, candles)
                        self._ohlcv_updates += 1
                        if not first_update:
                            first_update = True
                            logger.debug(
                                "[WsFeed][D-066] FIRST UPDATE %s: %d bars",
                                symbol, len(candles),
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self._errors += 1
                    loop_errors += 1
                    if loop_errors <= 5:
                        logger.warning(
                            "[WsFeed][D-066 PhC] ohlcv error #%d %s: %s (%s)",
                            loop_errors, symbol, e, type(e).__name__,
                        )
                    else:
                        logger.debug("[WsFeed] ohlcv error %s: %s", symbol, e)
                    # Safety kill: > 30 errors / min → re-raise чтобы batch reconnect
                    now = time.time()
                    if loop_errors >= 30 and (now - loop_window_start) < 60:
                        logger.error(
                            "[WsFeed][D-066 PhC] SAFETY KILL %s: %d errors/%ds — re-raise",
                            symbol, loop_errors, int(now - loop_window_start),
                        )
                        raise
                    if (now - loop_window_start) >= 60:
                        loop_window_start = now
                        loop_errors = 0
                    await asyncio.sleep(1.0)
        finally:
            self._active_ohlcv.discard(symbol)

    def _push_ohlcv_to_cache(self, symbol: str, candles: list) -> None:
        """D-066 Phase B: конвертирует WS OHLCV в формат REST + merge с существующим кешем.

        Формат идентичен api_engine._fetch_with_retry: columns time/o/h/l/c/v, time=int ms.
        Вместо overwrite — вызываем cache.merge() который сохраняет историю REST.
        """
        try:
            import pandas as pd
            df = pd.DataFrame(
                candles,
                columns=["time", "open", "high", "low", "close", "volume"],
            )
            for col in ("open", "high", "low", "close", "volume"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            result = self._ohlcv_cache.merge((symbol, _OHLCV_TF), df)
            # D-066: всё на DEBUG — стабильная работа, не спамим INFO логи.
            logger.debug("[WsFeed] cache.merge %s %s = %s", symbol, _OHLCV_TF, result)
        except Exception as e:
            logger.warning("[WsFeed][D-066] cache push error %s: %s (%s)",
                           symbol, e, type(e).__name__)
