---
name: bug-fvg-overlap-held-lookahead
description: detect_fvg_overlap held-флаг сканирует close до конца ВСЕГО переданного df (не до бара j) — lookahead в бэктестах compute_flags(full_df) + перф-бомба на больших df (5m/много баров)
metadata: 
  node_type: memory
  type: project
  originSessionId: 03741574-3261-416f-94b1-b4b7c6de6735
---

`detect_fvg_overlap` (core/smc/smc_engine.py:585,595): `held = all(close[j] >= lo for j in range(i0+1, n))` — `n` = длина ВСЕГО переданного df, не бар оценки. Для live (df=история до «сейчас») это корректно («held до сейчас»). Для бэктеста, где `compute_flags(df_break, break_tf)` зовётся ОДИН раз на ПОЛНЫЙ df_break (месяцы истории) и потом индексируется `flags_df.iloc[j]` для разных j << n — `fvg_overlap_held` на любом j отвечает «held до конца ВСЕЙ истории», а не «held на момент j» → лёгкий lookahead в признаке `fvg_held` (1 из 6 confirmations в [[oko_ote_torn_from_context]]/`_confirmations_bt`).

Та же функция — и перф-бомба: nested-loop bulls×bears, для каждой overlap-пары `all()` сканит close до n. На 5m (148k баров vs 24k на 15m) это доминирующий cost (~126s из ~307s профиля на BTC/USDT 4h→5m, наравне с исправленным [[bug_last_confirmed_pivot_quadratic]]).

**Why:** обнаружено при оптимизации oko_ote.py бэктеста под confs≥3 на 5m break_tf (24.06, сессия после "проверяй 5м" Егора). Затрагивает ВСЕ прошлые confs≥N бэктесты (4h→15m, 4h→1h), не только 5m — просто на меньших df эффект для замечен/менее заметен.

**How to apply:** НЕ менять `detect_fvg_overlap`/`smc_engine.py` напрямую (живая семантика для live корректна, риск дрейфа). Если нужен честный point-in-time `fvg_held` в бэктесте — считать ЛЕНИВО на truncated-slice `df.iloc[:j+1]` per-сетап (как уже сделано для `div_rev` в oko_ote.py и `_get_snap` far-magnet), не на полном df_break сразу. Сейчас в oko_ote.py НЕ исправлено — confs≥3 результаты (4h→15m 47 сделок, 4h→5m в работе) используют как есть; эффект скорее всего малый (1 из 6 флагов, confs нужен ЛЮБОЙ комбо из 3), но к строгой переоценке вернуться после основной 5m-валидации.
