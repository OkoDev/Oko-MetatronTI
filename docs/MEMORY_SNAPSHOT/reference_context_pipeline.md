---
name: reference-context-pipeline
description: "Трёхуровневая память проекта через Gemini — session_brief, project_timeline, obsidian_enrich"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 5125b728-fb4c-47f5-b019-176f112b7ee3
---

# Trёхуровневая память проекта (Gemini pipeline)

Инфраструктура чтобы Claude помнил весь проект, не читая 50k строк сырых архивов.

## Уровень A: session_brief.md (краткая память, обновляется автоматом)

**Скрипт:** `tools/context_brief.py`
**Output:**
- `memory/session_brief.md` — я читаю при старте сессии
- `obsidian/Sessions/YYYY-MM-DD-brief.md` — для пользователя в Obsidian

**Источники:** DISCUSSION.md (60 последних записей) + TASKS.md + memory/current_state.md + git log 7 дней + memory/MEMORY.md (индекс)

**Размер:** ~34k input → ~2.3k output (сжатие 14×).

**Автообновление:** SessionStart hook в `.claude/settings.json`:
```json
{"hooks": {"SessionStart": [{"matcher": "*", "hooks": [{
  "type": "command",
  "command": "C:/Users/yogoru/AppData/Local/Programs/Python/Python312/python.exe \"e:/MTF BOT/CURSOR/crypto_volume_bot/tools/context_brief.py\" --quiet --max-age-hours 6"
}]}]}}
```

Параметр `--max-age-hours 6`: если brief свежий (<6 часов) — скип, не жжём токены.

**Структура brief:** Открытые вопросы → В работе → Что ломалось → Что закрыли → Ключевые цифры → Приоритеты → Контекст фазы.

## Уровень B: project_timeline.md (долгая память, обновляется раз в неделю)

**Скрипт:** `tools/project_timeline.py` — двухпроходный pipeline
**Output:**
- `memory/project_timeline.md` — я читаю когда нужна история
- `obsidian/Project-Log/YYYY-MM-DD-timeline.md` — для Obsidian
- `memory/_timeline_parts/<MONTH>.md` — промежуточные выжимки (кешируются)

**Источники:** DISCUSSION-ARCHIVE-*.md (за все месяцы) + TASKS-ARCHIVE.md

**Pipeline:**
1. **Pass 1 (per-month):** каждый архив (~167k токенов) → Gemini → выжимка ~80-300 строк
2. **Pass 2 (merge):** все per-month выжимки + TASKS-ARCHIVE → Gemini → финальный timeline (~220 строк)

**Кеш:** per-month выжимка перегенерируется только если архив новее самой выжимки. Запуск `--force` форсирует.

**Структура timeline:** Главные фазы → Архитектурная эволюция (по темам) → Эволюция стратегий → ТОП-10 багов с уроками → Метрики по месяцам → Уроки проекта → Куда движется.

**Лимиты Gemini:** 250k input токенов/мин. Per-month запросы по 80-180k. Авто-retry на 429 (читает retryDelay из ответа).

## Уровень C: obsidian_enrich.py (досье задачи, по запросу)

**Скрипт:** `tools/obsidian_enrich.py <TASK_ID>`
**Output:** `obsidian/Tasks/<TASK_ID>.md`

**Использование:**
```powershell
$PY = "C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe"
& $PY tools/obsidian_enrich.py DEV-184            # создать (упадёт если файл есть)
& $PY tools/obsidian_enrich.py DEV-184 --force    # перезаписать
& $PY tools/obsidian_enrich.py ARCH-70            # для архитектурных
& $PY tools/obsidian_enrich.py TR-001             # для трейдерских
```

**Что делает:** grep по DISCUSSION.md + всем DISCUSSION-ARCHIVE-* + TASKS.md + TASKS-ARCHIVE.md + docs/ + memory/ + `git log --grep=<ID>` → блоки с контекстом ±3 строки → Gemini → структурированное досье.

**Структура досье:** Краткая суть → Инициатор → Acceptance → Хронология (по датам) → Что выяснили → Реализация (файлы/коммиты/конфиг) → Метрики → Открытые вопросы → Связанные задачи (wikilinks) → Текущий статус.

**Когда вызывать:** когда возвращаюсь к старой задаче через недели/месяцы, нужна полная история.

## Все 3 уровня — pattern экономии

| Без pipeline | С pipeline |
|---|---|
| Чтение DISCUSSION.md = 47k токенов в моём контексте | session_brief = 2.3k (×20 меньше) |
| Чтение архивов 3 месяцев = 400k токенов (невозможно) | project_timeline = 4.7k (доступно) |
| Поиск истории задачи руками = 5-10 Read+Grep | obsidian_enrich раз → файл готов |

## Ключи и модели

- `GEMINI_API_KEY` в `.env` (проект 238633346423, **без billing** — иначе free-tier=0)
- Primary: `gemini-2.5-flash`. Fallback при 503: `gemini-2.5-flash-lite`
- НЕ использовать: `gemini-2.0-flash` (требует billing на новых проектах)

## Известные ограничения

- **Per-month выжимки могут обрезаться:** при input >150k токенов Gemini иногда возвращает короткий output (~300 токенов вместо 8000). Сейчас это нормально — финальный merge всё равно даёт качественный timeline. Если станет проблемой — добавить sub-chunking архивов.
- **TPM лимит 250k:** очень большие архивы делятся между запросами с паузой 2 сек.
- **Hook не блокирует:** старт сессии задерживается на ~5-30 сек только при первом запуске за 6 часов.

## Команды для ручного обновления

```powershell
$PY = "C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe"
& $PY tools/context_brief.py                     # обновить session_brief сейчас
& $PY tools/context_brief.py --days 14           # шире окно git log
& $PY tools/project_timeline.py                  # обновить timeline (~3-5 мин)
& $PY tools/project_timeline.py --force          # перегенерировать с нуля
& $PY tools/obsidian_enrich.py DEV-200 --force   # досье на задачу
```

## Связанная feedback-memory
- [[reference-llm-delegator]] — общий `tools/llm_ask.py` для разовых вопросов
- [[feedback-bash-auto]] — bash автоматом, делегирование тоже
