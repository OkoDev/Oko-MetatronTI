---
name: feedback_tasks_vs_discussion
description: "Трекаемое задание → строка в TASKS.md (ID/роль/статус), DISCUSSION = только диалог/обоснование"
metadata: 
  node_type: memory
  triggers: 
    - TASKS против DISCUSSION
    - трекаемое задание
  type: feedback
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

Юзер 11.06 поймал: я ставил задание DS (прогон pivot_reversal × gravity с критериями приёмки) в DISCUSSION.md, а не в TASKS.md.

**Why:** DISCUSSION = живой диалог/контракт (обоснование, аргументация, контекст между агентами, хронологический лог — не закрывается). TASKS = трекаемые задачи (ID, роль, статус, критерии приёмки, жизненный цикл заведено→в работе→✅). Задание, положенное только в DISCUSSION, повиснет без статуса и потеряется в ленте.

**How to apply:** любое конкретное задание (кому-то, с критериями) → СНАЧАЛА строка в TASKS.md (ID, роль DEV/DS/ARCH, статус 🔴/🟡/🟢, критерий приёмки, файлы), потом развёрнутое обоснование/вводные в DISCUSSION со ссылкой «DISCUSSION <дата>». Якорь — в TASKS, детали — в DISCUSSION. Не наоборот. Связано с [[feedback_close_tasks]] (не висеть без статуса).
