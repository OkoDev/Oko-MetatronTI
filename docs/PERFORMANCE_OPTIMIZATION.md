# ⚡ Оптимизация производительности — 526 пар

> DS (DeepCode) · 12.06.2026 · Диагноз на основе логов и кода

## ДИАГНОЗ

```
Market-data (526 пар × OHLCV × 5 TF) → 3 прокси IP ✅ НЕ банится
Торговля/sync (direct IP)              → 100410 бан 298с 🔴
EventLoop lag                           → 0.609s
```

**Корень:** `get_open_orders(symbol)` — per-symbol REST, 10s TTL кэш.
При 200+ OPEN сделок на 100+ символах → ~10 прямых вызовов/сек на direct IP → rate-limit.

## 🔴 КРИТИЧНЫЕ (быстрый эффект, низкий риск)

### 1. Глобальный `get_open_orders` вместо per-symbol

**Сейчас:** `_get_open_orders_cached(symbol)` → REST call на каждый символ.
**BingX API позволяет:** `GET /swap/v2/trade/openOrders` **БЕЗ symbol** → возвращает ВСЕ открытые ордера одним вызовом.

```python
# Было: 100+ вызовов за цикл
for symbol in symbols_with_open_trades:
    orders = await self._get_open_orders_cached(symbol)

# Стало: 1 вызов за цикл
all_orders = await client.get_open_orders()  # без symbol
# Разложить по symbol → self._open_orders_cache[symbol]
```

**Эффект:** -99% прямых REST-вызовов (100 → 1). Бан 100410 уходит.

**Сложность:** Низкая. 1 новый метод + замена в 3 callsites.

### 2. Увеличить TTL кэша позиций

**Сейчас:** 15s TTL → `get_positions()` каждые 15с.
**BingX позиции не меняются每秒.** Безопасно увеличить до 60s.

```python
self._positions_ttl = 60  # было 15
```

**Эффект:** -75% вызовов (4/мин → 1/мин).

### 3. Увеличить TTL баланса

**Сейчас:** 30s TTL → `get_balance()` каждые 30с.
**Безопасно:** 120s (баланс меняется только при закрытии/открытии сделки).

```python
self._balance_ttl = 120  # было 30
```

**Эффект:** -75% вызовов.

---

## 🟠 ВАЖНЫЕ (средний эффект, проверить)

### 4. Троттлинг всех direct-вызовов

Добавить глобальный rate-limiter на direct IP: **макс 1 вызов/сек**.

```python
class DirectRateLimiter:
    def __init__(self, max_rps=1.0):
        self._last_call = 0
        self._min_interval = 1.0 / max_rps
    
    async def wait(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()
```

Применить ко ВСЕМ методам `bingx_client`, которые идут на direct IP (не через прокси).

### 5. Сниппет-баланс вместо REST

При закрытии сделки бот УЖЕ знает новый баланс (entry - exit = PnL). Можно вычислять без REST:

```python
estimated_balance = last_known_balance + closed_trade_pnl
# Раз в 5 минут — сверка через REST
```

### 6. EventLoop: разнести market-data и trading

**Сейчас:** OHLCV-фетчи (526 пар × 5 TF = 2630 запросов) в том же event loop что и торговля.
**Решение:** Выделить OHLCV-фетчи в отдельный ThreadPool или asyncio.TaskGroup с приоритетом.

```python
# OHLCV в фоне, не блокирует trading
async with asyncio.TaskGroup() as tg:
    tg.create_task(fetch_all_ohlcv())  # market-data
    tg.create_task(check_open_loop())  # trading
```

---

## 🟡 НИЗКИЙ ПРИОРИТЕТ

### 7. WebSocket вместо REST для market-data

BingX WS отдаёт OHLCV в реальном времени. Убрать 2630 REST-запросов за цикл.
**Сложность:** Высокая (переработка market-data слоя).

### 8. Reduce pairs: dynamic watchlist

526 пар — много мёртвых. Оставить топ-200 по объёму/волатильности.

---

## 📊 ПЛАН ВНЕДРЕНИЯ (порядок)

| # | Что | Эффект | Сложность | Кто | Статус |
|---|---|---|---|---|---|
| 1 | Глобальный get_open_orders | -99% вызовов | Низкая | Claude | ✅ 13.06 |
| 2 | TTL позиций 15→45s | -67% | 1 строка | Claude | ✅ 13.06 |
| 3 | TTL баланса 30→120s | -75% | 1 строка | Claude | ✅ 13.06 |
| 4 | Rate-limiter direct IP | защита от будущих банов | Средняя | Claude | ⬜ резерв |
| 5 | EventLoop split | убрать lag 0.6s | Средняя | Claude | ⬜ |

> **После #1-3 direct IP должен перестать баниться.** Если нет → #4. #5 для лага.

---

## ✅ ВНЕДРЕНО 13.06.2026 (Даат)

**Замер ДО (аудит логов 13.06):** 47 биржевых OPEN сделок (acc1=20, acc2=26, multiacct ON).
`repair_missing_sl` + `repair_missing_tp` каждые 60с × 47 = ~94 per-symbol `get_open_orders`
+ `position_sync` filled_orders → **~150 direct REST/мин**. Баны 100410: 4-26/час.

**#1 — `core/exchange/order_manager.py`:**
- Новый `_refresh_all_open_orders()` — per-account `get_open_orders()` БЕЗ symbol → раскладка
  по `_oo_cache[symbol]` через `from_bingx_symbol`. Коллизий символ+side между акк = 0 (проверено).
- `_get_open_orders_cached()`: при `_oo_global` и cache-miss → ОДИН глобальный refresh, затем кэш.
  Маркер `_oo_all_ts`: снимок свежий + символа нет → `[]` без запроса. `force=True` → per-symbol (точечно).
- `_invalidate_open_orders()`: сбрасывает `_oo_all_ts=0` (иначе stale после place/cancel).
- Эффект: ~94 → **2 вызова/цикл** (по аккаунту). За флагом `trading.open_orders_global: true`.

**#2/#3 — `config.yaml` (секция trading):**
- `positions_cache_ttl_sec: 45` (было дефолт 15). НЕ 60 — чтобы не совпасть с циклом 60с.
- `balance_cache_ttl_sec: 120` (было дефолт 30).

**Откат:** `open_orders_global: false`, ttl → 15/30. Все за config, рестарт не трогает код.
**Наблюдать после рестарта:** лог `[OrderManager] ... global=True`, падение банов 100410, отсутствие
дублей SL (`найдено N SL-ордеров` — не должно расти).

---

*Документ: живой. Обновлять по мере внедрения.*
