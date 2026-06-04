---
name: feedback-skill-vs-code
description: "SKILL.md меняет поведение Claude в чате (analytics-помощник), код в core/signals/ меняет поведение бота (auto-trading). Это разные слои — не смешивать."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 96017807-32f5-4df5-be76-34c459bb7da6
triggers:
  - 'SKILL.md'
  - 'skill'
  - '''новый навык TRADER'''
  - '''улучшит торговлю'''
  - 'выбор слоя chat-analytics vs trading-code'
---

# SKILL.md vs реализация в коде — два разных слоя

**Правило:** Когда обсуждаем новые "trader navыки" (chart patterns, funding readers, post-mortem analyzers и т.п.) — всегда разделять **SKILL.md** и **код в боте**.

**Why:** Пользователь спросил "напишем SKILL.md и что нам это даст?" — это явный сигнал что нужно держать различие прозрачным. Без него легко продать SKILL.md как «полезный для бота» когда он влияет только на Claude-чат. Это создаёт ложные ожидания о «улучшении торговли».

## Различие

| | SKILL.md | Код (`core/signals/`, `bot/loops/`) |
|---|---|---|
| Что меняет | Поведение Claude в чате | Поведение работающего бота |
| Где живёт | `C:/Users/yogoru/.claude/skills/<name>/SKILL.md` | `core/signals/<detector>.py` + wiring в `scan_loop.py` |
| Кто триггерит | Пользователь в чате (`/skill_name`) или контекст | scan_loop каждые 30-60с автоматически |
| Влияет на сделки | ❌ нет | ✅ да |
| Попадает в `simulated_trades` | ❌ нет | ✅ да |
| TG-алерт | ❌ нет | ✅ если is_actionable |
| Откат | удалить файл | `git revert` + регрессионный тест |
| Стоимость | 1 час, текст | 1-3 дня, код+тесты+бэктест |

## Когда что использовать

**SKILL.md полезен для:**
- Аналитических задач TRADER (TR-001 ежедневный разбор WL, TR-003 валидация Confirmation Registry, TR-007 audit)
- Post-mortem сделок (методичный walkthrough одной сделки)
- Прототипирование гипотезы **до** реализации в коде ("проверь 50 сделок — был ли паттерн X")
- Один и тот же повторяющийся ручной анализ

**Код в `core/signals/` нужен для:**
- Realtime детекции (бот должен ловить событие в момент)
- Влияние на entry/exit decisions (gate, confirmation в aggregator, изменение strength)
- Запись в БД для последующего ML обучения

## Гибридный путь (рекомендованный)

1. Skill первым — Claude прогоняет гипотезу по историческим сделкам, выдаёт статистику
2. Если статистика положительная → реализация в коде с публикацией в EventBus / ConfirmationAggregator
3. Если отрицательная → удаляем skill, экономим неделю кодирования

## How to apply

- Когда пользователь предлагает skill — сразу спросить: «это для тебя в чате (analytics) или для бота (realtime)?»
- Если для бота — это код в `core/signals/`, не skill
- Если оба — гибридный путь (skill → проверка → код)
- Никогда не утверждать что skill «улучшит торговлю» — он улучшит **аналитику Claude**

## Примеры

| Идея | Skill? | Код? |
|---|---|---|
| Trade Post-Mortem Analyzer | ✅ да (TRADER ручной разбор) | ❌ |
| Confirmation Synergy Analyzer | ✅ да (analytics перед DEV-204) | ❌ |
| Pair Profitability Heatmap | ✅ да (TR-001) | ❌ |
| Data Era Splitter | ✅ да (enforce правило) | ❌ |
| Chart Pattern Analyzer | 🟡 sкilл для prototype, потом код | ✅ если статистика +R |
| Funding Rate Reader | ❌ | ✅ как gate/feature |
| OI Δ Tracker | ❌ | ✅ как detector |
| Volatility Squeeze Detector | ❌ | ✅ как signal_type |
| DEX Pool Liquidity Watcher | ❌ | ✅ как detector |

Связано: [[arch_signal_types]], [[feedback_data_era_first]]
