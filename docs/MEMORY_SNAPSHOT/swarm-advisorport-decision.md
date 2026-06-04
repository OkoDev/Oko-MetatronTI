---
name: swarm-advisorport-decision
description: "Решение о роли роя team_ask в архитектуре — AdvisorPort (ARCH-125), не фоновый hook"
metadata: 
  node_type: memory
  type: project
  originSessionId: cd13384c-3354-4cc9-9310-0e1f1e8dc982
---

Решено 31.05.2026: рой `tools/team_ask.py` интегрируется в Куб Метатрона **как AdvisorPort (по ARCH-125)** — подключается как внешний советник через порт и пишет вывод в Shared Context Bus, а НЕ встраивается в ядро и НЕ добавляется просто строчкой в `jobs[]` стартовых hooks.

Контекст: при старте бота (`oko_mtf.py` → `_spawn_llm_background_jobs`) рой НЕ запускается. В фоне крутятся только одиночный Gemini-пайплайн (daily_trade_review / daily_log_digest / trade_postmortem / context_brief) + офлайн-агрегаторы Obsidian (daily_pipeline / weekly_digest / obsidian_indexer / task_linker). Рой вызывается вручную через `/team`, `/team-ask` и из `tools/audit_silent_detectors.py:165`.

**Why:** доктрина проекта «подключение, не встраивание»; AdvisorPort = полноценное ребро Куба, а фоновый hook был бы «сбоку от Куба» без сферы/ребра.

**How to apply:** само проектирование/реализацию пользователь отложил на отдельную сессию — НЕ проектировать здесь. Следующей сессии: читать примитив AdvisorPort в `docs/METATRON-KERNEL.md` + ADR в `docs/adr/`, затем проектировать порт + запись роя в Bus. Связано с [[arch125-metatron-kernel]] (если будет создан).
