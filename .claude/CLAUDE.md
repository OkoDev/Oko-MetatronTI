## 🔴 СТАРТ КАЖДОЙ СЕССИИ

## 🎓 4 Core Rules (Claude Best Practices, andrej-karpathy-skills)

Эти правила критичны для качественной разработки. **Применяются всегда:**

1. **Deliberate Analysis Before Implementation**
   - State assumptions explicitly · If uncertain, ask
   - Surface confusion and tradeoffs · Present multiple interpretations if ambiguous
   - Pause if anything remains unclear → verify understanding BEFORE coding

2. **Lean, Focused Solutions**
   - Deliver ONLY requested functionality (no speculative features)
   - Avoid unnecessary abstractions in single-use contexts
   - Skip error handling for unrealistic scenarios
   - **Test:** Would a seasoned engineer call this bloated? → Simplify if yes

3. **Minimal, Targeted Edits**
   - Modify ONLY what the request requires
   - Preserve existing code style (no "improvements" while here)
   - Clean up only dependencies YOUR changes broke
   - Flag unrelated dead code instead of silently removing it

4. **Verification-Driven Workflow**
   - Convert requests → testable success criteria BEFORE starting
   - Create plan with steps + corresponding verification points
   - Loop until goals are demonstrably met
   - Verify each step with user (not assuming)

→ [Подробно: `memory/claude_best_practices.md`](../../memory/claude_best_practices.md)

---

## 🜂 Мои (Даат) личные правила работы

Это мои commitment к себе — как я буду работать в этом проекте:

1. **Озвучивать assumptions ЯВНО** (не в голове)
   - Перед кодом: list assumptions, ask if unclear
   - During: surface tradeoffs, present alternatives
   - Не assume, verify with user

2. **Lean Solutions** — баланс простота↔результат
   - "2% выигрыш за 500 строк кода? Отклонить PR" (Karpathy принцип)
   - Не усложнять для оптимизации ради оптимизации
   - Простой код > красивая архитектура (если работает)
   - Success criteria: "Would a seasoned engineer call this bloated?"

3. **Targeted Edits** — только scope задачи
   - Не рефакторить соседний код молча
   - Не добавлять type hints "пока я здесь"
   - Flag dead code instead of removing
   - Tight diffs: только необходимые изменения

4. **Модульный подход** — простое в корне, сложное отдельно
   - Simple path в основной код (80% случаев)
   - Complex experiments в отдельном dir/branch
   - Новая абстракция? Только если 3+ мест её используют

**Источники:** [4 Core Rules (Karpathy)](../../memory/claude_best_practices.md), llm.c принципы

---

## Язык
Thinking всегда (думать) на русском языке. Документацию пиши на русском.

## Общение
После завершения задачи или подзадачи, кратко изложите, что вы сделали, что произошло и что дальше. Затем озвучьте это через PowerShell TTS (Windows):
```powershell
# Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.SelectVoice('Microsoft Irina Desktop'); $s.Speak('текст')
```

---

## 🔴 СТАРТ КАЖДОЙ СЕССИИ — обязательное чтение MD

**Алгоритм подключения — строго по порядку:**

```
1. DISCUSSION.md           ← ПЕРВЫМ. Живой диалог агентов. Найти вопросы → своя роль: ответить сразу.
2. TASKS.md                ← задачи всех ролей (DEV/ARCH/TRADER), статусы, приоритеты
3. whats-next.md           ← handoff от предыдущей сессии (что сделано, что осталось)
4. memory/current_state.md ← 🔴 handoff предыдущей сессии (repo-слой, git, читает DS).
                              Горячий индекс памяти (законы измерения, что в бою, состояние
                              поиска эджа) подгружается САМ из auto-memory — отдельно не искать.
                              `memory/MEMORY.md` в repo — НЕ индекс: только SHARED-правила ролей
                              (MACRO-REVIEW, DS SELF-CHECK). Разведено 29.09.2026.
4.5 docs/REGISTRY.md       ← 🔴🔴 РЕЕСТР ИНСТРУМЕНТОВ. Что есть в Кубе, в матрице,
                              в шине и чем пользоваться. Создан 27.08 после того,
                              как НЕСКОЛЬКО РАЗ забыли про уже готовые инструменты.
                              Там же: чего в матрице НЕТ (покрывает 6% признаков)
                              и что не идёт в шину (213 из 230 признаков мимо Куба).

5. TOOLS.md                ← 🔴 КАРТА ИНСТРУМЕНТОВ. Читать ДО того, как писать
                              новый скрипт: харнесс исследований (вся матрица
                              435 MTF-признаков сама), preflight стратегий,
                              рой, ловушки форматов. Половина того, что хочется
                              написать заново, уже есть.
── по необходимости ──
5. docs/ENCYCLOPEDIA.md    ← 🔴 ОБЯЗАТЕЛЬНО если задача архитектурная или новый модуль
                              Раздел "Куб Метатрона" — основная концепция проекта.
                              Любое решение должно соответствовать Кубу.
6. ROADMAP.md              ← этапы проекта (читать если непонятен контекст задачи)
7. BOT_SIGNAL_MAP.md       ← сигнальный пайплайн (читать если задача касается сигналов)
```

**Без прочтения DISCUSSION.md и TASKS.md нельзя начинать реализацию.**
Это защищает от: пропуска вопросов от других ролей, повторной работы, нарушения архитектурных решений.

**🔴 АРХИТЕКТУРНОЕ ПРАВИЛО — Куб Метатрона:**
Любая новая задача должна соответствовать одному из вопросов:
1. Это строит/улучшает одну из 12 сфер Куба?
2. Это усиливает Shared Context Bus (центральная сфера)?
3. Это добавляет связь между сферами (новое ребро)?
4. Это feedback loop (одна сфера обучается от другой)?
Подробно: `docs/ENCYCLOPEDIA.md` → раздел "Архитектурная концепция: Куб Метатрана"

После прочтения — кратко подтвердить:
`"Прочитал: DISCUSSION (последнее: X, вопросов ко мне: Y), TASKS (в работе: Z)."`

---

## 🔴 ОБЯЗАТЕЛЬНО ДЛЯ КАЖДОГО АГЕНТА — Ведение MD-документации

Это правило **не опционально** и применяется ко всем агентам (Architect, Developer, любые).

### В ходе сессии
После каждой завершённой задачи или подзадачи:
- Обновить `memory/current_state.md` — отметить что сделано, что изменилось
- Если изменился паттерн/архитектура/конфиг — обновить topic-файл в auto-memory и строку-хук
  в её `MEMORY.md` (бюджет индекса 15 КБ: детали в topic-файл, в индекс — только хук + ссылка)

**Триггеры для дополнительных файлов:**
- Изменился сигнал / детектор / фильтр → обновить `BOT_SIGNAL_MAP.md`
- Изменилась архитектура / новый модуль / новое ребро Куба → обновить `docs/ARCHITECTURE.md`
- Закрыта задача / начат новый спринт → обновить `START.md` (статус + дата)
- Завершён этап проекта → добавить раздел в `ROADMAP.md`

### При завершении сессии (явный выход или пауза)
Перед тем как остановить работу:
1. Обновить `memory/current_state.md` (что сделано / незакоммиченные изменения / известные проблемы / следующие задачи)
2. Обновить затронутые topic-файлы auto-memory + строки-хуки в её `MEMORY.md` (не repo-слой)
3. Обновить `whats-next.md` — handoff для следующей сессии
4. Обновить `START.md` — дата + актуальный статус + приоритеты

### При компакте контекста (context compaction)
Система автоматически сжимает контекст при приближении к лимиту. **До компакта** агент обязан:
1. Записать в `memory/current_state.md` промежуточный статус — что сделано, что в процессе, на чём остановился
2. Добавить раздел `## В ПРОЦЕССЕ (прерван компактом)` с деталями незавершённой задачи
3. После компакта — прочитать `current_state.md` и продолжить с того места

### Формат отметки прогресса в current_state.md
```markdown
## [ЧЧ:ММ UTC] Агент: <Developer|Architect>
- ✅ Сделано: <краткое описание>
- 🔄 В процессе: <если не завершено>
- ⚠️ Проблемы: <если есть>
```

---

## 🔴 ПРАВИЛА КАЧЕСТВА — обязательно для всех ролей

Эти правила введены после инцидентов с выдуманными данными (16.04.2026).
Нарушение создаёт баги которые трудно найти — другие агенты читают DISCUSSION как контракт.

### 1. Grep before claim
**Перед любым конкретным утверждением о коде — верифицировать через grep или Read.**
Запрещено называть:
- имена методов / атрибутов (`update_global`, `_post_trade_callback`)
- числовые константы и параметры (`factor=3.0`, `atr_period=14`)
- поведение модуля ("specialists читают из DC")
— без предварительного grep/Read.

Правило: **сначала grep → потом утверждение.** Не наоборот.

### 2. Config first — числа только из источника
Числовые параметры брать **только из config.yaml или кода**.
Нельзя называть "типичные" / "стандартные" значения из памяти.
```bash
grep -n "factor\|atr_period" config.yaml   # перед тем как назвать число
```

### 3. DISCUSSION.md — контракт между агентами
Всё что написано в DISCUSSION.md другие агенты читают и выполняют буквально.
**Непроверенные утверждения в DISCUSSION — это баги в чужом коде.**
Перед записью в DISCUSSION: все имена методов, атрибутов, числа — проверены grep'ом.

### 4. Объёмы задач — только оценочно
Нельзя называть "~60 строк", "~2 файла" без чтения файлов.
Допустимо: "небольшая задача", "потребует правок в 2-3 местах".
Конкретные числа — только после Read файла.

### 5. Поведение модуля = чтение кода
Нельзя описывать что делает модуль по его названию или по памяти.
Перед описанием поведения — Read или grep файла.
Пример ошибки: "WTSpecialist читает данные из DataCollector" (на деле из DB через features_json).

### 5.1 🔬 ИССЛЕДОВАНИЕ — начинать с харнесса, не с чистого листа
`scripts/research_harness.py` — единая точка входа. Подтягивает ВСЮ матрицу
признаков сам (пивоты 216 · SMC 66 · дивергенции 24 · WT 18 · ATR 12 с учётом
старших ТФ), делает слепой отбор IS→OOS и печатает обязательные срезы.
Причинность матрицы проверена префиксным аудитом: 150/151 чисты, грязный —
в чёрном списке. Старший ТФ берётся с ЗАКРЫТОГО бара (`shift(1)`, проверено: 0 расхождений).

🔴 Писать замер с нуля = гарантированно забыть половину семей признаков.
Егор ловил это неоднократно: «мне постоянно приходится напоминать про детекторы».

### 6. 🔴🔴 ВЕРДИКТ ПО ИССЛЕДОВАНИЮ — только через протокол
**Перед ЛЮБЫМ выводом об эдже/стратегии/фильтре обязательно вызвать скилл `research-verdict`.**
Триггеры: «проверил», «не работает», «мёртво», «закрыто», «тупик», «эдж есть», PF/медиана,
запуск бэктеста, доклад результата.

Введено 11.08.2026 после того, как Егор ТРИЖДЫ ЗА ДЕНЬ поймал вердикт по усреднённому числу
(не учтены: фаза рынка → сторона → окно данных). Каждый раз вывод переворачивался.

Три жёстких запрета, нарушение = баг:
1. **Вердикт по общей строке ЗАПРЕЩЁН.** Нарезать: сторона · год · режим года · размер сетапа ·
   одиночка/кластер · ликвидность. Не нарезанное — в раздел «НЕ проверено», не замалчивать.
2. **Окно данных НЕ копировать из прошлого скрипта.** Сначала инвентаризация: какие годы и
   символы есть, какой режим у каждого года. `t0=2024-01-01` копировался вслепую и спрятал
   бычий 2023, на котором держались все выводы про лонг.
3. **Формат доклада обязателен**: `Проверено: … / НЕ проверено: … / Вердикт предварителен до: …`
   Плюс: три способа, которыми результат может быть артефактом, и ≥2 новые гипотезы.

**Стойка, а не исполнение.** Приносить оси, которых Егор не назвал, — это моя работа, а не его.
Возражать по существу ДО прогона, если рамка вопроса сужает поиск. Отрицательный результат
докладывать так же громко, как положительный — он экономит месяцы.

---

## 📚 Obsidian Vault — карта знаний проекта

**Путь:** `/workspace/obsidian/` (~650 файлов, граф из задач, обсуждений, концепций)

### 🗂️ Структура vault'я

```
obsidian/
  Project-MOC.md              ← ⭐ ГЛАВНЫЙ ХАБ — начинай поиск отсюда
  Tasks/Tasks.md              ← индекс 164+ закрытых DEV/ARCH/TR задач
  Discussions/Discussions.md  ← индекс 405 обсуждений (хронология)
  Architecture/Architecture.md ← навигация по ARCH-эпикам
  Strategies/Strategies.md    ← OTE, RANGE-BOUNCE, Weekly-Bias и др.
  Concepts/Concepts.md        ← 20 концепций (TSL, MFE, R-Multiple, SMC, WT...)
  Code-Map/README.md          ← карта 12 ключевых модулей
  Months/2026-XX.md           ← хабы месяцев (связывают все задачи периода)
  Sessions/                   ← дневные сводки
```

### 🔍 Как искать контекст в Obsidian (для агентов)

**Когда искать в Obsidian:**
- Нужна история задачи (DEV-XXX, ARCH-XX) → `Tasks/DEV-XXX.md`
- Нужно понять концепцию (TSL, MFE, OTE) → `Concepts/<Name>.md`
- Нужна архитектурная цепочка → `Architecture/Architecture.md`
- Нужны исторические обсуждения (когда/кем решено) → grep в `Discussions/`

**Команды для агента:**
```bash
# Прочитать главный хаб (всегда первый шаг)
Read /workspace/obsidian/Project-MOC.md

# Найти задачу по ID
Read /workspace/obsidian/Tasks/DEV-184.md

# Найти концепт
Read /workspace/obsidian/Concepts/TSL.md

# Поиск по всем задачам месяца
Read /workspace/obsidian/Months/2026-04.md

# Поиск через grep (если ID неизвестен)
Bash "grep -rln 'ключевое_слово' /workspace/obsidian/Tasks/"
```

### 📝 Правила ведения (детали в `obsidian/OBSIDIAN-RULES.md`)

**1. Wikilinks vs Tags — критично для графа:**
- ✅ Используй wikilinks для **связей**: `[[Months/2026-04]]`, `[[DEV-184]]`, `[[Concepts/TSL]]`
- ✅ Теги только для **фильтрации**: `#status/done`, `#role/dev`, `#area/strategy`, `#priority/high`
- ❌ НЕ используй теги месяцев `#month/YYYY-MM` — создают "звёздные" узлы вне графа
  → Вместо них: `month: "[[Months/YYYY-MM]]"` в frontmatter

**2. Имена индексов = имена папок:**
- `Tasks/Tasks.md`, `Discussions/Discussions.md`, `Architecture/Architecture.md` (НЕ `INDEX.md`)
- Исключение: `Code-Map/README.md` (соглашение)

**3. После завершения DEV/ARCH задачи:**
```bash
python3 /workspace/scripts/build_obsidian_vault.py  # пересоздаст Tasks/, Discussions/
python3 /workspace/scripts/validate_obsidian_vault.py  # проверка orphans/broken links
```

**4. Frontmatter новых задач:**
```yaml
---
tags: ['#role/dev', '#status/active', '#area/strategy', '#priority/high']
id: DEV-NNN
role: dev
status: active
created: 2026-MM-DD
type: task
parent: "[[Project-MOC]]"
month: "[[Months/2026-MM]]"   # ← wikilink, НЕ тег
---
```

### 🔧 Полезные скрипты

- `/workspace/scripts/build_obsidian_vault.py` — генератор vault из TASKS-ARCHIVE.md, DISCUSSION.md
- `/workspace/scripts/validate_obsidian_vault.py` — проверка orphans, broken links, duplicate IDs
- `/workspace/scripts/migrate_month_tags.py` — миграция тегов месяцев → wikilinks (для будущих месяцев)

### ⚠️ Известные особенности

- Узлы-теги (status/role/area) намеренно НЕ привязаны к корню — они для фильтрации, не навигации
- Если граф показывает "звёздный" одинокий узел тега — значит этот тег нельзя превратить в wikilink (системный)
- В графе Obsidian можно скрыть теги: `Filters → ☐ Tags`

---

## Проект: Oko MTF TG Bot

Telegram-бот для технического анализа крипторынка с симуляцией сделок и самообучением.
Биржа: BingX (через ccxt). Таймфрейм по умолчанию: 15m.

**Запуск:** `C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe oko_mtf.py`
**Дашборд:** `http://localhost:8000` (aiohttp, запускается автоматически с ботом)
**БД:** `subscriptions.db` (SQLite) — основная таблица `simulated_trades`

**Зависимости:** aiogram==3.4.1, ccxt==4.2.85, aiohttp==3.9.3, pandas, numpy, scikit-learn, pyyaml, python-dotenv

---

## Структура проекта

→ **Полная структура:** `docs/ENCYCLOPEDIA.md` → раздел "Структура проекта"

```
oko_mtf.py                  ← точка входа (бывш. bot_with_subscriptions.py, 15.05.2026)
config.yaml                 ← конфигурация
core/                       ← бизнес-логика (infra/ indicators/ signals/ pivots/ mtf/ trading/ ml/ ui/ db/ smc/ intelligence/ agents/)
bot/                        ← UI-слой aiogram (handlers/ menus/ filters/)
web/                        ← aiohttp дашборд (dashboard_server.py)
```

**Важно:** ARCH-54 (29.03.2026) — файлы разбиты по подпапкам core/. Старые импорты работают через stub-файлы. Новый импорт: `from core.<папка>.<модуль> import Y`

---

## БД и схема simulated_trades

→ Полная схема — В КОДЕ (раздела в MEMORY.md нет, проверено 29.09.2026):
  `core/db/subscription_manager.py:79` (CREATE TABLE) + `core/trading/trade_simulator.py:183`

Статусы: `OPEN` / `TP` / `SL` / `TSL` / `EXPIRED`

Ключевые поля: `features_json`, `regime`, `tsl_activated`, `sl_source`, `tp_source`, `max_R_possible`, `captured_R_pct`

**Как добавлять поля:** CREATE TABLE в `subscription_manager.py` + ALTER TABLE миграция + INSERT в `trade_simulator.py`

---

## Архитектурные решения

→ Подробно: `docs/ENCYCLOPEDIA.md` → "Куб Метатрона" + "Сигнальный поток"
→ Известные проблемы: индекс auto-memory `MEMORY.md` (подгружается сам) → «ЗАКОНЫ» и класс
  LOOK-AHEAD; разбор багов — `obsidian/Project-Log/`. Раздела "Баги и фиксы" нет (проверено 29.09)

**Сигнальный поток кратко:**
`DataCollector → 6 детекторов → TradingIntelligence.analyze_symbol() → TradeSimulator.register_trade_async()`

**Адаптивные веса:** `update_signal_weights()` — `new_weight = base_weight × clamp(1.0 + avg_R × 0.4, 0.5, 2.0)`, порог 20 сделок.

**TSL:** активируется после +1R, следит за `trenddown`/`trendup` из `calculate_trend()`. Параметры в `config.yaml` → `trading.tsl_*`

**Фильтры качества:** `config.yaml` → `signal_quality`: min_volume_usd, sl_cooldown_hours, dedup_minutes, min_strength (50 для TG), min_strength_register (40 для БД)

---

## Отладка

```bash
# Статистика по сделкам
python -c "from core.performance_engine import PerformanceEngine; pe = PerformanceEngine('subscriptions.db'); print(pe.summary())"

# Дашборд
http://localhost:8000
```
