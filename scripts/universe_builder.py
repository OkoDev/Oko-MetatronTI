"""
DEV-35/п.2: Universe Builder — случайная выборка топ-200 монет для бэктеста.

Методология:
  1. CoinGecko /coins/markets → топ-250 по капитализации (кэш 24ч)
  2. Фильтр: стейблы, wrapped токены, BTC (особый случай)
  3. Стратификация 10+10+10 (топ-10, 11-50, 51-200)
  4. random.sample с фиксированным seed (воспроизводимость)
  5. Нормализация: CoinGecko symbol → CCXT pair (SYMBOL/USDT)

Использование:
  python scripts/universe_builder.py              # дефолт: 30 монет, seed=42
  python scripts/universe_builder.py --n 50 --seed 123 --strata 15,15,20
  python scripts/universe_builder.py --no-cache   # принудительное обновление

Файл кэша: data/universe_cache.json (обновляется раз в 24ч)
"""

import argparse
import asyncio
import json
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).parent.parent / "data" / "universe_cache.json"
_CACHE_TTL_HOURS = 24
_COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"

# Стейблкоины и wrapped токены по base-символу (uppercase)
_STABLE_SYMBOLS = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "GUSD", "FRAX",
    "LUSD", "SUSD", "USDD", "FDUSD", "PYUSD", "CRVUSD", "USDE",
}
_WRAPPED_PREFIXES = ("W", "ST", "CB")  # WBTC, WETH, STETH, CBETH и т.д.
_EXCLUDED_SYMBOLS = {"BTC"}  # BTC исключаем явно (особый случай)

# ETH не исключаем — другая динамика, репрезентативен для топ-10


# ── CoinGecko ────────────────────────────────────────────────────────────────

async def _fetch_coingecko(page: int, per_page: int = 250) -> List[dict]:
    """Один запрос к CoinGecko /coins/markets."""
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": per_page,
        "page": page,
        "sparkline": "false",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(_COINGECKO_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            return await resp.json()


async def fetch_top_coins(limit: int = 250) -> List[dict]:
    """Загружает топ-N монет с CoinGecko (paginated если нужно)."""
    results = []
    page = 1
    per_page = min(limit, 250)
    while len(results) < limit:
        batch = await _fetch_coingecko(page, per_page)
        if not batch:
            break
        results.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
        await asyncio.sleep(1.5)  # CoinGecko rate limit: ~50 req/min бесплатно
    return results[:limit]


# ── Кэш ──────────────────────────────────────────────────────────────────────

def _load_cache() -> Optional[List[dict]]:
    """Загружает кэш если он не старше TTL."""
    if not _CACHE_FILE.exists():
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(data["cached_at"])
        if datetime.utcnow() - cached_at > timedelta(hours=_CACHE_TTL_HOURS):
            logger.info("[universe] кэш устарел (%s), обновляем", cached_at.date())
            return None
        logger.info("[universe] кэш актуален (%s, %d монет)", cached_at.date(), len(data["coins"]))
        return data["coins"]
    except Exception as e:
        logger.warning("[universe] ошибка чтения кэша: %s", e)
        return None


def _save_cache(coins: List[dict]) -> None:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"cached_at": datetime.utcnow().isoformat(), "coins": coins}
    _CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[universe] кэш сохранён: %d монет → %s", len(coins), _CACHE_FILE)


# ── Фильтрация ────────────────────────────────────────────────────────────────

def _is_excluded(coin: dict) -> bool:
    """True если монету нужно исключить."""
    sym = (coin.get("symbol") or "").upper()
    name = (coin.get("name") or "").lower()

    if sym in _EXCLUDED_SYMBOLS:
        return True
    if sym in _STABLE_SYMBOLS:
        return True
    # Стейблы по имени
    if any(w in name for w in ("usd", "tether", "dollar", "euro", "stablecoin")):
        return True
    # Wrapped/staked токены
    if sym.startswith(("W", "ST", "CB")) and len(sym) > 2 and sym[1:] in _STABLE_SYMBOLS | {"BTC", "ETH", "BNB"}:
        return True
    # Фильтр по длине тикера (мусор типа SAFESOLSAFEMOON)
    if len(sym) > 10:
        return True
    return False


def _filter_coins(coins: List[dict]) -> List[dict]:
    """Удаляет стейблы, wrapped токены, BTC и прочий мусор."""
    filtered = [c for c in coins if not _is_excluded(c)]
    logger.info("[universe] после фильтра: %d из %d монет", len(filtered), len(coins))
    return filtered


# ── Стратификация ──────────────────────────────────────────────────────────────

def _stratified_sample(
    coins: List[dict],
    strata: Tuple[int, int, int] = (10, 10, 10),
    seed: int = 42,
) -> List[dict]:
    """
    Стратифицированная выборка по уровням капитализации.
    strata = (n_top10, n_top11_50, n_top51_200)
    coins — уже отфильтрованный список, отсортированный по market_cap DESC.
    """
    rng = random.Random(seed)

    tier1 = coins[:10]          # топ-10 (без BTC → это топ-11 без исключённых)
    tier2 = coins[10:50]        # 11-50
    tier3 = coins[50:200]       # 51-200

    def safe_sample(pool, n):
        return rng.sample(pool, min(n, len(pool)))

    result = (
        safe_sample(tier1, strata[0]) +
        safe_sample(tier2, strata[1]) +
        safe_sample(tier3, strata[2])
    )
    return result


# ── Нормализация символов ─────────────────────────────────────────────────────

def _to_ccxt_pair(coin: dict, quote: str = "USDT") -> str:
    """CoinGecko symbol ('btc') → CCXT pair ('BTC/USDT')."""
    sym = (coin.get("symbol") or "").upper()
    return f"{sym}/{quote}"


# ── Публичный интерфейс ───────────────────────────────────────────────────────

async def build_universe(
    n: int = 30,
    seed: int = 42,
    strata: Tuple[int, int, int] = (10, 10, 10),
    force_refresh: bool = False,
    quote: str = "USDT",
) -> List[str]:
    """
    Возвращает список пар для бэктеста: ['ETH/USDT', 'SOL/USDT', ...].

    Параметры:
        n       — целевое кол-во монет (используется как проверка, реальное = sum(strata))
        seed    — seed для воспроизводимой случайной выборки
        strata  — кол-во монет из каждого тира (топ-10, 11-50, 51-200)
        force_refresh — игнорировать кэш, скачать заново
        quote   — котировочная валюта (USDT)
    """
    # 1. Загружаем данные (кэш или API)
    coins = None if force_refresh else _load_cache()
    if coins is None:
        logger.info("[universe] загрузка топ-250 с CoinGecko...")
        coins = await fetch_top_coins(250)
        _save_cache(coins)

    # 2. Фильтрация
    coins = _filter_coins(coins)

    # 3. Стратифицированная выборка
    sampled = _stratified_sample(coins, strata=strata, seed=seed)

    # 4. Нормализация → CCXT пары
    pairs = [_to_ccxt_pair(c, quote) for c in sampled]

    logger.info(
        "[universe] выборка: %d монет (seed=%d, strata=%s)",
        len(pairs), seed, strata,
    )
    return pairs


def build_universe_sync(
    n: int = 30,
    seed: int = 42,
    strata: Tuple[int, int, int] = (10, 10, 10),
    force_refresh: bool = False,
) -> List[str]:
    """Синхронная обёртка для использования вне async-контекста."""
    return asyncio.run(build_universe(n=n, seed=seed, strata=strata, force_refresh=force_refresh))


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Universe Builder — выборка монет для бэктеста")
    parser.add_argument("--n",       type=int,   default=30,       help="Целевое кол-во монет")
    parser.add_argument("--seed",    type=int,   default=42,       help="Random seed")
    parser.add_argument("--strata",  type=str,   default="10,10,10", help="Стратификация тиров (через запятую)")
    parser.add_argument("--no-cache", action="store_true",          help="Игнорировать кэш")
    args = parser.parse_args()

    strata = tuple(int(x) for x in args.strata.split(","))
    if len(strata) != 3:
        parser.error("--strata должен содержать 3 числа, например: 10,10,10")

    pairs = build_universe_sync(n=args.n, seed=args.seed, strata=strata, force_refresh=args.no_cache)

    print(f"\nUniverse: {len(pairs)} пар (seed={args.seed}, strata={strata})")
    print("-" * 40)
    for i, p in enumerate(pairs, 1):
        print(f"  {i:2d}. {p}")
