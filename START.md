---
tags: [doc/status, session, project-overview]
type: status-overview
date: "2026-06-14"
sources: [TASKS.md, DISCUSSION.md, PROJECT-LOG.md]
---

# 🚀 START — Быстрый контекст сессии

**Проект:** Oko MTF TG Bot — Telegram-бот технического анализа крипторынка (BingX, 15m таймфрейм)
**Запуск:** `python oko_mtf.py` | **Дашборд:** `http://localhost:8000`
**Архитектура:** `CLAUDE.md` → раздел "Структура проекта" | **Полная история:** `PROJECT-LOG.md`

**🔴 ТЕКУЩИЙ ФОКУС (19.06, пара Даат+DS):** 🔴🔴 **fake-R ЖИВ** — `_resolve_exit` берёт чужой старый ордер (сверено с биржей: «R=+323» = реальный убыток −0.97). **Фикс = positionID** (колонка `position_id` + матч + миграция). Следствие: **OTE-ONLY avgR=0.913 отравлен** → compounding-режимы ПОСЛЕ фикса. Orphan'ы: корень найден, 17 закрыто, кирпич 1 (D-070 auto-close shadow). Детали → `whats-next.md`, [[bug_phantom_exit_resolve]]. Бот PID 33956 жив.

## 🧊 Stabilization Sprint (04.05–25.05.2026)

**План:** [`/root/.claude/plans/fluttering-snacking-whale.md`](/root/.claude/plans/fluttering-snacking-whale.md) — «Возврат управляемости».

**Корень:** в БД попадает ~4% детектируемых сигналов. Остальные 96% — silent drops. ML обучается на 30-40% данных. Сначала возвращаем видимость, потом разбиваем монолиты.

**Заморожено до Phase 4 (~25.05):** ARCH-74, ARCH-74-EXT, ARCH-96..99, ARCH-101..111. Только Phase 0-3 + активный спринт «Реальные убийцы».

**Прогресс:**
- 🔄 Phase 0.1 — заморозка фич (TASKS.md, START.md) — **в работе 04.05**
- ⏳ Phase 0.2 — DecisionTrace в 14 gates → колонка `decision_trace_json` уже готова
- ⏳ Phase 0.3 — таблица `signal_drops` для отброшенных сигналов
- ⏳ Phase 1 — `audit_mode` shadow + `audit_filter_efficacy.py`
- ⏳ Phase 2 — coverage matrix + ML skipped-rows visibility
- ⏳ Phase 3 — `bot/loops/broadcast_pipeline.py` + 14 gate-файлов

**Критерий выхода:** monitoring.py < 800 строк, coverage critical полей ≥ 90%, 7 дней без регрессии avgR.

---

## 📌 Текущий статус (18.05.2026)

**Последние изменения (сессия 18.05 ~00:00):**
- ✅ Аналитика TAIKO/USDT: action=WATCH → watchlist (не потеря), пивоты через PivotCalculatorFixed
- ✅ DISCUSSION.md: блок WPP-магнит + конфлюенции TAIKO записан
- 🔄 Три действия роя ждут 24ч наблюдения (pivot_cache fix был 17.05)
- 🔄 Этап 1.Е TradeRouter — не ранее 18.05 ~12:39 UTC (48ч стабильности)
- ⚠️ 36+ файлов незакоммичено — нужны коммиты

**Приоритеты следующей сессии:**
1. Проверить логи 24ч → реализовать 3 действия роя (pivot_reversal off, atr_change LONG off, confluence boost)
2. Этап 1.Е TradeRouter (cleanup дублей в trade_simulator.py)
3. Коммиты (6 групп)

---

## 📌 Архивный статус (29.04.2026)

**Последние изменения (сессия 18.04):**
- ✅ DEV-178 — Data integrity: 6835 сделок размечены `data_era`, ML фильтр применён (backfill при рестарте)
- ✅ DEV-164 — VST min_sl_dist guard: `open_bracket()` теперь проверяет SL дистанцию (как SIM path)
- ✅ DEV-163 — CircuitBreaker WR=0%: порог снижен 10→5, fast-trigger при 3+ убыточных подряд
- ✅ actual_entry_price: колонка в БД + сохраняется после исполнения bracket-ордера
- ✅ ARCH-83 — wt_entry убран из active_strategies (WR деградация 20%→4.7%)

**Бот работает** — рестарт 18.04 12:48 (backfill выполнен: 6835 сделок).

---

## 🔄 Активные задачи (приоритет)

| Приоритет | ID | Что делать |
|---|---|---|
| 🔴 | ARCH-84 | Жёсткий MTF gate: SHORT при BULL полностью блокировать (WR SHORT=33.5%) |
| 🟡 | ARCH-45 | OutcomePredictor ревью 20.04: теперь обучается на чистых данных (post_157 без micro-SL) |
| 🟡 | DEV-88/89 | OTE C1 shadow: 20 пар / 90 дней. Критерий: WR≥40% ∧ Sharpe≥1.5 ∧ n≥150 (~26.04) |
| 🟢 | ARCH-55-VAL | RANGE BOUNCE валидация shadow: дедлайн 23.04 |
| 🟢 | DEV-172 | Entry Priority Matrix: нужна диагностика (priority=None для всех) |
| 🔵 | DEV-177 | Adaptive weights: EMA вместо full-history avgR |
| 🔵 | DEV-144f | CSS редизайн дашборда: тёмная тема, responsive grid |

---

## ⚠️ Известные проблемы

- **Профитабельность:** убыточный рынок апрель 2026. post_fix WR=24.8%, avgR=-0.503. Наблюдаем до 28.04.
- **confluence** — полностью заблокирован (DEV-171). Был главный убийца (-348R).
- **DEV-172 Entry Matrix**: priority=None для всех — данные не пишутся (баг не найден).
- **micro-SL post_fix**: 18 сделок — VST path теперь защищён (DEV-164), новых не будет.

---

## 📂 Файлы сессии

- [TASKS.md](TASKS.md) — активные задачи (только незавершённые)
- [TASKS-ARCHIVE.md](TASKS-ARCHIVE.md) — все ✅ задачи
- [DISCUSSION.md](DISCUSSION.md) — живой диалог агентов
- [memory/MEMORY.md](memory/MEMORY.md) — архитектурные решения
- [PROJECT-LOG.md](PROJECT-LOG.md) — история изменений

## 🔗 Связанные заметки в Obsidian

- [[Project-MOC]] — Map of Content (главная)
- [[Sessions/2026-04-29]] — Последняя сессия (29.04.2026)
- [[Architecture/ARCH-95-Real-Killers]] — Спринт "Реальные убийцы"
- [[Architecture/Data-Invalidation-Log]] — ARCH-86 (критично для ML)
- [[Architecture/Cube-Metotron]] — Куб Метатрона (полная реализация)
- [[Features/DEV-190-Effective-Status]] — Корректная разметка результатов
- [[Roadmap-2026]] — Временная шкала всех этапов
