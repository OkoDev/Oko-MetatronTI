# -*- coding: utf-8 -*-
"""PriceWS — поток цены на СВОЁМ клиенте вместо ccxt.pro (N21, 05.10.2026).

Зачем (замер 04.10, Егор «делаем В и не откладываем»):
  · WsFeed на ccxt.pro шёл ЧЕРЕЗ VPN и добавлял ~12.5 ГБ/сут — A/B на прогретом боте:
    с ним 21.4/22.9/23.5 ГБ/сут, без него 11.4/9.35. Увести мимо туннеля там нельзя
    без подмены внутренней сессии; здесь bind — одна строка, как у свечей.
  · ccxt.pro живёт задачами в ОБЩЕМ event loop бота (единственный из трёх потоков);
    свечи и лента давно в своих процессах/потоках. Урок market_ws v1: high-rate WS
    в основном loop душит скан.
  · канал дешевле: разведка 04.10 на BTC (байт/с на пару) — markPrice 125,
    lastPrice 317, ticker 327 (его шлёт ccxt.pro), bookTicker 493, trade 743.

🔑 Почему markPrice по умолчанию: наши стоп-ордера на бирже стоят с
   `workingType = MARK_PRICE` — то есть биржа исполняет их ИМЕННО по этой цене.
   Следить за стопом по цене последней сделки значит смотреть не на тот прибор.
   lastPrice доступен тем же клиентом — `performance.price_ws_channel`.

Протокол BingX (проверен эмпирически, см. scratchpad/probe_bingx_channels.py):
  sub:  {"id": ..., "reqType": "sub", "dataType": "BTC-USDT@markPrice"}
  tick: {"code":0,"dataType":"BTC-USDT@markPrice","data":{"e":"markPriceUpdate","s":"BTC-USDT","p":"85841.7"}}
  lastPrice кладёт цену в поле "c", markPrice — в "p". Ping/Pong текстом, тело gzip.
"""
from __future__ import annotations

import asyncio
import collections
import gzip
import io
import json
import logging
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Set

import aiohttp

from core.infra.market_ws import _ccxt_to_ws, _ws_to_ccxt, local_ip_by_prefix

logger = logging.getLogger(__name__)

WS_URL = "wss://open-api-swap.bingx.com/swap-market"
_STAGGER_SEC = 1.5          # разносим handshake, чтобы не бить залпом (BingX 100410)
_RECONNECT_SEC = 5.0
_PRICE_TTL = 60.0           # цена старше — считаем протухшей (как было у WsFeed)
_SUB_PAUSE = 0.04           # пауза между подписками внутри соединения

# ── ЛОВЕЦ ЭПИЗОДОВ (ARCH-154, 31.10) ───────────────────────────────────────────
# Зачем: рестарты бота дают эпизоды роста памяти — очередь таймеров ЭТОГО цикла уходит
# с единиц до десятков миллионов (замер 31.10 02:48: 37,3 млн, 11,4 ГБ за 16 мин), и
# `pm2_guard` убивает бота по потолку 10 ГБ. Обычный хвост очереди — 1–16, эпизод — миллионы,
# поэтому порог можно поставить с запасом ×3000 и всё равно поймать самое начало разгона.
_CATCH_SEC = 10.0               # шаг замера (только чтение счётчиков и размера очереди)
_CATCH_HEAP_WARN = 50_000       # 50 тыс. таймеров в очереди — уже не норма
_CATCH_HEAP_EPISODE = 500_000   # 0,5 млн — явный разгон (в бою видели до 61 млн)
_CATCH_LOG = Path("logs/price_ws_catch.jsonl")


def episode_severity(heap: int, warn: int = _CATCH_HEAP_WARN, episode: int = _CATCH_HEAP_EPISODE) -> str:
    """'ok' | 'warn' | 'episode' по размеру очереди таймеров цикла (чистая функция — под тест)."""
    if heap >= episode:
        return "episode"
    if heap >= warn:
        return "warn"
    return "ok"


# 🔴 31.10 06:44 (живой замер): сторожа убил бота на 20 437 МБ, а очередь таймеров была **25** —
# значит эпизоды бывают РАЗНЫЕ, и одного «таймерного» признака мало. Поэтому ловец меряет ещё и
# приватную память процесса (то же число, что видит `pm2_guard`), и порог памяти ставится ДО потолка
# сторожа (10 240 МБ), чтобы успеть снять улики, а не узнать о разгоне из «ЛЕЧЕНИЕ».
_CATCH_RSS_WARN_MB = 4_096.0
_CATCH_RSS_EPISODE_MB = 6_144.0


def catch_severity(heap: int, rss_mb, warn: int = _CATCH_HEAP_WARN, episode: int = _CATCH_HEAP_EPISODE,
                   rss_warn: float = _CATCH_RSS_WARN_MB,
                   rss_episode: float = _CATCH_RSS_EPISODE_MB) -> str:
    """'ok' | 'warn' | 'episode' по ДВУМ признакам: очередь таймеров И память процесса."""
    rss = None if rss_mb is None else float(rss_mb)
    if heap >= episode or (rss is not None and rss >= rss_episode):
        return "episode"
    if heap >= warn or (rss is not None and rss >= rss_warn):
        return "warn"
    return "ok"


class PriceWS:
    """Цена по WS: N соединений батчами, bind мимо VPN, публикация в шину с порогом."""

    def __init__(
        self,
        symbols: list[str],
        bus=None,
        channel: str = "markPrice",
        batch_pairs: int = 100,
        bind_prefix: str = "",
        pub_sec: float = 15.0,
        pub_prio_sec: float = 1.0,
        fast_channel: str = "lastPrice",   # канал для торгуемых пар ("" = выключить)
        fast_limit: int = 60,              # сколько пар держим на быстром канале
        priority_provider=None,            # callable -> set[str]; None = спросить шину
    ):
        self._symbols = list(symbols)
        self._bus = bus
        self._channel = channel if channel in ("markPrice", "lastPrice") else "markPrice"
        self._batch = max(1, int(batch_pairs))
        self._bind_prefix = bind_prefix
        self._pub_sec = float(pub_sec)
        self._pub_prio_sec = float(pub_prio_sec)
        self._fast_channel = fast_channel if fast_channel in ("lastPrice", "bookTicker") else ""
        self._fast_limit = max(0, int(fast_limit))
        self._prio_provider = priority_provider

        self._prices: Dict[str, tuple] = {}        # sym → (price, ts)
        self._fast_at: Dict[str, float] = {}       # когда по паре приходил быстрый канал
        self._last_pub: Dict[str, float] = {}
        self._prio: Set[str] = set()
        self._prio_ts = 0.0
        self._running = False
        self._started_at: Optional[float] = None
        self.stats = {"updates": 0, "published": 0, "conns": 0, "reconnects": 0,
                      "pings": 0, "errors": 0, "subscribed": 0}
        # Ловец эпизодов (ARCH-154): счётчики поведения приёма + кольцо редких событий.
        # Пишем только целые числа в dict — цена на сообщение нулевая, WS не тормозим.
        self.anom = {"recv": 0, "timeout": 0, "nonmsg": 0, "spin": 0,
                     "err": 0, "reconn": 0, "sub": 0, "unsub": 0}
        self._events: collections.deque = collections.deque(maxlen=40)   # (ts, вид, деталь)
        self._fast_state = {"want": 0, "subscribed": 0}

    # ── интерфейс потребителя (совместим с WsFeed) ───────────────────────────
    def get_price(self, symbol: str) -> Optional[float]:
        entry = self._prices.get(symbol)
        if not entry:
            return None
        price, ts = entry
        return price if time.time() - ts <= _PRICE_TTL else None

    def is_alive(self) -> bool:
        return self._running and bool(self._prices)

    def stats_dict(self) -> dict:
        return {**self.stats, "pairs": len(self._prices), "channel": self._channel,
                "uptime_sec": int(time.time() - self._started_at) if self._started_at else 0}

    # ── приоритет публикации: там, где торгуем, цена нужна сейчас ────────────
    def _priority(self, now: float) -> Set[str]:
        """Пары, где цена нужна сейчас.

        🔴 05.10: сначала приоритет брался из `PairState.open_trade_id` — и был ПУСТ
        у всех 585 пар при семи живых позициях. Поле объявлено в каталоге шины за
        Сферой 10 и читается тремя заглушками в `bot/core/bot.py`, но НИКЕМ НЕ ПИШЕТСЯ
        (бэклог N22). Поэтому источник — поставщик снаружи (открытые сделки из БД),
        а шина остаётся запасным путём: watchlist в ней живой.
        """
        if now - self._prio_ts < 10.0:
            return self._prio
        self._prio_ts = now
        if self._prio_provider is not None:
            try:
                got = set(self._prio_provider() or ())
                if got:
                    self._prio = got
                    return self._prio
            except Exception as e:                  # noqa: BLE001
                logger.debug("[PriceWS] поставщик приоритета: %s", e)
        if self._bus is None:
            return self._prio
        try:
            prio = set()
            for sym in self._bus.all_symbols():
                st = self._bus.get(sym)
                if getattr(st, "open_trade_id", None) or getattr(st, "watchlist", None):
                    prio.add(sym)
            self._prio = prio
        except Exception as e:                      # noqa: BLE001
            logger.debug("[PriceWS] приоритет из шины: %s", e)
        return self._prio

    @staticmethod
    def _decode(data) -> str:
        if isinstance(data, (bytes, bytearray)):
            try:
                return gzip.GzipFile(fileobj=io.BytesIO(data)).read().decode("utf-8", "ignore")
            except Exception:
                return bytes(data).decode("utf-8", "ignore")
        return str(data)

    def _on_price(self, sym_ccxt: str, price: float, fast: bool = False) -> None:
        now = time.time()
        # Медленный канал не затирает свежую цену быстрого: на торгуемых парах
        # lastPrice отражает момент точнее, чем markPrice раз в десятки секунд.
        if not fast and now - self._fast_at.get(sym_ccxt, 0.0) < 20.0:
            return
        if fast:
            self._fast_at[sym_ccxt] = now
        self._prices[sym_ccxt] = (price, now)
        self.stats["updates"] += 1
        if self._bus is None:
            return
        gap = self._pub_prio_sec if sym_ccxt in self._priority(now) else self._pub_sec
        if now - self._last_pub.get(sym_ccxt, 0.0) < gap:
            return
        self._last_pub[sym_ccxt] = now
        try:
            from core.context.pair_context import SphereEvent
            self._bus.publish(sym_ccxt, SphereEvent.TICK_PRICE, {"price": price})
            self.stats["published"] += 1
        except Exception as e:                      # noqa: BLE001
            self.stats["errors"] += 1
            logger.debug("[PriceWS] publish %s: %s", sym_ccxt, e)

    def _parse(self, msg: dict, channel: Optional[str] = None) -> Optional[tuple]:
        ch = channel or self._channel
        dt = str(msg.get("dataType", ""))
        if f"@{ch}" not in dt:
            return None
        data = msg.get("data")
        if not isinstance(data, dict):
            return None
        raw = data.get("p") if ch == "markPrice" else data.get("c")
        try:
            price = float(raw)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None
        return _ws_to_ccxt(data.get("s") or dt.split("@")[0]), price

    # ── соединение ───────────────────────────────────────────────────────────
    async def _connection(self, batch: list[str], idx: int) -> None:
        if idx > 0:
            await asyncio.sleep(idx * _STAGGER_SEC)
        first = True
        while self._running:
            try:
                ip = local_ip_by_prefix(self._bind_prefix)
                conn = (aiohttp.TCPConnector(local_addr=(ip, 0), family=socket.AF_INET)
                        if ip else None)
                if first and idx == 0:
                    logger.info("[PriceWS] канал %s · bind %s · батчей %d",
                                self._channel, ip or "как все (через VPN)",
                                -(-len(self._symbols) // self._batch))
                async with aiohttp.ClientSession(connector=conn) as s:
                    async with s.ws_connect(WS_URL, timeout=aiohttp.ClientTimeout(total=20)) as ws:
                        self.stats["conns"] += 1
                        for sym in batch:
                            await ws.send_str(json.dumps({
                                "id": str(uuid.uuid4()), "reqType": "sub",
                                "dataType": f"{_ccxt_to_ws(sym)}@{self._channel}",
                            }))
                            self.stats["subscribed"] += 1
                            await asyncio.sleep(_SUB_PAUSE)
                        first = False
                        async for m in ws:
                            if not self._running:
                                break
                            if m.type not in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                                continue
                            raw = self._decode(m.data)
                            if raw == "Ping" or '"ping"' in raw.lower():
                                self.stats["pings"] += 1
                                try:
                                    await ws.send_str("Pong")
                                except Exception:   # noqa: BLE001
                                    break
                                continue
                            try:
                                msg = json.loads(raw)
                            except Exception:       # noqa: BLE001
                                continue
                            parsed = self._parse(msg)
                            if parsed:
                                self._on_price(*parsed)
            except asyncio.CancelledError:
                raise
            except Exception as e:                  # noqa: BLE001
                self.anom["err"] += 1
                self._note("conn_err", f"#{idx} {type(e).__name__}: {str(e)[:80]}")
                self.stats["errors"] += 1
                if self.stats["errors"] <= 3:
                    logger.warning("[PriceWS] соединение #%d: %s", idx, e)
            if self._running:
                self.stats["reconnects"] += 1
                await asyncio.sleep(_RECONNECT_SEC)

    async def _priority_connection(self) -> None:
        """Пары, где торгуем, — на БЫСТРОМ канале (lastPrice).

        Замер 05.10: markPrice дёшев (125 Б/с против 327 у ticker), но и обновляется
        реже — на парах с открытыми сделками цена в шине жила 10-45 с против 3-4 с
        у прежнего ccxt.pro. Для горстки торгуемых пар берём lastPrice: это десятки
        килобайт в секунду, зато там, где решается судьба позиции, цена живая.
        Список пересматривается каждые 30 с: сделки открываются и закрываются.
        """
        if not self._fast_channel:
            return
        while self._running:
            subscribed = set()
            try:
                ip = local_ip_by_prefix(self._bind_prefix)
                conn = (aiohttp.TCPConnector(local_addr=(ip, 0), family=socket.AF_INET)
                        if ip else None)
                async with aiohttp.ClientSession(connector=conn) as s:
                    async with s.ws_connect(WS_URL, timeout=aiohttp.ClientTimeout(total=20)) as ws:
                        self.stats["conns"] += 1
                        while self._running:
                            want = set(list(self._priority(time.time()))[:self._fast_limit])
                            for sym in want - subscribed:
                                await ws.send_str(json.dumps({
                                    "id": str(uuid.uuid4()), "reqType": "sub",
                                    "dataType": _ccxt_to_ws(sym) + "@" + self._fast_channel}))
                                self.anom["sub"] += 1
                                await asyncio.sleep(_SUB_PAUSE)
                            for sym in subscribed - want:
                                await ws.send_str(json.dumps({
                                    "id": str(uuid.uuid4()), "reqType": "unsub",
                                    "dataType": _ccxt_to_ws(sym) + "@" + self._fast_channel}))
                                self.anom["unsub"] += 1
                                await asyncio.sleep(_SUB_PAUSE)
                            self._fast_state["want"] = len(want)
                            if want != subscribed:
                                logger.info("[PriceWS] быстрый канал %s: пар %d",
                                            self._fast_channel, len(want))
                                subscribed = want
                            self._fast_state["subscribed"] = len(subscribed)
                            deadline = time.time() + 30
                            while self._running and time.time() < deadline:
                                try:
                                    _t0 = time.monotonic()
                                    m = await asyncio.wait_for(ws.receive(), timeout=5)
                                    self.anom["recv"] += 1
                                    if time.monotonic() - _t0 < 0.002:   # приём «вхолостую» — признак спина
                                        self.anom["spin"] += 1
                                except asyncio.TimeoutError:
                                    self.anom["timeout"] += 1
                                    continue
                                if m.type not in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                                    self.anom["nonmsg"] += 1
                                    self._note("recv_nonmsg", str(m.type))
                                    break
                                raw = self._decode(m.data)
                                if raw == "Ping" or '"ping"' in raw.lower():
                                    self.stats["pings"] += 1
                                    await ws.send_str("Pong")
                                    continue
                                try:
                                    msg = json.loads(raw)
                                except Exception:       # noqa: BLE001
                                    continue
                                parsed = self._parse(msg, channel=self._fast_channel)
                                if parsed:
                                    self._on_price(parsed[0], parsed[1], fast=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:                      # noqa: BLE001
                self.stats["errors"] += 1
                self.anom["err"] += 1
                self._note("fast_err", f"{type(e).__name__}: {str(e)[:80]}")
                if self.stats["errors"] <= 5:
                    logger.warning("[PriceWS] быстрый канал упал: %s: %s", type(e).__name__, e)
            if self._running:
                self.anom["reconn"] += 1
                self._note("fast_reconn", f"подписок {self._fast_state['subscribed']}")
                await asyncio.sleep(_RECONNECT_SEC)

    async def _stats_loop(self) -> None:
        while self._running:
            await asyncio.sleep(60)
            logger.info("[PriceWS] STATS: %s", self.stats_dict())

    # ── ЛОВЕЦ ЭПИЗОДОВ (ARCH-154) ─────────────────────────────────────────────
    def _note(self, kind: str, detail: str = "") -> None:
        """Редкое событие в кольцо — оно и станет уликой, когда начнётся разгон."""
        try:
            self._events.append((round(time.time(), 1), kind, detail))
        except Exception:                                    # noqa: BLE001 — ловец не смеет падать
            pass

    def _catch_snapshot(self) -> dict:
        """Срез «здоровья» этого цикла: очередь таймеров, память процесса, счётчики приёма, подписки."""
        loop = asyncio.get_running_loop()
        heap = len(getattr(loop, "_scheduled", ()))
        rss = None
        try:                                   # то же число, что видит pm2_guard (PrivateUsage)
            from core.infra.mem_census import _private_mb
            rss = _private_mb()
        except Exception:                      # noqa: BLE001 — ловец не смеет падать
            rss = None
        snap = dict(self.anom)
        snap.update({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "uptime_sec": int(time.time() - self._started_at) if self._started_at else 0,
            "heap": heap,
            "rss_mb": rss,
            "timers_cancelled": getattr(loop, "_timer_cancelled_count", 0),
            "ready": len(getattr(loop, "_ready", ())),
            "updates": self.stats["updates"],
            "conns": self.stats["conns"],
            "pairs": len(self._prices),
            "want": self._fast_state["want"],
            "subscribed": self._fast_state["subscribed"],
            "severity": catch_severity(heap, rss, warn=_CATCH_HEAP_WARN, episode=_CATCH_HEAP_EPISODE,
                                       rss_warn=_CATCH_RSS_WARN_MB,
                                       rss_episode=_CATCH_RSS_EPISODE_MB),
            "events": list(self._events)[-12:],
        })
        return snap

    async def _catch_loop(self) -> None:
        """Раз в 10 с меряет очередь таймеров СВОЕГО цикла (дёшево) и пишет срез раз в минуту.

        Норма — единицы таймеров, эпизод — миллионы (замер: 32–61 млн, память до 20 ГБ).
        При разгоне: ERROR в лог + срез в `logs/price_ws_catch.jsonl` + Telegram/WATCH через
        `scripts/_alert.notify` (смена состояния, без повторов). Возврат в норму — тоже факт.
        """
        prev = None
        last_state = None
        try:
            _last_write = 0.0
            while self._running:
                await asyncio.sleep(_CATCH_SEC)
                rec = self._catch_snapshot()
                if prev is not None:
                    dt = max(1e-6, rec["uptime_sec"] - prev["uptime_sec"])
                    rec["heap_delta"] = rec["heap"] - prev["heap"]
                    rec["recv_per_s"] = round((rec["recv"] - prev["recv"]) / dt, 1)
                    rec["timeout_per_s"] = round((rec["timeout"] - prev["timeout"]) / dt, 1)
                    rec["spin_per_s"] = round((rec["spin"] - prev["spin"]) / dt, 1)
                    rec["rss_delta"] = (round(rec["rss_mb"] - prev["rss_mb"], 1)
                                        if rec.get("rss_mb") is not None and prev.get("rss_mb") is not None
                                        else None)
                else:
                    rec["heap_delta"] = rec["recv_per_s"] = rec["timeout_per_s"] = rec["spin_per_s"] = 0
                    rec["rss_delta"] = None
                prev = rec
                sev = rec["severity"]
                if sev != "ok":
                    logger.error("[PriceWS][CATCH] %s: таймеров %d (+%d за %0.0f с) · память %s МБ "
                                 "(+%s) · приём %s/с · таймаутов %s/с · спин %s/с · отписки %d · "
                                 "подписок %d/%d · конн %d, реконнектов %d",
                                 sev.upper(), rec["heap"], rec["heap_delta"], _CATCH_SEC,
                                 rec.get("rss_mb"), rec.get("rss_delta"),
                                 rec["recv_per_s"], rec["timeout_per_s"], rec["spin_per_s"],
                                 rec["unsub"], rec["subscribed"], rec["want"],
                                 rec["conns"], rec["reconn"])
                now = time.monotonic()
                periodic = now - _last_write >= 60           # «живой» след раз в минуту
                if periodic:
                    _last_write = now
                    asyncio.create_task(asyncio.to_thread(_append_catch_log, rec))
                if sev != last_state:
                    # первый замер — только запоминаем состояние, чтобы не звонить «OK» на старте;
                    # запись в файл уже сделана выше (periodic), дубль не нужен
                    if last_state is not None:
                        self._catch_report(rec, write_file=not periodic)
                    last_state = sev
        except asyncio.CancelledError:
            raise
        except Exception as e:                              # noqa: BLE001 — ловец не роняет WS
            logger.warning("[PriceWS][CATCH] ловец остановлен: %s: %s", type(e).__name__, e)

    def _catch_report(self, rec: dict, write_file: bool = True) -> None:
        """Смена состояния ловца: файл + Telegram + WATCH.md + шина (`_alert.notify`)."""
        if write_file:
            asyncio.create_task(asyncio.to_thread(_append_catch_log, rec))
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from scripts._alert import notify as _notify
            state = {"episode": "EPISODE", "warn": "WARN", "ok": "OK"}[rec["severity"]]
            detail = (f"таймеров {rec['heap']:,} (+{rec['heap_delta']:,}) · "
                      f"память {rec.get('rss_mb')} МБ (+{rec.get('rss_delta')}) · "
                      f"приём {rec['recv_per_s']}/с · таймаутов {rec['timeout_per_s']}/с · "
                      f"спин {rec['spin_per_s']}/с · отписки {rec['unsub']} · "
                      f"подписок {rec['subscribed']}/{rec['want']} · "
                      f"конн {rec['conns']} · реконнектов {rec['reconn']}")
            _notify("price_ws_episode", state,
                    title=f"ARCH-154 · ловец эпизодов PriceWS · {state}",
                    tg_text=f"*ARCH-154 · PriceWS* — {state}\n{detail}",
                    task_detail=detail)
        except Exception as e:                              # noqa: BLE001 — оповещение не роняет WS
            logger.warning("[PriceWS][CATCH] оповещение не отправлено: %s", e)

    async def run(self) -> None:
        self._running = True
        self._started_at = time.time()
        batches = [self._symbols[i:i + self._batch]
                   for i in range(0, len(self._symbols), self._batch)]
        logger.info("[PriceWS] старт: пар %d, соединений %d, канал %s",
                    len(self._symbols), len(batches), self._channel)
        tasks = [asyncio.create_task(self._connection(b, i)) for i, b in enumerate(batches)]
        tasks.append(asyncio.create_task(self._priority_connection()))
        tasks.append(asyncio.create_task(self._stats_loop()))
        tasks.append(asyncio.create_task(self._catch_loop()))
        logger.info("[PriceWS][CATCH] ловец эпизодов включён: шаг %.0f с · порог warn %d, "
                    "episode %d таймеров", _CATCH_SEC, _CATCH_HEAP_WARN, _CATCH_HEAP_EPISODE)
        await asyncio.gather(*tasks, return_exceptions=True)


def _append_catch_log(rec: dict) -> None:
    """Дописать срез ловца в JSONL (в отдельном потоке — WS-цикл не ждёт диск)."""
    try:
        _CATCH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_CATCH_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:                                  # noqa: BLE001
        logger.debug("[PriceWS][CATCH] запись среза: %s", e)

    def stop(self) -> None:
        self._running = False


def _open_trade_symbols() -> set:
    """Пары с открытыми сделками — прямо из БД: единственный честный источник.

    Дёшево (индексированный запрос по status), зовётся раз в 10 с.
    """
    import sqlite3
    from pathlib import Path as _P
    db = _P(__file__).resolve().parents[2] / "subscriptions.db"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            return {r[0] for r in con.execute(
                "SELECT DISTINCT symbol FROM simulated_trades WHERE status='OPEN'")}
        finally:
            con.close()
    except Exception as e:                          # noqa: BLE001
        logger.debug("[PriceWS] открытые сделки из БД: %s", e)
        return set()


def start_price_ws(bot):
    """Запуск в ОТДЕЛЬНОМ потоке со своим loop — торговый loop не трогаем."""
    global _CATCH_SEC, _CATCH_HEAP_WARN, _CATCH_HEAP_EPISODE, _CATCH_RSS_WARN_MB, _CATCH_RSS_EPISODE_MB
    from core.infra.config_loader import config

    if not config.get("performance.price_ws_enabled", False):
        return None
    # Ловец эпизодов ARCH-154: шаг и пороги — из конфига (по умолчанию как в замерах)
    try:
        _CATCH_SEC = float(config.get("performance.price_ws_catch_sec", _CATCH_SEC))
        _CATCH_HEAP_WARN = int(config.get("performance.price_ws_catch_heap_warn", _CATCH_HEAP_WARN))
        _CATCH_HEAP_EPISODE = int(config.get("performance.price_ws_catch_heap_episode",
                                            _CATCH_HEAP_EPISODE))
        _CATCH_RSS_WARN_MB = float(config.get("performance.price_ws_catch_rss_warn_mb",
                                              _CATCH_RSS_WARN_MB))
        _CATCH_RSS_EPISODE_MB = float(config.get("performance.price_ws_catch_rss_episode_mb",
                                                 _CATCH_RSS_EPISODE_MB))
    except Exception as _c_e:                                  # noqa: BLE001 — как в замерах
        logger.warning("[PriceWS][CATCH] настройки не прочитаны (%s) — работают умолчания", _c_e)
    symbols = list(getattr(bot.data_collector, "usdt_pairs", []) or [])
    if not symbols:
        logger.warning("[PriceWS] вселенная пуста — не стартуем")
        return None

    feed = PriceWS(
        symbols,
        bus=getattr(bot, "pair_context", None),
        channel=str(config.get("performance.price_ws_channel", "markPrice")),
        batch_pairs=int(config.get("performance.price_ws_batch", 100)),
        bind_prefix=str(config.get("market_ws.bind_ip_prefix", "") or ""),
        pub_sec=float(config.get("performance.ws_bus_publish_sec", 15.0)),
        pub_prio_sec=float(config.get("performance.ws_bus_publish_priority_sec", 1.0)),
        fast_channel=str(config.get("performance.price_ws_fast_channel", "lastPrice")),
        fast_limit=int(config.get("performance.price_ws_fast_limit", 60)),
        priority_provider=_open_trade_symbols,
    )

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(feed.run())
        except Exception as e:                      # noqa: BLE001
            logger.error("[PriceWS] поток упал: %s", e)
        finally:
            loop.close()

    threading.Thread(target=_run, name="PriceWS", daemon=True).start()
    logger.info("[PriceWS] поток запущен (вне торгового loop)")
    return feed
