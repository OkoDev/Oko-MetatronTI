# Бриф для bot-data-audit — аудит целостности данных (матч/JOIN/семантика)

> Создан 18.06.2026 (Даат) для запуска субагента `bot-data-audit` в СВЕЖЕЙ сессии.
> Запуск: дать этот файл агенту как контекст. Правила проекта: thinking на русском, grep before claim,
> числа из config/кода, runtime-проверки ТОЛЬКО на копии БД (`cp subscriptions.db e:/tmp/...`), прогон main НЕ трогать.

## 🎯 ЦЕЛЬ
Найти баги класса **«сопоставление данных по неполному/неверному ключу»** и **неверная семантика полей** — по всему проекту (торговая логика приоритетнее дашборда: матч-баг в торговле = реальные деньги/неверный close/SL).

## 🔬 КЛАСС БАГА (эталон — уже найден и починен)
**R −3.28R на дашборде (18.06):** `_handle_live` (`web/dashboard_server.py:~1292`) матчил SL/TP биржевой позиции с sim-сделкой через `live_orders→simulated_trades` **только по `symbol`** (без `direction`). SHORT-позиция UB хватала закрытую LONG-сделку того же символа → инвертированный стоп → R-мусор. **Фикс:** ключ `(symbol, direction)` + `ORDER BY (status='OPEN') DESC, created_at DESC`.

Паттерн для поиска: матч/JOIN/`.get(symbol)`/`WHERE symbol=?` БЕЗ `direction`/`side`/`account_id`/`status`, где это влияет на корректность.

## ✅ УЖЕ ПРОВЕРЕНО (чисто, не трогать)
- Торговые матчи close/SL/TSL/reconcile — все с direction: `core/exchange/exec_ws_integration.py:62,117` (`symbol+direction+status`), `core/exchange/position_sync.py:366` (`symbol+direction`), `core/trading/trade_simulator.py:372` (`symbol+status+direction`), `core/exchange/position_parser.py:104 by_symbol_side` (ключ `(symbol,side)`).
- `web/dashboard_server.py _handle_live_orders:1023` — матч по точному `pos.sim_trade_id` (ID-мост) ✓.
- Cooldown-гейты (`gates/pair_cooldown_streak`, `gates/sl_cooldown`) — `WHERE symbol=?` намеренно по символу (cooldown на пару, не сторону) ✓.

## ✅ УЖЕ ПОЧИНЕНО (18.06, не дублировать)
1. `_handle_live` матч SL/TP → `(symbol, direction)` (коммит d51b26f).
2. `position_manager.get_by_symbol:159` — был `symbol+status` без side (dead code, мина) → добавлен опц. `side`.
3. `api.ts fetchLivePositions` — хардкод `regime="RANGE"` → реальный из матча (бэк отдаёт `st.regime`).

## 🔍 ГДЕ КОПАТЬ (приоритет сверху)
1. **core/exchange/** — рассинхрон БД↔биржа: `position_sync.py`, `order_reconciler.py`, `order_manager.py`. Матч позиция↔БД-сделка, close/cancel routing (история: hedge_close_multiacct — закрывали не тот аккаунт; КОРЕНЬ 101205). Проверить account_id/positionId/side в close/SL-путях.
2. **web/dashboard_server.py** — прочие endpoints с JOIN/матчем (sync overview orphan/zombie `_handle_repair_orphans:2841`, `_handle_kpi`, `_handle_stats`). Семантика risk/exposure.
3. **api.ts (oko-dashboard, НЕ git!)** — прочие хардкоды-заглушки в `fetchLivePositions`: `maxR=0`, `signal="confluence"`, `tf="15m"` (показывают ложь для биржевых позиций). Решить: реальные данные или «—».
4. **core/db/*_repo.py** — тонкий db-слой ARCH-DB-V2. Семантика `execution_mode` (SIM⟺order_id NULL, VST⟺order_id есть), `account_id` (backfill 76% старых=1), `qty`.
5. **Семантика полей в агрегатах** — `performance_engine`, метрики: фильтры `execution_mode='VST'`, `data_era`, `status IN (...)`. Проверить что фантомы/sim не текут в боевые метрики.

## 🛠️ МЕТОД
- grep паттерны: `WHERE symbol=` (без AND direction/side), `\.get\(.*symbol`, `JOIN .* ON .*symbol`, `IN \({ph}\)`, хардкоды в .ts.
- Для каждого подозрения: проверить на КОПИИ БД (реальные данные, hedge-символы с LONG+SHORT — лучший тест).
- Связанная память: `arch_db_v2_terminal`, `exec_sim_split_epic`, `hedge_close_multiacct_root`, `feedback_verify_metric_semantics`.

## 📤 ВЫХОД
Список находок с severity (деньги/отображение/мина), file:line, корень, предложенный фикс. НЕ править вслепую — сначала вердикт, фиксы по согласованию.
