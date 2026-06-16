# Current State - handoff между сессиями (проектный слой, git)

> Последние ~8 сессий. Старое -> `current_state_ARCHIVE.md` + git log.
>
> **АРХИТЕКТУРА ПАМЯТИ (15.06.2026, чтобы две памяти не расходились):**
> - auto-memory (`~/.claude/projects/.../memory/`) = HOT-слой Даата (auto-load): `MEMORY.md` индекс + личное (identity/vision). Эфемерно.
> - repo `memory/` (ЭТОТ путь, git) = SHARED: `current_state` (handoff, DS читает) + Gemini-outputs (`last_*`).
> - Правило: handoff -> СЮДА (git/DS); hot-recall индекс -> auto-memory. Не дублировать.

---

## [16.06.2026] Агент: Даат — BUS-CATALOG + дашборд-из-шины (оперативка), каша trades.tsx

### ✅ Сделано (коммиты на ветке arch-128-oko-sm)
- **EXEC-SIM-SPLIT кирпич 1** (2b51f81): VST-exit из реального WS-fill (exec_ws). Доказан в бою (FIGHTID REST 0.003603→WS 0.004085).
- **logging-фикс** (279f46d): market_ws воркер не держит crypto_bot.log (ротация WinError 32).
- **leverage+mark с биржи в шину** (3a7a081): position_sync→update_position (реальное плечо/цена). dashboard свой executor (фикс 'schedule after shutdown'). + tick_price из OHLCV (WsFeed off).
- **BUS-CATALOG** (61b7191): `core/context/bus_catalog.py` — меню данных шины (24 события+56 L1+6 L2), `bus.catalog()`/`docs/BUS_CATALOG.md`, самодокументируемый (validate синхрон). [[bus_catalog_data_menu]]
- **dashboard-from-bus** (03f5d13): `/api/open` (открытые лёгкий+цена/R/плечо/размер из шины), `/api/live.kpi` (open/unreal/risk/equity), equity→шина (position_sync). [[dashboard_oper_from_bus_analytics_sql]]
- **/api/open +leverage+notional** (07d7065): плечо+размер для оперативных сделок.
- equity проверено: /api/live.kpi полный (equity=273.96 risk=1.2), /api/open 0.3с, exchange_history 500 закрытых (tp82/sl365/tsl4).

### 🔴 НЕЗАВЕРШЕНО — каша trades.tsx (СЛЕДУЮЩАЯ СЕССИЯ, свежая голова)
Фронт oko-dashboard (НЕ git, на диске :3001 — старый :3000 убит). 3 бага + ТЗ в `whats-next.md` («КАША trades.tsx»): (1) Sim OPEN R-колонка показывает $; (2) Exchange OPEN 67 счётчик но пусто; (3) Exchange TP 0 но строка висит. Причина: быстрые правки рассинхронили Sim/Exchange×OPEN/закрытые. Метод: прочитать trades.tsx ЦЕЛИКОМ → один системный проход (stats 167/filtered 157/render-body/ALL_COLS 39).

### Урок
Огромная сессия → контекст забит → потеря консистентности фронта (каша). Юзер прав: остановиться, причесать со свежей головой, не лепить заплатки.

---

## [15.06.2026] Агент: Даат — 🔴 EXEC-SIM-SPLIT: метрики врут от смешения SIM/VST логик

### Корень (разобран на APEX #29750, ote_nested VST LONG)
- Биржа реально закрыла SL-STOP fill **ap=0.3242 (−1R штатно)**, но в БД `exit=0.2558 (−22%)` → фейк R=−20.9 → clamp `R_CLAMP_MIN=−15` (r_math.py:23).
- **НЕ баг — СМЕШЕНИЕ ДВУХ ЛОГИК** (вердикт юзера): `check_open._proc` (trade_simulator.py:2678-2680) обрабатывает SIM+VST в ОДНОМ пути (`not _exchange_managed_trade → VST wick / SIM close`). SIM-идеализация ложится на VST.

### Принцип юзера (фундамент)
- **SIM** = полигон «как НЕ торговать» (идеализирован, не знает биржи). **VST** = «как НАДО» (реальные SL/TP/цены). **VST = единственный источник истины.** Логики НЕ должны быть одинаковы.

### Решение = EXEC-SIM-SPLIT (BACKLOG #21, 🔴) — [[exec_sim_split_epic]]
1. БД раздельные (sim.db ↔ live.db). 2. Логики закрытия раздельные (SIM свеча / VST только биржевой fill). 3. SIM отдельным процессом (собирает данные, не мешает). 4. Метрики/доход/обучение ТОЛЬКО VST.
- Масштаб искажения: **217 VST-сделок R≤−10** (clamp-зона).
- ⚠️ Доход мерить по equity (`scripts/equity_curve.py` — биржевой факт), НЕ по R (искажён).

### 🔨 Кирпич 1 ГОТОВ (VST-exit достоверный) — НУЖЕН РЕСТАРТ
- Уточнение: `check_open` для VST НЕ закрывает по свече (LIVE-GUARD 2846-2867 ждёт биржу — чисто). Источник искажения = `_resolve_exit` (REST `get_filled_orders`) при EXEC-WS sync_close взял неверный ордер (0.2558 vs реальный fill 0.3242).
- Фикс в `exec_ws_integration.py` (4 правки, незакоммичено): EXEC-WS ловит `ap` закрывающего fill из `ORDER_TRADE_UPDATE` → `_close_fills[(sym,dir)]` → `sync_close` использует его приоритетно над REST. Гонка ОК (ORDER fill раньше ACCOUNT_UPDATE pa=0). Синтаксис ✅.
- **NEXT:** рестарт → наблюдать лог `[EXEC-WS][2b] ... WS-fill` → новые VST-exit точные. Старые 217 — backfill из биржевой fill-истории (сложнее) ИЛИ пометить недостоверными. Кирпичи 2-4 (раздельные БД/процесс/метрики) — далее.

### #8 закатан (4b22a0c)
- `AND execution_mode='VST'` в by_signal_type[_ema] — веса на VST-выборке (SIM-шум убран). Верно. Но VST-R чистить через #21.
- config-фикс `trading.min_sl_dist_pct: 0.5` добавлен (CONFIG-SLTP: inline дефолт был 0.1) — валиден, но не корень.
- DS закоммитил .agent_role fallback в check_tasks (4b22a0c) — ⚠️ общий файл .agent_role в корне: если Даат и DS делят репо, роль может конфликтовать. Проверить.

---

## [15.06.2026] Агент: Даат (Opus 4.8) — DISCUSSION-hook + гигиена TASKS

### ✅ Сделано
- **Stop-hook `scripts/check_tasks.py`** переписан: слушатель DISCUSSION для ролей **DAAT/DS** (ARCH/DEV/TRADER — алиасы, в отпуске). Парсит заголовки «Автор → Адресат», находит неотвеченные записи к роли/ALL → `block`. `sys.stdout.reconfigure(utf-8)` (Windows cp1251). Подключён в `.claude/settings.json` (Stop hook). Сразу поймал свежую `DS → Даат ✅ #7+#8 ML-аудит готов` — иначе пропустил бы.
- **Подсказки в approve:** BACKLOG (🔴/🟠) + задачи роли из табличного TASKS (строгий матч роли в 4-й колонке, `_ROLE_CELL`) + 🧹 детектор простыней (ячейка >200 симв → подсказка `tasks_tidy.py`). Сейчас 44 простыни.
- **TASKS компактный** (правило ≤80 симв): сжаты 4 свои секции-простыни (LISTENER/BUS-ACCOUNT/NOTIF/PERF). **Детали+коммиты НЕ потеряны** — полные карточки (метрики +4808R, 0.5% цикла, коммиты db9726d…) перенесены в `TASKS-ARCHIVE.md` (снимок 15.06).
- **Гигиена назначена DS** (постоянно, еженедельно): `AGENTS.md` → секция «🧹 Постоянная обязанность DS» (`tasks_tidy.py --apply`, формат, не терять коммиты) + установка hook с `AGENT_ROLE=DS`. Cron НЕ годится (recurring auto-expire 7 дней + session-only) → механизм через git-hook (живёт всегда).

### ✅ Сделано (продолжение)
- **TASKS реорг:** «Активные задачи» подняты под шапку (L235→L41), правила формата читаются первыми. Эпики/история — вниз. Бэкап `TASKS.md.bak_reorder`.
- **Гигиена прогнана** (DS + я): 561→423 строки, 6 уверенных ✅ в архив (LISTENER-CANON/DASH, BUS-L2-BRICK, NOTIF-MVP, TSL-CLEAN-TEST, PERF-DASH-THREAD). Реорг+tidy наложились без конфликта (но писали параллельно — впредь координировать, AGENTS #2).
- **#8 SIM-edge одобрен:** DS замерил (9/11 signal_type ↑ с `AND execution_mode='VST'`, 0 деградаций) → Даат подтвердил катку с тестом весов на копии БД + меткой активации. BACKLOG #8 → 🔄 (DS катит).
- **hook доказан трижды** (поймал #7+#8, поймал ответ DS при остановке, теперь approve).

### ✅ Рестарт 15.06 19:08 МСК (PID 24124) — фиксы в проде
- **Лог чист:** нет банов 100410, бот сканирует. `[DEV-52] лимит SHORT 25/25` + `router dropped` — l3_checker РАБОТАЕТ (фикс #2 виден в логе).
- **captured_R backfill добит:** 183 свежих нарушителя (на старом коде) → 0. Итог avg=34.3, min=0, max=100. Новые после рестарта пишутся clamp [0,100].
- **equity-кривая (`scripts/equity_curve.py`)** — посуточный реальный $ + data-era split. **Baseline ДО фикса: 793→631 = −162 (−20.4% за 3 дня)** (14.06 провал −271). ПОСЛЕ — эра только началась, наполнится за 2-3 дня → тогда замер эффекта фиксов.
- ⚠️ Минор в логе: `Сигнал liquidity_sweep не отправлен ни одному подписчику` (повторяется) — проверить NOTIF-подписку / TG-получателя.

### 🔜 Дальше
- **Через 2-3 дня:** `python scripts/equity_curve.py` → сравнить эру ПОСЛЕ с −20.4% ДО (сузился ли разрыв R↔$, перестал ли acc2 падать).
- DS катит фикс #8 в `performance_engine.by_signal_type[_ema]` → черкнёт хэш в DISCUSSION.
- Остаток гигиены: 44 простыни (ячейки >200 симв) + 17 ✅-под-заголовков в реестре — второй слой (DS/ручное). Детектор в hook напоминает.
- Рестарт бота (накоплено: #2 l3_checker, #6 captured_R, BUS-L2 позиции, SIM-TIME-EXIT) — рестарт делает юзер.

---

## [15.06.2026 ~02:10 UTC] Агент: Даат (Opus 4.8) — IP-бан 100410 при рестарте: 3 фикса (WS-залп+холодный старт)

### ✅ Сделано (6e7a006 + 7467f29)
- **Корень IP-бана при рестарте** (юзер: «до WS перезагрузки не банились»): 3 источника старт-залпа на один VPN IP (прокси не распределяют — медленные/cooldown):
  1. persist затирался холодным кэшем (periodic snapshot при Force-kill) → load≈0 → холодный REST-залп.
  2. rps=100 (overrides на 3 прокси) на один IP.
  3. 11 WS-соединений разом (market_ws.py:199).
- **3 фикса:** `save_to_disk(min_entries=1000)` guard (load тёплый 0→1653→1952), `api_rps 100→40`, `market_ws._connection` stagger idx×1.5с.
- **Тренд банов 12→4→2→~0**, persist самонастраивается (теплее каждый рестарт).
- НЕ прокси корень (работали раньше). VPN = постоянная среда (РФ).

### 🔬 Метод (3-я сага подряд на замерах)
- Отсеяны ложные гипотезы: ProcessPool (compute 0.5%), dashboard-нагрузка (OFF≈ON), прокси (работали раньше). Корень — WS-залп по зацепке юзера + grep.

### 🟢 Бот (рестарт нужен для финальной проверки фиксов)
- market_ws on (stagger), proxy on (rps=40), dashboard threaded, persist guard

### 🔄 Следующее
- Проверить баны→0 после рестарта на всех 3 фиксах
- DS нашёл «4 причины слива депозита» (DISCUSSION 00:25) — прочитать
- OHLCV-CACHE инструментация (be5510e) — увидеть REST per TF когда цикл стабилизируется

---

## [15.06.2026 ~00:10 UTC] Агент: Даат (Opus 4.8) — PERF: расследование GIL → dashboard в поток (вариант A)

### ✅ Сделано (33196ea + цепочка)
- **PERF-DASH-THREAD (вариант A)**: dashboard в отдельном потоке+loop за флагом `dashboard.threaded=true`. **Латентность /api/stats 7.5→0.3с, /api/pairs 11.4→0.25с (~30×)** под scan-нагрузкой. scan-цикл не пострадал, 0 cross-loop ошибок. SSE через `_broadcast_threadsafe` (call_soon_threadsafe мост).
- **LISTENER-CANON** (5d9cb97): NotificationDispatcher → подписчик шины. **LISTENER-DASH** (fdf750d): SSE метрики event-driven.
- **DS-325 Ф1+Ф2** принят (66b13ab, pydantic-схема).

### 🔬 Расследование perf (метод: замеры ДО кода)
- Гипотеза compute-GIL (ProcessPool, вариант B) → **опровергнута** (DS Ф1: WT+trend=0.5% цикла, pool медленнее sync). B мёртв.
- Гипотеза «dashboard грузит цикл» → **опровергнута** (эксперимент OFF: 282≈299с, в шуме).
- Реальный корень латентности dashboard 11с = **event-loop starvation** (HTTP ждёт очередь 522 scan-корутин) → вылечено вариантом A.
- Длина цикла ~290с = сам scan (REST-fetch 522×5TF) → market_ws/EXEC-WS (отдельная ось, в работе).
- **Ценность:** не влили ProcessPool-рефактор в scan_one и лишнюю dashboard-оптимизацию — 3 гипотезы отсеяны замерами.

### 🟢 Бот (PID 2172, рестарт 00:03)
- dashboard.threaded=true, dashboard.enabled=true
- LISTENER-CANON+DASH активны, market_ws v2 LIVE, EXEC-WS 2b

### ✅ Фронт: мигание dashboard MOCK↔LIVE убрано (oko-dashboard, НЕ под git)
- Корень: `useLive` (lib/use-oko-data.ts) сбрасывал на MOCK при любом сбое poll; `/api/stats` 7-11с на грани таймаута 12с → изредка abort → MOCK → «скачет».
- Фикс: после первого LIVE удерживаем данные (hasLiveRef), транзиентный сбой не мигает. + threaded dashboard 0.3с (запас до таймаута огромный). Next fast-refresh подхватит, обновить вкладку :3000.

### 🔄 Следующее
- Ось «длина цикла»: market_ws (OHLCV→WS) — главный IO-рычаг
- BUS-L2-BRICK (BalanceTracker), NOTIF-TIER2, DS-325 Ф3
- (опц.) полный SSE-push для dashboard вместо polling 10с

---

## [14.06.2026 ~22:40 UTC] Агент: Даат (Opus 4.8) — LISTENER-CANON Шаг 1 + DS-325 принят

### ✅ Сделано (5d9cb97)
- **LISTENER-CANON Шаг 1:** канонизирован единый listener-механизм через шину (Слой 2 роадмапа).
  - `PairContextBus.subscribe_async()` — sync→create_task адаптер, защищённая обёртка (изоляция, без «Task exception never retrieved»)
  - `sub_cube.compute_and_publish(current_price=)` — snap самодостаточен в шине
  - `NotificationDispatcher` подписан на `SMC_SNAP_UPDATED`, прямой вызов из scan_loop убран → 0 строк notif в ядре
  - Бот PID 13576 (22:26): «dispatcher подписан на шину» ✅, тест 3/3, 0 ошибок async-подписчика
- **Принцип:** scan_loop публикует → подписчики реагируют. Новый потребитель = +1 subscribe.

### ✅ DS-325 Ф1+Ф2 ПРИНЯТ (DS коммит 66b13ab)
- `core/infra/pydantic_config.py` (OkoConfig схема + ConfigProxy). Прогнал на боевом config.yaml: валидация чистая, 32 секции, orphan нет, ConfigProxy паритет. log-режим (strict=False) ✅.
- **2 хвоста на Ф3:** (1) config_validator.py физически не удалён (логика поглощена в pydantic, но старый ещё в load_config; pydantic спит — дубля-в-работе нет); (2) pydantic-settings в requirements избыточен (модуль юзает только pydantic). Ф3 (интеграция + удаление) — через меня (ядро).

### ✅ LISTENER-DASH Шаг 1 (fdf750d)
- SSE-метрики event-driven: `_metrics_version++` при закрытии сделки (auto/ручное/repair) → тяжёлый payload пересчитывается по версии+fallback 60с, не каждые 5с × N клиентов. per-client `_seen_version`.
- Бот PID 6936 (22:40): Dashboard запущен ✅, подписка notif ✅, 0 ошибок.
- Существующий `_handle_sse` переведён pull→push, фронт не тронут.

### 🔄 Следующее
- LISTENER-DASH Шаг 2: лента FVG/OB через `SMC_SNAP_UPDATED` push (новый UI-виджет, бэклог)
- `SubscriberHub`-реестр (теперь 2 подписчика — можно вырастить)
- BUS-L2-BRICK (BalanceTracker), NOTIF-TIER2, DS-325 Ф3

---

## [14.06.2026 ~21:30 UTC] Агент: Даат (Opus 4.8) — gear1 + Config validator + Repair API + BUS-ACCOUNT-EPIC спроектирован

### ✅ Сделано (коммиты ff3b029 + e2adf7f)
- **TSL gear1_be_atr=1.5** для ote_nested: `TSLProfile.gear1_be_atr` (default 1.0), BE активируется при +1.5 ATR. Хардкод `if mfe_atr>=1.0` убран → `>= profile.gear1_be_atr`. Рекомендация DS парного бэктеста (меньше резать 1-3R).
- **Config validator** (`core/infra/config_validator.py`): 15 правил тип+диапазон, вызов в `load_config()`, WARNING при аномалии. Проверено на боевом config — 0 проблем.
- **Repair API** (dashboard): `GET /api/repair/orphans`, `POST /api/repair/expire/{id}`, `POST /api/repair/expire_bulk` (older_than_hours) — архивация sim-only без скриптов.
- **Бот перезапущен** (PID был 28072 → 9680), валидатор отработал чисто.

### 🏛️ BUS-ACCOUNT-EPIC спроектирован (рой 2 раунда + DS)
- Расширить `PairContextBus` account/trader-измерениями (НЕ отдельный PortfolioBus). L1 PairState→L2 AccountState→L3 TraderState.
- Producer EXEC-WS push + REST fallback; доступ синглтон `get_bus()`; TraderState=async-подписчик.
- **Первый кирпич BUS-L2-BRICK:** BalanceTracker → AccountState → убирает REST-poll баланса + живой deposit.
- **Спор с роем:** Correlation Shield РАНЬШЕ Capital Allocator (Sharpe на фейк-R = усиление ошибки; сначала DATA-AUDIT-2).
- Дизайн закрыт, эпик в бэклоге. DISCUSSION [14.06 🏛️], TASKS → BUS-ACCOUNT-EPIC.

### 💡 Открытие про deposit_usdt
- Для VST/LIVE deposit УЖЕ живой (`get_available_balance()` → REST). Хардкод 710 бьёт только SIM + fallback + dashboard KPI. Реальные балансы: acc1=395$, acc2=377$, SUM=772$.

### 🔄 Следующее
- BUS-L2-BRICK (BalanceTracker) — когда займёмся
- NOTIF-TIER2, SSE realtime dashboard, EXEC-SIM-SPLIT

---

## [14.06.2026 ~20:40 UTC] Агент: Даат (Sonnet 4.6) — ARCH-130 + NOTIF-MVP

### ✅ Сделано
- **ARCH-130** (4d49074): `OhlcvCache.merge_dict` — replace-путь без `pd.DataFrame([r])`. Reader hot path чище, GIL-давление меньше.
- **NOTIF-MVP** (fbda2c8): `NotificationDispatcher` + `FvgDetectedListener` + `FvgTouchListener`. scan_loop = 1 строка `dispatcher.on_smc_snap`. `_norm_symbol` (ccxt↔YAML). Open/Closed: новый listener = новый файл, loop не трогаем.
- **CONFIG-SLTP-BUG** — закрыт ещё в 743cc64, верифицировано: merge работает при старте.
- **sem=12 эксперимент** — нестабилен (363-646s разброс), вернули sem=8. Baseline sem=8+WS ≈ 367s (−57s от старта сессии).

### 🟢 Бот работает (~20:40 UTC)
- sem=8, use_ws=true, sync_close=true, blacklist 4 пар
- ARCH-130 активен (merge_dict в reader)
- NOTIF-MVP активен (FVG уведомления XLM-USDT 3m LONG)
- EXEC-WS 2b: ok=True поток закрытий, ok=False = race condition (не критично)

### 🔄 Следующее
- NOTIF-TIER2: CHoCH/OTE/OB/Pivot listener'ы (бэклог, включать по одному)
- SSE realtime dashboard (убрать polling-мигание)
- EXEC-SIM-SPLIT (большой эпик, не сейчас)

---

## [14.06.2026 ~17:29 UTC] Агент: Даат (Sonnet 4.6) — MARKET-WS v2 ВАЛИДИРОВАН ✅

### ✅ Сделано (коммиты a98a130 + df0e0b5)
- **MARKET-WS v2 SHADOW РАБОТАЕТ**: `candles≈1252/s, errors=0`, 11 соединений, 526 пар. pid=27356.
- **Shadow без очереди** (df0e0b5): в shadow=True worker не кладёт свечи в Queue (только stats), нет QueueReaderThread → нет GIL overhead, нет overflow. LIVE режим (use_ws=true): батч-reader с дедупликацией (sym,tf) сохранён.
- **EXEC-WS 2b**: shadow логи `[EXEC-WS][2a] would write exch_id→... (SHADOW)` ✅. pa=0 событий не было (позиции не закрывались). `sync_close: false` → включить после наблюдения.
- **scan_semaphore_size: 5→8**, **SIM-DEPRIO: sim_check_interval_sec=300** — активны.

### 🟢 Бот работает (17:29 UTC)
- market_ws.enabled=true, use_ws=false (SHADOW Этап 1)
- EXEC-WS acc1+acc2 активны, order events идут
- scan_loop работает (semaphore=8)

### 🔄 Следующее
- Наблюдать EXEC-WS 2b: при закрытии позиции → `[EXEC-WS][2b] pa=0 (shadow)` → включить `sync_close: true`
- **CONFIG-SLTP-BUG** 🔴#1 (ARCH, осторожно): 26 параметров sl_tp_engine не читаются ботом
- Backlog: DS-325, STRATEGY-DISSECTION, EXEC-SIM-SPLIT

---

