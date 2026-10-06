---
name: structural-blindness-root-choch-length
description: "Структура была невидима майнингу — BOS/CHoCH в 1.3% сделок, 0 структурных флагов среди 75 в паттернах; корень — старший слой + примесь zigzag"
metadata: 
  node_type: memory
  type: project
  originSessionId: 6be29d28-5351-4bd1-8fa6-e6ec52dc3df7
  modified: 2026-09-02T20:40:47.963Z
---

🔴🔴 **СТРУКТУРНАЯ СЛЕПОТА МАТРИЦЫ — ЗАМЕРЕНА И ЗАКРЫТА (02.09.2026, C-01).**

Замер по **4 757 живым сделкам** (авг–сент, таблица `trade_features`), присутствие
семейства в снимке:

| семейство | присутствие |
|---|---|
| ATR/trend · WT · pivot · Donchian | 100% |
| RSI 92.7% · CMA 88.5% · **FVG 88.1%** | |
| Order Blocks | 36.4% |
| OTE/premium/discount | 19.6% |
| EQH/EQL · sweep | 3.4% |
| **BOS/CHoCH** | **1.3%** |

**Следствие, которое всё объясняет:** из **75 уникальных флагов**, набравших
статистику в 200 паттернах `config/arch104_patterns.yaml`, структурных —
**НОЛЬ**. Топ: `bull_fvg_1d` 46, `bear_fvg_1h` 44, `bull_fvg_4h` 35, pivot, rsi.
Ровно то, что Егор назвал сам: «из 75 уникальных только FVG, пивоты, RSI, ATR,
EMA и discount».

**Корень — прибор, а не рынок.** `swing_bridge.etl_bos_choch` брал ТОЛЬКО старший
слой (`arch104.choch_length=50`) и подмешивал туда `find_setups_zz`/`zigzag_atr` —
два движка писали в одни массивы. `bull_bos_1h` срабатывал **1 раз на 3 000 баров**
(0.03%). Ни одна комбинация с таким флагом не набирала n≥30.

**Лечение:** один двухслойный эталон `oko_sm_engine.run_structure(swing_len=50,
internal_len=5)` — см. [[smc_canon_engine_is_oko_sm]]. Старший слой сохранил имена
и семантику (сопоставимость со старыми замерами), микроструктура добавлена
отдельными флагами `bull_bos_i` / `bear_bos_i` / `bull_choch_i` / `bear_choch_i`
на каждом ТФ.

| | было | стало |
|---|---|---|
| структурных событий | 0.59% баров | **5.21%** (×9.8) |
| стоимость на 3000 баров | 19.8 мс | **9.8 мс** (примесь zigzag убрана) |
| `feature_snapshot.SCHEMA_VERSION` | 4 | **5** |

🔴 **Риск смены оказался нулевым:** 0 из 200 паттернов ссылались на bos/choch —
ломать было нечего. Блокер «не трогать, сломаем 187 паттернов» держался годами
на непроверенном допущении.

⚠️ Ре-майнинг структуры имеет смысл ТОЛЬКО на v5: на v3/v4 признака в данных
физически нет — [[law_no_finding_means_no_feature]].

Связано: [[matrix_covers_six_percent]] · [[detector_lag_is_a_parameter_not_statistics]] ·
[[feature_stores_two_layers_not_duplicates]]
