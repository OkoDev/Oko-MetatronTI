---
name: timeline
description: Обновить project_timeline.md (долгая память, все архивы DISCUSSION через Gemini). АКТИВИРУЙ на "/timeline", "обнови timeline", "история проекта", "хронология".
---

# Timeline — долгая память (хронология)

Запусти: `python tools/project_timeline.py [--force]`

Двухпроходный (обход лимита Gemini): Pass1 — каждый DISCUSSION-ARCHIVE-<month> → выжимка месяца (кеш `memory/_timeline_parts/`); Pass2 — выжимки + TASKS-ARCHIVE → финальный timeline.
Output: `memory/project_timeline.md` + `obsidian/Project-Log/<date>-timeline.md`.
