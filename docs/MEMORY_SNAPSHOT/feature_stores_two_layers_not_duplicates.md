---
name: feature-stores-two-layers-not-duplicates
description: "trade_features и features_json — не дубли, а разные слои; пересечение имён 1 из 488; для рыночных признаков брать trade_features"
metadata: 
  node_type: memory
  type: project
  originSessionId: 6be29d28-5351-4bd1-8fa6-e6ec52dc3df7
  modified: 2026-09-02T20:41:10.800Z
---

🔑 **ДВА ХРАНИЛИЩА ПРИЗНАКОВ — РАЗНЫЕ СЛОИ, НЕ ДУБЛИ** (замер 02.09.2026).

Пересечение имён между ними — **1 из 305/488**. Они отвечают на разные вопросы:

| слой | вопрос | листьев | покрытие |
|---|---|---|---|
| **`trade_features`** (ARCH-118, канон) | что было НА РЫНКЕ: combinator-флаги SMC/WT/RSI/ATR/EMA/pivot по ТФ | **488** | **98–100%** с июня |
| `simulated_trades.features_json` | как ПРИНИМАЛОСЬ решение: тайминги, роутинг, гейты, macro, `ds_*`, `soft_penalties` + `smc_snap`/`wt_snap` | 379 | мета 100%, snap-блоки **10%** |

🔴 **Для майнинга рыночных признаков брать `trade_features`.** Медиана `n_total`
там **362** признака на сделку против **42** top-level в `features_json`.
Вопрос «почему признаков мало» решается сменой таблицы, а не починкой снапа.

**Почему `features_json` обеднел — это НЕ регресс, а решение ARCH-118:**
`arch118.write_table: true` → снимок переехал в таблицу, «features_json НЕ
дублируется». Покрытие `smc_snap` в нём: апрель 62.7% → июнь 4.2% → сентябрь 0%.

**Но остаточный дефект реален:** `smc_snap`, `wt_snap`, `narrative` и плоские
SMC-поля кладёт в `recommendation.metadata` ТОЛЬКО `analyze_symbol`
(`trading_intelligence.py:1115`). Стратегии через `trade_router` со своим
`recommendation` приносят metadata без них — все четыре блока падают **синхронно**.
За июль-сентябрь обогащено 10.2% сделок; 100% у `confluence`/`monitoring`/
`pivot_reversal`/`event_bus`/`wt_signal`, **0%** у `atr_change` (4794),
`wt_sideways` (3773), `wl_breach` (2083), `ote_nested` (1810), `radar`,
`impulse_fib`, `rangefade4h` — то есть у всего, что реально торгует.

⚠️ **Нельзя чинить «взять snap из шины»**: в шине (`state.smc_snap` от
`build_smc_snapshot`) схема ПЛОСКАЯ + `by_tf`, а в ML-снапе `{tf: {...}}` от
`_build_smc_snap_from_df`. Положить одно под именем другого = смесь схем под
одним ключом. Каталог шины это описывал НЕВЕРНО до 02.09 — исправлено.

**Документы:** единственный каталог набора — `docs/FEATURE_CATALOG.md`.
`FEATURES_JSON_AUDIT.md` — история решения (май 2026, числа устарели),
`MATRIX_REGISTRY.md` — карта модулей-источников.

Связано: [[structural_blindness_root_choch_length]] · [[matrix_covers_six_percent]]
