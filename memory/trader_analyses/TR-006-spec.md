# TR-006 — Level 3 Авто-вход: 6-условный чеклист. Детальная спецификация

> Дата: 23.03.2026 | Автор: TRADER
> Статус: **ГОТОВО К ПЕРЕДАЧЕ В DEV**

---

## Обзор

Level 3 — самый строгий уровень входа. Все 6 условий должны быть выполнены для авто-регистрации сделки.

| Score | Действие |
|-------|----------|
| 6/6 | ✅ Вход (register_trade) |
| 5/6 | 👀 Watch List + уведомление "Сетап 5/6, ждём условие N" |
| 4/6 | 📝 Тихое логирование (без уведомления) |
| < 4 | 🚫 Игнорировать |

---

## Условие 1: 4h зона интереса активна (FVG или OB)

### Источник данных
`SMCContext` на 4h таймфрейме — `smc_ctx.fvg` и `smc_ctx.order_blocks`

### FVG (Fair Value Gap)
```python
# Активна если:
fvg.mitigated == False
fvg.mitigation_pct < 80.0          # < 80% заполненности (fill_pct)
bars_since_creation <= 10           # ≤ 10 баров 4h = 40 часов
# bars_since_creation = len(df_4h) - 1 - fvg.index

# Направление:
# LONG → FVGType.BULL (bullish FVG = незаполненный gap вниз → зона поддержки)
# SHORT → FVGType.BEAR

# Цена внутри зоны (для максимальной релевантности):
fvg.bottom <= current_price <= fvg.top   # необязательно, но +bonus если True
```

### Order Block (OB)
```python
# Активен если:
ob.mitigated == False
ob.volume_ratio >= 1.2              # повышенный объём на формировании (слабый фильтр)

# Направление:
# LONG → OBType.BULLISH, цена выше ob.bottom (не пробита снизу)
# SHORT → OBType.BEARISH, цена ниже ob.top (не пробита сверху)

# Bonus: ob.has_fvg_overlap == True → дополнительная конфлюэнция
```

### Агрегация
```
FVG_active OR OB_active → условие 1 ВЫПОЛНЕНО
FVG_active AND OB_active → условие 1 ВЫПОЛНЕНО + bonus_score += 5 (для условия 5)
```

### Edge cases
- Нет активных FVG и OB на 4h → условие НЕ выполнено
- `smc_ctx` недоступен (ошибка расчёта) → условие НЕ выполнено (fail-safe)

---

## Условие 2: Цена в DISCOUNT (LONG) / PREMIUM (SHORT)

### Приоритет 1: Fibonacci OTE
```python
# Источник: smc_ctx.fibonacci (на 4h)
# fib.active_ote: Optional[FibZone]

if fib.active_ote is not None:
    if direction == "LONG" and fib.active_ote.direction == "LONG":
        cond2 = fib.active_ote.price_in_ote  # True если цена в зоне 0.618–0.786
    elif direction == "SHORT" and fib.active_ote.direction == "SHORT":
        cond2 = fib.active_ote.price_in_ote
    else:
        cond2 = None  # OTE есть но противоположный → переходим к fallback
```

### Приоритет 2: 50% диапазона (fallback если нет OTE)
```python
# Источник: structure.swing_analysis на 4h
# Берём последний импульс (swing_high и swing_low из текущего диапазона)

swing_high = max(s.value for s in sa.highs[-3:])  # последние 3 swing highs
swing_low = min(s.value for s in sa.lows[-3:])    # последние 3 swing lows
midpoint = swing_low + (swing_high - swing_low) * 0.5

# LONG: цена ≤ midpoint (нижняя половина = DISCOUNT)
# SHORT: цена ≥ midpoint (верхняя половина = PREMIUM)
cond2 = (current_price <= midpoint) if direction == "LONG" else (current_price >= midpoint)
```

### Edge cases
- Нет данных о свингах → условие НЕ выполнено
- Цена ровно на midpoint (±0.1%) → условие выполнено (нейтральная зона считается ok)

---

## Условие 3: 1h структура не противоположна сигналу

### Источник данных
`SMCContext` на **1h** таймфрейме — `smc_ctx_1h.structure`

```python
last_break = structure.last_break  # Optional[StructureBreak]

if last_break is None:
    # Нет пробоя структуры → нейтрально → условие ВЫПОЛНЕНО
    cond3 = True
    score_penalty = 0

elif direction == "LONG":
    if last_break.break_type == BreakType.BEARISH_BOS:
        cond3 = False          # ← HARD BLOCK
        score_penalty = 0
    elif last_break.break_type == BreakType.BEARISH_CHOCH:
        cond3 = True           # ← SOFT BLOCK: условие выполнено, но штраф
        score_penalty = -8
    else:
        # BULLISH_BOS или BULLISH_CHOCH → по тренду
        cond3 = True
        score_penalty = 0

elif direction == "SHORT":
    if last_break.break_type == BreakType.BULLISH_BOS:
        cond3 = False          # ← HARD BLOCK
        score_penalty = 0
    elif last_break.break_type == BreakType.BULLISH_CHOCH:
        cond3 = True           # ← SOFT BLOCK
        score_penalty = -8
    else:
        cond3 = True
        score_penalty = 0
```

### Важно: "недавний" пробой
`last_break` — это последний подтверждённый пробой структуры. Если последний BOS был 5 дней назад, структура с тех пор могла восстановиться. Для production: проверять `break_index` — если `len(df_1h) - 1 - last_break.break_index > 48` (> 48 часов) → игнорировать hard block, использовать soft block.

---

## Условие 4: 15m/5m триггер (WT кросс в зоне + пивот)

### WT кросс (обязательная часть)
```python
# Источник: calculate_wt(df_15m) → wt1, wt2 arrays
# OB/OS пороги из indicators.py: get_zone(wt_value, ob1=60, os1=-60)

# LONG: кросс снизу вверх в зоне OS (wt1 < -60 в точке кросса)
wt1_curr, wt1_prev = wt1[-1], wt1[-2]
wt2_curr, wt2_prev = wt2[-1], wt2[-2]

long_cross = (wt1_prev <= wt2_prev) and (wt1_curr > wt2_curr)
long_in_os = wt1_prev < -60 or (min(wt1_prev, wt2_prev) < -53)  # был в OS на кросс
cond4_wt_long = long_cross and long_in_os

# SHORT: кросс сверху вниз в зоне OB
short_cross = (wt1_prev >= wt2_prev) and (wt1_curr < wt2_curr)
short_in_ob = wt1_prev > 60 or (max(wt1_prev, wt2_prev) > 53)
cond4_wt_short = short_cross and short_in_ob
```

### Пивот-подтверждение (рядом с уровнем)
```python
# Источник: pivot_calculator_fixed + pivot_levels.py
# tier1 = max(1.0%, min(ATR_15m * 1.5, 5.0%))  ← формула TR-004

for pivot_level in [PP, S1, S2, R1, R2, W_PP, W_S1, W_S2]:
    dist_pct = abs(current_price - pivot_level) / pivot_level * 100
    if dist_pct < tier1_pct:
        near_pivot = True
        pivot_type = "support" if pivot_level < current_price else "resistance"
        break

# LONG: near_pivot AND pivot_type == "support" (или PP)
# SHORT: near_pivot AND pivot_type == "resistance" (или PP)
```

### Агрегация условия 4
```
cond4 = WT_cross_triggered AND near_pivot

# Если WT кросс был но нет пивота → условие НЕ выполнено
# Если рядом с пивотом но нет WT кросса → условие НЕ выполнено
# Оба требуются
```

### Свежесть кросса
WT кросс валиден максимум **3 бара 15m = 45 минут** после сигнала. Старый кросс (> 3 баров) → условие НЕ выполнено.

---

## Условие 5: score ≥ 85

```python
# Источник: TradingRecommendation.overall_strength
# После применения score_penalty из условия 3

effective_score = recommendation.overall_strength + score_penalty
cond5 = effective_score >= 85
```

### Bonus score от условий 1 и 2
- Условие 1: FVG AND OB → `+5`
- Условие 2: OTE активна (не fallback 50%) → `+3`
- OB с `has_fvg_overlap == True` → `+4`

Эти бонусы не добавляются в `overall_strength` — они только влияют на `effective_score` для условия 5.

---

## Условие 6: Портфельный лимит

```python
# Источник: trade_simulator.get_open_trades()
open_trades = trade_simulator.get_open_trades()
open_longs = sum(1 for t in open_trades if t["direction"] == "LONG")
open_shorts = sum(1 for t in open_trades if t["direction"] == "SHORT")
total_open = len(open_trades)

if direction == "LONG":
    cond6 = (open_longs < 2) and (total_open < 4)
elif direction == "SHORT":
    cond6 = (open_shorts < 2) and (total_open < 4)
```

### Лимиты
| Параметр | Порог | Обоснование |
|----------|-------|-------------|
| max LONG одновременно | 2 | Концентрация риска |
| max SHORT одновременно | 2 | Концентрация риска |
| max OPEN всего | 4 | Диверсификация |

---

## Финальная агрегация

```python
conditions = {
    1: cond1,   # 4h зона интереса
    2: cond2,   # DISCOUNT/PREMIUM
    3: cond3,   # 1h структура
    4: cond4,   # WT кросс + пивот
    5: cond5,   # score ≥ 85
    6: cond6,   # портфель
}

score = sum(1 for c in conditions.values() if c)
failed = [k for k, v in conditions.items() if not v]

if score == 6:
    # ВХОД
    register_trade(recommendation)

elif score == 5:
    # WATCH LIST
    watchlist.add(symbol, reason=f"5/6: ждём условие {failed[0]}")
    notify_user(f"⚠️ {symbol} — сетап 5/6, ждём условие {failed[0]}")

elif score == 4:
    # Тихое логирование
    logger.info(f"Level3: {symbol} 4/6, failed={failed}")

else:
    # Игнорировать
    pass
```

---

## Граф зависимостей данных

```
DataCollector
├── 4h OHLCV → SMCContext_4h
│   ├── cond1: fvg, order_blocks
│   ├── cond2: fibonacci (OTE), structure.swing_analysis
│   └── bonus: has_fvg_overlap
├── 1h OHLCV → SMCContext_1h
│   └── cond3: structure.last_break
├── 15m OHLCV → indicators
│   ├── cond4a: wt1, wt2 (WT кросс)
│   └── cond4b: pivot_levels (tier1 = ATR-adaptive)
├── TradingRecommendation
│   └── cond5: overall_strength (+ penalties/bonuses)
└── TradeSimulator
    └── cond6: get_open_trades()
```

---

## Что ОТСУТСТВУЕТ в текущем коде и нужно добавить

| Недостаёт | Файл | Что нужно |
|-----------|------|-----------|
| `bars_since_creation` для FVG | `core/smc/fvg.py` | Поле отсутствует → вычислять из `fvg.index` и `len(df_4h)` в момент проверки |
| SMCContext на 4h таймфрейм | `core/smc/deep_analysis.py` | Сейчас `build_deep_analysis` принимает один df, нужен multi-TF вызов |
| SMCContext на 1h таймфрейм | то же | Нужен отдельный вызов или параметр tf |
| Свежесть WT кросса | `core/signal_checkers.py` | Проверка `bars_since_cross <= 3` |
| Портфельный лимит gate | `core/trade_simulator.py` | `register_trade_async()`: проверка до INSERT |
| Score bonuses | новый helper | Отдельная функция `calculate_l3_bonus_score()` |

---

## Приоритет реализации (для DEV)

1. **Высокий:** условия 5 и 6 — уже почти готовы, минимум кода
2. **Средний:** условие 3 — `SMCContext` на 1h + проверка `last_break`
3. **Средний:** условие 4 — WT кросс + свежесть + пивот
4. **Низкий:** условия 1 и 2 — требуют multi-TF SMC (сложнее всего)

**Рекомендация:** начать с условий 5+6+3 (Level 3-lite на 3 условиях) → добавлять 4, потом 1+2.

---

*TRADER, 23.03.2026*
