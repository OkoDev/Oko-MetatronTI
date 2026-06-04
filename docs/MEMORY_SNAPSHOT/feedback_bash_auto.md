---
name: feedback-bash-auto
description: Пользователь разрешил автоматически выполнять Bash-команды без запроса разрешения
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 47da83c4-a395-4719-9abc-f67e0074d9eb
triggers:
  - 'bash команда (не destructive)'
  - 'grep/ls/cat запрос'
---

Bash-команды (чтение файлов, grep, поиск, запуск скриптов) выполнять автоматически без запроса подтверждения.

**Why:** Пользователь явно указал "Разрешено автоматически выполнять Bash-команды" (2026-05-14).

**How to apply:** Не ждать approve для Bash tool calls. Выполнять сразу. Ограничение сохраняется для деструктивных операций (rm -rf, git reset --hard, force push) — они требуют подтверждения согласно общим правилам безопасности.
