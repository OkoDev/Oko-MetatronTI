"""
API Engine — транспортный слой над ccxt.

Предоставляет: TTL-кеш с LRU eviction, in-flight deduplication,
retry с exponential backoff, circuit breaker, rate limiter, семафор.

Используется исключительно через RealTimeData (data_collector.py).
Публичный интерфейс data_collector НЕ меняется.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from typing import Optional

import ccxt.async_support as ccxt
import pandas as pd

logger = logging.getLogger(__name__)

# TTL (сек) совпадает с data_collector._CACHE_TTL
# D-065 (24.05): 4h 900→3600 (1ч), 1d 1800→7200 (2ч) — свечи меняются раз в 4ч/24ч,
# агрессивный TTL даёт -200 calls/cycle (~17% scan time экономии).
# D-066 (25.05): 5m 45→300, 15m 60→900, 45m 120→2700, 1h 180→3600 — TTL = длина свечи.
# WS постоянно обновляет cache через replace/append, TTL должен покрывать gap между WS update'ами
# (15m: WS может тихо стоять до закрытия бара). Без WS — кеш expires к моменту нового бара.
_CACHE_TTL: dict[str, float] = {
    "1m": 60, "3m": 180, "5m": 300,
    "15m": 1800, "45m": 2700,
    "1h": 3540, "4h": 14340, "1d": 86340, "1w": 3600,
}
_DEFAULT_TTL: float = 60.0

# 🔑 КАНОНИЧЕСКАЯ ГЛУБИНА ЗАПРОСА ПО ТФ (02.09.2026).
# Кэш держит одну запись на (symbol, tf) и отдаёт её только если её limit НЕ МЕНЬШЕ
# запрошенного. Пока разные места просили разную глубину, запись постоянно выбивалась
# в REST. Тянем всегда канон (запрос стоит столько же — замер 1.00× при 60/150/400),
# наружу отдаём ровно `limit` последних баров, поэтому потребители ничего не замечают.
#
# Значения = максимум встречающегося в коде для этого ТФ, с небольшим запасом:
#   3m  — 20 / 100                                    → 150
#   5m  — 150 / 200                                   → 250
#   15m — 1 / 3 / 10 / 100 / 120 / 150 / 160          → 250
#   1h  — 30 / 50 / 55 / 60 / 100 / 150 / 160 / 400 / 530 → 550
#   4h  — 20 / 50 / 56 / 60 / 150 / 180               → 250
#   1d  — 3 / 5 / 14 / 35 / 60                        → 200
# 🔴 ОТКАТ 02.09 к минимуму. Первая версия ставила 3m 150 · 5m 250 · 15m 250 ·
# 1h 550 · 4h 250 — и это НЕ помогло, а по 1h/4h стало хуже (hit 90→81 и 98→79).
# Причина в другом месте: у младших ТФ `_CACHE_TTL` КОРОЧЕ цикла скана
# (3m — 180 с, 5m — 300 с при цикле 400-960 с), поэтому запись протухает по 3-5 раз
# ВНУТРИ одного прохода. Глубина такой промах не лечит вообще — лечит только
# сокращение цикла, WS-push или отказ от этих ТФ в скане.
# Оставляем ровно то, что нужно потребителям, и не больше:
#   1h → 400: столько просит двухмасштабная нога Сферы 20 (замер: при 400 совпало
#             6/6 с эталоном 1000, при 250 — 3/6);
#   4h → 200, 1d → 200: как было до правки (DS-322).
_CANON_LIMIT: dict[str, int] = {
    "1h": 400, "4h": 200, "1d": 200,
}

# ── Инструментация cache-hit vs REST per TF (диагностика market_ws/REST за цикл) ──
from collections import Counter as _Counter
_ohlcv_cache_hit: _Counter = _Counter()   # TF → сколько раз отдан из кэша (WS/TTL свежий)
_ohlcv_cache_miss: _Counter = _Counter()  # TF → сколько раз пошёл в реальный REST


def get_ohlcv_cache_stats() -> dict:
    """Сводка cache-hit/REST per TF. hit_rate показывает покрытие WS+TTL."""
    out = {}
    for tf in set(_ohlcv_cache_hit) | set(_ohlcv_cache_miss):
        h = _ohlcv_cache_hit.get(tf, 0)
        m = _ohlcv_cache_miss.get(tf, 0)
        tot = h + m
        out[tf] = {"hit": h, "rest": m, "hit_rate": round(h / tot, 3) if tot else 0.0}
    return out


def reset_ohlcv_cache_stats() -> None:
    _ohlcv_cache_hit.clear()
    _ohlcv_cache_miss.clear()


# 🔴 29.09 ДЫРЫ В WS-РЯДАХ. merge дописывал пришедший бар без проверки шага, а снимок с диска поднимался как есть:
# бары, пропущенные за время рестарта/обрыва WS, не докачивал никто, а TTL не истекал (WS освежает запись).
# Снимок 29.09 04:41: дыры у 613/621 записей 15m, 387 5m, 426 3m — ровно на моментах рестартов бота.
# Теперь: бар через дыру → запись сбрасывается (следующий get → REST целиком); запись с дырой из снимка не грузится.
_TF_STEP_MS: dict[str, int] = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "45m": 2_700_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}


def _has_gap(df: pd.DataFrame, tf: str) -> bool:
    step = _TF_STEP_MS.get(tf)
    if not step or df is None or len(df) < 2 or "time" not in df.columns:
        return False
    return bool((df["time"].astype("int64").diff().iloc[1:] != step).any())


class OhlcvCache:
    """TTL-кеш с LRU eviction.

    При 600 парах × 8 TF без eviction кеш растёт бесконтрольно.
    maxsize=5000 ≈ 600 пар × 8 TF × запас на разные limit-запросы.
    """

    def __init__(self, maxsize: int = 5000):
        self._data: OrderedDict = OrderedDict()
        self._maxsize = maxsize
        self.gap_drops = 0                  # записей сброшено из-за дыры (бар через пропуск)
        self._gap_logged = time.monotonic()
        # MARKET-WS Этап 2: cross-thread доступ (WS-поток пишет merge ↔ scan main-loop читает get).
        # RLock — reentrant (merge() вызывает self.set() внутри, иначе deadlock).
        self._lock = threading.RLock()

    def get(self, key: tuple, limit: int, ttl: float) -> Optional[pd.DataFrame]:
        """Возвращает копию DataFrame если кеш актуален и limit достаточен."""
        with self._lock:
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

    def get_stale(self, key: tuple, limit: int) -> Optional[pd.DataFrame]:
        """Возвращает кеш без проверки TTL (stale-on-error fallback при BingX DEGRADED)."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry["limit"] < limit:
                return None
            return entry["df"].copy()

    def set(self, key: tuple, df: pd.DataFrame, limit: int) -> None:
        """Записывает запись в кеш, вытесняя старейшую при переполнении."""
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = {"df": df, "ts": time.monotonic(), "limit": limit}
            # Evict oldest entries
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def merge(self, key: tuple, new_df: pd.DataFrame) -> str:
        """D-066 Phase B: merge новой WS свечи с существующим кешем.

        Args:
            key: (symbol, timeframe)
            new_df: DataFrame с колонками time/open/high/low/close/volume
                    (формат как у REST fetch_ohlcv в api_engine).
                    WS обычно даёт 1 строку — текущая активная свеча.

        Returns:
            'replace' | 'append' | 'init' | 'stale' | 'invalid'

        Логика:
            - Кеш пустой → init (set as-is)
            - new_df.last_time == cache.last_time → replace last row (свеча обновляется)
            - new_df.last_time > cache.last_time → append + drop oldest (новый bar открылся)
            - new_df.last_time < cache.last_time → stale (игнор)
        """
        if new_df is None or new_df.empty or "time" not in new_df.columns:
            return "invalid"
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                # D-066 fix: НЕ делаем init с малым limit (WS даёт 1 bar = limit=1).
                # scan_loop запрашивает limit=200+ → cache.get(limit=200) вернёт None
                # потому что entry["limit"]=1 < 200 → REST fetch → регрессия scan_loop.
                # Ждём пока REST загрузит первые N баров, потом WS только replace/append.
                return "skip_no_cache"
            existing = entry["df"]
            if "time" not in existing.columns:
                # Несовместимый формат в кеше — overwrite
                self.set(key, new_df.copy(), limit=len(new_df))
                return "init"
            try:
                new_last_t = int(new_df["time"].iloc[-1])
                cache_last_t = int(existing["time"].iloc[-1])
            except (ValueError, TypeError, IndexError):
                return "invalid"
            if new_last_t < cache_last_t:
                return "stale"
            if new_last_t == cache_last_t:
                # Тот же bar — обновляем последнюю строку in-place
                for col in ("open", "high", "low", "close", "volume"):
                    if col in new_df.columns:
                        existing.iloc[-1, existing.columns.get_loc(col)] = new_df[col].iloc[-1]
                entry["ts"] = time.monotonic()
                return "replace"
            if self._drop_on_gap(key, new_last_t - cache_last_t):
                return "gap"
            # Новый bar (new_last_t > cache_last_t): append + drop oldest, держим длину неизменной
            merged = pd.concat([existing, new_df.iloc[[-1]]], ignore_index=True)
            if len(merged) > entry["limit"]:
                merged = merged.iloc[len(merged) - entry["limit"]:].reset_index(drop=True)
            entry["df"] = merged
            entry["ts"] = time.monotonic()
            return "append"

    def merge_dict(self, key: tuple, row: dict) -> str:
        """ARCH-130: быстрый merge одной WS-свечи (dict) без pd.DataFrame([row]).

        replace-путь (90%+ случаев) = scalar df.at setter — без GIL-heavy NumPy allocation.
        append-путь (новый bar, ~раз в TF) = pd.concat как раньше, но это редко.
        """
        if not row or "time" not in row:
            return "invalid"
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return "skip_no_cache"
            existing = entry["df"]
            if "time" not in existing.columns:
                return "invalid"
            try:
                new_last_t = int(row["time"])
                cache_last_t = int(existing["time"].iloc[-1])
            except (ValueError, TypeError, IndexError):
                return "invalid"
            if new_last_t < cache_last_t:
                return "stale"
            if new_last_t == cache_last_t:
                last_idx = len(existing) - 1
                for col in ("open", "high", "low", "close", "volume"):
                    if col in row and col in existing.columns:
                        existing.at[last_idx, col] = row[col]
                entry["ts"] = time.monotonic()
                return "replace"
            if self._drop_on_gap(key, new_last_t - cache_last_t):
                return "gap"
            # Новый bar (append) — редко, pd.concat допустим
            new_df = pd.DataFrame([row])
            merged = pd.concat([existing, new_df], ignore_index=True)
            if len(merged) > entry["limit"]:
                merged = merged.iloc[len(merged) - entry["limit"]:].reset_index(drop=True)
            entry["df"] = merged
            entry["ts"] = time.monotonic()
            return "append"

    def _drop_on_gap(self, key: tuple, delta_ms: int) -> bool:
        """Бар пришёл через пропуск → сбросить запись (вызывается под self._lock)."""
        step = _TF_STEP_MS.get(key[1])
        if not step or delta_ms <= step:
            return False
        self._data.pop(key, None)
        self.gap_drops += 1
        if time.monotonic() - self._gap_logged >= 600:
            self._gap_logged = time.monotonic()
            logger.info("[OhlcvCache] дыры в WS-рядах: сброшено на REST %d записей (с запуска)", self.gap_drops)
        return True

    def __len__(self) -> int:
        return len(self._data)

    def save_to_disk(self, path: str, min_entries: int = 0) -> int:
        """D-069 (25.05): сохраняет cache на диск через pickle.

        Сохраняем wall-clock timestamp (time.time()), а НЕ monotonic —
        после рестарта Python monotonic сбрасывается. При load восстанавливаем
        ts через виртуальный monotonic = now - age_wallclock.

        min_entries (D-069 guard): НЕ перезаписывать файл, если текущий кэш меньше
        порога И на диске уже есть более полный снимок. Иначе периодический snapshot
        при рестарте (холодный кэш) затирал хороший файл почти пустым → load≈0 →
        холодный залп REST → IP-бан 100410. Защищаем лучший снимок.

        Returns: количество сохранённых entries (или существующих, если skip).
        """
        import pickle
        import os
        cur = len(self._data)
        # Guard: кэш недогрет — не затирать потенциально хороший файл на диске
        if min_entries > 0 and cur < min_entries and os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    existing = len(pickle.load(f))
                if existing > cur:
                    logger.info("[OhlcvCache] save SKIP: кэш недогрет (%d < %d на диске) — файл сохранён",
                                cur, existing)
                    return existing
            except Exception:
                pass  # файл битый/нечитаем — продолжаем перезапись
        snapshot = {}
        now_wall = time.time()
        for key, entry in self._data.items():
            age = time.monotonic() - entry["ts"]
            snapshot[key] = {
                "df": entry["df"],
                "limit": entry["limit"],
                "ts_wall": now_wall - age,   # фактический момент set
            }
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                pickle.dump(snapshot, f, protocol=pickle.HIGHEST_PROTOCOL)
            return len(snapshot)
        except Exception as e:
            logger.error("[OhlcvCache] save_to_disk error: %s", e)
            return 0

    def load_from_disk(self, path: str, max_ttl: float = 86400.0) -> int:
        """D-069 (25.05): загружает cache с диска, валидируя age по wall-clock.

        Args:
            max_ttl: отбрасываем entries старше N секунд (default 24h —
                     максимальный TTL в _CACHE_TTL для 1d свечей).

        Returns: количество загруженных entries.
        """
        import pickle
        import os
        if not os.path.exists(path):
            return 0
        try:
            with open(path, "rb") as f:
                snapshot = pickle.load(f)
        except Exception as e:
            logger.warning("[OhlcvCache] load_from_disk error: %s", e)
            return 0
        now_wall = time.time()
        now_mono = time.monotonic()
        loaded = holey = 0
        for key, entry in snapshot.items():
            age = now_wall - entry["ts_wall"]
            if age < 0 or age > max_ttl:
                continue  # stale или future ts (защита от системного clock skew)
            if _has_gap(entry["df"], key[1]):
                holey += 1
                continue  # 29.09: ряд с дырой не поднимаем — докачает REST целиком
            # Виртуальный monotonic timestamp: "как будто" set был age секунд назад
            self._data[key] = {
                "df": entry["df"],
                "ts": now_mono - age,
                "limit": entry["limit"],
            }
            loaded += 1
            if loaded >= self._maxsize:
                break
        if holey:
            logger.info("[OhlcvCache] снимок: %d записей с дырами не загружено (докачает REST)", holey)
        return loaded


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


class GlobalRateLimiter:
    """Token bucket rate limiter + глобальная пауза при BingX temp ban.

    Гарантирует не более `rps` запросов в секунду (скользящее окно).
    При получении 100410 (temp ban) — ВСЕ запросы приостанавливаются до разблокировки.
    """

    def __init__(self, rps: float = 8.0):
        self._rps = rps
        self._interval = 1.0 / rps  # мин. интервал между запросами
        # ⚡ B-эпик шаг 0 (13.06): threading.Lock вместо asyncio.Lock → loop-agnostic
        # (работает из любого event loop; обязательно для изоляции торгового loop, PERF-LOOP-DRIFT).
        # Лок держится ТОЛЬКО на арифметику резервации слота (мкс), asyncio.sleep — ВНЕ лока.
        # Бан через _ban_until (monotonic deadline), проверяется в acquire — без asyncio.Event/
        # ensure_future (они привязаны к loop → cross-loop crash). Прототип валидирован
        # scripts/test_rate_limiter_crossloop.py (4/4: shared RPS, cross-loop ban, single-loop parity).
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._ban_until = 0.0

    async def acquire(self) -> None:
        """Ждёт свою очередь с учётом rate limit и глобального бана. Loop-agnostic."""
        # Ждём окончания глобального бана (вне лока — чтобы не держать его во время sleep)
        while True:
            with self._lock:
                remaining = self._ban_until - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(remaining, 0.1))

        # Резервируем слот (lock на микросекунды — только арифметика)
        with self._lock:
            now = time.monotonic()
            ban_wait = self._ban_until - now
            if ban_wait > 0:
                sleep_for = ban_wait
                slot_time = now + ban_wait
            else:
                next_slot = max(self._last_request + self._interval, now)
                sleep_for = next_slot - now
                slot_time = next_slot
            self._last_request = slot_time

        if sleep_for > 0:
            await asyncio.sleep(sleep_for)

    def set_ban(self, duration_sec: float) -> None:
        """Глобальная пауза для ВСЕХ запросов (thread-safe, без asyncio — cross-loop safe)."""
        with self._lock:
            new_until = time.monotonic() + duration_sec
            if new_until > self._ban_until:
                self._ban_until = new_until
                logger.warning(
                    "🚫 GlobalRateLimiter: глобальный бан на %.0f сек (все запросы приостановлены)",
                    duration_sec,
                )


# Глобальный экземпляр rate limiter (один на весь процесс)
_global_rate_limiter: Optional[GlobalRateLimiter] = None


def get_global_rate_limiter(rps: float = 8.0) -> GlobalRateLimiter:
    """Возвращает singleton rate limiter."""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = GlobalRateLimiter(rps=rps)
    return _global_rate_limiter


class ApiEngine:
    """Транспортный слой над ccxt.

    Для каждого get_ohlcv-вызова порядок проверок:
    1. TTL-кеш (LRU, с учётом limit)
    2. Circuit breaker fast-fail
    3. In-flight deduplication (одинаковый key → один API-вызов)
    4. Global rate limiter (token bucket + ban pause)
    5. Retry с exponential backoff (NetworkError: 3×, RateLimitExceeded: 3×)
    6. Запись в кеш при успехе
    """

    def __init__(self, exchange, semaphore_size: int = 8, rps: float = 8.0, proxy_pool=None):
        self._exchange = exchange
        self._cache = OhlcvCache(maxsize=5000)
        self._cb = CircuitBreaker(threshold=10, timeout=60.0)
        # Централизованный семафор — ограничивает параллельные API-вызовы
        self._sem = asyncio.Semaphore(semaphore_size)
        # Глобальный rate limiter (singleton — общий для всех ApiEngine)
        self._rate_limiter = get_global_rate_limiter(rps=rps)
        # In-flight dedup: (symbol, timeframe, limit) → asyncio.Future
        self._in_flight: dict[tuple, asyncio.Future] = {}
        # PROXY-NODE: пул прокси для market-data (обход per-IP RPS). None = direct (как было).
        self._proxy_pool = proxy_pool
        if proxy_pool:
            logger.info("[ApiEngine] ProxyPool активен: %d прокси для market-data", proxy_pool.size)
        # Сфера 1 (N15, 29.09): 1h/4h/1d из хранилища закрытых баров + текущий бар из 15m (WS).
        # config market_store.bot_htf: off | shadow (REST как было + сверка в лог) | on.
        self._htf = None
        self._htf_tasks: set = set()
        try:
            from core.infra.config_loader import config as _cfg
            _raw = _cfg.get("market_store.bot_htf", "off")
            # голое on/off YAML отдаёт как bool (29.09: режим молча не включился)
            _mode = ("on" if _raw else "off") if isinstance(_raw, bool) else str(_raw).lower()
            if _mode not in ("off", "shadow", "on"):
                logger.warning("[HTF-STORE] неизвестный режим %r — выключено", _raw)
            if _mode in ("shadow", "on"):
                from core.infra.htf_from_store import HtfStore
                self._htf = HtfStore(_mode, {tf: n + 10 for tf, n in _CANON_LIMIT.items()})
                logger.info("[HTF-STORE] старшие ТФ из хранилища Сферы 1: режим %s", _mode)
        except Exception as _htf_e:  # noqa: BLE001 — без хранилища бот работает как раньше
            logger.warning("[HTF-STORE] не включён: %s", _htf_e)

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        since: Optional[int] = None,
        force_refresh: bool = False,
    ) -> Optional[pd.DataFrame]:
        """Основной метод получения OHLCV. Thread-safe для asyncio.

        force_refresh=True (DEV-227 stale-guard): обходит LRU-кэш и circuit breaker,
        делает реальный REST. Для активных OPEN сделок, чьи символы потеряли WS-обновление
        кэша (stale df → заниженный current_r). Свежий результат пишется обратно в кэш.
        """
        cache_key = (symbol, timeframe)
        # DS-322 + 02.09.2026: нормализация глубины — кэшируем ПОЛНЫЙ объём, отдаём
        # сколько просят. Раньше правило покрывало только 1h/4h/1d, а 3m/5m/15m шли
        # «как просили» — и давали 87% всех REST скана.
        #
        # 🔴 МЕХАНИКА ПРОМАХА. Кэш держит ОДНУ запись на (symbol, timeframe) и отдаёт
        # её, только если `entry.limit >= запрошенного`. По коду один и тот же ТФ
        # запрашивают с РАЗНОЙ глубиной: 1h — девятью (30/50/55/60/100/150/160/400/530),
        # 4h — шестью, 1d — пятью, 15m — шестью. Любой запрос глубже текущей записи
        # выбивает её в REST, следующий мелкий кладёт мелкую обратно — и так по кругу.
        # Отсюда hit 3m 32% и 5m 43% при 1h 91% и 4h 99%.
        #
        # 🔑 Замер BingX 02.09: REST при limit 60 / 150 / 400 стоит 1270 / 1248 / 1264 мс —
        # 1.00×. Глубина БЕСПЛАТНА, платим за факт запроса. Значит выгодно всегда тянуть
        # каноническую глубину: число запросов то же, а промахи исчезают.
        # Каноны = максимум, который встречается в коде для этого ТФ, с запасом.
        _fetch_limit = limit
        _canon = _CANON_LIMIT.get(timeframe)
        if _canon and limit < _canon:
            _fetch_limit = _canon
        dedup_key = (symbol, timeframe, _fetch_limit)
        ttl = _CACHE_TTL.get(timeframe, _DEFAULT_TTL)

        # Сфера 1: старший ТФ собирается из хранилища + 15m кэша; нехватка → обычный путь ниже.
        _htf = self._htf if (self._htf is not None and timeframe in ("1h", "4h", "1d")
                             and since is None and not force_refresh) else None
        if _htf is not None and _htf.mode == "on":
            df = await _htf.get(symbol, timeframe, _fetch_limit,
                                self._cache.get_stale((symbol, "15m"), limit=1))
            if df is not None:
                _ohlcv_cache_hit[timeframe] += 1
                return df.iloc[-limit:] if len(df) > limit else df

        if not force_refresh:
            # 1. Кеш
            cached = self._cache.get(cache_key, _fetch_limit, ttl)
            if cached is not None:
                _ohlcv_cache_hit[timeframe] += 1  # отдан из кэша (WS/TTL свежий)
                # DS-322: отдаём только запрошенное количество баров
                if len(cached) > limit:
                    return cached.iloc[-limit:]
                return cached

            # 2. Circuit breaker
            if self._cb.is_open():
                return None

        # 3. In-flight deduplication
        if dedup_key in self._in_flight:
            fut = self._in_flight[dedup_key]
            try:
                df = await asyncio.shield(fut)
                if df is not None:
                    if len(df) > limit:
                        return df.iloc[-limit:].copy()
                    return df.copy()
                return None
            except Exception:
                return None

        # 4. Создаём Future для этого запроса (другие корутины будут его ждать)
        _ohlcv_cache_miss[timeframe] += 1  # реальный REST (кэш промахнулся / force_refresh)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._in_flight[dedup_key] = fut

        try:
            # 🔴 17.08: запрашивать надо _fetch_limit, а НЕ limit. Иначе вызов с limit=3
            # (radar_armed_loop:457 просит 1d limit=3) тянул 3 бара, а в кэш они ложились
            # с меткой «200» → все следующие потребители 1d получали 3-4 бара вместо 200.
            # Итог: WT на 1d считался на 4 барах и взрывался до −328 у 99% монет.
            result = await self._fetch_with_retry(symbol, timeframe, _fetch_limit, since)
            # Любой ответ от API (даже пустой) = API доступен → success
            self._cb.record_success()
            if result is not None:
                self._cache.set(cache_key, result, _fetch_limit)
                if _htf is not None and _htf.mode == "shadow":
                    _t = asyncio.create_task(_htf.shadow_compare(
                        symbol, timeframe, result.copy(), self._cache.get_stale((symbol, "15m"), limit=1)))
                    self._htf_tasks.add(_t)
                    _t.add_done_callback(self._htf_tasks.discard)
                if len(result) > limit:      # вызвавшему отдаём ровно то, что он просил
                    result = result.iloc[-limit:]
            if not fut.done():
                fut.set_result(result)
            return result.copy() if result is not None else None
        except Exception as exc:
            # Только реальные сбои сети/rate-limit после всех retry → failure
            self._cb.record_failure()
            if not fut.done():
                fut.set_exception(exc)
                fut.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
            # Stale-on-error: при BingX DEGRADED лучше вернуть устаревший кеш чем None
            stale = self._cache.get_stale(cache_key, limit)
            if stale is not None:
                logger.debug("[ApiEngine] STALE fallback %s %s (REST err: %s)", symbol, timeframe, type(exc).__name__)
            return stale
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
            _last_proxy = None      # через какой прокси шла ЭТА попытка (None = direct)
            try:
                # Rate limiter: ждём свою очередь (token bucket + глобальный бан)
                await self._rate_limiter.acquire()
                async with self._sem:
                    if self._proxy_pool is not None:
                        # PROXY-NODE: market-data через пул прокси (обход per-IP RPS).
                        import time as _t
                        _pxurl = await self._proxy_pool.acquire()  # None = direct fallback
                        # запоминаем для внешнего except: 100410 приходит ПО IP,
                        # и наказывать нужно ровно этот выходной адрес
                        _last_proxy = _pxurl
                        _t0 = _t.monotonic()
                        try:
                            # race на aiohttp_proxy НЕ портит данные (любой прокси = тот же BingX-OHLCV),
                            # меняется лишь выходной IP → параллелизм сохранён (3× RPS), без lock.
                            self._exchange.aiohttp_proxy = _pxurl
                            candles = await self._exchange.fetch_ohlcv(
                                symbol, timeframe=timeframe, limit=limit, since=since)
                            self._proxy_pool.release(_pxurl, ok=True)
                            # throttled INFO-лог (каждый 25-й) — видно латентность прокси без спама
                            self._proxy_log_n = getattr(self, "_proxy_log_n", 0) + 1
                            if self._proxy_log_n % 25 == 0:
                                _ipshort = (_pxurl or "direct").split("@")[-1]
                                logger.info("[PROXY] %s %s via %s: %.0fms | pool=%s",
                                            symbol, timeframe, _ipshort,
                                            (_t.monotonic() - _t0) * 1000, self._proxy_pool.stats()["alive"])
                        except Exception as _pe:
                            # 27.09: ответ БИРЖИ (ExchangeError/BadSymbol — напр. 109415 по одной паре)
                            # значит, что прокси довёз запрос: штрафовать его нельзя. Раньше одна битая
                            # пара гнала здоровые прокси в карантин (277 раз за полчаса при 2 сетевых сбоях).
                            # 100410 (бан по IP) — тоже ExchangeError: его карантинит внешний except точечно.
                            _proxy_ok = isinstance(_pe, ccxt.ExchangeError)
                            self._proxy_pool.release(_pxurl, ok=_proxy_ok)
                            if not _proxy_ok:
                                _ipshort = (_pxurl or "direct").split("@")[-1]
                                logger.warning("[PROXY] %s %s via %s: FAIL %s: %s",
                                                symbol, timeframe, _ipshort, type(_pe).__name__, str(_pe)[:50])
                            raise
                    else:
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
                # Глобальный бан — все корутины тоже подождут
                self._rate_limiter.set_ban(wait)
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
                exc_str = str(exc)
                # BingX код 100410 — временный rate-limit бан (разблокировка через ~3 мин)
                if "100410" in exc_str:
                    # Извлекаем время разблокировки из ответа
                    wait = 30.0  # дефолт: 30 сек
                    try:
                        import re
                        m = re.search(r"unblocked after (\d+)", exc_str)
                        if m:
                            import time as _time
                            unblock_ms = int(m.group(1))
                            now_ms = int(_time.time() * 1000)
                            delta = (unblock_ms - now_ms) / 1000.0
                            if 0 < delta < 300:
                                wait = delta + 2.0  # +2 сек запас
                    except Exception:
                        pass
                    # 02.09.2026: 100410 выдаётся ПО IP — market-data идёт без ключа.
                    # Если запрос шёл через прокси, останавливать надо ТОЛЬКО его:
                    # прежде один забаненный адрес ставил глобальную паузу и тормозил
                    # весь пул, из-за чего смысл прокси терялся ровно в тот момент,
                    # когда они нужнее всего. Глобальная пауза остаётся для direct.
                    _quarantined = False
                    if self._proxy_pool is not None and _last_proxy is not None:
                        _quarantined = self._proxy_pool.quarantine(_last_proxy, wait)
                    if not _quarantined:
                        self._rate_limiter.set_ban(wait)
                        logger.warning(
                            "BingX 100410 (temp ban) %s %s — ГЛОБАЛЬНАЯ пауза %.1f сек (попытка %d/3)",
                            symbol, timeframe, wait, attempt + 1,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.info(
                            "BingX 100410 %s %s — забанен ОДИН прокси на %.0fs, пул продолжает",
                            symbol, timeframe, wait,
                        )
                    last_exc = exc
                    continue
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
                await self._rate_limiter.acquire()
                async with self._sem:
                    result = await self._exchange.fetch_ticker(symbol)
                self._cb.record_success()
                return result
            except ccxt.RateLimitExceeded:
                self._rate_limiter.set_ban(5.0 * (2 ** attempt))
                await asyncio.sleep(3.0 * (2 ** attempt))
            except Exception as exc:
                logger.debug("fetch_ticker %s: %s", symbol, exc)
                return None
        return None

    def cache_stats(self) -> dict:
        """Диагностика: размер кеша, состояние circuit breaker, rate limiter, in-flight запросы."""
        rl = self._rate_limiter
        ban_remaining = max(0.0, rl._ban_until - time.monotonic())
        return {
            "cache_size": len(self._cache),
            "cb_state": self._cb.state,
            "in_flight": len(self._in_flight),
            "rate_limiter_rps": rl._rps,
            "rate_limiter_banned": ban_remaining > 0,
            "rate_limiter_ban_remaining_sec": round(ban_remaining, 1),
        }
