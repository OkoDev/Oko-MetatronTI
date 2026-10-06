---
name: smc-two-parallel-implementations
description: "🔴🔴 ДВА ПАРАЛЛЕЛЬНЫХ SMC-НАБОРА в проекте: монолит `smc_engine.py` (64 КБ) и модульный `fvg/order_blocks/liquidity/swing_points/structure.py` (~66 КБ) дублируют ВСЕ 5 базовых детекторов. FVG вообще в ТРЁХ версиях с разными контрактами. `smc_snapshot.py` тянет из обоих — а он кормит ML-сферу 4 (AUC 0.180)"
metadata:
  node_type: memory
  type: project
  triggers:
    - detect_fvg
    - SMC детекторы
    - две реализации
    - дублирование кода
    - smc_engine
    - AUC 0.180
    - какой набор использовать
  originSessionId: ba54dcc8-d57e-4e24-aecf-62bb11c65e28
  modified: 2026-09-01T18:52:34.968Z
---

**Найдено 01.09.2026.** Егор: «других реализаций быть не должно, есть правила в проекте» —
повод был в том, что мой ручной анализ HYPE и боевой пайплайн видели РАЗНЫЕ FVG.
Нарушен [[principle_reuse_not_duplication]]. Всё ниже — grep, не память.

## Три FVG с разными контрактами

| Где | Логика | Возвращает |
|---|---|---|
| `core/indicators/indicators.py:206` | **только последние 3 бара**, без mitigation и порога | `('BULL'\|'BEAR'\|None, entry)` |
| `core/smc/smc_engine.py:540` | LuxAlgo: вся история, авто-порог значимости, mitigation по close | `List[tuple]` |
| `core/smc/fvg.py:259` | третий вариант | объект `FVGAnalysis` |

## Дублируется весь базовый набор

| Детектор | A — `smc_engine.py` | B — модульный |
|---|---|---|
| FVG | `:540` | `fvg.py:259` |
| Order Blocks | `:166` | `order_blocks.py:228` |
| Equal H/L | `:416` `detect_equal_levels` | `liquidity.py:240` `detect_equal_highs_lows` |
| Swings | `:71` `detect_swings` | `swing_points.py:252` `detect_swing_points` |
| Structure | `:103` `detect_structure_breaks` | `structure.py:342` `detect_structure` |

## Потребители разошлись, но НЕ по слоям

- **A**: `swing_bridge` (ARCH-128) · `chart_builder` · `oko_ote` · `ote_matrix` ·
  `ote_signal_generator` · `method_egor` · `method_v2` · `choch_wavec` · `choch_sl_transfer`
- **B**: `mtf_smc_specialist` · `pivot_reversal` · `liquidity_sweep_detector` · `cascade_tsl` ·
  `market_regime` · `confluence`
- 🔴 **`smc_snapshot.py` использует ОБА** — а он строит `smc_snap`, вход ML-сферы 4
- 🔴 **`pivot_reversal.py` импортирует две разные FVG в одном файле** (`:153` примитив,
  `:163` `_smc_detect_fvg`)

## 🔑 Гипотеза, которую это порождает (ARCH-137.2)

**AUC 0.180 у MTF SMC Specialist** ([[ml_spheres_worse_than_coinflip]]) может объясняться
рассогласованием: модель учится на признаках `smc_snap`, собранного из ДВУХ наборов, а метки
берёт со сделок, порождённых стратегиями набора A. «FVG» в признаке и «FVG» в сигнале —
разные функции с разной логикой mitigation.

Проверка дешёвая: пересобрать `smc_snap` на ОДНОМ наборе → переобучить. Перешёл 0.5 —
причина найдена, сфера 4 оживает без нового кода.

## Практическое правило до починки

Ручной анализ и замеры вести на **наборе A (`smc_engine`)** — он LuxAlgo-порт с mitigation
и порогом, и на нём же стоят стратегии и `chart_builder`. Никогда не использовать
`indicators.detect_fvg` — это не FVG по канону, а проверка трёх последних баров.

**Why:** три ответа на один вопрос означают, что «SMC не работает» никогда не было измерено —
мерили разными инструментами. Ср. [[smc_in_matrix_is_dead_weight]].
**How to apply:** перед любым замером SMC печатать, из какого модуля импортирован детектор.

Задача: `TASKS.md` § ARCH-137. Связано: [[gap_positioning_layer_missing]],
[[okosm_trend_depends_on_window]], [[detector_lag_is_a_parameter_not_statistics]].
