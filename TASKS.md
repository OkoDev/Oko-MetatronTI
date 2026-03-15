# 📋 TASKS — Координация агентов

Файл координации между Architect (yogoru) и Developer (oko.webdev).

**Workflow:** Architect создаёт задачу → Developer берёт в работу → Architect делает review

---

## 🔥 В РАБОТЕ (In Progress)

### [DEV-WT-B-1] ✅ wt_b_signal — реализация и запуск — ГОТОВО
Реализовано 15.03.2026 (сессия WT-B):
- `core/signal_models.py` — `WT_B_SIGNAL = "wt_b_signal"`
- `core/signal_checkers.py` — `check_wt_b_signals(symbol, df_1h)`:
  - CrossUP/DOWN ВО время нахождения WT в OS/OB (adaptive p10/p90)
  - Дивергенция: второй лоу выше первого (для LONG) — разрыв `div_strength` 3-20
  - div_strength > 20 = АНТИСИГНАЛ (WR=33%), фильтруется
  - Strength: 70 (div 3-6) / 80 (div 6-10) / 90 (div 10-20) + бонус +5 если depth < -70
  - confidence=0.88, timeframe="1h"
- `core/trading_intelligence.py` — вес 0.15, маппинг, asyncio.gather
- `config.yaml` — секция `analysis.wt_b: enabled/div_min/div_max/lookback`
- `core/trade_simulator.py` — приоритетный список signal_type (bug-fix):
  `wt_b_signal > mtf_bias > confluence > pivot_reversal > smc_structure > wt_signal > divergence > trend_signal > anomaly > mtf_signal`

**Бэктест:** 103 пары, 180 дней, 1h: n=59, WR=84.9%, avgRet=+4.82% при div_strength 3-20.

---

### [DEV-WT-B-2] 4h подтверждение к wt_b_signal (отложено)
**Агент:** Developer
**Приоритет:** Средний
**Статус:** 🕐 ЖДЁТ накопления 10+ реальных wt_b сделок

**Суть:** Если WT 4h в OS/OB зоне (adaptive p10/p90) в момент сигнала → `strength += 10`, `data["cascade_4h"] = True`.

**Бэктест:** wt_b + 4h OS/OB → WR=87.2% (vs 78.6% без 4h подтверждения).

**Что нужно сделать:**
1. В `trading_intelligence.py` — загрузить `df_4h` в asyncio.gather (~строка 512)
2. В `check_wt_b_signals(symbol, df_1h, df_4h=None)` — добавить параметр
3. Если 4h WT (adaptive p10/p90) в OS/OB → `strength = min(95, strength + 10)`, `data["cascade_4h"] = True`

**Не делать** пока не накопится 10+ реальных wt_b сделок.

**Файлы:** `core/signal_checkers.py`, `core/trading_intelligence.py`

---

### [ARCH-05] ✅ Интеграция Strategy Pattern в TradingIntelligence — ГОТОВО
**Агент:** Architect
**Дата:** 15.03.2026
- `trading_intelligence.py.__init__`: `self.strategy` + `self.strategies` — загрузка из `trading.active_strategy` / `trading.active_strategies`
- `analyze_symbol()` делегирует в `self.strategy.analyze()` с legacy-fallback; `_run_all_strategies()` — параллельный запуск через asyncio.gather
- Исправлен баг: `logger` использовался до определения (в except ImportError)
- `config.yaml`: добавлен `strategy_name: confluence` (верхний уровень)
- `tests/unit/test_strategy_pattern.py`: 22 regression-теста — все прошли
  - Registry, ConfluenceStrategy, ConservativeStrategy, MTFBiasStrategy, ConfluenceScannerStrategy, TradingIntelligence._run_strategy/_run_all_strategies

---


### [ARCH-04] ✅ Адаптивный выбор стратегии по режиму рынка — ГОТОВО
Реализовано 15.03.2026:
- `core/regime_strategy.py` — `RegimeParams`, `get_regime_params()`, `apply_regime_to_strategy()`
- TREND_UP/DOWN → `min_strategy_type=TRIPLE_TP_TSL`, `sl_factor=0.85`
- RANGE → `max_strategy_type=DUAL_TP`, `sl_factor=1.15`
- HIGH_VOL → `position_size_multiplier=0.5`, `tp1_r=0.5` (TP1 при 0.5R немедленно)
- `core/trade_simulator.py`: после расчёта strategy_type по RR применяется `apply_regime_to_strategy()`; `position_size_multiplier` пишется в `features_json`
- `config.yaml`: секция `risk_management.regime_strategy` со всеми параметрами + `enabled: true`
- `tests/unit/test_regime_strategy.py`: 14 тестов, все прошли

---

### [ARCH-08] ✅ Backtesting Workflow — быстрая проверка изменений — ГОТОВО
Реализовано 15.03.2026:
- `test_indicators.py`: удалён несуществующий `AnomalyDetector`, `detect_divergences` → `check_divergence_signals` / `check_anomaly_signals`
- `backtesting_engine.py`: `check_pivot_signals()` подключён в `detect_signals()` (всегда)
- `backtesting_engine.py`: `confluence_scanner` теперь запускается всегда (флаг `use_confluence=True`)
- `backtesting_engine.py`: `calculate_metrics()` — добавлена метрика `max_consecutive_sl` и разбивка по типам сигналов
- `backtesting_engine.py`: `BacktestConfig.train_pct=0.7`, `run_backtest()` возвращает `in_sample_metrics` + `out_of_sample_metrics` + `signal_split`
- `strategy_comparison.py`: исправлен сломанный `print_comparison_table` (были литералы `"<15"`)
- CLI: `python backtesting_engine.py --scenario quick_test` — читает `backtest_config.yaml`, выводит IS/OOS таблицу по типам сигналов

---

### [ARCH-03] ✅ State Machine для confluence (Шаг 2) — ГОТОВО
Реализовано 15.03.2026:
- `core/confluence_state_machine.py` — новый модуль, класс `ConfluenceStateMachine`
- Состояния: IDLE → WT_ZONE → TSL_CROSS → NEAR_PIVOT → DIVERGENCE → SIGNAL
- Таймаут 48h, сброс в IDLE при входе WT в противоположную зону
- SQLite `confluence_states` таблица: persist + load_from_db()
- Флаг в конфиге: `analysis.confluence.use_state_machine: true` (fallback → lookback scanner)
- `bot/core/bot.py`: `self.confluence_sm = ConfluenceStateMachine(db_path=...)` + load_from_db()
- `bot/loops/scan_loop.py`: scan_one() использует SM если use_state_machine=true
- `tests/unit/test_confluence_state_machine.py`: 15 тестов (state transitions, timeout, SQLite)

---

### [ARCH-07] ✅ Quality Gate — консистентность пайплайна — ГОТОВО
Реализовано 15.03.2026:

**8.4.2 — Единый snapshot_time:**
- `bot/loops/scan_loop.py` → `scan_one()`: `snapshot_time = datetime.now()` фиксируется до параллельного gather OHLCV — все данные по паре привязаны к одному моменту
- `core/trading_intelligence.py` → `analyze_symbol()`: `snapshot_time` уже был, перенесён до сбора сигналов; сохраняется в `recommendation.metadata["snapshot_time"]`

**8.4.2 — No silent fallback (hard block):**
- `_collect_all_signals()`: `df_1h is None → return (None, quality)` → `analyze_symbol()` → `return None` (без тихого пропуска)
- 15m quality check: `check_ohlcv_quality` fail → `return (None, quality)` → hard block

**8.4.3 — Hard vs Soft timeouts + analysis_quality:**
- `_collect_all_signals()` теперь возвращает `(signals, quality)` tuple вместо `Optional[List]`
  - `quality = "full"` — все 6 детекторов завершились без ошибок
  - `quality = "degraded"` — один или несколько детекторов упали (`return_exceptions=True`), но сигналы частично собраны
- `analyze_symbol()`:
  - **HARD timeout** (20s) на `_collect_all_signals` → `return None` (блокирует решение)
  - **SOFT timeout** (15s) на `_get_market_context` → деградирует quality до "degraded", fallback-контекст, анализ продолжается
  - `recommendation.metadata["analysis_quality"] = collect_quality` — маркируется в каждой рекомендации
  - Логирование `INFO` при `analysis_quality != "full"`
- `tests/unit/test_quality_gate.py`: 8 тестов — все прошли
  - returns (signals, quality) tuple, hard block on missing 1h, degraded when checker fails, full when all succeed
  - pre_collected → full, degraded propagates, hard block → analyze=None, snapshot_time valid ISO

---

### [DEV-04] ✅ Confluence Scanner — Lookback (Шаг 1) — ГОТОВО
Реализовано 09.03.2026:
- `core/confluence_scanner.py` — новый модуль, 5 факторов, score 0-100
- `core/signal_models.py` — добавлен `SignalType.CONFLUENCE`
- `core/trading_intelligence.py` — вес 0.35, в _SIGNAL_TYPE_MAP
- `bot/monitoring.py` — интеграция в scan_one() после MTF signals

---

### [ARCH-09] Разделение пайплайнов: разворот vs тренд
**Агент:** Architect
**Приоритет:** Высокий
**Статус:** 🕐 ЖДЁТ (быстрые фиксы уже в коде, нужна полная архитектура)
**Контекст:** 16.03.2026 — найдена причина "стало меньше сделок"

**Корень проблемы:**
1. `use_state_machine: true` — State Machine требует 5 последовательных состояний. Большинство разворотов не проходят → нет CONFLUENCE → ConfluenceScannerStrategy возвращает None → legacy
2. В legacy: `signal_count_factor = effective_count/5.0` → при 1 сигнале = 0.2 → confidence=0.14 < 0.55 → WATCH → сделки нет

**Уже сделано (быстрые фиксы 16.03.2026):**
- `config.yaml`: `use_state_machine: false` — lookback scanner вместо State Machine
- `confidence_calculator.py`: `signal_count_factor = min(0.5 + effective_count/10.0, 1.5)` — минимум 0.5 при 1 сигнале

**Архитектурная задача:**
Новые стратегии:
- `ReversalStrategy` — WT_SIGNAL, WT_B_SIGNAL, PIVOT_REVERSAL; confidence от самого сигнала, без штрафа по count
- `TrendFollowingStrategy` — TREND_SIGNAL, MTF_BIAS, SMC_STRUCTURE; требует ≥2 подтверждений
- Оба параллельно, лучший по strength идёт в TG

**Файлы:** `strategies/built_in/`, `core/intelligence/confidence_calculator.py`

---

## 📥 ОЧЕРЕДЬ (Backlog)

### [ARCH-08] ~~Backtesting Workflow~~ → ГОТОВО (см. В РАБОТЕ выше)
**Агент:** Architect
**Приоритет:** Высокий
**Описание:**
Нужен рабочий workflow: "изменил параметр/фильтр → запустил бэктест → увидел результат по каждому типу сигнала".

**Текущее состояние (анализ 15.03.2026):**
- `backtesting_engine.py` — 70-80% готов, использует реальные детекторы из `core/`
- `strategy_comparison.py` — работает, разбивка по сигналам есть, таблица вывода сломана (`"<15"`)
- `test_indicators.py` — НЕ ЗАПУСКАЕТСЯ: импортирует удалённый `AnomalyDetector`
- `backtest_config.yaml` — скелет, параметры не читаются из YAML

**Что отсутствует критично:**
1. `confluence_scanner` не вызывается в основном цикле бэктеста (только при `strategy="confluence_scanner"`)
2. `check_pivot_signals()` импортирован но не вызывается в `detect_signals()`
3. **In-sample / out-of-sample разделение** — полностью отсутствует (главная дыра)
4. `market_regime` не применяется (поле `regime` всегда None в BacktestTrade)

**Задачи Архитектора:**

**1. Починить test_indicators.py:**
- Заменить `from core.anomaly_detector import AnomalyDetector` → использовать `check_anomaly_signals` из `signal_checkers`
- Обновить `DivergenceDetector.detect_divergences()` → новый интерфейс

**2. Подключить всё в backtesting_engine.py:**
- `check_pivot_signals()` → добавить в `detect_signals()` (строки ~405-413)
- `confluence_scanner.scan_confluence()` → вызывать всегда, не только при `strategy="confluence_scanner"`
- `MarketRegimeClassifier.classify_from_ohlcv()` → заполнять поле `regime` в BacktestTrade

**3. In-sample / out-of-sample разделение:**
- Параметр `train_pct: 0.7` в BacktestConfig (70% данных = обучение, 30% = валидация)
- Результаты выводить отдельно: `in_sample_metrics` и `out_of_sample_metrics`
- Walk-forward уже есть — убедиться что работает корректно

**4. Читать `backtest_config.yaml`:**
- Реализовать парсинг сценариев `quick_test` / `full_test` / `stress_test`
- `quick_test`: 1 пара (BTC), 30 дней, только confluence+wt
- `full_test`: топ-10 пар, 90 дней, все сигналы
- CLI: `python backtesting_engine.py --scenario quick_test`

**5. Результаты по типам сигналов — улучшить вывод:**
Таблица в консоли:
```
Тип сигнала    | Сделок | WR%  | Avg R | Серия SL | In-sample | Out-of-sample
confluence     |   120  | 38%  | +0.8  |    7     |   +0.9R   |    +0.7R
wt_signal      |    85  | 31%  | +0.5  |   12     |   +0.6R   |    +0.4R
pivot_reversal |    45  | 42%  | +1.1  |    5     |   +1.2R   |    +0.9R
```

**6. Метрика "максимальная серия SL"** — добавить в `calculate_metrics()` и в вывод.

**Цель:** после изменения параметра запускаем `python backtesting_engine.py --scenario quick_test` и за 2-3 минуты видим — стало лучше или хуже, и по какому типу сигнала.

**Файлы:**
- `backtesting_engine.py`
- `strategy_comparison.py`
- `test_indicators.py`
- `backtest_config.yaml`

---

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

### [DEV-05] ✅ Умный выбор SL (структурный) — ГОТОВО
Реализовано 14.03.2026 (коммит 8e5ff4a):
- core/intelligence/recommendation_generator.py: новый приоритет SL:
  1) S1/R1 pivot из PIVOT_REVERSAL сигналов (data["level"] + data["pivot_type"])
  2) FVG midpoint из data["fvg_entry"] (PIVOT_REVERSAL bonus data)
  3) TSL-линия (trendup/trenddown)
  4) ATR/volatility fallback
- Убран SWING шаг (заменён S1 структурным пивотом)
- config.yaml: sl_min_pct 1.0 → 0.5, sl_max_pct 2.0 → 3.0

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

### [ARCH-03] ~~State Machine для confluence~~ → ГОТОВО

### [ARCH-04] Адаптивный выбор стратегии по режиму рынка
**Агент:** Architect
**Приоритет:** Низкий
**Статус:** 🔄 В работе (15.03.2026)

### [ARCH-01] ✅ Этап 8: Рефакторинг bot_with_subscriptions.py — ГОТОВО
Реализовано 14.03.2026 (коммит b4768ca):
- `bot/core/bot.py` — TradingAlertBot класс
- `bot/loops/scan_loop.py` — scan_all_pairs + monitor_market + _prefetch_pivots
- `bot/loops/ml_loop.py` — ml_training_loop + weekly_report_loop
- `bot/loops/trade_tracker.py` — trade_tracker_loop
- `bot_with_subscriptions.py` — только точка входа (75 строк)
- `bot/monitoring.py` — фильтры + фоновые проверки + broadcast (765 строк)

### [ARCH-02] ✅ Этап 8: Рефакторинг trading_intelligence.py — ГОТОВО
Реализовано 14.03.2026 (коммит b82214a):
- `core/intelligence/signal_aggregator.py` — analyze_signals_advanced, calculate_adaptive_weighted_strength
- `core/intelligence/confidence_calculator.py` — calculate_advanced_confidence
- `core/intelligence/recommendation_generator.py` — generate_recommendation, determine_risk_level, generate_reasoning, calculate_levels
- `core/intelligence/ml_enhancer.py` — enhance_analysis_with_ml, apply_ml_corrections
- trading_intelligence.py: 1536 → 1061 строк, методы стали тонкими делегатами

### [DEV-01] ✅ Этап 9: core/structure_detector.py — ГОТОВО
Реализовано 15.03.2026 (коммит 02c8e4b):
- detect_swing_highs_lows(), detect_choch(), detect_bos(), detect_structure()
- Делегирует в indicators.find_swing_highs/lows (единый источник)
- BOS > CHoCH по приоритету, strength 55/65
- 25/25 тестов passed

### [DEV-01b] ✅ Интеграция SMC → signal_checkers.py — ГОТОВО
Реализовано 14.03.2026 (коммит 17cb938):
- core/signal_models.py: SignalType.SMC_STRUCTURE = "smc_structure"
- core/signal_checkers.py: check_smc_signals(symbol, df) — вызывает detect_structure()
  BOS → strength=65, confidence=0.75; CHoCH → strength=55, confidence=0.65
- core/trading_intelligence.py: SMC_STRUCTURE вес 0.12 + _SIGNAL_TYPE_MAP

### [DEV-01c] ✅ Восстановление check_divergence_signals / check_pivot_signals — ГОТОВО
Реализовано 14.03.2026 (коммит 1d078f2):
- check_divergence_signals(symbol, df): DivergenceDetector sync → SignalData(DIVERGENCE)
- check_pivot_signals(symbol, df): max(high)/min(low) 60 баров → SignalData(PIVOT_REVERSAL)
- tests/unit/test_signal_checkers.py: убраны заглушки, тесты проходят

### [DEV-02] ✅ Тесты для signal_checkers.py — ГОТОВО
Реализовано 15.03.2026 (коммит be85635):
- check_wt_signals: OS crossover форсированный, df_1h=None/df фильтр (47 тестов total)
- check_divergence_signals: bullish сценарий, NaN данные, граничные 100 баров
- check_pivot_signals: near resistance SHORT, near support LONG, far from levels
- fix: PIVOT_ALERT→PIVOT_REVERSAL в strategies/built_in/
- fix: SignalData timestamp/data обязательные поля в test_strategies.py
- 231/231 passed

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
| ARCH-06 | tsl_activated UPDATE + 1h TSL логика | (уже в коде) |

---

## 📏 Правила

1. **Не редактировать один файл одновременно** — договариваться через этот файл
2. Architect задаёт архитектуру → Developer реализует
3. Каждая задача = отдельный git commit с внятным сообщением
4. После реализации — Architect делает `git diff HEAD~1` и пишет review здесь
