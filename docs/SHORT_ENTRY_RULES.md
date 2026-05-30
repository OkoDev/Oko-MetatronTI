# SHORT Entry Rules — Полное руководство

> Создано: 28.05.2026 | Бэктест n=3587, post-14.05.2026 | Oko MTF Bot

---

## 5 Универсальных правил SHORT входа

Эти правила работают для **большинства** SHORT сигналов (кроме исключений указанных ниже).

### Правило 1: Elliott n_down = 2-3 (волна 3 вниз)

`n_down` = число последовательных **снижающихся** swing highs на HTF = прокси нисходящей волны.

```
n_down = 1:  Начало движения (Волна 1 вниз) — подтверждения мало, осторожно
n_down = 2-3: Волна 3 — ОПТИМАЛЬНЫЙ SHORT вход (сильнейший импульс вниз)
n_down = 4+: Волна 5 — ЛОВУШКА, STOP SHORT (WR=10%, avgR=-1.814)
```

**Почему:** Волна 3 — самая длинная и быстрая нисходящая волна. Входить на её начале = максимальный потенциал движения к S1/S2.

**Данные (atr_change SHORT, n=3587):**

| n_down | Волна | avgR | WR | Действие |
|---|---|---|---|---|
| 2 | Волна 3 начало | +0.194 | 46% | ✅ ОК |
| 3 | Волна 3 продолжение | +0.164 | 42% | ✅ ОК |
| 4+ | Волна 5 / финал | **-1.814** | **10%** | ❌ STOP |

### Правило 2: Daily PP — цена AbovePP

Цена должна быть **выше дневного Pivot Point** при входе.

```
AbovePP = есть пространство вниз к PP → S1 → S2
BelowPP = цена у поддержки, SHORT рискован (нет пространства)
```

**Данные — AbovePP vs BelowPP для SHORT:**

| Сигнал | AbovePP avgR | AbovePP WR | BelowPP avgR | BelowPP WR |
|---|---|---|---|---|
| atr_change SHORT | **-0.115** | **44%** | -0.624 | 21% |
| confluence SHORT | **-0.401** | **38%** | -1.287 | 23% |
| wt_sideways SHORT | **-0.508** | **42%** | -2.465 | 32% |

> Даже "минусовые" сигналы значительно лучше AbovePP чем BelowPP — разрыв в avgR составляет 0.5-2.0R.

### Правило 3: HTF структура — BearBOS (тренд вниз продолжается)

**BearBOS на HTF = тренд ещё вниз = SHORT по тренду.**

```
BearBOS:    Тренд продолжается → SHORT aligned → выше WR
BullChoCH:  ЗАВИСИТ от n_down:
  n_down < 3:  откат Wave 2 вверх → SHORT после него ОК (контр-откат)
  n_down ≥ 3:  конец 5 волн → ABC коррекция ВВЕРХ → STOP SHORT!
```

**Данные:**

| Условие | avgR | WR |
|---|---|---|
| BearBOS + AbovePP | лучшее | лучшее |
| BullChoCH + n_down < 3 | умеренно | ~50% |
| BullChoCH + n_down ≥ 3 | **-2.181** | **0%** |

### Правило 4: HTF направление — aligned down

Цена на HTF (4h/1D) должна двигаться **вниз** последние 5 баров.

**Данные по `htf_price_dir`:**

| Сигнал | htf=down (aligned) | htf=up (counter) |
|---|---|---|
| divergence SHORT | +1.655 WR=65% | +0.100 WR=51% |
| wt_b_signal SHORT | **+2.560 WR=71%** | +0.691 WR=38% |
| watch_list_breach | улучшение | ухудшение |

> Исключение: divergence SHORT работает даже counter-trend (WR=51%) — это самодостаточный сигнал.

### Правило 5: LTF — WT OB или нейтральный + ATRTrend SHORT

На младшем таймфрейме (15m):
- **WT1/WT2 > +60** (OB — перекупленность) = истощение покупателей = откат вниз вероятен
- **ATRTrend = trenddown** = локальный тренд подтверждает SHORT
- **OTE [0.618–0.786]** от последнего импульса вниз = оптимальная зона шорта (Wave 2 retracement вверх)

```
LTF OTE для SHORT:
  Последний импульс ВНИЗ: High_impulse → Low_impulse
  Откат ВВЕРХ: Low_impulse → текущая цена
  OTE bottom = Low_impulse + (High - Low) * 0.618
  OTE top    = Low_impulse + (High - Low) * 0.786
  → Вход SHORT когда цена в [OTE_bottom, OTE_top]
```

---

## Правила по каждому signal_type

### signal_type = divergence SHORT (НЕЗАВИСИМЫЙ СИГНАЛ)

**Лучший SHORT сигнал по соотношению стабильности: avgR=+0.922 WR=56.5%**

Ключевое свойство — **самодостаточность**: не зависит от PP, Elliott, CHoCH.

| Фильтр | Значение | avgR | WR | Вывод |
|---|---|---|---|---|
| AbovePP | да | +0.935 | 58% | одинаково |
| BelowPP | нет | +1.093 | 57% | одинаково |
| n_down = 0 | — | +1.419 | — | не важно |
| n_down = 2 | — | +1.325 | — | не важно |
| n_down ≥ 5 | — | +2.048 | — | даже лучше |
| BullChoCH | разворот | +0.598 | 62% | работает |
| BearBOS | тренд | +1.097 | 57% | работает |
| htf=down aligned | — | **+1.655** | **65%** | **лучше** |
| htf=up counter | — | +0.100 | 51% | тоже OK |

**W19 аномалия:** W19 (до 14.05) = -0.827 — единственный плохой период. Post-14.05: +1.127 WR=60%.

**Когда применять дополнительные фильтры к divergence SHORT:**
- Для максимизации: добавить `htf=down` → +1.655 WR=65%
- Для отсева W19-подобных периодов: `AbovePP` дополнительно улучшает

### signal_type = pivot_reversal SHORT

**Второй по avgR: +1.899 WR=40%**

| Фильтр | avgR | WR | Примечание |
|---|---|---|---|
| AbovePP | +1.911 | 41% | чуть лучше |
| BelowPP | +1.868 | 39% | тоже хорошо (нарушает общее правило!) |
| n_down = 0-1 | лучше | — | ранние волны |
| htf любой | одинаково | — | нейтрален |

> **Особенность:** pivot_reversal SHORT нарушает общее правило PP — работает и AbovePP и BelowPP. Причина: сигнал возникает именно от уровня пивота, не от его позиции.

### signal_type = wt_b_signal SHORT

**Третий по avgR: +1.403 WR=50%**

| Фильтр | avgR | WR |
|---|---|---|
| htf=down aligned | **+2.560** | **71%** |
| htf=up counter | +0.691 | 38% |
| AbovePP | лучше | выше |

**HTF direction — критичен для wt_b_signal.** Без aligned htf=down — сигнал теряет половину силы.

### signal_type = atr_change SHORT

**Зависит от Elliott критически: avgR=-0.266 WR=36.7% overall**

| Elliott n_down | avgR | WR | Действие |
|---|---|---|---|
| 2 | **+0.194** | **46%** | ✅ ОК |
| 3 | **+0.164** | **42%** | ✅ ОК |
| 4 | **-1.814** | **10%** | ❌ STOP |

| PP позиция | avgR | WR |
|---|---|---|
| AbovePP | -0.115 | 44% |
| BelowPP | -0.624 | 21% |

**Минимальные требования для atr_change SHORT:** AbovePP + n_down ≤ 3.

### signal_type = confluence SHORT (ОСТОРОЖНО)

**Overall плохой: avgR=-0.714 WR=32.5%** — но с фильтрами улучшается.

| Elliott n_down | avgR | WR |
|---|---|---|
| 0 | -0.748 | — |
| 2 | -0.218 | — |
| 3 | -1.662 | — |
| 4 | **-2.701** | — |

| PP позиция | avgR | WR |
|---|---|---|
| AbovePP | **-0.401** | 38% |
| BelowPP | -1.287 | 23% |

> **Вывод:** confluence SHORT использовать ТОЛЬКО AbovePP + n_down ≤ 2. При n_down ≥ 3 — **запрещён**.

### signal_type = wt_sideways SHORT (ИЗБЕГАТЬ)

**Худший SHORT сигнал: avgR=-0.898 WR=38.9%**

| PP позиция | avgR | WR |
|---|---|---|
| AbovePP | -0.508 | 42% |
| BelowPP | **-2.465** | 32% |

> Даже с AbovePP фильтром — минус. BelowPP — катастрофа. Рекомендация: **отключить** или использовать только с triple confluence (AbovePP + n_down=2 + htf=down).

---

## Матрица: signal_type × фильтр → что применять

| Signal Type | PP фильтр | Elliott n_down | CHoCH/BOS | HTF dir | Приоритет |
|---|---|---|---|---|---|
| **divergence SHORT** | нейтрален | нейтрален | нейтрален | down = бонус | HIGH ✅ |
| **pivot_reversal SHORT** | нейтрален | n_down=0-2 | нейтрален | нейтрален | HIGH ✅ |
| **wt_b_signal SHORT** | AbovePP ✅ | n_down=2-3 | BearBOS | **down aligned** | HIGH ✅ |
| **atr_change SHORT** | AbovePP ✅ | **n_down=2-3** | BearBOS | down | MED ⚠️ |
| **confluence SHORT** | AbovePP ✅ | **n_down≤2** | BearBOS | down | LOW ⚠️ |
| **wt_sideways SHORT** | AbovePP | n_down=2 | BearBOS | down | ИЗБЕГАТЬ ❌ |

---

## ЗАПРЕТЫ для SHORT (жёсткие правила)

| Условие | Причина | Данные |
|---|---|---|
| **n_down ≥ 4** | Волна 5 = ЛОВУШКА (конец импульса) | WR=10%, avgR=-1.814 |
| **n_down ≥ 3 + BullChoCH** | Конец 5 волн → ABC коррекция вверх | WR=0%, avgR=-2.181 |
| **BelowPP** (большинство сигналов) | Нет пространства вниз, цена у поддержки | avgR всегда хуже |
| **S2/S3 при входе** | Глубокая поддержка → SHORT катастрофичен | — |
| **Reversal Mode active** (n_down≥4) | Идёт ABC коррекция вверх | avgR < -2.0 |
| **confluence SHORT n_down≥3** | Поздние волны = катастрофа | avgR=-2.701 |

---

## Fibonacci для SHORT

### OTE на откате вверх после импульса вниз

```
Импульс ВНИЗ:  High_swing → Low_swing
Откат (Волна 2 вверх): Low_swing → откат

OTE [0.618-0.786]:
  OTE bottom = Low_swing + (High - Low) * 0.618  ← мелкий откат
  OTE top    = Low_swing + (High - Low) * 0.786  ← глубокий откат

→ Вход SHORT когда цена в [OTE_bottom, OTE_top]
→ n_down=1 (первая снижающаяся swing high) + OTE = оптимальная точка Wave 2 retracement
```

### Связь Pivot → Fibonacci для SHORT

```
AbovePP → PP → S1 → S2 (OTE ≈ 0.618 вниз)
  ↑ ВХОД      ↑ TP1   ↑ TP2 = расширение

S1 ≈ 0.382 Fib ниже PP → первая цель
S2 ≈ 0.618 Fib = OTE зона вниз → расширение
S3 ≈ 1.0 расширение = цель Волны 3 SHORT
```

### ОПАСНОСТЬ: не входить SHORT у S2/S3

Если цена **уже у S2 или S3** — это глубокая поддержка, SHORT здесь = катастрофа. Ближайший уровень `pvt_nearest_level = S2` или `S3` при SHORT входе = **блокировать**.

---

## Elliott n_down — алгоритм расчёта

```python
# core/smc/elliott.py (планируется DEV-225)
def calculate_n_down(swing_high_values: list[float]) -> int:
    """
    swing_high_values — список значений swing highs от старых к новым.
    Возвращает число consecutive снижающихся swing highs с конца.
    """
    n = 0
    for i in range(len(swing_high_values)-1, 0, -1):
        if swing_high_values[i] < swing_high_values[i-1]:
            n += 1
        else:
            break
    return n
```

**Пример:**
```
swing_highs = [100, 98, 95, 93]  → все снижаются → n_down = 3 (волна 3)
swing_highs = [100, 98, 95, 97]  → последний вырос → n_down = 0 (разворот!)
swing_highs = [100, 98, 95, 93, 91] → n_down = 4 → STOP SHORT
```

---

## Reversal Mode — когда SHORT запрещён

Три условия (все три = SHORT запрещён):
```
1. WT 4h в OS (<-60) ИЛИ OB (>+60) = истощение Волны 5
2. ADX снижается последние 3 бара = momentum иссякает
3. CHoCH на 1h/15m = структурный слом

+ n_down ≥ 4 = сильнейший сигнал конца 5-волнового импульса
→ mode = REVERSAL → SHORT = ЗАПРЕТ
```

**Данные:** n_down ≥ 3 + BullChoCH: WR=0%, avgR=-2.181 — жёсткий запрет, не обсуждается.

---

## Чек-лист SHORT входа

**Обязательные условия:**
- [ ] n_down = 2-3 (волна 3 вниз, не 5)
- [ ] AbovePP (кроме pivot_reversal и divergence)
- [ ] НЕТ: n_down ≥ 3 + BullChoCH (STOP SHORT)
- [ ] НЕТ: BelowPP + SHORT (кроме pivot_reversal)

**Желательные условия (повышают WR):**
- [ ] HTF price_dir = down (aligned)
- [ ] BearBOS на HTF (тренд продолжается)
- [ ] WT LTF OB (>+60) — истощение покупателей
- [ ] ATRTrend = trenddown на LTF
- [ ] OTE [0.618–0.786] на LTF (Wave 2 retracement вверх)
- [ ] bear_div на LTF (дополнительное подтверждение)

**Дополнительная проверка (shadow DEV-225):**
- [ ] `pvt_nearest_level` ≠ S2/S3 (не входить у глубокой поддержки)
- [ ] `pvt_above_daily_pp = True` (цена выше дневного PP)
- [ ] `elliott_n_down` ≤ 3 (волна 3, не 5)
- [ ] `htf_price_dir = down` (последние 5 баров HTF идут вниз)

---

## Универсальные vs signal-specific фильтры

| Фильтр | Универсален? | Исключения |
|---|---|---|
| AbovePP | ✅ Универсален для SHORT | pivot_reversal (работает везде), divergence (не важен) |
| n_down ≤ 3 | ✅ Универсален | divergence (не зависит) |
| htf=down | ⚠️ Умеренно важен | divergence (counter-trend WR=51% тоже OK) |
| BearBOS | ⚠️ Важен для трендовых | divergence/pivot_reversal (нейтрален) |
| OTE LTF | Опционален | Усиливает любой сигнал |

**Три фильтра которые работают для БОЛЬШИНСТВА SHORT:**
1. **AbovePP** → применять всегда кроме pivot_reversal и divergence
2. **n_down ≤ 3** → применять для atr_change, confluence, wt_b_signal
3. **НЕ n_down≥3 + BullChoCH** → жёсткое правило для всех сигналов

---

## Сравнение SHORT vs LONG (ключевые отличия)

| Параметр | SHORT | LONG |
|---|---|---|
| PP правило | AbovePP | BelowPP |
| Elliott лучший | n_down = 2-3 | n_up = 2-3 |
| Elliott запрет | n_down ≥ 4 | n_up ≥ 4 |
| CHoCH запрет | n_down≥3 + BullChoCH | n_up≥3 + BearChoCH |
| HTF структура | BearBOS (тренд вниз) | BearBOS (контр-тренд LONG!) |
| Лучший сигнал | divergence SHORT (+0.922) | liquidity_sweep LONG (+4.418) |
| Инверсия PP | нет | liquidity_sweep AbovePP WR=89% |
| OTE зона | Wave 2 retracement вверх | Wave 2 retracement вниз |

> **Парадокс LONG:** BearBOS лучше и для SHORT (по тренду) И для LONG (контр-тренд с поддержкой). Механика разная: SHORT+BearBOS = по тренду; LONG+BearBOS = покупка у структурной поддержки пока тренд ещё вниз.

---

> Версия: 28.05.2026 | Источник: бэктест n=3587 post-14.05.2026 + рой 6 LLM (5/5 консенсус)
> Связанные файлы: `docs/LONG_ENTRY_RULES.md`, `docs/CONCEPT_MAP.md`, `docs/SMC_GUIDE.md`, `docs/ENCYCLOPEDIA.md`
