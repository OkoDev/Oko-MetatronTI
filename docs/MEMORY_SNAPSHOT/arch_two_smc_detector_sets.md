---
name: arch_two_smc_detector_sets
description: В проекте ДВА параллельных набора SMC-детекторов (smc_engine vs core.smc.fvg/order_blocks/structure) — риск «двух калькуляторов» ARCH-118
metadata:
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

В проекте ДВА параллельных набора SMC-детекторов:

1. **`core/smc/smc_engine.py`** — `detect_fvg`, `detect_order_blocks`, `detect_structure_breaks`, `zigzag_atr`, `detect_equal_levels`. Возвращают **tuple/dataclass** (FVG=tuple `(ts_left, top, bottom, kind, ts_i, mit)`, OrderBlock=class с `.kind/.top/.bottom/.mitigated_idx`). Используют: **chart_builder overlay, wave_chart_send, бэктесты** (`scripts/wave_smc_*`).

2. **`core/smc/fvg.py` + `order_blocks.py` + `structure.py` + `liquidity.py`** — `detect_fvg`→`FVGAnalysis(active_bull/active_bear)`, `detect_order_blocks`→`active_bull/active_bear`, `detect_structure`→`BreakType`. Используют: **`build_smc_snapshot`** (Сфера 4, ARCH-89) → Bus `smc_snap` → **`TPSelector._collect_magnets`** (ARCH-122, веса OB=3.5/EQL-EQH=3.0/FVG/Fib) → выбор TP1/TP2.

**Магниты бота** (зоны притяжения цены) = путь №2: `build_smc_snapshot(symbol, ohlcv_by_tf)` агрегирует MTF FVG/OB/EQL/Fib → `bull_fvg_active`/`bear_fvg_active` (поля `tf/top/bottom/mitigation_pct/age_bars`), nearest_OB, latest BOS/CHoCH.

**⚠️ Базовая формула gap идентична** (`low[i] > high[i-2]`), НО обёртки разные → результаты расходятся. **🔴 ЗАМЕРЕНО (09.06, `scripts/arch129_detector_parity.py`, 30 прогонов 15 пар×15m/1h):**

| Примитив | A зон | B зон | совпало | % | вердикт |
|---|---|---|---|---|---|
| **FVG** | 262 | 214 | 180 | **69%** | умеренный дрейф (A=auto-порог+без join; B=0.05%+join≤3) |
| **OB** | 201 | 93 | 15 | **7%** 🔴 | КАТАСТРОФА — почти не пересекаются |
| **structure** | — | — | 26/30 | **87%** | приемлемо, 13% на разворотах |

**🔴 OB = главная дыра:** чарт (A) и магниты TPSelector (B) показывают РАЗНЫЕ order blocks (7% пересечение). Юзер смотрит чарт, бот тянет к другому OB.

**🎯 КАНОН РЕШЁН ЭТАЛОНОМ OKO-SM (09.06):** спор «A или B» снят — [[reference_oko_sm_indicator|OKO-SM]] (Pine, эталон юзера) = арбитр. **A (smc_engine) ВОСПРОИЗВОДИТ эталон:** FVG порог auto (cum|gap%|×2), OB по ATR(200)-фильтру (LuxAlgo ob_coord = «спокойная» свеча high-low<ATR×2 в зоне свинг..пробой), ZigZag 1:1 (ARCH-128). **B ОТКЛОНЯЕТСЯ:** OB = последняя ПРОТИВОТРЕНДОВАЯ свеча по ЦВЕТУ (close<open)+volume_ratio (`_find_ob_candle`), FVG фикс-порог 0.05%+join. Разные критерии = 7% OB. **⟹ КАНОН = A (эталон). B → обёртки над A-расчётом, сохранив богатые поля (mitigation_pct/breaker/volume_ratio).**

**✅ ПАТТЕРНЫ НЕ ЗАТРОНУТЫ (проверено 09.06, grep):** `combinator_core.py:9,431` — combinator считает SMC через `swing_bridge → core.smc.smc_engine` = НАБОР A (эталон!). Значит **trade_features (211 фич, ARCH-118) + 187 паттернов arch104 + ML-train УЖЕ на каноне A** — re-mine/re-train НЕ нужен. **ДВА разных снимка:** (1) `trade_features` = combinator = A (паттерны отсюда, эталон ✅); (2) `smc_snap` Bus = `build_smc_snapshot` = B (магниты отсюда, отклонение ❌). Я их смешал — паттерны safe.

**⚠️ Реальный scope миграции B→A (УЖЕ, проверено по консьюмерам 09.06):**
| Консьюмер | Берёт | Критичность |
|---|---|---|
| `build_smc_snapshot`→магниты TPSelector | B OB/FVG/EQL | 🔴 ГЛАВНОЕ (прямо влияет на цели/TP) |
| `trading_intelligence` (ЯДРО) + pivot_reversal | **C** `indicators.detect_fvg` (ТРЕТИЙ FVG! 3 бара, БЕЗ порога=шум) | 🔴 ложные FVG-сигналы в ядре |
| `market_regime` | B `detect_structure` (13% дрейф) | 🟡 режим сдвинется |
| `cascade_tsl` DEV-221 `is_price_in_adverse_ob` | B OB | 🟡 ВТОРИЧНЫЙ force-close (только при r_gradient_drop де-эскалации, НЕ основной TSL) |
| `mtf_smc_specialist` | smc_snap B | 🟢 SHADOW (ждёт 200 сделок) |
| `liquidity_sweep_detector` | свои detect_liquidity/swing | ⚪ отдельная ветка |

**🔴 ВАЖНО: TSL trailing = ATR Trend (trendup/trenddown, `tsl_engine.compute_tsl`), НЕ OB!** OB в cascade_tsl только DEV-221 (вторичный force-close при де-эскалации). FVG = ТРИ калькулятора (A эталон-зоны / B зоны-отклонение / C indicators-триггер-без-порога). НЕ паттерны/ML (на A). **План:** (1) structure-канон A (корень OB-цепочки), (2) OB-канон A → магниты эталонные, (3) FVG-канон A (69%→100%), (4) проверить live B-консьюмеров (regime/specialist могли калиброваться на B-значениях). `scripts/arch129_detector_parity.py` = регресс-тест (7%→90%+ после).

**Why:** 09.06 при добавлении HTF-FVG на чарт юзер спросил «магниты же уже считаются?». Да — в TPSelector через snapshot. chart_builder/wave_chart_send рисуют HTF-FVG через smc_engine (та же формула, консистентно с остальным overlay), НЕ через snapshot.

**How to apply:** (1) для **live-торговли/магнитов** — путь №2 (snapshot→TPSelector); (2) для **чарта/бэктеста** — путь №1 (smc_engine); (3) **WAVE-WATCH** должен брать зоны из ОДНОГО источника что и бот (snapshot) — иначе сигналы канала ≠ магниты бота. (4) Архитектурный TODO: свести два набора в один `zone_provider` (или явно задокументировать какой канон). Перед правкой FVG/OB логики — править ОБА или вынести общее. → [[arch118_snapshot_decision]] инвариант «один калькулятор».
