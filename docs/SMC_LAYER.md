# SMC Layer — Smart Money Concepts

> Создано: 2026-03-20 | ARCH-17

## Назначение

SMC Layer — аналитический пакет `core/smc/`, аналог MTFContext.
Выдаёт **SMCContext** (структура рынка + зоны интереса), **НЕ** торговые сигналы.

Говорит **"где структура"** и **"что делают институционалы"**, не **"входи"**.

Вместе MTFContext + SMCContext дают системе:
- MTF: **куда смотреть** (тренд и направление на старших ТФ)
- SMC: **где входить** (Order Block, FVG, OTE зона, ликвидность)

---

## Архитектура

```
core/smc/
  __init__.py          ← экспорт: analyze_smc(), SMCContext
  models.py            ← SMCContext dataclass + analyze_smc() (точка входа)
  swing_points.py      ← Swing H/L с чередованием + HH/HL/LH/LL
  structure.py         ← BOS / CHoCH + Breaker Blocks
  fvg.py               ← Fair Value Gaps + mitigation tracking
  order_blocks.py      ← Order Blocks (зоны институциональных ордеров)
  liquidity.py         ← Кластеры ликвидности (swept/unswept)
  fibonacci.py         ← OTE зона (Fibonacci 0.618–0.786)
```

### Граф зависимостей

```
swing_points ──┬── structure ──┬── order_blocks
               │               └── fibonacci
               └── liquidity

fvg (независимый)

models (собирает все)
```

---

## Быстрый старт

```python
from core.smc import analyze_smc

# Один вызов — полный анализ
ctx = analyze_smc(df_15m, swing_period=5)

# Краткая сводка
print(ctx.summary())
# SMC(trend=BULLISH, last=BULLISH_BOS, fvg_bull=2, ob_bull=1, IN_OTE)

# Для ML — плоский dict (19 фичей)
features = ctx.to_features()
# {"smc_trend": "BULLISH", "smc_has_choch": False, ...}
```

---

## Модули

### 1. swing_points.py — Swing High/Low

**Что делает:**
Находит структурные пики (Swing High) и впадины (Swing Low) с:
- **Строгим чередованием** H-L-H-L (никогда два подряд одного типа)
- **Классификацией** HH/HL/LH/LL (Higher High, Lower Low и т.д.)
- **Определением тренда** из последовательности свингов

**Алгоритм:**
1. Pivot High: бар с `high` выше ВСЕХ соседей в окне `±period`
2. Pivot Low: бар с `low` ниже ВСЕХ соседей в окне `±period`
3. Чередование: при конфликте (два H подряд) — оставляем максимальный
4. Классификация: сравнение с предыдущим свингом того же типа
5. Тренд: HH+HL → BULLISH, LH+LL → BEARISH, иначе → NEUTRAL

**Ключевые типы:**

| Тип | Описание |
|-----|----------|
| `SwingPoint` | index, value, swing_type (HIGH/LOW), label (HH/HL/LH/LL/FIRST) |
| `SwingAnalysis` | swings[], highs[], lows[], trend, last_high, last_low |
| `StructureTrend` | BULLISH / BEARISH / NEUTRAL |

**Отличие от `indicators.find_swing_highs/lows`:**
Старые функции возвращают raw списки без чередования и классификации.
Новый модуль — полноценный structural analysis.

---

### 2. structure.py — BOS / CHoCH

**Что делает:**
Детектирует структурные пробои — ключевые события в SMC:

| Событие | Описание | Значение |
|---------|----------|----------|
| **BOS** (Break of Structure) | Пробой в направлении тренда | Подтверждение продолжения |
| **CHoCH** (Change of Character) | Пробой против тренда | Первый сигнал разворота |
| **Breaker Block** | Пробитый уровень | Зона ретеста (поддержка/сопротивление) |

**Логика классификации:**

```
Бычий тренд (HH+HL):
  Пробой Swing High вверх → BULLISH_BOS (продолжение)
  Пробой Swing Low вниз  → BEARISH_CHOCH (разворот!)

Медвежий тренд (LH+LL):
  Пробой Swing Low вниз  → BEARISH_BOS (продолжение)
  Пробой Swing High вверх → BULLISH_CHOCH (разворот!)
```

**Multi-bar confirmation:**
По умолчанию `use_close=True` — пробой фиксируется когда тело свечи
закрывается за уровнем, не по фитилю. Уменьшает ложные пробои.

**Strength расчёт:**

| Фактор | Бонус |
|--------|-------|
| BOS (базовый) | 70 |
| CHoCH (базовый) | 55 |
| Подтверждение по close | +10 |
| Давнее сопротивление (≥20 баров) | +10 |
| Давнее сопротивление (≥10 баров) | +5 |

---

### 3. fvg.py — Fair Value Gaps

**Что делает:**
Находит ценовые дисбалансы — зоны, куда институциональные игроки
стремятся вернуть цену.

**Типы FVG:**

```
Bull FVG: low[i] > high[i-2]
  Бычий импульс оставил gap — цена может вернуться для заполнения.
  Зона: [high[i-2], low[i]]

Bear FVG: high[i] < low[i-2]
  Медвежий импульс оставил gap.
  Зона: [high[i], low[i-2]]
```

**Дополнительные возможности:**
- **Mitigation tracking:** степень заполнения 0%–100%
- **Join consecutive:** два смежных FVG → расширенная зона
- **Min size filter:** фильтр по размеру gap (% от цены)
- **Nearest:** ближайший активный FVG к текущей цене

---

### 4. order_blocks.py — Order Blocks

**Что делает:**
Находит последнюю **противотрендовую** свечу перед импульсом BOS/CHoCH.
Это зона, где институциональные игроки размещали свои ордера.

**Пример:**
```
Бычий BOS → ищем последнюю МЕДВЕЖЬЮ свечу (close < open) перед пробоем.
Зона: [low, high] этой свечи → зона покупки при откате.
```

**Strength факторы:**

| Фактор | Базовый | Бонус |
|--------|---------|-------|
| Базовый OB | 60 | — |
| CHoCH-based (разворот) | — | +15 |
| Volume ≥ 2.0× MA | — | +15 |
| Volume ≥ 1.5× MA | — | +10 |
| FVG overlap | — | +10 |

**Суперсетап:** OB + FVG на одном уровне = двойное подтверждение зоны входа.

---

### 5. liquidity.py — Кластеры ликвидности

**Что делает:**
Группирует свинги в кластеры по близости уровней.
Много свингов на одном уровне = много стопов = зона интереса.

**Типы:**
- **Buy-side liquidity:** над Swing Highs (стопы шортистов)
- **Sell-side liquidity:** под Swing Lows (стопы лонгистов)

**Sweep tracking:**
После sweep (цена проходит через кластер) — ликвидность "собрана",
новые стопы ещё не накопились.

**Strength:** `30 + swing_count × 20` (макс 100), swept: -40.

---

### 6. fibonacci.py — OTE зона

**Что делает:**
Рассчитывает Fibonacci retracement от последнего импульса.
OTE (Optimal Trade Entry) = зона 0.618–0.786, наиболее вероятный
уровень отката перед продолжением тренда.

**Стандартные уровни:** 0.236, 0.382, 0.500, **0.618**, **0.786**, 0.886

**Пример для бычьего импульса (high=110, low=100):**
```
OTE top    = 110 - 10 × 0.618 = 103.82
OTE bottom = 110 - 10 × 0.786 = 102.14
→ Цена в [102.14, 103.82] = оптимальный LONG
```

---

## SMCContext — единый контекст

`SMCContext` объединяет все модули. Ключевые свойства:

### Derived properties (вычисляемые)

| Свойство | Тип | Описание |
|----------|-----|----------|
| `trend` | StructureTrend | BULLISH/BEARISH/NEUTRAL |
| `last_break` | StructureBreak? | Последний BOS/CHoCH |
| `has_choch` | bool | Был ли разворот? |
| `has_bos` | bool | Было ли подтверждение? |
| `active_resistance` | float? | Ближайший непробитый Swing High |
| `active_support` | float? | Ближайший непробитый Swing Low |
| `nearest_bull_ob` | OrderBlock? | Ближайший бычий OB |
| `nearest_bear_ob` | OrderBlock? | Ближайший медвежий OB |
| `price_in_ote` | bool | Цена в OTE зоне? |
| `has_bullish_ob_with_fvg` | bool | Суперсетап: OB + FVG бычий |
| `has_bearish_ob_with_fvg` | bool | Суперсетап: OB + FVG медвежий |
| `nearest_buy_liquidity` | LiquidityZone? | Ближайшая buy-side ликвидность |
| `nearest_sell_liquidity` | LiquidityZone? | Ближайшая sell-side ликвидность |

### to_features() — для ML

19 фичей с префиксом `smc_`:
```python
{
    "smc_trend": "BULLISH",
    "smc_has_choch": False,
    "smc_has_bos": True,
    "smc_last_break_type": "BULLISH_BOS",
    "smc_last_break_strength": 80,
    "smc_active_resistance": 1.2345,
    "smc_active_support": 1.1890,
    "smc_active_bull_fvg_count": 2,
    "smc_active_bear_fvg_count": 0,
    "smc_active_bull_ob_count": 1,
    "smc_active_bear_ob_count": 0,
    "smc_bull_ob_fvg_overlap": True,
    "smc_bear_ob_fvg_overlap": False,
    "smc_price_in_ote": True,
    "smc_ote_direction": "LONG",
    "smc_buy_liq_count": 1,
    "smc_sell_liq_count": 2,
    "smc_nearest_buy_liq_strength": 70,
    "smc_nearest_sell_liq_strength": 50,
}
```

---

## Использование в стратегиях

### Бонусы за SMC контекст

```python
ctx = analyze_smc(df_15m)

# Суперсетап: OB + FVG
if ctx.has_bullish_ob_with_fvg:
    strength += 25

# Цена в OTE зоне
if ctx.price_in_ote:
    strength += 15

# CHoCH = ранний сигнал разворота
if ctx.has_choch and ctx.last_break.is_choch:
    strength += 10

# Ликвидность собрана (sweep) → разворот вероятен
liq = ctx.nearest_sell_liquidity
if liq and not liq.is_active:
    strength += 10  # swept sell-side = бычий сигнал
```

### SL/TP из SMC

```python
# SL за ближайшим активным support/resistance
if ctx.active_support:
    sl_level = ctx.active_support * 0.998  # -0.2% буфер

# TP по ликвидности (цена стремится к ликвидности)
if ctx.nearest_buy_liquidity:
    tp_level = ctx.nearest_buy_liquidity.level
```

---

## Тесты

```bash
python -m pytest tests/unit/test_smc_layer.py -v
```

44 теста: swing_points (10), fvg (6), structure (6), order_blocks (4),
liquidity (5), fibonacci (4), models/SMCContext (8), edge cases.

---

## Совместимость

Старый `core/structure_detector.py` остаётся как fallback.
Он использует `indicators.find_swing_highs/lows` (без чередования/классификации).

Новый `core/smc/` — полная замена с расширенным функционалом.
Миграция: заменить `detect_structure()` из `structure_detector.py`
на `analyze_smc()` из `core/smc/` при интеграции в пайплайн.

---

## Интеграция в пайплайн (реализовано)

| # | Задача | Статус |
|---|--------|--------|
| 8 | Интеграция SMCContext в trading_intelligence.py | ✅ |
| 9 | SMC-фичи в features_json (для ML) | ✅ |
| 10 | Бонусы в стратегиях (OB+FVG=суперсетап) | ✅ |

### Шаг 8 — Интеграция в analyze_symbol

- `MarketContext.smc_context` — новое поле в `core/signal_models.py`
- В `_collect_all_signals` после OHLCV-загрузки вызывается `analyze_smc(df_entry)`
- SMCContext сохраняется в `market_context.smc_context` и `recommendation.metadata["smc_context"]`

### Шаг 9 — SMC фичи в features_json

- `trade_simulator.py`: 19 фичей с префиксом `smc_` добавляются в `features_json`
- Данные берутся из `metadata["smc_context"]` (результат `to_features()`)

### Шаг 10 — SMC бонусы в стратегиях

**ReversalStrategy** (`strategies/built_in/reversal_strategy.py`):
- CHoCH → +0.05 confidence (разворот структуры подтверждает разворотный сигнал)
- OB + FVG суперсетап → +0.07 confidence (двойное подтверждение зоны)
- OTE зона → +0.04 confidence (оптимальный откат)

**TrendFollowingStrategy** (`strategies/built_in/trend_strategy.py`):
- BOS → +0.04 confidence (подтверждение тренда)
- OTE зона → +0.05 confidence (откат внутри тренда)
- OB + FVG суперсетап → +0.06 confidence

**recommendation_generator.py** — SL приоритет 2.5:
- SMC Order Block используется как SL-уровень (приоритет между FVG и TSL)
- LONG: SL за нижней границей бычьего OB
- SHORT: SL за верхней границей медвежьего OB
