---
name: bug_stop_loss_inverted
description: "✅ ЗАКРЫТО (ложная тревога) — stop_loss>entry при tsl=0 = ШТАТНЫЙ безубыток DEV-40 (be_activated=1), НЕ баг. memory смотрел только tsl_activated, пропустил флаг be"
metadata: 
  node_type: memory
  type: project
  originSessionId: 01a80823-46cc-4251-9bdf-bf45da105c68
---

✅ **РАССЛЕДОВАНО И ЗАКРЫТО (18.06.2026) — это НЕ баг, а штатный безубыток. Ложная тревога.**

**Симптом был:** LONG `stop_loss` ВЫШЕ entry (SHORT — ниже) при `tsl_activated=0`, original_sl верный, сдвиг ПОСЛЕ регистрации. ~1374 сделок.

**Корень (механизм):** DEV-40 Breakeven, [[ote_engine_full_map]] — `core/trading/trade_simulator.py:2192-2216`. После `current_r >= breakeven_activation_r` (config `breakeven_activation_r: 0.5`) выполняется `UPDATE simulated_trades SET stop_loss=?, be_activated=1`. Перенос через `tsl_engine.breakeven_sl()`: LONG=`entry*(1+0.001)` (выше entry), SHORT=`entry*(1-0.001)` (ниже). `DEFAULT_BE_BUFFER=0.001` = ровно 0.1%. Защита прибыли в безубыток+комиссия — by design.

**Почему memory ошиблась:** фильтр был по `tsl_activated=0`, а безубыток ставит ДРУГОЙ флаг — `be_activated=1`. TSL и BE — два независимых механизма, оба двигают `stop_loss`.

**Данные (боевая БД, 18.06):** инвертированных SL всего 10455. Разбивка: be=0/tsl=1 → 7547 (TSL трейл в прибыль); be=1/tsl=1 → 1531; **be=1/tsl=0 → 1336** (= те самые «~1374», штатный BE); be=0/tsl=0 → 41 (BE из марта 2026 ДО появления колонок be_activated/original_sl, потому флаги=0 и original_sl=NULL — исторический артефакт `confluence`, до data-era). Все 4 примера memory (CYBER#31300, WOO#31308, HIVE#31304, ACU#31259) = `be=1, tsl=0, sl/entry=+0.100%` ровно. Buffer всех be=1: LONG +0.100% (n=637), SHORT −0.100% (n=699).

**Реального риска НЕТ:** be=1 status=SL → avgR=**+0.309** (n=2034, 942 в [−0.2..0.2]) = защищённые выходы около нуля. Контроль (чистый стоп без защиты) avgR=**−0.901** (n=13503). Свежих (>15.04) инвертированных SL без флагов защиты = **0**. BE активируется на +0.5R → цена >> be_sl → `is_side_valid` (sl<цена) проходит, мгновенного хита нет.

**Урок:** при «аномалии stop_loss» проверять ВСЕ флаги-двигатели SL (be_activated, tsl_activated), не один. Связь: [[bug_phantom_exit_resolve]] (экстремумы R=−15/+40 в be=1 группе = ОТДЕЛЬНЫЙ fake-R фантом, в работе через миграцию, не относится к SL-стороне).
