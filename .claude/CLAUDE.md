## Язык
Общайся на русском языке. Документацию пиши на русском.

---

## Проект: Oko MTF TG Bot

Telegram-бот для технического анализа крипторынка с симуляцией сделок и самообучением.
Биржа: BingX (через ccxt). Таймфрейм по умолчанию: 15m.

**Запуск:** `python bot_with_subscriptions.py`
**Дашборд:** `http://localhost:8000` (aiohttp, запускается автоматически с ботом)

---

## Структура проекта

```
bot_with_subscriptions.py   ← точка входа (1540+ строк, основной монолит)
config.yaml                 ← конфигурация (API ключи, параметры)
subscriptions.db            ← SQLite (пользователи, подписки, simulated_trades)

core/
  data_collector.py         ← получение данных с биржи (только OHLCV + ticker)
  trading_intelligence.py   ← 1850 строк: агрегация сигналов → рекомендация
  trade_simulator.py        ← регистрация сделок, SL/TP трекинг, R-multiple
  performance_engine.py     ← аналитика по simulated_trades (read-only)
  outcome_predictor.py      ← RandomForest на исходах сделок, P(win)
  market_regime.py          ← ADX+ATR+EMA классификатор (TREND_UP/DOWN/RANGE/HIGH_VOL)
  ml_predictor.py           ← OHLCV-based ML (PRICE_DIRECTION, SIGNAL_STRENGTH)
  anomaly_detector.py       ← всплески объёма
  indicators.py             ← технические индикаторы (WT, RSI и др.)
  mtf_checker.py            ← multi-timeframe анализ
  trend_signals.py          ← сигналы тренда
  divergence_detector.py    ← дивергенции
  pivot_levels.py           ← уровни пивотов
  pivot_reversal.py         ← разворотные сигналы
  message_builder.py        ← форматирование сообщений
  risk_manager.py           ← ВНИМАНИЕ: active_positions всегда пуст, не подключён
  historical_analyzer.py    ← дублирует часть функций trade_simulator, не основной

bot/
  handlers/                 ← обработчики aiogram (рефакторинг-скелет, частично используется)
  filters/
  main.py                   ← альтернативная точка входа (не основная)

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
status (OPEN/TP/SL/EXPIRED), exit_price, profit_pct, R_multiple, closed_at,
duration_minutes, features_json,
max_price, min_price,           ← MFE: экстремумы High/Low за время жизни сделки
max_R_possible, captured_R_pct ← MFE: лучший R и % захваченного потенциала
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

## Как добавлять поля в simulated_trades

1. Добавить колонку в `_create_table()` в `trade_simulator.py`
2. Добавить в `INSERT` в `register_trade()`
3. Если поле требует async данных — добавить получение в `register_trade_async()`
4. PerformanceEngine подхватит автоматически (читает через SELECT *)

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
