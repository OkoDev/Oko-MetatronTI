# 📋 TASKS — Координация агентов

> **Архив завершённых задач:** [TASKS-ARCHIVE.md](TASKS-ARCHIVE.md)
> **Живой диалог агентов:** [DISCUSSION.md](DISCUSSION.md)

## 👥 Роли

| Роль | Кто | Зона ответственности |
|---|---|---|
| **ARCH** | yogoru | Архитектура, постановка задач, review, приоритеты |
| **DEV** | oko.webdev | Разработка, интеграция, бэктест |
| **TRADER** | Claude (TRADER) | Торговая экспертиза, валидация стратегий, живой анализ |

**Workflow:** ARCH ставит → DEV берёт → ARCH review → TRADER валидирует
**Вопросы между ролями:** писать в DISCUSSION.md с тегом `→ ARCH:` / `→ DEV:` / `→ TRADER:`

---

## 🧊 Stabilization Sprint (04.05–25.05.2026) — заморозка vision

**План:** [`/root/.claude/plans/fluttering-snacking-whale.md`](/root/.claude/plans/fluttering-snacking-whale.md) — «Возврат управляемости».

**Корень:** в БД попадает ~4% детектируемых сигналов, остальные 96% теряются молча. ML обучается на 30-40% данных. `decision_trace.py` готов, но в `_broadcast_intelligence_alert` не вызывается. Сначала видимость, потом архитектура.

**Заморожено до Phase 4 (~25.05):** ARCH-74-EXT, ARCH-96..99, ARCH-101..104, ARCH-105..111. Не открываем, не удаляем — паузим. Активный спринт «Реальные убийцы» (DEV-184..193) **продолжается** как стабилизирующий.

**Фазы:**
- **Phase 0** (1-2д): DecisionTrace в 14 gates → таблица `signal_drops` → дашборд топ-10 reasons
- **Phase 1** (2-3д): `audit_mode` shadow + `audit_trades` → отчёт `audit_filter_efficacy.py`
- **Phase 2** (3-5д): coverage matrix + alerts на коллапс данных + ML skipped-rows visibility
- **Phase 3** (5-7д): `bot/loops/broadcast_pipeline.py` + 14 gate-файлов + тесты

**Критерий выхода:** monitoring.py < 800 строк, coverage critical полей ≥ 90%, 7 дней без регрессии avgR.

---

## 📊 Активные задачи

**Статусы:** 🔴 срочно | 🟡 важно | 🟢 в плане | 🔵 бэклог | 🔄 в работе | ⏸ отложено | 🧊 FROZEN до Phase 4

| ID | Ст | Описание | Роль |
|---|---|---|---|
| **🚀 СПРИНТ «CONFIRMATION-DRIVEN ARCHITECTURE» (09.05–23.05.2026)** — на основе R6/R7/R8: ATR Trend change cascade подтверждён, ЗАКОН confluence | | | |
| [DEV-199](#dev-199) | ✅ | **ATR Trend Change events:** `core/signals/atr_change_detector.py` + EventBus publish 15m/1h/4h. 1d не публикуется. Реализовано 09.05 | DEV |
| [DEV-200](#dev-200) | ✅ | **ConfirmationRegistry:** `core/confirmations/registry.py` — 25 типов (3 trigger + 22 confirmation), веса 1-18. 58/58 тестов PASSED. Реализовано 09.05 | DEV |
| [DEV-201](#dev-201) | ✅ | **SignalAggregator v2:** `ConfirmationAggregator` в `signal_aggregator.py`. `strength = Σ weight × confidence`, режимы cascade/reversal/momentum. Реализовано 09.05 | DEV |
| [DEV-202](#dev-202) | ✅ | **features_json: confirmations[]:** гранулярная запись подтверждений в monitoring.py + scan_loop.py. Реализовано 09.05 | DEV |
| [DEV-203](#dev-203) | ✅ | **DecisionTrace в gates:** `core/observability/decision_trace.py`, таблица `signal_drops`, 6 gates покрыты, `/api/dropped` дашборд. Реализовано 09.05 | DEV |
| [DEV-204](#dev-204) | 🟢 | **ML Outcome retrain weights:** после 200+ сделок → переобучение confirmation весов через RandomForest feature importance. Триггер: `signal_drops` стабилен 7 дней + 200+ trades с confirmations[] | DEV |
| [DEV-206](#dev-206) | ⏸ | **ML OutcomePredictor: re-enable после набора данных.** Отключён 09.05 (AUC=0.56 → blend 0.3 убивал все сигналы, conf падала с 0.65 → 0.50). Триггер: ≥200 новых закрытых сделок + AUC ≥ 0.62 при CV. Шаги: (1) `python -c "from core.ml.outcome_predictor import OutcomePredictor; op=OutcomePredictor(); op.fit('subscriptions.db'); print(op.info())"` — проверить AUC. (2) Если AUC ≥ 0.62 → `ml.use_outcome_predictor: true` + `ml.blend_weight: 0.1` (вынести 0.3 из кода). (3) Через неделю → 0.2 если WR не упал. Дата проверки: ~30.05.2026 | DEV |
| [DEV-205](#dev-205) | 🟢 | **Phase 0→2 расширение:** audit_mode shadow + audit_trades + alerts на коллапс данных + ML skipped-rows visibility (из исходного Stabilization Sprint Phase 1+2) | DEV |
| [DEV-208](docs/TASKS_DETAILS.md) | 🔴 | **Мониторинг Confirmation-Driven после рестарта (12.05).** Проверить 24-48ч после деплоя Этапов 1-4: (1) `_publish_conf` вызывается без exceptions для всех 13 типов; (2) `signal_drops` растёт (gate=strength_too_low, invalid_sl, register_returned_none); (3) atr_change сделки имеют `confirmations[]` ≥2 в features_json; (4) количество сделок atr_change_1h/4h выросло vs baseline (3/3 дня → ≥30/24ч ожидание); (5) avgR не упал ниже −0.437. SQL-проверки в [docs/TASKS_DETAILS.md → DEV-208](docs/TASKS_DETAILS.md) | DEV/TRADER |
| [TR-003](#tr-003) | 🟡 | TRADER валидация Confirmation Registry: ручной разбор 20 SHADOW-сделок по новой v2 логике. Подтвердить веса confirmations | TRADER |
| [TR-004](#tr-004) | 🟡 | **Наблюдение DEV-89ext: SHORT/LONG к Daily R/S уровням при counter-bias.** 09.05: расширили weekly_bias исключение с Weekly → Weekly+Daily (пример: VVV SHORT к 1D R1 при BTC BULLISH блокировался). Собрать ≥20 сделок где сработало исключение (`[DEV-58] ALLOWED — near tp_src:pivot_1D_R*`). Оценить: (1) RR реальный vs ожидаемый 1:3.4+ (2) WR при Daily vs Weekly уровнях (3) Логика: TP достигнут до возврата к weekly trend? Если WR < 30% или avgR < 0 → откатить (вернуть "1W" only), если OK → оставить. Триггер: 20+ сделок или 3 недели наблюдения (~30.05.2026) | TRADER |
| [ARCH-112](#arch-112) | ✅ | Аудит выполнен 12.05.2026 (DISCUSSION.md). 25 confirmation покрывают 6/13 сфер: S2/S3/S4/S7/S8/S11. 3 онтологических edge case (atr_change → S6 vs S7, ote_zone двойная, pivot_touch S7 vs S8). 3 GAP сфер (S5 Cross-Market, S6 MarketRegime, S9 Narrative) — кандидаты ARCH-112-EXT (бэклог после Phase 4) | ARCH |
| **🚀 СПРИНТ «РЕАЛЬНЫЕ УБИЙЦЫ» (25.04–02.05.2026)** — после D1+RE-AUDIT: фикс не D1-багов, а реальных источников −780R/10дн | | | |
| [DEV-191-TSL](#dev-191-tsl) | ✅ | **HOTFIX apply_floor:** SHORT floor = current_price*(1+0.3%) вместо entry*(1+0.3%). Корень TSL-заморозки: все SHORT в профите держали SL у entry±0.3%. 42/42 тестов ✅. Рестарт нужен | DEV |
| [DEV-184](#dev-184) | ✅ | **Отключить DUAL_TSL strategy_type:** `trend_strategy_type: DUAL_TP` в config.yaml (26.04.2026). DUAL_TSL avgR=-0.61 → DUAL_TP -0.23 | DEV |
| [DEV-185](#dev-185) | 🔄 | **Catastrophic slippage:** ✅ Расследовано (DISCUSSION.md). ✅ Шаг 1: `sl_limit_buffer_pct: 0.0→1.0` (−113R). ⏳ 48ч наблюдения → решение по 2.0 + watchdog | DEV/ARCH |
| DEV-185.2 | ✅ | **Emergency watchdog реализован** (27.04). [position_sync.py:_emergency_close_check](core/exchange/position_sync.py). Триггер: overshoot за SL >0.5% от entry, dwell 5 мин → market close. Подхватится при рестарте | DEV |
| DEV-185.3 | ✅ | **Volume whitelist** `signal_quality.min_volume_usd: 5000000` (04.05). 13 catast (DOLO/CLO/GIGGLE/VELODROME) — low liquidity. Применено | DEV |
| DEV-193 | ✅ | **sl_min в reversal_strategy.py** (04.05): SL зажат в [0.5%, 3.0%]. До: 116 сделок SL<0.5%, VELODROME R=-7.03→-0.49. Тесты 15/15 OK | DEV |
| [DEV-186](#dev-186) | 🟡 | **wt_signal regime gate:** SHORT block в TREND_UP/HIGH_VOL. 22 сделки avgR=−1.12 в TREND_UP. Эффект: −24R/10дн | DEV |
| [DEV-187](#dev-187) | 🟡 | **wt_b жёсткий floor для порогов:** wt1_1h<−30 (LONG) / >+30 (SHORT) поверх adaptive p10/p90. Сейчас 7 SHORT в N зоне avgR=−2.44. Эффект: −17R/10дн | DEV |
| [DEV-188](#dev-188) | 🟡 | **pivot_reversal SHORT TREND_DOWN:** проверка реального касания (wick через уровень) + объёма. 93 сделки avgR=−0.77. Эффект: −72R/10дн | DEV |
| [DEV-189](#dev-189) | 🟢 | **B3 фикс:** UPDATE stop_loss вынести из-под `_is_real_move` в trade_simulator.py:1980. Сейчас SIM сделки не апдейтят БД при TSL движении (80%) | DEV |
| [DEV-190](#dev-190) | ✅ | **effective_status helper готов** (27.04). Интегрирован в 8 модулей: performance_engine, circuit_breaker, outcome_predictor, mtf_wt/smc_specialist, auto_calibrator, confidence_calibrator, dashboard. Подхватится при рестарте | DEV |
| [DEV-191](#dev-191) | 🟢 | **wt1_at_trigger_tf поле в features_json:** для wt_b писать wt1 на 1h, не на 15m. B5 фикс | DEV |
| [DEV-192](#dev-192) | 🟢 | **entry_to_trigger_distance_pct в features_json:** для pivot_reversal — расстояние от entry до триггерного пивота (не до TP). B6 фикс | DEV |
| [ARCH-100](#arch-100) | ✅ | **Финальный re-audit** (04.05, data_era v4 post-26.04): pivot_reversal avgR=-0.449 (цель ≥-0.10 ❌), overall avgR=-0.437 (цель ≥+0.10 ❌). wt_b единственный прибыльный (+0.084). Два фикса применены (DEV-193 + DEV-185.3) | ARCH |
| **🚀 СПРИНТ «ЗАМЫКАНИЕ РАЗРЫВОВ» (19.04–26.04.2026)** — ✅ ARCH-88/89/90/91, DEV-172-FIX закрыты (→ TASKS-ARCHIVE) | | | |
| [ARCH-92](#arch-92) | 🟢 | Анализ WR/avgR по Entry Priority (P1/P2/P3) на 200+ закрытых сделках (~22.04). Решение: P3→WATCH или оставить shadow | ARCH |
| [ARCH-93](#arch-93) | 🟢 | Research: Future pivots touch→reaction на истории (20 пар, переходные часы day/week). Решение: добавлять feature или нет | ARCH/DEV |
| [ARCH-94](#arch-94) | 🔴 | Полный аудит TP-lifecycle: биржа vs БД рассинхрон, exchange_tp_order_id, TSL-отмена TP, position_sync верификация | ARCH/DEV |
| [ARCH-95](#arch-95) | 🔴 | Глобальное расследование: почему торгуем в минус. 6 read-only аудит-скриптов (H1 entry timing/SL близко, H2 SL distance vs исход, H3 pivot S/R×direction, H4 куб snapshots, H5 detector→entry slippage, H6 MTF alignment, H7 EMA per-strategy) | ARCH/DEV |
| **🆕 СИСТЕМНЫЕ СФЕРЫ КУБА (Claude consult 25.04 — параллельно с фиксами Слоя D ARCH-95)** | | | |
| [ARCH-96](#arch-96) | 🧊 | Execution Sphere (Сфера 14): IdempotencyGuard + SlippagePredictor + OrderTypeSelector + ExecutionTracker. Закрывает SL-дубликаты архитектурно, режет slippage. КРИТИЧНО перед LIVE — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-97](#arch-97) | 🧊 | Anomaly Detection Sphere (Сфера 15): self-observability на execution/trading/ML drift. Поймала бы DEV-174/175/SL-dup за 1-72ч до человека — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-98](#arch-98) | 🧊 | Portfolio Manager Sphere (Сфера 16): β-exposure к BTC/ETH, sector concentration, rolling DD. После Risk Sphere shadow — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-99](#arch-99) | 🧊 | Meta-Learning Sphere (Сфера 17): XGBoost f(context, signal_type)→E[R] контекстуальный фильтр — **FROZEN до Phase 4** | ARCH/DEV |
| **🆕 ДОЛГ ПО КАРТЕ ШИНЫ И КУБА (`docs/SIGNAL_BUS_CUBE_MAP.md`, 27.04 TRADER)** — Фаза 1 roadmap | | | |
| [ARCH-101](#arch-101) | 🧊 | Mesh шины: 11/16 детекторов → `event_bus.publish("signal_detected", ...)` в monitoring.py. Без этого Narrative/Anomaly/Exit слепы — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-102](#arch-102) | 🧊 | BTCRegimeProvider → `cross_market` publish при смене BULL↔BEAR. Расширение ARCH-78 — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-103](#arch-103) | 🧊 | `classify_mode` (reversal_mode) из shadow в production — **FROZEN до Phase 4** | ARCH |
| [ARCH-104](#arch-104) | 🧊 | Унификация двух нумераций сфер: `sphere_registry.SPHERE_NAMES` vs `selftest_cube`. Выбрать одну, выровнять — **FROZEN до Phase 4** | ARCH |
| **🆕 ВИДЕНИЕ: PREDICTIVE SETUP ENGINE (`docs/TRADER_VISION_PREDICTIVE_SETUPS.md`, 28.04 TRADER)** — переход от reactive market к predictive limit | | | |
| [ARCH-105](#arch-105) | 🧊 | Order Flow & Macro data sources: funding history + OI + liquidations. Базис для гипотез H5/H6 — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-106](#arch-106) | 🧊 | TriggerBus + persistence: новая шина атомарных триггеров + таблица `trigger_events`. Фундамент для ML на 100k+ событий — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-107](#arch-107) | 🧊 | Setup Engine v1 (Сфера 18): `TradingSetup` dataclass + state machine + таблица `trading_setups` — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-108](#arch-108) | 🧊 | Predictive entries: ladder limit orders + bracket-link. Зависит от ARCH-96 — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-109](#arch-109) | 🧊 | Strategy DSL: yaml-описания стратегий. После Setup Engine v2 — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-110](#arch-110) | 🧊 | Volume Profile + CVD: VPVR / POC / VAH / VAL + WS trade stream. Гипотеза H9 — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-111](#arch-111) | 🧊 | Setup-aware Meta-Learning: расширение ARCH-99 на `f(context, setup_type, trigger_chain) → E[R]` — **FROZEN до Phase 4** | ARCH/DEV |
| [TR-002](#tr-002) | 🟢 | Бэктест-валидация 10 гипотез прогнозирования H1–H10 на исторических данных TriggerBus (после ARCH-106 Фаза 1.5). Каждая гипотеза имеет acceptance criteria в vision-документе | TRADER |
| **DASHBOARD** | | | |
| [DEV-144](#dev-144) | 🟡 | Полный редизайн дашборда: Live Control + Analytics + Settings | DEV |
| [DEV-144f](#dev-144f) | 🟢 | P6: Единый CSS — тёмная тема, виджет-карточки, responsive grid | DEV |
| [DEV-207](docs/TASKS_DETAILS.md) | ✅ | **Dropped Signals UI + ATR Change visualization** реализовано 11.05. Backend: `/api/atr_stats` + `recent_closed` теперь возвращает `features_json`. Frontend: nav Drops (топ-10 gates карточки + recent таблица с фильтрами + sparkline + переключатель 1h/6h/24h/7d), ATR Change секция на summary (3 карточки 1h/4h/15m), фильтр Trigger + колонки Trig/Zone/Str в истории, stack-bar `strength_breakdown`. Smoke: 15m WR=44.2% n=172, 4h WR=41.7% n=12. Заработает после рестарта | DEV |
| **СТРАТЕГИЯ / СИГНАЛЫ** | | | |
| [ARCH-84](#arch-84) | ✅ | MTF gate ЗАКРЫТ (09.05): 0 срабатываний за 3 недели shadow. Данные опровергли гипотезу (SHORT в LONG-рынке avgR=−0.141 vs SHORT в BEAR avgR=−0.487). Код удалён из monitoring.py, параметры из config.yaml | ARCH/DEV |
| [DEV-172](#dev-172) | 🟢 | Entry Priority Matrix shadow: P1/P2/P3 пишется в features_json (200+ сделок → анализ) | DEV |
| [DEV-111act](#dev-111act) | ⏸ | BTC 4h gate production: отложен — риск блокировки alt-pumps при BTC боковике | DEV |
| [DEV-88](#dev-88) | 🟡 | OTE Step2: C1 (4h+CHoCH) Sharpe=2.68 ✅, WR=41.7%. Нужна расширенная выборка | DEV |
| [DEV-89](#dev-89) | 🟢 | OTE C1 shadow: 20 пар / 90 дней. Критерий: WR≥40% ∧ Sharpe≥1.5 ∧ n≥150 | DEV |
| [DEV-104](#dev-104) | 🔵 | Dead-Man Timer: emergency close all (Слой 3 ARCH-65) — только перед LIVE | DEV |
| **ML / АНАЛИТИКА** | | | |
| [DEV-162](#dev-162) | 🔵 | derive_wt_verdict: динамический confidence вместо статического (триггер: 200+ BLOCK) | DEV |
| **RISK INTELLIGENCE (Сфера 3 Куба) — обсуждение 19.04** | | | |
| DEV-180 | 🟢 | Risk Intelligence v1 формульный: risk_pct multiplier от EMA avg_R + Sharpe + warnings (shadow) | DEV |
| DEV-181 | 🟢 | Leverage selection: формула от SL distance + funding-awareness (треб. поле funding_paid) | DEV |
| DEV-182 | 🔵 | Risk Intelligence ML-слой: RandomForest на фичах контекста (ждёт 3–4 недели post_fix) | DEV |
| DEV-183 | 🔵 | Position count cap + correlation cap по BTC | ARCH/DEV |
| **КУБ МЕТАТРОНА** | | | |
| [ARCH-77](#arch-77) | ⏸ | Миникуб WTMTF: ЗАМОРОЖЕН до Sharpe>1 в проде (множитель к убытку бесполезен) | ARCH/DEV |
| [ARCH-79](#arch-79) | 🔵 | S10→S11: PostTradeAnalyser → NarrativeBuilder feedback (narrative_outcome в PairCtx) | DEV |
| [ARCH-55-VAL](#arch-55-val) | 🔄 | RANGE BOUNCE валидация: TRADER 27.04 — range_bounce WR+7.6pp, не вреден. Наблюдение 2 недели на чистой выборке (до ~11.05). ⚠️ Срок истекает — нужно финальное решение ARCH | ARCH/DEV |
| **АРХИТЕКТУРА** | | | |
| [ARCH-87](#arch-87) | 🔵 | Fibonacci контекст в PairState: swing H/L + 0.618/0.705/0.79 в features_json для ML. Триггер: 50+ OTE сделок | ARCH/DEV |
| [ARCH-85](#arch-85) | 🟡 | Формализация статусов стратегий (ACTIVE/SHADOW/DEPRECATED/REMOVED) + deprecated confluence/multi_signal (урок 2 AUDIT_LESSONS) — после спринта | ARCH |
| [ARCH-86](#arch-86) | 🟢 | ROADMAP: строки «invalidates data pre-YYYY-MM-DD» для DEV-157/171/174/175 (урок 3 AUDIT_LESSONS) | ARCH |
| [ARCH-80](#arch-80) | 🔵 | MarketRegime hysteresis + метрика regime_changes_per_day | ARCH |
| [ARCH-81](#arch-81) | 🔵 | Rolling Correlation Guard + portfolio_beta_to_btc (замена hardcoded) | ARCH/DEV |
| [ARCH-82](#arch-82) | 🔵 | L3 checker v2: regime-aware portfolio limits (TREND_UP: 3L+1S) | ARCH/DEV |
| [DEV-176](#dev-176) | 🔵 | SL cooldown per-TF калибровка (15m→2ч, 1h→4ч, 4h→12ч) | DEV |
| [ARCH-73](#arch-73) | 🔵 | Разбивка trading_intelligence.py (2578 строк): MLSpecialist + StrengthAggregator | ARCH/DEV |
| [ARCH-74](#arch-74) | 🧊 | Разбивка trade_simulator.py: TSLManager + MFETracker + ExchangeSyncGuard — **FROZEN до Phase 4** (Phase 3 даёт частичный split monitoring.py) | ARCH/DEV |
| [ARCH-74-EXT](#arch-74-ext) | 🧊 | **Smart TSL** (расширение ARCH-74): adaptive params per-pair/regime + Sphere 10 как brain + RL slot — **FROZEN до Phase 4** | ARCH/DEV |
| [ARCH-75](#arch-75) | 🔵 | Разбивка monitoring.py (1436 строк): SignalFilter + MessageDispatcher | ARCH/DEV |
| [ARCH-76](#arch-76) | 🔵 | CubeNode интерфейс: Фрактальный Куб (триггер: LIVE + прибыль 30+ дней) | ARCH |
| [ARCH-57](#arch-57) | 🔵 | Confluence TRADER/RANGE tier parameter | ARCH |
| [ARCH-67](#arch-67) | 🔵 | USDT.D macro gate: CoinGecko API + shadow (бэклог май) | ARCH |
| [ARCH-69](#arch-69) | 🔵 | Перенести verbose-секции CLAUDE.md → ENCYCLOPEDIA.md | ARCH |
| [ARCH-44](#arch-44) | 🔵 | Добавить роль DATA (триггер: AUC > 0.55) | ARCH |
| [ARCH-47](#arch-47) | 🔵 | SMC contradiction filter: SHORT при нулевых медвежьих сигналах | ARCH |
| **TRADER** | | | |
| [TR-001](#tr-001) | 🔄 | Ежедневный разбор Watch List с живыми свечами | TRADER |
| [TRADER-AUDIT-002](#trader-audit-002) | 🟢 | Аудит DUAL_TSL split 10%/90%: grid search после 500+ новых DUAL_TSL сделок (~30.04) | TRADER |

---

## 📖 Детальные описания задач → [docs/TASKS_DETAILS.md](docs/TASKS_DETAILS.md)

> Полные спецификации, acceptance criteria, SQL-примеры, код — в TASKS_DETAILS.md.
> В таблице выше — только статус + краткое описание + `→ opens:`.

---

## 🗺️ Зависимости (`→ opens:`)

| Задача | Открывает |
|---|---|
| DEV-185.2 ✅ | DEV-185.3 (volume whitelist после watchdog) |
| DEV-190 ✅ | ARCH-100 (re-audit на effective_status) |
| DEV-186 + DEV-187 | ARCH-103 (reversal_mode production после стабилизации gate) |
| ARCH-95 (аудит) | ARCH-96 (Execution Sphere) |
| ARCH-96 | ARCH-97, ARCH-108 (predictive entries требуют OCO) |
| ARCH-101 (Mesh шины) | ARCH-106 (TriggerBus — расширение EventBus) |
| ARCH-106 (TriggerBus) | ARCH-107 (Setup Engine v1), TR-002 (бэктест H1-H10) |
| ARCH-107 (Setup Engine v1) | ARCH-108 (predictive entries), ARCH-111 (Meta-Learning v2) |
| ARCH-104 (унификация сфер) | ARCH-96..99 (регистрация новых сфер без хаоса) |
| DEV-180 (Risk v1 shadow) | DEV-181 (leverage), ARCH-98 (Portfolio Manager) |
| Фаза 0 спринта (+avgR) | ARCH-103 (reversal_mode production) |
| **DEV-199 (atr_change events)** | **DEV-200 (registry), DEV-201 (aggregator)** |
| **DEV-200 (registry)** | **DEV-202 (features_json), DEV-204 (ML retrain), TR-003 (валидация)** |
| **DEV-201 (aggregator v2)** | **ARCH-112 (audit), DEV-204 (ML retrain)** |
| **DEV-203 (DecisionTrace)** | **DEV-205 (audit_mode shadow)** |
| **DEV-204 (ML retrain)** | ARCH-103 reversal_mode production, ARCH-99 Meta-Learning |

