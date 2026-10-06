---
name: telegram-claude-integration
description: Идея интеграции Claude Code с Telegram для управления ботом из чата
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

Хотим подключить Claude Code к Telegram чтобы управлять ботом из чата.

**Вариант А (предпочтительный):** отдельный бот токен через `claude -- --channels plugin:telegram@claude-plugins-official` — полный доступ к файлам/логам/БД.

**Вариант Б:** команда `/ask` в существующем боте → Claude API → ответ в чате. Проще но без доступа к коду.

**Why:** управлять ботом на ходу — смотреть логи, сделки, перезапускать — прямо из Telegram без ноутбука.

**How to apply:** отдельная задача когда будет время. Установка Ollama уже в процессе (скачивает).
