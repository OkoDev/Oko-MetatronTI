# 📋 TASKS — Координация агентов

> **Архив завершённых задач:** [TASKS-ARCHIVE.md](TASKS-ARCHIVE.md)
> **Живой диалог агентов:** [DISCUSSION.md](DISCUSSION.md)
> **Полные описания задач:** [docs/DISCUSSION-TASKS-DETAILS.md](docs/DISCUSSION-TASKS-DETAILS.md)

---

## 🔴 ПРАВИЛА ФОРМАТА — ОБЯЗАТЕЛЬНЫ ДЛЯ ВСЕХ АГЕНТОВ

**Строка задачи:** `| [ID](#anchor) | Ст | Краткое (≤80 символов) | Роль |`

- **Ст** = один эмодзи-статус: 🔴 срочно · 🟡 важно · 🟢 в плане · 🔵 бэклог · 🔄 в работе · ⏸ отложено · ✅ закрыто · 🧊 заморожено
- **Краткое** ≤ 80 символов — первая фраза, суть без деталей
- **Детали** (всё что больше одной фразы) → в `DISCUSSION.md` или `docs/DISCUSSION-TASKS-DETAILS.md`, **НЕ в ячейку TASKS**
- **Пустая строка** между каждыми двумя строками задач (читаемость в IDE)
- **Закрытые ✅** → немедленно в [TASKS-ARCHIVE.md](TASKS-ARCHIVE.md) (`python scripts/tasks_tidy.py --apply`)
- **Нельзя:** многострочные абзацы в ячейках · пустые строки внутри блока `|---|` · ячейки >200 символов

**Якорь:** ID в нижнем регистре, пробелы → дефисы. Пример: `[ARCH-96](#arch-96)`.

---

## 👥 Роли

| Роль | Кто | Зона ответственности |
|---|---|---|
| **ARCH** | yogoru | Архитектура, постановка задач, review, приоритеты |
| **DEV** | oko.webdev | Разработка, интеграция, бэктест |
| **TRADER** | Claude (TRADER) | Торговая экспертиза, валидация стратегий, живой анализ |
| **DS** | DeepSeek (DeepCode) | Рутина: `scripts/` аналитика, тесты, `docs/`, research, рефакторинг низкого риска |

**Workflow:** ARCH ставит → DEV берёт → ARCH review → TRADER валидирует
**Вопросы между ролями:** писать в DISCUSSION.md с тегом `→ ARCH:` / `→ DEV:` / `→ TRADER:` / `→ DS:`

**🔴 Координация Claude ↔ DeepSeek (два агента на git):** разделение по риску — Claude держит ЯДРО (`core/trading/`, signals, gates, `bot/`), DS — рутину. Перед коммитом `git status` → коммить ТОЛЬКО свои файлы; файл уже `M` = чужая работа. Критичный код (register_trade, gates, sl_tp) DS не трогает без согласования. Полный протокол: `AGENTS.md`.

---

## 🎧 LISTENER-CANON (14.06.2026) — канонизация механизма слушателей (Слой 2-5 роадмапа)

> **Принцип (юзер):** scan_loop = оркестратор, ВСЁ остальное = подписчики ОДНОЙ шины (`PairContextBus.subscribe`). Рост = добавить слушателя, не трогая ядро. Не плодить запросы — слушать информативную шину. `docs/BUS_SUBSCRIBER_ROADMAP.md` Слой 2-5.

| ID | Задача | Статус | Файлы |
|---|---|---|---|
| **LISTENER-CANON** | ✅ **Шаг 1 ГОТОВ (5d9cb97).** `PairContextBus.subscribe_async` (sync→create_task, изоляция ошибок) + `NotificationDispatcher` переведён с прямого вызова на подписку `SMC_SNAP_UPDATED` → 0 строк notif в scan_loop. snap самодостаточен (`compute_and_publish(current_price=)`). Бот PID 13576: «dispatcher подписан на шину» ✅, тест 3/3. `SubscriberHub` — на 2-м подписчике (Dashboard). | ✅ Шаг 1 done | `core/context/pair_context.py`, `core/smc/sub_cube.py`, `bot/core/bot.py`, `bot/loops/scan_loop.py` |

| **LISTENER-DASH** | ✅ **Шаг 1 ГОТОВ (fdf750d).** SSE-метрики event-driven: `_metrics_version++` при закрытии сделки (auto/ручное/repair) → тяжёлый payload (summary/analytics/equity по 24K+) пересчитывается ТОЛЬКО при сдвиге версии или fallback 60с, не вслепую каждые 5с × N клиентов. per-client `_seen_version`. **Шаг 2 (бэклог):** лента FVG/OB через подписку `SMC_SNAP_UPDATED` → push (новый UI-виджет). | ✅ Шаг 1 done | `web/dashboard_server.py` (`_handle_sse`) |

| **LISTENER-STRAT** | **Слой 4:** Strategy-as-Subscriber — ote_nested/arch104/atr_change из scan_loop → отдельные подписчики шины. Большой рефактор, после стабилизации Слоя 2. | 🔵 бэклог | scan_loop, observer-loops |

---

## 🏛️ BUS-ACCOUNT-EPIC (14.06.2026) — account/portfolio-измерение шины (L1→L2→L3)

| ID | Задача | Статус | Файлы |
|---|---|---|---|
| **BUS-ACCOUNT-EPIC** | **Спроектирован (рой 2 раунда + DS).** Расширить `PairContextBus` account/trader-измерениями (НЕ отдельный PortfolioBus). L1 PairState (есть) → L2 AccountState (equity/margin/drawdown) → L3 TraderState (дирижёр стратегий). Producer EXEC-WS push + REST fallback; доступ синглтон `get_bus()`. Детали+консенсус: DISCUSSION [14.06 🏛️]. | 🔵 эпик/бэклог | `core/context/pair_context.py`, `core/exchange/position_sync.py`, `docs/BUS_SUBSCRIBER_ROADMAP.md` |

| **BUS-L2-BRICK** | **Первый кирпич:** `BalanceTracker` — подписчик `EXEC_WS_BALANCE`/`ACCOUNT_UPDATE` → `AccountState` в шине. Убирает REST-polling баланса (event-driven) + живой deposit для SIM/dashboard (сейчас хардкод 710). Связь OPS-06-ACCOUNT. | 🟢 готов к старту | `core/context/pair_context.py`, `core/exchange/exec_ws_integration.py`, `core/infra/trading_settings.py` |

| **BUS-L3-ORDER** | **⚠️ Порядок L3 (спор с роем):** рой → Capital Allocator вторым. Даат держит → **Correlation Shield РАНЬШЕ** (не зависит от Sharpe; Capital Allocator аллоцирует по Sharpe = частично фейк-R → усиление ошибки). Capital Allocator ТОЛЬКО после DATA-AUDIT-2. | 🔵 после DATA-AUDIT-2 | — |

---

## 🟡 NOTIF-ENGINE (14.06.2026) — Notification Engine MVP (вердикт роя 7/7)

| ID | Задача | Статус | Файлы |
|---|---|---|---|
| **NOTIF-MVP** | ✅ **ГОТОВО (fbda2c8, Даат 14.06)** | ✅ done | |
| | `NotificationDispatcher` + `FvgDetectedListener` + `FvgTouchListener`. scan_loop = 1 строка `dispatcher.on_smc_snap`. `_norm_symbol` (ccxt↔YAML). Open/Closed: новый тип = новый listener, loop не трогаем. | | `core/notifications/dispatcher.py`, `core/notifications/evaluate.py` |

| **NOTIF-TIER2** | TIER-2 уведомления: CHoCH new / OTE zone / OB touch / Pivot breach. Точки вставки в scan_loop. Включать по одному после проверки FVG. | 🔵 бэклог | `config/notifications.yaml` (enabled:false → true), `bot/loops/scan_loop.py` |

| **NOTIF-DASH** | Дашборд: UI-переключение правил. Рой: после YAML-MVP стабилен. | 🔵 бэклог | — |

---

## 🔴 PERF-LOOP-DRIFT (13.06.2026) — event-loop конкуренция → DRIFT 118 (zombie/orphan)

| ID | Задача | Статус | Детали |
|---|---|---|---|
| **CONFIG-SLTP-BUG** 🔴🔴 #1 | **Секция `sl_tp_engine` (config.yaml 293-363, 26 ключей) НЕ читается ботом — код читает `trading.X` → DEFAULTS.** `config.get('trading.use_tsl')`=None, значение в sl_tp_engine. Игнорируются: use_tsl, tsl_activation_r_per_strategy (ote TSL=1.0 default, НЕ 4.0!), cascade_tsl, use_breakeven, breakeven_activation_r, max_positions_per_direction, min_sl_dist_pct, dual_tp, tp_selector_*. **Вся TSL-сага 14.06 была на неверном config (ote TSL 1.0, не 4.0).** ФИКС: влить sl_tp_engine в trading ИЛИ код→sl_tp_engine.X. ⚠️ НЕ наспех — разом включит 26 параметров (defaults→config), резкая смена exit-логики. Аккуратно: подтвердить trading.X везде → перенести → проверить применение → наблюдать. Бот на defaults стабилен. Детали: memory bug_sl_tp_engine_section_ignored. | 🔴 #1 ARCH (утром, осторожно) | `config.yaml` (293-363), `trade_simulator.py`, `trade_tracker.py`, `gates/`, `correlation_guard.py` |
| **TSL-CLEAN-TEST** → DS | ✅ **ЗАКРЫТ (ff3b029, Даат 14.06).** Парный бэктест DS: TSL нейтрален, WR×2. gear1_be_atr 1.0→1.5 для ote_nested применён (TSLProfile.gear1_be_atr=1.5 в tsl_engine.py). DS-321 гибрид работает. | ✅ done | `core/trading/tsl_engine.py` (gear1_be_atr=1.5) |
| **DEV-226-Ph2** → DS | ✅ **ЗАМЕР НА ЧИСТЫХ SL ГОТОВ (DS 13.06).** CLEAN VST: pull n=108 avgR=+1.94 WR=37% vs cont n=382 avgR=+1.47 WR=25%. Pull edge +0.47R ПОДТВЕРЖДЁН. n_down из shadow: всего 34 сделки, замер невозможен (данные копятся с 11.06). TSL на чистых SL: ВРЕДИТ (+0.32 vs +1.66 без). **Ждать n≥30 для pull×n_down.** | ⏳ ждёт n≥30 | `verdict_aggregator.py`, `simulated_trades` |
| **ATR-OTE-E3** → DS | ✅ **БЭКТЕСТ ГОТОВ (DS 13.06). WR89% — ФЕЙК (n=9).** 36K сигналов, 20 пар: A (текущий) avgR=+0.059, B (mid-OTE) +0.068. OTE покрытие 7%. PAIRED (n=2'442): A +0.095 vs B +0.068 → A ЛУЧШЕ. Полная OTE-конверсия НЕ улучшает. DEV-209 (текущий) = оптимум. Скрипт: `scripts/atr_ote_e3_backtest.py`. | 🟢 done → Э3 не нужен | `scripts/atr_ote_e3_backtest.py` |
| **OTE-RBUG** → DS | ✅ **АУДИТ ГОТОВ (DS 13.06).** Edge РЕАЛЬНЫЙ. SL<0.3%: n=557, sumR=+1'073 (VST +3.38 SIM +0.11). SL>=0.5% (чистый): n=2'017, avgR=+2.38, WR=58.1%, sumR=+4'808. VST чистый: +3.47 avgR, +4'152R. Инвертный SL: 1'982 сделок (72%), median=0.85% от entry — не «SL на другой стороне», а SL вплотную к entry. **Баланс не растёт НЕ из-за фейк-R, а из-за position sizing:** SL=0.1% → size=1000× → 1 убыток съедает 10 прибыльных. **Нужен min SL distance ≥0.5%.** **РОЙ 7/7 СОШЁЛСЯ независимо:** (1) min risk_distance guard 0.5-1%/ATR для R И position_size; (2) биржевой closed PnL (fills)=source of truth; (3) hard cap notional; (4) валидация стороны SL REJECT. Edge реальный (+4808R чистый) — guard НЕ убьёт раннеры. **ФИКС ч.1 СДЕЛАН (5e2fd0f, Даат):** min_sl_dist 0.3→0.5 + валидация стороны SL (LONG sl>=entry/SHORT sl<=entry→DROP) в обоих путях (gate + register_trade_async). Тест 5/5. **Backlog ч.2 (рой #2/#3):** биржевой closed PnL=source of truth, hard cap notional. | 🟢 ч.1 done 5e2fd0f / ч.2 backlog | `core/trading/gates/min_sl_dist.py`, `core/trading/trade_simulator.py`, `config.yaml` |
| **PERF-LOOP-B-TEST** → DS | ✅ DS unit-тест 4/4 (прототип) + Даат перенёс в боевой `GlobalRateLimiter`, cross-loop тест на боевом коде 3/3 (10.1 rps shared, ban cross-loop, single-loop parity). EXEC-WS listenKey вне IP-бюджета (DS нашёл → шаг 4 fix). | 🟢 done | `core/infra/api_engine.py:254-300`, `scripts/test_rate_limiter_crossloop.py` |
| **PERF-LOOP-B-DEADLOCK** → DS | ✅ **АУДИТ ГОТОВ (DS 13.06).** 6 WRITE-точек в торговом пути → cross-loop deadlock-риск при sqlite3 busy_timeout=10s: (1) `tsl_updater.set_exchange_{sl/tp}_order_id` [CRIT, 9 callsites]; (2) `position_sync._emergency_close_check` → UPDATE simulated_trades [CRIT, 693:694]; (3) `exec_ws_integration` → UPDATE exchange_order_id [HIGH, 86:91]; (4) `order_manager.snapshot_balances_per_account` → `save_snapshot` [MED]; (5) `order_manager._resolve_exit` → `close_trade` → register_trade [CRIT, через trade_simulator]; (6) `account_router` → INSERT/UPDATE live_positions [MED]. **READ-ы безопасны** (WAL mode: readers don't block). **Рекомендация:** вынести ВСЕ DB-записи обратно в main loop через очередь (`asyncio.Queue`), торговый loop только REST. Детали: `docs/DEADLOCK_AUDIT.md`. | 🟢 DS done → ждёт решение ARCH | `core/exchange/order_manager.py`, `core/exchange/position_sync.py`, `core/exchange/tsl_updater.py`, `core/exchange/exec_ws_integration.py`
| **PERF-COMPUTE-POOL** ❌ | ❌ **ЗАКРЫТ ЗАМЕРОМ (DS Ф1, 23:30) — НЕ ОКУПАЕТСЯ.** Прототип: WT+trend=12мс/пару=1.6с=**0.5% цикла**, НЕ бутылка. Pool медленнее sync (spawn 134мс+IPC+импорт pandas съедают). **Гипотеза compute-GIL ОПРОВЕРГНУТА** (замер до кода спас от бесполезного рефактора scan_one). **Разворот:** dashboard 11с = event-loop STARVATION (очередь 526 корутин), НЕ GIL → реабилитирует вариант A (dashboard отдельный поток — GIL свободен, поток получит время). Реальный IO-рычаг = market_ws/EXEC-WS (убрать REST OHLCV/polling). | ❌ закрыт (замер) | `scripts/perf_compute_pool_*.py` |

| **PERF-COMPUTE-POOL-Ф0/Ф1** → DS | ✅ **ЗАМЕР ГОТОВ (DS 23:15+23:30).** Ф0: trend+WT основное compute. Ф1 прототип: WT+trend=12мс/пару=1.6с=0.5% цикла, ProcessPool МЕДЛЕННЕЕ sync (spawn+IPC+импорт). **Вывод: compute НЕ бутылка, B не окупается.** Скрипты `scripts/perf_compute_pool_probe.py`+`_batched.py`. | ✅ done (вывод: B мёртв) | `scripts/perf_compute_pool_*.py` |

| **PERF-DASH-THREAD** | **Вариант A — dashboard в отдельный поток/процесс.** ДВОЙНОЕ обоснование: (1) compute не GIL-bound (DS Ф1: 0.5% цикла); (2) **эксперимент dashboard OFF 14.06: НЕ грузит цикл** (OFF 282 ≈ ON 299, в шуме) → dashboard=жертва starvation, не источник. Лаг 11с = его запрос ждёт очередь scan-корутин. Поток получит время (GIL свободен) → латентность спадёт. Флаг `dashboard.enabled` готов (398ac4e). | 🟢 обоснован, готов к старту | `web/dashboard_server.py`, `bot/core/bot.py` |

| **PERF-SCAN-CYCLE** | **Длина цикла ~290с = сам scan** (REST-fetch 522×5TF + observers + IO), НЕ dashboard/compute (оба развеяны замерами 14.06). Рычаг: market_ws (OHLCV→WS, убрать REST) + EXEC-WS. Уже в работе (MARKET-WS v2 SHADOW, EXEC-WS 2b). | 🔵 IO-рычаг (market_ws/EXEC-WS) | `core/infra/market_ws_v2.py`, scan_loop fetch |

| **PERF-LOOP-DRIFT** | **Direct-лаги от перегрузки event loop → корень рассинхрона БД↔биржа (DRIFT 118 = 37 zombie + 81 orphan).** Диагноз ДОКАЗАН: замер direct=400ms (сеть здорова); rtt 9-16с совпадают с пиками TaskSampler 200-386 задач; observer-всплески ote=183/arch104=187/mtf=203. Цепочка: пики loop → торговые direct (sync_time/get_positions) в очереди → timestamp invalid → position_sync классифицирует вслепую → DRIFT. Семейство DEV-230. **C+executor ЗАКОММИЧЕНЫ (`db9726d`):** keep-alive ClientSession (rtt 484→235ms) + OTE generate в `run_in_executor` (LAG секунды→0.141s). Верификация: **timestamp invalid −80%** (90→16/час), каскад DRIFT разорван, 0 ошибок. Шаг A (семафор) отпал. **B (отдельный торговый loop) — эпик, 🔴 БЛОКЕР:** GlobalRateLimiter shared синглтон (market-data `api_engine:436` + торговля `bingx_client:283`) с asyncio.Lock/Event → cross-loop crash. Рефактор = риск регрессии защиты от банов 100410. Объём: GlobalRateLimiter cross-safe + торговый loop + ~30 callsites (position_sync 9, tsl_updater 18) + EXEC-WS + AccountRouter + 92 живые позиции. **ARCH: проектируем эпик целиком (bot-arch/рой) перед кодом.** B критичен при 500+ пар (торговый rtt не зависит от числа пар), сейчас не срочно (C+executor дали 80%). | 🔵 C+executor done; B-эпик в проектировании | DISCUSSION [18:15]; `core/infra/api_engine.py` (GlobalRateLimiter), `core/exchange/bingx_client.py`, `bot/core/bot.py` |

---

## 🔬 СПРИНТ: STRATEGY-DISSECTION (12.06.2026) — разбор 3 боевых стратегий на запчасти

> **Контекст:** 3 стратегии держат 96% потока (3 дня, n=5595): **arch104 57% + ote_nested 32% + atr_change 7%**. Остальное (confluence/wt_signal/pivot_reversal/divergence) ≈0% (отключены/редки). Вскрытие RR-зоны 2-5R (research_zone_2_5r_dissection, `docs/MEMORY_SNAPSHOT`): мёртвая середина 2-5R, но в VST (реально) +1163R; SHORT +0.413 vs LONG −0.106; confluence катастрофа −1.136 (уже не в бою); pivot_1D TP-source убыточны.
> **Цель спринта:** препарировать КАЖДУЮ из 3 боевых стратегий по единой схеме → точечные улучшения (особенно TP-логика, попадающая в мёртвую зону 2-5R).
> **🔴 Единая схема разбора (acceptance для всех 3):** (1) УСЛОВИЯ ВХОДА — гейты/фильтры/что должно совпасть; (2) ТРИГГЕРЫ — что запускает регистрацию; (3) SL-ЛОГИКА — источник + формула + код; (4) TP-ЛОГИКА — источник + формула + код + попадание в RR-зоны; (5) ВЫХОД — TSL/частичный/time-exit; (6) МЕТРИКИ — avgR/median/WR/sumR data-era + разбивка по RR-зонам + VST vs SIM; (7) КОД — файлы/функции/конфиг; (8) ВЫВОД — что точечно улучшить.

| ID | Задача (полный разбор по единой схеме) | Статус | Файлы/данные |
|---|---|---|---|
| **DISSECT-ARCH104** | **Разбор arch104 (57% потока) на запчасти.** SL=`arch104:swing_15m`, TP=`arch104:TBD_r2.0` (фикс RR≈2 → зона 2-3R мёртвая). Паттерн-майнинг: 187 паттернов `config/arch104_patterns.yaml`. **Препарировать:** (1) как паттерн матчится на входе (какие условия features→паттерн), confirmation-score; (2) триггер регистрации (где в коде паттерн→register); (3) SL swing_15m — как находит swing, буфер; (4) TP r2.0 — почему фикс RR2, попадает в мёртвую зону 2-3R → **проверить avgR arch104 по RR-зонам в VST**; (5) выход (TSL? time-exit?); (6) метрики arch104 VST vs SIM по RR-зонам; (7) код: pattern-mining loop, `arch104_patterns.yaml`, register; (8) **гл. вопрос — стоит ли TP r2.0 заменить на структурный/раннер (мёртвая зона)?** | 🔵 разбор | `config/arch104_patterns.yaml`, pattern-mining loop, `trade_simulator`, `simulated_trades` (source_router=arch104) |
| **DISSECT-OTE** | **Разбор ote_nested (32% потока, ядро edge) на запчасти.** SL=`ote:1h_impulse`/`ote:4h_impulse`, TP=`ote:cont_*`/`ote:pull_*` (структурный, НЕ фикс RR → вне мёртвой зоны by design). Каркас: вход 5m в HTF-OTE, риск ×10, раннеры (clamp50 доказан). **Препарировать:** (1) условия входа — OTE-зона (Фибо 0.62-0.79), confirmation-score≥3, перебор триггеров, гейты DEV-44/64A; (2) триггеры — что в `ote_observer_loop`/`ote_signal_generator` запускает; (3) SL — за свечу реакции / impulse-нога, как; (4) TP — cont (продолжение) vs pull (откат), 1h/4h/5m вложенность, структурные цели; (5) выход — SINGLE+TSL, no RR-cap, раннеры; (6) метрики ote по pull/cont × n_down/n_up; (7) код: `core/smc/ote_signal_generator.py`, `bot/loops/ote_observer_loop.py`, `config/ote_setups.yaml`; (8) **гл. вопрос — pull vs cont edge, где OTE сильнее всего?** | 🔵 разбор | `core/smc/ote_signal_generator.py`, `bot/loops/ote_observer_loop.py`, `config/ote_setups.yaml`, ote_nested_mtf_strategy |
| **DISSECT-ATR** | **Разбор atr_change (7% потока, худшие метрики −0.426) на запчасти.** SL=`atr_trendline_buf`, TP=`atr_rr_3.0` (фикс RR=3 → зона 3-5R, −0.275 худшая). **Препарировать:** (1) условия входа — ATR-Supertrend смена ±1 (`calculate_trend` factor=1.25 бой), regime-гейт снят 11.06; (2) триггер — atr_change в scan_loop; (3) SL — atr_trendline (Supertrend-линия) + буфер, формула; (4) TP — atr_rr_3.0 (фикс RR3) → попадает в мёртвую 3-5R; (5) выход; (6) метрики atr_change VST vs SIM по RR-зонам; (7) код: `calculate_trend`, scan_loop atr_change, `_execute_atr_change_signal`; (8) **гл. вопрос — atr_change=триггер→вход в 5m-OTE (insight atr_change_ote_insight: WR89% в 5m-OTE) vs текущий прямой вход; фиксить TP или конвертить в OTE-триггер?** | 🔵 разбор | `calculate_trend`, `scan_loop` (atr_change), atr_change_ote_insight, `docs/PLAN_ATR_CHANGE_OTE.md` |

> Порядок рекомендуемый: **ote_nested** (ядро, понять эталон правильной стратегии) → **arch104** (массовая, TP-тюнинг) → **atr_change** (худшая, возможно конверсия в OTE-триггер). Каждый разбор = отдельный отчёт `docs/DISSECT_<NAME>.md` + вывод в этот спринт.
>
> **🔀 DS + Claude ПАРАЛЛЕЛЬНО (юзер 12.06):** **DS = data** (метрики по RR-зонам, бэктесты вариантов SL/TP, проверка гипотез H1..Hn — задание `docs/DISSECT_DS_TASK.md` с атомарными гипотезами на каждую стратегию). **Claude = code** (вход/триггеры/SL/TP логика из кода). Взаимный фильтр: DS-данные ↔ Claude код-реальность → синтез оптимального решения. Deliverable: DS `docs/DISSECT_<NAME>_DATA.md` + Claude `docs/DISSECT_<NAME>.md`.

---

## 🔥 СЕССИЯ 11.06.2026 (Даат) — REGIME-V2 + atr_change×OTE + C-01

| ID | Задача | Статус | Файлы |
|---|---|---|---|
| **MARKET-WS** | ✅ **v2 РЕАЛИЗОВАН (14.06, Даат).** `core/infra/market_ws_v2.py`: mp.Process+Queue+QueueReaderThread+supervisor. Этап 1 SHADOW enabled=true,use_ws=false. Наблюдать `[MarketWS-v2]` логи. | ✅ v2 SHADOW / наблюдение | `core/infra/market_ws_v2.py`, `bot/core/bot.py:511`, config `market_ws` |

| **REGIME-V2** | Унификация regime→Bus (D-10) + активация `classify_v2` | ✅ **АКТИВИРОВАН** (use_v2:true, Э1-4 готовы; мониторинг acceptance 1-2 дня) | `scan_loop:234/848/1384`, `config.market_regime`, `PLAN_REGIME_V2.md` |
| **ATR-GATES** | Снять regime/strength гейты atr_change (−178R, тавтология ATRTrend−1) | ✅ **СНЯТЫ** (allow_short_regimes, long_penalty=0, min_strength=0) | `config.signal_quality.atr_change` |
| **ATR-OTE** | atr_change×OTE интеграция: триггер→вход в 5m-OTE (бэктест WR89%) | 🟡 **дизайн готов** (Э1-Э4). Э1 фильтр ноги. Нужна история (46/273 пар) | `PLAN_ATR_CHANGE_OTE.md`, `scripts/atr_change_ote_test.py` |
| **C-01** | CHoCH length=5 ре-майнинг 69 паттернов | ✅ **ЗАКРЫТ 11.06** (полный прогон 45 симв, exit 0): 30 HTF→архив, DS_L096 вернут (n=74 avgR+0.20), 4 LTF-артефакта + 6 pivot (S060/092/093/098, L061/062) НЕ возвращать (length=50 завышал 5-8×). Можно катить swing_bridge на length=5 (флаг `arch104.choch_length`) | `arch104_patterns.yaml`, `ltf_metrics.csv`, `PLAN_C01_choch_length_fix.md` |
| **SIGNAL-AUDIT** | Аудит актуальности сигналов (confluence/wt_sideways отключены — shadow с полным trade_features, замерить) | 🟢 идея (юзер 11.06) | — |
| **HIGH-VOL-VOLUME** | Объёмное обогащение HIGH_VOL (volume_z из features) | 🟢 отложено | — |
| **DASHBOARD-VST-MODE** | Глобальный SIM/VST-фильтр: `summary(mode)` → весь дашборд (метрики/KPI/EV/Avg R) переключается SIM↔реальная торговля. Сейчас ВСЁ общее (балласт включён). Календарь уже сделан (`pnl_calendar(mode)`); распространить на summary + переключатель в топбаре. Эффект: VST 11.06 +2.012 vs SIM 0.26 — реальная картина прячется в общем | 🟢 идея (юзер 11.06) | `performance_engine.summary()`, `/api/stats`, топбар |
| **DB-ILLUSIONS-AUDIT** | ✅ **DS ЗАКРЫЛ:** R_multiple ДОСТОВЕРЕН (89.5% совпадение с формулой). Система маржинально прибыльна **avgR+0.20** (бумажный +0.216, реальный +0.204, завышение лишь 5% от EXPIRED R=0→−1). Гипотеза «бумажные/убыточна» ОПРОВЕРГНУТА (Claude ошибочно clip к сломанному MFE). clamp_r_smart раннеры НЕ режет (131 сд R>15, max 112R; зажатые=артефакты sl_dist≈0). | ✅ закрыто (Claude валидировал) | `scripts/db_illusions_audit.py` |

| **DATA-AUDIT-2** 🔴 | **Следующий слой достоверности (юзер 11.06 «поднагрузить DS»):** (1) **EDGE-воспроизводимость** — бэктест-WR vs live per-сигнал (AUDIT: wt_b 85%→33.6%, −15пп). Наши regime-v2/OTE-WR89%/ote_nested+2.455 — реальны или backtest-иллюзия? (2) **ML-честность** (AUDIT ML-01a/b/c/d): selection bias `max_R_possible>0`, AUC≈0.5 в confidence, K-Fold→TimeSeriesSplit, MFE-таргет vs realized R. (3) **MFE-трекинг фикс** — `max_R_possible` не обновляется (DS нашёл) → ломает captured_R + ML-таргет. (4) **zombie/SL reconcile** — БД↔биржа + биржевые STOP-ордера (ликвидация-риск, OPS-06) | 🔴 **DS** (Claude валидирует) | scripts/, `r_predictor.py`, `trade_simulator` MFE, биржа openOrders |
| **TP-ANOMALY** | (часть DB-ILLUSIONS) TP `R_multiple > max_R_possible` 3171 сделок. Корень: R-формула ИЛИ цены (exit/SL/min/max) ненадёжны. Связь OPS-06/ML-01c | 🔴 в составе DB-ILLUSIONS-AUDIT | `trade_simulator` TP close |
| **OPS-06 ч.3 qty** | ✅ **ФИКС 11.06:** `trade_router:290` (ARCH-94) писал только `exchange_order_id`, забыл `qty` → qty=NULL с 28.05 → реальный $ P&L не считался. Добавлен qty в UPDATE (qty>0 guard:257). После рестарта новые сделки пишут qty → `pnl_calendar.total_usd` (qty×Δprice) оживёт | ✅ сделано (рестарт применит) | `trade_router.py:290` |

| **OPS-06-ACCOUNT** | Разделение $ по СЧЕТАМ (acc1/acc2): поле `account` в `simulated_trades` (ALTER) + `trade_router` пишет `account_router.route(symbol)` рядом с qty + `pnl_calendar(mode, account)` + переключатель acc1/acc2/all. Сейчас счета НЕ различаются в БД (поле нет) → $ смешан. Связь ARCH-96 | 🟡 НОВАЯ (юзер 11.06 «два аккаунта, на уровне роутера») | `simulated_trades` schema, `trade_router`, `account_router.route()` |
| **GRAVITY-ROCKET** | MTF-gravity на входе → edge. На 628 боевых: gravity100+ avgR+2.483 WR74% (×4 база). DS-триангуляция: gravity ≠ самостоятельный trigger (random-bars corr −0.016), а **ранжировщик поверх сигналов** (selection bias). Консенсус: **ConfluenceField = направленный ГЕЙТ (доминанта по конфлюенции-к-цели подавляет встречное) + ранжировщик СОНАПРАВЛЕННЫХ**, НЕ генератор входов. Живое подтверждение XLM: pull-SHORT 0.1R vs cont-LONG 14.2R — приоритет pull (TIER1) прячет cont-ракету; pull контр-тренд by design (`ote_signal_generator:277`) валиден лишь при завершённом импульсе (Эллиотт) | 🟢 дизайн (валидировано, ждёт PIVOT-GRAVITY) → ARCH ConfluenceField (reuse GravityEngine tp_selector) | `scripts/gravity_entry_test.py`, `core/calculators/tp_selector.py`, DISCUSSION 11.06 |
| **PIVOT-GRAVITY** | ✅ **ЗАКРЫТ (MTF, 2 независимые оси → 1 вердикт).** GRAVITY (W_TF×W_type/dist^1.5, 452 сд): ВСЕ бакеты <0, даже g=250+ → −0.203, corr −0.089, winners avg_g≈losers. ELLIOTT-фаза: все бакеты <0. **pivot_reversal = балласт РАВНОМЕРНЫЙ, скрытой ракеты нет ни по конфлюенции, ни по фазе.** Депрекейт обоснован окончательно (−1272R = 25% системы) → разблокирует SIGNAL-CLEANUP | ✅ закрыто (Claude валидировал) | `scripts/`, DISCUSSION 11.06 |

| **ELLIOTT-COMPLETION** | ✅ **v2 ПРИНЯТ (Claude валидировал)** — методология чистая (3 дыры устранены). **PULL: гипотеза подтверждена** (SHORT n_down≥1→+3.23 WR85% vs n_down=0→−0.21; LONG зеркально n_up≥1→+1.52). **CONT: деградирует с фазой** (n_down=0→+2.08, ≥3→−0.19). **PIVOT_REVERSAL: фазой НЕ спасается** (все бакеты <0) → депрекейт. 🎯 Реварп: pull = MTF-согласование (вход по HTF-тренду через LTF-откат = ote_nested), не Эллиотт-разворот. ⚠️ caveat: pull n=81 мала, добрать перед жёстким гейтом. **→ DEV-226 Phase 2** | ✅ закрыто → DEV-226 Ph2 | `scripts/elliott_completion_test.py`, DISCUSSION 11.06 |

| **DEV-226 Ph2** | Точечный гейт фазы (из ELLIOTT v2): pull только при `n_down≥1`(SHORT)/`n_up≥1`(LONG); cont запрет при `n≥3`. **✅ SHADOW РЕАЛИЗОВАН (11.06):** `_elliott_phase_shadow` (ote_observer) считает n_down/n_up на входе FIRE → пишет `phase_nd_4h`/`phase_nu_4h`/`phase_gate_would_block`/`phase_gate_reason` в features_json, НЕ блокирует. Reuse `calculate_n_down/_up`. **✅ ДАННЫЕ ПОШЛИ (12.06): 18 ote-сделок несут фазу.** Предв. замер: would_block=0 avgR+4.62 (n=7) vs =1 +1.08 (n=3) — знак верный, но n мал + ракета ALLO(+37.8) раздувает. **След.: ЗАМЕР на n≥30/бакет** → hard-гейт (cont первым). Реальный рычаг архитектуры (STRADDLE показал dedup=не рычаг) | 🟡 shadow копит (18 сд, замер на n≥30) | `bot/loops/ote_observer_loop.py`, `indicators.py:576` |

| **SIM-DEPRIO** (SCALABILITY) | ✅ **РЕАЛИЗОВАН (14.06, Даат).** `trade_simulator._proc`: throttle sim-only (interval=300с из config `performance.sim_check_interval_sec`). `self._sim_checked` в `__init__`. Биржевые всегда. 🟡 Исходный дизайн: **СПРОЕКТИРОВАНО (юзер 14.06: «реже SIM, освободить loop, приоритет бирже»).** **Данные 14.06:** 312 OPEN = 189 sim_only (61%) + 123 биржевых + 4 TSL-активных. **61% бюджета loop тратится на фантомы** (margin-reject SIM-only варятся в одном Semaphore(15) с реальными). **Идея:** throttle sim_only в `check_open_trades_with_tsl._proc` — окно 300с вместо 60с (паттерн как DS-322 `_repair_checked` 3600с / DEV-227 `_force_rest_ts` 150с): `if not _exchange_managed_trade and _now_ts - self._sim_checked.get(trade_id,0) < SIM_CHECK_INTERVAL: return`. За флагом `performance.sim_check_interval_sec` (откат мгновенный). **Эффект:** ~38 вместо 189 sim/цикл → бюджет REST/Semaphore идёт биржевым. **Нюанс:** sim-закрытие с задержкой ≤5мин (статистика, не деньги — ок); биржевые (деньги) только выигрывают. **Чек:** runtime на копии БД (feedback_ast_parse_no_scope — критичный путь `_proc`). Часть EXEC-WS вектора (биржевые → event-driven, sim → редкий polling). | 🟡 ждёт решения «сейчас / после прогона» | `core/trading/trade_simulator.py:1816`, `config.performance` |

| **EXEC-WS** | ✅ **2b sync_close РЕАЛИЗОВАН (14.06, Даат).** `exec_ws_integration.py`: `_sync_close_async` + per-account handler. Флаг `sync_close: false` → включить после наблюдения. 🎯 **РЕШЕНО 14.06 — КОРЕНЬ = неверный VST WS-домен (фикс `user_data_ws.py`).** Код слушал PROD `open-api-swap.bingx.com` с VST-listenKey → 0 order events. docs-v3: VST WS = **`vst-open-api-ws.bingx.com/swap-market`** (PROD/LIVE = open-api-swap). Эмпирич. подтв. (`diag_exec_ws_endpoints.py` на VST-домене): acc1 ACCOUNT_UPDATE=4(m=ORDER,P[]) + ORDER(o)=8 (`TRADE_UPDATE` o.i=orderId o.X=FILLED) — **events ИДУТ**. Парсер был верный (msg.o), subscribe не нужен. Фикс: `VST_WS`/`LIVE_WS` по is_vst (user_data_ws.py:37-38,59,164). **NEXT: рестарт → [EXEC-WS] orders>0 → включить write_exch_id (2a) → дореализовать 2b sync_close (ACCOUNT_UPDATE pa=0 → close БД).** → memory `exec_ws_vst_userdata_proven`. ⬇️ старая «тупик»-диагностика устарела. ⛔ ~~ТУПИК НА VST 14.06 (диаг-скрипт `scripts/diag_exec_ws_endpoints.py`):~~ слушал ОБА endpoint параллельно 7мин с listenKey acc1. Результат: A `open-api-ws/market` молчит полностью (0 — неверный для swap); B `swap-market` = SNAPSHOT 667+ping, **ORDER=0** при **4 реальных биржевых открытиях acc1 в окно**. → VST user-data WS даёт только начальный снимок+heartbeat, НЕ пушит executionReport/ORDER_TRADE_UPDATE. **EXEC-WS 2a нежизнеспособен на VST.** exch_id и так пишется из REST place (работает). enabled=true держит бесполезный WS (snapshot-burst). NEXT: либо enabled=false (разгрузка), либо проверить LIVE user-data (бот на VST→тих). Корень рассинхрона лечить REST-sync. → memory `exec_ws_vst_userdata_proven` (коррекция). ⬇️ исходный статус. 🔴 **БЛОКЕР 14.06: WS НЕ ловит ORDER executions.** Прод (enabled=true): events=666 но orders=0/account=0 при **19 биржевых открытиях/23мин** на обоих акк → только SNAPSHOT burst + ping + редкий FUNDING_FEE. Корень: код `user_data_ws.py:33` на `open-api-swap.bingx.com/swap-market` (отдаёт snapshot/market), а BingX docs + `test_vst_listenkey.py` → user-data executionReport на **`open-api-ws.bingx.com/market?listenKey=`**. «path доказан 12.06» = доказан CONNECT, НЕ приём executions («714 событий» = SNAPSHOT burst, не executionReport). **2a write_exch_id включать НЕЛЬЗЯ (нечего ловить).** NEXT: диагностический скрипт — слушать ОБА endpoint параллельно, поймать открытие, найти где executionReport (НЕ менять вслепую). → memory `exec_ws_vst_userdata_proven` (коррекция). ⬇️ исходный статус ниже. ✅ **ЭТАП 1+2a РЕАЛИЗОВАНЫ (12.06).** Этап1: `user_data_ws.py` WS живой (endpoint `wss://open-api-swap.bingx.com/swap-market?listenKey=`, 714 событий/120с, 0 reconnect). Этап2a: `exec_ws_integration.py` — on_event пишет exch_id из `ORDER_TRADE_UPDATE`(FILLED MARKET ro=false→open) в OPEN-сделку symbol+ps без exch_id. Запуск `bot.py` за флагами `trading.exec_ws.{enabled,write_exch_id,sync_close}` (все OFF). AST+runtime(DRY на реальном событии) OK. **Включение поэтапно: enabled→[лог]→write_exch_id→[пишет]→sync_close(2b TODO).** **🔴 ЭТАП 2b:** ACCOUNT_UPDATE pa=0→sync close БД (через _resolve_exit). + multi-account (2-й WS). | 🟡 готово к включению (флаги off) → 2b | `core/exchange/{user_data_ws,exec_ws_integration}.py`, `bot/core/bot.py`, `config.trading.exec_ws` |

| **EXEC-SIM-SPLIT** (ВЕКТОР, не сейчас) | 🔵 **ВЕКТОР НА БУДУЩЕЕ — НЕ план к исполнению (трезвая оценка Claude 14.06).** Юзер накидал мысль, Claude разогнался в эпик → пересмотр: **СЕЙЧАС не делать.** Причины: (1) корень боли (189 фантомов) = margin-reject от RISK 95% / нет лимита позиций, а НЕ «sim живёт с биржей» → лечится риск-менеджментом дешевле; (2) 2 процесса с одной сигнальной логикой = крупнейший дубль, противоречит [[principle_reuse_not_duplication]] — strip УЖЕ протух за месяц (доказательство закона); (3) цена высока для соло + машина на пределе (BSOD). **80/5 альтернатива в ОДНОМ процессе:** лимит позиций (нет фантомов) + execution_mode разметка (ARCH-DB-V2 есть, sim/real в 1 БД помечены, обучение/дашборд фильтруют) + опц. SIM-DEPRIO throttle. **Оправдан КОГДА:** +юзер (мульти-тенант) ∥ strip = принципиально иная логика (дрейф=фича) ∥ железо мощнее. Дизайн ниже сохранён для того момента. → memory `exec_sim_split_epic.md`.\n\n_(исходный дизайн:)_ **Разделение контуров на 2 процесса:** main = ТОЛЬКО реальные (vst/live), loop/IP-бюджет идут торговле; strip = sim-полигон по ВСЕМ сигналам. **Разделение контуров на 2 процесса:** main = ТОЛЬКО реальные (vst/live), loop/IP-бюджет идут торговле; strip = sim-полигон по ВСЕМ сигналам. **🔴 КРИТИКА (grep 14.06):** обучение main питается ОТ sim — `update_signal_weights`→`PerformanceEngine.by_signal_type_ema` фильтрует лишь `status IN(TP,SL,TSL,EXPIRED)` БЕЗ различия sim/real; ARCH-104 mining + ML тоже читают `simulated_trades` целиком. Sim доминирует (27719 в осн. sim). → **sim НЕ удалять, а ПЕРЕСЕЛИТЬ в strip + перенаправить обучающий контур.** **РЕШЕНИЯ ЮЗЕРА:** (БД) РАЗДЕЛЬНЫЕ — strip=sim-only DB, main=реальные. **Мост:** main читает strip-БД для обучения через `db_path` (УЖЕ параметризован: `update_signal_weights(db_path)`, `PerformanceEngine(db)`) → config `trading.learning_db_path`. **Дефолты дизайна (на подтверждение):** (2) strip сканит НЕЗАВИСИМО на общем кэше (полный двойник→«обновить strip под main» критично); (4) strip без биржевого REST легче, при нужде меньше пар/реже (машина на пределе — BSOD/XMP); (5) main НЕ регистрирует не-биржевой сигнал (strip поймает). **Объединяет:** STRIP-TWIN (общий кэш=фундамент), SIM-DEPRIO (отменяется — sim уходит из main радикальнее throttle), ARCH-DB-V2 (execution_mode разметка). **Этапы:** (1) пересоздать strip из main; (2) STRIP-TWIN общий кэш; (3) strip→sim_only режим+своя БД; (4) main: execution_mode чисто vst, не писать sim; (5) мост learning_db_path; (6) дашборд sim из strip. → memory `exec_sim_split_epic.md`. **Проектировать роем+bot-arch перед кодом.** | 🔵 эпик (дизайн, после прогона) | `crypto_volume_bot_strip/`, `core/trading_intelligence.py:246`, `config.trading.learning_db_path` |

| **STRIP-TWIN** (research) | 🔵 **BACKLOG (юзер 14.06: «strip кормить нашим кэшем для симуляции?») — КОМПОНЕНТ EXEC-SIM-SPLIT (общий кэш).** **Идея:** strip-бот (`crypto_volume_bot_strip`) = A/B-близнец на ОБЩЕМ data-канале — потребляет OHLCV-кэш main вместо своего REST. **Двойная польза:** (1) IP-бюджет — strip НЕ тянет биржу → не удваивает запросы с одного IP → нет риска бан 100410 (GlobalRateLimiter защищает один IP); (2) детерминизм A/B — оба видят бит-в-бит одни данные → разница только в логике/конфиге (золотой стандарт сравнения). = `principle_reuse_not_duplication` (один источник, два потребителя). **Реальность:** main кэш = in-memory LRU (`ApiEngine._cache._data`), дисковый `ohlcv_cache.db` 2.5GB = периодич. дамп `save_to_disk` (mtime 18.05). 2 процесса не делят dict → нужен слой. **Варианты:** B(реком.) HTTP `/api/ohlcv` у dashboard:8000 (инфра есть, main горячий путь не трогаем, strip read-only); A общий SQLite-кэш WAL; C Redis (избыточно). **🔴 БЛОКЕР:** strip заброшен с ~16.05 на СТАРОМ коде (`bot_with_subscriptions.py`, до ночных ARCH/EXEC-WS/perf), НЕ git-связан с main. Врубить сейчас = старая логика → A/B грязный (конфиг + месяц дрейфа кода). Сначала: пересоздать strip из текущего main ЛИБО определить что тестирует иначе. → memory `strip_twin_shared_cache.md` | 🔵 backlog (research, после прогона) | `web/dashboard_server.py` (+/api/ohlcv), `crypto_volume_bot_strip/` (data_collector → HTTP-source) |

| **ADOPT-TRADES** | 🔵 **BACKLOG (важный момент, юзер 12.06): «открываю руками — бот ведёт?».** Сейчас НЕТ: бот ведёт только свои БД-сделки (`simulated_trades` с entry/sl/tp/regime/exch_id), ручная позиция = `exch-only`, `sync_positions` её не трогает. **Идея:** EXEC-WS ловит `ORDER_TRADE_UPDATE FILLED` (ручное открытие) → adopt-запись в БД → бот ведёт (TSL/SL/TP/exit). **Корень-вопрос (решить ПЕРЕД кодом):** откуда 1R/SL — (а) юзер ставит SL руками→бот берёт как `original_sl`; (б) бот сам ATR/за-свечу при adopt. Отличить ручное от ботовского (orderId не из ботовского place, нет в БД) иначе двойной adopt. Вектор «почти торговый терминал». → memory `adopt_manual_trades_vision.md`. Сначала базовый EXEC-WS 2b. | 🔵 backlog (дизайн) | `core/exchange/exec_ws_integration.py`, `trade_simulator.py` (adopt-INSERT) |

| **ARCH-DB-V2** | 🔵 **СПРОЕКТИРОВАН (синтез 5 нейронов + Claude, 12.06) — БД в торговый терминал.** Боль юзера: SIM/VST/LIVE + аккаунты в одной куче, реальный PnL и баланс per-account не отследить, фильтраций будет много. **Консенсус 5/5:** домены `Signal→Trade→Order→Account→Exchange`; 3 поля `account_id`+`execution_mode`(SIM/VST/LIVE явно, не через exch_order_id IS NULL)+`exchange_id`; справочники `exchanges`+`accounts`; **`balance_snapshots`** (история equity — решает «движение баланса»); `orders` отдельно; тяжёлое (features_json) → связанные таблицы. **🔬 Приземление Claude:** ORM НЕТ (raw sqlite3 в 33 файлах — SQLAlchemy=рефактор, не «1 строка»); backfill account 76% сделок не покрыть (account_routing моложе на 3мес → старые account_id=1, точно вперёд); positions=current-state НЕ история (иначе ~295K строк/день). **РЕШЕНИЕ ЮЗЕРА 12.06:** raw SQL + **тонкий db-слой** (репозиторий-функции в `core/db/`, не полный ORM); старт через эпик. **ПЛАН:** Ф1 (сейчас) ALTER +3 поля + balance_snapshots + backfill → фильтр режимов/аккаунтов + equity-график (80% боли, риск≈0); Ф2 exchanges/accounts/positions + дашборд-вкладки; Ф3 нормализация trades/signals/orders/trade_metrics через ETL; Ф4 db-слой→Postgres-readiness. Каждый шаг=db_migration+тест на копии. + добавить `fee` (точный реальный PnL). → `docs/DB_REDESIGN_SYNTHESIS.md`, `docs/DB_ARCHITECTURE_V2.md`, `docs/DB_REDESIGN_PROMPT.md`. **🔀 Ф1 ОТДАНА DS (модель юзера 12.06): DS делает всю Ф1 на КОПИИ `subscriptions_test.db` (DDL +3 поля + balance_snapshots + backfill + register_trade INSERT + тонкий db-слой `core/db/*_repo.py`) → Claude проверяет (взаимный фильтр + runtime на копии, feedback_ast_parse_no_scope) → Claude применяет на БОЕВУЮ через db_migrations + коммит. Боевую трогает ТОЛЬКО Claude.** Задание DS: `docs/DB_PHASE1_DS_TASK.md`. **✅ Ф1 РЕАЛИЗОВАНА (коммит 12.06): DS дал data-ядро (db-слой+backfill-логика), Claude взаимным фильтром нашёл 3 пробела (register_trade НЕ писал поля / save_snapshot НЕ вызывался / нет воспроизв. миграции) → Claude доделал интеграцию.** Готово: авто-миграция subscription_manager (+3 колонки+balance_snapshots+индексы), register_trade пишет account/mode/exchange, order_manager.snapshot_balances_per_account (multiacct), position_sync throttled save_snapshot (~10мин), `core/db/{balance,trades}_repo.py`, `scripts/db_phase1_backfill.py` idempotent. **Runtime-тест на копии OK** (миграция+register(+3 поля)+snapshot+backfill SIM14890/VST10313/старые acc=1). | 🟢 **Ф2 В ПРОДЕ (13.06):** exchanges/accounts/positions DDL+seed (БД), `balance_r… | DS+Claude · ✅ `core/db/`, `trade_simulator`, `order_manager`, `position_sync`, миграции |

| ~~EXEC-WS-path~~ | 🟢 **Execution Sphere WS (ARCH-96 разморозка) — PATH ДОКАЗАН 12.06.** Корень рассинхрона (orphan/drift/zombie/exch_id=None/фантомные SIM-only): всё на REST-polling (sync 60с отстаёт). **Решение: VST private user-data WS.** Тест `scripts/test_vst_listenkey.py`: ✅ listenKey via `POST open-api-vst.bingx.com/openApi/user/auth/userDataStream` (X-BX-APIKEY, без подписи) HTTP200; ✅ WS `wss://open-api-ws.bingx.com/market?listenKey=<vst_key>` подключён. ccxt sandbox НЕ умеет (нет sandbox user URL) → кастомный WS. **Эффект:** `executionReport` push с `i`(orderId)→надёжный exch_id; `ACCOUNT_UPDATE`/position-close→мгновенный sync. **1 соединение/аккаунт (НЕ per-pair) → scan_loop НЕ затронут** (vs market WS плато 750s). Реализация: listenKey lifecycle (keepalive PUT ~30мин, reconnect) + интеграция в register(exch_id)/position_sync. gzip-декод сообщений | 🔴 ARCH (новая, path доказан) | `core/infra/ws_feed.py` (новый user-stream), `trade_router`, `position_sync`, `scripts/test_vst_listenkey.py` |

### 📥 ПЕРЕНОС ИЗ DISCUSSION 11.06 (задачи из аудит-марафона + sign-audit)

| ID | Задача | Статус | Файлы |
|---|---|---|---|
| **SIGNAL-CLEANUP** | Балласт/мёртвые из SIGNAL-AUDIT: ✅ **`pivot_reversal` ОТКЛЮЧЁН** (−1272R, 2 оси). ✅ **`watch_list_breach` ОТКЛЮЧЁН 12.06** (`signal_quality.watch_list_breach_enabled:false` + ранний return в `_handle_wl_breach_entry`; балласт −169R, длинные сделки avg 701мин). Остаётся: CLEANUP мёртвых меток БД `wt_b_signal`/`mtf_bias`/`trend_signal`/`composite` (давно не торгуют, фоном) | 🟢 pivot+wl_breach OFF; cleanup меток фоном | `config.yaml`, `bot/monitoring.py:465`, `scan_loop.py:200` |

| **NULL-SIGNAL** | 17 сделок `signal_type=NULL` (+3.9R) — `source_router` есть, метка не записалась. Баг в `register_trade`? Потерянные edge-метки | 🟡 **DS** investigate | `register_trade`, `simulated_trades` |
| **CONFLUENCE-RETURN** | `confluence` +610R sumR но отключён 30.05 (WR30% низкий, +avgR). Вернуть? Оценка неполна (regime=NULL). Решить ПОСЛЕ regime/pattern fix (B3/ML-01d) | 🟡 отложено (ждёт regime-fix) | config, `scripts/` |
| **MFE-FIX (A3)** | `max_R_possible`/`max_price` не обновляются real-time → 43% сделок `max_price==entry`. Ломает `captured_R_pct` + ML-01c таргет. (= п.3 DATA-AUDIT-2) | 🔴 **DS** | `trade_simulator` MFE-трекинг |
| **AI-SPHERE-LOCAL** | Локальный DeepSeek-R1 как AI-сфера Куба (async, инсайты в Bus). Research готов (`docs/AI_ARCHITECTURE_R1.md`, `setup_r1.py`, `ds_r1_analyzer.py`). Железо: 1× GTX 1080 сейчас (1070 не установлена). + RAG из PDF-гайдов (Эллиотт/SMC) для Continue | 🟢 research готов, не интегрировано | `docs/AI_ARCHITECTURE_R1.md`, `scripts/setup_r1.py` |
| **VST-SLIPPAGE** | ✅ slippage мал (0.07-0.18%, НЕ 0.45%). Корень минуса = `pivot_reversal`+`confluence` (−1865R), НЕ исполнение. arch104 на VST в плюсе (+0.484R) | ✅ закрыто (08.06) | `scripts/vst_slippage_audit.py` |

| **TSL-PROFILE** | ✅ signal_type-aware Gear-профили (ote_nested gear3=8ATR дышит дольше; default 2/4/12) | ✅ сделано (af7bfae) | `tsl_engine.py` TSL_PROFILES |

| **A2 zombie/SL** | ✅ ликвидация-риск КОНТРОЛИРУЕТСЯ (0 голых сейчас, REPAIR-SL 33K детектов = активная защита). Перепроверен 3 независимыми источниками | ✅ закрыто (валидировано) | REPAIR-SL, `exchange_sl_order_id` |

> **snapshot (P2) — НЕ дыра:** `trade_features` 100% активных сигналов с 31.05 (`write_table`). Низкое общее покрытие = старые сделки + мёртвые сигналы. `features_json`=метаданные (не косяк).

---

## 🔍 АУДИТ 2026-06-09 — ВЕРИФИЦИРОВАН (отчёт `docs/audit/AUDIT_2026-06-09.md`, оценка 4.5/10)

> **⚠️ КОСЯК ПРОЦЕССА (юзер 09.06):** аудит читал `current_state.md`/`whats-next.md` из последнего коммита → доки УСТАРЕЛИ → 2 «критичные» задачи (WAL/sklearn) оказались давно сделаны. **Доки не обновляются регулярно** = тот же «раздвоенный источник правды», что аудит нашёл в коде. → задача **DOC-SYNC**.
> **Верификация Claude (grep по коду):** из 6 HIGH аудита — 6 реальны, 2 устарели, 1 не найдена. НЕ заводить готовое.

| ID | Спринт | Задача | Статус (верифик.) | Файл:строка |
|---|---|---|---|---|
| **SEC-01a** | 🔴 S | Dashboard bind `0.0.0.0`→`127.0.0.1` (1 строка, мгновенно закрывает дыру) | ✅ **СДЕЛАНО 09.06** (default 127.0.0.1 + config `dashboard.host`) | `dashboard_server.py:2224` + `bot/core/bot.py:491` |

| **SEC-01b** | 🔴 S | token-auth + CSRF на все POST (`/api/settings` пишет config, `/close` закрывает сделки — открыты всем в сети!) | 🔴 РЕАЛЬНА | `dashboard_server.py` POST-роуты |

| **SEC-01c** | 🔴 S | задействовать `ADMIN_ID` (грузится в `config_loader:57`, нигде не используется → нет admin-gate) | 🔴 РЕАЛЬНА | `config_loader.py:57` |

| **OPS-01a** | 🔴 R | анти-#1910 sanity-guard:** при OPEN, если цена ушла >X% за SL → форс-клоуз НЕЗ… | ✅ **СДЕЛАНО+ПРОВЕРЕНО В БОЮ 09.06 (#20556 INJ висела за SL −2.96R → после рестарта OPS-01a закрыл на честные −1R, экономия −1.96R). Фикс: пустой фильтр → SL-чек по текущей свече `df.tail(1)` | `trade_simulator.py:1918-1928` |

| **OPS-01b** | 🔴 R | `created_at`/SL-проверка от **биржевого времени**, не системных часов Windows | ✅ **СДЕЛАНО+ПРОВЕРЕНО RUNTIME 10.06** (smoke-baseline на копии БД: фикс поймал 2 ЖИВЫЕ сделки с skew 0.5/1.5 мин — хост опережает биржу; closed=3 без NameError). Решение: НЕ лишний `ex.fetch_time`, а биржевое время последнего бара `df["time"].iloc[-1]` (уже в данных, бесплатно) — детект forward-skew + кламп created_ms к биржевой шкале + лог величины. Лечит ВСЕ сделки (вкл. уже записанные с кривым created_at). Backward-skew (часы отстают→лишние бары до входа) — TODO, отдельная гипотеза. Корень #1910, OPS-01a остаётся финальной страховкой | `trade_simulator.py:1923-1944` |

| **OPS-04** | 🟠 R | авто-рестарт `monitor_market` при необработанном исключении (тихая остановка) +… | 🟠 РЕАЛЬНА (но `except:pass` в monitoring НЕ найден — проверить) | `bot/core/bot.py:107` |

| **OPS-06** | 🟡 R | ✅ LIVE-GUARD ТАЙМАУТ (12.06, v2 — перенесён в position_sync): корень orphan-… | 🔴 РЕАЛЬНА (ЖИВА) | `order_manager.py:727`, LIVE-GUARD `trade_simulator:~2493` |

| **OPS-05** | ✅ **ЗАКРЫТ (12.06 verified): параллелизация В ПРОДЕ.** grep подтвердил: `asyncio.gather(*[_proc(t)...])` + `Semaphore` в `check_open_trades_with_tsl` (trade_simulator:1778/2798), вызов из `trade_tracker.py:48`. Smoke доказан 09.06 (baseline≡параллель). Saturation лечится — статус висел 🔴 ошибочно (применён давно). _pivot_calc Lock отложен (гонка редкая). **Текущий drift 76 — НЕ saturation, а OPS-06** (zombie/sync). | ✅ закрыто (verified) | `trade_simulator.py:1778,2798` |

| **ML-01a** | 🟠 M | `cross_val_score` K-Fold → **TimeSeriesSplit** (утечка будущего на автокорр. рядах) | 🟠 РЕАЛЬНА | `r_predictor.py:68`, `outcome_predictor.py:224` |

| **ML-01b** | 🟠 M | замерить ЧЕСТНЫЙ AUC на TimeSeriesSplit; если ≈0.5 → НЕ подмешивать ML в `confidence` (сейчас 0.7×orig+0.3×P(win)=шум) | 🟠 РЕАЛЬНА | `trading_intelligence.py` confidence |

| **ML-01c** | 🟠 M | selection bias: убрать `AND max_R_possible>0`, таргет = **realized R**, не MFE-идеал (Kelly завышает размер) | 🟠 РЕАЛЬНА | `r_predictor.py:96,107` |

| **ML-01d** | 🟠 M | `regime` на инференсе (сейчас `regime=None`→one-hot `[0,0,0,0]`, 4/12 фич нулевы… | 🟠 РЕАЛЬНА | `trading_intelligence.py:691`, `outcome_predictor.py:201` |)

| **T-01** | 🟡 T | god-objects: разнести `dashboard_server.py` (2351 стр) + `trading_intelligence.py` (2789!) | 🟡 РЕАЛЬНА | — |

| **T-02** | 🟡 T | удалить мёртвый `bot/main.py` + `infrastructure/`/`presentation/` (Clean-Arch скелет, ~300 стр) | 🟡 РЕАЛЬНА | `bot/main.py` |

| **T-03** | 🟡 T | TTL/maxsize для `_last_signal`/`analysis_cache` (растут без лимита) + `asyncio.Lock` на CircuitBreaker/OhlcvCache | 🟡 РЕАЛЬНА | `bot/core/bot.py:75`, `api_engine.py:31` |

| **DOC-SYNC** | 🟡 T | регулярное обновление `current_state.md`/`whats-next.md` (косяк: аудит читал уст… | 🟡 НОВАЯ | — |)

| ~~OPS-02~~ | ✅ | ~~SQLite WAL+busy_timeout~~ — **УЖЕ СДЕЛАНО (DEV-148)** | ✅ устарела в аудите | `subscription_manager.py:30,37` |

| ~~OPS-03~~ | ✅ | ~~scikit-learn в requirements~~ — **УЖЕ ЕСТЬ** | ✅ устарела в аудите | `requirements.txt:21` |

**Спринты:** 🔴 **S** (Security, 1-2 дня, SEC-01a сразу=1 строка) → 🔴 **R** (Reliability/анти-#1910, критично деньги) → 🟠 **M** (ML-честность, неделя) → 🟡 **T** (техдолг, фон). **Старт: SEC-01a (bind) + OPS-01a (sanity-guard) — обе про потерю денег/безопасность.**

---

## 🖥️ ЭПИК DASHBOARD — Полноценное приложение (проектирование, 10.06.2026, инициатор ARCH)

> **Скелет:** [`docs/DASHBOARD_EPIC.md`](docs/DASHBOARD_EPIC.md). Цель юзера: дашборд → полноценное приложение, доступ С МОБИЛКИ ОНЛАЙН через сервер (PWA), хороший дизайн (инструмент: v0.app).

**Текущее (разведка 10.06):** API aiohttp ~45 роутов (god-object 2356 стр) + Vue-зачаток `/v2` (DEV-144 Stage-1) + auth почти НЕТ + **дашборд ЗАБЛОКИРОВАН как потребитель биржи** (live-роуты дёргали биржу напрямую → отъедали rate-limit торговли).

**🔴 РАЗВИЛКА (Phase 0, решение юзера):** v0.app генерит React/Next.js, текущий v2 = Vue → конфликт. **Рекомендация: вариант B (Next.js+Vercel)** — v0 нативно, мобильный/PWA из коробки = ровно цель юзера; Vue-зачаток мизерный, не жалко.

**Фазы:** 0 Решения (стек/деплой/auth) → 1 API-слой (вынести из god-object=**T-01**, версионировать, **live-роуты на БД/кэш = снять блокировку биржи**) → 2 Auth (**SEC-01b/c** вливается, ОБЯЗАТЕЛЬНО до выставления наружу) → 3 Фронт (v0→Next.js) → 4 Live (SSE/WS) → 5 Деплой (Cloudflare Tunnel+Vercel, HTTPS) → 6 PWA-polish.

**🔴 ИНВАРИАНТ:** дашборд читает ТОЛЬКО из БД/кэша, НИКОГДА не дёргает биржу сам (один владелец rate-limit = торговый цикл). **SEC-01b/c НЕ делать раньше Phase 2** (вольётся в auth нового API; сейчас держит `127.0.0.1`).

---

## 🎨 ARCH-128: Воспроизведение OKO-SM + parity детекторов (03.06.2026, инициатор ARCH)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| ARCH-128-S3 | 🔄 | **Шаг 3: ре-майнинг** на 75 признаках. A=Claude (ре-чек 215 текущих), B=DS-315 (полный walkforward+MHT). Интерпретация+калибровка OTE/EQH = Claude | DS+Claude |
| **🧹 DS-MAINTENANCE (03.06)** | | | |
| **DS-321** | 🚀 | **TSL гибридная коробка в проде:** `tsl_hybrid_enabled=true`, Gear 1/2/3, откат через config. Backtest +1.95R, 68% pos | DS |
| **DS-326** | 🔴 | WT-B LTF-вход: три последовательных фильтра (бэктест). Базовый скрипт готов:… | DS |

| **DS-325** | 🟢 **Ф1+Ф2 ГОТОВО (DS 14.06).** Файл: `core/infra/pydantic_config.py`. OkoConfig: 6 domain-моделей + 30 Dict-секций, `extra="forbid"` (поймал 30 неучтённых полей → добавлены в схему). `ConfigProxy.get("a.b.c")` совместим с ConfigLoader. Поглощён `config_validator.py`. `strict=True`: config.yaml проходит чисто. `requirements.txt`: pydantic>=2.0.0 + pydantic-settings>=2.0.0. **НЕ сделано:** Ф3 (миграция callsites), перестройка config.yaml. | 🟢 done (Ф1+Ф2) | `core/infra/pydantic_config.py` |)

| ARCH-128-ENGINE | 🔄 | **OTE-Retest Engine + Фрактальный Куб** (ВХОД-движок): слом→импульс→OTE→ретест→вход+SL. Ядро `ote_retest_setups`. **Исследование 03-04.06 (бэктест 5 пар) → `docs/RESEARCH_OTE_CUBE_2026-06-03.md`:** вложенность HTF-зона×LTF-слом=риск ×10; частичный TP1=1R лечит WR(12→72%); матрица оптимум 4h→15m(+0.471); каскад глубина=качество; двунаправленность (откаты ≥ продолж, 4h→5m откат +1.128 WR83%); дивергенция только В OTE; инвалид-SL(1.0)=неперекрытие Эллиотта; сверка с DS-316 сошлась на 15m. TP→TPSelector(вклад: отриц.фибо+EQL/FVG), TSL→tsl_updater, SL→ExitManager Ph2. **NEXT:** вход=LTF-слом в OTE+дивергенция; подтвердить 5m-откат на 45 парах. `memory/ote_nested_mtf_strategy.md` | Claude |
| **ARCH-128-MON** | ⏳ | **Мониторинг качества OTE / Premium-Discount** — периодическая отрисовка фибо на чартах для визуальной сверки (правильно ли определяются OTE-зона и premium/discount). Контроль эталона после изменений | Claude |
| **ARCH-128-C01** | 🔴 → DS | СЛЕПОТА CHoCH/SMC (length=50) в ядре паттернов → length=5 + ре-майнинг. Найд… | DS+Claude |

---

## 🧊 Stabilization Sprint (04.05–25.05.2026) — заморозка vision

**План:** [`/root/.claude/plans/fluttering-snacking-whale.md`](/root/.claude/plans/fluttering-snacking-whale.md) — «Возврат управляемости».

**Корень:** в БД попадает ~4% детектируемых сигналов, остальные 96% теряются молча. ML обучается на 30-40% данных. `decision_trace.py` готов, но в `_broadcast_intelligence_alert` не вызывается. Сначала видимость, потом архитектура.

**Заморожено до Phase 4 (~25.05):** ARCH-74-EXT, ARCH-96..99, ARCH-101..104, ARCH-105..111. Не открываем, не удаляем — паузим. Активный спринт «Реальные убийцы» (DEV-184..193) **продолжается** как стабилизирующий.

**Фазы:**
- **Phase 0** (1-2д): DecisionTrace в 14 gates → таблица `signal_drops` → дашборд топ-10 reasons
- **Phase 1** (2-3д): `audit_mode` shadow + `audit_trades` → отчёт `audit_filter_efficacy.py`
- **Phase 2** (3-5д): coverage matrix + alerts на коллапс данных + ML skipped-rows visibility
- **Phase 3** (5-7д): `bot/loops/broadcast_pipeline.py` + 14 gate-файлов + тесты

**Критерий выхода:** monitoring.py < 800 строк, coverage critical полей ≥ 90%, 7 дней без регрессии avgR.

---

## 🗺️ Архитектура

> **Два потока, Куб, статусы сфер:** [`docs/CURRENT_ARCHITECTURE.md`](docs/CURRENT_ARCHITECTURE.md) ← читать при потере ориентации
> **Куб Метатрона (концепция):** [`docs/ENCYCLOPEDIA.md`](docs/ENCYCLOPEDIA.md) → раздел "Куб Метатрона"
> **ARCH-104 migration plan:** [`docs/MIGRATION_ARCH104.md`](docs/MIGRATION_ARCH104.md)

---

## 📊 Активные задачи

**Статусы:** 🔴 срочно | 🟡 важно | 🟢 в плане | 🔵 бэклог | 🔄 в работе | ⏸ отложено | 🧊 FROZEN до Phase 4

| ID | Ст | Описание | Роль |
|---|---|---|---|
| **ARCH-130** | 🟢 | **OhlcvCache reader оптимизация** — заменить `pd.DataFrame([r])` per свечу в QueueReaderThread на сырой dict/tuple + `deque+SimpleQueue` вместо RLock-pandas-merge. Цель: убрать налог холодного старта (~200с), разблокировать sem=16+. Рой 14.06 (groq+openrouter): консенсус — правильный путь. Риск: аудит downstream потребителей OhlcvCache (rolling/groupby в analytics). Принцип: [[principle_reuse_not_duplication]]. Детали → DISCUSSION.md 14.06 19:00 UTC. | ARCH/Claude |

| **REGIME-V2** | 🟡 | Активировать regime v2 (HTF-доминанта) — через УНИФИКАЦИЮ (D-10), не просто фл… | ARCH/Claude |

| **HIGH-VOL-VOLUME** | 🟢 | HIGH_VOL + объём (VSA) — рой 7/7 консенсус 11.06. HIGH_VOL = чистый ATR (вол… | ARCH/Claude |)

| **🟢 ARCH-118 / ARCH-118.3: единый снимок признаков — ЗАКРЫТ (05-08.06)** | | | |
| ARCH-129-FLOW | 🔴 | 🆕 ЧИСТОТА ПОТОКОВ ДАННЫХ — ЭПИК (голосовая юзера 09.06 «Проект_Клауд_Телеграм»… | gap%\ | ×2, OB по ATR(200), zigzag 1:1 ARCH-128) → **A = КАНОН**. Набор **B** (`core.smc.fvg/order_blocks/structure`) отклоняется (OB по цвету свечи+volume, FVG фикс-порог 0.05%+join). **🔴 НАХОДКА: FVG = ТРИ калькулятора** (A эталон-зоны / B зоны-отклонение / **C** `indicators.detect_fvg` — 3 бара БЕЗ порога=шум, в ЯДРЕ `trading_intelligence`!). OB=два. **✅ Паттерны/ML/trade_features НЕ затронуты** (combinator→swing_bridge→A эталон, ARCH-118). **✅ TSL trailing=ATR Trend, чист** (OB только вторичный DEV-221 force-close). <br>**🔴 ФАЗА 1 — структура-канон A** (корень цепочки: structure 87%→OB 7%, малый дрейф breaks взрывается в OB). <br>**🔴 ФАЗА 2 — OB-канон A → магниты TPSelector эталонные** (ГЛАВНОЕ: цели/TP тянутся к не-эталонным OB). `build_smc_snapshot` B→A, богатые поля (mitigation_pct/breaker/volume_ratio) = обёртка над A-расчётом. <br>**🟡 ФАЗА 3 — FVG-канон A** (69%→100%): свести B+C к A; C(indicators) дать порог или обёртка над A (ядро TI/pivot_reversal сейчас на шумном C). <br>**🟡 ФАЗА 4 — live-консьюмеры** (могли калиброваться на B): market_regime (B-structure 13%), DEV-221 (B-OB вторичн.), mtf_smc_specialist (shadow). <br>**Регресс-тест:** `arch129_detector_parity.py` 7%→90%+ после. **🔴 WAVE-WATCH зависит:** брать зоны из A (эталон), НЕ из build_smc_snapshot(B) пока не мигрирован. **Делать со свежей головой, начать с магнитов (Фаза 1-2).** | ARCH/Claude |

| **🔭 DS-EVOLUTION: 4 приоритета после чтения документации (06.06.2026, инициатор DS, коммит f03a667)** | | | |
| ARCH-96-EXEC | 🟡 | Execution Sphere — разморозить, единый слой ордер-менеджмента. Сейчас исполн… | ARCH/DEV |

| **ARCH-96-HUB** | 🔴 | 🆕 ЕДИНЫЙ ACCOUNT-АГНОСТИЧНЫЙ КАНАЛ ИСПОЛНЕНИЯ… | «один калькулятор» ARCH-118/129 и DOC-SYNC. **🔴 КОРЕНЬ #21703 (доказано 09.06):** обработка main/sub НЕ идентична — ЧТЕНИЕ агрегирует все акки (`_get_positions_cached` Ф3 ✅), но ЗАКРЫТИЕ/SL зовут `position_sync._get_client_synced()` БЕЗ symbol → дефолт MAIN → видит sub-позицию, закрывает через main → «No position» → 5 голых позиций без SL (3 на sub). **🜂 ИНВАРИАНТ «ОДИН КАНАЛ, ACCOUNT ИЗ КОНТЕКСТА»:** каждая операция (read/place_sl/close/check/TSL) ОБЯЗАНА знать account позиции (symbol-routing ИЛИ position._account). ЗАПРЕТ дефолта на main. **Карта дыр:** `position_sync.py:160,224,564` (`_get_client_synced()` без symbol). **Цель:** новый sub автоматически защищён (один pipeline). **Покрывает OPS-06 ч.3** (qty+SL для sub). **🌌 УРОВЕНЬ ВЫШЕ — EXCHANGE=ПАРАМЕТР (вопрос юзера 09.06 «применится ли к другим биржам?»):** иерархия канала `exchange → account → symbol → position`. Замер 09.06: ЧТЕНИЕ уже exchange-агностично (`data_collector exchange_id` параметр + ccxt), ИСПОЛНЕНИЕ захардкожено BingX (14 строк + весь `bingx_client`: positionId/one_click/109400). **Фундамент multi-exchange (узнать ЗАРАНЕЕ, не «по факту»):** интерфейс `ExchangeAdapter` (place_order/place_sl/close/get_positions(account)/get_filled) — hub зовёт ИНТЕРФЕЙС; `BingXAdapter` изолирует специфику; ccxt-база (create_order/fetch_positions) + тонкий адаптер для биржа-уникального. Новая биржа=новый Adapter, hub НЕ меняется. **Тест чистоты:** описать hub БЕЗ слова «BingX». principle_reuse_not_duplication на уровне бирж. | ARCH/Claude |

| ARCH-96-MULTIACCT | 🔴 | Мульти-аккаунт BingX (субаккаунты) — обойти потолок 100 ордеров/аккаунт для ма… | Claude/ARCH |

| DS-BRIDGE-SNAP | 🔴 | Мост `trade_features` → решения: arch104/ote_nested СЛЕПЫ к снимку. Снимок 2… | Claude |

| DS-RISKINT-PROD | 🟡 | RiskIntelligence → production: код написан, НЕ включён. RI v1 (sizing/lifecy… | ARCH/DEV |)

| DS-CTXBUS-38 | 🟢 | Shared Context Bus — наполнить до спроектированных 38 полей. Центральная сфе… | ARCH |

| TR-ERA4 | 🟢 | Эра-4 замер (08.06, n_ote=745 n_arch=1760): OTE флагман +1115R avgR+1.50… | TRADER |

| **🔴🔴 VST-REALITY: баланс в МИНУС при R+ (08.06, юзер заметил баланс↓) — SLIPPAGE+FUNDING** | | | |
| **🌊 WAVE-SERVICE: волновой анализ MTF — ключ к качеству (08.06, юзер «там решение», погнали без ожидания стабилизации)** | | | |
| WAVE-SERVICE | 🔴 | MTF-волновой сервис — недостающее звено для pivot/arch104/OTE «знать где в вол… | 0.618w3; зигзаг B=0.618A/C=1\ | 1.618A; плоскость B≥0.9A/C=1.618A; чередование w2↔w4. **Эталон:** PDF(docs)+`obsidian/Concepts/Elliott-Wave*`(4 файла n=3597). **Поглощает:** ARCH-127, Elliott-Pivot Sub-куб. **Инструмент:** `scripts/wave_smc_entry.py`(анализ входа)+`scripts/wave_smc_backtest.py`(валидация, 6eb218f). | ARCH/Claude |

| WAVE-FLAGMAN | 🔴 | 🆕 НОВЫЙ флагман = ОЦИФРОВКА разгонной схемы юзера (раскрыта 08.06, user_wave… ). **Док:** [docs/METATRON-KERNEL.md](docs/METATRON-KERNEL.md), [docs/adr/ADR-001](docs/adr/ADR-001-external-services-via-port.md) (accepted). **Сделано:** §A reference-arch + ADR-конвенция. **Дальше (отдельные задачи):** §B извлечь `metatron-core`; рой→`swarm-service` (мини-Куб + API + team-update); порт в `scan_loop`; §C template-репо. Соответствие Кубу 4/4. | ARCH |

| **🟢 ARCH-126: DS-оркестратор роя за AdvisorPort — Phase 1 В ПРОДЕ (shadow) (02.06.2026, инициатор ARCH/пользователь)** | | | |
| ARCH-126 | 🟢 | AdvisorPort реализован end-to-end (продолжение ARCH-125, ADR-002). DeepSeek-… | ARCH/swarm |

| **🟡 ARCH-127: MTF Reversion Core — ось OB/OS вместо regime-классификации (02.06.2026, инициатор ARCH/пользователь)** | | | |
| ARCH-127 | 🟡 | Переосмысление сигнального ядра: regime-классификация (TREND/RANGE)… | ARCH/swarm |

| **🔵 OB-DATA: Order-Book данные крупных игроков — БЭКЛОГ (наработка 03.06.2026, инициатор пользователь)** | | | |
| OB-DATA | 🔵 | Наработка/инструменты для получения данных стакана (НЕ интегрировано). Цель:… | ARCH |

| **✅ DEV-237: РЕШЕНО 31.05 — сделки НЕ шли на биржу/VST (exchange_order_id=None) → btc_market_gate в shadow (30.05.2026, инициатор ARCH)** | | | |
| **✅ DEV-241: TSL-катастрофы R=-15 на SHORT — ИСПРАВЛЕНО 02.06 (commit 299b1a6)** | | | |
| **✅ DEV-237-OBS: ЗАКРЫТ 02.06 — LONG здоров, btc_market_gate→shadow подтверждён** | | | |
| **❓ DEV-237-B: вариант B — флэт-детектор BTC вместо shadow (под вопросом, НЕ приоритет) (31.05.2026, инициатор ARCH)** | | | |
| DEV-237-B | 🔵 | Под вопросом, пока не до неё. Постоянная замена временному shadow ARCH-78: н… | движение BTC 4h за N баров менее порога, напр. 2%/48ч, а блокировать только в настоящем падении. Чинит корень (лаг ATR Supertrend держит BEAR во флэте), сохраняя защиту в реальном BEAR. Альтернатива — ADX/hysteresis на `BTCRegimeProvider`. Брать только после итогов DEV-237-OBS. См. project_btc_regime_provider_lag. | ARCH/DEV |

| **🔴 DEV-238: расследование wt_signal=0 confirmations (31.05.2026, инициатор Claude из DEV-224)** | | | |
| **🟡 DEV-239: фикс shadow_pivot_LONG df_15m=None (31.05.2026, инициатор Claude из DEV-224)** | | | |
| [DEV-239](#dev-239) | 🟡 | 53 pivot_reversal LONG сделки имели `shadow_pivot_real_touch=NULL` и `shadow_p… | DEV |

| **🟢 DEV-240: timing-guard scan>250s — НЕ ВНЕДРЯТЬ (31.05.2026, инициатор Claude из DEV-224)** | | | |
| [DEV-240](#dev-240) | 🟢 | Гипотеза роя `scan_loop_duration > 250s = skip entries this cycle` ОПРОВЕРГНУТ… | DEV |

| **✅ ARCH-124: АУДИТ REGIME ЗАКРЫТ 30.05 — классификатор RANGE мешает (78% мислейбл)** | | | |
| [ARCH-124](#arch-124) | ✅ | АУДИТ системы режимов — помогает или мешает?** Гипотеза ARCH: «вычисление режи… | WT1-WT2\ | ≤10 → RANGE. В шумной крипте любое расхождение 15m/1h метит RANGE → подозрение что часть ТРЕНДОВ мислейблится в RANGE. **(3) SHORT-фильтр ПРОТЕКАЕТ:** `allow_short_regimes:[TREND_DOWN]` применяется ТОЛЬКО к atr_change (scan_loop:700) — 10/11 signal_type игнорируют → 455 RANGE SHORT/7д avgR=-0.391 (-178R). Главные протекатели: confluence(205, уже ВЫКЛ DEV-224) + watch_list_breach(160, не гейтится). **АУДИТ (только данные, НЕ менять до выводов):** (A) спот-чек 20-30 RANGE-сделок: реально ли range или мислейбл тренда (price action vs label)? (B) A/B: RANGE-сделки по signal_type/direction — где RANGE реально режет убыток, а где мешает прибыли? (C) ADX порог 25 — сравнить с MTF-методом (расходятся ли)? (D) Вопрос: упростить/убрать regime-гейтинг? Заменить на прямые фильтры (PP position, n_down×htf)? **Acceptance:** вывод help/hurt по каждому применению regime (block/downgrade/allow_short) + рекомендация. **🔗 Смежно DEV-237** (тот же мотив «классификатор режима мешает», но другой компонент — глобальный `BTCRegimeProvider`/лаг Supertrend vs per-pair `MarketRegimeClassifier`/рыхлость RANGE). Связь: (a) DEV-237 shadow btc_market_gate = живой A/B-эксперимент для пункта (B) — WR разблокированных LONG считает DEV-237-OBS; (b) DEV-237-B (флэт-детектор по фактическому движению) = частный случай пункта (D) «заменить regime-гейтинг прямыми фильтрами». **✅ АУДИТ ВЫПОЛНЕН 30.05 (TRADER):** (A) price-action спот-чек 18 RANGE-сделок → **14/18=78% реально ТРЕНДИЛИ** (LAB SHORT при +46%/40h ADX=44 → R=-1.11; BANANA -6.3% ADX=31 → R=-6.18). max_R proxy: RANGE 0.65>TREND 0.59 (трендили). (B) regime слабый дискриминатор (watch_list убыток везде; pivot_reversal ХУЖЕ в range). (C) RANGE LONG +0.16 vs SHORT -0.53 = дело в направлении. **КОРЕНЬ:** TREND требует 15m+1h+4h синхронность+wt_diff>10 → крипта-шум → 78% трендов в RANGE. **ВЕРДИКТ: классификатор МЕШАЕТ. Рекомендация: свернуть regime-гейт → прямые фильтры (htf_price_dir для SHORT + n_down×htf + PP) ИЛИ HTF-доминантность в классификаторе. Разбор: DISCUSSION 30.05. Скрипты: e:/tmp/arch124_spotcheck.py, arch124_audit.py. | ARCH/TRADER |

| **✅ DEV-233..236 ЗАКРЫТО (30.05): дивергенции+wt_cross исправлены, ретробэктест 3 этапа, golden изолирован** | | | |
| **🟡 ФАЗА 2 — разбор arch104 паттернов (путь к +): 111 сделок, 46% SL, держится на 2-3 паттернах** *(🔗 смежно DEV-237: arch104 минует ВСЕ режимные гейты monitoring — свой observer loop, soft_gates_enabled:[], exchange_enabled:true → его сделки не защищены btc_market_gate, учесть при анализе SL)* | | | |
| TR-232a | 🟡 | T5_L_02 — почему работает (+6.41R n=11 WR=55%): разобрать лучший live-паттер… | TRADER |

| TR-232b | 🟡 | Убытки: −1.00R массово + T4_S_09 (−7.58R n=3): почему обилие чистых −1.00R (… | TRADER |)

| TR-232c | 🔵 | 5m-топы не торговали: L1_golden_LTF_5m (бэктест n=268 WR=97%), T8_L_L3_5m_01… | TRADER |

| **🔴 DEV-230: деградация всего потока данных = перегрузка event loop от WS — [DISCUSSION.md](DISCUSSION.md)** | | | |
| DEV-230-FU | ⏸ | **WS постоянное решение — ОТЛОЖЕНО.** Сначала мониторим поток arch104-сделок через DEV-232 gate (2-3 цикла observer): стабильность ltf_fetched, пошёл ли поток 5m-топов (L1_golden WR=97%), решения не просели. Потом — решение по WS (A/B/C). | ARCH |
| DEV-231 | 🟡 | Дашборд `/api/dashboard` timeout >10с: `_handle_dashboard_api` → `full_stats… | DEV |

| **🔴 DEV-226: TSL не активируется при R>1 (два корня) — разбор в [DISCUSSION.md](DISCUSSION.md)** *(🔗 смежно DEV-237: TSL tracker стартует только для live/vst позиций — сделки в paper exch=none его НЕ активируют; проверить, не попадала ли часть «не активируется» на paper-сделки до shadow-фикса)* | | | |
| DEV-228 | 🔍 | **РАССЛЕДОВАНО (28.05):** первопричина stale = нестабильность ccxt.pro `watch_ohlcv` на BingX (1 instance×80 пар, `SLOW await 64-92s`×110, 560 errors, массовое залипание всех пар batch'а) + cap priority[:80] при OPEN~107 + `update_priority_pairs` no-op (D-073). НЕ баг кода — ограничение WS. Вердикт: force REST (DEV-227) = изолятор критичного пути; WS = best-effort для scan. Опции: WS-staleness метрика в дашборд, долгосрочно D-072 (data_service). Ждёт решения ARCH (закрыть/держать на D-072) | DEV/ARCH |
| DEV-229 | 🔵 | АУДИТ масштаба stale-кэша: скрипт — сколько OPEN сделок имеют расхождение st… | DEV |

| **🚀 СПРИНТ «CONFIRMATION-DRIVEN ARCHITECTURE» (09.05–23.05.2026)** — на основе R6/R7/R8: ATR Trend change cascade подтверждён, ЗАКОН confluence | | | |
| [DEV-200](#dev-200) | 🟡 | ✅ PHASE 1 ГОТОВ (04.06, observation-only, нужен рестарт). Реализован co-loca… | DEV |

| [DEV-201](#dev-201) | 🟡 | ⭐ Частично закрыт DEV-200 Phase 1 (04.06): `observe()` метод реализован (sig… | DEV |)

| **TR-241** | 🟡 | ✅ Скрипт ГОТОВ + инструментовка завершена (04.06). Запуск ~06.06: `python sc… | TRADER |

| **ARCH-118.3** | 🔵 | Phase 3: ОДИН КАЛЬКУЛЯТОР — владелец Claude(OTE).** **Шаг 1 (разблокирует DEV-… | Claude(OTE) |)

| [DEV-202](#dev-202) | 🟡 | features_json: confirmations[]: гранулярная запись всех подтверждений (не пл… | DEV |)

| [DEV-204](#dev-204) | 🟢 | ML Outcome retrain weights: после 200+ сделок → переобучение confirmation ве… | DEV |

| [DEV-205](#dev-205) | 🟢 | Phase 0→2 расширение: audit_mode shadow + audit_trades + alerts на коллапс д… | DEV |

| [TR-003](#tr-003) | 🟡 | TRADER валидация Confirmation Registry: ручной разбор ≥30 composite сделок с con… | TRADER |

| **🚀 СПРИНТ «РЕАЛЬНЫЕ УБИЙЦЫ» (25.04–02.05.2026)** — после D1+RE-AUDIT: фикс не D1-багов, а реальных источников −780R/10дн | | | |
| [DEV-191](#dev-191) | 🟢 | **wt1_at_trigger_tf поле в features_json:** для wt_b писать wt1 на 1h, не на 15m. B5 фикс | DEV |

| [DEV-192](#dev-192) | 🟢 | entry_to_trigger_distance_pct в features_json: для pivot_reversal… | DEV |

| **——— Архив: старые спринты перемещены в [TASKS-ARCHIVE.md](TASKS-ARCHIVE.md) ———** | | | |
| **🚀 СПРИНТ «ЗАМЫКАНИЕ РАЗРЫВОВ» (19.04–26.04.2026)** — ✅ ARCH-88/89/90/91, DEV-172-FIX закрыты (→ TASKS-ARCHIVE) | | | |
| [ARCH-92](#arch-92) | 🟢 | Анализ WR/avgR по Entry Priority (P1/P2/P3) на 200+ закрытых сделках (~22.04). Решение: P3→WATCH или оставить shadow | ARCH |

| [ARCH-93](#arch-93) | ⏸ | **FROZEN (25.05 рой 3/3):** Future pivots touch→reaction — DEV-36 modifier уже покрывает. Пересмотр при наличии данных | ARCH/DEV |
| **——— Старые ✅ спринты → [TASKS-ARCHIVE.md](TASKS-ARCHIVE.md) ———** | | | |
| [ARCH-95](#arch-95) | 🔴 | Расследование убытков (H1-H5 актуальны): H6 MTF alignment + H7 адаптивные ве… | ARCH/DEV |

| **🆕 СИСТЕМНЫЕ СФЕРЫ КУБА (Claude consult 25.04 — параллельно с фиксами Слоя D ARCH-95)** | | | |
| [ARCH-96](#arch-96) | 🧊 | Execution Sphere (Сфера 14): IdempotencyGuard + SlippagePredictor + OrderTypeSelector + ExecutionTracker. Закрывает SL-дубликаты архитектурно, режет slippage. КРИТИЧНО перед LIVE — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-97](#arch-97) | 🧊 | Anomaly Detection Sphere (Сфера 15): self-observability на execution/trading/ML drift. Поймала бы DEV-174/175/SL-dup за 1-72ч до человека — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-98](#arch-98) | 🧊 | Portfolio Manager Sphere (Сфера 16): β-exposure к BTC/ETH, sector concentration, rolling DD. После Risk Sphere shadow — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-99](#arch-99) | 🧊 | Meta-Learning Sphere (Сфера 17): XGBoost f(context, signal_type)→E[R] контекстуальный фильтр — **FROZEN до Phase 4** | ARCH/DEV |
| **🆕 ДОЛГ ПО КАРТЕ ШИНЫ И КУБА (`docs/SIGNAL_BUS_CUBE_MAP.md`, 27.04 TRADER)** — Фаза 1 roadmap | | | |
| [ARCH-101](#arch-101) | 🧊 | Mesh шины: 11/16 детекторов → `event_bus.publish("signal_detected", ...)` в monitoring.py. Без этого Narrative/Anomaly/Exit слепы — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-102](#arch-102) | 🧊 | BTCRegimeProvider → `cross_market` publish при смене BULL↔BEAR. Расширение ARCH-78 — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-103](#arch-103) | 🧊 | `classify_mode` (reversal_mode) из shadow в production — **FROZEN до Phase 4** | ARCH |
| [ARCH-104](#arch-104) | 🧊 | Унификация двух нумераций сфер: `sphere_registry.SPHERE_NAMES` vs `selftest_cube`. Выбрать одну, выровнять — **FROZEN до Phase 4** | ARCH |
| **🆕 ВИДЕНИЕ: PREDICTIVE SETUP ENGINE (`docs/TRADER_VISION_PREDICTIVE_SETUPS.md`, 28.04 TRADER)** — переход от reactive market к predictive limit | | | |
| [ARCH-105](#arch-105) | 🧊 | Order Flow & Macro data sources: funding history + OI + liquidations. Базис для гипотез H5/H6 — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-106](#arch-106) | 🧊 | TriggerBus + persistence: новая шина атомарных триггеров + таблица `trigger_events`. Фундамент для ML на 100k+ событий — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-107](#arch-107) | 🧊 | Setup Engine v1 (Сфера 18): `TradingSetup` dataclass + state machine + таблица `trading_setups` — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-108](#arch-108) | 🧊 | Predictive entries: ladder limit orders + bracket-link. Зависит от ARCH-96 — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-109](#arch-109) | 🧊 | Strategy DSL: yaml-описания стратегий. После Setup Engine v2 — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-110](#arch-110) | 🧊 | Volume Profile + CVD: VPVR / POC / VAH / VAL + WS trade stream. Гипотеза H9 — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-111](#arch-111) | 🧊 | Setup-aware Meta-Learning: расширение ARCH-99 на `f(context, setup_type, trigger_chain) → E[R]` — **FROZEN до Phase 4** | ARCH/DEV |
| [TR-002](#tr-002) | 🟢 | Бэктест-валидация 10 гипотез прогнозирования H1–H10 на исторических данных Trigg… | TRADER |

| **DASHBOARD** | | | |
| [DEV-144f](#dev-144f) | 🟢 | P6: Единый CSS — тёмная тема, виджет-карточки, responsive grid | DEV |

| **СТРАТЕГИЯ / СИГНАЛЫ** | | | |
| [DEV-111act](#dev-111act) | ⏸ | BTC 4h gate production: отложен — риск блокировки alt-pumps при BTC боковике | DEV |
| [DEV-104](#dev-104) | 🔵 | Dead-Man Timer: emergency close all (Слой 3 ARCH-65) — только перед LIVE | DEV |

| **ML / АНАЛИТИКА** | | | |
| [DEV-162](#dev-162) | 🔵 | derive_wt_verdict: динамический confidence вместо статического (триггер: 200+ BLOCK) | DEV |

| **RISK INTELLIGENCE (Сфера 3 Куба) — обсуждение 19.04** | | | |
| DEV-183 | 🔵 | Position count cap + correlation cap по BTC | ARCH/DEV |

| **КУБ МЕТАТРОНА** | | | |
| **🗺️ ROADMAP ПО ЭТАПАМ (30.05.2026)** — согласованная последовательность. Каждый этап = фундамент следующего. | | | |
| ЭТАП 0 | 🔄 | **СЕЙЧАС: рестарт + копим данные (24-48ч).** В бою: DEV-224 (TPSelector ВКЛ / confluence ВЫКЛ), ARCH-122 ч.2 магниты (OB/EQH/EQL/multiTF-FVG в tp1), ARCH-122 ч.1a (tp2 из магнитов), ARCH-120 SMC Sub-куб, ARCH-117 ph1 WTService. **Метрики мониторинга:** avgR/captured_R по сделкам, распределение `tp_source` (доля кластеров с ob/eqh vs одиночных), TP1/TP2 hit rate, нет ли регресса от новых магнитов. **Выход:** 50-100 закрытых сделок post-08:08 → A/B vs прежние выходы. | ALL |
| ЭТАП 1 | 🟡 | ARCH-118 — единый features_json snapshot (ВАРИАНТ B: из combinator). Решение… | ARCH |

| ЭТАП 2 | 🟢 | ARCH-122 ч.1b — Exit Manager Сфера 10 поверх ARCH-118… | ARCH/DEV |

| ЭТАП 3 (∥) | 🟢 | ARCH-117 ph2 — RSIService + миграция (extended_indicators wt2 EWM→SMA фикс… | ARCH/DEV |)

| ЭТАП 4 | 🟢 | Cube spheres: ARCH-123 (PivotSphere) → ARCH-119 (Reversal Mode) → ARCH-121 (… | DEV |)

| ЭТАП 5 | 🔵 | ARCH-122 ч.3 (SLSelector OB edge+CHoCH/BOS) + ARCH-120 ph2 (ML SMC Specialist… | ARCH/DEV |)

| **🆕 НОВЫЕ СФЕРЫ + SUB-КУБЫ (29.05.2026)** — архитектурный анализ WaveService + карта кандидатов. Полный разбор: [DISCUSSION.md → 29.05.2026 ARCH-115/116] | | | |
| [ARCH-121](#arch-121) | 🟡 | WaveService → Сфера 14: Elliott Wave прокси (переим… | ARCH/DEV |)

| [ARCH-122](#arch-122) | 🔄 | **Exit Manager Сфера 10: извлечь TPSelector + обогатить магниты — ЧАСТЬ 2 ГОТОВА (30.05.2026).** **Корень (DEV-224 находка):** TPSelector встроен в `calculate_levels` (единств. `.select()`), не узел. **✅ Часть 2 — магниты обогащены:** `TPSelector._magnets_from_snap()` читает Bus `smc_snap` (ARCH-120): **OB** (nearest_bull/bear_ob), **multi-TF FVG** (реальный tf-лейбл), **EQH/EQL liquidity**, **Fib ext**. Веса добавлены в `_WEIGHTS` (ob=3.5, eqh/eql=3.0, fib_ext=2.5). Инъекция snap в `market_context.smc_snap` через `_pair_context_bus.get(sym)` (trading_intelligence). Старый `smc_context.fvg` = fallback. Тест: AAVE LONG 1→10 магнитов (OB+EQH+multiFVG). 5 unit-тестов `test_tp_selector_magnets.py` ✅. **Ответ на `smc_context.fvg`:** это single-TF analyze_smc(df_entry 15m) — дубль SMCSubCube, оставлен (reversal_scanner/OTE/to_features используют), но TPSelector теперь предпочитает Bus snap. **✅ Часть 1a (30.05) — tp2 из магнитов:** `trade_simulator.register_trade` — при DUAL_TP + tp_selector_enabled берёт `recommendation.tp2_price` (TPSelector gravity-кластер) вместо pivot-async. Не None → `get_next_tp_by_hierarchy` пропускается (trade_simulator:1172). Fallback на pivot если TPSelector tp2 нет. Лог `[ARCH-122] TP2 из магнитов`. **✅ Часть 1b ExitManager Phase 2 (31.05) — TP в ТОЧКЕ СХОЖДЕНИЯ каналов.** **Корень (мониторинг):** магниты 0/100 даже после Phase 1 — TPSelector сидел в `calculate_levels` (ОДИН канал/intelligence-рек, редко регистрируется), а массовые сделки идут СВОИМИ каналами (atr_change:851 own atr_rr, wl_breach, pivot_reversal) → магниты орфаны. Многоканальность = Куб (по дизайну). **Phase 2:** `resolve_magnet_tp(sym, entry, sl, dir, bus, pivot_calc, config)` в exit_manager — резолвит магнит из Bus `smc_snap` (ARCH-120) для ЛЮБОГО канала, RR-aware (tp2 main dist_R≥1, не близкий tp1). Вызов в `register_trade` ПЕРЕД INSERT (точка схождения ВСЕХ источников) → каждая сделка получает магнит-TP независимо от канала. max_rr cap. Fallback на TP канала если магнит нет. Тест end-to-end (BONK/ADA/AAVE): RR 1.0-2.5, кластеры eqh+fvg+ob. Лог `[ExitManager P2] магнит-TP`. **⚠️ ПОРОГ dist_R≥1.0 НАМЕРЕННО СЛАБЫЙ (решение 31.05):** при WR бота ~35% магнит RR<2 математически убыточен (безубыток WR=1/(RR+1): RR=1→50%, RR=2→33%). НО оставляем 1.0 чтобы НАКОПИТЬ магнит-сделки по всему RR-спектру → измерить магнит-WR по RR-бакетам → поднять порог ПО ДАННЫМ (проверка gravity-thesis: даёт ли близкий магнит реальный высокий WR в live). До накопления НЕ трогать порог. **Phase 1 (база):** `magnet_tp_locked` предикат + 3 override-guard (monitoring:1130/1682, range_bounce:1156). 9 unit-тестов. **Требует рестарт → tp_source `@`-метки ВО ВСЕХ каналах, A/B магнит vs pivot измерим.** Предыдущее: МОНИТОРИНГ вскрыл: магниты считались, но НЕ применялись (0/106 сделок имели `@`-метку в tp_source — всё pivot, даже в TREND_UP). Корень: `monitoring.py:1122` БЕЗУСЛОВНО перетирал `recommendation.take_profit/tp_source` на pivot ПОСЛЕ calculate_levels (rec_generator:249 «monitoring перезапишет»). Фикс: guard в обоих override-пойнтах (main :1122 + side-strat :1681) — если `tp_selector_enabled` И tp_source содержит `@` (магнит) → pivot НЕ перетирает; atr_fallback (без @) → pivot как раньше. Лог `ARCH-122: TPSelector магнит сохранён`. **Без этого DEV-224 «TPSelector ВКЛ» работал вхолостую.** **🔄 Часть 1b остаток — полный Exit Manager сфера** (`core/trading/exit_manager.py`, единообразно всем signal_type) — после данных. **Связь ARCH-118:** Exit Manager читает единый Bus snapshot. **TSL** трейлит ATR/swing — опц. привязать к магнитам. **🔄 Часть 3 — SLSelector** (OB edge+CHoCH/BOS). **Легенда:** `docs/TP_SOURCE_LEGEND.md`. **⚠️ Требует рестарт.** | ARCH/DEV |
| [ARCH-123](#arch-123) | 🔄 | **PivotSphere Сфера 8 — PHASE 1 ГОТОВ (30.05, переим. с ARCH-118 — коллизия).** **✅ Создан** `core/pivots/pivot_sphere.py` — `PivotSphere.compute_and_publish(sym, pivot_calc, ctx_bus)` формализует inline-публикацию scan_loop: pivot_snap {1W/1D/1M: {PP,S1-S3,R1-R3}} + **`fibonacci_equiv`** (R2/S2=0.618 OTE, R3/S3=1.0 ext, PP=0.5 — ENCYCLOPEDIA Сфера 8). Singleton. scan_loop переведён на PivotSphere. period_label отфильтрован (никто не читал из Bus). 8 unit-тестов `tests/unit/test_pivot_sphere.py` ✅. **Phase 2 (low):** `trigger_loop` строит свой pivot_snap из кэша — мигрировать на чтение Bus `state.pivot_snap`; TPSelector `pivot_cache_1d_1w` → Bus. **Разблокирует ARCH-121** (Elliott-Pivot Sub-куб). Требует рестарт. | DEV |
| [ARCH-119](#arch-119) | 🟢 | MarketRegime → Сфера 6 v2: Reversal Mode (29.05.2026): Добавить `mode=REVERS… | DEV |

| [ARCH-120](#arch-120) | 🔄 | **SMC Sub-куб: формализация — PHASE 1 ГОТОВ (30.05.2026).** Первый фрактальный Sub-куб. **✅ Создан** `core/smc/sub_cube.py` — `SMCSubCube.compute_and_publish(sym, ohlcv_by_tf, ctx_bus)` единый вход: build_smc_snapshot + fast_smc_verdict → Bus (SMC_SNAP_UPDATED + SMC_VERDICT). Singleton. scan_loop переведён с двух раздельных вызовов на один. **✅ ARCH-120 ключевое — liquidity в snapshot:** добавлен `detect_equal_highs_lows` в `build_smc_snapshot` → snap теперь содержит `eqh_level/eql_level/eqh_near/eql_near`. Snap = ПОЛНЫЙ источник магнитов для ARCH-122: OB + multi-TF FVG (с tf) + Fib(8 уровней) + swing + **EQH/EQL**. 6 unit-тестов `tests/unit/test_smc_sub_cube.py` ✅. Проверено на реальных данных (BONK/AAVE/ADA). **Phase 2:** убрать дублирование — TPSelector читает `market_context.smc_context.fvg` (одиночный, лейбл fvg_1h) вместо Bus smc_snap (полный) → унифицировать в ARCH-122. Триггер ML SMC Specialist: 200+ smc_snap сделок. **Требует рестарт.** | ARCH/DEV |
| [ARCH-77](#arch-77) | ⏸ | Миникуб WTMTF: ЗАМОРОЖЕН до Sharpe>1 в проде (множитель к убытку бесполезен) | ARCH/DEV |
| [ARCH-79](#arch-79) | 🔵 | S10→S11: PostTradeAnalyser → NarrativeBuilder feedback (narrative_outcome в PairCtx) | DEV |

| **——— Старые ✅ спринты → [TASKS-ARCHIVE.md](TASKS-ARCHIVE.md) ———** | | | |

| [DEV-227](#dev-227) | 🟡 | **Бэктест ВСЕХ новых стратегий (28.05.2026):** (A) Wave3 OTE SHORT (B) BearBOS Counter-LONG | TRADER/DEV |

| [DEV-225](#dev-225) | 🔴 | ATRChange SHORT: Daily Pivot PP + ChoCH/BOS shadow gate (28.05.2026): Ретроб… | DEV |

| [ARCH-115](#arch-115) | 🟡 | Wave Phase Intelligence: Elliott × Signals Integration (28.05.2026)… | ARCH/DEV/TRADER |

| [DEV-211](#dev-211) | 🟡 | MTFPivotAnalyzer deprecation + upgrade: старый класс в mtf_pivot_integration… | ARCH/DEV |

| [DEV-212](#dev-212) | 🟢 | pivot_confluence_2plus activation: registry имеет вес=6 но никто не генериру… | DEV |

| **——— Старые ✅ спринты → [TASKS-ARCHIVE.md](TASKS-ARCHIVE.md) ———** | | | |
| [DEV-220](#dev-220) | 🟢 | **MTF событийная TSL активация:** активация по 1h ATR-trend flip | DEV |

| [DEV-221](#dev-221) | 🔵 | SMC OB exit при де-эскалации: если цена вернулась в Order Block при де-эскал… | DEV |

| **🆕 ARCH-104 ВОРОНКА (27.05.2026 расследование)** — 88/7д vs 591 confluence (×6.7 меньше). 31/215 паттернов задействовано (14%). Главный душитель — D-051 wt_cross hard gate (26.05): поток упал с 20/день до 1-3/день. T5_L_02 avgR=+6.41 — артефакт SWARMS+AIN pump-кластера (без них −0.71R). RI v1 не режет (99% apply). 90% потерь между risk_decisions_log и register_trade | | | |
| D-074 | 🟡 | Soft D-051 — решение по данным D-073 (29.05.2026): 1107 drops за 2 дня (1h=6… | DEV |)

| D-075 | 🟢 | Disable D2_L_L3_15m_03: 17 сделок avgR=−0.41 WR_TP=0%… | DEV |

| D-076 | 🟢 | Single-position-per-symbol guard для arch104: защита от SWARMS-style pyramid… | DEV |

| **🆕 SL/TP INTELLIGENCE (25.05.2026)** — рой 4/6 моделей (контекст 83K). Исследование: 156K уровней, 20 пар, 2.4 года. FVG <0.3R = 73-86% reach. Gravity α=1.5 → top10%=83%. Pyramiding lift +14-21%. БД: 42% SL имели max_R>0.5R. Прогноз: WR 25%→70-85%, expectancy −0.44R→+0.75R | | | |
| **АРХИТЕКТУРА** | | | |
| [ARCH-87](#arch-87) | 🔵 | Fibonacci контекст в PairState: swing H/L + 0.618/0.705/0.79 в features_json для ML. Триггер: 50+ OTE сделок | ARCH/DEV |

| [ARCH-85](#arch-85) | 🟡 | Формализация статусов стратегий (ACTIVE/SHADOW/DEPRECATED/REMOVED) + deprecated… | ARCH |

| [ARCH-86](#arch-86) | 🟢 | ROADMAP: строки «invalidates data pre-YYYY-MM-DD» для DEV-157/171/174/175 (урок 3 AUDIT_LESSONS) | ARCH |

| [ARCH-80](#arch-80) | 🔵 | MarketRegime hysteresis + метрика regime_changes_per_day | ARCH |

| [ARCH-81](#arch-81) | 🔵 | Rolling Correlation Guard + portfolio_beta_to_btc (замена hardcoded) | ARCH/DEV |

| [ARCH-82](#arch-82) | 🔵 | L3 checker v2: regime-aware portfolio limits (TREND_UP: 3L+1S) | ARCH/DEV |

| [DEV-176](#dev-176) | 🔵 | SL cooldown per-TF калибровка (15m→2ч, 1h→4ч, 4h→12ч) | DEV |

| [ARCH-73](#arch-73) | 🔵 | Разбивка trading_intelligence.py (2578 строк): MLSpecialist + StrengthAggregator | ARCH/DEV |

| [ARCH-74](#arch-74) | 🧊 | Разбивка trade_simulator.py: TSLManager + MFETracker + ExchangeSyncGuard — **FROZEN до Phase 4** (Phase 3 даёт частичный split monitoring.py) | ARCH/DEV |
| [ARCH-74-EXT](#arch-74-ext) | 🧊 | **Smart TSL** (расширение ARCH-74): adaptive params per-pair/regime + Sphere 10 как brain + RL slot — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-75](#arch-75) | 🔵 | Разбивка monitoring.py (1436 строк): SignalFilter + MessageDispatcher | ARCH/DEV |

| [ARCH-76](#arch-76) | 🔵 | CubeNode интерфейс: Фрактальный Куб (триггер: LIVE + прибыль 30+ дней) | ARCH |

| [ARCH-57](#arch-57) | 🔵 | Confluence TRADER/RANGE tier parameter | ARCH |

| [ARCH-67](#arch-67) | 🔵 | USDT.D macro gate: CoinGecko API + shadow (бэклог май) | ARCH |

| [ARCH-69](#arch-69) | 🔵 | Перенести verbose-секции CLAUDE.md → ENCYCLOPEDIA.md | ARCH |

| [ARCH-44](#arch-44) | 🔵 | Добавить роль DATA (триггер: AUC > 0.55) | ARCH |

| [ARCH-47](#arch-47) | 🔵 | SMC contradiction filter: SHORT при нулевых медвежьих сигналах | ARCH |

| **TRADER** | | | |
| [TR-001](#tr-001) | 🔄 | Ежедневный разбор Watch List с живыми свечами | TRADER |
| [TRADER-AUDIT-002](#trader-audit-002) | 🟢 | Аудит DUAL_TSL split 10%/90%: grid search после 500+ новых DUAL_TSL сделок (~30.04) | TRADER |

| **🚀 СПРИНТ «ARCH-104/105 LIVE» (22.05.2026)** — pipeline жив, ARCH-105 hidden div в проде | | | |
| D-046 | 🟡 | Separate Isolated Margin mode на BingX (Hedge уже есть) для D-026 Multi-TF S… | DEV |

| DOC-PAT-01 | 🟢 | Pattern Library Reference (`show_pattern.py` готов 23.05): CLI lookup tool д… | DEV/ARCH |

| D-051.B | 🔵 | Walkforward per-TF triggers (combinator surgery): `combinator_v3_nested` сей… | DEV |

| D-048 | 🟢 | Re-entry from watchlist после SL: pair → arch104_watchlist (TTL 4-8h) → ждат… | DEV |

| **🚀 СПРИНТ «API LOAD REDUCTION» (24.05.2026)** — quick fix после BingX TEMP BAN 100410 (190 ошибок/час). Перед возвратом к Real Killers. | | | |
| D-072 | 🔵 | data_service отдельный процесс + Redis (следующая архитектурная фаза по team… | DEV |)

| **🚀 СПРИНТ «OBSIDIAN AUTOMATION» (23.05.2026)** — реализовано в одну сессию | | | |

---

## 📖 Детальные описания задач → [docs/TASKS_DETAILS.md](docs/TASKS_DETAILS.md)

> Полные спецификации, acceptance criteria, SQL-примеры, код — в TASKS_DETAILS.md.
> В таблице выше — только статус + краткое описание + `→ opens:`.

---

## 🗺️ Зависимости (`→ opens:`)

| Задача | Открывает |
|---|---|
| DEV-185.2 ✅ | DEV-185.3 (volume whitelist после watchdog) |
| DEV-190 ✅ | ARCH-100 (re-audit на effective_status) |
| DEV-186 + DEV-187 | ARCH-103 (reversal_mode production после стабилизации gate) |
| ARCH-95 (аудит) | ARCH-96 (Execution Sphere) |
| ARCH-96 | ARCH-97, ARCH-108 (predictive entries требуют OCO) |
| ARCH-101 (Mesh шины) | ARCH-106 (TriggerBus — расширение EventBus) |
| ARCH-106 (TriggerBus) | ARCH-107 (Setup Engine v1), TR-002 (бэктест H1-H10) |
| ARCH-107 (Setup Engine v1) | ARCH-108 (predictive entries), ARCH-111 (Meta-Learning v2) |
| ARCH-104 (унификация сфер) | ARCH-96..99 (регистрация новых сфер без хаоса) |
| DEV-180 (Risk v1 shadow) | DEV-181 (leverage), ARCH-98 (Portfolio Manager) |
| Фаза 0 спринта (+avgR) | ARCH-103 (reversal_mode production) |
| **DEV-199 (atr_change events)** | **DEV-200 (registry), DEV-201 (aggregator)** |
| **DEV-200 (registry)** | **DEV-202 (features_json), DEV-204 (ML retrain), TR-003 (валидация)** |
| **DEV-201 (aggregator v2)** | **ARCH-112 (audit), DEV-204 (ML retrain)** |
| **DEV-203 (DecisionTrace)** | **DEV-205 (audit_mode shadow)** |
| **DEV-204 (ML retrain)** | ARCH-103 reversal_mode production, ARCH-99 Meta-Learning |

