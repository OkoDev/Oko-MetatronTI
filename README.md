# Oko MTF Bot — Telegram-бот для технического анализа крипторынка

Самообучающийся бот для BingX: сигналы по 8 стратегиям, симуляция сделок, ML на реальных исходах, каскадный TSL.

## Быстрый старт

```bash
pip install -r requirements.txt
cp .env.example .env   # заполнить TELEGRAM_TOKEN, ADMIN_ID, BINGX_API_KEY, BINGX_SECRET_KEY
C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe bot_with_subscriptions.py
```

> **Важно:** Использовать Python 3.12. `.venv` (Python 3.13) и системный `python` не имеют aiogram.

Дашборд: `http://localhost:8000`
Настройки live: `http://localhost:8000/settings` (hot-reload без перезапуска бота)

---

## Сигналы

| Тип | Специализация | Описание |
|-----|---------------|----------|
| `mtf_bias` | Тренд | MTF Bias — 6 TF alignment (WT momentum) + senior gate + entry TF selection |
| `trend_signal` | Тренд | EMA-тренд + откат + подтверждение |
| `confluence` | Откат в тренде | Мульти-фактор: WT zone + TSL cross + pivot + divergence |
| `wt_signal` | Откат в тренде | WaveTrend CrossUp/CrossDown в зонах OS/OB; **апгрейдируется до `confluence`** если цена в ±1% от пивота (ARCH-23) |
| `wt_b_signal` | Разворот | WT Type B — крест в OS/OB + дивергенция (WR≈85% backtest) |
| `divergence` | Разворот | Regular/Hidden дивергенции WT |
| `pivot_reversal` | Разворот | Разворот от уровней пивота (1M/1W/1D) |
| `anomaly` | Событийный | Всплески объёма + движение цены |

---

## Команды бота

```
/start                 — главное меню
/intelligence BTCUSDT  — полный анализ символа
/scan                  — топ-10 пар по силе сигнала
/watch add ETHUSDT     — добавить в watchlist (отмечается в /scan)
/watchlist             — мой список пар
/wl                    — watch list (пары ожидающие эскалации)
/pivots                — MTF пивоты (1M/1W/1D) + конфлюэнции
/settings              — персональный депозит/плечо/риск%
/stats                 — статистика бота
/subscribe             — управление подпиской
/monitor               — запуск/остановка мониторинга
```

---

## Архитектура

```
bot_with_subscriptions.py   -- точка входа (aiogram 3.4.1)
config.yaml                 -- параметры (редактируются через браузер)
subscriptions.db            -- SQLite

core/                       -- бизнес-логика (без aiogram)
  trading_intelligence.py   -- агрегация сигналов → TradingRecommendation
  intelligence/             -- модули: signal_aggregator, confidence, ML, recommendation
  signal_checkers.py        -- детекторы: WT, WT_B, anomaly, confluence, divergence, pivot
  trade_simulator.py        -- регистрация/закрытие сделок, MFE, TSL, частичные TP
  api_engine.py             -- LRU cache, CircuitBreaker, retry, in-flight dedup
  data_collector.py         -- OHLCV + ticker (делегирует в ApiEngine)
  confluence_scanner.py     -- мульти-факторный детектор (lookback + state machine)
  confluence_state_machine.py -- FSM: IDLE→WATCH→SIGNAL→EXPIRED
  mtf_interpreter.py        -- MTF Bias: 6 TF WT-momentum alignment + senior gate
  mtf_checker.py            -- collect_mtf_data: snapshot по ТФ (WT momentum)
  wt_15m_reversal_scanner.py -- WT Type B reversal с 1h/4h контекстом
  bounce_detector.py        -- контртренд-отскоки (ARCH-15)
  multi_tf_resolver.py      -- разрешение конфликтов ТФ + bounce support
  signal_watch_list.py      -- WATCH LIST: автонаблюдение и эскалация сигналов
  market_regime.py          -- ADX+ATR+EMA → TREND_UP/DOWN/RANGE/HIGH_VOL
  pivot_calculator_fixed.py -- пивоты UTC (1M/1W/1D) + find_near_pivot() [ARCH-23]
  trading_intelligence.py   -- агрегация + адаптивные веса + ML-блендинг
  outcome_predictor.py      -- RandomForest P(win) на реальных исходах
  performance_engine.py     -- аналитика из simulated_trades (read-only)
  smc/                      -- Smart Money Concepts пакет [ARCH-17]
    swing_points.py         -- HH/HL/LH/LL классификация
    structure.py            -- BOS/CHoCH детектор
    fvg.py                  -- Fair Value Gap + mitigation tracking
    order_blocks.py         -- Order Blocks (институциональные зоны)
    liquidity.py            -- swept/unswept кластеры ликвидности
    fibonacci.py            -- OTE зона (0.618-0.786)
    context.py              -- SMCContext: агрегат всех SMC-данных

bot/                        -- UI-слой (aiogram)
  core/bot.py               -- TradingAlertBot: инициализация зависимостей
  loops/scan_loop.py        -- основной цикл скана пар + ARCH-23 апгрейд WT
  loops/trade_tracker.py    -- трекинг открытых сделок, TSL, MFE
  loops/ml_loop.py          -- ML переобучение, еженедельные отчёты
  handlers/                 -- /start, /intelligence, /scan, /pivots, /settings
  menus/                    -- диспетчер меню (handler.py) + доменные модули

strategies/                 -- Strategy Pattern (ARCH-05)
  base.py                   -- BaseStrategy(ABC)
  registry.py               -- @register_strategy, get_strategy()
  built_in/                 -- confluence, reversal_scanner, trend

scripts/                    -- утилиты + backtesting
  backtesting_engine.py     -- бэктест: commission, leverage, SMC фильтры
  universe_builder.py       -- CoinGecko top-250, стратификация 3 тира, seed=42
  multi_source_ohlcv.py     -- авто-выбор источника: Binance→Crypto.com→BingX
  run_universe_backtest.py  -- оркестратор: 30 альтов, Monte Carlo, JSON-отчёт
  ohlcv_cache.py            -- SQLite кэш OHLCV для бэктеста

tests/                      -- unit + integration тесты
web/                        -- aiohttp дашборд (порт 8000)
```

---

## База данных

**`simulated_trades`** — все сделки:
```
symbol, timeframe, signal_type, direction,
entry_price, stop_loss, take_profit, tp1_price, tp1_hit_at,
strength, confidence, regime, created_at,
status (OPEN/TP/SL/TSL/EXPIRED), exit_price, profit_pct, R_multiple, closed_at,
duration_minutes, features_json,
max_price, min_price,           ← MFE: экстремумы за жизнь сделки
max_R_possible, captured_R_pct, ← MFE: лучший R и % захваченного потенциала
sl_source, tp_source,           ← источники SL/TP (atr_14, pivot_1W_R1, swing_low и т.д.)
tsl_activated                   ← 0/1: достигала ли порога tsl_activation_r
```

**`user_settings`** — персональный риск-менеджмент:
```
user_id, deposit_usdt, leverage, risk_pct, sl_pct, tp_pct, auto_sizing
```
Формула: `Position (USDT) = (Deposit × Risk%) / SL% × Leverage`

---

## Параметры (config.yaml / браузер)

```yaml
signal_quality:
  min_volume_usd: 1000000      # минимальный объём 24ч для мониторинга пары
  sl_cooldown_hours: 4.0       # пауза после SL по паре (часы)
  dedup_minutes: 30            # окно дедупликации одинаковых сигналов
  min_strength: 50             # минимальная сила для TG-алерта
  min_strength_register: 65    # минимальная сила для записи в БД
  watch_list_ttl_hours: 4      # TTL наблюдений в WATCH LIST

analysis:
  volume_multiplier: 5.0       # x среднего объёма — порог аномалии
  price_threshold: 7.0         # % изменения цены — порог аномалии
  history_size: 200            # глубина OHLCV для индикаторов
  check_interval: 60           # пауза между циклами скана, сек
  signals.min_confidence_by_type:
    confluence: 0.68           # фильтр по уверенности для confluence

trading:
  use_tsl: true                # Trailing Stop Loss
  tsl_activation_r: 1.0       # активация TSL после +1R
  use_breakeven: true          # перевод в безубыток после +0.5R
  breakeven_activation_r: 0.5
```

Параметры `analysis` и `trading` изменяются через `http://localhost:8000/settings` без перезапуска.

---

## TSL (Trailing Stop Loss)

Динамический стоп-лосс, следующий за трендом. Защищает прибыль после +1R.

- **Расчёт:** ATR trailing stop из `calculate_trend()` (индикатор на основе RMA-ATR)
- **Активация:** После +`tsl_activation_r` × R (по умолчанию 1.0)
- **Безубыток:** При +0.5R SL переставляется чуть выше/ниже entry
- **Для LONG:** Закрывает при пробое `trenddown`; для SHORT — при пробое `trendup`

> MTF Bias и wt_15m_reversal_scanner используют WT momentum (`wt1 > wt2`) для определения
> направления тренда на старших ТФ — быстро (1-2 свечи), в отличие от ATR trailing stop (лаг 3-5 свечей).

---

## ML и адаптация

**OutcomePredictor** — RandomForest(200 деревьев) на реальных исходах сделок:
- 12 признаков: strength, confidence, direction, signal_type (3 one-hot), volatility, price_change, regime (4 one-hot)
- Цель: TP=1, SL=0; CV AUC растёт с накоплением данных
- Блендинг: `confidence = 0.7 × orig + 0.3 × P(win)`

**Адаптивные веса** — `TradingIntelligence.update_signal_weights()`:
- Формула: `factor = clamp(1.0 + avg_R × 0.4, 0.5, 2.0)`
- Порог: минимум 20 закрытых сделок на тип сигнала
- Переобучение: при старте и после `train_all_models()`

---

## Производительность

| Метрика | Значение |
|---------|----------|
| Скан 600+ пар | ~25-32 сек |
| Параллельных API-запросов | Semaphore(20) |
| Cache hit (OHLCV) | LRU до 5000 записей |
| TTL кеша (15m) | 60 сек |

**Критичная настройка** (`core/data_collector.py`): `enableRateLimit: False` в ccxt.
Без этого скан занимает 20-90 минут вместо 30 секунд. Параллелизм контролирует `ApiEngine.Semaphore(20)`.

---

## Тестирование

```bash
# Unit-тесты
python -m pytest tests/ -v

# Конкретный модуль
python -m pytest tests/unit/test_confluence_state_machine.py -v
python -m pytest tests/unit/test_bounce_detector.py -v
```

---

## Диагностика

```bash
# Статистика по сделкам
python -c "
from core.performance_engine import PerformanceEngine
pe = PerformanceEngine('subscriptions.db')
print(pe.summary())
for r in pe.by_signal_type(): print(r)
"

# ML-качество
python -c "
from core.outcome_predictor import OutcomePredictor
op = OutcomePredictor(); op.fit('subscriptions.db')
print(op.info())
"

# API кеш
python -c "
from core.data_collector import RealTimeData
dc = RealTimeData('bingx')
print(dc._engine.cache_stats())
"
```

---

## Зависимости

```
aiogram==3.4.1
ccxt==4.2.85
aiohttp==3.9.3
pandas, numpy
scikit-learn
pyyaml, python-dotenv
```

## Переменные окружения (.env)

```env
TELEGRAM_TOKEN=...
ADMIN_ID=...
BINGX_API_KEY=...
BINGX_SECRET_KEY=...
```
