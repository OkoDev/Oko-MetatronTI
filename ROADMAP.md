---
tags: [doc/roadmap, planning, phases]
type: roadmap
date: "2026-04-30"
parent: "[[Project-MOC]]"
---

# ROADMAP — Oko MTF Bot

Документ прогресса: от текущего состояния (29.04.2026) к самообучающейся торговой системе.
Включает [[Data-Invalidation-Log]] (ARCH-86) — критична для ML decisions.

---

## 🚀 Этап 12 — Confirmation-Driven Architecture (09.05–23.05.2026)

**Корневое архитектурное изменение** на основе исследований R1–R8 (90 дней backtest, 10 топ-пар, реальный OHLCV BingX).

### Принятый ЗАКОН
**«Чем больше независимых подтверждений — тем лучше сигнал.»**

Заменяет парадигму «один сигнал → strength по хардкод формуле» на «множество подтверждений → strength = Σ weight × confidence».

### Что меняется

**Триггеры (всегда работают, без regime gates):**
- `atr_change_1h` — universal trigger (avgR=+0.281 за 90 дней, n=733), вес 15
- `atr_change_4h` — премиум trigger (avgR=+0.287, n=186), вес 18
- `atr_change_15m` — entry trigger (avgR=+0.123, n=3165), вес 8

**НЕ использовать как trigger:** `atr_change_1d` (avgR=−0.4, WR=20% — late signal).

**Confluence boost (по ЗАКОНУ):**
- Zone OS на 1h при LONG → +10 веса (avgR boost +0.428R по R8)
- Zone OB на 1h при SHORT → +5
- 15m predecessor → +2..+5
- WT cross same side → +3
- CHoCH 1h+ → +6..+8
- BOS, EQL/EQH sweep, FVG fill, OTE zone, pivot touch, volume spike, divergences

Полный каталог 22+ confirmations в [docs/TASKS_DETAILS.md → DEV-200](docs/TASKS_DETAILS.md).

### Архитектурный сдвиг

| Аспект | До v2 | После v2 |
|---|---|---|
| strength формула | хардкод `base + bonuses` | `Σ weight × confidence` |
| Куб Метатрона | 10/12 сфер активны | каждое confirmation = ребро от сферы → шина |
| EventBus | 22 events, 14 публикуются | 30+ confirmations публикуются |
| ML обучение | per signal_type (5 ярлыков) | per confirmation (30+ feature importance) |
| Regime gate | RANGE/TREND блокирует | analytics-only, НЕ блокирует |

### Спринт-задачи (DEV-199..205 + ARCH-112 + TR-003)

1. **DEV-199** 🔴 ATR Trend Change events publisher (15m/1h/4h)
2. **DEV-200** 🔴 ConfirmationRegistry (22+ types, dataclass)
3. **DEV-201** 🔴 SignalAggregator v2 (Σ weight × confidence)
4. **DEV-202** 🟡 features_json: confirmations[] гранулярно
5. **DEV-203** 🟡 DecisionTrace в 14 gates (Phase 0 Stabilization, параллельно)
6. **DEV-204** 🟢 ML Outcome retrain weights (после 200+ trades)
7. **DEV-205** 🟢 audit_mode shadow + audit_trades (Phase 1+2 Stabilization)
8. **ARCH-112** 🟢 архитектурный аудит соответствия Кубу
9. **TR-003** 🟡 валидация Confirmation Registry (20 SHADOW сделок)

### Acceptance criteria этапа

- ✅ За 24h после рестарта в БД новые `atr_change` события 3-х ТФ
- ✅ Все новые сделки имеют `features_json.confirmations: list[dict]` (среднее ≥2.5 на сделку)
- ✅ `signal_drops` дашборд показывает топ-10 reasons (закрытие 96% molчaliвых потерь)
- ✅ Регрессия: 7 дней без падения avgR ниже baseline −0.437
- ✅ Прогресс: avgR за 14 дней → ≥ −0.10 (цель: ≥+0.10 за 30 дней)

### Опровергнуто исследованиями (НЕ делаем)

- ❌ DEEP_CASCADE с 3m WT cross (R1: 0 событий / avgR=−0.131)
- ❌ Adaptive entry TF от regime (regime gate отменён)
- ❌ 1d ATR change как trigger (R8: avgR=−0.4)
- ❌ Cascade-фильтр (требовать 15m predecessor) — Δ=+0.014R (бесполезно)
- ❌ Trend-only alignment без zone (R2: avg ≈0R, шум)
- ❌ Высокий MTF alignment (≥80%) для pivot_reversal — ВРЕДИТ (R5: avgR=−0.58)

### Backtest данные (91 дней, 10 топ-пар, реальный OHLCV BingX)

| Setup | n | avgR | totalR | WR% |
|---|---|---|---|---|
| 1h_LONG ATR change | 733 | **+0.281** | +206 | 53.8% |
| 4h_SHORT ATR change | 186 | **+0.287** | +53 | 54.3% |
| 1h_SHORT ATR change | 739 | **+0.164** | +121 | 51.4% |
| 4h_LONG ATR change | 183 | +0.169 | +31 | 44.3% |
| 15m_LONG ATR change | 3165 | +0.123 | +390 | 52.1% |
| 15m_SHORT ATR change | 3168 | +0.036 | +114 | 47.7% |
| Zone OS confluence (1h_LONG) | 15 | **+0.701** | +10.5 | 66.7% |
| **1d ATR change** | 9-11 | **−0.378..−0.489** | -8.8 | 18-22% |

Скрипты: `e:\tmp\R1_deep_cascade.py` ... `e:\tmp\R8_atr_90days.py`.

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

## ✅ Этап 9.1 — WT Type B Research + wt_b_signal (15.03.2026)
**Цель:** найти и внедрить класс сигналов с высоким WR через систематический бэктест

### Исследование (scripts/analyze_wt_typeB.py)
- 103 пары, 180 дней, 1h таймфрейм — полный цикл: данные → гипотезы → тесты → реализация
- **Тип B:** CrossUP/DOWN ВО время нахождения WT в OS/OB + дивергенция (второй лоу > первого)
- **div_strength > 20 = антисигнал** — WR=33% (слишком большой разрыв = продолжение тренда)
- **div_strength 3-20 = оптимальный диапазон** — WR=84.9%, avgRet=+4.82% (n=59)
- **4h soft check** (WT 4h в OS/OB) → WR=87.2% (39/59 сигналов подтверждены)
- Adaptive OS/OB thresholds: p10/p90 из серии wt1 (vs fixed ±60)

| Стратегия | n | WR | avgRet |
|---|---|---|---|
| Тип A (текущий wt_signal) | ~500+ | ~49% | ~+0.5% |
| Тип B без фильтров | 158 | 57% | +1.6% |
| Тип B, div_strength 3-20 | 59 | **84.9%** | **+4.82%** |
| Тип B, div_strength 3-20 + 4h OS | 39 | **87.2%** | **+4.78%** |

### Реализация
- `core/signal_models.py` — `WT_B_SIGNAL = "wt_b_signal"`
- `core/signal_checkers.py` — `check_wt_b_signals()` с adaptive thresholds + div_strength фильтром
- `core/trading_intelligence.py` — вес 0.15
- `config.yaml` — секция `analysis.wt_b`
- `core/trade_simulator.py` — bug-fix: приоритетный список signal_type в _signal_type_from_recommendation

### Bug-fix: signal_type priority
asyncio.gather возвращает результаты в порядке аргументов → anomaly всегда первый в supporting_signals.
Исправлено приоритетным списком: `wt_b_signal > mtf_bias > confluence > pivot_reversal > ...`

## ✅ Этап 9.0 — SMC (Smart Money Concepts) базовая реализация (14-15.03.2026)
- `core/structure_detector.py` — detect_swing_highs_lows, detect_choch, detect_bos, detect_structure
- BOS > CHoCH по приоритету; strength: BOS=65, CHoCH=55
- `core/signal_checkers.py` — check_smc_signals() → SignalData(SMC_STRUCTURE)
- `core/signal_models.py` — SignalType.SMC_STRUCTURE
- 25/25 тестов в test_structure_detector.py
- Восстановлены check_divergence_signals / check_pivot_signals после рефакторинга ARCH-02

## ✅/🔲 Этап 10 — MTF Interpreter как аналитический центр (ARCH-12, 16.03.2026)
**Статус:** Шаги 1-4 ГОТОВЫ | Шаг 5 (ML на MTF фичах) ждёт накопления данных
**Приоритет:** КРИТИЧЕСКИЙ — архитектурный переход, меняет принцип работы бота

### Предпосылки (16.03.2026, анализ 210 сделок за 15-16.03)
- **82% сделок — SHORT**, WR SHORT = 33.5% (убыточно)
- **WR LONG = 67.6%** — в 2 раза лучше, но бот почти не лонгует
- **29 SHORT** выбиты одним пампом за 35 минут (коррелированный риск)
- **74% SL-сделок** были в плюсе (avg max_R=5.3) перед разворотом в убыток
- Бот ловит медвежьи сигналы на 15m внутри бычьего тренда на старших ТФ
- **Корень:** сигнал на 15m принимает решение, а старшие ТФ — только подтверждают

### Суть изменения
Инверсия порядка принятия решений: **анализ → решение → вход** вместо **сигнал → анализ → решение**.

`mtf_interpreter.py` из генератора сигнала (один из 6 чекеров) превращается в **аналитический центр** — единый фундамент для всех остальных компонентов.

### Архитектура ДО (плоская модель)
```
6 чекеров параллельно (anomaly, wt, mtf, trend, mtf_bias, wt_b)
  │
  ▼ плоский список сигналов (все равны)
  │
  стратегия (confluence/reversal/trend) — голосование
  │
  ▼ recommendation
  │
  monitoring — постфактум фильтры (BTC, dedup)
```

Проблема: 15m-сигнал **решает** направление. Старшие ТФ и пивоты — декорация.

### Архитектура ПОСЛЕ (иерархическая модель)
```
┌──────────────────────────────────────────────────┐
│  CORE ANALYTICS — mtf_interpreter (центр)        │
│                                                  │
│  Вход: snapshot 7 ТФ + пивоты 1M/1W/1D + regime │
│                                                  │
│  Выход: MTFContext {                             │
│    direction_bias: LONG/SHORT/NEUTRAL            │
│    bias_strength: 0.0-1.0                        │
│    price_zone: 0.0-1.0 (S5→R5 weekly)           │
│    wt_spreads: {tf: |wt1-wt2|}                   │
│    senior_reversal: dict|None                    │
│    regime: TREND_UP/DOWN/RANGE/HIGH_VOL          │
│  }                                               │
│                                                  │
│  Это КОНТЕКСТ, не сигнал.                        │
│  Говорит "куда смотреть", не "входи".            │
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────┐
│  SIGNAL LAYER — поиск точки входа                │
│                                                  │
│  Получает: MTFContext + OHLCV                    │
│  Ищет ТОЛЬКО в разрешённом направлении           │
│                                                  │
│  WT cross, confluence, pivot reversal,           │
│  divergence — как тайминг, не как решение        │
│                                                  │
│  strength *= context.direction_multiplier(dir)   │
│  SHORT у S2_weekly + bias=LONG → strength × 0.4  │
│  LONG у S2_weekly + bias=LONG → strength × 1.5   │
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────┐
│  EXECUTION LAYER — SL/TP/размер                  │
│                                                  │
│  SL: swing_low/high (из структуры)               │
│  TP: пивот иерархия (1M>1W>1D)                   │
│  Размер: Kelly × regime_multiplier               │
│  Тип: reversal (быстрый TP) / trend (широкий TSL)│
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────┐
│  RISK LAYER — последний фильтр                   │
│                                                  │
│  Dedup, position limit, correlation guard,       │
│  BTC filter                                      │
└──────────────────────────────────────────────────┘
```

### Что меняется принципиально
| | До | После |
|---|---|---|
| Кто решает направление | 6 чекеров голосуют | mtf_interpreter (старшие ТФ + пивоты) |
| Роль 15m сигналов | Решение | Тайминг входа |
| Пивоты | Только для TP (постфактум) | Фундамент анализа (зоны покупок/продаж) |
| Regime | Не используется (regime=None) | Определяет тип торговли |
| Strategies layer | 7 стратегий голосуют | Профили execution (reversal/trend) |

### Данные в MTFContext (уже доступны, но теряются)
| Данные | Источник | Текущий статус |
|--------|----------|---------------|
| wt2 по каждому ТФ | collect_mtf_data | Собирается, выбрасывается из tf_table |
| tf_table (28 фичей) | interpret() | В SignalData.data, не пишется в features_json |
| bull_pct / bear_pct | interpret() | Только в SignalData.data |
| senior_reversal | detect_senior_reversal() | Вычисляется, никем не читается |
| price_zone (пивоты) | pivot_calculator | Не связан с MTF пайплайном |
| wt_spread по ТФ | wt1-wt2 | Не вычисляется (wt2 выброшен) |

### План реализации (инкрементальный)
| Шаг | Что | Эффект |
|-----|-----|--------|
| 1 | `analyze_context()` → MTFContext (вернуть wt2, считать spreads, senior_reversal) | Данные доступны |
| 2 | `_apply_mtf_context()` — адаптивные множители strength по направлению и зоне | Мягкий фильтр (без блоков) |
| 3 | Обогатить MarketContext полями из MTFContext | Стратегии видят контекст |
| 4 | Писать полный снапшот в features_json (40 фичей) | Данные для ML |
| 5 | ML модель P(win) на MTF фичах (через 1-2 недели накопления) | Learned bias вместо rule-based |

### Принципы
- **Адаптивные веса, не жёсткие блоки** — SHORT на бычьем рынке ослабляется, но не запрещается (разворот от R5 должен пройти)
- **Инкрементальный переход** — каждый шаг можно откатить, данные собираются параллельно
- **ML обучение на пивотах** — после накопления 200-300 сделок с MTF фичами

---

## ✅ Этап 11.1 — SMC пакет core/smc/ (ARCH-17, 18.03.2026)
**Цель:** полная SMC-библиотека для фильтрации сигналов и бэктеста

- `core/smc/swing_points.py` — HH/HL/LH/LL классификация (≥2 бара каждая сторона)
- `core/smc/structure.py` — BOS/CHoCH детектор, серия swing points → структура
- `core/smc/fvg.py` — Fair Value Gap (3-свечной дисбаланс), mitigation tracking
- `core/smc/order_blocks.py` — OB = последняя свеча перед BOS/CHoCH, mitigation_pct
- `core/smc/liquidity.py` — sweeps (пробой swing high/low на 1 бар с возвратом)
- `core/smc/ote.py` — OTE зона (0.618-0.786 Fibonacci от импульса)
- `core/smc/context.py` — SMCContext: агрегат всех SMC-данных для символа/ТФ
- Принцип: **одно вычисление → многократное переиспользование** (SMCContext кэшируется)

## ✅ Этап 11.2 — Backtesting блок (DEV-32–35, 21-22.03.2026)
**Цель:** валидация стратегий на исторических данных с корректной экономикой

- **DEV-33 (commission):** `commission_pct` теперь применяется в `backtesting_engine.py` (был определён, но никогда не вычитался)
- **DEV-34 (SMC-эксперимент):** cfg1 (только флаги) / cfg2 (require OB) / cfg3 (OB+FVG) — 3 конфига для валидации гипотезы
- **DEV-35 (MultiSource):** `data_source="binance"` + `data_source="cryptocom"` в `BacktestConfig` — история с 2018 вместо даты листинга на BingX
- `scripts/universe_builder.py` — CoinGecko top-250, стратификация 3 тира (top-10 / 11-50 / 51-200), seed=42, воспроизводимо
- `scripts/multi_source_ohlcv.py` — автовыбор лучшего источника: Binance → Crypto.com → BingX (по глубине истории)
- `scripts/run_universe_backtest.py` — оркестратор: 30 альтов, Binance, 2022-2026, Monte Carlo, JSON-отчёт

**Ключевой результат DEV-30:** SL=0.3% (pivot × 0.997), EV=+0.256 vs baseline EV=+0.115 (2.2×). WR=23.1% при avg_R=+1.108 — автоматизация убирает эмоцию.

## ✅ Этап 11.3 — ARCH-23: WT + NEAR_PIVOT → confluence (22.03.2026)
**Цель:** апгрейд wt_signal → confluence при детекции WT-кросса у пивотного уровня

- `PivotCalculatorFixed.find_near_pivot(price, symbol, threshold_pct=1.0)` — новый метод (core слой, переиспользует прогретый pivot_cache)
- `scan_loop.py::scan_one()` — апгрейд в реальном пути выполнения:
  - WT cross в OS/OB + цена в ±1% от пивота (1M > 1W > 1D) → `signal_type = CONFLUENCE`, `strength += 20` (cap 95)
  - Данные пивота пишутся в `sig.data` для трассировки
- **Принцип:** одно вычисление пивота (при прогреве) → переиспользование при каждом WT-сигнале без дополнительных API-вызовов
- **Данные:** avg_R без пивота = +0.32 (n=472), с пивотом = +1.27 (n=~56) — разрыв 4×

## ✅ Этап 12 — Фильтры качества сделок (22–25.03.2026)
**Цель:** устранить систематические потери: контр-тренд входы, нереальные R:R, дублирование активов

- **DEV-32/41**: `regime_direction_block` — запрет LONG при TREND_DOWN и SHORT при TREND_UP
- **DEV-33**: `blocked_regimes: [HIGH_VOL]` — WR=0% в HIGH_VOL, входы отключены
- **DEV-35/64A**: `max_rr` cap — 6.0 → 3.0, устранены R:R=17–23x у pivot_reversal
- **DEV-37/ARCH-34**: Pivot Proximity Filter — входы только у пивотных уровней (ATR-adaptive)
- **DEV-38/ARCH-35**: Correlation Guard — не дублировать коррелированные активы (PAXG/XAUT и т.д.)
- **DEV-44/46**: второй рубеж защиты в `register_trade_async()` — все code-paths защищены
- **DEV-45**: Singleton PivotCalculatorFixed — 600 лишних инстансов/час устранены
- **DEV-49**: timezone-баг в created_at (UTC+3 → UTC), 948 старых сделок помечены
- **DEV-55/ARCH-46**: PIVOT_TOUCH staleness — штраф за устаревшие (>5 баров) касания

---

## ✅ Этап 13 — Top-Down контекст и L3 shadow mode (24–27.03.2026)
**Цель:** добавить макро-контекст и подготовить 6-условный чеклист входа

- **DEV-40**: DUAL_TP стратегия — TP1=ATR от входа, BE после TP1, TSL на остаток
- **DEV-56/58/ARCH-48**: Weekly Bias Filter — `price vs weekly PP` как top-down фильтр (shadow → production)
- **ARCH-50**: MTF Phase Detector — IMPULSE/CORRECTION/CASCADE_OS паттерны в MTFContext
- **DEV-52/53**: L3 shadow mode — 6-условный чеклист (структура 1h + score≥85 + портфельный лимит + WT freshness + CHoCH penalty)
- **ARCH-49**: Dynamic OS shadow — live-сравнение dynamic vs fixed порогов (30 дней)
- **DEV-67**: Cascade TSL fallback — при развороте тренда не "падает" на entry TF

---

## 🔲 Этап 14 — Multi-TF SMC и L3 production (план ≈06–15.04.2026)
**Цель:** система "видит" 4h/1D структуру, L3 чеклист включается в production

- **DEV-63/ARCH-51**: MTFSMCSnapshot в MTFContext — 4h и 1D OB/FVG/BOS видимы в pipeline
- **L3 production gate**: включить после накопления статистики shadow mode
- **Weekly Bias production (DEV-58)**: включить ≈27–29.03 после 3–5 дней данных
- **ARCH-45**: ревью OutcomePredictor — переобучение, AUC, решение о включении

---

## ✅ Этап 11 — Operations Dashboard (ARCH-13, 16.03.2026)
**Приоритет:** СРЕДНИЙ — операционный контроль бота без правки кода

### Предпосылки
- Future pivot alerts спамят ~30 сообщений за цикл в TG
- Настройки размазаны: web `/settings` (часть), config.yaml, хардкод
- Нет лайв-статуса (BTC режим, ML модели, скан-цикл) в одном месте
- Нет быстрых тогглов для вкл/выкл функций без перезапуска

### Архитектура
```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Telegram    │────▶│  /api/dashboard  │◀────│  Web UI      │
│  InlineKB    │     │  /api/toggles    │     │  /dashboard  │
│  (быстрый)   │     │  /api/actions    │     │  (полный)    │
└─────────────┘     └──────────────────┘     └──────────────┘
                           │
                    ┌──────┴──────┐
                    │ config.yaml │
                    │ + hot reload│
                    └─────────────┘
```

### Блоки
| Блок | Описание |
|------|----------|
| Live Status | Цикл скана, пары, BTC режим, ML, сигналы/час, WR |
| Тогглы | future_pivot→TG, mtf_register, cascade_div, confluence, TSL, BE, BTC mode |
| Quick Params | min_strength, dedup, cooldown, max_confluence, counter_trend_thr |
| Actions | Rescan, retrain ML, export CSV, reset counters |

### Новые конфиг-флаги
| Ключ | Default | Описание |
|------|---------|----------|
| `future_pivots.broadcast_tg` | false | Future pivot alerts в Telegram |
| `signals.mtf_alert_register` | true | Регистрация MTF reversal в симулятор |
| `signals.cascade_div_enabled` | true | Каскадные дивергенции |

---

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

## ✅ Этап 8.4 — Quality Gate до принятия сделки (14-16.03.2026)
**Цель:** повысить качество входов и снизить ложные регистрации до отправки в TG/БД

### ✅ 8.4.1 — Целостность данных перед анализом
- [x] `core/data_quality.py` — pre-check OHLCV (глубина/свежесть/NaN)
- [x] Интеграция в scan_one и _collect_all_signals

### ✅ 8.4.2 — Консистентность пайплайна
- [x] Единый `snapshot_time` до gather OHLCV
- [x] `_collect_all_signals()` → `(signals, quality)` tuple
- [x] No silent fallback: df_1h is None → hard block

### ✅ 8.4.3 — Таймауты и degraded-mode
- [x] HARD timeout 20s на сбор сигналов → return None
- [x] SOFT timeout 15s на market context → degraded + fallback
- [x] `analysis_quality = full|degraded|timeout` в metadata
- [x] 8 тестов `tests/unit/test_quality_gate.py`

### ✅ 8.4.4 — Дедуп по (symbol, signal_type, direction) (коммит 940a81e)
### ✅ 8.4.5 — Hidden divergence фильтр в RANGE/HIGH_VOL (коммит de9df08)

### 🔲 8.4.6–8.4.9 — Калибровка, наблюдаемость, тестовый контур, операционный контроль
- [ ] Калибровать confidence на реальных исходах (reliability curve)
- [ ] Decision trace для каждой сделки
- [ ] Replay-тесты на исторических окнах
- [ ] Еженедельный auto-review метрик

## ✅ Этап 8.5 — Strategy Pattern (ARCH-05, 15.03.2026)
**Цель:** модульная архитектура для стратегий и A/B тестирования

### ✅ Реализовано:
- [x] `strategies/base.py` — BaseStrategy(ABC): analyze(), calculate_sl_tp()
- [x] `strategies/registry.py` — @register_strategy, get_strategy(), list_strategies()
- [x] `strategies/built_in/` — confluence, reversal_scanner (ex-confluence_scanner), conservative, pivot_reversal, mtf_bias
- [x] `trading_intelligence.py` — _run_strategy(), _run_all_strategies() с asyncio.gather
- [x] `config.yaml` — `trading.active_strategy`, `trading.active_strategies`
- [x] 22 regression-теста в `tests/unit/test_strategy_pattern.py`

### 🔲 Планы (Phase 2):
- [ ] Hot-reload стратегий через `/api/strategies/switch/{name}`
- [ ] RuleEngine (YAML-driven стратегии)
- [ ] EnsembleStrategy (голосование N стратегий)

---

## ✅/🔲 Этап 9 — SMC (Smart Money Concepts)
**Цель:** стратегия на основе структуры рынка

### ✅ Базовая реализация (14-15.03.2026):
- [x] `core/structure_detector.py` — Swing H/L, CHoCH, BOS, detect_structure()
- [x] `core/signal_checkers.py` — check_smc_signals() → SignalData(SMC_STRUCTURE)
- [x] `core/signal_models.py` — SignalType.SMC_STRUCTURE, вес 0.12
- [x] 25/25 тестов в test_structure_detector.py

### 🔲 Расширение (Phase 2):
- [ ] Order Block — последняя свеча импульса перед BOS (зона входа/SL)
- [ ] Fibonacci 0.618 — зона входа на откате от импульса
- [ ] SMC-специфичная стратегия в strategies/built_in/

---

---

## 🔄 Этап 15 — Signal Quality & Adaptive Gates (апрель 2026, в работе)

**Цель:** система фильтрует сама себя — не «что войти», а «когда НЕ входить».

**Реализовано:**
- ✅ DEV-155: `min_strength_by_regime` — HIGH_VOL=85, LONG_RANGE=75
- ✅ DEV-156: Circuit Breaker — WR<15% → +10 к порогу на 30 мин
- ✅ DEV-157: guard аномального SL (dist<0.1% → пропуск)
- ✅ DEV-110/ARCH-55: RANGE BOUNCE — SL/TP от пивотов при RANGE режиме
- 🔄 DEV-111b/act: BTC 4h gate с HIGH_VOL блоком (дедлайн 14.04)
- 🔴 DEV-153: VerdictGate activation (verdict_gate.enabled: true)

**Результат:** три независимых рубежа защиты качества сигналов работают последовательно.

---

## 📍 ТЕКУЩАЯ ТОЧКА (29.04.2026) — Спринт «Реальные убийцы» (Фаза 0)

**Контекст:** система технически работает, но теряет деньги (-780R/10дней).
D1 (диагностика) + RE-AUDIT (правильные метрики) показали 5 реальных убийц.

**Фаза 0 — фиксы убийц (25.04–02.05.2026):**
- ✅ DEV-190: effective_status (скрытые TSL_hidden_win видимы в аналитике)
- ✅ DEV-185.2: emergency watchdog (catastrophic slippage → market close)
- 🔄 DEV-185: catastrophic slippage расследование + sl_limit_buffer
- 🔄 DEV-184: отключить DUAL_TSL strategy_type (−290R/10дн)
- 🔄 DEV-186: wt_signal regime gate SHORT→TREND_UP (−24R)
- 🔄 DEV-187: wt_b floor для адаптивных порогов (−17R)
- 🔄 DEV-188: pivot_reversal SHORT TREND_DOWN: касание уровня shadow

**Фаза 1 — архитектурный долг Куба (май 2026):**
- ARCH-101: Mesh шины (11 детекторов → EventBus)
- ARCH-102: BTCRegimeProvider → cross_market publish
- ARCH-103: reversal_mode production (зависит от +avgR в Фазе 0)
- ARCH-104: унификация нумерации сфер (до новых сфер)
- ARCH-96: Execution Sphere S14 (блокирует LIVE)

**Фаза 1.5 — TriggerBus + data (май–июнь 2026):**
- ARCH-105: Order Flow & Macro data sources
- ARCH-106: TriggerBus + persistence (100k+ событий)

**Фаза 2 — новые сферы ML (июнь 2026):**
- ARCH-97: Anomaly Detection Sphere S15
- ARCH-98: Portfolio Manager Sphere S16
- ARCH-99: Meta-Learning Sphere S17

**Фаза 2.5 — Setup Engine v1 (июль 2026):**
- ARCH-107: Setup Engine S18 (state machine + persistence)
- ARCH-108: Predictive entries (limit orders в зоне)

**Фаза 3 — Execution (после Setup Engine):**
- ARCH-109: Strategy DSL (yaml-стратегии)
- TR-002: бэктест H1-H10 на TriggerBus данных

---

## ⚠️ Data Invalidation Log (ARCH-86)

Артефакты данных живут дольше фиксов в коде. Сделки до следующих дат нельзя использовать в ML/анализе:

| Фикс | Дата | Что инвалидирует |
|---|---|---|
| DEV-157 (min_sl_dist_pct) | 2026-03-15 | data_era v1 → data_era v2: SL < 0.2% → micro-SL артефакт. 180+ сделок с R=+112 по пампу |
| DEV-171 (confluence strategy) | 2026-04-14 | data_era v2 → v3: confluence выключена как стратегия. Avg_R=+3.48 = иллюзия (median=-1.0) |
| DEV-174 (TSL 3 бага) | 2026-04-15 | data_era v3: TSL не активировалась, не двигала SL, писала неверные статусы. Все сделки до 15.04 с tsl_activated=1 — подозрительны |
| DEV-175 (slippage) | 2026-04-15 | data_era v3: SL исполнялся по рыночной цене без буфера → аномальный slippage. 16% сделок R < -1.5 артефакт |
| LIVE-GUARD fix (sim_only) | 2026-04-29 | execution_mode=sim_only был сломан: exchange_order_id="SIM" → bool=True → SL execution заблокирован. Strip-бот накопил 200+ stuck OPEN. Не влияет на main (vst), но любые pre-fix sim_only данные = мусор |
| smc_snap fix (5 багов в `_build_smc_snap_from_df`) | 2026-04-29 | data_era v3 → **v4**: 6 из 9 SMC полей всегда False (ob/fvg/ote/eqh/eql/liq) — wrong API calls + ImportError detect_ote_zone. Активных значений: 2/36 → 16-19/36. **MTFSMCSpecialist обучался на мусоре.** Все pre-fix smc_snap бесполезны для ML |

**Правило для ML:** обучать только на `created_at >= '2026-04-15'` (data_era v3) для общих фичей.
**Правило для SMC ML (MTFSMCSpecialist):** обучать только на `created_at >= '2026-04-29 22:00'` (data_era v4).
**Правило для аналитики:** перед утверждением «N% сделок плохие по X» — указывать data_era в запросе.

---

## 🔲 Этап 16 — OTE Production & Shadow Extended (апрель–май 2026)

**Цель:** OTE сигнал готов к production — первый сигнал с Sharpe > 2 в системе.

**Шаги:**
1. DEV-88: приземлить `min_zone_tf:"4h"` + `require_choch:true` в `detect_ote_signal()`
2. DEV-89: shadow на 20 парах / 90 дней — критерий `WR≥40% ∧ Sharpe≥1.5 ∧ n≥150`
3. Логировать `ote_confluence_count`, `ote_primary_tf`, `ote_entry_regime` в features_json
4. При успехе DEV-89 → создать DEV-90 (OTE production, weight=0.15)

**Почему важно:** C1 (4h+CHoCH) показал Sharpe=2.68 на бэктесте — это лучший риск-скорректированный результат в системе на сегодня. Если shadow подтвердит — это меняет струк��уру весов сигналов.

---

## 🔲 Этап 17 — Куб Метатрона: MCP External Layer (апрель–июнь 2026)

**Цель:** Куб становится когнитивной системой с внешним AI-слоем.

**Фаза 1 (✅ готово, 12.04.2026):** `/api/cube/context`, `/api/cube/event`, `/api/cube/ml/train`
Claude читает живое состояние 12 сфер, триггерит Full CALL, запускает ML вручную.

**Фаза 2 (следующий спринт):** `/api/cube/simulate`
Быстрый параметризованный бэктест одной стратегии на одном символе (~5-10 сек).
Использование: «проверь гипотезу — что если добавить SMC Bull OB как обязательный фильтр?»

**Фаза 3 (май–июнь 2026):** MCP Server (Python SDK)
Обернуть `/api/cube/*` в нативный MCP сервер — Claude видит `get_pair_context`, `inject_event`,
`simulate` как встроенные инструменты без WebFetch. Добавить в `.claude/settings.json`.

**Фаза 4 (CUBE-06, после накопления данных):** Narrative Builder v2
Claude читает PairFullState (все 12 сфер + история событий) → строит развёрнутый торговый
нарратив → публикует в TG. Отличие от текущего DEV-151: видит весь контекст, не только recommendation.

---

## 🔲 Этап 18 — Moment Score & Market Uncertainty (май–июнь 2026)

**Цель:** от бинарных сигналов к градуированному «качеству момента».

### 18.1 — Moment Score (Гипотеза 1)

Идея: PairFullState хранит значительно больше информации чем используется для принятия решения.
`cascade_count`, `wt_verdict`, `smc_verdict`, `reversal_mode`, `regime`, `wt_snap` по всем TF —
это не отдельные сигналы, а **торговое давление**. Можно построить:

```python
moment_score = f(
    wt_verdict_confidence,    # WT Specialist уверен?
    smc_verdict_confidence,   # SMC Specialist уверен?
    reversal_mode,            # REVERSAL > TREND > UNCLEAR
    cascade_count_norm,       # норм. счётчик убытков (чем выше — хуже)
    regime_quality,           # TREND > RANGE > HIGH_VOL
    tf_alignment_pct,         # % TF смотрят в одном направлении
)
```

Входить только при `moment_score > 75`. Проверка за 1 день: выгрузить features_json +
PairState на момент каждой сделки → построить скор → корреляция с R_multiple.
Если r > 0.3 — рабочий фильтр.

### 18.2 — Market Uncertainty Score (Гипотеза 2)

Идея: система должна знать когда она не знает.

```python
uncertainty_score = f(
    cascade_count > 2,             # система в стрике убытков
    reversal_mode == "UNCLEAR",    # MTF противоречие
    wt_snap_contradiction,         # 4h bullish, 1d bearish — конфликт
    regime == "HIGH_VOL",          # хаотичный рынок
)
```

При `uncertainty_score > threshold` → не входить вообще (не поднимать порог, а блокировать).
Разница: Circuit Breaker реагирует постфактум (WR упал). Uncertainty — проактивный сигнал
«прямо сейчас непредсказуемо».

**Реализация:** `core/context/moment_scorer.py` — читает PairState, возвращает (moment_score, uncertainty_score).
Применяется в `is_actionable()` как дополнительное условие.

---

## 🔲 Этап 19 — Experience-Based Trading (июнь–сентябрь 2026)

**Цель:** система использует собственную историю как базу знаний.

### 19.1 — Feature Store (CUBE-03)

Каждая сделка в `simulated_trades` с заполненным `features_json` — это вектор опыта.
Feature Store превращает историю в retrieval engine:

```
Запрос: "найди ситуации похожие на текущий BTC — WT oversold 4h + CHoCH + pivot S1"
→ Qdrant vector search → top-20 исторических сетапов
→ avg_outcome: TP в 63%, avg_R: 0.82
→ наиболее частые дополнительные условия при success: smc_bull_ob=True, cascade_count<2
```

Это **retrieval-augmented trading** — принципиально новый класс решений.
Триггер: `n ≥ 5000 сделок` с заполненным features_json И AUC > 0.55.

### 19.2 — Asymmetric Predictors (Гипотеза 4)

Идея: LONG и SHORT — разные явления. Паника быстрее эйфории. SHORT-сигналы
более технические и менее зашумлены сентиментом. Разделить OutcomePredictor:

```python
long_predictor  = OutcomePredictor(direction="LONG",  features=[...])
short_predictor = OutcomePredictor(direction="SHORT", features=[...])
```

Гипотеза: SHORT-модель покажет AUC > LONG-модели при тех же данных.
Реализация: разделить выборку в `outcome_predictor.py`, обучать два независимых RFC.
Триггер: `n ≥ 300 LONG` И `n ≥ 300 SHORT` закрытых сделок с features.

### 19.3 — Hypothesis Engine (CUBE-04)

Замыкает петлю: Claude генерирует гипотезу → CUBE-02 тестирует → лучшие добавляются в shadow.

```
Цикл Hypothesis Engine:
1. Claude анализирует PairState + недавние исходы
2. Генерирует гипотезу: "добавить SMC Bull OB как фильтр для LONG в RANGE"
3. POST /api/cube/simulate → WR: 41% → 56%, n=28
4. Если дельта > 10pp → создать DEV-NNN "shadow test [гипотеза]"
5. После 100 shadow сделок → ARCH review → production или discard
```

Это первая петля обратной связи человека-AI-системы. Система перестаёт быть инструментом
и становится соавтором стратегии.

---

## 🔲 Этап 20 — Production Readiness & LIVE (август–сентябрь 2026)

**Цель:** переход от симуляции к реальной торговле с доказанным edge.

**Критерии готовности к LIVE:**
- WR ≥ 38% (TP+TSL) на новых данных (апрель 2026+, без timezone-бага)
- AUC OutcomePredictor ≥ 0.55 (модель умеет различать winners/losers)
- Moment Score корреляция с R_multiple ≥ 0.3 (скор работает)
- 500+ DUAL_TSL сделок → аудит split 10%/90% пройден (TRADER-AUDIT-002)
- OTE C1 shadow WR ≥ 40% подтверждён (DEV-89)
- Dead-Man Timer реализован (DEV-104) — emergency close all

**Порядок включения:**
1. VST (Virtual Spot Trading) — биржа, но виртуальные деньги. Уже работает.
2. LIVE micro-lot (0.01% риска) — 2 недели наблюдения
3. LIVE normal (1% риска) — при подтверждении edge

### Этап 20.1 — Strategy Generator (CUBE-07, Q4 2026+)

Только после стабильной прибыли в LIVE за 3+ месяца. Genetic optimizer стратегий,
DSL условий, sandbox-тест. Это следующий проект, не эволюция текущего.

---

## 📊 Метрики прогресса

> Обновлено: 12.04.2026

| Метрика | Сейчас | Цель (Этап 20) |
|---------|--------|----------------|
| Сделок в БД | 3 200+ | 10 000+ |
| WR (TP+TSL, апр. данные) | ~25% | ≥ 38% |
| OutcomePredictor AUC | 0.41 | ≥ 0.55 |
| OTE C1 WR (shadow) | 41.7% (бэктест) | ≥ 40% (real shadow) |
| RANGE BOUNCE активен | ✅ 12.04 | ≥ 20 сделок для оценки |
| MCP Layer (Cube API) | ✅ Фаза 1 | Фаза 3 (proper MCP SDK) |
| Hypothesis Engine | 🔲 | CUBE-04 реализован |
| Режим торговли | VST (симуляция) | LIVE micro-lot |

---

## 🗺️ Временная шкала

```
Апрель 2026:
  ├─ Этап 15 ✅ (signal quality guards)
  ├─ Этап 16 🔄 (OTE shadow start)
  └─ Этап 17 Фаза 1 ✅ (MCP Layer)

Май 2026:
  ├─ Этап 17 Фаза 2 (Simulation Engine)
  ├─ Этап 18.1 (Moment Score прототип)
  └─ ARCH-45: OutcomePredictor ревью (цель AUC > 0.55)

Июнь 2026:
  ├─ Этап 17 Фаза 3 (proper MCP Server)
  ├─ Этап 18.2 (Market Uncertainty)
  └─ Этап 19.2 (Asymmetric Predictors, если n≥300)

Июль–Август 2026:
  ├─ Этап 19.1 (Feature Store, если n≥5000)
  ├─ Этап 19.3 (Hypothesis Engine прототип)
  └─ Этап 20 подготовка (Dead-Man Timer, LIVE checklist)

Сентябрь 2026+:
  └─ Этап 20: LIVE micro-lot → LIVE normal

Q4 2026+:
  ├─ Этап 20.1: Strategy Generator (R&D)
  └─ Этап 21: CubeNode — Фрактальный Куб Метатрона

После LIVE + стабильная прибыль 30+ дней:
  Этап 21.1 — CubeNode интерфейс:
    subscribe(event, handler) / publish(event, data) / get_state() / as_sphere()
    Каждый Specialist становится самостоятельным кубом
  Этап 21.2 — Fractal Specialists:
    WTCube:     5 TF как сферы (15m, 1h, 4h, 1d, 1w)
    SMCCube:    4 структуры (OB, FVG, CHoCH, Liquidity)
    RegimeCube: 3 индикатора (ADX, ATR, EMA)
  Этап 21.3 — MarketCube:
    524 пары как CubeNode-сферы
    Корреляционные события между парами (BTC_SHOCK → блок всех SHORT)
    Горизонтальное масштабирование: WTCube на отдельном процессе
```

---

## Метрики прогресса

> Обновлено: 27.03.2026

| Метрика | Сейчас | Цель |
|---------|--------|------|
| Сделок в БД (всего) | 3 218 | — |
| Закрытых сделок | 3 100 | — |
| Win rate (TP+TSL) | 20.3% | > 35% |
| Win rate (TP only) | 4.5% | > 25% |
| avg_R (TP-сделки) | +4.99 | > 3.0 |
| avg_R (TSL-сделки) | +5.34 | > 3.0 |
| avg_R (SL-сделки) | −0.71 | > −1.0 |
| CV AUC (OutcomePredictor) | отключён (AUC=0.33) | > 0.65 |
| Пар в мониторинге | 427 | — |

> **Примечание:** WR=20.3% включает ~948 сделок с timezone-багом (закрывались по phantom SL).
> После фильтрации по data_quality реальный WR ожидается ~35–38%.

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
| 2026-03-15 | ARCH-03: ConfluenceStateMachine (SQLite persist, 5 состояний), 15 тестов |
| 2026-03-15 | ARCH-04: regime_strategy — адаптивный выбор стратегии по режиму |
| 2026-03-15 | ARCH-05: Strategy Pattern — registry, _run_all_strategies, 22 regression-теста |
| 2026-03-15 | ARCH-07: Quality Gate — snapshot_time, no silent fallback, hard/soft timeouts, 8 тестов |
| 2026-03-15 | wt_b_signal: WT Type B (div_strength 3-20, WR=85% backtest), вес 0.15 |
| 2026-03-16 | Фикс "меньше сделок": confidence signal_count_factor min 0.5 + use_state_machine=false |
| 2026-03-16 | scan_loop: random.shuffle(pairs) — убирает алфавитный bias |
| 2026-03-16 | Порядок в проекте: тесты → tests/, скрипты → scripts/, docs/ MD |
| 2026-03-16 | ARCH-11: MTF Bias фиксы (5 багов), 313/313 тестов |
| 2026-03-16 | Фикс: pivot_rec fallback не регистрировался (elif→if), MTF alert fallback_rec добавлен |
| 2026-03-16 | Future pivot alerts убраны из TG (спам ~30/цикл), только лог |
| 2026-03-16 | ARCH-13: Operations Dashboard (Web + TG) — старт реализации |
| 2026-03-16 | ARCH-12 шаги 1-4: MTFContext, analyze_context, _apply_mtf_context, 14 MTF-фичей в features_json (371 тестов) |
| 2026-03-18 | Bugfix: trade_simulator.py — shadowing `import json` блокировал 100% регистраций; market_regime.py — DataFrame truthiness |
| 2026-03-18 | SELFTEST L12: Trade Lifecycle test (register → verify OPEN → close TP → verify closed → cleanup) |
| 2026-03-18 | Performance: api_semaphore_size 5→20, api_rps 8→15 (OHLCV тормозили 7+ сек) |
| 2026-03-18 | Cleanup: risk_manager.py pyc удалены |
| 2026-03-18 | Rename: confluence_scanner → wt_15m_reversal_scanner, ConfluenceScannerStrategy → ReversalScannerStrategy ("reversal_scanner"), 8 баров, обязат. TSL+WT гейты, pivot touch 0.15%, MTF soft penalty floor=0.75 |
| 2026-03-19 | DEV-23: shadow mode динамических порогов OB/OS — core/dynamic_thresholds.py, os_method в signal data |
| 2026-03-19 | DEV-26: per-signal-type confidence пороги (wt_b_signal=0.50, confluence=0.55, anomaly=0.60) |
| 2026-03-19 | DEV-27: rolling WR degradation detector (RollingWRMonitor, порог 0.3 WR, cooldown 6h) |
| 2026-03-19 | DEV-24: wt_b_signal реанимация + state machine фикс (WR=85% сигнал, confidence min 0.5) |
| 2026-03-20 | DEV-28: двунаправленный каскадный TSL — де-эскалация при R≥5.0 + WT exhaustion + TSL tightness |
| 2026-03-20 | DEV-21: Unified Message Generator — format_signal_message() в intelligence_formatter.py |
| 2026-03-21 | ARCH-51 спек: Cascade TSL 15m→1h→4h — де/эскалация по тренду старшего TF |
| 2026-03-22 | DEV-32: regime_direction_block — запрет LONG/TREND_DOWN и SHORT/TREND_UP |
| 2026-03-22 | DEV-35: max_rr cap 6.0 — устранены R:R=24–32x у PAXG/CRCLX |
| 2026-03-22 | DEV-WL-BREACH: автовход при пробое WL пивота (SL=пивот±0.5%, TTL=4h, rate-limit 3/30мин) |
| 2026-03-22 | DEV-40: DUAL_TP — ATR-based TP1 + breakeven + TSL gate по tp1_hit_at |
| 2026-03-23 | DEV-33: HIGH_VOL в blocked_regimes (WR=0% → входы отключены) |
| 2026-03-23 | DEV-37: Pivot Proximity Filter (tier1=max(1%,ATR*1.5)) — shadow → включён |
| 2026-03-23 | DEV-38: Correlation Guard — блок дубликатов PAXG/XAUT, BTC/WBTC, ETH/STETH |
| 2026-03-23 | DEV-45: Singleton PivotCalculatorFixed — −600 инстансов/час |
| 2026-03-23 | DEV-49: timezone-баг created_at (UTC+3→UTC), fallback df без phantom-баров |
| 2026-03-23 | DEV-51: scikit-learn установлен, OutcomePredictor запущен (AUC≈0.56) |
| 2026-03-24 | DEV-44/46: второй рубеж в register_trade_async() — все code-paths защищены |
| 2026-03-24 | DEV-52: L3 Фаза A — портфельный лимит 2+2+4, структура 1h, score≥85 (shadow) |
| 2026-03-24 | DEV-56: Weekly Bias Filter Фаза A shadow — weekly_bias в features_json |
| 2026-03-24 | DEV-57: BE activation по tp1_hit_at — безусловный триггер для MULTI_TP |
| 2026-03-24 | ARCH-50: MTF Phase Detector (IMPULSE/CORRECTION/CASCADE_OS) в mtf_interpreter.py |
| 2026-03-25 | DEV-53: L3 Фаза B — cond4 (WT freshness ≤3 баров + near_pivot) + CHoCH -8 penalty |
| 2026-03-25 | DEV-55: PIVOT_TOUCH staleness — penalty -10 если касание >5 баров назад |
| 2026-03-25 | DEV-67: Cascade TSL fallback — при развороте не падает на entry TF (prev_tsl_tf) |
| 2026-03-26 | DEV-64A: global max_rr=3.0 enforce в trade_simulator + scan_loop |
| 2026-03-26 | DEV-64B: signal_regime_block — явный список запрещённых (режим+направление) пар |
| 2026-03-26 | DEV-66: TSL factor 1.1→1.25 (бэктест +0.041R), бот перезапущен |
| 2026-03-27 | OutcomePredictor отключён (AUC=0.329 < 0.5), min_strength_register 65→75 |
| 2026-03-29 | ARCH-54: core/ разбит по подпапкам (signals/ indicators/ mtf/ pivots/ trading/ ml/ smc/ intelligence/ context/ exchange/ db/ infra/ ui/) |
| 2026-03-29 | Принято решение «Куб Метатрона» — Reactive Graph инкрементальный план (Фаза 0→3) |
| 2026-04-11 | Куб Метатрона ПОЛНАЯ РЕАЛИЗАЦИЯ: PairContextBus 38 полей, 22 события, SphereRegistry, NarrativeBuilder, HTFDetectors, 13 сфер подключены к шине |
| 2026-04-12 | DUAL_TSL 10%/90% — стандарт по бэктесту 5564 сделок (+847R). DUAL_TSL strategy_type |
| 2026-04-12 | DEV-87/88: OTE Step2 бэктест C1 — WR=41.7% Sharpe=2.68 (4h+CHoCH), остаётся в shadow |
| 2026-04-12 | DEV-155: min_strength по режиму HIGH_VOL=85, LONG_RANGE=78 |
| 2026-04-12 | DEV-156: CircuitBreaker — WR<15% rolling 50 → +10 к min_strength на 30 мин |
| 2026-04-12 | DEV-157: sl_dist_pct < 0.1% → skip guard в register_trade |
| 2026-04-13 | ARCH-73..76: спеки декомпозиции TI/TradeSimulator/Monitoring + CubeNode интерфейс |
| 2026-04-13 | DEV-161: VerdictGate rule-based (EXHAUSTION direction-aware, REVERSAL_SETUP) |
| 2026-04-14 | DEV-170: Time-of-day gate 09-18 UTC (wt_signal 04-18) |
| 2026-04-14 | DEV-171: Confluence полный стоп (убыток -348R, убыточен во всех режимах) |
| 2026-04-14 | DEV-172: Entry Priority Matrix shadow P1/P2/P3 → features_json |
| 2026-04-14 | DEV-121 Cube Selftest L13/L14/L15: 27 проверок (13 сфер + 10 рёбер + 4 loop) |
| 2026-04-15 | DEV-173: Orphan epidemic fix — dynamic contract precision, tsl_updater биржа как истина |
| 2026-04-15 | DEV-174: TSL системный аудит — 3 бага (pre-filter, orig_sl current_r, direction fallback) |
| 2026-04-16 | ARCH-78: BTCRegimeProvider (ATR Supertrend 4h) production — gate SHORT при BTC BULL |
| 2026-04-16 | DEV-175: slippage fix — min_volume_usd=5M, STOP-LIMIT, sanity check R<-2 |
| 2026-04-18 | docs/CUBE_ARCHITECTURE.md: 8 Mermaid-диаграмм полной схемы Куба Метатрона |

---

## 🔲 Этап 15 — Куб Метатрона: Валидация и Фаза 1 (апрель-май 2026)

**Цель:** доказать ценность каждого узла изолированно → соединить

- **DEV-89** (🟡): OTE C1 shadow 20 пар / 90 дней. Критерий ~26.04: WR≥40% ∧ Sharpe≥1.5 ∧ n≥150
- **ARCH-55-VAL** (🟢): RANGE BOUNCE валидация shadow → 23.04
- **ARCH-45** (🟢): OutcomePredictor ревью 20.04 (цель AUC > 0.55)
- **ARCH-77** (🟡): Миникуб WTMTF — 3 ребра в derive_wt_verdict (Cross-TF Div, Momentum Flow, Zone Depth)
- **DEV-172** (🟡): Entry Priority Matrix баг — priority=None у всех сделок, нужна диагностика
- **DEV-93** (Фаза 1): PairContextBus production (post_tsl_queue, cascade_count)
- **DEV-94** (Фаза 2): PostTradeAnalyser — SL→reversal WL, TSL→OTE Re-entry
- **DEV-95** (Фаза 3): TriggerBus event-driven scan (vs uniform polling)

## 🔲 Этап 16 — Декомпозиция монолитов (ARCH-73..75, май 2026)

**Предусловие:** LIVE стабилен ≥ 2 недели

- **ARCH-73**: trading_intelligence.py (2578 строк) → MLSpecialist + StrengthAggregator
- **ARCH-74**: trade_simulator.py (1978 строк) → TSLManager + MFETracker + ExchangeSyncGuard
- **ARCH-75**: monitoring.py (1436 строк) → SignalFilter + MessageDispatcher

## 🔲 Этап 17 — CubeNode + Фрактальный Куб (ARCH-76, июнь+ 2026)

**Предусловие:** LIVE + стабильная прибыль ≥ 30 дней + AUC > 0.55 + ≥5000 сделок

```python
class CubeNode:
    def subscribe(self, event_type, handler): ...
    def publish(self, event): ...
    def get_state(self) -> dict: ...
    def as_sphere(self) -> dict: ...
```

**Философия:** Полносвязная система. Emergent Intelligence — система знает вещи которые ни один индикатор не вычислит сам по себе.

---

## 🔗 Связанные заметки в Obsidian

- [[Project-MOC]] — Map of Content (главная)
- [[Architecture/ARCH-95-Real-Killers]] — Спринт "Реальные убийцы" (25.04–02.05.2026)
- [[Architecture/ARCH-74-EXT-Smart-TSL]] — TSL система (расширение ARCH-74)
- [[Architecture/ARCH-103-Price-Forecast]] — Прогнозирование цены (5 слотов)
- [[Features/DEV-190-Effective-Status]] — Корректная разметка (8 модулей)
- [[Data-Invalidation-Log]] — ARCH-86 (критично для ML и аналитики)
- [[Sessions/2026-04-25]] — Спринт начало
- [[Sessions/2026-04-29]] — Документация и Data Era v4
