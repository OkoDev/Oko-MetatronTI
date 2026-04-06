# 🔬 Полный гайд по индикаторам бота Oko MTF и их настройке

## 📋 Обзор системы индикаторов

Бот Oko MTF использует **8 типов сигналов** и **11 технических индикаторов** для комплексного анализа крипторынка. Система построена на принципах **Trading Bot Architect Mode** с адаптивными весами, ML-улучшениями и Strategy Pattern.

> **Принцип единого источника (с 12.03.2026):** все индикаторы реализованы в `core/indicators.py`. Другие модули только импортируют оттуда — дублирования нет.

---

## 🧮 Технические индикаторы (core/indicators.py)

### Полный реестр функций

| Функция | Назначение | Возвращает |
|---------|-----------|-----------|
| `calculate_wt(df, n1=10, n2=21)` | WaveTrend осциллятор | df с колонками wt1, wt2 |
| `calculate_trend(df, atr_period=43, factor=1.0)` | TREND + TSL линии | df с trend, trendup, trenddown, tsl |
| `true_range_series(df)` | True Range | pd.Series |
| `compute_atr(df, period)` | ATR из df | pd.Series |
| `compute_atr_values(h, l, c, period)` | ATR из numpy-массивов | List[float] |
| `compute_ema(df, period)` | EMA (добавляет в df) | df |
| `compute_ema_values(values, period)` | EMA из массива | np.ndarray |
| `compute_sma(values, period)` | SMA из массива | np.ndarray |
| `compute_volatility(closes, period=20)` | Волатильность | float, **в процентах** |
| `compute_adx(h, l, c, period=14)` | ADX | float (0–100) |
| `compute_rsi(closes, period=14)` | RSI (Wilder's RMA) | float (0–100) |
| `compute_volume_ratio(volumes, period=20)` | Отношение объема к SMA | float |
| `find_swing_highs(series, period)` | Локальные максимумы | List[int] (индексы) |
| `find_swing_lows(series, period)` | Локальные минимумы | List[int] (индексы) |
| `calculate_pivot_points(h, l, c)` | Пивот-уровни | Dict: PP, S1–S5, R1–R5 |
| `detect_fvg(df)` | Fair Value Gap | (bool, dict) |
| `get_zone(wt_value)` | Зона WT | "OB" / "OS" / "N" |

---

### 1. **WaveTrend (WT)** — основной осциллятор

```python
def calculate_wt(df: pd.DataFrame, n1=10, n2=21) -> pd.DataFrame:
```

**Алгоритм:**
- **HLC3** = (High + Low + Close) / 3
- **ESA** = EMA(HLC3, n1=10)
- **D** = EMA(|HLC3 − ESA|, n1=10)
- **CI** = (HLC3 − ESA) / (0.015 × D)
- **WT1** = EMA(CI, n2=21) — основная линия
- **WT2** = SMA(WT1, 4) — сигнальная линия

**Зоны:**
- **OB (Overbought)**: WT1 > +60
- **OS (Oversold)**: WT1 < −60
- **N (Neutral)**: −60 < WT1 < +60

**Настройка в config.yaml:**
```yaml
analysis:
  wt_periods:
    n1: 10
    n2: 21
```

---

### 2. **Trend Indicator + TSL** — единый источник тренда

```python
def calculate_trend(df: pd.DataFrame, atr_period=43, factor=1.0) -> pd.DataFrame:
```

**Алгоритм (точная реализация Pine Script):**
- ATR рассчитывается методом **Wilder's RMA** (не SMA)
- `up = hl2 − factor × ATR`
- `dn = hl2 + factor × ATR`
- `trendup[i]` = max(up, prev_trendup) если prev_hl2 > prev_trendup
- `trenddown[i]` = min(dn, prev_trenddown) если prev_hl2 < prev_trenddown
- `trend = +1` если hl2 > prev_trenddown, `-1` если hl2 < prev_trendup

**Выходные колонки df:**
| Колонка | Значение |
|---------|---------|
| `trend` | +1 (UP) / -1 (DOWN) |
| `trendup` | TSL-линия снизу (для LONG) |
| `trenddown` | TSL-линия сверху (для SHORT) |
| `tsl` | = trendup если LONG, = trenddown если SHORT |

**Используется в:** `signal_checkers.py`, `trade_simulator.py` (TSL-трекинг), `trading_intelligence._calculate_levels()`

---

### 3. **RSI** — Wilder's RMA

```python
def compute_rsi(closes, period=14) -> float:
```

⚠️ Использует **Wilder's RMA** (экспоненциальное сглаживание с alpha=1/period), как в Pine Script. Старая реализация через `rolling().mean()` давала расхождение с TradingView — исправлено 12.03.2026.

---

### 4. **ADX** — сила тренда

```python
def compute_adx(h, l, c, period=14) -> float:
```

Возвращает значение 0–100. Инициализация через SMA (не SUM) — исправлено 12.03.2026.

- ADX < 20: слабый тренд / флэт
- ADX 20–40: умеренный тренд
- ADX > 40: сильный тренд

Используется в `market_regime.py` для классификации рыночного режима.

---

### 5. **Volatility** — в процентах

```python
def compute_volatility(closes, period=20) -> float:
```

⚠️ Возвращает **проценты** (например, 2.5 = 2.5%). До 12.03.2026 возвращала доли → `sl_pct` всегда зажимался в `sl_min=1%`. Исправлено.

---

### 6. **Pivot Points**

```python
def calculate_pivot_points(high, low, close) -> Dict[str, float]:
```

Возвращает: `{PP, S1, S2, S3, S4, S5, R1, R2, R3, R4, R5}`

Делегируют оба класса: `pivot_levels.py` и `pivot_calculator_fixed.py`.

---

### 7. **Fair Value Gap (FVG)**

```python
def detect_fvg(df: pd.DataFrame) -> (bool, dict):
```

- **Bull FVG**: Low[2] > High[0] — бычий гэп
- **Bear FVG**: High[2] < Low[0] — медвежий гэп
- Проверяет последние 3 свечи

---

## 📊 8 типов торговых сигналов

### 1. **ANOMALY** — аномалии объема
**Файл:** `core/signal_checkers.py` (был `anomaly_detector.py`, удалён)
**Сила:** 70 | **Уверенность:** 0.7

```python
volume_ratio = current_volume / mean_volume_20
if volume_ratio > volume_multiplier:  # config: 5.0
    price_change = (close - prev_close) / prev_close * 100
    direction = LONG if price_change > 0 else SHORT
```

**Настройка:**
```yaml
analysis:
  volume_multiplier: 5.0   # 3.0–8.0
  price_threshold: 7.0     # 5.0–15.0
```

---

### 2. **WT_SIGNAL** — WaveTrend кроссы
**Файл:** `core/signal_checkers.py`
**Сила:** 70 | **Уверенность:** 0.8

```python
cross_up = wt1_prev < wt2_prev and wt1_last > wt2_last
if cross_up and wt1_last < -60:   # LONG в зоне OS
if cross_down and wt1_last > 60:  # SHORT в зоне OB
```

⚠️ Порог **±60** (не ±50) — официальный стандарт. Использование ±50 генерирует ложные сигналы и снижает win rate на 5–10%.

---

### 3. **MTF_SIGNAL** — мульти-таймфрейм синхронизация
**Файл:** `core/mtf_checker.py`
**Сила:** 85 | **Уверенность:** 0.9

```python
# Тренд 1H + WT 15m/3m
if trend_1h == 1 and wt1_15m > wt2_15m and wt1_3m < -60:   # LONG
elif trend_1h == -1 and wt1_15m < wt2_15m and wt1_3m > 60:  # SHORT
```

---

### 4. **TREND_SIGNAL** — развороты тренда
**Файл:** `core/trend_signals.py`
**Сила:** 60 | **Уверенность:** 0.7

Фиксирует смену `trend: +1 → -1` или `-1 → +1`. Текущая эффективность: avg_R = −0.50. Вес адаптивно снижен до 0.08.

---

### 5. **DIVERGENCE** — дивергенции
**Файл:** `core/divergence_detector.py`
**Сила:** 75 | **Уверенность:** 0.8

- **Regular Divergence**: разворот (цена ↑, осциллятор ↓ или наоборот)
- **Hidden Divergence**: продолжение тренда

⚠️ Дивергенции **не попадают** в `all_scan_signals` / `pre_signals` — только в отдельный список, чтобы не создавать `conflict_ratio`.

Требует limit=160 баров (max_bars=100 + pivot_period×2 + 50).

---

### 6. **PIVOT_REVERSAL** — развороты от пивот-уровней
**Файл:** `core/pivot_reversal.py`
**Сила:** 65 | **Уверенность:** 0.7 | avg_R = +0.50

Цена касается уровня из `pivot_calculator_fixed` (1M/1W/1D пивоты по UTC-периодам). TP пересчитывается через `get_pivot_tp_with_source()` с R ≥ 1.5.

---

### 7. **MTF_PIVOT_INTEGRATION** — MTF + пивот-конфлюэнция
**Файл:** `core/mtf_pivot_integration.py`
**Сила:** 90 | **Уверенность:** 0.95

Пересечение MTF сигнала + цена у пивот-уровня. Самый сильный одиночный сигнал, редкий.

---

### 8. **CONFLUENCE** — мультифакторный скан ⭐ новый
**Файл:** `core/confluence_scanner.py`

Проверяет 5+ факторов одновременно:

| Фактор | Условие LONG | Условие SHORT |
|--------|-------------|--------------|
| WT_OS | WT1 < −53 (threshold) | WT1 > +53 |
| WT_OB | WT1 < +53 (не в зоне OB) | — |
| WT_CROSS | Последний кросс вверх (в fresh_bars=10) | Последний кросс вниз |
| TSL_CROSS | Последний кросс trendline вверх | Последний кросс вниз |
| NEAR_SUPPORT/RESISTANCE | Цена близко к S1–S5 | Цена близко к R1–R5 |
| BELOW/ABOVE_PP | Цена ниже PP | Цена выше PP |
| WT_DIVERGENCE | Бычья дивергенция | Медвежья дивергенция |

**Фиксы (12.03.2026):**
- `last_tsl_cross` / `last_wt_cross` = `"UP" | "DOWN" | None` — взаимоисключающие (баг двойных LONG+SHORT устранён)
- Поиск только в последних `cross_fresh_bars=10` барах (2.5 часа)

```yaml
analysis:
  confluence:
    cross_fresh_bars: 10   # баров для поиска кросса
    wt_os_threshold: -53
    wt_ob_threshold: 53
```

---

## 🎯 Пивот-система

### Period-based пивоты (pivot_calculator_fixed.py)

Пивоты рассчитываются по **UTC-периодам** (не скользящее окно):
- **1M**: начало месяца 00:00 UTC
- **1W**: понедельник 00:00 UTC
- **1D**: 00:00 UTC

**SL/TP логика (реализована с 08.03.2026):**

| Приоритет | SL | TP |
|-----------|----|----|
| 1 (основной) | `1.5 × ATR(14)`, зажат в [1%, 4%] | Ближайший пивот с R ≥ 1.5 |
| 2 (fallback) | `volatility` → clamp(vol, 1%, 3%) | `1.5 × SL_dist` |
| 3 (крайний) | 2.5% | — |

Поля в TradingRecommendation: `sl_source`, `tp_source` — логируются для диагностики.

---

## 🏃 TSL (Trailing Stop Loss)

**Активен по умолчанию.** Включается после достижения +1R прибыли.

```yaml
trading:
  use_tsl: true
  tsl_activation_r: 1.0
  tsl_buffer_pct: 0.1
```

**Логика:**
- LONG: SL следует за `trendup` (снизу вверх)
- SHORT: SL следует за `trenddown` (сверху вниз)
- Рассчитывается через `calculate_trend()` из `core/indicators.py`

---

## 🌐 Рыночные режимы (core/market_regime.py)

**MarketRegimeClassifier** (ADX + ATR + EMA) классифицирует рынок при регистрации сделки:

| Режим | Условие |
|-------|---------|
| `TREND_UP` | ADX > порога, EMA50 < цены |
| `TREND_DOWN` | ADX > порога, EMA50 > цены |
| `RANGE` | ADX < порога, низкая волатильность |
| `HIGH_VOL` | высокая волатильность (ATR%) |

Записывается в поле `regime` таблицы `simulated_trades`. Используется OutcomePredictor (4 one-hot признака).

---

## 📦 Проверка качества данных (core/data_quality.py)

Три проверки OHLCV перед анализом:

| Проверка | Условие пропуска |
|---------|-----------------|
| **Глубина** | `len(df) < min_bars` (160 для scan_one, 50 для /intelligence) |
| **Свежесть** | Последняя свеча старше `freshness_mult × TF` |
| **NaN-пробелы** | >5% NaN в close |

---

## 🔧 API-движок (core/api_engine.py)

Транспортный слой под `data_collector.py`:

| Компонент | Функция |
|-----------|---------|
| `OhlcvCache` | LRU (OrderedDict), maxsize=5000, TTL по TF |
| `CircuitBreaker` | 10 ошибок → OPEN 30 сек → HALF_OPEN → проверка |
| In-flight dedup | `dict[(symbol, tf, limit), Future]` — один запрос на ключ |
| Retry | NetworkError: 1/2/4 сек; RateLimitExceeded: 5/10/20 сек |
| Semaphore | `Semaphore(20)` — единая точка контроля параллелизма |

`enableRateLimit: False` в ccxt — намеренно, управление через Semaphore.

---

## 🧠 Trading Intelligence — агрегация сигналов

### Сигнальный поток:

```
scan_one (monitoring.py)
  → analyze_symbol (trading_intelligence.py)
      → _collect_all_signals()       # таймаут 10 сек
      → _analyze_signals_advanced()  # взвешивание + conflict_ratio
      → _enhance_analysis_with_ml()  # MLPredictor + OutcomePredictor
      → _generate_recommendation()
  → _broadcast_intelligence_alert()
      → is_actionable (str ≥ 50, BUY/SELL, dir ≠ NEUTRAL) → TG-алерт
      → should_register (str ≥ 40, dir ≠ NEUTRAL)         → register_trade_async → DB
```

### Веса сигналов (адаптивные, 242+ сделок):

```python
signal_weights = {
    MTF_ALERT:          0.30,   # самый сильный
    MTF_SIGNAL:         0.25,
    PIVOT_REVERSAL:     0.24,   # адаптировано ↑ (avg_R = +0.50)
    DIVERGENCE:         0.15,
    WT_SIGNAL:          0.133,  # адаптировано ↑ (avg_R = +0.83)
    TREND_SIGNAL:       0.08,   # адаптировано ↓ (avg_R = −0.50)
    ANOMALY:            0.05,
}
```

**Формула адаптации:** `factor = clamp(1.0 + avg_R × 0.4, 0.5, 2.0)`, минимум 20 закрытых сделок.

### Пороги регистрации:

```yaml
signal_quality:
  min_strength: 50          # TG-алерт
  min_strength_register: 40 # запись в БД
```

### Таймаут и fallback цены:

При таймауте `_get_market_context` (15 сек) цена берётся из кеша OHLCV:
```python
_df = await data_collector.get_ohlcv(symbol, "15m", limit=5)
fallback_price = float(_df["close"].iloc[-1])
```
(Без этого `current_price=0` → `entry_price=None` → сделка не регистрируется)

---

## 🤖 ML-улучшения

### OutcomePredictor (core/outcome_predictor.py)

RandomForest(200 деревьев) на реальных исходах:
- **12 признаков**: strength, confidence, direction, signal_type(3), volatility, price_change, regime(4)
- **Таргет**: TP=1, SL=0
- **CV AUC**: ~0.486 (240+ сделок; вырастет при заполнении regime)
- **Блендинг**: `confidence = 0.7 × original + 0.3 × P(win)`

### MLPredictor (core/ml_predictor.py)

OHLCV-based предсказание направления и силы сигнала. RSI использует Wilder's RMA (исправлено 12.03.2026, было SMA-rolling).

---

## ⚙️ Ключевые параметры config.yaml

```yaml
analysis:
  volume_multiplier: 5.0
  price_threshold: 7.0
  wt_periods:
    n1: 10
    n2: 21
  trend:
    atr_period: 43
    factor: 1.0
  confluence:
    cross_fresh_bars: 10
    wt_os_threshold: -53
    wt_ob_threshold: 53

trading:
  use_tsl: true
  tsl_activation_r: 1.0
  tsl_buffer_pct: 0.1

signal_quality:
  min_volume_usd: 1000000
  sl_cooldown_hours: 4
  dedup_minutes: 30
  min_strength: 50
  min_strength_register: 40
```

---

## 📈 Мониторинг и оптимизация

### Текущие метрики (242+ сделок):

| Метрика | Значение | Цель |
|---------|----------|------|
| Win Rate | 39.7% | > 50% |
| CV AUC (ML) | 0.486 | > 0.65 |
| pivot_reversal avg_R | +0.50 | > 1.0 |
| wt_signal avg_R | +0.83 | > 1.0 |
| trend_signal avg_R | −0.50 | > 0 |

### Полезные команды:

```bash
# Статистика по типам сигналов
python -c "
from core.performance_engine import PerformanceEngine
pe = PerformanceEngine('subscriptions.db')
print(pe.summary())
for r in pe.by_signal_type():
    print(r)
"

# OutcomePredictor
python -c "
from core.outcome_predictor import OutcomePredictor
op = OutcomePredictor(); op.fit('subscriptions.db')
print(op.info())
"

# Диагностика API-движка
# (когда бот запущен, из REPL)
# bot.data_collector._engine.cache_stats()
```

### Дашборд:
```
http://localhost:8000           # статистика + EV + прогноз депозита
http://localhost:8000/settings  # редактирование параметров (hot-reload)
http://localhost:8000/api/stats # JSON
```

---

## 🔍 Частые проблемы

### Много ложных сигналов
```yaml
min_confidence: 0.8
min_strength: 60
volume_threshold: 500000
```

### WT пороги — ±60, не ±50!
Проверка:
```bash
grep -n "< -50\|> 50" core/signal_checkers.py   # должно быть пусто
grep -n "< -60\|> 60" core/signal_checkers.py   # должно быть
```

### Сделка не зарегистрирована
Смотреть лог:
```bash
grep "зарегистрир\|Сделка не\|action=WATCH" crypto_bot.log | tail -20
```

Причины:
1. `action=WATCH` — strength < 40 или direction=NEUTRAL
2. `entry_price=None` — таймаут market_context (исправлено 13.03.2026)
3. `conflict_ratio` высокий — противоречивые сигналы

### Ошибка `_build_result() missing argument`
Исправлено 13.03.2026 в `core/pivot_reversal.py` — добавлен `trend_label` в оба call site.

---

## 🏗️ Архитектурные ограничения (не менять без понимания)

- Дивергенции **не** в `all_scan_signals` — создают `conflict_ratio`
- `bot.pivot_calculator` — правильное имя (не `pivot_calculator_fixed`)
- `enableRateLimit: False` — намеренно (Semaphore(20))
- Python 3.12 строго — `.venv` и 3.13 не имеют aiogram
- `_ohlcv_cache` = алиас `self._engine._cache._data`
- `anomaly_detector.py`, `config.py`, `risk_manager.py` — **удалены**

---

## 📁 Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `core/indicators.py` | Все технические индикаторы (единый источник) |
| `core/signal_checkers.py` | Все детекторы сигналов (inc. anomaly) |
| `core/confluence_scanner.py` | Мультифакторный confluence-скан |
| `core/trading_intelligence.py` | Агрегация сигналов → рекомендация |
| `core/market_regime.py` | Классификатор рыночного режима |
| `core/data_quality.py` | Проверки OHLCV перед анализом |
| `core/api_engine.py` | LRU-кеш, CircuitBreaker, in-flight dedup |
| `core/trade_simulator.py` | Регистрация сделок, TSL-трекинг, MFE |
| `core/performance_engine.py` | Аналитика по simulated_trades |
| `core/outcome_predictor.py` | ML на реальных исходах (P(win)) |
| `core/pivot_calculator_fixed.py` | Period-based пивоты (1M/1W/1D UTC) |
| `config.yaml` | Все параметры |

---

*Обновлено: 13.03.2026. Все индикаторы централизованы в `core/indicators.py` (Этап 8.3, 12.03.2026).*
