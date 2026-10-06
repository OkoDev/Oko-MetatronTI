# 🔴 КОРЕНЬ orphan'ов: рассинхрон БД↔биржа (2 механизма)

18.06: при рестарте PID 31536 (22:45 МСК, sl_reconcile=live) детектор D-070 нашёл **14 orphan-позиций** на VST-бирже без OPEN-строки в БД (AKT, AUCTION, CLO, JASMY, ORDI, PEOPLE, PIEVERSE, POLYX, REAL, SIREN, SOMI, STX, TAO, XNY). Статический бэклог (новых за ~10 мин нет). Всё VST/paper, реальные деньги не затронуты.

**Два механизма копления (доказано БД+код):**

**A. SIM-orphans (6: JASMY/PEOPLE/REAL/SIREN/SOMI/XNY)** — `execution_mode=SIM`, `exchange_order_id=None`, `exchange_sl_order_id=None`. Код считает SIM чистой симуляцией БЕЗ биржевой позиции (`trade_simulator.py:1938` SIM-TIME-EXIT, коммент «биржевые НЕ трогаем»; `close_trade` трогает только БД). Но позиции на бирже есть. **REAL: вся история SHORT с 13.06 — SIM, ни одной VST** → биржевую позицию qty 53.2 не создавала ни одна DB-сделка. БД закрывает SIM-строку (SL по цене / time-exit 48ч) → позиция на бирже остаётся → orphan. = утечка на слое исполнения (смешение SIM/VST, [[exec_sim_split_epic]]).

**B. VST-orphans (8: AKT/AUCTION/CLO/ORDI/PIEVERSE/POLYX/STX/TAO)** — реальные VST (`exchange_order_id`=Y, у большинства был `exchange_sl_order_id`). БД закрыла TP/SL, позиция на бирже выжила. = **close-confirmation gap**: закрытие по цене/REST-поллингу без реального reduceOnly-флэта.

**REAL = учебный случай для SL-reconcile:** shadow ~час орал «REAL SHORT без SL» (17:18→19:17 МСК), затем БД закрыла SL по цене (`arch104:swing_15m`), реального SL-ордера не было ни разу → не закрылась → голый orphan. Прошлая сессия активировала reconcile, ожидая что REAL получит SL после рестарта, но REAL закрылся в БД (16:17 UTC) за ~3.5ч ДО рестарта → стал orphan → цель валидации испарилась.

**Вывод:** `sl_reconcile: live` БЕЗОПАСЕН (ошибок place нет, откат не нужен), но **бессилен против orphan'ов by design** — лечит только VST с живой OPEN-строкой (тянет SL из `simulated_trades WHERE status='OPEN'`; у orphan'а её нет → `_db_sl=None → continue`). `[live]` не сработал = (1) отслеживаемые VST уже с SL (здорово), (2) orphan'ы неэлигибельны.

**Лечение НЕ в reconcile, а на слое исполнения:** подтверждать реальный флэт через WS executionReport ([[exec_ws_vst_userdata_proven]]), не доверять цене; гарантировать что SIM не оставляет позиций на бирже. D-070 пока только алертит — расширить до adopt/close ([[adopt_manual_trades_vision]]).

**Cleanup СДЕЛАН (19.06):** `scripts/close_orphans.py --commit` закрыл **17** (набор подрос: +BABY/DOGE/KNC/PROVE/SCRT). Биржа 50→33, orphans=0. Патч: close-цикл стал account-aware (`_resolve_position_client`+positionId+`one_click_on_fail=True`) — был sticky-client (КОРЕНЬ 101205). Все code=0 (one-click fallback после 101205 hedge).

## ПРОФИЛАКТИКА — точный диагноз + дизайн (19.06)

**Safety-net УЖЕ есть и account-aware:** `position_sync._emergency_close_check` (103-263) — симулятор детектит exit VST-сделки → LIVE-GUARD ждёт `live_guard_timeout_min=7` → если биржа держит → emergency close (`_resolve_position_client`+positionId+one-click fallback, строки 215-235) → close БД. Срабатывает (232× в логе, успешно для JOTCHUA/FF).

**🔴 ТОЧНЫЙ ПРОБЕЛ root B:** строка 222 `close_position_market(...)` → при code=0 **сразу** закрывает БД (255), **НЕ верифицируя что позиция реально флэт**. Частичный fill / one-click code=0 без полного флэта → БД закрыта, позиция висит → orphan. Для AUCTION #31194 (17:42) / STX #31257 (19:46) emergency сработал, но «БД закрыта после emergency» в логе НЕТ → не до-флэтнул.

**✅ Кирпич 1 РЕАЛИЗОВАН (19.06, shadow, ждёт рестарта):** D-070 `_detect_orphans` (position_sync.py:647) alert→**auto-close**, config `trading.orphan_autoclose: off/shadow/live` (паттерн sl_reconcile). Hedge-safe: skip символов с DB-OPEN (`_ac_open_syms`) — one-click задел бы брата; pure-orphan → `_resolve_position_client`+positionId+`one_click_on_fail=True`. py_compile+config-read OK, pydantic чисто. Дефолт shadow=zero-risk → мониторить `[D-070][autoclose][shadow]` → флип live. ⚠️ НЕ закоммичено.

**Кирпич 2 (корневой):** verify-flat-after-close в `_emergency_close_check` — после close ре-фетч позиции, qty≈0 ПЕРЕД close БД; иначе retry, БД не трогать. ⚠️ риск ghost (false «держит» → DB OPEN при флэте) → нужен авторитетный ре-фетч.

**Root A (SIM-утечка) — источник НЕ диагностирован:** откуда биржевая позиция у SIM-сделки (order_id не захвачен при исполнении? позиция до split?). Отдельная задача.

DS советовал #21 свежей сессией (контекст тяжёлый). Live-правку close-логики — только после дизайн-ревью (discuss→verify→act).
