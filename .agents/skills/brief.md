---
name: brief
description: Обновить session_brief.md (короткая память последних 7 дней через Gemini). АКТИВИРУЙ на "/brief", "обнови brief", "session brief", "краткая сводка сессии".
---

# Brief — короткая память (7 дней)

Запусти: `python tools/context_brief.py [--days 14] [--force]` (пусто = дефолт 7 дней).

Собирает DISCUSSION (последние 7д) + TASKS + current_state + git log/diff → Gemini → структура: Контекст фазы → Открытые вопросы → В работе → Проблемы → Решено → Метрики → Приоритеты.
Output: `memory/session_brief.md` + `obsidian/Sessions/<date>-brief.md`.
