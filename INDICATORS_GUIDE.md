# 🔬 Полный гайд по индикаторам бота Oko MTF и их настройке

## 📋 Обзор системы индикаторов

Бот Oko MTF использует **7 типов сигналов** и **6 технических индикаторов** для комплексного анализа крипторынка. Система построена на принципах **Trading Bot Architect Mode** с адаптивными весами и ML-улучшениями.

---

## 🧮 Технические индикаторы (core/indicators.py)

### 1. **WaveTrend (WT)** - основной осциллятор

```python
def calculate_wt(df: pd.DataFrame, n1=10, n2=21) -> pd.DataFrame:
```

**Алгоритм:**
- **HLC3** = (High + Low + Close) / 3
- **ESA** = EMA(HLC3, n1=10) - экспоненциальная средняя
- **D** = EMA(|HLC3 - ESA|, n1=10) - среднее отклонение
- **CI** = (HLC3 - ESA) / (0.015 × D) - нормализованный индекс
- **WT1** = EMA(CI, n2=21) - основная линия
- **WT2** = SMA(WT1, 4) - сигнальная линия

**Зоны перекупленности/перепроданности:**
- **OB (Overbought)**: WT1 > +60 (официальная зона)
- **OS (Oversold)**: WT1 < -60 (официальная зона)
- **N (Neutral)**: -60 < WT1 < +60
- **⚠️ Примечание:** Для сигналов используется более мягкий порог ±50 (входим чуть раньше в официальную зону)

**Настройка в config.yaml:**
```yaml
analysis:
  wt_periods:
    n1: 10  # Период ESA (рекомендуется 10-12)
    n2: 21  # Период WT (рекомендуется 21-25)
```

**Применение:**
- Определение перекупленности/перепроданности
- Поиск разворотов по кроссам WT1/WT2
- Подтверждение тренда на младших таймфреймах
- **Минимум 50 баров** для расчета

---

### 2. **Trend Indicator** - определение тренда

```python
def calculate_trend(df: pd.DataFrame, atr_period=43, factor=1.0) -> pd.DataFrame:
```

**Алгоритм (Pine Script аналог):**
- **HL2** = (High + Low) / 2 - средняя цена
- **ATR** = EMA(TR, period=43) - средний истинный диапазон
- **Up** = HL2 - (factor × ATR) - верхняя граница
- **Down** = HL2 + (factor × ATR) - нижняя граница
- **TrendUp[i]** = max(Up[i], TrendUp[i-1]) if HL2[i-1] > TrendUp[i-1]
- **TrendDown[i]** = min(Down[i], TrendDown[i-1]) if HL2[i-1] < TrendDown[i-1]
- **Trend** = +1 если HL2 > TrendDown[prev], -1 если HL2 < TrendUp[prev]

**Выходные данные:**
- `trend`: текущее направление (+1 UP, -1 DOWN)
- `trendup`: уровень для восходящего тренда
- `trenddown`: уровень для нисходящего тренда
- `tsl`: Trailing Stop Loss (выбирает trendup или trenddown)

**Настройка:**
```yaml
analysis:
  trend:
    atr_period: 43  # Период ATR (рекомендуется 40-50)
    factor: 1.0     # Множитель ATR (0.8-1.2)
```

**Особенности:**
- Более гладкий, чем простые скользящие средние
- Учитывает волатильность через ATR
- Отлично работает на силовых движениях
- На флэте генерирует много ложных сигналов

---

### 3. **Fair Value Gap (FVG)** - детектор пробелов

```python
def detect_fvg(df: pd.DataFrame):
```

**Алгоритм:**
- Проверяет последние 3 свечи
- **Bull FVG**: Low[2] > High[0] (бычий гэп вверх)
- **Bear FVG**: High[2] < Low[0] (медвежий гэп вниз)
- **Entry** = средняя точка гэпа

**Применение:**
- Входы по пробеганию пробелов (FVG mitigation)
- Идентификация сильных движений
- **Потенциал:** 3-5% на одном движении

---

### 4. **RSI (Relative Strength Index)** - дополнительный

Используется в `divergence_detector.py` наряду с WT для выявления дивергенций.

**Формула:**
```
RS = Avg(Up moves) / Avg(Down moves)
RSI = 100 - (100 / (1 + RS))
```

**Зоны:**
- Overbought: RSI > 70
- Oversold: RSI < 30
- Divergence: цена выше, RSI ниже (или наоборот)

---

## 📊 7 типов торговых сигналов

### 1. **ANOMALY** - аномалии объема
**Файл:** `core/anomaly_detector.py`  
**Сила:** 70 | **Уверенность:** 0.7  
**Таймфрейм:** 1H

**Логика:** Всплески объема + движение цены в одном направлении
```python
volume_ratio = current_volume / mean_volume_20
if volume_ratio > 3.0:
    price_change = (close - prev_close) / prev_close * 100
    direction = LONG if price_change > 0 else SHORT
```

**Сигнал означает:** Начало сильного движения, скорее всего вслед за информацией

**Настройка:**
```yaml
analysis:
  volume_multiplier: 5.0  # Коэффициент аномалии объема (3.0-8.0)
  price_threshold: 7.0    # Минимальное движение цены % (5.0-15.0)
```

**Оптимизация:**
- Понизить `volume_multiplier` для более чутких сигналов (риск шума)
- Увеличить `price_threshold` для фильтрации ложные пики объема
- **Лучше на**: Листингах монет, экономических новостях

---

### 2. **WT_SIGNAL** - WaveTrend кроссы
**Файл:** `core/signal_checkers.py`  
**Сила:** 70 | **Уверенность:** 0.8  
**Таймфрейм:** 15m

**Логика:** Кроссы WT1/WT2 в официальных зонах перекупленности/перепроданности
```python
cross_up = wt1_prev < wt2_prev and wt1_last > wt2_last
cross_down = wt1_prev > wt2_prev and wt1_last < wt2_last

# Используем официальные пороги ±60 (не ±50!)
if cross_up and wt1_last < -60:      # LONG в OS (перепроданность)
if cross_down and wt1_last > 60:     # SHORT в OB (перекупленность)
```

⚠️ **Важно:** Использование ±50 вместо ±60 генерирует много ложных сигналов на колебаниях. Это нарушает архитектуру и снижает win rate на 5-10%.

**Сигнал означает:** Разворот от экстремума, часто в начало коррекции

**Особенности:**
- Очень быстрый сигнал (реагирует на 1-2 свечи)
- Хорошо на волатильных парах
- **Требует подтверждения** от других сигналов
- **Минимум 50 баров** для надежности

**Оптимизация:**
- Использовать вместе с MTF сигналом
- Требовать, чтобы trend на 1H совпадал с направлением
- Филтровать очень экстремальные значения (wt1 < -80 или > 80)

---

### 3. **MTF_SIGNAL** - мульти-таймфрейм синхронизация
**Файл:** `core/mtf_checker.py`  
**Сила:** 85 | **Уверенность:** 0.9  
**Таймфрейм:** MTF (1H + 15m + 3m)

**Логика:** Синхронизация трендов нескольких таймфреймов
```python
# Основное направление - тренд на 1H
trend_1h = calculate_trend(df_1h)["trend"].iloc[-1]

# Подтверждение - WaveTrend на 15m и 3m
wt1_15m, wt2_15m = calculate_wt(df_15m)[["wt1", "wt2"]].iloc[-1]
wt1_3m = calculate_wt(df_3m)["wt1"].iloc[-1]

# LONG условие (официальный стандарт ±60, не ±50!)
if trend_1h == 1 and wt1_15m > wt2_15m and wt1_3m < -60:
    return LONG

# SHORT условие (официальный стандарт ±60, не ±50!)
elif trend_1h == -1 and wt1_15m < wt2_15m and wt1_3m > 60:
    return SHORT
```

**Сигнал означает:** Высокая вероятность разворота или продолжения тренда, подтвержденная на 3+ таймфреймах

**Преимущества:**
- **Самый сильный сигнал** (avg_R = +0.50)
- Минимум ложных сигналов
- Высокая точность на трендовых рынках

**Недостатки:**
- Отстает в начале движения (ждет подтверждения)
- Плохо на флэте

---

### 4. **TREND_SIGNAL** - развороты тренда
**Файл:** `core/trend_signals.py`  
**Сила:** 60 | **Уверенность:** 0.7  
**Таймфрейм:** 1H

**Логика:** Отслеживание изменения направления тренда через TSL
```python
trend_current = calculate_trend(df)["trend"].iloc[-1]
trend_prev = calculate_trend(df)["trend"].iloc[-2]

if trend_current != trend_prev:
    # Средняя цена пересекла один из TSL уровней
    direction = LONG if trend_current == 1 else SHORT
```

**Сигнал означает:** Точка развора тренда, переход из UP в DOWN или наоборот

**Особенности:**
- Хорошо для позиционирования
- **Текущая эффективность:** avg_R = -0.50 (требует оптимизации)
- Может быть использован как стоп-сигнал для противоположных позиций

**Проблема:** Часто дает разворот, который продолжается в старом направлении (ложный сигнал)

---

### 5. **DIVERGENCE** - дивергенции цена/индикатор
**Файл:** `core/divergence_detector.py`  
**Сила:** 75 | **Уверенность:** 0.8  
**Таймфрейм:** 1H

**Логика:** Расхождения между движением цены и осциллятором (WT + RSI)
```python
# Bearish Divergence
recent_price_high > df["high"].iloc[-50:].max() and \
recent_wt_high < df_wt["wt1"].iloc[-50:].max()
# Цена выше, но осциллятор ниже → давление ослабевает → SHORT

# Bullish Divergence  
recent_price_low < df["low"].iloc[-50:].min() and \
recent_wt_low > df_wt["wt1"].iloc[-50:].min()
# Цена ниже, но осциллятор выше → дно не подтверждается → LONG
```

**Типы:**
- **Regular Divergence**: классическая дивергенция (разворот вероятен на 50-60%)
- **Hidden Divergence**: скрытая дивергенция (продолжение тренда на 60-70%)

**Применение:**
- Лучше всего работает на вершинах/дне
- Требует ** 2-3 локальных экстремума** для надежности
- На трендовом рынке работает лучше

---

### 6. **PIVOT_REVERSAL** - развороты от пивот-уровней
**Файл:** `core/pivot_reversal.py`  
**Сила:** 65 | **Уверенность:** 0.7  
**Таймфрейм:** 1H

**Логика:** Цена касается уровней поддержки/сопротивления из пивотов
```python
resistance_levels = calculate_traditional_pivots(prev_high, prev_low, prev_close)
for level in [R1, R2, R3, ...]:
    distance = abs(current_price - level) / current_price * 100
    if distance < 2.0:  # В пределах 2% от уровня
        return SHORT  # Разворот от сопротивления

# Аналогично для поддержки (S1-S5)
```

**Сигнал означает:** Цена касается технического уровня, вероятен разворот или откат

**Текущая эффективность:** avg_R = +0.50 (хорошо после улучшений)

**Уровни пивотов:**
```
PP (Pivot Point) = (H + L + C) / 3
S1 = PP × 2.003 - H
S2 = PP - (H - L)
S3 = PP × 2 - (2H - L)
R1 = PP × 1.997 - L
R2 = PP + (H - L)
R3 = PP × 2 + (H - 2L)
```

---

### 7. **MTF_PIVOT_INTEGRATION** - комбинированные сигналы
**Файл:** `core/mtf_pivot_integration.py`  
**Сила:** 90 | **Уверенность:** 0.95  

**Логика:** Пересечение MTF сигнала + пивот-конфлюэнции
```python
# Условия одновременно:
# 1. MTF сигнал (trend 1H + WT 15m/3m)
# 2. Цена в пределах 2% от пивот-уровня
# 3. Конфлюэнция недельных и дневных пивотов
return COMPOSITE_SIGNAL
```

**Это самый сильный сигнал** - применяется редко но с высокой вероятностью успеха.

---

## 🎯 Система пивотов (core/pivot_levels.py & core/pivot_calculator_fixed.py)

### **Типы пивотов:**

#### 1. **Traditional Pivot Points** (основной)
Формулы выше. Используется по умолчанию.

#### 2. **Woodie Pivot Points**
```
PP = (H + L) / 2 + Close
S1 = 2 × PP - H
R1 = 2 × PP - L
```
Смещение на закрытие предыдущего периода.

#### 3. **Camarilla Pivot Points**
```
A = (H - L) × 1.1 / 2
PP = (H + L) / 2
S1 = PP - A
R1 = PP + A
S2 = PP - A × 2
R2 = PP + A × 2
```
Более узкие уровни, хороши для скальпинга.

#### 4. **Fibonacci Pivot Points**
Использует коэффициенты Фибоначчи (0.236, 0.382, 0.618, 1.0).

### **Мульти-таймфрейм пивоты (Period-based):**
**Файл:** `core/pivot_calculator_fixed.py`

Вместо скользящего окна используются **UTC-периоды**:
- **1W** (недельные): пневдельница 00:00 UTC до следующего понедельника
- **1D** (дневные): 00:00 UTC до 23:59 UTC
- **1M** (месячные): начало месяца до конца

**Преимущества:**
- Одни и те же уровни на всех выкладкам за период
- Соответствуют финслужбам и аналитикам
- Более стабильные

### **Конфлюэнция (совпадение уровней):**
```python
# Порог совпадения
distance_percent = abs((weekly_price - daily_price) / weekly_price × 100)

if distance_percent <= 0.3%:  # Очень близко
    strength = "VERY_STRONG"
elif distance_percent <= 1.0%:
    strength = "STRONG"
```

**Обоснование:** Когда недельный и дневной пивоты совпадают, это сильный уровень за счет согласованности разных временных горизонтов.

---

## 🧠 Trading Intelligence - агрегация всех сигналов

### **Архитектура анализа:**
```
DataCollector (OHLCV с TTL-кешем)
  ↓
6 детекторов сигналов (anomaly, WT, MTF, trend, divergence, pivot) 
  ↓
TradingIntelligence.analyze_symbol()
  ├─ _collect_all_signals()     # Собирает 6 сигналов
  ├─ _filter_signals_by_quality()  # Удаляет шум
  ├─ _analyze_signals_advanced()   # Взвешивает и объединяет
  ├─ _enhance_analysis_with_ml()  # ML улучшения P(win)
  └─ _generate_recommendation()   # Финальная рекомендация
  ↓
TradeSimulator.register_trade_async()  # Логирование в БД
```

### **Веса сигналов (адаптивные):**
```python
signal_weights = {
    SignalType.MTF_ALERT: 0.30,         # 30% - самый сильный
    SignalType.MTF_SIGNAL: 0.25,        # 25%
    SignalType.PIVOT_REVERSAL: 0.20,    # 20%
    SignalType.DIVERGENCE: 0.15,        # 15%
    SignalType.WT_SIGNAL: 0.10,         # 10%
    SignalType.TREND_SIGNAL: 0.10,      # 10%
    SignalType.ANOMALY: 0.05,           # 5%
}
```

**Total: 115% (нормализуется при расчете)**

### **Адаптация весов (Этап 4):**

Веса автоматически адаптируются на основе **реальных результатов** из taблицы `simulated_trades`:

```python
def update_signal_weights(self):
    for signal_type:
        closed_trades = count_trades(signal_type, status IN [TP, SL])
        if closed_trades < 20:  # Минимум данных
            continue
        avg_R = avg(profit_R) for signal_type
        factor = clamp(1.0 + avg_R × 0.4, 0.5, 2.0)
        new_weight = base_weight × factor
```

**Формула:**
- avg_R = +1.0 → factor = 1.4 → вес ×1.4 (улучшилось)
- avg_R = 0.0 → factor = 1.0 → вес не меняется
- avg_R = -1.0 → factor = 0.6 → вес ×0.6 (ухудшилось)

**Текущие реальные веса (163 сделки):**
- `pivot_reversal`: 0.20 → **0.24** (avg_R = +0.50) ↑
- `trend_signal`: 0.10 → **0.08** (avg_R = -0.50) ↓
- `wt_signal`: 0.10 → **0.133** (avg_R = +0.83) ↑↑

### **Пороги принятия решений:**
```python
thresholds = {
    "min_signals": 2,              # Минимум сигналов для рекомендации
    "min_strength": 40,            # Минимальная сила сигнала (0-100)
    "min_confidence": 0.6,         # Минимальная уверенность (0-1.0)
    "conflict_threshold": 0.3,     # Доля противоречивых сигналов
    "volume_threshold": 100000,    # Min объем 24h USD
    "volatility_threshold": 50.0,  # Max волатильность %
}
```

**Переопределение для топ-пар:**
- BTC, ETH, BNB, SOL, XRP, ADA, DOGE, DOT, MATIC, AVAX
- Требуют минимум 1 сигнал (вместо 2)
- Проходят даже при неидеальном контексте

### **Фильтры качества сигналов:**

1. **По объему**: 24h volume > 100k USDT
2. **По волатильности**: < 50% (слишком высокая = шум)
3. **По листингу**: возраст > 30 дней (новые = риск)
4. **Cooldown после SL**: пауза перед новым сигналом (конфиг)
5. **Дедупликация**: одна пара не дает >1 алерта подряд

---

## 🤖 ML-улучшения (Этап 4.2)

### **OutcomePredictor - RandomForest на реальных исходах**

Обучается на закрытых сделках из `simulated_trades`:

**12 признаков:**
1. `strength` - сила сигнала (0-100)
2. `confidence` - уверенность (0-1)
3. `direction` - направление (LONG/SHORT, one-hot 2 признака)
4. `signal_type` - тип сигнала (3 one-hot для PIVOT/TREND/WT)
5. `volatility` - волатильность (ATR %)
6. `price_change` - движение цены за период
7. `regime` - рыночный режим (4 one-hot для TREND_UP/TREND_DOWN/RANGE/HIGH_VOL)

**Таргет:**
- TP = 1 (успешная сделка)
- SL = 0 (неудачная сделка)

**Метрики:**
- **CV AUC**: ~0.56 (базовая линия)
- **Улучшение**: после накопления 300+ сделок с заполненным полем `regime`

**Применение:**
```python
p_win = outcome_predictor.predict_proba(features)
confidence = 0.7 × original_confidence + 0.3 × p_win
```

### **MLPredictor - OHLCV-based (ещё в разработке)**

Предсказывает:
- **PRICE_DIRECTION**: вверх/вниз на следующей свече
- **SIGNAL_STRENGTH**: усиление силы текущего сигнала

---

## ⚙️ Настройка параметров (config.yaml)

### **Файл конфигурации:**
```yaml
# BingX API
bingx_api_key: "YOUR_KEY"
bingx_secret_key: "YOUR_SECRET"

# Telegram
telegram_token: "YOUR_TOKEN"
admin_id: 123456789

# Анализ дефолт  
analysis:
  volume_multiplier: 5.0        # Коэффициент объема (3.0-8.0)
  price_threshold: 7.0          # Минимум цены движения % (5.0-15.0)
  history_size: 200             # OHLCV глубина (150-300)
  check_interval: 60            # Интервал проверки сек (30-180)
  
  # WaveTrend параметры
  wt_periods:
    n1: 10                       # Главный период (9-12)
    n2: 21                       # Сигнальный период (20-25)
    
  # Trend параметры
  trend:
    atr_period: 43              # ATR период (35-50)
    factor: 1.0                 # ATR множитель (0.8-1.2)
    
  # Пивоты параметры
  pivot:
    confluence_threshold: 0.3   # Порог конфлюэнции % (0.1-0.5)
    max_levels: 5               # Макс уровней S/R (3-7)
    types: ["traditional", "woodie", "camarilla", "fibonacci"]
```

### **Адаптивные пороги (редактируются через браузер):**
```yaml
thresholds:
  min_signals: 2
  min_strength: 40
  min_confidence: 0.6
  conflict_threshold: 0.3
  volume_threshold: 100000
  volatility_threshold: 50.0
```

### **Hot-reload настроек:**
Все параметры можно менять через веб-интерфейс:
```
http://localhost:8000/settings
```

Изменения применяются мгновенно через `ConfigLoader.save_analysis()` без перезапуска бота.

---

## 📈 Мониторинг и оптимизация

### **Проверка эффективности сигналов:**
```bash
python -c "
from core.performance_engine import PerformanceEngine
pe = PerformanceEngine('subscriptions.db')
print(pe.summary())
for r in pe.by_signal_type(): 
    print(f'{r[\"signal_type\"]}: win_rate={r[\"win_rate\"]:.1%}, avg_R={r[\"avg_r\"]:.2f}')
"
```

### **Текущие метрики (на 163 сделках):**
| Метрика | Значение | Цель |
|---------|----------|------|
| Всего сделок | 163 | 500+ |
| Win Rate | 43.3% | > 50% |
| Avg R (win) | 2.0 | > 3.0 |
| CV AUC (ML) | 0.56 | > 0.65 |
| Avg captured_R% | — | > 60% |

### **Проверка OutcomePredictor:**
```bash
python -c "
from core.outcome_predictor import OutcomePredictor
op = OutcomePredictor(); op.fit('subscriptions.db')
print(op.info())
"
```

### **Дашборд в реальном времени:**
```
http://localhost:8000       # Статистика по сигналам
http://localhost:8000/api/stats   # JSON API
```

---

## 🚀 Рекомендации по оптимизации

### **Для повышения Win Rate (текущий 43.3% → цель 50%+):**

1. **Увеличить пороги качества**
   ```yaml
   min_strength: 50  # было 40
   min_confidence: 0.7  # было 0.6
   ```

2. **Улучшить фильтры**
   - Увеличить `volume_multiplier` для более редких, но точных аномалий
   - Добавить cooldown после SL (Этап 5.1)
   - Добавить BTC-корреляцию (Этап 5.2)

3. **Переоптимизировать веса**
   - На основе backtesting за разные рыночные условия
   - Снизить вес `trend_signal` (avg_R = -0.50)
   - Повысить вес `pivot_reversal` + MTF комбинации

4. **Дедупликация сигналов** (Этап 5.1)
   - Одна монета не дает >1 сигнала подряд
   - Требует нового данных между сигналами

### **Для повышения Avg R (2.0 → 3.0+):**

1. **Динамический TP по пивотам** (Этап 6)
   ```python
   tp = nearest_pivot_level (выше/ниже entry)
   R = (tp - entry) / (entry - sl)  # Теперь 3-10 вместо фиксированного
   ```

2. **R-регрессор для предсказания потенциала** (Этап 7)
   - GradientBoostingRegressor предсказывает `max_R_possible`
   - MFE-трекинг показывает, сколько потенциала теряем

3. **Trailing Stop Loss**
   - После достижения +1R подтянуть SL в безубыток
   - Защита от разворота при достигнутой прибыли

4. **Анализ MFE (Max Favorable Excursion)**
   - Смотреть, какой максимальный R был доступен
   - `captured_R_pct = R_multiple / max_R_possible × 100%`

---

## 🏗️ Архитектурные улучшения (ROADMAP)

### **Этап 8 - Масштабирование:**

1. **Разбить монолиты**
   - `bot_with_subscriptions.py` (1540 строк) → обработчики в `bot/handlers/`
   - `trading_intelligence.py` (1850 строк) → `core/signals/` + `core/ml/`

2. **Redis кэш для OHLCV**
   - Текущий: in-memory dict (теряются при рестарте)
   - Новый: Redis → сохраняется между перезапусками

3. **PostgreSQL вместо SQLite**
   - Для >100 пользователей
   - Миграция займет 1 день с текущей прослойкой

4. **Async обработка сигналов**
   - Текущий: последовательная (60 сек цикл)
   - Желаемый: параллельная (30 сек цикл)

---

## 🔍 Частые проблемы и решения

### **Проблема: Много ложных сигналов (low win rate)**
**Решение:**
```yaml
# Увеличить пороги
min_confidence: 0.8  # было 0.6
min_strength: 60     # было 40
volume_threshold: 500000  # было 100k
conflect_threshold: 0.1  # было 0.3 (не допускать противоречия)
```

### **⚠️ КРИТИЧНО: WT пороги должны быть ±60, не ±50!**
**Проблема:** Ошибка в архитектуре - использование ±50 вместо официального стандарта ±60
- Генерирует ложные сигналы на случайных колебаниях
- Снижает win rate на 5-10%
- Может привести к потерям денег

**Файлы с ошибкой (уже исправлены):**
- `core/signal_checkers.py`: проверяйте `wt1_last < -60`, `wt1_last > 60` (не ±50)
- `core/mtf_checker.py`: проверяйте `wt1_3m < -60`, `wt1_3m > 60` (не ±50)

**Проверка:**
```bash
grep -n "< -50\|> 50" core/signal_checkers.py  # Должно быть пусто!
grep -n "< -60\|> 60" core/signal_checkers.py  # Должно быть найдено
```

### **Проблема: Нет сигналов на интересующей паре**
**Решение:**
1. Проверить объем 24h > 100k USD
2. Проверить таймфреймы (нужны данные 1H, 15m, 3m)
3. Добавить в top_pairs для ослабления требований
4. Проверить волатильность (если > 50% - пауза)

### **Проблема: Дашборд не обновляется**
**Решение:**
1. Проверить что бот работает (есть код в консоли)
2. Очистить кэш браузера (Ctrl+Shift+Delete)
3. Перезайти на `http://localhost:8000`

### **Проблема: OutcomePredictor показывает 0.56 AUC**
**Решение:**
- Это базовая линия (чуть лучше случайного)
- Нужно 300+ сделок с заполненным полем `regime`
- После этого AUC вырастет до 0.60-0.65

---

## 📚 Дополнительные материалы

### **Структура папок:**
- **`core/`** - бизнес-логика (технические индикаторы, сигналы, ML)
- **`bot/`** - UI-слой Telegram (keyboards, handlers, menus)
- **`web/`** - дашборд aiohttp
- **`tests/`** - юнит-тесты и интеграционные тесты

### **Файлы для изучения:**
1. `core/indicators.py` - реализация всех индикаторов
2. `core/trading_intelligence.py` - главный анализ
3. `core/signal_checkers.py` - каждый тип сигнала
4. `core/performance_engine.py` - статистика по сделкам
5. `config.yaml` - все параметры

### **Полезные команды:**
```bash
# Запуск бота
python bot_with_subscriptions.py

# Тесты
python -m pytest tests/ -v

# Отладка конкретного символа
python -c "
from core.data_collector import RealTimeData
from core.trading_intelligence import TradingIntelligence
import asyncio
async def test():
    dc = RealTimeData()
    ti = TradingIntelligence(dc)
    r = await ti.analyze_symbol('BTCUSDT')
    print(r)
asyncio.run(test())
"
```

---

## ✅ Контрольный список для новичка

- [ ] Понимаю, что такое WaveTrend и его зоны
- [ ] Знаю разницу между 7 типами сигналов
- [ ] Могу отредактировать параметры в config.yaml
- [ ] Умею читать статистику из PerformanceEngine
- [ ] Проверил свежие сделки в БД (subscriptions.db)
- [ ] Посетил дашборд и увидел графики
- [ ] Готов к оптимизации весов на реальных данных

---

*Документ актуален на 5 марта 2026. Обновляется с каждым этапом ROADMAP.*
