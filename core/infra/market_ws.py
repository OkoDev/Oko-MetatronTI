"""
MarketWS — кастомный public kline WebSocket (MARKET-WS, разгрузка scan_loop).

Корень: scan_loop REST-fetch 5m/15m по 526 парам каждый цикл = узкое место loop
(цикл ~300с, 2867 lag-warnings). Решение — push свечей через WS в OhlcvCache,
scan читает из кэша БЕЗ REST. Доказано тестом (scripts/diag_market_ws_kline.py):
кастомный aiohttp WS (НЕ ccxt.pro, который дал плато 750s) держит поток легко.

Паттерн как EXEC-WS (core/exchange/user_data_ws.py): кастомный aiohttp, отдельный
поток/loop, gzip, Ping/Pong, реконнект. НАГРУЗКА: N соединений (батчи по M пар),
НЕ per-pair, НЕ в main loop → scan не затронут.

ЭТАПЫ (как EXEC-WS, за флагами market_ws.*):
  1 SHADOW (enabled, use_ws=false): WS пишет в ТЕНЕВОЙ кэш, scan на REST. Сравнение,
    масштаб-проверка, gap-статистика. Ноль влияния на основной cache/scan.
  2 (use_ws=true): merge в ОСНОВНОЙ OhlcvCache (+ threading.Lock) → scan читает WS.

Формат kline (эмпирически 14.06):
  {"dataType":"BTC-USDT@kline_5m","s":"BTC-USDT","data":[{"o","h","l","c","v","T"}]}
  T = время бара (ms), смена T → новый бар (merge replace/append).
"""
from __future__ import annotations

import asyncio
import gzip
import io
import json
import logging
import threading
import time
import uuid
from typing import Optional

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

WS_URL = "wss://open-api-swap.bingx.com/swap-market"  # public market (рынок единый VST/PROD)
_RECONNECT_SEC = 5.0
_TF_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _ws_to_ccxt(sym_ws: str) -> str:
    """'BTC-USDT' → 'BTC/USDT:USDT' (формат cache-key как в scan_loop/data_collector)."""
    parts = sym_ws.split("-")
    if len(parts) != 2:
        return sym_ws
    base, quote = parts
    return f"{base}/{quote}:{quote}"


def _ccxt_to_ws(sym_ccxt: str) -> str:
    """'BTC/USDT:USDT' → 'BTC-USDT' (для subscribe dataType)."""
    base = sym_ccxt.split("/")[0]
    quote = sym_ccxt.split("/")[1].split(":")[0] if "/" in sym_ccxt else "USDT"
    return f"{base}-{quote}"


class MarketWS:
    """Public kline WS по N соединений (батчи). on_candle → merge в cache."""

    def __init__(
        self,
        symbols: list[str],
        timeframes: list[str],
        cache,                       # OhlcvCache (теневой в Этапе 1, основной в Этапе 2)
        cache_lock: Optional[threading.Lock] = None,
        batch_pairs: int = 50,
        shadow: bool = True,
    ):
        self._symbols = symbols
        self._tfs = timeframes
        self._cache = cache
        self._lock = cache_lock or threading.Lock()
        self._batch = max(1, int(batch_pairs))
        self._shadow = shadow
        self._running = False
        self.stats = {"candles": 0, "replace": 0, "append": 0, "stale": 0,
                      "skip_no_cache": 0, "gaps": 0, "reconnects": 0, "pings": 0,
                      "conns": 0, "errors": 0}

    @staticmethod
    def _decode(data) -> str:
        if isinstance(data, (bytes, bytearray)):
            try:
                return gzip.GzipFile(fileobj=io.BytesIO(data)).read().decode("utf-8", "ignore")
            except Exception:
                return bytes(data).decode("utf-8", "ignore")
        return str(data)

    def _parse(self, msg: dict):
        """kline-msg → (sym_ccxt, tf, df 1-строка) или None."""
        dt = msg.get("dataType", "")
        if "@kline_" not in dt:
            return None
        data = msg.get("data")
        if not isinstance(data, list) or not data:
            return None
        k = data[0]
        try:
            sym_ws = msg.get("s") or dt.split("@")[0]
            tf = dt.split("@kline_")[1]
            row = {
                "time": int(k["T"]),
                "open": float(k["o"]), "high": float(k["h"]),
                "low": float(k["l"]), "close": float(k["c"]),
                "volume": float(k.get("v", 0)),
            }
        except (KeyError, ValueError, TypeError, IndexError):
            return None
        return _ws_to_ccxt(sym_ws), tf, pd.DataFrame([row])

    def _on_candle(self, sym_ccxt: str, tf: str, df: pd.DataFrame) -> None:
        key = (sym_ccxt, tf)
        # gap-detect: если новый бар отстоит >1.5×интервала от кэша → пропуск бара
        tf_ms = _TF_MS.get(tf, 0)
        with self._lock:
            try:
                entry = self._cache._data.get(key)
                if entry is not None and tf_ms:
                    try:
                        last_t = int(entry["df"]["time"].iloc[-1])
                        new_t = int(df["time"].iloc[-1])
                        if new_t - last_t > tf_ms * 1.5:
                            self.stats["gaps"] += 1
                    except Exception:
                        pass
                res = self._cache.merge(key, df)
            except Exception as e:
                self.stats["errors"] += 1
                logger.debug("[MarketWS] merge error %s %s: %s", sym_ccxt, tf, e)
                return
        self.stats["candles"] += 1
        if res in self.stats:
            self.stats[res] += 1

    async def _connection(self, batch: list[str], idx: int) -> None:
        while self._running:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(WS_URL, timeout=aiohttp.ClientTimeout(total=20),
                                            heartbeat=30) as ws:
                        self.stats["conns"] += 1
                        for sym in batch:
                            for tf in self._tfs:
                                await ws.send_str(json.dumps({
                                    "id": str(uuid.uuid4()), "reqType": "sub",
                                    "dataType": f"{_ccxt_to_ws(sym)}@kline_{tf}",
                                }))
                        logger.info("[MarketWS] conn#%d: %d пар × %d ТФ подписано",
                                    idx, len(batch), len(self._tfs))
                        async for m in ws:
                            if not self._running:
                                break
                            if m.type not in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                                if m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                    break
                                continue
                            dec = self._decode(m.data)
                            if dec == "Ping" or '"ping"' in dec.lower():
                                self.stats["pings"] += 1
                                try:
                                    await ws.send_str("Pong")
                                except Exception:
                                    pass
                                continue
                            try:
                                msg = json.loads(dec)
                            except Exception:
                                continue
                            if not isinstance(msg, dict):
                                continue
                            parsed = self._parse(msg)
                            if parsed:
                                self._on_candle(*parsed)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.stats["errors"] += 1
                logger.warning("[MarketWS] conn#%d error: %s — reconnect %.0fs", idx, e, _RECONNECT_SEC)
            if self._running:
                self.stats["reconnects"] += 1
                await asyncio.sleep(_RECONNECT_SEC)

    async def _stats_loop(self) -> None:
        while self._running:
            await asyncio.sleep(60)
            logger.info("[MarketWS] STATS (shadow=%s): %s", self._shadow, self.stats)

    async def run(self) -> None:
        self._running = True
        batches = [self._symbols[i:i + self._batch]
                   for i in range(0, len(self._symbols), self._batch)]
        logger.info("[MarketWS] старт: %d пар × %d ТФ → %d соединений (батч %d), shadow=%s",
                    len(self._symbols), len(self._tfs), len(batches), self._batch, self._shadow)
        tasks = [asyncio.create_task(self._connection(b, i)) for i, b in enumerate(batches)]
        tasks.append(asyncio.create_task(self._stats_loop()))
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

    def stop(self) -> None:
        self._running = False


def start_market_ws(bot):
    """Запуск MarketWS в ОТДЕЛЬНОМ потоке (свой asyncio loop) если market_ws.enabled.

    Этап 1 SHADOW (use_ws=false): теневой OhlcvCache (свой instance) — scan/основной
    cache НЕ затронуты. Этап 2 (use_ws=true): основной cache + lock.
    Возвращает (thread, market_ws) или None.
    """
    cfg = bot.config
    if not bool(cfg.get("market_ws.enabled", False)):
        return None
    tfs = cfg.get("market_ws.timeframes", ["5m", "15m"]) or ["5m", "15m"]
    batch = int(cfg.get("market_ws.batch_pairs", 50))
    use_ws = bool(cfg.get("market_ws.use_ws", False))

    # список пар из data_collector
    symbols = list(getattr(bot.data_collector, "usdt_pairs", []) or [])
    if not symbols:
        logger.warning("[MarketWS] enabled, но нет пар (usdt_pairs пуст) — не запускаю")
        return None

    from core.infra.api_engine import OhlcvCache
    if use_ws:
        # Этап 2: основной cache + lock (cache живёт в data_collector._engine._cache)
        cache = bot.data_collector._engine._cache
        lock = getattr(bot.data_collector._engine, "_cache_lock", None) or threading.Lock()
        shadow = False
    else:
        # Этап 1 SHADOW: свой теневой кэш — основной не трогаем
        cache = OhlcvCache(maxsize=5000)
        lock = threading.Lock()
        shadow = True

    mws = MarketWS(symbols, tfs, cache, lock, batch_pairs=batch, shadow=shadow)
    bot._market_ws = mws

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(mws.run())
        except Exception as e:
            logger.exception("[MarketWS] поток упал: %s", e)
        finally:
            loop.close()

    th = threading.Thread(target=_run, name="market-ws", daemon=True)
    th.start()
    logger.info("[MarketWS] поток запущен (%d пар, tfs=%s, use_ws=%s)", len(symbols), tfs, use_ws)
    return th, mws
