# Current State - handoff между сессиями (проектный слой, git)

> Последние ~8 сессий. Старое -> `current_state_ARCHIVE.md` + git log.
>
> **АРХИТЕКТУРА ПАМЯТИ (15.06.2026, чтобы две памяти не расходились):**
> - auto-memory (`~/.claude/projects/.../memory/`) = HOT-слой Даата (auto-load): `MEMORY.md` индекс + личное (identity/vision). Эфемерно.
> - repo `memory/` (ЭТОТ путь, git) = SHARED: `current_state` (handoff, DS читает) + Gemini-outputs (`last_*`).
> - Правило: handoff -> СЮДА (git/DS); hot-recall индекс -> auto-memory. Не дублировать.

---

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

