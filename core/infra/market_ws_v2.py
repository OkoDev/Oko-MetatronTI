"""
MarketWS v2 — kline WebSocket в ОТДЕЛЬНОМ ПРОЦЕССЕ (обходит GIL).

Корень v1-провала: поток с 70k свечей/мин (gzip+json+DataFrame CPU) держит GIL →
scan_loop 300с→600с+. Урок: high-rate WS в Python = ТОЛЬКО процесс, не поток.

Архитектура v2:
  producer-процесс  →  multiprocessing.Queue  →  QueueReaderThread (main)  →  OhlcvCache
  (GIL изолирован)       (межпроцессный IPC)      (daemon thread, merge)       (основной)

ЭТАПЫ (как v1, за флагами market_ws.*):
  enabled=true + use_ws=false  → теневой OhlcvCache (Этап 1 SHADOW, scan на REST)
  enabled=true + use_ws=true   → основной кэш (Этап 2, scan читает WS) — после валидации ≥99%

Переиспользует MarketWS из market_ws.py (соединения/Ping/реконнект не меняем).
"""
from __future__ import annotations

import asyncio
import logging
import queue as _stdlib_queue
import threading
import time
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ─── worker-процесс ────────────────────────────────────────────────────────────

_LIVE_DEDUP_INTERVAL = 5.0  # сек: одну (sym,tf) не шлём чаще → поток 1200/s→~200/s


def _mws_worker(out_queue, symbols: list, tfs: list, batch: int, shadow: bool = False) -> None:
    """Standalone-функция для multiprocessing.Process.

    shadow=True  → очередь не используется, только stats-логирование (Этап 1)
    shadow=False → кладёт свечи в out_queue для QueueReaderThread (Этап 2)
    Вызывается через spawn (Windows default) → top-level функция, не lambda/closure.
    """
    import asyncio as _aio
    import threading as _thr
    import time as _time
    from core.infra.market_ws import MarketWS

    class _QueueCache:
        """Заглушка OhlcvCache: нет lock, нет данных."""
        _lock = _thr.RLock()
        _data: dict = {}

        def merge(self, key, df):
            return "ws"

    class _MarketWSQueue(MarketWS):
        def __init__(self, q, syms, tfs_, batch_, shadow_):
            super().__init__(syms, tfs_, _QueueCache(), batch_pairs=batch_)
            self._q = q
            self._shadow = shadow_
            self._last_sent: dict = {}  # (sym,tf) → monotonic ts

        def _on_candle(self, sym_ccxt: str, tf: str, df: pd.DataFrame) -> None:
            if self._shadow:
                # Shadow: scan на REST — очередь не нужна, только считаем свечи для логов
                self.stats["candles"] += 1
                return
            # Throttle: не слать одну (sym,tf) чаще _LIVE_DEDUP_INTERVAL сек
            # → поток 1200/s→~200/s, reader справляется без overflow
            key = (sym_ccxt, tf)
            now = _time.monotonic()
            if now - self._last_sent.get(key, 0.0) < _LIVE_DEDUP_INTERVAL:
                return
            self._last_sent[key] = now
            try:
                r = df.iloc[0]
                self._q.put_nowait((
                    sym_ccxt, tf,
                    {
                        "time":   int(r["time"]),
                        "open":   float(r["open"]),
                        "high":   float(r["high"]),
                        "low":    float(r["low"]),
                        "close":  float(r["close"]),
                        "volume": float(r.get("volume", 0)),
                    },
                ))
                self.stats["candles"] += 1
            except Exception:
                self.stats["errors"] += 1

    mws = _MarketWSQueue(out_queue, symbols, tfs, batch, shadow)
    loop = _aio.new_event_loop()
    _aio.set_event_loop(loop)
    try:
        loop.run_until_complete(mws.run())
    except Exception:
        pass
    finally:
        loop.close()


# ─── QueueReaderThread ─────────────────────────────────────────────────────────

class QueueReaderThread(threading.Thread):
    """Daemon thread в main процессе: читает из mp.Queue → merge в OhlcvCache.

    Работает в фоне, не блокирует event loop. Единственная точка записи в cache
    из WS-потока — lock гарантирован самим OhlcvCache._lock (RLock).
    """

    def __init__(self, q, cache, shadow: bool = True):
        super().__init__(daemon=True, name="mws-reader")
        self._q = q
        self._cache = cache
        self._shadow = shadow
        self._running = True
        self.stats = {
            "applied": 0, "errors": 0, "shadow": shadow,
            "last_rate": 0.0, "_last_count": 0, "_last_ts": time.monotonic(),
        }

    _BATCH_MAX = 1000  # дренируем до 1000 элементов за цикл

    def run(self) -> None:
        while self._running:
            try:
                first = self._q.get(timeout=0.1)
            except _stdlib_queue.Empty:
                continue

            if self._shadow:
                # Shadow: scan_loop на REST, cache не используется →
                # просто дренируем очередь без pandas overhead (только счётчик)
                count = 1
                for _ in range(self._BATCH_MAX - 1):
                    try:
                        self._q.get_nowait()
                        count += 1
                    except _stdlib_queue.Empty:
                        break
                self.stats["applied"] += count
            else:
                # LIVE (use_ws=true): батч с merge в основной cache
                sym, tf, row = first
                latest: dict = {(sym, tf): row}
                for _ in range(self._BATCH_MAX - 1):
                    try:
                        s, t, r = self._q.get_nowait()
                        latest[(s, t)] = r  # последний выигрывает — финальная версия свечи
                    except _stdlib_queue.Empty:
                        break
                for (s, t), r in latest.items():
                    try:
                        self._cache.merge((s, t), pd.DataFrame([r]))
                        self.stats["applied"] += 1
                    except Exception as e:
                        self.stats["errors"] += 1
                        logger.debug("[MarketWS-v2] reader merge error: %s", e)

            # Лог раз в 60с
            now = time.monotonic()
            if now - self.stats["_last_ts"] >= 60:
                rate = (self.stats["applied"] - self.stats["_last_count"]) / (now - self.stats["_last_ts"])
                self.stats["last_rate"] = round(rate, 1)
                logger.info("[MarketWS-v2] reader STATS (shadow=%s): rate=%.1f/s applied=%d q≈%d",
                            self._shadow, rate, self.stats["applied"],
                            self._q.qsize() if hasattr(self._q, "qsize") else -1)
                self.stats["_last_count"] = self.stats["applied"]
                self.stats["_last_ts"] = now

    def stop(self) -> None:
        self._running = False


# ─── супервайзор ──────────────────────────────────────────────────────────────

async def _mws_supervisor(proc, out_queue, symbols, tfs, batch, cache, shadow, bot) -> None:
    """Async-таска в main loop: раз в 30с проверяет что worker-процесс жив."""
    import multiprocessing as mp
    while True:
        await asyncio.sleep(30)
        try:
            if not proc.is_alive():
                logger.warning("[MarketWS-v2] процесс упал (exitcode=%s) — рестарт", proc.exitcode)
                try:
                    proc.kill()
                except Exception:
                    pass
                new_proc = mp.Process(
                    target=_mws_worker,
                    args=(out_queue, symbols, tfs, batch, shadow),
                    daemon=True, name="market-ws-v2",
                )
                new_proc.start()
                bot._market_ws_proc = new_proc
                proc = new_proc
                logger.info("[MarketWS-v2] процесс перезапущен (pid=%d)", new_proc.pid)
        except Exception as e:
            logger.warning("[MarketWS-v2] supervisor error: %s", e)


# ─── точка входа ──────────────────────────────────────────────────────────────

def start_market_ws_v2(bot) -> Optional[tuple]:
    """Запускает MarketWS v2 (процесс) если market_ws.enabled.

    Этап 1 SHADOW (use_ws=false): теневой OhlcvCache — scan на REST, сравнение.
    Этап 2 (use_ws=true): основной кэш — scan читает из WS.

    Возвращает (process, reader_thread) или None.
    """
    import multiprocessing as mp

    cfg = bot.config
    if not bool(cfg.get("market_ws.enabled", False)):
        return None

    tfs   = cfg.get("market_ws.timeframes", ["5m", "15m"]) or ["5m", "15m"]
    batch = int(cfg.get("market_ws.batch_pairs", 50))
    use_ws = bool(cfg.get("market_ws.use_ws", False))

    symbols = list(getattr(bot.data_collector, "usdt_pairs", []) or [])
    if not symbols:
        logger.warning("[MarketWS-v2] enabled, но usdt_pairs пуст — не запускаю")
        return None

    from core.infra.api_engine import OhlcvCache
    if use_ws:
        cache  = bot.data_collector._engine._cache
        shadow = False
    else:
        cache  = OhlcvCache(maxsize=5000)
        shadow = True

    if shadow:
        # Этап 1 SHADOW: очередь не нужна — worker только логирует stats
        out_queue = None
        reader    = None
    else:
        # Этап 2 LIVE: буфер 70k свечей/мин → ~1200/с
        out_queue = mp.Queue(maxsize=200_000)
        reader    = QueueReaderThread(out_queue, cache, shadow=False)
        reader.start()

    proc = mp.Process(
        target=_mws_worker,
        args=(out_queue, symbols, tfs, batch, shadow),
        daemon=True, name="market-ws-v2",
    )
    proc.start()

    bot._market_ws_proc   = proc
    bot._market_ws_reader = reader
    bot._market_ws_queue  = out_queue

    # Супервайзор — async task в текущем event loop
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_mws_supervisor(proc, out_queue, symbols, tfs, batch, cache, shadow, bot))
    except RuntimeError:
        pass  # вне loop — пропускаем (вызывается до start)

    logger.info(
        "[MarketWS-v2] процесс запущен pid=%d (%d пар, tfs=%s, use_ws=%s, shadow=%s)",
        proc.pid, len(symbols), tfs, use_ws, shadow,
    )
    return proc, reader
