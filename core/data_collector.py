import ccxt.async_support as ccxt
from collections import deque
import asyncio
import logging
import time
import pandas as pd
import re

logger = logging.getLogger(__name__)

# TTL кеша зависит от таймфрейма: чем старше ТФ, тем дольше актуален
_CACHE_TTL = {
    "1m": 15, "3m": 30, "5m": 45,
    "15m": 60, "45m": 120,
    "1h": 180, "4h": 300, "1d": 600,
}
_DEFAULT_TTL = 60


class RealTimeData:
    def __init__(self, exchange_id="bingx"):
        self.exchange_id = exchange_id.lower()
        self.exchange = getattr(ccxt, exchange_id)({
            "enableRateLimit": True,
            "options": {"defaultType": "future"}
        })
        self.price_history = {}
        self.volume_history = {}
        self.timeframe = "1m"
        self.history_size = 200
        self.usdt_pairs = []
        self.is_running = False
        # Кеш OHLCV: {(symbol, timeframe): {"df": DataFrame, "ts": float, "limit": int}}
        self._ohlcv_cache = {}

    async def load_markets(self, min_volume_usd: float = 0):
        """Загрузить только USDT futures-пары (попытка универсальной фильтрации)"""
        try:
            await self.exchange.load_markets()
            symbols = list(self.exchange.symbols or [])
            candidates = []

            for s in symbols:
                if not isinstance(s, str):
                    continue
                # common future patterns
                if s.endswith("/USDT:USDT") or s.endswith("/USDT-P") or re.search(r":USDT$", s):
                    candidates.append(s)
                    continue
                # try to inspect markets info
                try:
                    m = self.exchange.markets.get(s)
                    if m:
                        t = (m.get("type") or "").lower()
                        info = str(m.get("info", "")).lower()
                        if "future" in t or "future" in info or "contract" in info:
                            candidates.append(s)
                except Exception:
                    continue

            # only keep those containing USDT
            self.usdt_pairs = sorted({p for p in candidates if "USDT" in p})
            # final filter: prefer explicit future suffix
            self.usdt_pairs = [p for p in self.usdt_pairs if (":USDT" in p or p.endswith("USDT-P") or p.endswith("/USDT:USDT"))]
            # фильтр: базовый актив не длиннее 10 символов (отсекаем NCSISP5002USD и прочий мусор)
            self.usdt_pairs = [
                p for p in self.usdt_pairs
                if len(p.split("/")[0]) <= 10
            ]

            logger.info(f"Loaded {len(self.usdt_pairs)} USDT-futures pairs")

            # Фильтр по объёму (Этап 5.1)
            if min_volume_usd > 0:
                self.usdt_pairs = await self._filter_by_volume(self.usdt_pairs, min_volume_usd)
                logger.info(f"После фильтра объёма (>{min_volume_usd/1e6:.0f}M$): {len(self.usdt_pairs)} пар")

            for s in self.usdt_pairs:
                self.price_history[s] = deque(maxlen=self.history_size)
                self.volume_history[s] = deque(maxlen=self.history_size)
            return self.usdt_pairs
        except Exception:
            logger.exception("load_markets error")
            return []

    async def _filter_by_volume(self, pairs: list, min_volume_usd: float) -> list:
        """Фильтрует пары по 24h quoteVolume через fetch_tickers (один batch-запрос)."""
        try:
            tickers = await self.exchange.fetch_tickers(pairs)
            result = []
            for sym in pairs:
                t = tickers.get(sym, {})
                vol = t.get("quoteVolume") or 0
                if vol >= min_volume_usd:
                    result.append(sym)
            return result
        except Exception as e:
            logger.warning(f"Фильтр объёма не применён (ошибка fetch_tickers): {e}")
            return pairs

    async def fetch_candles(self):
        """Background OHLCV fetcher (1m summary: price change % and volume)"""
        self.is_running = True
        while self.is_running:
            try:
                for s in list(self.usdt_pairs):
                    try:
                        candles = await self.exchange.fetch_ohlcv(s, timeframe=self.timeframe, limit=2)
                        if candles and len(candles) >= 2:
                            prev = candles[-2]
                            last = candles[-1]
                            prev_close = prev[4] or 0.0
                            last_close = last[4] or 0.0
                            if prev_close:
                                price_change = ((last_close - prev_close) / prev_close) * 100.0
                            else:
                                price_change = 0.0
                            current_vol = last[5] or 0.0
                            self.price_history.setdefault(s, deque(maxlen=self.history_size)).append(price_change)
                            self.volume_history.setdefault(s, deque(maxlen=self.history_size)).append(current_vol)
                    except Exception:
                        logger.debug(f"fetch_candles error for {s}", exc_info=True)
                        continue
                await asyncio.sleep(60)
            except Exception:
                logger.exception("fetch_candles loop error")
                await asyncio.sleep(5)

    async def get_ticker(self, symbol):
        """Получить тикер для символа"""
        try:
            return await self.exchange.fetch_ticker(symbol)
        except Exception:
            logger.debug(f"get_ticker error {symbol}", exc_info=True)
            return None

    async def symbol_exists(self, symbol):
        """Проверить существование символа"""
        try:
            await self.exchange.load_markets()
            return symbol in self.exchange.markets
        except Exception:
            logger.debug(f"symbol_exists error {symbol}", exc_info=True)
            return False

    def normalize_symbol(self, symbol):
        """Нормализует символ в формат биржи"""
        symbol = symbol.upper().strip()
        
        # Если уже в правильном формате
        if "/" in symbol and ":" in symbol:
            return symbol
        
        # Если через слеш без двоеточия (BTC/USDT)
        if "/" in symbol and ":" not in symbol:
            return f"{symbol}:USDT"
        
        # Если только базовая валюта (BTC, ETH)
        if len(symbol) <= 5 and symbol.isalpha():
            return f"{symbol}/USDT:USDT"
        
        # Если слитно (BTCUSDT)
        if "USDT" in symbol:
            base = symbol.replace("USDT", "")
            return f"{base}/USDT:USDT"
        
        # Fallback - добавляем USDT
        return f"{symbol}/USDT:USDT"

    async def symbol_exists_normalized(self, symbol):
        """Проверяет существование символа с нормализацией"""
        normalized = self.normalize_symbol(symbol)
        return await self.symbol_exists(normalized)

    async def get_ohlcv(self, symbol, timeframe="15m", limit=150, since=None):
        """Возвращает pandas.DataFrame с колонками: time, open, high, low, close, volume.
        Результат кешируется с TTL, зависящим от таймфрейма."""
        normalized_symbol = self.normalize_symbol(symbol)
        cache_key = (normalized_symbol, timeframe)
        now = time.monotonic()
        ttl = _CACHE_TTL.get(timeframe, _DEFAULT_TTL)

        # Проверяем кеш: совпадает ли ключ и достаточно ли свечей
        cached = self._ohlcv_cache.get(cache_key)
        if cached and (now - cached["ts"]) < ttl and cached["limit"] >= limit:
            return cached["df"].copy()

        try:
            candles = await self.exchange.fetch_ohlcv(normalized_symbol, timeframe=timeframe, limit=limit, since=since)
            if not candles:
                return None
            df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume"])
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            self._ohlcv_cache[cache_key] = {"df": df, "ts": now, "limit": limit}
            return df.copy()
        except Exception:
            logger.debug(f"get_ohlcv error {symbol} {timeframe}", exc_info=True)
            return None

    async def stop(self):
        self.is_running = False
        await self.close()

    async def close(self):
        try:
            await self.exchange.close()
        except Exception:
            logger.debug("exchange close error", exc_info=True)
