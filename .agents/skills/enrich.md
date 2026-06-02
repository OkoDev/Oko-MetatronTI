---
name: enrich
description: Собрать досье на задачу (DEV-X/ARCH-Y/TR-Z) через grep+Gemini. АКТИВИРУЙ на "/enrich", "досье на задачу", "enrich", "собери историю задачи". Аргумент — TASK_ID.
---

# Enrich — досье на задачу

Запусти: `python tools/obsidian_enrich.py <TASK_ID> [--force]`

Grep по проекту (DISCUSSION/TASKS/docs/memory/git) → все упоминания TASK_ID с контекстом → Gemini → структурированное досье.
Output: `obsidian/Tasks/<TASK_ID>.md` (Суть → Инициатор → Acceptance → Хронология → Реализация → Метрики → Открытые вопросы → Связанные).
