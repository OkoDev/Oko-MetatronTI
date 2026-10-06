---
name: be_exit_classification_findings
description: "🔴 ДЫРА effective_status: чистый BE (be_activated=1,tsl=0) = LOSS хотя 84% не убытки. + BE-буфер 0.1%=net ноль + TP-магнит=shadow (не закрывает)"
metadata:
  node_type: memory
  type: project
  originSessionId: 01a80823-46cc-4251-9bdf-bf45da105c68
---

🔍 **Три находки по exit-классификации (18.06.2026, расследование «кривого SL»).** Контекст: [[bug_stop_loss_inverted]] (=безубыток, не баг).

**🔴 1. ДЫРА в `core/trading/effective_status.py` (главная, под фикс).**
`BE_area` распознаётся ТОЛЬКО при `tsl_activated=1` (строки 74 и 120 SQL CASE). Чистый безубыток (`be_activated=1, tsl_activated=0`) про флаг `be_activated` модуль НЕ знает → сваливается в `SL_clean`/`SL_slipped` = **LOSS**.
Масштаб (be=1,tsl=0,status=SL, n=943): 398 в BE-зоне R∈[−0.2..0.1] (≈ноль), 394 R>0.1 (профит!), лишь **151 (16%) настоящий убыток**; 27 fake-R фантомы. avgR этой «loss»-группы = **+0.45** (абсурд для loss).
Эффект честной классификации (data-era post-15.04, BE→neutral): WR `atr_change` 38.5→**43.0** (+4.5пп, be_n=586), `arch104` 47.7→**50.1** (+2.4, be_n=964), `ote_nested` 59.3→60.3; `avg_r_loss` честно ГЛУБЖЕ (стопы хуже без BE-нулей: atr_change −0.675→−0.840). Кормит `update_signal_weights` (wins/losses/avg_r) искажённо для BE-зависимых стратегий.
**✅ ФИКС РЕАЛИЗОВАН (18.06, НЕ активирован — ждёт рестарта юзера).** Решение юзера: расширить `effective_status` (реюз, не новый статус).
- `core/trading/effective_status.py`: +параметр `be_activated`; ветка чистого BE (`be_activated AND not tsl_activated AND R∈[-0.2, BE_AREA_BE_R_HIGH=0.35] → BE_area`; верх 0.35 шире TSL-BE т.к. buffer/тугой sl даёт R>0.1; >0.35 = fake-R фантом); обновлены `SQL_EFFECTIVE_STATUS_CASE`, `is_win`/`*_from_row`; новый фрагмент `SQL_IS_BE_NEUTRAL_CASE` (TSL-BE + чистый-BE → нейтрал).
- `core/trading/performance_engine.py` (summary + by_signal_type + by_signal_type_ema): `closed = tp+tsl+sl − be_neutral` (BE вне знаменателя, как EXPIRED); `avg_r_loss` исключает BE.
- `web/dashboard_server.py`: прокинут `be_activated` в `effective_status`.
- 🔴 ВАЖНО: торговые ВЕСА НЕ меняются — `update_signal_weights` строит factor из `avg_r` (`trading_intelligence.py:298`), где R сделок BE уже учтён. Фикс честнит ТОЛЬКО win_rate/losses/avg_r_loss (дашборд+диагностика). ML-метки (`is_win`) не тронуты в вызовах (BE там и так не win).
- Проверки: py_compile OK; 11 функц-кейсов OK; runtime на КОПИИ (`e:/tmp/subs_be_test.db`, online-backup): summary VST WR 48.5→**51.0%**, avg_r_loss −0.604→−0.666, be_neutral=613; by_signal_type atr_change 44.1→**49.9**, arch104 52.6→55.5. Сверка summary==ручной контроль ✓.
- ⏳ Активация: рестарт бота (юзер). Откат мгновенный (git). НЕ закоммичено.

**2. BE-буфер 0.1% = net ноль (без запаса).**
`DEFAULT_BE_BUFFER=0.001` (`tsl_engine.py:29`) фиксирует gross +0.1%; round-trip комиссия = 0.1% notional (`trade_simulator.py:1715` `qty×entry×0.001`). Ровно равны → net ≈ 0 (с проскальзыванием чуть минус). R в БД GROSS (комиссия в `total_fee` отдельно). Медиана sl_dist BE-сделок **1.21%** (p25 0.79, p75 2.10) → буфер 0.15%→+0.04R, 0.2%→+0.08R, 0.3%→+0.17R net на выбитой. Больший буфер = be_sl ближе к цене = чаще выбивает (теряешь раннеры).
**РЕПЛЕЙ-СТЕНД `e:/tmp/be_buffer_stand.py` (788 сделок, период 16.04–15.05, 45 пар, горизонт 2дня, БЕЗ TSL):**
- BE-механизм САМ ценен: NO_BE → 80.6% добиваются по SL, net −0.084; с BE → 33% SL (BE спасает ~47% от полного стопа), net −0.03..+0.06.
- Размер буфера 0.1→0.5%: %BE-выбиваний растёт 60.9→64.0, раннеры (run≥2) ПАДАЮТ 4.4→2.0%, avgR_net слегка растёт (−0.049→+0.062) но НЕМОНОТОННО (раннеры доминируют в avgR, буфер их режет). Текущий 0.1% локально даже чуть хуже 0.0%/0.15% — в пределах шума раннеров.
- ⚠️ WR_net скачок 7→67% при buffer>0.1% = АРТЕФАКТ (как только buffer>fee 0.1%, каждый BE-выход net>0); смотреть avgR_net, не WR.
- ВЫВОД: НЕ повышать буфер — выигрыш net микроскопический (+0.05R на выбитой) и съедается потерей раннеров (=главный PnL, [[milestone_clamp50_runners_proven]]). 0.1% оставить.
- ⚠️ Ограничения: история до 17.05 (старый sl_dist ~1%, не текущий тугой 0.44%); модель БЕЗ TSL + горизонт 2дня занижает раннеров. Для прод-решения — свежая история + TSL в модели. Тенденция (буфер режет раннеров) валидна.

**3. TP-магнит как exit НЕ реализован.**
`magnet_tp_price/rr/src` = SHADOW ARCH-122 P2 (`trade_simulator.py:249` «НЕ закрывает»; :840 «магнит НЕ перетирает take_profit»), заполнен psycho@-уровнями. Реальные выходы: `status` TP(avgR **1.23**, MFE 1.27)/TSL(**0.47**, MFE 0.98, captured 80%); `tp_source` различает магнит-структурный pivot_1D/ote (**1.73R**) vs механич rr/atr/arch104 (**0.92R**). «Раннер» отдельной категорией НЕ помечен — размазан: R≥3 по TP(317)/TSL(152, captured 80% честный трейл)/SL(88 = fake-R фантомы [[bug_phantom_exit_resolve]], R>MFE невозможен)/EXPIRED(31). Бэклог: runner-флаг + достроить magnet-TP shadow→реальный exit (ARCH-122 P3).
