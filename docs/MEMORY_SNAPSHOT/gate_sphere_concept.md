---
name: gate-sphere-concept
description: "🏛️ КОНЦЕПЦИЯ-КАНДИДАТ: GateSphere — единый слой ограничителей (гейтов), централизация (юзер 11.06)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

**GateSphere** — концепция-кандидат (юзер 11.06.2026): ВСЕ гейты/ограничители входа должны жить в ОДНОМ месте, централизованно. Продолжение [[principle_reuse_not_duplication]] для ОГРАНИЧИТЕЛЕЙ (не расчётов). Часть эпика **ARCH-129-FLOW** (юзер 09.06 голосовая: «централизованно хранить гейты, избегать перекрёстных вычислений»).

**Проблема (замерено 11.06):** гейты РАЗМАЗАНЫ по 10+ файлам.
- Логика проверок: `scan_loop` (HIGH_VOL/RANGE/strength_too_low/invalid_sl/cooldown/sideways), `monitoring` (dedup/sl_cooldown/btc_counter_trend/min_strength_register/hidden-div), `arch104_observer` (D-051), `trade_simulator` (register), confluence_scanner, wt_15m_reversal_scanner, trigger_loop, ml_loop, advisor_loop.
- ❗ **Учёт УЖЕ централизован:** `record_drop` → `core/observability/decision_trace` → `/api/dropped` (все пишут gate_name+count, видно в дашборде Gate Blocks). НО **логика проверок размазана** — чтобы понять «что блокирует вход на паре X», обойти 10 файлов.

**GateSphere (идея):** сфера ограничителей Куба —
- все гейты определены в ОДНОМ месте (имя, условие, вкл/выкл из config, приоритет)
- сигнал проходит **gate-chain** в одной точке (не размазанные `if`)
- `record_drop` (учёт) уже есть → добавить единую логику применения
- прозрачность: «вход прошёл/заблокирован гейтом Y» в одном трейсе

**Связь:** regime-v2 ([[regime_v2_validated]], D-10) = ПЕРВЫЙ кирпич (regime-гейты HIGH_VOL/RANGE — частный случай GateSphere). Одна болезнь сессии 11.06 в 4 местах: расчёты размазаны (OTE-импульс/CHoCH-length/regime) + гейты размазаны → лекарство = централизация ([[vision_cube_tesseract_singularity]]).

**Статус:** архитектурный вопрос «где место GateSphere в Кубе» → отдан рою 11.06 (team-ask). Решение о форме (единая сфера vs реестр+pre-trade chain vs Bus-интеграция) — после синтеза роя.
