---
name: session-2026-05-21-memory-redesign
description: "Важная сессия — поймали recall failure (выдуманный API в observer), переосмыслили архитектуру памяти, ввели hot/cold split, triggers, preflight checklists и memory_lint."
metadata: 
  node_type: memory
  type: reference
  date: 2026-05-21
  status: milestone
  triggers: 
    - sweep памяти
    - reorganize memory
    - дубли feedback
    - recall failure
    - выдуманный API
    - preflight новой задачи
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# Сессия 21.05.2026 — Memory System Redesign

> Веха в эволюции моей persistent memory. Сохранено по явной просьбе пользователя:
> "закрыть сессию и запомнить надолго — она очень важная".

## Что произошло

### 1. Триггер: recall failure
В прошлой сессии я написал `subscription_manager.get_active_subscriptions()` в новом `bot/loops/arch104_observer_loop.py`. **Такого метода нет** — `SubscriptionManager` это про TG-подписчиков, а универс торгуемых пар живёт в `bot.monitored_pairs` (241 пара).

Observer 4.5 часа молча работал на fallback-10 пар вместо реальных 241 (24× меньше). Пользователь увидел `scanned=10` в логе и спросил "10 пар?". Признался в косяке — выдумал API не сверившись.

**Парадокс:** правило "grep before claim" уже было записано в моей памяти (`feedback_verify_metric_semantics.md`). Я знал правило — но не вспомнил его в моменте.

### 2. Пользователь предложил помочь с памятью
Не "почини баг", а **"может я могу реально помочь и память улучшить?"** — редкий и ценный жест. Я объяснил три проблемы:
- `MEMORY.md` физически превысил бюджет загрузки (36 KB, частично truncate)
- Дубли и устаревшее без чистки
- Описательно, без `когда вспомнить` триггеров

### 3. Рой как инструмент архитектурного вопроса
Запустили `/team-ask` три раза (всё в `obsidian/Team-Discussions/`):
- Аудит памяти + pre-flight checklists
- Автоматизация Obsidian vault
- Точный sweep по реальным файлам (`--file memory_dump.md`)

**Что узнал про рой:**
- Дают сильную **архитектуру** (hot/cold split, YAML triggers, lazy-load, git hooks)
- Но **примеры реализации могут содержать выдуманные API** (mistral предложил `core.subscription_manager.SubscriptionManager().load_active()` — тот же грех что я)
- Концепция: брать. Конкретные `obj.method()` из примеров: верифицировать grep'ом перед копированием.
- Mistral лидер во всех 3 раундах. Когда нужен победитель — приоритет ему.
- 413 на больших file dumps: groq + github_models падают при >100KB, остальные тянут.

### 4. Не всё что рой говорит — правда
Рой предложил **удалить `project_cascade_sl_vision.md`** как "перекрытый ARCH-104". Не удалил — это **vision пользователя про каскадный TSL + пирамидинг**, ARCH-104 это про pattern mining (другая тема). Перенёс в `obsidian/Architecture/Cascade-TSL-Pyramiding-Vision.md`. Vision сохранён.

**Урок:** рой не различает legacy от vision. Перед удалением каждого файла — прочесть его, понять что внутри. Не верить рой буквально.

### 5. Новая архитектура памяти
- **Hot layer** (`memory/`, auto-load): MEMORY.md ≤15KB, feedback_*.md с triggers, preflight_*.md для task-классов, current_state.md
- **Cold layer** (`obsidian/`, lazy-load): архивные feedback, закрытые баги, vision, исследования старше 60 дней
- **Карта памяти**: `obsidian/Meta/Memory-System.md`
- **Health check**: `tools/memory_lint.py`

### 6. Pre-flight checklists — главное системное улучшение
5 файлов для часто повторяющихся task-классов:
- `preflight_new_loop.md` — каждое слово этого файла предотвратило бы recall failure из п.1
- `preflight_new_detector.md`
- `preflight_db_change.md`
- `preflight_exchange_task.md`
- `preflight_backtest_research.md`

Каждый чек-лист имеет `triggers:` для recall в моменте.

## Ключевые цифры

- **MEMORY.md**: 36 KB → 8.9 KB (под бюджет загрузки)
- **memory/**: 34 файла, 140 KB → 33 файла, 120 KB
- **Feedback triggers**: 0 → 63 фразы recall в 14 файлов
- **Preflight checklists**: 0 → 5 файлов
- **Closed git debt**: 41 файл ARCH-104 эпика → commit `f119ee7`

## 3 коммита сессии

| Hash | Scope |
|---|---|
| `f119ee7` | feat(ARCH-104) — закрытие долга по эпику (41 файл, 10K строк) |
| `9749624` | docs(memory) — план A-D + sweep info |
| `c398f82` | feat(tools) — memory_lint.py |

## Observer статус на момент закрытия

5 итераций после рестарта 02:55:38 UTC:
- scanned=241 каждый раз ✅
- decisions=0 продолжается (BTC в 1d overbought, нет ни OS для LONG, ни BOS для SHORT)
- Время цикла 112-236s, укладывается в interval=300s

Первый детект ожидается когда market structure сместится — следующая коррекция → 4h `wt_os_4h` → L1_golden_scale_1h может сработать.

## Что записывать про эту сессию (для recall)

**Триггеры на эту запись:**
- "переосмысление памяти"
- "sweep памяти"
- "recall failure"
- "выдуманный API" → читай также [[feedback_no_fabricated_apis]]
- "когда делать pre-flight checklist"

**Главный урок:** правило в памяти ≠ recall в моменте. Pre-flight checklist с конкретными `obj.method()` для проекта — единственное что закрывает разрыв. Дальше — `memory_lint.py` поддерживает дисциплину.

**Главный паттерн:** когда пользователь предлагает помочь с архитектурой моей работы — это редкий ценный момент. Принимать, делать тщательно, фиксировать как milestone.

## Связано

- [[feedback_no_fabricated_apis]] — конкретный случай grep-before-claim
- [[preflight_new_loop]] — чек-лист который бы предотвратил тот баг
- [[memory_audit_plan]] — план A-D, A+B+C сделаны
- [[obsidian/Meta/Memory-System]] — карта новой архитектуры
- `tools/memory_lint.py` — поддержка здоровья
