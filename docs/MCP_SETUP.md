# MCP-серверы для Oko MTF Bot

> Актуально на: 12.04.2026
> Сниппеты конфигурации и живые эндпоинты.

---

## 0. Куб Метатрона — /api/cube/* (CUBE-01, готово)

> **Нативный HTTP API Куба.** Работает без дополнительных зависимостей — только бот должен быть запущен.

```bash
# Состояние пары (все 12 сфер)
curl http://localhost:8000/api/cube/context/BTC_USDT

# Лог событий шины (последние 20)
curl "http://localhost:8000/api/cube/events?limit=20"

# Статистика обеих шин
curl http://localhost:8000/api/cube/stats

# Ручной триггер Full CALL
curl -X POST http://localhost:8000/api/cube/event \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTC/USDT", "event_type": "wt_confluence"}'

# Переобучить ML вручную
curl -X POST http://localhost:8000/api/cube/ml/train
```

**Whitelist событий для инжекции:**
`wt_cross_4h`, `wt_cross_1d`, `wt_confluence`, `regime_change`,
`trend_change_1h`, `anomaly_volume`, `cascade`, `ote_reentry`

**Примечание:** символ в URL через `_` (BTC_USDT → BTC/USDT внутри).

---

---

## 1. SQLite MCP — прямой SQL к subscriptions.db

**Зачем:** вместо `python -c "..."` можно прямо в чате спросить «покажи 10 последних SL с regime=HIGH_VOL» — и получить ответ без bash.

**Установка:**
```bash
npx @anthropic-ai/mcp-server-sqlite --help   # проверить что есть
# или
pip install mcp-server-sqlite                 # если Python-пакет
```

**Конфиг** (`~/.claude/settings.json` или `.claude/settings.json` в проекте):
```json
{
  "mcpServers": {
    "sqlite": {
      "command": "npx",
      "args": [
        "@anthropic-ai/mcp-server-sqlite",
        "--db-path",
        "/workspace/subscriptions.db"
      ]
    }
  }
}
```

**Примеры запросов после подключения:**

```sql
-- Последние 10 SL в HIGH_VOL
SELECT symbol, direction, strength, R_multiple, closed_at
FROM simulated_trades
WHERE status='SL' AND regime='HIGH_VOL'
ORDER BY closed_at DESC LIMIT 10;

-- WR по режиму за неделю
SELECT regime, direction,
       COUNT(*) as n,
       ROUND(SUM(CASE WHEN status IN ('TP','TSL') THEN 1.0 ELSE 0 END)
             / COUNT(*) * 100, 1) as WR,
       ROUND(AVG(R_multiple), 2) as avgR
FROM simulated_trades
WHERE status != 'OPEN'
  AND created_at > datetime('now', '-7 days')
  AND regime IS NOT NULL
GROUP BY regime, direction
ORDER BY n DESC;

-- DEV-157: аномальные SL (проверить что guard работает)
SELECT symbol, entry_price, stop_loss,
       ROUND(ABS(entry_price - stop_loss) / entry_price * 100, 4) as sl_dist_pct,
       created_at
FROM simulated_trades
WHERE created_at > datetime('now', '-1 day')
ORDER BY sl_dist_pct ASC LIMIT 10;

-- DEV-155: статистика блокировок (нужны логи)
-- смотреть в логах: grep "[DEV-155]" bot.log

-- ARCH-55: RANGE BOUNCE сделки
SELECT symbol, sl_source, tp_source,
       R_multiple, status, created_at
FROM simulated_trades
WHERE sl_source LIKE 'range_bounce%'
ORDER BY created_at DESC LIMIT 20;

-- Circuit Breaker: rolling WR последних 50
SELECT SUM(CASE WHEN status IN ('TP','TSL') THEN 1.0 ELSE 0 END)
       / COUNT(*) * 100 as rolling_wr,
       COUNT(*) as n
FROM (
  SELECT status FROM simulated_trades
  WHERE status IN ('TP','SL','TSL','EXPIRED')
  ORDER BY closed_at DESC LIMIT 50
);
```

---

## 2. Filesystem MCP (уже встроен в Claude Code)

Встроен по умолчанию. Субагенты (Explore/Plan) имеют доступ к файлам.

---

## 3. Playwright MCP — проверка дашборда

**Зачем:** после деплоя проверить что `localhost:8000` показывает новые поля (`sl_source`, `strategy_type`) без ручных кликов.

**Установка:**
```bash
npm install -g @playwright/mcp
```

**Конфиг:**
```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp"]
    }
  }
}
```

**Когда использовать:** после каждого изменения дашборда — скриншот `localhost:8000`, проверить что таблица не сломалась.

---

## 4. Sequential Thinking MCP — структурированные ARCH-решения

**Зачем:** для сложных решений типа «A+B vs C+D» (как OTE Step2) — явная цепочка шагов вместо одного большого ответа.

**Установка:**
```bash
npx @modelcontextprotocol/server-sequential-thinking
```

**Конфиг:**
```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "npx",
      "args": ["@modelcontextprotocol/server-sequential-thinking"]
    }
  }
}
```

---

## 5. Приоритет подключения

| # | MCP | Польза | Сложность | Рекомендуется |
|---|---|---|---|---|
| 1 | SQLite | Отладка trades без Python | Низкая | ✅ Сейчас |
| 2 | Playwright | Тест дашборда | Средняя | 🟡 При активном UI-dev |
| 3 | Sequential Thinking | ARCH решения | Низкая | 🟡 Опционально |
| 4 | Fetch | BingX/ccxt docs | Встроен | ✅ Уже есть |
