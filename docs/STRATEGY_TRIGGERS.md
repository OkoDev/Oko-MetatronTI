# Триггеры входа по активным стратегиям

> Цель: дать конкретные, проверяемые на графике условия входа для каждой активной стратегии. Открываешь TradingView, ставишь нужные индикаторы, ищешь паттерн, сверяешь с реальными сделками в БД.

**Активные стратегии (config.yaml:190-195):** `pivot_reversal`, `reversal`, `trend_following`, `multi_signal`, `mtf_bias`.

**Параметры WT (Wavetrend):** `n1=10, n2=21, OB=+60, OS=-60`
**Параметры Trend (SuperTrend-like):** `atr_period=43, factor=1.25` → формула `hl2 ± 1.25 × ATR(43)`
**Зоны (get_zone):** `OB: wt1>+60 | OS: wt1<-60 | N: иначе`
**Текущая цена:** close последней закрытой 15m свечи (entry_timeframe=15m)

---

## 1. PIVOT_REVERSAL (основная, активна)

**Источник сигнала:** [core/pivots/pivot_reversal.py:7](core/pivots/pivot_reversal.py#L7) → `check_pivot_level_signal`
**Стратегия-фильтр:** [pivot_reversal_strategy.py](strategies/built_in/pivot_reversal_strategy.py) → `min_strength=60`

### LONG-триггер (вход вверх)

```
1. Цена у недельного S1/S2/S3 или PP             (расстояние ≤ 0.5%)
2. WT1 кросс ВВЕРХ через WT2 на 15m              (wt1_prev<wt2_prev И wt1_now>wt2_now)
3. WT zone = OS или N                            (wt1 < +60, чаще wt1 < -60)
4. Trend(43,1.25) на 15m = +1 (UP)               (зелёная линия trendup под ценой)
─────────────────────────────────────────────────
ВХОД: market BUY по close 15m
SL:   level_price × (1 - 0.003)                  (0.3% под уровнем поддержки)
TP1:  PP / R1 (первый пивот выше)
TP:   следующий пивот (R1→R2→R3)
```

**Score (strength):** 60 база + 10 (WT кросс) + 10 (trend flip на этом баре) + 10 (FVG бычья на 3m) + 10 (1W+1D confluence) = max 100. Минимум для входа: ≥60.

### SHORT-триггер (вход вниз)

```
1. Цена у недельного R1/R2/R3 или PP             (≤ 0.5%)
2. WT1 кросс ВНИЗ через WT2 на 15m
3. WT zone = OB или N
4. Trend(43,1.25) на 15m = -1 (DOWN)             (красная линия trenddown над ценой)
─────────────────────────────────────────────────
ВХОД: market SELL по close 15m
SL:   level_price × (1 + 0.003)                  (0.3% над уровнем сопротивления)
TP1:  PP / S1
TP:   следующий пивот (S1→S2→S3)
```

**Особенность RANGE-режима (ARCH-55):** SL/TP пересчитываются от ближайшего пивота с буфером 0.3%, мин TP=3.5R, макс SL=2%.

**Что искать на графике:**
- Прикладывай weekly pivots (PP/S1-3/R1-3)
- WT(10,21) с порогами ±60
- SuperTrend(43, 1.25)
- Бар где close 15m в 0.5% от уровня + кросс WT в баре

---

## 2. REVERSAL (1 разворотный сигнал)

**Стратегия:** [reversal_strategy.py](strategies/built_in/reversal_strategy.py) → `min_strength=70, min_confidence=0.60`
**Принимает:** WT_SIGNAL, WT_B_SIGNAL, PIVOT_REVERSAL, DIVERGENCE

### Триггер 2.1 — WT_SIGNAL (15m)

```
LONG:
  WT1 кросс ВВЕРХ через WT2          (wt1_prev<wt2_prev → wt1>wt2)
  GAP ≥ 3 пункта                     (wt1 - wt2 ≥ 3)
  wt1 < -60 (OS)
  1h фильтр: wt1_1h НЕ > +60 (если 1h в OB → отклонение)
─────────────────────────────────────
SHORT: симметрично — кросс вниз, gap≥3, wt1>+60, 1h НЕ в OS
```

**Strength:** глубина зоны решает.
- `|wt1| ≥ 80` → 85
- `|wt1| ≥ 70` → 75
- `|wt1| ≥ 60` → 65 (минимум)
- gap ≥ 10 → +5 бонус (макс 90)

Для прохождения reversal-стратегии нужна `strength ≥ 70` → значит реально нужен `|wt1| ≥ 70` ИЛИ `|wt1|≥60 AND gap≥10`.

### Триггер 2.2 — WT_B_SIGNAL (1h, дивергенция)

```
LONG (1h):
  WT кросс вверх в 1h
  wt1 < адаптивный OS (10-й перцентиль за 80 баров)
  Bullish дивергенция в окне 35 баров:
    min(wt1) во второй половине > min(wt1) в первой   (поднимающиеся лоу WT в OS)
  div_strength = (min2 - min1) ∈ [3.0, 20.0]
─────────────────────────────────────
Strength: div_strength ≥ 10 → 90, ≥6 → 80, иначе 70.
LONG-бонус: depth < -70 → +5.
```

**Что искать:** на 1h в зоне перепроданности (нижние 10% по WT) — два минимума WT с восходящим наклоном, второй кросс вверх.

### Триггер 2.3 — PIVOT_REVERSAL — см. блок 1.

### Триггер 2.4 — DIVERGENCE

```
Regular Bullish: цена ниже-низкий (LL), WT1 выше-низкий (HL) → LONG
Regular Bearish: цена выше-высокий (HH), WT1 ниже-высокий (LH) → SHORT
Hidden Bullish: цена HL, WT1 LL → LONG (продолжение тренда)
Hidden Bearish: цена LH, WT1 HH → SHORT
```

**Confidence:** 0.75 (фиксированная). **Strength:** считается `_calculate_strength` (зависит от размаха пиков).

### Конфликт-фильтр стратегии

Если есть LONG и SHORT кандидаты:
```
|long_score - short_score| / max(...) < 0.15  →  skip (близкие силы)
```

### SL/TP стратегии

```
SL = ATR × 1.5
TP = SL × 2.0      (по умолчанию tp_rr=2.0 в коде, но в config.yaml tp_rr=3.0 для reversal)
```

---

## 3. TREND_FOLLOWING (≥2 трендовых подтверждения)

**Стратегия:** [trend_strategy.py](strategies/built_in/trend_strategy.py) → `min_signals=2, min_strength=55, min_confidence=0.55, conflict_threshold=0.25`
**Принимает:** TREND_SIGNAL, MTF_BIAS, SMC_STRUCTURE, CONFLUENCE

### Триггер 3.1 — TREND_SIGNAL (1h)

```
SuperTrend на 1h ФЛИП в текущем баре:
  trend_prev = -1, trend_now = +1   →  LONG-сигнал
  trend_prev = +1, trend_now = -1   →  SHORT-сигнал
─────────────────────────────────────
Strength: 60 (фикс), confidence 0.7
```

**Что искать:** на 1h SuperTrend(43,1.25) меняет цвет/направление в этом баре.

### Триггер 3.2 — MTF_BIAS (7-TF консенсус)

```
1. Веса ТФ: 1d=20, 4h=15, 1h=12, 45m=10, 15m=8, 5m=5, 3m=3 (сумма 73)
2. Trend в каждом ТФ из SuperTrend(43,1.25)
3. bull_pct = bull_weight / total_weight × 100  (доля бычьих ТФ)
4. bull_pct ≥ 65%  →  LONG-кандидат
   bear_pct ≥ 65%  →  SHORT-кандидат
5. Senior gate: ≥ 2 из {1h, 4h, 1d} в нужную сторону
6. Entry TF: первый из {5m, 15m, 45m, 1h} с WT cross в нужную сторону
─────────────────────────────────────
Strength: base (по bull_pct) + senior_bonus (10 если 3/3) + cross_bonus (10) - range_penalty (15)
```

**Что искать:** все ТФ в одну сторону (5+ из 7), 1h+4h+1d согласны, на 5m/15m свежий WT кросс.

### Триггер 3.3 — SMC_STRUCTURE (BOS/CHoCH на 15m)

```
BOS  (Break of Structure):  прорыв предыдущего HH/LL    →  Strength=65, продолжение тренда
CHoCH (Change of Character): первый прорыв против тренда →  Strength=55, разворот
```

### Триггер 3.4 — CONFLUENCE — выключен в config (enabled: false).

### Логика стратегии

```
LONG: ≥2 сигналов LONG среди {TREND, MTF_BIAS, SMC_STRUCTURE, CONFLUENCE}
      AND |L-S|/(L+S) ≥ 0.25  (доминирование над контр-сигналами)
SHORT: симметрично
─────────────────────────────────────
SL = ATR × 2.0     (широкий, тренд должен дышать)
TP = SL × 3.0
```

**Бонусы к confidence:**
- Если есть MTF_BIAS среди supporting → ×1.05
- SMC: BOS → +0.04, OTE-зона → +0.05, OB+FVG → +0.06

---

## 4. MULTI_SIGNAL (взвешенная конфлюэнция)

**Стратегия:** [confluence.py](strategies/built_in/confluence.py) → `min_signals=2, conflict_threshold=0.3`
**Принимает:** все типы сигналов, веса по типу.

```
Веса:
  MTF_ALERT     0.30
  CONFLUENCE    0.35   (CONFLUENCE-сигнал выключен в config)
  PIVOT_REVERSAL 0.20
  DIVERGENCE    0.15
  WT_SIGNAL     0.10
  TREND_SIGNAL  0.10
  ANOMALY       0.05

LONG:
  long_strength = Σ (signal.strength × base_weight × quality)   где quality = strength/100 × confidence
  short_strength = аналогично
  long_strength > short_strength
  |L-S|/(L+S) ≥ 0.3
  count(LONG signals) ≥ 2
─────────────────────────────────────
SL = ATR × 1.5, TP = ATR × 3.0
```

**Что искать:** одновременно ≥2 разных типа сигналов в одну сторону, нет почти равного контр-сигнала.

---

## 5. MTF_BIAS (одиночный сильный MTF)

**Стратегия:** [mtf_bias.py](strategies/built_in/mtf_bias.py) → `min_strength=60, require_confluence=False`

```
1. Один SignalData с signal_type=MTF_BIAS                (генерируется mtf_interpreter — см. 3.2)
2. strength ≥ 60
3. direction ≠ NEUTRAL
─────────────────────────────────────
ВХОД: по close 15m в направлении MTF_BIAS
SL = ATR × 0.7      (узкий, скальп)
TP = ATR × 1.4      (R:R = 1:2)
position_size = 0.5
```

---

## Глобальные фильтры (применяются ПОСЛЕ генерации recommendation)

Любая сделка должна пройти:

| Фильтр | Условие | config |
|---|---|---|
| `min_strength_register` | strength ≥ 60 → пишется в БД | `signal_quality.min_strength_register: 60` |
| `min_strength` (TG) | strength ≥ 50 → шлётся в TG | `signal_quality.min_strength: 50` |
| `blocked_regimes` | regime НЕ в [HIGH_VOL] | `trading.blocked_regimes` |
| `btc_market_gate` | BTC BULL → SHORT блок (кроме pivot_reversal); SHORT при BTC BULL требует strength≥75 | `trading.btc_market_gate` |
| `verdict_gate` | SMC contra ≥0.65 → -10 strength; WT exhaustion ≥0.65 → +5 strength | `trading.verdict_gate` |
| `weekly_bias_filter` | Против weekly bias у уровня (±1.5%) → -25 strength | `trading.weekly_bias_filter` |
| `mtf_gate` (ARCH-84) | Сильный LONG bias пары → SHORT блок | `trading.mtf_gate_enabled: true` |
| `pivot_proximity_filter` | Цена прошла >2×ATR за уровнем → hard block | `trading.pivot_proximity_filter` |
| `min_sl_dist_pct` | SL ≥ 0.3% от entry, иначе skip | `trading.min_sl_dist_pct: 0.3` |
| `circuit_breaker` | Rolling WR<15% → +10 к min_strength | `trading.circuit_breaker` |
| `correlation_groups` | Не открывать дубли BTC/WBTC, ETH/STETH/WETH, PAXG/XAUT | `trading.correlation_groups` |
| `sl_cooldown_hours` | После SL по паре — кулдаун | `signal_quality.sl_cooldown_hours` |
| `dedup_minutes` | Анти-дребезг повторных сигналов | `signal_quality.dedup_minutes` |

---

## Выход (общий для всех стратегий)

| Механизм | Триггер | Действие |
|---|---|---|
| **TP1 (Dual TP)** | R ≥ +1.0 | Закрыть 20% (config: `tp1_close_pct: 0.2`) |
| **BE after TP1** | TP1 hit | SL → entry+0.1% (LONG) |
| **TSL активация** | R ≥ +1.0 | Следить за `trenddown`/`trendup` SuperTrend(43,1.25) |
| **Cascade TSL** | Рост R | TF поднимается 15m→1h→4h |
| **DEV-106 Pivot Fast Exit** | R≥2.0 + цена у недельного/месячного пивота | Форс 15m TSL |
| **SL** | Цена ≤ stop_loss (LONG) | STOP_MARKET закрытие на бирже |
| **TP** | Цена ≥ take_profit | TAKE_PROFIT_MARKET |
| **EXPIRED** | Timeout | Auto-close с возможным extend если R≥5.0 |

---

## Чек-лист для ручной верификации (на графике)

Возьми любую закрытую сделку из `simulated_trades`:

1. Открой 15m свечи символа в TV на момент `created_at`.
2. Включи: WT(10,21) ±60, SuperTrend(43,1.25), Weekly Pivots (PP/S1-3/R1-3), ATR(14).
3. По `signal_type` сверь триггер из этого документа.
4. **Что должно совпасть:**
   - Цена у уровня (если pivot_reversal): дистанция ≤ 0.5% к weekly pivot
   - WT направление: кросс на close сигнальной свечи
   - Trend: цвет SuperTrend на close 15m
   - Strength: посчитай по правилам стратегии — должно совпасть с `strength` в БД ±5
5. **Что часто не совпадает (баги для расследования):**
   - Entry цена дальше уровня чем 0.5% (поздний вход — H1 в ARCH-95)
   - Direction против level_type (pivot_reversal LONG у R1 — H3)
   - SL ближе чем 0.3% (мелкий шум выбьет — H2)
   - Зона WT не OS/OB (WT уже отыграл — H1)

---

## Связь с расследованием ARCH-95

| Гипотеза | Куда смотреть |
|---|---|
| **H1** Поздний вход | created_at vs WT cross bar — отставание |
| **H2** Тесный SL | sl_source vs реальная дистанция SL |
| **H3** Направление пивота | level_type × direction по PIVOT_REVERSAL |
| **H4** Куб не замкнут | features_json: smc_verdict vs narrative vs реальность |
| **H5** Detector vs entry slippage | detector_price (нет в схеме — добавить) vs entry_price |
| **H6** MTF alignment | features_json `mtf_bull_pct` |
| **H7** EMA весов | per-signal_type avgR post-15.04 |
