## Язык
Thinking (думать) на русском языке. Документацию пиши на русском.

## Общение
После завершения задачи или подзадачи, кратко изложите, что вы сделали, что произошло и что дальше. Затем используйте команду `say` , чтобы прочитать это вслух.

---

## Проект: Oko MTF TG Bot

Telegram-бот для технического анализа крипторынка с симуляцией сделок и самообучением.
Биржа: BingX (через ccxt). Таймфрейм по умолчанию: 15m.

**Запуск:** `python bot_with_subscriptions.py`
**Дашборд:** `http://localhost:8000` — статистика, `http://localhost:8000/settings` — настройки (aiohttp, запускается автоматически с ботом)

**TSL (Trailing Stop Loss):** Включен по умолчанию, активируется после +1R прибыли. Следует за трендом для защиты профита.

---

## 🧪 **Система тестирования на исторических данных**

Проект включает комплексную систему бэктестинга для тестирования всех индикаторов и стратегий на реальных исторических данных.

### 📊 **Компоненты тестирования:**

#### **1. Backtesting Engine (`backtesting_engine.py`)**
Полноценный движок бэктестинга с:
- ✅ Загрузка исторических OHLCV данных
- ✅ Расчет всех индикаторов (тренд, WT, дивергенции, аномалии)
- ✅ Обнаружение торговых сигналов
- ✅ Симуляция сделок с TSL
- ✅ Расчет метрик производительности (Sharpe, Win Rate, Max DD)

#### **2. Indicator Tester (`test_indicators.py`)**
Тестирование отдельных индикаторов:
- ✅ **Трендовые индикаторы** — распределение трендов, TSL анализ
- ✅ **WT индикатор** — зоны OB/OS, сигналы пересечения
- ✅ **Дивергенции** — обнаружение бычьих/медвежьих
- ✅ **Аномалии** — спайки объема и цены
- ✅ **FVG** — Fair Value Gaps
- ✅ **Рыночные режимы** — классификация ADX+ATR+EMA

#### **3. Strategy Comparator (`strategy_comparison.py`)**
Сравнение стратегий с разными параметрами:
- ✅ **TSL стратегии** — с разными уровнями активации
- ✅ **Уровни риска** — 0.5% до 2% на сделку
- ✅ **Символы** — BTC, ETH, BNB, ADA
- ✅ **Таймфреймы** — 15m, 1h, 4h, 1d

#### **4. Конфигурация (`backtest_config.yaml`)**
Гибкие настройки тестирования:
- ✅ **Сценарии** — quick_test, full_test, stress_test
- ✅ **Оптимизация** — генетические алгоритмы
- ✅ **Метрики** — Sharpe, Calmar, VaR
- ✅ **Валидация** — защита от переобучения

### 🚀 **Быстрый старт тестирования:**

```bash
# 1. Тестирование всех индикаторов
python test_indicators.py

# 2. Бэктестинг стратегий
python backtesting_engine.py

# 3. Сравнение стратегий
python strategy_comparison.py
```

### 📈 **Примеры результатов:**

#### **Тестирование индикаторов (BTC/USDT, 30 дней):**
```
📈 ТРЕНДОВЫЕ ИНДИКАТОРЫ:
   Распределение: UP 45.2%, DOWN 54.8%
   Изменений тренда: 23
   Средняя длина тренда: 37.8 баров

🌊 WT ИНДИКАТОР:
   Сигналов: 12
   Зоны: {'OB': 15.2%, 'OS': 18.7%, 'N': 66.1%}

🔄 ДИВЕРГЕНЦИИ:
   Всего: 8
   Типы: {'bullish': 4, 'bearish': 4}
```

#### **Сравнение стратегий:**
```
🏆 СРАВНЕНИЕ TSL СТРАТЕГИЙ
----------------------------------------------------------------------
Стратегия          | Win Rate | Avg R | Sharpe | Max DD | Доход
----------------------------------------------------------------------
Без TSL           | 42.1%    | 0.85  | 1.23   | -12.4% | +15.2%
После 1R         | 45.8%    | 0.92  | 1.45   | -9.8%  | +22.1% ⭐
После 1.5R       | 43.2%    | 0.88  | 1.38   | -11.2% | +18.7%
```

### 🎯 **Рекомендуемая стратегия:**
- **Символ:** BTC/USDT
- **Таймфрейм:** 1h
- **Риск на сделку:** 1%
- **TSL активация:** После +1R
- **Ожидаемый доход:** +22.1% за период
- **Sharpe ratio:** 1.45
- **Max Drawdown:** -9.8%

### 📊 **Метрики производительности:**
- **Total Return:** Общий доход стратегии
- **Win Rate:** Процент прибыльных сделок
- **Avg R:** Среднее R-multiple на сделку
- **Sharpe Ratio:** Риск-скорректированная доходность
- **Max Drawdown:** Максимальная просадка
- **Profit Factor:** Отношение прибыли к убыткам
- **Calmar Ratio:** Доходность к максимальной просадке

### 🔧 **Расширенные возможности:**

#### **Оптимизация параметров:**
```python
# Генетическая оптимизация
optimizer = GeneticOptimizer(population_size=50, generations=20)
best_params = optimizer.optimize(tsl_activation_r=[0.5, 1.0, 1.5, 2.0])
```

#### **Out-of-sample тестирование:**
```python
# 80% обучение, 20% валидация
trainer = WalkForwardTrainer(train_pct=0.8)
results = trainer.validate_strategy(strategy)
```

#### **Стресс-тестирование:**
```python
# Тестирование в экстремальных условиях
stresser = StressTester()
results = stresser.test_extreme_conditions(strategy)
```

### 📁 **Структура отчетов:**
```
backtest_reports/
├── strategy_comparison_results.json
├── detailed_metrics.csv
├── equity_curve.png
├── drawdown_chart.png
├── monthly_performance.html
└── risk_analysis.pdf
```

### ⚠️ **Важные замечания:**
- Все тесты используют **реальные исторические данные** с биржи
- **Комиссии и проскальзывание** учитываются в расчетах
- **Валидация на переобучение** встроена в систему
- **Параллельное выполнение** для ускорения тестирования

Эта система позволяет **объективно оценить** эффективность всех компонентов стратегии перед запуском в продакшн! 🎯

---

## Структура проекта

```
bot_with_subscriptions.py   ← точка входа (1540+ строк, основной монолит)
config.yaml                 ← конфигурация (API ключи, параметры)
subscriptions.db            ← SQLite (пользователи, подписки, simulated_trades)

core/                       ← ТОЛЬКО бизнес-логика, без aiogram
  api_engine.py             ← транспортный слой: LRU cache, CircuitBreaker, retry, in-flight dedup
  data_collector.py         ← получение данных с биржи (OHLCV + ticker); делегирует в api_engine
  indicators.py             ← технические индикаторы (WT, RSI и др.)
  signal_models.py          ← dataclass модели: SignalData, TradingRecommendation и др.
  signal_checkers.py        ← чистые функции проверок по всем типам сигналов
  anomaly_detector.py       ← всплески объёма
  divergence_detector.py    ← дивергенции (Regular, Hidden)
  trend_signals.py          ← сигналы тренда (EMA, ADX, slope)
  mtf_checker.py            ← multi-timeframe анализ
  mtf_pivot_integration.py  ← MTF + пивоты (комбинированные сигналы)
  pivot_levels.py           ← уровни пивотов (Woodie, Camarilla, Fibonacci)
  pivot_reversal.py         ← разворотные сигналы по пивотам
  pivot_calculator_fixed.py ← period-based пивоты (1M/1W/1D, UTC)
  trading_intelligence.py   ← 1850 строк: агрегация сигналов → рекомендация
  intelligence_formatter.py ← форматирование TradingRecommendation → HTML (re-export)
  trade_simulator.py        ← регистрация сделок, SL/TP трекинг, MFE
  performance_engine.py     ← аналитика по simulated_trades (read-only)
  outcome_predictor.py      ← RandomForest на исходах сделок, P(win)
  market_regime.py          ← ADX+ATR+EMA классификатор (TREND_UP/DOWN/RANGE/HIGH_VOL)
  ml_predictor.py           ← OHLCV-based ML (PRICE_DIRECTION, SIGNAL_STRENGTH)
  message_builder.py        ← форматирование символов, TV-ссылки
  config.py                 ← legacy-константы (заменён config_loader)
  config_loader.py          ← загрузка config.yaml и .env
  subscription_manager.py   ← SQLite: users, subscriptions, simulated_trades, user_settings
  watchlist_manager.py      ← watchlist пользователя
  risk_manager.py           ← ВНИМАНИЕ: active_positions всегда пуст, не подключён
  historical_analyzer.py    ← дублирует часть функций trade_simulator, не основной

bot/                        ← UI-слой (aiogram)
  keyboards.py              ← клавиатуры Telegram (494 строки)
  menus/                    ← меню бота
    __init__.py             ← экспортирует MenuHandler
    handler.py              ← диспетчер меню → делегирует в menu_*.py
    ai.py / signals.py / pivots.py / risk.py /
    history.py / settings.py / subscriptions.py
  handlers/                 ← обработчики команд aiogram
    core_handlers.py        ← /start, /help
    analysis_handlers.py    ← анализ символов
    scan_handlers.py        ← /scan, /watch
    pivot_handlers.py       ← /pivots
    subscription_handlers.py
    callback_handlers.py
  filters/
  main.py                   ← альтернативная точка входа (не основная)
  monitoring.py
  states.py

web/
  dashboard_server.py       ← aiohttp дашборд, порт 8000
  __init__.py

domain/ infrastructure/ presentation/  ← скелет архитектуры, НЕ рабочий код
```

---

## База данных

SQLite файл: `subscriptions.db`

Основная таблица: **`simulated_trades`**
```
id, symbol, timeframe, signal_type, direction, entry_price, stop_loss, take_profit,
strength, confidence, regime, created_at,
status (OPEN/TP/SL/TSL/EXPIRED), exit_price, profit_pct, R_multiple, closed_at,
duration_minutes, features_json,
max_price, min_price,           ← MFE: экстремумы High/Low за время жизни сделки
max_R_possible, captured_R_pct ← MFE: лучший R и % захваченного потенциала
```

**Статусы сделок:**
- `OPEN` — активная сделка
- `TP` — закрыта по Take Profit
- `SL` — закрыта по Stop Loss
- `TSL` — закрыта по Trailing Stop Loss
- `EXPIRED` — истекла по времени

---

## TSL (Trailing Stop Loss)

**Trailing Stop Loss** — динамический стоп-лосс, который следует за трендом и защищает прибыль.

### Как работает TSL:

1. **Расчет:** Использует алгоритм из `calculate_trend()` в `indicators.py`
2. **Активация:** Включается после достижения +1R прибыли
3. **Логика:** Для LONG — закрывает при пробое `trenddown`, для SHORT — при пробое `trendup`

### Параметры конфигурации (`config.yaml`):

```yaml
trading:
  use_tsl: true           # Включить TSL
  tsl_activation_r: 1.0   # Активировать после +1R
  tsl_buffer_pct: 0.1     # Буфер 0.1%
```

### Преимущества TSL:

- ✅ **Защита прибыли** — позволяет тренду развиваться, но защищает от разворота
- ✅ **Динамический** — следует за движением рынка
- ✅ **MFE анализ** — показывает, сколько потенциала упущено

### Тестирование TSL:

```bash
# Запуск теста
python test_tsl.py

# Проверка в дашборде
http://localhost:8000
```

Таблица **`user_settings`** (персональный риск-менеджмент):
```
user_id (PK), deposit_usdt, leverage, risk_pct, sl_pct, tp_pct,
auto_sizing (0/1), updated_at
```

Типы `signal_type` в БД: `pivot_reversal`, `trend_signal`, `wt_signal`, `composite`

---

## Архитектурные решения

### Как работает сигнальный поток
```
DataCollector (OHLCV)
  → 6 детекторов сигналов (anomaly, WT, MTF, trend, divergence, pivot)
  → TradingIntelligence.analyze_symbol()
      → _analyze_signals_advanced()         ← ОСНОВНОЙ метод
      → _calculate_adaptive_weighted_strength()
      → _enhance_analysis_with_ml()
          → MLPredictor (PRICE_DIRECTION, SIGNAL_STRENGTH)
          → OutcomePredictor.predict_win_prob()  ← P(win) из реальных исходов
      → _generate_recommendation()
  → TradeSimulator.register_trade_async(recommendation, data_collector)
      → MarketRegimeClassifier.classify_from_ohlcv()  ← записывает regime
      → INSERT INTO simulated_trades
```

### Адаптивные веса
`TradingIntelligence.update_signal_weights()` — вызывается при старте и после переобучения.
Формула: `new_weight = base_weight × clamp(1.0 + avg_R × 0.4, 0.5, 2.0)`
Порог: минимум 20 закрытых сделок на тип сигнала.

Текущие реальные веса (на ~150 сделках):
- `pivot_reversal`: 0.20 → **0.24** (avg_R = +0.50)
- `trend_signal`: 0.10 → **0.08** (avg_R = −0.50)
- `wt_signal`: 0.10 → **0.133** (avg_R = +0.83)

### OutcomePredictor (ML на исходах)
12 признаков: strength, confidence, direction, signal_type (3 one-hot), volatility, price_change, regime (4 one-hot).
Таргет: TP=1, SL=0. Текущий CV AUC ≈ 0.56 (базовая линия).
Качество вырастет по мере накопления сделок с заполненным полем `regime`.

---

## Зависимости

```
aiogram==3.4.1       ← Telegram Bot
ccxt==4.2.85         ← биржа BingX
aiohttp==3.9.3       ← дашборд
pandas, numpy        ← аналитика
scikit-learn         ← ML (pip install scikit-learn)
pyyaml, python-dotenv
```

---

## Как добавлять новые сигналы

1. Создать детектор в `core/` по образцу `anomaly_detector.py`
2. Добавить `SignalType.NEW_SIGNAL = "new_signal"` в enum в `trading_intelligence.py`
3. Добавить вес в `self.signal_weights` и `self._base_signal_weights`
4. Вызвать детектор в `analyze_symbol()` — секция сбора сигналов (~строка 280-320)
5. Новый `signal_type` автоматически появится в дашборде и в адаптивных весах после накопления 20 сделок

## Как отлаживать сигналы

```bash
# Смотреть последние сделки в БД
python -c "
from core.performance_engine import PerformanceEngine
pe = PerformanceEngine('subscriptions.db')
print(pe.summary())
for r in pe.by_signal_type(): print(r)
"

# Проверить OutcomePredictor
python -c "
from core.outcome_predictor import OutcomePredictor
op = OutcomePredictor(); op.fit('subscriptions.db')
print(op.info())
"

# Дашборд с живыми данными
# http://localhost:8000  (когда бот запущен)
```

## Как добавлять поля в simulated_trades

1. Добавить колонку в `CREATE TABLE` в `subscription_manager.py` (строки ~70-91)
2. Добавить миграцию через `ALTER TABLE` в том же блоке (для существующих БД)
3. Добавить в `INSERT` в `register_trade()` в `trade_simulator.py`
4. Если поле требует async данных — добавить получение в `register_trade_async()`
5. PerformanceEngine подхватит автоматически (читает через SELECT *)

## Известные проблемы / технический долг

- `risk_manager.py`: `active_positions` всегда пустой — методы `add_position/remove_position` нигде не вызываются
- `historical_analyzer.py`: дублирует часть логики trade_simulator, не является основным источником правды
- `bot_with_subscriptions.py` (1540 строк) + `trading_intelligence.py` (1850 строк) — монолиты, ROADMAP Этап 8 планирует разбивку
- Папки `domain/`, `infrastructure/`, `presentation/` — скелет, не рабочий код, не трогать
- `regime` в старых (до 04.03.2026) сделках = NULL, ML на режимах заработает с накоплением новых
- `max_price`/`min_price` в старых сделках = NULL (MFE добавлен 05.03.2026), заполняется для новых
- `signal_strength_gradient_boosting` — модель не обучается если в y_train только 1 класс (пропускается с WARNING)
- Прогрев кеша пивотов (`_prefetch_pivots`) не ждёт завершения — первый цикл мониторинга может стартовать до полного прогрева

## Фильтры качества сигналов (Этап 5.1)

Настраиваются в `config.yaml`:
```yaml
signal_quality:
  min_volume_usd: 1000000   # пары с объёмом < N не мониторируются
  sl_cooldown_hours: 4      # пауза после SL-закрытия по паре
  dedup_minutes: 30         # окно дедупликации одинаковых сигналов
  min_strength: 50          # порог силы для регистрации сделки в симуляторе
```

Логика `is_actionable` в `bot/monitoring.py`:
- `overall_strength >= min_strength`
- `action in ("BUY", "SELL")` (не WATCH/HOLD)
- `direction.value != "NEUTRAL"`

Только `is_actionable=True` → регистрация сделки + footer "Сделка зарегистрирована". Причина отказа логируется на уровне INFO.
