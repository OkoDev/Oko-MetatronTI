# 🧩 Синтез: перепроектирование БД в торговый терминал (12.06.2026)

> Свод 5 источников: **DS_V2** (DeepCode), **GPT**, **DeepSeek**, **Qwen3**, **Gemini** + **взаимный фильтр Claude** (приземление на реальный код).
> Метод: консенсус (где все сходятся = надёжно) → расхождения (вердикт) → приземление на факты кода.

---

## 1. КОНСЕНСУС — где сходятся ВСЕ 5/5 (берём не раздумывая)

| # | Согласие 5/5 | Решает боль |
|---|---|---|
| 1 | **Доменная модель `Signal → Trade → Order → Account → Exchange`** — разбить God-table | основа всего |
| 2 | **3 поля-измерения в trades:** `account_id` + `execution_mode`(SIM/VST/LIVE явно) + `exchange_id` | боль №1 (режимы) + №2 (аккаунты) |
| 3 | **Справочники `exchanges` + `accounts`** | multi-exchange + multi-account |
| 4 | **`balance_snapshots`** — история equity (ВСЕ 5 зовут ключевым) | боль №3 (движение баланса) |
| 5 | **`orders` отдельно** (расширить live_orders): 1 trade → N orders (partial TP, SL-переносы) | история исполнения |
| 6 | **Вынести тяжёлое** (features_json, decision_trace, метрики) в связанные таблицы → trades узкая/быстрая | боль №4 (фильтрации) |
| 7 | **Эволюция, НЕ переписывание с нуля** — параллельные таблицы + ETL-backfill, старое не ломать | риск |
| 8 | **PostgreSQL-схема совместима**, заложить наперёд; SQLite пока хватает | будущее |

→ **Это скелет. По нему расхождений нет — реализуем.**

---

## 2. РАСХОЖДЕНИЯ — где спорят (+ вердикт Claude)

| Вопрос | Лагерь A | Лагерь B | Вердикт (с приземлением) |
|---|---|---|---|
| **Как добавлять разметку** | ALTER +3 поля в simulated_trades (GPT, DS_V2) | сразу новая `trades` + ETL (Qwen, Gemini, DeepSeek) | **Оба по фазам:** ALTER сейчас (80% боли, риск≈0) → нормализация ETL потом |
| **Переименовать simulated_trades→trades** | да (GPT, Qwen, DeepSeek) | осторожно (DS_V2, Claude) | **НЕ сейчас** — горячий путь, 33 файла читают её. Новая схема рядом через ETL |
| **positions** | snapshot с историей (GPT, DS_V2) | только current-state (DeepSeek) | **DeepSeek прав:** история позиций = взрыв строк (205 поз × sync 60с = ~295K/день). Current-state, история не нужна |
| **ORM** | SQLAlchemy/SQLModel обязательно (Qwen, Gemini) | — | ⚠️ см. приземление №1 — это рефактор 33 файлов, отдельный проект |
| **fee/комиссии, leverage, MAE/MFE** | добавить явно (Gemini, Qwen) | не упомянули (DS_V2) | **Добавить fee** — без него реальный PnL неточен. leverage/MAE/MFE — да |

---

## 3. 🔬 ПРИЗЕМЛЕНИЕ на реальный код (взаимный фильтр — важнее общих советов)

Нейроны проект не видят. Проверил факты — три поправки:

**1. 🔴 ORM-слоя НЕТ. Raw `sqlite3` в 33 файлах.**
DS_V2 утверждал «db.py слой уже абстрагирует» — **неверно**. Qwen/Gemini советуют SQLAlchemy как «смена одной строки» — реально это **переписать 33 файла**. Вывод: ORM-переход = **отдельный крупный проект**, не побочный эффект. Либо вводить db-слой постепенно, либо принять raw SQL и Postgres-миграцию делать ручной правкой. **Решение за юзером** (см. §6).

**2. 🔴 Backfill `account_id` — 76% сделок не покрыть.**
`account_routing` живёт с 08.06 (4 дня), сделки — с 01.03 (3.5 мес). **19 092 сделки (76%) старше routing.** Все нейроны говорят «default для старых» — сходится. Честно: старые → `account_id=1`/`SIM`, **точный account только вперёд**. Аналитика per-account достоверна с момента миграции, не ретроспективно. (Хорошо: все routing `mode=vst`, LIVE не было → execution_mode backfill корректен.)

**3. 🟡 `position_snapshots` с историей — объём взорвёт БД.**
DeepSeek-вариант (current-state, PK `account+symbol`) — верный. GPT/DS_V2 (история) дал бы ~295K строк/день. Берём current-state.

**Плюс:** `execution_log`/`orders` все хотят **заменить** live_orders. Live_orders в горячем пути исполнения (33 файла, 10K строк). **Расширять параллельно**, не заменять рывком.

---

## 4. ЦЕЛЕВАЯ СХЕМА (синтез консенсуса + приземление)

```
ИНФРАСТРУКТУРА (master data)
  exchanges        (id, name, is_active)
  accounts         (id, exchange_id→, name, api_env, is_active)
  routing_rules    (= нынешний account_routing, FK на accounts.id)

СИГНАЛ
  signals          (id, symbol, tf, strategy_name, direction, strength, regime, created_at)
                   features_json/decision_trace → сюда (или trade_features)

СДЕЛКА (ядро, УЗКАЯ — быстрые фильтры)
  trades           (id, signal_id→, account_id→, exchange_id→, execution_mode[SIM/VST/LIVE],
                    symbol, direction, qty, leverage,
                    entry_price, actual_entry_price, stop_loss, take_profit, exit_price,
                    status, pnl_usdt, profit_pct, R_multiple, opened_at, closed_at)

ИСПОЛНЕНИЕ (1 trade → N orders)
  orders           (= расширенный live_orders: id, trade_id→, account_id→, exchange_order_id,
                    order_type[ENTRY/SL/TP1/TP2/CLOSE], side, price, qty, filled_qty,
                    fee, status, created_at, updated_at)

ДЕНЬГИ (РЕШАЕТ боль баланса)
  balance_snapshots (id, account_id→, timestamp, equity, available, used_margin,
                     unrealized_pnl, source[poll/trade_close/manual])
                     ← снимать при закрытии сделки + cron 5-15 мин

ПОЗИЦИИ (current-state, НЕ история)
  positions        (account_id, symbol, side, qty, entry_price, unrealized_pnl, updated_at,
                    PRIMARY KEY(account_id, symbol))

АНАЛИТИКА (тяжёлое из 50 колонок)
  trade_metrics    (trade_id→, max_R_possible, captured_R_pct, first_profit_r,
                    first_drawdown_r, MAE, MFE)
  trade_features   (= нынешняя, FK sim_trade_id→trade_id)
  report_cache     (report_key, data_json, computed_at) — материализация агрегатов
```

Индексы: `trades(account_id, created_at)`, `trades(execution_mode, created_at)`, `trades(symbol, created_at)`, `trades(status)`, составной `(account_id, execution_mode)`.

---

## 5. ПЛАН (поэтапный — компромисс «немедленная польза + правильный вектор»)

| Фаза | Шаги | Эффект | Риск |
|---|---|---|---|
| **Ф1 (сейчас)** | ALTER +`account_id`/`execution_mode`/`exchange_id` в simulated_trades; backfill (новые точно, старые default); создать `balance_snapshots` + начать сбор equity при закрытии/cron | **Фильтр SIM/VST/LIVE + per-account + график equity** — 80% боли | ≈0 (новые колонки DEFAULT) |
| **Ф2** | `exchanges`+`accounts`+`positions`; дашборд: вкладки аккаунтов, баланс-карточки, equity-график | визуальный терминал | низкий |
| **Ф3** | новая `trades`/`signals`/`orders`/`trade_metrics` через ETL; постепенно переключить запись; VIEW для дашборда | полная нормализация | средний (ETL на копии БД) |
| **Ф4 (опц)** | db-слой/ORM → готовность к Postgres; Postgres при разнесении на процессы | scale 5-10× | отдельный проект |

> Каждый шаг = отдельная `db_migration` + тест на копии БД (правило проекта: runtime на копии перед коммитом).

---

## 6. 🔴 ОТКРЫТЫЕ РЕШЕНИЯ ДЛЯ ЮЗЕРА (нужен выбор)

1. **ORM или raw SQL?** Нейроны хором за SQLAlchemy, но это рефактор 33 файлов. Варианты:
   - (а) Остаться на raw SQL, Postgres-миграцию делать вручную когда дойдём (дешевле сейчас)
   - (б) Постепенно вводить тонкий db-слой (репозиторий-функции) без полного ORM
   - (в) Полный SQLAlchemy сразу (дорого, но чистый путь к Postgres+JSONB)
2. **ETL или ALTER-эволюция?** Рекомендую начать с ALTER (Ф1, быстро/безопасно), нормализацию ETL — Ф3.
3. **fee/комиссии** — трекать сейчас (точный реальный PnL) или потом?

---

## РЕЗЮМЕ

5 нейронов единогласны в скелете (домены + 3 поля + balance_snapshots + эволюция). Расхождения — в темпе (ALTER vs ETL) и ORM. Приземление на код дало 3 поправки (нет ORM/33 файла, 76% backfill, positions current-state). **Старт = Фаза 1: +3 поля + balance_snapshots** — решает главную боль (разделение режимов/аккаунтов + график баланса) почти без риска, остальное достраивается поверх.

*Документ живой. Источники: docs/DB_ARCHITECTURE_V2.md (DS) + 4 нейрона (gpt/deepseek/qwen/gemini).*
