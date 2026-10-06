---
name: preflight-rules-table
description: Полная таблица pre-flight чек-листов (триггер→файл) — вынесена из MEMORY.md для экономии места в хот-индексе
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 03741574-3261-416f-94b1-b4b7c6de6735
---

Читать чек-лист ПЕРЕД началом задачи соответствующего класса.

| Триггер | Чек-лист |
|---|---|
| новый async loop | `preflight_new_loop.md` |
| новый detector/signal | `preflight_new_detector.md` |
| ALTER TABLE / поле БД | `preflight_db_change.md` |
| BingX/ccxt/order/VST | `preflight_exchange_task.md` |
| бэктест/walkforward | `preflight_backtest_research.md` |
