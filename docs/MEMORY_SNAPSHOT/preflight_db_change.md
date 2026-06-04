---
name: preflight-db-change
description: Pre-flight чек-лист перед добавлением поля / ALTER TABLE / миграцией в subscriptions.db
metadata: 
  node_type: memory
  type: preflight
  triggers: 
    - ALTER TABLE simulated_trades
    - новое поле в simulated_trades
    - миграция БД
    - subscription_manager.py CREATE TABLE
    - INSERT в trade_simulator.py
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# Pre-flight: изменение БД (subscriptions.db)

> Read **прежде чем** менять схему БД или добавлять поле. Поводы: новое поле в `simulated_trades` / `signal_drops` / `risk_decisions_log`, ALTER TABLE, новая таблица.

## 1. Где сейчас живёт схема

- **DDL источник:** `core/db/subscription_manager.py::__init__()` — `CREATE TABLE IF NOT EXISTS ...`
- **Миграции для существующих БД:** `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` в том же `__init__`
- **Запись в `simulated_trades`:** `core/trading/trade_simulator.py::register_trade_async()` + `close_trade()`
- **Запись в `signal_drops`:** `core/observability/decision_trace.py::record_drop()`
- **Запись в `risk_decisions_log`:** `core/intelligence/arch104_signal_adapter.py::process()`

## 2. Чек-лист добавления нового поля

1. **CREATE TABLE** — добавить столбец в `subscription_manager.py::__init__()`
2. **ALTER TABLE для legacy БД** — `try: ALTER TABLE ... ADD COLUMN ... except OperationalError: pass`
3. **INSERT** — добавить значение в `register_trade_async()` (или соответствующий writer)
4. **UPDATE/SELECT по полю** — если читается — добавить индекс если queries по этому полю частые
5. **features_json vs топ-level колонка**:
   - Часто используемое в queries / индексируется → топ-level колонка
   - Редко используемое / переменная структура → внутрь `features_json` (TEXT JSON)

## 3. SQLite специфика (наш случай)

- **Тип `INTEGER`** для bool (0/1), не BOOLEAN
- **Timestamps** — TEXT в ISO формате `2026-05-21T03:00:00+00:00` (timezone-aware!) — НЕ Unix int
- **Datetime сравнения** через `datetime(field) >= datetime(?)` если поле TEXT — string compare даёт мусор (см. `feedback_no_fabricated_apis` про DEV-215 datetime bug 17.05)
- **JSON поля** — `json_extract(features_json, '$.key')` для query

## 4. Не сломать существующее

- **Старые записи** (до миграции) — поле будет `NULL`. SELECT-запросы должны это учитывать (`COALESCE` или `WHERE x IS NOT NULL`)
- **simulated_trades** имеет 30 000+ записей — миграция дешевая (ADD COLUMN не блокирует), но `UPDATE WHERE id IN (SELECT ...)` массовый — long lock
- **Бэкап БД** перед массовым UPDATE: `cp subscriptions.db subscriptions.db.bak.YYYY-MM-DD`

## 5. Семантика и dataeras

→ [[feedback_verify_metric_semantics]] · [[feedback_data_era_first]]

- При добавлении нового поля **сразу запиши** в `memory/MEMORY.md` или topic-файл что оно значит (что туда пишется, в какой момент, какой тип)
- Иначе через месяц я (или другой агент) интерпретирую неправильно — это закрытый кейс из verify_metric_semantics
- Если поле появилось при фиксе X (например `is_micro_sl` после DEV-157) — это **новая data era**, старые записи без него

## 6. Тестирование миграции

1. На staging БД (копия prod): `python -c "from core.db.subscription_manager import SubscriptionManager; SubscriptionManager('test.db')"`
2. Проверить `PRAGMA table_info(simulated_trades)` — поле появилось
3. INSERT тестовой записи через `register_trade_async` — поле заполняется
4. SELECT — поле читается корректно

## 7. Документация

- Обновить `memory/MEMORY.md` если поле hot
- Создать topic-файл `memory/db_<feature>.md` если поле объёмное (например `db_risk_decisions_log.md`)
- TASKS.md — статус миграции

## Связано
- [[feedback_verify_metric_semantics]] · [[feedback_no_fabricated_apis]]
- [[feedback_data_era_first]] — новое поле = новая data era
- `core/db/subscription_manager.py` — главный DDL источник
