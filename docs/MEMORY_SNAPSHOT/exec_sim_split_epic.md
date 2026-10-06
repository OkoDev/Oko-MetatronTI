---
name: exec_sim_split_epic
description: "ЭПИК EXEC-SIM-SPLIT — main только реальные (дышит биржа), strip = sim-полигон по всем сигналам, раздельные БД, мост обучения через learning_db_path"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3743ba62-3271-4099-bf28-5bf1be14a516
---

**⚠️ ТРЕЗВАЯ ОЦЕНКА 14.06: ВЕКТОР, НЕ ДЕЛАТЬ СЕЙЧАС.** Юзер накидал мысль, Claude разогнался в эпик — пересмотр. (1) Корень боли (189 фантомов) = margin-reject от RISK 95% / нет лимита позиций, НЕ «sim с биржей» → дешевле риск-менеджментом. (2) 2 процесса с одной логикой = крупнейший дубль, против [[principle_reuse_not_duplication]]; strip УЖЕ протух за месяц = доказательство закона. (3) Цена высока для соло + машина на пределе (BSOD). **80/5 в ОДНОМ процессе:** лимит позиций + execution_mode разметка ([[arch_db_v2_terminal]], sim/real в 1 БД помечены) + опц. [[sim_deprioritize_loop]] throttle. **Оправдан КОГДА:** +юзер ∥ strip=иная логика (дрейф=фича) ∥ железо мощнее. Дизайн ниже — для того момента.

---

**ЭПИК EXEC-SIM-SPLIT (юзер 14.06: «strip обновить под main, оставить только SIM; из main SIM убрать совсем — дать дышать бирже»).**

Разделение ответственности на 2 процесса:
- **main** (vst/live) — ТОЛЬКО реальные сделки. Loop + IP-бюджет идут торговле. Лёгкий. «Биржа дышит».
- **strip** (sim_only) — sim-полигон: генерит/симулирует ВСЕ сигналы на ОБЩЕМ кэше main ([[strip_twin_shared_cache]]), без своего биржевого REST.

**🔴 КРИТИКА — почему sim НЕЛЬЗЯ просто удалить (grep 14.06):** обучение main питается ОТ sim. `update_signal_weights` (trading_intelligence.py:246) → `PerformanceEngine.by_signal_type_ema` (performance_engine.py:197) фильтрует лишь `status IN ('TP','SL','TSL','EXPIRED')` — БЕЗ различия sim/real. ARCH-104 mining (arch104_signal_adapter, pattern_lifecycle_manager) + ML тоже читают `simulated_trades` целиком. Sim доминирует (27719 сделок, в осн. sim; реальных мало). Убрать sim из main = разорвать feedback loop Куба, main ослепнет. → **sim ПЕРЕСЕЛЯЕТСЯ в strip, обучающий контур main перенаправляется.**

**РЕШЕНИЯ ЮЗЕРА 14.06:**
- **БД РАЗДЕЛЬНЫЕ:** strip = sim-only DB, main = реальные. (проще общей: нет конкуренции за запись).
- **Мост обучения:** main читает strip-БД (sim) для весов/паттернов/ML. `db_path` УЖЕ параметризован (`update_signal_weights(db_path=...)`, `PerformanceEngine(db)`) → config `trading.learning_db_path` = strip/subscriptions.db (read-only). Инфра наполовину готова.

**Дефолты дизайна (Claude, на подтверждение юзера):**
- (2) strip сканит НЕЗАВИСИМО на общем кэше = полный двойник логики → «обновить strip под main» критично (иначе расхождение сигналов).
- (4) ресурсы: strip без биржевого REST легче; машина на пределе (BSOD/XMP-история) → при нужде strip на меньшем наборе пар/реже.
- (5) main НЕ регистрирует не-биржевой сигнал — strip независимо его поймает (нет дубль-записи).

**Объединяет эпики:** [[strip_twin_shared_cache]] (общий кэш = фундамент), [[sim_deprioritize_loop]] (ОТМЕНЯЕТСЯ — sim уходит из main, это радикальнее throttle), [[arch_db_v2_terminal]] (execution_mode разметка). Куб: main=Сфера исполнения, strip=Сфера обучения (feedback 11), общий кэш=Shared Context, learning_db_path=ребро между процессами.

**Этапы (черновик):** (1) пересоздать strip из текущего main (git/копия) — strip заброшен с 16.05 на старом коде; (2) STRIP-TWIN общий кэш (HTTP /api/ohlcv); (3) strip → sim_only + своя БД; (4) main → execution_mode чисто vst, перестать писать sim_only; (5) мост learning_db_path; (6) дашборд: sim из strip.

**Статус:** 🔵 эпик-дизайн. Проектировать роем + bot-arch ПЕРЕД кодом. Не на ночь — прогон main не трогать. TASKS:EXEC-SIM-SPLIT.

---

## 🟢 17.06.2026 — выбран путь «80/5» (НЕ полный split), КИРПИЧ №1 реализован (shadow)
Консенсус: юзер → DS → рой (5/5 за откладывание split + мерку риск-экспозиция %; спор потолок: cerebras 5-10% vs DS 20%). Полный split отложен (дубль логики, strip протух, железо).

**Кирпич №1 = риск-экспозиция gate PER-ACCOUNT.** Реализован как РАСШИРЕНИЕ существующего **DEV-52 l3_checker** (`trade_simulator.py:~1221`, register — единая точка, `signal_router.enabled=true` → все входы через неё), НЕ новый gate (reuse). Мерка: `Σ(qty×|entry−sl|) открытых VST этого acc / equity_account`. equity per-account из **balance_snapshots** (НЕ количество, НЕ маржа). Shadow (`risk_gate_shadow: true`, cap `max_total_risk_pct: 10.0`) → лог `[DEV-52][RISK]` would_block без блока. Circuit Breaker by design (только новые входы). Файлы: config.yaml l3_checker, trade_simulator.py DEV-52, dashboard_server.py risk_exposure. py_compile+runtime на копии OK.

**🔴 SHADOW ВСКРЫЛ ГЛАВНОЕ (17.06):** риск по стопам ЗДОРОВ (acc1 0.8%, acc2 9.7%, ruin не грозит), а **реальная боль = МАРЖА 87% used на ОБОИХ акк** (available ~22) → вот корень margin-reject фантомов + риск ликвидации. **Margin pre-check (отложенный 2-й слой) ОСТРЕЕ кирпича №1** — поднять в приоритет. См. [[arch_db_v2_terminal]].

**🔴 DEPOSIT-РАССИНХРОН (4 источника, починен через «balance_snapshots = единый источник»):** config.deposit_usdt=710 (помечен SIM-номинал) ∥ user_settings ПУСТ→дашборд fallback 1000 ∥ реальный equity 316 (acc1~150+acc2~167) ∥ VST sizing от availableMargin ~22. Дашборд `risk_exposure` врал ~5× (n_vst×номинал) → теперь реальный риск/equity. **Глубже:** VST sizing берёт availableMargin (падает при занятой марже) → порочный круг фантомов (отдельный фикс sizing-base, backlog).

**🟢 КИРПИЧ №2 = margin pre-check (17.06, реализован shadow).** Корень фантомов (аудит `trade_router.py:167,203`): register пишет SIM-запись ДО `_place_exchange_order`; `open_bracket` margin-fail → order_id NULL → запись остаётся SIM = фантом. Кирпич №2 ловит ДО register: `available_per_account < min_available_usdt` (balance_snapshots) → `[DEV-52][MARGIN]` block. Рефактор DEV-52: общий lookup (account+equity+available) → 2 gate (риск+маржа). Config `min_available_usdt: 5.0`, `margin_gate_shadow: true`. Runtime OK. Available сильно колеблется (порог уточнить по shadow). Альтернатива (мощнее, обсудить): не оставлять SIM при open_bracket margin-fail прямо в trade_router (бить фантом в точке reject).

NEXT: рестарт → наблюдать `[DEV-52][RISK]`+`[DEV-52][MARGIN]` → активация (shadow:false) + уточнить пороги по распределению. Backlog: VST sizing-base (availableMargin→equity?). [ОБНОВЛЕНИЕ: гейты активированы 19.06, работают.]

---

## 🟢🟢 13.07 ЭПИК ОЖИЛ — дизайн УТВЕРЖДЁН консилиумом (bot-arch по коду + рой 6 моделей)
**Егор 12-13.07: «симуляцию отделить НАСОВСЕМ от биржи; приблизить логику, но полностью отделить; SIM мешает в исполнении» + «дизайн через bot-arch обязательно, подключить всех» + «монолиты решить заодно».**
Условие «оправдан КОГДА» наступило иначе: боль переместилась от фантомов (гейты победили) к СПЛЕТЕНИЮ
SIM×VST в close_trade (phantom-clamp LAB +32→+6.4, orphan-killer убил ручной LONG, tail-wall, BREV 9д
без time-exit, ote_nested SIM +0.52%/VST −0.57% = исполнение). Дизайн НЕ 2 процесса (отвергнуто
стоит) — раскол exit-контуров ВНУТРИ одного.

**План 7 шагов (порядок = консенсус; поведенческий раскол ДО файлового распила):**
1. Фикс гонки pa=0 в shadow (малый) 2. VST-time-exit reconciliation (малый, не ждёт cutover)
3. copy-DB тест 4. флип sphere_cutover 5. trade_writer finalize (средний) 6. SimExitEngine (средний)
7. распил монолита gates/sim_engine (большой/низкий риск).
**Гонка pa=0** (4/11 событий rp=0: pa=0 раньше fill на ~90мс, ledger пуст → мисс-класс AVAAI TP≠SL):
первично Δ`cr` из ACCOUNT_UPDATE + exit=WS-ap (_close_fills уже ловит) + классификатор по геометрии;
income-retry вторично; грейс отклонён (латентность; Model B: вредит импульсным=радар).
⚠️ Главная неизвестная = семантика cr (cumulative vs per-symbol) — валидировать на shadow ДО доверия.
**Частичные** (BILL/LAB-сироты): close только при tracked qty→0; reduceOnly+остаток = partial TP1.
**trade_writer** = ОДИН finalize (R+costs+4 хвоста: шина/веса/TG/SSE; clamp=параметр) → Сфера 11 не рвётся.
**position_sync** → reconciler (не удалять 2-3 нед). Полный план: DISCUSSION 13.07 + obsidian/Team-Discussions/2026-07-13-exec-sim-split-*.
CUTOVER-блокер снят фактически: rp-захват 11/11 (было 25%→65%→100%), остался фикс гонки. [[cutover_blocker_ws_closefill]]

## ✅ 13.07 ШАГИ 1-2 РЕАЛИЗОВАНЫ (коммит 79260dc, ЖДУТ РЕСТАРТА)
**Шаг 1 CR-DELTA:** Position.cum_realized (cr из ACCOUNT_UPDATE) → PositionStore стеш при pa>0 +
take_cr_delta → Sphere._exit_from_cr_delta в каскаде take_exit→CR-DELTA→REST→income + чистка стеша
при не-cr пути. Смоук на реальном AVAAI: SL @0.006036 rp=−5.34 (факт 0.00604) вместо «TP @ entry rp=0»;
ORDI сброс-цикл ✓; REST/income не тронуты (первичность доказана assert'ами). 75 тестов зелёные
(⚠️ 2 clamp-leverage теста падали ДО правок — pre-existing заноза, Егору зафлагано).
**Шаг 2 VST-time-exit:** position_sync._vst_time_exit_check (вызов после DEV-185.2) — age>TTL → лог
[VST-TIME-EXIT]+TG SYSTEM 1/сутки; config trading.vst_time_exit (enabled:false=shadow; per_source
ote_nested 3д/radar 2д/дефолт 5д); enabled:true → Sphere.close(pid) reduceOnly (БД закрывает штатный
WS-путь pa=0 — раскол не нарушен). position_id у VST OPEN = 5/5. Смоук живой БД: BREV #41641 пойман 9.2д.
**После рестарта мониторить:** [Sphere] exit via CR-DELTA в логах · rp=0 в WOULD CLOSE → 0 ·
[VST-TIME-EXIT] алерт BREV. Затем: shadow-сверка N дней → шаг 3 copy-DB тест → шаг 4 флип.
Механизм AVAAI-мусора (для истории): income-fallback при realized≈0 строит exit=entry, status=TP if rp>=0.

## ✅ 13.07 ШАГ 3 COPY-DB ПРОЙДЕН РЕТРОСПЕКТИВНО + пре-флип фиксы (коммит c104945)
Егор «пару дней ждать?! а сейчас что?» → тест сделан СРАЗУ на уже случившихся закрытиях: копия БД,
реоткрытие 8-9 сегодняшних VST-закрытий, applier сферы с CR-DELTA-интентами из реальных cr логов,
сверка с эталоном старого пути (scratchpad copydb_cutover_test.py; TZ-ловушка: лог=МСК, closed_at=UTC).
**Ядро 5/8 идентично (Δpx<0.1%)**; расхождения информативны: STRK — сфера ЧЕСТНЕЕ (БД «TP @ entry
gross 0» = fake-BE класс ALGO 08.07, cr-истина −7.63 USDT) · TIA — SL вместо мусорного EXPIRED ·
AGLD ×2 — SL→TSL класс + partial-размазка cr-цены (rp честный, цена=средневзвес кусков).
**Фиксы:** db_writer SL→TSL коррекция (перенос из 2b, + TP от знаковой классификации CR_DELTA/INCOME;
нативный TAKE_PROFIT не трогаем) · position_store partial-защита (частичный reduceOnly < позиции −2%
не стешится как exit). LAB OPEN@0 в тесте = дизайн «не гадаем» (cr-цена ≤0 → эскалация watchdog).
87 тестов зелёные (2 clamp-leverage pre-existing). **Осталось до флипа: свежие CR-DELTA в живых логах
(рестарт) → короткое наблюдение → sphere_cutover:true.** «Пара дней» сжата в день.

## 🔴→✅ 13.07 LAB-КЕЙС (первое живое CR-DELTA) — два глюка BingX пойманы и починены (2e23dac)
LAB #47205 (радар-раннер TP1/TP2/хвост): сфера дала TP @ 0.40944 rp=8.751 vs факт TSL @ 0.3505.
Полная pa-история вскрыла МУСОРНОЕ WS-событие BingX: **pa 52.2→522.0 (×10) при неизменном ep, без
fill'ов, cr=""(пустая строка)**. Два отравления: (1) _f("")=0.0 затёр cr-стеш → Δcr=8.75 вместо
честных 3.94 (хвост после частичек); (2) store.qty=522 → цена восстановлена от ×10 объёма.
**Фиксы:** adapter cr="" → None · store qty-скачок >×2.5 при том же ep = глюк → прежний qty
(реальный добор сдвинул бы среднюю цену). Реплей полной истории: exit=0.350675 vs факт 0.3505
(Δ0.05%), rp=+3.94 ✓.
**🔑 НАХОДКА: BingX VST систематически НЕ шлёт закрывающие ORDER_TRADE_UPDATE** (TP1/TP2/финал LAB —
только ACCOUNT_UPDATE; все 11 утренних WOULD CLOSE reason=ws_pa0) → **CR-DELTA = ОСНОВНОЙ путь
закрытия, не фоллбек**. Тем ценнее Δcr-механика. Residual-риск: новые формы глюков BingX в
ACCOUNT_UPDATE — мониторить [Sphere] CR-DELTA vs факты первую неделю после флипа.

## 🎉🎉 13.07 16:04 ФЛИП СДЕЛАН — ШАГ 4 ЗАВЕРШЁН (79a6f27, «эпичный рестарт»)
`[SPHERE-CUTOVER] pipeline построен (on_close=db_writer АВТОРИТЕТЕН; старые close-пути ВЫКЛ)`.
Путь к флипу за ОДИН день: живой BEAT Δpx 0.076% fees-точный rp (финальная сверка) → Егор «добро!».
**VST-выход отвязан от SIM.** Старые пути (position_sync close-by-price + 2b) выключены флагом,
откат = false+рестарт, fail-safe 2-3 недели. Мониторить: [db_writer] закрытия vs факты · дубли
POSITION_CLOSED · stuck-OPEN VST · rp=0. NEXT: шаг 5 trade_writer finalize → шаг 6 SimExitEngine →
шаг 7 распил. Параллельно: квадрант-конкорданс гейт BUILD в бою (SHORT@PUP+*/LONG@PDN+* → вето,
ночь 5/5 лоссов против потока; oi-fast перезапущен).
**16:09 ПЕРВОЕ АВТОРИТЕТНОЕ ЗАКРЫТИЕ — БЕЗУПРЕЧНО:** #47500 CAP LONG → SL @ 0.018630 (CR-DELTA
Δcr=−3.535; gross записи = Δcr с точностью 0.000; exit на 0.28% ниже SL = честный слиппедж прокола,
который старый путь маскировал; R/costs посчитаны; 2b SKIP — дублей нет; 26мс от WS до БД vs 60с
поллинг). Раскол работает в бою.

## ✅ 13.07 ШАГ 5 — trade_writer (единый finalize), ЖДЁТ РЕСТАРТА
Егор «монолиты! читай graphify давай решать». Graphify: TradeSimulator = god node (101 ребро),
TradingIntelligence (110, монолит №2 — будущий кандидат) → принцип распила: **ФАСАД НЕИЗМЕНЕН**,
внутренности по модулям, рёбра не трогаем. `core/trading/trade_writer.py`: compute_finalize (чистая
математика без IO — R/TP1/MFE/duration/costs), persist_close, emit_close_events (6 хвостов ровно
1 раз). close_trade сжат ~290→~100 (guard→read→clamp-resolve→writer). **PARITY-тест на копии БД:
24 реальных сделки перезакрыты — все 7 полей идентичны эталону (<1e-6).** 47=47 тестов
(⚠️ 27 в test_trade_simulator падали ДО — pre-existing, тесты отстали от схемы, зафлагано).
NEXT: шаг 6 SimExitEngine (SIM-ветки монитора check_open_trades_with_tsl) → шаг 7 gates/.

## ✅ 13.07 ШАГ 6 — sim_exit (дом SIM-выхода), ЖДЁТ РЕСТАРТА
Шаг 5 подтверждён живьём (#47234 TSL R=0.502 через writer). `core/trading/sim_exit.py`:
`detect_candle_exit` — ЧИСТАЯ функция свечного детекта (touch/close-режимы, DUAL_TP каскад,
TSL-supremacy, тай-брейк, MFE) — впервые юнит-тестируема, контракт = tests/unit/test_sim_exit.py
(8 кейсов; правила = data-era, менять только с пометкой) + `sim_time_exit_if_due` (анти-орфан).
Side-effects (tp-хиты в БД, шина TP1_HIT, close) — в мониторе. После CUTOVER монитор разделён
политикой: SIM закрывает детект, биржевые — сфера (LIVE-GUARD лишь логирует, radar тихо скипает).
Осталось: шаг 7 — gates/ из register_trade_async (большой, низкий риск) + кандидат монолит №2
TradingIntelligence (110 рёбер). Смоук 7/7, 87 тестов ✓.

## 🏁🏁 13.07 ШАГ 7 ФИНАЛ — ЭПИК 7/7 ЗАВЕРШЁН ЗА ОДИН ДЕНЬ (ждёт рестарта)
Егор «почему завтра?» → сделали сразу. 🔑 Инвентаризация ПЕРЕД выносом (signal_drops 7дн):
router/gates SOFT-пайплайн блокирует 99% (dedup 27.5K), инлайн-слой ловит ~316 — DEV-44 HIGH_VOL
~260 (penalty НЕ останавливает!), corr ~29 → **инлайн = НЕ дубль, а второй HARD-рубеж
(defense-in-depth), СОХРАНЁН полностью**. core/trading/register_gates.py: 7 гейтов 1:1
(DEV-170/ARCH-42/DEV-38/DEV-44+64B+133/DEV-155/DEV-98/DEV-52). register = фасад-оркестратор.
Попутно: symbol безусловно (dc=None путь глотал UnboundLocal в старых except).
**trade_simulator: 3152 → 2629 (−525/день).** Смоук: блоки ✓, живой register ✓, дубль-рубеж ✓,
95 тестов. Реестр дублей: двухрубежность гейтов = ОПРАВДАННЫЙ дубль (semantics HARD vs SOFT).
Монолит №2 = TradingIntelligence (110 рёбер) — отдельный эпик, не сейчас.

## 🔴→✅ 14.07 ZBT-КЛАСС (первая ночь CUTOVER): LIMIT-вход стешился как exit — 6 сделок нулями
«TP net=−0.09%» × 6 подряд = замазанные лоси. Корень: `Fill.is_open_fill` требовал
order_type==MARKET → LIMIT-вход радара падал в exit-стеш (exit=entry rp=0 «TP») и при pa=0
перекрывал CR-DELTA. Ночной VST «+9.05%» был фейком → реально **−3.3%** (ZBT 0→−2.27, EVAA
0→−3.00, EGLD 0→−2.92, LUMIA −1.66, WIF −0.93, JCT −2.15). ТОТ ЖЕ класс, что ALGO 08.07 —
фикс жил только в старом пути (_close_fills ro-фильтр), в сферу НЕ продублирован
(**урок reuse ×4 за два дня**). Фикс 2 рубежа: is_open_fill MARKET→(MARKET,LIMIT) +
exit-стеш только для ЗАКРЫВАЮЩЕЙ стороны (SELL+LONG|BUY+SHORT). Ретро: 6 сделок исправлены
из WS-fill логов через compute_finalize (reuse). ⚠️ Лог обрезает WS-JSON — парсить
регексами, не json.loads. Мониторинг-маркер класса: «TP с net≈−costs».
Попутно 14.07: wt_os_depth-фича доехала не в тот dict (drop-путь) — фикс в боевой extra;
4h-atr-ветка (задышала после off 15m, 39 сделок/ночь) бэктест −0.505%/сд 4/5 лет → ВЫКЛ.

## 🔴 14.07 ДВА DRIFT-КЛАССА (дашборд Егора «2 DRIFT»)
1. **SAND-класс** (#47688): LIMIT зафиллился+закрылся МЕЖДУ циклами радара → «exit резолвит
   position_sync» МЁРТВ (close-by-price выключен CUTOVER'ом) → вечный OPEN. ✅ Фикс:
   _late_fill_verify_close в radar_armed (флэт → закрывающий fill по positionID → close_trade).
2. **AIOT-класс** (#47734): позиция закрылась SL в 11:59:17 — РОВНО в окно рестарта (WS поднялся
   11:59:32): pa=0 пролетел, cold_start флэт уже не видел → вечный OPEN. ⚠️ БЭКЛОГ: reconcile
   «БД-OPEN-биржевые vs биржа-флэт» (раз в N мин в position_sync-reconciler; старый _detect_orphans
   ловит ОБРАТНОЕ). Маркер обоих: дашборд SIM↔EXCHANGE drift «OPEN IN SIM, NO EXCHANGE POS».
Оба закрыты руками честно: AIOT SL −4.14%, SAND SL −0.90%.

## 🔴🔴 15-16.07 ТИХАЯ СМЕРТЬ ЛУПОВ (6.5ч) + два фикса страховки
**Егор: «14 DRIFT при 2 позициях?! интернет плохо работает — может бот влияет?»** Диагноз:
19:03 сеть просела → BingX FAIL 200/200 (и прокси, и direct) → scan/tracker/position_sync
повисли на ретраях и умерли МОЛЧА. **pm2 status=online, restarts=0** (жил только WS-таск:
STATS капали, 292 реконнекта) → авто-рестарта НЕ БЫЛО 6.5ч. Следствия: 12 позиций без
сопровождения (TSL/BE стояли), шина не обновлялась → `/api/live` отдавал **2 из 12** реальных
позиций → дашборд рисовал фантом «14 DRIFT» + RISK 29870% (Егор поймал ГЛАЗОМ — как всегда).
Не бот убил сеть (у него 0 соединений — он же завис); сеть убила бота.
**Фикс 1 — HEARTBEAT:** `core/infra/heartbeat.py` beat() → touch `logs/heartbeat/<name>`
(атомарно, без локов, переживает зависший loop); пульс в scan + tracker;
`scripts/heartbeat_watchdog.py` (pm2 `hb-watchdog`, cron */3): тишина >8мин при online →
TG SYSTEM + `pm2 restart oko-bot` (grace 5мин, анти-флаппинг 20мин).
**Фикс 2 — RECONCILE:** `reconcile_watchdog` при CUTOVER только ЛОГИРОВАЛ would-close
(наследие shadow-эпохи) → при флипе страховку не переключили = дыра. Теперь `_fire_close`
→ db_writer закрывает зомби («не гадаем» сохранено).
**Урок:** `pm2 online` ≠ «бот работает». Любой критичный луп обязан пульсировать, иначе
тихая смерть невидима. Реальных зомби было 5 (не 15): LTC/UNI закрыты по факту, 3 без
fill-следа. NEXT-бэклог: таймауты/fail-fast в сетевом слое (лупы не должны виснуть вечно);
`/api/live` fallback на REST при пустой шине.

## ✅ 17.07 РОУТЕР БЫЛ ВИНОВАТ — не бот (Егор отнёс в сервис) + 2 фикса
Замер ДО/ПОСЛЕ запуска на починенном роутере: BingX 363→346ms, **Telegram 729→370ms (3/3 ok)**
— вчерашний «Cannot connect to api.telegram.org» = роутер, НЕ блокировка РФ. Канал под полной
нагрузкой (11 процессов, скан 530 пар + радар 500 перпов) НЕ проседает. Диагноз «бот душит
интернет» опровергнут; вклад дал proxy-off (10 конн вместо ферм-30).
**🔴 Первый бой вотчдога вскрыл ЕГО дизайн-ошибку:** beat("scan") стоял в КОНЦЕ цикла, а скан
на щадящем direct идёт 5-10 мин → пульс «молчал» 7+ мин при ЖИВОМ лупе (SMC_SNAP лились) →
вотчдог (порог 8м) устроил бы рестарт-петлю (и это выглядело бы как «бот падает постоянно»!).
Фикс: `heartbeat.beat_progress(name, min_interval=15)` — пульс ПО ХОДУ (в scan_one, троттл 15с);
**принцип: пульс = «луп жив», НЕ «цикл завершён»**. tracker не тронут (бьёт в начале 60с-цикла).
Проверено: scan-пульс 54с ✓. Вотчдог реально сработал сам в 10:21 (тишина лупов → рестарт) —
механизм рабочий. **Урок: медленный луп ≠ мёртвый; порог вотчдога должен быть > реального цикла,
либо пульс по прогрессу.**
