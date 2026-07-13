# 🏗️ Архитектура БД v2: от денормализованного лога к торговому терминалу

> **Инициатор:** ARCH (yogoru) · **Анализ:** DS (DeepCode) · **Дата:** 12.06.2026
> **Исходная схема:** 50 колонок в `simulated_trades`, 207 MB, WAL-mode, 24 846 сделок.
> **Цель:** полноценный торговый терминал с мульти-аккаунтом, мульти-биржей, историей баланса.

---

## 0. ДИАГНОЗ ТЕКУЩЕГО СОСТОЯНИЯ

```
simulated_trades (50 cols, 24K rows)
├── 📛 СМЕШАНО: сигнал + цены + результат + биржа + мета — в одной таблице
├── ❌ НЕТ account_id → сделки acc1/acc2 неразличимы
├── ❌ НЕТ execution_mode → SIM/VST/LIVE через exchange_order_id IS NULL (хрупко)
├── ❌ НЕТ balance_history → график equity невозможен
├── ❌ НЕТ exchange → multi-exchange не заложен
├── ✅ WAL-mode есть → конкурентное чтение
├── ✅ db_migrations есть → миграции работают
└── ✅ 207 MB → SQLite справляется (предел ~1 GB без деградации)
```

**Вывод:** не «переписать с нуля», а **эволюционно нормализовать** — добавлять таблицы, не ломая работающий код.

---

## 1. ЦЕЛЕВАЯ АРХИТЕКТУРА (фазы 1-3)

### Фаза 1: Минимально-необходимое (сейчас, без ломки)

Добавить в `simulated_trades` ТРИ поля (ALTER TABLE, backward-compatible):

```sql
ALTER TABLE simulated_trades ADD COLUMN account_id INTEGER DEFAULT 1;
ALTER TABLE simulated_trades ADD COLUMN execution_mode TEXT DEFAULT 'SIM';
ALTER TABLE simulated_trades ADD COLUMN exchange TEXT DEFAULT 'bingx';
```

Заполнить ретроспективно:
- `account_id` ← `account_routing.symbol` JOIN по символу на момент `created_at`
- `execution_mode` ← `'VST' WHERE exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM'`, иначе `'SIM'`
- `exchange` ← `'bingx'`

**Новая таблица: `balance_snapshots`** (для графика equity):

```sql
CREATE TABLE balance_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL,
    exchange    TEXT NOT NULL DEFAULT 'bingx',
    timestamp   TEXT NOT NULL,              -- ISO 8601
    equity      REAL NOT NULL,             -- общий
    available   REAL,                       -- свободный
    used_margin REAL,                       -- в позициях
    unrealized  REAL,                       -- плавающий PnL
    source      TEXT DEFAULT 'poll',        -- 'poll' | 'trade_close' | 'manual'
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_balance_account_ts ON balance_snapshots(account_id, exchange, timestamp);
```

> **Зачем:** каждый час (или при закрытии сделки) сохраняем equity счёта → график движения баланса по дням/неделям. 1 запись/час × 2 аккаунта × 30 дней = 1 440 строк — ничтожно для SQLite.

---

### Фаза 2: Нормализация (вынос в отдельные таблицы)

#### 2.1 `accounts` — реестр счетов

```sql
CREATE TABLE accounts (
    id          INTEGER PRIMARY KEY,
    exchange    TEXT NOT NULL,              -- 'bingx' | 'binance' | 'bybit'
    label       TEXT NOT NULL,              -- 'Main acc1' | 'Sub acc2 demo'
    api_env     TEXT DEFAULT 'demo',        -- 'live' | 'demo'
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Связь `account_routing` остаётся, но теперь ссылается на `accounts.id`.

#### 2.2 `execution_log` — жизненный цикл ордера на бирже

```sql
CREATE TABLE execution_log (
    id                  INTEGER PRIMARY KEY,
    trade_id            INTEGER NOT NULL REFERENCES simulated_trades(id),
    account_id          INTEGER NOT NULL,
    exchange            TEXT NOT NULL,
    order_type          TEXT NOT NULL,      -- 'ENTRY_MARKET' | 'SL_STOP' | 'TP_LIMIT' | 'CLOSE_MARKET'
    exchange_order_id   TEXT,
    side                TEXT,               -- BUY/SELL
    qty                 REAL,
    price_requested     REAL,
    price_filled        REAL,
    status              TEXT NOT NULL,      -- 'PENDING' | 'FILLED' | 'CANCELLED' | 'FAILED'
    slip_pct            REAL,
    error_code          TEXT,               -- 109400 etc
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT
);
CREATE INDEX idx_exec_trade ON execution_log(trade_id);
```

> **Заменяет** `live_orders` (12 col) — более полная, с историей статусов.

#### 2.3 `position_snapshots` — состояние открытых позиций во времени

```sql
CREATE TABLE position_snapshots (
    id          INTEGER PRIMARY KEY,
    account_id  INTEGER NOT NULL,
    symbol      TEXT NOT NULL,
    direction   TEXT NOT NULL,              -- LONG/SHORT
    qty         REAL,
    entry_price REAL,
    mark_price  REAL,
    sl_price    REAL,
    tp_price    REAL,
    unrealized  REAL,
    timestamp   TEXT NOT NULL,
    UNIQUE(account_id, symbol, direction, timestamp)
);
```

> Та же логика, что `balance_snapshots` — снапшот позиций. Даёт график: «как менялся SL/TP/unrealized со временем».

---

### Фаза 3: Аналитика и отчёты (поверх нормализованной схемы)

#### 3.1 VIEW: `v_trades_full` — единый источник для дашборда

```sql
CREATE VIEW v_trades_full AS
SELECT 
    t.*,
    a.label AS account_label,
    a.exchange,
    COALESCE(t.execution_mode,
        CASE WHEN t.exchange_order_id IS NOT NULL AND t.exchange_order_id != 'SIM' 
             THEN 'VST' ELSE 'SIM' END) AS exec_mode_resolved,
    -- последний снапшот баланса на момент закрытия
    (SELECT equity FROM balance_snapshots bs 
     WHERE bs.account_id = t.account_id 
       AND bs.timestamp <= t.closed_at 
     ORDER BY bs.timestamp DESC LIMIT 1) AS equity_at_close
FROM simulated_trades t
LEFT JOIN accounts a ON a.id = t.account_id;
```

#### 3.2 `report_cache` — материализованные агрегаты

```sql
CREATE TABLE report_cache (
    report_key  TEXT PRIMARY KEY,          -- 'daily_pnl:acc1:2026-06-11'
    data_json   TEXT NOT NULL,            -- {sumR, n_trades, winrate, ...}
    computed_at TEXT NOT NULL
);
```

> Чтобы не пересчитывать `SUM(R_multiple) WHERE account_id=? AND closed_at BETWEEN` на каждую загрузку дашборда.

---

## 2. ПЛАН МИГРАЦИИ (эволюционный, без даунтайма)

| Шаг | Что делаем | Риск | Откат |
|---|---|---|---|
| **M1** | `ALTER TABLE simulated_trades ADD account_id/execution_mode/exchange` | Нулевой — новые колонки с DEFAULT | `ALTER TABLE DROP COLUMN` (SQLite 3.35+) |
| **M2** | Заполнить ретроспективу (Python-скрипт, 24K строк) | Средний — проверка на копии БД | Транзакция + бэкап |
| **M3** | Создать `balance_snapshots` + накопить 7 дней | Нулевой — новая таблица | DROP TABLE |
| **M4** | Адаптировать `get_balance` → писать снапшот при опросе | Низкий — дописываем строку | Комментим вызов |
| **M5** | Создать `accounts`, мигрировать `account_routing` | Низкий | Транзакция |
| **M6** | Создать `execution_log`, перенести `live_orders` | Средний — двойная запись переходный период | Оставляем live_orders |
| **M7** | VIEW `v_trades_full` → дашборд переключить на него | Средний — тест на копии | Откат на прямой SELECT |

> **Каждый шаг — отдельная миграция в `db_migrations`. Один коммит = один шаг.**

---

## 3. POSTGRESQL: порог перехода

SQLite справляется до ~1-2 GB / 100K+ сделок без деградации. Признаки что пора:

| Симптом | Порог |
|---|---|
| Размер БД > 1 GB | 🔴 |
| WAL-файл > 100 MB стабильно | 🟡 |
| Запросы > 500 мс на агрегатах | 🟡 |
| 2+ процесса пишут одновременно | 🔴 (SQLite single-writer) |
| Нужна репликация / бекап без лока | 🔴 |

**Стратегия перехода:** слой `db.py` уже абстрагирует SQLite-запросы. При переходе:
- Оставляем схему (DDL адаптируется: `AUTOINCREMENT` → `SERIAL`, `TEXT` даты → `TIMESTAMPTZ`)
- Добавляем `TimescaleDB` для `balance_snapshots`/`position_snapshots` (авто-партиционирование по времени)
- Алchemy или asyncpg для пула соединений

---

## 4. ЧТО НЕ ДЕЛАТЬ (anti-patterns для этого проекта)

| ❌ Не делать | Почему |
|---|---|
| EAV (Entity-Attribute-Value) для фильтраций | JSON-поля (`features_json`) + индексы на ключевые поля эффективнее |
| Полный редизайн с нуля | 24K сделок — не те объёмы где овчина стоит выделки. Эволюция. |
| MongoDB / NoSQL | Нужны JOIN'ы (сделка→аккаунт→баланс), транзакции, аггрегаты — SQL родное |
| timescaleDB на SQLite | Нет аналога. Для time-series — PostgreSQL потом |
| sharding / партиционирование сейчас | 207 MB — это влезает в память целиком. Преждевременная оптимизация |

---

## 5. ДОРОЖНАЯ КАРТА (рекомендуемый порядок)

```
Неделя 1:  M1 (ALTER +3 поля) + M2 (заполнение) 
           → дашборд получает фильтр SIM/VST/LIVE + per-account 🎯

Неделя 2:  M3 (balance_snapshots) + M4 (сбор equity) 
           → график эквити по аккаунтам 📈

Неделя 3:  M5 (accounts) + M6 (execution_log) 
           → полная история биржевых ордеров

Неделя 4:  M7 (VIEW) + дашборд v2 
           → единый источник правды для фронта
```

---

## 6. КОНКРЕТНЫЕ ЦИФРЫ (что даёт каждая фаза)

| Фаза | Новые поля/таблицы | Размер БД+ | Эффект |
|---|---|---|---|
| M1-M2 | +3 поля в simulated_trades | ~1 MB | **Фильтр SIM/VST/LIVE и per-account** — главная боль решена |
| M3-M4 | balance_snapshots (1 440 строк/мес) | ~100 KB/мес | **График equity** — «вижу движение баланса» |
| M5-M6 | accounts (3 строки) + execution_log (~10K строк) | ~2 MB | **История ордеров** — «что произошло на бирже» |
| M7 | VIEW + report_cache | ~500 KB | **Быстрый дашборд** без пересчёта агрегатов |

> **Итого:** +3.5 MB к БД за ВСЕ фазы. SQLite справляется с запасом.

---

*Документ: живой. Обновлять по мере реализации фаз.*
