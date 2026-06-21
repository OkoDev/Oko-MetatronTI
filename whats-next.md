# What's Next — Handoff

## 🔧 СЕССИЯ 22.06 (ИНФРА, НЕ бот-логика) = Continue/Ollama + почин зацикленного Stop-хука

> ⚠️ Сессия = личная инфра (редактор Continue) + диагностика/фикс зацикленного Stop-хука. **Кода бота НЕ трогали.** Если работаешь над ботом — мотай ниже к «СЕССИЯ 21.06 (читать ПЕРВЫМ)».

**<original_task>** Подключить новую локальную модель `LONGTIMEDEVELOPERS/deepseek-v4-pro-qwen_russian` в Continue вместо DeepSeek R1 14B. По ходу: добавить qwen, убрать лишние конфиги, удалить r1:14b с диска, разобрать настройки контекста, обсудить роль DS без платного DeepSeek, починить зациклившийся хук.

**<work_completed>**
- **Continue `c:\Users\yogoru\.continue\config.yaml`:** модель `deepseek-r1:14b` → `LONGTIMEDEVELOPERS/deepseek-v4-pro-qwen_russian:latest` (точный тег из `ollama list`/манифеста `registry.ollama.ai/LONGTIMEDEVELOPERS/...`; короткий `deepseek-v4-pro-qwen_russian` НЕ резолвится). Добавлена 2-я модель `qwen3:8b`. Обе: roles chat/edit/apply, `contextLength: 16384`, temp 0.3. Правило «только русский» сохранено.
- **`contextLength` оставлен 16384 осознанно:** железо 2×8 GB (GTX 1070 + GTX 1080). Модель 4.5 GB + KV-кэш ~2.3 GB (≈150 КБ/токен fp16) влезают на одну карту. 32768 ≈ 4.6 GB кэш — впритык/спил. 256K (потолок модели) ≈ 36 GB KV = невозможно. qwen3:8b = 5.2 GB, 5.2+2.3≈7.5 GB, впритык в 8 GB.
- **Удалено:** `e:/MTF BOT/CURSOR/crypto_volume_bot/.continue/agents/new-config.yaml` (дефолт-пример «Example Config») + `new-config-1.yaml` («DSv4 Config» — юзер сам сделал, но тег `deepseek-v4-pro-qwen_russian` БЕЗ префикса/тега + `contextLength: 256000`). Папка `.continue/agents/` теперь пуста. Модель `deepseek-r1:14b` снесена с диска (`ollama rm`, ~9 GB). В Ollama осталось: deepseek-v4-pro-qwen_russian:latest (4.5 GB) + qwen3:8b (5.2 GB).
- **DISCUSSION.md — 3 добавленных записи (это бот-репо!):** `[21.06 00:55] DS → РОЙ/Даат` (консенсус на тред 0→A→B→C: A добит коммитами, CUTOVER пауза, ревиз. порядок A-перемер→B→0→C); `[22.06 01:20] DS → Даат` (ДА, нужен start/end на `/api/income` для post-fix split; acceptance перемера в net $, per-account, min 10); `[22.06 01:30] Даат → команда ✅` (закрытие треда). Опора: git log (`e762449`/`05d644b`/`77fd649`/`e86a3e8`) + сами записи, без выдуманных чисел.
- **Хук-петля диагностирована и пофикшена (проверено эмпирически):** корень — `scripts/check_tasks.py` (роль из env `AGENT_ROLE=DAAT`, `.agent_role`=DAAT) блокирует stop, если верхняя запись адресована роли и выше нет записи этой роли (строки 113-117). Каждая запись одной роли создаёт «долг» другой → пинг-понг DAAT↔DS. Фикс: закрывающая запись `Даат → команда` (адресат «команда» вне `ROLE_ALIASES`+`BROADCAST`) гасит долг DAAT без нового долга DS. Проверено: `AGENT_ROLE=DAAT` и `AGENT_ROLE=DS python scripts/check_tasks.py` → оба `{"decision":"approve"}`.
- **Роль DS (решение юзера):** DeepSeek кончился по балансу (−¥0.53, июнь ¥114.52 / 1.4 млрд токенов). НЕ переключать конфиг — при пополнении DeepCode подключится обратно. Пока DS = Opus (канон по [[team-topology]]: DS=Opus 4.8, DeepSeek=подключаемый сверху). DeepCode/`AGENTS.md` НЕ трогали.

**<work_remaining>** Нет — сессия закрыта, всё подтверждено. Опц. гигиена (не срочно): хук видит **50 «простыней» >200 симв в TASKS.md** → `python scripts/tasks_tidy.py --apply`.

**<critical_context>**
- `whats-next.md` = боевой handoff бот-проекта; НЕ перезаписывать целиком (потому добавил раздел сверху, а не overwrite).
- Тег Ollama-модели брать ТОЛЬКО из `ollama list`/манифеста — имя на странице модели («deepseek-v4-pro») вводит в заблуждение: локальная 4.5 GB = ~8B qwen-файнтюн, НЕ настоящий облачный DeepSeek V4 Pro.
- `contextLength` в Continue Ollama-провайдере транслируется в `num_ctx` → завышение = OOM/спил.

**<current_state>** ✅ Continue настроен (2 модели, 16384). ✅ Лишние конфиги + r1:14b удалены. ✅ Хук-петля разорвана (approve для DAAT и DS). ✅ DS на Opus до пополнения. Бот-логику НЕ затрагивали (жив, рестарт 21.06 21:46 UTC — см. раздел ниже).

---

## 🌅 СЕССИЯ 21.06 = EXIT-FIX ДОБИТ (BE на биржу) + ИСТИННЫЙ BE + CUTOVER пауза (читать ПЕРВЫМ)

> Русский · grep before claim · числа из config/кода · TTS Irina · ветка `arch-128-oko-sm`. Метрика-истина = income-ledger/`o.rp`.
> Глубокий контекст: `current_state.md` (записи 21.06 сверху) + auto-memory [[bug_be_not_synced_to_exchange]], [[ote_all_setups_honest_map]], [[cutover_blocker_ws_closefill]].

**ГЛАВНАЯ ПОБЕДА: найден+починен КОРЕНЬ exit-утечки (реальные деньги).** DEV-40 Breakeven двигал SL **только в БД**, на биржу НЕ доезжал → биржа держала исходный SL (−1R). Live-доказано `e:/tmp/sl_sync_check.py`: 18 OPEN VST → 11 GAP, NAORIS закрылся −0.8R при «безубытке». Это и был give-back (закрытая когорта be=1 но 39% R<0).

**✅ ПОЧИНЕНО+ЗАПУШЕНО+ПОДТВЕРЖДЕНО вживую (5 коммитов):**
- `e762449` **BE синкается на биржу** (append в `_ops05tsl` → om.update_sl cancel+replace). Подтверждён: BUTTCOIN/COLLECT, GAP=0 на 23 поз. Флаг `trading.be_exchange_sync`.
- **Реконсайл 14 GAP** (`e:/tmp/reconcile_be_sl.py`) — GAP 14→0.
- `05d644b` **BE от `actual_entry_price`** (не сигнальной).
- `77fd649` **BE = тугой STOP-LIMIT 0.15%** (per-order `be_limit_buffer_pct`). Подтверждён: AVA buf=0.15%. TSL держит 1%. = «истинный BE» (actual_entry+комиссия+тугой лимит).
- `e86a3e8` **entry-capture: дотянуть avgPrice по orderId** когда синхр.ответ дал 0 (~2%) +WARNING. Дыра была таймлайн-деплоя, не баг; post-fix 94% реальный филл.
- ✅ TSL подтверждён (`[TSL-UPDATER] ✅`).

**📊 ПЕРЕМЕР 7 OTE-сетапов (честный R)** → `ote_all_setups_honest_map.md`: **ЗАКОН SHORT=pull (0.47→1.585), LONG=cont_1h_5m (0.694)**, крест мёртв. ⚠️ avgR был от сломанного выхода → **перемерить через 3-5 дней на post-fix** перед обрезкой. cont SHORT держим (юзер).

**🔴 CUTOVER — НЕ флипать (юзер: ПАУЗА, путь A):** «?» застрял **75%**, корень = WS close-fill `o.rp` ловится лишь **25%** (гонка fill↔pa=0 + one-click 101205). Флип без fallback = 75% орфанов. B (P&L-fallback) отклонён. **Эпик A** = починить WS close-fill capture. [[cutover_blocker_ws_closefill]].

**СЛЕДУЮЩЕЕ:** (1) через 3-5дн перемерить cont/pull на post-fix → отрезать мёртвый крест; (2) Эпик A (WS close-fill capture); (3) trade_simulator split (EXEC-SIM-SPLIT, имя врёт — делает реальное исполнение); (4) опц. backfill stragglers actual=NULL.

**Инструменты (read-only, e:/tmp):** `sl_sync_check.py`, `reconcile_be_sl.py`, `check_goblin.py`. **Бот:** жив (рестарт 21.06 21:46 UTC, все фиксы активны).

---

## 🌅 СЕССИЯ 19-20.06 = EXEC-REBUILD + ДЕНЬ ПРАВДЫ (свежий handoff, читать ПЕРВЫМ)

> Думать/писать по-русски · grep before claim · числа из config/кода · TTS Microsoft Irina · ветка `arch-128-oko-sm`.
> **🔑 МЕТРИКА-ИСТИНА: `/openApi/swap/v2/user/income` + WS `o.rp`, НЕ БД-realized (врёт ~$323/день, инвертирует знак!).**
> Глубокий контекст: `memory/current_state.md` (записи 20.06, сверху), auto-memory [[income_ledger_db_overstates_realized]], [[condor_integration_strategy]].

**ЧТО ПРОИЗОШЛО (одним абзацем):** Построен весь **EXEC-REBUILD Ф2→Ф4.1** (`core/execution/`: domain/ExchangeAdapter/BingXAdapter/ExecutionCalc/PositionStore/ExecutionLedger[DS]/ExecutionSphere/db_writer/reconcile-watchdog), **92 теста**, ~26 коммитов запушено. SHADOW-врезка живёт (on_close=None). Дёрнули **income-леджер → ВСКРЫЛАСЬ ЛОЖЬ МЕТРИК:** БД-realized +$121 vs биржа −$202 (06-19); **ote_nested за 6д реально NET −$510**, а БД показывала +$230 (инверсия знака $654). funding≈0 (прежняя −$266 атрибуция неверна). Диагноз: **вход ЖИВОЙ (48% до +1R, среднее MFE 1.31R), выход УБИВАЕТ (46% SL дошли +1R→отдали), плечо 50×→ликвидации.** Стратегия НЕ мёртвая — фиксимо. Всё на бумаге (VST), реальных потерь 0.

**✅ ПОЧИНЕНО за сессию (активно/запушено):**
- **l3 VST-only** (`trade_simulator.py:1231`) — FIRE снова регистрируются (47 SIM-теней забивали лимит 50/50 → блок). АКТИВНО.
- **orphan SIM-masking** (`position_sync` tracked_pairs только биржевые) — SIM не прячет призраков.
- **orphan_autoclose:live** (стоп течи), **fake-R** positionID, **r_predictor OOS-gate** (был шум → честно off), **SL-safety кап**.
- **DB↔биржа синхронны** (10/10, 0 призраков/orphan на момент закрытия).

**🔴 СТАРТ СЛЕДУЮЩЕЙ СЕССИИ (finish-line этого Куба, BingX-direct standalone):**
1. ✅ **Ф5 дашборд-когезия (СДЕЛАНО 20.06, коммит f91e379):** шапка↔таблица Trades = один WHERE (get_summary status-aware + «showing X of N»). Деплой+проверка: SL/VST 14135→8154. ⏳ Остаток (TASKS 🔵): шапка `POSITIONS` vs таблица 17 vs 11 (DASH-COH-SWEEP), RISK base $1189 vs equity $750, OPEN-вкладка live-R (DASH-OPEN-SUM).
2. ✅ **CUTOVER pid-fix + флип ЗА ФЛАГОМ ГОТОВЫ (СДЕЛАНО 20.06):**
   - pid-fix (б) ✅ коммит 4efe297: `sphere._resolve_exit_via_rest` при pid=None → None (не угадывает, инверсия TP↔SL убрана). Часть (а) — positionId в store — УЖЕ была. +тест. Активен с рестарта (PID 22124).
   - CUTOVER-флип ✅ коммит 37f1f7f: флаг `trading.exec_ws.sphere_cutover` (default **false**). true → Sphere авторитетен (on_close=build_close_applier) + ВЫКЛ старые пути (exec_ws 2b sync_close + position_sync close-by-price). copy-DB смоук 6/6 MATCH.
   - **🔴 ПРОЦЕДУРА ФЛИПА (deliberate, после зелёной сверки):** (1) DS/грепнуть `[SPHERE-SHADOW] WOULD CLOSE` — % с чистым exit (фейк-inverted теперь «?»); (2) зелено → `config.yaml sphere_cutover: true` + рестарт; (3) грепать `[SPHERE-CUTOVER]` + `[db_writer] #id … → status` (реально закрывает) + `[EXEC-WS][2b] … cutover SKIP` + `[POSITION-SYNC] close-by-price OFF`; (4) сверить БД↔биржа 10/10; откат = `false`+рестарт.
3. 💰 **EXIT-FIX (рычаг ПРИБЫЛИ):** вход живой → выход отдаёт +1R. BE уже фирит на +0.5R (`[DEV-40]`), но +1R всё равно отдаётся → анализ НА o.rp: BE/TSL медленные vs интрабар? трейл? частичный TP? Цель: из −$510/6д в плюс. Перемерить edge на income/o.rp многодневно.

**🔒 РЕШЕНИЕ (юзер 20.06, твёрдо):** этот Куб доделываем **сами, standalone, BingX-direct**. **Condor = отдельный Cube2** (НЕ интегрировать сюда). Проект «наш с тобой» (Егор+Даат). [[condor_integration_strategy]].

**Бот:** жив (рестарты ~03:40:52 + SIM-masking). Поток ote_nested→биржа течёт. SPHERE-SHADOW копит сверку.

---

## 🏛️🔴 АРХИВ — старт сессии 19.06 (EXECUTION-REBUILD манифест, ниже — что ставили в начало)

## 🏛️🔴 НОВАЯ СЕССИЯ = EXECUTION-REBUILD (манифест юзера 19.06 вечер: «хватит латать, перестраиваем»)

> **ГЛАВНОЕ ТЗ:** [docs/EXECUTION_REBUILD_EPIC.md](docs/EXECUTION_REBUILD_EPIC.md) — читать ПЕРВЫМ.
> Pre-flight: + `docs/BINGX_WS_ACCOUNT_SPEC.md` + skills `.agents/skills/bingx-swap-ws-account/api-reference.md` + `current_state.md` (19:04 запись).
> Думать/писать по-русски · grep before claim · числа из config/кода · TTS Microsoft Irina. Ветка `arch-128-oko-sm`.

**Юзер сформулировал (19.06 вечер):** хватит заплаток — деньги утекают всё равно (VST −48%/нед = REST −$435 мимо стратегии). Нужна ПЕРЕСТРОЙКА: (1) отделить SIM от VST (SIM изжил себя, VST=боевая песочница=истина, разные БД); (2) единые узлы входа/выхода/мониторинга вместо 8 лоскутов (WS=истина, REST close-by-price убрать); (3) дашборд-редизайн (чёткое разделение биржа/БД, время open/close, нормальные ID — сейчас «табличка со смешанными режимами»).

**Корень всех дыр (доказано 19.06):** два конкурирующих источника закрытия — WS `pa=0` (истина) ∥ REST `position_sync:504` close-by-price (по 15s-кэшу, ложно→призраки). + account-хардкод (`:364`) + не юзаем WS `o.rp/o.n/FUNDING_FEE/LIQUIDATION`. Всё = лоскутное исполнение. Карта 8 узлов + фазы перестройки → в ТЗ.

**✅ Ф1 (docs/API-меню) ЗАКРЫТА:** установлен `BingX-API/api-ai-skills` (27 skills, swap-trade/account/ws-account) + WS-спека выжата.

**✅ Ф2 (дизайн) ЗАКРЫТА 19.06 ~16:25 → [docs/EXECUTION_SPHERE_DESIGN.md](docs/EXECUTION_SPHERE_DESIGN.md):** контракт ExecutionSphere (open/close/on_event/adjust_sl/state) + ExchangeAdapter ABC + PositionStore + ExecutionLedger; доменная модель биржа-агностик; правило-истина закрытия (§6: только WS pa=0, close-by-price `position_sync:501-654` УДАЛИТЬ); карта поглощения 8 узлов (§8); порядок миграции Ф3.1→Ф5 (§9). **4 развилки (§10) на ревью ARCH/рой.**

**✅ Ф3-Ф4.1 ПОСТРОЕНЫ И ЗАПУШЕНЫ (19.06 вечер, 14 коммитов, origin/arch-128-oko-sm):** весь слой `core/execution/` (domain · adapter ABC · BingXAdapter · ExecutionCalc · PositionStore · ExecutionLedger[DS] · ExecutionSphere · db_writer), **88 тестов**, copy-DB close-path зелёный. Аудит BingXClient (`docs/BINGX_CLIENT_AUDIT.md`). SHADOW-врезка в живой WS (`exec_ws.sphere_shadow:true`) активна — Sphere прогоняет WS параллельно старому 2a/2b, `on_close=None` (только лог `[SPHERE-SHADOW]`, position_sync close-by-price НЕ тронут).

**✅ ПОБОЧНО: течь призраков ОСТАНОВЛЕНА** — `orphan_autoclose: live` (BNB+Q закрыты по positionId, проверено). **DS forward-сверка 3/3** (WOULD CLOSE = реальный [EXEC-WS][2b]). 2 shadow-находки закрыты: is_open_fill (hedge-retry close) + гонка fill↔pa=0 (REST exit-fallback).

**✅ CUTOVER-готовность ДОСТРОЕНА (19-20.06, 19 коммитов запушены):** детект close (DS 3/3✅) + exit-резолв (stash o.ap ✅ + REST-fallback по positionId на гонке ✅, валидирован ZEREBRO real exit) + **reconcile-watchdog** (`Sphere.reconcile_watchdog`+`PositionStore.drop`, §6 bounded-staleness, врезан shadow в `position_sync` throttle 2мин) — страховка для «?»-exit/WS-drop остатка. 2 shadow-находки закрыты (is_open_fill hedge-retry + гонка fill↔pa=0). Побочно: **течь призраков остановлена** (orphan_autoclose:live) + **#7 ML-честность** закрыт (r_predictor OOS-gate).

**🔵 СТАРТ следующей сессии = эмпирическая валидация → CUTOVER:**
1. **Рестарт** (активирует exit-fallback + reconcile-watchdog в shadow). Грепать `[SPHERE-SHADOW] WOULD CLOSE` (real exit?) + `[SPHERE-SHADOW] RECONCILE` (ловит ли «?»-остаток).
2. **DS: % WOULD CLOSE с непустым exit** + watchdog ловит ли остаток. ~100% покрытие (stash+REST+watchdog) → зелёный.
3. **CUTOVER (deliberate, discuss-before-act):** в `exec_ws_integration` за флагом `exec_ws.sphere_cutover`: `Sphere(on_close=build_close_applier(trade_simulator))` + reconcile-watchdog escalated→sphere.close/db_writer + гейт `position_sync:501-654` close-by-price OFF. 🔴 повторный copy-DB тест перед флипом. Откат = флаг.
4. ПОТОМ Ф5 дашборд-split (биржа/БД/SIM).

**⏳ ПЕРЕД перестройкой (висит):** PUSH накопленного (≈8 файлов заплаток + доки, см. current_state). Симптом призраков НЕ закрыт (`orphan_autoclose: shadow`). Бот жив PID 31496 (рестарт #3, 19:04).

**Заплатки сегодня (НЕ путать с корнем, в ТЗ §8):** SL-кап, OTE-CASCADE shadow(+fix регистра), balance_history кэш, exchange_history/trades_filtered масштаб(lev/size/$), fake-R/leverage/margin-mode.

---

## 📦 АРХИВ — handoff начала сессии 19.06 (CASCADE/OTE — поглощён эпиком выше)

> ⚠️ Этот блок сгенерирован `/whats-next` в СВЕЖЕЙ сессии (19.06, после 09:20 UTC), в которой ещё НЕ было своей работы — он СИНТЕЗ актуального состояния из `whats-next.md` (предыдущий топ), `memory/current_state.md` и `DISCUSSION.md` (запись DS 09:20). In-session работы для захвата нет. Старый топ переоформлен в структуру `/whats-next`, детальные архивы ниже — без изменений.
> Думать/писать по-русски · grep before claim · числа из config/кода · TTS Microsoft Irina после задач.
> Ветка `arch-128-oko-sm`. Бот **жив** (рестарт #5 ~04:12 local 19.06, leverage-enforcement активен). DEV/ARCH отдыхают — пара Даат + DS.

<original_task>
Парная сессия Даат + DS (19.06). По ходу дня закрыты: убийство fake-R (фантомные exit), активация Режима В (OTE-ONLY), 3 косяка плеча, оживление дашборда. К концу дня сформирован **главный открытый вектор**: DS-прогон на паркетах показал, что 1D-сетапы как самостоятельный сигнал (CLONE) экстремально редки → CLONE хороним. Даат разделил CLONE (самостоятельный сигнал) и CASCADE (1D-тренд как ФИЛЬТР на каждый ote_nested-вход) — CASCADE НЕ редок (частота = ote_nested). DS подтвердил разделение (DISCUSSION 09:20 UTC). **ПЕРВЫЙ ШАГ НОВОЙ СЕССИИ: Даат строит SHADOW 1D-трендфильтр на каждый ote_nested FIRE.**
</original_task>

<work_completed>
**1. fake-R УБИТ** ([[bug_phantom_exit_resolve]]): колонка `position_id` (`core/db/subscription_manager.py` CREATE TABLE + миграция-loop) + захват при открытии (`core/exchange/tsl_updater.fetch_and_save_position_id`, retry 3×2с) + спавн задачи захвата (`trade_router._place_exchange_order`) + **positionID-якорь в `position_sync._resolve_exit`** (PRIMARY-матч close-side FILLED той же позиции, ВЫШЕ orderId/эвристики symbol+side, прокинут в 3 пути + WS). Миграция боевой БД: `scripts/migrate_fakeR_positionid.py --commit --with-exchange`, бэкап `subscriptions.db.fakeR-bak-20260619-023649` (304МБ). Итог: **Tier1 3956 истинных exit + Tier2 clamp 26 + карантин 40** (R>10 MFE=None → R/profit=NULL + `fakeR_quarantine=1`, 447.5R яда снято). STG #31400 R **+323.6→−1.13**. avgR базы +0.108→−0.045. **ote_nested честный avgR +0.474** WR61% (был 0.846, net ~+0.2-0.3R). positionID-захват подтверждён вживую (#31453-31457 несут колонку).
**2. Режим В OTE-ONLY** (config.yaml): risk 0.5%, leverage 50×, l3-гейты активны (max_total_risk 25%, shadow→false). Изоляция: `signal_router.source_policies` все false кроме ote_nested + `default_policy` off (убил liquidity_sweep catch-all). **arch104 + atr_change ОТКЛЮЧЕНЫ** (честный R оба минус: arch104 LONG −0.182/SHORT −0.050, atr_change LONG −0.083/SHORT −0.183). **arch104 ЗАКРЫТ окончательно** (перемайн = data mining на −0.05R, DS+Даат согласны).
**3. 3 косяка плеча** (юзер нашёл): (a) per-source (`SourcePolicy.leverage/risk_pct`, None→глобал fallback; `trade_router._place_exchange_order` читает из `ctx.policy`); (b) кламп к max пары (`order_manager._get_pair_max_leverage`, кэш+TTL 1ч); (c) факт-в-БД (колонка `leverage`, `BracketResult.leverage`=ФАКТ, trade_router UPDATE) + дашборд из факта (bus→БД→config, не «перекрашивает» старые живым конфигом). Файлы: `source_policies.py`, `trade_router.py`, `order_manager.py`, `bingx_client.py`, `subscription_manager.py`, `config.yaml`, `dashboard_server.py`. Проверено: новые позиции БД-плечо = биржа.
**4. margin-mode**: acc2 был массово CROSS (бот архитектурно ждёт separate_isolated для positionId) → юзер переключил дефолт + я закрыл 15 cross-балластных позиций account-aware (`close_orphans`/`one_click_on_fail`). **orphan'ы = 0.**
**5. Дашборд** (репо `oko-dashboard`, коммит `f0613d5`): шапка R+$ на ОДНОМ множестве (VST-приоритет, SIM-тень вторична), дедуп дублей позиций (`fetchLivePositions` по symbol+direction). + оживление analytics-экрана (см. ниже).
**6. Дашборд analytics оживлён:** корень «полумёртвости» = `/api/stats/analytics` таймаутил (6 агрегаций/29K без кэша под локом с write-циклом) → весь экран на mock ($undefined, MFE 0/0). Фикс: `_ANALYTICS_CACHE` (TTL 60с + detached) + `signal_weights/history` туда же + фронт-гард `{!!d.usd}`. Активно после рестарта.
**🛡️ Дисциплина дня:** 5 раз «красивое число → проверка → потом» поймала фантом ДО боя: fake-R · SL-за-FVG (бэктест опроверг, тугой SL net-оптимален) · WT-сюрприз DS (узкий-SL+n=3) · arch104 (data mining) · OTE-CLONE +0.710 (=fake-R от 08.06, DS подтвердил).
**DS подтвердил CLONE≠CASCADE** (DISCUSSION 19.06 ~09:20 UTC): CLONE → в архив с arch104; CASCADE → Claude строит SHADOW, DS валидирует дельту на live; batch-оптимизация generate() НЕ нужна.
</work_completed>

<work_remaining>
**🔪 ПЕРВЫЙ ШАГ — SHADOW 1D-CASCADE трендфильтр (Даат строит, DS меряет):**
1. На каждый ote_nested FIRE считать 1D-тренд: fetch `get_ohlcv(sym,'1d',60)` напрямую → `calculate_trend` на ~60 1D-барах (НЕ полный generate/price-in-zone). Корень «1d не фирит» = `ote_observer_loop:99` 1h limit=300 → всего 12 1d-баров < 50 нужных; генератор НЕ сломан, live-фикс = 1 строка после подтверждения edge.
2. Логировать `would_block` если вход контр-тренду 1D + дельту R.
3. DS меряет на live-потоке: режет ли фильтр убыточные контр-трендовые. Валидация ФОРВАРДОМ (shadow), НЕ batch-backtest.
4. Edge есть → гейтим (live); нет → закрываем CASCADE.

**✅ SL-SAFETY КАП ПЛЕЧА — РЕАЛИЗОВАН 19.06 (~09:35 UTC), ждёт рестарта.** Третий слой leverage в `order_manager.open_bracket` (после кап-пары, ~473): `leverage = min(req, pair_max, floor(1/(sl_dist + buf)))`. Config `trading.liq_safety_enabled:true` + `liq_safety_buffer_pct:0.5`. Только СНИЖАЕТ плечо (qty уже посчитан запрошенным → риск корректен, маржа выше=безопаснее). py_compile+config-load OK. Симуляция на 5 живых VST: ловит ТОЛЬКО POPCAT (50×, SL 2.75% → liq 1.9% < SL) → **50→30×** (liq 3.33% > SL); остальные 4 не тронуты. **🔴 РЕСТАРТ нужен** для активации; откат = `liq_safety_enabled:false`. Незакоммичено: `order_manager.py`, `config.yaml`. Контекст: юзер нашёл на SEI; ⚠️ биржевой SL расходится с БД `stop_loss` (TSL/BE двигает) — но кап работает в момент открытия (sl=исходный), это верно. [[ote_tight_sl_validated]] × leverage.

**WT-REVERSION (параллельно, SHADOW-first):** P5/200b +10R = артефакт узкого SL (0.05%), +2.5R фильтр = n=3. Даат добавляет `wt_pct` shadow-фичу в ote-пайплайн, копим на чистом потоке n≥30-50; DS перепрогоняет P5/200b на прод-SL 0.5%.

**⏳ Бэклог:**
- exec-sim-split (полный, эпик [[exec_sim_split_epic]]) — дашборд-каша = его симптом.
- Orphan кирпич 2 (verify-flat в `_emergency_close_check`) · margin-enforce кирпич (бот ставит isolated перед открытием — 136 пустых cross-символов acc2; `grep marginType/set_margin`=пусто, бот НЕ управляет margin-mode) · acc1 cross (114 конфиг).
- Push: main `02beb18` + analytics-кэш + dashboard `f0613d5` + analytics.tsx — НЕ запушено, по отмашке юзера.
- ⏳ визуально подтвердить, что календарь/MFE на дашборде ожили после рестарта.
</work_remaining>

<attempted_approaches>
- **OTE-CLONE (1D как самостоятельный сигнал)** — DS-прогон на паркетах: единицы fires за 2.4 года/пару (0 fires на 10 парах × 8 дней). Даже honest +0.39R не спасает — частота убивает. ХОРОНИМ (как arch104). НЕ оптимизировать generate() под batch — решение не той задачи.
- **arch104 перемайн** — DS+Даат: data mining на −0.05R, редкое-отрицательное не стоит инженерии. ЗАКРЫТ.
- **config_ote_V.yaml (DS-черновик Режима В)** — НЕ применял: был неполный/опасный (cp снёс бы конфиг, ключи мимо, не изолировал source_policies). Применил Режим В вручную через правки config.yaml.
- **SL-за-FVG** — бэктест опроверг, тугой SL net-оптимален ([[ote_tight_sl_validated]]).
- **fake-R через orderId-матч** (прошлая сессия) — ломался после cancel+replace (exchange_sl_order_id устаревал → матч брал старый ордер от 12.06). Решение = positionID-якорь (устойчив к cancel+replace).
- Tier3 MFE=None монстры (R>10) — clamp бессилен (max/min=NULL) → карантин (R/profit=NULL).
</attempted_approaches>

<critical_context>
- **Цель** ([[vision_bot_as_anchor_against_emotion]]): бот = якорь против эмоции; путь к $1M через компаундинг → выживание/ruin первично. SL-safety кап = прямой инструмент против ruin.
- **CASCADE ≠ CLONE** — ключевое разделение дня: CLONE = 1D-сетап как сигнал (редок, мёртв); CASCADE = 1D-тренд как фильтр на КАЖДЫЙ ote_nested-вход (частота ote_nested, дёшев). Не путать.
- **fake-R теперь честный** — ote_nested avgR +0.474 (не 0.846). Любые выводы о compounding/режимах — только на этом честном R. Старые «+0.7..+0.8R» = фантом.
- **Биржевой SL ≠ БД `stop_loss`** — TSL/BE двигают биржевой ордер; DB-проверка маскирует SL-safety проблему. Смотреть `raw.liquidationPrice` vs реальный SL-ордер.
- **margin-mode дрейф молчит** — бот НЕ ставит isolated (`grep marginType`=пусто); 136 пустых cross-символов acc2 откроются cross при новой сделке. Нужен кирпич ENFORCE.
- **execution_mode:** SIM⟺order_id NULL, VST⟺order_id есть. Обучение (`performance_engine`) фильтрует VST → SIM-фантомы вне весов.
- **Правила:** прогон main не трогать (рестарт = юзер); register/INSERT-путь → runtime-тест на КОПИИ БД ([[feedback_ast_parse_no_scope]]); биржевое → BingX docs/код сначала ([[preflight_exchange_task]]); русский; TTS Irina; data-era split post-15.04.
- **oko-dashboard НЕ git** — фронт осторожно, отдельный коммит.
- VST = бумага (не горит реальными деньгами) → SL-safety кап безопасно отлаживать в VST, но обязателен перед LIVE.
</critical_context>

<current_state>
- **fake-R:** ✅ убит (код + миграция боевой БД + карантин), ✅ подтверждён вживую, активен с рестарта #5.
- **Режим В OTE-ONLY:** ✅ применён (config.yaml), активен. arch104 + atr_change off, arch104 закрыт.
- **3 косяка плеча:** ✅ исправлены, проверено БД=биржа, активны с рестарта #5.
- **margin-mode:** ✅ acc2→isolated, ✅ orphan'ы=0. ⏳ enforce-кирпич в бэклоге (дрейф повторится).
- **Дашборд:** ✅ R+$ одно множество + дедуп (f0613d5), ✅ analytics-кэш. ⏳ визуально подтвердить календарь/MFE.
- **ote_nested темп:** ✅ здоров (72/час, 257/6ч; «мало открытых» ~11 = быстрый churn). Гейты Режима В с запасом.
- **SHADOW 1D-CASCADE:** 🔵 НЕ начат — ПЕРВЫЙ ШАГ новой сессии (Даат строит, DS меряет дельту на live).
- **SL-safety кап плеча:** 🔵 НЕ начат — критично перед LIVE, место известно (`order_manager.open_bracket`).
- **WT-REVERSION:** 🔵 shadow-first, не начат.
- **Git:** main `02beb18` (+ analytics-кэш) + dashboard `f0613d5` (+ analytics.tsx) — ⏳ НЕ запушено. DS-конфиги (`config_loader/validator/pydantic`) uncommitted, НЕ трогать. Бот жив (рестарт #5 ~04:12 local).
- Точка остановки логическая. Эта сессия (`/whats-next`) своей работы не вела — handoff = синтез состояния.
</current_state>

## 📦 АРХИВ прошлого handoff (SL-reconcile ✅ проверен выше) — #21 EXEC-SIM-SPLIT

> Думать/писать по-русски · grep before claim · числа из config/кода · TTS Microsoft Irina после задач.
> Ветка `arch-128-oko-sm` (запушена, ahead 0). Бот рестартнут 18.06 ~22:30 UTC (PID 31536, sl_reconcile=live).

### 🔴 ПЕРВЫЙ ШАГ (validation pending — активировано биржевое действие `0e96325`)
**Проверить `[SL-RECONCILE][live]`:** `grep -a "SL-RECONCILE\]\[live\]" logs/crypto_bot.log | tail`
- Ожидание: REAL/USDT SHORT (sl≈0.061912) + KAT/USDT SHORT (sl≈0.005315) получают SL (oid=…) в 1-м цикле reconcile (~5мин после старта).
- ⚠️ Если ошибки place (account / qty / precision / «No position») → ОТКАТ: `config.yaml trading.sl_reconcile: live → shadow` + рестарт. Loop account-aware (`arch96.multiaccount=true`, роутер по symbol), но live на бою ВПЕРВЫЕ — подтвердить.
- Чисто выставлены → #1 закрыт окончательно. Loop: `position_sync.sync_positions:386-420` (throttle 5мин).

### ЗАДАЧА: #21 EXEC-SIM-SPLIT (🔴 `docs/BACKLOG_CONSOLIDATED.md` #21)
**Первый шаг — сводка DEV-52 shadow-логов** (копятся с 18.06):
`grep -aE "\[DEV-52\]\[(RISK|MARGIN)\]" logs/crypto_bot.log` → частота would_block + распределение risk%/available per-account (acc1/acc2).
Далее: калибровка порогов (`trading.l3_checker.max_total_risk_pct=10`, `min_available_usdt=5`) → активация (`risk_gate_shadow:false`/`margin_gate_shadow:false` + рестарт, откат мгновенный). Память [[exec_sim_split_epic]]. Полный контекст эпика — в handoff EXEC-SIM-SPLIT ниже.

### ✅ Сделано сессию 18.06 вечер (Даат) — 6 коммитов, ЗАПУШЕНО (arch-128-oko-sm)
- `bce5d47` **классификатор BE** — безубыток вне win_rate (`effective_status` +be_activated → BE_area нейтрал; `performance_engine` closed−=be_neutral) + фикс `/api/kpi` 500 (datetime naive/aware смешан). WR VST 48.5→51.0 (копия). ВЕСА НЕ затронуты (update_signal_weights по avg_r). [[be_exit_classification_findings]].
- `0e96325` **#1 SL-reconcile LIVE** (loop был shadow, account-aware) — ↑проверить первым шагом.
- `ceb1380` NOTIF-TIER2 уведомления, `1edd2cf` роль-инфра, `a6eb622` gitignore `*.bak*`, `ef186d1` доки.
- Расследование «кривого SL» ЗАКРЫТО = штатный безубыток (НЕ баг) [[bug_stop_loss_inverted]]. BE-буфер 0.1% НЕ трогать (стенд `e:/tmp/be_buffer_stand.py`: режет раннеры). Git чист (research-зона DS 93 untracked не трогал).
**Бэклог:** runner-флаг + magnet-TP shadow→exit (ARCH-122 P3); ARCH-104 перемайн на честном R; свежая parquet-история (>17.05) под стенды; atr_change→4h.

───────────── ниже: handoff DS-326 (DEV, другой вектор) ─────────────

## 🆕 Сессия 18.06.2026 (DEV / Opus 4.8) — DS-326 ЗАКРЫТА (research)
> Коммиты: `6b2cda1` → `1108201` → `60c06d6` (ветка `arch-128-oko-sm`, НЕ запушено). Боевой код НЕ тронут (чистое исследование, бот не запускался).

**DS-326 (WT-B дивергентный edge) — ЗАКРЫТА с честным негативным вердиктом:**
- ADX<25 (1h→15m) = единственный gross-фильтр +0.204R, OOS устойчив (2024 +0.302, 2025 +0.304; walk-forward IN +0.233/OUT +0.175). 4h-намёк отброшен (режим-зависим).
- TSL: crude(0.5R) чемпион; боевой hybrid/trend-based хуже для контртренда wt_b.
- 🔴 **РАЗВОРОТ:** +0.204 = артефакт узкого бэктест-SL 0.3%. R считается от SL → узкий SL раздувает R вчетверо. На прод-SL 0.5% gross→**+0.048**, net после комиссии BingX → **−0.145**. **Торгуемого edge НЕТ.**
- 🧭 **МЕТОД-УРОК (для всех бэктестов проекта):** R фантомен при узком SL — фиксировать прод-SL перед выводом. Память [[feedback-backtest-realistic-sl]]; проверка `python scripts/ds326_fees.py --min-sl 0.005 --max-sl 0.02`.
- Отчёт: `data/research/ds326_wtb_filters_result.md` (в `.gitignore`, локально). Скрипты: `scripts/ds326_{all_filters,edge_levers,tf_matrix,oos,fees}.py` (закоммичены).
- **Следующей сессии:** DS-326 НЕ открывать заново. Если копать wt_b — только прод-SL + maker-выход (TP лимиткой) + combo (SHORT+div5-12) + ликвидные пары, и то net тонкий.

───────────── ниже: предыдущий handoff EXEC-SIM-SPLIT (ДРУГОЙ живой вектор, 17-18.06, Даат) ─────────────

# What's Next — Handoff (EXEC-SIM-SPLIT, сессия 17-18.06.2026, Даат / Opus 4.8)

> Свежей сессии: прочитай этот файл + `memory/current_state.md` (тот же статус короче) + DISCUSSION.md (записи 21:23–21:50 UTC 17.06).
> Думать/писать по-русски · grep before claim · числа из config/кода · TTS Microsoft Irina после задач.
> Коммит сессии: **1a22f70** (ветка `arch-128-oko-sm`, НЕ запушен).

<original_task>
Юзер: «EXEC-SIM-SPLIT — что будем делать? опиши подробно». Эпик был «🔵 ВЕКТОР, не делать сейчас» (полный split на 2 процесса main/strip — дубль логики против reuse, strip протух, железо на пределе). Юзер выбрал путь **«80/5» в одном процессе** (НЕ полный split) и поручил ограничители риска. Порядок: (1) лимит позиций → мерка = риск-экспозиция %; (2) консенсус (рой+DS); (3) кирпич №1 shadow; (4) «починить config 710» → «balance_snapshots = единый источник»; (5) margin pre-check кирпичом №2; (6) рестарт+валидация; (7) коммит. Побочно: центровка «loading…» в дашборде CUBE; план Settings→Entry Gates.
</original_task>

<work_completed>
**Консенсус:** путь «80/5» принят тройным консенсусом юзер→DS→рой (team-ask 5/5: откладывать split + мерка риск-экспозиция %). Спор по потолку: cerebras 5-10% (нестабильность, 60% фантомов) vs остальные 20-30%; Mistral-meta признал cerebras сильнее. Разрешение: shadow-first → потолок по данным, старт активации 10%. Рой: `memory/last_team_discussion.md`.

**Кирпич №1 — риск-экспозиция gate (PER-ACCOUNT, shadow):** расширение DEV-52 l3_checker в `core/trading/trade_simulator.py` (~1252-1335, внутри `register_trade_async`). Мерка `Σ(qty×|entry−sl|) открытых VST acc / equity_account`. equity per-account из `balance_snapshots` (SELECT через `self._db_connect()`). Вклад новой = `risk_pct%` (qty ещё не посчитан). Лог `[DEV-52][RISK]`.

**Кирпич №2 — margin pre-check (PER-ACCOUNT, shadow):** тот же блок (рефактор: общий lookup account+equity+available → 2 gate). Корень фантомов (аудит `core/trading/trade_router.py:167,203`): `register_trade_async` создаёт SIM-запись ДО `_place_exchange_order`; `open_bracket` margin-fail → order_id NULL → запись остаётся SIM = фантом. Мерка `available_per_account < min_available_usdt`. Лог `[DEV-52][MARGIN]`.

**Системный фикс депозита («balance_snapshots = единый источник»):** было 4 рассинхрона — `config.deposit_usdt=710` ∥ `user_settings` ПУСТ→дашборд 1000 ∥ реальный equity 316 (acc1~150+acc2~167) ∥ VST sizing от `availableMargin`~22. `web/dashboard_server.py` (~750-765): `risk_exposure` = реальный риск `Σ(qty×|entry−sl|)` VST / equity (`balance_repo.get_accounts()`), врало ~5×. `config.yaml deposit_usdt` помечен SIM-номиналом (710 не трогал).

**Config (`config.yaml`→`trading.l3_checker`, ~203-219):** `max_total_risk_pct: 10.0`, `risk_gate_shadow: true`, `min_available_usdt: 5.0`, `margin_gate_shadow: true`. Существующие: `enabled: true`, `max_open_long/short: 25`, `max_open_total: 50` (количественный — реально блокирует).

**Проверки:** py_compile OK. Runtime на КОПИИ `subscriptions.db` (→`e:/tmp/subs_risktest.db`): №1 acc2 9.7-10.2% would_block / acc1 0.8-2.4% pass; дашборд risk 5.8%/eq307.

**ВАЛИДАЦИЯ В ПРОДЕ (shadow, после 2 рестартов):** 18.06 00:42 MSK WHITEWHALE acc2 → ОБА would_block: `[DEV-52][RISK] 12% > 10%` + `[DEV-52][MARGIN] avail=2.8 < 5.0`. Ровно сценарий фантома. Количественный DEV-52 блокирует (`SHORT 31/25`). Ошибок DEV-52 нет.

**Коммит 1a22f70:** trade_simulator.py, dashboard_server.py, config.yaml, TASKS.md, DISCUSSION.md (+291). Документация: DISCUSSION (6 записей), `memory/exec_sim_split_epic.md`, `memory/current_state.md`, TASKS (якорь + новый backlog DASH-SETTINGS-GATES).

**Побочное:** `oko-dashboard/app/page.tsx` ScreenFallback → `fixed inset-0` (центровка «loading…»). ⚠️ oko-dashboard НЕ git — НЕ в коммите, зафиксировать отдельно.
</work_completed>

<work_remaining>
0. **ЗАПУСТИТЬ `bot-data-audit`** в свежей сессии с брифом `docs/AUDIT_DATA_INTEGRITY_BRIEF.md` (глубокий аудит матчей/семантики; юзер просил). Уже в этой сессии починены: R-баг `_handle_live` (коммит d51b26f, матч (symbol,direction)), `get_by_symbol` +side, `fetchLivePositions` regime из бэка.
1. Накопить shadow-данные (дни) в `logs/crypto_bot.log` (`[DEV-52][RISK]`/`[DEV-52][MARGIN]`).
2. **Сводка по логам** (первый шаг новой сессии по теме): частота would_block + распределение risk%/available per-account. `grep -aE "\[DEV-52\]\[(RISK|MARGIN)\]" logs/crypto_bot.log`.
3. Калибровка порогов: `max_total_risk_pct` (10), `min_available_usdt` (5, available колеблется 2.8↔70).
4. Активация: `risk_gate_shadow: false` / `margin_gate_shadow: false` → рестарт (откат мгновенный).
5. DASH-SETTINGS-GATES (TASKS): лимиты в дашборд→Settings→«Entry Gates & Protection» (реестр `dashboard_server.py:2142+` + POST + фронт `settings.tsx` GATE_TOGGLES/слайдеры; `*_shadow` как Shadow/Block). ПОСЛЕ активации.
6. Вопрос DS (DISCUSSION 21:35): margin-альтернатива — бить фантом в точке `open_bracket` margin-fail в trade_router.
7. Backlog глубже: VST sizing-base (`availableMargin`→equity?) — порочный круг при занятой марже.
8. Push 1a22f70 — по отмашке юзера.
</work_remaining>

<attempted_approaches>
- №1 сначала делил на `config.deposit_usdt=710` суммарно → shadow вскрыл расхождение → переделано на per-account equity из balance_snapshots.
- Runtime на копии: Python не понимает git-bash `/e/tmp/...` → Windows-путь `r'e:/tmp/...'`. Не-ASCII в print падает под cp1251 → ASCII или `PYTHONIOENCODING=utf-8`.
- `grep -c` exit 1 при 0 → оборачивать `(grep ... || true)`.
- Рой завис на meta ~22 мин (sambanova timeout) — 6 ответов есть, meta дописался; читать `memory/last_team_discussion.md`.
- ПЕРВЫЙ рестарт был между кирпичами → нужен был ВТОРОЙ. Урок: рестарт ПОСЛЕ всех правок.
- Tracebacks в логе из `bot/monitoring.py:1919 send_photo` (Telegram) — НЕ DEV-52, игнор.
</attempted_approaches>

<critical_context>
- Цель ([[vision_bot_as_anchor_against_emotion]]): риск-экспозиция % = тормоз жадности; путь к $1M через компаундинг → выживание/ruin первично.
- [[principle_reuse_not_duplication]]: кирпичи = расширение DEV-52, НЕ новые gate. Полный split отложен из-за дубля.
- Мерка = риск %, НЕ количество/маржа: `notional=risk/sl_dist` взрывается до 20× при узком стопе (`position_sizer.py:72-89`, cap `max_notional_mult=20`).
- Per-account ОБЯЗАТЕЛЕН: acc1 VST-Main ~150, acc2 VST-Sub ~167. Суммарный прячет проблему.
- 🔴 ГЛАВНАЯ НАХОДКА: реальная боль = МАРЖА 87% used на обоих акк (avail~22), НЕ стопы (риск стопов 0.8-10% здоров). Фантомы+ликвидация от маржи → margin pre-check острее.
- execution_mode: SIM⟺order_id NULL, VST⟺order_id есть. Обучение (`performance_engine.by_signal_type_ema`) фильтрует VST → фантомы вне весов.
- Правила: прогон main не трогать (рестарт=юзер); register-путь → runtime на копии ([[feedback_ast_parse_no_scope]]); биржевое → docs/код сначала ([[preflight_exchange_task]]); русский; TTS Irina.
- oko-dashboard НЕ git — фронт осторожно, отдельно.
- Всё за shadow-флагами → реально не блокирует, только лог. Безопасно.
</critical_context>

<current_state>
- Кирпичи №1+№2: ✅ реализованы, ✅ протестированы (py_compile+runtime копия), ✅ ВАЛИДИРОВАНЫ В ПРОДЕ (shadow), ✅ закоммичены (1a22f70). Работают в боте, копят логи.
- Deposit-рассинхрон: ✅ починен.
- Активация: ⏳ ждёт накопления данных (shadow=true, реально не блокирует).
- Дашборд risk_exposure: ✅ реальные % (в коммите). loading-fix oko-dashboard НЕ закоммичен (др. репо).
- DASH-SETTINGS-GATES: 🔵 backlog, после активации.
- Push: 1a22f70 локальный, НЕ запушен.
- Точка остановки логическая. Следующий заход по теме = сводка логов → калибровка → активация. Крупные новые задачи — в СВЕЖЕЙ сессии (этот контекст тяжёлый).
</current_state>
