# LONG Entry Rules — Полное руководство

> Создано: 28.05.2026 | Бэктест n=3587, post-14.05.2026 | Oko MTF Bot

---

## 5 Универсальных правил LONG входа

Эти правила работают для **большинства** LONG сигналов (кроме исключений указанных ниже).

### Правило 1: Elliott n_up = 2-3 (волна 3 вверх)

`n_up` = число последовательных **растущих** swing lows на HTF = прокси восходящей волны.

```
n_up = 1:  Начало движения (Волна 1 вверх) — осторожно, подтверждения мало
n_up = 2-3: Волна 3 — ОПТИМАЛЬНЫЙ LONG вход (сильнейший импульс)
n_up = 4+: Волна 5 — ЛОВУШКА, избегать (аналогия с n_down=4)
```

**Почему:** Волна 3 — самая длинная и сильная, входить в её начало = максимальный потенциал.

### Правило 2: Daily PP — цена BelowPP

Цена должна быть **ниже дневного Pivot Point** при входе.

```
BelowPP = есть пространство вверх к PP и R1
AbovePP = цена у сопротивления, LONG рискован (исключение: liquidity_sweep)
```

**Данные (n=3587):**
| Сигнал | BelowPP avgR | AbovePP avgR |
|---|---|---|
| confluence LONG | +0.227 | -0.303 |
| watch_list_breach LONG | +0.235 | -0.136 |
| arch104 LONG | +2.001* | убыток* |

*arch104 BelowPP+BearBOS = лучшая комбинация

### Правило 3: HTF структура — BearBOS или нейтральная

**BearBOS на HTF + LONG = контр-трендовый вход с поддержкой.**

Это парадоксальная но эмпирически подтверждённая закономерность:
- BearBOS означает что HTF тренд ещё вниз → цена у поддержки
- LONG из этой зоны = покупка у структурной поддержки = конфлюенция

**Данные:**
| Сигнал | BearBOS avgR | BullChoCH avgR |
|---|---|---|
| arch104 LONG BelowPP | **+2.001** WR=56% | -0.235 WR=35% |
| watch_list_breach LONG BelowPP | **+1.556** WR=61% | убыток |
| confluence LONG | +0.052 | -0.586 |

> **Ключевой вывод:** BullChoCH на HTF при LONG входе = часто ловушка (цена уже развернулась вверх = вы опоздали). BearBOS + LONG = покупаете у дна пока тренд ещё вниз = дешевле.

### Правило 4: LTF — WT OS + OTE зона

На младшем таймфрейме (15m):
- **WT1/WT2 < -60** (OS — перепроданность) = истощение продавцов
- **OTE [0.618–0.786]** от последнего импульса вверх = оптимальная зона откупа

```
LTF OTE для LONG:
  Последний импульс ВВЕРХ: Low_impulse → High_impulse
  Откат: High_impulse → текущая цена
  OTE bottom = High_impulse - (High - Low) * 0.786
  OTE top    = High_impulse - (High - Low) * 0.618
  → Вход LONG когда цена в [OTE_bottom, OTE_top]
```

### Правило 5: Дополнительное подтверждение — bull_div на LTF

Бычья дивергенция на 15m = дополнительное подтверждение что sellers истощились:
- WT делает новый OS (< -60) но цена НЕ делает новый Low = скрытая сила покупателей
- Комбо: bull_div + OTE + BelowPP = тройная конфлюенция

---

## Правила по каждому signal_type

### signal_type = arch104

**Лучшая комбинация:** `BelowPP + BearBOS = avgR=+2.001 WR=56%`

| Фильтр | avgR | WR | Рекомендация |
|---|---|---|---|
| BelowPP + BearBOS | **+2.001** | 56% | ✅ ВОЙТИ |
| BelowPP + BullChoCH | -0.235 | 35% | ❌ СТОП |
| AbovePP + любое | убыток | <30% | ❌ СТОП |

**Когда НЕ работает:** AbovePP, BullChoCH на HTF.

### signal_type = watch_list_breach

**Лучшая комбинация:** `BelowPP + BearBOS = avgR=+1.556 WR=61%`

| Фильтр | avgR | WR |
|---|---|---|
| BelowPP + BearBOS | **+1.556** | 61% |
| AbovePP | -0.136 | 28% |

### signal_type = liquidity_sweep (ИСКЛЮЧЕНИЕ — ИНВЕРСИЯ PP)

**liquidity_sweep LONG полностью инвертирует правило PP:**

| Позиция PP | avgR | WR | Объяснение |
|---|---|---|---|
| **AbovePP** | **+8.595** | **89%** | Свип ниже PP + восстановление = BULLISH |
| BelowPP | -0.281 | 38% | Нет свипа = нет сигнала |

**Механика liquidity_sweep LONG:**
```
1. Цена пробивает вниз ниже PP (sweep стопов быков)
2. Маркет-мейкер собирает ликвидность (stop hunt)
3. Цена быстро восстанавливается ВЫШЕ PP
4. Текущая цена AbovePP = подтверждение что свип был ложным
→ LONG: ожидаем движение к R1, R2

Elliott: n=0-1 → avgR=+6.187 WR=75% (ранние волны лучше)
```

### signal_type = divergence (НЕЗАВИСИМЫЙ СИГНАЛ)

**divergence LONG НЕ зависит от PP, Elliott, CHoCH:**

| Период | avgR | WR | Независимость |
|---|---|---|---|
| W19 (до 14.05) | +0.5 | 55% | Работает при любых PP |
| W20 (post-14.05) | +1.1 | 60% | Продолжает работать |
| AbovePP | схожий | схожий | PP не важен |
| BelowPP | схожий | схожий | PP не важен |

**Дивергенция самодостаточна** потому что кодирует ослабление momentum — это независимый от структуры сигнал.

### signal_type = confluence LONG

| Фильтр | avgR | WR |
|---|---|---|
| BelowPP | +0.227 | 41% |
| AbovePP | -0.303 | 25% |
| BearBOS | +0.052 | 38% |
| BullChoCH | -0.586 | 30% |

**Минимальные требования для confluence LONG:** BelowPP + BearBOS или BelowPP + нейтральный.

---

## Матрица: signal_type × фильтр → что применять

| Signal Type | PP фильтр | Elliott фильтр | CHoCH фильтр | HTF dir | Приоритет |
|---|---|---|---|---|---|
| **arch104 LONG** | BelowPP ✅ | n_up=2-3 | BearBOS ✅ | down/flat | HIGH |
| **watch_list_breach LONG** | BelowPP ✅ | n_up=2-3 | BearBOS ✅ | up aligned | HIGH |
| **liquidity_sweep LONG** | AbovePP ✅ (инверсия!) | n=0-1 ранние | любой | любой | HIGH |
| **divergence LONG** | нейтрален | нейтрален | нейтрален | down = +20% | MED |
| **confluence LONG** | BelowPP ✅ | n_up≤3 | BearBOS | up | MED |
| **pivot_reversal LONG** | BelowPP | n_up=1-2 | нейтрален | нейтрален | MED |
| **wt_b_signal LONG** | BelowPP | n_up=2-3 | BearBOS | up aligned | MED |

---

## Elliott n_up — прокси восходящей волны (зеркало n_down)

`n_up` = число последовательных **растущих** swing lows на HTF.

```python
# Зеркальный алгоритм к n_down
def calculate_n_up(swing_lows: list[float]) -> int:
    """Число consecutive растущих swing lows с конца."""
    n = 0
    for i in range(len(swing_lows)-1, 0, -1):
        if swing_lows[i] > swing_lows[i-1]:
            n += 1
        else:
            break
    return n
```

**Эмпирика (зеркальная к SHORT):**
| n_up | Волна | Ожидаемый исход |
|---|---|---|
| 1 | Волна 1 — начало | WR умеренная, подождать |
| 2-3 | **Волна 3 — ОПТИМУМ** | Лучшие LONG результаты |
| 4+ | Волна 5 — ЛОВУШКА | Избегать LONG |

---

## Fibonacci для LONG

### OTE на откате вниз после импульса вверх

```
Импульс ВВЕРХ:  Low_swing → High_swing
Откат (Волна 2): High_swing → откат

OTE [0.618-0.786]:
  OTE_top    = High_swing - (High - Low) * 0.618  ← более мелкий откат
  OTE_bottom = High_swing - (High - Low) * 0.786  ← глубокий откат

→ Вход LONG когда цена в [OTE_bottom, OTE_top]
```

### Связь Pivot → Fibonacci для LONG

```
BelowPP → PP → R1 → R2 (OTE ≈ 0.618 вверх)
  ↑ ВХОД      ↑ TP1   ↑ TP2 = расширение
```

R2 ≈ 0.618 Fibonacci от дневного диапазона = естественная цель волны 3 вверх.

---

## Связь WT + ATRTrend + PP + CHoCH для LONG подтверждения

```
WT1/WT2 < -60 (OS)  → продавцы истощены → разворот вверх вероятен
ATRTrend = trendup  → тренд подтверждает LONG направление
BelowPP             → есть пространство к PP, R1, R2
BearBOS на HTF      → вход у структурной поддержки
bull_div на LTF     → скрытая бычья сила (momentum не снижается)
```

**Чек-лист LONG входа:**
- [ ] n_up = 2-3 (волна 3 вверх) ИЛИ n_up = 0 (начало разворота)
- [ ] BelowPP (кроме liquidity_sweep)
- [ ] BearBOS на HTF (контр-тренд с поддержкой)
- [ ] WT OS (<-60) на LTF
- [ ] ATRTrend = trendup или нейтральный
- [ ] OTE [0.618-0.786] на LTF (опционально, усиливает)
- [ ] bull_div на LTF (опционально, усиливает)

---

## ЗАПРЕТЫ для LONG

| Условие | Причина | Данные |
|---|---|---|
| n_up ≥ 4 | Волна 5 LONG = ловушка | По аналогии с n_down=4 SHORT: WR=10% |
| AbovePP (кроме liquidity_sweep) | Нет пространства вверх | avgR всегда хуже |
| BullChoCH на HTF (arch104) | Опоздали, разворот уже случился | avgR=-0.235 WR=35% |
| Reversal Mode SHORT (рынок идёт вверх) | ABC коррекция вверх = не LONG | — |

---

> Версия: 28.05.2026 | Источник: бэктест n=3587 post-14.05.2026 + рой 6 LLM
