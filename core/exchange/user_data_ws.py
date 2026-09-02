"""
UserDataStream — кастомный private user-data WebSocket для BingX (EXEC-WS, Execution Sphere).

Real-time push событий аккаунта вместо REST-polling (sync 60с отстаёт → orphan/drift/exch_id=None):
  - order updates (orderId, статус) → надёжная запись exchange_order_id
  - account/position updates → мгновенный sync БД↔биржа

Path доказан 12.06 (scripts/test_vst_listenkey.py): listenKey via VST REST + WS общий домен.
ccxt sandbox НЕ поддерживает VST user-stream → этот кастомный клиент (aiohttp).

НАГРУЗКА: 1 соединение на аккаунт (НЕ per-pair) → scan_loop НЕ затронут.

ЭТАП 1 (SHADOW): listenKey + WS loop + reconnect + keepalive + лог событий + on_event callback.
ЭТАП 2 (позже): on_event → запись exch_id / position_sync (через callback, код тут не меняется).
"""
from __future__ import annotations

import asyncio
import gzip
import io
import json
import logging
import time
from typing import Awaitable, Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)

VST_REST = "https://open-api-vst.bingx.com"
LIVE_REST = "https://open-api.bingx.com"
# 🎯 SWAP user-data WS — РАЗНЫЕ домены VST/PROD (docs-v3, эмпирич. подтв. 14.06):
#   VST  → vst-open-api-ws.bingx.com (order/account events ИДУТ)
#   PROD → open-api-swap.bingx.com   (LIVE)
# Баг до 14.06: для VST слушали PROD-домен с VST-listenKey → только SNAPSHOT+ping,
# 0 order events (executions идут на vst-домен). Корень orders=0 / "EXEC-WS тупик".
VST_WS  = "wss://vst-open-api-ws.bingx.com/swap-market?listenKey="
LIVE_WS = "wss://open-api-swap.bingx.com/swap-market?listenKey="

_KEEPALIVE_SEC = 1800.0   # PUT listenKey каждые 30 мин (BingX TTL ~60 мин)
_RECONNECT_SEC = 5.0
_LISTENKEY_RETRY_SEC = 30.0


class UserDataStream:
    """Один private user-data WS на аккаунт. on_event(event_type:str, msg:dict) — async callback."""

    def __init__(
        self,
        api_key: str,
        secret: str = "",
        is_vst: bool = True,
        on_event: Optional[Callable[[str, dict], Awaitable[None]]] = None,
        account_tag: str = "acc1",
    ):
        self._key = api_key
        self._secret = secret
        self._rest = VST_REST if is_vst else LIVE_REST
        self._ws_base = VST_WS if is_vst else LIVE_WS
        self._on_event = on_event
        self._tag = account_tag
        self._listen_key: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._running = False
        self.stats = {"events": 0, "orders": 0, "account": 0, "reconnects": 0, "pings": 0}

    # ── listenKey lifecycle ──────────────────────────────────────────────
    async def _get_listen_key(self) -> Optional[str]:
        url = f"{self._rest}/openApi/user/auth/userDataStream"
        async with self._session.post(
            url, headers={"X-BX-APIKEY": self._key},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            data = await r.json(content_type=None)
            return data.get("listenKey") if isinstance(data, dict) else None

    async def _keepalive(self) -> None:
        if not self._listen_key:
            return
        url = f"{self._rest}/openApi/user/auth/userDataStream?listenKey={self._listen_key}"
        try:
            async with self._session.put(
                url, headers={"X-BX-APIKEY": self._key},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                txt = await r.text()
                logger.info("[EXEC-WS][%s] keepalive HTTP%s %s", self._tag, r.status, txt[:80])
        except Exception as e:
            logger.warning("[EXEC-WS][%s] keepalive error: %s", self._tag, e)

    async def _keepalive_loop(self) -> None:
        while self._running:
            await asyncio.sleep(_KEEPALIVE_SEC)
            await self._keepalive()

    async def _stats_loop(self) -> None:
        """Диагностика: периодический лог счётчиков — видно, растут ли orders/account (поток жив)."""
        while self._running:
            await asyncio.sleep(60)
            logger.info("[EXEC-WS][%s] STATS: %s", self._tag, self.stats)

    # ── декод + обработка ────────────────────────────────────────────────
    @staticmethod
    def _decode(data) -> str:
        if isinstance(data, (bytes, bytearray)):
            try:
                return gzip.GzipFile(fileobj=io.BytesIO(data)).read().decode("utf-8", "ignore")
            except Exception:
                return bytes(data).decode("utf-8", "ignore")
        return str(data)

    async def _handle(self, raw) -> None:
        decoded = self._decode(raw)
        logger.debug("[EXEC-WS][%s] RAW: %r", self._tag, decoded[:200])
        # BingX heartbeat: сервер шлёт "Ping" → отвечаем "Pong"
        if decoded == "Ping" or '"ping"' in decoded.lower():
            self.stats["pings"] += 1
            try:
                await self._ws.send_str("Pong")
            except Exception:
                pass
            return
        try:
            msg = json.loads(decoded)
        except Exception:
            return
        if not isinstance(msg, dict):
            return
        etype = str(msg.get("e") or msg.get("dataType") or msg.get("E") or "").strip()
        self.stats["events"] += 1
        up = etype.upper()
        if "ORDER" in up or msg.get("o") is not None:
            self.stats["orders"] += 1
            logger.info("[EXEC-WS][%s][ORDER] %s", self._tag, decoded[:300])
        elif "ACCOUNT" in up or msg.get("a") is not None:
            self.stats["account"] += 1
            logger.info("[EXEC-WS][%s][ACCOUNT] %s", self._tag, decoded[:300])
        else:
            logger.info("[EXEC-WS][%s][evt] %s", self._tag, decoded[:200])
        # ЭТАП 2 hook (сейчас обычно None → SHADOW)
        if self._on_event is not None:
            try:
                await self._on_event(etype, msg)
            except Exception as ce:
                logger.warning("[EXEC-WS][%s] on_event error: %s", self._tag, ce)

    # ── главный цикл ─────────────────────────────────────────────────────
    async def run(self) -> None:
        self._running = True
        self._session = aiohttp.ClientSession()
        ka_task = asyncio.create_task(self._keepalive_loop())
        st_task = asyncio.create_task(self._stats_loop())
        logger.info("[EXEC-WS][%s] started (rest=%s)", self._tag, self._rest)
        try:
            while self._running:
                try:
                    self._listen_key = await self._get_listen_key()
                    if not self._listen_key:
                        logger.warning("[EXEC-WS][%s] нет listenKey — retry %.0fs", self._tag, _LISTENKEY_RETRY_SEC)
                        await asyncio.sleep(_LISTENKEY_RETRY_SEC)
                        continue
                    async with self._session.ws_connect(
                        self._ws_base + self._listen_key,
                        timeout=aiohttp.ClientTimeout(total=20),
                        # 02.09.2026: было heartbeat=30 → 95 разрывов за 6 часов.
                        # Причина доказана исходником aiohttp 3.9.3: при неполученном
                        # pong _pong_not_received() бросает asyncio.TimeoutError() БЕЗ
                        # аргументов — отсюда 91 запись «loop error:  — reconnect»
                        # с пустым текстом. Наш канал идёт через перегруженный VPN,
                        # где latency скачет до 14 с, и потеря одного pong за 30 с —
                        # обычное дело. 60 с даёт запас, не теряя способности заметить
                        # реально мёртвое соединение (listenKey живёт 60 мин).
                        # 🔴 Откат: вернуть 30, если разрывы пойдут по иной причине —
                        # теперь она видна в логе, тип исключения печатается.
                        heartbeat=60,
                    ) as ws:
                        self._ws = ws
                        logger.info("[EXEC-WS][%s] connected (listenKey %s...)", self._tag, self._listen_key[:12])
                        async for m in ws:
                            if m.type in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                                await self._handle(m.data)
                            elif m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                logger.warning("[EXEC-WS][%s] WS закрыт: %s", self._tag, m.type)
                                break
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    # 02.09.2026: печатался только str(e), а у сетевых исключений
                    # (ServerTimeoutError, ClientConnectionError, ConnectionResetError)
                    # сообщение пустое → в логе 91 запись вида «loop error:  — reconnect»
                    # без единого признака причины. Тип обязателен: без него разрывы
                    # торгового WS не диагностируются, а он несёт ордера и статус счёта.
                    logger.warning(
                        "[EXEC-WS][%s] loop error: %s: %s — reconnect %.0fs",
                        self._tag, type(e).__name__, (str(e) or "«без сообщения»"),
                        _RECONNECT_SEC,
                    )
                if self._running:
                    self.stats["reconnects"] += 1
                    await asyncio.sleep(_RECONNECT_SEC)
        finally:
            ka_task.cancel()
            st_task.cancel()
            if self._session and not self._session.closed:
                await self._session.close()
            logger.info("[EXEC-WS][%s] stopped (stats=%s)", self._tag, self.stats)

    async def stop(self) -> None:
        self._running = False
        try:
            if self._ws is not None and not self._ws.closed:
                await self._ws.close()
        except Exception:
            pass
