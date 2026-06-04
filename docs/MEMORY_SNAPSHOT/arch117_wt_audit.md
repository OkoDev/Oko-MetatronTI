---
name: arch117-wt-audit
description: "Полный аудит WT/RSI для ARCH-117 — все расхождения формул, порогов, определений wt_cross и wt_div по всем модулям проекта"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# ARCH-117: Аудит WT/RSI расхождений (29.05.2026)

Собрано автономно при анализе D-073 данных и DEV-234 фикса.
**Why:** пользователь попросил запоминать всё для ARCH-117.

> **🔴 ph3 ВЕРДИКТ (31.05.2026) — shadow-сравнение combinator vs core/ (40 пар) + радиус (187 паттернов) + рой:**
> | Признак | combinator | core/ | Расхождение | Паттернов зависит |
> |---|---|---|---|---|
> | WT1 | wavetrend | calculate_wt | **0.000000 ИДЕНТИЧНО** | 115/187 (безопасно) |
> | RSI | SMA-rolling | compute_rsi Wilder | медиана 7.8пт, зона 60% | 50/187 |
> | trend | EWM-ATR+свой supertrend | Wilder-RMA-ATR+Pine | 85% совпадение | 108/187 |
>
> **РЕШЕНИЕ:** combinator = ЗАМОРОЖЕН как эталон паттернов/бэктеста/snapshot (RSI-SMA + trend-EWM).
> Сферы (RSIService Wilder, calculate_trend Pine) = LIVE-сигналы, ДРУГАЯ формула НАМЕРЕННО.
> WT — общий (идентичен), сферы уже = combinator. RSI/trend switch на «стандарт» = пересчёт
> DEV-235-масштаба (58%/27% паттернов, многие топовые T2_S_* avgR~1.2 WR~80%) — НЕ оправдано.
> Инвариант «один калькулятор» РЕЛАКСИРОВАН: WT общий, RSI/trend раздельны (combinator↔snapshot↔ML,
> сферы↔live). **НЕ путать combinator-RSI(SMA) с RSIService(Wilder) — это РАЗНЫЕ числа.**
> ML-мина развязана: snapshot из combinator самосогласован (train=stored), сферный RSI не в snapshot.
> Скрипты: `e:/tmp/ph3_shadow_compare.py`, `ph3_blast_radius.py`. Рой: `obsidian/Team-Discussions/2026-05-31-arch-117-ph3-*`.

> **ОБНОВЛЕНИЕ 30.05.2026:** `extended_indicators.py` УДАЛЁН параллельной ARCH-118 сессией
> (коммит ffd88c8, 429 строк мёртвого кода, нигде не импортировался). Значит:
> - wt2 EWM(span=4)→SMA(4) «баг» = **MOOT** (файла нет, нулевой радиус)
> - «7+ файлов» дублирования = на деле меньше: indicators.py(канон) + combinator(уже фикс DEV-234) + chart_builder(display) + 4 скрипта(offline)
> - ARCH-117 ph2 рефокус: RSIService (RSI почти не live-сигнал) + ml_predictor RSI дубль + chart_builder
> - RSIService строится на `compute_rsi` (канон, Wilder RMA) БЕЗ новой формулы: value+zone(70/30)+cross50

---

## Каноничная формула WT (indicators.py — ЕДИНСТВЕННЫЙ ИСТОЧНИК ПРАВДЫ)

```python
# core/indicators/indicators.py:5-21
hlc3 = (high + low + close) / 3
esa  = EMA(hlc3, n1=10)
d    = EMA(abs(hlc3 - esa), n1=10)
ci   = (hlc3 - esa) / (0.015 * d)
wt1  = EMA(ci, n2=21)
wt2  = wt1.rolling(window=4).mean()   ← SMA-4 (простое скользящее)
```

**ARCH-18 оптимизация:** если n1=10, n2=21 и колонки уже есть → skip пересчёт.

---

## Сводная таблица расхождений

| Модуль | wt1 формула | wt2 формула | Отличие |
|--------|------------|------------|---------|
| `core/indicators/indicators.py` | ✅ EMA(n1=10, n2=21) | ✅ SMA(4) = rolling(4) | КАНОНИЧНО |
| `tools/pattern_mining/combinator_v2.py` | ✅ использует indicators | ✅ использует indicators | ✅ OK |
| `tools/pattern_mining/combinator_v1.py` | ⚠️ нужно проверить | ⚠️ | ? |
| `core/indicators/extended_indicators.py:279` | ✅ EMA(n1=10, n2=21) | ❌ **EWM(span=4)** ≠ SMA(4)! | РАСХОЖДЕНИЕ |
| `core/ui/chart_builder.py` | ⚠️ нужно проверить | ⚠️ | ? |
| Скрипты (analyze_history, daily_trade_review...) | ⚠️ независимые копии | ⚠️ | ? |

**EWM(span=4) vs SMA(4) — это разные вещи!**
- `rolling(window=4).mean()` = простое среднее последних 4 баров
- `ewm(span=4).mean()` = экспоненциальное среднее с α=2/(4+1)=0.4
- При spike wt1 → wt2 ewm реагирует быстрее → cross обнаруживается раньше

---

## Расхождения wt_cross

### Определения по модулям:

| Модуль | Формула | Зона проверяется? | Порог | Момент |
|--------|---------|-------------------|-------|--------|
| **scan_loop.py wt_snap** | `wt1_prev≤wt2_prev AND wt1_cur>wt2_cur` | ❌ Нет | — | — |
| **WTSpecialist** | читает snap + `zone in ("OB","OS")` | ✅ Да | ±60 | ПОСЛЕ кросса (wt_cur) |
| **combinator_v2 DEV-234** | `wt[i-1]≤wt2[i-1] AND wt[i-1]<-60 AND wt[i]>wt2[i]` | ✅ Да | **-60** | **ДО кросса (wt_prev)** |
| **signal_checkers.py** | cross + `wt1_last < _os_gate` | ✅ Да | adaptive | ПОСЛЕ кросса |
| **extended_indicators.py** | cross + `wt1[i] < -50` | ✅ Да | **-50** (мягче!) | ПОСЛЕ кросса |
| **htf_detectors.py** | явно "в зонах OB/OS" | ✅ Да | ? | ? |
| **funding_detector.py** | `os_level=-40.0, ob_level=40.0` | ✅ Да | **±40** (самый мягкий!) | ? |

**Итого 4 разных порога:** -40, -50, -60, adaptive. Все разные!

### Ключевое: ДО vs ПОСЛЕ кросса

```
combinator_v2 (строго): wt[i-1] < -60  ← был в зоне ДО кросса
WTSpecialist  (мягко):  zone = "OS"    ← в зоне СЕЙЧАС (после кросса wt1 мог выйти из -60)
extended_ind  (мягко):  wt1[i] < -50   ← ПОСЛЕ кросса, мягкий порог
```

Combinator = самый строгий и семантически правильный.

---

## Расхождения wt_divergence

Два принципиально разных алгоритма:

### WT_X (реализован в combinator_v2 после DEV-233b)
```
Пивот = Williams fractal на самом WT (центр wt[i-2])
Цена = по low/high (не close!)
Trendline = НЕТ (не нужна)
Сравнение = текущий WT-фрактал с предыдущим WT-фракталом
```

### LonesomeTheBlue (реализован в combinator_v2 после DEV-233 для RSI, и в scan_loop/divergence_detector для основного бота)
```
Пивот = по close (close-pivot)
Trendline = ДА (non-intersection check)
Сравнение = pivot-к-pivot по close + trendline по close+osc
persist = 3 бара (в combinator)
```

**Важно:** эти два алгоритма НЕСОВМЕСТИМЫ по частоте и качеству сигналов:
- WT_X: пивот на WT → менее зашумлён, но другая периодичность
- LonesomeTheBlue: пивот по цене → ближе к "классической" дивергенции

**Для ARCH-117:** WTService должен определиться — один из двух алгоритмов для WT-div, или оба с разными флагами.

---

## Потребители wt_snap (из scan_loop)

Все читают `wt_snap[tf]['wt_cross']` = сырой cross (без зоны):

| Потребитель | Добавляет zone-фильтр? | Как |
|-------------|----------------------|-----|
| `wt_specialist.derive_wt_verdict()` | ✅ Да | `abs(cross)≥1 AND zone in ("OB","OS")` |
| `entry_matrix.py` | ⚠️ нужно проверить | ? |
| ARCH-104 observer (D-051 gate) | ❌ Нет | использует `active_flags` из combinator, НЕ wt_snap |

**Вывод:** ARCH-104 и основной бот используют РАЗНЫЕ источники wt_cross:
- arch104: combinator.compute_flags() → `wt_cross_up_1h` (cross В ЗОНЕ, строго)
- основной бот: scan_loop wt_snap → `wt_cross` (сырой) + WTSpecialist добавляет zone

---

## wt2 формула в extended_indicators — ЭТО БАГ?

```python
# extended_indicators.py:280
wt2 = pd.Series(wt1).ewm(span=4, adjust=False).mean().values  ← EWM
# indicators.py:20 (canonical)
df["wt2"] = df["wt1"].rolling(window=4, min_periods=1).mean()  ← SMA
```

EWM(span=4) даёт другую wt2 → другие кроссы → extended_indicators сигналы расходятся с canonical.

**Кто использует extended_indicators?**  
Нужно проверить: если arch105 или другие паттерны используют `wt_cross_in_os_{tf}` из extended_indicators — они работают на другой формуле wt2.

---

## КЛЮЧЕВОЙ ПРИНЦИП (от пользователя 29.05)

> "Зона OB/OS в вычислениях должна быть правильной — а не как надо комбинатору!"

**Текущая проблема:** 4 разных захардкоженных порога (-40, -50, -60, adaptive) — все произвольные.

**Правильный подход:** пороги должны вычисляться из природы данных пары, а не из удобства потребителя.

**Готовое решение уже есть** — `core/indicators/dynamic_thresholds.py` (DEV-23, shadow):
```python
# mean ± k*std по последним 50 барам wt1
dyn_os = mean(wt1[-50:]) - 0.8 * std(wt1[-50:])
dyn_ob = mean(wt1[-50:]) + 0.8 * std(wt1[-50:])
```
Сейчас отключён (`dynamic_os_enabled=False`). Для ARCH-117 WTService — **активировать как основной**, с fallback на -60 при нехватке данных.

**Почему важно:** если зона определена неверно (например -60 при реальном диапазоне пары -30..+30), то:
- cross_in_zone никогда не срабатывает (сигналы теряются)
- или срабатывает постоянно (шум)
- arch104 D-051 gate отказывает по ложным причинам

---

## Для реализации ARCH-117 (WTService)

```python
class WTService:
    # 1. Формула — ТОЛЬКО из indicators.py (canonical)
    # wt2 = SMA(4), НЕ EWM(4)
    
    # 2. cross_in_zone — ДО кросса (combinator-стиль)
    def _cross_up_in_os(self, wt1, wt2, threshold=-60):
        # wt1[i-1] <= wt2[i-1]  (был ниже wt2)
        # wt1[i] > wt2[i]        (пересёк вверх)
        # wt1[i-1] < threshold   (был в OS ДО кросса) ← строгий вариант
    
    # 3. zone_threshold = -60/+60 (как combinator_v2, не -50 не -40)
    
    # 4. Дивергенция = WT_X алгоритм (Williams fractal на WT)
    #    RSIService отдельно = LonesomeTheBlue (pivot по close)
    
    # 5. Публикует в Bus:
    #    wt_snap: {wt1, wt2, zone, cross_raw, cross_in_zone, divergence}
    #    Потребители получают ОБА типа cross
```

**Открытые вопросы для дизайна ARCH-117:**
1. Публиковать `cross_raw` И `cross_in_zone` оба — или только `cross_in_zone`?
2. Нужно ли обратно совместимое поле `wt_cross` = 0/1/-1 (для WTSpecialist который не ломать)?
3. EWM(4) в extended_indicators — фиксить сразу или в рамках ARCH-117?
4. Единый порог ±60 или сохранить adaptive (как в signal_checkers)?

---

## Связанные задачи

- [[ARCH-117]] — WTService + RSIService как единые сферы
- [[DEV-233]] ✅ — WT_X дивергенции (pivot на WT)
- [[DEV-234]] ✅ — wt_cross выровнен в combinator (кросс В ЗОНЕ)
- [[DEV-235]] 🔄 — ретробэктест, зависит от правильных div/cross
- [[memory/feedback_wt_cross_zone.md]] — краткое напоминание
