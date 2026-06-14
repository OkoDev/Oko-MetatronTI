# TASKS — Полные описания задач

> Перенесено из TASKS.md при рефакторинге 13.06.2026.
> Краткие якоря → TASKS.md; детали → здесь.

---

## ID: **MARKET-WS** — 🔵 kline-push WS → OhlcvCache, scan без REST (LOOP-разгрузка, рой+DS)

**ДОКАЗАН тестом 14.06** (`scripts/diag_market_ws_kline.py`): 20/20 потоков kline 5m/15m, 2224 апдейта/90с, кастомный aiohttp, 1 соединение. **Боль:** scan_loop 296-341с/526пар, REST-fetch LTF = узкое место loop. **Цель:** kline push → OhlcvCache → scan читает БЕЗ REST-polling. ccxt.pro WsFeed провалился (плато 750s, нелинейный overhead) — кастомный WS лёгкий (как EXEC-WS). **DS-аспект:** (1) валидация WS-свеча == REST-свеча на ЗАКРЫТЫХ барах (нет расхождений/гэпов) на копии; (2) замер экономии REST/цикл. **DEV/ARCH:** батчи соединений (526×2=1052 подписки, лимит BingX/conn), OhlcvCache-интеграция (DataFrame time/OHLCV, гибрид WS+REST), незакрытая свеча (is_closed), отдельный поток (threading.Lock на кэш), gap-fill+stale-guard (как DEV-227), shadow-миграция за флагом (WS теневой → сравнить REST → переключить по ТФ). Рой опрошен 14.06 (team_ask, 8 вопросов). → memory `market_ws_kline_proven`. **РОЙ 14.06 (5/5 ЗА):** единственный верный путь разгрузки; отдельный поток (как EXEC-WS); gap-fill обязателен (REST-добор при разрыве timestamp >интервал×1.5); shadow-миграция за флагом `market_ws.shadow_enabled` (теневой кэш → сравнить REST ≥99%/10мин → `use_ws=true`); консенсус ГИБРИД (WS+REST fallback) vs полный (спор, синтез за гибрид). План (openrouter): новый `core/infra/market_ws.py`, батчи по 100 пар, keep-alive PING/PONG 20с, backoff-реконнект, gap-detector. **NEXT:** event_loop_debug=false дал 0 lag но scan-цикл ~300с не изменился (узкое=REST, не debug) → MARKET-WS = главный рычаг. **🔴 РЕЗУЛЬТАТ 14.06: ПОТОК ПРОВАЛИЛСЯ (GIL).** Этап 1+2 в проде (fd3a925): merge replace 256k/append работал, DS WS==REST≥99%. НО market_ws-поток ~70k свечей/мин (gzip+json+merge=CPU) держит GIL → scan 300с→600с+ (не завершался). ОТКАТ c88fd94 (enabled=false), тёплый цикл вернулся 351с. **MARKET-WS v2 = отдельный ПРОЦЕСС (D-072: data_service + Redis/IPC, обходит GIL)** — код market_ws.py + OhlcvCache RLock + heartbeat-фикс сохранены за флагом. Урок: high-rate WS (>~1k msg/с CPU) в Python = ТОЛЬКО процесс, не поток. EXEC-WS работает (order-события редкие).

---

## ID: **ARCH-DB-V2** — 🟢 **Ф2 В ПРОДЕ (13.06):** exchanges/accounts/positions DDL+seed (БД), `balance_r…

🟢 **Ф2 В ПРОДЕ (13.06):** exchanges/accounts/positions DDL+seed (БД), `balance_repo.{upsert_positions,get_positions,get_accounts}`, position_sync пишет positions, `/api/accounts`+`/api/positions` endpoints, `PositionsPanel` компонент в overview. ⚠️ Рестарт бота нужен (авто-миграция exchanges/accounts/positions в sub_mgr). **Ф3:** нормализация trades/signals/orders через ETL.

---
## ID: **OPS-01a** — анти-#1910 sanity-guard:** при OPEN, если цена ушла >X% за SL → форс-клоуз НЕЗ…

**анти-#1910 sanity-guard:** при OPEN, если цена ушла >X% за SL → форс-клоуз НЕЗАВИСИМО от time-фильтра. Корень: пустой `df_filtered`→`continue`→SL не проверен (−9.74R)

---
## ID: **OPS-04** — авто-рестарт `monitor_market` при необработанном исключении (тихая остановка) +…

авто-рестарт `monitor_market` при необработанном исключении (тихая остановка) + graceful shutdown (`bot/core/bot.py:107-115` create_task без finally)

---
## ID: **OPS-06** — ✅ LIVE-GUARD ТАЙМАУТ (12.06, v2 — перенесён в position_sync):** корень orphan-…

**✅ LIVE-GUARD ТАЙМАУТ (12.06, v2 — перенесён в position_sync):** корень orphan-зависания — exchange-managed exit ждал биржу БЕЗ таймаута → висел → EXPIRED R=0. **⚠️ Юзер вскрыл изъян v1:** force-close в симуляторе плодил orphan (биржа держит, а БД закрыл). **v2 правильно:** `trade_simulator` только трекает `_live_guard_first_detect`+лог (НЕ закрывает); `position_sync._emergency_close_check` 2-й триггер — детект exit+таймаут(`live_guard_timeout_min`7) → market close РЕАЛЬНОЙ позиции + БД (orphan-prevent, переиспользует close-механизм). Ловит «биржевой SL не сработал, overshoot мал» (dev185_2 молчит). AST+импорт OK. **✅ 109400 ONE-CLICK FALLBACK (12.06):** корень orphan — `order_manager:717` (SL пробит→close market) при 109400 hedge только warning+return None→позиция висит. Фикс: `close_position_market(one_click_on_fail)` → после retry без reduceOnly, если fail → one-click (closeAllPositions, доказано close_orphans). order_manager:717 передаёт True; position_sync/emergency уже имели свой. Предотвращает orphan в корне. **✅ 13 orphan закрыты** (close_orphans.py + safety-фильтры). Остаётся: автоматический ghost-reconcile (D-070 только детектит). **✅ ЧАСТЬ 1 (09.06): emergency_close→БД.** Корень USELESS-класса: `_emergency_close_check` закрывал ПОЗИЦИЮ на бирже но НЕ вызывал close_trade → orphan OPEN навсегда. Фикс: после успеха emergency → `_resolve_exit`(реальный SL/TP/TSL по filled-ордеру)+`close_trade` (`position_sync.py:190`). Тест: бой-наблюдение `[OPS-06]` логи. **🟡 Остаётся:** ghost-позиции (биржа держит, БД нет), LIVE-GUARD таймаут, разбор 109400, periodic auto-sync. **🔴 ЧАСТЬ 3 — МУЛЬТИАККАУНТ-УЯЗВИМОСТЬ (найдено 09.06, #21703 USELESS на SUB-acc2):** из 53 exchange-managed OPEN — **ВСЕ 53 с qty=None** (qty не пишется в БД при register, emergency спасает только fallback'ом qty с биржи = костыль), **4 БЕЗ SL-ордера на бирже** (голые позиции в убытке). #21703 жил на acc2(sub) без SL/qty → не закрывался (check_open/emergency не видели sub-позицию вовремя). Связка ARCH-96. **Фиксы:** (1) писать qty в БД при register exchange-managed; (2) гарантировать SL-ордер для ВСЕХ (sub тоже); (3) check_open проверяет позиции ВСЕХ аккаунтов. #21703 закрыт вручную (acc2 one-click + БД SL R=−1). **Exchange-sync рассинхрон БД↔биржа — ДВУСТОРОННИЙ (найдено 09.06, гипотеза stale-кэш ОПРОВЕРГНУТА логами).** Сделки за SL висят OPEN часами (USELESS #21703 −4.65R 2.6ч, close пробивал SL 10/10). **Корень из логов:** check_open ВИДИТ SL (не stale!) → `order_manager` close market FAILED `code=109400` («SL should be lower than current» + «No position to close») → **LIVE-GUARD ждёт подтверждения биржи БЕЗ таймаута → orphan висит вечно**, R утекает. `sync_db_exchange.py` закрыл 46 orphans (OPEN 114→68), НО синхрон=False: **91 биржа vs 68 БД = 23 ghost** (биржа держит позицию, БД считает закрытой). **Фиксы:** (1) LIVE-GUARD таймаут — если биржа N мин «No position»/FAILED → закрыть БД по SL-цене (R≈−1, НЕ EXPIRED R=0 как sync); (2) разобрать 109400 (почему SL-ордер не исполняется штатно); (3) ghost — БД подхватывает биржевые позиции; (4) периодический auto-sync как временная защита. ⚠️ sync ставит EXPIRED R=0 — искажает (USELESS реально SL −1R). **🔴 ИСКАЖЕНИЕ МЕТРИК (юзер 09.06):** при «No position to close» order_manager `return None` (в БД НЕ пишет, стр.727), check_open LIVE-GUARD `continue` → сделка ВИСИТ OPEN без отметки → sync→EXPIRED R=0. Реальный SL-убыток (−1R на бирже) ТЕРЯЕТСЯ → avgR/WR завышаются = «бумажная иллюзия» (аудит DS). Связь [[ML-01c]] realized-R таргет. Фикс должен писать SL с РЕАЛЬНЫМ R, не R=0.

---
## ID: **ML-01d** — `regime` на инференсе (сейчас `regime=None`→one-hot `[0,0,0,0]`, 4/12 фич нулевы…

`regime` на инференсе (сейчас `regime=None`→one-hot `[0,0,0,0]`, 4/12 фич нулевые) + `TSL`/`EXPIRED` в обучение (сейчас только TP/SL)

---
## ID: **DOC-SYNC** — регулярное обновление `current_state.md`/`whats-next.md` (косяк: аудит читал уст…

регулярное обновление `current_state.md`/`whats-next.md` (косяк: аудит читал устаревшее). Авто-напоминание/скрипт сверки доки↔код

---
## ID: **DS-326** — WT-B LTF-вход: три последовательных фильтра (бэктест).** Базовый скрипт готов:…

**WT-B LTF-вход: три последовательных фильтра (бэктест).** Базовый скрипт готов: `scripts/backtest_wt_b_ltf_entry.py` (45 пар, 2.5г, LTF+4h-фильтр). Добавить три `kind` и сравнительную таблицу. **Тест 1 — Elliott n_down:** SHORT n_down_1h∈{3,4}, LONG n_down_1h==0; `calculate_n_down` есть в `core/indicators/indicators.py`; `kind="ltf_ndown"`. **Тест 2 — CHoCH 15m:** `detect_structure_breaks(df_15m, length=5)` — CHoCH в направлении сигнала в окне 8 баров после 1h-триггера; `kind="ltf_choch"`. **Тест 3 — LTF-вход в OTE:** вместо первого 15m-кросса — кросс строго в OTE-зоне (0.618–0.786 Фибо последнего 1h-свинга через zigzag period=10); `kind="ltf_ote"`. **Вывод:** 6 строк (Baseline/LTF/LTF+4h/+ndown/+CHoCH/+OTE) × avgR/WR/n/sumR, разбивка по direction и div_strength. SL везде через `calculate_trend(atr_period=43, factor=1.25)` — единый калькулятор. Python: `C:/Users/yogoru/AppData/Local/Programs/Python/Python312/python.exe`. Детали в DISCUSSION 13.06.

---
## ID: **DS-325** — CONFIG-TYPED: типизировать `config_loader.py` через pydantic-settings (бэклог…

**CONFIG-TYPED: типизировать `config_loader.py` через pydantic-settings (бэклог, ~пол-дня, нулевой риск).** **Диагноз (4 боли):** (1) дублирование defaults — `_get_default_config()` (100 строк) дублирует `config.yaml`, значения разъехались (`volume_multiplier: 4.0` в YAML vs `5.0` в дефолтах — бот молча стартует с другим конфигом при ошибке загрузки); (2) строковый доступ без типов — `config.get("trading.tsl_activation_r")` → `Any`, опечатка в ключе → `None` в рантайме, IDE слепа; (3) 8 одинаковых `save_*()` методов (300+ строк) — один паттерн read→patch→write скопирован 8 раз; (4) велосипед `_replace_env_vars()` — 15 строк ручной замены `${VAR}` вместо нативного механизма pydantic. **Что делать:** Pydantic-модели для каждой секции (`TradingConfig`, `AnalysisConfig`, `SignalQualityConfig`, ...) + кастомный `YamlConfigSettingsSource` + `SecretStr` для `api_key`/`secret` (API-ключи не текут в логи). Доступ: `config.trading.tsl_activation_r` (float, IDE знает) вместо строки. Убрать `_get_default_config()` и `_replace_env_vars()`. **Что НЕ трогать:** `save_*()` методы — оставить как есть (pydantic при записи делает `yaml.dump(model_dump())` → все 708 строк комментариев с историей решений теряются навсегда; write-слой = текущий механизм через raw YAML). Hot-reload `config.reload()` = переинициализация объекта. **Acceptance:** `config.trading.tsl_activation_r` возвращает `float`; бот запускается с ошибкой при невалидном конфиге (не в глубине кода); API-ключи — `SecretStr`.

---
## ID: **ARCH-128-C01** — СЛЕПОТА CHoCH/SMC (length=50) в ядре паттернов → length=5 + ре-майнинг.** Найд…

**СЛЕПОТА CHoCH/SMC (length=50) в ядре паттернов → length=5 + ре-майнинг.** Найдено 11.06 сверкой с OKO-SM. `swing_bridge` ×3 (`etl_order_blocks`/`etl_bos_choch`/`etl_ote_premium`) зовут `detect_structure_breaks(df)` БЕЗ length → дефолт 50. Замер `scripts/choch_length_check.py`: 5m/15m=**0 CHoCH**, 1h лаг 202. Эталон=length=5 ([[calib_choch_length5]]). Отравлены OB/BOS/CHoCH/OTE-premium → **69/200 паттернов (34%)** на слепых ob/discount (131 чистые на FVG). 🔴 train↔live: паттерны майнились на 50 → фикс+ре-майнинг неразделимы. **План:** `docs/PLAN_C01_choch_length_fix.md`. **Реестр:** `docs/DUPLICATES_REGISTRY.md`→C-01. **Handoff:** DISCUSSION 11.06. **DS:** фикс за config-флагом + ре-майнинг 69 + A/B бэктест (раннеры не сломать). **Claude:** валидирую+решаю кат.

---
## ID: **REGIME-V2** — Активировать regime v2 (HTF-доминанта) — через УНИФИКАЦИЮ (D-10), не просто фл…

**Активировать regime v2 (HTF-доминанта) — через УНИФИКАЦИЮ (D-10), не просто флаг.** Данные 11.06 (6992 сделок, `regime_v2_validated.md`): v2 ЛУЧШЕ разделяет edge (разброс avgR **0.798 vs v1 0.552**), v1 валит 47% в RANGE (мислейбл, [[arch124_regime_audit]]), v2 22%. **RANGE-сделки ПРИБЫЛЬНЫ (0.971) → гейты на RANGE резали прибыль** (давний вопрос). **🔴 НАХОДКА 11.06 (D-10):** regime = дубль 3 метода в 6+ местах (`classify_from_ohlcv` старый ADX в scan_loop:234 HIGH_VOL-gate!, `classify_from_dataframes` v1, `classify_v2` shadow). `use_v2` флаг меняет ТОЛЬКО trade_simulator → гейты входа на старом ADX, активация НЕПОЛНА. **План:** (1) все точки regime → читать `pair_context.regime` из Bus (monitoring уже ✅); (2) Bus публикует `classify_v2`; (3) `use_v2` переключает реально всё; (4) A/B измерить. Реестр `docs/DUPLICATES_REGISTRY.md`→D-10.

---
## ID: **HIGH-VOL-VOLUME** — HIGH_VOL + объём (VSA) — рой 7/7 консенсус 11.06.** HIGH_VOL = чистый ATR (вол…

**HIGH_VOL + объём (VSA) — рой 7/7 консенсус 11.06.** HIGH_VOL = чистый ATR (волатильность 1.8×median) БЕЗ объёма = концептуальная дыра (avgR **0.176** худший режим). Объём ПИШЕМ (`volume_24h`/`pivot_volume_z`) но режим НЕ юзает — ирония crypto_VOLUME_bot. **Рой:** интегрировать объём (volume spike → impulse vs вынос/шум), смягчить HARD-гейт (пропускать объёмные пробои = сильнейшие движения). **Спор 4vs3:** обогатить HIGH_VOL ∥ отдельная **VolumeSphere** (Куб). Индустрия: VSA. Полное: `obsidian/Team-Discussions/2026-06-11-high_vol-*`, `regime_v2_validated.md`.

---
## ID: ARCH-129-FLOW — 🆕 ЧИСТОТА ПОТОКОВ ДАННЫХ — ЭПИК (голосовая юзера 09.06 «Проект_Клауд_Телеграм»…

**🆕 ЧИСТОТА ПОТОКОВ ДАННЫХ — ЭПИК (голосовая юзера 09.06 «Проект_Клауд_Телеграм», `Obsidian-Brain/_Inbox`).** Цель — убрать хаос в [[Куб]]: прозрачность потоков, централизованно хранить гейты, избегать перекрёстных вычислений, сверить переиспользованные формулы. Продолжает DS-312/313, ARCH-117 (WT/RSI), ARCH-118 (снимок). Детали: [[arch_two_smc_detector_sets]]. <br>**✅ ФАЗА 0 — АУДИТ (готов 09.06, `scripts/arch129_detector_parity.py`):** замерен дрейф 2 наборов SMC-детекторов на 30 прогонах (15 пар×15m/1h): **FVG 69%, OB 7%🔴, structure 87%**. **🎯 КАНОН РЕШЁН ЭТАЛОНОМ OKO-SM:** набор **A** (`smc_engine`) воспроизводит эталон (FVG auto-порог cum\

---
## ID: ARCH-96-EXEC — Execution Sphere — разморозить, единый слой ордер-менеджмента.** Сейчас исполн…

**Execution Sphere — разморозить, единый слой ордер-менеджмента.** Сейчас исполнение размазано (order_manager/position_sync/repair). Цель: единая сфера Куба для ордеров. *Связано: инцидент TSL/repair 06.06.* **→ ЯДРО = ARCH-96-MULTIACCT (мультиаккаунт).**

---
## ID: **ARCH-96-HUB** — 🆕 ЕДИНЫЙ ACCOUNT-АГНОСТИЧНЫЙ КАНАЛ ИСПОЛНЕНИЯ…

**🆕 ЕДИНЫЙ ACCOUNT-АГНОСТИЧНЫЙ КАНАЛ ИСПОЛНЕНИЯ — ПЕРЕИСПОЛЬЗОВАНИЕ, НЕ ДУБЛИРОВАНИЕ (принцип юзера 09.06).** 🧬 **Суть (формулировка юзера):** sub НЕ копия main (дублирование→дрейф→баг), а ТОТ ЖЕ код с account=параметр (переиспользование, нечему расходиться). DRY на уровне исполнения — сквозной закон Куба вместе с [[arch_two_smc_detector_sets

---
## ID: ARCH-96-MULTIACCT — Мульти-аккаунт BingX (субаккаунты) — обойти потолок 100 ордеров/аккаунт для ма…

**Мульти-аккаунт BingX (субаккаунты) — обойти потолок 100 ордеров/аккаунт для масштабирования веера (OTE+WAVE-FLAGMAN).** Дизайн-док `docs/ARCH-96-MULTIACCOUNT-DESIGN.md` + ВЕРДИКТ РОЯ (08.06, 7 моделей консенсус). **Архитектура:** AccountRouter (слой НАД OrderManager) + БД sticky symbol→account (НЕ hashing — сдвиг=разрыв позиций) + make_client(mode,acc) + расширить единую дверь `_get_client_synced(symbol)`. **🔴 Этапность (рой: IP ПЕРВЫМ!):** ✅ **Ф1 IP-троттлинг ГОТОВ (fcade86):** GlobalRateLimiter (синглтон=общий IP-бюджет) на get/post/post_raw/delete + `_maybe_set_ban`(100410/109429→глоб.пауза). Smoke OK. Нужен рестарт. Ф1 было: GlobalRateLimiter на ВСЕ торговые запросы (сейчас только OHLCV) → лечит 100410-боль СЕЙЧАС + фундамент; Ф2 AccountRouter+sticky+2 суба VST; Ф3 order-count гибрид(pending+REST)+динам.route; Ф4 failover(freeze+резерв)+transfer API. **Старт: Ф1 IP-троттлинг.** Verified: make_client(mode)→1 клиент, OrderManager 1 дверь (13+ вызовов).

---
## ID: DS-BRIDGE-SNAP — Мост `trade_features` → решения: arch104/ote_nested СЛЕПЫ к снимку.** Снимок 2…

**Мост `trade_features` → решения: arch104/ote_nested СЛЕПЫ к снимку.** Снимок 211 фич ПИШЕТСЯ (ARCH-118 ✅), но движки его НЕ ЧИТАЮТ для гейтов/решений — архив постфактум. Цель: движки используют контекст снимка на входе (data-proven гейты: напр. `ema50_above_ema200_1h`→блок OTE SHORT, доказано Δ−1.5R на снимках). DEV-200.2 мост (f94b0f7) частично снял слепоту (combinator-флаги→агрегатор, 3% заполняемость). *Моя зона — снимок/гейты.*

---
## ID: DS-RISKINT-PROD — RiskIntelligence → production: код написан, НЕ включён.** RI v1 (sizing/lifecy…

**RiskIntelligence → production: код написан, НЕ включён.** RI v1 (sizing/lifecycle) существует, но не в боевом пути для всех источников. Включить + A/B.

---
## ID: DS-CTXBUS-38 — Shared Context Bus — наполнить до спроектированных 38 полей.** Центральная сфе…

**Shared Context Bus — наполнить до спроектированных 38 полей.** Центральная сфера Куба недонаполнена. Связать снимок (trade_features) ⟷ Bus runtime.

---
## ID: TR-ERA4 — Эра-4 замер (08.06, n_ote=745 n_arch=1760): OTE флагман +1115R avgR+1.50…

**Эра-4 замер (08.06, n_ote=745 n_arch=1760): OTE флагман +1115R avgR+1.50; arch104 ожил (LTF) +387R avgR+0.22.** 🔴 **arch104 LONG avgR=−0.01 — НЕ дефект, РЫНОК:** BTC −14% за неделю (73846→60851, разворот 07.06). LONG ранняя(медвежий)−0.27→поздняя(разворот)+0.20; SHORT +0.50→+0.28. **Урок: судить по avgR с учётом рыночной фазы (data-era/режим split), иначе медвежий период «убивает» рабочий LONG в усреднении.** НЕ отключать arch104 LONG. Накопить бычью фазу для чистого замера.

---
## ID: WAVE-SERVICE — MTF-волновой сервис — недостающее звено для pivot/arch104/OTE «знать где в вол…

**MTF-волновой сервис — недостающее звено для pivot/arch104/OTE «знать где в волне».** Корень слепоты: входят БЕЗ волновой фазы (pivot LONG на обвале=нож W12 −0.94 WR2%, на росте=валид W16 +0.99). **ЕСТЬ (кирпичи):** `detect_elliott_impulse`(smc_engine — ТОЛЬКО импульс R1/R2/R3), `calculate_n_down/n_up`(прокси), `elliott_*_impulse`/`elliott_textbook`(флаги снимка). **🔴 ТАКСОНОМИЯ (эталон `docs/Гайд по структурам движения.pdf`+`коррекции.pdf`, 08.06):** ДВИЖЕНИЕ — импульс✅, диагональ начальная❌, **диагональ КОНЕЧНАЯ❌⭐**(волна5/C=конец тренда=разворот); КОРРЕКЦИЯ — зигзаг ABC❌, двойной зигзаг WXY❌, треугольник ABCDE❌, плоскость ABC❌, комбинация WXY❌. **Чего НЕТ:** WaveService (оркестровка), классификация структуры (импульс vs коррекция), nested 4h⟷1h, Фибо-валидация. **Цель:** per ТФ → {structure, phase, wave_num, position} + MTF-согласование (4h импульс↑+1h коррекция=LONG на откате) → Bus `wave_snap` → движки вход по фазе. **КЛЮЧ к PIVOT-CONTEXT:** pivot LONG нож=середина импульса-3 вниз; валид=конец коррекции (зигзаг/плоскость C) ИЛИ конечная диагональ. **Фибо(гайд):** имп w2=0.618w1/w4=0.382w3/w5=w1\

---
## ID: WAVE-FLAGMAN — 🆕 НОВЫЙ флагман = ОЦИФРОВКА разгонной схемы юзера (раскрыта 08.06, [[user_wave…

**🆕 НОВЫЙ флагман = ОЦИФРОВКА разгонной схемы юзера (раскрыта 08.06, [[user_wave_runner_strategy]]).** 🧬 **Стратегия юзера ($50→$7000 руками):** разворот на МЛАДШЕМ ТФ → вход на откате после волны-1 → вылет в волну-3 (длинную) → после 1-го импульса на СТАРШЕМ ТФ выход → реинвест(50+профит) → откат старшего ТФ → опять волна-3 = КАСКАД младший→старший ТФ (=наш nested-MTF, OTE риск×10). **Почему оцифровать:** юзер «эмоционально подгорел» (плечо, страх упустить→преждевременные входы→потери). БОТ не боится → берёт edge без эмоции (= суть проекта «убрать себя как эмоцию»). **Движок (НЕ в OTE):** связка Волна+SMC+OTE+Пивоты, конфлюэнция Фибо×Пивот×CHoCH-retest. Бэктест: REVERSAL_SHORT WR72% +0.72R ([[wave_smc_backtest_validated]]). **🔴 SL под ИНВАЛИДАЦИЮ структуры (НЕ безубыток!):** вход в волну-3 → волна-2 откатывает глубоко (0.618-0.786 волны-1) → SL под начало волны-1 (правило: волна-2 не за начало волны-1), держать через откат-2. **Живое подтверждение 08.06:** XLM LONG @0.1987 (зона 4h-OTE×S1) → +71% (волна-3 пошла!). **RR честный = от инвалидации:** вход на МЛАДШЕМ ТФ (1m/3m) → компактный стоп под swing → RR 7:1 (vs 2.4:1 дальний). **🔴 ГЛАВНЫЙ ВЫЗОВ:** читать ХАРАКТЕР волны-2 (затяжная: накопление→вынос ликвидности→ТОЛЬКО потом волна-3; различить накопление vs разворот, sweep-ликвидности vs инвалидация — объёмы/время/EQL-EQH). Это превращает «бот по учебнику 1-2-3» в «почерк юзера». SINGLE+TSL clamp50. signal_type='wave_smc'. Старт: `scripts/wave_smc_entry.py`→детектор→observer-loop. **🔴 КРИТИЧНО (инсайт юзера 08.06): zigzag `dev` ДОЛЖЕН адаптироваться по TF** — фикс dev=3 на 5m=шум(9 точек), на 4h=слизывает структуру → ложные/пропущенные сетапы. Решения: ~~(1) dev_per_tf таблица~~ — **ОТВЕРГНУТА демо 08.06** (dev зависит НЕ от TF, а от окна/волатильности: 5m опт dev=3, 4h опт dev=1.5 при окне 150 — обратно «логике»). **(2) АДАПТИВНЫЙ dev = ПРИОРИТЕТ:** подбирать dev пока N_swing≈целевое (~8 точек на окно) → авто под любой TF/окно/монету. (3) мульти-масштаб `detect_elliott_mtf(devs=3,5,8)` УЖЕ есть — крупный=главные волны, мелкий=подволны = фрактальная разметка. Без адаптива WAVE-FLAGMAN «не поймает разметку». → [[user_wave_runner_strategy]].

---
## ID: WAVE-WATCH — 🆕 --watch + КАНАЛ-СИГНАЛЫ (идея юзера 08.06).** Расширить `scripts/wave_smc_en…

**🆕 --watch + КАНАЛ-СИГНАЛЫ (идея юзера 08.06).** Расширить `scripts/wave_smc_entry.py --watch <ПАРА>`: фон-цикл (60-180с) → АЛЕРТ когда (1) цена в конфлюэнт-зоне (Фибо×Пивот) И (2) LTF (3m/5m) CHoCH в сторону = триггер созрел. **🔴 Подача БЕЗ терминала (юзер в России, Telegram-доступ проблемный — проект УЖЕ работает без TG):** супер-сильные сигналы (Волна+SMC+Метатрон конфлюэнция) → в КАНАЛ юзера (раньше слал из TradingView). Только сильнейшие (не спам). Не торгует — сигналит для ручного входа. Альтернатива: простой веб-интерфейс (надстройка без CLI). **Связь:** одно ядро с WAVE-FLAGMAN (watch=ручной, flagman=авто). Старт: --watch + polling + зона∩триггер + канал-уведомление.

---
## ID: WAVE-CHART — 🆕 Размеченный график → PNG → TG (прототип ГОТОВ 08.06).** `core/ui/chart_build…

**🆕 Размеченный график → PNG → TG (прототип ГОТОВ 08.06).** `core/ui/chart_builder.py`(matplotlib+mplfinance, уже есть) + overlay: 🌊 волновые метки (0-1-2-3-4-5, нумерация С 0 — волна N=отрезок(N-1)→N) + 🟢🔴 OB-боксы(bull/bear) + 📐 FVG(штрих) + 💧 EQL + 4h/daily-пивоты + вход/SL/TP стрелки. **Прототип:** `/tmp/wave_chart5m.py` (XLM 5m: волна+OB×4+FVG×12+EQL+пивоты, dev=2 ловит подволны). **Поток:** WAVE-FLAGMAN/WATCH сетап → chart_builder PNG → TG-канал юзера (визуальный сигнал = почерк юзера, как раньше в TradingView). **Доставка отделена от рендера** (TG/папка/web — юзер в РФ). **🔴 След.уровень:** маркировка ФАЗЫ (импульс vs зигзаг-накопление) на графике = «чтение характера волны» [[user_wave_runner_strategy]]. **🆕 Правки 09.06 (`scripts/wave_chart_send.py`):** (1) ❌ нумерация волн УБРАНА (zigzag нумерует все swing подряд, не различает импульс 1-5 / коррекцию ABC → «7 волн» врёт; вернуть КОГДА появится классификатор структуры из WAVE-SERVICE); (2) ✅ RR до ДАЛЬНЕЙ цели старшего ТФ (daily high/low 20д) = суть MTF (компактный swing-SL + далёкая цель → asymmetric RR 1:10-26), TP показывает TP1⟶TP2 (фиксация⟶раннер); (3) ✅ контр-тренд сценарий помечен ⚠️ (RR-потенциал есть, но против старшего bias = не приоритет); (4) ✅ вердикт указывает КОНКРЕТНУЮ след. daily OTE-зону ниже цены (0.618/0.705/0.786 + «ищи OB») вместо общего «ждать OTE». **🔮 В ПЛАНЫ (идея юзера 09.06): ВЛОЖЕННОСТЬ расчёта волн как в Кубе** — в старшем ТФ считать младшие волны, каскад 1D→4h→1h→15m (фрактал: волна-3 на 1D = импульс 1-5 на 4h = …). Уже частично есть `detect_elliott_mtf(devs)`. Цель WAVE-SERVICE.

---
## ID: PIVOT-WAVE-GATE — Вернуть pivot_reversal из shadow С волновым гейтом (бэктест обосновал).** pivo…

**Вернуть pivot_reversal из shadow С волновым гейтом (бэктест обосновал).** pivot слепой = −0.36R WR27% ([[PIVOT-CONTEXT]]); связка волна+SMC = +0.72R WR72% на тех же разворотах. **Гейт:** pivot_reversal проходит ТОЛЬКО если волновая фаза разрешает (импульс против = блок; конец коррекции/CHoCH+откат = разрешить). Читает wave-контекст (из WAVE-SERVICE Bus ИЛИ инлайн `wave_smc_entry` логика). После гейта → `arch104.vst_trading`/`signal_router pivot_reversal exchange_enabled` обратно true. **Проверка:** бэктест pivot+гейт на тех −1126R LONG (отсёк бы слив?).

---
## ID: PIVOT-CONTEXT — pivot_reversal СЛЕП к рыночной фазе → −1126R слив (НЕ дефект, СЛЕПОТА…

**pivot_reversal СЛЕП к рыночной фазе → −1126R слив (НЕ дефект, СЛЕПОТА — DS-приоритет#2).** Data (3517 сделок): pivot LONG = чистая функция рынка — РОСТ W10/W16 +0.67/+0.99 WR56-60% ✅, ОБВАЛ W12/W15 −0.94/−1.20 **WR 2-7%** 🔴. atr_trend_1h_bias ЕСТЬ в features но SHADOW (постфактум, НЕ гейт) → входит LONG при atr DOWN (531 сделок −0.38). По pivot_level: только R2 +1.74 живёт (PP/S1/R1 сливают). **РЕШЕНИЕ (накормить, НЕ резать — урок arch104):** гейт pivot LONG ⊥ BTC/HTF TREND_DOWN (Сфера 5 Cross-Market + снимок ARCH-118 ema50<ema200). = первый реальный кейс **DS-BRIDGE-SNAP** (движки читают контекст снимка). Замыкает Куб: ARCH-118(снимок)→движок видит фазу→не лонг против рынка. confluence SHORT −203R аналогично (контр-фаза).

---
## ID: VST-SLIPPAGE-OLD — R_multiple ОБМАНЧИВ — баланс минус при sumR+.** Юзер: баланс VST идёт вниз, хо…

**R_multiple ОБМАНЧИВ — баланс минус при sumR+.** Юзер: баланс VST идёт вниз, хотя замер +1125R(ote)/+386R(arch). **Диагностика:** открытые НЕ виноваты (unrealized +19.9R). Комиссии ~0.05-0.12R (не критично). **КОРЕНЬ — slippage: BingX VST fill ~0.45%/сторона хуже рынка** (из order_book разведки 03.06, `memory/order_book_backlog.md`). slippage_R = 0.9% / median_SL: **ote ~1.1R, arch104 ~0.48R на сделку.** Реальный нетто: **ote +1.50→+0.28 (скромный+), arch104 +0.22→−0.31 (МИНУС!)** → arch104 (1770 сделок, движение мелкое median+0.09R) тонет в slippage, тянет баланс. **Фиксы:** (1) добавить slippage в `performance_engine` (реальный edge ≠ бумажный R); (2) **min-R фильтр на вход** — R должен покрыть slippage+комиссию (ote R>1, arch104 R>0.6); (3) arch104 мелкие движения не торговать. ⚠️ ВЕСЬ анализ avgR в проекте под вопросом — мерили бумажный R.

---
## ID: VST-FUNDING — Funding добивает баланс: 172 perpetual-позиции висят днями** (OTE runner до HT…

**Funding добивает баланс: 172 perpetual-позиции висят днями** (OTE runner до HTF-target = días). Funding каждые 8ч × дни × позиции = накопленный расход, НЕ в R_multiple. **Связь с Inbox② (узел данных).** Нужно: получать funding rate по монете → (1) видеть реальную стоимость удержания; (2) фильтр входа против дорогого funding; (3) time-exit короче для дорогого funding.

---
## ID: TSL-PROFILE — Per-strategy Gear-профили для hybrid TSL (вердикт роя 08.06, КОНСЕНСУС 5-6 мод…

**Per-strategy Gear-профили для hybrid TSL (вердикт роя 08.06, КОНСЕНСУС 5-6 моделей).** Проблема: DS-321 hybrid (Gear по MFE-ATR) глобальный → OTE long-runner активирует @4R (MFE~4ATR) → сразу Gear3 lock → режет хвост (realized 1.29 vs maxR 1.75, **26% на столе**). **Вердикт роя:** движок (hybrid) = универсален ✅, но Gear-пороги signal_type-aware. TSL trailing = свойство ДВИЖКА, Gear-параметры = задаёт СТРАТЕГИЯ. **Граница (на согласовании DS):** DS добавляет `profile` param в `compute_hybrid_tsl` (дефолт=текущее 2/4/12); Claude задаёт OTE-профиль `ote_nested→{gear3_atr:8}` (long-runner дышит). **Gear3 = f(target_RR):** короткие(RR2-3)→4ATR, OTE(RR8-22)→8ATR. **Бонус роя:** slippage+funding делают универсальный TSL убыточным для мелких arch104 (связь VST-SLIPPAGE/FUNDING). Разбор: `obsidian/Team-Discussions/2026-06-08-философия-tsl-выхода-*`.

---
## ID: INBOX-FUNDING-NODE — Inbox② (08.06 02:55): доработать узел получения данных биржи**…

**Inbox② (08.06 02:55): доработать узел получения данных биржи** — funding rate по монете + стакан + ордера макс.глубины. **🎯 Прямо решает VST-FUNDING/SLIPPAGE!** Glubokий стакан Binance (depth 5000, публичный без ключа) — уже наработан в `memory/order_book_backlog.md`. Цель: funding+стакан → реальная стоимость + slippage-оценка + магниты цены.

---
## ID: PROXY-NODE — ✅ ФАЗА 1+2 ГОТОВЫ + ПРОФИЛЬ (коммит 7b5f1f8, 13.06).** ProxyNode…

**✅ ФАЗА 1+2 ГОТОВЫ + ПРОФИЛЬ (коммит 7b5f1f8, 13.06).** ProxyNode — ротация IP для market-data (КОРЕНЬ: BingX лимит rps ПО IP). **🔴 ПРАВИЛО: ТОЛЬКО public OHLCV через прокси; торговля — ВСЕГДА direct IP (ключ↔whitelist, чужой IP=бан).** **Ф1:** `proxy_pool.py` (round-robin least-loaded + token-bucket per-IP + health-карантин + fallback direct + env PROXY_LIST). **Ф2:** интеграция в `ApiEngine` (market-data через пул, aiohttp_proxy без lock — race не портит OHLCV; throttled логи `[PROXY]`); прокинуто bot→RealTimeData→ApiEngine. **ПРОФИЛЬ:** `config_loader.perf()` — один флаг `proxy_pool.enabled` переключает performance↔overrides (база rps35/sem5/10 ↔ proxy rps100/sem15/30), не править руками. **🔬 A/B ДОКАЗАНО (13.06):** прокси работают (sandbox давал ложный 10013, не сеть; WireGuard kill-switch мешал split-tunnel→прокси через VPN, латентность ~1с). При 202 парах ВЫИГРЫША НЕТ (цикл ~125с=как без прокси, RPS не bottleneck, rps35→100 не влияет). При 526 пар бан 100410 от ТОРГОВОГО direct IP (не прокси). **Раскроются при 500+ пар** (1 IP упрётся в 50 RPS) — но тогда упрётся и торговый direct IP (нужен раздельный лимит). 3 Singapore прокси в .env, enabled=true (работает, цикл не хуже). **Куб: DataInfraSphere. Связь D-072 DataService, гейт пар (min_volume).**

---
## ID: INBOX-WAVE-CLOUD — Inbox① (08.06 02:54): волновая теория Эллиотта в cloud + обход API-лимита Bing…

**Inbox① (08.06 02:54): волновая теория Эллиотта в cloud + обход API-лимита BingX.** Анализ ограничения API BingX; алгоритм Эллиотта в cloud; обход лимита через доп.аккаунт/субаккаунт. *Эллиотт уже частично в боте (n_down/up прокси, `obsidian/Concepts/Elliott-Wave`).*

---
## ID: ARCH-124-FU — Production-флип `regime_v2`** (ARCH-124 ✅ = аудит+shadow `5389bcc`/`ded6ea4`…

**Production-флип `regime_v2`** (ARCH-124 ✅ = аудит+shadow `5389bcc`/`ded6ea4`; это — включение в бой). **Контроль-проверка 02.06 (TASKS✅ vs факт):** `config market_regime.use_v2:false` (НЕ флипнут), накоплено **14/~30** закрытых с `regime_v2` shadow в БД. **Действие:** при ~30 закрытых → `python scripts/regime_v2_ab.py` → если v2 ловит вредные SHORT (v1=RANGE→v2=TREND_DOWN, как APE/INJ/NEAR/STX на истории) → **флип `market_regime.use_v2:true`** + рестарт. **Зачем:** regime кормит 8 потребителей (ML r_predictor, mtf penalty, pivot_reversal, sl_tp, regime_strategy); RANGE 78% мислейбл ([market_regime.py:191](core/indicators/market_regime.py#L191) требует синхронности всех TF) → чистка разблокирует качество сигналов по всему Кубу. **Acceptance:** A/B на n≥30 закрытых → решение флип/откат, обоснованное данными.

---
## ID: ARCH-125 — Видение зафиксировано (ВЫСШИЙ УРОВЕНЬ).** Архитектура Куба переросла проект →…

**Видение зафиксировано (ВЫСШИЙ УРОВЕНЬ).** Архитектура Куба переросла проект → выделить переносимый скелет (`metatron-core`) и сделать бот + LLM-рой двумя клиентами. **Новый примитив:** `AdvisorPort` (Hexagonal/Ports&Adapters) — Куб **подключает** недетерминированные/переиспользуемые сервисы (рой, внешний ML), а НЕ встраивает. Контракт `consult(AdvisoryRequest)→AdvisoryVerdict\

---
## ID: ARCH-126 — AdvisorPort реализован end-to-end (продолжение ARCH-125, ADR-002).** DeepSeek-…

**AdvisorPort реализован end-to-end (продолжение ARCH-125, ADR-002).** DeepSeek-v4 (1M) = ДИРИЖЁР роя: умная нарезка контекста под каждую из 7 моделей + синтез на полном контексте (vs обрезки mistral-meta). **Swarm-сторона (Claude swarm):** `tools/swarm_orchestrator.py` (`SwarmOrchestrator` реализует `AdvisorPort`) + `core/intelligence/advisor_contract.py` (FROZEN: `AdvisoryRequest/Verdict/AdvisorPort`, 0 зависимостей = зерно metatron-core §B). **Порт-сторона (Claude порт):** `advisor_connector.py` (timeout/circuit-breaker/shadow/persist) + `bot/loops/advisor_loop.py` (часовой по закрытию свечи + ТГ #брифинг) + хук `bot.py:spawn_advisor`. **Высота B+C** (НЕ per-pair scan_loop — рой слеп к данным DEV-240, дублирует сферы): глобальный брифинг рынка (`intent=market_brief`, label∈{RISK_ON/RISK_OFF/CAUTION/HOLD}) + ревью исходов (C свёрнут в B, один consult). **Каскад деградации проверен вживую (balance=0):** DS 402→mistral-fallback→raw, выдал CAUTION conf=0.80 — НЕ ломается без баланса. **prompt-cache** порядок (статика первой, ×50-120 при v4-pro). **В ПРОДЕ shadow** (`advisor.enabled=true`), копит `advisor_brief_log.jsonl` для A/B. **Соответствие Кубу:** AdvisorPort = ребро Куб↔внешний советник; мета-куб (2×Claude+DS+рой) — фрактал «куб в Кубе». **Коммиты:** 86e30f4→8845abc (13). **Дальше:** баланс DeepSeek → полный DS-режим; Phase 2 многораундовые уточнения; A/B advisor-брифингов.

---
## ID: ARCH-127 — Переосмысление сигнального ядра: regime-классификация (TREND/RANGE)…

**Переосмысление сигнального ядра: regime-классификация (TREND/RANGE) — ТУПИК (78% мислейбл, не помогает торговле). Ось = MTF-зоны OB/OS + волна + Фибо, НЕ лейбл режима.** Философия (пользователь): искать RANGE/боковик бессмысленно; ядро = LONG из OS-экстремума / SHORT из OB-экстремума, на любом ТФ НО с согласованием старшего, + Эллиотт-фаза + Фибо/OTE. **Подтверждено данными 02.06:** liquidity_sweep LONG +4.4R (вход из OS), divergence SHORT n_down=4 +3.37R (OB), deep LTF pullback n_down_1h=6-8→LONG; regime_v2 A/B (рой 7/7 conf=0.92): use_v2 НЕ включать, v2 лагает в OS. **Ключевой инсайт — MTF=фазовая карта со сдвигом:** 4h-OB (06.05) и 1h-OB (10.05) рассинхронны по природе → v1 (синхрон) и v2 (доминанта) оба неверны; режим = ВЗАИМНОЕ отношение фаз ТФ. **Концепция (переоркестровка существующего, НЕ стройка с нуля):** WTService(зоны) × MTF-cache(согласование) × Elliott n_down/up(фаза) × PivotSphere/OTE(Фибо) × TPSelector gravity(+HTF-MA магниты) × SMC(конфлюенция). **Поглощает:** ARCH-119 (WT-reversal = частный случай), ARCH-124 (regime_v2 → подслой). **Расширение вверх (из разбора инфлюенсера RMNVtrade):** 1D/1W контекст + HTF-MA (200W/200D/20W) как магниты-цели (дамп шёл к ma200w ~62k). **Первый шаг (data-driven ПЕРЕД перестройкой):** `scripts/mtf_reversion_backtest.py` на истории (parquet: OB 06.05 + OS-фазы) — вход LONG из MTF-OS-согласования vs baseline, avgR/WR по фазам. Если бьёт — строим. **Acceptance:** бэктест показывает преимущество зонального входа → план перестройки сигнального ядра. **Связь:** Elliott-Pivot Sub-куб (vision), nested LTF паттерны (WR=100%), project_confluence_principle.

---
## ID: OB-DATA — Наработка/инструменты для получения данных стакана (НЕ интегрировано).** Цель:…

**Наработка/инструменты для получения данных стакана (НЕ интегрировано).** Цель: магниты цены + позиционные уровни китов (не скальпинг, снимок раз в день). **Источник: Binance spot depth limit 5000** (публичный, без ключа) — лучший: глубже BingX, реальная ликвидность, BingX торгуется ~0.45% ниже рынка. Endpoints + выводы + готовые скрипты → `memory/order_book_backlog.md`. **Что готово (`e:/tmp/`):** стакан+пивоты+конфлюенция, кумулятивная ликвидность по зонам, кластеры, история уровня. Пивоты по формуле бота (`calculate_pivot_points`). **Идея интеграции:** OrderBookSphere/Сфера ликвидности — дневной снимок стен → Bus как магниты + подтверждение пивотов; сохранение снимков с датой → отсев спуфинга. **⚠️ REST=снимок, не поток (спуфинг ловится серией).** Примеры разборов BTC/SOL: DISCUSSION 03.06 + obsidian/Team-Discussions/2026-06-03-*. **Соответствие Кубу:** новая сфера + ребро к PivotSphere/SMC/TPSelector.

---
## ID: DEV-237-B — Под вопросом, пока не до неё.** Постоянная замена временному shadow ARCH-78: н…

**Под вопросом, пока не до неё.** Постоянная замена временному shadow ARCH-78: не блокировать LONG, если BTC реально стоит (

---
## ID: [DEV-239](#dev-239) — 53 pivot_reversal LONG сделки имели `shadow_pivot_real_touch=NULL` и `shadow_p…

**53 pivot_reversal LONG сделки имели `shadow_pivot_real_touch=NULL` и `shadow_pivot_volume_spike=NULL`** (100%). Корень: `core/observability/shadow_signal_quality.py:_compute_pivot_shadow` требует `df_15m`, который пробрасывается из `trade_simulator.py:514` через `data_collector._engine._cache.get_stale((sym,"15m"),limit=30)`. Возвращает None → shadow проверки пропускаются. **Возможные причины:** (a) limit=30 недостаточен (cache содержит меньше), (b) формат ключа кеша не совпадает, (c) cache.get_stale требует другой схемы вызова. **Фикс:** (A) исследовать какие ключи реально лежат в кеше для pivot_reversal LONG пар; (B) альтернативно — извлечь df_15m из `recommendation.market_context.mtf_context` (если доступно) или передавать через extra_features при вызове register_trade_async из scan_loop; (C) понизить limit до 22 (нам нужно 21 бар). **Acceptance:** ≥80% новых pivot_reversal LONG сделок имеют `shadow_pivot_real_touch` ∈ (true,false) (не NULL).

---
## ID: [DEV-240](#dev-240) — Гипотеза роя `scan_loop_duration > 250s = skip entries this cycle` ОПРОВЕРГНУТ…

**Гипотеза роя `scan_loop_duration > 250s = skip entries this cycle` ОПРОВЕРГНУТА данными.** Shadow n=630 closed (27.05-31.05): LATE (scan>250s) n=418 avgR=-0.135 WR=50.5%; FAST (<250s) n=212 avgR=-0.612 WR=47.2%. **Δ +0.477R/сделку В ПОЛЬЗУ LATE.** Возможная причина: LATE циклы успевают накопить более полный confirmation context (FAST = первый импульс без подтверждений). Альтернатива: scan_loop duration коррелирует с волатильностью рынка — высокая волатильность даёт более качественные сигналы. **Действие:** НЕ внедрять timing-guard. Оставить shadow логирование `shadow_scan_loop_late/duration_s` в features_json для долгосрочного мониторинга. **Триггер пересмотра:** если данные изменятся на n≥1000 closed (~7-10 дней).

---
## ID: [ARCH-124](#arch-124) — АУДИТ системы режимов — помогает или мешает?** Гипотеза ARCH: «вычисление режи…

**АУДИТ системы режимов — помогает или мешает?** Гипотеза ARCH: «вычисление режимов нам очень мешает». **Находки (данные 7д, n=1432):** **(1) RANGE = убыточный мажоритар:** RANGE 55% потока avgR=-0.145 vs TREND_UP +0.144 / TREND_DOWN +0.398. RANGE тянет картину вниз. **(2) Классификатор «рыхлый» (over-labeling RANGE):** `classify_from_dataframes` (market_regime.py): MTF конфликт (15m тренд≠1h) → RANGE; MTF aligned но \

---
## ID: TR-232a — T5_L_02 — почему работает (+6.41R n=11 WR=55%):** разобрать лучший live-паттер…

**T5_L_02 — почему работает (+6.41R n=11 WR=55%):** разобрать лучший live-паттерн. Что в anchor_factors даёт edge? Не один ли TP тащит avgR (4 TP)? Распределение R, не выброс ли? Воспроизводим ли на post-fix данных. Цель — понять и защитить ядро edge

---
## ID: TR-232b — Убытки: −1.00R массово + T4_S_09 (−7.58R n=3):** почему обилие чистых −1.00R (…

**Убытки: −1.00R массово + T4_S_09 (−7.58R n=3):** почему обилие чистых −1.00R (SL без движения — плохой вход / близкий SL?). T4_S_09 −7.58R = slippage/катастрофа? D2_L_L3_15m_03 (n=17 avgR=−0.41, 10 TSL+7 SL) — частый но убыточный. Live-WR ≪ бэктест (97% обещал) — look-ahead в бэктесте? stale-вход? Корень расхождения

---
## ID: TR-232c — 5m-топы не торговали:** L1_golden_LTF_5m (бэктест n=268 WR=97%), T8_L_L3_5m_01…

**5m-топы не торговали:** L1_golden_LTF_5m (бэктест n=268 WR=97%), T8_L_L3_5m_01 (WR=98%) — 0 сделок в live (observer не успевал). После DEV-232 рестарта проверить — пошёл ли их поток. Если да — чистая выборка для валидации

---
## ID: DEV-231 — Дашборд `/api/dashboard` timeout >10с:** `_handle_dashboard_api` → `full_stats…

**Дашборд `/api/dashboard` timeout >10с:** `_handle_dashboard_api` → `full_stats()` тяжёлый (агрегаты по `simulated_trades` + open_trades обогащение). Профилировать запрос, кэшировать тяжёлые агрегаты (TTL 10-30с) или вынести в фоновый расчёт. Симптом «дашборд глючит» (после отключения WS event loop свободен, остался БД-bottleneck)

---
## ID: DEV-229 — АУДИТ масштаба stale-кэша:** скрипт — сколько OPEN сделок имеют расхождение st…

**АУДИТ масштаба stale-кэша:** скрипт — сколько OPEN сделок имеют расхождение stale-cache (df.close в БД min/max) vs реальная цена (REST). Оценить системность: сколько TSL/BE не сработали из-за stale

---
## ID: [DEV-200](#dev-200) — ✅ PHASE 1 ГОТОВ (04.06, observation-only, нужен рестарт).** Реализован co-loca…

**✅ PHASE 1 ГОТОВ (04.06, observation-only, нужен рестарт).** Реализован co-located helper `_publish_and_confirm()` ([scan_loop.py](bot/loops/scan_loop.py)) — публикует событие в EventBus И регистрирует Confirmation в агрегаторе, БЕЗ bus-subscriber. **5 точек подключены:** wt_extreme, smc_bos (UP/DOWN→LONG/SHORT), smc_choch, fvg_touch×2 (→fvg_fill bull=LONG/bear=SHORT), liquidity_sweep (direction→smc_eql/eqh_swept). `+wt_extreme {6,6}` в registry (26 типов). `observe(symbol,side)` в `signal_aggregator.py` — отдаёт ВСЕ confirmations в окне БЕЗ требования trigger (gate `aggregate()` НЕ тронут). Fallback-merge в `monitoring.py` (после DEV-201): мерж observe() в `extra['confirmations']` по source + флаг `confirmations_no_trigger`. Тесты: 65 ✅ (test_confirmations 26 типов + новый test_confirmation_aggregator 5 шт), runtime-smoke OK (6 publish, 5 confirms, aggregate gate=0). **— Корень DEV-238 закрыт: было 4/28 источников, стало ≥9 публикуют в агрегатор.** **Phase 2 (24-48ч после рестарта):** % wt_signal/pivot_reversal сделок с `confirmations_no_trigger=true` + avgR при confirm>0 vs ==0. **Phase 3 (по данным):** SOFT penalty -15 если confirmations==0 (если Δ avgR>+0.3R).

---
## ID: [DEV-201](#dev-201) — ⭐ Частично закрыт DEV-200 Phase 1 (04.06): `observe()` метод реализован** (sig…

**⭐ Частично закрыт DEV-200 Phase 1 (04.06): `observe()` метод реализован** (signal_aggregator.py) + fallback-merge в monitoring.py. **Остаток:** `strength = Σ weight × confidence` для НЕ-ARCH-104 сделок (wt_b, pivot_reversal, divergence) как РЕАЛЬНЫЙ strength (сейчас observe() только пишет в features_json, не влияет на strength). Брать после Phase 2 данных DEV-200. ARCH-104 flow идёт через decision_fusion.py.

---
## ID: **TR-241** — ✅ Скрипт ГОТОВ + инструментовка завершена (04.06).** Запуск ~06.06: `python sc…

**✅ Скрипт ГОТОВ + инструментовка завершена (04.06).** Запуск ~06.06: `python scripts/tr241_confirmation_fillrate.py` (заполняемость+avgR split, R_multiple, фокус wt/pivot, вердикт Δ>+0.3R→Phase 3). Единый helper `attach_confirmations` пишет `confirmations_no_trigger` во ВСЕХ путях (scan_loop watch_list/atr/sideways + monitoring) — **нужен рестарт.** **DEV-200 Phase 2 ВАЛИДАЦИЯ заполняемости (триггер ~06.06, после 24-48ч).** Замерить на закрытых сделках с полем `confirmations_no_trigger` в features_json: **(A)** % wt_signal/pivot_reversal сделок с ≥1 confirmation (`len(confirmations)>0`); **(B)** avgR при `confirm_count>0` vs `==0` (split по signal_type, min 10 на группу, data-era post-рестарт). **🔴 Acceptance ПЕРЕСМОТРЕН (04.06, предв. анализ n=4575 `memory/tr241-confirmation-finding.md`):** заполняемость = факт ПОКРЫТИЯ, НЕ proxy качества (divergence 0% conf но avgR+0.727; ote_nested 0% но +1.493 — самодостаточны). Вердикт ТОЛЬКО по avgR-split **per signal_type** (min 10/группа, data-era post-instrumentation). **Phase 3 НЕ катить слепо/глобально:** предв. данные показали эффект РАЗНОНАПРАВЛЕН — pivot_reversal Δ+0.149R (плюс), но **wt_signal Δ−0.777R (confirmations ВРЕДЯТ!)**. SOFT penalty за confirmations==0 наказал бы лучшие wt_signal. Phase 3 — только per-signal_type, где Δ>+0.3R на НОВОМ пайплайне. ⚠️ предв. данные ДО-инструментовочные (старый confluence ≠ новые helper-источники smc/fvg/div_cascade/wt_cross). SQL по `simulated_trades` (created_at UTC, status TP/SL/TSL/EXPIRED). Источник: DEV-238 + DISCUSSION 01.06. ⚠️ smc_bos копит только tf=1h (DEV-200.2).

---
## ID: **ARCH-118.3** — Phase 3: ОДИН КАЛЬКУЛЯТОР — владелец Claude(OTE).** **Шаг 1 (разблокирует DEV-…

**Phase 3: ОДИН КАЛЬКУЛЯТОР — владелец Claude(OTE).** **Шаг 1 (разблокирует DEV-200.2):** вынести `compute_flags`+индикаторы из `tools/pattern_mining/combinator_v2.py` (research, side-effects) в чистый `core/calculators/` БЕЗ research-импортов. Моя территория (combinator/smc_engine; `ote_retest_setups` уже использую из core/smc в движке генерации). **Шаг 2:** combinator → PairContextBus → агрегатор/EventBus/стратегии/snapshot читают ОТТУДА (не из детекторов). Цель: parity live==бэктест (`scripts/arch118_parity_check.py`=0). Убирает 2 калькулятора = корень самоподтверждения. **Координация:** я выношу калькулятор в core, соседняя сессия подключает мост поверх. Phase 2 НЕ блокируется (растёт событийным слоем). Делать ПОСЛЕ полировки движка OTE. ROADMAP Этап 13 · `memory/arch118_snapshot_decision.md`

---
## ID: [DEV-202](#dev-202) — features_json: confirmations[]:** гранулярная запись всех подтверждений (не пл…

**features_json: confirmations[]:** гранулярная запись всех подтверждений (не плоские поля). Для будущего ML обучения весов. Acceptance: 100% новых сделок имеют поле `confirmations` (list[dict])

---
## ID: [DEV-204](#dev-204) — ML Outcome retrain weights:** после 200+ сделок → переобучение confirmation ве…

**ML Outcome retrain weights:** после 200+ сделок → переобучение confirmation весов через RandomForest feature importance. Триггер: `signal_drops` стабилен 7 дней + 200+ trades с confirmations[]

---
## ID: [DEV-205](#dev-205) — Phase 0→2 расширение:** audit_mode shadow + audit_trades + alerts на коллапс д…

**Phase 0→2 расширение:** audit_mode shadow + audit_trades + alerts на коллапс данных + ML skipped-rows visibility (из исходного Stabilization Sprint Phase 1+2)

---
## ID: [TR-003](#tr-003) — TRADER валидация Confirmation Registry: ручной разбор ≥30 composite сделок с con…

TRADER валидация Confirmation Registry: ручной разбор ≥30 composite сделок с confirmations[] по v2 логике. Сейчас n=12 (13.05–14.05) — ждём накопления. Предварительно: signal_type=composite (не atr_change), sl_source=atr_trendline_buf (DEV нужен фикс SL-выбора)

---
## ID: [DEV-192](#dev-192) — entry_to_trigger_distance_pct в features_json:** для pivot_reversal…

**entry_to_trigger_distance_pct в features_json:** для pivot_reversal — расстояние от entry до триггерного пивота (не до TP). B6 фикс

---
## ID: [ARCH-95](#arch-95) — Расследование убытков (H1-H5 актуальны):** H6 MTF alignment + H7 адаптивные ве…

**Расследование убытков (H1-H5 актуальны):** H6 MTF alignment + H7 адаптивные веса покрыты ARCH-104. Открыты: H1 поздние входы scan-on-close, H2 тесный SL, H3 pivot direction, H4 cube snapshots, H5 slippage.

---
## ID: [TR-002](#tr-002) — Бэктест-валидация 10 гипотез прогнозирования H1–H10 на исторических данных Trigg…

Бэктест-валидация 10 гипотез прогнозирования H1–H10 на исторических данных TriggerBus (после ARCH-106 Фаза 1.5). Каждая гипотеза имеет acceptance criteria в vision-документе

---
## ID: ЭТАП 1 — ARCH-118 — единый features_json snapshot (ВАРИАНТ B: из combinator).** Решение…

**ARCH-118 — единый features_json snapshot (ВАРИАНТ B: из combinator).** Решение 30.05: снимок = `combinator.compute_flags(df)` для live И бэктеста = ОДИН код → parity live=backtest ПО ОПРЕДЕЛЕНИЮ. **НЕ зависит от ARCH-117** (combinator готов post DEV-233/234). Вариант A (снимок из Bus) НЕ решает parity — бэктест Bus не имеет → отвергнут. Параллельный трек: ARCH-117 (сферы→Bus = runtime-развязка), слияние позже когда сферы==combinator. До любого ML/re-mining.

---
## ID: ЭТАП 2 — ARCH-122 ч.1b — Exit Manager Сфера 10** поверх ARCH-118…

**ARCH-122 ч.1b — Exit Manager Сфера 10** поверх ARCH-118. TP/SL единообразно к финальной рекомендации. Чинит liquidity_sweep-обход (AVNT). tp1+tp2+SL из магнитов.

---
## ID: ЭТАП 3 (∥) — ARCH-117 ph2 — RSIService + миграция** (extended_indicators wt2 EWM→SMA фикс…

**ARCH-117 ph2 — RSIService + миграция** (extended_indicators wt2 EWM→SMA фикс, chart_builder, 4 скрипта). ПАРАЛЛЕЛЬНЫЙ трек (не блокирует ARCH-118). Runtime-развязка live-пайплайна.

---
## ID: ЭТАП 4 — Cube spheres:** ARCH-123 (PivotSphere) → ARCH-119 (Reversal Mode) → ARCH-121 (…

**Cube spheres:** ARCH-123 (PivotSphere) → ARCH-119 (Reversal Mode) → ARCH-121 (WaveService Elliott). Каждая prerequisite следующей.

---
## ID: ЭТАП 5 — ARCH-122 ч.3 (SLSelector OB edge+CHoCH/BOS) + ARCH-120 ph2 (ML SMC Specialist…

**ARCH-122 ч.3 (SLSelector OB edge+CHoCH/BOS) + ARCH-120 ph2 (ML SMC Specialist при 200+ smc_snap сделок) + ARCH-115 (Wave Phase Intelligence — фильтры n_down×htf, TP по фазе).**

---
## ID: [ARCH-121](#arch-121) — WaveService → Сфера 14: Elliott Wave прокси (переим…

**WaveService → Сфера 14: Elliott Wave прокси (переим. с ARCH-117, 29.05.2026):** Реализовать `core/intelligence/wave_service.py`. Гибридный подход: синхронный вычисление + SharedContextBus publish + опц. EventBus при `wave_phase_changed`. Интерфейс: `WaveService.compute_and_publish(sym, df_4h, df_1h, df_ltf, ctx_bus) → WavePhase`. Поля в Bus: `elliott_phase`, `elliott_conf`, `elliott_n_down`, `elliott_n_down_1h`. gap_guard при TSL off. Порядок: ARCH-123 (PivotSphere) → ARCH-119 (Reversal Mode) → ARCH-121.

---
## ID: [ARCH-119](#arch-119) — MarketRegime → Сфера 6 v2: Reversal Mode (29.05.2026):** Добавить `mode=REVERS…

**MarketRegime → Сфера 6 v2: Reversal Mode (29.05.2026):** Добавить `mode=REVERSAL/TREND` к MarketRegimeClassifier. Reversal Mode = три условия одновременно: WT 4h в OS/OB + ADX снижается 3 бара + CHoCH на 1h. Это эквивалент Волна 5 → ABC по Эллиотту. Данные: `n_down≥4 + BullishChoCH = avgR=-2.181, WR=0%` (n=154 W20). Влияние на pipeline: `mode=REVERSAL → ЗАПРЕТ SHORT` (идёт ABC коррекция вверх), `mode=REVERSAL из нисходящего → BOOST LONG`. Acceptance: бот распознаёт Reversal Mode ≥1 раза в 4h при реальном развороте рынка.

---
## ID: [DEV-225](#dev-225) — ATRChange SHORT: Daily Pivot PP + ChoCH/BOS shadow gate (28.05.2026):** Ретроб…

**ATRChange SHORT: Daily Pivot PP + ChoCH/BOS shadow gate (28.05.2026):** Ретробэктест n=367 сделок 14-24.05 выявил ключевые предикторы. **Главный: daily PP position.** above_pp: avgR=+0.342 WR=57.6%, W20=-0.010 (!!). below_pp: avgR=-0.934 WR=16.6%, W20=-1.049. **Покрытие:** 79% W20 блокируется, 82% W19 пропускает. **Вторичный: ближайший уровень S1/S2** → avgR=-1.344 WR=2.8% — block. **Бонус: YES ChoCH + above PP** = W20 avgR=+1.216 WR=83.3% (ChoCH — усилитель, НЕ блок). **WT1:** ATRChange SHORT не из OS зоны (медиана=-19), WT>-40 добавляет минимально. **Phase 1 (shadow, 3-5 дней):** (1) Загрузить df_1d в scan_loop (сейчас None). (2) Передать df_htf + df_1d в `_execute_atr_change_signal`. (3) Вычислить daily PP и ChoCH через `get_daily_pivot()` + `detect_structure()`. (4) Писать в features_json: `pvt_above_daily_pp` (bool), `pvt_nearest_level` (PP/R1/S1...), `pvt_would_block` (True если ниже PP или S1/S2), `smc_htf_last_break`, `smc_htf_bars_ago`. TF скоуп: 15m→1h PP (df_1h), 1h→4h PP (df_4h), 4h→1d PP (df_1d — требует загрузки). **Phase 2 (hard gate после 50+ shadow сделок):** если `pvt_would_block=True` показывает значимо хуже → hard block.

---
## ID: [ARCH-115](#arch-115) — Wave Phase Intelligence: Elliott × Signals Integration (28.05.2026)**…

**Wave Phase Intelligence: Elliott × Signals Integration (28.05.2026)** — Системное улучшение на основе глубокого исследования Elliott Wave + бэктеста n=3597. **Контекст:** бот торгует без учёта волновой фазы — одни и те же правила применяются к диаметрально разным ситуациям. **7 конкретных изменений:** **(1) n_down × htf_direction фильтр** — `n_down=0` сам по себе бесполезен; `n_down=0 + htf=down` = начало волны 3 (SHORT) vs `n_down=0 + htf=up` = начало роста (STOP SHORT). Внедрить в `_execute_atr_change_signal` и другие execute-функции. Данные: этот фильтр уберёт ловушку n_down=4 для atr_change (avgR=-0.904). **(2) TP режимы по волновой фазе** — три разных горизонта: Волна 3 mid (n_down=1-3, нет div) → широкий TP 161.8% волны 1 (цель wave3); Волна 5 финал (n_down=4+ + divergence) → консервативный TP ближайший FVG (0.3-0.5R, WR=79%); ABC Wave B (htf_dir=up, коррекция) → TP=50-61.8% от A. Текущий TPSelector считает gravity одинаково — добавить `wave_phase_modifier` к score. **(3) "Deep Trend Divergence SHORT" стратегия** — `divergence + n_down_4h=3-4 + htf=down` как самостоятельный паттерн с boost: avgR=+3.372 WR=79.4% n=34. Требует: выделить отдельный путь в `_execute_divergence_signal`, уменьшить TSL activation threshold (или выключить TSL), увеличить Kelly fraction (WR=79% → Kelly ≈ 0.35 vs текущий 0.10-0.15). **(4) `confluence` SHORT требует divergence** — signal_type=confluence убыточен при всех n_down (avgR=-0.714, n=765). Добавить в execute_confluence: если direction=SHORT и нет активной bull_divergence → block или reduce strength×0.3. **(5) SL = волновой invalidation level** — текущий swing_high+buffer бьёт по коррекционному swing внутри волны 2/4. Правильный SL: если вход в OTE волны 2 (61.8-78.6% от волны 1) → SL = начало волны 1 (100% откат = invalidation). Реализовать как дополнительный SL кандидат в `_compute_sl`. **(6) TSL off для divergence + liquidity_sweep** — data ARCH-104: no_trail + 24h time exit > TSL на быстрых разворотных сигналах. Добавить `tsl_activation_r_per_strategy: divergence: null, liquidity_sweep: null` + `time_exit_hours: 6` для этих типов. **(7) Fibonacci confluence score для TP** — где несколько Fib уровней совпадают = сильный TP. Добавить `fibonacci_confluence_score()` (реализован в `obsidian/Concepts/Elliott-Wave-Fibonacci-Tools.md`) в TPSelector как weight multiplier. **Документация:** `obsidian/Concepts/Elliott-Wave-Labeling.md`, `Elliott-Wave-Fibonacci-Tools.md`, `Elliott-Wave-Crypto-Practice.md`. **Acceptance:** запустить `scripts/elliott_n_down_backtest.py` после внедрения — ожидаем: atr_change SHORT n_down=4 исчезает из таблицы (заблокирован), divergence n_down=4 остаётся как GOLD паттерн.

---
## ID: [DEV-211](#dev-211) — MTFPivotAnalyzer deprecation + upgrade:** старый класс в mtf_pivot_integration…

**MTFPivotAnalyzer deprecation + upgrade:** старый класс в mtf_pivot_integration.py использует `45m` (нестандартный TF) + старые импорты. Пометить deprecated; pivot confluence работает через PivotCalculatorFixed.find_confluences()

---
## ID: [DEV-212](#dev-212) — pivot_confluence_2plus activation:** registry имеет вес=6 но никто не генериру…

**pivot_confluence_2plus activation:** registry имеет вес=6 но никто не генерирует. После 50+ fvg_pivot_zones записей — подключить как ConfirmationRegistry confirmation

---
## ID: [DEV-221](#dev-221) — SMC OB exit при де-эскалации:** если цена вернулась в Order Block при де-эскал…

**SMC OB exit при де-эскалации:** если цена вернулась в Order Block при де-эскалации → закрывать позицию. Уникальная идея Mistral из team-ask

---
## ID: D-074 — Soft D-051 — решение по данным D-073 (29.05.2026):** 1107 drops за 2 дня (1h=6…

**Soft D-051 — решение по данным D-073 (29.05.2026):** 1107 drops за 2 дня (1h=62%, 15m=29%, 5m=5%, 4h=4%). **Принятый вариант: TF-зависимый (B)** — 1h HARD оставить (62% drops = основной источник ложных сигналов), 15m penalty -15 strength (убирает слабые, не блокирует сильные). 5m/4h без изменений (HTF-gate DEV-232 уже справляется). D2_L_L3_15m_03 (186 drops, avgR=-0.41) = gate режет правильно → подтверждает D-075 disable. Реализация: `arch104_observer_loop.py` — при 15m паттерне без wt_cross добавить `strength -= 15` вместо `return`.

---
## ID: D-075 — Disable D2_L_L3_15m_03:** 17 сделок avgR=−0.41 WR_TP=0%…

**Disable D2_L_L3_15m_03:** 17 сделок avgR=−0.41 WR_TP=0% — самый частый шумовой паттерн arch104 (лидер по объёму, проигрывает). `config/arch104_patterns.yaml` → `enabled: false`. Подтвердить ещё раз перед disable что данных достаточно (n=17 на грани значимости)

---
## ID: D-076 — Single-position-per-symbol guard для arch104:** защита от SWARMS-style pyramid…

**Single-position-per-symbol guard для arch104:** защита от SWARMS-style pyramid (25.05 за 2.5ч 4 сделки на одной паре по +15R — иллюзия силы T5_L_02). Проверка `existing_open WHERE source_router='arch104' AND symbol=?` в `arch104_observer_loop._try_register_vst_trade` перед router.submit. Опционально — допустить пирамиду но cap=3 (D-026 multi-TF независимость не должна страдать)

---
## ID: [ARCH-85](#arch-85) — Формализация статусов стратегий (ACTIVE/SHADOW/DEPRECATED/REMOVED) + deprecated…

Формализация статусов стратегий (ACTIVE/SHADOW/DEPRECATED/REMOVED) + deprecated confluence/multi_signal (урок 2 AUDIT_LESSONS) — после спринта

---
## ID: D-046 — Separate Isolated Margin mode** на BingX (Hedge уже есть) для D-026 Multi-TF S…

**Separate Isolated Margin mode** на BingX (Hedge уже есть) для D-026 Multi-TF Scaling. Закрыть все позиции → переключить mode → убрать "позиция уже открыта" check в OrderManager + уникальный trade_mode per (det_tf, pattern_id). Даёт N независимых позиций per пара.

---
## ID: DOC-PAT-01 — Pattern Library Reference** (`show_pattern.py` готов 23.05): CLI lookup tool д…

**Pattern Library Reference** (`show_pattern.py` готов 23.05): CLI lookup tool для 175 patterns. **TODO расширить:** markdown docs в `obsidian/Architecture/ARCH-104-Pattern-Library/` со словесными описаниями каждого pattern ("Bull continuation through 4h trend + 1h FVG support") + readable таблицы по tier'ам

---
## ID: D-051.B — Walkforward per-TF triggers (combinator surgery):** `combinator_v3_nested` сей…

**Walkforward per-TF triggers (combinator surgery):** `combinator_v3_nested` сейчас работает только с 1h-data для HTF mask. Чтобы валидировать `wt_cross_*_5m/15m/4h` как trigger — нужно переписать на multi-TF HTF grids. 5-10ч код + 4-6ч walkforward. Запускать ТОЛЬКО если D-051 shadow покажет positive edge

---
## ID: D-048 — Re-entry from watchlist** после SL: pair → arch104_watchlist (TTL 4-8h) → ждат…

**Re-entry from watchlist** после SL: pair → arch104_watchlist (TTL 4-8h) → ждать divergence + cross_*_15m → re-entry на confirmation. Использует сохранённый HTF context

---
## ID: D-072 — data_service отдельный процесс + Redis** (следующая архитектурная фаза по team…

**data_service отдельный процесс + Redis** (следующая архитектурная фаза по team-ask 5/5 LLM, D-071 discussion). Цель: разгрузить main_bot event loop под scale 5-10× (533 BingX пар + multi-exchange ready). WS+REST → отдельный Python процесс → Redis Pub/Sub → main_bot subscribe. Schema: `stream:pair:{sym}:ohlcv`, `stream:pair:{sym}:ticks`, `pubsub:commands:order`, `pubsub:events:health`. Установка Redis через Docker (Windows). 1-2 дня работы. Полное обсуждение: [`obsidian/Team-Discussions/2026-05-25-d-071-стратегия-подготовка-к-5-10-нагрузке.md`](obsidian/Team-Discussions/).

---
