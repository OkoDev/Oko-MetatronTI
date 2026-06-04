---
name: oko-sm-pine-ob-fvg
description: "Полный Pine-индикатор пользователя \"OKO - SM\". Эталон для бота. КЛЮЧЕВОЕ для ARCH-128 (swing significance): ZigZag с ATR-deviation порогом + двухуровневые swings (len=50 значимый / len=5 internal). Бот использует наивный fractal period=5 без фильтра значимости — это корень \"мелких свингов\" (DS-311 OTE + слом структуры)."
metadata: 
  node_type: memory
  type: reference
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# OKO-SM — эталонный индикатор (Pine), дан пользователем 02.06.2026

Самый полный индикатор пользователя. Бот должен воспроизводить его логику. ATR-trend формула (supertrend factor=1/pd=43) — пользователь сам считает неидеальной (искал лучшее), НЕ копировать слепо. Остальное — эталон.

## 🔑 КРИТИЧНО для ARCH-128 (swing significance) — 2 метода значимости

### 1. ZigZag с ATR-deviation порогом (блок "Waves")
```pine
i_dev_thresh = ta.atr(10)/close*100 * 3   // порог значимости = 3×(ATR% от close)
i_depth = 11                               // глубина pivot
pivots(src, depth/2, isHigh):              // pivot = src выше/ниже всех ±depth/2
  c = src[length]; ok = all(src[i] <= c) for i in 0..2*length
pivotFound(dev, ...):                       // СВИНГ ТОЛЬКО ЕСЛИ:
  if same_direction: обновить экстремум (продолжение)
  else if abs(dev) > i_dev_thresh: новый свинг  // ← ФИЛЬТР ЗНАЧИМОСТИ
calc_dev = 100*(price - base_price)/price
```
**Суть:** свинг подтверждается только если разворот ≥ 3×ATR% — отсекает шум. Это решение «мелких свингов».

### 2. Двухуровневые swings (LuxAlgo SMC)
```pine
swings(len):
  os := high[len] > highest(len) ? 0 : low[len] < lowest(len) ? 1 : os[1]
  top = os==0 and os[1]!=0 ? high[len] : 0
  btm = os==1 and os[1]!=1 ? low[len] : 0
[top, btm]   = swings(50)   // SWING structure (значимые HH/HL/LH/LL)
[itop, ibtm] = swings(5)    // INTERNAL structure (мелкие)
```
**Суть:** ДВА уровня — значимый (50) для структуры/слома, внутренний (5) для входа. Ровно метод пользователя: слом значимой структуры → импульс на младшем.

## Структура BOS/CHoCH (LuxAlgo)
- `ta.crossover(close, top_y)` + trend<0 → CHoCH, иначе BOS (swing). Аналогично internal (itop_y).
- Strong/Weak High/Low: по знаку trend (Strong High при trend<0).
- Premium/Discount/Equilibrium зоны: от trail_up/trail_dn (0.95/0.525/0.05 деления).

## Order Blocks (фильтр значимости)
- `ob_filter = 'Atr'` (atr=ta.atr(200)) ИЛИ 'Cumulative Mean Range' (cum(H-L)/n).
- OB = свеча где (high-low) < ob_threshold*2, внутри структурного интервала.

## EQH/EQL
- `ta.pivothigh(eq_len=3, eq_len)` + `max < min + atr*eq_threshold(0.1)` → равные.

## FVG
- `src_l > src_h[2] and src_c1 > src_h[2] and delta% > threshold` (auto: cum(|delta|)/n*2).
- ✅ `swing_service.detect_fvg` (02.06). **2 критичных нюанса** (SOL 15m сверка):
  1. **Порог = среднее |gap%| по ВСЕМ барам ×2** (gap=0 где нет FVG), НЕ только по FVG-барам.
     Среднее по FVG-барам задирают редкие крупные гэпы (0.83%/1.08%) → порог 0.42% режет валидные.
     По всем барам → 0.097% → ловит эталонные bear-FVG (@80.5/78/76.5).
  2. **Mitigation по CLOSE за границей** (bull: close<bottom, bear: close>top) — НЕ касание фитилём,
     иначе тренд закрывает валидные FVG откатами.
  - Косметика: подпись FVG↑/↓ + **midline 0.5** (consequent encroachment, перекрытие 0.5).
- ✅ `detect_equal_levels` (EQH/EQL, pivot eq_len=3, |Δ|<0.1×ATR) — подтверждён GRT.
- ✅ Полный слой собран на SOL 15m (ZigZag+HH/HL+BOS/CHoCH+OTE+EQH/EQL+FVG) — «каши» нет, читаемо.

## CMA Lines (Фибо-SMA → MA-магниты)
- SMA 21/55/89/144/233 (Фибоначчи). ← кандидаты в HTF-MA магниты TPSelector (см. разбор инфлюенсера: дамп к ma200w).

## Прочее
- Hull+Kahlman scalping (crossup/crossdn) — entry-сигнал на сглаженной Hull MA через Kahlman-фильтр.
- Dynamic Channel — linreg slope+deviation (тренд-канал).
- FF Pivots (daily/weekly/monthly/yearly future PP+S1/R1).

## Бот vs эталон (gap)
| Компонент | Бот | Эталон |
|---|---|---|
| Swing-detection | fractal period=5 (наивный) | **ZigZag ATR-dev + двухуровневые swings(50/5)** ❌ нет в боте |
| SMC BOS/CHoCH/OB/FVG/EQH | SMC sub-куб (есть) | LuxAlgo (эталон) |
| MA-магниты | pivot/FVG/swing | **CMA 21/55/89/144/233** ❌ нет |
| Hull+Kahlman scalp | нет | есть |

**Вывод для ARCH-128:** заменить fractal-5 на двухуровневые swings (значимый/internal) + ZigZag ATR-dev. Источник формул — этот файл.

## ПРОГРЕСС ARCH-128 (02.06.2026)
- ✅ **ZigZag «Waves» ВОСПРОИЗВЕДЁН 1:1** (коммит 304f1c8, `core/smc/swing_service.py:zigzag_atr`). Настройки пользователя: dev=3, depth=11, белый dotted, width=4. Подтверждено визуально на XLM 1m. Баги что чинил: look-ahead в pivot (Pine подтверждает через length баров назад) + ATR должен быть Wilder RMA (не SMA). ZigZag = ДЕТАЛЬНАЯ волновая линия (≠ structure labels).
- 🔴 **ФИКС плато-пивотов (02.06):** `pivot_at` сравнивал соседей строго `>`/`<` → при РАВНЫХ тиках (плато) каждый бар плато = «пивот» → лишние zz-точки (GRT 18:06 L, 18:36 H). Опасно: разбивают большой импульс → крадут большую фибу (пользователь: «построил бы ещё одну большую шортовую»). Фикс: **слева строго (`>=`/`<=` отменяет), справа нестрого (`>`/`<`)** — на плато проходит только первый бар, лишние уходят, значимые целы. ⚠️ Полный `>=/<=` с ОБЕИХ сторон СЛИШКОМ жёсткий (на 1m убил валидные пивоты) — только left-strict.
- 🔄 **Swing Structure HH/HL/LH/LL** — настройка «Show Swings Points = 50» = LuxAlgo `swings(length=50)`. Классификация: HH если swing-high > пред. high, LH если ниже; LL если swing-low < пред. low, HL если выше. ОТДЕЛЬНЫЙ слой от ZigZag (структурные точки, не волновая линия). Внутренняя структура — swings(5).
- ✅ **OTE bull+bear ПОДТВЕРЖДЁН до цента** (GRT 02.06): bull-CHoCH LONG (импульс low→high, OTE near low) и bear-CHoCH SHORT (high→low, near high). build_ote совпал с ручной разметкой по цене И времени.
- 🔴🔴 **ПЕРЕЛОМ автопоиска (02.06): структуру строить на ZigZag, НЕ на swings(50)!** Пользователь вскрыл: LuxAlgo/swings(50) **пропускает важные вершины** → детектит слом постфактум/не там. На GRT 02.06 swings(50) дал `CHoCH bull @21:06`, а настоящий слом был @**19:53** (ZigZag поймал: 19:00 LH 0.02342 → 19:33 LL 0.02284 → 19:53 high 0.02348 пробил LH = слом вверх).
- 🔴 **ФОРМУЛА АВТОПОИСКА сетапа** (подтверждена визуально, ждёт кода):
  1. ZigZag(dev=3,depth=11) → структурные точки H/L (ловит то, что swings(50) теряет).
  2. классификация HH/HL/LH/LL по пред. экстремуму.
  3. СЛОМ = close пробивает последний значимый ZigZag-экстремум ПРОТИВ структуры: нисходящая (LL+LH) + пробой последнего LH вверх = bull-CHoCH; восходящая + пробой HL вниз = bear-CHoCH.
  4. **ИМПУЛЬС для фибо = тот, что СЛОМАЛ структуру** (от экстремума-начала до бара-пробоя), НЕ последняя нога и НЕ «последний CHoCH». На GRT: low 19:33 → high 19:53.
  5. фибо на импульсе слома → OTE (bull→near low LONG, bear→near high SHORT).
  6. вход на ретесте OTE, стоп за 1.0. Проверка GRT: откат @20:22 в OTE 0.705 → разворот вверх, LONG отработал.
- ⚠️ Баг старого `find_choch_ote`: берёт `chochs[-1]` (последний по времени) + детект на len=5/50 → ловит шум/пропускает слом. Заменено на `find_setups_zz` (ZigZag + перебор сломов).
- 🔴 **ФИКС (02.06): слом = пробой ЗАЩИЩЁННОГО уровня, НЕ соседней вершины.** Пользователь: «смотришь только на предыдущую вершину! логика сломана HH/HL/LH/LL». `find_setups_zz` переписан: ведёт `prot_high`/`prot_low` (защитные структурные уровни, держатся пока тренд жив) + `cand_*` (последний swing = новый защитный при подтверждении). «Самый главный слом» на GRT = пробой защитного low **0.02327@15:31** (держался ~3ч) около 18:54 — НЕ сосед 0.02376. CHoCH bull @19:53 (пробой 0.02342) подтверждён. Пользователь: «+».
- 🚫 Объём на 1m НЕ использовать как критерий слома (пользователь 02.06: «про объём на минутке не стоит»). Важнее точные структурные точки.
- ⏳ Дальше: формализовать find на ZigZag-структуре (код) → прогон на GRT (найти и LONG@19:53 и bear-слом) → EQL/EQH + FVG → OTE-Retest Engine + бэктест.
