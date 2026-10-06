---
name: bug_ote_sl_near_entry_r_explosion
description: 🔴 КРИТ-БАГ ote_nested — SL вплотную к entry (<0.3%) взрывает R и position_size; SIM-метрики ≠ реальный баланс
metadata: 
  node_type: memory
  type: project
  originSessionId: 3743ba62-3271-4099-bf28-5bf1be14a516
---

🔴 **КРИТИЧЕСКИЙ БАГ (найден 14.06.2026 юзером: «+207R раннер, а баланс только снижался!»).**

**Симптом:** ote_nested SIM показывает sumR +682R/день (раннеры +207R HOME, +66, +50), НО реальный баланс обоих VST-аккаунтов ~$500 (не вырос, снижается).

**Корень — SL ставится ВПЛОТНУЮ к entry** (за свечу реакции/OTE-ногу), иногда на НЕВЕРНОЙ стороне:
- HOME LONG: entry=0.029893, **stop_loss=0.029954 (ВЫШЕ entry для LONG!)**, R=207.55, **max_R_possible=1.815**, captured_R_pct=11435% (мусор).
- `R = profit / |entry−SL|` → SL≈entry → risk_distance→0 → **R взрывается** (207 вместо реальных 1.8).
- `position_size = risk / |entry−SL|` → SL≈entry → **размер позиции ×2** (notional avg 73 vs 36) → реальный риск выше.

**Масштаб (13.06, n=436 ote_nested):** 123 сделки (28%) с SL<0.3% от entry → sumR +438R ФЕЙК из +682. 4 из 5 топ-раннеров (208R@0.205%, 66R@0.079%, 50R@0.28%, 34R@0.112%) = артефакт.

**Двойная недостоверность SIM↔баланс:**
1. SL≈entry → R и position_size взорваны (деление на ~0).
2. R/profit_pct СИМУЛЯТОРНЫЕ (симуляторный TSL-trailing/exit) ≠ реальный биржевой PnL. Раннеры +207R = виртуальный TSL, на бирже STOP_MARKET закрывает иначе/раньше. **Баланс — единственная истина.**

**⚠️ СЛЕДСТВИЕ:** вся «доказанная» раннер-статистика ote_nested (clamp50, [[milestone_clamp50_runners_proven]] SKYAI/ONDO) могла быть на фейк-R (SL≈entry). Решения на SIM-R/profit_pct НЕНАДЁЖНЫ — сверять с реальным балансом/биржевым PnL.

**ФИКС (TODO, приоритет):**
1. Guard min risk_distance: SL минимум ~0.5-1% от entry (иначе skip/расширить SL).
2. Валидация стороны SL (HOME LONG SL>entry = невалидно, отсекать — `is_side_valid` где-то не срабатывает для ote_nested).
3. Реальный учёт PnL: биржевой closed PnL, не симуляторный R/profit_pct.
4. Ретро-аудит: пересчитать ote_nested без SL<0.3% — реальный edge (чистые SL>=0.3%: +244R, но и это симуляторное).

Связано: [[feedback_verify_metric_semantics]], [[feedback_metrics_hygiene]], db_illusions_audit. R_multiple НЕ достоверен при tight/inverted SL.
