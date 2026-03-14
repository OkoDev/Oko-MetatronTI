# ROADMAP — Oko MTF Bot

Документ прогресса: от текущего состояния к самообучающейся торговой системе.

---

## ✅ Этап 1 — Trade Simulator (фундамент)
- TradeSimulator: регистрация сделок, SL/TP трекинг по OHLC
- R_multiple, profit_pct, duration_minutes
- Статусы: OPEN / TP / SL / EXPIRED (48ч)
- При одновременном hit SL+TP в одной свече — победа того, кто ближе к open

## ✅ Этап 2 — TTL кеш OHLCV
- Timeframe-dependent TTL в `data_collector.py`
- Снижение API-запросов с ~1150 до ~300 в цикл
- TTL: 1m=15с, 3m=30с, 5m=45с, 15m=60с, 45m=120с, 1h=180с, 4h=300с, 1d=600с

## ✅ Этап 3 — Веб-дашборд
- `web/dashboard_server.py`, порт 8000
- `/` HTML-сводка, `/api/stats` JSON endpoint
- `core/performance_engine.py` — агрегирует статистику из simulated_trades
- Автозапуск вместе с ботом через `asyncio.create_task`

## ✅ Этап 4 — Market Regime + ML + Пивоты

### 4.1 — Market Regime
- `core/market_regime.py`: MarketRegimeClassifier (ADX + ATR + EMA)
- Режимы: TREND_UP / TREND_DOWN / RANGE / HIGH_VOL
- Запись `regime` в `simulated_trades` через `register_trade_async()`

### 4.2 — ML OutcomePredictor + Адаптивные веса
- `core/outcome_predictor.py`: RandomForest(200 деревьев), CV AUC ≈ 0.56
- 12 признаков: strength, confidence, direction, signal_type(3), volatility, price_change, regime(4)
- Блендинг confidence = 0.7×orig + 0.3×P(win) в TradingIntelligence
- Адаптивные веса: `new_weight = base × clamp(1 + avg_R × 0.4, 0.5, 2.0)`

### 4.3 — Фиксированные пивоты (period-based кеш)
- `core/pivot_calculator_fixed.py`: замена скользящего окна на UTC-периоды
- Месячные (1M), недельные (1W), дневные (1D) — фиксируются на весь период
- Конфлюэнции: 1M-1W, 1M-1D, 1W-1D

### 4.4 — MFE трекинг + user_settings (05.03.2026)
- `max_price`, `min_price` — накапливаются при каждой проверке открытых сделок
- `max_R_possible` — лучший достижимый R за время жизни
- `captured_R_pct` — процент захваченного потенциала (R_multiple / max_R_possible × 100%)
- Таблица `user_settings`: персональный депозит/плечо/риск% для каждого пользователя

## ✅ Этап 4.5 — Разделение слоёв (core/ vs bot/)
- `core/` — только бизнес-логика без aiogram (28 файлов)
- `bot/keyboards.py` + `bot/menus/` — весь UI-слой
- `bot_with_subscriptions.py` импортирует UI только из `bot/`

---

## ✅ Этап 5 — Веб-настройки стратегии (05.03.2026)
**Цель:** редактировать параметры бота без перезапуска через браузер

- Страница `/settings` (aiohttp): форма с текущими значениями из `config.yaml`
- Параметры анализа: volume_multiplier, price_threshold, check_interval, history_size
- Адаптивные веса сигналов — отображение из PerformanceEngine (read-only)
- Формула расчёта позиции: `Position = (Deposit × Risk%) / SL% × Leverage`
- Персональные настройки (депозит/плечо/риск%) — `/settings` в боте (user_settings)
- Hot-reload: `ConfigLoader.save_analysis()` → перезапись `config.yaml` → `reload()` без остановки бота
- Эндпоинты: `GET /settings`, `GET /api/settings`, `POST /api/settings`

## ✅ Этап 5.1 — Качество сигналов (06.03.2026)
**Цель:** убрать шум и дублирование

- Фильтр объёма: `min_volume_usd` — пары < порога не мониторируются (config.yaml)
- Фильтр мусорных пар: base asset длиннее 10 символов → пропустить
- Cooldown после SL: `sl_cooldown_hours` — пауза N часов перед новым сигналом по паре
- Дедупликация: `dedup_minutes` — один и тот же тип сигнала по одной паре не дублируется
- `min_strength` — сделка не регистрируется если `overall_strength < 50`
- `is_actionable`: регистрация только BUY/SELL + non-NEUTRAL direction
- INFO-лог с причиной пропуска сделки (strength/action/direction)

## ✅ Этап 5.2 — BTC-корреляционный фильтр (06.03.2026)
**Цель:** учитывать рыночный контекст при выдаче сигналов

- `_get_btc_regime(bot)` — кешированный режим BTC/USDT (TTL 5 мин, таймфрейм 1h)
- BTC HIGH_VOL → сигнал полностью пропускается
- BTC TREND_UP + SHORT направление → пропускается
- BTC TREND_DOWN + LONG направление → пропускается
- Фильтр применяется после AI-анализа в `_broadcast_intelligence_alert()`

## ✅ Этап 5.3 — Еженедельный отчёт в Telegram (06.03.2026)
**Цель:** пользователь видит итоги недели без ручных запросов

- `PerformanceEngine.weekly_summary(days_back=7)` — статистика за N дней
- `send_weekly_report(bot)` + `format_weekly_report(stats)` в `bot/monitoring.py`
- `_weekly_report_loop()` — asyncio задача, отправляет каждое воскресенье в 20:00 UTC

## ✅ Этап 6 — Динамический TP (pivot-based) (06.03.2026)
**Цель:** заменить фиксированный TP% на ближайший уровень пивота

- `PivotCalculatorFixed.get_pivot_tp(direction, entry, symbol, sl, min_r=1.5)` — без API-запросов, из кеша
- Выбирает ближайший пивот (1M/1W/1D) в направлении сделки с R >= 1.5
- Интеграция в `bot/monitoring.py` → `_broadcast_intelligence_alert()` перед регистрацией сделки
- `distance_to_pivot_pct` сохраняется в `features_json` — используется RPredictor (Этап 7)
- R теперь варьируется от 1.5 до 10+ в зависимости от структуры рынка

## ✅ Этап 7 — R-регрессор (Kelly-sizing)
**Цель:** ML-предсказание ожидаемого R → адаптивный размер позиции

- `core/r_predictor.py` создан: `RPredictor` с `GradientBoostingRegressor`
- 14 признаков: 12 базовых + `distance_to_pivot_pct` + режим рынка (4 one-hot)
- `kelly_fraction(win_rate, avg_r_win)` и `kelly_position_size(deposit, ...)` реализованы
- MIN_SAMPLES снижен 100→75 (обучение доступнее)
- Итог: `Position = Deposit × kelly_f × confidence`

## ✅ Этап 8.0 — Стабильный API-движок (07.03.2026)
**Цель:** устойчивость к сетевым сбоям и масштабируемость ×10-50

- `core/api_engine.py` — транспортный слой под `data_collector.py`:
  - `OhlcvCache` — LRU с ограниченным размером (maxsize=5000, evict oldest)
  - `CircuitBreaker` — CLOSED → OPEN (10 ошибок) → HALF_OPEN (30 сек пауза) → CLOSED
  - `ApiEngine` — retry × 3 + exponential backoff (NetworkError 1/2/4 сек, RateLimit 5/10/20 сек)
  - In-flight deduplication: один API-вызов для N одновременных запросов одного ключа
  - Централизованный `Semaphore(20)` — единственная точка ограничения параллелизма
- `data_collector.py` — `get_ohlcv`/`get_ticker` делегируют в ApiEngine (публичный интерфейс не меняется)
- `fetch_candles` — параллельный `asyncio.gather` вместо sequential for-loop (~10 мин → ~30 сек)
- `bot/monitoring.py` — `_analyze_sem = Semaphore(3)` для ограничения параллельных `analyze_symbol`
- `trading_intelligence.py` — `timeout=10.0` для `_collect_all_signals`

## ✅ Этап 8.1 — Критический фикс производительности скана (08.03.2026)
**Цель:** ускорить скан с 22-93 минут до приемлемых значений

**Корневые причины медленного скана (диагностика):**
1. `enableRateLimit: True` в ccxt — встроенный rate limiter сериализует ВСЕ запросы через один exchange-экземпляр (~1 запрос/сек), игнорируя asyncio-параллелизм. Эффект: 600 пар × 3 TF = 1800 запросов × 1 сек = **1800 сек = 30 мин**.
2. `fetch_candles()` — фоновая задача запускала 398 API-запросов каждые 60 сек через тот же Semaphore, конкурируя со сканом. При скане 5177 сек = 86 запусков × 398 = ~34 000 паразитных запросов.
3. Дивергенции: `scan_one` делал prefetch с `limit=150`, но `detect_divergence` запрашивал `limit=160` → cache miss на каждой паре.

**Исправления:**
- `core/data_collector.py`: `enableRateLimit: False` — ApiEngine.Semaphore(20) управляет параллелизмом сам (ускорение **44-186x**, скан 399 пар → **25-32 сек**)
- `bot/monitoring.py`: убран `fetch_candles()` из `monitor_market()`. `price_history`/`volume_history` обновляются из `df_15m` прямо в `scan_one` — без дополнительных API-вызовов
- `bot/monitoring.py`: prefetch в `scan_one` изменён на `limit=160` (совпадает с требованием divergence)
- `bot/monitoring.py`: BTC-фильтр переделан из жёсткой блокировки в мягкое предупреждение ⚠️ — сигналы против тренда BTC доставляются с пометкой, не дропаются
- `bot/monitoring.py`: ключ дедупликации изменён с `(symbol, signal_type)` на `symbol` — один алерт на пару за окно `dedup_minutes`
- Добавлены timing-логи: `[scan] OHLCV медленно %s: %.1fs`, `[scan] Пара медленно %s: total=%.1fs`

**Результат:**
| Метрика | До | После |
|---|---|---|
| Скан 399 пар | 1337-5617 сек | 25-32 сек |
| Скорость | ~1 пара/сек | ~15 пар/сек |
| Паразитные запросы | ~34 000/цикл | 0 |
| Пропущенные сигналы (BTC фильтр) | Все LONG при TREND_DOWN | Доставляются с предупреждением |
| Дубли TG-сообщений | 47/мин после рестарта | 1/пару/dedup_window |

## ✅ Этап 8.1.1 — Рефакторинг bot_with_subscriptions.py (ARCH-01, 14.03.2026)
- `bot/core/bot.py` — TradingAlertBot класс
- `bot/loops/scan_loop.py` — scan_all_pairs + monitor_market + _prefetch_pivots
- `bot/loops/ml_loop.py` — ml_training_loop + weekly_report_loop
- `bot/loops/trade_tracker.py` — trade_tracker_loop
- `bot_with_subscriptions.py` → только точка входа (75 строк)

## ✅ Этап 8.1.2 — Рефакторинг trading_intelligence.py (ARCH-02, 14.03.2026)
- `core/intelligence/signal_aggregator.py` — analyze_signals_advanced
- `core/intelligence/confidence_calculator.py` — calculate_advanced_confidence
- `core/intelligence/recommendation_generator.py` — generate_recommendation, calculate_levels
- `core/intelligence/ml_enhancer.py` — enhance_analysis_with_ml
- trading_intelligence.py: 1536 → 1061 строк

## ✅ Этап 8.1.3 — SL/TP система (14-15.03.2026)
- DEV-05: Структурный SL — приоритет S1/R1 pivot → FVG midpoint → TSL-линия → ATR fallback
- DEV-06: RR-фильтр перед регистрацией (RR ≥ 2.0 → skip + INFO лог)
- DEV-07: Частичные TP — TRIPLE_TP_TSL (RR≥3), DUAL_TP (RR∈[2,3)), SINGLE (прочее)
- trекинг tp2/tp3 hit в check_open_trades_with_tsl()
- 7 новых тестов TestRRFilter, 6 тестов TestStrategyType

## ✅ Этап 9 — SMC (Smart Money Concepts) базовая реализация (14-15.03.2026)
- `core/structure_detector.py` — detect_swing_highs_lows, detect_choch, detect_bos, detect_structure
- BOS > CHoCH по приоритету; strength: BOS=65, CHoCH=55
- `core/signal_checkers.py` — check_smc_signals() → SignalData(SMC_STRUCTURE)
- `core/signal_models.py` — SignalType.SMC_STRUCTURE
- 25/25 тестов в test_structure_detector.py
- Восстановлены check_divergence_signals / check_pivot_signals после рефакторинга ARCH-02

## 🔲 Этап 8.2 — Масштабирование архитектуры
**Цель:** готовность к >100 пользователям

- Разбить `bot_with_subscriptions.py` (1540+ строк) на обработчики в `bot/handlers/`
- Разбить `trading_intelligence.py` (1850+ строк) на `core/signals/` + `core/ml/`
- SQLAlchemy ORM → переход на PostgreSQL займёт 1 день при наличии прослойки
- WebSocket klines через `ccxt.pro` (Phase 2 ApiEngine) — REST только для исторических данных

## 🔲 Этап 8.3 — Рефакторинг архитектуры меню TG
**Цель:** устойчивая к изменениям система меню без text-based маршрутизации

**Текущие проблемы (задокументированы 09.03.2026):**
- Text-based роутинг через 9 frozenset'ов — хрупкий, уникальность держится только на эмодзи
- При добавлении кнопки нужно менять 3 места: ReplyKeyboard + frozenset + if-elif (легко пропустить)
- `current_menu` / `menu_stack` в MenuHandler — мёртвый код, не используется для маршрутизации
- 4 пары дублированных ReplyKeyboard/InlineKeyboard (ai, signals, risk, history)
- Inline-клавиатуры создаются но callback-обработчики могут быть не подключены

**План рефакторинга:**
- Перейти на FSM-состояния для текущего меню (MenuStates.main/signals/pivots/etc.)
- `F.text & StateFilter(MenuStates.signals)` вместо frozenset-детектора
- Удалить мёртвые `current_menu` / `menu_stack` из MenuHandler
- Объединить дублированные ReplyKeyboard/InlineKeyboard или удалить Inline-версии
- Проверить и подключить все callback_data обработчики

**Условие старта:** нет срочности, запускать при добавлении нового раздела меню

## 🔲 Этап 8.4 — Quality Gate до принятия сделки
**Цель:** повысить качество входов и снизить ложные регистрации до отправки в TG/БД

### 8.4.1 — Блокер: целостность данных перед анализом
- [ ] Ввести pre-check на свежесть OHLCV по каждому TF (`age`, пропуски, дубликаты)
- [ ] Пропускать сигнал, если не хватает минимальной глубины истории для конкретного детектора
- [ ] Логировать причину skip в едином формате (`symbol`, `tf`, `reason`, `timestamp`)

### 8.4.2 — Блокер: консистентность пайплайна принятия решения
- [ ] Синхронизировать пороги `is_actionable` и `should_register` (единая policy-таблица)
- [ ] Зафиксировать единый `snapshot_time` данных для всех проверок одного сигнала
- [ ] Запретить регистрацию сделки при частичном падении критичных шагов анализа (no silent fallback)

### 8.4.3 — Высокий приоритет: таймауты и degraded-mode
- [ ] Разделить таймауты на `hard` (блокирует решение) и `soft` (допускает решение)
- [ ] Явно маркировать degraded-решения в TG/БД (`analysis_quality=degraded`)
- [ ] Добавить счётчики SLA: `% full-analysis`, `% degraded`, `% timeout by step`

### 8.4.4 — Высокий приоритет: дедуп и конкуренция сигналов
- [ ] Перейти на dedup-ключ, учитывающий `symbol + side + class`, а не только `symbol`
- [ ] Разрешить замену слабого сигнала более сильным внутри dedup-окна
- [ ] Добавить правило `latest-confirmation wins` для конкурирующих сигналов по одной паре

### 8.4.5 — Высокий приоритет: рыночный контекст
- [ ] Ужесточить фильтрацию hidden-divergence в `RANGE/HIGH_VOL`
- [ ] Добавить коэффициент корреляционного риска с BTC (не только warning)
- [ ] Ввести kill-switch на экстремальной волатильности рынка

### 8.4.6 — Средний приоритет: качество признаков и калибровка
- [ ] Проверить стабильность распределений фичей по неделям (data drift)
- [ ] Калибровать `confidence` на реальных исходах (reliability curve)
- [ ] Валидировать вклад каждого типа сигнала в итоговый `R` (ablation)

### 8.4.7 — Средний приоритет: наблюдаемость и аудит решений
- [ ] Сделать `decision trace` для каждой сделки: какие фильтры прошли/не прошли
- [ ] Добавить дашборд причин отказа (top skip reasons)
- [ ] Вести метрику latency от детекта до регистрации/рассылки

### 8.4.8 — Средний приоритет: тестовый контур качества сигналов
- [ ] Набор replay-тестов на исторических окнах для всей цепочки от сигнала до решения
- [ ] Регрессионные тесты на пограничные режимы (тонкий рынок, новости, флет)
- [ ] Canary-режим: сравнение старой и новой policy без реального влияния на рассылку

### 8.4.9 — Операционный контроль (постоянно)
- [ ] Еженедельный review: win rate, avg R, captured R%, false-positive ratio
- [ ] Авто-алерт при деградации метрик ниже порога
- [ ] Формальный changelog policy: каждое изменение фильтров с гипотезой и KPI проверки

**Definition of Done (Этап 8.4):**
- [ ] Нет silent fallback при критичных ошибках анализа
- [ ] Все skip/timeout причины наблюдаемы в логах и дашборде
- [ ] Доля degraded-решений контролируется SLA и не растёт без алерта
- [ ] Качество входов стабильно улучшается по weekly review метрикам

## 🔲 Этап 8.5 — Strategy Pattern Refactoring
**Цель:** вынести торговые решения в модульную архитектуру для легкого добавления новых стратегий и A/B тестирования

### 8.5.1 — Архитектура (Strategy Pattern + Registry)
**Структура папок:**
```
strategies/
├── __init__.py
├── base.py                    ← BaseStrategy interface (analyze, calculate_sl_tp, backtest)
├── built_in/
│   ├── confluence.py          ← текущая логика (2+ сигнала, адаптивные веса, ML)
│   ├── mtf_bias.py            ← новая быстрая стратегия (только MTF alerts)
│   ├── conservative.py        ← консервативная (узкий SL atr*0.7, для минимизации DD)
│   └── __init__.py
├── rule_based.py              ← RuleEngine для config-driven стратегий (Phase 2.1)
└── registry.py                ← фабрика get_strategy(name, config), list_strategies()
```

**BaseStrategy интерфейс:**
```python
class BaseStrategy(ABC):
    def analyze(signals: List[SignalData], market_context: MarketContext) → TradingRecommendation
    def calculate_sl_tp(entry, direction, atr, context) → (sl, tp, position_size)
    def backtest(ohlcv_data, pairs) → {symbol: {signals, win_rate, avg_r}}
```

- [ ] Создать `strategies/base.py` с интерфейсом
- [ ] Создать `strategies/registry.py` с фабрикой и STRATEGY_REGISTRY
- [ ] Реализовать ConfluenceStrategy: перенос логики из `_analyze_signals_advanced()` + `_generate_recommendation()` (~200 строк)
- [ ] Реализовать MTFBiasStrategy и ConservativeStrategy: примеры простых стратегий (~50-100 строк каждая)

### 8.5.2 — Интеграция в TradingIntelligence
- [ ] Инициализировать стратегию в `__init__`: `self.strategy = get_strategy(config["strategy.name"])`
- [ ] Делегировать `_analyze_signals_advanced()` → `self.strategy.analyze()`
- [ ] Делегировать `_generate_recommendation()` → логика внутри `strategy.analyze()`
- [ ] Рефактор `trade_simulator.py`: параметризовать SL/TP, вынести в `calculate_sl_tp()` (опционально на Phase 2)
- [ ] Тестирование: ConfluenceStrategy должна выдавать идентичные результаты текущей логике (regression test)

### 8.5.3 — Config и переключение стратегий
- [ ] Добавить в `config.yaml` секцию для выбора стратегии
- [ ] Hot-reload: `ConfigLoader.save()` переуспешивает config → `bot.strategy = get_strategy()` без перезапуска
- [ ] GET дашборда: `/api/strategies` → список всех + текущая + метрики win_rate по каждой
- [ ] POST дашборда: `/api/strategies/switch/{name}` → переключить в DEMO-режиме, логировать смену

### 8.5.4 — A/B тестирование и бэктестинг
- [ ] Расширить `strategy_comparison.py`: сравнение всех стратегий из registry
- [ ] Добавить unit-тесты в `tests/test_strategies.py` (параметризованные по registry)
- [ ] Вывод таблицы: Strategy | Win Rate | Sharpe | Avg R | Max DD
- [ ] Production: установить `strategy.name = "confluence"` + disable переключения

### 8.5.5 — Phase 2.1 (future): Rule Engine для экспериментов
- [ ] Реализовать `RuleEngine` в `strategies/rule_based.py` — интерпретирует YAML правила
- [ ] Фабрика: `if config.type == "rule": strategy = RuleEngine(config)`

### 8.5.6 — Phase 2.2 (future): Ensemble стратегий
- [ ] EnsembleStrategy: запускает N стратегий, голосует (majority или weighted)
- [ ] Use case: production-safety (2 из 3 согласны → BUY)

**Definition of Done (Этап 8.5):**
- [ ] ConfluenceStrategy дублирует текущее поведение: win_rate/sharpe совпадают (regression)
- [ ] Можно добавить новую стратегию одним файлом (~50-200 строк) + одна строка в registry
- [ ] Все стратегии могут сравниваться через strategy_comparison.py
- [ ] Дашборд показывает список доступных и позволяет переключить (DEMO-only)
- [ ] Тесты параметризованы по всем стратегиям в registry

---

## 🔲 Этап 9 — SMC (Smart Money Concepts)
**Цель:** стратегия на основе структуры рынка — вход после слома структуры на откате 0.618

- `core/structure_detector.py` — детектор Swing High/Low на ценовом графике
- CHoCH (Change of Character) — первый слом структуры = сигнал разворота
- BOS (Break of Structure) — пробой предыдущего swing = подтверждение направления
- Order Block — последняя свеча импульса перед BOS (зона входа/SL)
- Fibonacci 0.618 — зона входа на откате от импульса (BOS → коррекция → 0.618 → вход)
- Confluence с FVG (уже есть в `core/indicators.py`) и пивот уровнями (Этап 6)
- Новый `signal_type = "smc_signal"` с весом ~0.25 в TradingIntelligence
- **Условие старта:** после Этапа 7 — ML валидирует реальную ценность SMC vs текущих стратегий

---

## Метрики прогресса

| Метрика | Сейчас | Цель (Этап 7) |
|---------|--------|----------------|
| Сделок в БД | 226+ | 500+ |
| Win rate | 43.3% | > 50% |
| avg_R (win) | 2.0 | > 3.0 (dynamic TP) |
| CV AUC (OutcomePredictor) | 0.56 | > 0.65 |
| avg captured_R_pct | — | > 60% |
| Пар в мониторинге | 600+ | — |

---

## История обновлений

| Дата | Изменение |
|------|-----------|
| 2025-03-01 | Этап 1: simulated_trades, trade_simulator, интеграция в бота |
| 2026-03-04 | Этапы 2–4.3: кеш OHLCV, дашборд, Market Regime, ML, пивоты |
| 2026-03-05 | Этап 4.4: MFE трекинг, user_settings |
| 2026-03-05 | Этап 4.5: подтверждено разделение core/ (бизнес) vs bot/ (UI) |
| 2026-03-05 | Этап 5: веб-настройки /settings, hot-reload config.yaml |
| 2026-03-06 | ML: исправлен cold-start (joblib вне try/except, stub MLPClassifier, 1-class guard) |
| 2026-03-06 | Этап 5.1: фильтры качества (cooldown, dedup, min_strength, volume, is_actionable) |
| 2026-03-06 | Унификация сообщений: tv_link во всех типах, символ без :USDT, strength целым числом |
| 2026-03-06 | Дашборд: tvUrl/symLink в таблицах, aiohttp.access → WARNING |
| 2026-03-06 | Прогрев кеша пивотов при старте (asyncio.gather + Semaphore=20, 600+ пар) |
| 2026-03-06 | Этап 5.2: BTC-корреляционный фильтр (HIGH_VOL + направление vs тренд) |
| 2026-03-06 | Этап 5.3: Еженедельный отчёт (weekly_summary + _weekly_report_loop каждое вс. 20:00) |
| 2026-03-06 | Этап 6: динамический TP (get_pivot_tp из кеша 1M/1W/1D, min_r=1.5) |
| 2026-03-06 | Этап 7 prep: core/r_predictor.py (GBR + Kelly), distance_to_pivot_pct в features_json |
| 2026-03-07 | Сканер: per-pair scan_all_pairs, prefetch limit=160, _analyze_sem=Semaphore(3) |
| 2026-03-07 | Этап 8.0: core/api_engine.py (LRU cache, CircuitBreaker, retry, in-flight dedup) |
| 2026-03-08 | Этап 8.1: enableRateLimit=False (скан 30 мин → 30 сек), убран fetch_candles(), BTC фильтр → предупреждение, dedup по паре |
| 2026-03-09 | Этап 8.4: добавлен подробный Quality Gate roadmap (9 подэтапов + DoD) |
| 2026-03-09 | Фикс: pivot TP применяется ДО форматирования сообщения; добавлен блок "📍 Ближайшие пивоты" в комплексный анализ |
| 2026-03-09 | Этап 8.4.1: core/data_quality.py — pre-check OHLCV (глубина/свежесть/NaN), интеграция в scan_one и _collect_all_signals |
| 2026-03-14 | ARCH-01: рефакторинг bot_with_subscriptions.py → bot/core/bot.py + bot/loops/ (75 строк точка входа) |
| 2026-03-14 | ARCH-02: рефакторинг trading_intelligence.py → core/intelligence/ (4 модуля, 1536→1061 строк) |
| 2026-03-14 | DEV-05: структурный SL (S1/R1 pivot → FVG → TSL → ATR), sl_min_pct 1.0→0.5, sl_max_pct 2.0→3.0 |
| 2026-03-14 | DEV-01b: check_smc_signals() в signal_checkers.py, SignalType.SMC_STRUCTURE, вес 0.12 |
| 2026-03-14 | DEV-01c: восстановлены check_divergence_signals / check_pivot_signals после ARCH-02 |
| 2026-03-15 | DEV-01: core/structure_detector.py (Swing H/L, CHoCH, BOS), 25/25 тестов |
| 2026-03-15 | DEV-06: RR-фильтр ≥2.0 перед регистрацией сделки, 7 тестов TestRRFilter |
| 2026-03-15 | DEV-07: Частичные TP (TRIPLE_TP_TSL/DUAL_TP), трекинг tp2/tp3, 6 тестов TestStrategyType |
| 2026-03-15 | DEV-03: тесты DivergenceDetector (hidden bull/bear, cascade, граничные условия), 16/16 passed |
| 2026-03-15 | DEV-02: дополнены тесты signal_checkers (WT OS/OB, divergence, pivot near levels), 47/47 passed |
| 2026-03-15 | fix: PIVOT_ALERT→PIVOT_REVERSAL в strategies/built_in/, fix SignalData fields в test_strategies.py |
| 2026-03-15 | Итого тестов: 231 passed, 11 skipped |
