# 🚀 PUMP-BOT: Полная Техническая Спецификация

**Статус:** 🔴 ACTIVE PLANNING (27.06.2026)  
**Архитектура:** Сфера 14 Куба Метатрона  
**Целевой WR:** ≥55% (порог выхода из SHADOW)  
**Автор:** Claude(Даат) + DeepSeek(DS)

---

## 📌 СУТЬ (1 минута)

**Памп-Бот** — детектор аномальных объёмов на криптопарах (памп) → разворот к цене ДО пампа.

**Сигнал:**
- Объём +6% за 5-15 мин (volume_ratio > 3.0)
- RSI экстремальный (80+ SHORT / 20+ LONG)
- Trend поддерживает (1D/1W/BTC)
- Confidence ≥50%

**Выход:**
- Entry зона (тугой вход, ±0.2%)
- SL (защита, выше пампа на 1%)
- TP1/TP2/TP3 (откат к уровням: 50%/75%/100%)
- TG-сообщение (как на скриншотах гайда)

---

## 🏗️ АРХИТЕКТУРА

```
┌─────────────────────────────────────────────────────────┐
│         Сфера 14: PumpDetectorSphere                    │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  WsFeed (Phase 2)                                        │
│    ├─ Входная точка: real-time OHLCV кеш               │
│    ├─ BatchSize: 50 пар                                │
│    ├─ TimeFrame: 15m                                    │
│    └─ Callback: on_ohlcv_candle_close()                │
│       ↓                                                  │
│  PumpDetector.detect_pump(df, symbol)                   │
│    ├─ Проверка 1: volume_ratio > 3.0?                  │
│    ├─ Проверка 2: AnomalyModel.is_anomaly()?           │
│    ├─ Проверка 3: RSI экстремальный?                   │
│    ├─ Проверка 4: Trend поддерживает?                  │
│    ├─ Проверка 5: Grade = A/B/C (по факторам)         │
│    ├─ Проверка 6: Confidence = % (по кол-ву факторов)│
│    └─ Выход: PumpContext { entry, sl, tp1-3, ... }   │
│       ↓                                                  │
│  PumpLevelCalculator.calculate_entry_sl_tp()           │
│    ├─ Найти swing_low (последний перед памп)          │
│    ├─ Найти swing_high (последний максимум)           │
│    ├─ Найти traditional pivots (S1-S5, R1-R5)         │
│    ├─ Entry = pump_price ± 0.2%                       │
│    ├─ SL = max(pump_price × 1.01, swing_high × 1.002)│
│    ├─ TP1 = pump - range × 0.5  (R:R 0.4, 40%)       │
│    ├─ TP2 = pump - range × 0.75 (R:R 0.6, 30%)       │
│    └─ TP3 = swing_low            (R:R 0.7, 30%)       │
│       ↓                                                  │
│  PumpFormatter.format_pump_alert(context)              │
│    ├─ TG-сообщение (Grade, Confidence, Entry/SL/TP)  │
│    ├─ Таблица TP уровней                              │
│    ├─ Timeline (25%/50%/75%/100% откат)               │
│    └─ Скрина графика (опционально)                    │
│       ↓                                                  │
│  EventBus.publish(SphereEvent.PUMP_DETECTED)           │
│    ├─ Сфера 11 (EventBus) записывает в логи           │
│    ├─ Сфера 12 (PairContextBus) обновляет watchlist   │
│    └─ OOS-портфель может skip/take памповые пары    │
│       ↓                                                  │
│  TradingAlertBot.send_to_telegram()                    │
│    └─ Отправить в TG-канал                            │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

---

## 📁 ФАЙЛЫ ДЛЯ СОЗДАНИЯ

### 1. `core/pump/__init__.py`
**Назначение:** Экспорт публичного API  
**Содержимое:**
```python
from .pump_detector import detect_pump, PumpContext
from .pump_levels import calculate_entry_sl_tp
from .pump_formatter import format_pump_alert
```

---

### 2. `core/pump/pump_detector.py`
**Назначение:** Основной детектор памп-сигналов  

**Dataclass PumpContext:**
```python
@dataclass
class PumpContext:
    symbol: str
    timestamp: float
    pump_price: float
    current_price: float
    volume_ratio: float
    anomaly_score: float  # -1..+1 (IF score)
    anomaly_strength: int  # 0-100
    rsi_value: float
    rsi_oversold: bool  # 80+ (SHORT) / 20+ (LONG)
    trend_1d: int  # 1/-1/0 (UP/DOWN/FLAT)
    trend_1w: int
    btc_trend: int
    grade: str  # 'A' / 'B' / 'C' / None
    confidence: int  # 0-100
    entry_min: float
    entry_max: float
    stop_loss: float
    tp1: dict  # {"price": X, "pct": 50, "ratio": 0.4}
    tp2: dict
    tp3: dict
    direction: str  # 'LONG' / 'SHORT'
    signal_type: str  # 'PUMP'
```

**Функция: `async detect_pump(symbol: str, df: pd.DataFrame) -> PumpContext | None`**

```python
async def detect_pump(symbol: str, df: pd.DataFrame) -> PumpContext | None:
    """
    Детектор памп-сигналов. Проверяет все условия по гайду.
    
    Логика:
    1. volume_ratio = current_vol / MA(vol, 20)
       → if ratio < 3.0: return None
    
    2. AnomalyModel (IF) обучается на 200 последних барах
       → if not is_anomaly(): return None
    
    3. price_change = (close - close_prev) / close_prev * 100
       → direction = LONG if change > 0 else SHORT
    
    4. RSI проверка:
       → if direction == SHORT and rsi < 80: return None (SHORT requires OB)
       → if direction == LONG and rsi > 20: return None (LONG requires OS)
    
    5. Trend проверка (1D, 1W, BTC):
       → trend_1d = calculate_trend(df, ...) → 1/-1
       → trend_1w = ... (требует fetch 1W свечей)
       → btc_trend = ... (требует BTC/USDT данные)
       → if direction == SHORT and trend != -1: return None
       → if direction == LONG and trend != 1: return None
    
    6. Grade расчёт (по факторам):
       - 3+ фактора = Grade A (Confidence 80-100)
       - 2 фактора = Grade B (Confidence 60-79)
       - 1 фактор = Grade C (Confidence 40-59)
       - 0 факторов = return None (Confidence < 40)
    
    7. calculate_entry_sl_tp(pump_price, df, direction)
       → возвращает Entry, SL, TP1-3
    
    8. return PumpContext(...)
    
    Args:
        symbol: Пара (например, 'BTC/USDT:USDT')
        df: DataFrame с OHLCV + volume
    
    Returns:
        PumpContext или None если сигнал не валиден
    """
```

---

### 3. `core/pump/pump_levels.py`
**Назначение:** Расчёт Entry/SL/TP по уровням  

**Функция: `find_support_resistance(df: pd.DataFrame, period: int = 5) -> tuple[float, float]`**
```python
def find_support_resistance(df: pd.DataFrame, period: int = 5) -> tuple[float, float]:
    """
    Находит последнюю поддержку и сопротивление.
    
    Поддержка: swing_low (последний локальный минимум)
    Сопротивление: swing_high (последний локальный максимум)
    
    Returns:
        (support_level, resistance_level)
    """
```

**Функция: `calculate_entry_sl_tp(pump_price: float, current_price: float, df: pd.DataFrame, direction: str) -> dict`**
```python
def calculate_entry_sl_tp(pump_price: float, current_price: float, df: pd.DataFrame, direction: str) -> dict:
    """
    Расчёт Entry, SL, TP1-3 по гайду и уровням.
    
    Логика:
    
    1. Найти swing_low (последний) перед памп-зоной
       swing_lows = find_swing_lows(df["close"], period=5)
       last_swing_low = swing_lows[-2] если len >= 2 else df["close"].min()
    
    2. Найти swing_high (последний)
       swing_highs = find_swing_highs(df["high"], period=5)
       last_swing_high = swing_highs[-1] если len >= 1 else df["high"].max()
    
    3. Entry зона = текущая цена ± 0.2% (тугой вход)
       entry_min = pump_price * 0.998
       entry_max = pump_price * 1.002
    
    4. SL = выше пампа на 1% ИЛИ выше swing_high
       sl = max(pump_price * 1.01, last_swing_high * 1.002)
    
    5. TP уровни = откат к предыдущим ценам
       range_size = pump_price - last_swing_low
       tp1 = pump_price - range_size * 0.5   # 50% откат (R:R 0.4)
       tp2 = pump_price - range_size * 0.75  # 75% откат (R:R 0.6)
       tp3 = last_swing_low                   # 100% откат (R:R 0.7)
    
    6. Проверка по Traditional Pivots (факультативно)
       pivots = calculate_pivot_points(H, L, C)
       → S1, R1 могут быть доп. уровнями
    
    Returns:
        {
            "entry_min": float,
            "entry_max": float,
            "stop_loss": float,
            "tp1": {"price": float, "pct": 50, "ratio": 0.4},
            "tp2": {"price": float, "pct": 75, "ratio": 0.6},
            "tp3": {"price": float, "pct": 100, "ratio": 0.7}
        }
    """
```

---

### 4. `core/pump/pump_formatter.py`
**Назначение:** Форматирование сообщения для TG  

**Функция: `format_pump_alert(context: PumpContext) -> str`**
```python
def format_pump_alert(context: PumpContext) -> str:
    """
    Форматирует PumpContext в TG-сообщение.
    
    Шаблон (как на скриншотах гайда):
    
    SLXUSDT · SHORT Binance Futures · 15m
    ─────────────────────────────────
    
    Price           0.51361    +8.55%
    Grade           B
    Confidence      45/100     ███░░░░░░
    
    Volume          6.76M / 15m
    Funding         +0.0050%
    RSI             1m 89 · 1h 73
    Trend           1D flat · 1W flat · BTC bear
    
    TRADE SETUP
    Entry           0.51104 — 0.51618
    Stop Loss       0.55375    +7.8%
    TP1             0.49891    R:R 0.4    40%
    TP2             0.49156    R:R 0.6    30%
    TP3             0.48421    R:R 0.7    30%
    
    CONTEXT
    Shape           Body Move · 45% rev
    Momentum        exhausting · reversal likely
    ─────────────────────────────────
    
    Returns:
        Форматированная строка для TG
    """
```

---

### 5. `bot/loops/pump_loop.py`
**Назначение:** Главный цикл Памп-Бота  

**Функция: `async pump_monitor_loop(data_collector, ws_feed, tg_bot)`**
```python
async def pump_monitor_loop(data_collector, ws_feed, tg_bot):
    """
    Слушает WS-обновления OHLCV из Phase 2 (WsFeed).
    На каждой новой свече 15m:
    1. Получить df из кеша
    2. Вызвать detect_pump(symbol, df)
    3. Если PumpContext != None и confidence >= 50:
       → format_pump_alert() → send_to_telegram()
    4. Опубликовать EventBus.PUMP_DETECTED
    
    Цикл запускается через asyncio.create_task() из bot.py.
    Работает параллельно со scan_loop (НЕ блокирует).
    """
```

---

### 6. `config.yaml` (новая секция)
```yaml
pump_bot:
  # Режимы
  enabled: true
  shadow_mode: true          # false = ARMED (торговля)
  
  # Пороги детектора
  detection:
    min_volume_usd: 100000
    volume_ratio_threshold: 3.0
    min_anomaly_strength: 50
    min_confidence_tg: 50
    min_confidence_trade: 55
  
  # RSI пороги
  rsi:
    oversold_threshold: 20      # LONG (покупка)
    overbought_threshold: 80    # SHORT (продажа)
    rsi_period: 14
  
  # Уровни
  levels:
    swing_period: 5
    sl_offset_pct: 1.0
    entry_offset_pct: 0.2
    use_traditional_pivots: true
  
  # WS для памповых пар
  ws:
    enabled: true
    batch_size: 50
    timeframe: 15m
    watch_tfs: ["5m", "15m", "1h"]  # Дополнительные ТФ
  
  # Фильтры памповых монет
  watchlist:
    auto_filter_by_volatility: true
    min_24h_volatility_pct: 5.0
    max_pairs: 100
    
  # Logging
  logging:
    log_all_checks: false      # Много логов
    log_shadows: true          # SHADOW-сигналы
    log_file: "logs/pump_bot.log"
```

---

## 🎯 ПРИНЦИПЫ РАБОТЫ

### 1. **Real-time vs REST**
- ✅ **WS (фаза 2)**: real-time OHLCV от WsFeed
- ❌ **REST**: только fallback если WS упал

### 2. **Памповые монеты = watchlist**
- Динамический список (по волатильности 24h)
- Auto-subscribe в WsFeed.watch_ohlcv()
- Max 100 пар (экономия ресурсов)

### 3. **Confidence = честный рейтинг**
- 0-40: пропустить (шум)
- 40-60: Grade C (сомнительные)
- 60-80: Grade B (хороший сигнал)
- 80-100: Grade A (сильный сигнал)

### 4. **Entry/SL/TP = от уровней, НЕ от % офсетов**
- Swing points (pivot high/low)
- Traditional pivots (S1-S5, R1-R5)
- Конфлюенция (если несколько уровней совпадают → сильнее)

### 5. **SHADOW → ARMED**
- Неделя 1: работает, логирует, НЕ торгует
- Неделя 2: walkforward валидация (200 пар × 5 дней)
- Неделя 3+: WR ≥55% → ARMED (торговля)

### 6. **Integration с Кубом**
- Сфера 14 публикует `SphereEvent.PUMP_DETECTED`
- Сфера 12 (PairContextBus) обновляет watchlist
- OOS-портфель может skip/take памповые пары
- Результаты → обучение других сфер

---

## 📊 УСПЕХ-КРИТЕРИИ

| Метрика | Требование | Статус |
|---------|-----------|--------|
| **WR (decisive)** | ≥55% | ⏳ валидировать |
| **avgR (на decisives)** | ≥+0.30 | ⏳ валидировать |
| **Sharpe ratio** | ≥1.5 | ⏳ валидировать |
| **Max DD** | ≤-15% | ⏳ валидировать |
| **Выборка (n)** | ≥100 сделок | ⏳ валидировать |
| **На выборке из 200 пар** | 2+ недели live | ⏳ валидировать |

---

## 🔗 ЗАВИСИМОСТИ

| Модуль | Используется | Статус |
|--------|-------------|--------|
| `core.infra.data_collector.RealTimeData` | OHLCV кеш | ✅ есть |
| `core.infra.ws_feed.WsFeed` | Phase 2 (real-time) | ✅ есть |
| `core.indicators.anomaly_model.AnomalyModel` | ML детектор | ✅ есть |
| `core.indicators.indicators.compute_volume_ratio` | Vol ratio | ✅ есть |
| `core.indicators.indicators.calculate_trend` | Trend проверка | ✅ есть |
| `core.indicators.indicators.calculate_wt` | Opции (дополнительный фильтр) | ✅ есть |
| `core.indicators.indicators.find_swing_highs/lows` | Уровни | ✅ есть |
| `core.indicators.indicators.calculate_pivot_points` | Traditional pivots | ✅ есть |
| `core.context.pair_context.PairContextBus` | Watchlist обновление | ✅ есть |
| `core.context.event_bus.EventBus` | SphereEvent публикация | ✅ есть |
| `bot.monitoring.TradingAlertBot` | TG отправка | ✅ есть |

---

## ⏱️ TIMELINE

| Этап | Дата | Задача | Собственник |
|------|------|--------|-------------|
| **Phase 1: Dev** | 27-28.06 | Реализовать 6 файлов | DEV |
| **Phase 2: Shadow** | 29-30.06 | SHADOW-режим, логирование | DEV + TRADER |
| **Phase 3: Walkforward** | 01-07.07 | 200 пар × 7 дней live | TRADER |
| **Phase 4: Armed** | 08.07+ | WR ≥55% → боевой режим | TRADER + ARCH |

---

## 📝 КОНТРАКТ

**DISCUSSION.md 27.06.2026 11:50 UTC** — Памп-Бот архитектура и план утверждены.

**Вариант A (Сфера 14 Куба)** выбран. Начало реализации.

