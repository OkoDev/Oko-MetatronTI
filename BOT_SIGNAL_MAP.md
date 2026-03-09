# Карта сигнальных цепочек — Oko MTF Bot

> Сгенерировано: 2026-03-08

## ОБЩАЯ БЛОК-СХЕМА

```
START monitoring
  │
  ├─ load_markets (фильтр: min_vol=1M USDT)
  │
  ├─ monitor_market (цикл, каждые 60 сек)
  │   │
  │   ├─ scan_all_pairs — Semaphore(20)
  │   │   └─ scan_one per pair
  │   │       ├─ OHLCV prefetch (15m+1h+3m, limit=160)
  │   │       ├─ check_anomaly_signals
  │   │       ├─ check_wt_signals
  │   │       ├─ check_mtf_signals
  │   │       └─ detect_mtf_divergence | detect_divergence → _div_passes_filters
  │   │
  │   │   СНАРУЖИ семафора (fire-and-forget):
  │   │   └─ _broadcast_intelligence_alert
  │   │       ├─ async with _analyze_sem (max 3)
  │   │       ├─ analyze_symbol (timeout 30s)
  │   │       ├─ Фильтры: dedup / sl_cooldown / BTC-режим
  │   │       ├─ is_actionable (strength>=50, BUY/SELL, not NEUTRAL)
  │   │       ├─ should_register (strength>=40) → register_trade_async
  │   │       └─ broadcast_with_subscription_check → TG
  │   │
  │   ├─ Каждые 5 мин: check_mtf_alerts, check_trend_signals, check_pivot_reversals
  │   └─ Каждый час: check_cascade_divergences (4h→1h)
  │
  ├─ trade_tracker_loop (каждые 5 мин)
  │   └─ check_open_trades_with_tsl → SL/TP/TSL → close_trade
  │
  └─ Dashboard http://localhost:8000 (read-only)
```

---

## ТИПЫ СИГНАЛОВ И ИХ ФИЛЬТРЫ

### 1. ANOMALY (Аномалия объёма)
- **Детектор:** `core/signal_checkers.py` → `check_anomaly_signals`
- **Условие:** volume_ratio > 3.0× (против 20-свечного MA)
- **Сила:** min(volume_ratio × 10, 100)
- **Направление:** по изменению close последних 2 свечей
- **Внутренние фильтры:** только порог 3.0×
- **Цикл:** scan_one (каждые 60 сек)

### 2. WT_SIGNAL (WaveTrend)
- **Детектор:** `core/signal_checkers.py` → `check_wt_signals`
- **Условие LONG:** CrossUP (wt1 пересекает wt2 снизу вверх) + wt1 < -60
- **Условие SHORT:** CrossDOWN + wt1 > 60
- **Фильтр 1h:** если 1h-wt1 в противоположной зоне → отклонение
- **Сила:** 70, confidence: 0.8
- **Цикл:** scan_one (каждые 60 сек)

### 3. MTF_SIGNAL (Мульти-таймфрейм)
- **Детектор:** `core/signal_checkers.py` → `check_mtf_signals`
- **Условие LONG:** тренд 1h=UP + WT 15m растёт + wt1_3m < -60
- **Условие SHORT:** тренд 1h=DOWN + WT 15m падает + wt1_3m > 60
- **Сила:** 85, confidence: 0.9
- **Цикл:** scan_one (каждые 60 сек)

### 4. MTF_ALERT (7 таймфреймов)
- **Детектор:** `core/mtf_checker.py` → `check_mtf_alert`
- **Таймфреймы:** 3m, 5m, 15m, 45m, 1h, 4h, 1d
- **Режимы:** Classic / Aggressive / Conservative
- **Сила:** 40–100 (адаптивная)
- **Цикл:** фоновая задача, каждые 5 мин

### 5. DIVERGENCE (Дивергенция WT)
- **Детектор:** `core/divergence_detector.py` → `detect_divergence`
- **Типы:**
  - Regular Bullish: цена LL + wt HL (оба пивота < -60) → разворот вверх
  - Regular Bearish: цена HH + wt LH (оба пивота > 60) → разворот вниз
  - Hidden Bullish: цена HL + wt LL → продолжение тренда вверх
  - Hidden Bearish: цена LH + wt HH → продолжение тренда вниз
- **Параметры:** pivot_period=5, max_bars=100, min_bars=5
- **Расчёт силы (0–100):**
  - Расстояние между точками: до 25 балл
  - Изменение WT: до 25 балл
  - Изменение цены: до 20 балл
  - Зона (OB/OS): до 30 балл
  - Бонус двойная: +15, тройная: +25
- **ВНЕШНИЕ ФИЛЬТРЫ** (`_div_passes_filters` в monitoring.py):
  - Regular Bull: wt1_current < -40
  - Regular Bear: wt1_current > +40
  - Hidden Bull: wt1_current < 0 (не в OB)
  - Hidden Bear: wt1_current > 0 (не в OS)
  - Pivot proximity: цена в пределах 2% от дневного пивота
- **Цикл:** scan_one (каждые 60 сек)

### 6. MTF_DIVERGENCE (Каскадная конфлюэнция)
- **Детектор:** `core/divergence_detector.py` → `detect_cascade_divergence(1h→15m)`
- **Логика:** Hidden на 1h (тренд продолжается) + Regular на 15m (точка входа) в одном направлении
- **Бонус иерархии:** 1W→1D: +25, 1D→4h: +20, 4h→1h: +15, 1h→15m: +10
- **Те же внешние фильтры** что и у DIVERGENCE
- **Приоритет:** проверяется ПЕРВОЙ, если найдена — обычная дивергенция не ищется
- **Цикл:** scan_one (каждые 60 сек); 4h→1h — каждый час

### 7. TREND_SIGNAL (Тренд EMA)
- **Детектор:** `core/trend_signals.py` → `check_trend_following_signal`
- **Таймфреймы:** 4h (тренд) + 1h (подтверждение) + 15m (откат) + 5m (вход)
- **Условие LONG:** 4h UP + 1h UP + 15m WT нейтраль/OS + 5m разворот вверх
- **Режимы:** Classic / Aggressive / Conservative
- **Цикл:** фоновая задача, каждые 5 мин

### 8. PIVOT_REVERSAL (Разворот от пивота)
- **Детектор:** `core/pivot_reversal.py` → `check_pivot_level_signal`
- **Таймфреймы:** 1m (цена) + 5m (тренд) + 3m (FVG) + 15m (WT)
- **Условие LONG:** цена в 0.5% от S1/S2/PP + WT CrossUP (OS/нейтраль) + тренд 5m UP
- **Условие SHORT:** цена в 0.5% от R1/R2/PP + WT CrossDOWN (OB/нейтраль) + тренд 5m DOWN
- **Бонус:** FVG BULL/BEAR на 3m
- **Цикл:** фоновая задача, каждые 5 мин

---

## ЦЕПОЧКА ФИЛЬТРОВ ДО TELEGRAM И БД

```
1. Детектор (порог срабатывания)
       ↓
2. _div_passes_filters (только для дивергенций):
     WT zone + pivot proximity
       ↓
3. _broadcast_intelligence_alert:
     WATCH+NEUTRAL → skip
     is_duplicate_signal (dedup_minutes=30, ключ=symbol) → skip
     is_in_sl_cooldown (sl_cooldown_hours=4) → skip
     BTC контр-тренд: strength < 70 → block, >= 70 → warning
       ↓
4. analyze_symbol (TradingIntelligence):
     _collect_all_signals (timeout 10s)
     _analyze_signals_advanced → adaptive weights
     _enhance_analysis_with_ml (timeout 5s)
     _generate_recommendation
       ↓
5. is_actionable:
     strength >= 50 AND action in (BUY,SELL) AND direction != NEUTRAL
     → footer "Сделка зарегистрирована" в TG
       ↓
6. should_register:
     strength >= 40
     → register_trade_async → INSERT simulated_trades
       ↓
7. broadcast_with_subscription_check → TG пользователям
```

---

## АДАПТИВНЫЕ ВЕСА СИГНАЛОВ

| Тип | Базовый вес | Пример после адаптации |
|-----|------------|------------------------|
| MTF_ALERT | 0.30 | 0.30 (нет данных) |
| MTF_SIGNAL | 0.25 | 0.25 |
| PIVOT_REVERSAL | 0.20 | 0.24 (avg_R=+0.50) |
| DIVERGENCE | 0.15 | 0.15 |
| WT_SIGNAL | 0.10 | 0.133 (avg_R=+0.83) |
| TREND_SIGNAL | 0.10 | 0.08 (avg_R=-0.50) |
| ANOMALY | 0.05 | 0.05 |

Формула: `new_weight = base × clamp(1 + avg_R × 0.4, 0.5, 2.0)`
Минимум 20 закрытых сделок по типу сигнала для адаптации.

---

## SEMAPHORE И ТАЙМАУТЫ

| Семафор | Лимит | Назначение |
|---------|-------|-----------|
| `_analyze_sem` | 3 | analyze_symbol (тяжёлый: ML + 3 OHLCV) |
| scan_all_pairs | 20 | параллельный скан пар |
| check_mtf_alerts | 10 | фоновые MTF-алерты |
| check_trend_signals | 10 | фоновые тренд-сигналы |
| check_pivot_reversals | 10 | фоновые пивот-сигналы |
| check_cascade_divs | 5 | MTF-дивергенции (4h→1h) |
| _prefetch_pivots | 5 | прогрев кеша пивотов |

| Операция | Таймаут | Следствие при превышении |
|----------|---------|--------------------------|
| _collect_all_signals | 10 сек | пустой список сигналов |
| _get_market_context | 15 сек | fallback без контекста |
| _enhance_analysis_with_ml | 5 сек | рекомендация без ML |

---

## РЕГИСТРАЦИЯ СДЕЛКИ

```
register_trade_async(recommendation, data_collector)
  ├─ MarketRegimeClassifier.classify_from_ohlcv
  │   └─ ADX + ATR + EMA → TREND_UP / TREND_DOWN / RANGE / HIGH_VOL
  ├─ get_pivot_tp_with_source → TP привязан к ближайшему пивоту (min R=1.5)
  └─ INSERT simulated_trades:
       symbol, timeframe (15m), signal_type, direction,
       entry_price, stop_loss, take_profit, sl_source, tp_source,
       strength, confidence, regime, created_at, status=OPEN,
       features_json: {volume_24h, price_change_24h, volatility, ...}
```

---

## ЗАКРЫТИЕ СДЕЛОК (trade_tracker_loop)

```
Каждые 5 минут:
  check_open_trades_with_tsl
    ├─ Получить текущие OHLCV
    ├─ Обновить max_price / min_price (MFE трекинг)
    ├─ LONG: если цена < trenddown → TSL (если активирован после +1R)
    ├─ SHORT: если цена > trendup → TSL
    ├─ SL: пробой stop_loss
    └─ TP: достижение take_profit
```

**Параметры TSL:** `tsl_activation_r=1.0`, `tsl_buffer_pct=0.1`

---

## ИЗВЕСТНЫЕ ПРОБЛЕМЫ И ТЕХНИЧЕСКИЙ ДОЛГ

1. **risk_manager.py**: `active_positions` всегда пустой — `add_position/remove_position` нигде не вызываются
2. **Fallback pivot**: если `analyze_symbol` упал по таймауту — pivot_reversal регистрируется без AI
3. **Скрытые дивергенции**: фильтр `wt1 < 0` может быть мягким в боковом рынке
4. **Прогрев пивотов**: `_prefetch_pivots` запускается как `create_task` — первый цикл стартует до завершения прогрева
5. **analyze_symbol кеш**: TTL=5 мин, один и тот же символ может быть проанализирован повторно через разные сигнальные пути

---

## ДИАГНОСТИКА ПРОБЛЕМ

### Сигнал не попадает в БД:
1. `is_duplicate_signal`? (одна пара < 30 мин)
2. `is_in_sl_cooldown`? (SL по паре в последние 4 часа)
3. `is_actionable`? (strength < 50 или direction=NEUTRAL)
4. BTC контр-тренд + strength < 70?
5. `analyze_symbol` вернул None (таймаут 30 сек)?
6. Для дивергенций: `_div_passes_filters`?

### Сигнал не отправляется в TG:
1. Нет подписчиков?
2. subscription-фильтры (`can_receive_signal`, дневной лимит)?
3. WATCH+NEUTRAL фильтр?

### Сделка не закрывается:
1. `trade_tracker_loop` работает?
2. `trenddown`/`trendup` рассчитывается (calculate_trend)?
3. `use_tsl=true` в config.yaml?
