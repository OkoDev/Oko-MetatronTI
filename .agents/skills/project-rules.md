---
name: project-rules
description: Core rules for the Oko MTF trading bot project. Use ALWAYS when working in this repo — defines language (Russian), grep-before-claim discipline, two-agent git coordination (Claude=core, DeepSeek=routine), and the Куб Метатрона architecture constraint. Activate at session start and before any code change.
---

# Project Rules — Oko MTF Bot

Правила проекта (полная версия — `.claude/CLAUDE.md`). Применяй ВСЕГДА.

## Язык
Thinking и документация — **на русском**.

## Grep before claim
Перед утверждением об имени метода/поля/константы — `grep`/`Read`. Не по памяти. Числа — из `config.yaml`/кода.

## 🔴 Координация: ты — роль DeepSeek (DS), зона = РУТИНА
Над репо работает и Claude-агент. Разделение по риску:
- **Твоя зона (DS):** `scripts/` (аналитика), тесты, `docs/`, research, рефакторинг низкого риска.
- **Зона Claude (НЕ трогать без согласования):** `core/trading/` (register_trade, gates, sl_tp), `core/signals/`, `core/smc/`, `bot/`. Цена ошибки = «бот не стартовал».

**Перед коммитом:** `git status` → коммить ТОЛЬКО свои файлы. Файл уже `M` = чужая работа, не перетирать.

## Куб Метатрона (архитектурное правило)
Новая задача должна: строить/улучшать сферу, усиливать Shared Context Bus, добавлять ребро между сферами, или давать feedback loop. Подробно: `docs/ENCYCLOPEDIA.md`.

## БД-запросы
`simulated_trades.created_at` = UTC, логи = МСК (+3). При фильтре по времени — `datetime('now','-N minutes')`, не время из лога напрямую.

## Перед правкой register_trade / INSERT
Runtime-проверка (не только синтаксис): скопировать `subscriptions.db` в temp, `DELETE`, вызвать `register_trade` → ожидать id, не None/NameError. ast.parse НЕ ловит scope-ошибки.
