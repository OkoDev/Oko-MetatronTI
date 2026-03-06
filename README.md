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
| `anomaly` | Всплески объёма + движение цены |
| `wt_signal` | WaveTrend CrossUp/CrossDown в зонах перекупленности/перепроданности |
| `mtf_alert` | MTF разворот (4 таймфрейма одновременно) |
| `trend_signal` | EMA-тренд + откат + подтверждение |
| `divergence` | Regular/Hidden дивергенции (RSI, WT) |
| `pivot_reversal` | Разворот от уровней пивота (Woodie, Camarilla, Fibonacci) |
| `composite` | Комплексный анализ TradingIntelligence (все сигналы — одна рекомендация) |

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
bot_with_subscriptions.py   -- точка входа (aiogram 3.4.1)
config.yaml                 -- параметры (редактируются через браузер)
subscriptions.db            -- SQLite

core/          -- бизнес-логика (без aiogram)
  trading_intelligence.py   -- агрегация сигналов -> TradingRecommendation
  trade_simulator.py        -- регистрация/закрытие симулированных сделок, MFE
  performance_engine.py     -- аналитика по закрытым сделкам
  market_regime.py          -- ADX+ATR+EMA -> TREND_UP/DOWN/RANGE/HIGH_VOL
  outcome_predictor.py      -- RandomForest P(win) на реальных исходах
  data_collector.py         -- OHLCV + ticker (TTL-кеш, ~300 запросов/цикл)
  pivot_calculator_fixed.py -- пивоты на UTC-периодах (1M/1W/1D, не скользящие)
  config_loader.py          -- загрузка config.yaml + .env, hot-reload

bot/           -- UI-слой (aiogram handlers, keyboards, menus)
web/           -- aiohttp дашборд (порт 8000)
  dashboard_server.py       -- GET /, /api/stats, GET/POST /settings, /api/settings
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

### Быстрый запуск всех тестов

```bash
# Запуск полного комплекта тестов
python run_all_tests.py
```

### Отдельные компоненты

```bash
# 1. Тестирование всех индикаторов
python test_indicators.py

# 2. Тест TSL функциональности
python test_tsl.py

# 3. Бэктестинг стратегий
python backtesting_engine.py

# 4. Сравнение стратегий
python strategy_comparison.py
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
