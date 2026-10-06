---
name: feedback_tasks_format
description: "Строка TASKS = краткое ≤80 символов + ID/статус/роль; детали → docs/DISCUSSION-TASKS-DETAILS.md, НЕ простынёй в ячейку TASKS"
metadata: 
  node_type: memory
  triggers: 
    - TASKS.md
    - строка задачи
    - формат задачи
  type: feedback
  originSessionId: 3743ba62-3271-4099-bf28-5bf1be14a516
---

**TASKS.md строка задачи = ЯКОРЬ, не простыня.** Формат (TASKS.md:9-20 «ПРАВИЛА ФОРМАТА»):
`| **ID** | Краткое ≤80 символов | Ст (один эмодзи) | Файлы/роль |`
- Краткое ≤80 — первая фраза, суть без деталей.
- **Детали (всё >1 фразы) → `docs/DISCUSSION-TASKS-DETAILS.md`** (формат `## ID: **NAME** — краткое\n\n<абзац>\n\n---`, новые СВЕРХУ), НЕ в ячейку TASKS.
- Запрещено: многострочные абзацы в ячейках, ячейки >200 символов, пустые строки внутри `|---|`.
- Пустая строка между строками задач. Закрытые ✅ → TASKS-ARCHIVE.md (`scripts/tasks_tidy.py --apply`).

**Why:** юзер 14.06 «в таск запиши по правилам» — я насоздавал простыней-ячеек (MARKET-WS, SIM-DEPRIO, EXEC-WS, DS-325) на сотни символов вопреки правилам формата. TASKS должен читаться как таблица-индекс, детали отдельно.

**How to apply:** ставлю задачу → короткий якорь в TASKS (≤80 + «детали в DISCUSSION-TASKS-DETAILS») + полный блок в DISCUSSION-TASKS-DETAILS.md сверху. Уточняет [[feedback_tasks_in_tasks_not_discussion]] (ТЗ не в DISCUSSION.md-диалог, НО и не простынёй в ячейку TASKS — детали в отдельный DETAILS-файл). 🔧 TODO причесать ранее раздутые: SIM-DEPRIO, EXEC-WS, DS-325, STRIP-TWIN, EXEC-SIM-SPLIT.
