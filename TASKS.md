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
| [DEV-188](#dev-188) | ✅ | **pivot_reversal SHORT real_touch gate (27.05 коммит 2e7abc8):** wick >= level*0.999 — жёсткий блок при отсутствии. volume_z < 0.8 → +10 penalty. 93 сделки avgR=-0.77 (-72R/10дн) — shadow данные подтверждали гипотезу. | DEV |
| [DEV-189](#dev-189) | ✅ | **B3 фикс (12.05):** `_sl_changed` отделён от `_needs_exchange_update`. UPDATE stop_loss теперь ВСЕГДА при движении ≥0.15%, биржевой cancel+replace — только при exchange_order_id. До фикса SIM avgR=-0.63 vs exchange +0.67 (Δ240R за сутки) | DEV |
| [DEV-190](#dev-190) | ✅ | **effective_status helper готов** (27.04). Интегрирован в 8 модулей: performance_engine, circuit_breaker, outcome_predictor, mtf_wt/smc_specialist, auto_calibrator, confidence_calibrator, dashboard. Подхватится при рестарте | DEV |
| [DEV-191](#dev-191) | 🟢 | **wt1_at_trigger_tf поле в features_json:** для wt_b писать wt1 на 1h, не на 15m. B5 фикс | DEV |
| [DEV-192](#dev-192) | 🟢 | **entry_to_trigger_distance_pct в features_json:** для pivot_reversal — расстояние от entry до триггерного пивота (не до TP). B6 фикс | DEV |
| [ARCH-100](#arch-100) | ✅ | **Финальный re-audit** (04.05, data_era v4 post-26.04): pivot_reversal avgR=-0.449 (цель ≥-0.10 ❌), overall avgR=-0.437 (цель ≥+0.10 ❌). wt_b единственный прибыльный (+0.084). Два фикса применены (DEV-193 + DEV-185.3) | ARCH |
| **🚀 СПРИНТ «ЗАМЫКАНИЕ РАЗРЫВОВ» (19.04–26.04.2026)** — ✅ ARCH-88/89/90/91, DEV-172-FIX закрыты (→ TASKS-ARCHIVE) | | | |
| [ARCH-92](#arch-92) | 🟢 | Анализ WR/avgR по Entry Priority (P1/P2/P3) на 200+ закрытых сделках (~22.04). Решение: P3→WATCH или оставить shadow | ARCH |
| [ARCH-93](#arch-93) | ⏸ | **FROZEN (25.05 рой 3/3):** Future pivots touch→reaction — DEV-36 modifier уже покрывает через ±10 overall_strength. ML-фича нецелесообразна до 200+ confirmations-trades. Пересмотр при наличии данных | ARCH/DEV |
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
| [DEV-144](#dev-144) | ✅ | **Полный редизайн дашборда (25.05 закрыт)** — план 24.05 от team_ask 3/3 LLM. **6 stages × 1 неделя** = Vue 3 + Vite миграция + Pattern Heatmap (215×режимов) + Command Palette (Cmd+K) + "Why did bot do X?" Decision Trace timeline + Drag-and-drop (опц.). **Полное описание + wireframe + миграция поэтапно + библиотеки:** [`obsidian/Architecture/DEV-144-Dashboard-Redesign-Plan.md`](obsidian/Architecture/DEV-144-Dashboard-Redesign-Plan.md). Quick Wins (Critical Alerts / Collapsible / Drops card) — закрыты в D-067 24.05. **Stage 1 (25.05):** ✅ Vite + Vue 3 + Pinia + Vue Router setup в [`web/dashboard/`](web/dashboard/), App.vue с sidebar/topbar, перенос палитры в `src/assets/main.css` через CSS-переменные, 5 страниц-заглушек. **Stage 2 (25.05 — ✅ 5/5):** Все компоненты делегированы в cerebras gpt-oss-120b (~5500 output tokens суммарно). [`CriticalAlerts.vue`](web/dashboard/src/components/CriticalAlerts.vue) (D-067 QW1 правила), [`HeroGrid.vue`](web/dashboard/src/components/HeroGrid.vue) (4 карточки BingX Equity / Risk / Позиции-WR / Drops c свой fetch /api/dropped 60s), [`EquityCurve.vue`](web/dashboard/src/components/EquityCurve.vue) (самописный SVG cumulative R curve, area+line, корнер-лейблы), [`StrategyMetrics.vue`](web/dashboard/src/components/StrategyMetrics.vue) (4 KPI: EV/PF/AvgR-WL/Open P&L), [`ATRChange.vue`](web/dashboard/src/components/ATRChange.vue) (3 карточки 1h/4h/15m из /api/atr_stats). **Stage 3 (25.05 — ✅):** [`composables/useSSE.js`](web/dashboard/src/composables/useSSE.js) (EventSource обёртка с auto-reconnect и exponential backoff 1s→30s), [`stores/dashboardStore.js`](web/dashboard/src/stores/dashboardStore.js) (Pinia: SSE `/api/events?dashboard=1` для stats/equity/confluence/breakeven/analytics/signal_weights + lightweight polling `/api/dashboard` 10s для scan_health), [`stores/liveStore.js`](web/dashboard/src/stores/liveStore.js) (polling `/api/live` 5s — SSE не покрывает баланс биржи). **Critical fix:** `/api/summary` endpoint не существует — Stage 2 компоненты получали 404. Stage 3 переключил на `/api/stats` через SSE. **Stage 4 (25.05 — ✅):** [`OpenPositionsTable.vue`](web/dashboard/src/components/OpenPositionsTable.vue) (15 sortable колонок, символ/направление/SL/TP/Δ%/R/MFE/strength/конф/режим/время) и [`ClosedTradesTable.vue`](web/dashboard/src/components/ClosedTradesTable.vue) (16 sortable колонок + status-badge + длительность h/m + пагинация панель с per-page select 25/50/100/200), [`stores/closedTradesStore.js`](web/dashboard/src/stores/closedTradesStore.js) (Pinia + `/api/closed_trades?page&per_page`). Open trades тянутся через `dashboardStore.stats.open_trades` (SSE). **Stage 5 (25.05 — ✅):** Backend [`_handle_patterns`](web/dashboard_server.py) (новый endpoint `/api/patterns` парсит `config/arch104_patterns.yaml` → 215 production patterns). Frontend [`Patterns.vue`](web/dashboard/src/pages/Patterns.vue) и [`DecisionTimeline.vue`](web/dashboard/src/pages/DecisionTimeline.vue) (route `/trades/:id?`). **Stage 6 (25.05 — ✅):** [`CommandPalette.vue`](web/dashboard/src/components/CommandPalette.vue) (Cmd+K/Ctrl+K глобальный с preventDefault — иначе Chrome ловит в адресной строке; источники — 7 страниц + open_trades + 215 patterns; ↑↓ навигация + Enter + Esc), [`composables/useDensity.js`](web/dashboard/src/composables/useDensity.js) (Compact/Comfort toggle через CSS-каскад `.density-compact` в main.css + localStorage persistence) с кнопкой в topbar, [`Sparkline.vue`](web/dashboard/src/components/Sparkline.vue) (мини-SVG line+area+zero-dash+last-dot для будущей интеграции в таблицы). **Финальный production build: 3.26s, 49 модулей, 0 ошибок, bundle 57 KB gzipped — в плановом бюджете 80-120 KB. DEV-144 закрыта.** 7 страниц / 5 компонентов / 3 store / 2 composable / 8 routes. | DEV |
| [DEV-144f](#dev-144f) | 🟢 | P6: Единый CSS — тёмная тема, виджет-карточки, responsive grid | DEV |
| D-067 | ✅ | **Dashboard Quick Wins (24.05):** (QW1) **Critical Alerts** баннеры при `exchange_health=DOWN` / `scan_health=DEAD` / `monitored_pairs=0` / `latency>3000ms` — diagnostic-first design. (QW2) **Collapsible sections** через `<details>/<summary>` для 10 вторичных таблиц (by_strategy, by_signal_type, by_direction, by_regime, by_session, confluence breakdown, BE statistics ×2, адаптивные веса, симуляция депозита) — scroll fatigue устранён. (QW3) **Drops summary card** — 4-я hero-карточка с топ-3 gates за последний час (`/api/dropped?hours=1&limit=3`). Все 3 QW на vanilla JS, без миграции стека. | DEV |
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
| [DEV-224](#dev-224) | 🔴 | **A/B анализ Shadow Mode (поставлена 27.05.2026 ~11:00 UTC):** Через **24-48ч** (цель: 50-100 закрытых сделок) проверить накопленные shadow данные. **Два эпика shadow:** (A) **ARCH-113 TPSelector** (commit 49eafbc) — сравнить предсказанный `tp_selector_tp1_price/dist_R` с фактическим exit на закрытых сделках. Решение: если предсказание `dist_R` достигнут (max_R >= dist_R) чаще чем фактический `R_multiple` → включить `tp_selector_enabled: true`. (B) **Signal Quality 4 правки роя** (commit eb3f0d0) — для каждой стратегии (confluence/wt_signal/pivot_reversal + timing) сравнить `would_pass=true` vs `false` по WR/avgR. **SQL (см. memory/current_state.md):** `SELECT signal_type, json_extract(features_json,'$.shadow_confluence_would_pass'), COUNT(*), AVG(R_multiple), 100.0*SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END)/COUNT(*) AS wr FROM simulated_trades WHERE status IN ('TP','SL','TSL','EXPIRED') AND created_at >= '2026-05-27 11:00' GROUP BY 2;`. Источник правок: рой 5/5 — `obsidian/Team-Discussions/2026-05-27-улучшить-триггеры-входа-3-убыточных-стратегий-дета.md`. **Acceptance:** если `would_pass=true` показывает Δ avgR ≥ +0.3R И n ≥ 20 → переводить gate в production HARD (по каждой стратегии отдельно). | DEV |
| [DEV-223](#dev-223) | 🔴 | **Ревизия режимной фильтрации (data audit 26.05.2026):** Аудит 8409 сделок post-15.04 показал: режимы НЕ предсказывают исход. Все 4 режима дают WR<50% и avgR<0. Медиана R=-1.0 у большинства групп — режим не влияет на попадание в SL. Единственное обоснованное исключение — **HIGH_VOL**: WR=6.9%, avgR=-0.231, 94% SL. **Действия:** (1) Убрать `allow_short_regimes: ["TREND_DOWN"]` из ATRChange — данные не подтверждают. (2) Аудит всех других режимных фильтров (wt_signal DEV-186, pivot DEV-210, ARCH-82) — оставить только HIGH_VOL блокировки. (3) Проверить почему ATRChange SHORT в HIGH_VOL = 0 сделок. | DEV |
| [DEV-211](#dev-211) | 🟡 | **MTFPivotAnalyzer deprecation + upgrade:** старый класс в mtf_pivot_integration.py использует `45m` (нестандартный TF) + старые импорты. Пометить deprecated; pivot confluence работает через PivotCalculatorFixed.find_confluences() | ARCH/DEV |
| [DEV-212](#dev-212) | 🟢 | **pivot_confluence_2plus activation:** registry имеет вес=6 но никто не генерирует. После 50+ fvg_pivot_zones записей — подключить как ConfirmationRegistry confirmation | DEV |
| **🆕 TSL/SL ROЙ-КОНСЕНСУС (18.05.2026)** — результаты team-ask 4/6 моделей, консенсус 5/5 | | | |
| [DEV-216](#dev-216) | ✅ | **De-escalation fix (18.05):** `r_gradient_rollback_pct: 0.75→0.25` + `r_gradient_peak_min_r: 2.0→2.5`. TSL де-эскалирует при 75% откате от пика (было: 25%). TSL живёт дольше на старшем ТФ | DEV |
| [DEV-217](#dev-217) | ✅ | **Per-strategy TSL activation (18.05):** `tsl_activation_r_per_strategy` в config.yaml + чтение в trade_simulator.py:1703. pivot=0.5R, wt_b=0.8R, wt_signal=1.0R, atr_change=1.5R | DEV |
| [DEV-218](#dev-218) | ✅ | **Swing SL fix (18.05):** `_compute_swing_levels` в trading_intelligence.py:2530 — `min→max` для LONG (ближайший swing low), `max→min` для SHORT. Причина: раньше брался самый дальний → всегда >3% → fallback ATR | DEV |
| [DEV-219](#dev-219) | ✅ | **SL кап 2% (18.05):** `sl_max_pct: 3.0→2.0` в двух местах config.yaml. Данные: SL 2-3% avgR=-0.206 (убыточен) | DEV |
| [DEV-220](#dev-220) | 🟢 | **MTF событийная TSL активация:** активация по 1h ATR-trend flip (не по +R порогу). Триггер: DEV-199 EventBus уже публикует ATR trend events. Требует интеграции в check_open_trades_with_tsl | DEV |
| [DEV-221](#dev-221) | 🔵 | **SMC OB exit при де-эскалации:** если цена вернулась в Order Block при де-эскалации → закрывать позицию. Уникальная идея Mistral из team-ask | DEV |
| [DEV-222](#dev-222) | ✅ | **arch104 исключён из blocked_regimes HIGH_VOL (27.05 коммит 07663bd):** `trading.blocked_regimes_exceptions: [arch104]` в config + Guard 1 в trade_simulator. Было: 19 drops/6h. Контекст: блок 24.04 был ДО BE engine; с BE@0.5R HIGH_VOL = +0.351R. | DEV |
| **🆕 ARCH-104 ВОРОНКА (27.05.2026 расследование)** — 88/7д vs 591 confluence (×6.7 меньше). 31/215 паттернов задействовано (14%). Главный душитель — D-051 wt_cross hard gate (26.05): поток упал с 20/день до 1-3/день. T5_L_02 avgR=+6.41 — артефакт SWARMS+AIN pump-кластера (без них −0.71R). RI v1 не режет (99% apply). 90% потерь между risk_decisions_log и register_trade | | | |
| D-073 | ✅ | **D-051 observability (27.05 коммит f7356ac):** `await record_drop(gate_name='arch104_d051_no_wt_cross')` в [arch104_observer_loop.py:414-428](bot/loops/arch104_observer_loop.py#L414-L428). Был silent return → теперь signal_drops с pattern_id/det_tf/required_flag/anchor_factors. Через 3 дня — точный счётчик D-051 отказов. Acceptance: `SELECT gate_name='arch104_d051_no_wt_cross', COUNT(*), COUNT(DISTINCT symbol)` показывает данные | DEV |
| D-074 | 🟢 | **Soft D-051 — решение по данным D-073:** через 3 дня после рестарта проверить распределение из signal_drops. Варианты: (A) soft penalty −25 strength + shadow flag (сделка живёт, min_strength отсеет слабые); (B) TF-зависимый soft (1h hard, 4h/15m/5m −15); (C) оставить hard если D-073 покажет что D-051 режет преимущественно мусор | DEV |
| D-075 | 🟢 | **Disable D2_L_L3_15m_03:** 17 сделок avgR=−0.41 WR_TP=0% — самый частый шумовой паттерн arch104 (лидер по объёму, проигрывает). `config/arch104_patterns.yaml` → `enabled: false`. Подтвердить ещё раз перед disable что данных достаточно (n=17 на грани значимости) | DEV |
| D-076 | 🟢 | **Single-position-per-symbol guard для arch104:** защита от SWARMS-style pyramid (25.05 за 2.5ч 4 сделки на одной паре по +15R — иллюзия силы T5_L_02). Проверка `existing_open WHERE source_router='arch104' AND symbol=?` в `arch104_observer_loop._try_register_vst_trade` перед router.submit. Опционально — допустить пирамиду но cap=3 (D-026 multi-TF независимость не должна страдать) | DEV |
| **🆕 SL/TP INTELLIGENCE (25.05.2026)** — рой 4/6 моделей (контекст 83K). Исследование: 156K уровней, 20 пар, 2.4 года. FVG <0.3R = 73-86% reach. Gravity α=1.5 → top10%=83%. Pyramiding lift +14-21%. БД: 42% SL имели max_R>0.5R. Прогноз: WR 25%→70-85%, expectancy −0.44R→+0.75R | | | |
| [ARCH-113](#arch-113) | 🔴 | **TPSelector — Intelligent TP Gravity Engine** (исследование 25.05.2026, 7 скриптов). **Phase 1 (~2-3д):** `core/smc/tp_selector.py` — кластеризация FVG(decay)+PDH+psycho+pivot ±0.5%, `score=gravity/dist^1.5` (α=1.5 доказан данными), возвращает TP1 (LTF dist<0.5R) + TP2 (HTF dist 1-3R). Plugin-layer в `recommendation_generator.py` через `apply_tp_selector()` + флаг `sl_tp_engine.tp_selector_enabled: false` в config. **Phase 2 (~1-2д):** SLSelector — добавить OB edge + CHoCH/BOS confirmation + параметрический буфер. **Phase 3 (~1-2д):** Pyramiding signal PYRAMID_ADD при TP1 hit → monitoring.py trigger к TP2 (lift +20.9% при HTF/LTF ratio 1.5-2.5x). MVP источников: FVG(young 0-3 bars)+PDH+psycho (консенсус 5/5 роя). A/B по стратегиям+парам. Team-discuss: `obsidian/Team-Discussions/2026-05-25-arch-113-tpselector-plan-реализации-intelligent-sl.md`. Исследование: [[obsidian/Research/ARCH-113-TPSelector-Research-2026-05-25.md]] | ARCH/DEV |
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
| **🚀 СПРИНТ «ARCH-104/105 LIVE» (22.05.2026)** — pipeline жив, ARCH-105 hidden div в проде | | | |
| D-046 | 🟡 | **Separate Isolated Margin mode** на BingX (Hedge уже есть) для D-026 Multi-TF Scaling. Закрыть все позиции → переключить mode → убрать "позиция уже открыта" check в OrderManager + уникальный trade_mode per (det_tf, pattern_id). Даёт N независимых позиций per пара. | DEV |
| D-049 | ✅ | **SL exit_price slippage fix (23.05 commit 80f5c26):** при status='SL' и R<-2.0 заменяем `exit_price = SL_price` вместо artifact mark_price. Корень: position_sync берёт current mark при не-нахождении filled order. HANA T4_S_09: 3 SL все по exit=0.03829 → R=-7.58 (вместо -1). Backlog D-049.2 — правильный fetch_order(exchange_order_id) | DEV |
| D-055 | ✅ | **Noise mute (26.05.2026): min_strength 50→80 для pivot_reversal/wt_signal/confluence** в `config.yaml` source_policies. Данные: pivot_reversal avg=-0.22R WR=29%, wt_signal avg=-0.48R WR=32%, confluence avg=-0.58R WR=31% (n=8163 post-15.04). Без рестарта кода — только конфиг. | DEV |
| D-056 | ✅ | **BE engine активирован (26.05.2026): `use_breakeven: true`, `breakeven_activation_r: 0.5`** в `config.yaml`. Код уже был (DEV-40), только `false` → `true`. A/B sim: BE@0.5R+TP2.0R = +0.32..+0.47R на всех режимах vs current -0.14..−0.25R. SL переносится в entry после +0.5R (54.4% сделок достигают этого уровня). | DEV |
| D-053 | ✅ | **CRITICAL fix (26.05 commit d002668): WsFeed cascade crash → auto-restart.** 3-part fix: (1) WsFeed.reset() + restart-loop в _start_ws_feed (30s cooldown, бесконечно); (2) monitor_market outer restart-loop (10s cooldown) вместо fatal Exception exit; (3) gather(return_exceptions=True) в scan_all_pairs. До: WsFeed crash = 4.5h downtime. После: auto-recover < 30s. | DEV |
| D-054 | 🟡 | **API throttling — бот перегружает minor pairs:** 109,183 случая slow OHLCV >10s за 3 дня. Топ-10: SHIB, ZK, CC, WHITEWHALE, BARD, NIGHT, BEAT, BLUAI, WIF, FARTCOIN — все minor liquidity. Корень: `scan_semaphore_size=20` × 237 пар × 4 TF = 948 OHLCV calls per scan burst → BingX throttle → cascade на D-053. **Fix:** (1) semaphore 20→12, (2) stagger fetch 4 TF в scan_one (не параллельно), (3) min_volume_usd 5M→20M (отсечёт половину slow pairs), (4) per-pair tier prioritization (major sync, minor async lazy) | DEV |
| DOC-PAT-01 | 🟢 | **Pattern Library Reference** (`show_pattern.py` готов 23.05): CLI lookup tool для 175 patterns. **TODO расширить:** markdown docs в `obsidian/Architecture/ARCH-104-Pattern-Library/` со словесными описаниями каждого pattern ("Bull continuation through 4h trend + 1h FVG support") + readable таблицы по tier'ам | DEV/ARCH |
| D-051 | ✅ | **Runtime per-TF trigger gate:** `wt_cross_{dir}_{det_tf}` gate в `_try_register_vst_trade`. Retest 26.05: без wt_cross_up_1h якорь → WR=37% (шум), 1h cross критичен. Gate применяется только к паттернам БЕЗ wt_cross_*_1h в anchor_factors (T8 освобождены). Коммит 3348afa | DEV |
| D-051.B | 🔵 | **Walkforward per-TF triggers (combinator surgery):** `combinator_v3_nested` сейчас работает только с 1h-data для HTF mask. Чтобы валидировать `wt_cross_*_5m/15m/4h` как trigger — нужно переписать на multi-TF HTF grids. 5-10ч код + 4-6ч walkforward. Запускать ТОЛЬКО если D-051 shadow покажет positive edge | DEV |
| D-048 | 🟢 | **Re-entry from watchlist** после SL: pair → arch104_watchlist (TTL 4-8h) → ждать divergence + cross_*_15m → re-entry на confirmation. Использует сохранённый HTF context | DEV |
| **🚀 СПРИНТ «API LOAD REDUCTION» (24.05.2026)** — quick fix после BingX TEMP BAN 100410 (190 ошибок/час). Перед возвратом к Real Killers. | | | |
| D-059 | ✅ | **Balance cache 30s TTL** в OrderManager. 5 callsites (trade_router, scan_loop×3, monitoring) теперь идут через единый `_balance_cache`. До: ~190 ошибок 100410/час. После: 0 ban'ов за 4+ мин с рестарта 22:12 | DEV |
| D-060 | ✅ | **Architecture audit повторных API calls** (team_ask 4/4 LLM consensus): найдено 7 callsites `get_positions`, 8 `get_open_orders`, 3 `get_filled_orders` без кеша. Все 4 LLM независимо предложили PairStateRegistry (но это уже спроектировано в ARCH-96 FROZEN). Решение: точечные кеши на текущей итерации (D-061/D-062), архитектурный fix — после разморозки ARCH-96 в Phase 4. | DEV/ARCH |
| D-061 | ✅ | **Positions cache 15s TTL** в OrderManager (`_get_positions_cached`). Подключено: order_manager×3, position_sync, position_manager. Invalidate на open_bracket. До: ~840 calls/час. После: ~240. | DEV |
| D-062 | ✅ | **Open_orders per-symbol cache 10s TTL** в OrderManager (`_get_open_orders_cached`). 8 callsites: get_sl_order_id, get_tp_order_id, place_tp dup-check, place_sl dup-check (без force), verify+update_sl (force=True). Invalidate в cancel_order/place_tp/place_sl. До: ~5040 calls/час. После: ~360. | DEV |
| D-063 | ✅ | **ARCH-18 enforce — reuse pre-computed wt1/trend** в 4 детекторах (confluence_scanner, confluence_state_machine, divergence_detector, trend_signals). До: `calculate_wt/trend` вызывался 6-12× на pair на scan. После: 1× если scan_one уже сделал pre-compute. Защита от дублирования — `if "wt1" not in df.columns` | DEV |
| D-064 | ✅ | **Архитектурный аудит ускорения OHLCV scan loop** (team_ask 4/4 LLM + BingX official docs). **Главное открытие:** анализ цикла 474s → **94% времени = OHLCV fetch** (4099/4356s), 6% = SMC+MTF, 0% = divergence. **189 пар с OHLCV>15s включая LINK/BERA/KAITO** — это НЕ minor liquidity, а очередь нашего rate_limiter. Найдено: `api_rps=15` это **30% от потолка BingX (50 RPS per IP)** — самоограничение 2024 года. Multiple API keys отвергнуты (лимит per IP). Roadmap: WsFeed для 15m × 239 пар (D-066), Lazy 4h/1d fetch, SWR cache | DEV/ARCH |
| D-065 | ✅ | **Quick wins ускорения** (24.05): `api_rps 15→30` (60% потолка BingX), `_CACHE_TTL 4h 900→3600s + 1d 1800→7200s` в api_engine.py + data_collector.py. Ожидаемый эффект: cycle **474s → ~250s** (2× speedup). | DEV |
| D-066 | ✅ | **WsFeed для 15m — STABLE на Phase D config (1 instance × ≤120 пар).** Phase A/B/C ✅, Phase D ✅ (109 пар × 10 часов 0 errors). **Phase E (25.05 13-15):** попытка 3×80=240 пар сломалась — event loop saturation, scan_loop 700-3327s, дашборд завис. **Phase F (25.05 20:15):** попытка 1×240 — стабильный плато 750s/cycle. **STABLE rollback (25.05 21:15):** возврат к Phase D + улучшенные TTL (15m=900s, 1h=3600s, 4h=14400s) + skip_no_cache fix в merge() (избавился от limit=1 бага). Multi-instance код + dynamic add `update_priority_pairs` сохранены. Финал: WS ~100 priority пар (открытые сделки + watchlist), scan_loop 227-305s, 0 errors. | DEV |
| D-068 | ✅ | **WsFeed startup wait extended (25.05 20:00):** `_start_ws_feed` ждал 30 сек на monitored_pairs. Если scan_loop не успевал заполнить — WsFeed не запускался (warning + return). Фикс: wait 5 мин + retry каждую минуту до 30 мин общего ожидания. Устранена hidden bug "WsFeed не запущен" после быстрых рестартов. | DEV |
| D-069 | ✅ | **Persistent OHLCV cache (26.05 01:22):** `OhlcvCache.save_to_disk()` / `load_from_disk()` в [api_engine.py:125-194](core/infra/api_engine.py). Wall-clock timestamp (не monotonic — сбрасывается). При load валидация age < max_ttl (24h), виртуальный monotonic = now - age. Lifecycle в bot.py: load при startup, save в finally `start_polling()` (graceful Ctrl+C), periodic snapshot каждые 5 мин (защита от kill -9). Файл `cache/ohlcv_snapshot.pkl` (~16MB на 1446 entries). Эффект: устранил initial REST tax после рестарта (~1159s/cycle → cache pre-loaded). | DEV |
| D-070 | ✅ | **Orphan position detector (26.05 00:50):** в `core.exchange.position_sync._detect_orphans()` — встроен в существующий `sync_positions` (каждые 60с), без новых API calls. Сравнивает `open_on_exchange` с `simulated_trades.status='OPEN'`. Orphan = на бирже есть, в БД нет → Telegram alert через `broadcast_with_subscription_check`. Throttle 30 мин/символ. Поводом стал PIEVERSE 25.05: позиция закрыта в БД (status=SL), но на бирже остался SHORT без stop loss → закрыто вручную. | DEV |
| D-071 | ✅ | **Quick Wins для подготовки к 5-10× нагрузке (26.05 01:22):** team_ask 5/5 LLM consensus. **(QW1)** `fetchMarketsThrottle: 3600*1000` в ccxt config — отключён автоматический market reload. До: 306 calls `/contracts` + 207 calls `/symbols` за 35 мин (порочный круг ccxt retries при BingX timeouts). После: **0 calls/12мин**. **(QW2)** ccxt timeout 10s→30s во всех BingXClient методах (`aiohttp.ClientTimeout(total=30)` × 6 мест) + `timeout: 30000` в ccxt config. **(QW3)** `sync_time()` throttle 60s — skip если синхронизировались < 60с назад. До: 96 fails/35мин (каждые 22с). После: **3 fails/12мин (-94%)**. POSITION-SYNC errors: 9 → 1 (-89%) → D-070 заработает. | DEV |
| D-072 | 🔵 | **data_service отдельный процесс + Redis** (следующая архитектурная фаза по team-ask 5/5 LLM, D-071 discussion). Цель: разгрузить main_bot event loop под scale 5-10× (533 BingX пар + multi-exchange ready). WS+REST → отдельный Python процесс → Redis Pub/Sub → main_bot subscribe. Schema: `stream:pair:{sym}:ohlcv`, `stream:pair:{sym}:ticks`, `pubsub:commands:order`, `pubsub:events:health`. Установка Redis через Docker (Windows). 1-2 дня работы. Полное обсуждение: [`obsidian/Team-Discussions/2026-05-25-d-071-стратегия-подготовка-к-5-10-нагрузке.md`](obsidian/Team-Discussions/). | DEV |
| **🚀 СПРИНТ «OBSIDIAN AUTOMATION» (23.05.2026)** — реализовано в одну сессию | | | |
| ARCH-OBS-01 | ✅ | **`tools/obsidian_status_sync.py`** — frontmatter sync TASKS.md ↔ Tasks/*.md. `.git/hooks/post-commit`. 23 файла обновлено | DEV |
| ARCH-OBS-02 | ✅ | **`tools/vault_health.py`** → `obsidian/Meta/HEALTH.md` — orphans 65%, broken 17%, untagged 2.1%. Daily в obsidian_loop | DEV |
| ARCH-OBS-03 | ✅ | **`tools/obsidian_autolink.py`** — wikilinks по ID. `.git/hooks/post-merge`. 164 known IDs, 2779 потенциальных links | DEV |
| ARCH-OBS-04 | ✅ | **`tools/obsidian_weekly_digest.py`** → `obsidian/Index/WEEKLY-*.md`. Weekly в obsidian_loop (воскресенье) | DEV |
| ARCH-OBS-05 | ✅ | **`tools/obsidian_dedup_discussions.py`** — LLM semantic dedup (Groq→Gemini). → `obsidian/Meta/DEDUP-REPORT.md` | DEV |
| ARCH-OBS-06 | ✅ | **`tools/obsidian_archive.py`** — файлы >90 дней без ссылок → `_archive/`. Weekly в obsidian_loop (воскресенье) | DEV |

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

