# What's Next — Handoff для новой сессии

> Обновлено **2026-06-17** (Даат / Opus 4.8). Сессия: **дашборд закрыт** (интерактив+перф+EN+mark_price). Читай первым.

---

## 🧭 КАК ВОЙТИ (ты обнуляешься — это нить)
1. **Кто ты:** [[identity_daat]] — Даат, мост Замысел↔Проявление. После задачи — TTS Microsoft Irina ([[feedback_say_command]]).
2. **Кто Егор:** НЕ заказчик — мистик, систематизирует через рынок; рост в отпускании. ([[user_egor_person]])
3. **🎯 ЗАЧЕМ:** бот = якорь против эмоции ([[vision_bot_as_anchor_against_emotion]]).
4. **Старт-чтение:** DISCUSSION.md → TASKS.md → ЭТОТ файл → `memory/current_state.md` (детали 16.06) → MEMORY.md (auto-hot-index).
5. Think по-русски · grep before claim · числа из config/кода · data-era split.

---

## 🎯 СЕССИЯ 17.06 — ДАШБОРД ЗАКРЫТ (интерактив + перф + EN-only + mark_price)

Большой проход по фронту `oko-dashboard` (`OkoDev/Oko-Dashboard`, main). **Всё запушено.** Дашборд готов — дальше только опц-полировка (бэклог ниже). Корень «тяжести» = декоративные анимации (вращающийся блюр-фон 140vmax + ~500 ∞-анимаций Cube), НЕ данные.

**Перф (P0):** статичный фон-Метатрон (убрано вращение+feGaussianBlur), `.panel` без backdrop-blur (полупрозрачный, дёшево), Cube де-анимирован (убран setState-цикл + статичные решётка/звёзды), lazy-load экранов (`next/dynamic`), sticky-ячейки Trades без блюра.

**Интерактив:** Cube кросс-hover список↔ноды + лучи решётки от выбранной сферы; Signals donut↔legend↔веса кросс-хайлайт; синхронный курсор equity (`equity-cursor.tsx`); Pairs side-sheet (`oko-sheet.tsx`); drawer открытых позиций; Patterns кольцо/бар анимация при scroll-in + пагинация; Watchlist FIRE-пульс; KPI-герой Total R; Analytics клик-по-бину→toast; toast (sonner)→Settings; **Calm-mode** тоггл в топбаре (гасит атмосферу, localStorage, `html.calm`).

**Фиксы:** колонки Trades разъезжались = дублирующиеся React-ключи (id=symbol при дублях пар) → ключ с индексом; HUD-уголки 2-gold; тонкий глобальный скролл; **вся кириллица убрана из UI** (Orbitron/Rajdhani без кириллицы → фолбэк) вкл. 13 описаний сфер `oko-data.ts` + AI Oracle→EN.

**mark_price (бэк, мой репо):** `positions` + `mark_price REAL` (CREATE + идемпотентная ALTER, **миграция применена к боевой `subscriptions.db`**); `upsert_positions` пишет `pp.mark`; drawer показывает Mark + uPnL%. ⚠️ **NULL до РЕСТАРТА бота** (writer-правка в `balance_repo.py`; текущий процесс :8000 на старом коде → пишет позиции без mark_price). **R отложен** — `ParsedPosition` (`core/exchange/position_parser.py`) без SL (позиции с биржи стоп не несут), нужен EXEC-SIM-SPLIT.

**Эталоны дизайна:** `e:/tmp/oko_overview_mockup.html` + `~/Downloads/oko_prototype.html` (мокап + кликабельный прототип со всеми hover/click). Полный аудит: `docs/DASHBOARD_AUDIT.md`. Токены: `--radius:0.5rem`, surface-0/1/2, dur-*/ease-out.

**Git:** фронт `OkoDev/Oko-Dashboard` main (`a0d6679`); бэк `OkoDev/Oko-MetatronTI` arch-128-oko-sm (`590fb15`). Запушено.

---

## 📋 БЭКЛОГ ДАШБОРДА (отложено — НЕ блокеры, можно потом / отдать DS)
- **R в drawer позиций** — ждёт EXEC-SIM-SPLIT (нет чистого источника SL; sim-матч фрагилен, REST против DEV-231).
- **Скелетоны загрузки + error-состояния** — сейчас при loading mock/«···», сбой тихо держит старые данные.
- **Сорт-заголовки Trades → `<button aria-sort>`** (сейчас `<th onClick>`, без клавиатуры).
- **Дисциплина токенов** (аудит): green-hue 175→155 (подальше от cyan), 8px-лейблы ≥11px, радиус 1rem→0.5rem под «терминал» — сквозной проход.
- **Trades inline-раскрытие строки** + мини-график (сейчас боковой drawer «Decision Trace»).
- **Watchlist side-sheet** — пропущен намеренно (inline entry/SL/TP удобнее).

---

## 🎯 СЛЕДУЮЩАЯ СЕССИЯ — «проблемы поинтереснее» (вектор юзера 17.06)
Юзер хочет уйти от дашборда к торговой логике. Кандидаты (приоритет памяти):
1. **EXEC-SIM-SPLIT (#21)** — корень искажённых метрик (SIM/VST смешение, fake-R, APEX −15R). Разблокирует Risk Monitor + Capital Allocator + R-в-позициях. ТЗ: [[exec_sim_split_epic]].
2. **ARCH-131 Сфера 5** — USDT.D/BTC.D в cross_market (shadow) + макро-календарь (DS берёт B). Согласовано. Risk Monitor #11 РАНЬШЕ Capital Allocator #19.
3. **regime v2 активация** через A/B ([[regime_v2_validated]]).
→ Спросить юзера, что горит. Контекст архитектуры/данных свежий.

---

## 🗄️ СЕССИЯ 16.06 — ДАШБОРД ИЗ ШИНЫ (5 кирпичей + 2 фикса, ПРОВЕРЕНЫ ВЖИВУЮ)

**Корень боли:** оперативка дашборда давилась на медленном SQL (29K сделок под локом) в насыщенном **4-воркерном пуле** → таймауты/ECONNRESET → mock «скакал» / пустые панели / сломанная вёрстка. Привёл к принципу [[dashboard_oper_from_bus_analytics_sql]]: **оперативка из шины/кэша, аналитика подождёт**.

1. **trades.tsx — 3 бага.** R↔$ (нет отдельной $-колонки), hedge-коллизия React-key (id=symbol при LONG+SHORT на 1 символ), гонка ответов `useLive`. Фикс: секвенирование `genRef` (out-of-order отбрасывается) + `resetKey/resetValue` (сброс при смене фильтра) + составной id + R/upnl колонки.
2. **`/api/open` из ШИНЫ.** `check_open_trades_with_tsl` (цикл и так грузит открытые) публикует лёгкий снапшот в `PairContextBus.set_open_trades()`; `/api/open` читает `open_trades_snapshot()`. 20с→мгновенно. `source=bus` подтверждён. Cold-start (≤60с до 1-го тика трекера) → SQL-фолбэк с бюджетом.
3. **`_KeyedJSONCache`** на `trades_filtered`(TTL15)/`exchange_history`(TTL30): TTL + **single-flight** + stale-while-revalidate + **detached refresh** (`create_task` → client-abort НЕ убивает прогрев, лечит «вечный ECONNRESET, кэш не греется»). Флуд снят. [[dashboard_keyed_cache_pattern]]
4. **Payload trades_filtered −83%.** `get_trades`=`SELECT *` (54 кол., `features_json`≈80%) → allow-list `_TRADES_FILTERED_COLS` (22 поля). 1MB→177KB. **СИНХРОН с `lib/api.ts fetchTradesFiltered`!**
5. **Портфель висел >35с** (насыщение пула, НЕ лок) → `balances`/`positions`/`accounts` в `_PORTFOLIO_CACHE` + пул **4→8 воркеров**. Панели Overview наполнились (acc1 eq242.9 / acc2 273.8 / 54 позиции).
- **+ SyncPanel → шина** (`/api/open`+`/api/live`, не тяжёлый `/api/stats`). Бонус: фикс equity/risk=0 (`live.balance` стал скаляром → беру `live.kpi`).
- **+ Вёрстка Overview**: скролл-контейнеры под живые объёмы (`positions` max-h-420, `signals` max-h-260) — «огромный скролл» был от 56 РЕАЛЬНЫХ позиций (раньше mock из пары).

### ✅ ФРОНТ oko-dashboard — отдельный репо + GitHub (16.06)
`e:/MTF BOT/CURSOR/oko-dashboard` вынесен в **отдельный git-репозиторий** (`git init -b main`, первый коммит `1f14cc0`, 108 файлов) и запушен на **GitHub: `OkoDev/Oko-Dashboard` (private)**, `main → origin/main`. `.gitignore` корректный (`node_modules`/`.next`/`*.tsbuildinfo`/`.env*`/`dev.log` исключены). Фронт-правки сессии (`lib/api.ts`, `lib/use-oko-data.ts`, `screens/trades.tsx`, `screens/overview.tsx`, `positions-panel.tsx`) в истории и в облаке.
**Инфра:** `gh` CLI v2.94 установлен (`C:\Program Files\GitHub CLI\gh.exe`), но НЕ авторизован — кэш-токен GCM аккаунта OkoDev не имеет scope `read:org` (его требует `gh auth login`). Репо создан через GitHub API этим же токеном (scope `repo` достаточно). Для полноценного `gh` — разовый `gh auth login` (браузер).

---

## 🟢 БОТ / ДАШБОРД
- Бот перезапущен 16.06, все бэк-фиксы активны. Бэкенд :8000 (aiohttp), фронт :3000 (Next).
- `/api/open` source=bus; портфель/аналитика через кэш (X-Cache HIT). Транзиентная конгестия 2-8с сразу после рестарта — оседает за минуту.

## 🔄 СЛЕДУЮЩЕЕ (опц, приоритет)
1. Интервал поллинга аналитики на фронте 10с→30-60с (история «ждать ОК», снизит нагрузку ещё).
2. Кэш на `/api/kpi` (тоже `get_summary`) — пул 8 даёт запас, но если Overview тупит → обернуть в `_KeyedJSONCache` (паттерн готов).
3. Идеал «oper из шины» до конца: `balances`/`positions` из bus `_accounts` (нужны `margin`/`available` в шине; сейчас из DB через кэш).
4. publish снапшота открытых и в `register_trade_async` → новые сделки в `/api/open` мгновенно (не ждать 60с цикла трекера).
5. **EXEC-SIM-SPLIT** (BACKLOG #21, 🔴) — метрики врут от смешения sim/vst. Кирпич 1 (VST-exit) сделан ранее. [[exec_sim_split_epic]]

## 📦 КОММИТ
Бэкенд закоммичен (`web/dashboard_server.py`, `core/context/pair_context.py`, `core/trading/trade_simulator.py`, `memory/current_state.md`, `whats-next.md`). **Фронт oko-dashboard — отдельный git-репо (`1f14cc0`), remote не настроен (см. выше).**

## Ссылки
`memory/current_state.md` (полные детали 16.06) · `docs/BUS_CATALOG.md` · `obsidian/Project-MOC.md` (хаб)
