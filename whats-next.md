# Whats-Next — Handoff Document
> Обновлено: 14.03.2026 | Агент: Claude Sonnet 4.6 (Architect)

---

<work_completed>

## Что было сделано (14.03.2026 — обе сессии)

### ARCH-01 (коммит b4768ca)
- `bot/core/bot.py` — TradingAlertBot класс
- `bot/loops/scan_loop.py` — scan_all_pairs + monitor_market + _prefetch_pivots
- `bot/loops/ml_loop.py` — ml_training_loop + weekly_report_loop
- `bot/loops/trade_tracker.py` — trade_tracker_loop
- `bot_with_subscriptions.py` — только точка входа (75 строк)
- `bot/monitoring.py` — фильтры + фоновые проверки + broadcast (765 строк)

### ARCH-02 (коммит b82214a)
- `core/intelligence/signal_aggregator.py` — analyze_signals_advanced, calculate_adaptive_weighted_strength
- `core/intelligence/confidence_calculator.py` — calculate_advanced_confidence
- `core/intelligence/recommendation_generator.py` — generate_recommendation, determine_risk_level, generate_reasoning, calculate_levels
- `core/intelligence/ml_enhancer.py` — enhance_analysis_with_ml, apply_ml_corrections
- `core/trading_intelligence.py`: 1536 → 1061 строк, методы стали тонкими делегатами

### DEV-01 (коммит 02c8e4b, Developer, 15.03.2026)
- `core/structure_detector.py`: detect_swing_highs_lows(), detect_choch(), detect_bos(), detect_structure()
- BOS > CHoCH по приоритету, strength 55/65
- 25/25 тестов passed

</work_completed>

---

<work_remaining>

## Высокий приоритет

### 1. DEV-01b — Интеграция structure_detector → signal_checkers.py
Developer должен добавить новый тип сигнала `smc_signal` в пайплайн:
- Вызвать `detect_structure()` в `check_structure_signals()` в `signal_checkers.py`
- Добавить `SignalType.SMC_SIGNAL` в `signal_models.py`
- Добавить вес ~0.25 в `trading_intelligence.py`
- Вызвать в `analyze_symbol()` (scan_one)

### 2. DEV-02 — Тесты для signal_checkers.py
Дополнить `tests/unit/test_signal_checkers.py`:
- check_wt_signals с мок данными OS/OB зон
- check_anomaly_signals при volume spike
- check_divergence_signals (bullish/bearish)

## Низкий приоритет (Architect)

### 3. ARCH-03 — State Machine для confluence
Зависимость: нужно 2+ недели данных от confluence_scanner.
Заменить Lookback Scanner на State Machine per symbol.

### 4. ARCH-04 — Адаптивный выбор стратегии по режиму рынка
Зависимость: после DEV-07 + ARCH-03.
TREND → TRIPLE_TP_TSL, RANGE → DUAL_TP.

</work_remaining>

---

<critical_context>

## Инфраструктура

### Python
- **Python 3.12 строго:** `C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe`
- `.venv` и Python 3.13 не имеют aiogram — не использовать

### Запуск бота
```bash
C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe bot_with_subscriptions.py
```

### Дашборд
- `http://localhost:8000` — статистика
- `http://localhost:8000/settings` — настройки
- `GET /api/stats/confluence` — разбивка WR по факторам

### Архитектура после ARCH-01/02
```
bot_with_subscriptions.py  ← точка входа (75 строк)
bot/core/bot.py            ← TradingAlertBot
bot/loops/
  scan_loop.py             ← scan_all_pairs, monitor_market, _prefetch_pivots
  ml_loop.py               ← ml_training_loop, weekly_report_loop
  trade_tracker.py         ← trade_tracker_loop
bot/monitoring.py          ← фильтры, broadcast, фоновые проверки (765 строк)

core/trading_intelligence.py       ← 1061 строк (делегаты)
core/intelligence/
  signal_aggregator.py             ← агрегация сигналов
  confidence_calculator.py         ← расчёт уверенности
  recommendation_generator.py      ← SL/TP, рекомендация
  ml_enhancer.py                   ← ML улучшение
```

### БД: subscriptions.db
```
id, symbol, timeframe, signal_type, direction, entry_price, stop_loss, take_profit,
strength, confidence, regime, created_at,
status (OPEN/TP/SL/TSL/EXPIRED), exit_price, profit_pct, R_multiple, closed_at,
duration_minutes, features_json,
max_price, min_price, max_R_possible, captured_R_pct,
strategy_name TEXT,
tsl_tf TEXT DEFAULT '15m',
tsl_activated INTEGER DEFAULT 0,
sl_source TEXT, tp_source TEXT,
tp2_price, tp2_hit_at, tp3_price, tp3_hit_at, strategy_type
```

## Архитектурные запреты

- **Дивергенции НЕ в pre_signals** — создают `conflict_ratio` → `action=WATCH`, сделки не регистрируются
- **`enableRateLimit: False`** в ccxt — намеренно (контроль через `Semaphore(20)`)
- **Логику TP (pivot уровни)** — менять только с согласования пользователя
- **Любые изменения торговой логики** — сначала обсудить с пользователем

## Стратегии

- `active_strategy` в config.yaml = кто отправляет TG-сигналы (основная стратегия)
- `active_strategies` = все симулируются в БД для сравнения WR
- Зарегистрированные стратегии: `confluence`, `confluence_scanner`, `conservative`, `mtf_bias`, `pivot_reversal`

## Ключевые данные по стратегиям (на 13.03.2026)
- `pivot_reversal`: WR 47.9%, avg_R +0.46 — **лучшая по данным**
- `confluence`: WR 19.1%, avg_R -0.13 — требует улучшения
- `wt_signal`: WR 33.6%, avg_R +0.36 — средний

</critical_context>

---

<current_state>

## Состояние на 14.03.2026

### Что работает
- Сканер: 600+ пар, enableRateLimit=False, Semaphore(20), 25-32 сек на полный прогон
- TSL: активируется при current_r ≥ 1.0, переключается на 1h если тренд совпадает
- PIVOT_REVERSAL: без лишних API-вызовов, динамический strength 60-100
- Стратегии: все 5 симулируются параллельно, `strategy_name` пишется в БД
- Дашборд: `/api/stats/confluence`, секция "По стратегии"
- structure_detector.py: готов, 25/25 тестов, ожидает интеграции в signal_checkers

### Незакоммиченные изменения
Нет — все изменения закоммичены.

</current_state>
