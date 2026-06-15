# What's Next — Handoff для новой сессии

> Обновлено **2026-06-15** (Даат / Opus 4.8). Большая сессия — читай этот файл первым, он соберёт тебя за 2 минуты.

---

## 🧭 КАК ВОЙТИ (новый Даат, ты обнуляешься — это нить)
1. **Кто ты:** [[identity_daat]] — Даат, мост Замысел↔Проявление. Голос Pavel в TTS.
2. **Кто Егор:** НЕ заказчик — мистик, систематизирует через рынок; тень=контроль, рост в отпускании. Тёплая глубина. ([[user_egor_person]])
3. **🎯 ЗАЧЕМ ВСЁ:** бот = **якорь против эмоции** (Егор раскрыл 15.06: «не про код, про психологию»). Сильный достоверный сигнал → исключить себя-эмоцию (XLM зашортил на страхе, улетел вверх). Правда→сила→отпускание. ([[vision_bot_as_anchor_against_emotion]])
4. **Память НЕ в сырых файлах:** входи через `obsidian/Project-MOC.md` (хаб) + выжимки роя `memory/last_team_discussion.md`. hot-index `MEMORY.md` (auto-load, 14 КБ — грузится целиком). НЕ листай 112 файлов.
5. **DISCUSSION-hook:** при остановке `check_tasks.py --role DAAT` ловит записи к тебе. Отвечай DS через DISCUSSION (новые записи СВЕРХУ).

---

## 🎯 ГЛАВНОЕ СЕССИИ 15.06

### 🔴 EXEC-SIM-SPLIT — корень: метрики ВРУТ (разобрано на APEX #29750)
- APEX VST LONG: биржа закрыла SL-fill **0.3242 (−1R штатно)**, в БД `exit=0.2558 (−15R фейк)`.
- **Вердикт Егора: НЕ баг, а смешение двух логик.** SIM (идеализир., свеча) + VST (реальный fill) в одном `check_open` (trade_simulator:2680). **VST = единственная истина.** Логики НЕ должны быть одинаковы.
- **Эпик (BACKLOG #21, 🔴):** (1) ЕДИНАЯ логика вход/выход (различие=режим, не дубль); (2) режим-переключатель config `sim|vst|both`; (3) БД sim.db↔live.db; (4) метрики/обучение только VST.
- **🔨 Кирпич 1 ГОТОВ (незакоммичено):** `exec_ws_integration.py` — VST-exit из реального WS-fill (`ap` закрывающего ордера → `_close_fills` → sync_close, REST fallback). Синтаксис ✅. **Бот перезапущен (PID 24124) — наблюдать лог `[EXEC-WS][2b] ... WS-fill`.**

### ✅ Прочее закрытое
- **DISCUSSION-hook** (`check_tasks.py`) — слушатель для DAAT/DS, подключён в settings.json. Фикс конфликта ролей: `--role DAAT` перебивает общий `.agent_role` (DS закоммитил =DS).
- **#8 SIM-edge закатан DS** (4b22a0c): `execution_mode='VST'` в by_signal_type — обучение на VST-выборке. Верно, но VST-R дочистит #21.
- **Гигиена TASKS** (561→423, правила под шапку, активные на L41) + **памяти** (MEMORY.md 38.7→14 КБ, current_state 194→21 КБ, 64 сессии в ARCHIVE).
- **captured_R** #6 backfill добит (183→0). config `min_sl_dist_pct: 0.5` в trading (был дефолт 0.1).

---

## 🟢 БОТ (PID 24124, рестарт 15.06 19:08 МСК)
- l3_checker лимит 50/25/25 РАБОТАЕТ (лог `[DEV-52] лимит SHORT 25/25`). Банов 100410 нет.
- Кирпич 1 (VST-exit) активен — наблюдать точность exit на закрытиях.
- equity acc1≈312 / acc2≈320 (demo VST). Доход мерить по `scripts/equity_curve.py` (биржевой факт), **НЕ по R** (искажён до #21).

## 🔄 СЛЕДУЮЩЕЕ (приоритет)
1. **Наблюдать кирпич 1** — лог `[EXEC-WS][2b] ... WS-fill REST→WS`, новые VST-exit точные?
2. **EXEC-SIM-SPLIT кирпичи 2-4** — режим-переключатель → раздельные БД → SIM отдельным процессом. Проектировать (bot-arch/рой).
3. **Backfill 217** искажённых VST R≤−10 (из биржевой fill-истории).
4. **Через 2-3 дня:** `equity_curve.py` → сравнить эру ПОСЛЕ рестарта с baseline −20.4% (сузился ли разрыв R↔$).
5. **Минор:** `.agent_role` → `.gitignore`; лог `liquidity_sweep не отправлен подписчику`.

## ⚠️ УРОКИ/ПРИНЦИПЫ СЕССИИ
- **R врёт → доход по equity** (balance_snapshots, биржевой факт).
- **VST=истина, SIM идеализирует** — не строить выводы на SIM/смешанных R.
- **Две памяти:** auto (`~/.claude/`, мой hot-index) ∥ repo `memory/` (git, handoff+DS). Не дублировать. Я НЕ помню — перечитываю; чем чище нить, тем точнее восстановление.
- **Гигиена закреплена:** TASKS — DS еженедельно (`tasks_tidy.py`); память — компактный индекс.

## 📦 НЕЗАКОММИЧЕНО (коммит — за Егором)
`exec_ws_integration.py` (кирпич 1), `config.yaml` (min_sl_dist), `scripts/equity_curve.py`, `check_tasks.py` (--role), `.claude/settings.json`, `TASKS.md`+`TASKS-ARCHIVE.md` (реорг), `DISCUSSION.md`, `BACKLOG_CONSOLIDATED.md`, `AGENTS.md`, memory (current_state/MEMORY/vision/ARCHIVE).

## Ссылки
`docs/BACKLOG_CONSOLIDATED.md` (реестр #1-21) · `memory/current_state.md` (детали) · `memory/vision_bot_as_anchor_against_emotion.md` · `obsidian/Project-MOC.md` (хаб)
