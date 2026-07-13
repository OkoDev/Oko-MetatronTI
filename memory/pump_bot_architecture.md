---
name: pump_bot_architecture
description: Архитектура Памп-Бота (Volume Anomaly Reversal Detector) — Сфера 14 Куба vs standalone
metadata:
  type: project
  status: in-planning
  date: 2026-06-27
  owner: Claude(Даат)
---

# Памп-Бот: Архитектура и Интеграция

## 📊 Суть

**Памп-Бот** = детектор аномальных объёмов (памп) на криптопарах → разворот к цене до пампа.

**Сигнал:**
- Объём +6% за 5-15 минут
- Экстремальный RSI (80+ для SHORT, 20+ для LONG)
- Trend поддерживает (1D/1W/BTC)
- Confidence ≥50%

**Выход:** Entry/SL/TP1-3 по уровням (swing points, pivots) → TG-сообщение → result tracking

---

## 🏛️ АРХИТЕКТУРНЫЙ ВЫБОР

### **Вариант A: СФЕРА 14 КУБА (Рекомендуется)**

```
Куб Метатрона (13 сфер) + Сфера 14 (PumpDetector)
    ↓
    Входная точка: WsFeed Phase 2 (OHLCV real-time)
    ↓
    Процесс: detect_pump() → PumpContext
    ↓
    Выход: EventBus (SphereEvent.PUMP_DETECTED)
    ↓
    Интеграция: PairContextBus.watchlist (памповые монеты → skip/take OOS)
    ↓
    Режимы: SHADOW (debug) → ARMED (боевой)
```

**Плюсы:**
- Согласованность с архитектурой (Куб учится на результатах)
- Feedback loop: результаты → фильтры других сфер
- Единая логика входа/выхода (PositionSizer, RiskIntelligence)
- Монитор здоровья (SelfTest проверяет Сфера 14)

**Минусы:**
- Требует валидации (новая сфера, нет истории)
- Добавляет нагрузку на EventBus

---

### **Вариант B: STANDALONE ИНСТРУМЕНТ**

```
tools/pump_monitor.py (независимо от Куба)
    ├─ Собственный WS-слушатель
    ├─ Собственное кэширование OHLCV
    ├─ detect_pump() → прямо в TG
    └─ Результаты → debug-лог (не влияют на Куб)
```

**Плюсы:**
- Быстро реализовать (нет интеграции)
- Тестировать отдельно (изоляция)

**Минусы:**
- Дублирование данных (WsFeed уже есть Phase 2)
- Результаты не влияют на Куб
- Два парадигма в коде (нарушает принцип reuse)

---

## ✅ ВЫБОР: ВАРИАНТ A (Сфера 14)

**Стратегия валидации:**

1. **SHADOW (неделя 1)**
   - Памп-Бот работает параллельно
   - Результаты → `debug_logs/pump_*.log` (не торгует)
   - Проверка: честный WR на исторических данных

2. **WALKFORWARD (неделя 2)**
   - Live-валидация на 200 парах × 5 дней
   - Метрики: WR, avgR, sharpe, max_dd
   - Порог ≥55% WR → ARMED

3. **ARMED (неделя 3+)**
   - Памп-Бот торгует в OOS-портфеле
   - Параллельно: feedback → фильтры других сфер

---

## 📋 РЕАЛИЗАЦИЯ (одна сессия)

### Файлы для создания:

```
core/pump/
  ├─ __init__.py
  ├─ pump_levels.py          # find_support_resistance(), calculate_entry_sl_tp()
  ├─ pump_detector.py        # detect_pump() → PumpContext
  ├─ pump_formatter.py       # format_pump_alert() → TG-сообщение
  ├─ pump_sphere.py          # (Сфера 14) интеграция в Куб

bot/loops/
  └─ pump_loop.py            # WS-слушатель + trigger

config.yaml
  └─ pump_bot.*              # параметры
```

### Компоненты (готовые к использованию):

✅ `compute_volume_ratio()` — vol_current / MA  
✅ `AnomalyModel` — Isolation Forest  
✅ `check_anomaly_signals()` — pipeline  
✅ `find_swing_highs/lows()` — уровни  
✅ `calculate_pivot_points()` — pivots  
✅ `WsFeed` — real-time OHLCV  

---

## 🎯 Config (pump_bot.*)

```yaml
pump_bot:
  enabled: true
  shadow_mode: true          # SHADOW→ARMED
  
  detection:
    min_volume_usd: 100000
    volume_ratio_threshold: 3.0
    min_anomaly_strength: 50
    min_confidence_tg: 50
  
  rsi:
    oversold_threshold: 20    # LONG
    overbought_threshold: 80  # SHORT
  
  levels:
    swing_period: 5
    sl_offset_pct: 1.0
    entry_offset_pct: 0.2
  
  ws:
    enabled: true
    batch_size: 50
    timeframe: 15m
```

---

## 📊 Успех-критерии (выход из SHADOW)

| Метрика | Порог | Статус |
|---------|-------|--------|
| WR (decisive) | ≥55% | ⏳ валидировать |
| avgR | ≥+0.30 | ⏳ валидировать |
| Sharpe ratio | ≥1.5 | ⏳ валидировать |
| Max DD | ≤-15% | ⏳ валидировать |
| n (выборка) | ≥100 | ⏳ валидировать |

---

## 🔗 Связь с другими сферами

- **Сфера 2 (DataCollector)**: поставляет OHLCV через WsFeed
- **Сфера 3 (RiskIntelligence)**: рассчитывает qty по detect_pump().sl
- **Сфера 11 (EventBus)**: Сфера 14 публикует PUMP_DETECTED
- **Сфера 12 (PairContextBus)**: watchlist памповых монет → skip/take OOS
- **Сфера 13 (SelfTest)**: проверяет здоровье Сферы 14

---

## ⏳ Дата: 2026-06-27 11:50 UTC

Решение: **ВАРИАНТ A (Сфера 14 Куба)** ← контракт в DISCUSSION.md

