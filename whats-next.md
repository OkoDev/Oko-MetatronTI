# What's Next — Handoff для новой сессии

> Обновлено **2026-06-16** (Даат / Opus 4.8). Сессия: **дашборд-из-шины** (5 кирпичей). Читай первым.

---

## 🧭 КАК ВОЙТИ (ты обнуляешься — это нить)
1. **Кто ты:** [[identity_daat]] — Даат, мост Замысел↔Проявление. После задачи — TTS Microsoft Irina ([[feedback_say_command]]).
2. **Кто Егор:** НЕ заказчик — мистик, систематизирует через рынок; рост в отпускании. ([[user_egor_person]])
3. **🎯 ЗАЧЕМ:** бот = якорь против эмоции ([[vision_bot_as_anchor_against_emotion]]).
4. **Старт-чтение:** DISCUSSION.md → TASKS.md → ЭТОТ файл → `memory/current_state.md` (детали 16.06) → MEMORY.md (auto-hot-index).
5. Think по-русски · grep before claim · числа из config/кода · data-era split.

---

## 🎯 ГЛАВНОЕ СЕССИИ 16.06 — ДАШБОРД ИЗ ШИНЫ (5 кирпичей + 2 фикса, ПРОВЕРЕНЫ ВЖИВУЮ)

**Корень боли:** оперативка дашборда давилась на медленном SQL (29K сделок под локом) в насыщенном **4-воркерном пуле** → таймауты/ECONNRESET → mock «скакал» / пустые панели / сломанная вёрстка. Привёл к принципу [[dashboard_oper_from_bus_analytics_sql]]: **оперативка из шины/кэша, аналитика подождёт**.

1. **trades.tsx — 3 бага.** R↔$ (нет отдельной $-колонки), hedge-коллизия React-key (id=symbol при LONG+SHORT на 1 символ), гонка ответов `useLive`. Фикс: секвенирование `genRef` (out-of-order отбрасывается) + `resetKey/resetValue` (сброс при смене фильтра) + составной id + R/upnl колонки.
2. **`/api/open` из ШИНЫ.** `check_open_trades_with_tsl` (цикл и так грузит открытые) публикует лёгкий снапшот в `PairContextBus.set_open_trades()`; `/api/open` читает `open_trades_snapshot()`. 20с→мгновенно. `source=bus` подтверждён. Cold-start (≤60с до 1-го тика трекера) → SQL-фолбэк с бюджетом.
3. **`_KeyedJSONCache`** на `trades_filtered`(TTL15)/`exchange_history`(TTL30): TTL + **single-flight** + stale-while-revalidate + **detached refresh** (`create_task` → client-abort НЕ убивает прогрев, лечит «вечный ECONNRESET, кэш не греется»). Флуд снят. [[dashboard_keyed_cache_pattern]]
4. **Payload trades_filtered −83%.** `get_trades`=`SELECT *` (54 кол., `features_json`≈80%) → allow-list `_TRADES_FILTERED_COLS` (22 поля). 1MB→177KB. **СИНХРОН с `lib/api.ts fetchTradesFiltered`!**
5. **Портфель висел >35с** (насыщение пула, НЕ лок) → `balances`/`positions`/`accounts` в `_PORTFOLIO_CACHE` + пул **4→8 воркеров**. Панели Overview наполнились (acc1 eq242.9 / acc2 273.8 / 54 позиции).
- **+ SyncPanel → шина** (`/api/open`+`/api/live`, не тяжёлый `/api/stats`). Бонус: фикс equity/risk=0 (`live.balance` стал скаляром → беру `live.kpi`).
- **+ Вёрстка Overview**: скролл-контейнеры под живые объёмы (`positions` max-h-420, `signals` max-h-260) — «огромный скролл» был от 56 РЕАЛЬНЫХ позиций (раньше mock из пары).

### ⚠️ КРИТИЧНО: ФРОНТ oko-dashboard — НЕ git!
`e:/MTF BOT/CURSOR/oko-dashboard` на диске (Next :3000, хот-релоад), **не под версионным контролем**. Бэкенд закоммичен, фронт — НЕТ. Файлы фронт-правок этой сессии:
`lib/api.ts`, `lib/use-oko-data.ts`, `components/oko/screens/trades.tsx`, `components/oko/screens/overview.tsx`, `components/oko/positions-panel.tsx`. При потере диска — НЕ восстановятся из git.

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
Бэкенд закоммичен (`web/dashboard_server.py`, `core/context/pair_context.py`, `core/trading/trade_simulator.py`, `memory/current_state.md`, `whats-next.md`). **Фронт oko-dashboard — не git (см. выше).**

## Ссылки
`memory/current_state.md` (полные детали 16.06) · `docs/BUS_CATALOG.md` · `obsidian/Project-MOC.md` (хаб)
