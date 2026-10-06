# Current State - handoff между сессиями (проектный слой, git)

> Последние ~8 сессий. Старое -> `current_state_ARCHIVE.md` + git log.
>
> **АРХИТЕКТУРА ПАМЯТИ (15.06.2026, чтобы две памяти не расходились):**
> - auto-memory (`~/.claude/projects/.../memory/`) = HOT-слой Даата (auto-load): `MEMORY.md` индекс + личное (identity/vision). Эфемерно.
> - repo `memory/` (ЭТОТ путь, git) = SHARED: `current_state` (handoff, DS читает) + Gemini-outputs (`last_*`).
> - Правило: handoff -> СЮДА (git/DS); hot-recall индекс -> auto-memory. Не дублировать.

---

## [22.06.2026 00:53 UTC] Агент: Даат — ✅ ЧЕСТНЫЕ МЕТРИКИ В ДАШБОРДЕ ($-истина из income-ledger биржи)

- **Задача юзера:** «честные метрики в дашборде» (БД-realized R врёт ~$323/день, инвертирует знак — [[income_ledger_db_overstates_realized]]).
- **Решение:** новый авторитетный $-источник из биржевого `/openApi/swap/v2/user/income` (НЕ зависит от WS-capture 25%, НЕ от БД-R). 4 части:
  - `core/exchange/bingx_client.py` `get_income(start,end,limit,income_type)` — signed GET + пагинация по time (endTime=mn−1) + дедуп tranId, ≤20 страниц.
  - `core/exchange/order_manager.py` `get_income_per_account(start,end)` — агрегат по incomeType (REALIZED_PNL/TRADING_FEE/FUNDING_FEE/INSURANCE_CLEAR=liq/TRANSFER) per VST-аккаунт + net_trading.
  - `web/dashboard_server.py` `/api/income?days=7` (+`_INCOME_CACHE` TTL90с) — net/realized/fee/funding/liq per acc + total.
  - Фронт (НЕ git): `lib/api.ts fetchIncome`, `components/oko/income-truth.tsx` (панель «Exchange Truth», 7/30d toggle), на Overview под KPI.
- **Коммит бэкенда: e82ea4c.** Фронт собран (`npm build`) + pm2 restart oko-dash (PID 19992).
- **🔴 ЖИВАЯ ПРАВДА (7д VST):** acc1 net −941 + acc2 net −882 = **−1823 USDT/нед** (realized −1314, fee −279, liq −230). Сквозь прокси :3000→:8000 совпадает. БД-R показывала бы плюс. Стратегия реально глубоко в минусе — подтверждает income-ledger находку.
- **Деплой:** бот рестартнут (последний PID 7568, /api/income активен), дашборд pm2 (PID 19992).
- **+start/end на /api/income** (коммит 88cd1a2, по запросу DS): произвольное окно epoch ms (приоритет над days), ответ несёт start_ms/end_ms — для чистого post-fix data-era split. Проверено 2д-окном (net −1094, n=1740). **Реальный ts_fix** BE-синка для DS = коммит e762449 = 2026-06-20 20:12:53 UTC (epoch 1781986373000); handoff'овский «21.06 21:46 UTC» = БУДУЩЕЕ (часы в сессии скакали 12:39→00:53→01:06 — причина BingX timestamp-банов, проверить системные часы Windows).
- **🔧 ФИКС Stop-хука (check_tasks.py):** env `AGENT_ROLE=DS` просочился в МОЮ (Даат) сессию → хук считал меня DS, флагал мои же `Даат→DS` записи. Фикс: `.claude/settings.local.json` → `env.AGENT_ROLE=DAAT` (локально, не трогает DS/общий settings.json). `.agent_role`=DAAT был верен, перебивал env. Вступит на перезапуске сессии Claude Code.

---

## [20.06.2026 13:16 UTC] Агент: Даат — ✅ CUTOVER pid-fix (б): _resolve_exit_via_rest не угадывает при pid=None

- **Блокер CUTOVER снят** (коммит 4efe297). `sphere._resolve_exit_via_rest:253` при `position_id=None` матчил close by symbol+side → ЧУЖОЙ ордер → инверсия TP↔SL (fake-R класс). Фикс: `pid=None → return None` (эскалация watchdog) + строгий positionId-матч. Путь SHADOW (on_close=None) — живую торговлю НЕ трогает.
- Часть (а) handoff (positionId в store) **уже была** (open-fill enrich + cold-start get_positions). +тест `test_race_no_pid_no_guess`, 63/63 execution.
- ✅ Активирован рестартом (PID 22124, чистка stale-lock).
- **✅ CUTOVER-ФЛИП ГОТОВ за флагом** (коммит 37f1f7f): `config.yaml trading.exec_ws.sphere_cutover` (default **false**). true → Sphere авторитетен (on_close=build_close_applier) + ВЫКЛ exec_ws 2b sync_close + position_sync close-by-price (5 правок: config, exec_ws_integration ×3, position_sync). Орфан-детект не тронут. copy-DB смоук 6/6 MATCH, 57 тестов. **Прод НЕ меняется** (флаг off). Процедура флипа → whats-next.md item 2.
- ⏭️ **Дальше юзер:** валидация shadow-сверки (DS % WOULD CLOSE чистый) → флип (sphere_cutover:true + рестарт) → грепать [SPHERE-CUTOVER]/[db_writer]/2b-SKIP → сверка БД↔биржа. Откат=false. Потом EXIT-FIX (рычаг прибыли).

---

## [20.06.2026 12:39 UTC] Агент: Даат — ✅ Ф5 ДАШБОРД-КОГЕЗИЯ (приоритет №1 юзера): шапка↔таблица = один источник

### ✅ Сделано
- **Корень рассинхрона (экран Trades, Sim-режим):** шапка `stats` брала серверный `get_summary` (агрегат по ВСЕМ закрытым, БЕЗ status, без limit), а таблица — `get_trades` (фильтр по status + LIMIT 300). → (1) шапка игнорила активную вкладку (жмёшь SL — шапка считает все статусы); (2) «16000 trades» в шапке vs 300 строк.
- **Решение (юзер выбрал «истинные итоги + окно»):** шапка = настоящий агрегат по той же выборке (account+mode+**status**), таблица = последние ≤300 с честной подписью `showing X of N`.
- **Правки (3):**
  - `core/db/trades_repo.py` `get_summary(... , status=None)` — при конкретном закрытом статусе агрегирует `WHERE status=?` (иначе как было `IN(...)`). 🔴 СМЕНА СИГНАТУРЫ (3-й опц. параметр, обратно совместимо).
  - `web/dashboard_server.py` `_handle_trades_filtered` — передаёт `status` в `get_summary` (ключ кэша уже включал status).
  - `oko-dashboard/components/oko/screens/trades.tsx` — подпись `showing {filtered.length} of {stats.total}` (только sim, когда окно < N).
- **Проверка (runtime, read-only боевая БД):** 4/4 статуса MATCH с прямым COUNT; Σ по статусам 3064+19098+7421+1717=31300=ALL. SL: n=19098 WR18.5% −12704R (вкладка SL теперь честна).

### ✅ ДЕПЛОЙ + ПРОВЕРКА (12:55 UTC, та же сессия)
- `npm run build` ✅ compiled. Бот перезапущен (PID 30492 :8000), дашборд под **pm2** (oko-dash PID 10564 :3000, `pm2 save` → автоперезапуск).
- **Сквозная проверка до/после:** вкладка SL/VST было `summary.n=14135` WR45.2% (шапка игнорила вкладку) → стало `8154` WR27.7% (= ровно SL). Через прокси :3000→:8000 тоже 8154. **Шапка=вкладка.**
- **Orphan-аудит после рестарта** (`scripts/audit_missing_stops.py --only-missing`): 4 открытых поз, ВСЕ с SL, 0 голых, 0 untracked. Рестарт чист.
- ⚠️ **Грабли рестарта на Windows:** `Stop-Process -Force` НЕ вызывает atexit → stale `bot_instance.lock` (O_EXCL, [oko_mtf.py:56](oko_mtf.py)) блокирует новый инстанс («Бот уже запущен»). Лечение: удалить lock перед стартом (PID внутри мёртв). Лок НЕ детектит мёртвый PID — потенциальный TODO (проверять живость PID в локе).
- Не трогал `/api/kpi` (get_summary без status) — глобальный KPI намеренно по всем закрытым.

---

## [17.06.2026 21:23 UTC] Агент: Даат — 🟢 EXEC-SIM-SPLIT кирпич №1 реализован (shadow) + deposit-рассинхрон починен

### ✅ Сделано (всё за флагами, прогон main НЕ трогал — вступит при рестарте)
- **Направление принято консенсусом:** юзер → DS → рой (5/5). Путь «80/5» (НЕ полный 2-процессный split). Мерка лимита = риск-экспозиция % (не количество/маржа).
- **Кирпич №1 = риск-экспозиция gate PER-ACCOUNT** — расширение DEV-52 l3_checker (`core/trading/trade_simulator.py` ~1221, register = единая точка). Мерка `Σ(qty×|entry−sl|) открытых VST этого acc / equity_account`, equity из `balance_snapshots`. Shadow: `risk_gate_shadow: true`, cap `max_total_risk_pct: 10.0` (config.yaml l3_checker). Reuse gate-chain + shadow-механизм + Circuit Breaker by design.
- **Системный фикс депозита (юзер: «balance_snapshots = единый источник»):** `dashboard_server.py` risk_exposure = реальный риск/equity (не `n_vst×номинал`, врал ~5×); `config.yaml deposit_usdt` помечен SIM-номинал.
- **Проверка:** py_compile + runtime на КОПИИ subscriptions.db. acc2 9.7%+1%=10.7% > cap → WOULD_BLOCK ловится; acc1 0.8% pass. Дашборд: реальный 5.8% / equity 307.

### 🔴 SHADOW ВСКРЫЛ (главная находка)
- Риск по стопам ЗДОРОВ (acc1 0.8%, acc2 9.7%) — ruin не грозит.
- **Реальная боль = МАРЖА 87% used на ОБОИХ акк** (available ~22) → корень margin-reject фантомов + риск ликвидации. **Margin pre-check (отложенный 2-й слой) ОСТРЕЕ кирпича №1.**
- **Deposit 4 рассинхрона:** config 710 ∥ user_settings ПУСТ→1000 ∥ реальный equity 316 ∥ VST sizing от availableMargin ~22 (падает при занятой марже = порочный круг).

### ✅ Кирпич №2 (margin pre-check) — тоже реализован (shadow, 21:35 UTC)
- Корень фантомов (аудит `trade_router.py:167,203`): register пишет SIM ДО `_place_exchange_order`; `open_bracket` margin-fail → запись остаётся SIM = фантом. Кирпич №2 ловит ДО register.
- Рефактор DEV-52: общий lookup (account+equity+available из balance_snapshots) → 2 gate. Кирпич №2: `available_per_account < min_available_usdt` → `[DEV-52][MARGIN]`. Config `min_available_usdt: 5.0`, `margin_gate_shadow: true`. Runtime OK (acc1 avail70 pass, acc2 avail16 pass; сработает при <5).

### ✅ ВАЛИДИРОВАНО В ПРОДЕ (18.06 00:42, shadow)
WHITEWHALE acc2 дал ОБА would_block одновременно: `[DEV-52][RISK]` 12%>10% + `[DEV-52][MARGIN]` avail=2.8<5 USDT — ровно сценарий фантома (avail исчерпана, сделка всё равно зарегалась shadow = будущий SIM-фантом). Кирпич №1 ловит acc2 у потолка, №2 ловит критич. маржу. Количественный DEV-52 тоже блокирует (`SHORT 31/25`, enabled). Ошибок DEV-52 нет. available колеблется 2.8↔70.

### ✅ ДАШБОРД-ФИКСЫ + АУДИТ (18.06, та же сессия)
- **R −3.28R баг ПОЧИНЕН** (коммит d51b26f): `_handle_live` матчил SL/TP позиции с sim по symbol БЕЗ direction → SHORT хватал закрытую LONG → R-мусор. Фикс: ключ `(symbol, direction)` + ORDER BY OPEN/свежесть. UB SHORT → правильный SHORT SL, R≈−0.44 вместо −3.28.
- **Аудит «подобных багов»:** критичных больше нет (торговая логика с direction). 2 мелких ПОЧИНЕНЫ: `position_manager.get_by_symbol` +side (мина), `api.ts fetchLivePositions` regime из бэка (был хардкод RANGE).
- **Бриф для bot-data-audit:** `docs/AUDIT_DATA_INTEGRITY_BRIEF.md` — запустить субагент в СВЕЖЕЙ сессии (глубокий аудит: core/exchange рассинхрон, db-repos, семантика полей).
- ⚠️ api.ts (oko-dashboard) НЕ git — backend-фиксы закоммичены, фронт отдельно. Вступит после рестарта.
- **+balance-фикс (коммит 7965967):** `_handle_live` `float(result["balance"])` падал когда balance=dict → KPI equity/risk_pct не считались (22× с 00:32, баг СУЩЕСТВОВАЛ ДО сессии). Достаём equity из dict. ⚠️ нужен ЕЩЁ ОДИН рестарт чтобы этот фикс вступил (предыдущий рестарт 03:32 был до него). Не критично (бот жив, KPI fallback).

### ⏭️ NEXT
0. **Запустить `bot-data-audit`** с `docs/AUDIT_DATA_INTEGRITY_BRIEF.md` (свежая сессия).
1. ✅ Рестарт сделан, оба gate в проде (shadow). Накопить распределение (часы/дни).
2. Собрать распределение → активация (`risk_gate_shadow: false`, `margin_gate_shadow: false`) + уточнить пороги.
3. Альтернатива margin (мощнее, обсудить с DS): не оставлять SIM при open_bracket margin-fail в trade_router (бить фантом в точке reject).
4. Backlog: VST sizing-base (availableMargin → equity?) — корень деградации при занятой марже.
→ детали memory `exec_sim_split_epic.md`, DISCUSSION 17.06 21:23.

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

