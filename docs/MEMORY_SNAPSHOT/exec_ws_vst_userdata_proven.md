---
name: exec_ws_vst_userdata_proven
description: VST private user-data WS работает (listenKey+WS подтверждено) — фундамент фикс рассинхрона БД↔биржа
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# 🔌 VST private user-data WS — PATH ДОКАЗАН (12.06.2026)

> 🎯 РЕШЕНО 14.06 — КОРЕНЬ был НЕВЕРНЫЙ VST WS-ДОМЕН (фикс `user_data_ws.py`).
> **Баг:** для VST код слушал PROD-домен `wss://open-api-swap.bingx.com/swap-market` с VST-listenKey → только SNAPSHOT+ping, **0 order events** (executions VST идут на ДРУГОЙ домен). docs-v3 (юзер прислал): VST WS = **`wss://vst-open-api-ws.bingx.com/swap-market?listenKey=`**, PROD/LIVE = `open-api-swap.bingx.com`. listenKey REST = `open-api-vst.bingx.com` (был верный).
> **Эмпирич. подтв. (diag_exec_ws_endpoints.py на VST-домене, 7мин):** acc1 ACCOUNT_UPDATE=4 (m=ORDER, P[] позиции) + ORDER(o)=8 (`ORDER_TRADE_UPDATE`/`TRADE_UPDATE`, `o.i`=orderId, `o.X`=FILLED, `o.s`, `o.ps`, `o.o`=MARKET/STOP/TAKE_PROFIT_MARKET). acc2 ORDER(o)=2. **events ИДУТ!**
> **Парсер был ВЕРНЫЙ** (`exec_ws_integration` ждёт `msg.o` — ровно формат TRADE_UPDATE). subscribe НЕ нужен (only listenKey).
> **Фикс:** `VST_WS`/`LIVE_WS` по `is_vst` (`user_data_ws.py:37-38,59,164`). NEXT: рестарт → проверить [EXEC-WS] orders>0 в проде → включить write_exch_id (2a, дедуп с REST) → дореализовать 2b sync_close (ACCOUNT_UPDATE pa=0). «714 событий 12.06» = был SNAPSHOT burst (не executions) — иллюзия от PROD-домена.


Корень ВСЕХ рассинхронов БД↔биржа (orphan, drift, zombie, `exchange_order_id=None` баг-семья, фантомные SIM-only, «220 OPEN» иллюзия): всё на **REST-polling** (`sync_positions` 60с — отстаёт, плодит фантомы). Решение — **private user-data WebSocket** (real-time push).

**Тест `scripts/test_vst_listenkey.py` + `catch_ws_event.py` (12.06) — РАБОТАЕТ, живые события пойманы:**
1. ✅ listenKey: `POST https://open-api-vst.bingx.com/openApi/user/auth/userDataStream` header `X-BX-APIKEY` (БЕЗ подписи) → HTTP200 `{listenKey}`
2. ✅ WS: **`wss://open-api-swap.bingx.com/swap-market?listenKey=<vst_key>`** (🔴 SWAP endpoint, НЕ `/market` spot — это был корень «0 событий + idle close»). Стабильно: 714 событий/120с, **0 reconnect**, Ping/Pong (`Pong` на `Ping`) работает.

**Формат событий (для интеграции Этап 2):**
- `ORDER_TRADE_UPDATE` / `TRADE_UPDATE`: `o.i`=**orderId** (=exch_id!), `o.s`=symbol, `o.S`=BUY/SELL, `o.o`=MARKET/STOP_MARKET/TAKE_PROFIT_MARKET, `o.X`=FILLED/CANCELED, `o.ps`=LONG/SHORT, `o.z`=filled qty, `o.ap`=avg price, `o.rp`=realized profit, `o.pi`=positionId
- `ACCOUNT_UPDATE`: `a.B[]`=балансы (`wb`=wallet balance), `a.P[]`=позиции (`s`,`pa`=position amount [**pa=0 → закрыта** → sync БД], `ps`,`ep`=entry, `up`=unrealized)
- `SNAPSHOT` при connect: leverage config всех символов (`ac.s/l/S/mt`)

**Ключевое:**
- ccxt.pro имеет `watchOrders/watchBalance/watchMyTrades`=True, но **VST sandbox user-WS НЕ настроен** в ccxt (`NotSupported: no sandbox URL for user endpoints`) → нужен **КАСТОМНЫЙ WS** (aiohttp, не ccxt).
- WS-домен ОБЩИЙ (`open-api-ws.bingx.com`), VST-контекст несёт сам listenKey (сгенерён через VST REST).
- События: `ACCOUNT_UPDATE` (баланс a/wb/bc), order `executionReport` (s/X/**i=orderId**/l/z). Сообщения **gzip**-сжаты, на «Ping»→слать «Pong».
- **Нагрузка: 1 соединение/аккаунт (НЕ per-pair)** → scan_loop НЕ затронут (vs market WS [[ws_feed]] плато 750s при 240 парах). Юзер опасался перегрузки — снято.

**Эффект (лечит корень, не симптомы):** orderId push при открытии → надёжная запись exch_id (баг-семья уходит); position-close push → мгновенный sync (orphan/drift/zombie уходят); balance push → real-time pre-check.

**🔑 LIVE доступ (12.06):** user-data WS / listenKey доступен ТОЛЬКО на **ОСНОВНОМ** (master) аккаунте. **Суб-аккаунт ключ → 404** (`BINGX_API_KEY` 2zDHkp = LIVE-суб, listenKey 404 на всех путях/с подписью). **Основной ключ `BINGX_VST_API_KEY` (5G6nUxnT) работает для VST И LIVE** (open-api.bingx.com listenKey HTTP200, WS connected, 715 SNAPSHOT). Один основной ключ покрывает оба режима. ⚠️ В `exec_ws_integration.start_exec_ws` LIVE-ветка берёт `BINGX_API_KEY` (суб!) → надо брать основной для LIVE. Order-поток на LIVE НЕ проверен (бот на VST → LIVE тих). Master listenKey обычно покрывает суб-аккаунты (проверить).

**= Execution Sphere (Сфера 14, ARCH-96 FROZEN) разморозка.** Реализация: listenKey lifecycle (keepalive PUT ~30мин + reconnect) + интеграция register(exch_id)/position_sync. TASKS: **EXEC-WS**. Связь: [[feedback_read_bingx_docs]] (docs первыми — сработало).
