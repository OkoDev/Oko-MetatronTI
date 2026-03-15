# Oko MTF Bot — Telegram-бот для технического анализа крипторынка

Самообучающийся бот для BingX: сигналы по 7 стратегиям, симуляция сделок, ML на реальных исходах.

## Быстрый старт

```bash
pip install -r requirements.txt
cp .env.example .env   # заполнить TELEGRAM_TOKEN, ADMIN_ID, BINGX_API_KEY, BINGX_SECRET_KEY
python bot_with_subscriptions.py
```

Дашборд: `http://localhost:8000`
Настройки: `http://localhost:8000/settings` (hot-reload без перезапуска)

## Сигналы

| Тип | Описание |
|-----|----------|
| `wt_b_signal` | WT Type B — крест в OS/OB + дивергенция (WR=85% backtest) |
| `confluence` | Мульти-факторный сетап: WT zone + TSL cross + pivot + divergence |
| `mtf_bias` | MTF Bias — 7 TF alignment + senior gate + entry TF selection |
| `pivot_reversal` | Разворот от уровней пивота (1W/1D/1M) |
| `smc_structure` | BOS/CHoCH — структурные сигналы Smart Money |
| `wt_signal` | WaveTrend CrossUp/CrossDown в зонах OS/OB |
| `divergence` | Regular/Hidden дивергенции WT |
| `trend_signal` | EMA-тренд + откат + подтверждение |
| `anomaly` | Всплески объёма + движение цены |

## Команды бота

```
/start                 — главное меню
/intelligence BTCUSDT  — полный анализ символа
/scan                  — топ-10 пар по силе сигнала
/watch add ETHUSDT     — добавить в watchlist (отмечается в /scan)
/watchlist             — мой список пар
/pivots                — MTF пивоты (1M/1W/1D) + конфлюэнции
/settings              — персональный депозит/плечо/риск%
/subscribe             — управление подпиской
```

## Архитектура

```
bot_with_subscriptions.py   -- точка входа (75 строк, aiogram 3.4.1)
config.yaml                 -- параметры (редактируются через браузер)
subscriptions.db            -- SQLite

core/                       -- бизнес-логика (без aiogram)
  trading_intelligence.py   -- агрегация сигналов → TradingRecommendation
  intelligence/             -- вынесенные модули (signal_aggregator, confidence, ML, recommendation)
  signal_checkers.py        -- детекторы: WT, WT_B, anomaly, MTF, divergence, pivot, SMC
  trade_simulator.py        -- регистрация/закрытие сделок, MFE, TSL, частичные TP
  api_engine.py             -- LRU cache, CircuitBreaker, retry, in-flight dedup
  data_collector.py         -- OHLCV + ticker (делегирует в ApiEngine)
  confluence_scanner.py     -- мульти-факторный детектор (lookback + state machine)
  mtf_interpreter.py        -- MTF Bias: 7 TF alignment + senior gate
  structure_detector.py     -- SMC: BOS/CHoCH/Swing
  market_regime.py          -- ADX+ATR+EMA → TREND_UP/DOWN/RANGE/HIGH_VOL
  pivot_calculator_fixed.py -- пивоты UTC (1M/1W/1D)

bot/                        -- UI-слой (aiogram)
  core/bot.py               -- TradingAlertBot класс
  loops/                    -- scan_loop, trade_tracker, ml_loop
  handlers/                 -- /start, /intelligence, /scan, /pivots, /settings
  menus/                    -- диспетчер меню

strategies/                 -- Strategy Pattern (ARCH-05)
  base.py                   -- BaseStrategy(ABC)
  registry.py               -- @register_strategy, get_strategy()
  built_in/                 -- confluence, confluence_scanner, conservative, pivot_reversal, mtf_bias

scripts/                    -- бэктестинг, анализ, утилиты
tests/                      -- unit + integration тесты
web/                        -- aiohttp дашборд (порт 8000)
```

## База данных

**`simulated_trades`** — все сделки:
```
symbol, timeframe, signal_type, direction,
entry_price, stop_loss, take_profit, strength, confidence, regime,
status (OPEN/TP/SL/EXPIRED), exit_price, profit_pct, R_multiple,
max_price, min_price, max_R_possible, captured_R_pct
```

**`user_settings`** — персональный риск-менеджмент:
```
user_id, deposit_usdt, leverage, risk_pct, sl_pct, tp_pct, auto_sizing
```
Формула: `Position (USDT) = (Deposit * Risk%) / SL% * Leverage`

## Параметры анализа (config.yaml / браузер)

```yaml
analysis:
  volume_multiplier: 5.0    # x среднего объёма — порог аномалии
  price_threshold: 7.0      # % изменения цены — порог аномалии
  history_size: 200         # глубина OHLCV для индикаторов
  check_interval: 60        # пауза между циклами мониторинга, сек

signal_quality:
  min_volume_usd: 1000000   # минимальный объём 24ч для мониторинга пары
  sl_cooldown_hours: 4      # пауза после SL по паре (часы)
  dedup_minutes: 30         # окно дедупликации одинаковых сигналов
  min_strength: 50          # минимальная сила для регистрации сделки

trading:
  use_tsl: true             # Trailing Stop Loss
  tsl_activation_r: 1.0    # активация TSL после +1R
```

Параметры `analysis` и `trading` изменяются через `http://localhost:8000/settings` без перезапуска бота.

## 🧪 Система тестирования

Проект включает комплексную систему бэктестинга для объективной оценки стратегий на исторических данных.

### Unit-тесты

```bash
python -m pytest tests/ -v
```

### Бэктестинг и сравнение стратегий

```bash
# Бэктестинг стратегий
python scripts/backtesting_engine.py --scenario quick_test

# Сравнение стратегий
python scripts/strategy_comparison.py

# CLI бэктест конкретной стратегии
python scripts/run_backtest.py --strategy confluence_scanner --symbol BTC/USDT --days 30
```

### Результаты тестирования

- **Исторические данные:** Реальные OHLCV с биржи BingX
- **Метрики:** Sharpe ratio, Win Rate, Max Drawdown, Profit Factor
- **Валидация:** Защита от переобучения, out-of-sample тестирование
- **Отчеты:** JSON, CSV, графики (equity curve, drawdown)

### Рекомендуемая стратегия (на основе бэктестинга)

- **Символ:** BTC/USDT
- **Таймфрейм:** 1h
- **Риск на сделку:** 1%
- **TSL активация:** После +1R прибыли
- **Ожидаемый доход:** +22.1% за период
- **Sharpe ratio:** 1.45

## Производительность

| Метрика | Значение |
|---------|----------|
| Скан 399 пар | ~25-32 сек |
| Параллельных API-запросов | Semaphore(20) |
| Cache hit (OHLCV) | LRU до 5000 записей |
| TTL кеша (15m) | 60 сек |
| Пар в мониторинге | 600+ |

**Критичная настройка** (`core/data_collector.py`): `enableRateLimit: False` в ccxt — без этого встроенный rate limiter сериализует все запросы (~1/сек) и скан занимает 20-90 минут вместо 30 секунд. Параллелизм контролирует `ApiEngine.Semaphore(20)`.

## Зависимости

```
aiogram==3.4.1
ccxt==4.2.85
aiohttp==3.9.3
pandas, numpy
scikit-learn
pyyaml, python-dotenv
```

## Запуск (Python 3.12)

```bash
# Использовать Python 3.12 (aiogram установлен только там)
C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe bot_with_subscriptions.py
```

> **Важно:** `.venv` (Python 3.13) и системный `python` не имеют aiogram — бот не запустится.

## Переменные окружения (.env)

```env
TELEGRAM_TOKEN=...
ADMIN_ID=...
BINGX_API_KEY=...
BINGX_SECRET_KEY=...
```

## Тесты

```bash
python -m pytest tests/ -v
```

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
```
