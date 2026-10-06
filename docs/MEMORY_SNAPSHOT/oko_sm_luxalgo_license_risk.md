---
name: oko_sm_luxalgo_license_risk
description: "🔴 IP: OkoSM v163 (эталон структуры Куба) — производная от SMC LuxAlgo (CC BY-NC-SA 4.0, некоммерческая): 76 совпадений конструкций, дословные группы настроек, в заголовке «© yogoru» без указания LuxAlgo. Блокирует продажу всего, что показывает результат OKO-SM"
metadata:
  node_type: memory
  type: project
  originSessionId: ea98197f-5cfa-4b48-ab76-1b2fcebf5d0d
  modified: 2026-09-26T13:43:25.210Z
---

Проверено 26.09.2026 grep'ом по `docs/reference/OkoSM_v163.pine` (2 199 строк): 76 совпадений с
конструкциями SMC LuxAlgo (`Strong High/Weak Low`, `trail_up/dn`, `swings()`, группа настроек
«Real Time Internal Structure» дословно). `OkoSM_choch_formation.pine` — 7 совпадений. Лицензия оригинала
(TradingView, «Smart Money Concepts (SMC) [LuxAlgo]») — CC BY-NC-SA 4.0: указание автора, некоммерческое
использование, та же лицензия для производных. `core/smc/oko_sm_engine.py` — построчный порт (память 23.07).
От него зависят SMC-детекторы ARCH-137, `core/waves`, волновой аналитик, канал Oko_Waves.

Уточнение 26.09: в Pine v163 строки 1162–2199 (~47% файла) — скрипт SMC LuxAlgo целиком, со всей раскладкой
разделов; строки 1–1161 — слой Егора (фракталы с пометкой `WICK.ed` — чужой сниппет, лицензия не выяснена).

**Решение Егора 26.09:** переписать всё без кода LuxAlgo (Python + Pine), сначала паритет, потом своё.
**Фаза 5 (26.09):** слои OKO — OTE на ноге (канон fibonacci.py), цели по пивотам Егора (flat_target / боевой _pivot_2nd),
ноги DC (dc_legs 3.0×ATR43): `core/structure/layers.py` + группа «Слои OKO» в Pine-блоке; тесты 6/6; сверка на графике — ждёт TV.
**Фаза 4 сделана (26.09):** порт удалён, `oko_sm_engine`/`smc_engine` — фасады над `core/structure`, потребители на новых
именах; поведение 261/261 отпечатков. 26.09 16:12 процессы pm2 перезапущены, псевдонимы сняты, страж
`test_no_legacy_names_in_production`. Остаются слепки TV-скрипта с блоком LuxAlgo в `docs/reference` (v163, tv169) — до загрузки v200 в TV.
**Фазы 2–3 сделаны (26.09):** `core/structure/levels.py`, `zones.py` — паритет 324/324 проверок со старыми
функциями `smc_engine`; Pine-блок `docs/reference/OkoSM_structure_block.pine`, сборка `OkoSM_v200.pine` на основе
текущего TradingView v169 (копия `OkoSM_tv169.pine`: слой Егора 1–1138, LuxAlgo 1139–2197, хвост «RSI Дивергенции»
2198–2519 — происхождение не выяснено). Паритет Pine ↔ Python по меткам графика: SOL 1h 474/474, BTC 4h 426/426.
В TradingView v200 НЕ загружен — решение Егора (алерты на именах LuxAlgo сломаются). Фаза 4 (перевод боя) — с подтверждения.
**Фаза 1 сделана:** `core/structure/` по `docs/STRUCTURE_KERNEL_SPEC.md`; `scripts/structure_parity.py` — 108/108 пар,
191 162 слома, 100% совпадение; тесты `tests/unit/test_structure_trace.py`. Дальше фазы 2–5 (см. спецификацию).

**Why:** монетизация индикаторов, терминала, волновых разборов на OKO-SM = коммерческое использование
некоммерческой производной. Идеи/алгоритмы обычно не защищены, текст кода — защищён; построчный порт ближе к
производной (не юридическое заключение).
**How to apply:** до коммерческих продуктов — clean-room структурный слой на стандартных фракталах с перемером
паритета, либо договорённость с LuxAlgo, либо OKO-SM только бесплатно/внутренне. Продукты без OKO-SM
(проверка эджа, методика, режим/доминации/радар) — свободны. Связано: [[oko_sm_engine_ported]],
[[product_portfolio_audit_26sep]].
