---
name: preflight-new-loop
description: "Pre-flight чек-лист перед интеграцией нового async loop в бот (как arch104_observer_loop, scan_loop, обсидиан-loop)"
metadata: 
  node_type: memory
  type: preflight
  triggers: 
    - новый async loop
    - добавляю scan/observer/watcher в бот
    - bot.loops/* интеграция
    - create_task в bot/core/bot.py
    - периодическая задача в боте
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# Pre-flight: новый async loop в боте

> Read **прежде чем** писать новый loop. Поводы прочтения: подсказка от пользователя про новый loop, упоминание `asyncio.create_task` в `bot/core/bot.py`, файл `bot/loops/*.py`.

## 1. Источник данных — пар, цен, контекста

| Что нужно | Откуда брать (verified 21.05.2026) |
|---|---|
| Список активных пар | `bot.monitored_pairs` (set, 241 пара) |
| OHLCV | `bot.data_collector.get_ohlcv(sym, tf, limit)` (async, кеш inside) |
| Текущий тикер | `bot.data_collector.fetch_ticker(sym)` (если нужен `last`) |
| SMC snapshot | `bot._last_smc_snap.get(sym)` (если включён smc_loop) |
| Pivot levels | `bot.pivot_cache.get(f"{sym}_{tf}")` (см. `feedback_no_fabricated_apis` — ключ с TF суффиксом!) |
| Regime | `bot.regime_classifier.last_regime(sym)` или из PairContextBus |
| EventBus publish | `bot.event_bus.publish(sym, event_type, priority, payload)` |

**❌ НЕ ИСКАТЬ:** `subscription_manager.get_active_subscriptions()` (нет такого, это TG-подписчики, не универс пар).

## 2. Производительность

- 241 пара × N TF × ~1s per fetch = легко уходит в минуты. Используй `asyncio.Semaphore(8-15)` + `gather`
- Целевое время цикла ≤ 0.5 × interval (запас для slowdown)
- Лог `WARNING` если цикл > 0.8 × interval
- Не дублируй fetch — `data_collector` имеет кеш, второй вызов в окне TTL бесплатен

## 3. Error handling

```python
while True:
    try:
        await asyncio.sleep(interval_seconds)
        # ... main work
    except asyncio.CancelledError:
        logger.info("[my_loop] cancelled")
        break
    except Exception as e:
        logger.exception("[my_loop] error: %s", e)
        await asyncio.sleep(60)  # cooldown перед retry
```

## 4. Wiring в `bot/core/bot.py`

- Где: метод `start()` или `monitor_market()` (для долгоживущих)
- Как: `asyncio.create_task(my_loop(self, interval_seconds=300))`
- Логировать spawn: `logger.info("[my_loop] task spawned")`
- Опционально: добавить в `self._tasks` для graceful cancel при shutdown

## 5. Конфиг

- Если loop имеет параметры — выноси в `config.yaml` секцию (`my_loop.interval_seconds`, `my_loop.enabled`)
- Дефолты в коде как fallback, читать через `bot.config.get("my_loop.interval_seconds", 300)`
- Не хардкодить интервалы и timeouts в коде

## 6. Observability

- Структурный лог в начале/конце цикла: `[my_loop] scanned=N hits=M in Xs (pairs=K)`
- Не логировать на каждой паре — спам логов
- Если loop пишет в БД — таблица с индексами по `ts, symbol`
- Если loop генерирует EventBus events — описать priority + dedup стратегию

## 7. Что НЕ делать

- ❌ Блокирующие операции (`time.sleep`, sync requests) — только `await asyncio.sleep` и async I/O
- ❌ Глобальный mutex на всю функцию — теряется параллелизм
- ❌ Запись в shared state без lock (если есть concurrent writes)
- ❌ Запуск через `Thread` или `Process` — у нас async-only

## Связано
- [[feedback_no_fabricated_apis]] — grep API перед вызовом
- [[feedback_fix_checklist]] — что проверить до/после
- Пример живого loop: `bot/loops/arch104_observer_loop.py`
- Пример wiring: `bot/core/bot.py::start()` → spawn observer task
