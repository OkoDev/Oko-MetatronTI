# -*- coding: utf-8 -*-
"""ORDER FLOW / CVD — агрегатор ленты сделок BingX (ЭПИК A, 04.09.2026).

Егор: «order flow / CVD — копить с нуля». Это последний слой, который нельзя
догнать задним числом: OI и стакан уже пишутся, лента — нет.

🔴 ПОЧЕМУ ОТДЕЛЬНЫЙ ПРОЦЕСС И БЕЗ ПОСДЕЛОЧНОГО ХРАНЕНИЯ.
Урок market_ws v1 (записан в шапке `core/infra/market_ws.py`): поток с 70k свечей/мин
держал GIL и растянул scan_loop с 300 до 600+ с. Лента сделок ПЛОТНЕЕ клайнов на
порядок. Поэтому:
  · запускается ОТДЕЛЬНЫМ процессом (pm2), к боту не прикасается;
  · сделки НЕ пишутся по одной — агрегируются в минутные бары прямо в памяти;
  · вселенная ограничена топом по обороту (лента по 500 парам не нужна и вредна).

ЧТО СЧИТАЕМ (то, чего нет в OHLCV):
  buy_vol / sell_vol  — объём по инициатору (в OHLCV агрегат, инициатор потерян)
  cvd                 — накопленная дельта за бар = buy − sell
  n_buy / n_sell      — число сделок каждой стороны (средний размер ≠ объём)
  max_trade_usd       — крупнейшая сделка бара (след крупного игрока)
  vol_usd             — оборот бара в долларах

🔑 Смысл слоя: OHLCV отвечает «куда пришла цена», лента — «кто её двигал».
Дельта-прокси по цвету свечи, который у нас сейчас, этого не различает: свеча
может закрыться вверх на продажах в стакан.

Запуск:  python scripts/orderflow_ws.py [top_n]
pm2:     pm2 start scripts/orderflow_ws.py --name orderflow-ws --interpreter python
"""
from __future__ import annotations

import asyncio
import gzip
import io as _io
import json
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("orderflow")

WS_URL = "wss://open-api-swap.bingx.com/swap-market"
DB = str(ROOT / "oko_feed" / "external_data.db")
BAR_SEC = 60                 # минутные бары: мельче не нужно, крупнее теряет всплески
FLUSH_SEC = 30               # сброс в БД
TOP_N_DEFAULT = 40           # вселенная по обороту
_TICKER = "https://open-api.bingx.com/openApi/swap/v2/quote/ticker"


def _ddl(c: sqlite3.Connection) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS orderflow_1m (
        symbol TEXT NOT NULL, ts INTEGER NOT NULL,
        buy_vol REAL, sell_vol REAL, cvd REAL,
        n_buy INTEGER, n_sell INTEGER,
        max_trade_usd REAL, vol_usd REAL,
        PRIMARY KEY (symbol, ts))""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_of_ts ON orderflow_1m(ts)")


def _cached_symbols() -> set[str]:
    """Символы, по которым есть история свечей. Формат кэша: 'BTC/USDT'."""
    try:
        c = sqlite3.connect(str(ROOT / "ohlcv_cache.db"), timeout=10)
        try:
            return {r[0] for r in c.execute("SELECT DISTINCT symbol FROM ohlcv_cache")}
        finally:
            c.close()
    except Exception as e:      # noqa: BLE001
        logger.warning("кэш недоступен (%s) — вселенная БЕЗ фильтра", e)
        return set()


def top_symbols(n: int) -> list[str]:
    """Топ по 24ч-обороту ∩ кэш истории — там лента осмысленна.

    🔴 Пересечение с кэшем обязательно. Голый топ по обороту затягивает синтетику
    BingX (NCCOGOLD2USD = золото, NCFXUSD2JPY = форекс, NCSINASDAQ100 = индекс) —
    04.09 таких было 13 из 40, треть потока писалась впустую. Их нет в боевой
    вселенной, и главное — нет истории, с которой ленту можно было бы сопоставить.
    """
    import urllib.request
    try:
        cache = _cached_symbols()
        req = urllib.request.Request(_TICKER, headers={"User-Agent": "oko"})
        data = json.load(urllib.request.urlopen(req, timeout=15)).get("data", [])
        rows = [(float(t.get("quoteVolume") or 0), str(t.get("symbol", "")))
                for t in data if t.get("symbol", "").endswith("-USDT")]
        rows.sort(reverse=True)
        picked = [s for _, s in rows if not cache or s.replace("-", "/") in cache]
        skipped = len(rows[:n]) - len([s for _, s in rows[:n]
                                       if not cache or s.replace("-", "/") in cache])
        if skipped:
            logger.info("[ORDERFLOW] отсеяно вне кэша в топ-%d: %d", n, skipped)
        return picked[:n]
    except Exception as e:  # noqa: BLE001
        logger.warning("ticker error: %s — фолбэк на BTC/ETH", e)
        return ["BTC-USDT", "ETH-USDT"]


def _decode(data) -> str:
    if isinstance(data, (bytes, bytearray)):
        try:
            return gzip.GzipFile(fileobj=_io.BytesIO(data)).read().decode("utf-8", "ignore")
        except Exception:      # noqa: BLE001
            return bytes(data).decode("utf-8", "ignore")
    return str(data)


class Aggregator:
    """Сделки → минутные бары. Держим ТОЛЬКО текущий и предыдущий бар на символ."""

    def __init__(self) -> None:
        self.bars: dict[tuple[str, int], dict] = defaultdict(
            lambda: {"buy_vol": 0.0, "sell_vol": 0.0, "n_buy": 0, "n_sell": 0,
                     "max_trade_usd": 0.0, "vol_usd": 0.0})
        self.trades = 0

    def add(self, sym: str, price: float, qty: float, is_buyer_maker: bool, ts_ms: int) -> None:
        bar = (ts_ms // 1000 // BAR_SEC) * BAR_SEC
        b = self.bars[(sym, bar)]
        usd = price * qty
        # BingX 'm': true = покупатель был МЕЙКЕРОМ ⇒ инициатор ПРОДАВЕЦ (агрессивная продажа)
        if is_buyer_maker:
            b["sell_vol"] += qty
            b["n_sell"] += 1
        else:
            b["buy_vol"] += qty
            b["n_buy"] += 1
        b["vol_usd"] += usd
        if usd > b["max_trade_usd"]:
            b["max_trade_usd"] = usd
        self.trades += 1

    def flush(self, keep_after: int) -> list[tuple]:
        """Отдаёт ЗАКРЫТЫЕ бары (старше keep_after) и убирает их из памяти."""
        out, drop = [], []
        for (sym, bar), b in self.bars.items():
            if bar >= keep_after:
                continue
            out.append((sym, bar, b["buy_vol"], b["sell_vol"],
                        b["buy_vol"] - b["sell_vol"], b["n_buy"], b["n_sell"],
                        b["max_trade_usd"], b["vol_usd"]))
            drop.append((sym, bar))
        for k in drop:
            self.bars.pop(k, None)
        return out


async def run(top_n: int) -> None:
    syms = top_symbols(top_n)
    logger.info("[ORDERFLOW] вселенная: %d пар (топ по обороту), бар %ds", len(syms), BAR_SEC)
    agg = Aggregator()
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    _ddl(con)
    con.commit()
    last_flush = time.time()
    written = 0

    while True:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.ws_connect(WS_URL, timeout=aiohttp.ClientTimeout(total=20),
                                           heartbeat=60) as ws:
                    for s in syms:
                        await ws.send_str(json.dumps({"id": f"of-{s}", "reqType": "sub",
                                                      "dataType": f"{s}@trade"}))
                        await asyncio.sleep(0.05)      # не бить пачкой — сервер режет
                    logger.info("[ORDERFLOW] подписка отправлена (%d)", len(syms))
                    async for m in ws:
                        if m.type not in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                            continue
                        raw = _decode(m.data)
                        if raw == "Ping" or '"ping"' in raw.lower():
                            try:
                                await ws.send_str("Pong")
                            except Exception:      # noqa: BLE001
                                pass
                            continue
                        try:
                            msg = json.loads(raw)
                        except Exception:      # noqa: BLE001
                            continue
                        dt = str(msg.get("dataType", ""))
                        if "@trade" not in dt:
                            continue
                        sym = dt.split("@")[0]
                        d = msg.get("data")
                        items = d if isinstance(d, list) else ([d] if isinstance(d, dict) else [])
                        for it in items:
                            try:
                                agg.add(sym, float(it.get("p") or it.get("price") or 0),
                                        float(it.get("q") or it.get("qty") or 0),
                                        bool(it.get("m", False)),
                                        int(it.get("T") or it.get("t") or time.time() * 1000))
                            except (TypeError, ValueError):
                                continue
                        now = time.time()
                        if now - last_flush >= FLUSH_SEC:
                            rows = agg.flush(keep_after=int(now // BAR_SEC) * BAR_SEC)
                            if rows:
                                con.executemany(
                                    "INSERT OR IGNORE INTO orderflow_1m VALUES (?,?,?,?,?,?,?,?,?)",
                                    rows)
                                con.commit()
                                written += len(rows)
                                logger.info("[ORDERFLOW] +%d баров (всего %d) · сделок %d · "
                                            "в памяти %d", len(rows), written, agg.trades,
                                            len(agg.bars))
                            last_flush = now
        except asyncio.CancelledError:
            raise
        except Exception as e:      # noqa: BLE001
            logger.warning("[ORDERFLOW] loop error: %s: %s — reconnect 5s",
                           type(e).__name__, str(e) or "«без сообщения»")
            await asyncio.sleep(5)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else TOP_N_DEFAULT
    try:
        asyncio.run(run(n))
    except KeyboardInterrupt:
        logger.info("[ORDERFLOW] остановлен")
