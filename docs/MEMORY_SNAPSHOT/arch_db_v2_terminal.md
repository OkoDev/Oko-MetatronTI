---
name: arch_db_v2_terminal
description: ARCH-DB-V2 — перепроектирование БД в торговый терминал (синтез 5 нейронов + приземление). Решение и план
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# 🧩 ARCH-DB-V2: БД → торговый терминал (12.06.2026)

**Боль юзера:** SIM/VST/LIVE + суб-аккаунты в одной куче (`simulated_trades` 50 колонок), реальный PnL и баланс per-account не отследить, фильтраций будет много, цель = «почти торговый терминал». Корень: НЕТ полей `account_id`/`execution_mode`/`exchange` (режим определялся косвенно через `exchange_order_id IS NULL`).

**Метод:** промт рою (`docs/DB_REDESIGN_PROMPT.md`) → 5 ответов (DS_V2 `docs/DB_ARCHITECTURE_V2.md` + GPT/DeepSeek/Qwen/Gemini) → синтез Claude `docs/DB_REDESIGN_SYNTHESIS.md`.

**Консенсус 5/5 (надёжный скелет):** домены `Signal→Trade→Order→Account→Exchange`; 3 поля-измерения (`account_id`+`execution_mode` SIM/VST/LIVE явно+`exchange_id`); справочники `exchanges`+`accounts`; **`balance_snapshots`** (история equity — ВСЕ зовут ключевым для «движение баланса»); `orders` отдельно (1 trade→N orders); тяжёлое (features_json) → связанные таблицы; эволюция НЕ переписывание + ETL-backfill.

**🔬 Приземление Claude на код (важнее общих советов нейронов):**
1. **ORM НЕТ** — raw `sqlite3` в 33 файлах. DS_V2 ошибся («db.py есть»). SQLAlchemy = рефактор 33 файлов, не «1 строка».
2. **Backfill account 76% не покрыть** — `account_routing` с 08.06, сделки с 01.03 (19092=76% старше). Старые → `account_id=1`, точно ТОЛЬКО вперёд. (Все routing mode=vst, LIVE не было → execution_mode backfill ок.)
3. **positions = current-state** (PK account+symbol), НЕ история (иначе 205 поз × sync 60с = ~295K строк/день).
4. `orders` РАСШИРЯТЬ не заменять live_orders рывком (горячий путь). + добавить `fee` (точный реальный PnL — Gemini/Qwen).

**🔑 РЕШЕНИЕ ЮЗЕРА 12.06:** (1) raw SQL + **тонкий db-слой** (репозиторий-функции в `core/db/`, не полный ORM) — компромисс дёшево-сейчас/Postgres-проще-потом; (2) старт через **эпик в TASKS** (ARCH-DB-V2), не сразу код.

**ПЛАН (фазы):** Ф1 (сейчас) ALTER +3 поля + balance_snapshots + backfill-скрипт на копии БД → фильтр режимов/аккаунтов + equity-график (80% боли, риск≈0); Ф2 exchanges/accounts/positions + дашборд-вкладки/баланс-карточки; Ф3 нормализация trades/signals/orders/trade_metrics через ETL; Ф4 db-слой→Postgres-readiness (Postgres при разнесении на процессы/машины — связано с отложенным VPS). Каждый шаг = `db_migration` + runtime-тест на копии.

**✅ Ф1 ЗАВЕРШЕНА НА БОЕВОЙ (12.06):** DS дал data-ядро (db-слой+backfill), Claude взаимным фильтром нашёл 3 пробела (register_trade не писал / save_snapshot не вызывался / нет миграции) + доделал интеграцию. Авто-миграция subscription_manager (+3 колонки+balance_snapshots+индексы), register_trade, order_manager.snapshot_balances_per_account, position_sync throttled snapshot (~10мин), core/db/{balance,trades}_repo.py, scripts/db_phase1_backfill.py. **🔑 execution_mode = ФАКТ исполнения (юзер, найдено на боевой): register→SIM, при order_id (trade_router/exec_ws)→VST/LIVE; shadow(order_id NULL)=SIM.** Боевая консистентна: SIM⟺order_id NULL (14917), VST⟺order_id есть (10321), 0 расхождений. account старые 75%=1, свежие по routing (acc1=22234/acc2=3004). balance_snapshots собирается per-account (acc1 eq291/acc2 eq556 раздельно, ~12мин). Боль решена: SIM/VST разделены + per-account + equity-история. Коммиты: feat Ф1 + fix факт-логика. → **Ф2: exchanges/accounts/positions таблицы + дашборд-вкладки/баланс-карточки/equity-график.**

**SQLite достаточно** (24846 сделок/207MB/WAL — мизер). Postgres-триггер = разнесение на машины (тот же момент что VPS, отложено). Связь: «почти торговый терминал» vision, [[adopt_manual_trades_vision]], ARCH-96 Execution Sphere.
