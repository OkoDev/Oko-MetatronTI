---
name: postmortem
description: Разбор убыточной сделки через Gemini — диагноз root cause + урок. АКТИВИРУЙ на "/postmortem", "разбор сделки", "postmortem", "почему убыток", "разбери сделку". Аргумент — trade_id или --hours N --threshold -X.
---

# Postmortem — разбор убыточной сделки

Запусти: `python tools/trade_postmortem.py <trade_id | --hours 24 --threshold -2.0 | --force>`

Читает полный record из `subscriptions.db` (features_json, decision_trace_json, confirmations) → Gemini критический промпт → Суть → Контекст входа → Что планировалось → Что случилось → анализ confirmations → Главный диагноз → Урок → Связано.
