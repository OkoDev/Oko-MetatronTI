"""
DEV-35/п.3: MultiSourceOHLCV — умный фетчер с автовыбором источника данных.

Логика:
  1. Для каждого символа пробует источники в порядке PRIORITY
  2. Выбирает источник с наиболее ранней доступной датой
  3. Скачивает данные → сохраняет в общий SQLite кэш (scripts/ohlcv_cache.py)
  4. Кэш ключи включают префикс источника — нет коллизий между биржами

Порядок приоритетов:
  binance   → BTC с 2017, большинство альтов с 2019-2021
  cryptocom → крупные монеты с 2018
  bingx     → история только с даты листинга на BingX

Использование:
  from scripts.multi_source_ohlcv import MultiSourceOHLCV

  fetcher = MultiSourceOHLCV()
  df = await fetcher.fetch("BTC/USDT", "15m", since_ms, end_ms)
  df = await fetcher.fetch("SOL/USDT", "1h", since_ms, end_ms)  # автовыбор Binance/Crypto.com/BingX
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

try:
    import ccxt.async_support as ccxt_async
except ImportError:
    ccxt_async = None  # тесты без ccxt

logger = logging.getLogger(__name__)

# Порядок источников: лучший → худший по глубине истории
PRIORITY: List[str] = ["binance", "cryptocom", "bingx"]

# Минимальная дата для каждого источника (UTC timestamp ms)
_SOURCE_SINCE_MS = {
    "binance":   int(datetime(2017, 1, 1).timestamp() * 1000),
    "cryptocom": int(datetime(2018, 1, 1).timestamp() * 1000),
    "bingx":     int(datetime(2020, 1, 1).timestamp() * 1000),
}

# Задержка между batch-запросами (секунды)
_BATCH_SLEEP = {
    "binance":   0.1,
    "cryptocom": 0.2,
    "bingx":     0.15,
}


# ── Биржи ────────────────────────────────────────────────────────────────────

def _make_exchange(source: str):
    """Создаёт ccxt exchange объект для указанного источника."""
    if ccxt_async is None:
        raise RuntimeError("ccxt не установлен")
    opts = {"enableRateLimit": True}
    if source == "binance":
        return ccxt_async.binance(opts)
    if source == "cryptocom":
        return ccxt_async.cryptocom(opts)
    if source == "bingx":
        return ccxt_async.bingx({**opts, "options": {"defaultType": "swap"}})
    raise ValueError(f"Неизвестный источник: {source}")


def _normalize_symbol(symbol: str, source: str) -> str:
    """Нормализует символ для конкретного источника."""
    spot = symbol.split(':')[0]  # убираем ':USDT' суффикс
    if source == "bingx":
        # BingX swap: BTC/USDT → BTC/USDT:USDT
        parts = spot.split('/')
        quote = parts[1] if len(parts) > 1 else "USDT"
        return f"{spot}:{quote}"
    return spot  # binance и cryptocom — spot формат


# ── Probe earliest date ───────────────────────────────────────────────────────

async def probe_earliest_date(symbol: str, source: str, exchange=None) -> Optional[int]:
    """
    Пробует найти самую раннюю доступную свечу для (symbol, source).
    Возвращает timestamp ms первой свечи или None если символ недоступен.
    """
    owned = exchange is None
    if owned:
        exchange = _make_exchange(source)
    src_symbol = _normalize_symbol(symbol, source)
    try:
        since = _SOURCE_SINCE_MS.get(source, _SOURCE_SINCE_MS["bingx"])
        candles = await exchange.fetch_ohlcv(src_symbol, "1d", since=since, limit=1)
        if candles:
            return int(candles[0][0])
        return None
    except Exception as e:
        logger.debug("[probe] %s@%s: %s", symbol, source, e)
        return None
    finally:
        if owned and hasattr(exchange, 'close'):
            await exchange.close()


# ── MultiSourceOHLCV ──────────────────────────────────────────────────────────

@dataclass
class SourceMeta:
    source: str
    earliest_ms: int


class MultiSourceOHLCV:
    """
    Умный фетчер OHLCV: автоматически выбирает источник с максимальной историей.
    Использует ohlcv_cache.py как единое хранилище (с prefix источника в ключе).
    """

    def __init__(self, priority: List[str] = None):
        self._priority = priority or PRIORITY
        self._source_cache: Dict[str, SourceMeta] = {}  # symbol → лучший источник
        self._exchanges: Dict[str, object] = {}

    async def _get_exchange(self, source: str):
        if source not in self._exchanges:
            self._exchanges[source] = _make_exchange(source)
        return self._exchanges[source]

    async def close(self):
        for ex in self._exchanges.values():
            if hasattr(ex, 'close'):
                try:
                    await ex.close()
                except Exception:
                    pass
        self._exchanges.clear()

    async def get_best_source(self, symbol: str) -> Optional[SourceMeta]:
        """
        Определяет лучший источник для символа (с наиболее ранней датой).
        Результат кэшируется на время жизни объекта.
        """
        if symbol in self._source_cache:
            return self._source_cache[symbol]

        best: Optional[SourceMeta] = None
        tasks = {
            source: probe_earliest_date(symbol, source, await self._get_exchange(source))
            for source in self._priority
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for source, earliest in zip(tasks.keys(), results):
            if isinstance(earliest, Exception) or earliest is None:
                continue
            if best is None or earliest < best.earliest_ms:
                best = SourceMeta(source=source, earliest_ms=earliest)
                logger.debug("[multisrc] %s: %s → earliest %s", symbol, source,
                             datetime.utcfromtimestamp(earliest / 1000).strftime("%Y-%m-%d"))

        if best:
            self._source_cache[symbol] = best
            logger.info("[multisrc] %s → %s (с %s)", symbol, best.source,
                        datetime.utcfromtimestamp(best.earliest_ms / 1000).strftime("%Y-%m-%d"))
        else:
            logger.warning("[multisrc] %s: нет доступных источников", symbol)
        return best

    async def fetch(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        end_ms: int,
        limit: int = 1000,
        preferred_source: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Загружает OHLCV для символа из лучшего доступного источника.

        Параметры:
            symbol     — пара в формате 'BTC/USDT'
            timeframe  — '15m', '1h', '4h', '1d'
            since_ms   — начало диапазона (Unix ms)
            end_ms     — конец диапазона (Unix ms)
            preferred_source — если указан, использовать этот источник без probe
        """
        try:
            from scripts.ohlcv_cache import get_cache
            cache = get_cache()
        except Exception:
            cache = None

        # Выбираем источник
        if preferred_source:
            source = preferred_source
        else:
            meta = await self.get_best_source(symbol)
            if meta is None:
                logger.error("[multisrc] %s: нет источника, возвращаем None", symbol)
                return None
            source = meta.source

        cache_key = f"{source}:{_normalize_symbol(symbol, source)}"

        # Проверяем кэш
        if cache is not None:
            c_min, c_max = cache.get_coverage(cache_key, timeframe)
            if c_min is not None and c_min <= since_ms and c_max is not None and c_max >= end_ms:
                df = cache.read(cache_key, timeframe, since_ms, end_ms)
                if df is not None:
                    logger.info("[multisrc] cache HIT %s %s (%d bars)", cache_key, timeframe, len(df))
                    return df

        # Загружаем из биржи
        df = await self._fetch_from_exchange(symbol, source, timeframe, since_ms, end_ms, limit)

        # Сохраняем в кэш
        if df is not None and cache is not None:
            try:
                cache.save(cache_key, timeframe, df)
            except Exception as e:
                logger.debug("[multisrc] cache save failed: %s", e)

        return df

    async def _fetch_from_exchange(
        self, symbol: str, source: str, timeframe: str, since_ms: int, end_ms: int, limit: int
    ) -> Optional[pd.DataFrame]:
        """Скачивает OHLCV пачками из указанного источника."""
        exchange = await self._get_exchange(source)
        src_symbol = _normalize_symbol(symbol, source)
        sleep_sec = _BATCH_SLEEP.get(source, 0.2)

        all_data = []
        current_since = since_ms
        _retries = 0

        while True:
            try:
                candles = await exchange.fetch_ohlcv(src_symbol, timeframe, since=current_since, limit=limit)
                _retries = 0
            except Exception as e:
                err_str = str(e)
                # BingX-специфичный rate limit
                if source == "bingx" and "100410" in err_str and _retries < 3:
                    _retries += 1
                    await asyncio.sleep(5 * _retries)
                    continue
                logger.error("[multisrc] fetch error %s@%s %s: %s", symbol, source, timeframe, e)
                break

            if not candles:
                break

            df_batch = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume"])
            for col in ("open", "high", "low", "close", "volume"):
                df_batch[col] = pd.to_numeric(df_batch[col], errors="coerce")
            df_batch = df_batch[df_batch["time"] <= end_ms]
            if df_batch.empty:
                break

            all_data.append(df_batch)
            last_time = int(candles[-1][0])
            if last_time >= end_ms or len(candles) < limit:
                break
            current_since = last_time + 1
            await asyncio.sleep(sleep_sec)

        if not all_data:
            return None
        df = (
            pd.concat(all_data, ignore_index=True)
            .drop_duplicates(subset=["time"])
            .sort_values("time")
            .reset_index(drop=True)
        )
        logger.info("[multisrc] загружено %d баров %s@%s %s", len(df), symbol, source, timeframe)
        return df

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

async def _cli_main():
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="MultiSourceOHLCV — probe лучшего источника")
    parser.add_argument("symbol", help="Символ, например BTC/USDT")
    parser.add_argument("--tf", default="1d", help="Таймфрейм (default: 1d)")
    args = parser.parse_args()

    async with MultiSourceOHLCV() as fetcher:
        meta = await fetcher.get_best_source(args.symbol)
        if meta:
            dt = datetime.utcfromtimestamp(meta.earliest_ms / 1000).strftime("%Y-%m-%d")
            print(f"{args.symbol}: лучший источник = {meta.source} (история с {dt})")
        else:
            print(f"{args.symbol}: источник не найден")


if __name__ == "__main__":
    asyncio.run(_cli_main())
