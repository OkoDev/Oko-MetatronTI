# CONCEPT MAP — Единая система концепций для MTF торговли

> Создано: 28.05.2026 | Oko MTF Bot | Консенсус рой 6 LLM (5/5)

Эта карта описывает 6 концепций и их роли в построении сигналов на всех таймфреймах.
Цель: иметь возможность собирать **новые** точные и прибыльные стратегии на основе связей между концепциями.

---

## 6 Концепций и их роли

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MTF TRADING FRAMEWORK                            │
│                                                                     │
│  HTF (1D/4h)          MTF (1h)              LTF (15m)              │
│  ─────────────────   ──────────────────    ──────────────────      │
│  1. Elliott Waves     3. Pivot Points       2. Fibonacci/OTE       │
│     n_down/n_up          PP/S1/R1/S2/R2       [0.618-0.786]       │
│     ФАЗА рынка           ПРОСТРАНСТВО         ЗОНА ВХОДА           │
│                                                                     │
│  4. WaveTrend         4. WaveTrend           5. Divergence         │
│     OS/OB 4h             OS/OB 1h              Regular/Hidden      │
│     ИСТОЩЕНИЕ            ПОДТВЕРЖДЕНИЕ         РАЗВОРОТ/ПРОДОЛЖ.   │
│                                                                     │
│  6. CHoCH/BOS                                                       │
│     Структурный слом                                                │
│     НАПРАВЛЕНИЕ                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Концепция 1: Elliott Waves (n_down / n_up)

**Роль:** определяет **ФАЗУ** рынка (в какой волне находимся)

**Реализация в боте:**
- `n_down` = число consecutive снижающихся swing highs на HTF = прокси нисходящей волны
- `n_up` = число consecutive растущих swing lows на HTF = прокси восходящей волны
- Источник: `find_swing_highs()` / `find_swing_lows()` из `core/indicators.py`

**Что говорит каждое значение:**
```
n_down = 1:   Волна 1 вниз — начало тренда
n_down = 2:   Волна 3 вниз — набирает силу → ЛУЧШИЙ SHORT
n_down = 3:   Волна 3/5 — всё ещё ОК для SHORT
n_down = 4+:  Волна 5 — конец импульса → STOP SHORT (WR=10%)

+ BullChoCH:  n_down<3 = откат Wave 2, SHORT после ОК
              n_down≥3 = конец 5 волн, STOP SHORT (avgR=-2.181)
```

**Данные (n=3587, post-14.05.2026):**
| n_down | Signal | avgR | WR |
|---|---|---|---|
| 2-3 | atr_change SHORT | +0.194 | 46% |
| 4+ | atr_change SHORT | **-1.814** | **10%** |
| 4+ | confluence SHORT | **-2.701** | — |

---

## Концепция 2: Fibonacci / OTE [0.618–0.786]

**Роль:** определяет **ЗОНУ ВХОДА** (где именно войти)

**Реализация в боте:**
- OTE = Optimal Trade Entry зона [0.618–0.786] от последнего импульса
- Файл: `core/smc/fibonacci.py`, функция `detect_fibonacci()`
- Текущий диапазон в боте: [0.705–0.786] (консервативный)

**Математическая связь Elliott ↔ OTE:**
```
Волна 2 откатывает 61.8-78.6% Волны 1 = ТОЧНО OTE диапазон
Волна 4 откатывает 38.2% Волны 3 = мельче OTE (менее оптимальна)

→ OTE = математическое проявление Wave 2 retracement
→ Лучший SHORT: OTE при n_down=1 (Wave 2 retracement вверх)
→ Лучший LONG:  OTE при n_up=1 (Wave 2 retracement вниз)
```

**Связь с Pivot Points:**
```
R2 = pp + (H-L) ≈ 0.618 Fib выше PP = OTE уровень вверх
S2 = pp - (H-L) ≈ 0.618 Fib ниже PP = OTE уровень вниз
```

---

## Концепция 3: Pivot Points (PP/S1/R1/S2/R2/S3/R3)

**Роль:** определяет **ПРОСТРАНСТВО ДЛЯ ДВИЖЕНИЯ** (куда может дойти цена)

**Реализация в боте:**
- `core/pivots/` — period-based пивоты (1M/1W/1D UTC)
- Публикует в шину: `pivot_snap`

**Формулы (НЕ МЕНЯТЬ):**
```
PP  = (High + Low + Close) / 3
R1  = pp*1.997 - Low     ≈ 0.382 Fib выше PP
R2  = pp + (H-L)         ≈ 0.618 Fib = OTE зона вверх
R3  = R1 + (H-L)         ≈ 1.0 расширение вверх (Волна 3 LONG цель)
S1  = pp*2.003 - High    ≈ 0.382 Fib ниже PP
S2  = pp - (H-L)         ≈ 0.618 Fib = OTE зона вниз
S3  = S1 - (H-L)         ≈ 1.0 расширение вниз (Волна 3 SHORT цель)
```

**Торговые правила (универсальные):**
- SHORT: входить AbovePP → цель S1 → расширение S2/S3
- LONG: входить BelowPP → цель R1 → расширение R2/R3
- ИСКЛЮЧЕНИЕ: liquidity_sweep LONG AbovePP WR=89% (инверсия!)

---

## Концепция 4: WaveTrend (WT1/WT2)

**Роль:** определяет **ИСТОЩЕНИЕ** (OS/OB) и **СИЛУ** (нейтральная зона)

**Реализация в боте:**
- `calculate_wt(df, n1=10, n2=21)` из `core/indicators.py`
- OB > +60, OS < -60
- Используется на всех TF: 4h (HTF истощение), 1h (MTF), 15m (LTF вход)

**Роли на разных TF:**
```
4h WT:  Определяет РЕЖИМ (OS/OB 4h = Reversal Mode)
1h WT:  Подтверждение зоны входа
15m WT: Точный вход (OS для LONG, OB для SHORT)
```

**Связь с ATRTrend/Supertrend:**
- `calculate_trend(df, atr_period=43, factor=1.0)` → trend/trendup/trenddown
- trendup на LTF подтверждает LONG; trenddown подтверждает SHORT
- ATRTrend = динамический SL (TSL следит за trendup/trenddown)

---

## Концепция 5: Divergence (Regular / Hidden)

**Роль:** определяет **РАЗВОРОТ** (regular) или **ПРОДОЛЖЕНИЕ** (hidden)

**Реализация в боте:**
- `core/indicators/divergence_detector.py`
- Regular divergence: цена делает новый экстремум, WT — нет = ослабление тренда
- Hidden divergence: WT делает новый экстремум, цена — нет = продолжение

**Ключевое свойство — самодостаточность:**
```
divergence SHORT: avgR=+0.922 WR=56.5% при ЛЮБЫХ условиях:
  AbovePP или BelowPP — одинаково
  n_down=0 или n_down=5 — одинаково
  BullChoCH или BearBOS — одинаково
  W19 или W20 — почти одинаково (+0.5 и +1.1)

Единственный период когда не работал: W19 = -0.827 (аномалия)
```

**Почему дивергенция независима:** она кодирует ослабление *momentum* (силы движения), что является фундаментальным сигналом который не зависит от структуры. Momentum может ослабнуть в любой фазе Elliott, в любой позиции PP.

---

## Концепция 6: CHoCH / BOS

**Роль:** определяет **СТРУКТУРНЫЙ СЛОМ** (смена тренда или его продолжение)

**Реализация в боте:**
- `core/smc/structure.py`, `detect_structure()`
- BOS (Break of Structure): пробой в направлении тренда = тренд продолжается
- CHoCH (Change of Character): пробой против тренда = первый сигнал разворота

**Сила сигнала:**
```
BOS:   70 баз. очков (надёжен — подтверждает тренд)
CHoCH: 55 баз. очков (менее надёжен — только первый намёк)
```

**CHoCH × Elliott (ключевая матрица):**
```
n_down < 3 + BullishChoCH:  WR=50%, avgR=+0.019 → откат Wave 2, SHORT ОК
n_down ≥ 3 + BullishChoCH:  WR=0%,  avgR=-2.181 → STOP SHORT (ABC коррекция)
```

---

## Взаимодействие концепций по TF уровням

### HTF (1D / 4h) — определяем ЗАПРЕТ или РАЗРЕШЕНИЕ

```
HTF анализ:
  Elliott n_down/n_up  → Фаза рынка (волна 2-3 = OK, волна 4-5 = осторожно)
  CHoCH / BOS          → Структурное направление
  WT OS/OB 4h          → Режим (Reversal Mode если WT 4h OS/OB + ADX↓ + CHoCH)

Решения:
  n_down = 2-3 + BearBOS + WT neutral = РАЗРЕШЕНИЕ SHORT
  n_down ≥ 4 + BullChoCH = ЗАПРЕТ SHORT
  n_up = 2-3 + BullBOS + WT neutral   = РАЗРЕШЕНИЕ LONG
```

### MTF (1h) — определяем ЗОНУ ВХОДА

```
MTF анализ:
  Pivot Points (PP/S1/R1) → Где находится цена в структуре дня
  WT OS/OB 1h             → Истощение на среднем TF

Решения:
  AbovePP + WT OB = зона SHORT входа
  BelowPP + WT OS = зона LONG входа
```

### LTF (15m) — ТОЧНЫЙ ВХОД

```
LTF анализ:
  OTE [0.618-0.786]  → Точная зона (где входить в пределах зоны)
  Divergence         → Подтверждение разворота
  WT OS/OB           → Локальное истощение

Вход:
  OTE + bull_div + WT OS  = LONG вход
  OTE + bear_div + WT OB  = SHORT вход
```

---

## Формулы сигналов

### Формула SHORT сигнала (высокая WR)

```
1. HTF Elliott: n_down = 2-3 (волна 3 вниз) + HTF price_dir = down
2. Daily PP: цена AbovePP (пространство к S1, S2)
3. HTF CHoCH: BearBOS (тренд продолжается)
   ИЛИ n_down < 3 + BullChoCH (откат Wave 2, SHORT после отката)
4. LTF: WT OB (>+60) ИЛИ нейтральный + ATRTrend = SHORT
5. Опционально: OTE [0.618-0.786] + bear_div для усиления

ЗАПРЕТЫ:
  n_down ≥ 4 (волна 5 = ловушка)
  n_down ≥ 3 + BullChoCH (конец 5 волн = STOP SHORT)
  BelowPP + SHORT (нет пространства вниз)
  S2/S3 при входе (глубокая поддержка)
```

### Формула LONG сигнала (высокая WR)

```
1. HTF Elliott: n_up = 2-3 (волна 3 вверх) + HTF price_dir = up
   ИЛИ n_down разворот (начало восстановления)
2. Daily PP: цена BelowPP (пространство к R1, R2)
3. HTF CHoCH: BearBOS (контр-тренд с поддержкой) — парадоксально но лучше!
4. LTF: WT OS (<-60) + OTE [0.618-0.786] от последнего LOW импульса
5. Опционально: bull_div на LTF для усиления

ЗАПРЕТЫ:
  n_up ≥ 4 (волна 5 LONG = ловушка)
  AbovePP (нет пространства вверх) — кроме liquidity_sweep!
  Reversal Mode из восходящего тренда (идёт SHORT ABC)
```

---

## Карта связей между концепциями

```
Elliott (n_down/n_up)
    │
    ├──→ OTE: Волна 2 = OTE диапазон [0.618-0.786] → оптимальный вход
    │
    ├──→ CHoCH: n_down≥3 + BullChoCH = STOP SHORT
    │
    └──→ Reversal Mode: n_down≥4 + WT OS + CHoCH = конец Волны 5

OTE [0.618-0.786]
    │
    ├──→ Pivot: R2/S2 ≈ 0.618 = те же зоны на дневном масштабе
    │
    └──→ WT: OB/OS в OTE = Triple Confluence (OTE + WT + Elliott)

Pivot Points (PP/S1/R1...)
    │
    ├──→ Universal rule: AbovePP SHORT / BelowPP LONG
    │
    └──→ ИСКЛЮЧЕНИЕ: liquidity_sweep LONG AbovePP = инверсия (WR=89%)

WaveTrend
    │
    ├──→ Reversal Mode: WT OS/OB 4h + ADX↓ + CHoCH = Reversal Mode
    │
    └──→ Divergence: WT дивергенция = самодостаточный сигнал

Divergence
    │
    └──→ Независим от: PP, Elliott, CHoCH → работает при ЛЮБЫХ условиях

CHoCH/BOS
    │
    ├──→ LONG: BearBOS + BelowPP = лучший LONG (arch104 WR=56%, avgR=+2.001)
    │
    └──→ SHORT: n_down≥3 + BullChoCH = STOP SHORT (WR=0%, avgR=-2.181)
```

---

## Практический пример — сборка нового сигнала

**Задача:** собрать HIGH WR SHORT сигнал на 4h/1h/15m

```
Шаг 1. Проверяем HTF (4h):
  - n_down = 2 ✅ (Волна 3 вниз)
  - BearBOS на 4h ✅
  - WT 4h нейтральный (не OS) ✅

Шаг 2. Проверяем MTF (1h):
  - Цена AbovePP дневного ✅ (пространство к S1)
  - WT 1h нейтральный или OB ✅

Шаг 3. Проверяем LTF (15m):
  - Цена в OTE [0.618-0.786] от последнего HIGH ✅
  - WT 15m OB (>+60) ✅
  - bear_div на 15m (опционально, усиливает)

Итог: Triple Confluence (OTE + Elliott Wave 3 + AbovePP BearBOS)
       Ожидаемый результат: avgR ≈ +1.0-2.0, WR ≈ 56-71%
```

---

> Версия: 28.05.2026 | Источник: бэктест n=3587 post-14.05.2026 + рой 6 LLM (5/5 консенсус)
> Связанные файлы: `docs/SMC_GUIDE.md`, `docs/LONG_ENTRY_RULES.md`, `docs/ENCYCLOPEDIA.md`, `docs/INDICATORS_GUIDE.md`
