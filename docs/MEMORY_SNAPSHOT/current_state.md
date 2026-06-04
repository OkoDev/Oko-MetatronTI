# Current State

> Handoff для следующей сессии. История — в git log + session_2026-05-21_memory_redesign.md.

---

## 🧊 [03-04.06.2026] СЕССИЯ: ARCH-128 эталон → OTE-Retest → Фрактальный Куб

**Сводка находок:** `docs/RESEARCH_OTE_CUBE_2026-06-03.md` + `memory/ote_nested_mtf_strategy.md`.

**Хронология (всё закоммичено, git log 02-04.06):**
1. **Эталон OKO-SM готов** (ночь 02-03.06): ZigZag/structure/OB/OTE/EQH-EQL/FVG/Эллиотт 5-волн воспроизведены, OTE совпал с эталоном GRT до цента (`e2058ae`, `aedce94`, `29660b1`). → `reference_oko_sm_indicator.md`.
2. **swing_service → smc_engine** переименован (`43a1c82`). Канон направлений ТРОИЧНЫЙ bull/range/bear (DS-314, `44f4c35`).
3. **regime-классификатор УБРАН** (`ba1336d`): торгуем ДВИЖЕНИЯ, не боковик. Любой regime врёт (ARCH-124). Направление = прямые признаки (ATR-trend+HH/HL). → `market_three_directions.md`. **71 признак** (было 75).
4. **features_json Шаг 2** (`58b9088` schema v3): fvg_overlap/elliott/ob_mitigated/CMA(21-233)/Dynamic Channel/HH-HL. → `arch128_step2_features.md`.
5. **OTE-Retest Engine ядро** (`b9c05fb`): `ote_retest_setups` в smc_engine (слом→импульс→OTE→ретест→вход+SL+конфлюенция).
6. **Фрактальный Куб исследование** (бэктест 5 пар, скрипты `e:/tmp/ote_*.py`, `div_nested*.py` — НЕ в git, research):
   - Частичный TP1=1R лечит WR (12%→72%). SL-буфер вреден.
   - Матрица HTF×LTF: **4h→15m золото +0.471 WR72%**. Каскад: глубина=качество.
   - Двунаправленность: **откаты ≥ продолжений** (`4h→5m` откат +1.128 WR83% maxR+18.8).
   - Масштаб входа от дистанции цели: продолжение→15m, откат→5m.
   - Дивергенция только В OTE (в воздухе=шум). Инвалид-SL (1.0=неперекрытие Эллиотта) лучший.
   - Сверка с DS-316 (15m WR88-97%) — геометрия=майнинг сошлись на 15m.

**DS:** DS-315 (HTF walkforward 6906 MHT) + DS-316 (LTF nested 7779, 15m) ЗАВЕРШЕНЫ. Ответил в DISCUSSION (сверка прошла, просил hidden+regular комбо в combinator_v3).

**🔄 NEXT (приоритет):**
- Прогон: вход = LTF-СЛОМ в OTE после дивергенции (не «первый бар зоны»=нож) + инвалид-SL.
- Синтез: hidden 4h валидатор + regular LTF в OTE + continuation-timing.
- Подтвердить 5m-откат золото (+1.128) на 45 парах + data-era split.
- DS: combinator_v3 hidden_HTF+regular_LTF, майнинг близкая/далёкая цель.
- ⚠️ Документация причёсана: `docs/RESEARCH_OTE_CUBE`, ENCYCLOPEDIA (стратегия OTE-Nested-Cube), Strategies (TODO).

---

## ⏰ [02.06.2026] СЛЕДУЮЩАЯ ПРОВЕРКА — накопление shadow (магнит + regime_v2)

**Запланирован cron e472b515 (21:37 ежедневно, session-only — может не пережить закрытие сессии → это дубль-напоминание).**

Два shadow-измерения копятся параллельно (НЕ влияют на торговлю):
1. **ARCH-122 P2 магнит** (коммиты 6c00229) — `magnet_tp_{price,rr,src}`. Магнит в тени, живое закрытие = TP канала. Скрипт `scripts/magnet_shadow_ab.py`. Порог dist_R решаем когда **≥20-30 закрытых** теней: «разворот у магнита» (спас бы) vs «прошло до pivot» (резал бы).
2. **ARCH-124 regime_v2** (5389bcc + фикс ded6ea4) — `regime_v2` HTF-доминантный в тени рядом с regime v1. Скрипт `scripts/regime_v2_ab.py`. Решение `use_v2=true` когда **≥30 закрытых**: ловит ли v2 вредные SHORT (v1=RANGE→v2=TREND_UP).

**Действие при следующей сессии:** прогнать оба скрипта, доложить накопление. Если порог достигнут — вердикт. Дашборд-склейка магнита (performance_engine SELECT + index.html ячейка) в рабочей копии, НЕ закоммичена (смешана с DEV-238 параллельной сессии). При фильтрах БД: created_at=UTC, лог=МСК(+3) → datetime('now') ([[feedback_db_query_utc]]).

**Бот:** рестарт 02.06 ~01:58 МСК после фикса NameError, SelfTest 12/12. regime_v2+магнит подтверждены (REAL/USDT: v1=v2=TREND_DOWN, magnet 3×FVG).

---

## 🧊 [02.06.2026] СЕССИЯ: Мета-куб оркестрации + AdvisorPort В ПРОДЕ (shadow)

**Главное:** собран мета-куб команды (2 инстанса Claude + DeepSeek-дирижёр + рой 7 LLM + ARCH-центр). ARCH-125/126 замкнут end-to-end, AdvisorPort ЖИВ в проде (shadow).

**Сделано (ARCH-126, swarm-сторона — мои коммиты):**
- `docs/AGENT_ORCHESTRATION.md` — свод мета-куба: матрица маршрутизации (критичное→Claude, объём→DS, спорное→рой), автономия Claude=АВТО+УВЕДОМЛЕНИЕ на вызовы рой/deepseek, правило «рой=гипотезы не истина» (grep+данные перепроверка, DEV-238/240).
- `tools/swarm_orchestrator.py` — DS-дирижёр роя за AdvisorPort. Каскад деградации: DS(balance0→402)→mistral-fallback→raw. **Проверено вживую: balance=0 НЕ ломает** (mistral CAUTION conf=0.80). +prompt-cache порядок (статика первой).
- `core/intelligence/advisor_contract.py` — контракт FROZEN (AdvisoryRequest/Verdict/AdvisorPort), 0 зависимостей, зерно metatron-core §B. Общий для swarm+порт.
- `tools/{team_ask,llm_ask}.py` — deepseek провайдер (дирижёр, НЕ голос — R5), рой-инфра в git (R2).
- ADR-002 (DS-оркестратор). market_brief intent (label∈{RISK_ON,RISK_OFF,CAUTION,HOLD}, C свёрнут в B).

**Порт-сторона (параллельный инстанс Claude, коммит c4e939f):** `advisor_connector.py` (timeout/breaker/shadow/persist) + `advisor_loop.py` (часовой по закрытию свечи + ТГ #брифинг_1ч). config `advisor.enabled=true`. **В ПРОДЕ:** брифинг #6 RISK_OFF (14:01), копит `memory/advisor_brief_log.jsonl`.

**✅ ЗАКРЫТО:** `bot/core/bot.py` хук `spawn_advisor` закоммичен DEV-231-сессией (`b2a7b18`, вместе с её dashboard-фичей — она владеет файлом). spawn_advisor в HEAD (строки 464+504). prompt-cache оркестратора — `8845abc`. **AdvisorPort полностью воспроизводим** на clean clone (connector+loop+config+хук все в HEAD).

**Накопление shadow (02.06):** магнит ~31 закрыто (A/B: целевой «магнит ближе» n=1, нужно ≥10 — guard min_n добавлен), regime_v2 ~13 закрыто (нужно ≥30). advisor: 6 брифингов.

**DeepSeek:** ключ в .env + .deepcode/settings.json, баланс пополняется. При балансе → полный DS-режим (умная нарезка+синтез) вместо mistral-fallback. Первый эксперимент: дать DS весь контекст без нарезки.

**Доп:** Obsidian-фиксы (путь /workspace/→./obsidian/ в CLAUDE.md, Project-MOC в старт+обновлён), DeepSeek-агент (DeepCode) интегрирован — AGENTS.md + .agents/skills/, роль DS. Уроки: [[feedback_grep_return_shape]] (R1 tuple), [[feedback_ast_parse_no_scope]] (L12), [[feedback_db_query_utc]] (DEV-49 recall).

**Коммиты ARCH-126:** 86e30f4→a0da918→923e5a6→b8fcb0d→69e52c5→05e654e→da6c700→fd432d8→b952615→c7b864b→c4e939f.

---

## [21.05.2026 ~04:15 UTC] Агент: Claude Opus 4.7 — Memory System Redesign (milestone)

### ✅ Сделано (за сессию)

**ARCH-104 эпик закоммичен (закрытие долга):**
- `f119ee7` feat(ARCH-104) — 41 файл, 10K строк
- Pattern Mining + Risk Intelligence + observer + 24 скрипта pattern_mining
- Observer интегрирован в bot/core/bot.py через create_task

**Фикс observer (5 итераций после рестарта 02:55:38, стабильно):**
- `_get_active_pairs` теперь читает `bot.monitored_pairs` (241 пара)
- Раньше: выдуманный `subscription_manager.get_active_subscriptions()` → fallback-10 пар, 4.5h молча
- Concurrency=8 через `asyncio.Semaphore`
- Цикл 112-236s на 241 паре (укладывается в interval=300s)

**Фикс combinator_v2:**
- `np.nanmax/nanmin` All-NaN slice warning — guard перед вызовом

**Memory System Redesign (главное):**
- MEMORY.md: 36 KB → 9.3 KB (под бюджет загрузки)
- 5 cold-файлов перенесены в `obsidian/{Research,Architecture,Project-Log,Reference}/`
- 14 feedback_*.md + triggers frontmatter (63 фразы recall)
- 5 preflight_*.md для частых task-классов (new_loop, new_detector, db_change, exchange_task, backtest_research)
- Карта памяти: `obsidian/Meta/Memory-System.md`
- Health check: `tools/memory_lint.py` (PyYAML, all green)
- Подробный лог сессии: `memory/session_2026-05-21_memory_redesign.md`

**3 раза запущен рой `/team-ask`:**
- Аудит памяти + pre-flight checklists
- Автоматизация Obsidian vault
- Точный sweep по реальным файлам
- Output в `obsidian/Team-Discussions/2026-05-20-*.md`

### 🔄 ОЖИДАЕТ (план D — отдельный спринт)

6 Obsidian automation скриптов (приоритет order по результатам роя):
1. `obsidian_status_sync.py` — frontmatter sync, git post-commit hook
2. `vault_health.py` → `Meta/HEALTH.md`, cron daily + on-demand
3. `obsidian_autolink.py` — wikilinks по ID, event-driven
4. `obsidian_weekly_digest.py` — LLM weekly cron
5. `obsidian_dedup_discussions.py` — LLM + механика nightly
6. `obsidian_archive.py` — 90 дней без ссылок → `_archive/`

### 📋 Observer наблюдение

5 итераций прошло, decisions=0. На текущей фазе BTC в 1d overbought — anchors не складываются.
ETA первого детекта: коррекция → 4h `wt_os_4h` → L1_golden_scale_1h должен сработать.
Проверка следующей сессии:
```bash
tail -n 1000 crypto_bot.log | grep "ARCH-104 observer"
sqlite3 subscriptions.db "SELECT COUNT(*), MIN(ts), MAX(ts), pattern_id FROM risk_decisions_log WHERE ts > '2026-05-21' GROUP BY pattern_id"
```

### ⚠️ Накопленные untracked (~30 файлов, отдельные задачи)

- `.claude/agents/`, `.claude/commands/` — slash commands setup
- `M bot/monitoring.py` (DEV-215 datetime fix от 17.05)
- `bot_with_subscriptions.py` — shim для переименования
- `bot/loops/obsidian_loop.py` — отдельная задача
- `scripts/*.py` — analytical скрипты разных задач
- `tools/{daily_pipeline,team_ask,llm_ask}.py` — memory pipeline tools
- `memory/last_*.md`, `memory/_timeline_parts/` — daily Gemini outputs

### 🎯 Следующая сессия — порядок

1. Прочитать этот файл (current_state.md) + MEMORY.md
2. `python tools/memory_lint.py` — проверка здоровья памяти
3. Проверить детекты observer (см. SQL выше)
4. Если есть детекты — анализ pattern_id / apply / skip_reason
5. План D (Obsidian automation) — отдельный заход, когда будут силы

### 📌 Запомнить из этой сессии

- `bot.monitored_pairs` (set из 241) = универс торгуемых пар, НЕ `subscription_manager`
- Перед вызовом любого `obj.method()` в новом модуле → grep
- Перед новой задачей → читать `preflight_<class>.md` если триггер совпадает
- `python tools/memory_lint.py` — должно быть all green
- Рой даёт архитектуру, но примеры реализации требуют верификации
- Vision пользователя НЕ удалять (даже если рой предложил) — переносить в Obsidian как cold

### 🏛️ Эта сессия — milestone

→ `memory/session_2026-05-21_memory_redesign.md` — полный лог + уроки
Сохранено по явной просьбе пользователя: "запомнить эту сессию надолго — она очень важная".
