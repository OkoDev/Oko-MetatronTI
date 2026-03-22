# Architecture Analysis — Trading Bot
**Дата:** 2026-03-19
**Статус:** Диагностика завершена, изменений не вносилось

---

## Обзор

Бот сканирует ~600 пар на BingX, детектирует торговые сигналы и отправляет алерты в Telegram.
Ниже — полный разбор архитектуры по уровням от входа данных (OHLCV) до выхода (TG + БД).

---

## Layer 0: OHLCV — получение данных

**Файлы:** `core/api_engine.py`, `core/data_collector.py`

### Как работает
- `data_collector.get_ohlcv(symbol, tf, limit)` → `api_engine` → BingX REST API
- Кэш в `ApiEngine._cache` (LRU + TTL): `15m=60s`, `1h=180s`, `4h=300s`, `1d=600s`
- Семафор `api_semaphore_size=8` ограничивает параллельные запросы
- `GlobalRateLimiter` (ARCH-16): при ошибке 100410 (temp ban) паузирует ВСЕ запросы

### В scan_loop
```python
# scan_loop.py:137-141 — ПАРАЛЛЕЛЬНАЯ загрузка всех TF за один gather
_fetch_tasks = [get_ohlcv(sym, tf, 160) for tf in _entry_tfs]  # 15m
_fetch_tasks.append(get_ohlcv(sym, "1h", 160))
_fetch_tasks.append(get_ohlcv(sym, "3m", 100))
_fetch_tasks.append(get_ohlcv(sym, "4h", 60))
_fetched = await asyncio.gather(*_fetch_tasks)  # ✅ параллельно
```

### Параллельность пар
```python
# scan_loop.py:422 — все 600 пар запускаются одновременно
await asyncio.gather(*[scan_one(sym) for sym in pairs])
# но ограничены: scan_semaphore_size = 5 (одновременно только 5 пар)
```

### Проблемы
- ✅ Кэш есть и работает
- ⚠️ `collect_mtf_data` (7 TF) в `analyze_symbol._build_mtf_context` вызывается повторно (второй раз за цикл после scan_loop:371), хотя данные ещё в кэше — wt/trend пересчитываются заново
- ⚠️ В `_build_mtf_context` дополнительно делаются `get_ohlcv(sym, "15m", 5)` и `get_ohlcv(sym, "15m", 100)` + `get_ohlcv(sym, "1h", 100)` — 3 лишних фетча для цены и режима

---

## Layer 1: Индикаторы

**Файл:** `core/indicators.py`

### Экспортируемые функции
```
calculate_wt(df, n1=10, n2=21)              → wt1, wt2
calculate_trend(df, atr_period=43, factor=1.0) → trend, trendup, trenddown, tsl
calculate_trend_strength(df)
get_zone(wt_value, ob1=60, os1=-60)
detect_fvg(df)
compute_atr(df, period=14)
compute_ema_values(values, period)
compute_volatility(closes, period=20)
compute_adx(highs, lows, closes, period=14)
compute_rsi(closes, period=14)
compute_volume_ratio(volumes, period=20)
find_swing_highs(series, period=5)
find_swing_lows(series, period=5)
calculate_pivot_points(high, low, close)
true_range_series(df)
```

### Проблема: массовое дублирование вычислений

Каждый детектор Layer 2 пересчитывает `calculate_wt` и `calculate_trend` независимо.
**Параметры всегда одинаковые:** `n1=10, n2=21`, `atr_period=43, factor=1.0`
**Кэша между детекторами нет.**

#### Таблица вызовов на одну пару за один цикл

| Файл | Строки | calculate_wt | calculate_trend | Условие |
|---|---|---|---|---|
| `signal_checkers.py` | 96 | — | ✅ | только если аномалия найдена (lazy) |
| `signal_checkers.py` | 133 | ✅ (15m) | — | всегда |
| `signal_checkers.py` | 147 | ✅ (1h) | — | всегда |
| `signal_checkers.py` | 333 | — | ✅ (1h) | всегда |
| `signal_checkers.py` | 336 | ✅ (15m) | — | всегда |
| `signal_checkers.py` | 341 | ✅ (3m) | — | всегда |
| `wt_15m_reversal_scanner.py` | 113 | ✅ (15m) | — | всегда |
| `wt_15m_reversal_scanner.py` | 114 | — | ✅ (15m) | всегда |
| `scan_loop.py` | 272–274 | ✅ (15m) | ✅ (1h) | только если check_divergences=True |
| `trading_intelligence.py` | ~820–822 | — | implied | в _build_mtf_context |
| `mtf_checker.py` | 22, 25 | ✅ × 7 TF | ✅ × 7 TF | в collect_mtf_data |

**Итого:** ~10 вызовов `calculate_wt` + ~7 вызовов `calculate_trend` на пару
вместо нужных **4** (wt + trend для 15m и 1h).

### Оценка ущерба

| Компонент | Время | При 600 парах, sem=5 |
|---|---|---|
| Один `calculate_wt(160 строк)` | ~1–3 мс | — |
| Один `calculate_trend(160 строк)` | ~2–5 мс | — |
| 10 лишних вызовов на пару | ~30–50 мс | +3–6 сек на цикл |
| Процент от 60-сек цикла | — | **5–10% потерь** |

Плюс **риск дрейфа параметров**: если параметры изменят в одном месте и забудут в другом — детекторы начнут давать несогласованные результаты.

### Правильная архитектура
```python
# scan_loop: один раз после OHLCV fetch
df_15m = calculate_wt(df_15m)
df_15m = calculate_trend(df_15m)
df_1h  = calculate_wt(df_1h)
df_1h  = calculate_trend(df_1h)
# → передаём обогащённые df во все детекторы
```

---

## Layer 2: Детекторы сигналов

**Файлы:** `core/signal_checkers.py`, `core/wt_15m_reversal_scanner.py`, `core/divergence_detector.py`

### Карта вызовов

#### В scan_loop (каждый цикл, каждая пара) — ПОСЛЕДОВАТЕЛЬНО:
```
await check_anomaly_signals(sym, df_15m)      # 1й — ждёт завершения
await check_wt_signals(sym, df_15m, df_1h)   # 2й — ждёт завершения
await check_mtf_signals(sym, df_1h, df_15m, df_3m)  # 3й — ждёт завершения
scan_wt_15m_reversal(sym, df_15m, ...)        # 4й — ждёт завершения
detect_mtf_divergence(sym, ...)               # 5й — async I/O, ждёт
detect_divergence(sym, ...)                   # 6й — async I/O, ждёт
```

#### В фоне (каждые 5 циклов):
```
check_mtf_alerts    → collect_mtf_data (7 TF!) × 600 пар
check_trend_signals → check_trend_following_signal (фетчит 4h+5m)
check_pivot_reversals → check_pivot_level_signal (фетчит 1m+5m)
check_future_pivot_alerts → future pivots (3 TF × 600 пар)
```

#### Только для тестов / backtesting (НЕ в продакшне):
```
check_divergence_signals   ← calculate_wt внутри
check_pivot_signals        ← без индикаторов
```

### Детальный разбор каждого детектора

#### `check_anomaly_signals` — ✅ умнее всех
```python
if volume_ratio > ratio_thr:           # сначала дёшево проверяет объём
    df_t = calculate_trend(df, ...)    # trend только если аномалия найдена
```
Единственный детектор с lazy-вычислением.

#### `check_wt_signals` — ⚠️ всегда пересчитывает
```python
df_wt    = calculate_wt(df_15m)        # 1-й расчёт
df_1h_wt = calculate_wt(df_1h)         # 2-й расчёт
```
Логика: cross_up/cross_down по последним 2 барам + gap ≥ 3 + фильтр 1h зоны.

#### `check_mtf_signals` — ❌ самый расточительный
```python
df_1h_trend = calculate_trend(df_1h)   # 1-й расчёт
df_15m_wt   = calculate_wt(df_15m)     # 2-й расчёт (был в check_wt_signals!)
df_3m_wt    = calculate_wt(df_3m)      # 3-й расчёт
```
3 независимых расчёта. `calculate_trend(df_1h)` уже был в `check_anomaly_signals`.

#### `check_wt_b_signals` — ❌ МЁРТВЫЙ КОД
```
- Написан, работоспособен
- Бэктест: WR=84.9%, avg_ret=+4.82% (103 пары, 180 дней)
- Адаптивные OS/OB: p10/p90 percentiles (лучше фиксированных ±60)
- В scan_loop НЕ вызывается
- В _collect_all_signals вызывается — но только при ручном запросе (без pre_signals)
- В нормальном потоке (pre_signals есть) НИКОГДА не выполняется
```

#### `check_trend_signals` — вызывается в фоне (каждые 5 циклов)
Всегда пересчитывает `calculate_trend`. Детектирует flip тренда (prev ≠ current).

#### `check_smc_signals` — ✅ не пересчитывает
Вызывает `detect_structure(df)` из `structure_detector`. Без indicator recalc.

#### `check_mtf_bias_signal` — ⚠️ фетчит данные сам
Вызывает `collect_mtf_data(symbol, data_collector)` → 7 TF × (wt + trend).
Правильно вынесен в фоновый цикл (раз в 5 мин), но создаёт 14 индикаторных расчётов.

### Проблема: последовательное выполнение детекторов

Все 6 детекторов в scan_one ждут друг друга. CPU-bound части не выигрывают от
`asyncio.gather` (GIL), но I/O-bound части (divergence) блокируют CPU-части.

**Потеря времени:**
- Для CPU-bound (`check_anomaly`, `check_wt`, `check_mtf`, `confluence`): незначительная
- Для I/O-bound (`detect_mtf_divergence`, `detect_divergence`): **30–120 мс** дополнительного ожидания
  пока предыдущие детекторы заканчивают CPU-работу

### КРИТИЧЕСКАЯ ПРОБЛЕМА: Inline дивергенция в `scan_wt_15m_reversal` СЛОМАНА

**Файл:** `core/wt_15m_reversal_scanner.py`

```python
def _check_bullish_divergence_wt(window, div_min_bars=5):
    n = len(window)
    if n < div_min_bars * 2 + 1:   # требует 5*2+1 = 11 баров
        return False
```

**Окно скоринга:** `df.iloc[-lookback_bars-1:-1]` = 8 строк
**Результат:** `8 < 11` → **всегда False**

`WT_DIVERGENCE` (+20 очков) и `WT_HIDDEN_DIV` (+20 очков) **никогда не добавляются к score**.
Это мёртвый код внутри активного модуля. Максимальный score без дивергенции = 75 (TSL+WT_IN_ZONE+PIVOT_TOUCH).

### КРИТИЧЕСКАЯ ПРОБЛЕМА: Дивергенции изолированы от pre_signals

```python
# scan_loop.py:297-306 — дивергенция идёт ТОЛЬКО в recent_signals
_div_stub = SignalData(symbol=sym, signal_type=SignalType.DIVERGENCE, ...)
bot.recent_signals[sym] = [...] + [_div_stub]
# all_scan_signals НЕ содержит дивергенцию!

# scan_loop.py:411 — pre_signals из all_scan_signals
pre = all_scan_signals if all_scan_signals else None
# → analyze_symbol НИКОГДА не получает дивергенцию в pre_signals
```

Дивергенция живёт только в `recent_signals` (для меню "Все сигналы").
Layer 3 (`analyze_symbol`) о ней не знает.

---

## Layer 3: Trading Intelligence / analyze_symbol

**Файл:** `core/trading_intelligence.py`

### Два пути выполнения

```
_broadcast_intelligence_alert
    └── analyze_symbol(symbol, pre_signals=...)
              │
    ┌─────────▼──────────────────────────────┐
    │ pre_signals есть?                       │
    │  ДА → signals = pre_signals             │  ← _collect_all_signals пропускается
    │  НЕТ → _collect_all_signals()           │  ← 6 детекторов параллельно + 3 OHLCV фетча
    └────────────────────────────────────────┘
              │
    _build_mtf_context()  ← ВСЕГДА, даже с pre_signals
    ├── collect_mtf_data(symbol)   ← 7 TF × (wt + trend) — ВТОРОЙ вызов за цикл!
    ├── get_ohlcv(sym, "15m", 5)  ← для текущей цены
    ├── get_ohlcv(sym, "15m", 100) ← для режима рынка
    └── get_ohlcv(sym, "1h", 100)  ← для режима рынка
```

### Нормальный путь (pre_signals переданы)

```
1. signals = pre_signals           ← из scan_loop (без дивергенций!)
2. _build_mtf_context()            ← 7 TF + 3 фетча (данные уже в кэше, но wt пересчитывается)
3. _get_market_context()           ← объём 24h, цена
4. _run_all_strategies()           ← asyncio.gather, параллельно ✅
5. _pick_best_recommendation()     ← reversal_scanner > reversal > legacy
6. ML predictor (asyncio.wait_for, 5 сек таймаут)
7. confidence gate
8. cache_analysis (TTL 5 мин)      ← кэш есть, но каждый сигнал создаёт новый task
```

### `_collect_all_signals` (только без pre_signals)

```python
# trading_intelligence.py:743-750 — 6 детекторов ПАРАЛЛЕЛЬНО
results = await asyncio.gather(
    check_anomaly_signals(symbol, df_15m),
    check_wt_signals(symbol, df_15m),
    check_mtf_signals(symbol, df_1h, df_15m, df_3m),
    check_trend_signals(symbol, df_1h),
    check_mtf_bias_signal(symbol, ...),   # ← 7 TF сам фетчит!
    check_wt_b_signals(symbol, df_1h),    # ← здесь check_wt_b_signals ЕСТЬ
    return_exceptions=True,
)
```

**Парадокс `check_wt_b_signals`:**
- В `_collect_all_signals` вызывается → но только при ручном запросе
- В нормальном потоке (pre_signals есть) → пропускается
- Итог: в продакшне никогда не выполняется

### Веса сигналов (из конфига + адаптивные)

```python
signal_weights = {
    SignalType.MTF_BIAS:       0.50,   # главное ядро — WaveTrend 7 TF
    SignalType.PIVOT_REVERSAL: 0.20,   # второе ядро — пивоты
    SignalType.CONFLUENCE:     0.15,   # производный от WT
    SignalType.WT_B_SIGNAL:    0.15,   # WR=85% — но сигнал никогда не приходит!
    SignalType.SMC_STRUCTURE:  0.12,
    SignalType.DIVERGENCE:     0.10,
    SignalType.MTF_ALERT:      0.10,
    SignalType.WT_SIGNAL:      0.08,
    SignalType.MTF_SIGNAL:     0.05,
    SignalType.TREND_SIGNAL:   0.05,
    SignalType.ANOMALY:        0.03,
}
```

Адаптивные веса обновляются из `simulated_trades` (мин. 20 закрытых сделок на тип).

### `_analyze_sem` — глобальный singleton

```python
# monitoring.py:28–37
_analyze_sem: Optional[asyncio.Semaphore] = None  # глобальный!
size = int(bot.config.get("performance.analyze_semaphore_size", 3))  # default=3, факт=2
```

- Создаётся один раз при первом вызове
- При hot-reload конфига **не пересоздаётся**
- Ограничивает параллельные analyze_symbol (тяжёлый: ML + 3 OHLCV + collect_mtf_data)

---

## Layer 4: Broadcast + Регистрация

**Файл:** `bot/monitoring.py`

### Центральная функция `_broadcast_intelligence_alert`

```
Вход: (bot, symbol, raw_text, signal_type, fallback_rec, pre_signals)
          │
  1. direction = first pre_signal.direction
  2. _is_duplicate_signal(symbol, signal_type, direction)  ← dedup TTL=30 мин
  3. _is_in_sl_cooldown(symbol)                           ← sqlite3 синхронно! ⚠️
          │
  4. async with _analyze_sem (size=2)
     └── analyze_symbol(symbol, pre_signals)              ← Layer 3, тяжёлый
          │
  5. BTC режим: shadow (логирует, не блокирует)
  6. Pivot TP: get_tp_by_hierarchy() → override take_profit
  7. should_register = action in (BUY,SELL) AND strength >= 50
          │
  8. register_trade_async(recommendation)  ← ДО отправки TG ✅
  9. format_intelligence_message()
 10. broadcast_with_subscription_check()   ← TG отправка
 11. all_strategy_recs → register остальных стратегий в БД (без TG)
```

### Фильтры качества

| Фильтр | Логика | Порог |
|---|---|---|
| Dedup | (symbol, signal_type, direction) | TTL=30 мин |
| SL cooldown | последний SL по паре | 4 часа |
| BTC regime | btc_filter_mode=shadow | не блокирует |
| min_strength | overall_strength | ≥ 50 |
| confidence gate | confidence после ML | ≥ 0.55 |
| WATCH+NEUTRAL | action=WATCH и direction=NEUTRAL | пропускается |

### Мёртвые функции в monitoring.py

Следующие функции СУЩЕСТВУЮТ, но не вызываются из `monitor_market`:

```python
check_anomalies(bot)      ← заменена scan_loop
check_wt_signals(bot)     ← заменена scan_loop
check_mtf_signals(bot)    ← заменена scan_loop
check_divergences(bot)    ← заменена scan_loop (третий мёртвый путь дивергенций!)
```

Занимают ~150 строк, создают путаницу при навигации по коду.

### Fallback_rec отключён (намеренно)

```python
# monitoring.py:868
if not should_register and not trade_registered and fallback_rec is not None:
    logger.info("[%s] Fallback НЕ регистрируем (MTF bypass fix)...", symbol)
```

Старый fallback обходил MTF context → WR=8.7%. Правильно заблокирован.

### `_is_in_sl_cooldown` — синхронный SQLite в async

```python
# monitoring.py:595
with sqlite3.connect(db_path) as conn:  # блокирует event loop!
    row = conn.execute("SELECT 1 FROM simulated_trades ...").fetchone()
```

Вызывается для КАЖДОГО сигнала. При нескольких параллельных сигналах
блокирует asyncio event loop на время дискового I/O (~1–5 мс).

---

## Полная карта потоков данных

```
OHLCV (Layer 0)
    │   asyncio.gather — параллельно ✅
    ▼
df_15m, df_1h, df_3m, df_4h (сырые данные)
    │
    │   НИГДЕ не обогащаются до детекторов ❌
    │
    ▼
Детекторы (Layer 2) — ПОСЛЕДОВАТЕЛЬНО ❌
    ├── check_anomaly_signals  → calculate_trend (lazy ✅)
    ├── check_wt_signals       → calculate_wt × 2
    ├── check_mtf_signals      → calculate_trend + calculate_wt × 2
    └── scan_wt_15m_reversal   → calculate_wt + calculate_trend
                                   └── inline div: СЛОМАНА (n=8 < 11)
    │
    ▼
all_scan_signals (без дивергенций!)
    │
    ├── divergence detection (async I/O)
    │       └── → recent_signals ТОЛЬКО  ← изолированы! ❌
    │
    ▼
Multi-TF Resolver (если multi-TF режим)
    │
    ▼
broadcast → asyncio.create_task (fire-and-forget)
    │
    ▼
analyze_symbol (Layer 3)  — через _analyze_sem=2
    ├── pre_signals (без дивергенций)
    ├── _build_mtf_context → collect_mtf_data × 2-й раз!
    ├── _run_all_strategies (параллельно ✅)
    └── ML predictor
    │
    ▼
register_trade_async → SQLite (sync! ⚠️)
    │
    ▼
broadcast_with_subscription_check → Telegram
```

---

## Полный список проблем по приоритету

### 🔴 Критические (влияют на качество сигналов)

| # | Проблема | Файл | Строки | Влияние |
|---|---|---|---|---|
| 1 | Inline дивергенция сломана: `n=8 < div_min_bars*2+1=11` | `wt_15m_reversal_scanner.py` | ~180 | `WT_DIVERGENCE`/`WT_HIDDEN_DIV` (+20 очков) никогда не добавляются к score confluence |
| 2 | `check_wt_b_signals` (WR=84.9%) не работает в продакшне | `signal_checkers.py`, `trading_intelligence.py` | 240–319, 749 | Пропускаем высококачественные 1h сигналы |
| 3 | Дивергенции не попадают в `pre_signals` → `analyze_symbol` их не видит | `scan_loop.py` | 297–306, 411 | Layer 3 принимает решения без информации о дивергенциях |

### 🟠 Архитектурные (влияют на производительность и надёжность)

| # | Проблема | Файл | Строки | Влияние |
|---|---|---|---|---|
| 4 | 10× дублирование `calculate_wt`/`calculate_trend` | Все детекторы | — | +5–10% времени цикла; риск дрейфа параметров |
| 5 | Детекторы в scan_one работают последовательно | `scan_loop.py` | 192–344 | I/O-bound дивергенции блокируют; потеря 30–120 мс на пару |
| 6 | `collect_mtf_data` вызывается дважды за цикл | `scan_loop.py`, `trading_intelligence.py` | 371, 794 | 7 TF × (wt + trend) пересчитываются повторно |
| 7 | `_build_mtf_context` делает 3 лишних OHLCV фетча | `trading_intelligence.py` | 801, 820–822 | Для цены и режима, хотя данные только что фетчились |
| 8 | `_is_in_sl_cooldown` — синхронный SQLite в async | `monitoring.py` | 595–605 | Блокирует event loop при каждом сигнале |

### 🟡 Технический долг (мусор в коде)

| # | Проблема | Файл | Влияние |
|---|---|---|---|
| 9 | 4 мёртвых функции в monitoring.py | `monitoring.py` | ~150 строк, путают навигацию |
| 10 | `_analyze_sem` глобальный singleton — не сбрасывается при hot-reload | `monitoring.py` | Изменение `analyze_semaphore_size` в конфиге не применяется без рестарта |
| 11 | Дневной пивот смещён ~0.27% (timezone bug) | `pivot_calculator_fixed.py` | Критично для pivot_touch gate (+25 очков) |
| 12 | Дашборд UTC vs TG UTC+3 | — | 3-часовое расхождение в отображении времени |

---

## Три уровня дивергенций (исторически сложились)

| Уровень | Файл | Что умеет | Статус |
|---|---|---|---|
| Level 1 | `divergence_detector.py` | Regular + Hidden Bullish/Bearish, 1h, 100+ баров | ✅ Работает, но изолирован от pre_signals |
| Level 2 | `wt_15m_reversal_scanner.py` | Regular только, 15m inline | ❌ СЛОМАН (окно 8 < 11) |
| Level 3 | `confluence_scanner.py` | Legacy, отключён | ❌ `use_state_machine: false` |

Правильное решение: **использовать только Level 1**, починить передачу в pre_signals.

---

## Что НЕ является проблемой

- **Дублирование индикаторов** само по себе не ломает логику (результат детерминирован)
- **fallback_rec** правильно отключён (WR=8.7% был неприемлем)
- **BTC filter в shadow mode** — правильное решение для накопления статистики
- **Кэш OHLCV** работает корректно, TTL подобраны разумно
- **Стратегии запускаются параллельно** (`asyncio.gather` в `_run_all_strategies`)

---

*Анализ выполнен 2026-03-19. Изменений в код не вносилось.*
