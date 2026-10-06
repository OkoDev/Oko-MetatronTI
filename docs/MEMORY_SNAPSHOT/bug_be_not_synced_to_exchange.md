---
name: bug_be_not_synced_to_exchange
description: "🔴 КОРНЕВОЙ БАГ выхода — DEV-40 Breakeven двигает SL только в БД, на биржу НЕ синкается (live 11/12)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 0b9885d0-84da-4125-92df-2c24b01a41a7
---

# 🔴 DEV-40 Breakeven НЕ доезжает на биржу — корень exit-утечки (20.06.2026)

**Подтверждено на ЖИВЫХ деньгах** read-only чекером `e:/tmp/sl_sync_check.py` (get_open_orders per-account, сверка DB stop_loss vs биржевой STOP.stopPrice). Из 18 OPEN VST **прямо сейчас**: **11 GAP** (be=1 в БД, биржа на ИСХОДНОМ SL), **1 БЕЗ SL** (NAORIS — exchange_sl_order_id stale, живого стопа нет), 6 OK (все be=0). Закон: be=0→синк OK 6/6; be=1→**11/12 не доехали**.

## КОРЕНЬ (код)
`core/trading/trade_simulator.py:2230-2242` (DEV-40 BE): при `current_r>=breakeven_activation_r` (0.5) делает **ТОЛЬКО** `UPDATE simulated_trades SET stop_loss=?, be_activated=1` + локально `sl=be_sl`. **НЕ пишет в `tsl_moved`** (очередь биржевого синка, которую `update_tsl_on_exchange` cancel+replace кладёт на биржу). TSL-ветка пишет — BE НЕТ. Исходный bracket-SL остаётся висеть на бирже на исходном уровне (−1R).

## ПОСЛЕДСТВИЯ (3 фронта)
1. **РИСК занижен:** бот думает 11 позиций в безубытке (safe), реально они на полном −1R. NAORIS — без стопа вовсе (риск до ликвидации).
2. **Профит-утечка:** закрытая когорта be=1 но **39% R<0** ([[cont_setups_honest_exit_diagnosis]]) — это BE-фикция: биржа стопнула на исходном SL = убыток, хотя БД «защитил».
3. **Метрика врёт:** be_activated=1 ≠ защищён. Объясняет «BE-буфер net ноль» из [[be_exit_classification_findings]] — net не ноль, а −1R на части.

## ФИКС ✅ РЕАЛИЗОВАН going-forward (20.06, ждёт рестарт)
`trade_simulator.py` BE-блок (~2230): после DB-update BE теперь **append в `_ops05tsl`** (та же очередь что TSL) → `update_tsl_on_exchange` → `om.update_sl` cancel+replace со всеми guard'ами. Единый проверенный путь, БЕЗ дубля (reuse-закон). Гейт: реальный `exchange_order_id` + флаг `config.yaml trading.be_exchange_sync` (default true, false=откат). py_compile OK.
- **Почему НЕ Sphere.adjust_sl** (юзер выбирал его): adjust_sl не готов (place без cancel; Position без sl_order_id; store-fragility в shadow) и всё равно делегировал бы в этот путь → создал бы ВТОРОЙ путь синка (анти-цель). Миграция BE+TSL внутрь Sphere.adjust_sl = отдельный CUTOVER-шаг (двигать оба ВМЕСТЕ).
- ✅✅ **ВАЛИДИРОВАНО ЖИВЬЁМ end-to-end (20.06 23:23 UTC):** после рестарта 23:14 новые BE BUTTCOIN(id32693)/COLLECT(id32694) → лог `[DEV-40][BE-SYNC]` → `sl_sync_check`: биржа=DB BE (0.01868/0.05016). GAP=0 на 23 позициях. SIM (W/ZK/BARD) корректно пропущены (нет order_id). Цепочка целиком: BE→_ops05tsl→om.update_sl cancel+replace→биржа.
- ✅ **14 СУЩЕСТВУЮЩИХ GAP РЕКОНСАЙЛЕНО** (`e:/tmp/reconcile_be_sl.py`, юзер одобрил): cancel+replace SL→BE, place+cancel code=0, DB обновлён. GAP 14→0.
- NAORIS закрылся сам EXPIRED **R=−0.804** (id 32665, 20:04 UTC) — баг доказан вживую (be=1, но биржа на исходном → убыток).
- Связь корня с дуал-путём БД↔биржа: [[orphan_root_dbexch_desync]] [[cont_setups_honest_exit_diagnosis]] [[exec_ws_vst_userdata_proven]].

## КАК ПЕРЕПРОВЕРИТЬ
`python e:/tmp/sl_sync_check.py` (read-only, 2 запроса/акк, ордера не трогает) — печатает GAP/НЕТ SL/stale-ID по каждой открытой VST.
