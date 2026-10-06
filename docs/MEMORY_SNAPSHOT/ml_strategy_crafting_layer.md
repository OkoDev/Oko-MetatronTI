---
name: ml-strategy-crafting-layer
description: "🤖 ВЕКТОР (Егор 01.07): арсенал детекторов готов в коде (12+) → подключить ML-слой для авто-крафта стратегий ВМЕСТО ручного перебора комбо. Детекторы=фичи, ML находит edge-комбинации + feature importance. НО target=% net (НЕ R, закон №1), LightGBM (НЕ чат-LLM), walk-forward OOS. r_predictor уже провалился (R²<0) — но он предсказывал R. Это Слой 2 — питается ручным feature-discovery"
metadata:
  node_type: memory
  type: project
  originSessionId: 03741574-3261-416f-94b1-b4b7c6de6735
---

**ВЕКТОР «ML-слой крафта стратегий» (Егор 01.07.2026). Мотив: «всё уже готово в коде» — арсенал
детекторов огромен, пользуемся фрагментарно. Подключить ML/отдельную модель для авто-крафта.**

## Арсенал-фичи (всё в коде, готово)
```
Структура: detect_structure_breaks (CHoCH/BOS) · detect_swings · find_setups_zz
Зоны:      detect_order_blocks (OB) · build_ote/find_choch_ote (OTE)
Неэффект.: detect_fvg · detect_fvg_overlap (imbalance)
Ликвид.:   detect_equal_levels (EQH/EQL) · sweep
Свечи:     detect_sponsored_candle (SC)
Волны:     detect_elliott_impulse/mtf
Осцилл.:   WT (wt_cross) · RSI (rsi_div bull/bear regular/hidden)
Тренд:     supertrend (atr_change)
Уровни:    pivots (weekly/daily) · gravity-магниты
Контекст:  режим (weekly-bias), ТФ, dist-to-pivot
```
features_json УЖЕ пишется на каждую сделку (ARCH-118 снимок признаков) → датасет почти готов.

## ⚠️ Уроки (почему НЕ наивный ML)
- **r_predictor УЖЕ провалился**: R²<0 (хуже naive), не обобщает = шум. KFold-leak маскировал, честный
  TimeSeriesSplit → провал. См. memory ML-честность.
- **НО корень провала — предсказывал R** (закон №1: R=мусор!). На **% net** ML ещё не учили.
- **Чат-LLM галлюцинирует на числах** → ТОЛЬКО LightGBM/XGBoost (CPU, интерпретируемо).
- _TRUTH: confluence-COUNT механический = плоско (conf0..5 все ≤0) — но мерили в R и как СЧЁТ, не контекст.

## Правильный ML-слой (с учётом законов)
```
Target:    % net = profit% − costs%   ← НЕ R ([[principle_measure_pct_not_r_LAW]])
Features:  детекторы (бинарные/числовые) + контекст (режим, ТФ, dist-to-pivot)
Модель:    LightGBM (feature importance/SHAP → ВИДНО какие детекторы несут edge)
Валидация: walk-forward OOS (НЕ KFold — leak), OOS-gate (бьёт baseline или мусор)
Costs:     в target (fee×N + slip + funding)
```
**Ценность:** feature importance отвечает прямо — «FVG@pivot реально важен? atr_change+режим? иллюзия?»
Превращает «много инструментов» → «знаем какие 3-5 несут edge».

## Граница (честно)
Crypto = шум доминирует (R²<0 не случаен). Edge может быть слишком слаб для ML после costs.
Но target % net + OOS-gate = честная проверка; даже отрицательный итог = знание, не вера.

## Порядок (КЛЮЧЕВОЕ — это Слой 2, не сейчас)
**ML без знания ЧТО класть в фичи + без чистого target = r_predictor №2 (мусор→мусор).**
- **Слой 1 (сейчас, РУЧНОЙ):** крафт+валидация в % net (atr_change, смысловая конфлюэнция FVG@pivot) →
  находит ЖИВЫЕ фичи + отлаживает методологию target % net (income, не БД-R).
- **Слой 2 (потом, ML):** LightGBM на тех же чистых фичах + % net → авто-комбинации/масштаб.
Ручное исследование ПИТАЕТ ML (feature discovery + чистый target). Не наоборот.

**Why:** Куб «Strategy Evolution» — ML крафтит стратегии из готового арсенала. Но методология > модель
(_TRUTH): сначала правильный target (% net) + OOS + знание живых фич, потом модель. Иначе r_predictor №2.
**How to apply:** не запускать ML пока (а) target не переведён на % net из income, (б) ручное исследование
не выявило 3-5 живых фич/контекстов. Связь: [[principle_measure_pct_not_r_LAW]] · [[ote_production_drift_root]] · [[income_ledger_db_overstates_realized]].
