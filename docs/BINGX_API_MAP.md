# 🗺️ BingX Perpetual Swap API — Полная карта команд

> Собрано из: `core/exchange/bingx_client.py`, `core/exchange/order_manager.py`, `core/exchange/position_parser.py`
> API: BingX Swap V2 (`/openApi/swap/v2/`). Режим: **Hedge Mode** (positionSide=LONG|SHORT).
> Дата: 12.06.2026. Собирал: DS (DeepCode).

---

## 1. БАЗОВАЯ АРХИТЕКТУРА

```
Base URL:  https://open-api.bingx.com  (или TRADE_URL из config)
Auth:     X-BX-APIKEY header + HMAC-SHA256 signature
Signing:  timestamp + params (sorted) → HMAC(secret)
```

### Режимы позиции (Margin Mode):

| Режим | positionSide | Одновременно LONG+SHORT | Используется |
|---|---|---|---|
| **Hedge Mode** | LONG / SHORT (обязателен) | ✅ Да | ✅ Бот |
| One-Way Mode | BOTH / пусто | ❌ Нет | ❌ |

> **Hedge Mode — стандарт бота (27.05.2026 fix).** positionSide передаётся во ВСЕХ запросах (открытие, SL/TP, закрытие). Без positionSide → LONG-сигнал блокировался.

---

## 2. ПОЛНЫЙ СПИСОК REST ЭНДПОИНТОВ

### 2.1 Публичные (без подписи)

| Метод | Путь | Назначение | Параметры |
|---|---|---|---|
| GET | `/swap/v2/server/time` | Серверное время (ms) | — |
| GET | `/swap/v2/quote/contracts` | Спецификации контрактов (precision, minQty) | — |

### 2.2 Приватные — Аккаунт

| Метод | Путь | Назначение | Параметры |
|---|---|---|---|
| GET | `/swap/v2/user/balance` | Баланс USDT | — |
| GET | `/swap/v2/user/positions` | Открытые позиции | — |

### 2.3 Приватные — Ордера

| Метод | Путь | Назначение | Ключевые параметры |
|---|---|---|---|
| **POST** | `/swap/v2/trade/order` | **Универсальный: открытие/SL/TP/закрытие** | `symbol, side, positionSide, type, quantity` |
| DELETE | `/swap/v2/trade/order` | Отмена ордера | `symbol, orderId` |
| GET | `/swap/v2/trade/openOrders` | Открытые ордера | `symbol` (опц.) |
| GET | `/swap/v2/trade/allOrders` | История ордеров | `symbol, limit` |
| POST | `/swap/v2/trade/leverage` | Установка плеча | `symbol, side, leverage` |
| POST | `/swap/v2/trade/closeAllPositions` | One-click закрытие | `symbol` |

---

## 3. ЖИЗНЕННЫЙ ЦИКЛ СДЕЛКИ (Hedge Mode)

### 3.1 ОТКРЫТИЕ ПОЗИЦИИ (Bracket Order)

```python
POST /swap/v2/trade/order
{
  "symbol":       "ADA-USDT",
  "side":         "BUY",           # BUY=Long, SELL=Short
  "positionSide": "LONG",          # ОБЯЗАТЕЛЕН в hedge
  "type":         "MARKET",
  "quantity":     "63",
  "stopLoss":     '{"type":"STOP_MARKET","stopPrice":0.168,"price":0,"workingType":"MARK_PRICE"}',
  "takeProfit":   '{"type":"TAKE_PROFIT_MARKET","stopPrice":0.160,"price":0,"workingType":"MARK_PRICE"}',
}
```

**Особенность (dual-signing):** `stopLoss` и `takeProfit` — JSON-объекты. HMAC подписывает RAW строку (без URL-encode), URL получает URL-encoded версию. `post_raw()` разделяет.

**Типы SL:**
- `STOP_MARKET` — по рынку (стандарт)
- `STOP` (Stop-Limit) — с `price` + `sl_limit_buffer_pct` (DEV-175, рекомендуется)

### 3.2 ЗАКРЫТИЕ ПОЗИЦИИ

```python
POST /swap/v2/trade/order
{
  "symbol":       "ADA-USDT",
  "side":         "SELL",          # Закрытие LONG → SELL; SHORT → BUY
  "positionSide": "LONG",
  "type":         "MARKET",
  "quantity":     "63",
  "reduceOnly":   "true",          # Закрытие, не открытие встречной
}
```

**⚠️ Hedge Mode баги (OPS-06):**
1. **109400 + "ReduceOnly ... Hedge mode"** → убираем `reduceOnly`, повтор
2. **101205 "No position to close"** → убираем `reduceOnly`, повтор
3. **Всё ещё fail → one-click fallback** (`closeAllPositions`)

> **Стратегия закрытия (три попытки):**
> 1. `reduceOnly=true` MARKET
> 2. Без `reduceOnly` MARKET (hedge fix)
> 3. `closeAllPositions` (one-click, закрывает ВСЮ позицию по символу)

### 3.3 МОДИФИКАЦИЯ SL (TSL)

```python
# Шаг 1: Отменить старый SL
DELETE /swap/v2/trade/order  {"symbol": "ADA-USDT", "orderId": "2061..."}

# Шаг 2: Поставить новый SL
POST /swap/v2/trade/order
{
  "symbol":       "ADA-USDT",
  "side":         "SELL",          # Закрытие LONG
  "positionSide": "LONG",
  "type":         "STOP_MARKET",   # или STOP (Limit)
  "quantity":     "63",
  "stopPrice":    "0.171",
  "workingType":  "MARK_PRICE",
  "positionId":   "..."            # ОБЯЗАТЕЛЕН для Separate Isolated
}
```

### 3.4 МОДИФИКАЦИЯ TP

```python
# Аналогично SL, но type="TAKE_PROFIT_MARKET"
POST /swap/v2/trade/order
{
  "symbol":       "ADA-USDT",
  "side":         "SELL",
  "positionSide": "LONG",
  "type":         "TAKE_PROFIT_MARKET",
  "quantity":     "63",
  "stopPrice":    "0.155",
  "workingType":  "MARK_PRICE",
}
```

### 3.5 ПОЛУЧЕНИЕ SL/TP ORDER ID

```python
# Получить ID SL-ордера для позиции
GET /swap/v2/trade/openOrders  {"symbol": "ADA-USDT"}
# → фильтровать по type="STOP_MARKET"/"STOP" + positionSide="LONG"

# Получить ID TP-ордера
# → фильтровать по type="TAKE_PROFIT_MARKET" + positionSide="LONG"
```

### 3.6 ONE-CLICK ЗАКРЫТИЕ (аварийное)

```python
POST /swap/v2/trade/closeAllPositions  {"symbol": "ADA-USDT"}
# Закрывает ВСЮ позицию по символу (LONG+SHORT если есть оба в hedge)
```

---

## 4. HEDGE MODE — КЛЮЧЕВЫЕ ПРАВИЛА

### 4.1 positionSide ВЕЗДЕ

| Операция | positionSide |
|---|---|
| Открытие LONG | `LONG` |
| Открытие SHORT | `SHORT` |
| Закрытие LONG | `LONG` |
| Закрытие SHORT | `SHORT` |
| SL для LONG | `LONG` |
| TP для LONG | `LONG` |

**27.05.2026 fix:** `order_manager.open_bracket()` — `pos_side = direction` (раньше было `BOTH` → LONG-сигнал блокировался).

### 4.2 Одновременные LONG + SHORT

В Hedge Mode можно держать ОБЕ позиции на одной паре одновременно. Ключ = `(symbol, positionSide)`.

```python
# position_parser.py: build_index() → dict[(symbol, "LONG"|"SHORT")]
# Бот различает их по positionSide, не по символу
```

### 4.3 reduceOnly и Hedge Mode

- `reduceOnly=true` + Hedge Mode → **109400 ошибка** при закрытии встречной стороны
- Решение: retry без `reduceOnly` (открывает встречную позицию, которая НЕТТИНГУЕТСЯ с существующей на бирже BingX)
- **Важно:** без `reduceOnly` бот открывает встречную позицию того же размера → netting закрывает обе. Это работает на BingX, но ТРЕБУЕТ иметь достаточный баланс для маржи встречной позиции

---

## 5. ПОЛУЧЕНИЕ ДАННЫХ

### 5.1 Позиции

```python
GET /swap/v2/user/positions
→ [{"symbol":"ADA-USDT","positionSide":"LONG","positionAmt":"63","entryPrice":"0.1654",
    "unrealizedProfit":"0.03","leverage":"5","liquidationPrice":"..."}]
```

**Важно в Hedge:** `positionAmt` всегда ≥ 0. Направление из `positionSide`, НЕ из знака.

### 5.2 Ордера

```python
GET /swap/v2/trade/openOrders  {"symbol": "ADA-USDT"}
→ {"data":{"orders":[
    {"orderId":"...","symbol":"ADA-USDT","type":"STOP_MARKET","side":"SELL",
     "positionSide":"LONG","stopPrice":"0.168","status":"NEW"}
]}}
```

### 5.3 Баланс

```python
GET /swap/v2/user/balance
→ {"data":{"balance":{"userId":"...","asset":"USDT","availableMargin":"48.02",
    "equity":"492.87","usedMargin":"444.57"}}}
```

**Rate-limit:** 100410 (бан за частые запросы), 109429 (timestamp-бан).

---

## 6. WEB SOCKET (User Data Stream) — ИСПРАВЛЕНО + EXEC-WS (12.06)

> 🔴 ИСПРАВЛЕНИЕ: endpoint был указан неверно (`/ws/user`). Боевая проверка 12.06 → правильный **swap-market**.

```
listenKey:  POST /openApi/user/auth/userDataStream  (header X-BX-APIKEY, БЕЗ подписи) → {listenKey}
            валиден 60 мин · продление PUT каждые 30 мин · удаление DELETE
WS:         wss://open-api-swap.bingx.com/swap-market?listenKey=<key>
            🔴 swap-market (НЕ /market — тот spot, даёт только SNAPSHOT + 0 order-событий)
🔑 listenKey ТОЛЬКО на ОСНОВНОМ (master) аккаунте. Суб-аккаунт ключ → 404.
   Основной ключ покрывает VST(open-api-vst) И LIVE(open-api).
```

**События (формат, боевой):**
| событие | поля |
|---|---|
| `ORDER_TRADE_UPDATE` / `TRADE_UPDATE` | `o.i`=orderId, `o.s`=symbol, `o.S`=side, `o.o`=type, `o.X`=status, `o.q/z`=qty, `o.ap`=avgPrice, `o.n`=**commission**, `o.rp`=**realized PnL**, `o.ps`=posSide, `o.pi`=positionId, `o.ro`=reduceOnly |
| `ACCOUNT_UPDATE` | `a.B[]`=балансы(`wb/cw/bc`), `a.P[]`=позиции(`pa`=amt[0=закрыта],`ep`,`up`=unreal,`cr`=realized,`ps`), `a.m`=ORDER/FUNDING_FEE |
| `SNAPSHOT` | при connect — leverage config (`ac.s/l/S/mt`) |
| `listenKeyExpired` | пересоздать listenKey |

**🔌 Обрывы связи (КРИТИЧНО для терминала):**
- BingX шлёт application **"Ping"** (текст) → клиент ОБЯЗАН ответить **"Pong"** (иначе разрыв ~60с)
- сообщения **gzip**-сжаты → декодировать (gzip.GzipFile)
- reconnect при CLOSED/error: пересоздать listenKey + reconnect
- keepalive PUT каждые 30 мин (TTL 60)
- ⚠️ order-поток на VST приходит **рвано** (пятнами) — на LIVE надёжнее (проверять)

**Реализация:** `core/exchange/user_data_ws.py` (UserDataStream: listenKey lifecycle + reconnect + ping/pong + gzip + stats) + `core/exchange/exec_ws_integration.py` (on_event → exch_id запись, за config-флагами `trading.exec_ws.*`). EXEC-WS = источник истины о реальных деньгах (realPnL/commission/funding) для честных метрик.

---

## 7. ТИПЫ ОРДЕРОВ (сводка)

| type | Назначение | Параметры |
|---|---|---|
| `MARKET` | Рыночное открытие/закрытие | `quantity, side, positionSide` |
| `STOP_MARKET` | SL по рынку | `stopPrice, quantity, workingType` |
| `STOP` | SL с лимитной ценой | `stopPrice, price, quantity` |
| `TAKE_PROFIT_MARKET` | TP по рынку | `stopPrice, quantity, workingType` |

---

## 8. ЧАСТЫЕ ОШИБКИ (КОДЫ)

| Код | Значение | Решение |
|---|---|---|
| **109400** | ReduceOnly + Hedge конфликт | Retry без reduceOnly |
| **101205** | No position to close | Retry без reduceOnly → one-click |
| **100410** | Rate-limit (слишком частые REST) | Бан на N сек |
| **109429** | Timestamp skew (часы не синхронизированы) | `sync_time()` |
| **0** | Успех | — |

---

## 9. POSITION MODE (Hedge ↔ One-Way) — управление режимом

> Дополнено 12.06 (Claude). НЕ путать с Margin Mode (isolated/cross). Это РАЗНЫЕ настройки.

```
Query:  GET  /openApi/swap/v1/positionSide/dual → {"data":{"dualSidePosition":"true"}}
Set:    POST /openApi/swap/v1/positionSide/dual   body dualSidePosition=true|false
        ⚠️ смена режима ТРЕБУЕТ закрыть ВСЕ позиции (иначе reject)
```

**ТЕКУЩИЙ режим аккаунта: HEDGE (`dualSidePosition:true`) + Separate Isolated (`isolated:true`).**

### Margin Mode (отдельно от position mode)
```
Set: POST /openApi/swap/v2/trade/marginType  {symbol, marginType: ISOLATED|CROSSED}
```
- **Separate Isolated** (`isolated:true`) → BingX ТРЕБУЕТ `positionId` для close/SL-ордеров (источник 109400 "positionId must")
- positionId берётся из `GET /swap/v2/user/positions` → `positionId` поле (кэшировать, обновлять при изменении)

---

## 10. HEDGE-ORPHAN — класс рассинхрона (корень + решение)

**Hedge-orphan:** биржа держит позицию (symbol, side), которой нет в БД OPEN, НО БД держит ДРУГУЮ сторону того же символа. Возникает ТОЛЬКО в hedge mode (две стороны на символ).

**Матрица закрытия hedge-orphan (боевой опыт 12.06, `scripts/close_hedge_orphans.py`):**
| ситуация | действие |
|---|---|
| БД-брат = **SIM-only** (не на бирже) | на бирже только orphan-сторона → **one-click** безопасен (закроет только её) |
| биржевой брат ЕСТЬ (реальный hedge, обе на бирже) | точечный close `side+positionSide+positionId` БЕЗ reduceOnly; если 101205 → НЕ one-click (закроет брата) |

**Очистка orphan-классов (скрипты):**
- `scripts/close_orphans.py` — чистые orphan (БД пусто по символу) + safety: пропуск если БД держит OPEN по символу (hedge-skip)
- `scripts/close_hedge_orphans.py` — hedge-orphan точечно (one-click для SIM-брата)
- D-070 (`position_sync._detect_orphans`) — детектит, не лечит

---

## 11. 🎯 РЕКОМЕНДАЦИИ для торгового терминала

1. **Hedge → One-Way** (стратегическое): для бота без hedge-стратегий one-way устраняет ВЕСЬ orphan-класс в корне (одна позиция на символ, чистый `reduceOnly` close, нет 101205). Смена: закрыть все позиции → `POST positionSide/dual false`. **Если hedge нужен** (одновременные long+short) — строго `positionId+positionSide` в каждом close, НИКОГДА reduceOnly.
2. **User-data WS (EXEC-WS) как источник истины** — orderId/realPnL/commission/funding/закрытия real-time. Решает рассинхрон БД↔биржа в корне (vs REST-polling отставание). На LIVE через master-ключ.
3. **Обрывы связи:** ping/pong + listenKey keepalive + reconnect (реализовано в UserDataStream). Для терминала — переподписка после reconnect, дедуп событий по orderId.
4. **positionId кэш** в Separate Isolated — обязателен для close/SL, обновлять при изменении позиций.
5. **closeAllPositions vs точечный** — one-click закрывает ВСЕ стороны символа (опасно при реальном hedge). Точечный нужен positionId.

**НЕ реализовано в bingx_client (для терминала):** `POST positionSide/dual` (set mode), `POST marginType` (set margin), `DELETE userDataStream` (listenKey).

---

*Собрано: DS 12.06.2026 (секции 1-8) + Claude 12.06.2026 (секции 6-исправл, 9-11: position mode, EXEC-WS, hedge-orphan, обрывы). Боевой опыт сессии 11-12.06.*
