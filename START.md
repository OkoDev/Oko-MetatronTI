# 🚀 START — Быстрый контекст сессии

**Проект:** Oko MTF TG Bot — Telegram-бот технического анализа крипторынка (BingX, 15m таймфрейм)
**Запуск:** `python bot_with_subscriptions.py` | **Дашборд:** `http://localhost:8000`
**Архитектура:** `CLAUDE.md` → раздел "Структура проекта" | **Полная история:** `PROJECT-LOG.md`

---

## 📌 Текущий статус (18.04.2026)

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
