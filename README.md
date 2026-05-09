---
tags: [doc/readme, project-intro, getting-started]
type: reference
date: "2026-04-30"
parent: "[[Project-MOC]]"
---

# Oko MTF Bot — Telegram-бот для технического анализа крипторынка

Самообучающийся бот для BingX: сигналы по 8 стратегиям, симуляция сделок, ML на реальных исходах, каскадный TSL.

## Быстрый старт

```bash
pip install -r requirements.txt
cp .env.example .env   # заполнить TELEGRAM_TOKEN, ADMIN_ID, BINGX_API_KEY, BINGX_SECRET_KEY
python bot_with_subscriptions.py
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
| `wt_signal` | Откат в тренде | WaveTrend CrossUp/CrossDown в OS/OB; апгрейд +20 если цена в ±1% от пивота |
| `wt_b_signal` | Разворот | WT Type B — крест в OS/OB + дивергенция |
| `divergence` | Разворот | Regular/Hidden дивергенции WT |
| `pivot_reversal` | Разворот | Разворот от уровней пивота (1M/1W/1D) |
| `watch_list_breach` | Пробой | Автовход при пробое пивотного уровня наблюдаемой парой |
| `anomaly` | Событийный | Всплески объёма + движение цены |

---

## Команды бота

```
/start                 — главное меню
/intelligence BTCUSDT  — полный анализ символа
/scan                  — топ-10 пар по силе сигнала
/watch add ETHUSDT     — добавить в watchlist
/watchlist             — мой список пар
/wl                    — Watch List (пары в ожидании эскалации)
/wlr SYMBOL            — быстрый отчёт по паре: режим, WT, пивоты, открытая сделка
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
  intelligence/             -- signal_aggregator, confidence, ML, recommendation
  signal_checkers.py        -- детекторы: WT, WT_B, anomaly, confluence, divergence, pivot
  trade_simulator.py        -- регистрация/закрытие сделок, Cascade TSL, MFE, частичные TP
  api_engine.py             -- LRU cache, CircuitBreaker, retry, in-flight dedup
  data_collector.py         -- OHLCV + ticker (делегирует в ApiEngine)
  mtf_interpreter.py        -- MTF Phase Detector + Zone Cascade (IMPULSE/CORRECTION/CASCADE_OS)
  mtf_checker.py            -- collect_mtf_data: snapshot по ТФ (WT momentum)
  wt_15m_reversal_scanner.py -- WT Type B reversal с 1h/4h контекстом
  signal_watch_list.py      -- Watch List: автонаблюдение и пробойные входы
  market_regime.py          -- ADX+ATR+EMA → TREND_UP/DOWN/RANGE/HIGH_VOL
  pivot_calculator_fixed.py -- пивоты UTC (1M/1W/1D) singleton + find_near_pivot()
  outcome_predictor.py      -- RandomForest P(win) на реальных исходах
  performance_engine.py     -- аналитика из simulated_trades (read-only)
  smc/                      -- Smart Money Concepts (swing, BOS/CHoCH, FVG, OB, OTE)

bot/                        -- UI-слой (aiogram)
  core/bot.py               -- TradingAlertBot: инициализация зависимостей
  loops/scan_loop.py        -- цикл скана + WL breach входы
  loops/trade_tracker.py    -- трекинг сделок: Cascade TSL, MFE, BE, частичные TP
  loops/ml_loop.py          -- ML переобучение, еженедельные отчёты
  handlers/                 -- /start, /intelligence, /scan, /pivots, /settings, /wlr
  menus/                    -- диспетчер меню + доменные модули

web/                        -- aiohttp дашборд (порт 8000)
scripts/                    -- backtesting_engine.py, universe_builder.py, анализ
tests/                      -- unit + integration тесты
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
sl_source, tp_source,           ← источники SL/TP (atr_14, pivot_1W_R1, swing_low...)
tsl_activated, be_activated,    ← 0/1: достигала ли порогов TSL/BE
tsl_tf                          ← таймфрейм последнего Cascade TSL
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
  min_strength_register: 75    # минимальная сила для записи в БД

trading:
  use_tsl: true                # Trailing Stop Loss
  tsl_activation_r: 1.0       # активация TSL после +1R
  use_breakeven: true          # перевод в безубыток
  breakeven_activation_r: 0.8  # активация BE после +0.8R
  max_rr: 3.0                  # максимальный cap R:R для любой сделки
  regime_direction_block:      # запрет контр-тренд входов
    enabled: true
    TREND_DOWN: LONG
    TREND_UP: SHORT
  blocked_regimes: [HIGH_VOL]  # режимы без входов (WR=0%)
  correlation_groups:          # не дублировать коррелированные активы
    - [PAXG, XAUT]
    - [BTC, WBTC]

analysis:
  history_size: 200            # глубина OHLCV для индикаторов
  check_interval: 60           # пауза между циклами скана, сек
```

Параметры `analysis` и `trading` изменяются через `http://localhost:8000/settings` без перезапуска.

---

## TSL (Trailing Stop Loss)

Динамический стоп-лосс, следующий за трендом. Защищает прибыль после +1R.

- **Расчёт:** ATR trailing stop из `calculate_trend()` (RMA-ATR)
- **Активация:** После +`tsl_activation_r` × R (по умолчанию 1.0)
- **Безубыток:** При +0.8R SL переставляется к entry ± 0.1%
- **Для LONG:** Закрывает при пробое `trenddown`; для SHORT — при пробое `trendup`

**Cascade TSL** — при подтверждении тренда на старшем TF автоматически переключается на него:
`15m → 1h → 4h`. Старший TF = более широкий стоп = позиция держится дольше на крупном тренде.
Если тренд разворачивается и ни один TF не подходит — используется последний сохранённый `tsl_tf` (DEV-67).

---

## ML и адаптация

**OutcomePredictor** — RandomForest(200 деревьев) на реальных исходах сделок:
- 12 признаков: strength, confidence, direction, signal_type, volatility, price_change, regime
- Цель: TP=1, SL=0; CV AUC растёт с накоплением данных (нужно ~200+ закрытых сделок)
- Блендинг: `confidence = 0.7 × orig + 0.3 × P(win)`

**Адаптивные веса** — `TradingIntelligence.update_signal_weights()`:
- Формула: `factor = clamp(1.0 + avg_R × 0.4, 0.5, 2.0)`
- Порог: минимум 20 закрытых сделок на тип сигнала

---

## Производительность

| Метрика | Значение |
|---------|----------|
| Скан 600+ пар | ~25–32 сек |
| Параллельных API-запросов | Semaphore(20) |
| Cache hit (OHLCV) | LRU до 5000 записей |
| TTL кеша (15m) | 60 сек |

**Критичная настройка** (`core/data_collector.py`): `enableRateLimit: False` в ccxt.
Без этого скан занимает 20–90 минут вместо 30 секунд.

---

## Тестирование

```bash
python -m pytest tests/ -v
python -m pytest tests/unit/test_confluence_state_machine.py -v
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

---

## Документация

| Файл | Содержание |
|------|-----------|
| [PROJECT-LOG.md](PROJECT-LOG.md) | История изменений проекта — от первого запуска |
| [ROADMAP.md](ROADMAP.md) | Этапы разработки и планы |
| [TASKS.md](TASKS.md) | Активные задачи агентов |
| [BOT_SIGNAL_MAP.md](BOT_SIGNAL_MAP.md) | Сигнальный пайплайн (от данных до регистрации) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Архитектурная карта модулей |
| [docs/INDICATORS_GUIDE.md](docs/INDICATORS_GUIDE.md) | Руководство по индикаторам |
| [docs/SMC_GUIDE.md](docs/SMC_GUIDE.md) | Smart Money Concepts — теория и реализация |
| [DISCUSSION.md](DISCUSSION.md) | Живой диалог агентов (23–27.03) |

---

## 🔗 Связанные заметки в Obsidian

- [[Project-MOC]] — Map of Content (главная)
- [[START]] — Быстрый контекст сессии
- [[STATUS]] — Текущее состояние (29.04.2026)
- [[ROADMAP-2026]] — Полная временная шкала всех этапов
- [[Architecture/Cube-Metotron]] — Куб Метатрона (полная реализация)
- [[Sessions/2026-04-29]] — Последняя сессия (документация + Data Era v4)
- [[Data-Invalidation-Log]] — ARCH-86 (критично для ML)
- [[Architecture/ARCH-95-Real-Killers]] — Спринт "Реальные убийцы" (Фаза 0)
