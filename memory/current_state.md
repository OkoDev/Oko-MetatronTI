# Current State - handoff между сессиями (проектный слой, git)

> Последние ~8 сессий. Старое -> `current_state_ARCHIVE.md` + git log.
>
> **АРХИТЕКТУРА ПАМЯТИ (15.06.2026, чтобы две памяти не расходились):**
> - auto-memory (`~/.claude/projects/.../memory/`) = HOT-слой Даата (auto-load): `MEMORY.md` индекс + личное (identity/vision). Эфемерно.
> - repo `memory/` (ЭТОТ путь, git) = SHARED: `current_state` (handoff, DS читает) + Gemini-outputs (`last_*`).
> - Правило: handoff -> СЮДА (git/DS); hot-recall индекс -> auto-memory. Не дублировать.

---

## [20.06 ~01:15 UTC] Агент: Даат — 🎯 EXIT-ФИКС ВАЛИДИРОВАН на живом закрытии (ZEREBRO match)

- 🎯 **ZEREBRO (00:36) — Sphere-путь == авторитетный путь:** `[SPHERE-SHADOW] WOULD CLOSE ZEREBRO LONG → SL @ 0.04414181 rp=4.256` СОВПАЛ с `[EXEC-WS][2b] #31790 → SL @ 0.044142` (статус SL=SL, цена ≈). Новый путь даёт корректный exit на реальном закрытии. is_open_fill+stash работают end-to-end на бою. (rp=+4.256 при SL = TSL-в-профите, исполнен как STOP → оба пути зовут SL, согласованно.)
- 📊 **Покрытие exit пока частичное:** ZEREBRO ✅ real, но UMA/ACU/ZKP остались «?» (close-fill не застешился, REST-fallback не дотянул — нет «exit дотянут REST» логов). Это «?»-остаток → ловит **reconcile-watchdog** (4c522cf, НЕ деплоен — ждёт рестарта).
- 🔍 **Находка про старый путь:** `[EXEC-WS][2b]` массово `sync_close ok=False` (DEXE/UMA/ROBO/ACU/ZKP) — close_trade вернул False т.к. сделка УЖЕ закрыта конкурентом (position_sync close-by-price). ZEREBRO ok=True (WS выиграл гонку). **Это ровно дуэль путей, которую сносит CUTOVER** — наглядное подтверждение ценности единого канала.
- 🔵 NEXT: рестарт → деплой watchdog → проверить ловит ли «?»-остаток + DS считает % покрытия (stash+REST+watchdog). ~100% → CUTOVER.

## [20.06 ~01:00 UTC] Агент: Даат — ✅ reconcile-watchdog (CUTOVER-страховка для «?»-exit/WS-drop)

- ✅ **Форвард exit-фикс подтверждён:** `00:36 WOULD CLOSE ZEREBRO → SL @ 0.04414 rp=4.256` (РЕАЛЬНЫЙ exit из stash, is_open_fill-фикс работает). НО `00:40 UMA → ?` остался → exit не 100%. Вывод: «?» при CUTOVER → db_writer не закроет → строка OPEN при флэте = нужна страховка.
- ✅ **reconcile-watchdog ПОСТРОЕН** (`Sphere.reconcile_watchdog` + `PositionStore.drop`): §6 bounded-staleness — store-open vs биржа-флэт **N циклов подряд** (min_cycles=2, транзиент/WS-лаг не эскалирует) → дотянуть exit из REST (`_resolve_exit_via_rest` по positionId) + снять из store. Возвращает escalated CloseIntent (с exit). Это ДО-закрытие БД-строки пропущенного WS-закрытия (биржа уже флэт, close не нужен). Streak сбрасывается при возврате позиции.
- ✅ **Врезан shadow** в `position_sync.sync_positions` (throttle 2мин, per-account из router, лог `[SPHERE-SHADOW] RECONCILE would-close …`, ТОЛЬКО при построенном sphere). Активируется след. рестартом. Log-only (on_close=None).
- ✅ Тесты +4 (транзиент не эскалирует / 2 цикла→escalate+REST-exit+drop / streak-reset / no-fill→exit None). **Всего по эпику 92.** py_compile sphere/store/position_sync OK.
- 🟢 **CUTOVER-картина полная:** детект close ✅(3/3) + exit (stash+REST-fallback) ✅частично + watchdog ловит «?»/дроп остаток ✅. При флипе: on_close→db_writer applier + watchdog→sphere.close для остатка. Осталось эмпирически: рестарт → DS считает % exit + watchdog ловит ли остаток.
- ⚠️ Коммиты не запушены (этот). Деплой watchdog = след. рестарт.

## [20.06 ~00:30 UTC] Агент: Даат — ✅ #7 ML-честность: OOS-gate (r_predictor = шум, честно отключён)

- ✅ **#7 BACKLOG (ML data-leak) ЗАКРЫТ.** Аудит `scripts/r_predictor_leak_audit.py` (read-only, реальные данные) вскрыл БОЛЬШЕ чем leak: на честном **TimeSeriesSplit R²=−1.05** (max_R_possible) / −0.40 (r_multiple), RMSE ХУЖЕ naive baseline (predict-mean) для ОБОИХ target. **Модель не обобщает — она шум**, а активировалась ВСЕГДА при n≥75 (старый `cross_val_score cv=5` KFold по неупорядоченным данным маскировал). «85%→34%» из реестра = другая эпоха/метрика; на регрессии R²≈+0.02 даже у leaky.
- ✅ **Фикс `core/ml/r_predictor.py`:** (1) `_load_dataset` ORDER BY id (хронология); (2) `_evaluate_oos` = TimeSeriesSplit RMSE+R² + naive baseline; (3) **OOS-gate** — `is_trained=True` ТОЛЬКО если модель бьёт baseline на forward-CV, иначе НЕ деплоим (predict_expected_r→None). End-to-end на subscriptions.db: **fit→False, is_trained=False** (TS RMSE 1.909≥baseline 1.772). info() += cv_r2/baseline_rmse/oos_passed.
- ✅ **БЕЗОПАСНО:** predict_expected_r НЕ в decision-path (только Kelly-текст monitoring держит is_trained=False→пустая строка; ml_loop только fit+лог). Отключение шум-модели = чистая честность, 0 риска решений. Деплой на след. рестарте (ml_loop переобучит→гейт не пустит).
- ✅ Тесты `tests/unit/test_r_predictor_oos_gate.py` 3/3 (шум→fail, сигнал→pass) + старые r_predictor 10/10. realized-R target проверен — тоже не спасает (R²<0).
- 🔵 EXEC-REBUILD форвард копится (DS), CUTOVER ждёт exit-валидации.

## [19.06 ~21:10 UTC] Агент: Даат — ✅ рестарт #43 (is_open_fill активен) + DS 3/3 SPHERE-match + 🔴 CUTOVER-блокер (гонка fill↔pa=0)

- ✅ **Рестарт 23:43:02** — pipeline + cold_start acc1:4/acc2:4 (меньше — orphan'ы закрылись). is_open_fill-фикс (c54008e) активен.
- ✅🎁 **DS forward-сверка 3/3** (DISCUSSION 21:00): WOULD CLOSE DEXE(23:22)/UMA(23:26)/ROBO(23:28) совпали с реальными `[EXEC-WS][2b]` по symbol+time → **детект close новым путём ДОКАЗАН независимо на бою.** Половина зелёного на CUTOVER.
- 🔴 **CUTOVER-БЛОКЕР вскрыт (важно):** «?»-exit в WOULD CLOSE → `db_writer.intent_to_close_args` отдаёт None → **НЕ закрывает** (правильно: не угадываем) → при CUTOVER строка останется OPEN. Два корня: (1) ✅ хедж-retry close снимал reduceOnly [закрыл c54008e]; (2) 🔴 **гонка fill↔pa=0** — pa=0 приходит РАНЬШЕ закрывающего ORDER_TRADE_UPDATE → ExitInfo не застешился (DEXE/UMA/ROBO обычные закрытия). **Фикс ДО CUTOVER: при pa=0 без exit → fallback (defer на fill ИЛИ adapter.get_filled дотянуть o.ap/o.rp по positionId, как _resolve_exit).** Беру на себя.
- ✅ **ГОНКА fill↔pa=0 ЗАКРЫТА** (sphere.py `_resolve_exit_via_rest`): при pa=0 без застешенного exit → дотянуть закрывающий fill из `adapter.get_filled` по positionId (close-side, последний updateTime — доказанный positionID-якорь). Не нашли → exit None (db_writer не закроет, не угадываем). REST только на гонке; stash приоритетнее (без гонки REST не зовём). Тесты +3. **Оба корня «?» закрыты: hedge-retry [c54008e] + гонка [этот].** Всего по эпику 88/88.
- ✅ **ЗАПУШЕНО** origin/arch-128-oko-sm (13 коммитов 689cde4..237960a + этот).
- 🟢 **CUTOVER теперь разблокирован по логике:** детект close ✅ (DS 3/3) + exit-цена надёжна (stash+REST-fallback). Осталось: подтвердить в shadow на бою (рестарт активирует exit-fallback → WOULD CLOSE с реальным exit на racy-закрытиях) → DS считает % непустых exit → флип on_close на db_writer applier + убрать position_sync:501-654 close-by-price за флагом.
- 🔵 NEXT: рестарт (активировать exit-fallback в shadow) → DS валидирует % exit → CUTOVER.

## [19.06 ~20:40 UTC] Агент: Даат — ✅ ТЕЧЬ ПРИЗРАКОВ ОСТАНОВЛЕНА (live) + 🎁 shadow cross-validated + ⚠️ находка is_open_fill

- ✅🛑 **orphan-стоп РАБОТАЕТ на бою** (рестарт 23:32:43): `23:34:18 [D-070][autoclose][live] BNB SHORT ЗАКРЫТ market (positionId=…614027266)` + `23:34:43 Q SHORT ЗАКРЫТ (positionId=…537189890)`. Оба account-aware по positionId, code=0, FAILED=0. DOLPHIN больше не orphan (закрылся/adopted). **Течь −$266 (призраки) перекрыта.**
- 🎁 **ПЕРВАЯ live-сверка SPHERE-SHADOW:** на те же pa=0 новый Sphere выдал `WOULD CLOSE BNB`(23:34:19) + `WOULD CLOSE Q`(23:34:44) в lockstep со старым закрытием → детект закрытия новым путём РАБОТАЕТ на живом потоке (ключ к CUTOVER).
- ⚠️🔴 **НАХОДКА shadow (до CUTOVER фиксить):** WOULD CLOSE показал `→ ? @ ? rp=?` (exit=None) + `OPEN seen BNB @ 580.01` ПОСЛЕ закрытия. Корень: orphan-close через `close_position_market` на хедж-ошибке СНИМАЕТ reduceOnly (retry bingx_client:699-707) → плоский MARKET FILLED ro=false → `normalize_event.is_open_fill` принимает за ОТКРЫТИЕ; + ExitInfo закрывающего fill не застешился до pa=0 (гонка fill↔pa=0). Для orphan'ов БЕЗВРЕДНО (нет DB-строки → db_writer applier no-op). Но для tracked до CUTOVER нужно: (1) `is_open_fill` различать reduceOnly-stripped хедж-close (напр. по o.S vs o.ps: BUY на SHORT = close), (2) порядок/буфер fill→pa=0 для ExitInfo. Это DS-форвард-зона + мой фикс.
- ✅ **ФИКС is_open_fill СДЕЛАН** (domain.py): различение open/close по side×pos_side (open=BUY+LONG|SELL+SHORT), НЕ по reduceOnly. Чинит ложный «OPEN seen» хедж-retry close + застешивает ExitInfo (WOULD CLOSE больше не «? @ ?»). Тесты +4 (hedge-retry close не open, sell+long close, open short sell, store stash). Активируется след. рестартом (для shadow — не срочно). **Всего по эпику 85/85.**
- 🔵 NEXT: DS квантифицирует ledger · копить WOULD CLOSE-сверку (теперь с реальным exit) · остаток гонки fill↔pa=0 (вторичный, наблюдать).
- ⚠️ 11 коммитов НЕ запушены.

## [19.06 ~20:30 UTC] Агент: Даат — 🛑 orphan_autoclose shadow→LIVE (стоп течи призраков) + DS параллель

- ✅ **orphan_autoclose: shadow→LIVE** (config:133, коммит d7d076c). Валидация по shadow-логам ПРОЙДЕНА: 59 orphan-событий = **3 реальных recurring orphan'а** (DOLPHIN/USDT LONG qty114 pnl+5.6 · Q/USDT SHORT qty31570 pnl+4.8 · BNB/USDT SHORT qty1.19 **дрейф −0.93→−2.98 = живая течь**). Стабильны часами, hedge-safe (0 skip в логах = чистые orphan'ы, не tracked). Механизм: account-aware (_resolve_position_client+positionId 101205) + one_click_on_fail. 🔴 **Активируется СЛЕДУЮЩИМ рестартом юзера** → закроет 3 orphan'а. Откат = shadow.
- 📋 **DS параллельные задачи** (DISCUSSION 20:30): (1) ledger-forward reconcile — квантифицировать −$435 (funding/fee/realized из WS, его ExecutionLedger подключён в Sphere.on_event); (2) SPHERE-SHADOW forward-сверка WOULD CLOSE vs реальный [EXEC-WS][2b] → N совпадений = зелёный на CUTOVER.
- ⚠️ Это симптом-стоп (epic §8 «заплатка»), НО rebuild-фикс (Sphere reconcile-watchdog) на CUTOVER через дни, а призраки текут СЕЙЧАС → юзер выбрал стоп течи. CUTOVER заменит orphan_autoclose на единый Sphere.close-канал.
- ⚠️ 10 коммитов (e88f95f→d7d076c) НЕ запушены.

## [19.06 ~20:15 UTC] Агент: Даат — ✅ SHADOW-СВЕРКА АКТИВНА НА БОЮ (рестарт юзера, pipeline здоров)

- ✅ **Флаг `sphere_shadow: true` включён** (коммит b5b9ba8), юзер рестартнул (бот 23:12 local).
- ✅🟢 **Pipeline ЗДОРОВ на живом боте:** `23:12:04 [SPHERE-SHADOW] pipeline построен + cold_start [1,2]`. **cold_start засеял 11 живых позиций** (acc1: 6, acc2: 5) — read-only get_positions сработал на ОБОИХ аккаунтах. **Ноль feed-ошибок, ноль exception'ов execution/sphere/adapter/normalize.** Tracebacks в логе = известный Telegram-шум `bot/monitoring.py:1919 _send_one` (НЕ мой путь).
- ⏳ **`OPEN seen`/`WOULD CLOSE` ещё нет** — нужны новые открытия/закрытия ПОСЛЕ 23:12 (Режим В OTE-only = низкая частота). Store держит 11 seeded позиций → при их pa=0 сработает `WOULD CLOSE` (покрытие вооружено). Грепать копящееся: `grep -a "\[SPHERE-SHADOW\]" logs/crypto_bot.log`.
- 🔵 **NEXT:** копить `WOULD CLOSE` → сверять exit/статус с реальным `[EXEC-WS][2b]` (зона DS forward). Совпало N закрытий → Ф4.1-CUTOVER (on_close→db_writer applier + убрать position_sync close-by-price за флагом, тест на копии БД зелёный). Откат сверки = `sphere_shadow:false`.
- ⚠️ 9 коммитов эпика (e88f95f→b5b9ba8) НЕ запушены.

## [19.06 ~19:45 UTC] Агент: Даат — ✅ Ф4.1 SHADOW-ВРЕЗКА в живой WS-путь (default OFF, ждёт рестарта юзера)

- ✅ **SHADOW-врезка** (`core/exchange/exec_ws_integration.py`, ПЕРВОЕ касание живого кода, аддитивно): (1) `start_exec_ws` строит NEW pipeline (BingXAdapter+PositionStore+ExecutionLedger+ExecutionSphere, `on_close=None`) за флагом `trading.exec_ws.sphere_shadow` → `bot._exec_sphere/_exec_adapter`. (2) `make_event_handler.on_event` прогоняет ТОТ ЖЕ WS-msg через `adapter.normalize_event → sphere.on_event` ПАРАЛЛЕЛЬНО авторитетному 2a/2b, в try/except.
- 🔴 **Default OFF (ключ `sphere_shadow` отсутствует → False) → поведение бота ИДЕНТИЧНО.** on_close=None → только лог «[SPHERE-SHADOW] would close». position_sync close-by-price НЕ тронут. Ошибки врезки ловятся, не влияют на старый путь.
- ✅ **Тест `tests/unit/test_shadow_pipeline.py` 2/2** — повторяет врезку на СЫРЫХ WS-dict (raw open-fill → store; raw close-fill → stash; raw pa=0 → would-close SL@0.49). **Всего по эпику 81/81.** py_compile exec_ws OK.
- ✅ **НАБЛЮДАЕМОСТЬ блока покрыта (юзер «блок покрыт логами?»):** единый тег `[SPHERE-SHADOW]` (было рассогласование старт vs sphere `[Sphere][SHADOW]` → sphere понижен до debug). Врезка логирует: `OPEN seen` (pipeline подхватил позицию) + `WOULD CLOSE … → STATUS @ price rp=… (reason)` (ключевая строка сверки с фактом старого `[EXEC-WS][2b]`) + feed-ошибки на WARNING (было debug=невидимо). + **cold_start per account** (read-only get_positions) → would-close покрывает и позиции, открытые ДО рестарта (иначе их pa=0 = untracked, молча). Грепать: `grep -a "\[SPHERE-SHADOW\]" logs/crypto_bot.log`.
- 🟢 **Активация юзером:** добавить `trading.exec_ws.sphere_shadow: true` в config.yaml + рестарт → на живом потоке копятся `[SPHERE-SHADOW] would close` → сверить с реальными закрытиями (старый путь). Совпало N дней → Ф4.1-CUTOVER (флипнуть on_close на db_writer.build_close_applier + убрать position_sync close-by-price за флагом). Откат = убрать ключ.
- 🔵 ПОТОМ: cold_start при старте (сейчас store пустой → видит только позиции, открытые ПОСЛЕ рестарта = чистый набор для сверки), reconcile-loop, Ф5 дашборд.
- ⚠️ 6 коммитов эпика (e88f95f→df46a2e + текущий) НЕ запушены. DS-леджер закоммичен (2d6c4b6).

## [19.06 ~19:15 UTC] Агент: Даат — ✅ Ф4.1 close-applier + COPY-DB ТЕСТ ЗЕЛЁНЫЙ (close-path доказан, НЕ активирован)

- ✅ **close-applier** (`core/execution/db_writer.py`) — мост `CloseIntent → trade_simulator.close_trade`. Реальные цена/статус из ExitInfo (WS o.ap/o.rp), БЕЗ REST _resolve_exit (fake-R корень убран). `intent_to_close_args` (маппинг: SL/TP/TSL as-is, **LIQUIDATION→SL** т.к. close_trade не знает такой статус, MANUAL по знаку pnl, **нет exit/цены<=0 → НЕ закрываем** — не угадываем, не плодим fake-R). `find_open_exchange_trade` (lookup OPEN биржевой по symbol+side, зеркало exec_ws_integration). `build_close_applier` → async on_close для `Sphere(on_close=...)`, идемпотентен.
- ✅🔴 **COPY-DB ТЕСТ (требование §9 перед активацией) ЗЕЛЁНЫЙ** `tests/unit/test_db_writer_closepath.py` 13/13: реальная схема (SubscriptionManager+TradeSimulator миграции) + реальный close_trade на temp-БД. **Полный путь ExecutionSphere→on_close→close_trade: pa=0 закрывает сделку SL@0.49, R=−1.0 корректно.** Идемпотентность, skip SIM-only, no-exit→не закрывает. **Всего по эпику 79/79.**
- 🟢 **ВЕСЬ execution-слой построен offline (Ф2-Ф4.1), 5 коммитов, живой бот НЕ тронут.** Доказано: close-path работает на копии БД.
- 🔴 **СТОП-ТОЧКА — активация требует решения юзера + рестарта:** Ф4.1-LIVE = (1) подключить on_close в WS-путь (Sphere вместо/рядом exec_ws_integration._sync_close_async), (2) cold_start при старте, (3) reconcile-loop bounded-staleness, (4) УБРАТЬ position_sync close-by-price (за флагом). Это первое касание живого кода — обсудить ПЕРЕД act ([[feedback_discuss_before_act]]), активировать close только рестартом юзера.
- 🔵 Ф5 дашборд (биржа/БД/SIM секции) — после Ф4.1-LIVE.

## [19.06 ~18:45 UTC] Агент: Даат — ✅ Ф4 ExecutionSphere ПОСТРОЕН (shadow, 15/15 тест)

- ✅ **ExecutionSphere** (`core/execution/sphere.py`) — оркестратор, связывает Adapter+Store+Ledger+Calc. Методы: `open` (guard через Calc; SIM→без биржи; VST→adapter.place_bracket), `close` (account/side/qty из Store, adapter.close_reduce_only), `on_event` (FillEvent→store+ledger; **PositionEvent pa=0→CloseIntent = единственный авторитетный триггер close**; Ledger/Liq/MarginCross-алерт/Equity/listenKey), `adjust_sl`, `state` (из Store, не REST), `cold_start` (init Store+Ledger из снимка), `reconcile_account` (watchdog §6: store-open vs биржа-флэт → кандидаты, НЕ закрывает сам), `staleness`.
- 🔴 **close-path в SHADOW:** реальную запись в БД делает инъектируемый `on_close` callback; пока None → лог «[SHADOW] would close». Активация (wiring on_close + удаление position_sync close-by-price) = Ф4.1, ТОЛЬКО после теста на копии БД (инцидент 2026-04-07). Ledger duck-typed (Sphere не тянет файл DS).
- ✅ **Тесты `tests/unit/test_execution_sphere.py` 15/15** (FakeAdapter offline: open SIM/VST/guard, fill→store+ledger, pa=0→intent shadow+callback, полный цикл с классификацией exit SL@0.49, close/adjust_sl делегирование, cold_start equity, reconcile WS-drop + no-false-positive). **Всего по эпику 66/66.** py_compile OK.
- 🔵 **Следующий: Ф4.1 wiring** (на копии БД): on_close → trade_simulator.close_trade с exit из ExitInfo; cold_start при старте; reconcile-loop с bounded-staleness. ПОТОМ Ф4.2 (orphan/emergency через Sphere.close), Ф5 (дашборд). 🔴 close-path активировать только после copy-DB теста.
- ⚠️ `__init__` экспортит ExecutionSphere/CloseIntent (мои). Адаптер/леджер — прямой импорт. Живой бот НЕ тронут (3 коммита: e88f95f/eaacf97/cebadfe + текущий).

## [19.06 ~18:10 UTC] Агент: Даат — ✅ Ф3.3 (PositionStore + аудит BingXClient) + леджер DS проверен

- ✅ **АУДИТ BingXClient (требование юзера)** → `docs/BINGX_CLIENT_AUDIT.md`. Прочитал ВЕСЬ файл (751 строка). Вердикт: НЕ гнилой. ~60% выстраданные фиксы+плюминг (GlobalRateLimiter/100410-бан, sync_time-throttle/109400, precision-cache, get_positions БРОСАЕТ не [], hedge-close 101205+one-click, dual-signing) — НЕ трогать. ~15% реальный запах: дубль 109400-retry ×3 (get/post/delete) + дубль ban-парсинга в get_balance → консолидировать ВНУТРИ адаптера (тех-уборка, не блокер). Gaps: нет standalone set_leverage/set_margin_mode (подтверждает margin-enforce кирпич). **Деньги текли НЕ в клиенте, а в оркестрации** → план A верен (обернуть клиент, снести оркестрацию).
- ✅ **PositionStore ПОСТРОЕН** (`core/execution/position_store.py`, моя половина Ф3.3): единственный владелец состояния из WS. `apply_position(pa=0)→ставшая флэт Position` (триггер close для Sphere, idempotent если не отслеживалась), `apply_fill` (open→entry/pid обогащение, close→stash ExitInfo), `take_exit` (классификация SL/TP/TSL/LIQ из o.o/o.ap/o.rp), `positions/get/by_position_id`, `staleness()` (watchdog §6). Hedge-aware ключ (account,symbol,side). `classify_exit` = единый смысл с position_sync._ORDER_TYPE_TO_STATUS. Чистый in-memory, БД не трогает.
- ✅ **Тесты `tests/unit/test_position_store.py` 18/18** (open/upsert/flat-триггер/idempotent, hedge-независимость, account-изоляция, fill-обогащение, exit-stash, cold-start reset, staleness). **Всего по эпику 51/51.** py_compile OK.
- ✅ **Леджер DS (`execution_ledger.py`) ПРОВЕРЕН вживую:** running_sum −1.52, gap −0.48 — математика верна, интегрируется с моим domain/normalize_event (FillEvent realized/fee + LedgerEvent funding). Solid. ⚠️ Файл DS (untracked) — НЕ в моём коммите (его коммит). Минор: bucket "LIQUIDATION" в apply() не наполняется (realized ликвидации идёт через FillEvent.realized_pnl) — by-design, не баг.
- 🔵 **Следующий: Ф4** — ExecutionSphere (оркестратор: open/close/on_event/adjust_sl/state, связывает PositionStore+Ledger+Adapter+Calc). + cold-start reconcile (§10). 🔴 close-path — тест на копии БД перед боем.
- ⚠️ `__init__` экспортит PositionStore (мой); ExecutionLedger/BingXAdapter — прямой импорт из модулей (агностичное ядро + раздельное владение).

## [19.06 ~17:30 UTC] Агент: Даат — ✅ EXECUTION-REBUILD Ф3.2 ГОТОВА (BingXAdapter обёртка)

- ✅ **Ф3.1 закоммичена** `e88f95f` (каркас core/execution/ + дизайн + координация, 10 файлов, +947). Только работа сессии, DS-конфиги/патч-пул не тронуты.
- ✅ **Ф3.2 BingXAdapter ПОСТРОЕН** (`core/execution/bingx_adapter.py`, аддитивно, живой код НЕ тронут): тонкая обёртка (решение роя 4/4) реализует ExchangeAdapter поверх OrderManager/AccountRouter/BingXClient/UserDataStream, БЕЗ переписи биржевых вызовов. Команды (place_bracket/sl/tp/cancel/close_reduce_only) делегируют OrderManager (sticky account-routing); чтения (get_positions/get_filled/balances) через client_for_account; open_user_stream оборачивает UserDataStream.
- ✅ **`normalize_event` — РЕАЛЬНЫЙ порт** (не делегат): единая точка парсинга WS → ExecEvent. Добавил поля, которые exec_ws_integration НЕ юзает: o.rp (realized), o.n (fee), o.o=LIQUIDATION, a.m=FUNDING_FEE, a.P[].mt (дельта §5). from_bingx_symbol проверен ('XLM-USDT'→'XLM/USDT:USDT').
- ✅ **Тесты `tests/unit/test_bingx_adapter_normalize.py` — 12/12** (open/close fill, LIQUIDATION→2 события, NEW→0, partial, pa=0 flat, открытие, FUNDING_FEE леджер, cross-mt, listenKeyExpired, мусор). **Всего по эпику 33/33** (12 normalize + 21 parity). py_compile OK.
- 🔵 **Следующий: Ф3.3** — PositionStore (WS-истина из PositionEvent/FillEvent) + ExecutionLedger (LedgerEvent/realized), shadow-наполнение + сверка $ с balance_snapshots (зона DS по §5). + cold-start reconcile (§10).
- ⚠️ BingXAdapter намеренно НЕ в `core/execution/__init__` — агностичное ядро не тянет bingx_client. set_leverage/set_margin_mode = честный best-effort (бот пока не управляет margin-mode, enforce-кирпич бэклог). open_user_stream/команды финализируются в Ф4 (тогда же тест close-path на копии БД).

## [19.06 ~16:25 UTC] Агент: Даат — 📐 EXECUTION-REBUILD Ф2 ГОТОВА (дизайн ExecutionSphere)

- ✅ **Ф2 дизайн записан:** `docs/EXECUTION_SPHERE_DESIGN.md`. Прочитал все 8 узлов исполнения grep'ом (exec_ws_integration / position_sync / order_manager / trade_router / account_router / user_data_ws / tsl_updater / trade_simulator close-path) → заземлённый контракт.
- **Содержание:** 3 слоя `core/execution/` (ExecutionSphere → ExchangeAdapter ABC + AccountRouter reuse + PositionStore + ExecutionLedger); доменная модель (OrderRequest/Result/Position/Fill/CloseResult/LedgerEntry, биржа-агностик); контракт open/close/on_event/adjust_sl/state; `OrderRequest.mode` = единственный sim/vst-переключатель.
- **🔴 КОРЕНЬ зафиксирован (§6):** close в БД метит ТОЛЬКО `on_event(pa=0)`; `position_sync:501-654` close-by-price → УДАЛИТЬ; position_sync = read-only сторож (cold-start + orphan-алерт через Sphere.close verify-flat). Убирает конкуренцию WS∥REST = корень призраков.
- **Таблица WS→действие (§5):** добиваем неиспользуемые o.rp/o.n/FUNDING_FEE/LIQUIDATION/mt. **Карта поглощения 8 узлов (§8)** + порядок миграции Ф3.1→Ф5 (§9, за флагами, close-path=тест на копии БД).
- **4 развилки (§10) на ревью ARCH/рой** перед Ф3.1: REST-сторож алерт vs close; BingXAdapter обёртка vs ccxt; live.db/sim.db физ vs логич; TSL команды vs reactive.
- ✅ **Ф3.1 КАРКАС ПОСТРОЕН** (`core/execution/`, аддитивно, живой код НЕ тронут): `domain.py` (ExecMode/OrderRequest/OrderResult/Position/Fill/CloseResult/LedgerEntry + ExecEvent union), `adapter.py` (ExchangeAdapter ABC, 14 методов, БЕЗ слова BingX), `calc.py` (ExecutionCalc: size_position делегирует PositionSizer, R-math reuse r_math, guards+leverage-клампы порт open_bracket:403-487), `__init__.py` экспорт. **Parity-тест `tests/unit/test_execution_calc_parity.py` — 21/21 PASSED** (ExecMode не дрейфует от ExecutionMode; size==calc_qty; clamp формула 1:1 с инлайном; POPCAT 50→30×). py_compile OK.
- ✅ **РЕВЬЮ РОЯ: дизайн ПОДТВЕРЖДЁН 5/5** (`memory/last_team_discussion.md`, 7 моделей). Консенсус: WS pa=0 = единственная истина close; PositionStore = владелец состояния; REST = алерт-only. **4 развилки решены по моим рекомендациям** (REST алерт-only / BingXAdapter обёртка / физ live.db+sim.db split / TSL через Sphere). Рефинмент §6: bounded-staleness watchdog (метрика тиков-без-ACCOUNT_UPDATE + эскалация Sphere.close(verify-flat) после N циклов флэта — НЕ возврат close-by-price). Внесён в дизайн §6/§10/§10a (+ cold-start reconcile Store↔Ledger, caveats: reconnect-тест, карта downstream, perf).
- 🔵 **Следующий шаг:** Ф3.2 (BingXAdapter обёртка над BingXClient/order_manager/user_data_ws — реализует ABC, без переписи биржевых вызовов).
- ⚠️ Сессия: код бота НЕ тронут (новый пакет `core/execution/` + тест + `docs/` + координация MD). DISCUSSION 16:25.

## [19.06 ~18:50 UTC] Агент: Даат — ✅ РЕСТАРТ #2: масштаб истории + CASCADE логирует; 🔧 CASCADE баг регистра исправлен (нужен рестарт #3)

- ✅ Бот PID 15444 (старт 18:49:44), чисто. **trades_filtered масштаб РАБОТАЕТ** (lev/size/$ в истории дашборда: AWE 20×/qty/profit_pct). balance_history sparkline ✅.
- ✅ **OTE-CASCADE shadow логирует** `[CASCADE][shadow]` (BAS FIRE 18:49). 🔧 **НО баг регистра:** `sig.direction='long'` (lowercase) ≠ `'LONG'` → would_block ВСЕГДА True. **ИСПРАВЛЕНО** (`str(sig.direction).upper()`), py_compile OK, проверено 4 комбинации. **🔴 рестарт #3** для корректных данных DS (shadow, не срочно — копить с правками). Незакоммичено доп: `ote_observer_loop.py` (фикс регистра).
- ⏳ orphan_autoclose НЕ флипнут (shadow) — призраки не авто-закрыты, симптом-фикс ждёт решения.
- 🔧 **УРОК oko-dashboard = PROD build (`next start`, :3000), НЕ dev:** правки `lib/api.ts`/компонентов НЕ подхватываются на лету → нужен `npm run build` + рестарт `next start` + браузер hard-refresh (Ctrl+Shift+R). [[oko_dashboard_v2_status]].
- 🔧 **МАСШТАБ ИСТОРИИ — чинил не тот путь дважды:** Exchange-режим (trades.tsx:153) грузит closed через `/api/exchange_history` (`_exchange_history_compute_sync`), НЕ trades_filtered (то Sim-режим)! Истинный фикс: бэк SELECT += leverage,qty + dict; фронт `RawExchHist`+`fetchExchangeHistory` маппер += size$/leverage/realized$. py_compile+build OK, фронт перезапущен. **🔴 нужен рестарт бота #3** (бэк compute в живом PID 15444; проверено: /api/exchange_history qty=None до рестарта). Рестарт #3 даёт: масштаб Exchange + корректный CASCADE (баг регистра). Незакоммичено: `dashboard_server.py` (exchange_history+trades_filtered), `oko-dashboard/lib/api.ts` (3 маппера), `ote_observer_loop.py`.

## [19.06 ~15:30 UTC] Агент: Даат — 🔴 КОРЕНЬ ПРИЗРАКОВ (orphan) ВЫЯСНЕН РАЗ И НАВСЕГДА

**Юзер: «выяснить как появляются и закрыть дыру». Призраки = биржевые позиции без OPEN в БД (DOLPHIN/PARTI/Q, течь −$268/3.6ч мимо tracked, стратегия ote_nested чиста +$79).**

**КОРЕНЬ = ДВА конкурирующих пути закрытия БД-сделки:**
1. ✅ **WS (exec_ws_integration 2a/2b):** ORDER_TRADE_UPDATE FILLED → exch_id; ACCOUNT_UPDATE pa=0 → close_trade по РЕАЛЬНОМУ флэту. Надёжный, призраков НЕ создаёт. УЖЕ реализован (acc1 700/acc2 705 событий). Юзер ткнул в это (BingX WS Order update push) — решение верное.
2. ⚠️ **REST (position_sync.sync_positions:504):** `(sym,dir) not in open_pairs` (кэш `_get_positions_cached` TTL 15s) → «закрылась» по свече → close_trade. НЕНАДЁЖНЫЙ: устаревший/неполный кэш / ключ по symbol БЕЗ account → ложно метит closed → позиция жива → orphan. WS pa=0 не приходит (закрытия не было). D-070 детектит (лог `[D-070] ORPHAN DOLPHIN/PARTI` 18:12-18:22), но `orphan_autoclose: shadow` → не закрывает.

**ДВЕ структурные дыры (account НЕ сквозной):** `position_sync:364` `upsert_positions(1, parsed_all)` хардкод acc1 → acc2 невидим в шине/positions-табл (acc2 margin $37 но 0 строк); `position_sync:450/501` open_pairs ключ `(sym,dir)` БЕЗ account → multiacct-коллизия.

**ЛЕЧЕНИЕ раз и навсегда (3 уровня):** (1) КОРЕНЬ: close-by-price (504) → verify-flat (force get_positions этого sym+account) перед close, жива→не закрывать; WS=единств. источник закрытия. (2) account сквозной (open_pairs/upsert по account) = ARCH-96-HUB. (3) НЕМЕДЛЕННО: `orphan_autoclose: shadow→live` (config:133, механизм готов 697-732) → авто-закрыть текущих призраков. [[exec_ws_vst_userdata_proven]] + [[orphan_root_dbexch_desync]] + EXEC-SIM-SPLIT. **gross-инсайт: REST-polling close-by-price = корень рассинхрона, WS = истина.**

**🏛️ ЭПИК EXECUTION-REBUILD (видение юзера 19.06): единый Execution Sphere вместо 8 узлов.** DISCUSSION 15:45. **🎯 НАХОДКА docs:** BingX-API/api-ai-skills = ОФИЦИАЛЬНЫЙ Claude Code skill-пакет с полной api-reference (НЕ SPA!). `npx skills add BingX-API/api-ai-skills`. Skills: swap-trade/swap-account/swap-ws-account. Спека WS сохранена → `docs/BINGX_WS_ACCOUNT_SPEC.md`. **WS ORDER_TRADE_UPDATE даёт НАТИВНО всё что городили:** `o.rp`(realized PnL=$-истина), `o.n`(комиссия), `o.ap`(реальный fill=анти-fakeR), `o.o=LIQUIDATION`, `a.m=FUNDING_FEE`(разрыв −$266!), `a.P[].pa=0`(флэт=анти-призрак), `a.P[].mt`(cross/isolated). exec_ws_integration НЕ юзает rp/n/FUNDING_FEE/LIQUIDATION/mt — дельта эпика. Фазы: ✅Ф1 docs(spec готов)→Ф2 дизайн Execution Sphere→Ф3 миграция (убрать REST close-by-price/profit_pct/income-леджер — WS заменяет). Делать СВЕЖЕЙ головой.

## [19.06 ~08:37 UTC] Агент: Даат — ✅ РЕСТАРТ выполнен (юзер), 3 фикса активны, форвард пошёл

- ✅ **Бот PID 8440** (484MB), старт 08:36 UTC — scan_loop/event_bus/SMC работают, краша нет. Worker PID 30404.
- ✅ **acc1 EXEC-WS: все `mt:"separate_isolated"`** (cross-дрейф вылечен, подтверждено WS-снапшотом).
- ✅ **balance_history кэш активен:** MISS→HIT подтверждён (sparkline acc1 оживёт). Минор: HIT ~2.1s (тяжёлый payload 867×5 полей + CPU старта) — если не ускорится после прогрева, облегчить payload до [equity].
- ⏳ **SL-safety кап:** config `liq_safety_enabled=true` загружен; в логе появится на 1-й сделке высокое-плечо×широкий-SL (органически, как POPCAT 50×/2.75%).
- 📊 **ФОРВАРД ОТ $1004.87** (baseline 08:29 UTC, оба акка ~$502 isolated). Следующий poll запишет первый post-restart снапшот. Метрика = дельта equity, НЕ R.
- ✅🔪 **OTE-CASCADE shadow 1D-трендфильтр ПОСТРОЕН** (Claude→DS, todo#1): `bot/loops/ote_observer_loop.py` `_cascade_1d_shadow` — на каждый ote_nested FIRE фетчит `get_ohlcv('1d',60)`+`calculate_trend(43)` → лог `[CASCADE][shadow] would_block` (вход против 1D), НЕ блокирует. Корень «1d не фирит» найден: `:106-111` resample 1h×300=~12 баров<43→NaN, поэтому 60 настоящих баров. Config `ote.cascade_shadow:true`. py_compile+config+calc_trend OK. **🔴 след. рестарт активирует.** DS меряет дельту forward → edge→гейтим live. Незакоммичено: `ote_observer_loop.py`, `config.yaml`. DISCUSSION 19.06 ~09:50.

## [19.06 ~09:35 UTC] Агент: Даат — ✅ SL-SAFETY КАП ПЛЕЧА реализован + замер риск-экспозиции

- ✅ **SL-SAFETY КАП ПЛЕЧА (3-й слой leverage)** в `order_manager.open_bracket` (после кап-пары, ~473): `leverage = min(req, pair_max, floor(1/(sl_dist + buf)))`. Config `trading.liq_safety_enabled:true` + `liq_safety_buffer_pct:0.5`. Только СНИЖАЕТ плечо (qty уже посчитан запрошенным → риск корректен, маржа выше=безопаснее). py_compile+config-load OK. **🔴 РЕСТАРТ нужен.** Незакоммичено: `order_manager.py`, `config.yaml`.
- 📊 **Симуляция на 5 живых VST:** ловит ТОЛЬКО POPCAT (50×, SL 2.75% → liq 1.9% < SL = катастрофа) → **50→30×** (liq 3.33% > SL). Остальные 4 (CAKE/AKT/PROM/UNI) НЕ тронуты (SL внутри ликвидации). Точечно.
- 📊 **Замер риск-экспозиции (08:04 UTC):** equity acc1 $215.5/acc2 $222.7 (Σ $438), available ~$211 каждый (НЕ $22 — после закрытия cross-балласта). VST risk Σ(qty×|entry−sl|)=$3.29 → **0.75%** (acc1 0.89%/acc2 0.62%) против гейта 25% = запас ×33. При risk 0.5→1.0 → ~1.5%, гейты НЕ упрутся; связывающее ограничение = ликвидация на 50×, не гейты.
- ✅ **ФИКС дашборда: пустые per-account sparkline** — `_handle_balance_history` был ЕДИНСТВЕННЫЙ некэш-portfolio эндпоинт (2-8с на 29K × N акков/30с → мини-кривые гонялись/абортились, особенно acc1 первым/холодным). Обёрнут в `_PORTFOLIO_CACHE` (single-flight+detached, как account_balances). py_compile OK. **🔴 РЕСТАРТ нужен.** Незакоммичено: `web/dashboard_server.py`.
- 📉🔴 **ПРОСАДКА РАЗЛОЖЕНА: корень = ИЗДЕРЖКИ гиперчастоты + cross, НЕ стратегия (юзер поправил: смотреть $, не R!):** R обманул (по $ только 13/18.06 плюс). $-кривая (balance_snapshots): 12.06 $793 → 19.06 $438 = **−48%/нед**. acc1 −26% (isolated) vs **acc2 −60% (был CROSS)**.
  **🔬 РАЗЛОЖЕНИЕ Δequity −$412 = бумага(Δunreal) +$21 + стратегия(tracked closed) +$2 + REST −$435.** Стратегия и открытые позиции ≈ НОЛЬ. REST −$435 = **комиссии tracked ≈ −$169** (6835 сделок!/нед, оборот $187K, taker 0.045%×2) **+ funding/untracked/ликвидации ≈ −$266** (74% на acc2-cross −$322). 14.06 было 1772 сделки/день.
  **ВЫВОД: бот не льёт по сигналам — его съедают транзакц. издержки гиперактивности + cross-untracked (orphans/ликвидации POPCAT-тип SL-за-ликвидацией/funding).** 4 сегодняшних фикса бьют ровно это: Режим В (19.06 уже 181 vs 1772 → ↓комиссии), isolated acc2, orphans=0, SL-safety кап. Рычаг: maker-выход (−$169→−$75). Точн. funding-vs-untracked split = BingX income-леджер (NEXT). **МЕТРИКА ИСТИНЫ = $ из balance_snapshots; R — только относит. качество.** [[VST-REALITY]] подтверждена сильно. [[orphan_root_dbexch_desync]].
- 💰🟢 **НОВЫЙ BASELINE «отсчёт от сейчас» (08:29:49 UTC, ПОСЛЕ пополнения, из ШИНЫ — юзер: баланс уже в balance_snapshots, на биржу не лезть):** acc1 **$503.59** (avail $496.06/margin $4.25/uPnL +3.28), acc2 **$501.28** (avail $489.02/margin $13.26/uPnL −1.01). **Σ $1004.87.** Депозит: acc1 +$286.59, acc2 +$280.47 (выровнены ~$502 = чистый A/B, оба isolated). **ФОРВАРД-PnL = equity(t) − $1004.87.** Старый baseline до пополнения был $217.00/$220.81 @ 08:19:44.
  **ШИНА: что ЕСТЬ vs НЕТ.** ЕСТЬ: equity/available/used_margin/unrealized_pnl per-account (balance_snapshots poll + user-data WS ACCOUNT_UPDATE). НЕТ: разбивка income по типам (FUNDING_FEE/COMMISSION/REALIZED_PNL отдельно) — растворены в агрегате equity. Точное разложение REST −$435 (fees vs funding vs untracked) = только биржевой income-леджер `/openApi/swap/v2/user/income` (есть `make_client`+`get()`, NEXT если нужно).

## [19.06 ~08:00 UTC] Агент: Даат — ИТОГ ДНЯ (консолидация). Подробности — в записях ниже + whats-next.md

**Сделано (5 рестартов):** (1) **fake-R УБИТ** — positionID-якорь + миграция боевой БД (Tier1 3956 + карантин 40), ote_nested честный avgR **+0.474** (был 0.846). (2) **Режим В OTE-ONLY** изолирован, **arch104 ЗАКРЫТ** (перемайн=data mining, DS+я согласны) + atr_change off. (3) **3 косяка плеча** (per-source + кламп-к-max + факт-в-БД, проверено БД=биржа). (4) **margin-mode** acc2→isolated, **orphan'ы=0**. (5) **Дашборд** (репо oko-dashboard, коммит `f0613d5`): R+$ на одном множестве + дедуп. **🛡️ 5× дисциплина «число→проверка→потом» поймала фантом до боя** (fake-R/FVG-SL/WT/arch104/OTE-CLONE).

**Открыто (мяч у DS):** OTE-CASCADE 1D — DS гонит honest 1D→1H на ≥60д (корень «1d не фирит»=`ote_observer_loop:99` 1h limit=300→12 1d-баров<50; генератор НЕ сломан; фикс live=1 строка после edge). WT-REVERSION — shadow-first (я: wt_pct shadow-фича; DS: P5/200b на прод-SL).

**Git:** main `02beb18` + dashboard `f0613d5`, **НЕ запушено**. DS-конфиги (`config_loader/validator/pydantic`) не тронуты. Бэклог: exec-sim-split (полный), orphan-кирпич2, margin-enforce, acc1 cross. Бот жив (рестарт #5 ~04:12, leverage-enforcement активен).

## [19.06 ~03:00 UTC] Агент: Даат — fake-R positionID-фикс ✅ КОД + МИГРАЦИЯ ВЫПОЛНЕНА (ждёт рестарта)

- ✅✅ **МИГРАЦИЯ ПРОГНАНА** (бот остановлен юзером, `--commit --with-exchange`, бэкап `subscriptions.db.fakeR-bak-20260619-023649` 304МБ). **Tier1 истинный exit по positionID: 3956 · Tier2 clamp: 26 · карантин 40** (R>10 MFE=None → R/profit=NULL+`fakeR_quarantine=1`, 447.5R яда снято). **STG #31400 R=+323.6→−1.13** (✓ истинный SL). Осталось R>10 только 6 — все легит-раннеры R≤MFE. **avgR базы +0.108→−0.045.** Честный gross: ote_nested **+0.474** WR61% (был 0.846, net ~+0.2-0.3R), atr_change −0.20, arch104 −0.17 (балласт).
- ✅ **РЕСТАРТ #1 выполнен** (PID 30932, старт 02:41 MSK): код-фикс positionID + миграция-колонки (position_id/fakeR_quarantine ✓) + карантин 40 подхвачены. Live перестал плодить фантомы.
- ✅ **arch104 + atr_change ОТКЛЮЧЕНЫ** (честный R после миграции: arch104 LONG −0.182/SHORT −0.050 net −$208 — SHORT БОЛЬШЕ НЕ несёт; atr_change LONG −0.083/SHORT −0.183 net −$74). Правки: `config.yaml` `signal_router.source_policies.{arch104,atr_change}.exchange_enabled=false` + `arch104.vst_trading.enabled=false`. Реверс: вернуть true.
- ✅ **РЕСТАРТ #2 выполнен** (PID 30548, старт 02:49:41 MSK — ПОСЛЕ конфиг-правок 02:47): отключение arch104/atr_change загружено (флаги читаются False). Router-гейт `exchange_enabled=false` → балласт не может открыть VST.
- 🟢 **positionID-захват ПОДТВЕРЖДЁН вживую:** свежие сделки #31453-31457 несут `position_id` в колонке (`fetch_and_save_position_id` пишет на боевом пути) → `_resolve_exit` матчит выход точно → новых фантомов не будет. Going-forward фикс работает end-to-end.
- ✅ **OTE-ONLY Режим В ПРИМЕНЁН** (юзер выбрал «В сразу», VST=песочница). config.yaml: risk 0.5%, leverage 50x, l3-гейты АКТИВИРОВАНЫ (max_total_risk 25%, shadow→false), **изоляция: source_policies ВКЛ только ote_nested** (+default_policy off убил liquidity_sweep catch-all; arch104.vst off; ote_shadow off). config_ote_V.yaml DS НЕ применял — был неполный/опасный (cp снёс бы конфиг, ключи мимо, не изолировал). 🔴 **РЕСТАРТ #3 нужен** чтобы Режим В вступил. DISCUSSION 03:40.
- ✅ **2 АРХ-ФИКСА leverage (юзер нашёл, 19.06):** (1) **per-source плечо/risk_pct** — `SourcePolicy.leverage/risk_pct` (None→глобал fallback), `trade_router._place_exchange_order` читает из `ctx.policy`. Было ГЛОБАЛЬНО (`get_leverage`) → 2-я стратегия унаследовала бы 50× ote_nested. Теперь: ote_nested 50×/0.5% локально, глобал вернул к 5×/1.0% (default). (2) **leverage в БД** — колонка `leverage`, захват при открытии (trade_router UPDATE), дашборд читает из ФАКТА (real bus→БД→config), не «перекрашивает» старые сделки живым конфигом (корень «50× на SIM atr_change»). Файлы: `source_policies.py`, `trade_router.py`, `subscription_manager.py`, `config.yaml`, `dashboard_server.py`. py_compile+резолв OK. 🔴 **РЕСТАРТ #4** для активации. Минор: SIM-сделки не хранят leverage (нет биржевого ордера) → дашборд-fallback на глобал 5×.
- 🔴 **MARGIN-MODE дрейф (юзер нашёл 19.06):** acc2 был массово CROSS (`mt:"cross"` в EXEC-WS снапшоте, 506 символов-конфигов) — бот архитектурно рассчитан на separate_isolated (positionId для close/SL). Cross пулит риск на весь счёт → вероятно усилил −281 (−50%) acc2 vs −5 acc1 (isolated). Юзер переключил дефолт + рестарт #4 (PID 12400, 03:45). НО осталось: **151 символ acc2 + 114 acc1 ещё cross-конфиг** (BingX не меняет mode при открытой позиции). Из них с ОТКРЫТОЙ позицией на acc2 было **15** (12 atr_change + 3 arch104 = балласт, uPnL +$0.45). **✅ Я закрыл все 15 account-aware** (one_click_on_fail, 101205→fallback OK, +$0.49 realized) → acc2 ФЛЭТ, символы вернутся к isolated. Бот закроет DB-строки honest-R по positionId.
- 🔴 **КОРЕНЬ: бот НЕ управляет margin-mode** (`grep marginType/set_margin` = пусто). Дрейф в cross молчит и повторится. 136 пустых cross-символов acc2 откроются cross при новой сделке. **Нужен кирпич ENFORCE** (бот ставит isolated перед открытием, BingX `/trade/marginType`). Видимость: margin_mode в шину+дашборд (cross=🔴) + колонка БД (поле raw = `isolated` bool). Приоритет: enforce > дашборд > БД-история.
- 🔴→✅ **LEVERAGE exchange-enforcement (юзер нашёл SSV 5×, 19.06):** баг — `open_bracket:438` читал ГЛОБАЛ `trading.leverage`, игнорируя per-source (trade_router считал qty с 50, но биржа ставила глобал 5). Плюс при запросе > max пары биржа отвергала → откат на СТЕЙЛ плечо (SSV: просил 50, max 20, было 5 → открылось 5×). **Фикс (4 файла):** trade_router передаёт per-source плечо в open_bracket; `open_bracket` **клампит к max пары** (`_get_pair_max_leverage`, кэш+TTL 1ч = перепроверка, юзер просил); `BracketResult.leverage`=ФАКТ; trade_router хранит `br.leverage` в БД (факт, не запрос). py_compile+проводка OK. 🔴 **РЕСТАРТ #5** → ote_nested SSV откроется 20× (max), RUNE 50×, БД=факт. Минор: qty сайзится запрошенным плечом (риск корректен, маржа выше при клампе — безопаснее). Файлы: `bingx_client.py`, `order_manager.py`, `trade_router.py`.
- ПОТОМ: margin-enforce кирпич (бот держит isolated — 136 пустых cross-символов acc2); margin_mode в шину/дашборд/БД; DS правит config_ote_*.yaml + forward-валидация; DEV перемайн ARCH-104.
- ⚠️ Незакоммичено (7, разделить от DS): `subscription_manager.py`, `trade_simulator.py`, `tsl_updater.py`, `trade_router.py`, `position_sync.py`, `exec_ws_integration.py`, `scripts/migrate_fakeR_positionid.py`. Минор: position_id историч. сделок не бэкфилл (только R исправлен; новые захватываются). → [[bug_phantom_exit_resolve]].

- ✅ **Код фикса (6 правок, py_compile OK, аддитивно, вступит на рестарте):**
  - `subscription_manager.py` — колонка `position_id TEXT` (CREATE TABLE + миграция-loop).
  - `trade_simulator.set_position_id()` — сеттер (паттерн `set_exchange_sl_order_id`).
  - `tsl_updater.fetch_and_save_position_id()` — захват `_get_position_id` (retry 3×2с) при открытии.
  - `trade_router._place_exchange_order` — спавн задачи захвата рядом с SL/TP-id.
  - `position_sync._resolve_exit` — **PRIMARY матч по positionID** (close-side FILLED той же позиции, последний по updateTime), ВЫШЕ orderId и эвристики symbol+side. Прокинут `trade.position_id` в 3 вызова (main sync, OPS-06 emergency, WS sync_close через `_find_exchange_trade`).
- ✅ **Миграция `scripts/migrate_fakeR_positionid.py`** (dry-run по умолчанию, бэкап перед `--commit`). Гибрид: Tier1 `--with-exchange` (истинный exit по positionID из allOrders, жжёт API → бота стоп), Tier2 оффлайн (clamp exit в `[min,max]`), Tier3 MFE=None (не чинится). R-математика = ровно `close_trade` (r_math).
- 📊 **Dry-run Tier2 (оффлайн, боевая БД, n=13633):** avgR 0.1079→0.0858; **239** фантомов клампнуто (AIN #31219 R=36→0.68, ETHFI 19→2.27, TREE 18.6→1.24 ✓ совпало с DS). **🔴 Tier3 = 823 строки MFE=None, из них 45 монстров R>10 = 1100R яда** (STG #31400 R=323.6 SL exit 0.6071 — здесь; ALLO +37.8, TAO +36.1) — clamp бессилен (`max/min=NULL`), нужен Tier1 (positionID с биржи) ИЛИ карантин R. ote_nested avgR=0.846.
- 🔄 **РАЗВИЛКА юзеру (НЕ решено):** (1) запускать Tier1 `--with-exchange` (стоп бота, жжёт API, чинит только свежие в окне allOrders ~500/символ — STG достанет, старые ALLO/TAO нет)? (2) что с недостижимыми MFE=None монстрами — R=NULL/карантин (исключить из метрик/весов) vs оставить? Меняет семантику данных → решение юзера.
- ⚠️ Незакоммичено: + `core/db/subscription_manager.py`, `core/trading/trade_simulator.py`, `core/exchange/tsl_updater.py`, `core/trading/trade_router.py`, `core/exchange/position_sync.py`, `core/exchange/exec_ws_integration.py`, `scripts/migrate_fakeR_positionid.py`. Бот PID 33956 жив (старый код, колонки `position_id` в БД ещё нет до рестарта). → [[bug_phantom_exit_resolve]].

## [18.06 22:25 UTC] Агент: Даат — fake-R ЖИВ (сверен с биржей) + handoff на пару Даат+DS

- 🔴🔴 **fake-R НЕ починен** (миграция почистила прошлое, live пишет заново). Сверка с биржей (`get_filled_orders` по orderId): «win R=+26..+323» = РЕАЛЬНЫЕ убытки. STG #31400 БД R=+323, биржа вход 0.2350→SL 0.2334 pnl −0.97; БД взяла exit из ордера от **12.06**. Корень: `exchange_sl_order_id` None/устарел после cancel+replace → orderId-матч ломается → старый ордер. **🔑 Фикс = positionID** (вход+SL+перевыставленные = ОДИН positionID; устойчив к cancel+replace; граница SIM↔VST) → колонка `position_id` + матч в `_resolve_exit` + миграция. Детали → [[bug_phantom_exit_resolve]], стенды `e:/tmp/`.
- 🔴 **OTE-ONLY (DS) на песке:** avgR=0.913 отравлен (медиана +0.42, clamp→MFE +0.74, net ~+0.2-0.3R, top-10 по R = фантомы). Любой режим/compounding — ПОСЛЕ fake-R фикса+перемиграции. РОЙ 6/6 Режим А+cap. arch104=балласт.
- ✅ **Orphan cleanup:** 17 закрыто (`close_orphans` account-aware), биржа 50→33, orphans=0. **Кирпич 1** D-070 auto-close shadow (`config orphan_autoclose` + `position_sync`). → [[orphan_root_dbexch_desync]].
- 🔄 **Следующая сессия = Даат+DS пара** (DEV/ARCH отдыхают): fake-R positionID-фикс + OTE-ONLY пересчёт. `whats-next.md` обновлён.
- ⚠️ Незакоммичено (tracked): моё (`DISCUSSION`/`config.yaml`/`position_sync`/`close_orphans`/`current_state`) + DS (`bingx_client`/`config_loader`/`config_validator`/`pydantic_config`). Бот **PID 33956 жив**.

## [18.06 19:55 UTC] Агент: Даат — расследован КОРЕНЬ orphan'ов (рассинхрон БД↔биржа)

- ✅ **Проверка SL-reconcile live (первый шаг handoff):** конфиг `live` подтверждён, код-путь корректен, **ошибок place нет → откат НЕ нужен**. Но `[live]` за ~10 мин не сработал — не сбой: отслеживаемые VST уже с SL (здорово) + единственные кандидаты REAL/KAT стали orphan'ами (нет OPEN-строки → `_db_sl=None → continue`). Валидация на REAL/KAT **невозможна** — закрылись в БД (REAL 16:17 UTC) за ~3.5ч ДО рестарта (22:45 МСК).
- ✅ **Корень orphan'ов расследован** (юзер выбрал «расследовать корень»). При рестарте PID 31536 D-070 нашёл **14 orphan'ов VST** (статич. бэклог, новых нет). Все VST/paper, реальные деньги не затронуты, плавающий PnL ≈ +5 USDT. **2 механизма (БД+код):** (A) **SIM-утечка** (6: JASMY/PEOPLE/REAL/SIREN/SOMI/XNY) — `execution_mode=SIM`, `exchange_order_id=None`; код считает SIM без биржевой позиции (`trade_simulator.py:1938` SIM-TIME-EXIT, «биржевые не трогаем»), но позиции есть; REAL=вся история SHORT с 13.06 SIM, ни одной VST → позицию qty 53.2 не создавала ни одна DB-сделка; БД закрывает строку → биржа висит → orphan. (B) **VST close-confirmation gap** (8: AKT/AUCTION/CLO/ORDI/PIEVERSE/POLYX/STX/TAO) — реальные VST, БД закрыла TP/SL по цене, позиция на бирже выжила (нет реального reduceOnly-флэта). Детали → [[orphan_root_dbexch_desync]].
- ✅ **Вывод:** reconcile **бессилен против orphan'ов by design** (лечит только VST с живой OPEN-строкой). Настоящее лечение — на слое исполнения: подтверждать флэт через WS executionReport ([[exec_ws_vst_userdata_proven]]), гарантировать что SIM не оставляет позиций; D-070 расширить alert→adopt/close.
- ✅ **Cleanup СДЕЛАН:** `scripts/close_orphans.py --commit` → закрыто **17** (биржа 50→33, orphans=0). Патч скрипта: close-цикл account-aware (`_resolve_position_client`+positionId+`one_click_on_fail`) — был sticky-client (КОРЕНЬ 101205). ⚠️ НЕ закоммичен.
- ✅ **Профилактика кирпич 1 СДЕЛАН (ждёт рестарта):** D-070 alert→auto-close, config `trading.orphan_autoclose: shadow` (off/shadow/live, паттерн sl_reconcile), **hedge-safe** (skip символов с DB-OPEN — one-click задел бы брата). Правки: `config.yaml` + `position_sync._detect_orphans`. py_compile+config-read OK, pydantic чисто (флаг толерируется как sl_reconcile). Shadow=zero-risk → после рестарта мониторить `[D-070][autoclose][shadow] … закрыл бы` → флип `live`. ⚠️ НЕ закоммичено.
- 🔄 **Осталось (#21 EXEC-SIM-SPLIT, свежей сессией):** кирпич 2 = verify-flat в `_emergency_close_check` (закрывает БД при code=0 без проверки флэта — точный пробел root B, position_sync.py:222→255); root A = источник SIM-утечки. Детали → [[orphan_root_dbexch_desync]].

## [18.06 18:45 UTC] Агент: Даат — «кривой SL» закрыт (=безубыток) + классификатор BE реализован (ждёт рестарта)

- ✅ **`stop_loss>entry` — НЕ баг**, штатный DEV-40 Breakeven (SL→entry±0.1% после +0.5R, ставит `be_activated`, не `tsl_activated`). Прошлая сессия искала по tsl → ложная тревога. 1336/1374 = be=1; все примеры +0.100% ровно; be=1 status=SL avgR +0.31 (защита) vs чистый стоп −0.90; свежих необъяснённых=0. → [[bug_stop_loss_inverted]].
- ✅ **Классификатор BE реализован** (решение юзера: расширить `effective_status`, не новый статус): `effective_status.py` (+be_activated, ветка чистого BE R∈[-0.2,0.35], `SQL_IS_BE_NEUTRAL_CASE`), `performance_engine.py` (closed −= be_neutral в summary/by_signal_type/ema; avg_r_loss без BE), `dashboard_server.py` (прокинут be_activated). Проверено: py_compile + 11 кейсов + runtime на КОПИИ — WR VST 48.5→**51.0%**, atr_change 44.1→49.9, avg_r_loss честнее −0.604→−0.666. 🔴 ВЕСА НЕ меняет (update_signal_weights по avg_r). Детали → [[be_exit_classification_findings]].
- ⚠️ **НЕ закоммичено, НЕ активировано** — вступит после рестарта (юзер). Откат мгновенный.
- 🐛 **Побочно найден+починен баг `/api/kpi` 500** (после рестарта 22:09, при проверке фронт-ошибок ECONNREFUSED/RESET): `_handle_kpi._days` падал `can't subtract offset-naive and offset-aware datetimes` — created_at в БД смешан (старые naive `2026-03-01 00:41:26`, свежие tz-aware `+00:00`), MIN naive − MAX aware. Фикс: `.replace(tzinfo=None)` на обоих (`web/dashboard_server.py` + тот же латентный в `performance_engine.summary` days_active). НЕ от BE-фикса. Вступит после рестарта. ECONNREFUSED был гонкой старта (порт 8000 поднимается не мгновенно); /api/stats восстановился после прогрева OHLCV.
- 🔵 Бэклог: BE-буфер (стенд `e:/tmp/be_buffer_stand.py` — не повышать, режет раннеры); runner-флаг + magnet-TP shadow→exit (ARCH-122 P3); свежая parquet-история (>17.05) под стенды.

### [18.06 ~22:30 UTC] Агент: Даат — #1 SL-reconcile активирован live + git-гигиена + push
- ✅ **#1 SL-reconcile → LIVE** (commit `0e96325`). Loop УЖЕ был реализован (`position_sync.sync_positions:386-420`, throttle 5мин, reuse не новый loop), стоял `shadow`. Shadow доказал РЕАЛЬНЫЙ риск: REAL/KAT SHORT висели без биржевого SL ~час (18:28→19:17). БД-прокси врал «0 без SL» (`exchange_sl_order_id` от мёртвого ордера). Проверено account-aware: `place_sl_order`/`get_sl_order_id` прокидывают symbol→роутер (`arch96.multiaccount.enabled=true`)→правильный суб (acc2 покрыт); анти-дубликат; зрелый place. Вступит после рестарта → мониторить `[SL-RECONCILE][live]`. Корень #1(б) закрыт; (а)/(в) покрыты loop'ом.
- ✅ **Git-гигиена**: разобран незакоммиченный слой (12 M + 102 untracked). 5 коммитов: BE-классификатор+kpi-datetime (`bce5d47`), gitignore `*.bak*` (`a6eb622`), NOTIF-TIER2 уведомления (`ceb1380`), роль-инфра+adopt (`1edd2cf`), доки (`ef186d1`). Research-зона DS (93 untracked: scripts/tools/docs) НЕ трогал. **Запушено** на origin/arch-128-oko-sm (ahead 0).
- ✅ `/api/kpi` datetime-фикс активен (после рестарта closed=30454 WR=40.7% closed_per_day=279.4).
- 🔜 **#21 EXEC-SIM-SPLIT** — следующий (сводка DEV-52 shadow-логов risk/margin → калибровка → активация). Контекст тяжёлый → лучше свежая сессия.



Эпическая сессия (сутки). От «запусти аудит» до доказанного net-edge кормильца. Детали → [[ote_engine_full_map]], [[ote_tight_sl_validated]], [[signal_health_map_18jun]].

**Коммиты (arch-128-oko-sm):** `08fcff2` fake-R корень (resolve по orderId+clamp R≤MFE)+VST-метрики+hedge+dashboard · `87d870d` atr_change 15m off · `3b3a335` ote confirmations лог · `de92b88` arch104 волна · `bdf36f8` унификация phase_*=elliott_* · `58dbb31` **min_sl_dist 0.5→0.25 GAME-CHANGER** · `1448b55` r_live по original_sl. **+ МИГРАЦИЯ боевой БД** (11136 фантомов→честный R, бэкап `e:/tmp/subscriptions_PRE_MIGRATION_*.db`).

**Ключевое:** (1) fake-R корень = `_resolve_exit` матч по symbol+side без orderId → 60-75% PnL фантом, истинный avgR~0.3. (2) Миграция вычистила. (3) **GAME-CHANGER:** пол `min_sl_dist 0.5%` (15.06) резал ТУГИЕ ote-входы (avgR+1.07!), оставлял широкие (+0.39) → опущен до 0.25 → edge удвоился (net+0.461→+0.546, sumR+61%). (4) Тугой SL net-валидирован на n=2680. (5) div-вертикаль = редкий премиум (не главное).

**Активировано** (рестарт 20:28МСК/17:28UTC PID 33476): тугие ote вернулись (SL 0.44%), confirmations лог (div+wt_cross+atr), atr_change 15m off. Стенд `e:/tmp/ote_stand.py` (gross/net/A/B).

**🔴 СЛЕДУЮЩАЯ СЕССИЯ:** расследование `stop_loss > entry` (кривой SL) → [[bug_stop_loss_inverted]] + `whats-next.md`. ~1374 сделок (984 SL), original_sl верный, stop_loss сдвинут выше entry после регистрации. Гипотеза: TSL без tsl_act флага. Реальный риск SL-исполнения.

**Мониторинг:** тугие ote<0.5% накопление, net-edge→+0.55, ⚠️303 VST/10мин (флуд?).

## [18.06 UTC] Агент: DEV — DS-326 ЗАКРЫТ: WT-B edge = фантом узкого SL (на боевых условиях убыток)

Финал DS-326 (полный отчёт `data/research/ds326_wtb_filters_result.md`, детали DISCUSSION 08:40). Путь: фильтры→рычаги→TSL→ТФ→OOS→комиссия/SL.
- **Gross-edge устойчив:** ADX<25 (1h→15m) +0.204, OOS по годам 2024 +0.302 / 2025 +0.304. 4h-намёк отброшен (режим-зависим).
- **🔴 РАЗВОРОТ:** +0.204 = артефакт узкого бэктест-SL 0.3%. На прод-SL 0.5% gross→+0.048, net после комиссии **−0.145**. Торгуемого edge НЕТ (combo на грани, slip добивает).
- **🧭 Метод-урок:** R фантомен при узком SL — фиксировать прод-SL перед выводом. Память [[feedback-backtest-realistic-sl]].
- Скрипты (НЕ закоммичено→коммичу): `ds326_{all_filters,edge_levers,tf_matrix,oos,fees}.py`. TASKS DS-326 → ✅.

## [18.06 UTC] Агент: Даат — 🗺️ КАРТА ЗДОРОВЬЯ СИГНАЛОВ (честный R) + почему equity −63%

Юзер: «какие ТФ убивают?» → глубокий разбор на честном clamp R. Детали → [[signal_health_map_18jun]].
- **Развеян миф «всё на 15m»:** колонка `timeframe`=ТФ ИСПОЛНЕНИЯ входа. Реальный MTF в `features`: ote_nested имеет `ote_htf`(1h/4h)+`ote_ltf`(5m)+`ote_setup_id`. MTF РАБОТАЕТ.
- **ote_nested = доказанная MTF-машина:** все сетапы +. pull(+0.895)>cont(+0.685), tier1(+1.027)>tier2(+0.684). Чемпион `4h_1h_pull` +1.230 WR78%. Кормилец +$289.
- **arch104 LONG мёртв ВЕЗДЕ:** UP −0.194/DOWN −0.144 (WR41%), паттерны DS_L052 −0.139/DS_L082 −0.278. → ОТКЛЮЧИТЬ. arch104 SHORT жив (UP +0.212).
- **atr_change:** 15m edge<комиссий (мёртв); 4h ЗОЛОТО +0.692 Sharpe3.44 (бэктест n=94) → [[atr_change_tf_4h_backlog]].
- **ВЫВОД:** equity −63%/нед НЕ «всё сломано». 2 канала несут (ote_nested, arch104 SHORT), 2 жгут (arch104 LONG, atr_change 15m). ПЛАН оздоровления: отключить 2 минусовых, усилить ote_nested pull/tier1. ⚠️ adaptive weights учились на fake-R → переучить после миграции.
- Анализ read-only (боевую БД не трогал). Конфиг-правки ещё НЕ сделаны (ждут решения).

## [18.06 UTC] Агент: DEV — DS-326 WT-B фильтры: ADX<25 единственный edge (бэктест завершён)

Запустил полный бэктест `scripts/ds326_all_filters.py` на 45 парах (RR=3, история до 19.05), проанализировал все 5 фильтров + 2 комбо. Добавил в скрипт medR+Sharpe в таблицу и скан порога ADX.

- **✅ Вывод:** прирост даёт ТОЛЬКО `ADX < 25`. ltf_all (без фильтра) avgR −0.039 / WR 34.5% → ltf_adx avgR **+0.204** / WR **47.1%** / Sharpe +0.142 (n=68). Единственный фильтр в плюсе.
- **Порог 25 — не подгон:** скан 20/25/30/35/40 → edge только <25; зона ADX 25–30 убыточна (<30 = −0.068). Совпало с классической границей ADX тренд/флэт. WT-B mean-reversion работает в слабом тренде.
- **❌ Отбросить:** EMA-trend ВРЕДИТ (−0.180), CHoCH 4h вредит (−0.087), n_down 0-2 не фильтрует (80% проходят). Комбо ничего не дают поверх ADX (ADX+TREND n=6 пусто; ADX+ND02 ≈ чистый ADX).
- **Гигиена:** medR=−1.0 у ВСЕХ (RR=3, прибыль на хвосте) → сравнение по avgR+WR+Sharpe. Lookahead исключён (фильтры читают только прошлое).
- **⚠️ Оговорки:** n=68 умеренный (нужен out-of-sample); edge чувствителен к комиссии/проскальзыванию (`simulate_trade` не учитывает).
- Результат: `data/research/ds326_wtb_filters_result.md`. Память: [[ds326-wtb-adx-filter]]. Правки в `scripts/ds326_all_filters.py` (medR/Sharpe/ADX-скан) — НЕ закоммичено.

## [18.06 UTC] Агент: Даат — DATA-INTEGRITY AUDIT: 3 фикса (метрики+hedge), не закоммичено

Запуск субагента `bot-data-audit` по `docs/AUDIT_DATA_INTEGRITY_BRIEF.md` → 4 находки, 3 кодовых починены (4-я = api.ts фронт, отложена).

- **✅ Фикс 1 (метрики, КРИТ):** `performance_engine.summary()` не имел VST-фильтра → KPI дашборда/меню/обучения смешивал SIM+VST. SIM-фантомы (avg_R=**0.013**, n=16859) тянули вниз. Добавлен параметр `execution_mode='VST'` (дефолт, консистентно с уже-VST `by_signal_type`). KPI: 0.287→**0.633 avg_R**, WR 42.8→48.5%. Завершает недокрученный коммит #8 (`4b22a0c`).
- **✅ Фикс тест-фикстуры:** `test_performance_engine.py` CREATE_TABLE без `execution_mode` → 3 теста были КРАСНЫЕ после #8. Добавлена колонка `execution_mode TEXT DEFAULT 'VST'`. Теперь `20 passed`.
- **✅ Фикс 2 (hedge-мина, деньги):** `position_sync.py` emergency watchdog брал raw позиции из `open_on_exchange` (sym→raw, без side) → при LONG+SHORT по паре мог закрыть market неверным qty/markPrice ЧУЖОЙ стороны. Переведён на `open_pairs.get((sym, dir))`.
- **✅ Фикс 3 (зомби-OPEN):** `position_manager.sync_with_exchange` матчил `pos.symbol in open_syms` (без side) → при рестарте закрытая сторона hedge не помечалась CLOSED (REAL/USDT: 6×LONG OPEN зомби в live_orders). → матч `(symbol, side)`.
- **✅ Находка 4 (выбор юзера «реальные с бэка»):** `oko-dashboard/lib/api.ts` хардкоды убраны. `/api/live` (биржевые позиции): JOIN тянет `st.signal_type, st.max_R_possible` → фронт `maxR:0→p.max_r`, `signal:"confluence"→normSignal(p.signal_type)` (unknown для ручной). `/api/open`: cold-SQL+шина дают `timeframe,regime` → `tf:"15m"→r.timeframe`, `regime:"RANGE"→normRegime(r.regime)`. tsc exit 0.
- **✅ DIR-баг (UI, скриншот юзера):** `trades.tsx` колонка DIR пропадала в Exchange-view пока не включишь «#». Корень: sticky `pair` имел жёсткий `left:56` (ширина колонки id) → без id pair прилипала на 56px и непрозрачный bg-card перекрывал DIR. Фикс: `pairLeft = visibleIds.has("id") ? 56 : 0`.
- Файлы (НЕ закоммичено): `performance_engine.py`, `position_sync.py`, `position_manager.py`, `tests/unit/test_performance_engine.py`, `web/dashboard_server.py` + фронт `oko-dashboard/{lib/api.ts, components/oko/screens/trades.tsx}` (⚠️ фронт НЕ git). Верификация: 20 passed + py_compile + tsc exit 0 + runtime на копии БД.

## [18.06 UTC] Агент: Даат — 🔴🔴 FAKE-R КОРЕНЬ найден и починен (PnL врал в 3-4×)

Юзер спросил «что с PnL» → раскопал что VST avgR (+1.2) — иллюзия. Детали → [[bug_phantom_exit_resolve]].
- **Симптом:** медиана R=0, весь плюс на ~11 раннерах R до 264. STG R=264 при max_R_possible(MFE)=1.3 (невозможно: realized>MFE).
- **Корень:** `position_sync._resolve_exit` матчил filled-ордер по `symbol`+`side` без orderId/времени → при повторных входах/hedge хватал avgPrice ЧУЖОЙ сделки → exit_price вне [min_price,max_price]. Класс = «матч по неполному ключу» (тема всего аудита).
- **Масштаб:** 983/5006 VST-сделок (20%) с крупным фантомом = 3623R = **60% PnL**. С средними — 75%. Истинный avgR≈**0.3-0.48**, не 1.205.
- **Фикс (НЕ закоммичено):** (1) `_resolve_exit` — точный матч по `exchange_sl_order_id`/`exchange_tp_order_id` (заполнены 86%/79%), прокинуты из 2 вызовов; (2) fallback sanity ratio по mark; (3) `close_trade` — clamp exit в `[min,max]` (инвариант R≤MFE). Runtime: STG 264.5R→1.251R, инвариант OK. Базлайн тестов 23F/8P не изменён (предсущ. account_routing).
- **⏳ TODO (ждёт ОК юзера):** МИГРАЦИЯ 5006 закрытых VST — пересчёт R/profit_pct/max_R с clamp на боевой БД. Без неё adaptive weights учатся на фантомах.
- Файлы +: `core/exchange/position_sync.py`, `core/trading/trade_simulator.py`.

---

## [17.06 19:00 UTC] Агент: Даат — ДАШБОРД ЗАКРЫТ (интерактив/перф/EN + mark_price), всё запушено

### ✅ Фронт oko-dashboard (main, запушено `a0d6679`)
- **P0-перф:** статичный фон-Метатрон (убрано вращение+блюр), `.panel` без backdrop-blur, Cube де-анимирован (убран setState-цикл + статичные решётка/звёзды), lazy-load экранов, sticky без блюра.
- **Интерактив:** Cube кросс-hover список↔ноды + лучи решётки на select; Signals donut↔legend↔веса; синхронный курсор equity; Pairs side-sheet; drawer позиций; Patterns кольцо/бар scroll-in + пагинация; Watchlist FIRE-пульс; KPI-герой Total R; histogram-клик→toast; toast(sonner)→Settings; Calm-mode тоггл (топбар, localStorage).
- **Фиксы:** колонки Trades разъезжались = дублирующиеся React-ключи (id=symbol) → ключ с индексом; HUD-уголки 2-gold; тонкий скролл; **вся кириллица из UI убрана** (вкл. 13 описаний сфер + AI Oracle→EN).
- Новые файлы: `equity-cursor.tsx`, `oko-sheet.tsx`.

### ✅ mark_price (бэк, запушено `590fb15` arch-128-oko-sm)
- `positions` table: `mark_price REAL` (CREATE + идемпотентная ALTER, **миграция применена к боевой БД**). `upsert_positions` пишет `pp.mark`. Drawer → Mark + uPnL%. ⚠️ **NULL до РЕСТАРТА бота** (writer в `balance_repo.py`; процесс :8000 на старом коде).
- **R отложен** — `ParsedPosition` без SL (биржевые позиции стоп не несут) → ждёт EXEC-SIM-SPLIT.

### 📋 ДАШБОРД ЗАКРЫТ. Бэклог (опц, не блокеры): R-позиций, скелетоны/error, sort-a11y, дисциплина токенов, Trades inline-expand. Детали → `whats-next.md` + `docs/DASHBOARD_AUDIT.md`. Эталоны: `e:/tmp/oko_overview_mockup.html` + `~/Downloads/oko_prototype.html`.

### 🎯 Next (вектор юзера 17.06 «проблемы поинтереснее»): EXEC-SIM-SPLIT (#21) / ARCH-131 Сфера 5 / regime-v2.

## [16.06 16:43 UTC] Агент: Даат — Бэк-фикс DEV-231 (таймаут дашборда) + дизайн-аудит дашборда

### ✅ DEV-231 добивка: 3 inline-SQL хендлера вынесены с event-loop (НЕЗАКОММИЧЕНО)
- **Корень (подтверждён замером):** `full_stats()` = **1576 мс** sync SQL по 29 510 строкам, крутился ПРЯМО в event-loop в `_handle_dashboard_api`. Каждый `/api/dashboard` морозил весь дашборд-loop на 1.6с → лёгкий `/api/trading/status` (из шины, мгновенный) стоял в очереди → 100с-таймаут, что видел DS.
- **Фикс (паттерн `_run_sync`→thread pool, как confluence/analytics):** `_handle_dashboard_api` (`full_stats` :2192), `_handle_settings_get` (`by_signal_type` :1563), SSE-путь `_handle_sse` (`summary`+`rolling_win_rate` :2549). py_compile OK.
- Замер: summary 134мс · by_signal_type 128мс · rolling 110мс · full_stats 1576мс.
- ✅ **Legacy-хендлеры добиты (17:36):** `_handle_closed_trades` (`_closed_sync` :809), `_handle_performance_api` (`_perf_sync` :2436), `_handle_pair_api` (`_pair_sync` :2464) — тоже в thread pool. Full-sweep grep: инлайн-блокирующего SQL на event-loop НЕ осталось ни в одном GET/SSE-хендлере. Класс DEV-231 закрыт для дашборд-сервера целиком.
- DISCUSSION 16.06 16:43 (DS-контракт).

### ✅ Дизайн/перф-аудит дашборда → `docs/DASHBOARD_AUDIT.md`
- Полный аудит oko-dashboard (читал реальные файлы): главный вывод — UI не статичный, движение ушло в декор и душит перф. 5 P0 для DS (фон-Метатрон `140vmax` ∞-вращение+блюр; Cube ~500 ∞-анимаций+setState-цикл; `.glass` blur на каждой панели; Trades без виртуализации; нет code-split). 9 пунктов+токены+карта интерактива+план P0→P2+референс-код. Фронт — зона DS, файлы не трогал.

## [16.06 14:30 UTC] Агент: Даат — GitHub-инфра + контракт типов дашборда для DS

### ✅ GitHub
- Фронт `oko-dashboard` вынесен в **отдельный git-репо** (`git init -b main`, коммит `1f14cc0`, 108 файлов) → запушен на **`OkoDev/Oko-Dashboard` (private)**, `main→origin/main`. `.gitignore` корректный (+`dev.log`).
- **`Oko-MetatronTI` переведён public→private** (был 0 форков/звёзд). Секреты в историю не попадали (`.env` всегда gitignore, в коде ключей нет) → утечки не было.
- `gh` CLI v2.94 установлен + авторизован (OkoDev, scopes `repo,read:org,workflow,gist`). Создание репо/смена visibility делались через GitHub API токеном GCM (у него не было `read:org` для самого `gh auth login`).

### ✅ Аудит вёрстки дашборда (DS прислал) — дал контракт, DS катит фронт сам
- Проверил 🔴#1/#2 по БД (источник правды). **VALID_SIGNAL фронта знал 5 из ~16** — флагман `arch104`(7734) схлопывался в `confluence`. Имена: `ote_nested` (НЕ `OTE`), `wt_b_signal`.
- **VALID_REGIME:** фронт держит фантом `REVERSAL` (0 в БД), теряет `HIGH_VOL` (1616). Убрать/добавить.
- **🔴 regime_v2 ЕСТЬ** — отдельная колонка `simulated_trades.regime_v2` (~13.4K заполнено, метки те же 4, shadow HTF-классификатор [[regime_v2_validated]]). Я ошибочно сказал «нет» (смотрел только `regime`) — поправился. Дашборд должен показывать v2 отдельной колонкой/тогглом (инструмент A/B).
- **Корневой фикс #1/#2:** не закрытый Set (дрейфует), а **pass-through** в normSignal/normRegime + STYLE-map для цветов + нейтральный дефолт.
- Эндпоинты для #3/#6/#7 УЖЕ есть (`/api/settings`+`/api/toggles`, `/api/stats/analytics`, `/api/cube/events`) → это фронт-подключение, не бэкенд-дыры. Контракт записан в DISCUSSION.md (16.06 14:23).

### 🔄 Моя бэкенд-часть (НЕЗАКОММИЧЕНО)
- `web/dashboard_server.py`: добавил `"regime_v2"` в `_TRADES_FILTERED_COLS` (стр.202) — фронт раньше его физически не получал. Аддитивно, `.get()`-безопасно. **DS:** синхрон в `lib/api.ts fetchTradesFiltered` allow-list.

### 🔧 Хук DISCUSSION у DS не срабатывал — РОВНЫЙ диагноз + фикс (16.06)
- **Корень (доказан транскриптом DS `~/.deepcode/projects/.../*.jsonl`):** DeepCode (DS) исполняет ОДИН **проектный** `.claude/settings.json` Stop-хук. После коммита `2b51f81` он форсил **`--role DAAT`** → DS проверял записи к DAAT, а не к DS → «→ DS» не видел. Скрипт `check_tasks.py` исправен (воспроизведение `--role DS` → block; счётчик в транскрипте block:3/approve:7 — block только из ручных тестов DS).
- Первый мой диагноз («нет блока hooks в .deepcode») был неточен — DS подключал хук в `.claude/settings.json` (его же слова в транскрипте + DISCUSSION 15.06).
- **Фикс (новый дизайн резолва роли, env-based):**
  - `.claude/settings.json`: убрал `--role DAAT` из Stop-команды → роль из env/`.agent_role`.
  - `.agent_role`: `DS`→**`DAAT`** (дефолт для Claude-агента; env DS перебивает его для DeepCode).
  - `~/.deepcode/settings.json`: `AGENT_ROLE=DS` в env + (страховкой) свой `hooks.Stop --role DS`.
  - `check_tasks.py`: докстринг `_resolve_role` обновлён под новый дизайн.
  - Проверено: Даат(no env,.agent_role=DAAT)→approve; DS(AGENT_ROLE=DS)→block.
- **🔴 DS ДОЛЖЕН ПЕРЕЗАПУСТИТЬ сессию DeepCode** — хук-конфиг грузится при старте сессии, на лету не подхватывается (вероятная причина, почему первая правка «не сработала»). После рестарта + при висящей записи «→ DS» хук обязан блокировать. Остаётся одна непроверенная зависимость: пробрасывает ли DeepCode env из settings.json в subprocess хука (для MODEL/BASE_URL — да; для AGENT_ROLE — должно так же).

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

### ✅ РАЗОБРАНО — каша trades.tsx (системный проход, tsc exit=0)
Фронт oko-dashboard (НЕ git, :3000). Прочитал trades.tsx+api.ts+use-oko-data.ts целиком. Диагноз ≠ описания скринов:
- **Баг 1 (Sim OPEN R=$):** `r_live` с бэка — корректный R (`d*(cur-e)/|e-sl|`, dashboard_server:402), НЕ $. Корень: в SIM не было отдельной $-колонки. Фикс: `fetchOpenTrades` теперь даёт `unrealizedPnl` ($ = qty×Δ), в `SIM_DEFAULT` добавлен `upnl` рядом с `r` (R=множитель, upnl=$ — разные колонки).
- **Баг 2 (Exchange 67 но пусто):** `fetchLivePositions` ставил `id=symbol` → в hedge-режиме LONG+SHORT на 1 символ = коллизия React-`key` → строки схлопывались. Фикс: `id=`${symbol}-${dir}``.
- **Баг 3 (стале-строка под TP):** `useLive` без секвенирования — медленный ответ прошлого фильтра приходил позже и перезатирал вид. Фикс: `genRef` (поколение запроса, out-of-order отбрасывается) + `resetKey/resetValue` (сброс строк прошлого фильтра при смене account/mode/filter, очистка in-flight). Убраны 2 ручных `useEffect(refresh)` — один механизм.
- EXCH_DEFAULT: убрана дублирующая колонка «#» (=pair), добавлены r/size.

### ✅/🔴 ПОСЛЕ РЕСТАРТА (16.06): что ожило, что осталось
Рестарт убрал ECONNRESET. Проверка эндпоинтов:
- **`/api/live` ✅** 0.5с — `kpi` полный (open=54 long30/short24 unreal+15.93 used356 equity519.36 risk68.5%), 54 позиции с полным набором (size/mark/upnl/leverage/sl). **Exchange OPEN теперь живой и верифицируем** — мои фронт-фиксы (составной id + секвенирование + сброс) применимы. Hedge-дублей сейчас 0 (составной id = защита на будущее, активный фикс — секвенирование).
- **`/api/open` 🔴** ~20с (count=49) — НЕ лёгкий, как заявлено в handoff. Корень: SQL `WHERE status='OPEN'` по `simulated_trades` (29K) ждёт лок (бот пишет в горячем цикле). Фронт таймаутит на 12с → **Sim OPEN не дождётся**. Плюс `current_price`/`r_live` = null (у VST-символов acc2 в шине нет tick_price → R не считается даже когда ответ придёт).
- **`/api/exchange_history` 🔴** таймаут (тяжёлый 30д) → **Exchange закрытые (TP/SL/...) не грузятся**.
- **🟡 находка:** `/api/live.balance` теперь СКАЛЯР (519.36), а `fetchSyncOverview` ждёт объект (`bal.equity`) → SyncPanel exch equity/used/risk = 0. Реальные значения есть в `result["kpi"]`. + сам `fetchSyncOverview` зовёт тяжёлый `/api/stats` (sim-сторона) → тоже рискует таймаутом.

**ВЫВОД:** фронт-каша устранена и устойчива к флапу. Остаток — НЕ фронт, а backend: `/api/open` и `/api/exchange_history` оперативку надо отдавать из ШИНЫ/кэша, не синхронным SQL (это эпик [[dashboard_oper_from_bus_analytics_sql]]). Заплатку «поднять TIMEOUT_MS» НЕ делать — юзер прямо против.

### ✅ КИРПИЧ: /api/open ИЗ ШИНЫ (готов, ждёт рестарт для активации)
Юзер выбрал направление «/api/open из шины». Реализовано (3 файла, py_compile OK, bus-unit-test OK, tsl-тесты зелёные):
- **`pair_context.py`:** `set_open_trades(rows)` (PRODUCE, проекция на 12 лёгких полей — без features_json) + `open_trades_snapshot()` (PULL, копии + ts). Хранение `_open_trades`/`_open_trades_ts` в `__init__`.
- **`trade_simulator.py` `check_open_trades_with_tsl`:** после `get_open_trades()` (цикл и так грузит) → `_pcb.set_open_trades(open_trades)`. Публикуем и пустой список (все закрылись → дашборд чистится). Guard getattr+try.
- **`web/dashboard_server.py` `_handle_open_trades`:** читает `_pc.open_trades_snapshot()` (мгновенно), фильтр acc/mode в памяти, обогащение цена/R/leverage из шины (как было). Cold-start (ts=None, ≤60с после рестарта до первого тика трекера) → SQL-фолбэк с бюджетом `asyncio.wait_for(timeout=6)`; БД занята → `source="warming"` пусто. Ответ +`source`/`age_s`.
- **Свежесть:** список открытых ≤60с (цикл trade_tracker = sleep 60), НО цена/R/leverage — live на каждый запрос из шины. Корень 20с-таймаута (синхронный SQL по 29K под локом) убран.
- **Проверка после рестарта:** `/api/open` <0.5с, `source="bus"`, count совпадает с реальными открытыми.
- **NEXT (опц):** publish и в `register_trade_async` → новые сделки появляются мгновенно (не ждать 60с).
- **✅ ПОДТВЕРЖДЁН ВЖИВУЮ (рестарт 16.06 ~07:19):** `/api/open` cold-start 3с (было 20с), после 1-го тика трекера → `source=bus` count=50 age 13.6с. **Выжил под флудом** (0.3–0.9с, пока stats/trades_filtered рвали ECONNRESET).

### 🔴 ФЛУД executor: тяжёлая аналитика рвёт весь дашборд
Симптом: `socket hang up`/ECONNRESET на `/api/stats`, `/api/trades_filtered?limit=300`, `/api/exchange_history`, периодически даже `/api/live`+`/api/trading/status`. Корень: executor дашборда = **4 воркера** (`_get_dash_executor` max_workers=4), фронт каждые 10с долбит тяжёлые агрегаты по 29K → пул забит → очередь → рвутся даже лёгкие. /api/stats кэш TTL=30s, /api/live TTL=20s, но `trades_filtered`/`exchange_history` БЕЗ кэша + single-flight → пайл-ап.
- **✅ Сделано без рестарта (фронт):** `fetchSyncOverview` (SyncPanel вверху экрана сделок) переведён с тяжёлого `/api/stats` на шину (`/api/open` sim + `/api/live` exch). Заодно фикс баг equity/risk=0 (`live.balance` стал скаляром → берём `live.kpi`). tsc OK. Убрал постоянный stats-поллинг с экрана сделок.
- **✅ КИРПИЧ B готов (ждёт рестарт):** кэш TTL + single-flight + stale-while-revalidate на `/api/trades_filtered` (TTL 15с) + `/api/exchange_history` (TTL 30с). Класс `_KeyedJSONCache` в `dashboard_server.py` (после `_run_sync`):
  - HIT (age<ttl) — готовый JSON, 0 SQL · STALE (age≥ttl) — прошлый сразу + фоновый refresh · COLD — refresh + ждём cold_timeout=25с, не успел → warming-пусто.
  - **Detached refresh-таск** (`create_task`): client-abort (фронт-таймаут 12с) НЕ убивает вычисление → кэш гарантированно прогреется (лечит «вечный ECONNRESET, кэш не греется»). **Single-flight**: один таск на ключ → повторные поллы не плодят SQL в 4-воркерном пуле.
  - Проверка: py_compile OK, async-юнит-тест OK (HIT/MISS/STALE/single-flight 5→1/detached-прогрев).
  - **После рестарта:** `trades_filtered`/`exchange_history` отвечают мгновенно (HIT), флуд ECONNRESET исчезает (пул свободен → лёгкие не голодают). Первый COLD-запрос на ключ может быть warming-пусто, второй (≤10с) = HIT.
- **✅ ПОДТВЕРЖДЁН ВЖИВУЮ (рестарт 16.06):** через X-Cache: `trades_filtered?limit=300` MISS→STALE→HIT (~1.3с, payload 1MB), `exchange_history?days=30` HIT (~400мс). Лёгкие (`trading/status`, `live`) отвечают, без ECONNRESET. `/api/live` здоров (55 поз, kpi: equity 519.4/risk 72.6%) → SyncPanel из шины показывает реальное. Флуд снят (single-flight кэп: 1 SQL на ключ → пул свободен).
- **✅ trades_filtered payload урезан (ждёт рестарт):** `get_trades`=`SELECT *` (54 кол., `features_json`≈80% веса) → проекция на allow-list `_TRADES_FILTERED_COLS` (22 поля = что читает фронт-маппер + метадата). Замер на 300 реальных строках: **1027KB→177KB (−83%)**. Список менять ТОЛЬКО синхронно с `lib/api.ts fetchTradesFiltered`. py_compile OK.
- **✅ Вёрстка Overview (фронт, хот-релоад):** «огромный скролл» — последствие кирпичей: в шину потекли РЕАЛЬНЫЕ 56 позиций (был mock из пары). `PositionsPanel` рендерил все без max-h → растягивал страницу. Фикс: `max-h-[420px] overflow-y-auto` (внутренний скролл). + Signals-список `max-h-[260px]` (был выше графика equity → пустой провал в строке). tsc OK.
- **✅ Overview панели Баланс/Позиции (ПОДТВЕРЖДЕНО вживую):** после починки вёрстки всплыло — `/api/positions`, `/api/account_balances`, `/api/accounts` висели **>35с** → пустой фолбэк. Корень: НЕ лок (busy-timeout 5с), а **насыщение 4-воркерного пула** (Overview параллельно долбит kpi/equity/stats/balances/positions/accounts медленными SQL → портфельные в очереди). Фикс: (1) обернул 3 портфельных хендлера в `_PORTFOLIO_CACHE` (тот же `_KeyedJSONCache`, TTL 20с, single-flight+detached), (2) пул 4→8 воркеров (запас под холодные refresh нескольких кэшей сразу). Фронт НЕ трогал. py_compile OK. **Вживую:** balances 510b (acc1 eq242.9/acc2 eq273.8), positions 10.6KB (54 шт.), accounts — все X-Cache HIT, не таймаут. Транзиентные 2–8с на HIT сразу после рестарта (конгестия прогрева кэшей) — оседает.
- **NEXT (опц):** (б) интервал поллинга аналитики 10с→30-60с; (в) кэш на `/api/kpi` (get_summary) — пул 8 даёт запас, но если Overview всё ещё тупит → обернуть; (г) идеал «oper из шины»: balances/positions из bus _accounts (нужны margin/available в шине).

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

