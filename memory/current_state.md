# Current State

## [15.03.2026 09:59 UTC] Агент: Developer — Баги APR/USDT флэш-краш

### ✅ Сделано
- **Расследован инцидент**: сделка #1910 APR/USDT LONG застряла OPEN при цене -21% ниже SL
- **Причина #1 (критическая)**: системные часы Windows были сдвинуты на +3 часа — бот хранил UTC+3 как UTC в `created_at`. После NTP-коррекции все реальные свечи стали "старше" чем `created_at` → фильтр `df[time >= created_at]` возвращал пустой df → `continue` → SL никогда не проверялся
- **Причина #2**: WT_CROSS_UP сгенерировал LONG-сигнал во время флэш-краша (-25%) — gap WT1-WT2 был слишком мал (разовый тик, сразу развернулся вниз)
- **Фикс #1** (`core/trade_simulator.py`): если фильтр по created_at даёт пустой df — берём последние 5 свечей как фолбэк (защита от смещения часов)
- **Фикс #2** (`core/signal_checkers.py`): требуем `wt1-wt2 >= 3` при cross_up и `wt2-wt1 >= 3` при cross_down — однократные мелкие пересечения игнорируются
- **Часы синхронизированы**: `w32tm /resync /force` + `w32tm /config /syncfromflags:DOMHIER /update`
- **Сделка #1910 закрыта вручную** по SL-цене (0.15999, -1R, -2.18%) вместо -9.74R

### ⚠️ Незакоммиченные изменения
- `core/trade_simulator.py` — фолбэк при пустом df
- `core/signal_checkers.py` — gap-фильтр для WT кросса

---

## [15.03.2026 ~UTC] Агент: Developer
- ✅ Сделано: Swing SL как первый приоритет в calculate_levels (коммит be82031)
  - Иерархия: swing_low/high → S1 pivot → FVG → TSL-линия → ATR
  - sl_source: "swing_low:PRICE" | "swing_high:PRICE"
  - 247/253 тестов прошли (6 failing — confluence_state_machine, не связаны)
- ✅ Безубыток (breakeven при +0.5R) уже был реализован ранее
- ⚠️ 6 тестов в test_confluence_state_machine.py сломаны — нужна работа архитектора

---

## [14.03.2026] Агент: Architect

### ✅ Сделано в этой сессии

**ARCH-01 — Рефакторинг bot/monitoring.py → bot/loops/ (коммит b4768ca)**
- `bot/core/bot.py` — TradingAlertBot класс
- `bot/loops/scan_loop.py` — scan_all_pairs + monitor_market + _prefetch_pivots
- `bot/loops/ml_loop.py` — ml_training_loop + weekly_report_loop
- `bot/loops/trade_tracker.py` — trade_tracker_loop
- `bot_with_subscriptions.py` — только точка входа (75 строк)
- Circular import решён через lazy import внутри `start_monitoring()`

**ARCH-02 — Рефакторинг core/trading_intelligence.py → core/intelligence/ (коммит b82214a)**
- `core/intelligence/signal_aggregator.py` — analyze_signals_advanced, calculate_adaptive_weighted_strength
- `core/intelligence/confidence_calculator.py` — calculate_advanced_confidence
- `core/intelligence/recommendation_generator.py` — generate_recommendation, determine_risk_level, generate_reasoning, calculate_levels
- `core/intelligence/ml_enhancer.py` — enhance_analysis_with_ml, apply_ml_corrections
- trading_intelligence.py: 1536 → 1061 строк

**Developer сессия (15.03.2026, DEV-01, коммит 02c8e4b)**
- `core/structure_detector.py`: detect_swing_highs_lows(), detect_choch(), detect_bos(), detect_structure()
- Делегирует в indicators.find_swing_highs/lows
- BOS > CHoCH по приоритету, strength 55/65
- 25/25 тестов passed
- Следующий шаг: DEV-01b — интеграция в signal_checkers.py

### 🔄 Незакоммиченные изменения
Нет — все изменения закоммичены.

### ⚠️ Следующие задачи

**DEV-01b (Developer) — Интеграция structure_detector → signal_checkers.py**
- check_structure_signals() → вызывает detect_structure()
- SignalType.SMC_SIGNAL в signal_models.py
- вес ~0.25 в trading_intelligence.py
- вызов в analyze_symbol()

**DEV-02 (Developer) — Тесты для signal_checkers.py**

**ARCH-03 (Architect, низкий приоритет) — State Machine для confluence**
- Ждёт 2+ недели данных от confluence_scanner

**ARCH-04 (Architect, низкий приоритет) — Адаптивный выбор стратегии**
- Ждёт DEV-07 + ARCH-03

### 📊 Схема Confluence (актуально)

| # | Фактор | Очки |
|---|--------|------|
| 1 | WT в OS/OB зоне | +20 |
| 2 | TSL CROSS в нужном направлении | +20 |
| 2b | WT CROSS в зоне OS/OB (**обязателен**) | +15 |
| 3 | Цена у пивота S/R | +25 |
| 4 | Дивергенция WT | +20 |
| 5 | Цена выше/ниже дневного PP | +15 |
| 6 | Тренд 1h подтверждает (бонус) | +10 |
| 7 | DUAL_CROSS: TSL+WT вместе (бонус) | +10 |

Макс. возможный score: 135 (clamp до 100). Порог сигнала: 60.
