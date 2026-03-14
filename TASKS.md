# 📋 TASKS — Координация агентов

Файл координации между Architect (yogoru) и Developer (oko.webdev).

**Workflow:** Architect создаёт задачу → Developer берёт в работу → Architect делает review

---

## 🔥 В РАБОТЕ (In Progress)

### [DEV-04] ✅ Confluence Scanner — Lookback (Шаг 1) — ГОТОВО
Реализовано 09.03.2026:
- `core/confluence_scanner.py` — новый модуль, 5 факторов, score 0-100
- `core/signal_models.py` — добавлен `SignalType.CONFLUENCE`
- `core/trading_intelligence.py` — вес 0.35, в _SIGNAL_TYPE_MAP
- `bot/monitoring.py` — интеграция в scan_one() после MTF signals

---

## 📥 ОЧЕРЕДЬ (Backlog)

### [DEV-04] Confluence Scanner — Lookback (Шаг 1)
**Агент:** Developer
**Приоритет:** Высокий
**Описание:**
Новый модуль `core/confluence_scanner.py`:
- `scan_confluence(df_15m, df_1h, pivot_levels, lookback_bars=20) → ConfluenceSetup | None`
- Условия: WT в OS → TSL cross UP → цена у S1/PP ±0.5% → дивергенция bullish → цена выше PP
- Интеграция в `bot/monitoring.py` → scan_one(), signal_type="confluence"
- Порог strength ≥ 60 (3+ из 5 факторов)

**Цель:** находить сетапы как на графике BASUSDT 09.03.2026 (1H+15M)

### [DEV-05] Умный выбор SL (структурный)
**Агент:** Developer
**Приоритет:** Высокий
**Зависимость:** После DEV-04
**Описание:**
Изменить `_calculate_levels()` в `core/trading_intelligence.py`:
- Приоритет: под S1 → под FVG → под TSL линией → ATR fallback
- Зажим [0.5%, 3%]. Добавить `sl_source` описание в TradingRecommendation (уже есть)

### [DEV-06] ✅ RR-фильтр перед регистрацией сделки — ГОТОВО
Реализовано 15.03.2026 (коммит 1e48630):
- RR = abs(tp-entry)/abs(entry-sl), если < 2.0 → skip + log INFO
- Также зафиксированы sl_source/tp_source/strategy_name/tsl_tf в CREATE TABLE (были только в INSERT)
- 7 новых тестов TestRRFilter, 25/25 passed

### [DEV-07] ✅ Частичные TP в trade_simulator — ГОТОВО
Реализовано 15.03.2026 (коммит 5e1be9d):
- tp2_price/tp2_hit_at/tp3_price/tp3_hit_at/strategy_type в схеме + миграция
- RR≥3→TRIPLE_TP_TSL, RR∈[2,3)→DUAL_TP, уровни рассчитываются при регистрации
- Трекинг tp2/tp3 в check_open_trades_with_tsl() для LONG и SHORT
- 31/31 тестов passed

### [ARCH-03] State Machine для confluence (Шаг 2)
**Агент:** Architect
**Приоритет:** Низкий
**Зависимость:** После 2 недель данных от DEV-04
**Описание:**
Заменить Lookback Scanner на State Machine per symbol:
IDLE → WT_OS → TSL_CROSS → NEAR_PIVOT → DIVERGENCE → SIGNAL
Хранение состояний в памяти или SQLite `confluence_states`. Таймаут 48h.

### [ARCH-04] Адаптивный выбор стратегии по режиму рынка
**Агент:** Architect
**Приоритет:** Низкий
**Зависимость:** После DEV-07 + ARCH-03
**Описание:**
TREND → TRIPLE_TP_TSL, агрессивный SL
RANGE → DUAL_TP, консервативный SL
HIGH_VOL → меньше размер позиции, TP1 обязателен сразу

### [ARCH-01] ✅ Этап 8: Рефакторинг bot_with_subscriptions.py — ГОТОВО
Реализовано 14.03.2026 (коммит b4768ca):
- `bot/core/bot.py` — TradingAlertBot класс
- `bot/loops/scan_loop.py` — scan_all_pairs + monitor_market + _prefetch_pivots
- `bot/loops/ml_loop.py` — ml_training_loop + weekly_report_loop
- `bot/loops/trade_tracker.py` — trade_tracker_loop
- `bot_with_subscriptions.py` — только точка входа (75 строк)
- `bot/monitoring.py` — фильтры + фоновые проверки + broadcast (765 строк)

### [ARCH-02] Этап 8: Рефакторинг trading_intelligence.py
**Агент:** Architect
**Приоритет:** Высокий
**Описание:**
Разбить 1850+ строк:
- `core/intelligence/signal_aggregator.py` — _analyze_signals_advanced
- `core/intelligence/confidence_calculator.py` — _calculate_advanced_confidence
- `core/intelligence/recommendation_generator.py` — _generate_recommendation
- `core/intelligence/ml_enhancer.py` — _enhance_analysis_with_ml

### [DEV-01] Этап 9: core/structure_detector.py
**Агент:** Developer
**Приоритет:** Средний
**Зависимость:** После ARCH-01 завершён
**Описание:**
Создать детектор SMC структуры:
- `detect_swing_highs_lows(df)` → список пиков/впадин
- `detect_choch(highs, lows)` → Change of Character
- `detect_bos(highs, lows)` → Break of Structure
- Интеграция в signal_checkers.py как новый тип сигнала

### [DEV-02] Тесты для signal_checkers.py
**Агент:** Developer
**Приоритет:** Средний
**Описание:**
`tests/unit/test_signal_checkers.py` уже существует — дополнить тестами:
- check_wt_signals с мок данными OS/OB зон
- check_anomaly_signals при volume spike
- check_divergence_signals (bullish/bearish)

### [DEV-03] ✅ Тесты для divergence_detector.py — ГОТОВО
Реализовано 15.03.2026 (коммит 14e6626):
- tests/unit/test_divergence_detector.py (новый файл, 306 строк)
- Hidden bull/bear zone фильтры, ind_change знаки, cascade bonus все уровни
- 16 passed, 6 skipped

---

## ✅ ГОТОВО (Done)

| ID | Описание | Коммит |
|----|----------|--------|
| — | Этап 7: RPredictor интеграция | 7c7310e |
| — | Разделение порогов min_strength | ff407d4 |
| — | /settings полный дашборд | 00b5ef1 |
| — | /settings сброс на defaults | 80572c0 |
| — | conflict_ratio баг-фикс (0.15→0.05) | bddb51b |
| — | Kelly sizing в TG-алертах | bddb51b |
| — | RPredictor MIN_SAMPLES 100→75 | bddb51b |

---

## 📏 Правила

1. **Не редактировать один файл одновременно** — договариваться через этот файл
2. Architect задаёт архитектуру → Developer реализует
3. Каждая задача = отдельный git commit с внятным сообщением
4. После реализации — Architect делает `git diff HEAD~1` и пишет review здесь
