---
name: preflight-exchange-task
description: "Pre-flight чек-лист для задач касающихся биржи (BingX API, ccxt, VST/LIVE, order types, position management)"
metadata: 
  node_type: memory
  type: preflight
  triggers: 
    - BingX
    - ccxt
    - order type / stopPrice / positionSide
    - VST / LIVE поведение биржи
    - core/exchange/*
    - placeOrder / cancelOrder / fetchPosition
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# Pre-flight: задача с биржей (BingX)

> Read **прежде чем** трогать exchange-код или диагностировать поведение биржи.

## 1. Главный закон

→ [[feedback_read_bingx_docs]]

**ДО** grep кода или гипотез — открыть/запросить официальные docs BingX:
- Swap v2 API: `https://bingx-api.github.io/docs/`
- Если docs недоступны — попросить пользователя выдержку
- НЕ строить гипотезы "биржа сломана / не поддерживает X" без docs

**Исторический урок (19.04.2026):** час потрачен на ложную гипотезу "BingX не сохраняет STOP-LIMIT" — реальный баг был в **нашем** `update_sl` фильтре. Сначала docs, потом наш код, потом обвинение биржи.

## 2. Где живёт exchange-код

- `core/exchange/order_manager.py` — placeOrder + bracket
- `core/exchange/tsl_updater.py` — обновление SL ордеров
- `core/exchange/position_sync.py` — state reconciliation
- `core/exchange/exchange_client.py` — ccxt wrapper

## 3. Известные особенности BingX (verified)

→ [[obsidian/Reference/BingX-PlaceOrder-Response]]

- `placeOrder` response **НЕ возвращает** TP/SL orderId — только основной orderId
- TP/SL orderIds получать через `fetch_open_orders(symbol)` через 2-3 сек после placeOrder
- TP типы: `TAKE_PROFIT` / `TAKE_PROFIT_MARKET`
- SL типы: `STOP` / `STOP_MARKET`
- `workingType: "MARK_PRICE"` — стандарт для bracket orders
- VST = виртуальная среда, но с **реальными ценами и исполнением** — нет нужды в shadow поверх неё (D-028)

## 4. VST vs LIVE

- VST (виртуальные деньги): bot работает в `bingx_vst` режиме (config.yaml)
- LIVE: capital ramp 10→20→30→50→100% (см. `docs/MIGRATION_ARCH104.md`)
- Tests / observer: на VST с production execution
- Kill-switches: 3 losing days OR rolling-7d Sharpe < -1 → auto-shadow

## 5. ccxt enableRateLimit

→ `memory/MEMORY.md` historical: ccxt `enableRateLimit: False` дал 44-186× ускорение (08.03.2026 fix). НЕ возвращать `True` без понимания почему.

## 6. Ошибки exchange

- Парсить `error['code']` (число), не текст
- `code=100400` family — параметры (наши)
- `code=80014` — недостаточно маржи
- При неизвестном code — лог `ERROR` + не повторять call в цикле (CircuitBreaker)

## 7. State reconciliation

- При рестарте бота: `core/exchange/position_sync.py::sync_positions()` приводит в порядок open positions
- Idempotency keys: `clientOrderId` = `f"{trade_id}_{purpose}"` (purpose=entry/tp/sl)
- Не делать `cancel + place` без проверки текущего состояния

## 8. Не сломать prod

- Любая правка `order_manager.py` / `tsl_updater.py` → тест на VST минимум 24ч
- Pre-commit: `python -c "import core.exchange.order_manager"` чтобы убедиться импорты не сломаны
- Логи перед/после реалистичного теста — изменилось ли поведение

## Связано
- [[feedback_read_bingx_docs]] — главное правило
- [[obsidian/Reference/BingX-PlaceOrder-Response]]
- [[feedback_verify_metric_semantics]] — проверь семантику биржевых полей
- [[feedback_no_fabricated_apis]] — не выдумывай методы ccxt/order_manager
