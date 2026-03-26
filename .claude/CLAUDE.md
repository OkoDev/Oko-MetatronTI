## 🔴 СТАРТ КАЖДОЙ СЕССИИ 

## Язык
Thinking всегда (думать) на русском языке. Документацию пиши на русском.

## Общение
После завершения задачи или подзадачи, кратко изложите, что вы сделали, что произошло и что дальше. Затем озвучьте это через PowerShell TTS (Windows):
```powershell
# Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.SelectVoice('Microsoft Irina Desktop'); $s.Speak('текст')
```

---

## 🔴 СТАРТ КАЖДОЙ СЕССИИ — обязательное чтение MD

**Алгоритм подключения — строго по порядку:**

```
1. DISCUSSION.md      ← ПЕРВЫМ. Живой диалог агентов. Найти вопросы → своя роль: и ответить сразу.
2. TASKS.md           ← задачи всех ролей (DEV/ARCH/TRADER), статусы, приоритеты
3. whats-next.md      ← handoff от предыдущей сессии (что сделано, что осталось)
4. memory/MEMORY.md   ← архитектурные решения, известные баги, паттерны
── по необходимости ──
5. ROADMAP.md         ← этапы проекта (читать если непонятен контекст задачи)
6. BOT_SIGNAL_MAP.md  ← сигнальный пайплайн (читать если задача касается сигналов)
```

**Без прочтения DISCUSSION.md и TASKS.md нельзя начинать реализацию.**
Это защищает от: пропуска вопросов от других ролей, повторной работы, нарушения архитектурных решений.

После прочтения — кратко подтвердить:
`"Прочитал: DISCUSSION (последнее: X, вопросов ко мне: Y), TASKS (в работе: Z)."`


## 🔴 ОБЯЗАТЕЛЬНО ДЛЯ КАЖДОГО АГЕНТА — Ведение MD-документации

Это правило **не опционально** и применяется ко всем агентам (Architect, Developer, любые).

### В ходе сессии
После каждой завершённой задачи или подзадачи:
- Обновить `memory/current_state.md` — отметить что сделано, что изменилось
- Если изменился паттерн/архитектура/конфиг — обновить соответствующий раздел в `memory/MEMORY.md`

### При завершении сессии (явный выход или пауза)
Перед тем как остановить работу:
1. Обновить `memory/current_state.md`:
   - Раздел "Что было сделано"
   - Раздел "Незакоммиченные изменения"
   - Раздел "Известные проблемы"
   - Раздел "Следующие задачи"
2. Обновить разделы `memory/MEMORY.md` которые затронула работа сессии

### При компакте контекста (context compaction)
Система автоматически сжимает контекст при приближении к лимиту. **До компакта** агент обязан:
1. Записать в `memory/current_state.md` промежуточный статус — что сделано, что в процессе, на чём остановился
2. Добавить раздел `## В ПРОЦЕССЕ (прерван компактом)` с деталями незавершённой задачи
3. После компакта — прочитать `current_state.md` и продолжить с того места

### Формат отметки прогресса в current_state.md
```markdown
## [ЧЧ:ММ UTC] Агент: <Developer|Architect>
- ✅ Сделано: <краткое описание>
- 🔄 В процессе: <если не завершено>
- ⚠️ Проблемы: <если есть>
```

---

## Проект: Oko MTF TG Bot

Telegram-бот для технического анализа крипторынка с симуляцией сделок и самообучением.
Биржа: BingX (через ccxt). Таймфрейм по умолчанию: 15m.

**Запуск:** `python bot_with_subscriptions.py`
**Дашборд:** `http://localhost:8000` — статистика, `http://localhost:8000/settings` — настройки (aiohttp, запускается автоматически с ботом)

**TSL (Trailing Stop Loss):** Включен по умолчанию, активируется после +1R прибыли. Следует за трендом для защиты профита.

---

## 🧪 Система тестирования

```bash
python scripts/backtesting_engine.py   # полный бэктест стратегий
python scripts/test_indicators.py      # тест отдельных индикаторов
python scripts/strategy_comparison.py  # сравнение стратегий
```

Метрики: Win Rate, Avg R, Sharpe Ratio, Max Drawdown, Profit Factor.
Данные: реальные OHLCV с BingX, комиссии учтены.

---

## Структура проекта

```
bot_with_subscriptions.py   ← точка входа (1540+ строк, основной монолит)
config.yaml                 ← конфигурация (API ключи, параметры)
subscriptions.db            ← SQLite (пользователи, подписки, simulated_trades)

core/                       ← ТОЛЬКО бизнес-логика, без aiogram
  # ARCH-54 (29.03.2026): файлы разбиты по подпапкам.
  # Старые импорты (from core.X import Y) работают через stub-файлы в корне core/.
  # Новый импорт: from core.<папка>.<модуль> import Y

  infra/                    ← транспорт и конфигурация
    api_engine.py           ← LRU cache, CircuitBreaker, retry, in-flight dedup
    data_collector.py       ← получение данных с биржи (OHLCV + ticker)
    config_loader.py        ← загрузка config.yaml и .env
    data_quality.py         ← валидация качества OHLCV
    entry_config.py         ← конфигурация entry TF

  indicators/               ← технические индикаторы
    indicators.py           ← WT, RSI, ATR, EMA, ADX, trend, swing H/L
    divergence_detector.py  ← дивергенции (Regular, Hidden) + MTF cascade
    trend_signals.py        ← сигналы тренда (EMA cross, ADX, slope)
    market_regime.py        ← ADX+ATR+EMA → TREND_UP/DOWN/RANGE/HIGH_VOL
    anomaly_model.py        ← модель аномалий объёма
    bounce_detector.py      ← детектор bounce от уровней
    dynamic_thresholds.py   ← адаптивные пороги по волатильности

  signals/                  ← модели и чекеры сигналов
    signal_models.py        ← dataclass: SignalData, TradingRecommendation и др.
    signal_checkers.py      ← чистые функции проверок по всем типам сигналов
    signal_watch_list.py    ← логика WL breach сигналов
    wt_15m_reversal_scanner.py ← сканер WT разворотов на 15m
    structure_detector.py   ← детектор CHoCH/BOS на барах

  pivots/                   ← уровни пивотов
    pivot_levels.py         ← Woodie, Camarilla, Standard
    pivot_reversal.py       ← разворотные сигналы по пивотам
    pivot_calculator_fixed.py ← period-based пивоты (1M/1W/1D, UTC)
    mtf_pivot_integration.py  ← MTF + пивоты (комбинированные сигналы)

  mtf/                      ← multi-timeframe анализ
    mtf_checker.py          ← MTF проверки согласованности
    mtf_interpreter.py      ← интерпретация MTF контекста
    multi_tf_resolver.py    ← резолвер конфликтов между TF

  trading/                  ← торговый движок
    trade_simulator.py      ← регистрация сделок, SL/TP/TSL трекинг, MFE
    trade_analyzer.py       ← анализ закрытых сделок
    performance_engine.py   ← аналитика по simulated_trades (read-only)
    regime_strategy.py      ← адаптация параметров под рыночный режим (ARCH-04)

  ml/                       ← ML-модели
    ml_predictor.py         ← OHLCV-based ML (PRICE_DIRECTION, SIGNAL_STRENGTH)
    outcome_predictor.py    ← RandomForest на исходах сделок, P(win)
    r_predictor.py          ← предсказание max R-multiple
    rl_exit_agent.py        ← RL-агент управления выходом (stub)
    auto_calibrator.py      ← автокалибровка MTF multipliers

  ui/                       ← форматирование и вывод
    message_builder.py      ← TV-ссылки, форматирование символов
    message_composer.py     ← composer паттерн для сборки сообщений
    intelligence_formatter.py ← TradingRecommendation → HTML
    chart_builder.py        ← генерация candlestick PNG

  db/                       ← работа с БД
    subscription_manager.py ← SQLite: users, subscriptions, simulated_trades, user_settings
    watchlist_manager.py    ← watchlist пользователя (max 20/user)

  confluence/               ← confluence детекторы
    confluence_scanner.py
    confluence_state_machine.py

  smc/                      ← Smart Money Concepts (уже был)
  intelligence/             ← агрегация сигналов → рекомендация (уже был)
  agents/                   ← агент-архитектура (уже был)

  trading_intelligence.py   ← монолит 1850 строк (остаётся в корне, ROADMAP Этап 8)
  selftest.py
  # Stub-файлы в корне (backward compat): api_engine.py, config_loader.py и др.
  #   → каждый делает: from core.<папка>.<модуль> import *

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
Таргет: TP=1, SL=0. CV AUC = 0.329 — хуже случайного, **отключён** (`ml.use_outcome_predictor: false`).
Повторно включить при AUC > 0.55 (после накопления данных с заполненным `regime`).

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

- ~~`risk_manager.py`~~: удалён 18.03.2026 (active_positions был пуст, мёртвый код)
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
