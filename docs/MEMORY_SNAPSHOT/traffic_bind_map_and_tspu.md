---
name: traffic_bind_map_and_tspu
description: "🌐 05.10 КАРТА ТРАФИКА: мимо VPN уведены свечи, цена, REST market-data (ccxt+прокси), лента BingX, ликвидации Bybit. 🔴 Binance НЕЛЬЗЯ (ТСПУ режет — проверено ценой: handshake timeout). Торговля можно, но отложено: whitelist по IP НЕ включён (проверено read-only балансом)"
metadata:
  node_type: memory
  type: project
  originSessionId: ea98197f-5cfa-4b48-ab76-1b2fcebf5d0d
  modified: 2026-10-05T01:48:53.756Z
---

**Приём один на все каналы:** `core/infra/net_bind.py` — `aiohttp_connector()` для WS/aiohttp,
`install_urllib_bind()` для urllib (source_address у HTTPConnection), `local_ip_by_prefix` для ccxt.
Префикс один на проект: `market_ws.bind_ip_prefix: "192.168.1."`.

**КТО ГДЕ (05.10):**

| канал | маршрут | как сделано |
|---|---|---|
| свечи `MarketWS-v2` | **мимо VPN** | `bind_ip_prefix` (29.09: VPN 33 → 12 ГБ/сут) |
| цена `PriceWS` | **мимо VPN** | свой клиент, N21 |
| REST market-data (ccxt + 3 прокси) | **мимо VPN** | `ApiEngine._ensure_bound_session()`, флаг `performance.rest_bind_ip_prefix`; звать ДО `load_markets` — после ccxt уже создал сессию |
| лента `orderflow-ws` (BingX) | **мимо VPN** | `aiohttp_connector()` |
| ликвидации `liq-ws` (Bybit) | **мимо VPN** | то же |
| `oi-fast`, `btc-flows` | 🔴 **В ТУННЕЛЕ** | ходят на `fapi.binance.com` |
| `EXEC-WS`, `BingXClient` (торговля) | в туннеле | можно увести, отложено — бэклог N23 |

🔴 **BINANCE МИМО VPN НЕЛЬЗЯ** — ТСПУ режет. Я включил bind не проверив хосты и сразу получил
`<urlopen error _ssl.c:993: handshake operation timed out>`. Правило было записано ещё 29.09
([[network_vpn_routing_happ]]), я его знал и всё равно наступил. **Перед bind — проверять ХОСТЫ:**
`grep -oE "https?://[a-z0-9.-]+" файл`.

🔎 **WHITELIST ПО IP НЕ ВКЛЮЧЁН** (Егор усомнился, проверка подтвердила): read-only баланс рабочим
ключом VST прошёл ОДИНАКОВО через туннель и мимо (`scratchpad/check_ip_whitelist.py`).
Правило `proxy_pool.py:8` «чужой IP = бан ключа» на текущих ключах не воспроизводится — оставлено
как верное на случай включения whitelist. Через ПРОКСИ торговлю не пускаем в любом случае.

🔴 **Боевой ключ `BINGX_API_KEY` не аутентифицируется**: `100413 Incorrect apiKey` одинаково на обоих
маршрутах (не про IP). Бот на VST, поэтому не мешает, но переключение на LIVE упрётся — бэклог N24.

**Мерить эффект:** только суточным логом `scripts/traffic_log.py` (pm2 `traffic-log`), окна с прогревом
исключаются автоматически. Окна в минуты врали трижды за сутки — [[price_ws_own_client_n21]].
