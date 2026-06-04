---
name: arch_indicator_precompute
description: Архитектурное решение — pre-compute индикаторов в scan_one + набор TF для MTF (6 вместо 7)
type: project
---

## Pre-compute индикаторов в scan_one (принято, не реализовано)

**Проблема:** `calculate_wt()` и `calculate_trend()` вызываются 12-14 раз на одном и том же df за один цикл сканирования пары. Каждый детектор считает сам.

**Решение:** Pre-compute один раз в `scan_one`, передавать обогащённый df во все детекторы:
```python
df = calculate_trend(df)  # добавляет: trend, trendup, trenddown
df = calculate_wt(df)     # добавляет: wt1, wt2, wt_vwap
```
Детекторы читают `df["wt1"]` — не пересчитывают.

**Why:** 600 пар × 14 вызовов = 8400 вычислений за цикл на одних данных. Параметры всегда одинаковы (n1=10, n2=21, atr_period=43, factor=1.25).

**How to apply:** При любом рефакторинге scan_one или детекторов — pre-compute идёт первым шагом.

---

## Набор TF для scan_one и MTF (принято, не реализовано)

**Принятый набор — 6 TF:**

| TF  | limit | Назначение |
|-----|-------|------------|
| 3m  | 100   | wt_b crossing в mtf_signals |
| 5m  | 150   | trend_signals, MTF snapshot |
| 15m | 160   | entry TF, главный |
| 1h  | 160   | тренд-подтверждение |
| 4h  | 60    | cascade TSL, reversal scanner |
| 1d  | 150   | MTF snapshot, старший контекст |

**Убрать 45m из mtf_checker** (текущий список: `["3m","5m","15m","45m","1h","4h","1d"]`):
- 45m — нестандартный TF, покрывается 15m снизу и 1h сверху
- Только ради него нужен отдельный fetch вне pre-compute

**Пороги alignment под 6 TF:**
- `4/6 = 67%` ≈ смысловой эквивалент `5/7 = 71%`
- `5/6 = 83%` ≈ смысловой эквивалент `6/7 = 86%`

**1M TF** — только для pivot_calculator, не нужен в scan_one.

**Why:** Все 6 TF уже нужны в scan_one для разных детекторов → единый fetch покрывает всё без лишних запросов. 45m убирается без потери смысла MTF alignment.

**How to apply:** При реализации pre-compute слоя — использовать именно этот набор. Обновить mtf_checker.py: убрать "45m" из списка timeframes.
