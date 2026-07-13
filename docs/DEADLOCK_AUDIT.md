# Deadlock-аудит: БД-вызовы в торговом пути (шаг 2)

> DS · 13.06.2026 · Для PERF-LOOP-DRIFT шаг 2 (отдельный торговый loop)

## Методология

sqlite3 WAL-mode (`subscriptions.db`, `busy_timeout=10000`):
- **READERS не блокируют** — safe cross-loop
- **WRITERS: только ОДИН одновременно.** Второй ждёт `busy_timeout` (10s).
- Если торговый loop и main loop пишут одновременно → один ждёт 10s → deadlock-пауза на весь event loop.

## Найденные WRITE-точки

### 🔴 CRITICAL — блокируют оба loop на 10s

| # | Файл:строка | Что пишет | Частота |
|---|---|---|---|
| 1 | `tsl_updater.py:127,134,169,180,187,295,302,327` | `set_exchange_sl_order_id()` — 9 callsites | При каждом place/cancel SL |
| 2 | `tsl_updater.py:224,231,257` | `set_exchange_tp_order_id()` — 3 callsites | При каждом place/cancel TP |
| 3 | `position_sync.py:693-694` | `UPDATE simulated_trades SET exit_price=, status=` | Emergency close |
| 4 | `order_manager.py` → `_resolve_exit` → `close_trade` → `register_trade` | INSERT/UPDATE `simulated_trades` | При каждом закрытии позиции |

### 🟠 HIGH

| # | Файл:строка | Что пишет | Частота |
|---|---|---|---|
| 5 | `exec_ws_integration.py:86-91` | `UPDATE exchange_order_id=` | Каждый WS FILLED event |

### 🟡 MEDIUM

| # | Файл:строка | Что пишет | Частота |
|---|---|---|---|
| 6 | `order_manager.py:219` → `save_snapshot` → `core/db/balance_repo.py` | INSERT `balance_snapshots` | Каждые ~10 мин |
| 7 | `account_router.py:50,84` | INSERT/UPDATE `live_positions` | При синхронизации позиций |

### ✅ SAFE — только READ

| Файл | Что читает |
|---|---|
| `circuit_breaker.py:88-95` | SELECT simulated_trades |
| `gates/market_stress.py:43-44` | SELECT simulated_trades |
| `position_sync.py:625-627` | SELECT simulated_trades |

## Рекомендация

**Вынести ВСЕ DB-записи обратно в main loop через `asyncio.Queue`.** Торговый loop — только REST (place/cancel/get_positions). После успешного REST — кладёт событие в очередь. Main loop читает очередь → пишет БД.

```python
# Торговый loop (только REST)
result = await client.place_sl_order(...)
await db_write_queue.put({
    "op": "set_exchange_sl_order_id",
    "trade_id": trade_id,
    "sl_order_id": result["orderId"]
})

# Main loop (потребитель очереди)
while True:
    msg = await db_write_queue.get()
    if msg["op"] == "set_exchange_sl_order_id":
        trade_simulator.set_exchange_sl_order_id(msg["trade_id"], msg["sl_order_id"])
    ...
```

**Преимущества:**
- Zero deadlock (пишет только main loop)
- Торговый loop не ждёт БД (REST → ответ → очередь → следующий запрос)
- `_resolve_exit` / `close_trade` уже в main loop (вызывается через bus/event)
- `exec_ws_integration` уже в main loop (WebSocket колбэки)
