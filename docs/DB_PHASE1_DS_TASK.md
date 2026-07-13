# Задание DS: ARCH-DB-V2 Фаза 1 — DDL + backfill (data-ядро)

> Модель (юзер 12.06): **DS делает ВСЮ Фазу 1 на КОПИИ БД → Claude проверяет (runtime на копии)
> → Claude применяет на боевую + коммит.** DS = исполнитель, Claude = QA + финальный gate.
> Решение юзера: raw SQL + тонкий db-слой (НЕ ORM). Эволюция, не ломать.

---

## КОНТЕКСТ (факты боевой БД subscriptions.db)
- SQLite WAL, 24 848 сделок, 207 MB, система миграций `db_migrations`.
- `simulated_trades` — 50 колонок, центральная. НЕТ полей account/execution_mode/exchange.
- `account_routing` (459 строк): `symbol, account_id, mode, assigned_at`. assigned с **08.06.2026**.
  - acc=1 mode=vst (230 символов), acc=2 mode=vst (229 символов). LIVE-режима НЕТ.
- `simulated_trades.created_at`: с **01.03.2026**. **19 092 сделки (76%) старше account_routing** →
  для них account ретроспективно НЕИЗВЕСТЕН.
- `exchange_order_id`: заполнен у 10 092 (исполнены), NULL у 14 754 (SIM).
- `live_orders` (10k): `sim_trade_id ↔ exchange_order_id` — связь сделка↔биржа (НЕ трогать в Ф1).

## ЗАДАЧА Фазы 1 (минимум риска, решает 80% боли)

### 1. DDL: ALTER +3 поля (backward-compatible, DEFAULT)
```sql
ALTER TABLE simulated_trades ADD COLUMN account_id     INTEGER DEFAULT 1;
ALTER TABLE simulated_trades ADD COLUMN execution_mode TEXT    DEFAULT 'SIM';
ALTER TABLE simulated_trades ADD COLUMN exchange       TEXT    DEFAULT 'bingx';
```
> exchange как TEXT (не FK) — таблица `exchanges` будет в Ф2, тогда нормализуем в exchange_id.

### 2. DDL: новая `balance_snapshots` (история equity — главная новая ценность)
```sql
CREATE TABLE IF NOT EXISTS balance_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL,
    exchange     TEXT NOT NULL DEFAULT 'bingx',
    timestamp    TEXT NOT NULL,                  -- ISO8601 UTC
    equity       REAL NOT NULL,                  -- total
    available    REAL,
    used_margin  REAL,
    unrealized_pnl REAL,
    source       TEXT DEFAULT 'poll',            -- 'poll'|'trade_close'|'manual'
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_balance_acc_ts ON balance_snapshots(account_id, exchange, timestamp);
```

### 3. Backfill-скрипт (Python, на КОПИИ БД — НЕ боевой!)
Заполнить 3 новых поля у 24 848 существующих сделок:
- **execution_mode:** `exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM'` → `'VST'`, иначе `'SIM'`.
  (LIVE не было — все исполненные = VST. Если найдёшь признак LIVE — сообщи.)
- **account_id:** для сделок с `created_at >= '2026-06-08'` (свежие 24%) — JOIN `account_routing`
  по symbol (взять account_id где routing.symbol = trade.symbol). Для старых 76% (`< '2026-06-08'`)
  → оставить DEFAULT 1 (точный account неизвестен, не выдумывать). Отметить сколько проставлено
  точно vs default.
- **exchange:** всё → `'bingx'`.
- Батчами по 1000, в транзакции, идемпотентно (можно прогнать повторно).

### 4. Валидация (запросы после backfill — показать распределение)
```sql
SELECT execution_mode, COUNT(*) FROM simulated_trades GROUP BY 1;
SELECT account_id, COUNT(*) FROM simulated_trades GROUP BY 1;
SELECT COUNT(*) FROM simulated_trades WHERE created_at>='2026-06-08';  -- сколько потенц. точных
-- sanity: сумма должна сойтись с 24848
```

## DS ДЕЛАЕТ ВСЮ Фазу 1 (на КОПИИ БД, напр. `cp subscriptions.db subscriptions_test.db`)
5. **Интеграция в `register_trade`/`trade_simulator`**: INSERT новых сделок пишет `account_id`
   (из account_routing по symbol+направлению), `execution_mode` (текущий режим бота), `exchange`
   ('bingx'). Найди где register_trade формирует INSERT — добавь 3 колонки.
6. **Тонкий db-слой** `core/db/` (НЕ ORM): репозиторий-функции, напр. `balance_repo.py`
   (`save_snapshot(account_id, equity, ...)`, `get_equity_series(account_id, since)`),
   `trades_repo.py` (фильтры по account/mode). Цель: SQL в одном месте, не раскидан.
7. **Сбор balance_snapshots**: где бот опрашивает баланс (order_manager `_get_*balance*` /
   position_sync) — дописать вызов `save_snapshot` при закрытии сделки + периодически.

## 🔴 ГРАНИЦЫ (DS на копии, Claude — боевая)
- DS работает ТОЛЬКО на КОПИИ `subscriptions_test.db`. **НЕ трогать боевую `subscriptions.db`.**
- DS НЕ коммитит, НЕ регистрирует в `db_migrations` (это финальный gate Claude).
- DS прогоняет свой backfill + register_trade на копии, показывает что работает.

## DELIVERABLE от DS
1. DDL (ALTER + CREATE balance_snapshots).
2. Backfill-скрипт (на копии, статистика точных/default account).
3. Правки `register_trade` (INSERT +3 поля) + тонкий db-слой `core/db/*_repo.py`.
4. Вызовы save_snapshot (закрытие + cron).
5. Доказательство работы на копии (запросы: новые сделки с полями, snapshot пишется).
6. Заметки: признак LIVE? edge-cases?

## CLAUDE (QA + gate, ПОСЛЕ DS)
- Взаимный фильтр: прочитать правки DS, поймать дыры (scope, горячий путь, реальность кода).
- **Runtime-тест на копии** (правило feedback_ast_parse_no_scope: register/INSERT → прогон на
  копии боевой, ast.parse не ловит scope L12).
- Применить миграцию на БОЕВУЮ `subscriptions.db` через `db_migrations`.
- Финальный коммит (логический).
