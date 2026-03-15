# Whats-Next — Handoff Document
> Обновлено: 15.03.2026 | Агент: Claude Sonnet 4.6 (Developer — WT-B сессия)

---

<work_completed>

## Что было сделано (15.03.2026 — WT-B исследование)

### Бэктест WT сигналов (scripts/)

Проведён полный цикл: данные → гипотезы → тесты → реализация.

**Скрипты анализа (все в `scripts/`):**
- `analyze_wt_signals.py` — 3 гипотезы из БД (gap, нулевая линия, дивергенции)
- `analyze_wt_divergence.py` — Fixed ±60 vs Adaptive p10/p90, типы A/B/C
- `analyze_wt_typeB.py` — детальный анализ типа B с фильтрами и каскадной 4h проверкой

**Ключевые результаты бэктеста (103 пары, 180 дней, 1h):**

| Стратегия | n | WR | avgRet |
|---|---|---|---|
| Тип A (текущий wt_signal) | ~500+ | ~49% | ~+0.5% |
| Тип B без фильтров | 158 | 57% | +1.6% |
| Тип B, div_strength 3-20 | 53 | **84.9%** | **+4.82%** |
| Тип B, div_strength 3-20 + 4h OS | 39 | **87.2%** | **+4.78%** |

**Открытия:**
- `div_strength > 20` = антисигнал (WR=33%) — слишком большой разрыв = продолжение тренда
- `div_strength 10-20` = WR=100% (n=15) — гипотеза: это каскадная дивергенция с 4h
- Gap WT1-WT2 >= 10 → WR=60% vs 37% при gap<10 (внедрено ранее: +5 к strength)

### DEV: Реализован wt_b_signal

| Файл | Что изменено |
|---|---|
| `core/signal_models.py` | `WT_B_SIGNAL = "wt_b_signal"` |
| `core/signal_checkers.py` | `check_wt_b_signals(symbol, df_1h)` — полная логика |
| `core/trading_intelligence.py` | вес 0.15, маппинг, вызов в gather |
| `config.yaml` | секция `wt_b: div_min/div_max/lookback` |
| `core/trade_simulator.py` | приоритетный список signal_type в БД (баг-фикс) |

### Баг-фикс: signal_type в БД

**Проблема:** `_signal_type_from_recommendation` брал первый сигнал из supporting_signals
(порядок = порядок asyncio.gather: anomaly первый). Если срабатывал anomaly + mtf_bias
→ в БД писалось "anomaly". Адаптивные веса mtf_bias не накапливались.

**Фикс:** приоритетный список в `trade_simulator.py`:
```
wt_b_signal → mtf_bias → confluence → pivot_reversal → smc_structure
→ wt_signal → divergence → trend_signal → anomaly → mtf_signal
```

</work_completed>

---

<work_remaining>

## Высокий приоритет

### 1. DEV-WT-B-2 — 4h подтверждение к wt_b_signal (бонус к strength)

**Суть:** Загружать df_4h в `analyze_symbol()` и передавать в `check_wt_b_signals`.
Если WT 4h в OS/OB зоне (adaptive p10/p90) → strength += 10.

Данные бэктеста:
- B + 4h OS → WR=87.2% (vs 78.6% без 4h)

**Что нужно сделать:**
1. В `trading_intelligence.py` добавить `df_4h` в asyncio.gather загрузки OHLCV (строка ~512)
2. В `check_wt_b_signals(symbol, df_1h, df_4h=None)` — добавить параметр
3. Если 4h WT в OS/OB → `strength = min(95, strength + 10)`, в `data["cascade_4h"] = True`

**Не делать** пока не запустится бот и не накопится 10+ реальных wt_b сделок.

---

### 2. DEV-01b — Интеграция structure_detector → signal_checkers.py

Developer должен добавить `smc_signal` в пайплайн:
- Вызвать `detect_structure()` в `check_structure_signals()` в `signal_checkers.py`
- Добавить `SignalType.SMC_SIGNAL` в `signal_models.py` (уже есть `SMC_STRUCTURE`)
- Вес ~0.12 в `trading_intelligence.py` (уже есть в signal_weights)
- Вызвать в `asyncio.gather` в `_collect_all_signals`

---

### 3. DEV-02 — Тесты для signal_checkers.py

Дополнить `tests/unit/test_signal_checkers.py`:
- `check_wt_b_signals` — проверить что сигнал генерируется при div_strength 3-20
- `check_wt_signals` с мок данными OS/OB зон
- `check_anomaly_signals` при volume spike

---

## Низкий приоритет (Architect)

### 4. ARCH-WT-B — Тип C как следующий класс сигналов

**Тип C:** crossover ВНЕ OS/OB + дивергенция WT (паттерн пользователя).
Бэктест типа C на adaptive пороге показал WR=58% (vs 49% типа A).
Нужен отдельный бэктест на 1h перед реализацией.
Команда: `python scripts/analyze_wt_divergence.py --days 180 --tf 1h`

### 5. ARCH-03 — State Machine для confluence

Зависимость: нужно 2+ недели данных от confluence_scanner.
Заменить Lookback Scanner на State Machine per symbol.

### 6. ARCH-04 — Адаптивный выбор стратегии по режиму рынка

Зависимость: после DEV-07 + ARCH-03.
TREND → TRIPLE_TP_TSL, RANGE → DUAL_TP.

---

## Наблюдать через 2 недели

- **wt_b_signal WR в реальных сделках** — цель > 65% (бэктест 85%)
- **Шаг 2 gap фильтра** — проверить Q1 (gap < 3.4): если WR < 40% → добавить фильтр
- **signal_type в БД** — после фикса проверить что mtf_bias/confluence накапливают правильную статистику

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

### Архитектура после ARCH-01/02
```
bot_with_subscriptions.py  ← точка входа (75 строк)
bot/core/bot.py            ← TradingAlertBot
bot/loops/
  scan_loop.py             ← scan_all_pairs, monitor_market, _prefetch_pivots
  ml_loop.py               ← ml_training_loop, weekly_report_loop
  trade_tracker.py         ← trade_tracker_loop
bot/monitoring.py          ← фильтры, broadcast, фоновые проверки

core/trading_intelligence.py       ← 1061 строк (делегаты)
core/intelligence/
  signal_aggregator.py             ← агрегация сигналов
  confidence_calculator.py         ← расчёт уверенности
  recommendation_generator.py      ← SL/TP, рекомендация
  ml_enhancer.py                   ← ML улучшение
```

### wt_b_signal — параметры (config.yaml)
```yaml
analysis:
  wt_b:
    enabled: true
    div_min: 3.0    # min разрыв лоу/хай (div_strength)
    div_max: 20.0   # max — выше = продолжение тренда
    lookback: 35    # баров назад для поиска дивергенции
```

### signal_type приоритет в БД (trade_simulator.py)
```
wt_b_signal > mtf_bias > confluence > pivot_reversal > smc_structure
> wt_signal > divergence > trend_signal > anomaly > mtf_signal
```

### БД: subscriptions.db
```
id, symbol, timeframe, signal_type, direction, entry_price, stop_loss, take_profit,
strength, confidence, regime, created_at,
status (OPEN/TP/SL/TSL/EXPIRED), exit_price, profit_pct, R_multiple, closed_at,
duration_minutes, features_json,
max_price, min_price, max_R_possible, captured_R_pct,
strategy_name, tsl_tf, tsl_activated, sl_source, tp_source,
tp2_price, tp2_hit_at, tp3_price, tp3_hit_at, strategy_type
```

## Архитектурные запреты

- **Дивергенции НЕ в pre_signals** — создают `conflict_ratio` → `action=WATCH`
- **`enableRateLimit: False`** в ccxt — намеренно (контроль через `Semaphore(20)`)
- **Логику TP (pivot уровни)** — менять только с согласования пользователя
- **wt_b_signal на 1h** — НЕ переводить на 15m без бэктеста на 15m данных
- **div_max = 20** — НЕ повышать: div_strength > 20 = антисигнал (WR=33% в бэктесте)

## Стратегии

- `active_strategy` в config.yaml = кто отправляет TG-сигналы
- `active_strategies` = все симулируются в БД для сравнения WR
- Зарегистрированные: `confluence`, `confluence_scanner`, `conservative`, `mtf_bias`, `pivot_reversal`

## Ключевые данные (на 15.03.2026)
- `pivot_reversal`: WR 47.9%, avg_R +0.46 — лучшая по реальным данным
- `wt_signal`: WR 33.6%, avg_R +0.36
- `wt_b_signal`: только запущен, нужно накопить данные

</critical_context>

---

<current_state>

## Состояние на 15.03.2026

### Что работает
- Сканер: 600+ пар, enableRateLimit=False, Semaphore(20)
- TSL: активируется при current_r ≥ 1.0
- wt_b_signal: реализован, активен, пишет в БД как "wt_b_signal"
- signal_type приоритет: исправлен в trade_simulator.py
- structure_detector.py: готов, 25/25 тестов, ожидает интеграции

### Незакоммиченные изменения
- `core/signal_models.py` — WT_B_SIGNAL
- `core/signal_checkers.py` — check_wt_b_signals + хелперы
- `core/trading_intelligence.py` — импорт + вес + вызов
- `core/trade_simulator.py` — приоритетный список signal_type
- `config.yaml` — секция wt_b
- `scripts/analyze_wt_typeB.py` — расширен (div-min/max, 4h cascade, 103 пары)

**Нужно сделать коммит перед запуском бота!**

</current_state>
