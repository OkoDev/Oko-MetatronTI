import ccxt.async_support as ccxt
from collections import deque
import asyncio
import logging
import re

from core.api_engine import ApiEngine

logger = logging.getLogger(__name__)

# TTL кеша — оставляем для обратной совместимости (используется в api_engine)
_CACHE_TTL = {
    "1m": 15, "3m": 30, "5m": 45,
    "15m": 60, "45m": 120,
    "1h": 180, "4h": 300, "1d": 600,
}
_DEFAULT_TTL = 60


class RealTimeData:
    def __init__(self, exchange_id="bingx", api_semaphore_size: int = 5, api_rps: float = 8.0):
        self.exchange_id = exchange_id.lower()
        self.exchange = getattr(ccxt, exchange_id)({
            "enableRateLimit": False,   # ApiEngine управляет rate limiting сам
            "options": {"defaultType": "future"}
        })
        self.price_history = {}
        self.volume_history = {}
        self.timeframe = "1m"
        self.history_size = 200
        self.usdt_pairs = []
        self.is_running = False
        # ApiEngine: LRU cache + retry + circuit breaker + rate limiter + in-flight dedup
        self._engine = ApiEngine(self.exchange, semaphore_size=api_semaphore_size, rps=api_rps)
        # Алиас для обратной совместимости (код, который напрямую обращается к _ohlcv_cache)
        self._ohlcv_cache = self._engine._cache._data

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
        """Background OHLCV fetcher: параллельный fetch для всех пар (Semaphore через ApiEngine)."""
        self.is_running = True
        while self.is_running:
            try:
                pairs = list(self.usdt_pairs)

                async def _fetch_one(s: str) -> None:
                    try:
                        df = await self._engine.fetch_ohlcv(s, self.timeframe, limit=2)
                        if df is not None and len(df) >= 2:
                            prev_close = df.iloc[-2]["close"] or 0.0
                            last_close = df.iloc[-1]["close"] or 0.0
                            price_change = (
                                ((last_close - prev_close) / prev_close) * 100.0
                                if prev_close else 0.0
                            )
                            current_vol = df.iloc[-1]["volume"] or 0.0
                            self.price_history.setdefault(
                                s, deque(maxlen=self.history_size)
                            ).append(price_change)
                            self.volume_history.setdefault(
                                s, deque(maxlen=self.history_size)
                            ).append(current_vol)
                    except Exception:
                        logger.debug("fetch_candles error for %s", s, exc_info=True)

                await asyncio.gather(*[_fetch_one(s) for s in pairs])
                logger.debug(
                    "fetch_candles завершён: %d пар | %s",
                    len(pairs), self._engine.cache_stats(),
                )
                await asyncio.sleep(60)
            except Exception:
                logger.exception("fetch_candles loop error")
                await asyncio.sleep(5)

    async def get_ticker(self, symbol):
        """Получить тикер для символа (с circuit breaker и retry через ApiEngine)."""
        normalized = self.normalize_symbol(symbol)
        return await self._engine.fetch_ticker(normalized)

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
        Делегирует в ApiEngine: LRU cache → in-flight dedup → retry → circuit breaker."""
        normalized_symbol = self.normalize_symbol(symbol)
        return await self._engine.fetch_ohlcv(normalized_symbol, timeframe, limit, since)

    async def stop(self):
        self.is_running = False
        await self.close()

    async def close(self):
        try:
            await self.exchange.close()
        except Exception:
            logger.debug("exchange close error", exc_info=True)
