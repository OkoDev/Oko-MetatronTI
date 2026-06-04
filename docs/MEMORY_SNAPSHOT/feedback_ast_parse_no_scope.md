---
name: ast-parse-scope-nameerror-runtime-register-trade
description: "Проверка ast.parse подтверждает только синтаксис, НЕ ловит runtime-ошибки области видимости (NameError, переменная из другой функции). При правках register_trade / INSERT / любой код через несколько функций — прогонять реальный вызов (SelfTest L12 или локальный register_trade на копии боевой схемы), а не только ast.parse."
metadata: 
  node_type: memory
  type: feedback
  triggers: 
    - правка register_trade / register_trade_async
    - добавление поля в INSERT simulated_trades
    - переменная используется в другой функции чем определена
    - проверка ast.parse перед коммитом
    - shadow-поле через sync/async путь
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

Правило: `ast.parse` (синтаксис) НЕ заменяет runtime-проверку. Перед коммитом изменений `register_trade`/INSERT — прогнать реальный вызов на копии боевой схемы.

**Why:** 02.06.2026 (коммит 5389bcc, ARCH-124) инициализировал `_regime_v2` в `register_trade_async` (async), а использовал в INSERT внутри `register_trade` (sync, другой scope) → `NameError: _regime_v2 not defined` на КАЖДОЙ регистрации → SelfTest L12 CRITICAL FAIL → **бот не стартовал**. Я проверил `ast.parse` — «OK syntax» — и закоммитил. Магнит-переменные работали, т.к. инициализированы ВНУТРИ sync-функции; regime_v2 промахнулся мимо scope. ast.parse это пропустил (синтаксис валиден, scope — runtime). Фикс ded6ea4: regime_v2 как ПАРАМЕТР sync register_trade (как regime), async передаёт.

**How to apply:**
1. `register_trade` (sync, def ~314) и `register_trade_async` (~913) — РАЗНЫЕ scope. Переменная из async НЕ видна в sync INSERT. Передавать через параметр register_trade (как `regime`), вызов на trade_simulator.py:1291.
2. Перед коммитом правок register_trade/INSERT — runtime smoke: скопировать боевую `subscriptions.db` в temp (там полная схема: source_router, magnet_*, regime_v2 — `TradeSimulator.init_database` создаёт НЕПОЛНУЮ), `DELETE FROM simulated_trades`, вызвать `register_trade(rec, regime=...)` → ожидать id, не None/NameError. Шаблон: `e:/tmp/l12b.py`.
3. SelfTest L12 (`core/selftest.py:711`) ловит это при старте — но бот падает CRITICAL. Лучше до коммита.
4. ast.parse оставлять как быстрый pre-check, но НЕ как единственную верификацию для кода через несколько функций.
Связь: [[feedback_fix_checklist]] (что сломает), [[feedback_db_query_utc]].
