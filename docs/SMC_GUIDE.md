# SMC Layer — Полный гайд для трейдера и разработчика

> Создано: 21.03.2026 | ARCH-17 | Версия 1.0

---

## Оглавление

1. [Что такое SMC и зачем он нам](#1-что-такое-smc-и-зачем-он-нам)
2. [Как SMC видит рынок — ментальная модель](#2-как-smc-видит-рынок--ментальная-модель)
3. [Модуль 1: Swing Points — скелет структуры](#3-модуль-1-swing-points--скелет-структуры)
4. [Модуль 2: Structure (BOS / CHoCH) — пульс тренда](#4-модуль-2-structure-bos--choch--пульс-тренда)
5. [Модуль 3: FVG — следы институционалов](#5-модуль-3-fvg--следы-институционалов)
6. [Модуль 4: Order Blocks — где сидят деньги](#6-модуль-4-order-blocks--где-сидят-деньги)
7. [Модуль 5: Liquidity — где стоят стопы](#7-модуль-5-liquidity--где-стоят-стопы)
8. [Модуль 6: Fibonacci OTE — золотая зона](#8-модуль-6-fibonacci-ote--золотая-зона)
9. [SMCContext — единый объект](#9-smccontext--единый-объект)
10. [Как SMC интегрирован в бот](#10-как-smc-интегрирован-в-бот)
11. [Торговые сценарии и суперсетапы](#11-торговые-сценарии-и-суперсетапы)
12. [ML-фичи и обучение](#12-ml-фичи-и-обучение)
13. [Что НЕ делает SMC Layer](#13-что-не-делает-smc-layer)
14. [Тюнинг параметров](#14-тюнинг-параметров)

---

## 1. Что такое SMC и зачем он нам

**Smart Money Concepts (SMC)** — методология анализа, основанная на идее что рынком двигают институциональные игроки ("умные деньги"). Они оставляют следы в ценовых паттернах, которые можно обнаружить алгоритмически.

### Проблема без SMC

Наш бот до SMC видел рынок так:
- WT пересёкся в OS → "BUY!"
- Дивергенция на 1h → "Возможно разворот"

Это **когда** торговать, но не **где**. WT может дать cross в OS, но если это зона без структурной поддержки — цена просто продолжит падать.

### Что добавляет SMC

SMC отвечает на вопрос **"где именно входить и ставить стоп"**:

```
Было:  WT cross в OS → BUY                         → WR ~20%
Стало: WT cross в OS + Order Block + FVG + OTE зона → WR ???%
       (суперсетап — 3 подтверждения на одном уровне)
```

### Два контекста = полная картина

```
MTFContext — КУДА смотреть (направление, тренд на 7 ТФ)
SMCContext — ГДЕ входить  (структура, зоны, ликвидность)
```

MTFContext говорит "тренд бычий, 76% таймфреймов за LONG".
SMCContext говорит "вот конкретный уровень 1.2340–1.2365, тут Order Block + FVG, стоп за 1.2315".

---

## 2. Как SMC видит рынок — ментальная модель

Представь что ты институциональный трейдер с ордером на $50M. Ты не можешь просто кликнуть "BUY" — рынок тебя сожрёт проскальзыванием. Тебе нужно:

1. **Собрать ликвидность** — вытолкнуть цену к стопам ритейла, чтобы забрать их объём
2. **Войти в зоне** — на уровне где раньше были твои ордера (Order Block)
3. **Двигать цену** — создавая BOS (пробой структуры)

SMC Layer отслеживает каждый из этих шагов:

```
Шаг институционала          Что видит SMC Layer
─────────────────────       ───────────────────────
1. Накопление ордеров   →   Order Block (последняя противотрендовая свеча)
2. Импульс              →   BOS/CHoCH (пробой структуры) + FVG (дисбаланс)
3. Сбор ликвидности     →   Liquidity sweep (цена вынесла стопы)
4. Откат в зону         →   Цена вернулась в OTE (0.618–0.786 Фибоначчи)
5. Продолжение          →   Новый BOS в том же направлении
```

---

## 3. Модуль 1: Swing Points — скелет структуры

**Файл:** `core/smc/swing_points.py`

### Что это

Swing Points — это структурные пики (Swing High) и впадины (Swing Low). Это **скелет** рынка, от которого строится всё остальное.

### Визуально

```
Цена
  │     SH ←─ Swing High (HH)
  │    / \
  │   /   \        SH ←─ LH (Lower High = слабость)
  │  /     \      / \
  │ /       \    /   \
  │/    SL ──\──/     \
  │     ↑     \/       \
  │   HL     SL ←─ LL (Lower Low = медведи)
  └─────────────────────── Время
```

### Алгоритм (4 шага)

**Шаг 1: Поиск raw pivot'ов**

Pivot High = бар, чей `high` выше ВСЕХ соседей в окне `±period`.

```python
# period=5: бар должен быть выше 5 баров слева И 5 баров справа
for i in range(period, n - period):
    is_high = all(high[i] > high[j] for j in range(i-period, i+period+1) if j != i)
```

Чем больше `period` — тем значимее свинг:
- `period=3` → мелкие свинги, много шума
- `period=5` → умеренно (наш дефолт)
- `period=10` → только крупные, пропустит мелкие развороты

**Шаг 2: Чередование (alternation)**

В реальном рынке структура всегда чередуется: HIGH → LOW → HIGH → LOW.

Если алгоритм нашёл два HIGH подряд — это конфликт. Правило:
- Два HIGH подряд → оставляем **тот, что выше** (значимее)
- Два LOW подряд → оставляем **тот, что ниже** (значимее)

```
Сырые данные:  H  H  L  H  L  L  H
                ↓
После чередования: H  L  H  L  H
                   (убрали дубли, оставили экстремумы)
```

Почему это важно: без чередования BOS/CHoCH детекция сломается — она считает "пробой Swing High ВВЕРХ" и "пробой Swing Low ВНИЗ". Если два H подряд, непонятно какой пробивать.

**Шаг 3: Классификация**

Каждый свинг сравнивается с предыдущим свингом **того же типа**:

| Свинг | Предыдущий H | Сравнение | Метка |
|-------|-------------|-----------|-------|
| HIGH = 105 | 100 | 105 > 100 | **HH** (Higher High) |
| HIGH = 98 | 105 | 98 < 105 | **LH** (Lower High) |
| LOW = 95 | 90 | 95 > 90 | **HL** (Higher Low) |
| LOW = 88 | 95 | 88 < 95 | **LL** (Lower Low) |

**Шаг 4: Определение тренда**

По комбинации последних меток:

| Паттерн | Тренд | Значение |
|---------|-------|----------|
| HH + HL | **BULLISH** | Растущие пики И растущие впадины |
| LH + LL | **BEARISH** | Падающие пики И падающие впадины |
| Иное | **NEUTRAL** | Нет чистой структуры |

### Код использования

```python
from core.smc.swing_points import detect_swing_points

analysis = detect_swing_points(df_15m, period=5)

print(analysis.trend)       # BULLISH / BEARISH / NEUTRAL
print(analysis.last_high)   # HH(1.2345@142)
print(analysis.last_low)    # HL(1.2100@128)
print(len(analysis.swings)) # 12 (чередующаяся H-L-H-L последовательность)
```

### Чем отличается от старого `indicators.find_swing_highs/lows`

Старая функция в `indicators.py` просто находила пики без:
- Чередования (могла дать два HIGH подряд)
- Классификации (HH/LH/HL/LL)
- Структурного тренда

Новый модуль — полноценный structural analysis, фундамент для BOS/CHoCH.

---

## 4. Модуль 2: Structure (BOS / CHoCH) — пульс тренда

**Файл:** `core/smc/structure.py`

### Что это

BOS и CHoCH — два ключевых события в SMC:

**BOS (Break of Structure)** = пробой в НАПРАВЛЕНИИ текущего тренда.
Цена делает новый HH (в бычьем) или новый LL (в медвежьем) — тренд подтверждён.

**CHoCH (Change of Character)** = пробой ПРОТИВ текущего тренда.
Первый сигнал что тренд может разворачиваться.

### Визуально

```
БЫЧИЙ ТРЕНД:
          HH ←── BULLISH BOS (пробой предыдущего High = тренд продолжается)
         / \
   HH   /   \
  / \  /     ↓
 /   \/      LL ←── BEARISH CHoCH! (пробой Low ВНИЗ = первый сигнал разворота)
/    HL

МЕДВЕЖИЙ ТРЕНД:
\    LH
 \   /\      HH ←── BULLISH CHoCH! (пробой High ВВЕРХ = возможен разворот)
  \ /  \     ↑
   LL   \   /
         \ /
          LL ←── BEARISH BOS (пробой Low = медвежий тренд продолжается)
```

### Логика классификации

```
Текущий тренд     Что пробито         Тип          Значение
─────────────     ────────────         ────         ────────
BULLISH           Swing High вверх     BULLISH_BOS  Тренд продолжается
BULLISH           Swing Low вниз       BEARISH_CHoCH  ⚠️ РАЗВОРОТ!
BEARISH           Swing Low вниз       BEARISH_BOS  Тренд продолжается
BEARISH           Swing High вверх     BULLISH_CHoCH  ⚠️ РАЗВОРОТ!
NEUTRAL           Swing High вверх     BULLISH_CHoCH  Начало нового тренда?
NEUTRAL           Swing Low вниз       BEARISH_CHoCH  Начало нового тренда?
```

### Multi-bar confirmation

По умолчанию `use_close=True`: пробой считается только если **тело свечи** (close) закрылось за уровнем. Фитиль (high/low) может пробить уровень, но если close вернулся — это ложный пробой.

```
  │    ┌──┐ ← Фитиль пробил Swing High, но close ниже = НЕ пробой
  │    │  │
──│────└──┘── Swing High уровень
  │
  │    ┌──┐
  │    │  │
──│────│──│── Swing High уровень
  │    └──┘ ← Close ВЫШЕ уровня = подтверждённый BOS ✅
```

### Strength (сила пробоя)

| Фактор | Очки |
|--------|------|
| BOS (базовый) | 70 |
| CHoCH (базовый) | 55 (менее надёжен, может быть ложным) |
| Close confirmation | +10 |
| Уровень держался ≥20 баров | +10 |
| Уровень держался ≥10 баров | +5 |
| **Максимум** | **100** |

Почему CHoCH слабее: BOS подтверждает существующий тренд (momentum), а CHoCH — только первый намёк на разворот. Многие CHoCH оказываются ложными.

### CHoCH × Контекст волн Эллиотта (матрица n_down)

CHoCH **не является надёжным сигналом разворота сам по себе** — его интерпретация критически зависит от волнового контекста, измеряемого через `elliott_n_down` (число последовательных снижающихся swing highs на HTF).

#### Ключевая матрица (эмпирика W20, n=154, post-14.05.2026)

| Условие | WR | avgR | Интерпретация |
|---|---|---|---|
| n_down < 3 + BullishChoCH | 50% | +0.019 | Откат волны 2/4 → SHORT после него ОК |
| n_down ≥ 3 + BullishChoCH | **0%** | **-2.181** | Конец 5 волн → ABC коррекция → **STOP SHORT** |

#### Логика по волновой теории

```
n_down = 1-2:  Рынок в волне 1-2 (начало движения)
  ChoCH бычий = коррекционный откат (Wave 2 вверх)
  → Ложный разворот, SHORT после отката в OTE = ОК

n_down ≥ 3:   Рынок завершил 5-волновой импульс
  ChoCH бычий = структурный слом HTF
  → Начало ABC коррекции ВВЕРХ → STOP SHORT!
```

#### Правило: ВСЕГДА проверять n_down перед интерпретацией CHoCH

1. `n_down < 3` + BullishChoCH → **коррекция волны 2/4**, SHORT ещё возможен с конфлюенцией (AbovePP + OTE + WT OB)
2. `n_down ≥ 3` + BullishChoCH → **конец 5-волнового импульса**, SHORT **запрещён**
3. При входе в SHORT: убедиться что `n_down ≤ 3` (волна 3, не 5)

> **Связь с OTE:** при n_down=1 и цена в OTE [0.618–0.786] → оптимальный SHORT вход (Wave 2 retracement в OTE = Triple Confluence).
> **Связь с Pivot Points:** AbovePP + n_down≥3 + BullishChoCH = двойной стоп-сигнал для SHORT.

### Breaker Blocks

После пробоя, пробитый уровень часто становится поддержкой (для бычьего BOS) или сопротивлением (для медвежьего).

```
   Пробитый Swing High (100.50)
   ──────────────────────────────
          │    └── Ретест (цена вернулась к 100.50 = поддержка)
          │        └── Отскок вверх ✅
```

### Active Support / Resistance

Из всех свингов вычисляются непробитые уровни:
- `active_resistance` = ближайший непробитый Swing High **выше** текущей цены
- `active_support` = ближайший непробитый Swing Low **ниже** текущей цены

Это реальные структурные уровни, не индикаторные линии.

### Код использования

```python
from core.smc.structure import detect_structure

result = detect_structure(df_15m, swing_period=5)

# Тренд
print(result.trend)              # BULLISH

# Последний пробой
if result.last_break:
    brk = result.last_break
    print(brk.break_type)        # BULLISH_BOS
    print(brk.level)             # 1.2345 (пробитый уровень)
    print(brk.strength)          # 80
    print(brk.confirmed)         # True (close за уровнем)
    print(brk.is_choch)          # False (это BOS, не CHoCH)

# Уровни
print(result.active_support)     # 1.2100
print(result.active_resistance)  # 1.2500
```

---

## 5. Модуль 3: FVG — следы институционалов

**Файл:** `core/smc/fvg.py`

### Что это

**Fair Value Gap** — ценовой дисбаланс, "дыра" в ценовом действии. Когда институционал двигает цену мощным импульсом, он оставляет gap — зону где не было ни одной сделки.

Рынок "не любит" незаполненные зоны и стремится вернуть цену обратно.

### Визуально

```
Бычий FVG (Bull):

Бар i:     ┌──┐
           │  │  low[i] = 105
           └──┘
                 ← GAP (105 - 102 = 3 пункта FVG)
Бар i-1:   ┌──┐
           │  │  (импульсная свеча)
           └──┘
Бар i-2:   ┌──┐
           │  │  high[i-2] = 102
           └──┘

Условие Bull FVG:  low[i] > high[i-2]
Зона: [102, 105] — цена вероятно вернётся сюда
```

```
Медвежий FVG (Bear):

Бар i-2:   ┌──┐
           │  │  low[i-2] = 108
           └──┘
                 ← GAP (108 - 105 = 3 пункта FVG)
Бар i-1:   ┌──┐
           │  │  (импульсная свеча вниз)
           └──┘
Бар i:     ┌──┐
           │  │  high[i] = 105
           └──┘

Условие Bear FVG:  high[i] < low[i-2]
Зона: [105, 108] — цена вероятно вернётся сюда
```

### Mitigation (заполнение)

FVG отслеживается после создания. Когда цена возвращается в зону:

```
0%   — нетронут (цена ещё не дошла до зоны)
50%  — частично заполнен (цена зашла в верхнюю половину)
100% — полностью mitigated (цена прошла через всю зону)
```

**Активный** FVG (< 100% mitigation) = зона куда цена может вернуться.
**Mitigated** FVG (100%) = зона отработана, больше не актуальна.

### Объединение consecutive FVG

Два бычьих FVG подряд (≤3 бара между ними), которые перекрываются → расширенная зона.

```
FVG1: [100, 103]
FVG2: [102, 106]  (перекрывается с FVG1)
→ Merged: [100, 106]  (одна большая зона)
```

### Фильтр по размеру

`min_size_pct=0.05` — FVG меньше 0.05% от цены = шум, игнорируем.
На BTC ($65,000) это $32.50. На альтах с ценой $0.10 это $0.00005.

### Код использования

```python
from core.smc.fvg import detect_fvg

analysis = detect_fvg(df_15m, min_size_pct=0.05)

print(len(analysis.active_bull))   # 2 незаполненных бычьих FVG
print(len(analysis.active_bear))   # 0 незаполненных медвежьих

if analysis.nearest_bull:
    fvg = analysis.nearest_bull
    print(f"Ближайший бычий FVG: {fvg.bottom:.4f}–{fvg.top:.4f}")
    print(f"Midpoint: {fvg.midpoint:.4f}")
    print(f"Заполнен на {fvg.mitigation_pct:.0%}")
```

---

## 6. Модуль 4: Order Blocks — где сидят деньги

**Файл:** `core/smc/order_blocks.py`

### Что это

**Order Block** — последняя **противотрендовая** свеча перед импульсным движением (BOS/CHoCH).

Идея: институционал не может исполнить весь объём за раз. Он размещает ордера в зоне — и эта зона видна как последняя свеча против тренда перед импульсом.

### Визуально

```
Бычий Order Block:

                 ┌──┐
                 │  │  BOS! (пробой Swing High)
                 │  │
            ┌──┐ └──┘
            │  │
       ┌──┐ └──┘
       │  │
  ┌────┐──┘
  │ OB │ ← Последняя МЕДВЕЖЬЯ свеча (close < open) перед импульсом
  └────┘   Зона: [low, high] этой свечи = зона институциональных покупок
       │
       │   При откате цена вернётся к этой зоне → LONG вход
```

```
Медвежий Order Block:

  ┌────┐ ← Последняя БЫЧЬЯ свеча (close > open) перед медвежьим BOS
  │ OB │   Зона: [low, high] = зона институциональных продаж
  └────┘
       ┌──┐
       │  │
       └──┘ ┌──┐
            │  │
            └──┘ BOS вниз!
```

### Почему противотрендовая свеча?

Институционал закупается **против движения**. Перед бычьим импульсом он покупает "на красной свече" (когда ритейл продаёт). Это его зона входа.

### Volume Ratio

OB с аномальным объёмом — сильнее. Институционал исполняет большой объём в этой свече.

```
Volume OB свечи / MA(20) = volume_ratio

ratio ≥ 2.0 → очень сильный OB (+15 к strength)
ratio ≥ 1.5 → сильный OB (+10)
ratio < 1.5 → обычный OB (0)
```

### Strength (сила OB)

| Фактор | Очки | Почему |
|--------|------|--------|
| Базовый OB | 60 | — |
| CHoCH-based (из разворота) | +15 | Разворот = новая агрессия институционала |
| Volume ≥ 2.0× MA | +15 | Аномальный объём = крупный игрок |
| Volume ≥ 1.5× MA | +10 | Повышенный объём |
| FVG overlap | +10 | Два подтверждения на одном уровне |
| **Максимум** | **100** | |

### Mitigation

OB "отработан" (mitigated) когда цена полностью проходит через зону:
- Bullish OB: цена ушла НИЖЕ `bottom` зоны → OB не сработал
- Bearish OB: цена ушла ВЫШЕ `top` зоны → OB не сработал

### Суперсетап: OB + FVG

Когда Order Block и FVG перекрываются на одном уровне — это **двойное подтверждение**:

```
Order Block: [100.50, 101.20]
Bull FVG:    [100.80, 101.50]
→ Overlap! Суперсетап на уровне ~101.00

Логика: институционал разместил ордера (OB)
        + рынок оставил дисбаланс (FVG)
        = очень высокая вероятность отскока от зоны
```

В нашем боте суперсетап даёт **+0.07** к confidence (самый большой SMC-бонус).

### Код использования

```python
from core.smc.structure import detect_structure
from core.smc.order_blocks import detect_order_blocks

struct = detect_structure(df_15m)
obs = detect_order_blocks(df_15m, struct)

for ob in obs.active_bull:
    print(f"Bullish OB: {ob.bottom:.4f}–{ob.top:.4f}")
    print(f"  Strength: {ob.strength}")
    print(f"  Volume: {ob.volume_ratio:.1f}x")
    print(f"  FVG overlap: {ob.has_fvg_overlap}")
    print(f"  CHoCH-based: {ob.origin_break.is_choch}")
```

---

## 7. Модуль 5: Liquidity — где стоят стопы

**Файл:** `core/smc/liquidity.py`

### Что это

**Ликвидность** — скопление стоп-ордеров на определённых уровнях.

Ритейл-трейдеры ставят стопы предсказуемо:
- **Buy-side liquidity** — стопы шортистов **НАД** Swing Highs
- **Sell-side liquidity** — стопы лонгистов **ПОД** Swing Lows

Институционалы "охотятся" за этой ликвидностью — двигают цену к стопам, собирают объём и разворачиваются.

### Визуально

```
═══ Buy-side liquidity ═══  ← Стопы шортистов (stop-buy ордера)
    SH    SH    SH          ← Три Swing High на одном уровне = сильный кластер
   / \  / \   / \
  /   \/   \ /   \
 /    SL    SL    \
══ Sell-side liquidity ══   ← Стопы лонгистов (stop-sell ордера)
```

### Кластеризация

Свинги группируются в кластеры по близости уровней:

```
Swing Highs: 100.50, 100.65, 100.42
tolerance = 0.3% от уровня ≈ 0.30

|100.50 - 100.65| = 0.15 < 0.30 → один кластер
|100.42 - 100.50| = 0.08 < 0.30 → тоже туда

→ Кластер: уровень = 100.52, swing_count = 3
```

### Sweep (сбор ликвидности)

Когда цена **пробивает** зону ликвидности — стопы срабатывают, ликвидность "собрана":

```
═══ Buy-side liquidity (100.50) ═══
                    │
        ┌──┐       │
        │  │←──── Sweep! High > 100.50
        └──┘       │
                    │    → swept = True
                    │    → Ликвидность собрана
                    │    → Разворот вниз вероятен
```

После sweep зона уже не актуальна — новые стопы ещё не накопились.

### Strength

```
strength = 30 + swing_count × 20

1 свинг  → 50  (слабый)
2 свинга → 70  (средний)
3 свинга → 90  (сильный)
4+ свинга → 100 (максимум)

Если swept: strength -= 40 (минимум 10)
```

### Торговое применение

**TP по ликвидности:** цена стремится к ликвидности. Ближайшая buy-side liquidity = потенциальный TP для LONG.

**Разворот после sweep:** swept sell-side liquidity = бычий сигнал (стопы лонгистов собраны → институционал развернёт вверх).

### Код использования

```python
from core.smc.swing_points import detect_swing_points
from core.smc.liquidity import detect_liquidity

swings = detect_swing_points(df_15m)
liq = detect_liquidity(df_15m, swings)

for zone in liq.buy_side:
    print(f"Buy-side: {zone.level:.4f} (n={zone.swing_count}, str={zone.strength})")
    if zone.swept:
        print(f"  SWEPT at bar {zone.sweep_index}")

# Ближайшие зоны
if liq.nearest_buy:
    print(f"TP target: {liq.nearest_buy.level:.4f}")
if liq.nearest_sell:
    print(f"Support zone: {liq.nearest_sell.level:.4f}")
```

---

## 8. Модуль 6: Fibonacci OTE — золотая зона

**Файл:** `core/smc/fibonacci.py`

### Что это

**OTE (Optimal Trade Entry)** — зона 0.618–0.786 по Fibonacci от последнего импульса.

Статистически цена чаще всего откатывается в эту зону перед продолжением тренда. Вход здесь даёт оптимальное соотношение risk/reward.

### Как рассчитывается

**Бычий импульс (после BOS вверх):**

```
High = пробитый Swing High (например 110)
Low  = предыдущий Swing Low  (например 100)
Diff = 110 - 100 = 10

Уровни:
  0.236 → 110 - 10×0.236 = 107.64
  0.382 → 110 - 10×0.382 = 106.18
  0.500 → 110 - 10×0.500 = 105.00
  ─── OTE зона ───
  0.618 → 110 - 10×0.618 = 103.82  ← OTE top
  0.786 → 110 - 10×0.786 = 102.14  ← OTE bottom
  ────────────────
  0.886 → 110 - 10×0.886 = 101.14

→ Цена в [102.14, 103.82] = оптимальный LONG
```

**Медвежий импульс (после BOS вниз):**

```
High = предыдущий Swing High (100)
Low  = пробитый Swing Low (90)
Diff = 100 - 90 = 10

OTE bottom = 90 + 10×0.618 = 96.18
OTE top    = 90 + 10×0.786 = 97.86

→ Цена в [96.18, 97.86] = оптимальный SHORT
```

### Почему 0.618–0.786?

Fibonacci 0.618 (золотое сечение) — математическое соотношение, которое часто встречается в рыночных откатах. Диапазон 0.618–0.786 — "sweet spot":
- Откат достаточно глубокий для хорошего R:R
- Но не настолько глубокий чтобы сигнализировать о развороте
- Институционалы часто размещают ордера именно здесь

### Связь с другими модулями

OTE зона часто совпадает с Order Block — это усиливает зону:

```
OTE:           [102.14, 103.82]
Order Block:   [102.50, 103.20]  ← внутри OTE!
→ Тройное подтверждение: OTE + OB + FVG (если есть)
```

### Код использования

```python
from core.smc.structure import detect_structure
from core.smc.fibonacci import detect_fibonacci

struct = detect_structure(df_15m)
fib = detect_fibonacci(df_15m, struct)

if fib.active_ote:
    ote = fib.active_ote
    print(f"ЦЕНА В OTE! {ote.ote_bottom:.4f}–{ote.ote_top:.4f}")
    print(f"Направление: {ote.direction}")
    print(f"Импульс: {ote.impulse_low:.4f}–{ote.impulse_high:.4f}")

    for lvl in ote.levels:
        print(f"  Fib {lvl.label}: {lvl.price:.4f}")
```

### OTE как зона коррекционной волны Эллиотта

OTE `[0.618–0.786]` математически совпадает с зоной отката **Волны 2** по теории Эллиотта (Волна 2 откатывает 61.8–78.6% Волны 1 = ТОЧНО OTE диапазон).

#### Соответствие Эллиотт ↔ OTE

| Волна Эллиотта | Откат | OTE применимость | Вход |
|---|---|---|---|
| Волна 2 (после Волны 1) | 61.8–78.6% | ✅ Точное совпадение с OTE | Оптимальный |
| Волна 4 (после Волны 3) | ~38.2% | ⚠️ Мельче OTE | Возможен, но не оптимальный |

#### Лучшие точки входа через OTE + Elliott

```
SHORT (n_down=1 — первая снижающаяся swing high):
  Волна 1: импульс вниз
  Волна 2: откат вверх → цена входит в OTE [0.618–0.786] от Волны 1
  Вход: SHORT в OTE зоне = оптимальная точка Wave 2 retracement

LONG (n_up=1 — первая растущая swing low):
  Волна 1: импульс вверх
  Волна 2: откат вниз → цена входит в OTE [0.618–0.786] от Волны 1
  Вход: LONG в OTE зоне
```

#### Triple Confluence — сигнал наивысшего качества

```
OTE [0.618–0.786]          ← зона входа (где)
+ OB/FVG на том же уровне  ← институциональный след (почему)
+ n_down/n_up = 1-2        ← волновой контекст (когда)
= Triple Confluence → максимальная WR
```

#### Связи между концепциями

- **OTE ↔ Pivot Points:** R2 ≈ 0.618 = OTE уровень вверх; S2 ≈ 0.618 = OTE уровень вниз
- **OTE ↔ WaveTrend:** WT OB (>+60) + цена в OTE SHORT = подтверждение истощения в зоне
- **OTE ↔ CHoCH:** n_down<3 + ChoCH бычий + OTE → SHORT с конфлюенцией (см. CHoCH × n_down выше)
- **OTE ↔ Divergence:** divergence SHORT в OTE = самодостаточный сигнал (avgR=+0.922 WR=56.5% независимо от PP/Elliott)

---

## 9. SMCContext — единый объект

**Файл:** `core/smc/models.py`

### Единая точка входа

```python
from core.smc import analyze_smc

ctx = analyze_smc(df_15m, swing_period=5)
print(ctx.summary())
# SMC(trend=BULLISH, last=BULLISH_BOS, fvg_bull=2, ob_bull=1, IN_OTE, BULL_SUPER)
```

Один вызов → полный анализ всех 6 модулей.

### Граф вызовов

```
analyze_smc(df)
  ├── detect_structure(df)       ← включает detect_swing_points()
  ├── detect_fvg(df)             ← независимый
  ├── detect_order_blocks(df, structure)   ← зависит от structure
  ├── detect_liquidity(df, swing_analysis) ← зависит от swing_points
  ├── detect_fibonacci(df, structure)      ← зависит от structure
  └── _mark_fvg_overlap(order_blocks, fvg) ← помечает суперсетапы
```

### Ключевые derived properties

| Свойство | Что значит |
|----------|-----------|
| `ctx.trend` | BULLISH / BEARISH / NEUTRAL |
| `ctx.last_break` | Последний BOS/CHoCH (или None) |
| `ctx.has_choch` | Был ли разворот? (среди ВСЕХ пробоев) |
| `ctx.has_bos` | Было ли подтверждение тренда? |
| `ctx.active_resistance` | Ближайший Swing High выше цены |
| `ctx.active_support` | Ближайший Swing Low ниже цены |
| `ctx.nearest_bull_ob` | Ближайший бычий Order Block |
| `ctx.nearest_bear_ob` | Ближайший медвежий Order Block |
| `ctx.nearest_bull_fvg` | Ближайший бычий FVG |
| `ctx.price_in_ote` | Цена в OTE зоне? (bool) |
| `ctx.has_bullish_ob_with_fvg` | **Суперсетап**: бычий OB + FVG перекрываются |
| `ctx.has_bearish_ob_with_fvg` | **Суперсетап**: медвежий OB + FVG |
| `ctx.nearest_buy_liquidity` | Ближайшая buy-side ликвидность |
| `ctx.nearest_sell_liquidity` | Ближайшая sell-side ликвидность |

### to_features() — для ML

19 фичей с префиксом `smc_`:

```python
features = ctx.to_features()
# {
#     "smc_trend": "BULLISH",
#     "smc_has_choch": False,
#     "smc_has_bos": True,
#     "smc_last_break_type": "BULLISH_BOS",
#     "smc_last_break_strength": 80,
#     "smc_active_resistance": 1.2345,
#     "smc_active_support": 1.1890,
#     "smc_active_bull_fvg_count": 2,
#     "smc_active_bear_fvg_count": 0,
#     "smc_active_bull_ob_count": 1,
#     "smc_active_bear_ob_count": 0,
#     "smc_bull_ob_fvg_overlap": True,   ← суперсетап
#     "smc_bear_ob_fvg_overlap": False,
#     "smc_price_in_ote": True,
#     "smc_ote_direction": "LONG",
#     "smc_buy_liq_count": 1,
#     "smc_sell_liq_count": 2,
#     "smc_nearest_buy_liq_strength": 70,
#     "smc_nearest_sell_liq_strength": 50,
# }
```

---

## 10. Как SMC интегрирован в бот

### Точки интеграции

```
analyze_symbol()                              ← trading_intelligence.py
  ├── _collect_all_signals()                  ← собирает сигналы
  ├── analyze_smc(df_entry) ─── NEW ────────  ← вызов SMC после OHLCV
  ├── market_context.smc_context = smc_ctx    ← сохраняем в контексте
  ├── strategies.analyze(signals, context)    ← стратегии читают SMC
  │   ├── ReversalStrategy  ← SMC бонусы к confidence
  │   └── TrendFollowing    ← SMC бонусы к confidence
  ├── recommendation_generator.calculate_levels()
  │   └── SL по SMC Order Block               ← приоритет 2.5
  └── recommendation.metadata["smc_context"]   ← для features_json
          └── trade_simulator.register_trade()
              └── features_json += 19 smc_ фичей ← для ML
```

### 1. MarketContext → `smc_context`

```python
# core/signal_models.py
@dataclass
class MarketContext:
    ...
    smc_context: Optional['SMCContext'] = None  # ARCH-17
```

### 2. Вызов в analyze_symbol()

```python
# core/trading_intelligence.py, в analyze_symbol() после OHLCV загрузки:
from core.smc import analyze_smc
df_entry = await self.data_collector.get_ohlcv(symbol, "15m", limit=100)
if df_entry is not None and len(df_entry) >= 30:
    smc_context = analyze_smc(df_entry)
    market_context.smc_context = smc_context
```

### 3. Бонусы в стратегиях

**ReversalStrategy** (разворотные сигналы):

| Условие SMC | Бонус к confidence | Почему |
|-------------|-------------------|--------|
| CHoCH обнаружен | +0.05 | Структурный разворот подтверждает сигнал |
| OB + FVG суперсетап | +0.07 | Двойное подтверждение зоны входа |
| Цена в OTE | +0.04 | Оптимальный уровень отката |

**TrendFollowingStrategy** (трендовые сигналы):

| Условие SMC | Бонус к confidence | Почему |
|-------------|-------------------|--------|
| BOS обнаружен | +0.04 | Структурное подтверждение тренда |
| Цена в OTE | +0.05 | Оптимальный откат внутри тренда |
| OB + FVG суперсетап | +0.06 | Зона институционального интереса |

### 4. SL по Order Block

В `recommendation_generator.py`, приоритет 2.5 (между FVG из сигналов и TSL):

```
SL приоритеты:
  0.   Swing LOW/HIGH
  1.   S1/R1 (пивот)
  2.   FVG (из сигналов)
  2.5  SMC Order Block ← NEW
  3.   TSL-линия
  4.   ATR / volatility / fallback 2%
```

LONG: SL за нижней границей ближайшего бычьего OB + buffer 0.3%
SHORT: SL за верхней границей ближайшего медвежьего OB + buffer 0.3%

### 5. Features в БД

Все 19 `smc_*` фичей сохраняются в `features_json` таблицы `simulated_trades`.
Используются для ML обучения (OutcomePredictor, gradient boosting).

---

## 11. Торговые сценарии и суперсетапы

### Сценарий 1: Суперсетап (OB + FVG + OTE)

**Самый сильный вход.** Три подтверждения на одном уровне.

```
Условия:
  ✅ SMC trend = BULLISH (HH + HL)
  ✅ Последний break = BULLISH_BOS
  ✅ Цена откатилась в OTE зону (0.618–0.786)
  ✅ В зоне OTE есть бычий Order Block
  ✅ В зоне OTE есть бычий FVG (OB + FVG overlap = суперсетап)

Вход: LONG при WT cross в зоне OB
SL:   Под bottom Order Block (+ 0.3% buffer)
TP:   Ближайшая buy-side liquidity

Бонус confidence: +0.07 (OB+FVG) + +0.04 (OTE) = +0.11
```

### Сценарий 2: CHoCH + OB (ранний разворот)

**Агрессивный контртрендовый вход.**

```
Условия:
  ✅ SMC trend = BEARISH
  ✅ Обнаружен BULLISH_CHoCH (первый пробой High вверх)
  ✅ Есть бычий Order Block на уровне пробоя
  ✅ WT дал cross в OS

Вход: LONG
SL:   Под CHoCH уровнем
TP:   Active resistance (непробитый Swing High)

Бонус confidence: +0.05 (CHoCH) + +0.07 (если есть FVG overlap)
```

### Сценарий 3: BOS + OTE (трендовое продолжение)

**Консервативный вход по тренду.**

```
Условия:
  ✅ SMC trend = BULLISH
  ✅ Свежий BULLISH_BOS
  ✅ Цена откатилась в OTE зону
  ✅ MTF alignment > 60%

Вход: LONG на откате
SL:   Под OTE bottom
TP:   BOS level + ATR

Бонус confidence: +0.04 (BOS) + +0.05 (OTE) = +0.09
```

### Сценарий 4: Liquidity sweep + разворот

**Контртрендовый после сбора стопов.**

```
Условия:
  ✅ Sell-side liquidity swept (стопы лонгистов собраны)
  ✅ CHoCH вверх после sweep
  ✅ Order Block или FVG на уровне sweep

Вход: LONG после sweep
SL:   Под sweep level
TP:   Buy-side liquidity (цена пойдёт собирать стопы шортистов)

Логика: институционал собрал ликвидность снизу → теперь гонит цену вверх
```

---

## 12. ML-фичи и обучение

### 19 фичей в features_json

Каждая сделка сохраняет полный SMC-контекст. После накопления 100+ сделок ML модель (OutcomePredictor) начнёт находить паттерны:

**Ожидаемые ML insights:**
- `smc_bull_ob_fvg_overlap = True` → выше P(TP)
- `smc_price_in_ote = True` → выше P(TP) для трендовых
- `smc_has_choch = True` + `smc_trend != direction` → может снизить P(TP) (ложный CHoCH)
- `smc_last_break_strength > 75` → выше P(TP)
- `smc_buy_liq_count > 0` → хороший TP target, выше captured_R

### Как данные используются

```
Сделка → features_json (19 smc_ фичей)
                    ↓
        OutcomePredictor.fit()    (RandomForest)
                    ↓
        P(win) = predict(features) → confidence blend
                    ↓
        Будущие сделки: confidence × P(win) → лучшая фильтрация
```

---

## 13. Что НЕ делает SMC Layer

1. **Не генерирует сигналы.** SMCContext — это КОНТЕКСТ, не сигнал. Он обогащает существующие сигналы (WT, divergence, pivot reversal) контекстом.

2. **Не заменяет MTFContext.** MTF отвечает за направление (какой тренд на 7 ТФ). SMC отвечает за уровни (где входить). Вместе — полная картина.

3. **Не определяет timing.** SMC говорит "эта зона интересна", но не "входи прямо сейчас". Timing — за WT cross, дивергенцией или пивотом.

4. **Не работает на шумных данных.** Если `len(df) < 30` — возвращает пустой контекст. Нужно минимум 30 баров для надёжного анализа.

5. **Не гарантирует отскок от зоны.** OB и FVG повышают вероятность, но не дают 100%. Рынок может пройти через любую зону.

---

## 14. Тюнинг параметров

### analyze_smc() параметры

| Параметр | Дефолт | Что меняет |
|----------|--------|------------|
| `swing_period` | 5 | Больше = крупнее свинги, меньше шума, но медленнее реакция |
| `fvg_min_size_pct` | 0.05 | Больше = только крупные FVG, меньше = больше FVG (включая шум) |
| `cluster_tolerance_pct` | 0.3 | Больше = больше свингов в кластере, шире зоны ликвидности |

### Когда менять

**Для интрадей (5m/15m):**
- `swing_period=3-5` (мелкие свинги, быстрая реакция)
- `fvg_min_size_pct=0.03` (мелкие FVG видны)

**Для свинг-трейдинга (1h/4h):**
- `swing_period=7-10` (только значимые свинги)
- `fvg_min_size_pct=0.1` (только крупные дисбалансы)

### Мониторинг эффективности

После запуска бота с SMC — следить за:

```sql
-- Сделки с SMC суперсетапом vs без
SELECT
  CASE WHEN json_extract(features_json, '$.smc_bull_ob_fvg_overlap') = 1
       OR json_extract(features_json, '$.smc_bear_ob_fvg_overlap') = 1
  THEN 'SUPER' ELSE 'NORMAL' END as setup,
  COUNT(*) as cnt,
  AVG(CASE WHEN status='TP' THEN 1.0 ELSE 0.0 END) as wr,
  AVG(R_multiple) as avg_r
FROM simulated_trades
WHERE features_json IS NOT NULL
  AND json_extract(features_json, '$.smc_trend') IS NOT NULL
GROUP BY setup;

-- Сделки в OTE vs не в OTE
SELECT
  json_extract(features_json, '$.smc_price_in_ote') as in_ote,
  COUNT(*) as cnt,
  AVG(CASE WHEN status='TP' THEN 1.0 ELSE 0.0 END) as wr
FROM simulated_trades
WHERE features_json IS NOT NULL
GROUP BY in_ote;
```

---

## Тесты

```bash
python -m pytest tests/unit/test_smc_layer.py -v
# 44 tests: swing(10) + fvg(7) + structure(6) + ob(4) + liquidity(5) + fib(4) + context(8)
```

---

## Файловая карта

```
core/smc/
  __init__.py           ← экспорт: analyze_smc(), SMCContext
  models.py             ← SMCContext dataclass + analyze_smc() + _mark_fvg_overlap()
  swing_points.py       ← detect_swing_points() → SwingAnalysis
  structure.py          ← detect_structure() → StructureAnalysis (BOS/CHoCH)
  fvg.py                ← detect_fvg() → FVGAnalysis
  order_blocks.py       ← detect_order_blocks() → OBAnalysis
  liquidity.py          ← detect_liquidity() → LiquidityAnalysis
  fibonacci.py          ← detect_fibonacci() → FibAnalysis

Интеграция:
  core/signal_models.py           ← MarketContext.smc_context
  core/trading_intelligence.py    ← вызов analyze_smc() + metadata
  core/trade_simulator.py         ← smc_ фичи в features_json
  core/intelligence/recommendation_generator.py ← SL по Order Block
  strategies/built_in/reversal_strategy.py      ← SMC confidence бонусы
  strategies/built_in/trend_strategy.py         ← SMC confidence бонусы

Тесты:
  tests/unit/test_smc_layer.py    ← 44 теста

Документация:
  docs/SMC_LAYER.md               ← техническая документация
  docs/SMC_GUIDE.md               ← этот файл (полный гайд)
```
