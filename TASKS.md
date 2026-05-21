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

## 🗺️ Архитектура

> **Два потока, Куб, статусы сфер:** [`docs/CURRENT_ARCHITECTURE.md`](docs/CURRENT_ARCHITECTURE.md) ← читать при потере ориентации
> **Куб Метатрона (концепция):** [`docs/ENCYCLOPEDIA.md`](docs/ENCYCLOPEDIA.md) → раздел "Куб Метатрона"
> **ARCH-104 migration plan:** [`docs/MIGRATION_ARCH104.md`](docs/MIGRATION_ARCH104.md)

---

## 📊 Активные задачи

**Статусы:** 🔴 срочно | 🟡 важно | 🟢 в плане | 🔵 бэклог | 🔄 в работе | ⏸ отложено | 🧊 FROZEN до Phase 4

| ID | Ст | Описание | Роль |
|---|---|---|---|
| **🚀 СПРИНТ «CONFIRMATION-DRIVEN ARCHITECTURE» (09.05–23.05.2026)** — на основе R6/R7/R8: ATR Trend change cascade подтверждён, ЗАКОН confluence | | | |
| [DEV-199](#dev-199) | ✅ | **ATR Trend Change events (17.05 закрыт):** `core/signals/atr_change_detector.py` + EventBus publisher `atr_change_15m/1h/4h` в `scan_loop.py`. Подключён в bot.py. НЕ публикует `atr_change_1d` | DEV |
| [DEV-200](#dev-200) | 🔴 | **ConfirmationRegistry:** `core/confirmations/registry.py` — каталог 12 базовых confirmation типов с весами. Datadclass `Confirmation(source, weight, confidence, evidence, ts)`. Acceptance: каждый детектор публикует Confirmation events | DEV |
| [DEV-201](#dev-201) | 🔴 | **SignalAggregator v2 (fallback path):** `strength = Σ weight × confidence` для НЕ-ARCH-104 сделок (wt_b, pivot_reversal, divergence). ARCH-104 flow идёт через decision_fusion.py. Scope сужен. | DEV |
| [DEV-202](#dev-202) | 🟡 | **features_json: confirmations[]:** гранулярная запись всех подтверждений (не плоские поля). Для будущего ML обучения весов. Acceptance: 100% новых сделок имеют поле `confirmations` (list[dict]) | DEV |
| [DEV-203](#dev-203) | ✅ | **DecisionTrace в gates (17.05 закрыт):** `core/observability/decision_trace.py` + таблица `signal_drops` (23515 записей) + `/api/dropped` дашборд. Top drop: dedup 64%, below_min_strength 17%, validate_inputs 1%. Работает. | DEV |
| [DEV-204](#dev-204) | 🟢 | **ML Outcome retrain weights:** после 200+ сделок → переобучение confirmation весов через RandomForest feature importance. Триггер: `signal_drops` стабилен 7 дней + 200+ trades с confirmations[] | DEV |
| [DEV-205](#dev-205) | 🟢 | **Phase 0→2 расширение:** audit_mode shadow + audit_trades + alerts на коллапс данных + ML skipped-rows visibility (из исходного Stabilization Sprint Phase 1+2) | DEV |
| [DEV-209](#dev-209) | ✅ | **ATR 15m + OTE zone trigger (17.05 закрыт):** `scan_loop.py:1370-1446` OTE zone trigger с `price_in_ote` + auto confirmation `ote_zone` (w=7) + per-source window 1800с для 15m. Acceptance: ≥20 сделок за 7 дней | DEV |
| [TR-003](#tr-003) | 🟡 | TRADER валидация Confirmation Registry: ручной разбор ≥30 composite сделок с confirmations[] по v2 логике. Сейчас n=12 (13.05–14.05) — ждём накопления. Предварительно: signal_type=composite (не atr_change), sl_source=atr_trendline_buf (DEV нужен фикс SL-выбора) | TRADER |
| [ARCH-112](#arch-112) | ✅ | Архитектурный аудит 11.05: 25 confirmations соответствуют Кубу, 6/13 сфер активны, 3 edge cases задокументированы, 3 GAP (S5/S6/S9) → бэклог ARCH-112-EXT | ARCH |
| **🚀 СПРИНТ «РЕАЛЬНЫЕ УБИЙЦЫ» (25.04–02.05.2026)** — после D1+RE-AUDIT: фикс не D1-багов, а реальных источников −780R/10дн | | | |
| [DEV-191-TSL](#dev-191-tsl) | ✅ | **HOTFIX apply_floor:** SHORT floor = current_price*(1+0.3%) вместо entry*(1+0.3%). Корень TSL-заморозки: все SHORT в профите держали SL у entry±0.3%. 42/42 тестов ✅. Рестарт нужен | DEV |
| [DEV-184](#dev-184) | ✅ | **DUAL_TSL отключён (17.05):** `config.yaml` `trend_strategy_type: DUAL_TP` (было DUAL_TSL). Эффект: −290R/10дн устранён | DEV |
| [DEV-185](#dev-185) | ✅ | **Catastrophic slippage (17.05 закрыт):** ✅ `sl_limit_buffer_pct: 1.0` (−113R) ✅ watchdog `position_sync.py:_emergency_close_check` ✅ volume whitelist `min_volume_usd: 5M`. Все 3 шага выполнены | DEV/ARCH |
| DEV-185.2 | ✅ | **Emergency watchdog реализован** (27.04). [position_sync.py:_emergency_close_check](core/exchange/position_sync.py). Триггер: overshoot за SL >0.5% от entry, dwell 5 мин → market close. Подхватится при рестарте | DEV |
| DEV-185.3 | ✅ | **Volume whitelist** `signal_quality.min_volume_usd: 5000000` (04.05). 13 catast (DOLO/CLO/GIGGLE/VELODROME) — low liquidity. Применено | DEV |
| DEV-193 | ✅ | **sl_min в reversal_strategy.py** (04.05): SL зажат в [0.5%, 3.0%]. До: 116 сделок SL<0.5%, VELODROME R=-7.03→-0.49. Тесты 15/15 OK | DEV |
| [DEV-186](#dev-186) | ✅ | **wt_signal regime gate (17.05 закрыт):** `monitoring.py:951` `dev186_wt_signal_regime_gate: True`, SHORT блокируется в TREND_UP/HIGH_VOL. Эффект: −24R/10дн устранён | DEV |
| [DEV-187](#dev-187) | ✅ | **wt_b жёсткий floor (17.05 закрыт):** `config.yaml` `os_floor: -30.0`, `ob_floor: 30.0` применены. Эффект: −17R/10дн устранён | DEV |
| [DEV-188](#dev-188) | 🟡 | **pivot_reversal SHORT TREND_DOWN:** проверка реального касания (wick через уровень) + объёма. 93 сделки avgR=−0.77. Эффект: −72R/10дн | DEV |
| [DEV-189](#dev-189) | ✅ | **B3 фикс (12.05):** `_sl_changed` отделён от `_needs_exchange_update`. UPDATE stop_loss теперь ВСЕГДА при движении ≥0.15%, биржевой cancel+replace — только при exchange_order_id. До фикса SIM avgR=-0.63 vs exchange +0.67 (Δ240R за сутки) | DEV |
| [DEV-190](#dev-190) | ✅ | **effective_status helper готов** (27.04). Интегрирован в 8 модулей: performance_engine, circuit_breaker, outcome_predictor, mtf_wt/smc_specialist, auto_calibrator, confidence_calibrator, dashboard. Подхватится при рестарте | DEV |
| [DEV-191](#dev-191) | 🟢 | **wt1_at_trigger_tf поле в features_json:** для wt_b писать wt1 на 1h, не на 15m. B5 фикс | DEV |
| [DEV-192](#dev-192) | 🟢 | **entry_to_trigger_distance_pct в features_json:** для pivot_reversal — расстояние от entry до триггерного пивота (не до TP). B6 фикс | DEV |
| [ARCH-100](#arch-100) | ✅ | **Финальный re-audit** (04.05, data_era v4 post-26.04): pivot_reversal avgR=-0.449 (цель ≥-0.10 ❌), overall avgR=-0.437 (цель ≥+0.10 ❌). wt_b единственный прибыльный (+0.084). Два фикса применены (DEV-193 + DEV-185.3) | ARCH |
| **🚀 СПРИНТ «ЗАМЫКАНИЕ РАЗРЫВОВ» (19.04–26.04.2026)** — ✅ ARCH-88/89/90/91, DEV-172-FIX закрыты (→ TASKS-ARCHIVE) | | | |
| [ARCH-92](#arch-92) | 🟢 | Анализ WR/avgR по Entry Priority (P1/P2/P3) на 200+ закрытых сделках (~22.04). Решение: P3→WATCH или оставить shadow | ARCH |
| [ARCH-93](#arch-93) | 🟢 | Research: Future pivots touch→reaction на истории (20 пар, переходные часы day/week). Решение: добавлять feature или нет | ARCH/DEV |
| [ARCH-94](#arch-94) | ✅ | **Аудит lifecycle ордеров (17.05 закрыт):** Root cause exchange_order_id=NULL — TradeRouter не делал UPDATE в БД после открытия ордера. Фикс: UPDATE SET exchange_order_id=? в _place_exchange_order() (ARCH-94). atr_change исправлен DEV-215. Orphan=0 подтверждён | ARCH/DEV |
| [ARCH-95](#arch-95) | 🔴 | **Расследование убытков (H1-H5 актуальны):** H6 MTF alignment + H7 адаптивные веса покрыты ARCH-104. Открыты: H1 поздние входы scan-on-close, H2 тесный SL, H3 pivot direction, H4 cube snapshots, H5 slippage. Переименовано: ARCH-95-EXEC. | ARCH/DEV |
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
| **СТРАТЕГИЯ / СИГНАЛЫ** | | | |
| [ARCH-84](#arch-84) | ✅ | MTF gate shadow → production (16.05): `verdict_gate.enabled: true` в config.yaml. EXHAUSTION gate блокирует OB_bias+LONG (WR=6.2%). Данные WOULD_BLOCK собраны | ARCH/DEV |
| [DEV-172](#dev-172) | ✅ | **Entry Priority Matrix (17.05 закрыт):** `core/intelligence/entry_matrix.py` + `evaluate_entry_priority()` в `trade_simulator.py:870-881`, пишет `entry_priority` P1/P2/P3 в features_json | DEV |
| [DEV-111act](#dev-111act) | ⏸ | BTC 4h gate production: отложен — риск блокировки alt-pumps при BTC боковике | DEV |
| [DEV-88](#dev-88) | ✅ | **OTE C1 покрыт ARCH-104 (21.05):** `S8_ote_strong` в arch104_patterns.yaml (n=164, avgR=+1.339, WR=90.2%) — superset C1. Данные собраны VST observer. | DEV |
| [DEV-89](#dev-89) | ✅ | **OTE shadow покрыт ARCH-104 (21.05):** Stage 1 VST observer на 241 паре (вкл. S8_ote) = superset 20-пар shadow. | DEV |
| [DEV-104](#dev-104) | 🔵 | Dead-Man Timer: emergency close all (Слой 3 ARCH-65) — только перед LIVE | DEV |
| **ML / АНАЛИТИКА** | | | |
| [DEV-162](#dev-162) | 🔵 | derive_wt_verdict: динамический confidence вместо статического (триггер: 200+ BLOCK) | DEV |
| **RISK INTELLIGENCE (Сфера 3 Куба) — обсуждение 19.04** | | | |
| DEV-180 | ✅ | **Risk Intelligence v1 shadow (17.05 закрыт):** `core/intelligence/risk_intelligence.py` — RiskIntelligenceV1, shadow mode, логирует решения без применения | DEV |
| DEV-181 | ✅ | **Leverage formula реализована в ARCH-104 (21.05):** `risk_intelligence.py:171-174` — `leverage = ceil(risk_pct / sl_distance_pct × safety_buffer)`. Shadow only → активация в Stage 3 ARCH-104. | DEV |
| DEV-182 | ✅ | **Risk ML покрыт ARCH-104 Stage 3 (21.05):** `decision_fusion.py` принимает `V2MLPrediction` (p_win, predicted_mfe_r). LightGBM Phase 1.5 задокументирован. Реализуется в рамках Stage 3 ARCH-104. | DEV |
| DEV-183 | 🔵 | Position count cap + correlation cap по BTC | ARCH/DEV |
| **КУБ МЕТАТРОНА** | | | |
| [ARCH-77](#arch-77) | ⏸ | Миникуб WTMTF: ЗАМОРОЖЕН до Sharpe>1 в проде (множитель к убытку бесполезен) | ARCH/DEV |
| [ARCH-79](#arch-79) | 🔵 | S10→S11: PostTradeAnalyser → NarrativeBuilder feedback (narrative_outcome в PairCtx) | DEV |
| [ARCH-55-VAL](#arch-55-val) | ✅ | RANGE BOUNCE валидация завершена (16.05): `range_bounce: enabled: true` в config.yaml, sl_source=range_bounce активен. Закрыто в DISCUSSION.md 27.04 | ARCH/DEV |
| **🆕 PIVOT RESEARCH ACTIONS (17.05.2026)** — на основе командного исследования 650 сделок post-v4 | | | |
| [DEV-210](#dev-210) | ✅ | **Pivot regime gates + FVG+pivot confluence (17.05):** TREND_UP LONG soft_penalty=-25 ✅, RANGE+no_rejection soft_penalty=-15 ✅, FVG+pivot confluence shadow в features_json ✅. Acceptance: через 7 дней avgR pivot_reversal улучшается | DEV |
| [DEV-213](#dev-213) | ✅ | **wt_sideways отключён (17.05):** `sideways_mode.enabled: false` в config.yaml. Причина: -131R/24ч, 50% убыточного флоу. Возврат при изменении данных | DEV |
| [DEV-214](#dev-214) | ✅ | **Swing SL для pivot_reversal (17.05):** swing_low/high primary SL (avgR=+0.846 n=41), fallback на pivot±0.3% если swing >5% от уровня или не найден | DEV |
| [DEV-215](#dev-215) | ✅ | **datetime timezone bug (17.05):** `closed_at` в БД хранится как ISO `T`-format, cutoff как `%Y-%m-%d %H:%M:%S` (пробел). SQLite string compare: `T`(84) > `' '`(32) → все ISO timestamps всегда >= cutoff → market_stress/sl_cooldown всегда срабатывали. Фикс: `datetime(closed_at)>=datetime(?)` + `'%Y-%m-%dT%H:%M:%S'`. 3 файла: `gates/market_stress.py`, `gates/sl_cooldown.py`, `bot/monitoring.py` | DEV |
| [DEV-211](#dev-211) | 🟡 | **MTFPivotAnalyzer deprecation + upgrade:** старый класс в mtf_pivot_integration.py использует `45m` (нестандартный TF) + старые импорты. Пометить deprecated; pivot confluence работает через PivotCalculatorFixed.find_confluences() | ARCH/DEV |
| [DEV-212](#dev-212) | 🟢 | **pivot_confluence_2plus activation:** registry имеет вес=6 но никто не генерирует. После 50+ fvg_pivot_zones записей — подключить как ConfirmationRegistry confirmation | DEV |
| **🆕 TSL/SL ROЙ-КОНСЕНСУС (18.05.2026)** — результаты team-ask 4/6 моделей, консенсус 5/5 | | | |
| [DEV-216](#dev-216) | ✅ | **De-escalation fix (18.05):** `r_gradient_rollback_pct: 0.75→0.25` + `r_gradient_peak_min_r: 2.0→2.5`. TSL де-эскалирует при 75% откате от пика (было: 25%). TSL живёт дольше на старшем ТФ | DEV |
| [DEV-217](#dev-217) | ✅ | **Per-strategy TSL activation (18.05):** `tsl_activation_r_per_strategy` в config.yaml + чтение в trade_simulator.py:1703. pivot=0.5R, wt_b=0.8R, wt_signal=1.0R, atr_change=1.5R | DEV |
| [DEV-218](#dev-218) | ✅ | **Swing SL fix (18.05):** `_compute_swing_levels` в trading_intelligence.py:2530 — `min→max` для LONG (ближайший swing low), `max→min` для SHORT. Причина: раньше брался самый дальний → всегда >3% → fallback ATR | DEV |
| [DEV-219](#dev-219) | ✅ | **SL кап 2% (18.05):** `sl_max_pct: 3.0→2.0` в двух местах config.yaml. Данные: SL 2-3% avgR=-0.206 (убыточен) | DEV |
| [DEV-220](#dev-220) | 🟢 | **MTF событийная TSL активация:** активация по 1h ATR-trend flip (не по +R порогу). Триггер: DEV-199 EventBus уже публикует ATR trend events. Требует интеграции в check_open_trades_with_tsl | DEV |
| [DEV-221](#dev-221) | 🔵 | **SMC OB exit при де-эскалации:** если цена вернулась в Order Block при де-эскалации → закрывать позицию. Уникальная идея Mistral из team-ask | DEV |
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

