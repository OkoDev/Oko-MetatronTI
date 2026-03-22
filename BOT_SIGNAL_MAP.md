# Карта сигнальных цепочек — Oko MTF Bot

> Обновлено: 2026-03-22

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
  │   │       ├─ check_wt_signals → [ARCH-23] find_near_pivot() → если ±1% → CONFLUENCE +20str
  │   │       ├─ confluence_sm.update() / scan_wt_15m_reversal() [pivot_cache передаётся]
  │   │       ├─ check_wt_b_signals (1h)
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

### 2. WT_SIGNAL (WaveTrend) / CONFLUENCE (апгрейд, ARCH-23)
- **Детектор:** `core/signal_checkers.py` → `check_wt_signals`
- **Условие LONG:** CrossUP (wt1 пересекает wt2 снизу вверх) + wt1 < -60, gap ≥ 3
- **Условие SHORT:** CrossDOWN + wt1 > 60, gap ≥ 3
- **Фильтр 1h:** если 1h-wt1 в противоположной зоне → отклонение
- **Сила:** 70 базово, confidence: 0.8
- **ARCH-23 апгрейд** (в `scan_loop.py::scan_one`, после детекции):
  - `pivot_calculator.find_near_pivot(last_close, sym, threshold_pct=1.0)`
  - Если цена в ±1% от пивота (1M > 1W > 1D): `signal_type = CONFLUENCE`, `strength += 20` (cap 95)
  - Данные: `sig.data["near_pivot/pivot_level/pivot_source"]`
- **Данные:** avg_R без пивота +0.32, с пивотом +1.27 (4× разница)
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
- **Таймфреймы:** 15m (цена + тренд + WT из кеша scan_one, без лишних API-запросов) + 3m (FVG бонус)
- **Условие LONG:** цена в 0.5% от S1/S2/PP + WT CrossUP (OS/нейтраль) + тренд 15m UP
- **Условие SHORT:** цена в 0.5% от R1/R2/PP + WT CrossDOWN (OB/нейтраль) + тренд 15m DOWN
- **SL:** ATR(14) × 1.5, зажат в [1%, 4%]
- **TP:** следующий недельный уровень (R1→R2→R3 для LONG, S1→S2→S3 для SHORT)
- **Бонус:** FVG BULL/BEAR на 3m → confidence=VERY_HIGH, strength +10
- **Бонус:** Конфлюэнция 1W+1D → strength +10
- **Сила:** 60 базово + до 40 очков за WT кросс / смена тренда / FVG / конфлюэнцию
- **Стратегия:** `PivotReversalStrategy` (`strategies/built_in/pivot_reversal_strategy.py`)
- **Цикл:** фоновая задача, каждые 5 мин

### 9. CONFLUENCE (Конфлюэнция факторов)
- **Детектор:** `core/wt_15m_reversal_scanner.py` → `scan_wt_15m_reversal()`
- **Стратегия:** `ReversalScannerStrategy` (`strategies/built_in/reversal_scanner_strategy.py`), зарегистрирована как `"reversal_scanner"`
- **Таймфреймы:** 15m (WT, TSL) + 1W (пивоты)
- **Обязательные гейты (mandatory):**
  - TSL cross (тренд меняется)
  - WT cross (подтверждение)
- **Факторы силы:** WT zone, pivot touch (0.15%), дивергенция
- **Lookback:** 8 баров (было 20)
- **Убрано:** trend_1h, PP bias, dual_cross — обрабатывается через MTF контекст
- **MTF контекст:** применяет soft penalty к CONFLUENCE сигналам: floor=0.75 (макс. −25%)
- **SL:** TSL-линия из market_context.tsl_trendup/trenddown + буфер 0.3%, fallback ATR×1.5
- **Цикл:** scan_one (каждые 60 сек)
- **Legacy:** старый `core/confluence_scanner.py` (`scan_confluence()`) сохранён для обратной совместимости (state machine, бэктестинг)

### 10. WT_B_SIGNAL (WaveTrend Type B — дивергенция в OS/OB)
- **Детектор:** `core/signal_checkers.py` → `check_wt_b_signals`
- **Таймфрейм:** 1h (явно)
- **Условие LONG:** CrossUP ВО время OS (wt1 < adaptive p10) + дивергенция (min2_wt > min1_wt, разрыв 3-20)
- **Условие SHORT:** CrossDOWN ВО время OB (wt1 > adaptive p90) + дивергенция (max2_wt < max1_wt, разрыв 3-20)
- **Adaptive OS/OB:** p10/p90 из серии wt1 (vs фиксированных ±60 у WT_SIGNAL)
- **Фильтры:**
  - `div_strength < 3` → пропуск (слишком слабый сигнал)
  - `div_strength > 20` → пропуск (АНТИСИГНАЛ, WR=33% — продолжение тренда)
  - `lookback: 35 баров`
- **Сила:**
  - div_strength 10-20 → base=90 (WR=100% n=15 в бэктесте)
  - div_strength 6-10 → base=80 (WR=82%)
  - div_strength 3-6 → base=70 (WR=73%)
  - LONG + depth < -70 → +5
- **Confidence:** 0.88
- **Вес в TradingIntelligence:** 0.15
- **Цикл:** через analyze_symbol (fire-and-forget из scan_one)
- **Бэктест:** 103 пары, 180 дней: WR=84.9%, avgRet=+4.82% (div_strength 3-20)
- **config.yaml:** `analysis.wt_b: enabled/div_min/div_max/lookback`

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

## АДАПТИВНЫЕ ВЕСА СИГНАЛОВ (актуально на 15.03.2026)

| Тип | Базовый вес | После адаптации | Статус |
|-----|------------|-----------------|--------|
| **MTF_BIAS** | **0.50** | 0.50 | ★ ГЛАВНОЕ ЯДРО (tie-breaker) |
| **PIVOT_REVERSAL** | **0.20** | 0.24 (avg_R=+0.50) | ★ второе ядро |
| WT_B_SIGNAL | 0.15 | 0.15 | ★ новый (бэктест WR=85%, нужно 20+ сделок) |
| CONFLUENCE | 0.15 | 0.15 | через ReversalScannerStrategy (reversal_scanner) |
| SMC_STRUCTURE | 0.12 | 0.12 | BOS/CHoCH, только в pipeline |
| DIVERGENCE | 0.10 | 0.10 | только фоновые задачи |
| WT_SIGNAL | 0.08 | 0.133 (avg_R=+0.83) | — |
| TREND_SIGNAL | 0.05 | 0.04 (avg_R=-0.50) | — |
| ANOMALY | 0.03 | 0.03 | — |
| MTF_SIGNAL | — | — | ⚠️ LEGACY → заменён MTF_BIAS |
| MTF_ALERT | — | — | ⚠️ LEGACY → заменён MTF_BIAS |

**signal_type приоритет в БД (trade_simulator.py):**
`wt_b_signal > mtf_bias > confluence > pivot_reversal > smc_structure > wt_signal > divergence > trend_signal > anomaly > mtf_signal`

Формула: `new_weight = base × clamp(1 + avg_R × 0.4, 0.5, 2.0)`
Минимум 20 закрытых сделок по типу сигнала для адаптации.

> ⚠️ **Архитектурная особенность:** Дивергенции и пивоты НЕ собираются в `_collect_all_signals()` — только из фоновых задач. Это гарантирует отсутствие `conflict_ratio` в основном потоке.

> ⚠️ **MTF_BIAS** при `strength ≥ 70` и конфликте направлений — фиксирует итоговое направление рекомендации (tie-breaker).

---

## SEMAPHORE И ТАЙМАУТЫ

| Семафор | Лимит | Назначение |
|---------|-------|-----------|
| `_analyze_sem` | 3 | analyze_symbol (тяжёлый: ML + 3 OHLCV) |
| API Semaphore | 20 | api_engine (все API-вызовы к бирже), api_rps=15 |
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
    ├─ Получить текущие OHLCV (TF сделки, limit=200)
    ├─ EXPIRED: если сделка старше max_duration_minutes
    ├─ Обновить max_price / min_price (MFE трекинг)
    ├─ TSL активация при current_r >= tsl_activation_r=1.0:
    │   ├─ UPDATE tsl_activated=1 в БД
    │   ├─ Загрузить 1h OHLCV
    │   ├─ Если тренд 1h == направление сделки → TSL по 1h (широкий, меньше шума)
    │   └─ Иначе → TSL по TF сделки (15m, тесный)
    ├─ LONG: если цена <= tsl → close TSL
    ├─ SHORT: если цена >= tsl → close TSL
    ├─ SL: пробой stop_loss
    ├─ TP1: первая цель (50% фиксация, обновляет tp1_hit_at)
    └─ TP: достижение take_profit (если TP1 ещё не было)
```

**Параметры TSL:** `tsl_activation_r=1.0` (снижено с 1.5), `tsl_buffer_pct=0.5`
**Поле `tsl_activated`:** 0 = не достигал порога активации, 1 = хотя бы раз пересёк +1R

---

## СТРАТЕГИИ (strategies/)

```
strategies/
  base.py          ← BaseStrategy(ABC): analyze(), calculate_sl_tp()
  registry.py      ← @register_strategy("name"), get_strategy(name, config)
  built_in/
    confluence.py              ← ConfluenceStrategy
    reversal_scanner_strategy.py   ← ReversalScannerStrategy ★ АКТИВНАЯ (зарег. как "reversal_scanner")
    confluence_scanner_strategy.py ← ConfluenceScannerStrategy (legacy)
    conservative.py            ← ConservativeStrategy
    pivot_reversal_strategy.py ← PivotReversalStrategy
    mtf_bias.py               ← MTFBiasStrategy (в разработке)
```

**Активная стратегия:** задаётся в `config.yaml` → `trading.active_strategy: reversal_scanner`
**Переключение:** изменить значение и перезапустить бота
**CLI бэктест:** `python run_backtest.py --strategy reversal_scanner --symbol BTC/USDT --days 30`

---

## ИЗВЕСТНЫЕ ПРОБЛЕМЫ И ТЕХНИЧЕСКИЙ ДОЛГ

1. ~~risk_manager.py~~ — удалён (active_positions был пустой, мёртвый код), pyc очищены 18.03
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
