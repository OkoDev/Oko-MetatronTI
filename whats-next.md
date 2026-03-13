# Whats-Next — Handoff Document
> Обновлено: 13.03.2026 | Агент: Claude Sonnet 4.6

---

## work_completed — ЧТО СДЕЛАНО В ЭТОЙ СЕССИИ

### 1. Confluence аналитика WR + фикс TP пивоты (коммит e1106c6)
- `bot/monitoring.py`: сохраняем `confluence_factors` в `features_json` при регистрации
- `core/performance_engine.py`: новый метод `confluence_breakdown()` — WR по direction/strength/tp_source/факторам
- `web/dashboard_server.py`: секция "Confluence — разбивка WR", endpoint `GET /api/stats/confluence`

### 2. Параллельный запуск всех стратегий (коммит 5716911)
- `config.yaml`: `active_strategies: [confluence_scanner, pivot_reversal, confluence, mtf_bias]`
- `core/subscription_manager.py` + `trade_simulator.py`: колонка `strategy_name` в `simulated_trades`
- `core/trading_intelligence.py`: `self.strategies dict`, `_run_all_strategies()` — параллельный запуск
- `bot/monitoring.py`: регистрирует сделки всех стратегий в БД (без TG-спама для не-основных)
- `core/performance_engine.py`: `by_strategy()` + `full_stats` включает `by_strategy`
- `web/dashboard_server.py`: секция "По стратегии" на главной странице

### 3. CLAUDE.md обновлён (правило обязательного чтения MD)
- Добавлен блок "🔴 СТАРТ КАЖДОЙ СЕССИИ" — список файлов для обязательного чтения

---

## current_state — ТЕКУЩЕЕ СОСТОЯНИЕ

### Активная стратегия (TG-сигналы)
`confluence_scanner` — основная, отправляет TG-сигналы

### Параллельные стратегии (только БД)
`pivot_reversal`, `confluence`, `mtf_bias` — накапливают сделки с `strategy_name` тегом

### Что работает
- `python run_backtest.py --list-strategies` → 5 стратегий
- `/api/stats` → включает `by_strategy` таблицу
- `/api/stats/confluence` → разбивка WR по факторам

### Данные по стратегиям
Старые сделки в БД имеют `strategy_name = NULL` (до этой сессии).
Новые сделки с `strategy_name` начнут накапливаться после перезапуска бота.

---

## work_remaining — ЧТО ОСТАЛОСЬ

### 1. 🔥 ВЫСОКИЙ ПРИОРИТЕТ: Перезапустить бота
Все изменения вступят в силу только после перезапуска:
```bash
C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe bot_with_subscriptions.py
```

### 2. Мониторинг через 1-2 недели
После накопления данных проверить WR по стратегиям:
```bash
python -c "
from core.performance_engine import PerformanceEngine
pe = PerformanceEngine('subscriptions.db')
for r in pe.by_strategy(): print(r)
"
```

### 3. Confluence — улучшение сигналов (из анализа данных)
Данные показали: strength 50-70 = WR 50-57%, strength 70-80 = WR 4.3% (аномалия 12.03).
Нужно разобраться почему 12.03 было 198 сигналов с плохим качеством.

### 4. MTF WT — ведение сделок по TSL старшего TF (обсуждено, не реализовано)
- После входа на 15m → trailing по TSL 1h вместо 15m TSL
- Pivot confluence как цель (кластеры уровней с разных TF)

### 5. Из TASKS.md (в очереди)
- [DEV-05] Умный выбор SL (структурный): под S1 → под FVG → под TSL → ATR fallback
- [DEV-06] RR-фильтр перед регистрацией (RR < 2.0 → не регистрировать)
- [ARCH-01] Рефакторинг bot_with_subscriptions.py (1540+ строк)

---

## critical_context

### Python
- Python 3.12 строго: `C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe`
- `.venv` и Python 3.13 не имеют aiogram — не использовать

### Стратегии
- `active_strategy` = кто отправляет TG-сигналы
- `active_strategies` = все симулируются в БД для сравнения WR
- Все 5 стратегий зарегистрированы: `confluence, confluence_scanner, conservative, mtf_bias, pivot_reversal`

### Ключевые находки из данных (13.03.2026)
- pivot_reversal: WR 47.9%, avg_R +0.46 — лучшая стратегия по данным
- confluence: WR 19.1%, avg_R -0.13 — требует улучшения условий входа
- wt_signal: WR 33.6%, avg_R +0.36 — средний результат
- TP источник: pivot_1D:S2/S3 даёт WR 0-7% (цена не доходит до дальних уровней)

### Архитектурное решение: НЕ трогать без обсуждения
- Логику выставления TP (pivot уровни) — только с согласования пользователя
- Любые изменения торговой логики (SL/TP/условия входа) — сначала обсудить
