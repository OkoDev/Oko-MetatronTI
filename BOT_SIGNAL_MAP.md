---
tags: [doc/architecture, signals, pipeline]
type: architecture
date: "2026-04-30"
parent: "[[Project-MOC]]"
---

# Карта сигнальных цепочек — Oko MTF Bot

> Обновлено: 2026-04-30 | Структура: core/signals/, core/indicators/, core/pivots/, core/mtf/
>
> 🔴 **Полная карта запуска шины и Куба** (RAW → детекторы → шина → сферы S1–S17 → roadmap):
> [[docs/SIGNAL_BUS_CUBE_MAP.md]](docs/SIGNAL_BUS_CUBE_MAP.md)

## ОБЩАЯ БЛОК-СХЕМА

```
START oko_mtf.py
  │
  ├─ load_markets (фильтр: min_vol=5M USDT ← DEV-175)
  │
  ├─ monitor_market (цикл, каждые 60 сек)
  │   │
  │   ├─ btc_regime_provider.update() ← ARCH-78 (ATR Supertrend 4h, TTL 5 мин)
  │   │
  │   ├─ scan_all_pairs — Semaphore(20)
  │   │   └─ scan_one per pair
  │   │       ├─ OHLCV prefetch (15m+1h+3m, limit=160)
  │   │       ├─ check_anomaly_signals
  │   │       ├─ check_wt_signals → [ARCH-23] find_near_pivot() → если ±1% → CONFLUENCE +20str
  │   │       ├─ scan_wt_15m_reversal() [ReversalScannerStrategy ★ АКТИВНАЯ]
  │   │       ├─ check_wt_b_signals (1h) ← ★ WR=85%
  │   │       ├─ check_smc_signals (df_15m) ← BOS/CHoCH
  │   │       └─ detect_mtf_divergence | detect_divergence → _div_passes_filters
  │   │
  │   │   СНАРУЖИ семафора (fire-and-forget):
  │   │   └─ _broadcast_intelligence_alert
  │   │       ├─ _is_duplicate_signal (dedup 30 мин) — DEBUG лог
  │   │       ├─ _is_in_sl_cooldown (4ч) — DEBUG лог
  │   │       ├─ BTC regime gate ← BTCRegimeProvider (ARCH-78):
  │   │       │     SHORT при BTC BULL: str<75 → BLOCK (кроме pivot_reversal)
  │   │       │     HIGH_VOL: предупреждение
  │   │       ├─ async with _analyze_sem (max 3)
  │   │       ├─ analyze_symbol (timeout 20s hard)
  │   │       ├─ WATCH+NEUTRAL → skip (INFO лог)
  │   │       ├─ DEV-155: min_strength по режиму (HIGH_VOL=85, LONG_RANGE=78)
  │   │       ├─ DEV-156: CircuitBreaker WR<15% → +10 к min_strength
  │   │       ├─ is_actionable (strength≥50, BUY/SELL, not NEUTRAL)
  │   │       ├─ should_register (strength≥75) → register_trade_async (DEV-68)
  │   │       └─ broadcast_with_subscription_check → TG
  │   │
  │   ├─ watch_list_breach_check (каждые 60 сек, параллельно)
  │   │   └─ SignalWatchList: пары в режиме ожидания пробоя
  │   │       ├─ WL breach → AUTO-ENTRY (без analyze_symbol)
  │   │       ├─ Escalation: WATCH+направление → дождаться пробоя → BUY/SELL
  │   │       └─ min_strength guard (DEV-68): strength ≥ 75
  │   │
  │   ├─ Каждые 5 мин: check_mtf_alerts, check_trend_signals, check_pivot_reversals — Sem(10)
  │   └─ Каждый час: check_cascade_divergences (4h→1h) — Sem(5)
  │
  ├─ trade_tracker_loop (каждые 5 мин)
  │   └─ check_open_trades_with_tsl → BE(+0.8R) / TSL(+0.5R) / TP1/TP2/TP3 / SL / EXPIRED
  │
  └─ Dashboard http://localhost:8000 (read-only)
```

---

## АРХИТЕКТУРА features_json (три слоя)

> Обновлено: 2026-05-04 | Источник: `core/trading/trade_simulator.py` строки 411-563

```
Слой 1: Universal (ВСЕГДА для всех сигналов через extra_features из TradingIntelligence)
  wt_snap, smc_snap, mtf_context (mtf_aligned_pct, mtf_senior_matches, ...),
  session, data_era, entry_tf, rr_at_entry, sl_atr_ratio, distance_to_sl_pct,
  entry_lag_seconds, detector_price, volatility, volume_24h, price_change_24h,
  btc_4h_regime, atr_trend_1h_bias, weekly_bias, wt1_value, wt2_value, wt_zone

Слой 2: Signal-specific (только для своего типа, из signal.data через supporting_signals)
  pivot_reversal  → pivot_real_touch, pivot_close_rejection, pivot_volume_z,
                    pivot_level, pivot_type, pivot_trend_changed
  wt_b_signal     → wt_b_div_strength, wt_b_depth, wt_b_wt1, wt_b_zone,
                    wt_b_os_adaptive, wt_b_ob_adaptive
  watch_list_breach → wl_score, wl_pivot_key  (fast path, Слой 1 неполный)

Слой 3: Strat metadata (в отдельных колонках БД, не в features_json)
  sl_source, tp_source, signal_type, regime
```

**⚠️ watch_list_breach** обходит `analyze_symbol()` → Слой 1 неполный (~20 полей вместо ~82).

---

## ТИПЫ СИГНАЛОВ И ИХ ПАРАМЕТРЫ

### 1. ANOMALY (Аномалия объёма)
- **Детектор:** `core/signals/signal_checkers.py` → `check_anomaly_signals`
- **Условие:** volume_ratio > 3.0× (против 20-свечного MA)
- **Сила:** min(volume_ratio × 10, 100)
- **Направление:** по изменению close последних 2 свечей
- **Вес в TI:** 0.03
- **Цикл:** scan_one (каждые 60 сек)

---

### 2. WT_SIGNAL (WaveTrend) / CONFLUENCE (апгрейд, ARCH-23)
- **Детектор:** `core/signals/signal_checkers.py` → `check_wt_signals`
- **Условие LONG:** CrossUP (wt1 пересекает wt2 снизу вверх) + wt1 < -60, gap ≥ 3
- **Условие SHORT:** CrossDOWN + wt1 > 60, gap ≥ 3
- **Фильтр 1h:** если 1h-wt1 в противоположной зоне → отклонение
- **Сила:** 70 базово, confidence: 0.8
- **ARCH-23 апгрейд** (в `scan_loop.py::scan_one`, после детекции):
  - `pivot_calculator.find_near_pivot(last_close, sym, threshold_pct=1.0)`
  - Если цена в ±1% от пивота (1M > 1W > 1D): `signal_type = CONFLUENCE`, `strength += 20` (cap 95)
- **Данные:** avg_R без пивота +0.32, с пивотом +1.27 (4× разница)
- **Адаптивный вес:** 0.133 (avg_R=+0.83)
- **Time gate (DEV-170):** только 04:00–18:00 UTC
- **Цикл:** scan_one (каждые 60 сек)

---

### 3. WT_B_SIGNAL (WaveTrend Type B — дивергенция в OS/OB) ★ WR=85%
- **Детектор:** `core/signals/signal_checkers.py` → `check_wt_b_signals`
- **Таймфрейм:** 1h (явно)
- **Условие LONG:** CrossUP ВО время OS (wt1 < adaptive p10) + дивергенция (min2_wt > min1_wt, разрыв 3-20)
- **Условие SHORT:** CrossDOWN ВО время OB (wt1 > adaptive p90) + дивергенция (max2_wt < max1_wt, разрыв 3-20)
- **Adaptive OS/OB:** p10/p90 из серии wt1 (vs фиксированных ±60 у WT_SIGNAL)
- **Фильтры:**
  - `div_strength < 3` → пропуск (слишком слабый)
  - `div_strength > 20` → пропуск (АНТИСИГНАЛ WR=33%, продолжение тренда)
  - `lookback: 35 баров`
- **Сила:**
  - div_strength 10-20 → base=90 (WR=100% n=15 в бэктесте)
  - div_strength 6-10 → base=80 (WR=82%)
  - div_strength 3-6 → base=70 (WR=73%)
  - LONG + depth < -70 → +5
- **Вес в TI:** 0.15
- **Бэктест:** 103 пары, 180 дней: WR=84.9%, avgRet=+4.82% (div_strength 3-20)
- **Цикл:** через analyze_symbol (fire-and-forget из scan_one)
- **features_json (Слой 2):** `wt_b_div_strength`, `wt_b_depth`, `wt_b_wt1`, `wt_b_zone`, `wt_b_os_adaptive`, `wt_b_ob_adaptive` ← добавлено 04.05.2026

---

### 4. CONFLUENCE ★ (ReversalScannerStrategy — АКТИВНАЯ СТРАТЕГИЯ)
- **Детектор:** `core/signals/wt_15m_reversal_scanner.py` → `scan_wt_15m_reversal()`
- **Стратегия:** `ReversalScannerStrategy` (`strategies/built_in/reversal_scanner_strategy.py`)
- **Таймфреймы:** 15m (WT, TSL) + 1W (пивоты)
- **Обязательные гейты:**
  - TSL cross (тренд меняется)
  - WT cross (подтверждение)
- **Факторы:** WT zone, pivot touch (0.15%), дивергенция
- **Lookback:** 8 баров
- **MTF контекст:** soft penalty floor=0.75 (макс. −25%)
- **SL:** TSL-линия + буфер 0.3%, fallback ATR×1.5
- **Статус DEV-171:** `analysis.confluence.enabled: false` — ПОЛНЫЙ СТОП (14.04.2026)
  - Причина: -348R суммарный убыток, убыточен во все часы и все режимы
- **Вес в TI:** 0.15
- **Цикл:** scan_one (каждые 60 сек)

---

### 5. MTF_BIAS (Multi-Timeframe Bias) ★ ГЛАВНОЕ ЯДРО
- **Детектор:** `core/mtf/mtf_interpreter.py` → `MTFInterpreter.interpret()`
- **Таймфреймы:** 6 TF: 3m, 15m, 45m, 1h, 4h, 1d
- **Модуль:** `core/intelligence/wt_specialist.py` → `derive_wt_verdict(wt_snap)`:
  - EXHAUSTION — все/большинство TF в OS/OB → conf=0.80 → gate блокирует если OB+LONG
  - REVERSAL_SETUP — кросс WT в нужной зоне → conf=0.75
  - TREND_CONTINUATION — shadow (n=48, нужно ≥150)
  - UNCLEAR → проходит
- **Вес в TI:** 0.50 (★ tie-breaker — при strength≥70 фиксирует итоговое направление)
- **Time gate (DEV-170):** только 09:00–18:00 UTC
- **Цикл:** через analyze_symbol

---

### 6. SMC_STRUCTURE (Smart Money Concepts)
- **Детектор:** `core/signals/signal_checkers.py` → `check_smc_signals`
- **Engine:** `core/smc/structure.py` → BOS/CHoCH + Breaker Blocks
- **Пакет:** `core/smc/` — swing, structure, fvg, order_blocks, fibonacci, liquidity, context
- **Условие:** BOS (Break of Structure) или CHoCH (Change of Character) на 15m
- **Вес в TI:** 0.12
- **Цикл:** scan_one (каждые 60 сек)

---

### 7. DIVERGENCE (Дивергенция WT)
- **Детектор:** `core/signals/divergence_detector.py` → `detect_divergence`
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
- **Внешние фильтры** (`_div_passes_filters` в monitoring.py):
  - Regular Bull: wt1_current < -40
  - Regular Bear: wt1_current > +40
  - Hidden Bull: wt1_current < 0 (не в OB)
  - Hidden Bear: wt1_current > 0 (не в OS)
  - Pivot proximity: цена в пределах 2% от дневного пивота
- **Вес в TI:** 0.10
- **Цикл:** scan_one (каждые 60 сек)

---

### 8. MTF_DIVERGENCE (Каскадная конфлюэнция)
- **Детектор:** `core/signals/divergence_detector.py` → `detect_cascade_divergence(1h→15m)`
- **Логика:** Hidden на 1h (тренд продолжается) + Regular на 15m (точка входа) в одном направлении
- **Бонус иерархии:** 1W→1D: +25, 1D→4h: +20, 4h→1h: +15, 1h→15m: +10
- **Те же внешние фильтры** что и у DIVERGENCE
- **Приоритет:** проверяется ПЕРВОЙ, если найдена — обычная дивергенция не ищется
- **Цикл:** scan_one (каждые 60 сек); 4h→1h — каждый час

---

### 9. MTF_ALERT (7 таймфреймов, фоновый)
- **Детектор:** `core/mtf/mtf_checker.py` → `check_mtf_alert`
- **Таймфреймы:** 3m, 5m, 15m, 45m, 1h, 4h, 1d
- **Режимы:** Classic / Aggressive / Conservative
- **Сила:** 40–100 (адаптивная)
- **Цикл:** фоновая задача, каждые 5 мин, Sem(10)

---

### 10. TREND_SIGNAL (Тренд 4h+1h+15m+5m, фоновый)
- **Детектор:** `core/indicators/trend_signals.py` → `check_trend_following_signal`
- **Паттерны:**
  - Классический откат: 15m в OS + cross_up + 5m UP — confidence=HIGH
  - Агрессивный вход: 1h в OS + 15m/5m UP (без cross) — confidence=MEDIUM ⚠️ (сомнительный)
  - Консервативный: все ТФ UP + 5m из OS — confidence=VERY_HIGH
- **Адаптивный вес:** 0.04 (avg_R=-0.50, деградировал)
- **Цикл:** фоновая задача, каждые 5 мин, Sem(10)

---

### 11. PIVOT_REVERSAL (Разворот от пивота, фоновый)
- **Детектор:** `core/pivots/pivot_reversal.py` → `check_pivot_level_signal`
- **Таймфреймы:** 15m (цена + тренд + WT из кеша scan_one) + 3m (FVG бонус)
- **Условие LONG:** цена в 0.5% от S1/S2/PP + WT CrossUP (OS/нейтраль) + тренд 15m UP
- **Условие SHORT:** цена в 0.5% от R1/R2/PP + WT CrossDOWN (OB/нейтраль) + тренд 15m DOWN
- **SL:** ATR(14) × 1.5, зажат в [1%, 4%]
- **TP:** следующий недельный уровень (hierarchy: pivot → FVG → ATR)
- **Бонусы:** FVG на 3m → confidence=VERY_HIGH + str +10; конфлюэнция 1W+1D → str +10
- **Адаптивный вес:** 0.24 (avg_R=+0.50, лучший из трековых)
- **BTC gate исключение:** pivot_reversal всегда проходит BTC SHORT блок (разворот у уровня)
- **Цикл:** фоновая задача, каждые 5 мин, Sem(10)
- **features_json (Слой 2):** `pivot_real_touch`, `pivot_close_rejection`, `pivot_volume_z`, `pivot_level`, `pivot_type`, `pivot_trend_changed` ← добавлено 02-04.05.2026

---

### 12. WATCH_LIST_BREACH (пробой пивотного уровня)
- **Детектор:** `core/db/signal_watch_list.py` → `SignalWatchList`
- **Логика:** пара добавляется в WL (WATCH action + чёткое направление). Ждёт пробоя уровня.
- **Auto-entry:** без analyze_symbol → прямой вызов register_trade_async
- **Escalation:** WATCH → улучшение условий (div_count вырос) → форсируем BUY/SELL
- **min_strength guard (DEV-68):** strength < 75 → пропуск
- **Цикл:** scan_loop, каждые 60 сек (параллельно со scan_all_pairs)

### 13. IMPULSE_FIB (импульс → лимит на откате 0.382) ★ В БОЮ с 20.08.2026
- **Детектор:** `core/smc/impulse_fib.py` → `find_setup()` · луп `bot/loops/impulse_fib_loop.py`
- **Логика:** импульс ПО ОПРЕДЕЛЕНИЮ (ход ≥3 ATR, контр-откат ≤35%, длина ≤60 баров, 1h)
  → лимит на откате 0.382 от экстремума (живёт 12 баров) → стоп 2.5·ATR → цель −1.618 фибо
- **🔴 Ключевой фильтр — РАЗМЕР СТОПА 1.5–3.2%:** вне зоны механика мертва
  (>5.7% → PF 0.71 на 2025-26), ниже 1.5% косты 0.35% съедают цель (PF 0.49)
- **Гейты (все три обязательны):** объём импульса 1.0–1.5× · по тренду EMA200 · ATR/SMA100 ≥ 1.1
- **Выход:** ФИКСИРОВАННЫЙ — БУ, трейлинг и частичная фиксация измерены, забирают до 25%
- **Обход analyze_symbol:** сигнал идёт прямо в `trade_router.submit(source="impulse_fib")`
- **Гейты роутера:** `min_sl_dist_per_strategy: 1.4` (глобальный 4.0 зарезал бы ВСЁ),
  `min_rr_per_strategy: 2.0` (RR по конструкции ~6.2), плечо 10, LIMIT-вход
- **Журнал:** таблица `impulse_shadow` ведётся и в живом режиме — сверка ФАКТИЧЕСКОЙ цены
  фила с заявленной (единственный вопрос, который бэктест закрыть не может)
- **Цикл:** каждые 900 сек · вселенная top-250 по обороту · кэп 8 позиций
- **Числа:** OOS×OOS PF 1.88 против контроля 0.70, WR ~48% (2023: 65%, 2026: 25%),
  ~17 сделок/мес → `memory/impulse_fib_cell_live.md`

---

## ЦЕПОЧКА ФИЛЬТРОВ ДО TELEGRAM И БД

```
1. Детектор (порог срабатывания)
       ↓
2. _div_passes_filters (только для дивергенций):
     WT zone + pivot proximity
       ↓
3. _broadcast_intelligence_alert:
     _is_duplicate_signal (dedup_minutes=30, ключ=symbol) → skip [DEBUG]
     _is_in_sl_cooldown (sl_cooldown_hours=4) → skip [DEBUG]
     BTC gate (ARCH-78, BTCRegimeProvider):
       HIGH_VOL → предупреждение ⚠️
       SHORT при BTC BULL + str<75 → block [INFO], кроме pivot_reversal
       ↓
4. analyze_symbol (TradingIntelligence):
     _collect_all_signals (timeout 10s)
     _analyze_signals_advanced → adaptive weights
     _enhance_analysis_with_ml (timeout 5s)
     _generate_recommendation
       ↓
5. WATCH+NEUTRAL → skip [INFO]
       ↓
6. DEV-155: min_strength по режиму
     HIGH_VOL → 85, LONG_RANGE → 78, базовый → 50
   DEV-156: CircuitBreaker
     WR<15% rolling 50 → +10 к min_strength
       ↓
7. is_actionable:
     strength ≥ min_strength AND action in (BUY,SELL) AND direction ≠ NEUTRAL
     → сообщение в TG
       ↓
8. should_register:
     strength ≥ 75 (min_strength_register, DEV-68)
     → register_trade_async — Quality Gates:
         ① Market Stress Gate (DEV-48): high stress → block (shadow)
         ② Correlation Guard (DEV-38): BTC/WBTC, PAXG/XAUT → skip дубли
         ③ Regime Direction Block (DEV-64B): LONG в TREND_DOWN / SHORT в TREND_UP
         ④ blocked_regimes (DEV-33): HIGH_VOL (настраивается в config)
         ⑤ signal_regime_block: явные запреты из config.yaml
         ⑥ max_rr cap (DEV-64A): R:R > 3.0 → обрезать TP
         ⑦ DEV-157: sl_dist_pct < 0.1% → skip
         ⑧ Portfolio Limit (DEV-52): 2L+2S+4 OPEN total
         → INSERT simulated_trades + Entry Priority Matrix shadow (DEV-172)
       ↓
9. broadcast_with_subscription_check → TG пользователям
```

---

## АДАПТИВНЫЕ ВЕСА СИГНАЛОВ (актуально на 18.04.2026)

| Тип | Базовый вес | После адаптации | Статус |
|-----|------------|-----------------|--------|
| **MTF_BIAS** | **0.50** | 0.50 | ★ ГЛАВНОЕ ЯДРО (tie-breaker при str≥70) |
| **PIVOT_REVERSAL** | **0.20** | **0.24** (avg_R=+0.50) | ★ лучший реальный |
| WT_B_SIGNAL | 0.15 | 0.15 | ★ WR=85% бэктест, нужно ≥20 реальных |
| CONFLUENCE | 0.15 | 0.15 | ⛔ ОСТАНОВЛЕН (DEV-171, убыток -348R) |
| SMC_STRUCTURE | 0.12 | 0.12 | BOS/CHoCH, только в pipeline |
| DIVERGENCE | 0.10 | 0.10 | только фоновые задачи |
| WT_SIGNAL | 0.08 | **0.133** (avg_R=+0.83) | — |
| TREND_SIGNAL | 0.10 | **0.04** (avg_R=-0.50) | — |
| ANOMALY | 0.03 | 0.03 | — |

**signal_type приоритет в БД:**
`wt_b_signal > mtf_bias > confluence > pivot_reversal > smc_structure > wt_signal > divergence > trend_signal > anomaly`

Формула: `new_weight = base × clamp(1 + avg_R × 0.4, 0.5, 2.0)`
Минимум 20 закрытых сделок по типу для адаптации.

---

## ДОПОЛНИТЕЛЬНЫЕ КОМПОНЕНТЫ (не сигналы)

### BTCRegimeProvider (ARCH-78, 16.04.2026)
- **Файл:** `core/exchange/btc_regime_provider.py`
- **Метод:** ATR Supertrend (43/1.25) на BTC 4h
- **Выходы:** BULL / BEAR / NEUTRAL (переходный период)
- **TTL:** 5 мин, singleton в bot.py
- **Влияние:** gate в monitoring.py — SHORT при BULL str<75 → BLOCK (кроме pivot_reversal)

### Entry Priority Matrix (DEV-172, shadow, 14.04.2026)
- **Файл:** `core/intelligence/entry_matrix.py`
- **Выход:** P1 / P2 / P3 / None → пишется в `features_json.entry_priority`
- **Критерии:** bias_ok (ATR 1h согласован) + zone_ok (OS/OB на 1h/4h) + trigger (WT кросс 15m)
- **Статус:** shadow, не блокирует. ⚠️ priority=None для всех сделок — баг не найден

### PairContextBus / Event Bus / SphereRegistry (Куб Метатрона)
- **Файлы:** `core/context/pair_context.py`, `core/context/event_bus.py`, `core/context/sphere_registry.py`
- **Суть:** 22 типа событий, 38 полей PairState, 13 сфер, health_check()
- **Selftest:** `core/selftest_cube.py` — L13/L14/L15 (27 проверок)

### Self-Diagnostics Suite (DEV-121, 16.04.2026)
- **Файлы:** `core/selftest.py` (L1-L12) + `core/selftest_cube.py` (L13-L15)
- **Запуск:** `python core/selftest_cube.py` (идёт за живым отчётом в `GET /api/cube/selftest`;
  бот должен быть запущен). `--stub` — каркас без бота, там все MISSING, это **не** статус сфер.
- **Проверяет:** 13 сфер (ACTIVE/SHADOW/MISSING) + 10 рёбер + 4 feedback loop

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

| Таймаут | Лимит | Следствие |
|---------|-------|-----------|
| _collect_all_signals | 10 сек | пустой список сигналов |
| _get_market_context | 15 сек | fallback без контекста |
| _enhance_analysis_with_ml | 5 сек | рекомендация без ML |
| analyze_symbol HARD | 20 сек | return None |

---

## ЗАКРЫТИЕ СДЕЛОК (trade_tracker_loop)

```
Каждые 5 минут:
  check_open_trades_with_tsl (DEV-174 фиксы применены)
    ├─ MFE трекинг: max_price / min_price
    ├─ BE при current_r (от original_sl) >= 0.8 → SL → entry ± 0.1%
    ├─ TSL активация при current_r >= 0.5 (tsl_activation_r=0.5, снижено с 1.0):
    │   ├─ Cascade TSL (DEV-67): 15m → 1h → 4h
    │   │   ├─ 4h тренд совпадает → TSL по 4h (самый широкий)
    │   │   ├─ 1h тренд совпадает → TSL по 1h
    │   │   ├─ 15m тренд совпадает → TSL по 15m
    │   │   └─ Fallback: только при совпадающем тренде (DEV-174 фикс)
    │   └─ factor=1.25 (DEV-66): TSL-линия шире → держатся дольше
    ├─ TP1 hit → tp1_hit_at записан → BE обязателен (DEV-57)
    ├─ LONG: если цена <= tsl → TSL close
    ├─ SHORT: если цена >= tsl → TSL close
    ├─ SL: пробой stop_loss
    └─ EXPIRED: > 48 часов
```

**Параметры TSL:** `tsl_activation_r=0.5` (снижено с 1.5→1.0→0.5), `tsl_buffer_pct=0.5`

---

## ДИАГНОСТИКА ПРОБЛЕМ

### Сигнал не попадает в БД:
1. `_is_duplicate_signal`? (одна пара < 30 мин)
2. `_is_in_sl_cooldown`? (SL по паре в последние 4 часа)
3. BTC gate? (SHORT при BTC BULL str<75)
4. `WATCH+NEUTRAL` фильтр?
5. `is_actionable`? (strength < min_strength или direction=NEUTRAL)
6. DEV-155 режимный порог? (HIGH_VOL=85, LONG_RANGE=78)
7. DEV-156 CircuitBreaker? (WR<15% → +10 к порогу)
8. `should_register`: strength < 75 (DEV-68)?
9. Regime block (DEV-64B): LONG при TREND_DOWN или SHORT при TREND_UP?
10. Portfolio limit: 2L+2S+4 OPEN total?
11. sl_dist_pct < 0.1% (DEV-157)?

### Сигнал не отправляется в TG:
1. Нет подписчиков?
2. subscription-фильтры (can_receive_signal, дневной лимит)?
3. analyze_symbol вернул None (таймаут 20 сек)?

### Сделка не закрывается:
1. trade_tracker_loop работает?
2. trenddown/trendup рассчитывается (calculate_trend)?
3. use_tsl=true в config.yaml?
4. original_sl заполнен? (нужен для правильного current_r — DEV-174)

---

## 🔗 Связанные заметки в Obsidian

- [[Project-MOC]] — Map of Content (главная)
- [[Architecture/ARCH-78-BTC-Regime]] — BTC gate (ATR Supertrend 4h)
- [[Features/DEV-190-Effective-Status]] — Классификация исходов сделок
- [[Features/DEV-185-Slippage-Guard]] — STOP-LIMIT buffer система
- [[Features/DEV-156-Circuit-Breaker]] — WR monitor и адаптивные пороги
- [[Features/DEV-155-Regime-Strength]] — Режимные пороги силы сигналов
- [[Signals/MTF-Bias-Generator]] — Главное ядро (tie-breaker)
- [[Signals/Pivot-Reversal]] — Разворот от уровней (лучший по avg_R)
