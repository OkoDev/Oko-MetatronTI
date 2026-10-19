# 📦 TASKS ARCHIVE — Завершённые задачи

> Все задачи со статусом ✅. Детальные спецификации — в git-истории и PROJECT-LOG.md.
> Последнее обновление: 13.06.2026 (+106 карточек из TASKS.md, секция внизу).

---

## ✅ Завершённые задачи (хронология)

| ID | Дата | Описание |
|---|---|---|
| DEV-53 | 25.03 | L3 Фаза B: cond4 WT freshness + CHoCH penalty (-8) |
| DEV-59 | 29.03 | Закрыто через DEV-64A: global max_rr=3.0 кепает pivot_reversal |
| DEV-61 | 25.03 | RANGE-специфичный RR cap + min_strength_by_regime |
| DEV-62 | 25.03 | Tiered EXPIRED: конвертация прибыльных TREND позиций в TSL |
| DEV-63 | 29.03 | ARCH-51: MTFSMCSnapshot + shadow logging |
| DEV-64A | 29.03 | Global max_rr=3.0 enforce в register_trade() + WL breach |
| DEV-64B | 29.03 | signal_regime_block: pivot_reversal block в RANGE/TREND_DOWN |
| DEV-64C | 29.03 | Отменено — первопричина устранена DEV-64A |
| DEV-65 | 29.03 | Бэктест: tsl_line vs ATR×1.5 — проблема в RR=18x, не в SL |
| DEV-66 | 29.03 | factor 1.1 → 1.25 в config.yaml (бэктест подтвердил) |
| DEV-67 | 29.03 | Cascade TSL fallback: prev_tsl_tf при развороте тренда |
| DEV-68 | 29.03 | WL breach min_strength guard (DOGE str=18 баг) |
| DEV-69 | 29.03 | WL breach min_strength_wl_breach: 45 |
| DEV-70 | 29.03 | ARCH-04 gap: cfg → get_regime_params() + sl_factor комментарий |
| DEV-71 | 27.03 | ARCH-54 Фаза 1: папки + файлы + stub re-exports |
| DEV-72 | 27.03 | ARCH-54 Фаза 2: обновить CLAUDE.md структуру |
| DEV-73 | 29.03 | TSL gate fix: активировать при +1R для DUAL/TRIPLE |
| DEV-74 | 29.03 | DUAL_TP в RANGE деактивировать → SINGLE (avg_R=-0.942) |
| DEV-75 | 29.03 | Перевернуть иерархию TP: 1D→1W→confluence→1M |
| DEV-76 | 28.03 | ARCH-53: core/signals/ote_detector.py + shadow mode |
| DEV-77 | 29.03 | OrderExecutor: SIM/VST/LIVE + bracket + partial close |
| DEV-78 | 29.03 | PositionManager + PositionSizer + live_orders + OrderReconciler |
| DEV-79 | 29.03 | Trading Panel: web/static/ рефакторинг |
| DEV-80 | 29.03 | Trading Panel: /trading page + Position Sizer UI + badge |
| DEV-81 | 29.03 | FUNDING_EXTREME detector: core/signals/funding_detector.py |
| DEV-82 | 29.03 | LIQUIDITY_SWEEP detector: core/signals/liquidity_sweep_detector.py |
| DEV-83 | 29.03 | ARCH-56: phase_detector + zone_cascade + avoid_reason + named_pattern |
| DEV-84 | 28.03 | L3 Фаза C: FVG/OB + OTE shadow logging |
| DEV-85 | 28.03 | OTE v2: Step0 stale-invalidation + Step1 wide [0.705-0.786] + ATR gate |
| DEV-86 | 29.03 | get_tp_by_hierarchy(): убрать R4–R5/S4–S5 расширенные уровни |
| DEV-88 | 28.03 | Market Regime патч: Fix1 avg 3 ATR + Fix3 spike guard 5 bars |
| DEV-89 | 28.03 | Cascade TSL: OR-логика 4h+1h WT + weekly pivot touch trigger |
| DEV-90 | 29.03 | ARCH-59: classify_v2() shadow mode + config.yaml |
| DEV-91 | 29.03 | TR-009: _r_gradient_drop shadow trigger в cascade TSL |
| DEV-91-v2 | 02.04 | R-gradient drop: убран shadow → реальный gate де-эскалации |
| DEV-92 | 29.03 | TR-010 Фаза 1: _post_tsl_queue в TradeSimulator |
| DEV-93 | 29.03 | PairContextBus: core/context/pair_context.py |
| DEV-94 | 29.03 | PostTradeAnalyser: core/trading/post_trade_analyser.py |
| DEV-95 | 29.03 | TriggerBus: trigger_bus.py + trigger_loop.py + bot интеграция |
| DEV-96 | 29.03 | SMC флаги: 4 направленных флага в to_features() |
| DEV-98 | 29.03 | Guard 4: pivot_reversal strength≥80 → skip (WR=4.5%) |
| DEV-99 | 29.03 | Скан 534 пар >70 сек: scan_semaphore 10→20, min_volume 0→1M |
| DEV-101 | 29.03 | WS Фаза 1: _log_ws_stats_after_warmup + pre-filter trade_tracker |
| DEV-103 | 02.04 | Exchange Health Loop + TG алерт (Слои 1+2 ARCH-65) |
| DEV-106 | 02.04 | Pivot Touch Fast Exit: R≥2.0 → force 15m TSL (+2.44R avg) |
| DEV-107 | 02.04 | CASCADE_TFS.index() баг — cascade де-эскалация никогда не работала |
| DEV-108 | 02.04 | dynamic_os активирован только в RANGE: mean±0.8std |
| DEV-109 | 02.04 | RANGE: confluence разблокирован (WR=63.6% SHORT, avg_R=+2.67R) |
| DEV-111 | 02.04 | BTC 4h market gate shadow: _get_btc_4h_regime() + gate в monitoring.py |
| DEV-113 | 02.04 | Dashboard VST P1: auto-refresh 30s + BTC 4h badge + cascade badge |
| DEV-114 | 02.04 | Dashboard VST P1: Risk Exposure карточка + Open P&L |
| DEV-115 | 02.04 | Dashboard VST P1: live R в open trades + cap%/MFE в closed |
| DEV-116 | 02.04 | Dashboard P2: Session heatmap + R-distribution + bar chart |
| DEV-118 | 30.03 | Фикс двойного analyze_symbol: один вызов на пару за цикл |
| DEV-119 | 30.03 | TRIPLE_TP_TSL убран, DUAL_TP переработан: TP1=пивот, TP2=след. пивот |
| DEV-120 | 30.03 | DUAL_TSL TREND + параллельный broadcast asyncio.gather |
| DEV-122 | 02.04 | tsl_activation_r_range=0.7 + tp_pivot_min_r_range=1.2 |
| DEV-123 | 02.04 | anti-degradation gate: R >= 5R → skip degradation |
| DEV-124 | 02.04 | EXPIRED extension: max_R_possible >= 5R → 120h |
| DEV-125 | 02.04 | TREND → SINGLE: DUAL убраны (SINGLE +1866R vs DUAL -88.5R) |
| DEV-126 | 03.04 | features_json баг: session + htf_wt1_1h у 53% сделок |
| DEV-128 | 03.04 | weekly_bias gate: pivot_reversal блок при weekly_bias=NONE |
| DEV-128ext | 04.04 | Контртренд gate: LONG TREND_DOWN / SHORT TREND_UP / SHORT HIGH_VOL |
| DEV-129 | 05.04 | PivotTouchTrigger: pivot касание → немедленный analyze_symbol (shadow) |
| DEV-130 | 04.04 | pivot_1M заблокирован как TP + core/exchange/ рефакторинг |
| DEV-131 | 04.04 | PositionManager VST Phase 2 + TSL Вариант A (cancel+replace) |
| DEV-132 | 04.04 | ENA TSL floor + VST sync фиксы |
| DEV-133 | 04.04 | blocked_combos (direction×regime) + htf_wt в WL breach |
| DEV-134 | 04.04 | ENA TSL floor = entry price (финальный фикс) |
| DEV-135 | 04.04 | Guard 3B + открываем SHORT RANGE/TREND_DOWN (+141R) |
| DEV-136 | 04.04 | TSL биржа: exchange_order_id/sl_order_id/qty в simulated_trades |
| DEV-137 | 05.04 | ARCH-68: Reversal Mode Detector — classify_mode() |
| DEV-138 | 05.04 | ARCH-68: MTF WT Specialist — core/ml/mtf_wt_specialist.py |
| DEV-139 | 05.04 | ARCH-68: MTF SMC Specialist — core/ml/mtf_smc_specialist.py |
| DEV-140 | 05.04 | ARCH-68: EQH/EQL детектор — detect_equal_highs_lows() |
| DEV-141 | 05.04 | ARCH-68: Narrative Builder — core/intelligence/narrative_builder.py |
| DEV-142 | 05.04 | ARCH-68: PairContextBus pub/sub + wt/smc/mode поля |
| DEV-143 | 05.04 | position_sync: get_ticker() fallback → корректный exit_price VST |
| DEV-144a | 05.04 | Риск-менеджмент в settings UI: deposit/risk_pct/leverage |
| DEV-144b | 05.04 | JOIN live_orders+simulated_trades → SL/TP цены в /api/live_orders |
| DEV-144c | 05.04 | /api/live: реальный баланс BingX + позиции с биржи |
| DEV-145 | 05.04 | position_sync рефакторинг: sync_time + filled_orders + reconcile() при старте |
| TR-008 | 27.03 | ARCH-54 валидация: 31/31 модулей ОК |
| TR-009 | 29.03 | R-gradient де-эскалация TSL → DEV-91 |
| TR-010 | 29.03 | Post-TSL OTE Re-entry → DEV-92/93 |
| TR-011 | 29.03 | SMC shadow: LONG+SMC антисигнал, SHORT нейтрально |
| ARCH-48 | 28.03 | Weekly Pivot Bias Filter: Phase B включена |
| ARCH-51 | 29.03 | MTFSMCSnapshot: smc_h4/smc_d1 в MTFContext — shadow активен |
| ARCH-52 | 29.03 | Ретроспектива PROJECT-LOG.md (55 задач) |
| ARCH-53 | 28.03 | OTE детектор: спек → DEV-76 |
| ARCH-54 | 27.03 | Рефакторинг core/: разбивка по подпапкам |
| ARCH-56 | 29.03 | MTF Interpreter v2 Phase B: спек → DEV-83 |
| ARCH-58 | 29.03 | TP Architecture: get_tp_by_hierarchy() → DEV-86 |
| ARCH-59 | 29.03 | Market Regime v2: спек → DEV-90 |
| ARCH-60 | 29.03 | PostTradeAnalyser спек → DEV-94 |
| ARCH-61 | 29.03 | TriggerBus Фаза 1 спек → DEV-95 |
| ARCH-63 | 30.03 | Bear market filter: BTC 4h gate спек → DEV-111 |
| ARCH-65 | 30.03 | Exchange Health Guard спек → DEV-103 |
| ARCH-66 | 30.03 | RANGE BOUNCE стратегия спек → DEV-110 |
| DEV-151 | 05.04 | Groq AI-комментарий к сигналам в TG (monitoring.py + TradeAnalyzer.analyze_signal) |
| DEV-100 | 20.03 | chart_builder: try/except + blacklist малоликвидных пар (GAIB, BANANA) |
| DEV-110 | 30.03 | RANGE BOUNCE: calc_range_bounce_sl_tp() в sl_tp_calculator.py |
| DEV-127 | 25.03 | SMC None gate: smc_has_bos OR smc_has_choch (shadow) в wt_15m_reversal_scanner |
| DEV-87  | 12.04 | OTE backtest v2: WR=35.1% SWING, 29.2% SCALP — нужны доп. фильтры (→ DEV-88) |
| DEV-149 | 06.04 | OutcomePredictor: вектор 16→23 фич (distance_to_sl + sl_atr + wt1/2_15m + reversal_mode) |
| ARCH-45 | 06.04 | OutcomePredictor ревью: AUC=0.41 → не активировать. Следующий: 20.04.2026 |
| ARCH-55 | 30.03 | DEV-110 интеграция: MarketContext.pivot_cache_1d_1w + RANGE BOUNCE в calculate_levels() |
| ARCH-64 | 22.03 | pivot_reversal weekly_bias gate: UNKNOWN→WATCH + против bias→-20 (shadow) |
| ARCH-68 | 06.04 | Куб Метатрона Фаза 2+3: все компоненты shadow + EventBus 6 триггеров |
| ARCH-70 | 06.04 | EventBus Full CALL шина: приоритетная очередь, cooldown 30 мин/пара, семафор 3 |
| ARCH-71 | 10.04 | Real Full CALL: _fire_analysis() загружает все 6 TF + дивергенции + pre_fetched_dfs |
| ARCH-72 | 10.04 | Feedback Loop: PostTradeAnalyser → update_weights каждые 50 + EventBus trade_closed |
| DEV-146 | 06.04 | VerdictAggregator: WTVerdict+SMCVerdict → gate/strength (shadow, активирован 13.04) |
| DEV-152 | 10.04 | EventBus диагностика: логи FIRE/CONSUMED/None добавлены |
| CUBE-08 | 13.04 | Живые Сферы: WT Specialist + SMC Specialist → wt_verdict/smc_verdict для 524 пар |
| TR-007  | 13.04 | Валидация MTF WT Specialist: AUC=0.49, conf<0.65 везде → gate безопасен, нужен rule-based |
| DEV-154 | 10.04 | Position Sync fail-safe: get_positions error → skip cycle, не закрывать сделки |
| DEV-147 | 07.04 | TSL SL накопление: update_sl() → cancel ALL STOP_MARKET → place one |
| DEV-158 | 07.04 | VST: risk_pct 0.5%→1.5% — MIN_NOTIONAL fix (notional=8.25 > 5 USDT) |
| DEV-159 | 08.04 | VST: SL-direction guard в order_manager.py:140 — LONG SL<entry, SHORT SL>entry |
| DEV-160 | 09.04 | TSL guard в order_manager.py:343 — откат SL блокируется до min_move_pct |
| DEV-148 | 09.04 | SQLite WAL mode + busy_timeout=10000 — circuit_breaker + trade_analyzer + position_sync |
| DEV-157 | 11.04 | Фикс аномального SL: min_sl_dist_pct guard (ASR: -450R, XPIN: -81R при SL < 0.1%) |
| DEV-155 | 12.04 | min_strength_by_regime: HIGH_VOL=85, LONG_RANGE=75 в config + is_actionable() |
| DEV-156 | 12.04 | Circuit Breaker: rolling WR<15% за 50 сделок → +10 к min_strength на 30 мин |
| DEV-111b| 12.04 | BTC 4h gate: HIGH_VOL в условие блока LONG + лог режима при каждом вызове |
| DEV-153 | 13.04 | VerdictGate активация: verdict_gate.enabled: true (активирован 13.04) |
| DEV-161 | 13.04 | VerdictGate: rule-based derive_wt_verdict() заменил ML predict() в trading_intelligence.py:977 |
| DEV-163 | 13.04 | CircuitBreaker: лог-путаница API CB vs торговый CB исправлена; DB ошибки → WARNING |
| DEV-164 | 13.04 | DEV-157 guard вынесен из TP-блока: проверяет SL независимо от наличия TP |
| DEV-165 | 13.04 | R_multiple sanity clamp [-15,+15]: ASR R=-450 при P=-0.95% отравлял аналитику |
| DEV-166 | 13.04 | RANGE min_strength 60→70, LONG_RANGE 75→78: 52% сделок в RANGE, WR=20% |
| DEV-167 | 13.04 | RANGE BOUNCE реально заработал: pivot_cache был пуст + pivot_reversal добавлен |
| DEV-168 | 14.04 | LIVE-GUARD лог спам: cooldown 1ч/пара в trade_simulator.py |
| DEV-169 | 14.04 | atr_trend_1h_bias: UP/DOWN пишется в features_json (сбор данных) |
| DEV-170 | 14.04 | Time-of-day gate: блок входов вне 09:00–18:00 UTC, wt_signal=04:00–18:00 |
| DEV-171 | 14.04 | confluence полный стоп: `enabled: false` — было 6 combos, теперь всё |
| DEV-121 | 16.04 | Self-Diagnostics Suite: L13/L14/L15 Куб реализован |
| ARCH-78 | 16.04 | S5 BTC gate → S7/S13: BTCRegimeProvider → market_context + NarrativeBuilder |
| ARCH-83 | 18.04 | wt_entry удалена из active_strategies (WR 20%→5%, деградация) |
| DEV-178 | 18.04 | Data integrity: 6835 сделок размечены data_era, ML фильтр применён |
| ARCH-45 | 18.04 | OutcomePredictor Этап A: AUC 0.41→0.582, use_outcome_predictor активирован |
| ARCH-88 | 19.04 | Per-pair Loss Memory: код merged, shadow активен до ~21.04 |
| ARCH-89 | 19.04 | SMC_SNAP_UPDATED издатель: smc_snapshot.py + scan_loop publish (benchmark 56.9мс) |
| ARCH-90 | 19.04 | NarrativeBuilder читает smc_snap + 4 SMC-фичи в OutcomePredictor (27-вектор) |
| ARCH-91 | 19.04 | Narrative TG-блок + classify_lost_reason + narrative_outcome feedback (10/10 PASS) |
| DEV-172-FIX | 19.04 | Диагностика priority=None: NOT-A-BUG (P1/P2/P3=49/280/176 за 4д) |
| DEV-177 | 19.04 | Adaptive weights EMA (hl=50, era=post_fix) + dashboard trajectory (6/6 PASS) |
| DEV-179 | 19.04 | Метрики стратегий: median/Sharpe/p90/top20_share + warning badges |

---

## ✅ Перенесено из TASKS.md 13.06.2026 (полные карточки)


### 🔥 СЕССИЯ 11.06.2026 (Даат) — REGIME-V2 + atr_change×OTE + C-01

| ID | Ст | Описание | Роль |
|---|---|---|---|
| **STRADDLE-FREEDOM** | ✅ **ЗАКРЫТ (DS, Claude валидировал).** FREEDOM>DEDUP лишь **+0.15%** (+7.65R), **co-FIRE редок 1%** (24/2316) → dedup почти не вредит → **ОСТАВИТЬ.** Юзер-гипотеза «свобода» подтверждена по знаку, рычаг мизерный. **PHASE-SELECT:** данные пошли (DEV-226 shadow, 18 сделок); предв. would_block=0 +4.62 vs =1 +1.08 (верный знак, но n мал + ракета ALLO раздувает) → замер на n≥30. **Вывод: dedup НЕ рычаг (1%), реальный рычаг = DEV-226 Ph2** | ✅ закрыто | `scripts/straddle_freedom_test.py`, DISCUSSION 12.06 |
| **FUNDING-NODE** | ✅ data-узел funding rate + стакан Binance | ✅ скрипт готов | `scripts/funding_node.py` |
| **B4 time-decay** | ✅ деградации НЕТ — edge РАСТЁТ: ote_nested W22+1.51→W23+2.37, arch104 положителен | ✅ вывод закрыт | — |

### 🎨 ARCH-128: Воспроизведение OKO-SM + parity детекторов (03.06.2026, инициатор ARCH)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| ARCH-128 | ✅ | **Эталон OKO-SM в коде** — `core/smc/smc_engine.py`: ZigZag(+фикс плато)/structure/BOS-CHoCH(защищённые)/OB/OTE 0.5-0.79/EQH-EQL/FVG(+overlap)/Эллиотт(+extension). Провалидирован GRT/SOL/AVAX. Ветка `arch-128-oko-sm`. + `docs/PRICE_PATTERNS_LIBRARY.md` | Claude |
| DS-312 | ✅ | **Аудит parity детекторов** — карта 8 признаков × реализации. 🔴 Swing(5 версий)/OB(naive)/Premium-Discount(ОТСУТСТВУЕТ). Связал swing→DS-311 OTE=0 | DS |
| **DS-313** | ✅ | **Шаг 1 «один калькулятор»** — `swing_service_bridge.py` + naive в `compute_flags` заменены на `smc_engine`. Smoke BTC 15m OK (47 cols). Claude → Шаг 2 | DS |
| **DS-314** | ✅ | **Унификация направлений:** троичный канон `bull(+1)/range(0)/bear(−1)`. Dir-мета в bridge → ждёт Шаг 2 | DS |
| ARCH-128-S2 | ✅ | **Шаг 2: features_json эталонные поля** — `fvg_overlap`/`elliott`/`regime`(троичный +`regime_dir`)/`ob_mitigated` в bridge ETL + compute_flags (60 cols). schema v2→3. Коммит 58b9088. Нюанс: elliott постфактум. `memory/arch128_step2_features.md` | Claude |
| **DS-315** | ✅ | **Шаг 3B: walkforward+MHT** — 14789 паттернов → **6906 MHT-значимых, 2683 стабильных** (n≥50). FVG доминирует, fvg_overlap(Шаг2)=716 выживших. ⚠️ regime убран; CMA/HH-HL/dc не вошли (нет bull/bear префикса в генерации) | DS |
| **DS-316** | ✅ | **LTF-дыра закрыта:** `combinator_v3_nested_ds316.py`. SOFT HTF × LTF 15m. 7779 паттернов, n=тысячи (не 12-18). fvg_overlap на 15m: +1.552R | DS |

### 🧹 DS-MAINTENANCE (03.06)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| **DS-317** | ✅ | **Obsidian vault 2.0:** 677 файлов мигрировано, 127 stubs (4363→899 битых), Dataview-хабы, brief-фиксы | DS |
| **DS-318** | ✅ | **hidden_HTF+regular_LTF:** 249 комбо-паттернов. SHORT +1.84R WR95% | DS |
| **DS-319** | ✅ | **arch104 расследование:** pivot-уровни (R2/S3/цены) в active_htf_flags → 0 сигналов. Фикс bool-фильтр + headless-режим + aiohttp monkey-patch | DS |
| **DS-322** | ✅ | **Разгрузка scan loop:** arch104 900с, ote 600с, scan_sem 5, OHLCV кэш норм, slow_cb 1с, логи −70% (SMC_SNAP/KUB/REPAIR→DEBUG) | DS |
| **DS-323** | ✅ | **Чистка untracked + .gitignore:** `*.log.*` для ротации, `memory/last_*`, `memory/advisor_brief*`, `memory/session_brief.md`, `memory/log_digest.md`, `memory/project_timeline.md`, `.claude/agents/`, `.claude/commands/`. `crypto_bot.log.1` удалён, `monitor2.py` → `scripts/ote_monitor_xlm.py` | DS |
| **DS-324** | ✅ | **Re-mine discount/premium-паттернов после ARCH-118:** `remine_discount.py` → 39 паттернов пересчитаны с новым ROLLING dealing range. 33 отключены (n_test=0), 6 обновлены. `config/arch104_patterns.yaml` обновлён. | DS |
| ARCH-128-EXT | ✅ | **Эталон полный (75 признаков)** — +CMA Фибо(21-233) +Dynamic Channel +HH/HL/LH/LL. Коммит 25a8d98. Hull+Kahlman отложен | Claude |

### 🪵 Логи

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DS-301 | ✅ | **Ротация crypto_bot.log:** `RotatingFileHandler` (10×50MB) в `oko_mtf.py`. Архив 1.7GB → `logs/` | DS |

### 📦 Архивация

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DS-302 | ✅ | **Архивация TASKS.md:** ~40 старых ✅ задач → `TASKS-ARCHIVE.md` | DS |
| DS-303 | ✅ | **Архивация DISCUSSION.md:** 15.05–17.05 → `DISCUSSION-ARCHIVE-MAY2026.md` (2274→1660 строк) | DS |

### 🔧 Obsidian Vault

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DS-304 | ✅ | **Obsidian: аудит + фиксы** (фронтматтер 6 файлам, Months/2026-06, обновление Project-MOC) | DS |

### 🧹 Расчистка

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DS-305 | ✅ | **Obsidian: Knowledge Hub** — `_KNOWLEDGE-HUB.md`: 12 тем вместо 408 файлов | DS |
| DS-306 | ✅ | **Мёртвый код:** 7 файлов удалено. bot_with_subscriptions.py сохранён (24 ссылки) | DS |
| DS-307 | ✅ | **Logs/ + Daily-Review/:** НЕ дубликаты (разный контент). Вердикт: не объединять | DS |

### 🧹 Расчистка корня

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DS-310 | ✅ | **Порядок в корне:** логи → `logs/`, 7 файлов перенесено/удалено. Пути в `oko_mtf.py`, `bot/main.py`, `daily_log_digest.py` исправлены | DS |

### 📊 Аналитика

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DS-308 | ✅ | **DEV-229: Аудит stale-кэша** — скрипт `scripts/audit_stale_cache.py`. Находка: 14/32 OPEN с аномалиями, 11 биржевых. BE/TSL не работает на REST-only! | DS |
| DS-309 | ✅ | **TR-232a/b: T5_L_02** — подтверждён pump-артефакт. −1.00R требуют deeper анализа | DS |

### 🧬 ARCH-127 (→ DS от Claude)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DS-311 | ✅ | **ARCH-127 v2:** `scripts/mtf_reversion_backtest_v2.py`. Supertrend HTF, OTE/ATR/Fib-TP, data-era. POST_15APR: LONG +0.13 SHORT +0.19 | DS |

### 🔬 ARCH-128 (→ DS от Claude, 03.06)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DS-312 | ✅ | **Аудит parity детекторов:** карта 8 признаков × реализации. 3 крит. расхождения (swing, OB, Premium). План «один калькулятор» в DISCUSSION | DS |

### 🟢 ARCH-118 / ARCH-118.3: единый снимок признаков — ЗАКРЫТ (05-08.06)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| ARCH-118.3 | ✅ | **Вынос чистого калькулятора в `core/calculators/`** (`combinator_core.py` + `swing_bridge.py`) БЕЗ side-effects (stdout-hijack/HISTORY_DIR убраны). Бит-идентично (147 кол, 0 расх). Все пути (feature_snapshot/ote/arch104/combinator_v2) → один calculator. Хак `_import_cb` убран. Разблокировал DEV-200.2. Коммит 8667da4. | Claude |
| ARCH-118-discount | ✅ | **discount/premium ROLLING dealing range** (последний confirmed swing H/L, `_swings_luxalgo` len=20) вместо глобального ATH/ATL. **Parity 8/10→0/10.** Семантический фикс (SMC меряет от dealing range, не ATH) + lookahead-safe. discount теперь 9/600 баров (было ~почти-всегда). Коммит 6063816. DS сделал re-mine discount-паттернов (1e0858e). | Claude/DS |
| ARCH-118-snapshot | ✅ | **Единый снимок 211 фич в `trade_features`, 100% всех 11 стратегий** (ote_nested/arch104/atr_change/...). Домены meta/context{smc,wt,rsi,trend,pivot,mom}/signal, sparse (~40 true/сделку), schema_v3. wt_state_up/down флаг (юзер) в снимке. Один калькулятор live≡backtest. | Claude |

### 🔭 DS-EVOLUTION: 4 приоритета после чтения документации (06.06.2026, инициатор DS, коммит f03a667)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DS-322-TSL | ✅ | **Инцидент TSL/repair 06.06: `UnboundLocalError _now_ts` в throttle REPAIR-SL** — пофикшен (b2afa3a, import time + вынос _now_ts). *Пост-разбор: что ещё сломалось в repair-пути 06.06?* | DS |

### 🌊 WAVE-SERVICE: волновой анализ MTF — ключ к качеству (08.06, юзер «там решение», погнали без ожидания стабилизации)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| VST-SLIPPAGE | ✅ | **РЕШЕНО (DS af7bfae). Моя оценка 0.45% была ОШИБОЧНА** (спред BingX≠fill). DS-аудит `vst_slippage_audit.py`: реальный entry-slip **~0.1%**. arch104 real +0.12R (вернул из shadow), OTE+arch104 +1501R на VST. Реальный минус = pivot_reversal+confluence (→ PIVOT-CONTEXT). Урок: НЕ резать по оценке, мерить данными. | DS |

### ✅ DEV-237: РЕШЕНО 31.05 — сделки НЕ шли на биржу/VST (exchange_order_id=None) → btc_market_gate в shadow (30.05.2026, инициатор ARCH)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DEV-237 | ✅ | **Симптом:** сделки регистрируются в `simulated_trades` с `exchange_order_id=None` (paper), на биржу/VST НЕ уходят. Пример id=16075 MNT LONG pivot_reversal. **Найдено в логе (точная цепочка):** `21:42:27 ARCH-78 btc_market_gate: BUY→WATCH (BTC BEAR блокирует LONG)` → `21:42:28 TradeSimulator: зарегистрирована id=16075` → `[TradeRouter] MNT LONG pivot_reversal → #16075 source=other_strategy soft=0 exch=none`. **Противоречие (ARCH):** «мы ранее убирали ВСЕ гейты» — но `ARCH-78 btc_market_gate` активен и понижает BUY→WATCH. **Данные:** исторически на биржу идёт ~33% (5209/15539); сделки `exch=none` шли ВЕСЬ день до рестарта (16065@17:47, 16067/68/69, 16071/72) — НЕ связано с рестартом/ARCH-118 (snapshot только пишет features_json, исполнение не трогает). Сегодня BTC BEAR → масса LONG в paper. **РАССЛЕДОВАТЬ (отдельно от ARCH-118):** (A) `btc_market_gate` (ARCH-78) — активен намеренно или забыли выключить при «убирании гейтов»? где включается (config/код)? (B) логика TradeRouter: почему downgrade BUY→WATCH ведёт к `exch=none`+`source=other_strategy` (paper-регистрация), а не к полному блоку? (C) grep всех активных гейтов в пути входа — какие реально режут биржевое исполнение (btc_market_gate, regime, min_strength, портфельный лимит LONG 41/2 из лога). **Acceptance:** карта «что блокирует биржевое исполнение сейчас» + ответ активен/забыт по каждому гейту + рекомендация (вернуть исполнение / оставить paper). **СТАРТ-ДИАГНОСТИКА (30.05, найдено):** НЕ все гейты убраны — БОЕВЫЕ (не shadow): `trading.btc_market_gate`{enabled:True, shadow_mode:False, block_short_in_uptrend:True, counter_trend_min_strength:75} ← виновник MNT (BUY→WATCH при BTC BEAR), `trading.verdict_gate`{enabled:True}, `signal_quality.weekly_bias_gate`{enabled:True, shadow:False}, `dev186_wt_signal_regime_gate:True`, `ote_use_trend_gate:True`. ВЫКЛ/shadow: market_stress_gate(False), time_gate(False), btc_filter(shadow), mtf_gate(shadow). → Осталось (B) логика TradeRouter exch=none при WATCH, (C) портфельный лимит LONG 41/2. **2-я причина exch=none (16076 TONCOIN SHORT):** `[OrderManager] позиция уже открыта, пропуск` → `[TradeRouter] position_already_open — exchange skipped (SIM-only)` — это НЕ гейт, защита от дублей (корректно). **Вывод: причин paper несколько:** (1) btc_market_gate downgrade→WATCH [спорно], (2) position_already_open [корректно], (3) портфельный лимит [?]. TradeRouter ведёт SIM-статистику для ВСЕХ сигналов, на биржу — только если gate пропустил + нет открытой позиции + лимиты ок. Фокус расследования: реально ли (1) btc_market_gate должен быть ВКЛ (единственный «забытый гейт» по мнению ARCH). **✅ РЕШЕНО 31.05 (ARCH):** (A) механизм — `btc_market_gate` (ARCH-78) понижает BUY→WATCH → основной путь не вызывает TradeRouter → сделка пролезает как `source=other_strategy` (exchange_enabled=false) → paper [by design, Этап 1.Д]; (B) причина «BEAR» — runtime-проверка (`tools/check_btc.py`): BTC флэт +0.51%/48ч, но ATR Supertrend держит trend=-1 уже 17 баров (лаг); NEUTRAL недостижим (только 1 цикл при смене) → NEUTRAL-фикс роя бесполезен; (C) arch104 НЕ затронут (свой observer loop, soft_gates_enabled:[], exchange_enabled:true). **Консультация роя (3 модели), вариант A:** `config.yaml btc_market_gate.shadow_mode: false→true` (коммит `885377f`). **Подтверждено в проде** (рестарт 22:50, ~1ч50м): paper 0/7, биржа 7/7, 3 LONG на бирже, 15 `SHADOW WOULD_BLOCK` залогировано без блока. Откат: `shadow_mode: false`. Память: [[project_btc_regime_provider_lag]]. → хвосты: DEV-237-OBS (наблюдение), DEV-237-B (вариант B). **🔗 Смежно:** ARCH-124 (аудит режимов — тот же мотив, другой классификатор); ФАЗА 2/arch104 (arch104 — единственный путь на биржу, минующий btc_market_gate: свой observer loop, soft_gates_enabled:[], exchange_enabled:true); DEV-226 (TSL запускается только для live/vst — сделки в paper exch=none TSL не активируют, проверить не отсюда ли часть «TSL не активируется»). | ARCH/DEV |

### ✅ DEV-241: TSL-катастрофы R=-15 на SHORT — ИСПРАВЛЕНО 02.06 (commit 299b1a6)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| [DEV-241](#dev-241) | ✅ | **22 биржевых SHORT-сделки (с 30.05 22:50) закрылись status=TSL с R≤-3 → −174.5R (avgR=-7.93).** Без них SHORT был бы +57R. **КОРЕНЬ НАЙДЕН (grep position_sync.py):** D-049 slippage-фикс (строка 375: `if status == "SL" and _r_calc < -2.0: exit_price = _sl`) **НЕ покрывает TSL** — потому что SL→TSL переклассификация (строка 321-329: `original_sl != stop_loss → status="TSL"`) происходит **ДО** sanity-check. Цепочка: (1) `_resolve_exit` находит filled STOP_MARKET → status="SL", exit_price=mark_price (артефакт: цена ушла за стоп между fill T0 и polling detect T1 +30-60s); (2) строка 329 SL→TSL; (3) sanity `if status == "SL"` НЕ ловит (уже TSL) → artifact mark остаётся → R=-15 (clamp). **Доказательства:** все 22 имеют `tsl_activated=1`, `exit/SL_dist` = 3x-98x (ZRO maxR=+2.25→R=-15 exit/SL=76.8x; A maxR=+2.0→R=-9.2 exit/SL=97.9x). Сделки были В ПЛЮСЕ → TSL должен был защитить → закрылись на -15R = поломка, не торговля. **✅ ФИКС ПРИМЕНЁН 02.06 (commit 299b1a6):** обе sanity-проверки (R>3 и R<-2, position_sync.py:355/375) расширены на `status in ("SL","TSL")`. Для TSL exit_price → `_sl` (текущая TSL-линия, DEV-189 обновляет stop_loss при движении только tighter). **Валидация на 22 сделках (симуляция exit→stop_loss): -174.5R → +12.0R, экономия +186.6R.** 18/22 TSL были в профите (→+1..+2R), 4 near-breakeven. NB: фикс правит R-учёт (метрику стратегии); реальный execution slippage — отдельный слой (emergency watchdog DEV-185.2). Консистентно с D-049 для SL. **⚠️ Требует рестарт** (применится к новым закрытиям; исторические 22 не пересчитываются). | DEV |

### ✅ DEV-237-OBS: ЗАКРЫТ 02.06 — LONG здоров, btc_market_gate→shadow подтверждён

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DEV-237-OBS | ✅ | **Проверено 02.06 (n=101 биржевых LONG с 30.05 22:50): WR LONG=54.5%, avgR=+0.082, +8.3R.** Критерий тревоги (WR<35% при n≥10) НЕ сработал — снятие btc_market_gate блока LONG было правильным. **Оставляем `shadow_mode:true`**, DEV-237-B (флэт-детектор) не срочен. **НО:** проверка вскрыла бОльший лик — SHORT n=181 WR=59% но avgR=-0.647 (-117R) из-за 22 TSL-катастроф → вынесено в **DEV-241**. После `btc_market_gate→shadow` контр-трендовый блок LONG снят. SQL: `SELECT direction,COUNT(*),AVG(R_multiple) FROM simulated_trades WHERE status IN ('TP','SL','TSL','EXPIRED') AND exchange_order_id NOT IN ('SIM') AND created_at>='2026-05-30 22:50' GROUP BY direction`. | ARCH |

### 🔴 DEV-238: расследование wt_signal=0 confirmations (31.05.2026, инициатор Claude из DEV-224)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| [DEV-238](#dev-238) | ✅ | **РАССЛЕДОВАНО 31.05.2026 (Claude, grep + анализ).** **Корень: ConfirmationAggregator пустой потому что только ATR Trend Change Detector публикует в него — все остальные детекторы публикуют ТОЛЬКО в EventBus.** **Доказательства:** (A) `grep on_confirmation` → **только 4 вызова, все в scan_loop:1447-1477** в блоке ATR Trend Change Detector. Публикуются только: `atr_change_{tf}` (trigger), `zone_OS_{tf}`/`zone_OB_{tf}`, `ote_zone`. (B) `grep publish` EventBus → SMC BOS/CHoCH, FVG touch, wt_extreme, zone_enter, liquidity_sweep — **все идут в EventBus, не в ConfirmationAggregator** (scan_loop:1410/1540/1546/1561/1575). (C) Два разных механизма: EventBus = async dispatch для launching Full CALL; ConfirmationAggregator = strength подсчёт через registry. **НЕ синхронизированы.** (D) Мой `_WT_REQUIRED_CONFIRM_SOURCES` в shadow_signal_quality.py содержал ОШИБОЧНЫЕ имена: `smc_bos_15m` (в registry только `smc_bos_1h`), `hidden_div_*` (в registry `div_hidden_bull/bear_15m`), `fvg_touch` (в registry `fvg_fill`), `wt_extreme` (в registry НЕТ). Из 10 имён в моём массиве реально публикуется только `ote_zone` (и то только в ATR change блоке). **Window 600s НЕ релевантна** — источники просто не публикуются. **Выводы:** (1) **Это не баг shadow_signal_quality.py — это блокер DEV-200/DEV-201** (Confirmation-Driven Architecture недореализована). (2) HARD gate `len(confirmations) >= 1` для wt_signal убрал бы 100% потока **по архитектурной причине**, а не по качеству сигнала. (3) **Действия:** (i) DEV-200/DEV-201 — реализовать публикацию SMC/div/pivot/fvg/wt_extreme в ConfirmationAggregator (5-10 строк per детектор, рядом с существующим `event_bus.publish`); (ii) после (i) — обновить `_WT_REQUIRED_CONFIRM_SOURCES` на реальные имена из registry: `smc_choch_1h`, `smc_bos_1h`, `ote_zone`, `pivot_confluence_2plus`, `div_regular_bull_15m`, `div_regular_bear_15m`, `div_hidden_bull_15m`, `div_hidden_bear_15m`, `fvg_fill`; (iii) повторить shadow A/B через 50+ сделок — тогда данные станут осмысленными. | DEV |

### ✅ DEV-233..236 ЗАКРЫТО (30.05): дивергенции+wt_cross исправлены, ретробэктест 3 этапа, golden изолирован

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DEV-233 | ✅ | **RSI-дивергенции → LonesomeTheBlue (close, trendline).** `_pivot_indices(close)` + `_calc_divergence()` пивот-к-пивоту + live-ветка (правый конец=фактич. экстремум, dontconfirm). bull_div/bear_div=regular, rsi_div_*_hidden. Чарт-подтверждение OK (tmp_charts/trx_divergence.png). | DEV |
| DEV-233b | ✅ | **WT-дивергенции → WT_X (фрактал на WT + low/high, БЕЗ trendline).** Отдельный `_wtx_divergences()`: williams-фрактал на самом WT (центр wt[i-2]), цена по low/high, сравнение с пред. WT-фракталом. ≠ RSI-алгоритм (это ДВА разных индикатора, подтвердил ARCH). Совпало с WT_X на TRX (🐂R на 29 13:00). Чарт OK (trx_wtx_div.png). | DEV |
| DEV-234 | ✅ | **wt_cross выровнен на wt1×wt2 в OS/OB.** combinator считал кросс НУЛЯ (с создания), а основной бот (confluence_scanner/mtf_checker/WT_X) — кросс wt1×wt2 в зоне. Фикс: +wt2=SMA4, кросс в зоне OS/OB (пороги -60/60 = config). Частота упала с ~50-80 (кросс нуля) до 4-8/пара (реальный entry). Затрагивало D-051 gate + T8-паттерны. py_compile OK. | DEV |
| DEV-235 | ✅ | **РЕТРОБЭКТЕСТ — ЭТАП 1 закрыт (29.05).** `tools/pattern_mining/retrobacktest_dev235.py`, CSV `tmp_charts/dev235_retrobacktest.csv`. 88 HTF-паттернов пересчитано на исправленном combinator (46 пар × 2.4г). Итог: L1_golden просел +1.89→+0.46, L1_golden_scale_1h +6.07→+0.47 (держались на сломанных div). SHORT (S1-S8) устойчивы ~без изменений. Перевернулось в минус только 4. Осталось сильными 52. **Старые метрики LONG-golden были завышены ложными div.** | DEV |
| DEV-235.2 | ✅ | **РЕТРОБЭКТЕСТ ЭТАП 2 (5m+15m) ГОТОВ.** `retrobacktest_dev235_ltf.py`, CSV dev235_ltf_5m/15m.csv. 5m: 36 пересч, 0 в минус, 31 сильных. 15m: 36 пересч, 0 в минус, 33 сильных. **ВЕРДИКТ (3 этапа): re-mining НЕ нужен.** Рушится только golden (bull_div_1d): L1_golden_LTF_5m 97%→44.7%, _15m 100%→68%. Костяк T2L/D2_S/SHORT — Δ=0.0, реальный edge. | DEV |
| DEV-236 | ✅ | **Изолировано 28 паттернов (enabled:false) — 30.05.** Registry: +поле `enabled`, фильтр в `find_matching` + `htf_gate_open`. YAML: 28 паттернов с div/cross-якорем и деградацией ≥0.5R (golden ×7, T4_L div ×8, T2_L div ×4, T2L_L_L1 ×6, T6_L_02, T7_S_A4_5m_02). 215→187 активных. golden НЕ матчится при полном HTF (проверено). НЕ тронуты 15 паттернов с деградацией БЕЗ div/cross (причина = разница симуляции, не наши фиксы). ✅ Рестарт PID 8340 — подтверждено в проде: decisions 21→6, golden в decisions=0. | DEV |
| ARCH-117 | ✅ | **WT/RSI как ЕДИНЫЕ СФЕРЫ Куба — ВСЕ 3 ФАЗЫ ЗАКРЫТЫ (31.05).** Корень DEV-233/234: WT-формула в 7+ файлах (indicators.py канон, extended_indicators.py ×2, combinator_v1/v2, chart_builder, 4 скрипта), производные (cross/div/zone) считаются КАЖДЫМ потребителем по-своему. Аудит: `memory/arch117_wt_audit.md` (4 разных порога зоны, 3 момента проверки, wt2 EWM≠SMA). **✅ Phase 1:** `core/intelligence/wt_service.py` (WTService) — единый источник: `wt_cross`(сырой, обр.совместимость), `cross_in_zone`(строгий — wt1 был в OS/OB ДО кросса, combinator-стиль), `zone`(±60). scan_loop→`build_wt_snap()`. 17 тестов ✅, в бою healthy. dynamic_thresholds — опция (DEV-23, default ±60). **✅ Phase 2 ГОТОВ (30.05, рефокус):** Параллельная ARCH-118 сессия УЖЕ удалила `extended_indicators.py` (ffd88c8) → wt2 EWM→SMA фикс **moot**. Реальный объём меньше. **✅ (1)** `core/intelligence/rsi_service.py` RSIService — на каноне `compute_rsi` (Wilder RMA) БЕЗ новой формулы: value+zone(70/30)+cross50. 9 тестов ✅. **✅ (2)** `ml_predictor._calculate_rsi` (SMA-дубль) удалён → только канон compute_rsi. **✅ (3)** `chart_builder._calculate_wt` → `indicators.calculate_wt` (убрана 5-я копия WT, cross-маркеры остались). **Остаток (low):** 4 offline-скрипта (analyze_history и др.) — не live, низкий приоритет; RSIService в live-консьюмера не подключён (RSI пока не live-сигнал — combinator RSI-div уже консолидирован DEV-233). WT-div(WT_X) ≠ RSI-div(LonesomeTheBlue). **✅ Phase 3 ЗАКРЫТ (31.05) — combinator ЗАМОРОЖЕН как эталон.** Shadow-сравнил combinator vs core/ на 40 парах (`e:/tmp/ph3_shadow_compare.py`) + радиус 187 паттернов (`ph3_blast_radius.py`): **WT ИДЕНТИЧЕН** (diff=0.000000, 115 паттернов — сферы уже = combinator), **RSI РАСХОДИТСЯ** (SMA-rolling vs Wilder, медиана 7.8пт, 50 паттернов), **trend РАСХОДИТСЯ** (EWM-ATR+свой supertrend vs Wilder-RMA+Pine, 85% совпадение, 108 паттернов). **РЕШЕНИЕ (рой 5/5 + sambanova «стабильность>правильность»):** combinator = ЗАМОРОЖЕН эталон паттернов/бэктеста/snapshot/ML (RSI-SMA + trend-EWM — нестандарт, но 187 паттернов на нём, топовые T2_S_* avgR~1.2 WR~80%). Сферы (RSIService Wilder, calculate_trend Pine) = live-сигналы, ДРУГАЯ формула НАМЕРЕННО, задокументировано. Switch на «стандарт» = пересчёт DEV-235-масштаба (58%/27% паттернов) — НЕ оправдано. Инвариант релаксирован: WT общий, RSI/trend раздельны. **НЕ путать combinator-RSI(SMA) ≠ RSIService(Wilder).** ML-мина развязана: snapshot из combinator самосогласован (train=stored). Вердикт: `memory/arch117_wt_audit.md` ph3-блок. Рой: `obsidian/Team-Discussions/2026-05-31-arch-117-ph3-*`. **ARCH-117 ВЕСЬ ЗАКРЫТ.** | ARCH/DEV |
| ARCH-118 | ✅ | **Единый снимок features_json — ЗАВЕРШЁН (31.05, вариант B, коммиты b1fe5d8→97918ce).** Корень самоподтверждения golden устранён: снимок = `combinator.compute_flags` ОДНИМ кодом live+backtest. **Шаги:** (1) `core/intelligence/feature_snapshot.py` snapshot_features+декодер; (2) live shadow в register_trade_async; (3) сверка parity → 2 источника расхождения (только HTF); (4) **PARITY ДОСТИГНУТ** (рой 7/7: канон independent-last `snapshot_features_at` + `HTFHistoryCache` ≥4320 баров → 0 расхождений на 10 парах, было 100); (5a) свёртка pivot (рой 6/7 вариант B: 3 числовых `pivot_nearest/dist_pct/relation` ПАРАЛЛЕЛЬНО булевым, один калькулятор, 187 паттернов целы); (5b) таблица `trade_features`(FK) + индекс + `_write_trade_features`, config `arch118.write_table`. **Инвариант «один калькулятор»** зафиксирован высшим уровнем (ENCYCLOPEDIA). Подтверждён в проде (id 16075/16096/16104). `scripts/arch118_parity_check.py`. **Требует рестарт** (write_table активация). Долг (ARCH-117 ph3): вынести compute_flags в core/ без import-side-effects. | ARCH |

### 🟡 ФАЗА 2 — разбор arch104 паттернов (путь к +): 111 сделок, 46% SL, держится на 2-3 паттернах** *(🔗 смежно DEV-237: arch104 минует ВСЕ режимные гейты monitoring — свой observer loop, soft_gates_enabled:[], exchange_enabled:true → его сделки не защищены btc_market_gate, учесть при анализе SL)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DEV-232 | ✅ | **HTF-gate + кэш HTF для 5m-фетча ARCH-104 (29.05):** observer фетчил 5m для всех 242 пар → цикл 1020-3168с. Реализовано: `registry.htf_gate_open()` + перестроен `_scan_one_pair` (HTF first → gate → 5m только если все HTF-anchors паттерна активны) + кэш HTF-флагов per-symbol (TTL 1800с). 15m не тронут (cache-hit от scan). Тест gate на реальных флагах OK (golden/short→open, empty/partial→closed). 0/72 паттернов без HTF-anchor. Лог `[DEV-232 gate: ltf_fetched=N htf_only=M]`. py_compile OK, **нужен рестарт** | DEV |

### 🔴 DEV-230: деградация всего потока данных = перегрузка event loop от WS — [DISCUSSION.md](DISCUSSION.md)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DEV-230 | ✅ | **WS kill-switch применён (30.05 commit `7433f33`):** `config.yaml performance.ws_enabled: false`. Подтверждено: scan 76-96s → **8s**, health DEGRADED→HEALTHY. WsFeed не запускается, поток на REST. Изначально: 5 ccxt.pro WS на одном event loop забивали loop (`SLOW await 64-92s`, 339×DEGRADED 0×recover). | DEV/ARCH |

### 🔴 DEV-226: TSL не активируется при R>1 (два корня) — разбор в [DISCUSSION.md](DISCUSSION.md)** *(🔗 смежно DEV-237: TSL tracker стартует только для live/vst позиций — сделки в paper exch=none его НЕ активируют; проверить, не попадала ли часть «не активируется» на paper-сделки до shadow-фикса)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DEV-226 | ✅ | **Слой 1 — pre-filter мёртвая зона:** WS pre-filter в `trade_simulator.py` делал `continue` для сделок с `tsl_activated=0` в профите но далеко от SL/TP. Фикс: early-profit check (`R≥0.3` по `_ws_price`). py_compile OK, нужен рестарт | DEV |
| DEV-226.2 | ✅ | **Слой 2 (вариант 1) — cross-source R:** `current_r` считался по stale 15m OHLCV-кэшу (UNI: +0.41R при реальных +2.15R). Фикс: корректируем R вверх по `_ws_price` (get_current_price: WS ticker/1m кэш). py_compile OK, нужен рестарт | DEV |
| DEV-226.3 | ✅ | **Слой 2 (вариант 2) — stale-guard + REST bypass:** `fetch_ohlcv(force_refresh=True)` обходит LRU+circuit breaker. В `trade_simulator` детект протухшего бара (возраст > 2×TF или None) → force REST для активных OPEN. Причина: вариант 1 (cross-source) не помог — весь WS-слой мёртв для UNI/BERA/ICNT (`_ws_price` тоже stale). py_compile OK, нужен рестарт | DEV |

### 🚀 СПРИНТ «CONFIRMATION-DRIVEN ARCHITECTURE» (09.05–23.05.2026)** — на основе R6/R7/R8: ATR Trend change cascade подтверждён, ЗАКОН confluence

| ID | Ст | Описание | Роль |
|---|---|---|---|
| [DEV-199](#dev-199) | ✅ | **ATR Trend Change events (17.05 закрыт):** `core/signals/atr_change_detector.py` + EventBus publisher `atr_change_15m/1h/4h` в `scan_loop.py`. Подключён в bot.py. НЕ публикует `atr_change_1d` | DEV |
| **DEV-200.2** | ✅ | **Phase 2: РАСШИРИТЬ агрегатор 26→~70 источников — ГОТОВ (07.06, DS).** Мост combinator-флагов → EventBus + агрегатор: `_COMBINATOR_BASE_WEIGHTS` (63 базы, 252 TF-записей в registry), `_publish_combinator_confirmations()` в scan_loop (1h, edge-detection, исключены Claude-домены fvg/bos/choch/eql/eqh). Smoke OK, граница Claude=0 пересечений. Требует рестарт бота. Файлы: `core/confirmations/registry.py` + `bot/loops/scan_loop.py`. | DS |
| [DEV-203](#dev-203) | ✅ | **DecisionTrace в gates (17.05 закрыт):** `core/observability/decision_trace.py` + таблица `signal_drops` (23515 записей) + `/api/dropped` дашборд. Top drop: dedup 64%, below_min_strength 17%, validate_inputs 1%. Работает. | DEV |
| [DEV-209](#dev-209) | ✅ | **ATR 15m + OTE zone trigger (17.05 закрыт):** `scan_loop.py:1370-1446` OTE zone trigger с `price_in_ote` + auto confirmation `ote_zone` (w=7) + per-source window 1800с для 15m. Acceptance: ≥20 сделок за 7 дней | DEV |
| [ARCH-112](#arch-112) | ✅ | Архитектурный аудит 11.05: 25 confirmations соответствуют Кубу, 6/13 сфер активны, 3 edge cases задокументированы, 3 GAP (S5/S6/S9) → бэклог ARCH-112-EXT | ARCH |

### 🚀 СПРИНТ «РЕАЛЬНЫЕ УБИЙЦЫ» (25.04–02.05.2026)** — после D1+RE-AUDIT: фикс не D1-багов, а реальных источников −780R/10дн

| ID | Ст | Описание | Роль |
|---|---|---|---|
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

### DASHBOARD

| ID | Ст | Описание | Роль |
|---|---|---|---|
| [DEV-144](#dev-144) | ✅ | **Полный редизайн дашборда (25.05 закрыт)** — план 24.05 от team_ask 3/3 LLM. **6 stages × 1 неделя** = Vue 3 + Vite миграция + Pattern Heatmap (215×режимов) + Command Palette (Cmd+K) + "Why did bot do X?" Decision Trace timeline + Drag-and-drop (опц.). **Полное описание + wireframe + миграция поэтапно + библиотеки:** [`obsidian/Architecture/DEV-144-Dashboard-Redesign-Plan.md`](obsidian/Architecture/DEV-144-Dashboard-Redesign-Plan.md). Quick Wins (Critical Alerts / Collapsible / Drops card) — закрыты в D-067 24.05. **Stage 1 (25.05):** ✅ Vite + Vue 3 + Pinia + Vue Router setup в [`web/dashboard/`](web/dashboard/), App.vue с sidebar/topbar, перенос палитры в `src/assets/main.css` через CSS-переменные, 5 страниц-заглушек. **Stage 2 (25.05 — ✅ 5/5):** Все компоненты делегированы в cerebras gpt-oss-120b (~5500 output tokens суммарно). [`CriticalAlerts.vue`](web/dashboard/src/components/CriticalAlerts.vue) (D-067 QW1 правила), [`HeroGrid.vue`](web/dashboard/src/components/HeroGrid.vue) (4 карточки BingX Equity / Risk / Позиции-WR / Drops c свой fetch /api/dropped 60s), [`EquityCurve.vue`](web/dashboard/src/components/EquityCurve.vue) (самописный SVG cumulative R curve, area+line, корнер-лейблы), [`StrategyMetrics.vue`](web/dashboard/src/components/StrategyMetrics.vue) (4 KPI: EV/PF/AvgR-WL/Open P&L), [`ATRChange.vue`](web/dashboard/src/components/ATRChange.vue) (3 карточки 1h/4h/15m из /api/atr_stats). **Stage 3 (25.05 — ✅):** [`composables/useSSE.js`](web/dashboard/src/composables/useSSE.js) (EventSource обёртка с auto-reconnect и exponential backoff 1s→30s), [`stores/dashboardStore.js`](web/dashboard/src/stores/dashboardStore.js) (Pinia: SSE `/api/events?dashboard=1` для stats/equity/confluence/breakeven/analytics/signal_weights + lightweight polling `/api/dashboard` 10s для scan_health), [`stores/liveStore.js`](web/dashboard/src/stores/liveStore.js) (polling `/api/live` 5s — SSE не покрывает баланс биржи). **Critical fix:** `/api/summary` endpoint не существует — Stage 2 компоненты получали 404. Stage 3 переключил на `/api/stats` через SSE. **Stage 4 (25.05 — ✅):** [`OpenPositionsTable.vue`](web/dashboard/src/components/OpenPositionsTable.vue) (15 sortable колонок, символ/направление/SL/TP/Δ%/R/MFE/strength/конф/режим/время) и [`ClosedTradesTable.vue`](web/dashboard/src/components/ClosedTradesTable.vue) (16 sortable колонок + status-badge + длительность h/m + пагинация панель с per-page select 25/50/100/200), [`stores/closedTradesStore.js`](web/dashboard/src/stores/closedTradesStore.js) (Pinia + `/api/closed_trades?page&per_page`). Open trades тянутся через `dashboardStore.stats.open_trades` (SSE). **Stage 5 (25.05 — ✅):** Backend [`_handle_patterns`](web/dashboard_server.py) (новый endpoint `/api/patterns` парсит `config/arch104_patterns.yaml` → 215 production patterns). Frontend [`Patterns.vue`](web/dashboard/src/pages/Patterns.vue) и [`DecisionTimeline.vue`](web/dashboard/src/pages/DecisionTimeline.vue) (route `/trades/:id?`). **Stage 6 (25.05 — ✅):** [`CommandPalette.vue`](web/dashboard/src/components/CommandPalette.vue) (Cmd+K/Ctrl+K глобальный с preventDefault — иначе Chrome ловит в адресной строке; источники — 7 страниц + open_trades + 215 patterns; ↑↓ навигация + Enter + Esc), [`composables/useDensity.js`](web/dashboard/src/composables/useDensity.js) (Compact/Comfort toggle через CSS-каскад `.density-compact` в main.css + localStorage persistence) с кнопкой в topbar, [`Sparkline.vue`](web/dashboard/src/components/Sparkline.vue) (мини-SVG line+area+zero-dash+last-dot для будущей интеграции в таблицы). **Финальный production build: 3.26s, 49 модулей, 0 ошибок, bundle 57 KB gzipped — в плановом бюджете 80-120 KB. DEV-144 закрыта.** 7 страниц / 5 компонентов / 3 store / 2 composable / 8 routes. | DEV |
| D-067 | ✅ | **Dashboard Quick Wins (24.05):** (QW1) **Critical Alerts** баннеры при `exchange_health=DOWN` / `scan_health=DEAD` / `monitored_pairs=0` / `latency>3000ms` — diagnostic-first design. (QW2) **Collapsible sections** через `<details>/<summary>` для 10 вторичных таблиц (by_strategy, by_signal_type, by_direction, by_regime, by_session, confluence breakdown, BE statistics ×2, адаптивные веса, симуляция депозита) — scroll fatigue устранён. (QW3) **Drops summary card** — 4-я hero-карточка с топ-3 gates за последний час (`/api/dropped?hours=1&limit=3`). Все 3 QW на vanilla JS, без миграции стека. | DEV |

### СТРАТЕГИЯ / СИГНАЛЫ

| ID | Ст | Описание | Роль |
|---|---|---|---|
| [ARCH-84](#arch-84) | ✅ | MTF gate shadow → production (16.05): `verdict_gate.enabled: true` в config.yaml. EXHAUSTION gate блокирует OB_bias+LONG (WR=6.2%). Данные WOULD_BLOCK собраны | ARCH/DEV |
| [DEV-172](#dev-172) | ✅ | **Entry Priority Matrix (17.05 закрыт):** `core/intelligence/entry_matrix.py` + `evaluate_entry_priority()` в `trade_simulator.py:870-881`, пишет `entry_priority` P1/P2/P3 в features_json | DEV |
| [DEV-88](#dev-88) | ✅ | **OTE C1 покрыт ARCH-104 (21.05):** `S8_ote_strong` в arch104_patterns.yaml (n=164, avgR=+1.339, WR=90.2%) — superset C1. Данные собраны VST observer. | DEV |
| [DEV-89](#dev-89) | ✅ | **OTE shadow покрыт ARCH-104 (21.05):** Stage 1 VST observer на 241 паре (вкл. S8_ote) = superset 20-пар shadow. | DEV |

### RISK INTELLIGENCE (Сфера 3 Куба) — обсуждение 19.04

| ID | Ст | Описание | Роль |
|---|---|---|---|
| DEV-180 | ✅ | **Risk Intelligence v1 shadow (17.05 закрыт):** `core/intelligence/risk_intelligence.py` — RiskIntelligenceV1, shadow mode, логирует решения без применения | DEV |
| DEV-181 | ✅ | **Leverage formula реализована в ARCH-104 (21.05):** `risk_intelligence.py:171-174` — `leverage = ceil(risk_pct / sl_distance_pct × safety_buffer)`. Shadow only → активация в Stage 3 ARCH-104. | DEV |
| DEV-182 | ✅ | **Risk ML покрыт ARCH-104 Stage 3 (21.05):** `decision_fusion.py` принимает `V2MLPrediction` (p_win, predicted_mfe_r). LightGBM Phase 1.5 задокументирован. Реализуется в рамках Stage 3 ARCH-104. | DEV |

### 🆕 НОВЫЕ СФЕРЫ + SUB-КУБЫ (29.05.2026)** — архитектурный анализ WaveService + карта кандидатов. Полный разбор: [DISCUSSION.md → 29.05.2026 ARCH-115/116]

| ID | Ст | Описание | Роль |
|---|---|---|---|
| [ARCH-116](#arch-116) | ✅ | **Карта Sub-кубов Куба Метатрона (29.05.2026 закрыта):** Задокументированы 3 Sub-куба. **(A) SMC Sub-куб** (ARCH-120) — OBSphere+FVGSphere+StructSphere+LiqSphere → SMCContext+SMCVerdict. **(B) Elliott-Pivot Sub-куб** (ARCH-121/118/119) — WaveService+PivotSphere+FibSphere → PricePositionContext. **(C) WT Sub-куб** (Этап 21 vision). Создан `docs/CUBE_SUBCUBES.md`. | ARCH |
| [ARCH-55-VAL](#arch-55-val) | ✅ | RANGE BOUNCE валидация завершена (16.05): `range_bounce: enabled: true`. Закрыто | ARCH/DEV |

### ——— Старые ✅ спринты → [TASKS-ARCHIVE.md](TASKS-ARCHIVE.md) ———

| ID | Ст | Описание | Роль |
|---|---|---|---|
| [DEV-222](#dev-222) | ✅ | **arch104 исключён из blocked_regimes HIGH_VOL (27.05 коммит 07663bd):** `trading.blocked_regimes_exceptions: [arch104]` в config + Guard 1 в trade_simulator. Было: 19 drops/6h. Контекст: блок 24.04 был ДО BE engine; с BE@0.5R HIGH_VOL = +0.351R. | DEV |

### 🆕 ARCH-104 ВОРОНКА (27.05.2026 расследование)** — 88/7д vs 591 confluence (×6.7 меньше). 31/215 паттернов задействовано (14%). Главный душитель — D-051 wt_cross hard gate (26.05): поток упал с 20/день до 1-3/день. T5_L_02 avgR=+6.41 — артефакт SWARMS+AIN pump-кластера (без них −0.71R). RI v1 не режет (99% apply). 90% потерь между risk_decisions_log и register_trade

| ID | Ст | Описание | Роль |
|---|---|---|---|
| D-073 | ✅ | **D-051 observability (27.05 коммит f7356ac):** `await record_drop(gate_name='arch104_d051_no_wt_cross')` в [arch104_observer_loop.py:414-428](bot/loops/arch104_observer_loop.py#L414-L428). Был silent return → теперь signal_drops с pattern_id/det_tf/required_flag/anchor_factors. Через 3 дня — точный счётчик D-051 отказов. Acceptance: `SELECT gate_name='arch104_d051_no_wt_cross', COUNT(*), COUNT(DISTINCT symbol)` показывает данные | DEV |
| D-073-FOLLOWUP | ✅ | **ARCH-104 action plan — ЗАКРЫТ 29.05.2026 (deadline 31.05 выполнен досрочно):** (1) ✅ **БОТ ПЕРЕЗАПУЩЕН 27.05 19:27 UTC** — D-073 patch активен, первые 2.5h дали 20 записей `arch104_d051_no_wt_cross`, per-pattern L2_wt_double_fvg=7, T2L_L_L2_15m_05=4, T2_L_10=4, T7_S_A3_15m_01=4; per-TF 1h=11 / 15m=9; per-dir LONG=16 / SHORT=4. (2) **31.05.2026** (через 3 дня) — `SELECT gate_name, COUNT(*) cnt, COUNT(DISTINCT symbol) syms, json_extract(features_json,'$.pattern_id') pid, json_extract(features_json,'$.detection_tf') tf FROM signal_drops WHERE gate_name='arch104_d051_no_wt_cross' AND dropped_at>='2026-05-27 19:27' GROUP BY pid, tf ORDER BY cnt DESC`. По данным принять решение D-074. Предварительная гипотеза по first-2.5h данным: TF-зависимый soft (1h hard / 15m −15 penalty) — оправдан, т.к. 15m/1h почти 50/50. (3) **Trigger D-076 → 🔴:** если `simulated_trades WHERE source_router='arch104' AND created_at>='2026-05-27 19:27' GROUP BY symbol HAVING COUNT(*)>=3 AND (MAX(julianday(created_at))-MIN(julianday(created_at)))*24 < 6` вернёт ≥1 строки (повтор SWARMS-style кластера) — поднять D-076 в HIGH и реализовать single-position guard немедленно | DEV |

### 🆕 SL/TP INTELLIGENCE (25.05.2026)** — рой 4/6 моделей (контекст 83K). Исследование: 156K уровней, 20 пар, 2.4 года. FVG <0.3R = 73-86% reach. Gravity α=1.5 → top10%=83%. Pyramiding lift +14-21%. БД: 42% SL имели max_R>0.5R. Прогноз: WR 25%→70-85%, expectancy −0.44R→+0.75R

| ID | Ст | Описание | Роль |
|---|---|---|---|
| [ARCH-113](#arch-113) | ✅ | **TPSelector — Intelligent TP Gravity Engine** (исследование 25.05.2026, 7 скриптов). **Phase 1 (~2-3д):** `core/smc/tp_selector.py` — кластеризация FVG(decay)+PDH+psycho+pivot ±0.5%, `score=gravity/dist^1.5` (α=1.5 доказан данными), возвращает TP1 (LTF dist<0.5R) + TP2 (HTF dist 1-3R). Plugin-layer в `recommendation_generator.py` через `apply_tp_selector()` + флаг `sl_tp_engine.tp_selector_enabled: false` в config. **Phase 2 (~1-2д):** SLSelector — добавить OB edge + CHoCH/BOS confirmation + параметрический буфер. **Phase 3 (~1-2д):** Pyramiding signal PYRAMID_ADD при TP1 hit → monitoring.py trigger к TP2 (lift +20.9% при HTF/LTF ratio 1.5-2.5x). MVP источников: FVG(young 0-3 bars)+PDH+psycho (консенсус 5/5 роя). A/B по стратегиям+парам. Team-discuss: `obsidian/Team-Discussions/2026-05-25-arch-113-tpselector-plan-реализации-intelligent-sl.md`. Исследование: [[obsidian/Research/ARCH-113-TPSelector-Research-2026-05-25.md]] | ARCH/DEV |

### 🚀 СПРИНТ «ARCH-104/105 LIVE» (22.05.2026)** — pipeline жив, ARCH-105 hidden div в проде

| ID | Ст | Описание | Роль |
|---|---|---|---|
| D-049 | ✅ | **SL exit_price slippage fix (23.05 commit 80f5c26):** при status='SL' и R<-2.0 заменяем `exit_price = SL_price` вместо artifact mark_price. Корень: position_sync берёт current mark при не-нахождении filled order. HANA T4_S_09: 3 SL все по exit=0.03829 → R=-7.58 (вместо -1). Backlog D-049.2 — правильный fetch_order(exchange_order_id) | DEV |
| D-055 | ✅ | **Noise mute (26.05.2026): min_strength 50→80 для pivot_reversal/wt_signal/confluence** в `config.yaml` source_policies. Данные: pivot_reversal avg=-0.22R WR=29%, wt_signal avg=-0.48R WR=32%, confluence avg=-0.58R WR=31% (n=8163 post-15.04). Без рестарта кода — только конфиг. | DEV |
| D-056 | ✅ | **BE engine активирован (26.05.2026): `use_breakeven: true`, `breakeven_activation_r: 0.5`** в `config.yaml`. Код уже был (DEV-40), только `false` → `true`. A/B sim: BE@0.5R+TP2.0R = +0.32..+0.47R на всех режимах vs current -0.14..−0.25R. SL переносится в entry после +0.5R (54.4% сделок достигают этого уровня). | DEV |
| D-053 | ✅ | **CRITICAL fix (26.05 commit d002668): WsFeed cascade crash → auto-restart.** 3-part fix: (1) WsFeed.reset() + restart-loop в _start_ws_feed (30s cooldown, бесконечно); (2) monitor_market outer restart-loop (10s cooldown) вместо fatal Exception exit; (3) gather(return_exceptions=True) в scan_all_pairs. До: WsFeed crash = 4.5h downtime. После: auto-recover < 30s. | DEV |
| D-054 | ✅ | **API throttling — бот перегружает minor pairs:** 109,183 случая slow OHLCV >10s за 3 дня. Топ-10: SHIB, ZK, CC, WHITEWHALE, BARD, NIGHT, BEAT, BLUAI, WIF, FARTCOIN — все minor liquidity. Корень: `scan_semaphore_size=20` × 237 пар × 4 TF = 948 OHLCV calls per scan burst → BingX throttle → cascade на D-053. **Fix:** (1) semaphore 20→12, (2) stagger fetch 4 TF в scan_one (не параллельно), (3) min_volume_usd 5M→20M (отсечёт половину slow pairs), (4) per-pair tier prioritization (major sync, minor async lazy) | DEV |
| D-051 | ✅ | **Runtime per-TF trigger gate:** `wt_cross_{dir}_{det_tf}` gate в `_try_register_vst_trade`. Retest 26.05: без wt_cross_up_1h якорь → WR=37% (шум), 1h cross критичен. Gate применяется только к паттернам БЕЗ wt_cross_*_1h в anchor_factors (T8 освобождены). Коммит 3348afa | DEV |

### 🚀 СПРИНТ «API LOAD REDUCTION» (24.05.2026)** — quick fix после BingX TEMP BAN 100410 (190 ошибок/час). Перед возвратом к Real Killers.

| ID | Ст | Описание | Роль |
|---|---|---|---|
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

### 🚀 СПРИНТ «OBSIDIAN AUTOMATION» (23.05.2026)** — реализовано в одну сессию

| ID | Ст | Описание | Роль |
|---|---|---|---|
| ARCH-OBS-01 | ✅ | **`tools/obsidian_status_sync.py`** — frontmatter sync TASKS.md ↔ Tasks/*.md. `.git/hooks/post-commit`. 23 файла обновлено | DEV |
| ARCH-OBS-02 | ✅ | **`tools/vault_health.py`** → `obsidian/Meta/HEALTH.md` — orphans 65%, broken 17%, untagged 2.1%. Daily в obsidian_loop | DEV |
| ARCH-OBS-03 | ✅ | **`tools/obsidian_autolink.py`** — wikilinks по ID. `.git/hooks/post-merge`. 164 known IDs, 2779 потенциальных links | DEV |
| ARCH-OBS-04 | ✅ | **`tools/obsidian_weekly_digest.py`** → `obsidian/Index/WEEKLY-*.md`. Weekly в obsidian_loop (воскресенье) | DEV |
| ARCH-OBS-05 | ✅ | **`tools/obsidian_dedup_discussions.py`** — LLM semantic dedup (Groq→Gemini). → `obsidian/Meta/DEDUP-REPORT.md` | DEV |
| ARCH-OBS-06 | ✅ | **`tools/obsidian_archive.py`** — файлы >90 дней без ссылок → `_archive/`. Weekly в obsidian_loop (воскресенье) | DEV |

---

## 📦 Снимок деталей TASKS до сжатия 15.06.2026 (LISTENER/BUS/NOTIF/PERF — полные карточки, метрики+коммиты)

> Сжато в TASKS.md до компактного индекса (правило ≤80 символов). Полные детали и коммит-хэши сохранены здесь.
## 🎧 LISTENER-CANON (14.06.2026) — канонизация механизма слушателей (Слой 2-5 роадмапа)

> **Принцип (юзер):** scan_loop = оркестратор, ВСЁ остальное = подписчики ОДНОЙ шины (`PairContextBus.subscribe`). Рост = добавить слушателя, не трогая ядро. Не плодить запросы — слушать информативную шину. `docs/BUS_SUBSCRIBER_ROADMAP.md` Слой 2-5.

| ID | Задача | Статус | Файлы |
|---|---|---|---|
| **LISTENER-CANON** | ✅ **Шаг 1 ГОТОВ (5d9cb97).** `PairContextBus.subscribe_async` (sync→create_task, изоляция ошибок) + `NotificationDispatcher` переведён с прямого вызова на подписку `SMC_SNAP_UPDATED` → 0 строк notif в scan_loop. snap самодостаточен (`compute_and_publish(current_price=)`). Бот PID 13576: «dispatcher подписан на шину» ✅, тест 3/3. `SubscriberHub` — на 2-м подписчике (Dashboard). | ✅ Шаг 1 done | `core/context/pair_context.py`, `core/smc/sub_cube.py`, `bot/core/bot.py`, `bot/loops/scan_loop.py` |

| **LISTENER-DASH** | ✅ **Шаг 1 ГОТОВ (fdf750d).** SSE-метрики event-driven: `_metrics_version++` при закрытии сделки (auto/ручное/repair) → тяжёлый payload (summary/analytics/equity по 24K+) пересчитывается ТОЛЬКО при сдвиге версии или fallback 60с, не вслепую каждые 5с × N клиентов. per-client `_seen_version`. **Шаг 2 (бэклог):** лента FVG/OB через подписку `SMC_SNAP_UPDATED` → push (новый UI-виджет). | ✅ Шаг 1 done | `web/dashboard_server.py` (`_handle_sse`) |

| **LISTENER-STRAT** | **Слой 4:** Strategy-as-Subscriber — ote_nested/arch104/atr_change из scan_loop → отдельные подписчики шины. Большой рефактор, после стабилизации Слоя 2. | 🔵 бэклог | scan_loop, observer-loops |

---

## 🏛️ BUS-ACCOUNT-EPIC (14.06.2026) — account/portfolio-измерение шины (L1→L2→L3)

| ID | Задача | Статус | Файлы |
|---|---|---|---|
| **BUS-ACCOUNT-EPIC** | **Спроектирован (рой 2 раунда + DS).** Расширить `PairContextBus` account/trader-измерениями (НЕ отдельный PortfolioBus). L1 PairState (есть) → L2 AccountState (equity/margin/drawdown) → L3 TraderState (дирижёр стратегий). Producer EXEC-WS push + REST fallback; доступ синглтон `get_bus()`. Детали+консенсус: DISCUSSION [14.06 🏛️]. | 🔵 эпик/бэклог | `core/context/pair_context.py`, `core/exchange/position_sync.py`, `docs/BUS_SUBSCRIBER_ROADMAP.md` |

| **BUS-L2-BRICK** | ✅ **ГОТОВО (6e0d616).** `AccountState` в `PairContextBus` (equity/маржа, L2-измерение) + `update_account`/`total_equity`. EXEC-WS `ACCOUNT_UPDATE` (wb) → `bus.update_account` (push). `trading/status` читает `total_equity()` из шины + fallback БД (cold start). Баланс ЖИВОЙ (push, не REST/10-мин polling), 0 cross-loop. Корень "баланс слушает шину" (юзер). Smoke 3/3. **NEXT:** position_sizer тоже читать из шины (deposit живой); на L2 → Risk Monitor/Circuit Breaker. | ✅ done | `core/context/pair_context.py`, `core/exchange/exec_ws_integration.py`, `web/dashboard_server.py` |

| **BUS-L3-ORDER** | **⚠️ Порядок L3 (спор с роем):** рой → Capital Allocator вторым. Даат держит → **Correlation Shield РАНЬШЕ** (не зависит от Sharpe; Capital Allocator аллоцирует по Sharpe = частично фейк-R → усиление ошибки). Capital Allocator ТОЛЬКО после DATA-AUDIT-2. | 🔵 после DATA-AUDIT-2 | — |

---

## 🟡 NOTIF-ENGINE (14.06.2026) — Notification Engine MVP (вердикт роя 7/7)

| ID | Задача | Статус | Файлы |
|---|---|---|---|
| **NOTIF-MVP** | ✅ **ГОТОВО (fbda2c8, Даат 14.06)** | ✅ done | |
| | `NotificationDispatcher` + `FvgDetectedListener` + `FvgTouchListener`. scan_loop = 1 строка `dispatcher.on_smc_snap`. `_norm_symbol` (ccxt↔YAML). Open/Closed: новый тип = новый listener, loop не трогаем. | | `core/notifications/dispatcher.py`, `core/notifications/evaluate.py` |

| **NOTIF-TIER2** | TIER-2 уведомления: CHoCH new / OTE zone / OB touch / Pivot breach. Точки вставки в scan_loop. Включать по одному после проверки FVG. | 🔵 бэклог | `config/notifications.yaml` (enabled:false → true), `bot/loops/scan_loop.py` |

| **NOTIF-DASH** | Дашборд: UI-переключение правил. Рой: после YAML-MVP стабилен. | 🔵 бэклог | — |

---

## 🔴 PERF-LOOP-DRIFT (13.06.2026) — event-loop конкуренция → DRIFT 118 (zombie/orphan)

| ID | Задача | Статус | Детали |
|---|---|---|---|
| **CONFIG-SLTP-BUG** 🔴🔴 #1 | **Секция `sl_tp_engine` (config.yaml 293-363, 26 ключей) НЕ читается ботом — код читает `trading.X` → DEFAULTS.** `config.get('trading.use_tsl')`=None, значение в sl_tp_engine. Игнорируются: use_tsl, tsl_activation_r_per_strategy (ote TSL=1.0 default, НЕ 4.0!), cascade_tsl, use_breakeven, breakeven_activation_r, max_positions_per_direction, min_sl_dist_pct, dual_tp, tp_selector_*. **Вся TSL-сага 14.06 была на неверном config (ote TSL 1.0, не 4.0).** ФИКС: влить sl_tp_engine в trading ИЛИ код→sl_tp_engine.X. ⚠️ НЕ наспех — разом включит 26 параметров (defaults→config), резкая смена exit-логики. Аккуратно: подтвердить trading.X везде → перенести → проверить применение → наблюдать. Бот на defaults стабилен. Детали: memory bug_sl_tp_engine_section_ignored. | 🔴 #1 ARCH (утром, осторожно) | `config.yaml` (293-363), `trade_simulator.py`, `trade_tracker.py`, `gates/`, `correlation_guard.py` |
| **TSL-CLEAN-TEST** → DS | ✅ **ЗАКРЫТ (ff3b029, Даат 14.06).** Парный бэктест DS: TSL нейтрален, WR×2. gear1_be_atr 1.0→1.5 для ote_nested применён (TSLProfile.gear1_be_atr=1.5 в tsl_engine.py). DS-321 гибрид работает. | ✅ done | `core/trading/tsl_engine.py` (gear1_be_atr=1.5) |
| **DEV-226-Ph2** → DS | ✅ **ЗАМЕР НА ЧИСТЫХ SL ГОТОВ (DS 13.06).** CLEAN VST: pull n=108 avgR=+1.94 WR=37% vs cont n=382 avgR=+1.47 WR=25%. Pull edge +0.47R ПОДТВЕРЖДЁН. n_down из shadow: всего 34 сделки, замер невозможен (данные копятся с 11.06). TSL на чистых SL: ВРЕДИТ (+0.32 vs +1.66 без). **Ждать n≥30 для pull×n_down.** | ⏳ ждёт n≥30 | `verdict_aggregator.py`, `simulated_trades` |
| **ATR-OTE-E3** → DS | ✅ **БЭКТЕСТ ГОТОВ (DS 13.06). WR89% — ФЕЙК (n=9).** 36K сигналов, 20 пар: A (текущий) avgR=+0.059, B (mid-OTE) +0.068. OTE покрытие 7%. PAIRED (n=2'442): A +0.095 vs B +0.068 → A ЛУЧШЕ. Полная OTE-конверсия НЕ улучшает. DEV-209 (текущий) = оптимум. Скрипт: `scripts/atr_ote_e3_backtest.py`. | 🟢 done → Э3 не нужен | `scripts/atr_ote_e3_backtest.py` |
| **OTE-RBUG** → DS | ✅ **АУДИТ ГОТОВ (DS 13.06).** Edge РЕАЛЬНЫЙ. SL<0.3%: n=557, sumR=+1'073 (VST +3.38 SIM +0.11). SL>=0.5% (чистый): n=2'017, avgR=+2.38, WR=58.1%, sumR=+4'808. VST чистый: +3.47 avgR, +4'152R. Инвертный SL: 1'982 сделок (72%), median=0.85% от entry — не «SL на другой стороне», а SL вплотную к entry. **Баланс не растёт НЕ из-за фейк-R, а из-за position sizing:** SL=0.1% → size=1000× → 1 убыток съедает 10 прибыльных. **Нужен min SL distance ≥0.5%.** **РОЙ 7/7 СОШЁЛСЯ независимо:** (1) min risk_distance guard 0.5-1%/ATR для R И position_size; (2) биржевой closed PnL (fills)=source of truth; (3) hard cap notional; (4) валидация стороны SL REJECT. Edge реальный (+4808R чистый) — guard НЕ убьёт раннеры. **ФИКС ч.1 СДЕЛАН (5e2fd0f, Даат):** min_sl_dist 0.3→0.5 + валидация стороны SL (LONG sl>=entry/SHORT sl<=entry→DROP) в обоих путях (gate + register_trade_async). Тест 5/5. **Backlog ч.2 (рой #2/#3):** биржевой closed PnL=source of truth, hard cap notional. | 🟢 ч.1 done 5e2fd0f / ч.2 backlog | `core/trading/gates/min_sl_dist.py`, `core/trading/trade_simulator.py`, `config.yaml` |
| **PERF-LOOP-B-TEST** → DS | ✅ DS unit-тест 4/4 (прототип) + Даат перенёс в боевой `GlobalRateLimiter`, cross-loop тест на боевом коде 3/3 (10.1 rps shared, ban cross-loop, single-loop parity). EXEC-WS listenKey вне IP-бюджета (DS нашёл → шаг 4 fix). | 🟢 done | `core/infra/api_engine.py:254-300`, `scripts/test_rate_limiter_crossloop.py` |
| **PERF-LOOP-B-DEADLOCK** → DS | ✅ **АУДИТ ГОТОВ (DS 13.06).** 6 WRITE-точек в торговом пути → cross-loop deadlock-риск при sqlite3 busy_timeout=10s: (1) `tsl_updater.set_exchange_{sl/tp}_order_id` [CRIT, 9 callsites]; (2) `position_sync._emergency_close_check` → UPDATE simulated_trades [CRIT, 693:694]; (3) `exec_ws_integration` → UPDATE exchange_order_id [HIGH, 86:91]; (4) `order_manager.snapshot_balances_per_account` → `save_snapshot` [MED]; (5) `order_manager._resolve_exit` → `close_trade` → register_trade [CRIT, через trade_simulator]; (6) `account_router` → INSERT/UPDATE live_positions [MED]. **READ-ы безопасны** (WAL mode: readers don't block). **Рекомендация:** вынести ВСЕ DB-записи обратно в main loop через очередь (`asyncio.Queue`), торговый loop только REST. Детали: `docs/DEADLOCK_AUDIT.md`. | 🟢 DS done → ждёт решение ARCH | `core/exchange/order_manager.py`, `core/exchange/position_sync.py`, `core/exchange/tsl_updater.py`, `core/exchange/exec_ws_integration.py`
| **PERF-COMPUTE-POOL** ❌ | ❌ **ЗАКРЫТ ЗАМЕРОМ (DS Ф1, 23:30) — НЕ ОКУПАЕТСЯ.** Прототип: WT+trend=12мс/пару=1.6с=**0.5% цикла**, НЕ бутылка. Pool медленнее sync (spawn 134мс+IPC+импорт pandas съедают). **Гипотеза compute-GIL ОПРОВЕРГНУТА** (замер до кода спас от бесполезного рефактора scan_one). **Разворот:** dashboard 11с = event-loop STARVATION (очередь 526 корутин), НЕ GIL → реабилитирует вариант A (dashboard отдельный поток — GIL свободен, поток получит время). Реальный IO-рычаг = market_ws/EXEC-WS (убрать REST OHLCV/polling). | ❌ закрыт (замер) | `scripts/perf_compute_pool_*.py` |

| **PERF-COMPUTE-POOL-Ф0/Ф1** → DS | ✅ **ЗАМЕР ГОТОВ (DS 23:15+23:30).** Ф0: trend+WT основное compute. Ф1 прототип: WT+trend=12мс/пару=1.6с=0.5% цикла, ProcessPool МЕДЛЕННЕЕ sync (spawn+IPC+импорт). **Вывод: compute НЕ бутылка, B не окупается.** Скрипты `scripts/perf_compute_pool_probe.py`+`_batched.py`. | ✅ done (вывод: B мёртв) | `scripts/perf_compute_pool_*.py` |

| **PERF-DASH-THREAD** | ✅ **ГОТОВО (33196ea, вариант A).** Dashboard в отдельном потоке+loop за флагом `dashboard.threaded`. **Латентность: /api/stats 7.5с→0.3с, /api/pairs 11.4с→0.25с (~20-40×)** под scan-нагрузкой. scan-цикл не пострадал, 0 cross-loop ошибок. SSE через `_broadcast_threadsafe` (call_soon_threadsafe мост главный↔dashboard loop). Cross-thread безопасно: engine per-call connect WAL, all_symbols()=снимок, close_trade sync WAL, AppRunner без signal-handlers. | ✅ done | `web/dashboard_server.py`, `bot/core/bot.py`, `config.yaml` |

| **PERF-SCAN-CYCLE** | **Длина цикла ~290с = сам scan** (REST-fetch 522×5TF + observers + IO), НЕ dashboard/compute (оба развеяны замерами 14.06). Рычаг: market_ws (OHLCV→WS, убрать REST) + EXEC-WS. Уже в работе (MARKET-WS v2 SHADOW, EXEC-WS 2b). | 🔵 IO-рычаг (market_ws/EXEC-WS) | `core/infra/market_ws_v2.py`, scan_loop fetch |

| **PERF-LOOP-DRIFT** | **Direct-лаги от перегрузки event loop → корень рассинхрона БД↔биржа (DRIFT 118 = 37 zombie + 81 orphan).** Диагноз ДОКАЗАН: замер direct=400ms (сеть здорова); rtt 9-16с совпадают с пиками TaskSampler 200-386 задач; observer-всплески ote=183/arch104=187/mtf=203. Цепочка: пики loop → торговые direct (sync_time/get_positions) в очереди → timestamp invalid → position_sync классифицирует вслепую → DRIFT. Семейство DEV-230. **C+executor ЗАКОММИЧЕНЫ (`db9726d`):** keep-alive ClientSession (rtt 484→235ms) + OTE generate в `run_in_executor` (LAG секунды→0.141s). Верификация: **timestamp invalid −80%** (90→16/час), каскад DRIFT разорван, 0 ошибок. Шаг A (семафор) отпал. **B (отдельный торговый loop) — эпик, 🔴 БЛОКЕР:** GlobalRateLimiter shared синглтон (market-data `api_engine:436` + торговля `bingx_client:283`) с asyncio.Lock/Event → cross-loop crash. Рефактор = риск регрессии защиты от банов 100410. Объём: GlobalRateLimiter cross-safe + торговый loop + ~30 callsites (position_sync 9, tsl_updater 18) + EXEC-WS + AccountRouter + 92 живые позиции. **ARCH: проектируем эпик целиком (bot-arch/рой) перед кодом.** B критичен при 500+ пар (торговый rtt не зависит от числа пар), сейчас не срочно (C+executor дали 80%). | 🔵 C+executor done; B-эпик в проектировании | DISCUSSION [18:15]; `core/infra/api_engine.py` (GlobalRateLimiter), `core/exchange/bingx_client.py`, `bot/core/bot.py` |

---


---

## ✅ Перенесено из TASKS.md 15.06.2026 (полные карточки)


### 🎧 LISTENER-CANON (14.06.2026) — слушатели шины (роадмап Слой 2-5)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| **LISTENER-CANON** | ✅ | NotificationDispatcher → подписчик `SMC_SNAP_UPDATED`, 0 строк в scan_loop | 5d9cb97 · BACKLOG #10/#12 |
| **LISTENER-DASH** | ✅ | SSE event-driven (`_metrics_version++` при закрытии сделки, не каждые 5с) | fdf750d |

### 🏛️ BUS-ACCOUNT-EPIC (14.06.2026) — account-измерение шины (L1→L2→L3)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| **BUS-L2-BRICK** | ✅ | AccountState в шине (equity/маржа) + позиции, баланс живой push | 6e0d616 · BACKLOG #11 |

### 🟡 NOTIF-ENGINE (14.06.2026) — Notification Engine MVP (вердикт роя 7/7)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| **NOTIF-MVP** | ✅ | Dispatcher + FvgDetected/FvgTouch listeners, scan_loop=1 строка | fbda2c8 |

### 🔴 PERF-LOOP-DRIFT (13.06.2026) — event-loop конкуренция → DRIFT 118 (zombie/orphan)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| **TSL-CLEAN-TEST** | ✅ | gear1_be_atr 1.0→1.5 ote_nested; TSL нейтрален WR×2 (DS) | ff3b029 |
| **PERF-DASH-THREAD** | ✅ | Dashboard в поток, латентность ~20-40× (7.5с→0.3с) | 33196ea |

---

## ✅ Перенесено из TASKS.md 15.06.2026 (полные карточки)


---

## ✅ Перенесено из TASKS.md 16.06.2026 (полные карточки)


---

## ✅ Перенесено из TASKS.md 17.06.2026 (полные карточки)


---

## ✅ Перенесено из TASKS.md 29.09.2026

| ID | Дата | Описание |
|---|---|---|
| DEV-242 | 29.09 | `tools/graphify_refresh.py`: граф знаний одной командой — код / `--docs` / `--labels` / `--all`; чинит склейку extract (узлы, номера сообществ, гиперрёбра). Запись в TOOLS.md, REGISTRY.md |


---

# 📦 Июнь 2026 — разделы, свёрнутые 19.10.2026

> Перенесено из `TASKS.md` при разборе актуальности (310 открытых строк → 13 живых).
> Основания по каждой задаче — `docs/TASKS_AUDIT_2026-10-17.md` § «Батч 3».
> Живое из этих разделов осталось в `TASKS.md`: MFE-FIX, NULL-SIGNAL, остаток T-02.
> Текст ниже — как был, ничего не правлено.

## 🎧 LISTENER-CANON (14.06.2026) — слушатели шины (роадмап Слой 2-5)

> scan_loop = оркестратор, остальное = подписчики ОДНОЙ шины. Контракт: `docs/BUS_SUBSCRIBER_ROADMAP.md`.

| ID | Ст | Кратко (≤80) | Детали → |
|---|---|---|---|
| **LISTENER-STRAT** | 🔵 | Слой 4: стратегии (ote/arch104/atr) → отдельные подписчики шины | BACKLOG #20 |

---

## 🏛️ BUS-ACCOUNT-EPIC (14.06.2026) — account-измерение шины (L1→L2→L3)

| ID | Ст | Кратко (≤80) | Детали → |
|---|---|---|---|
| **BUS-ACCOUNT-EPIC** | 🔵 | PairContextBus + account/trader (L2 AccountState → L3 TraderState) | ROADMAP · DISCUSSION 14.06 |
| **BUS-L3-ORDER** | 🔵 | L3: Correlation Shield → Regime Router → Capital Allocator (после DATA-AUDIT-2) | BACKLOG #19 |

---

## 🟡 NOTIF-ENGINE (14.06.2026) — Notification Engine MVP (вердикт роя 7/7)

| ID | Ст | Кратко (≤80) | Детали → |
|---|---|---|---|
| **NOTIF-TIER2** | 🔵 | CHoCH/OTE/OB/Pivot уведомления, включать по одному после FVG | BACKLOG #12 |
| **NOTIF-DASH** | 🔵 | Дашборд: UI-переключение правил уведомлений | — |

---

## 🔴 PERF-LOOP-DRIFT (13.06.2026) — event-loop конкуренция → DRIFT 118 (zombie/orphan)

| ID | Ст | Кратко (≤80) | Детали → |
|---|---|---|---|
| **CONFIG-SLTP-BUG** | 🔴 | Секция `sl_tp_engine` (config 293-363, 26 ключей) НЕ читается → defaults. Осторожно | memory bug_sl_tp_engine_section_ignored |
| **DEV-226-Ph2** | ⏳ | pull edge +0.47R подтверждён; TSL на чистых SL вредит. Ждёт n≥30 | DS 13.06 |
| **ATR-OTE-E3** | 🟢 | DEV-209 = оптимум, полная OTE-конверсия не улучшает (DS) | scripts/atr_ote_e3_backtest.py |
| **OTE-RBUG** | 🟢 | Edge реальный +4808R; min_sl_dist 0.3→0.5 + валидация стороны SL. ч.2 backlog | 5e2fd0f |
| **PERF-LOOP-B-TEST** | 🟢 | GlobalRateLimiter cross-loop 3/3, listenKey вне IP-бюджета | api_engine:254 |
| **PERF-LOOP-B-DEADLOCK** | 🟢 | 6 WRITE-точек cross-loop риск; DB-записи в main loop через Queue | docs/DEADLOCK_AUDIT.md |
| **PERF-COMPUTE-POOL** | 🔵 **ПЕРЕОТКРЫТ 02.09** | ~~«compute=0.5% цикла, GIL-гипотеза опровергнута»~~ — **вывод НЕ подтвердился**. Замеры 02.09: SMC 173 с + calculate_trend 97 с = **~270 с CPU за цикл** при цикле ~300 с, то есть compute был почти ВСЁ время, а не 0.5%. GIL подтверждён: процесс ест 44% ОДНОГО ядра из 16. Прямая векторизация (.iloc→numpy) уже дала 270→37 с без всякого пула. Пул процессов имеет смысл как СЛЕДУЮЩИЙ шаг — 15 ядер простаивают | замеры в [[scan_bottleneck_is_the_channel]] |
| **PERF-SCAN-CYCLE** | ✅ **02.09** | Рычаги применены: прокси (3 ISP, разные /24) + market_ws live 3m/5m/15m + векторизация CPU. Цикл **832 → 256-311 с**, выбросы latency >8с 75%→0%, HARD timeout 83→8 в час. Осталось: узкое место — домашний канал ([[scan_bottleneck_is_the_channel]]) | market_ws_v2 |
| **PERF-LOOP-DRIFT** | 🔵 | C+executor done (timestamp invalid −80%); B (торговый loop) = эпик | db9726d · BACKLOG #20 |

---

## 🔬 СПРИНТ: STRATEGY-DISSECTION (12.06.2026) — разбор 3 боевых стратегий на запчасти

> **Контекст:** 3 стратегии держат 96% потока (3 дня, n=5595): **arch104 57% + ote_nested 32% + atr_change 7%**. Остальное (confluence/wt_signal/pivot_reversal/divergence) ≈0% (отключены/редки). Вскрытие RR-зоны 2-5R (research_zone_2_5r_dissection, `docs/MEMORY_SNAPSHOT`): мёртвая середина 2-5R, но в VST (реально) +1163R; SHORT +0.413 vs LONG −0.106; confluence катастрофа −1.136 (уже не в бою); pivot_1D TP-source убыточны.
> **Цель спринта:** препарировать КАЖДУЮ из 3 боевых стратегий по единой схеме → точечные улучшения (особенно TP-логика, попадающая в мёртвую зону 2-5R).
> **🔴 Единая схема разбора (acceptance для всех 3):** (1) УСЛОВИЯ ВХОДА — гейты/фильтры/что должно совпасть; (2) ТРИГГЕРЫ — что запускает регистрацию; (3) SL-ЛОГИКА — источник + формула + код; (4) TP-ЛОГИКА — источник + формула + код + попадание в RR-зоны; (5) ВЫХОД — TSL/частичный/time-exit; (6) МЕТРИКИ — avgR/median/WR/sumR data-era + разбивка по RR-зонам + VST vs SIM; (7) КОД — файлы/функции/конфиг; (8) ВЫВОД — что точечно улучшить.

| ID | Задача (полный разбор по единой схеме) | Статус | Файлы/данные |
|---|---|---|---|
| **DISSECT-ARCH104** | **Разбор arch104 (57% потока) на запчасти.** SL=`arch104:swing_15m`, TP=`arch104:TBD_r2.0` (фикс RR≈2 → зона 2-3R мёртвая). Паттерн-майнинг: 187 паттернов `config/arch104_patterns.yaml`. **Препарировать:** (1) как паттерн матчится на входе (какие условия features→паттерн), confirmation-score; (2) триггер регистрации (где в коде паттерн→register); (3) SL swing_15m — как находит swing, буфер; (4) TP r2.0 — почему фикс RR2, попадает в мёртвую зону 2-3R → **проверить avgR arch104 по RR-зонам в VST**; (5) выход (TSL? time-exit?); (6) метрики arch104 VST vs SIM по RR-зонам; (7) код: pattern-mining loop, `arch104_patterns.yaml`, register; (8) **гл. вопрос — стоит ли TP r2.0 заменить на структурный/раннер (мёртвая зона)?** | 🔵 разбор | `config/arch104_patterns.yaml`, pattern-mining loop, `trade_simulator`, `simulated_trades` (source_router=arch104) |
| **DISSECT-OTE** | **Разбор ote_nested (32% потока, ядро edge) на запчасти.** SL=`ote:1h_impulse`/`ote:4h_impulse`, TP=`ote:cont_*`/`ote:pull_*` (структурный, НЕ фикс RR → вне мёртвой зоны by design). Каркас: вход 5m в HTF-OTE, риск ×10, раннеры (clamp50 доказан). **Препарировать:** (1) условия входа — OTE-зона (Фибо 0.62-0.79), confirmation-score≥3, перебор триггеров, гейты DEV-44/64A; (2) триггеры — что в `ote_observer_loop`/`ote_signal_generator` запускает; (3) SL — за свечу реакции / impulse-нога, как; (4) TP — cont (продолжение) vs pull (откат), 1h/4h/5m вложенность, структурные цели; (5) выход — SINGLE+TSL, no RR-cap, раннеры; (6) метрики ote по pull/cont × n_down/n_up; (7) код: `core/smc/ote_signal_generator.py`, `bot/loops/ote_observer_loop.py`, `config/ote_setups.yaml`; (8) **гл. вопрос — pull vs cont edge, где OTE сильнее всего?** | 🔵 разбор | `core/smc/ote_signal_generator.py`, `bot/loops/ote_observer_loop.py`, `config/ote_setups.yaml`, ote_nested_mtf_strategy |
| **DISSECT-ATR** | **Разбор atr_change (7% потока, худшие метрики −0.426) на запчасти.** SL=`atr_trendline_buf`, TP=`atr_rr_3.0` (фикс RR=3 → зона 3-5R, −0.275 худшая). **Препарировать:** (1) условия входа — ATR-Supertrend смена ±1 (`calculate_trend` factor=1.25 бой), regime-гейт снят 11.06; (2) триггер — atr_change в scan_loop; (3) SL — atr_trendline (Supertrend-линия) + буфер, формула; (4) TP — atr_rr_3.0 (фикс RR3) → попадает в мёртвую 3-5R; (5) выход; (6) метрики atr_change VST vs SIM по RR-зонам; (7) код: `calculate_trend`, scan_loop atr_change, `_execute_atr_change_signal`; (8) **гл. вопрос — atr_change=триггер→вход в 5m-OTE (insight atr_change_ote_insight: WR89% в 5m-OTE) vs текущий прямой вход; фиксить TP или конвертить в OTE-триггер?** | 🔵 разбор | `calculate_trend`, `scan_loop` (atr_change), atr_change_ote_insight, `docs/PLAN_ATR_CHANGE_OTE.md` |

> Порядок рекомендуемый: **ote_nested** (ядро, понять эталон правильной стратегии) → **arch104** (массовая, TP-тюнинг) → **atr_change** (худшая, возможно конверсия в OTE-триггер). Каждый разбор = отдельный отчёт `docs/DISSECT_<NAME>.md` + вывод в этот спринт.
>
> **🔀 DS + Claude ПАРАЛЛЕЛЬНО (юзер 12.06):** **DS = data** (метрики по RR-зонам, бэктесты вариантов SL/TP, проверка гипотез H1..Hn — задание `docs/DISSECT_DS_TASK.md` с атомарными гипотезами на каждую стратегию). **Claude = code** (вход/триггеры/SL/TP логика из кода). Взаимный фильтр: DS-данные ↔ Claude код-реальность → синтез оптимального решения. Deliverable: DS `docs/DISSECT_<NAME>_DATA.md` + Claude `docs/DISSECT_<NAME>.md`.

---

## 🔥 СЕССИЯ 11.06.2026 (Даат) — REGIME-V2 + atr_change×OTE + C-01

| ID | Задача | Статус | Файлы |
|---|---|---|---|
| **MARKET-WS** | ✅ **v2 РЕАЛИЗОВАН (14.06, Даат).** `core/infra/market_ws_v2.py`: mp.Process+Queue+QueueReaderThread+supervisor. Этап 1 SHADOW enabled=true,use_ws=false. Наблюдать `[MarketWS-v2]` логи. | ✅ v2 SHADOW / наблюдение | `core/infra/market_ws_v2.py`, `bot/core/bot.py:511`, config `market_ws` |
| **REGIME-V2** | Унификация regime→Bus (D-10) + активация `classify_v2` | ✅ **АКТИВИРОВАН** (use_v2:true, Э1-4 готовы; мониторинг acceptance 1-2 дня) | `scan_loop:234/848/1384`, `config.market_regime`, `PLAN_REGIME_V2.md` |
| **ATR-GATES** | Снять regime/strength гейты atr_change (−178R, тавтология ATRTrend−1) | ✅ **СНЯТЫ** (allow_short_regimes, long_penalty=0, min_strength=0) | `config.signal_quality.atr_change` |
| **ATR-OTE** | atr_change×OTE интеграция: триггер→вход в 5m-OTE (бэктест WR89%) | 🟡 **дизайн готов** (Э1-Э4). Э1 фильтр ноги. Нужна история (46/273 пар) | `PLAN_ATR_CHANGE_OTE.md`, `scripts/atr_change_ote_test.py` |
| **C-01** | CHoCH length=5 ре-майнинг 69 паттернов | ✅ **ЗАКРЫТ 11.06** (полный прогон 45 симв, exit 0): 30 HTF→архив, DS_L096 вернут (n=74 avgR+0.20), 4 LTF-артефакта + 6 pivot (S060/092/093/098, L061/062) НЕ возвращать (length=50 завышал 5-8×). Можно катить swing_bridge на length=5 (флаг `arch104.choch_length`) | `arch104_patterns.yaml`, `ltf_metrics.csv`, `PLAN_C01_choch_length_fix.md` |
| **SIGNAL-AUDIT** | Аудит актуальности сигналов (confluence/wt_sideways отключены — shadow с полным trade_features, замерить) | 🟢 идея (юзер 11.06) | — |
| **HIGH-VOL-VOLUME** | Объёмное обогащение HIGH_VOL (volume_z из features) | 🟢 отложено | — |
| **DASHBOARD-VST-MODE** | Глобальный SIM/VST-фильтр: `summary(mode)` → весь дашборд (метрики/KPI/EV/Avg R) переключается SIM↔реальная торговля. Сейчас ВСЁ общее (балласт включён). Календарь уже сделан (`pnl_calendar(mode)`); распространить на summary + переключатель в топбаре. Эффект: VST 11.06 +2.012 vs SIM 0.26 — реальная картина прячется в общем | 🟢 идея (юзер 11.06) | `performance_engine.summary()`, `/api/stats`, топбар |
| **EXIT-TYPE-FIX** | `_resolve_exit` не знал тип закрывающего ордера `MARKET`/`LIMIT` (реальный тип большинства закрытий на VST) → падал в EXPIRED вместо SL/TSL, хотя биржа отдаёт `profit` в том же ордере | ✅ **ПОЧИНЕНО+ЗАКОММИЧЕНО 25.06 (Даат).** Аудит 2×25 сделок: oko_ote 25/25, ote_nested 24/25 фиксится. 1912 историчных VST EXPIRED строк потенциально неверны (status+R) — backfill НЕ делал, отдельная задача. → DISCUSSION [25.06 01:30] | `core/exchange/position_sync.py::_resolve_exit` |
| **DB-ILLUSIONS-AUDIT** | ✅ **DS ЗАКРЫЛ:** R_multiple ДОСТОВЕРЕН (89.5% совпадение с формулой). Система маржинально прибыльна **avgR+0.20** (бумажный +0.216, реальный +0.204, завышение лишь 5% от EXPIRED R=0→−1). Гипотеза «бумажные/убыточна» ОПРОВЕРГНУТА (Claude ошибочно clip к сломанному MFE). clamp_r_smart раннеры НЕ режет (131 сд R>15, max 112R; зажатые=артефакты sl_dist≈0). | ✅ закрыто (Claude валидировал) | `scripts/db_illusions_audit.py` |
| **DATA-AUDIT-2** | 🟢 **ГОТОВО (DS 15.06). 4 аудита:** (1) EDGE: VST-селектор = весь edge, SIM убыточен; (2) ML: train_test_split → временной leak + selection bias; (3) MFE: 5% битых (НЕ 43%), captured_R_pct сломан; (4) Zombie: 211 SL без биржевого ордера. **Вытекло в #7+#8.** | 🟢 done → #7+#8 | DISCUSSION [15.06 04:45], `scripts/` |
| **MFE-FIX (A3)** | 🟢 **ЗАКРЫТ.** MFE-трекинг НЕ сломан (5%, не 43%). captured_R_pct починен Даатом (#6, clamp[0,100]). | 🟢 done | `trade_simulator` MFE |
| **TP-ANOMALY** | (часть DB-ILLUSIONS) TP `R_multiple > max_R_possible` 3171 сделок. Корень: R-формула ИЛИ цены (exit/SL/min/max) ненадёжны. Связь OPS-06/ML-01c | 🔴 в составе DB-ILLUSIONS-AUDIT | `trade_simulator` TP close |
| **OPS-06 ч.3 qty** | ✅ **ФИКС 11.06:** `trade_router:290` (ARCH-94) писал только `exchange_order_id`, забыл `qty` → qty=NULL с 28.05 → реальный $ P&L не считался. Добавлен qty в UPDATE (qty>0 guard:257). После рестарта новые сделки пишут qty → `pnl_calendar.total_usd` (qty×Δprice) оживёт | ✅ сделано (рестарт применит) | `trade_router.py:290` |
| **OPS-06-ACCOUNT** | Разделение $ по СЧЕТАМ (acc1/acc2): поле `account` в `simulated_trades` (ALTER) + `trade_router` пишет `account_router.route(symbol)` рядом с qty + `pnl_calendar(mode, account)` + переключатель acc1/acc2/all. Сейчас счета НЕ различаются в БД (поле нет) → $ смешан. Связь ARCH-96 | 🟡 НОВАЯ (юзер 11.06 «два аккаунта, на уровне роутера») | `simulated_trades` schema, `trade_router`, `account_router.route()` |
| **GRAVITY-ROCKET** | MTF-gravity на входе → edge. На 628 боевых: gravity100+ avgR+2.483 WR74% (×4 база). DS-триангуляция: gravity ≠ самостоятельный trigger (random-bars corr −0.016), а **ранжировщик поверх сигналов** (selection bias). Консенсус: **ConfluenceField = направленный ГЕЙТ (доминанта по конфлюенции-к-цели подавляет встречное) + ранжировщик СОНАПРАВЛЕННЫХ**, НЕ генератор входов. Живое подтверждение XLM: pull-SHORT 0.1R vs cont-LONG 14.2R — приоритет pull (TIER1) прячет cont-ракету; pull контр-тренд by design (`ote_signal_generator:277`) валиден лишь при завершённом импульсе (Эллиотт) | 🟢 дизайн (валидировано, ждёт PIVOT-GRAVITY) → ARCH ConfluenceField (reuse GravityEngine tp_selector) | `scripts/gravity_entry_test.py`, `core/calculators/tp_selector.py`, DISCUSSION 11.06 |
| **PIVOT-GRAVITY** | ✅ **ЗАКРЫТ (MTF, 2 независимые оси → 1 вердикт).** GRAVITY (W_TF×W_type/dist^1.5, 452 сд): ВСЕ бакеты <0, даже g=250+ → −0.203, corr −0.089, winners avg_g≈losers. ELLIOTT-фаза: все бакеты <0. **pivot_reversal = балласт РАВНОМЕРНЫЙ, скрытой ракеты нет ни по конфлюенции, ни по фазе.** Депрекейт обоснован окончательно (−1272R = 25% системы) → разблокирует SIGNAL-CLEANUP | ✅ закрыто (Claude валидировал) | `scripts/`, DISCUSSION 11.06 |
| **ELLIOTT-COMPLETION** | ✅ **v2 ПРИНЯТ (Claude валидировал)** — методология чистая (3 дыры устранены). **PULL: гипотеза подтверждена** (SHORT n_down≥1→+3.23 WR85% vs n_down=0→−0.21; LONG зеркально n_up≥1→+1.52). **CONT: деградирует с фазой** (n_down=0→+2.08, ≥3→−0.19). **PIVOT_REVERSAL: фазой НЕ спасается** (все бакеты <0) → депрекейт. 🎯 Реварп: pull = MTF-согласование (вход по HTF-тренду через LTF-откат = ote_nested), не Эллиотт-разворот. ⚠️ caveat: pull n=81 мала, добрать перед жёстким гейтом. **→ DEV-226 Phase 2** | ✅ закрыто → DEV-226 Ph2 | `scripts/elliott_completion_test.py`, DISCUSSION 11.06 |
| **DEV-226 Ph2** | Точечный гейт фазы (из ELLIOTT v2): pull только при `n_down≥1`(SHORT)/`n_up≥1`(LONG); cont запрет при `n≥3`. **✅ SHADOW РЕАЛИЗОВАН (11.06):** `_elliott_phase_shadow` (ote_observer) считает n_down/n_up на входе FIRE → пишет `phase_nd_4h`/`phase_nu_4h`/`phase_gate_would_block`/`phase_gate_reason` в features_json, НЕ блокирует. Reuse `calculate_n_down/_up`. **✅ ДАННЫЕ ПОШЛИ (12.06): 18 ote-сделок несут фазу.** Предв. замер: would_block=0 avgR+4.62 (n=7) vs =1 +1.08 (n=3) — знак верный, но n мал + ракета ALLO(+37.8) раздувает. **След.: ЗАМЕР на n≥30/бакет** → hard-гейт (cont первым). Реальный рычаг архитектуры (STRADDLE показал dedup=не рычаг) | 🟡 shadow копит (18 сд, замер на n≥30) | `bot/loops/ote_observer_loop.py`, `indicators.py:576` |
| **SIM-DEPRIO** (SCALABILITY) | ✅ **РЕАЛИЗОВАН (14.06, Даат).** `trade_simulator._proc`: throttle sim-only (interval=300с из config `performance.sim_check_interval_sec`). `self._sim_checked` в `__init__`. Биржевые всегда. 🟡 Исходный дизайн: **СПРОЕКТИРОВАНО (юзер 14.06: «реже SIM, освободить loop, приоритет бирже»).** **Данные 14.06:** 312 OPEN = 189 sim_only (61%) + 123 биржевых + 4 TSL-активных. **61% бюджета loop тратится на фантомы** (margin-reject SIM-only варятся в одном Semaphore(15) с реальными). **Идея:** throttle sim_only в `check_open_trades_with_tsl._proc` — окно 300с вместо 60с (паттерн как DS-322 `_repair_checked` 3600с / DEV-227 `_force_rest_ts` 150с): `if not _exchange_managed_trade and _now_ts - self._sim_checked.get(trade_id,0) < SIM_CHECK_INTERVAL: return`. За флагом `performance.sim_check_interval_sec` (откат мгновенный). **Эффект:** ~38 вместо 189 sim/цикл → бюджет REST/Semaphore идёт биржевым. **Нюанс:** sim-закрытие с задержкой ≤5мин (статистика, не деньги — ок); биржевые (деньги) только выигрывают. **Чек:** runtime на копии БД (feedback_ast_parse_no_scope — критичный путь `_proc`). Часть EXEC-WS вектора (биржевые → event-driven, sim → редкий polling). | 🟡 ждёт решения «сейчас / после прогона» | `core/trading/trade_simulator.py:1816`, `config.performance` |
| **EXEC-WS** | ✅ **2b sync_close РЕАЛИЗОВАН (14.06, Даат).** `exec_ws_integration.py`: `_sync_close_async` + per-account handler. Флаг `sync_close: false` → включить после наблюдения. 🎯 **РЕШЕНО 14.06 — КОРЕНЬ = неверный VST WS-домен (фикс `user_data_ws.py`).** Код слушал PROD `open-api-swap.bingx.com` с VST-listenKey → 0 order events. docs-v3: VST WS = **`vst-open-api-ws.bingx.com/swap-market`** (PROD/LIVE = open-api-swap). Эмпирич. подтв. (`diag_exec_ws_endpoints.py` на VST-домене): acc1 ACCOUNT_UPDATE=4(m=ORDER,P[]) + ORDER(o)=8 (`TRADE_UPDATE` o.i=orderId o.X=FILLED) — **events ИДУТ**. Парсер был верный (msg.o), subscribe не нужен. Фикс: `VST_WS`/`LIVE_WS` по is_vst (user_data_ws.py:37-38,59,164). **NEXT: рестарт → [EXEC-WS] orders>0 → включить write_exch_id (2a) → дореализовать 2b sync_close (ACCOUNT_UPDATE pa=0 → close БД).** → memory `exec_ws_vst_userdata_proven`. ⬇️ старая «тупик»-диагностика устарела. ⛔ ~~ТУПИК НА VST 14.06 (диаг-скрипт `scripts/diag_exec_ws_endpoints.py`):~~ слушал ОБА endpoint параллельно 7мин с listenKey acc1. Результат: A `open-api-ws/market` молчит полностью (0 — неверный для swap); B `swap-market` = SNAPSHOT 667+ping, **ORDER=0** при **4 реальных биржевых открытиях acc1 в окно**. → VST user-data WS даёт только начальный снимок+heartbeat, НЕ пушит executionReport/ORDER_TRADE_UPDATE. **EXEC-WS 2a нежизнеспособен на VST.** exch_id и так пишется из REST place (работает). enabled=true держит бесполезный WS (snapshot-burst). NEXT: либо enabled=false (разгрузка), либо проверить LIVE user-data (бот на VST→тих). Корень рассинхрона лечить REST-sync. → memory `exec_ws_vst_userdata_proven` (коррекция). ⬇️ исходный статус. 🔴 **БЛОКЕР 14.06: WS НЕ ловит ORDER executions.** Прод (enabled=true): events=666 но orders=0/account=0 при **19 биржевых открытиях/23мин** на обоих акк → только SNAPSHOT burst + ping + редкий FUNDING_FEE. Корень: код `user_data_ws.py:33` на `open-api-swap.bingx.com/swap-market` (отдаёт snapshot/market), а BingX docs + `test_vst_listenkey.py` → user-data executionReport на **`open-api-ws.bingx.com/market?listenKey=`**. «path доказан 12.06» = доказан CONNECT, НЕ приём executions («714 событий» = SNAPSHOT burst, не executionReport). **2a write_exch_id включать НЕЛЬЗЯ (нечего ловить).** NEXT: диагностический скрипт — слушать ОБА endpoint параллельно, поймать открытие, найти где executionReport (НЕ менять вслепую). → memory `exec_ws_vst_userdata_proven` (коррекция). ⬇️ исходный статус ниже. ✅ **ЭТАП 1+2a РЕАЛИЗОВАНЫ (12.06).** Этап1: `user_data_ws.py` WS живой (endpoint `wss://open-api-swap.bingx.com/swap-market?listenKey=`, 714 событий/120с, 0 reconnect). Этап2a: `exec_ws_integration.py` — on_event пишет exch_id из `ORDER_TRADE_UPDATE`(FILLED MARKET ro=false→open) в OPEN-сделку symbol+ps без exch_id. Запуск `bot.py` за флагами `trading.exec_ws.{enabled,write_exch_id,sync_close}` (все OFF). AST+runtime(DRY на реальном событии) OK. **Включение поэтапно: enabled→[лог]→write_exch_id→[пишет]→sync_close(2b TODO).** **🔴 ЭТАП 2b:** ACCOUNT_UPDATE pa=0→sync close БД (через _resolve_exit). + multi-account (2-й WS). | 🟡 готово к включению (флаги off) → 2b | `core/exchange/{user_data_ws,exec_ws_integration}.py`, `bot/core/bot.py`, `config.trading.exec_ws` |
| **EXEC-SIM-SPLIT** | 🟢 **17.06: путь «80/5» принят (юзер→DS→рой 5/5). КИРПИЧ №1 (риск-экспозиция gate PER-ACCOUNT) РЕАЛИЗОВАН SHADOW** — расширение DEV-52 l3_checker (`trade_simulator.py`, `max_total_risk_pct:10`, `risk_gate_shadow:true`), мерка `Σ(qty×|entry−sl|) VST acc / equity_account` (equity из balance_snapshots), НЕ количество/маржа. Reuse gate-chain. py_compile+runtime на копии OK (acc2 9.7% would_block, acc1 0.8% pass). **Shadow вскрыл: реальная боль = МАРЖА 87% used на обоих акк (стопы здоровы) → margin pre-check в приоритет.** Deposit-рассинхрон (4 источника) починен: balance_snapshots=единый источник (gate+дашборд risk_exposure+config SIM-номинал). **КИРПИЧ №2 (margin pre-check) РЕАЛИЗОВАН SHADOW** — `available_per_account < min_available_usdt` (`min_available_usdt:5`, `margin_gate_shadow:true`), ловит корень фантомов (register пишет SIM ДО placement, margin-fail оставляет SIM). Рефактор DEV-52: общий lookup → 2 gate. NEXT: рестарт → наблюдать `[DEV-52][RISK]`+`[DEV-52][MARGIN]` → активация (shadow:false) + уточнить пороги. → memory `exec_sim_split_epic.md`. ⬇️ исходный вектор-дизайн: 🔵 **ВЕКТОР НА БУДУЩЕЕ — НЕ план к исполнению (трезвая оценка Claude 14.06).** Юзер накидал мысль, Claude разогнался в эпик → пересмотр: **СЕЙЧАС не делать.** Причины: (1) корень боли (189 фантомов) = margin-reject от RISK 95% / нет лимита позиций, а НЕ «sim живёт с биржей» → лечится риск-менеджментом дешевле; (2) 2 процесса с одной сигнальной логикой = крупнейший дубль, противоречит [[principle_reuse_not_duplication]] — strip УЖЕ протух за месяц (доказательство закона); (3) цена высока для соло + машина на пределе (BSOD). **80/5 альтернатива в ОДНОМ процессе:** лимит позиций (нет фантомов) + execution_mode разметка (ARCH-DB-V2 есть, sim/real в 1 БД помечены, обучение/дашборд фильтруют) + опц. SIM-DEPRIO throttle. **Оправдан КОГДА:** +юзер (мульти-тенант) ∥ strip = принципиально иная логика (дрейф=фича) ∥ железо мощнее. Дизайн ниже сохранён для того момента. → memory `exec_sim_split_epic.md`.\n\n_(исходный дизайн:)_ **Разделение контуров на 2 процесса:** main = ТОЛЬКО реальные (vst/live), loop/IP-бюджет идут торговле; strip = sim-полигон по ВСЕМ сигналам. **Разделение контуров на 2 процесса:** main = ТОЛЬКО реальные (vst/live), loop/IP-бюджет идут торговле; strip = sim-полигон по ВСЕМ сигналам. **🔴 КРИТИКА (grep 14.06):** обучение main питается ОТ sim — `update_signal_weights`→`PerformanceEngine.by_signal_type_ema` фильтрует лишь `status IN(TP,SL,TSL,EXPIRED)` БЕЗ различия sim/real; ARCH-104 mining + ML тоже читают `simulated_trades` целиком. Sim доминирует (27719 в осн. sim). → **sim НЕ удалять, а ПЕРЕСЕЛИТЬ в strip + перенаправить обучающий контур.** **РЕШЕНИЯ ЮЗЕРА:** (БД) РАЗДЕЛЬНЫЕ — strip=sim-only DB, main=реальные. **Мост:** main читает strip-БД для обучения через `db_path` (УЖЕ параметризован: `update_signal_weights(db_path)`, `PerformanceEngine(db)`) → config `trading.learning_db_path`. **Дефолты дизайна (на подтверждение):** (2) strip сканит НЕЗАВИСИМО на общем кэше (полный двойник→«обновить strip под main» критично); (4) strip без биржевого REST легче, при нужде меньше пар/реже (машина на пределе — BSOD/XMP); (5) main НЕ регистрирует не-биржевой сигнал (strip поймает). **Объединяет:** STRIP-TWIN (общий кэш=фундамент), SIM-DEPRIO (отменяется — sim уходит из main радикальнее throttle), ARCH-DB-V2 (execution_mode разметка). **Этапы:** (1) пересоздать strip из main; (2) STRIP-TWIN общий кэш; (3) strip→sim_only режим+своя БД; (4) main: execution_mode чисто vst, не писать sim; (5) мост learning_db_path; (6) дашборд sim из strip. → memory `exec_sim_split_epic.md`. **Проектировать роем+bot-arch перед кодом.** | 🔵 эпик (дизайн, после прогона) | `crypto_volume_bot_strip/`, `core/trading_intelligence.py:246`, `config.trading.learning_db_path` |
| **STRIP-TWIN** (research) | 🔵 **BACKLOG (юзер 14.06: «strip кормить нашим кэшем для симуляции?») — КОМПОНЕНТ EXEC-SIM-SPLIT (общий кэш).** **Идея:** strip-бот (`crypto_volume_bot_strip`) = A/B-близнец на ОБЩЕМ data-канале — потребляет OHLCV-кэш main вместо своего REST. **Двойная польза:** (1) IP-бюджет — strip НЕ тянет биржу → не удваивает запросы с одного IP → нет риска бан 100410 (GlobalRateLimiter защищает один IP); (2) детерминизм A/B — оба видят бит-в-бит одни данные → разница только в логике/конфиге (золотой стандарт сравнения). = `principle_reuse_not_duplication` (один источник, два потребителя). **Реальность:** main кэш = in-memory LRU (`ApiEngine._cache._data`), дисковый `ohlcv_cache.db` 2.5GB = периодич. дамп `save_to_disk` (mtime 18.05). 2 процесса не делят dict → нужен слой. **Варианты:** B(реком.) HTTP `/api/ohlcv` у dashboard:8000 (инфра есть, main горячий путь не трогаем, strip read-only); A общий SQLite-кэш WAL; C Redis (избыточно). **🔴 БЛОКЕР:** strip заброшен с ~16.05 на СТАРОМ коде (`bot_with_subscriptions.py`, до ночных ARCH/EXEC-WS/perf), НЕ git-связан с main. Врубить сейчас = старая логика → A/B грязный (конфиг + месяц дрейфа кода). Сначала: пересоздать strip из текущего main ЛИБО определить что тестирует иначе. → memory `strip_twin_shared_cache.md` | 🔵 backlog (research, после прогона) | `web/dashboard_server.py` (+/api/ohlcv), `crypto_volume_bot_strip/` (data_collector → HTTP-source) |
| **ADOPT-TRADES** | 🔵 **BACKLOG (важный момент, юзер 12.06): «открываю руками — бот ведёт?».** Сейчас НЕТ: бот ведёт только свои БД-сделки (`simulated_trades` с entry/sl/tp/regime/exch_id), ручная позиция = `exch-only`, `sync_positions` её не трогает. **Идея:** EXEC-WS ловит `ORDER_TRADE_UPDATE FILLED` (ручное открытие) → adopt-запись в БД → бот ведёт (TSL/SL/TP/exit). **Корень-вопрос (решить ПЕРЕД кодом):** откуда 1R/SL — (а) юзер ставит SL руками→бот берёт как `original_sl`; (б) бот сам ATR/за-свечу при adopt. Отличить ручное от ботовского (orderId не из ботовского place, нет в БД) иначе двойной adopt. Вектор «почти торговый терминал». → memory `adopt_manual_trades_vision.md`. Сначала базовый EXEC-WS 2b. | 🔵 backlog (дизайн) | `core/exchange/exec_ws_integration.py`, `trade_simulator.py` (adopt-INSERT) |
| **ARCH-DB-V2** | 🔵 **СПРОЕКТИРОВАН (синтез 5 нейронов + Claude, 12.06) — БД в торговый терминал.** Боль юзера: SIM/VST/LIVE + аккаунты в одной куче, реальный PnL и баланс per-account не отследить, фильтраций будет много. **Консенсус 5/5:** домены `Signal→Trade→Order→Account→Exchange`; 3 поля `account_id`+`execution_mode`(SIM/VST/LIVE явно, не через exch_order_id IS NULL)+`exchange_id`; справочники `exchanges`+`accounts`; **`balance_snapshots`** (история equity — решает «движение баланса»); `orders` отдельно; тяжёлое (features_json) → связанные таблицы. **🔬 Приземление Claude:** ORM НЕТ (raw sqlite3 в 33 файлах — SQLAlchemy=рефактор, не «1 строка»); backfill account 76% сделок не покрыть (account_routing моложе на 3мес → старые account_id=1, точно вперёд); positions=current-state НЕ история (иначе ~295K строк/день). **РЕШЕНИЕ ЮЗЕРА 12.06:** raw SQL + **тонкий db-слой** (репозиторий-функции в `core/db/`, не полный ORM); старт через эпик. **ПЛАН:** Ф1 (сейчас) ALTER +3 поля + balance_snapshots + backfill → фильтр режимов/аккаунтов + equity-график (80% боли, риск≈0); Ф2 exchanges/accounts/positions + дашборд-вкладки; Ф3 нормализация trades/signals/orders/trade_metrics через ETL; Ф4 db-слой→Postgres-readiness. Каждый шаг=db_migration+тест на копии. + добавить `fee` (точный реальный PnL). → `docs/DB_REDESIGN_SYNTHESIS.md`, `docs/DB_ARCHITECTURE_V2.md`, `docs/DB_REDESIGN_PROMPT.md`. **🔀 Ф1 ОТДАНА DS (модель юзера 12.06): DS делает всю Ф1 на КОПИИ `subscriptions_test.db` (DDL +3 поля + balance_snapshots + backfill + register_trade INSERT + тонкий db-слой `core/db/*_repo.py`) → Claude проверяет (взаимный фильтр + runtime на копии, feedback_ast_parse_no_scope) → Claude применяет на БОЕВУЮ через db_migrations + коммит. Боевую трогает ТОЛЬКО Claude.** Задание DS: `docs/DB_PHASE1_DS_TASK.md`. **✅ Ф1 РЕАЛИЗОВАНА (коммит 12.06): DS дал data-ядро (db-слой+backfill-логика), Claude взаимным фильтром нашёл 3 пробела (register_trade НЕ писал поля / save_snapshot НЕ вызывался / нет воспроизв. миграции) → Claude доделал интеграцию.** Готово: авто-миграция subscription_manager (+3 колонки+balance_snapshots+индексы), register_trade пишет account/mode/exchange, order_manager.snapshot_balances_per_account (multiacct), position_sync throttled save_snapshot (~10мин), `core/db/{balance,trades}_repo.py`, `scripts/db_phase1_backfill.py` idempotent. **Runtime-тест на копии OK** (миграция+register(+3 поля)+snapshot+backfill SIM14890/VST10313/старые acc=1). | 🟢 **Ф2 В ПРОДЕ (13.06):** exchanges/accounts/positions DDL+seed (БД), `balance_r… | DS+Claude · ✅ `core/db/`, `trade_simulator`, `order_manager`, `position_sync`, миграции |
| ~~EXEC-WS-path~~ | 🟢 **Execution Sphere WS (ARCH-96 разморозка) — PATH ДОКАЗАН 12.06.** Корень рассинхрона (orphan/drift/zombie/exch_id=None/фантомные SIM-only): всё на REST-polling (sync 60с отстаёт). **Решение: VST private user-data WS.** Тест `scripts/test_vst_listenkey.py`: ✅ listenKey via `POST open-api-vst.bingx.com/openApi/user/auth/userDataStream` (X-BX-APIKEY, без подписи) HTTP200; ✅ WS `wss://open-api-ws.bingx.com/market?listenKey=<vst_key>` подключён. ccxt sandbox НЕ умеет (нет sandbox user URL) → кастомный WS. **Эффект:** `executionReport` push с `i`(orderId)→надёжный exch_id; `ACCOUNT_UPDATE`/position-close→мгновенный sync. **1 соединение/аккаунт (НЕ per-pair) → scan_loop НЕ затронут** (vs market WS плато 750s). Реализация: listenKey lifecycle (keepalive PUT ~30мин, reconnect) + интеграция в register(exch_id)/position_sync. gzip-декод сообщений | 🔴 ARCH (новая, path доказан) | `core/infra/ws_feed.py` (новый user-stream), `trade_router`, `position_sync`, `scripts/test_vst_listenkey.py` |

### 📥 ПЕРЕНОС ИЗ DISCUSSION 11.06 (задачи из аудит-марафона + sign-audit)

| ID | Задача | Статус | Файлы |
|---|---|---|---|
| **SIGNAL-CLEANUP** | Балласт/мёртвые из SIGNAL-AUDIT: ✅ **`pivot_reversal` ОТКЛЮЧЁН** (−1272R, 2 оси). ✅ **`watch_list_breach` ОТКЛЮЧЁН 12.06** (`signal_quality.watch_list_breach_enabled:false` + ранний return в `_handle_wl_breach_entry`; балласт −169R, длинные сделки avg 701мин). Остаётся: CLEANUP мёртвых меток БД `wt_b_signal`/`mtf_bias`/`trend_signal`/`composite` (давно не торгуют, фоном) | 🟢 pivot+wl_breach OFF; cleanup меток фоном | `config.yaml`, `bot/monitoring.py:465`, `scan_loop.py:200` |
| **NULL-SIGNAL** | 17 сделок `signal_type=NULL` (+3.9R) — `source_router` есть, метка не записалась. Баг в `register_trade`? Потерянные edge-метки | 🟡 **DS** investigate | `register_trade`, `simulated_trades` |
| **CONFLUENCE-RETURN** | `confluence` +610R sumR но отключён 30.05 (WR30% низкий, +avgR). Вернуть? Оценка неполна (regime=NULL). Решить ПОСЛЕ regime/pattern fix (B3/ML-01d) | 🟡 отложено (ждёт regime-fix) | config, `scripts/` |
| **MFE-FIX (A3)** | `max_R_possible`/`max_price` не обновляются real-time → 43% сделок `max_price==entry`. Ломает `captured_R_pct` + ML-01c таргет. (= п.3 DATA-AUDIT-2) | 🔴 **DS** | `trade_simulator` MFE-трекинг |
| **AI-SPHERE-LOCAL** | Локальный DeepSeek-R1 как AI-сфера Куба (async, инсайты в Bus). Research готов (`docs/AI_ARCHITECTURE_R1.md`, `setup_r1.py`, `ds_r1_analyzer.py`). Железо: 1× GTX 1080 сейчас (1070 не установлена). + RAG из PDF-гайдов (Эллиотт/SMC) для Continue | 🟢 research готов, не интегрировано | `docs/AI_ARCHITECTURE_R1.md`, `scripts/setup_r1.py` |
| **VST-SLIPPAGE** | ✅ slippage мал (0.07-0.18%, НЕ 0.45%). Корень минуса = `pivot_reversal`+`confluence` (−1865R), НЕ исполнение. arch104 на VST в плюсе (+0.484R) | ✅ закрыто (08.06) | `scripts/vst_slippage_audit.py` |
| **TSL-PROFILE** | ✅ signal_type-aware Gear-профили (ote_nested gear3=8ATR дышит дольше; default 2/4/12) | ✅ сделано (af7bfae) | `tsl_engine.py` TSL_PROFILES |
| **A2 zombie/SL** | ✅ ликвидация-риск КОНТРОЛИРУЕТСЯ (0 голых сейчас, REPAIR-SL 33K детектов = активная защита). Перепроверен 3 независимыми источниками | ✅ закрыто (валидировано) | REPAIR-SL, `exchange_sl_order_id` |

> **snapshot (P2) — НЕ дыра:** `trade_features` 100% активных сигналов с 31.05 (`write_table`). Низкое общее покрытие = старые сделки + мёртвые сигналы. `features_json`=метаданные (не косяк).

---

## 🔍 АУДИТ 2026-06-09 — ВЕРИФИЦИРОВАН (отчёт `docs/audit/AUDIT_2026-06-09.md`, оценка 4.5/10)

> **⚠️ КОСЯК ПРОЦЕССА (юзер 09.06):** аудит читал `current_state.md`/`whats-next.md` из последнего коммита → доки УСТАРЕЛИ → 2 «критичные» задачи (WAL/sklearn) оказались давно сделаны. **Доки не обновляются регулярно** = тот же «раздвоенный источник правды», что аудит нашёл в коде. → задача **DOC-SYNC**.
> **Верификация Claude (grep по коду):** из 6 HIGH аудита — 6 реальны, 2 устарели, 1 не найдена. НЕ заводить готовое.

| ID | Спринт | Задача | Статус (верифик.) | Файл:строка |
|---|---|---|---|---|
| **SEC-01a** | 🔴 S | Dashboard bind `0.0.0.0`→`127.0.0.1` (1 строка, мгновенно закрывает дыру) | ✅ **СДЕЛАНО 09.06** (default 127.0.0.1 + config `dashboard.host`) | `dashboard_server.py:2224` + `bot/core/bot.py:491` |
| **SEC-01b** | 🔴 S | token-auth + CSRF на все POST (`/api/settings` пишет config, `/close` закрывает сделки — открыты всем в сети!) | 🔴 РЕАЛЬНА | `dashboard_server.py` POST-роуты |
| **SEC-01c** | 🔴 S | задействовать `ADMIN_ID` (грузится в `config_loader:57`, нигде не используется → нет admin-gate) | 🔴 РЕАЛЬНА | `config_loader.py:57` |
| **OPS-01a** | 🔴 R | анти-#1910 sanity-guard:** при OPEN, если цена ушла >X% за SL → форс-клоуз НЕЗ… | ✅ **СДЕЛАНО+ПРОВЕРЕНО В БОЮ 09.06 (#20556 INJ висела за SL −2.96R → после рестарта OPS-01a закрыл на честные −1R, экономия −1.96R). Фикс: пустой фильтр → SL-чек по текущей свече `df.tail(1)` | `trade_simulator.py:1918-1928` |
| **OPS-01b** | 🔴 R | `created_at`/SL-проверка от **биржевого времени**, не системных часов Windows | ✅ **СДЕЛАНО+ПРОВЕРЕНО RUNTIME 10.06** (smoke-baseline на копии БД: фикс поймал 2 ЖИВЫЕ сделки с skew 0.5/1.5 мин — хост опережает биржу; closed=3 без NameError). Решение: НЕ лишний `ex.fetch_time`, а биржевое время последнего бара `df["time"].iloc[-1]` (уже в данных, бесплатно) — детект forward-skew + кламп created_ms к биржевой шкале + лог величины. Лечит ВСЕ сделки (вкл. уже записанные с кривым created_at). Backward-skew (часы отстают→лишние бары до входа) — TODO, отдельная гипотеза. Корень #1910, OPS-01a остаётся финальной страховкой | `trade_simulator.py:1923-1944` |
| **OPS-04** | 🟠 R | авто-рестарт `monitor_market` при необработанном исключении (тихая остановка) +… | 🟠 РЕАЛЬНА (но `except:pass` в monitoring НЕ найден — проверить) | `bot/core/bot.py:107` |
| **OPS-06** | 🟡 R | ✅ LIVE-GUARD ТАЙМАУТ (12.06, v2 — перенесён в position_sync): корень orphan-… | 🔴 РЕАЛЬНА (ЖИВА) | `order_manager.py:727`, LIVE-GUARD `trade_simulator:~2493` |
| **OPS-05** | ✅ **ЗАКРЫТ (12.06 verified): параллелизация В ПРОДЕ.** grep подтвердил: `asyncio.gather(*[_proc(t)...])` + `Semaphore` в `check_open_trades_with_tsl` (trade_simulator:1778/2798), вызов из `trade_tracker.py:48`. Smoke доказан 09.06 (baseline≡параллель). Saturation лечится — статус висел 🔴 ошибочно (применён давно). _pivot_calc Lock отложен (гонка редкая). **Текущий drift 76 — НЕ saturation, а OPS-06** (zombie/sync). | ✅ закрыто (verified) | `trade_simulator.py:1778,2798` |
| **ML-01a** | 🟠 M | `cross_val_score` K-Fold → **TimeSeriesSplit** (утечка будущего на автокорр. рядах) | 🟠 РЕАЛЬНА | `r_predictor.py:68`, `outcome_predictor.py:224` |
| **ML-01b** | 🟠 M | замерить ЧЕСТНЫЙ AUC на TimeSeriesSplit; если ≈0.5 → НЕ подмешивать ML в `confidence` (сейчас 0.7×orig+0.3×P(win)=шум) | 🟠 РЕАЛЬНА | `trading_intelligence.py` confidence |
| **ML-01c** | 🟠 M | selection bias: убрать `AND max_R_possible>0`, таргет = **realized R**, не MFE-идеал (Kelly завышает размер) | 🟠 РЕАЛЬНА | `r_predictor.py:96,107` |
| **ML-01d** | 🟠 M | `regime` на инференсе (сейчас `regime=None`→one-hot `[0,0,0,0]`, 4/12 фич нулевы… | 🟠 РЕАЛЬНА | `trading_intelligence.py:691`, `outcome_predictor.py:201` |)
| **T-01** | 🟡 T | god-objects: разнести `dashboard_server.py` (2351 стр) + `trading_intelligence.py` (2789!) | 🟡 РЕАЛЬНА | — |
| **T-02** | 🟡 T | удалить мёртвый `bot/main.py` + `infrastructure/`/`presentation/` (Clean-Arch скелет, ~300 стр) | 🟡 РЕАЛЬНА | `bot/main.py` |
| **T-03** | 🟡 T | TTL/maxsize для `_last_signal`/`analysis_cache` (растут без лимита) + `asyncio.Lock` на CircuitBreaker/OhlcvCache | 🟡 РЕАЛЬНА | `bot/core/bot.py:75`, `api_engine.py:31` |
| **DOC-SYNC** | 🟡 T | регулярное обновление `current_state.md`/`whats-next.md` (косяк: аудит читал уст… | 🟡 НОВАЯ | — |)

**Спринты:** 🔴 **S** (Security, 1-2 дня, SEC-01a сразу=1 строка) → 🔴 **R** (Reliability/анти-#1910, критично деньги) → 🟠 **M** (ML-честность, неделя) → 🟡 **T** (техдолг, фон). **Старт: SEC-01a (bind) + OPS-01a (sanity-guard) — обе про потерю денег/безопасность.**

---

## 🖥️ ЭПИК DASHBOARD — Полноценное приложение (проектирование, 10.06.2026, инициатор ARCH)

> **Скелет:** [`docs/DASHBOARD_EPIC.md`](docs/DASHBOARD_EPIC.md). Цель юзера: дашборд → полноценное приложение, доступ С МОБИЛКИ ОНЛАЙН через сервер (PWA), хороший дизайн (инструмент: v0.app).

**Текущее (разведка 10.06):** API aiohttp ~45 роутов (god-object 2356 стр) + Vue-зачаток `/v2` (DEV-144 Stage-1) + auth почти НЕТ + **дашборд ЗАБЛОКИРОВАН как потребитель биржи** (live-роуты дёргали биржу напрямую → отъедали rate-limit торговли).

**🔴 РАЗВИЛКА (Phase 0, решение юзера):** v0.app генерит React/Next.js, текущий v2 = Vue → конфликт. **Рекомендация: вариант B (Next.js+Vercel)** — v0 нативно, мобильный/PWA из коробки = ровно цель юзера; Vue-зачаток мизерный, не жалко.

**Фазы:** 0 Решения (стек/деплой/auth) → 1 API-слой (вынести из god-object=**T-01**, версионировать, **live-роуты на БД/кэш = снять блокировку биржи**) → 2 Auth (**SEC-01b/c** вливается, ОБЯЗАТЕЛЬНО до выставления наружу) → 3 Фронт (v0→Next.js) → 4 Live (SSE/WS) → 5 Деплой (Cloudflare Tunnel+Vercel, HTTPS) → 6 PWA-polish.

**🔴 ИНВАРИАНТ:** дашборд читает ТОЛЬКО из БД/кэша, НИКОГДА не дёргает биржу сам (один владелец rate-limit = торговый цикл). **SEC-01b/c НЕ делать раньше Phase 2** (вольётся в auth нового API; сейчас держит `127.0.0.1`).

---

## 🎨 ARCH-128: Воспроизведение OKO-SM + parity детекторов (03.06.2026, инициатор ARCH)

| ID | Ст | Описание | Роль |
|---|---|---|---|
| ARCH-128-S3 | 🔄 | **Шаг 3: ре-майнинг** на 75 признаках. A=Claude (ре-чек 215 текущих), B=DS-315 (полный walkforward+MHT). Интерпретация+калибровка OTE/EQH = Claude | DS+Claude |
| ARCH-128-OOS | ❌ | **OOS-аудит: EDGE = MIRAGE.** 4h→5m config-канон: IN (73 trades) +$228 WR37% → OUT (50 trades) +$13 WR22%. target_-1.618: +$13 (шум). runner_choch: +$174 → -$107. Вердикт: переподгонка под pre-2026. →DISCUSSION 26.06 21:00 | DS ✅ |
| ARCH-128-OOS-NESTED | 🟢 | **OOS: EDGE РЕАЛЕН.** 7/9 (78%) OOS-кварталов +, avg +0.180R. 2026Q1 +0.318R, 2026Q2 +0.339R. NOT a mirage. TP@1R чемпион. →DISCUSSION 26.06 22:30 | DS ✅ |
| **🧹 DS-MAINTENANCE (03.06)** | | | |
| **DS-321** | 🚀 | **TSL гибридная коробка в проде:** `tsl_hybrid_enabled=true`, Gear 1/2/3, откат через config. Backtest +1.95R, 68% pos | DS |
| **DS-325** | 🟢 **Ф1+Ф2 ГОТОВО (DS 14.06).** Файл: `core/infra/pydantic_config.py`. OkoConfig: 6 domain-моделей + 30 Dict-секций, `extra="forbid"` (поймал 30 неучтённых полей → добавлены в схему). `ConfigProxy.get("a.b.c")` совместим с ConfigLoader. Поглощён `config_validator.py`. `strict=True`: config.yaml проходит чисто. `requirements.txt`: pydantic>=2.0.0 + pydantic-settings>=2.0.0. **НЕ сделано:** Ф3 (миграция callsites), перестройка config.yaml. | 🟢 done (Ф1+Ф2) | `core/infra/pydantic_config.py` |)
| ARCH-128-ENGINE | 🔄 | **OTE-Retest Engine + Фрактальный Куб** (ВХОД-движок): слом→импульс→OTE→ретест→вход+SL. Ядро `ote_retest_setups`. **Исследование 03-04.06 (бэктест 5 пар) → `docs/RESEARCH_OTE_CUBE_2026-06-03.md`:** вложенность HTF-зона×LTF-слом=риск ×10; частичный TP1=1R лечит WR(12→72%); матрица оптимум 4h→15m(+0.471); каскад глубина=качество; двунаправленность (откаты ≥ продолж, 4h→5m откат +1.128 WR83%); дивергенция только В OTE; инвалид-SL(1.0)=неперекрытие Эллиотта; сверка с DS-316 сошлась на 15m. TP→TPSelector(вклад: отриц.фибо+EQL/FVG), TSL→tsl_updater, SL→ExitManager Ph2. **NEXT:** вход=LTF-слом в OTE+дивергенция; подтвердить 5m-откат на 45 парах. `memory/ote_nested_mtf_strategy.md` | Claude |
| **ARCH-128-MON** | ⏳ | **Мониторинг качества OTE / Premium-Discount** — периодическая отрисовка фибо на чартах для визуальной сверки (правильно ли определяются OTE-зона и premium/discount). Контроль эталона после изменений | Claude |
| **ARCH-128-C01** | 🔴 **ВОССТАНОВЛЕН 02.09 в новой формулировке** | Снимал как «неверное понимание» — **поспешил, Егор поймал**. Суть верна: матрица НЕДОБИРАЕТ структурные события. Механизм: `swing_bridge._get_choch_length()` → `config.yaml arch104.choch_length: 50`, то есть `etl_bos_choch` считает ТОЛЬКО старший слой. Замер 02.09: micro/swing = **8.8:1** → матрица видит **~11%** структурных событий. Следствие: `bull_choch`/`bear_choch`/`bull_bos`/`bear_bos` производятся, но **ни один из 200 паттернов на них не отобрался** — событий не хватает на порог n≥30. 🔑 Правильное решение НЕ «сменить 50→5», а отдать ОБА слоя разными признаками (`*_choch_swing` и `*_choch_micro`): эталон считает их одновременно, бесплатно. **Это и есть основание для ре-майнинга** — не пересчёт старого, а первая подача микроструктуры. | [[smc_canon_engine_is_oko_sm]] |

---

## 🧊 Stabilization Sprint (04.05–25.05.2026) — заморозка vision

**План:** [`/root/.claude/plans/fluttering-snacking-whale.md`](/root/.claude/plans/fluttering-snacking-whale.md) — «Возврат управляемости».

**Корень:** в БД попадает ~4% детектируемых сигналов, остальные 96% теряются молча. ML обучается на 30-40% данных. `decision_trace.py` готов, но в `_broadcast_intelligence_alert` не вызывается. Сначала видимость, потом архитектура.

🔴 **ЗАМОРОЗКА ИСТЕКЛА (срок был ~25.05, сейчас 02.09 — три месяца).** Заморожены были: ARCH-74-EXT, ARCH-96..99, ARCH-101..104, ARCH-105..111. Статус каждой НЕ проверялся — при следующем заходе либо разморозить и переоценить, либо снять окончательно. Держать «заморожено» с истёкшим сроком хуже, чем закрыть: выглядит как живая задача, но никем не ведётся.

**Фазы:**
- **Phase 0** (1-2д): DecisionTrace в 14 gates → таблица `signal_drops` → дашборд топ-10 reasons
- **Phase 1** (2-3д): `audit_mode` shadow + `audit_trades` → отчёт `audit_filter_efficacy.py`
- **Phase 2** (3-5д): coverage matrix + alerts на коллапс данных + ML skipped-rows visibility
- **Phase 3** (5-7д): `bot/loops/broadcast_pipeline.py` + 14 gate-файлов + тесты

**Критерий выхода:** monitoring.py < 800 строк, coverage critical полей ≥ 90%, 7 дней без регрессии avgR.

---



---

# 📦 Август–сентябрь 2026 — разделы, свёрнутые 19.10.2026

> Перенесено из `TASKS.md` при разборе актуальности. Это планы исследований: по каждому
> вердикт вынесен и лежит в памяти, а план продолжал выглядеть открытой работой.
> Основания — `docs/TASKS_AUDIT_2026-10-17.md` § «Батч 3». Живое осталось в `TASKS.md`:
> FIX-ONCHAIN-COLLECTOR, FIX-SPHERE-NUM. Уникальные таблицы реестра перенесены
> в `docs/REGISTRY.md` § 3.6. Текст ниже — как был, ничего не правлено.

## 🧊 HYPERCUBE-EXP: 8 ЭКСПЕРИМЕНТОВ НА ГИПЕРКУБЕ (10.09.2026)

> **Основание:** потолок информации гиперкуба измерен — `I(ячейка; знак) = 0.0055 бит`,
> потолок точности 55.6% против необходимых 62.9%. Направление в ценовой структуре
> закрыто МАТЕМАТИЧЕСКИ. Но потолок посчитан только для ЗНАКА — для других задач не мерен.
> Детали: [[hypercube_information_ceiling]] · [[hypercube_scale_step_is_12x_not_4x]]
>
> **Что стоит твёрдо:** ось = окно детектора (не ТФ) · вложенность `R ≥ 0.85` → 95-97%,
> воспроизведено трижды · зеркальность +0.885 · 228 ячеек из 2187 · размерность 6.3 из 7.

| ID | Ст | Краткое (≤80 символов) | Роль |
|---|---|---|---|
| [HYP-3](#hyp-3) | 🔄 | Кросс-монетный куб: ячейка ВСЕГО рынка, а не монеты | ARCH |
| [HYP-4](#hyp-4) | 🟢 | Куб переходов: скорость обхода ячеек как признак | ARCH |
| [HYP-5](#hyp-5) | 🔵 | Куб как признак для модели, не как правило (one-hot 228) | DEV |
| [HYP-6](#hyp-6) | 🟢 | Классификация состояний вместо предсказания цены | ARCH |
| [HYP-7](#hyp-7) | 🔄 | Та же машинерия на OI/фандинге — **27.09 ИЗМЕРЕНО (предварительно):** фандинг 2022–26 сверх цены +0.0003–0.0007 бит (жил в 2022/2024, в 2025–26 ≈0); OI 23 дня — на уровне шума, знак прибавки меняется между половинами монет. **Осталось:** OI на 4 годах из Binance metrics (история есть с 2022), позиционирование как фильтр механик, хвосты. `scripts/{oi,funding}_info_ceiling.py`, память `positioning_layer_info_ceiling` | ARCH |
| [HYP-8](#hyp-8) | 🔵 | Детектор аномалий: 89% пространства пусто | ARCH |

### WT-СХЕМА ЕГОРА (вне списка HYP, замерена 10.09.2026)

Схема: кросс WT в зоне OS/OB на старшем (4h) = разрешение на LIFE=12 баров →
вход на младшем (1h) по пересечению медианы WT(34) → выход разворотом в
противоположной зоне. 314 монет, 1h-кэш 2022-2026 (МЕДВЕДЬ/БЫК/нейтраль/МЕДВЕДЬ/МЕДВЕДЬ).

| что | статус | результат |
|---|---|---|
| как стратегия | ✅ ЗАКРЫТА ОТРИЦАТЕЛЬНО | безтоп10% отрицателен во всех 64 конфигурациях стоп×таймаут |
| короткий структурный стоп | ✅ ЗАКРЫТ | выбивается в 87% при стопе 0.53%, срезает 66% сделок по −2.244% |
| «вход не в воздухе» | ✅ ЗАКРЫТ | ≤0.5 ATR −0.210% против >2 ATR −0.273%, все корзины в минусе |
| расширение дельты на HTF | ✅ ЗАКРЫТО | сужается +1.110% против расширяется +1.121% = ноль |
| превышение над базой, long | 🟡 кандидат | +1.392 п.п., 4/5 лет; абсолют всё равно отрицателен |
| превышение над базой, short | ✅ закрыт | +0.154 п.п. = нет |
| схема поверх геометрии стенда | 🔴 СЛЕДУЮЩЕЕ | база стенда неотрицательна, в отличие от «держать до перекупленности» |
| LIFE / MED_LEN / порог зон | 🔴 НЕ проверено | ни один из трёх не варьировался |

Детали и три снятых промежуточных вывода: [[wt_htf_zone_median_scheme_measured]]

**Порядок:** 1 и 2 считаются за час на готовых данных · 3 требует пересборки куба ·
7 — единственный, где потолок неизвестен, и потому единственный с шансом на другой порядок.

**Обязательные критерии для любого результата (введены 09-10.09):**
зеркальность (обе стороны) · IS→OOS · охват >60% монет · медианы >0 ·
🔴 проверка момента доступности признака (утечка вида 6 поймана дважды за сессию).

---

## 🔍🔍 ARCH-138: ИТОГИ ЧЕТЫРЁХСТОРОННЕГО АУДИТА — 4 эпика (04.09.2026)

> Полные находки: **[docs/AUDIT_FINDINGS_04SEP.md](docs/AUDIT_FINDINGS_04SEP.md)**
> Гипотезы поиска: **[docs/HYPOTHESES_AUDIT_04SEP.md](docs/HYPOTHESES_AUDIT_04SEP.md)**
>
> Аудит: документация · память (45 topic) · боевые данные (56 695 сделок) · инструменты Куба.
> Перекрёстная проверка агентами + рой. Из 6 гипотез предварительного ранга **4 имели дефект**.
> Порядок эпиков обоснован фактом: за 03–04.09 трижды поймали артефакт в своих же замерах
> и дважды переоткрыли записанное — потери от состояния фундамента, не от нехватки идей.

| ID | Ст | Краткое | Роль |
|---|---|---|---|
| [ARCH-138-A](#arch-138-a) | 🔄 | ЭПИК A: накопление данных — OI ✅, стакан ✅, order flow | DEV |
| [ARCH-138-B](#arch-138-b) | 🔄 | ЭПИК B: разблокировать написанное — micro ✅, sc_* ✅, CANDLE+VOL, ATR-перцентиль | DEV |
| [ARCH-138-C](#arch-138-c) | 🔴 | ЭПИК C: хардкоды и кривые детекторы (H-01..H-06, F-01..F-08) | DEV |
| [ARCH-138-D](#arch-138-d) | 🔵 | ЭПИК D: поиск по отобранным гипотезам — после A+B | ARCH |
| [ARCH-138-S](#arch-138-s) | 🟡 | СФЕРЫ: 4 сломаны/shadow, 5 отсутствуют, шина видит только свечи | ARCH |
| [ARCH-138-DOC](#arch-138-doc) | 🟡 | ДОКУМЕНТАЦИЯ: 9 расхождений с замерами (D-01..D-09) | ARCH |
| [ARCH-138-T](#arch-138-t) | 🟢 | ТЕРМИНАЛ: детектор ШИРИНЫ РЫНКА на :8010/filter | DEV |

### ARCH-138-A
ЭПИК A — накопление данных. ✅ **OI**: `radar_state` имел `symbol PRIMARY KEY` (состояние,
не история) → добавлена append-таблица `oi_history`, поллер перезапущен 04.09.
✅ **Стакан**: `core/exchange/depth_snapshot.py` — снимок глубины в момент регистрации сделки
(fire-and-forget, троттлинг 20 с/символ). Метрика `cost_to_move` = сколько $ сдвигают цену
на 0.1% — прямая мера исполнимости лимитки; закрывает нехватку данных для вычета
adverse selection и несведённую ось ликвидности (5 замеров, 3 прокси, взаимоисключающие).
🔵 Остаётся **order flow / CVD** (`aggTrades` WS, копить с нуля).
🔴 Срочность эпика календарная: данные нельзя догнать задним числом.

### ARCH-138-B
ЭПИК B — разблокировать написанное. ✅ **микро-слой + согласование масштабов**: собраны
поверх ЭТАЛОНА (`swing_bridge`, не копией research-кода — иначе третий движок структуры).
Замер на 1h: `sc_pullback` **16.30%** баров, `sc_resume` **54.64%** против 0.04–0.20% у
swing-сломов. Матрица впервые получила СОСТОЯНИЕ («где мы внутри структуры»), а не редкое
событие. Признаки названы заранее (`matrix_full.py:476`) → защищены от подгонки.
🔵 Остаётся: CANDLE+VOL (в бою объём = 1 флаг `vol_spike`), ATR-перцентиль (U-03, U-04).

### ARCH-138-C
ЭПИК C — единство источников. **Хардкоды:** фандинг-вето `0.0` (1.5 млн строк истории мимо
боя) · `min_stop = max_stop = 4.0` у bigflush15 (0 сделок с 13.08) · канон OTE в ТРЁХ местах ·
режим в 3 методах и 6+ местах · «кластер» в 3 несовместимых определениях · два формата
`created_at` (NaT у 53 355 из 56 448 записей).
**Кривые детекторы:** `active_order_blocks` не каузальна (4–5 баров из 19 851) ·
`detect_fvg` порог по всему ряду · `mitigated_idx`/`is_breaker` смотрят вперёд ·
`detect_equal_levels` инвариант сломан (134/134) при том, что EQH боевой ·
zigzag перерисовывает 40–73% событий.

### ARCH-138-D
ЭПИК D — поиск. Отобрано после перекрёстной проверки и роя: **Г1** широкая зона отката
(сначала забрать shadow `ote_cell_shadow`, копится с 11.08, + перестановочный контроль на
53 ячейках) · **Г2** `sc_pullback`/`sc_resume` (названы заранее) · **Г3** пересечение OB×свип ·
**Г4** лимит на откате, расщепить на тип ордера и геометрию, вычесть adverse selection ·
**Г5** адресный разбор `atr_change` (не отключать по среднему — разрез по стопу).
🔴 Снято с ранга 1: **кластер** — в бою отсёк 143/144 = 99.3% при бэктестовых 12%,
корень в асинхронной детекции на незакрытом баре.

### ARCH-138-T
ТЕРМИНАЛ — детектор ширины рынка на `:8010/filter` (`web/structure_terminal.py:742`).
Сейчас фильтр отвечает «какие монеты подходят под условия», но НЕ отвечает «широкий ли
сейчас залив» — а именно ширина оказалась единственным гейтом с четырьмя независимыми
подтверждениями (+2.24 rangefade · +3.27 1h long · +1.29 15m short · +1.17 atr_s2).
Данные уже в шине (`_fetch_snap`), считать нечего: сгруппировать прошедших по метке бара,
показать число монет и число РАЗНЫХ СЕМЕЙСТВ (боевой гейт требует ≥2 семейств — 04.08
пришёл псевдо-кластер NCSKTM2USD/NCSKPL2USD/… = одна обёртка, не рыночное падение).
🔑 Смысл: видеть ширину глазами, а не только в логах бота.

### ARCH-138-S
СФЕРЫ. Работают 9 из 20. Сломаны/shadow: 3 и 4 (ML — хуже монетки, после `_v=2` ноль
записей при `MIN_TRADES=50`) · 5 (не публикует `CROSS_MARKET`) · 10 (монолит в
`trade_simulator`) · 13 Phase (логирует, не гейтит) · 19 (в бою с 01.09, читателей нет) ·
20 WaveService (считает — никто не читает). Отсутствуют: 14 Execution · 15 Anomaly ·
16 Portfolio · 17 Meta-Learning · **18 Setup Engine** (описан в `TRADER_VISION`, не начат).
Шина видит только свечи: 213 из 230 признаков мимо неё — не блокер поиска, но блокер
торговли найденного.

### ARCH-138-DOC
ДОКУМЕНТАЦИЯ — 9 расхождений с замерами. Главные: вердикт по EQH устарел на следующий
день после записи (индекс `MEMORY.md` тоже) · метка «бычий 2023» отменена автором, но
живёт в 5+ файлах · `BEARBOS_COUNTER_LONG` помечен «подтверждена данными» при отсутствии
бэктеста · канон 0.618–0.786 не имеет первоисточника-замера и расходится с эталоном
`build_ote` · фандинг в `TRADER_VISION` назван приоритетом №1 после того, как замер его
отклонил · раздел свечных моделей пуст с 03.06, а признаки уже посчитаны.

---

## 🌐 ARCH-129: MARKET DATA SPHERE (Сфера 19) — внешние данные в шину (27.08.2026)

> Повод (Егор): «все в шину! Куб должен работать по полной! сферы их не видят, а ведь
> должны». Сверка показала: **213 из 230 признаков боевых решений идут МИМО шины** —
> Куб видит только свечи. Подробно: `docs/REGISTRY.md` § 3.5 · [[bus_sees_only_candles]]

| ID | Ст | Краткое | Роль |
|---|---|---|---|
| [ARCH-129](#arch-129) | 🔄 | Market Data Sphere (19): фандинг · OI · доминация · onchain · mcap → в шину. **🟢 В БОЮ с 01.09 22:44** — `market_data_loop` подключён, SelfTest 12/12, позиции целы (OPEN 36/37, PENDING 12/12), два цикла подряд по 106 пар. Только публикует, НЕ гейтит | ARCH/DEV |
| | | | |
| | | | |
| | | | |
| [ARCH-129.1](#arch-129-1) | 🔶 | **ЯДРО СДЕЛАНО 01.09, к боевому пути НЕ подключено** (бот торгует). `core/context/market_data_sphere.py` + 9 полей в `PairState` + событие `FUNDING_UPDATED`, тесты 17/17, поля доезжают 7/7. 🔴🔴 Вскрыто: **вето по фандингу мертво ДВАЖДЫ** — вход захардкожен `0.0` (`arch104_observer_loop.py:290`) и единицы разошлись (ccxt/таблица дают ДОЛЮ, порог ждёт ПРОЦЕНТЫ → мягче в 100×: 0.24% против 13.43% срабатываний). [[bug_funding_veto_dead_and_units]] | DEV |
| | | | |
| [ARCH-129.5](#arch-129-5) | 🔶 | Производные реализованы (`streak`/перцентиль/`cum_3d`), но 🔴 **«серия» как гейт НЕ ГОДИТСЯ**: \|серия\|≥3 = 76.4% расчётов, ≥20 = 43.1%. Фандинг устойчив по знаку — серия это норма, а не событие. Нужен другой порог (связка с перцентилем или РАЗВОРОТ серии) | DEV |
| | | | |
| [ARCH-129.2](#arch-129-2) | 🔶 | **ПОСТАНОВКА БЫЛА НЕВЕРНА — таблица ЕСТЬ.** `oko_feed/external_data.db → oi_snapshots`: **145 166 строк**, 18 символов, 2026-07-02 → сегодня, сбор идёт (`oko_feed/collectors/oi.py`, Binance). Квадрант OI×цена тоже уже есть (`radar_state.quadrant`, 12.07). 🔴 Ловушка: в КОРНЕ лежит пустышка `external_data.db` на 0 байт — открыв её, видишь «таблиц нет» (класс OPS-ROOT-DBCOPIES). Сделано 01.09: 5 полей OI в `PairState`, событие `OI_UPDATED`, `publish_oi` + толкование сквиза; на живом снимке 389 символов — 20.8% short_squeeze, 14.4% long_flush, 64.8% подтверждено. Тесты 23/23. 🔴 Предсказательная сила НЕ измерена; к `scan_loop` не подключено | DEV |
| | | | |
| | | | |
| [FIX-ONCHAIN-COLLECTOR](#fix-onchain-collector) | 🟡 | Сборщик onchain: 48.5% дублей · БИТКОЙНЫ в поле `amount_usd` · сломан `symbol` | DEV |
| | | | |
| [ONCHAIN-REMEASURE](#onchain-remeasure) | 🟢 | Разбор onchain ПОСЛЕ починки: окно ≥120 дней, крупные тx, альты | DEV |
| | | | |
| | | | |
| [ARCH-129.5](#arch-129-5) | 🔴 | **ПРОИЗВОДНЫЕ, а не сырые числа**: `funding_streak` · перцентиль · `oi_price_regime` | DEV |
| | | | |
| | | | |
| [FIX-SPHERE-NUM](#fix-sphere-num) | 🟡 | Конфликт нумерации: ARCH-96 (Execution) и ARCH-121 (WaveService) обе «Сфера 14» | ARCH |

> **🔴 Подтверждение задачи живой сделкой (30.08.2026, HYPE).** Разбор вручную показал, ЧТО
> именно теряется без этой сферы: пробой плиты EQH на объёме 2.11× по всем шести боевым
> источникам выглядел СИЛОЙ (цена↑, объём↑, WT↑) — а OI в тот час **падал**, то есть это был
> сквиз шортов. Движение умерло за два бара. Шесть ценовых источников не могли этого увидеть
> в принципе. Фандинг BingX предупреждал о сквизе **за 12 часов** серией −0.0060 → −0.0097 →
> −0.0078 → −0.0064 при медиане +0.005%, но боевое вето (`risk_intelligence`, порог
> \|f\|>0.03%/8ч) такого не ловит: сигнал был не в УРОВНЕ, а в СЕРИИ.
> Детали: [[gap_positioning_layer_missing]] · спека → `docs/TASKS_DETAILS.md` § ARCH-129

## 🔴🔴 ARCH-137: ДВА ПАРАЛЛЕЛЬНЫХ SMC-НАБОРА — нарушен закон reuse ≠ дублирование (01.09.2026)

> Повод (Егор 01.09): «других реализаций быть не должно, есть правила в проекте».
> Найдено при разборе, каким инструментарием я вёл анализ HYPE, — оказалось, что мой набор
> и боевой это **разные функции с одним именем**. Проверено grep'ом, не по памяти.
> Закон: [[principle_reuse_not_duplication]]

**ТРИ реализации FVG с разными контрактами:**
`indicators.py:206` (только 3 последних бара → `(str, float)`) · `smc_engine.py:540`
(LuxAlgo, история + mitigation → `List[tuple]`) · `fvg.py:259` (→ объект `FVGAnalysis`).

**Дублируется ВЕСЬ базовый набор:**

| Детектор | Набор A — `smc_engine.py` (64 КБ) | Набор B — модульный (~66 КБ) |
|---|---|---|
| FVG | `:540` | `fvg.py:259` (+ `indicators.py:206`) |
| Order Blocks | `:166` | `order_blocks.py:228` |
| Equal H/L | `:416` `detect_equal_levels` | `liquidity.py:240` `detect_equal_highs_lows` |
| Swings | `:71` `detect_swings` | `swing_points.py:252` `detect_swing_points` |
| Structure | `:103` `detect_structure_breaks` | `structure.py:342` `detect_structure` |

**Потребители разошлись, но НЕ по слоям:**
- A: `swing_bridge` · `chart_builder` · `oko_ote` · `ote_matrix` · `ote_signal_generator` ·
  `method_egor` · `method_v2` · `choch_wavec` · `choch_sl_transfer` — стратегии и графики
- B: `mtf_smc_specialist` · `pivot_reversal` · `liquidity_sweep_detector` · `cascade_tsl` ·
  `market_regime` · `confluence` — ML, сигналы, риск
- 🔴 `smc_snapshot.py` тянет из **ОБОИХ** — а именно он строит `smc_snap`, вход ML-сферы 4
- 🔴 `pivot_reversal.py` использует две разные FVG **в одном файле** (:153 и :163)

### ✅ ARCH-137.1 ЗАКРЫТ 02.09.2026 — эталон определён ФАКТАМИ

Замер: 18 пар · 1h · 400 баров · матч событий **по ЦЕНЕ уровня** (±0.05%).

| сравнение | событий | матч по цене | тип BOS/CHoCH совпал |
|---|---|---|---|
| **`oko_sm_engine` ↔ `smc_engine`** | 393 / 354 | **354 = 100% от A** | **349/354 = 99%** |
| `smc_engine` ↔ БОЙ (`structure.py`) | 354 / 455 | **57 = 16%** | 34/57 = 60% |
| `oko_sm_engine` ↔ БОЙ | 393 / 455 | **64 = 16%** | 34/64 = 53% |

**Вывод: два «правильных» движка — фактически один** (сдвиг индекса 0 в 348 случаях
из 354). Расходится только третий, тот что в бою.

🔴 **ПОПРАВКА 02.09 (Егор):** «движок считает структуру сразу с двумя длинами, 5 и 50 —
это детекция структуры и микроструктуры ОДНОВРЕМЕННО». Зафиксировано ещё 28.08 в
`docs/MATRIX_REGISTRY.md:146`. Первая редакция вывода называла корнем масштаб — **неверно**.

`run_structure` ведёт ДВА слоя разом, раздельные `trend`/`itrend`, флаг `internal` у события:

| слой | длина | событий (18 пар, 1h/400) | BOS / CHoCH |
|---|---|---|---|
| эталон · МИКРО | `internal_len=5` | 353 | **54% / 46%** |
| эталон · СТРУКТУРА | `swing_len=50` | 40 | **62% / 38%** |
| **БОЙ** (один слой) | `swing_period=5` | 455 | **29% / 71%** |

Микро/структура = 8.8:1 (сходится с 1006/126 от 28.08).

**Масштаб ни при чём:** микро-слой эталона на ТОЙ ЖЕ длине 5 даёт каноничные 54/46.

🔑 **НАСТОЯЩИЙ КОРЕНЬ — `structure.py:221-232`:** `if local_trend == BULLISH: BOS else: CHoCH`.
`_infer_local_trend` даёт направление только при чистых HH+HL / LH+LL, иначе `NEUTRAL`,
а при <3 свингов `None`. Замер на 250 пробоях: NEUTRAL **34.4%**, None **10.8%**.
🔴 **45% сломов метятся CHoCH не потому, что рынок развернулся, а потому что движок
не смог определить тренд.** Молчаливый отказ: неизвестность оформлена как факт.

Бой не соответствует НИ ОДНОМУ слою: с микро совпало 16%, со структурой 20% (тип 0/8).
**Старшего слоя у боя нет вовсе.** Двухслойность конструктивна: при `swing_len=internal_len=5`
микро-слой даёт **0 событий**.

📊 Визуально: артефакт «Проверка детекторов глазами», секция C-02.

<details><summary>Первая (ошибочная) редакция вывода — про масштаб</summary>

| движок | дефолты | масштаб |
|---|---|---|
| `smc_engine.detect_structure_breaks` | `length=50, vol_len=20, vol_mult=1.2` | swings-**50** |
| `oko_sm_engine.run_structure` | `swing_len=50, internal_len=5` | **50 + internal 5** |
| `structure.detect_structure` (**БОЙ**) | `swing_period=5, min_distance_bars=3` | swings-**5** |

Подгонка параметра НЕ лечит: `detect_structure(swing_period=50)` даёт 24 события
и **0 матчей по цене** — реализации расходятся принципиально.
</details>

🔴 **Следствие:** все находки по структуре (CHoCH ×3.68, BOS-гейт, волны ARCH-137)
меряны эталоном, а бой читает третий движок — **перенос находок в бой не гарантирован**.
Затронуты: ML-сфера 4 (`smc_snap`), **режим** (`market_regime.py:266`),
**TSL** (`cascade_tsl.py:102`), `signal_checkers.py:468`, `mtf_smc_specialist.py:128`.

🪤 **Ловушка (стоила неверной цифры):** первый прогон матчил по ИНДЕКСУ бара и дал
«57% согласия». Номера баров случайно совпадают при разных уровнях. По цене общих
событий 16%, не 58%. **Детекторы сравнивать только по цене/уровню.**

📜 **История — правило не нарушали, миграцию не довели.** 22.03 создан модульный набор;
02.06 ARCH-128 сделал порт OKO-SM/LuxAlgo 1:1; 03.06 переименован в `smc_engine`
с формулировкой в DISCUSSION: *«ровно инвариант ARCH-118 „один калькулятор"»*.
Коммит: *«переименован, пока 0 импортов в проекте»* — эталон применили к DS-пути
(признаки/combinator), боевой скан остался на мартовском наборе.
🔴 В MEMORY.md ARCH-118 значился ✅ — исправлено на «наполовину».

Детали: [[smc_canon_engine_is_oko_sm]] · цена наборов: [[smc_set_b_40x_slower]]

| ID | Ст | Кратко | Роль |
|---|---|---|---|
| [ARCH-137](#arch-137) | 🔴 | Свести SMC к ОДНОМУ набору; канон = `oko_sm_engine`/`smc_engine`, остальное — тонкие адаптеры | ARCH |
| | | | |
| | | | |
| | | | |
| ARCH-137.5б | 🟡 | `last_break` = последнее событие ЛЮБОГО слоя, а их 9:1 в пользу микро. `market_regime` и `mtf_smc_specialist` читают именно его — им логичнее СТАРШИЙ слой. Правка логики потребителя, не источника | DEV |
| | | | |
| ARCH-137.6 | 🔴 | **ВЕСЬ вектор признаков сферы 4 — булевы «есть ли зона»** (8 из 9 полей). Перемер 02.09 опроверг гипотезу «дело в источнике»: на едином эталоне AUC **0.507** против **0.549** у старых, почти-констант стало **9/36** вместо 5. Причина: чем ЛУЧШЕ детектор, тем ближе признак к константе — `fvg_open` после починки FVG = **100% True**. Спрашивать надо: расстояние до зоны в ATR · возраст в барах · размер · глубину захода цены. Единственное непрерывное поле сейчас — `ob_distance_pct` | DEV |

### 💡 БЭКЛОГ: прокси для WS-подписок (апгрейд ProxyPool)

Вопрос Егора 02.09: «и ведь у каждого прокси есть подписка WS?» — **нет, не сейчас**.
Проверено grep'ом: в `market_ws_v2.py`, `market_ws.py`, `ws_feed.py` — **ноль** упоминаний
proxy. `aiohttp.ClientSession()` создаётся без него, значит ВСЕ WS-соединения уходят
с одного IP (VPN-выход), а купленные прокси обслуживают только REST market-data.

**Технически возможно:** `aiohttp` принимает `proxy=` в `ws_connect()`.
Пул уже умеет раздавать адреса (`ProxyPool.acquire`), нужен только проброс.

**Зачем может понадобиться:** обход лимита BingX на число WS-соединений с одного IP.
Сейчас 12 батчей по 50 пар × 3 ТФ. Если захотим больше пар, больше ТФ (1m для точного
отслеживания стопов) или second instance — упрёмся в этот лимит, и распределение
по 3 адресам даст ×3 запас.

🔴 **Сейчас НЕ делать — проблемы нет:** market-WS с одного IP держит стабильно
(rate 174–221/с, очередь ≈12, ошибок 0, обрывов 10 за день). Усложнять код
без причины не стоит. Триггер к работе: обрывы WS, отказы подписки, упор в лимит.

---

### 📊 ПЕРЕМЕР СФЕРЫ 4 (02.09.2026) — гипотеза ОПРОВЕРГНУТА

Метод: прямой перемер невозможен (snap в БД собран старым кодом до 31.08), поэтому
признаки пересобраны **задним числом** — те же 300 сделок, свечи строго ДО входа,
окно до 21.08 (граница кэша), три ТФ, WR 50%.

| набор | AUC | почти-константы |
|---|---|---|
| старые (как в БД) | **0.549** | 5 / 36 |
| новые (эталон) | **0.507** | **9 / 36** |
| смешанные (новые детекторы + старые eqh/eql) | 0.506 | — |

Разбор по признакам (доля True, старое → новое):

| признак | 15m | 1h | 4h | |
|---|---|---|---|---|
| **choch** | 73→47% | 62→47% | 79→51% | ✅ починен |
| **bos** | 26→53% | 36→53% | 9→48% | ✅ починен |
| `ob_bull` | 31→81% | 28→76% | 26→76% | 🔴 перекос |
| `fvg_open` | 97→**100%** | 94→98% | 88→99% | 🔴 константа |
| `eqh_near` | 82→**2%** | 56→**1%** | 32→**1%** | 🔴 убит отсевом снятых |
| `eql_near` | 80→3% | 55→**2%** | 32→**2%** | 🔴 то же |

🔴 **Правки детекторов откатывать НЕ нужно** — они сверены с Pine и устраняют доказанные
дефекты (CHoCH/BOS это подтверждают). Ломается слой НАД ними: `_build_smc_features`
спрашивает не то.

🪤 **Цифра 0.180 не подтвердилась** — на этой выборке старые дают 0.549. Переустановить
перед любой ссылкой на неё.

**НЕ проверено:** сторона · фаза рынка · боевые глубины окон (брал 200/200/150, бой строит
на 60/400/180 — самый вероятный источник искажения) · блок 1d (9 нулей у обеих сторон).

Детали: [[sphere4_features_are_binary_not_source]]

### 🏁 ИТОГ ARCH-137.5 (02.09.2026) — пять детекторов на едином эталоне

| детектор | было | стало |
|---|---|---|
| **structure** | 45% сломов метились CHoCH **от незнания тренда** (NEUTRAL 34.4% + None 10.8% падали в `else`); BOS/CHoCH 29/71 | 55/45, **два слоя** (micro 5 + swing 50) |
| **FVG** | фиксированный порог 0.05% | адаптивный (средний \|gap%\| × 2); зон 834→536, активных 140→165 |
| **order blocks** | ICT-определение; совпадало с тем, что РИСУЕТСЯ на графике, на 13% | LuxAlgo `ob_coord`; активных bull 33→89, bear 1→3 |
| **EQH/EQL** | **вырожден: 83-100% True**; сравнивались все high со всеми в окне 50 при фикс. 1% | пивоты + `atr×0.1`, сверено с Pine (95-97%), + отсев СНЯТЫХ |
| **swings** | свой pivot-поиск | `_swings_luxalgo`; 418→661 |

Флаги отката: `config.yaml → smc.{structure,fvg,ob,eq,swings}_canon`.
**Контракты сохранены везде — ни один потребитель не правился.**
Коммиты: `bf1f182` `3ae5907` `02a7e71` `0b941d3` `535e16a` `8f76c8b`.
Проверка: SelfTest 12/12 после каждого шага, smoke 6/6 потребителей, 6 рестартов
без потери позиций. Эффект в бою: BOS 28-32%→38%, EQH/EQL с 100% True до 10-30%.
| | | | |
| [ARCH-137.2](#arch-137-2) | 🔴 | **Гипотеза AUC 0.180**: `smc_snap` собирается из ДВУХ наборов, метки — со сделок набора A ⇒ модель учится на рассогласованных данных. Пересобрать снап на одном наборе → переобучить | DEV |
| | | | |
| [ARCH-137.3](#arch-137-3) | 🟡 | `indicators.detect_fvg` (3 бара) — примитив, не FVG по канону. Переименовать или удалить | DEV |
| | | | |
| [ARCH-137.4](#arch-137-4) | 🟡 | `pivot_reversal.py` — убрать двойной импорт FVG, оставить один | DEV |

🔑 **ARCH-137.2 — самая дешёвая проверка с самым большим выигрышем**: если AUC перейдёт 0.5,
сфера 4 оживает без нового кода. Сейчас MTF SMC AUC **0.180**, MTF WT **0.283** при монетке 0.5
([[ml_spheres_worse_than_coinflip]]), а ребро WT→TI вовсе разорвано
(`selftest_cube.py:462`: `predict` не вызывается, вердикт идёт от rule-based DEV-161).

## 🔴🔴 ARCH-134: ПЕРЕСЧЁТ ВСЕЙ МАТРИЦЫ НА БОЕВОМ ОКНЕ (29.08.2026)

> **Задача не закрывается, пока не проверены ВСЕ признаки** (решение Егора 29.08).

| ID | Ст | Кратко | Роль |
|---|---|---|---|

### ✅ ИТОГ ARCH-134

**1. Чувствительность измерена** (`window_sensitivity.py`, 219 признаков): зависимы 40,
и почти все — семья SMC-состояний (35 из 60). SCALES и WAVES — **0.0%**, старая матрица 4.4%.
Причина в природе признака: SCALES/WAVES спрашивают про ТЕКУЩЕЕ событие, SMC-состояния
считают НАКОПЛЕННЫЕ зоны.

**2. SMC пересчитан боевым окном** (`recompute_smc_live_window.py`, 6728 сделок, 11 мин).
Медианное совпадение версий **0.394** — больше половины информации было свойством длины
истории. Сверка с прямым вызовом: 60/60.

**3. 🔴 Главное — найдена ОШИБКА СРАВНЕНИЯ, из-за которой находка была ложно отменена.**
Матрица считает признаки со `shift(1)` (закрытый бар), а проверочный код смотрел последний.
Замер сдвига: `0 → ×1.20 · 1 → ×3.73 · 2 → ×2.05`. Физика: «цена БЫЛА у уровня и уже
отходит» = отбой; «цена У уровня сейчас» = касание, которое ещё может обернуться проколом.
🔑 **Урок: сравнивать можно только версии, совпадающие по ОКНУ и по СДВИГУ.**

**4. Находки перепроверены** на пересчитанной матрице (база `гейт+short` 2.40, n=939):

| ось | n | PF | подъём | безтоп10% | зеркало long | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|
| **EQH (порог 1.0)** | **310** | **5.39** | **×2.25** | **+1066** | **0.77** | ×3.01 | ×1.67 | **×1.31** |
| SC bear зона | 228 | 4.28 | ×1.78 | +559 | 0.96 | ×3.11 | ×1.39 | ×0.77 |
| swing MAJOR high | 41 | 7.99 | ×3.33 | +200 | 1.12 | мало | мало | мало |
| любая из трёх | 408 | 4.33 | ×1.80 | +1056 | — | | | |
| ни одной | 531 | 1.38 | — | −430 | | | | |

EQH — единственный, у кого **все годы положительны**, зеркало отрицательное (0.77 при
базе long 1.04) и OOS переносится (train ×2.48 → test ×1.99). В бою: `enabled: true`,
`tolerance_atr: 1.0`. Рестарт сделан, SelfTest 12/12.

**5. Пивоты 1W разобраны.** 1D устойчивы (0.0%), 1W — 97.5%: ресемпл брал ПЕРВУЮ неделю
окна обрезанной. Правка внесена (первый период отбрасывается) — теперь на окне 1000 баров
1W-пивоты не считаются вовсе вместо того, чтобы считаться неверно.
🔑 Отдельный вывод: **«боевое окно» не универсально**. В бою 1W-пивоты берутся запросом
недельных свечей (`get_weekly_pivots`, limit=10), где истории достаточно — для них правильная
модель боя это ДЛИННАЯ история, в отличие от SMC-зон. Смотреть надо, ОТКУДА в бою берётся
признак, а не механически применять окно ко всему.

| [ARCH-134.1](#arch-134-1) | 🔴 | Замер чувствительности каждого признака к окну | DEV |
| [ARCH-134.2](#arch-134-2) | 🔴 | Пересчёт зависимых признаков скользящим окном | DEV |
| [ARCH-134.3](#arch-134-3) | 🔴 | Перепроверка ВСЕХ находок сессии на пересчитанной матрице | DEV |

**Повод.** Находка EQH отменена при попытке ввода в бой: `detect_equal_levels` в замере
получал ПОЛНУЮ историю символа (~60 000 баров), а боевой runner подаёт `bars: 1000`.

| | n | PF | подъём | Жаккар версий |
|---|---|---|---|---|
| полная история (как мерилось) | 163 | 5.06 | ×2.11 | — |
| **боевое окно 1000** | 92 | **2.88** | **×1.20** | **0.131** |

Жаккар 0.131 означает, что это **почти разные признаки**, а не тот же с шумом. Плато по
окну отсутствует: `1000 → ×1.20 · 2000 → ×1.02 · 4000 → ×0.81 · 8000 → ×1.11`.

🔴 **Дефект СИСТЕМНЫЙ, а не про один признак.** Вся матрица (679 признаков) считается на
полной истории. Проверены на боевом окне ТОЛЬКО ТРИ: `SC bear` выжил (×1.61→×1.57),
`swing high` держится (n=56), `EQH` развалился. **Остальные ~90 новых признаков и весь
`combinator_core` не проверены** — значит под подозрением ВСЕ находки смены, включая
`churn` и «24 часа после импульса».

🔑 Но зависят от окна НЕ ВСЕ: rolling-метрики (ATR, WT, EMA, объёмные отношения, дистанции
до скользящих) по построению смотрят на последние N баров и от длины ряда не меняются.
Зависят те, что копят СОБЫТИЯ и УРОВНИ: свинги, структура, OB, FVG, EQH, Эллиотт, ноги.
Поэтому первый шаг — замер чувствительности, а не слепой пересчёт всего (он дорог).

**Инструмент:** `scripts/window_sensitivity.py` — считает каждый признак двумя способами
на одних барах и печатает долю расхождений: 🟢 ≤2% устойчивые · 🟡 2-20% шаткие ·
🔴 >20% мерить на полной истории нельзя.

**Критерий закрытия:** все признаки классифицированы, зависимые пересчитаны окном,
находки перепроверены на пересчитанной матрице. Согласуется с
[[law_reproduce_live_config_first]] и [[law_recorded_pf_needs_remeasure]].

## 🎯🎯 ARCH-137: ВОЛНОВАЯ СЕМЬЯ НА ЯДРЕ — ЕДИНСТВЕННОЕ НАПРАВЛЕНИЕ (31.08.2026)

### ✅ ВЕРДИКТ ВЫНЕСЕН 01.09.2026 — семья проверена целиком, доведена до конца

Критерии записаны ДО прогона: `obsidian/Research/2026-09-01-ARCH-137-Wave-Family-Criteria.md`.
Инструменты: `scripts/wave_family_run.py` · `_cells.py` · `_combo.py` · `_scale.py` · `_slices.py`.
Детали и числа: [[wave_leg_1h_long_candidate]].

**🟢 КАНДИДАТ В SHADOW — 1h long, `leg_minor_breaks_1h ≤ 5` И `leg_span_bars_1h ≤ 86`**
(«нога короткая и чистая»). Боевая зона: n=397, PF 5.55 против 2.67 = ×2.08, безтоп10%
+1183. Независимая широкая зона (4397 сд): ×1.53, безтоп10% **−1245 → +899**, зеркало
×0.70, **5 из 5 лет положительны**, монет 79 (66% в плюсе), без топ-10% +960%.
🔑 **Жаккар с дрейф-гейтом 0.08 — независимая ось**; волна БЕЗ дрейфа PF 6.43.
Причинность проверена ЗАПУСКОМ (0 расхождений из 25), P(шум)=0.000.
🔴 В 2025-26 на широкой зоне абсолютно убыточен (0.90 / 0.68) — подъём есть, денег нет.

**🔴 В БОЙ НЕЛЬЗЯ — 15m short.** Набор `leg_dir_4h>0` И `leg_span_bars_4h≥107` даёт
×3.25, но **без дрейф-гейта PF 0.91** (своего эджа нет), а как фильтр поверх боевого
режет деньги: дрейф один безтоп10% **+7002** → дрейф+волна **+4005** при PF 4.25→5.78.
Классический [[gate_threshold_frequency_vs_money]].

**🔑 Побочное, ценнее находок:** весь эдж ОБЕИХ сторон сидит в КЛАСТЕРЕ (одиночка
15m short PF 0.66 · 1h long 0.79; кластер 1.29 и 3.27) · вход ПРОТИВ ноги 4h сильнее
входа по ней (1h long: нога 1h вверх при 4h вниз → PF 4.86, n=580) · четыре «находки»
на 1h оказались ОДНОЙ осью (Жаккар 0.58-0.79).

> 🔴🔴 **ЭТО ЕДИНСТВЕННАЯ ЗАДАЧА В РАБОТЕ. Всё остальное — бэклог.**
> Повод: Егор 30.08 — «ты опять начал страдать херней и проверять все что только хочется
> и можется! У НАС ЕСТЬ ОСНОВА И НАМ НУЖНО НАЙТИ ЭДЖ».
> За 30.08 я открыл 7 направлений и не довёл ни одного ([[feedback_session_30_08_mistakes]]).

### ОСНОВА — что уже проверено на ядре и НЕ ТРОГАЕМ

| элемент | статус на ядре 97 монет | ТФ |
|---|---|---|
| дрейф-гейт `drift30≥5` | 🟢 PF **4.25**, монет 76/96, без топ-3 +10241% | 15m short |
| EQH-дверь, порог 1.0 ATR | 🟢 ×**1.89**, зеркало long ×0.85, P=0.000, 62/96 монет | 15m short |
| зона стопа 1.5-3.234 | 🟢 ОПТИМАЛЬНА для long (за пределами обвал) | 1h |
| глубина входа 0.382 | 🟢 ОПТИМАЛЬНА (0.382→2.57 · 0.5→2.19 · 0.75→1.45) | 1h |
| база 1h | 🟢 long PF 2.67, безтоп10% **+928** (на 15m −23717) | 1h |

**Основа рабочая. Нужен ЭДЖ — добавка к ней, а не пересмотр её.**

### ПОЧЕМУ ИМЕННО ВОЛНЫ — по данным, а не по желанию

Слепой отбор на ядре 1h (757 признаков, 1572 сделки) оставил **ДВА признака, и оба
волновые**:

```
leg_age_origin_1h        <= 89   PF 1.97  безтоп10% +12  охват 58%
leg_age_extreme_4h__from_4h >= 64  PF 1.70  безтоп10% +20  охват 62%
```

Хрупкость почти нулевая — как готовые находки не годятся. **Но семья себя показала:**
из 757 признаков выжили только эти два, и оба про ВОЗРАСТ НОГИ, причём один со старшего ТФ.
Это совпадает с тем, на что указывает Егор: «у нас разные ноги на разных ТФ + волны».

🔴 И это ровно то, что я в прошлой сессии **подменил**: мерил «завершённость импульса»
через сырой экстремум цены, хотя семья WAVES (42 признака на 1h) уже лежала в матрице.
Импульс `find_impulses` и волновая нога — разные объекты.

### ЧТО МЕРИТЬ (и ничего сверх этого)

1. **Вся семья WAVES по трём ТФ** — 15m / 1h / 4h на ядре, обе стороны, БЕЗ гейтов;
2. **вложенность**: нога младшего ТФ внутри ноги старшего (`__from_1h`, `__from_4h`) —
   не поодиночке, а КАК НАБОР (пункт 1.2 плана перепроверки: «290 признаков старших ТФ
   мерились поодиночке, набором — ни разу»);
3. **фаза ноги** как непрерывная шкала, не порог: где в ноге стоит вход
   (`leg_age_origin` / `leg_span_bars` = доля пройденного пути);
4. согласованность ног 15m↔1h↔4h: совпадают направления или расходятся.

### ОБЯЗАТЕЛЬНЫЕ РАМКИ (нарушение = повтор косяков 30.08)

- [ ] **критерии записать ДО прогона** — что считаем находкой, что отбрасываем;
- [ ] в КАЖДОМ выводе первой строкой: **ТФ · файл данных · n · детектор**;
- [ ] **зеркало обязательно** — если растут обе стороны, это среда, а не ось;
- [ ] **по годам на ядре** — состав фиксирован, но эпоха нет;
- [ ] множественность с поправкой на семью (перестановка берёт ЛУЧШУЮ из N клеток);
- [ ] механизм не объяснять, пока не измерен отдельно;
- [ ] новая ветка мысли → **в бэклог, не в работу**.

### Критерий закрытия

Либо кандидат, прошедший полный протокол (включая зеркало, годы, множественность,
месячную устойчивость) — тогда в shadow; либо честный вердикт «волновая семья эджа
не даёт», с перечислением проверенного и НЕ проверенного.

### 🚫 ЧЕГО НЕ ДЕЛАТЬ В ЭТОЙ СЕССИИ

Не трогать: OTE · конфлюэнцию · поток/геометрию · RS · пивоты (136.D) · остаток 136.E ·
ARCH-135 ФАЗУ 1. Всё это записано и подождёт.

---

## 🚨 ARCH-136: РЕВИЗИЯ НА ЯДРЕ — что принято на выборке из 40 монет (30.08.2026)

> 🔴 **Отдельно от ARCH-135 намеренно.** ARCH-135 — исследование «что вообще есть»,
> оно большое и медленное. Здесь — ревизия УЖЕ ПРИНЯТОГО, и часть этого торгует прямо
> сейчас. Разные цели, разная срочность, разные критерии закрытия. Смешивать нельзя:
> срочное утонет в большом.

### Повод: два вердикта отменены за один прогон

30.08 матрица прогнана на балансированной панели (97 монет, 27684 сделки против 40 монет
и 6730). **Обе long-находки предыдущего дня оказались артефактом выборки:**

| находка | 40 монет | **97 монет** |
|---|---|---|
| `rs_rank30 ∈ [26,48]` | зеркало ×0.62 🟢 | зеркало **×1.05** — ось двусторонняя |
| «пробой swing-минимума» | PF 1.83 ×2.04, P=0.000 | PF 0.88 **×0.84**, P=0.340 — знак перевернулся |

Обе прошли OOS, поправку на множественность, блочную перестановку и Жаккар — и все эти
тесты были ВЕРНЫ для тех монет. Ни один не проверяет репрезентативность вселенной
([[law_sample_representativeness]]).

🔴 **Источник ошибки общий:** главный прогон шёл `--symbols 40`. На той же выборке стоят
и другие принятые выводы.

### 🚨 Приоритет 1 — то, что ТОРГУЕТ ПРЯМО СЕЙЧАС

- [ ] **EQH-дверь** (`config.yaml:503`, `enabled: true`, `tolerance_atr: 1.0`, sides `[short]`)
      — включена 29.08 по замеру на `matrix_run_15m_lw` (40 монет). Перемерить на ядре
      **до того, как наторгует**, а не после. Вердикт по ней и так менялся ТРИЖДЫ;
- [ ] **дрейф-гейт** (порог 5.0) — установить, на какой вселенной калибровался, перемерить;
- [ ] **зона impulse_fib 1.5-3.234** — то же;
- [ ] остальные включённые источники: `rangefade`, BOS-гейт, `atr_change` S2, CHoCH→волна C.

**Критерий:** каждый боевой параметр либо подтверждён на ядре, либо снят/переведён в shadow.
Решение о снятии — Егора, моё дело принести числа.

### Приоритет 2 — ОТРИЦАТЕЛЬНЫЕ вердикты (возможно, важнее приоритета 1)

Отрицательный результат никто не перемеряет — поэтому ошибка в нём живёт вечно.
Доказательство, что это не теория: **база long на 40 монетах PF 0.89 (убыточна),
на 97 — PF 1.05 (прибыльна)**. Пол-сессии строилось на «база long убыточна».

- [x] ✅ **«0 из 446» СНЯТ 01.09** — на ядре по семьям выживает много (P=0.000 в каждой):
      `mkt_drift_slope` PF 5.17 безтоп10% +3723 · `st50_dir_x_age_4h` 3.96 ·
      `smc_bear_fvg_age` 3.14 · `wt_spread_4h` 2.62. Но 🔑 бóльшая часть — переоткрытие
      известного (дрейф-гейт, EQH, swing high). Новое: ВОЗРАСТ медвежьего FVG и
      направление×возраст структуры 4h;
- [x] ✅ «4h закрыт» — снят ранее в 136.B (PF 2.80);
- [x] ✅ «пивоты — артефакт 2024» — 136.D, вердикт УСТОЯЛ (см. выше);
- [x] ✅ **«SMC не работает» ОПРОВЕРГНУТ для short** (5 клеток PF 2.67-3.14, хрупкость +),
      подтверждён для long (все «выжившие» PF 0.58-0.61 = убыток);
- [x] 🔴 **«long кровит» ПОДТВЕРЖДЁН и жёстче**: база 15m long OOS **PF 0.49**, WR 11.5%,
      безтоп10% −8193. Настолько плохо, что относительный критерий трижды за сессию
      пропускал убыточные клетки как «находки». **На 15m long фильтровать нечего —
      нужен другой ТФ** (на 1h long PF 2.67). Детали:
      `obsidian/Research/2026-09-01-136-Priority2-Negative-Verdicts.md`.

### Приоритет 3 — записанные находки, ещё не в бою

- [ ] SC bear зона ×1.57 · CHoCH ×3.68 · EQH ×2.25 · дистанция до ERL · свежесть WT ·
      «не входить 24 ч» · вторая структура · волновые оси — все мерились на 40 монетах.

### Что делать НЕ надо

🔴 Не искать новое на выборке из 40 монет — это производство артефактов. До закрытия
приоритета 1 любой новый поиск идёт только на ядре.

### Инструменты

`research_harness.core_universe(tf)` · `collect(core=True)` · `matrix_global_run.py --core`
(пишет в отдельный `cache/matrix_core_{tf}.parquet`) · `year_vs_composition.py`.
Стоимость прогона: **5.4 часа** машинного времени, внимания не требует.

---

### 📋 РЕВИЗИЯ СУЩЕСТВУЮЩИХ ЗАДАЧ: что меняется от ядра, а что нет (30.08)

🔑 **Ключевое разделение.** Ядро меняет только выводы, полученные ИЗ МАТРИЦЫ. Всё, что
измерено на боевых сделках (`simulated_trades`, леджер биржи), — факт и не зависит от
размера исследовательской вселенной. Путать эти два класса нельзя.

**🟢 НЕ МЕНЯЕТСЯ (факт из боевых данных или инфраструктура):**

| задача | почему устойчива |
|---|---|
| РЕЕСТР СТРАТЕГИЙ (ср.R по источникам) | факт из `simulated_trades`, а не замер по матрице |
| 0.1 биржевой стоп («22% без стопа») | дефект учёта, доказан посекундно по леджеру |
| 0.2 `ote_nested` перемер | 9456 БОЕВЫХ сделок биржи; adverse selection — факт исполнения |
| 0.4 лимитный вход, 0.5 задержка сигнала | форвард и телеметрия |
| ARCH-129 · ARCH-132 · ARCH-133 | инфраструктура и сферы, замеров не содержат |
| все баги (BE↔LOSS, orphan, hedge-close) | поведение кода |

**🔴 МЕНЯЕТСЯ — перемерить на ядре:**

| задача / вывод | что было | что теперь известно |
|---|---|---|
| 0.3 MATRIX-FULL, прогон 565 признаков | 40 монет | ядро 97 → уже даёт другую базу (long 0.89 → **1.05**) |
| таблица ТФ: «15m/1h — 0 из 446» | 40 монет | отрицательный вердикт на бедной вселенной ничего не доказывает |
| «4h закрыт: хуже случайного входа» | 40 монет | перемерить, прогон `--core --tf 4h` |
| семья пивотов: «216 признаков — артефакт 2024» | 40 монет | 2024 на общей вселенной раздут новичками ([[method_year_vs_composition]]) |
| 1.2 конфлюэнция по этажам 15m/1h/4h | 40 монет | гнать сразу на ядре |
| 1.3 свежесть WT · ERL · амплитуда 8.5% | 40 монет | перемерить, приоритет 3 |

**🔄 ПЕРЕОСМЫСЛЕНО — постановка пункта была неверной:**

- **1.1 «слепой отбор ПОВЕРХ дрейф-гейта»** — так искать НЕЛЬЗЯ. Замерено 30.08: под гейтом
  клетка `rs_rank30` давала long ×2.58 при short ×2.12, то есть гейт создаёт СРЕДУ, где
  растут обе стороны, и односторонний признак от двустороннего становится неотличим.
  Правильная постановка: искать на голой базе (ARCH-135), гейт добавлять в ФАЗЕ 3
  и мерить как отдельный инструмент.

**✅ УЖЕ ПЕРЕМЕРЕНО 30.08 (числа в реестрах устарели):**

| инструмент | в реестре | **на ядре 97** |
|---|---|---|
| дрейф-гейт (боевой `drift30≥5`) | PF 1.24 → 4.61 | **PF 4.25**, монет 76/96, без топ-3 +10241% |
| EQH-дверь, порог 1.0 ATR | ×2.25, PF 5.39 | **×1.89**, PF 2.41, зеркало ×0.85 🟢 |
| зона стопа 1.5-3.234 | «часть эджа» | **вшита в механику — неизмерима** |
| long: «пробой swing-минимума» | ×2.04 | **×0.84 — ОТМЕНЕНА** |
| long: `rs_rank30 ∈ [26,48]` | ×1.49, зеркало ×0.62 | **зеркало ×1.05 — ОТМЕНЕНА** |

### 🆕 Новые подзадачи, поставленные этой ревизией

- [x] **136.A ✅ СДЕЛАН 30.08** прогон `--core --tf 1h`: 1572 сд, 93 монеты. 1h КАЧЕСТВЕННО ЛУЧШЕ 15m и там LONG сильнее SHORT (2.67 против 2.26, безтоп10% +928 против 15m −23717). 🔴 но поток 0.86 сд/день против 18.96 на 15m. Выжили на слепом отборе ДВА ВОЛНОВЫХ признака: `leg_age_origin_1h<=89` и `leg_age_extreme_4h__from_4h>=64`.  ~~прогон~~ — 1h торгует ОБЕ стороны, там же
      «impulse_fib 1h: 5 лет из 5 в плюсе», статус 🟢 в реестре стратегий;
- [x] **136.B ✅ СДЕЛАН 30.08** — вердикт «4h хуже случайного входа» СНЯТ: с адекватной зоной 228 сд, PF 2.80, безтоп10% +373. 🔴 но n мало, 2025-26 почти пусты (27 и 18 сд), поток 0.12 сд/день. Сложилась ЛЕСТНИЦА: 4h 2.80 / 1h 2.57 / 15m 1.14 — чем старше ТФ, тем выше качество и меньше поток.
      🔴 **Первая попытка провалена моей ошибкой (30.08): 5 сделок на 2 монетах.**
      Перенёс на 4h календарную длительность (`wait=3, hold=24` = те же 12 ч и 4 суток),
      но ОСТАВИЛ зону стопа 1.5-3.234% — на 4h бары крупнее, стопы естественно шире,
      и зона отсекла почти всё. Это ровно [[twins_15m_stabilized_by_measure]]: константа
      между ТФ не переносится. Предупредил про `wait`/`hold` и проглядел стоп.
      **Правило на будущее: при переносе механики на другой ТФ пересчитывать ВСЕ
      размерные константы, а не только временные. Пустой прогон — сигнал об этом.**
      Перезапуск: `--stop-lo 0.5 --stop-hi 20 --tag _wide`, потом резать по корзинам;
- [ ] **136.C** прогон 15m с РАСШИРЕННЫМ диапазоном стопа (0.5-8%) — единственный способ
      измерить вшитую зону 1.5-3.234;
- [x] **136.D ✅ ЗАКРЫТ 01.09** — вердикт по пивотам УСТОЯЛ на ядре: 0 живых на 1h short
      и 15m long, по одному пограничному (P=0.050) на 1h long и 15m short, оба —
      НЕДЕЛЬНЫЕ пивоты с 97.5% зависимостью от окна, в бой не годятся.
      🔑 На 15m long четыре признака «пережили OOS» с PF 0.66-0.74 — то есть теряя
      деньги; снято критерием «PF>1.0 абсолютно». Детали:
      `obsidian/Research/2026-09-01-136D-Pivot-Family-On-Core.md`;
- [~] **136.E** 01.09: три источника из четырёх перемерены, BOS-гейт заблокирован.
      **atr_s2** — выжил, но +0.431→+0.319%/сд, а при боевых костах 0.35% (вход
      лимитный) **+0.169%, PF 1.08**; хрупкость по сделкам −14914 = лотерея;
      одиночка PF 0.45 против кластера 1.17. **CHoCH→волна C** — вселенная НИ ПРИ ЧЁМ
      (120 монет PF 1.12 → ядро 1.14 на одном окне), падение до 1.01 даёт ГОД 2023;
      long убыточен на обеих вселенных; 🔴 боевой коридор стопа 8-15% не воспроизведён.
      **rangefade** — боевой порог WT−70 даёт PF 1.84, кластер-гейт → 1.88, а боевой
      **потолок стопа 4% опускает до 0.84**; вывод «поднять потолок» СНЯТ возражением
      Егора («7-20% — не стоп, а лотерея»), переведён в гипотезы Г-5/Г-6.
      ✅ **BOS-гейт ЗАКРЫТ 01.09** — блокер снят пересборкой сигналов вместо пропавшего
      дампа (`scripts/bos_gate_core.py`, ядро 97 монет, 6164 сигнала с 2023).
      Вердикт ПОДТВЕРЖДЁН: len5 ≥1 BOS даёт PF 1.81→**2.14** (×1.18), хрупкость
      **+10 → +702**; len50 ВРЕДИТ (×0.43) — «шкала len5 критична» верно.
      Записанный подъём ×1.17 совпал с измеренным ×1.18.
      Детали: `obsidian/Research/2026-09-01-136E-Live-Sources-On-Core.md`.

| [FIX-BIGFLUSH-STOP](#fix-bigflush-stop) | 🔴 | **bigflush15 НЕ МОЖЕТ торговать: `bigflush_min_stop_pct: 4.0` и `max_stop_pct: 4.0` = пустое окно.** Факт БД: 0 сделок с 13.08 (и `rangefade` 1h тоже 0). Отрезана зона 6-20%, где PF 3.28-4.16 при 88/95 монет в плюсе. Правка 13.08 делалась для `rangefade4h` по n=56, а `MAX_STOP_PCT` читается один на весь луп ([rangefade_loop.py:256](bot/loops/rangefade_loop.py#L256)). Лечение: порог per-source + проверка `min ≥ max` в `strategy_preflight`. [[bug_bigflush_min_equals_max_stop]] | DEV |
- [x] **136.F ✅ ЗАКРЫТ ОТРИЦАТЕЛЬНО 30.08** — поток на 1h через размер стопа НЕ поднять. Расширение 0.382→0.75: PF 2.57→1.45, поток ×0.08. Кандидат `short 2.5-3.234 ∪ 5-8` по общей строке был ЛУЧШЕ боевого (2.44 против 2.26, хрупкость +608 против +64), но 48% его сделок из 2022, в остальных 4 годах хуже боевого, P=0.980. 🟢 Побочно подтверждено: боевая зона 1.5-3.234 для long ОПТИМАЛЬНА; глубина входа 0.382 оптимальна с большим отрывом — 0.382→2.57 · 0.5→2.19 · 0.618→1.28 · 0.75→1.45. 🔴 кривая монотонна только до 0.5, дальше плато 1.3-1.5 (0.618 ниже 0.75 — при n=299/128 шум).

### 🔴🔴 136.F: почему поток на 1h важнее любого фильтра на 15m

**Факт, вскрытый прогоном 136.A:**

| | 1h (93 монеты) | 15m (96 монет) |
|---|---|---|
| long | PF **2.67** · безтоп10% **+928** · охват 74% | PF 1.05 · безтоп10% **−23717** |
| short | PF 2.26 · безтоп10% +64 | PF 1.27 · безтоп10% −11040 |
| **поток** | **0.86 сделки в день** на всю вселенную | **18.96 в день** |

**Лучший по качеству ТФ торгует в 22 раза реже худшего.** На 1h база прибыльна с
ПОЛОЖИТЕЛЬНОЙ хрупкостью — на 15m такого нет ни в одном срезе за всю сессию.

**Арифметика, из-за которой это приоритетнее поиска фильтров.** Найденный фильтр может
поднять качество, но всегда РЕЖЕТ поток (закон [[gate_threshold_frequency_vs_money]]).
А здесь поток можно поднять на уже прибыльной базе: если 1h выдержит вдвое больший поток
хотя бы с половиной текущего PF, это даст больше, чем любой фильтр на 15m, где база
структурно убыточна по хрупкости.

**Что именно расширяется.** Геометрия 1h: `wait=12, hold=96, зона стопа 1.5-3.234`.
Зона — ВШИТЫЙ гейт: отсекает сетапы при ГЕНЕРАЦИИ, поэтому в матрице нет контрпримеров
и измерить её нельзя. Первый прогон снимает именно её: `--stop-lo 0.5 --stop-hi 8`.

**Дизайн замера — один прогон вместо нескольких.** Расширяем зону максимально, а затем
режем результат ПО КОРЗИНАМ СТОПА постфактум. Так за один прогон получаем и профиль
качества по размеру стопа, и достижимый поток на каждом пороге.

```bash
python scripts/matrix_global_run.py --tf 1h --core --sides long,short \
       --stop-lo 0.5 --stop-hi 8 --tag _wide     # → cache/matrix_core_1h_wide.parquet
```

**Что печатать по каждой корзине стопа:** n · сделок в день · PF · WR · безтоп10% ·
охват монет · по годам · медиана месяца. Обе стороны раздельно.

**Критерий решения:**
- 🟢 расширять зону — если при росте потока PF падает медленнее, чем растёт n,
  и безтоп10% остаётся положительным;
- 🔴 не трогать — если хрупкость уходит в минус (значит новые сделки живут на хвосте);
- ⚠️ если качество держится только в узкой корзине — это подтверждение
  [[stop_zone_survived_blind_test]], и тогда поток надо искать через `wait`/`hold`,
  а не через стоп.

🔴 **Оговорка, которую нельзя терять:** 1h long держится на 2023 (546 из 1215 сделок,
PF 6.31), а в 2026 убыточен (0.61). Рост потока обязан проверяться ПО ГОДАМ отдельно —
иначе мы удвоим поток бычьего года и назовём это улучшением.

**Добавлено в инструмент:** `matrix_global_run.py --stop-lo/--stop-hi/--tag`, при изменении
зоны печатает предупреждение, что выборка будет ДРУГОЙ, и пишет в отдельный файл.

**Связано:** [[law_sample_representativeness]] · [[method_year_vs_composition]] ·
[[law_recorded_pf_needs_remeasure]] · [[law_reproduce_live_config_first]].

## 🔬🔬 ARCH-135: ГОЛЫЙ СРЕЗ — ВСЕ НАБОРЫ КУБА НА ВСЕХ ТФ, БЕЗ ГЕЙТОВ (30.08.2026)

> **Постановка Егора (30.08):** «разобрать все наборы и инструменты куба на всех тф,
> без гейтов, получить срез голых данных, а после уже улучшать и вытягивать показатели.
> запиши самую подробную задачу с пошаговой проверкой достоверности данных».
>
> 🔴 **Статус: НЕ НАЧАТА.** Это задача для НОВОЙ СЕССИИ. Начинать строго с ФАЗЫ 0 —
> ни одно число из ФАЗ 1-3 не имеет силы, пока ФАЗА 0 не пройдена целиком.

### Зачем именно ГОЛЫЙ срез — три доказанных причины, не вкусовщина

**1. Гейт превращает ОСЬ в СРЕДУ и это неразличимо изнутри.** Замерено 30.08 на находке
`rs_rank30` ([[long_relative_strength_axis]]):

| срез | long | short | что это |
|---|---|---|---|
| rs_rank БЕЗ гейта | ×1.49 (PF 1.33) | ×0.62 (PF 0.72) | 🟢 односторонняя ОСЬ |
| rs_rank + дрейф-гейт | ×2.58 (PF 2.30) | ×2.12 (PF **2.47**) | 🔴 просто хорошая СРЕДА |

Под гейтом клетка выглядит ВДВОЕ прибыльнее — и при этом перестаёт быть long-осью:
short в ней выше long. Без замера без гейта отличить одно от другого невозможно.

**2. Гейт режет базу вдвое и прячет явления.** `long + гейт` = 2216 из 4077 сделок.
Всё, что живёт в отсечённой половине, для поиска не существует. Ровно так весь поиск
связок 29.08 шёл поверх short-гейта — и вернул «в long находок нет».

**3. База под гейтом — уже не полная база.** [[golden_keys_matrix_verdict]]: фильтр мерить
против ПОЛНОЙ базы. Гейт в фоне подменяет базу тихо, и все подъёмы считаются не от того.

**Гейты не отменяются — они меряются ОТДЕЛЬНО, в ФАЗЕ 3, как инструмент поверх голого
среза.** Порядок «сначала голое, потом добавки» и есть суть задачи.

---

### 🔴 ФАЗА 0 — ПРОВЕРКА ДОСТОВЕРНОСТИ (без неё замеров нет)

Каждый шаг: **чем проверяется · критерий провала · что делать при провале.**
Все шаги ПЕЧАТАЮТ результат в лог прогона — «проверил в уме» не считается.

#### 0.1 Инвентаризация данных (запрет копировать окно)

| проверка | как |
|---|---|
| что есть в кэше | `SELECT timeframe, COUNT(DISTINCT symbol), MIN(time), MAX(time) GROUP BY timeframe` |
| режим КАЖДОГО года | медианный годовой дрейф вселенной + доля растущих монет |
| есть ли в окне обе фазы | если нет бычьего года — вердикт заведомо односторонний, писать это В ВЫВОДЕ |

🔴 **Провал:** окно взято «как в прошлом скрипте». `t0=2024-01-01` копировался вслепую
и прятал бычий 2023, на котором держались все выводы про long.
🔴 **Известно на 30.08:** 2023 БЫК (+11.31%), 2024/2025/2026 медведь. Три из четырёх лет
односторонние — это ОБЯЗАНО быть в шапке каждого отчёта.

#### 0.2 Причинность признаков (префиксный аудит)

Проверка запуском, не рассуждением: `детектор(df[:n])[-1] == детектор(df)[n-1]`.

| что проверить | критерий провала |
|---|---|
| каждый признак матрицы | расхождение на любом баре |
| старший ТФ | берётся НЕ с закрытого бара (`shift(1)` отсутствует) |
| нормировки/пороги | считаются по ВСЕМУ ряду вместо окна |

🔴 **Реальный случай:** `detect_fvg(threshold=None)` считал порог по всему ряду —
look-ahead через глобальную нормировку, 8 признаков текли до 1590 баров.
🔴 **Пять известных видов look-ahead:** [[oko_suite_trend_wt_validated]] (3 класса),
[[bug_fvg_flag_shifted_two_bars]], [[bug_fill_toxicity_lookahead]] (признак = результат).

#### 0.3 Задержка подтверждения КАЖДОГО детектора

Лаг детектора — его ПАРАМЕТР, а не статистика ([[detector_lag_is_a_parameter_not_statistics]]).

| детектор | лаг | следствие |
|---|---|---|
| structure_breaks · order_blocks · fvg | 0 | — |
| equal_levels | `eq_len` | — |
| SC-флаги | 5 | — |
| **detect_swings** | **ровно `length`** | при len=50 на 15m это **12.5 ЧАСА** |

🔴 **Критерий провала:** признак «событие N баров назад» с N **меньше** лага детектора —
это look-ahead. Так была раздута находка «не входить 24 часа»: лаг 6 баров, мерил с 1ч.

#### 0.4 Вырожденные признаки (константы и почти-константы)

| проверка | критерий провала |
|---|---|
| `nunique() < 2` | признак-константа, из перебора исключить и НАЗВАТЬ в отчёте |
| доля ненулевых | <0.5% помеченных баров = признак ничего не мерит |
| покрытие NaN | >30% NaN — выборка не та, что кажется |

🔴 **Реальный случай:** 13 из 69 SMC-признаков были КОНСТАНТА 0, а Order Blocks помечали
**4-5 баров из 19851** — `active_order_blocks` отдавал блоки, активные на ПОСЛЕДНЕМ баре
ряда. Вывод «SMC не работает» НЕ БЫЛ ИЗМЕРЕН ([[smc_in_matrix_is_dead_weight]]).

#### 0.5 Зависимость от окна расчёта

Считать признак двумя способами на одних барах: полная история против боевого окна (1000).

| класс | доля расхождений | что делать |
|---|---|---|
| 🟢 устойчивый | ≤2% | мерить как есть |
| 🟡 шаткий | 2-20% | мерить обоими, расхождение печатать |
| 🔴 оконно-зависимый | >20% | **на полной истории мерить НЕЛЬЗЯ** |

🔴 **Известно:** ломается ТОЛЬКО SMC — 37.3% (35 из 60). SCALES 0.0%, WAVES 0.0%.
Худшие: счётчики активных зон 93-99%, недельные пивоты 97.5%
([[window_sensitivity_only_smc_breaks]]). Инструмент: `scripts/window_sensitivity.py`.

#### 0.6 СДВИГ: сверить матрицу и проверку

🔴🔴 Отдельный шаг, потому что на этом трижды перевернулся вердикт по EQH.

| сдвиг | множитель EQH |
|---|---|
| 0 (последний бар) | ×1.20 → «мёртв» |
| **1 (как считает матрица)** | **×3.73** |
| 2 | ×2.05 |

**Правило:** сравнивать можно ТОЛЬКО версии, совпадающие по ОКНУ и по СДВИГУ. Перед любым
сравнением с прошлым замером — напечатать оба параметра ([[eqh_liquidity_short_works_in_2026]]).

#### 0.7 Вселенная замера = боевая?

| проверка | критерий провала |
|---|---|
| список символов | расхождение с боевым скринером |
| ликвидность/обороты | вселенная замера ликвиднее боевой |
| правила отбора | «взял что было в кэше» |

🔴 Расхождение уже стоило −101% на rangefade4h ([[universe_mismatch_backtest_vs_live]]).

#### 0.8 Калибровка конвейера на ЧИСТОМ ШУМЕ (делать ДО реального прогона)

Прогнать весь конвейер на перемешанном pnl и записать, **сколько «находок» он производит
из ничего**. Это порог отсечения на весь дальнейший замер.

🔴 **Известно:** тот же конвейер даёт на short медиану 3.0 выживших, на long — 4.5.
Разная плотность шума на сторонах — это СИМПТОМ разной базы, а не результат.
Без этой калибровки 5 выживших на long читались бы как находка.

#### 0.9 Отбор признаков не должен резать по алфавиту

🔴 **Реальный дефект (нашёл субагент):** `--max-feats 250` при `--families all` не пропускал
**ни одного** признака SCALES/WAVES (имена в конце алфавита), из SMC проходило 5 из 60.
«Полный охват» молча был охватом одной семьи.
**Проверка:** печатать СОСТАВ отобранных признаков по семьям перед прогоном.

#### 0.10 🔴🔴 Каких семей в матрице НЕТ (главный урок 30.08)

«Находок нет» — сначала подозревать отсутствие ПРИЗНАКА, а не отсутствие явления
([[law_no_finding_means_no_feature]]). Три случая подряд:

| «не нашлось» | оказалось |
|---|---|
| эдж по объёму | объём — 1 признак из 565, анатомия свечи — 0 |
| 0 из 446 | 216 решающих признаков вне матрицы |
| **связок в long нет** | **относительной силы монеты не было НИКОГДА** |

**Обязательный шаг:** перед прогоном грепнуть матрицу на семью, отвечающую вопросу задачи.
Ищешь long — есть ли RS? Ищешь исполнение — есть ли спред? Отсутствие семьи даёт РОВНО ТУ ЖЕ
картину, что отсутствие эджа.

**Известные пробелы на 30.08 (проверить, не появились ли новые):** профиль объёма внутри
свечи · история OI (физически не существует) · спред/стакан · ликвидации ·
коррекционные структуры Эллиотта · счёт волны · проекция цели.

#### 0.11 🔴🔴 СМЕНА СОСТАВА ВСЕЛЕННОЙ ПО ГОДАМ (survivorship)

Вскрыто 30.08 при инвентаризации кэша. На 15m символов с данными **до 2024-01 — только 169
из 496**; на 1h 164 из 514; на 4h 148 из 491; на 5m — **ноль**.

**Следствие:** «2023 работал, 2026 нет» может быть утверждением о СОСТАВЕ вселенной,
а не о рынке. Ранние годы — это выжившие монеты (те, что дожили до сегодня и попали в кэш),
поздние — все подряд, включая свежие листинги.

✅ **МЕТОД ГОТОВ И ПРОВЕРЕН 30.08 — `scripts/year_vs_composition.py`.** Три теста:

| тест | что делает | зачем |
|---|---|---|
| **1 · состав без времени** | внутри ОДНОГО года: ядро против новичков | время одно, рынок один — различается только состав |
| **2 · время без состава** | все годовые сравнения на балансированной панели | если картина другая — вывод был о составе |
| **3 · декомпозиция** | Δ_total = Δ_core + Δ_comp, доля состава = \|Δ_comp\|/\|Δ_total\| | >50% состав · **>100% знак перевернулся** |

```bash
python scripts/year_vs_composition.py --side long
python scripts/year_vs_composition.py --side long --col rs_rank30 --lo 26.24 --hi 48.47
```

**Первый прогон (15m, ядро 15 монет из 40):**

| вывод | доля состава | итог |
|---|---|---|
| long деградирует 1.53→0.48 по годам | **3-6%** | 🟢 РЕАЛЬНО, на ядре 1.53→1.27→0.68→0.45 |
| находка `rs_rank30` растёт к 2026 | 1-20% | 🟢 устойчива, на ядре ×0.93→×1.65→×1.55→×1.97 |
| **short в 2024 лучше, чем в 2025** | **135%** | 🔴 **АРТЕФАКТ: на ядре ЗНАК ОБРАТНЫЙ** (1.17 против 1.31) |

🔴🔴 Найденный артефакт: новички 2024 дали short PF **3.69** против 1.17 у ядра — разрыв
×3.15 на 149 сделках вытянул весь год. **Это задевает записанное «пятый результат подряд
формы 2024-25 да / 2023-2026 нет»** — часть паттерна может быть составом, а не механикой.
**Обязательно в ФАЗЕ 1: перепроверить все выводы про short с участием 2024 на ядре.**

### ✅ ЛЕЧЕНИЕ, А НЕ ТОЛЬКО ДИАГНОСТИКА: ядро строится БОЛЬШИМ (30.08)

Егор: **«а не проще собрать ядро одинаковое и большое для всех лет?»** — проще, и так надо.

Ядро из 15 монет было не пределом данных, а следствием **параметра**: матрица гонялась
`--symbols 40`, а `universe()` отбирал по ЧИСЛУ баров (`MIN_BARS_TF[15m]=12000` ≈ 125 дней)
и брал первые 40 после перемешивания. Монеты с полным покрытием туда попадали случайно.

**Отбор по ПОКРЫТИЮ ПЕРИОДА даёт в 6.5 раз больше:**

| ТФ | ядро с 2023 | ядро с сер. 2022 | всего не-junk |
|---|---|---|---|
| 15m | **97** | 0 (кэш 15m у выживших начинается позже) | 495 |
| 1h | **94** | 88 | 513 |
| 4h | **94** | 88 | 490 |

🔴 Пересечение старой выборки 40 с ядром — всего **11 монет** на 15m. Прошлые прогоны шли
почти целиком по монетам с неполной историей.

**Реализовано:** `research_harness.core_universe(tf, since, until)` + `collect(core=True)` +
флаг `--core` у `matrix_global_run.py`. Прогон с ядром пишется в **отдельный** файл
`cache/matrix_core_{tf}.parquet` — перезапись затёрла бы базу прошлых выводов.

```bash
python scripts/matrix_global_run.py --tf 15m --core --sides long,short
```

При `--core` состав ФИКСИРОВАН по построению: годы сравнимы напрямую, поправка на состав
не нужна. Обычный прогон печатает предупреждение, что состав по годам различается.

🔴 **Ограничение, писать в каждом отчёте:** ядро — это ВЫЖИВШИЕ монеты. Если явление жило
только в тех, что ушли, ядро его не покажет. Поэтому **ФАЗА 1 гонится ДВАЖДЫ**: на ядре
(чистое сравнение годов) и на полной вселенной (что реально торгуется). Расхождение между
ними — сам по себе результат, а не помеха.

**Правило:** любой вывод, где сравниваются годы, либо идёт с прогона `--core`,
либо проходит тест 3 ПЕРЕД докладом.

#### 0.12 База прибыльна ли САМА — фильтр не создаёт эдж

Перед перебором признаков напечатать базу каждого ТФ и стороны.

🔴 **Реальный случай 30.08:** база long 15m имела PF 0.89 — **убыточна**. Перебор над ней
структурно искал «где менее плохо», а не «где хорошо», и честно вернул шум. Ответ был верный
на неверный вопрос. Если база убыточна — это надо сказать в шапке и трактовать находки
как «фильтр меньшего вреда», пока не найдётся срез с PF>1 без единого признака.

---

### ФАЗА 1 — ГОЛЫЙ СРЕЗ (только после ФАЗЫ 0)

**Правило фазы: НИ ОДНОГО фильтра поверх. Ни дрейф-гейта, ни RR, ни min_strength,
ни source_policies. Полная база, обе стороны, каждый ТФ отдельно.**

🔴🔴 **ГЕЙТЫ БЫВАЮТ ВШИТЫЕ — снимать надо и их (вскрыто 30.08 при ревизии).**
Зона стопа 1.5-3.234% живёт не в конфиге поверх, а В САМОЙ МЕХАНИКЕ генерации:
`matrix_global_run.GEOM["15m"] = dict(lo=1.5, hi=3.234)` и отсев `if not (lo <= sp <= hi): continue`.
Следствия, обе неочевидные:
- в матрице **0 сделок из 27684 вне зоны** — то есть выборка отфильтрована НА ВХОДЕ,
  и эффект зоны по ней измерить НЕВОЗМОЖНО (нет контрпримеров);
- заявленное в конфиге «short + drift30≥10 + **зона 1.5-3.234** → PF 4.61» на самом деле
  равно «short + drift30≥10»: зона уже применена, второй раз она не режет ничего.

**Для ФАЗЫ 1 обязателен прогон с РАСШИРЕННЫМ диапазоном стопа** (например 0.5-8%), иначе
«голый срез» голым не будет. Перед прогоном — грепнуть механику на такие вшитые отсевы
(`continue` по условию) и перечислить их в шапке отчёта.

**Фактический кэш (пересчитан 30.08 из `ohlcv_cache.db`, НЕ из старой таблицы реестра —
она разошлась с БД):**

| ТФ | символов | окно | символов ДО 2024-01 | что известно на 30.08 |
|---|---|---|---|---|
| 5m | 449 | 2025-01→2026-05 | **0** | 🔴 бычьего 2023 НЕТ ВООБЩЕ — long в быке на 5m непроверяем |
| 15m | 496 | 2022-01→2026-08 | 169 | ✅ матрица 753 колонки + RS |
| 3m | 42 | 2022-01→2026-04 | — | 🔵 узкая вселенная, отдельный вопрос |
| 1h | 514 | 2022-01→2026-08 | 164 | 🔴 старая матрица (446), с RS/SCALES/WAVES **не гонялась** |
| 4h | 491 | 2022-01→2026-08 | 148 | 🔴 «закрыт: хуже случайного входа» — на СТАРОЙ матрице |
| 1d | **19** | **2026-01→2026-05** | 0 | 🔴 **5 месяцев** — не «мало данных», а замер невозможен |

🔴🔴 **СОСТАВ ВСЕЛЕННОЙ МЕНЯЕТСЯ ПО ГОДАМ — это отдельный шаг проверки (0.11).**
На 15m: 2023 представлен 169 символами, 2026 — всеми 496. **Сравнение годов сравнивает
разные вселенные.** Все выводы «2023 работал, 2026 нет» могли быть выводами о СОСТАВЕ.
Обязательно: прогнать ключевые срезы на подвыборке символов, живших ВО ВСЕ годы (~148-169),
и сравнить с полной. Расхождение = вывод был о составе, а не о рынке.

**Что печатать по КАЖДОМУ ТФ (шапка отчёта, без неё числа не читаются):**
1. база long и база short — PF, WR, n, безтоп10%, охват монет;
2. база по годам + режим года;
3. **медиана МЕСЯЦА** — вскрылось 30.08: база long PF 0.89 выглядела «почти безубыточной»,
   а медиана месяца у неё **−60.0%**. PF прячет масштаб проблемы;
4. месяцев в плюсе, % — устойчивость во времени;
5. состав вселенной и окно.

**Наборы, которые обязаны попасть в срез (все, не выборочно):**
пивоты · SMC (BOS/CHoCH/FVG/OB/EQH/EQL + SC) · WT · дивергенции · ATR-тренд ·
SCALES (две структуры 5/50) · WAVES (ноги) · SMC-состояния · CANDLE/объём ·
**RS (новая, 30.08)** · FUND · MKT · вложенность со старших ТФ (`__from_1h/4h`) ·
профиль объёма старших баров.

---

### ФАЗА 2 — ОБЯЗАТЕЛЬНЫЕ СРЕЗЫ КАЖДОЙ НАХОДКИ

Ни один вердикт не выносится по общей строке. По каждому кандидату:

| срез | критерий отбраковки |
|---|---|
| **сторона** (зеркало) | зеркало РАСТЁТ → это среда, а не ось. Проверено на rs_rank+гейт |
| **год** | живёт в одном годе (доля ≥70%) → эдж эпохи, не инструмент |
| **режим года** | работает только в своём режиме — сказать это явно |
| **месячная устойчивость** | <50% месяцев в плюсе / медиана месяца < 0 → хрупко во ВРЕМЕНИ |
| **размер стопа** | нет плато по корзинам стопа → подгонка |
| **хрупкость по сделкам** | безтоп10% отрицателен → держится на хвосте |
| **хрупкость по монетам** | «без лучших трёх» отрицателен → держится на паре монет |
| **охват монет** | <35% монет в плюсе |
| **пересечение находок** | Жаккар ≥0.5 с уже известной → то же явление под новым именем |
| **множественность** | перестановка с выбором ЛУЧШЕЙ из N клеток, не одной |
| **блочная перестановка** | перемешивать ВНУТРИ месяца — сохраняет слипание сделок |
| **независимость n** | сколько РАЗНЫХ дней/недель/месяцев; плотнейший месяц >30% = один эпизод |

**Пороги брать КВАНТИЛЕМ, не константой.** Округление 26.24 вместо `quantile(0.2)`
сдвинуло выборку на 5% (732→693).

**Форма кривой — смотреть децили целиком, а не порог.** Кривая RS оказалась СЕРЕДИННОЙ:
и нижние 20% (падающий нож, PF 0.72), и верхние 20% (моментум, 0.78) хуже базы, живёт
вторая снизу четверть (1.27). Отбор порогами `>=` такую клетку **пропускает**.

**Формат вердикта обязателен:**
```
Проверено:      <срезы с числами>
НЕ проверено:   <честно>
Вердикт предварителен до: <что закроет вопрос>
```
Плюс три способа, которыми результат может быть артефактом (самый вероятный — проверить),
и ≥2 новые гипотезы.

---

### ФАЗА 3 — ТОЛЬКО ПОТОМ УЛУЧШЕНИЕ

Порядок обязателен: **голое → срезы → добавки.**

1. измерить КАЖДЫЙ гейт отдельно поверх голого среза: что он добавляет и **что режет**
   (у гейта два числа: подъём PF и потерянный поток — [[gate_threshold_frequency_vs_money]]);
2. связки находок между собой — с проверкой Жаккара, чтобы не сложить одно и то же;
3. перенос находок между ТФ — **мерить, не предполагать** (гейт BOS помог long, навредил short);
4. только выжившее — в shadow-форвард, и лишь затем в бой.

---

### Критерий закрытия ARCH-135

- [ ] ФАЗА 0: все 12 шагов пройдены и **напечатаны** в логе прогона;
- [ ] ФАЗА 1: голый срез по 5m/15m/1h/4h/1d, обе стороны, шапка с медианой месяца;
- [ ] ФАЗА 2: каждый кандидат прошёл 12 срезов, вердикт в обязательном формате;
- [ ] названы семьи, которых в матрице НЕТ (по каждому ТФ);
- [ ] ФАЗА 3 начата только после подписи ФАЗ 0-2.

**Инструменты:** `scripts/matrix_full.py` (753 колонки + RS) · `research_harness.py` ·
`window_sensitivity.py` · `pair_search.py` (3 дефекта исправлены 30.08) ·
`long_inventory.py` · `rs_probe.py` · `detector_confirmation_lag.py`.

**Связано:** [[law_no_finding_means_no_feature]] · [[long_relative_strength_axis]] ·
[[feedback_verdict_protocol_egor]] · [[law_reproduce_live_config_first]] ·
[[window_sensitivity_only_smc_breaks]] · [[law_relative_threshold_and_permutation]].

## 🌊 ARCH-132: WAVE SPHERE — единый волновой детектор (29.08.2026)

> Повод (Егор, 29.08): «детектор должен быть обособленно и только переиспользоваться».
> Вскрыто при добавлении волн в матрицу: волновая логика размазана по 4+ реализациям.
> 🔴 Номер сферы: **S14 ЗАНЯТ Execution (ARCH-96)**, WaveService помечен «14?» с
> конфликтом. Свободна **20** (карта: «Занято 1–19»). Решает ARCH через FIX-SPHERE-NUM.
> 🔴 `WaveService` в коде НЕ СУЩЕСТВУЕТ — только упоминания в комментариях
> (`core/smc/sub_cube.py:12`, `bot/monitoring.py:467`).
> ✅ **НО СПЕЦИФИКАЦИЯ ЕСТЬ** — `docs/CUBE_SUBCUBES.md` §«Sub-куб 2: Elliott-Pivot»,
> строки 237-344: класс с кодом, `SWING_PERIOD_4H/1H = 5`, `LTF = 3`, `MIN_BARS = 15`.
> Все зависимости на месте (`find_swing_highs/lows`, `calculate_n_down/n_up` в
> `core/indicators/indicators.py`). То есть **реализовать написанное, а не изобретать**.
> 🔑 Волны живут в **СУБ-КУБЕ 2**, а не отдельной сферой верхнего уровня — это меняет
> постановку: WaveSphere = внутренняя сфера Elliott-Pivot вместе с Pivot/Reversal/Fib.
> 🔑 Спецификация `StructureSphere` (суб-куб 1) уже требует `last_break_dir` и
> `bars_since_break` — ровно то, что 28.08 добавлено в матрицу как `st50_dir`/`st50_age`.

| ID | Ст | Кратко | Роль |
|---|---|---|---|
| [ARCH-132](#arch-132) | 🟢 | Wave Sphere: ядро 29.08, **ПОДКЛЮЧЕНА В SHADOW 02.09** — `bot/loops/wave_loop.py` | ARCH/DEV |

### ✅ СДЕЛАНО 29.08 — `core/intelligence/wave_service.py` (10 тестов)

Реализована написанная спецификация `CUBE_SUBCUBES.md` §Sub-куб 2 + требование Егора
про память разметки. Сервис считает волновую фазу на 4h/1h/LTF, хранит **историю**
(64 снимка на символ) и ловит **пересчёт счёта** как отдельное событие со счётчиком.

**Два дефекта, вскрытых при реализации — оба «молчаливый отказ»:**

1. **Полей `elliott*`/`wave*` в `PairState` не было**, а `PairContextBus.update()` молча
   роняет неизвестные ключи в debug-лог. Сервис «работал» бы, а в шину не попадало бы
   ничего. Поля заведены (+13 строк, только добавления).
2. **Спецификация берёт `htf_price_dir` из шины, а такого поля НЕТ нигде в проекте** —
   грep даёт единственное упоминание в самом сервисе. По спеке фаза всегда возвращала бы
   `undefined`. Лечение: сервис считает направление сам (определение из `ENCYCLOPEDIA`,
   порог 0.5 ATR за окно). **До:** 100% `undefined`. **После (20 монет):** `wave3_mid` 9 ·
   `impulse_start` 7 · `undefined` 4 — ровно там, где рынок плоский.

### 🔴 ОСТАЛОСЬ: подключение к `scan_loop` (не сделано НАМЕРЕННО)

Бот в момент работы торговал — 11 открытых позиций `ote_nested` + 8 `impulse_fib`.
Правка живого цикла ночью без присмотра рискует управлением позициями, поэтому сервис
проверен на реальных данных отдельно, а подключение оставлено на решение ARCH.

**Точка подключения:** синхронный вызов в `scan_loop` там, где уже загружены df по ТФ
(решение роя 4/4 от 29.05: ordering гарантирован, async EventBus — этап 21).

```python
phase = wave_svc.compute_and_publish(sym, df_4h, df_1h, df_15m, bot.pair_bus)
```

Порядок ввода: **SHADOW** (только публикует в шину, ничего не гейтит) → накопить снимки →
только потом решать, гейтит ли фаза. Так же вводилась `phase_sphere`.
После подключения обязателен рестарт + SelfTest 12/12.

| [ARCH-132.1](#arch-132-1) | 🟡 | Инвентаризация: свести 4 детектора структуры/ног, выбрать канон | DEV |
| [ARCH-132.2](#arch-132-2) | 🟢 | Переезд потребителей на канон + parity-тест (как ARCH-130-REGISTRY) | DEV |
| [ARCH-132.3](#arch-132-3) | 🟢 | Публикация волнового состояния в шину (ребро Куба) | DEV |
| [ARCH-132.4](#arch-132-4) | 🟡 | СЧЁТЧИК ВОЛН: вычислитель геометрии + волновой интерпретатор | DEV |

**ВСЁ ЭТО — ОДИН МОДУЛЬ `wave_service` (решение Егора 29.08).** Разделение на «счётчик /
интерпретатор / вычислитель геометрии» снято: это были три названия одной вещи, а не три
модуля. Дробить преждевременно — правило проекта: новая абстракция только когда её просят
3+ места. Спецификация в `docs/CUBE_SUBCUBES.md` §«Sub-куб 2» изначально описывает единый
`WaveService`, к ней и возвращаемся.

Не гейт и не классификатор режима — **источник геометрии сделки**: где мы в счёте, какая
структура, куда фибо-проекция цели.

**Что модуль обязан ДЕЛАТЬ (список функций, не список классов):**
- размечать волны на нескольких масштабах (`detect_elliott_mtf` уже даёт `scale` 3/5/8);
- **ХРАНИТЬ разметку во времени** (требование Егора 29.08: «волны нужно в памяти держать,
  чтобы знать историю и прогнозировать по теории»). Сейчас каждый прогон считает с нуля,
  поэтому бот в бою не знает, в какой он волне — видит только последний импульс;
- 🔑 отдельно хранить **факт пересчёта разметки**: слом счёта = по канону сигнал, что
  старшая разметка была неверной. Сейчас это событие не видит никто, каждый прогон стирает
  прошлое;
- применять правила разволновки (чередование, personality, недопустимые конфигурации);
- отдавать геометрию: уровни, фибо-проекции от нужной степени волны;
- публиковать состояние в шину (иначе остальные сферы его не увидят — сейчас 213 из 230
  признаков идут мимо Куба, [[bus_sees_only_candles]]).

Состояние, а не расчёт → место в шине, как у `PairContextBus`.

Что обязан учитывать (уточнения Егора, все в одну сторону — это НЕ подгоняемый коэффициент,
а канон разметки):
- **чередование** — если предыдущая коррекция простая (зигзаг), следующая сложная
  (плоскость/треугольник), и наоборот;
- **вложенность** — волна старшего масштаба состоит из волн младшего (у нас уже есть
  два масштаба 50/5 и `leg_history`, [[method_egor_two_scale_entry]]);
- **прочие правила разволновки** — соотношения длин, недопустимые конфигурации.

🔴 **Масштаб волны задаётся РАЗМЕТКОЙ, а не таймфреймом** — доказано замером 29.08
(`scripts/ltf_2026.py`, 2026-01→05, 40 монет, одна вселенная): на 5m амплитуда импульса
**8.63%** против **8.90%** на 15m, цель 13.96% против 14.40% — почти одинаковые.
Причина: `find_impulses` калиброван в ATR (`MIN_ATR=3.0`) и на любом ТФ ловит движение
той же относительной величины. PF при этом ХУЖЕ: 0.56 против 0.89 (до костов 0.68 / 1.06),
косты одинаковые 17-18% от стопа. **Опускать ТФ бесполезно** — нужен счётчик, который
знает масштаб волны сам.

🔴 **РОЛЬ ИНТЕРПРЕТАТОРА ПЕРЕОПРЕДЕЛЕНА (Егор, 29.08: «именно поэтому я и думаю про
интерпретатор»).** Он был записан как классификатор режима `UP/DOWN/FLAT` для гейта.
Разбор 2026 показал, что нужен он для другого — и это делает его центральным, а не
вспомогательным.

**Цепочка, которая к этому привела:**
1. в 2026 механика перестала работать, и **ни один фильтр не чинит**: 10 осей дают
   среднее \|x−1\| = 0.30, разделения в данных нет ([[market_2026_no_separability]]);
2. геометрия сетапов при этом ОДИНАКОВА во все 4 года (амплитуда 7.9-8.4%, стоп 2.0-2.2%) —
   механика находит то же самое, меняется поведение рынка ПОСЛЕ входа;
3. причина в масштабе цели: **цель / локальный коридор 30д** = 32% (2024) · 31% (2025) ·
   **49% (2026)**. Цель 1.618×амплитуда требует пройти ПОЛОВИНУ коридора;
4. 🔑 канон волновой теории (напоминание Егора) объясняет это структурно: в зигзаге
   **C ≈ A** (или 1.618·A), в плоскости **C ≈ A**, а в **треугольнике каждая следующая
   волна МЕНЬШЕ предыдущей**. В боковике доминируют плоскости и треугольники — фиксированная
   цель 1.618 недостижима ПО ПОСТРОЕНИЮ, а не по невезению.

**Отсюда роль:** интерпретатор говорит, какая сейчас структура, и из этого следует
**фибо-проекция цели от ПРЕДЫДУЩЕЙ волны**, а не множитель текущей.

🔴 Важное ограничение, поставленное самим Егором («адаптивная в зависимости от волн и фибо?
или адаптивная просто в воздух?»): адаптивность допустима ТОЛЬКО как проекция от разметки.
Произвольный подгоняемый множитель (пробовался вариант «цель × коэффициент по объёму»)
отвергнут — это класс, уже проигравший в [[constants_plateau_not_fibonacci]], где адаптивные
окна оказались хуже фиксированных.

Замер правил цели на одном потоке сетапов: `scripts/adaptive_target.py`
(`fix_1618` контроль · `fix_1000` · `edge_080` до стены коридора · `cap` ·
`prevA_1000` и `prevA_1618` фибо от предыдущей волны · `by_shape` выбор проекции
по сжатию/расширению волн). Проверяется на ВСЕХ годах — правило, выигрывающее только
в 2026, это подгонка под текущий рынок.

🔴 **ПОЧЕМУ ЭТА ЗАДАЧА НЕ ЗАВИСИТ ОТ СУДЬБЫ ОТДЕЛЬНОГО ПРИЗНАКА** (поправка 29.08).
Формулировка «временной OOS сэкономил реализацию Wave Sphere» была НЕВЕРНОЙ и снята.
В бой не идёт ПРАВИЛО `churn`-гейта — волновой анализ при этом уже работает в бою
(`choch_wavec`, `rangefade_loop`, `impulse_fib`, терминал структуры). Сфера нужна по
трём причинам, ни одна из которых не про эдж конкретного признака:

1. **архитектура** — четыре несогласованных детектора структуры/ног (таблица ниже);
   пока их четыре, любой волновой замер непроверяем: неясно, чей ответ мерили;
2. **наблюдаемость** — волновое состояние не публикуется в шину, поэтому ни одна сфера
   не может на него опереться и ни один feedback loop его не видит;
3. 🔑 **прибор для различения эпох** — и это довод, который дал сам отрицательный
   результат. Находки жили в 2024-25 и умерли в 2026; разрез по типу волны показал
   ПОЧЕМУ (2023 = 63% волной UP, где правило вредит). Именно неспособность правил
   переживать смену эпохи — аргумент ЗА прибор, который эпоху различает, а не против.

🔴 **ARCH-132 поглощает ARCH-121 и ARCH-127 (WAVE-SERVICE).** Проверено 29.08 по git и Obsidian:
задача поставлена **08.06.2026** (коммит `1c283bf`, «юзер: там решение, погнали»), висит 🔴 в
**11 недельных дайджестах подряд** (W25–W35). Кода не было НИКОГДА — `git log --diff-filter=A
-- '*wave_service*'` пуст, коммит трогал только `TASKS.md` и `config.yaml`.
Формулировка тогда: «кирпичи есть (`detect_elliott_impulse`/`n_down`/elliott-флаги в снимке),
**нет оркестровки** (WaveService, nested wave, MTF-синхрон)» — то есть ровно то, что начато
28-29.08 семьями SCALES и WAVES в матрице.

**Первое подтверждение ценности (29.08):** тип волны — не косметика, он МОДУЛИРУЕТ находки.
Одна и та же механика: волна UP Δ −0.14 · DOWN +0.83 · **FLAT +1.33**. Год 2023 затухал не
«из-за эпохи», а потому что был на **63% волной UP** → [[wave_type_flat_modulates_findings]].

## 🧭 ARCH-133: ПОРЯДОК В КУБЕ — панель ↔ карта ↔ код разошлись (29.08.2026)

> Повод (Егор): «нужно наводить порядок внутренний по кубу и сферам, на localhost:3000
> похоже неактуальная визуализация». Подтверждено прогоном `scripts/cube_registry_audit.py`.

| ID | Ст | Кратко | Роль |
|---|---|---|---|
| [ARCH-133](#arch-133) | 🟡 | Свести панель Куба, единую карту и код к одному состоянию | ARCH/DEV |
| [ARCH-133.1](#arch-133-1) | 🟡 | 3 узла панели показывают несуществующие файлы | DEV |
| [ARCH-133.2](#arch-133-2) | 🟡 | 2 конфликта номера сфер: панель S14=WAVE / S15=WT против карты | ARCH |
| [ARCH-133.3](#arch-133-3) | 🟢 | Префикс `S` означает И сферу, И детектор — развести обозначения | ARCH |
| [ARCH-133.4](#arch-133-4) | 🟢 | Панель на статических демо-данных: сделки и winRate выдуманы | DEV |
| [ARCH-133.5](#arch-133-5) | 🟡 | СУБ-КУБЫ: 4 внутренних сферы ведут на несуществующие файлы | ARCH/DEV |

**Замер (`scripts/cube_registry_audit.py`, 29.08):** узлов в панели 13 · сфер в карте 19.

| проблема | детали |
|---|---|
| **битые пути (3)** | `CONFIRM` → `core/signals/confirmation` · `WAVE` → `core/intelligence/wave_service.py` · `DIAG` → `scripts/run_diagnostics.py` — ни одного не существует |
| **конфликт номеров (2)** | панель: `WAVE = S14`, карта: **S14 = Execution Sphere** · панель: `WT = S15`, карта: **S15 = Anomaly Detection** |
| **не показаны (6)** | S13 PairContextBus · S14 Execution · S15 Anomaly · S16 Portfolio · S17 Meta-Learning · S18 Setup Engine |
| **демо-данные** | `oko-dashboard/lib/oko-data.ts` — сделки `T-2041 BTC 67120`, стратегии с winRate 72% захардкожены |

🔴 Панель рисует сферу **рабочей там, где кода нет вовсе** — это молчаливый отказ на уровне
интерфейса: глазу показывают зелёный узел вместо отсутствующего модуля.

**СУБ-КУБЫ — вторая, вложенная решётка, и её тоже надо сверять** (напоминание Егора 29.08;
панель рисует вложенные узлы через поле `sub:`, на глаз они неотличимы от рабочих):

| суб-куб | внутренние сферы | состояние |
|---|---|---|
| **1 · SMC** (ARCH-120) | OB · FVG · Structure · Liquidity · OTE | 4/5 ✅, нет `core/smc/ote.py` — 🔑 но OTE в коде ЕСТЬ под другими именами (`oko_ote.py`, `ote_matrix.py`, `ote_signal_generator.py`) → расхождение ИМЁН, не отсутствие |
| **2 · Elliott-Pivot** (ARCH-121/118/119) | Wave · Pivot · Reversal · Fib | **1/4 ✅** — нет `wave_service.py`, `pivot_calculator.py`, `fib_clusters.py` |
| **3 · WT** (Этап 21) | WT 15m/1h/4h/1d/1w → MTF-вердикт | vision, файлов не назначено |

🔑 Суб-куб 1 показывает, что часть «дыр» — это **разошедшиеся имена**, а не пропавший код.
Правка начинается со сверки имён, а не с написания новых модулей.

🔴 Отдельно: сам аудитор в первой версии выдал ложный конфликт «S14 = FUNDING_EXTREME» —
парсер читал таблицу ДЕТЕКТОРОВ. Это и есть 133.3: **префикс `S` в проекте обозначает две
разные сущности** (сфера S14 Execution и сигнал S14 FUNDING_EXTREME), и на этом спотыкается
не только скрипт.

**Порядок правок — только такой:** КОД → карта → панель. Правка панели первой закрепит
расхождение вместо того, чтобы его снять ([[cube_map_unified_one_source]]: истина = код).

**Что размазано сейчас (проверено грепом 29.08):**

| реализация | что делает | кто на ней |
|---|---|---|
| `core/smc/oko_sm_engine.py` | `run_structure` — ДВА масштаба (50/5), `trend`/`itrend`, **`leg_history` (ноги)** | боевая `choch_wavec`, `rangefade_loop`, терминал, 9 скриптов |
| `core/smc/smc_engine.py` | `detect_structure_breaks` + `_swings_luxalgo` — ОДИН масштаб, зато с `has_volume` | `swing_bridge` → `combinator_core` → **вся матрица** |
| `core/smc/impulse_fib.py` | `find_impulses` — ПЕРЕБОР окна `range(5,60)` | боевые оба инстанса `impulse_fib` |
| `core/smc/dc_legs.py` | Directional Change, конечный автомат | исследования |

🔑 `dc_legs.py` в своей же шапке называет перебор в `impulse_fib` **корнем проблемы**:
«НИ ОДНА открытая реализация так не делает», случай KAIA 20.08 — origin встал на сутки
раньше дна. То есть выбор канона уже наполовину обоснован внутри проекта.

⚠️ Сверено 28.08: `oko_sm_engine` и `smc_engine` дают **идентичные сломы** (совпадение
100%, 1006 internal + 126 swing, допуск ±0 баров). Различие одно — `has_volume`.
Значит слияние этих двух безопасно; `impulse_fib.find_impulses` — отдельный вопрос,
он боевой и трогать его без замера нельзя ([[law_reproduce_live_config_first]]).

**Связь с ARCH-129-FLOW:** тот же класс («три калькулятора FVG, два OB»), но про
структуру и ноги. Делать после или вместе, канон выбирать одним решением.

**Что это даёт:** сферы получают доступ к данным, на которых бот УЖЕ принимает решения;
становится возможен feedback loop по ним; исчезает дублирование (каждая стратегия
тянет фандинг/OI сама). Плюс замеры смогут их использовать — сейчас матрица
покрывает 6% решающих признаков ([[matrix_covers_six_percent]]).

**Занятые номера сфер:** 1-12 (боевые) · 13 Фаза/Decision Core (`phase_sphere.py`) ·
14 Execution (ARCH-96, frozen) ИЛИ WaveService (ARCH-121) — конфликт ·
15 Anomaly · 16 Portfolio · 17 Meta-Learning · 18 Setup Engine · **19 Market Data (новая)**.

## 🎯 РЕЕСТР СТРАТЕГИЙ (27.08.2026) — статус и что перепроверить

> Отмечать этап в колонке **Ст**. Числа — факт из `simulated_trades` на 27.08.
> Детали замеров: отчёт https://claude.ai/code/artifact/ac941b82-9ec0-460c-b83b-9a0aa2ea5e1f

| Стратегия | Ст | В бою / ср.R | Что перепроверить | Роль |
|---|---|---|---|---|
| impulse_fib 1h | 🟢 | да · 55 сд · +0.19 | ядро, 5 лет из 5 в плюсе — НЕ трогать, усилить не удалось ничем | DEV |
| | | | | |
| impulse_fib 15m | 🔄 | да · 12 сд · −3.45 | стопы · свежесть WT в shadow · ERL в shadow | DEV |
| | | | | |
| ote_nested | 🔴 | НЕТ с 24.07 · +0.32 WR 55% | 🔴 лучший ср.R в базе (9443 закрытых) и молчит месяц — выяснить почему | DEV |
| | | | | |
| radar_pump | 🔴 | да · 305 сд · −0.06 | 🔴 14 пробоев −1R (худшая −8.92) · 21% позиций без биржевого стопа | DEV |
| | | | | |
| radar_spring | 🔴 | да · 105 сд · −0.15 | 🔴 8 пробоев на 20 позиций — стопы в первую очередь | DEV |
| | | | | |
| watch_list_breach | 🟡 | да · 4865 сд · −0.28 | крупнейший источник убытка — нужен ли вообще, кто его включает | ARCH |
| | | | | |
| choch_wavec | 🟡 | да · 3 сд · −0.04 | набрать выборку, пока данных нет | DEV |
| | | | | |
| rangefade / rangefade4h | 🟡 | молчит с 13.08 · −0.14 | почему молчит · 27% позиций без стопа | DEV |
| | | | | |
| ds_advisor | 🟡 | молчит с 13.08 · −0.43 | нужен ли · 23% без стопа | ARCH |
| | | | | |
| confluence | 🔵 | молчит с 13.08 · +0.07 | эдж умер: март +0.50 → август −0.28 — закрыть или перемерить | DEV |
| | | | | |
| atr_change | 🔵 | молчит с 22.07 · −0.28 | 10536 сделок в минус — закрыть | DEV |
| | | | | |
| wt_sideways | 🔵 | молчит с 17.08 · −0.32 | 7706 закрытых в минус — закрыть | DEV |
| | | | | |
| pivot_reversal | ⏸ | выкл · −0.27 | закрыт, не возвращаться без нового повода | — |
| | | | | |
| method_egor / method_v2 | 🧊 | выкл | заморожены | — |

### 🔴 Критично, вне очереди

| ID | Ст | Краткое | Роль |
|---|---|---|---|
| [FIX-STOPS](#fix-stops) | 🔴 | 22% позиций открываются БЕЗ биржевого стопа — 27 пробоев −1R за август | DEV |
| | | | |
| [WHY-OTE-OFF](#why-ote-off) | 🔴 | ote_nested (+0.32, WR 55%, 9443 сд) молчит с 24.07 — найти причину | DEV |

---

## 🔬 РЕЕСТР ИНСТРУМЕНТОВ И MTF-СВЯЗОК (27.08.2026)

> На чём делаем проверки. Матрица подтягивается харнессом (`scripts/research_harness.py`)
> целиком — забыть семью технически невозможно. Старшие ТФ берутся с ЗАКРЫТОГО бара (shift 1).
>
> 🔴🔴 **ВСЕ СТАТУСЫ НИЖЕ ПОЛУЧЕНЫ НА ВЫБОРКЕ ИЗ 40 МОНЕТ (30.08).** На балансированной
> панели из **97 монет** база меняется (long PF 0.89 → **1.05**), а две находки уже
> отменены. Отрицательные вердикты («0 из 446», «4h хуже случайного») на бедной вселенной
> НИЧЕГО НЕ ДОКАЗЫВАЮТ — см. ARCH-136. Перемерять через `matrix_global_run.py --core`.

### Таймфреймы и связки

| ТФ | в кэше | **ядро** (полное покрытие) | старшие | боевой инстанс | статус проверки |
|---|---|---|---|---|---|
| 5m | 449 (2025-01→2026-05) | **0 до 2024** | 15m · 1h | нет | 🔵 не трогали · бычьего 2023 НЕТ |
| | | | | | |
| 15m | 496 (2022-01→2026-08) | **97** | 1h · 4h | short + дрейф-гейт | 🔄 ядро прогнано 30.08: 27684 сд, 757 призн. Старое «0 из 446» — на 40 монетах |
| | | | | | |
| 1h | 514 (2022-01→2026-08) | **94** | 4h · 1d | обе стороны | 🔴 ядро НЕ прогнано (136.A). «0 из 446» — на 40 монетах, вердикт снят до перемера |
| | | | | | |
| 4h | 491 (2022-01→2026-08) | **94** | 1d | нет | 🔴 «закрыт: хуже случайного входа» — на 40 монетах. **Вердикт СНЯТ** до перемера (136.B) |
| | | | | | |
| 1d | **19** (2026-01→2026-05) | 0 | — | нет | 🔴 5 месяцев данных — замер невозможен, не «мало», а нельзя |

### Семьи признаков (446 в матрице → **757 на ядре 30.08**)

🔴 Колонка «Статус» — вердикты, полученные на 40 монетах. На ядре 97 их надо переоткрыть:
самый крупный — **пивоты, 216 признаков, «вся семья артефакт 2024»** (136.D), при том что
2024 на общей вселенной оказался раздут новичками ([[method_year_vs_composition]]).

| Семья | Признаков | Статус | Примечание |
|---|---|---|---|
| пивоты | 216 | ✅ 0 выжило | вся семья — артефакт 2024 года |
| | | | |
| SMC (BOS/CHoCH/FVG/OB/EQH/EQL) | 66 | ✅ 0 выжило | живой бычий FVG = ХУДШАЯ зона для long |
| | | | |
| WT | 18 | ✅ 0 выжило поодиночке | но связки дали находки — см. ниже |
| | | | |
| дивергенции | 24 | ✅ 0 выжило | фрактальные для short: PF 1.40, OOS 1.33 |
| | | | |
| ATR-тренд | 12 | ✅ 0 выжило | — |
| | | | |
| со старших ТФ (`__from_1h/4h`) | 290 | ✅ 0 выжило | мерились поодиночке — по этажам НЕ мерились |

### Инструменты вне матрицы (наши)

| Инструмент | Где работает | Результат | Статус |
|---|---|---|---|
| дрейф-гейт вселенной (d30) | 15m short | PF 1.24 → 4.61 (40 монет) · **на ядре 97: PF 4.25, монет 76/96, без топ-3 +10241%** | ✅ **ПОДТВЕРЖДЁН НА ЯДРЕ 30.08** — стал сильнее. 🔴 порог не плато: 15→7.41, но 20→3.17 |
| | | | |
| свежесть состояния WT (0-5 баров) | 15m short | PF 4.17 → 6.48 · OOS 5.68 | 🔴 **на 40 монетах** — перемерить на ядре до shadow (136.E) |
| | | | |
| wt1 выше медианы SMA(50) | 15m short | PF 17.51 · OOS 11.67 · 13 сд/мес | 🟡 кандидат, узкий |
| | | | |
| спред wt1−wt2 как величина | 15m short | PF 1.39 · OOS 1.64 · 3 года из 4 | 🟡 кандидат |
| | | | |
| дистанция до ERL | 15m short | PF 4.03 → 8.66 · слепой прогон ПРОЙДЕН | 🔴 **на 40 монетах** — перемерить на ядре (136.E) |
| | | | |
| кластер филлов | 15m обе | +3.53%/сд · OOS +3.54 | 🔴 нереализуем при лимитном входе |
| | | | |
| амплитуда импульса ≥8.5% | 15m short | нестабильна: OOS 7.66 против 3.44 | 🔴 в конфиг НЕ ставить |

### Слой УПРАВЛЕНИЯ ПОЗИЦИЕЙ (в матрице признаков ОТСУТСТВУЕТ — это выход, а не вход)

> Найдено 27.08 по замечанию Егора «вспомни про TSL/каскады/эскалацию/деэскалацию».
> Код: `core/trading/tsl_engine.py` · `core/trading/cascade_tsl.py` · конфиг `trading.*`

| Метод | Где | Состояние | Что перепроверить |
|---|---|---|---|
| TSL простой (`compute_tsl`) | все источники | для impulse ОТКЛЮЧЁН (99.0) | обоснование: забирает 7-25% дохода — мерилось на простом TSL |
| | | | |
| TSL гибридный (`compute_hybrid_tsl`) | `tsl_hybrid_enabled: true` | вкл глобально | на impulse не мерился отдельно |
| | | | |
| КАСКАД вверх по ТФ (15m→1h→4h) | `cascade_tsl: true` | вкл | 🔴 на impulse_fib НЕ мерился ни разу |
| | | | |
| ДЕЭСКАЛАЦИЯ по R-градиенту | `check_r_gradient_drop()` | пик ≥2.5R, откат >40% | 🔴 не мерилась — может НЕ обрубать ход, в отличие от простого TSL |
| | | | |
| cap каскада после TP1 | `cap_tf_after_tp1: 1h` | вкл | не мерился |
| | | | |
| anti-degradation для ракет | `no_degrade_above_r: 8.0` | вкл | не мерился |
| | | | |
| force close в adverse OB | `is_price_in_adverse_ob()` | DEV-221 | не мерился |
| | | | |
| безубыток (BE) | `use_breakeven: false` | ВЫКЛ глобально | 🟡 замер: вредит в прибыльные периоды, помогает в убыточные |
| | | | |
| BE после TP1 | `use_be_after_tp1: false` | выкл | не мерился |
| | | | |
| частичная фиксация | `tp_partial_pct: 0.2` | есть в sl_tp | 🟡 замер: WR растёт, деньги падают |
| | | | |
| продление EXPIRED | `expired_extend_min_r: 5.0` | 120 часов | не мерилось |
| | | | |
| конверсия EXPIRED в TSL | `tsl_convert_min_r: 1.5` | только в трендах | не мерилась |
| | | | |
| динамический ATR для SL | `atr_dynamic: true` | expand 1.3 / contract 0.8 | не мерился |
| | | | |
| структурный SL | `struct_sl_buffer_pct: 0.3` | max 2.0% | не мерился |
| | | | |
| RR-кэп | `max_rr: 3.0` | impulse освобождён | ✅ проверено: кэп режет деньги |

### Слой РИСКА И ЗАЩИТЫ (вне матрицы, влияет на результат)

| Механизм | Состояние | Что перепроверить |
|---|---|---|
| 🔴 биржевой стоп-ордер | 22% позиций БЕЗ него | 🔴 [FIX-STOPS](#fix-stops) — корень пробоев −1R |
| | | |
| кэпы позиций / заявок | 10 / 12 на 15m | разведены 22.08, работают |
| | | |
| лимит на монету | 3 на сторону | не мерился на деньгах |
| | | |
| loss_streak_halt | пауза 6ч, для 8 механик выкл | ✅ трактовка отменена 22.08 |
| | | |
| circuit_breaker | вкл | вырезал 96% торговли — проверить снова |
| | | |
| dedup / sl_cooldown | вкл | не мерились на деньгах |
| | | |
| VST time-exit | 4.5ч для impulse_fib_15m | не мерился |

### 🔴🔴 ЧТО ВНЕ МАТРИЦЫ — сверка graphify + features_json (27.08.2026)

> Граф: `graphify-out/graph.json` (8442 узла, 17429 рёбер). Сверка боевых признаков
> с `combinator_core.compute_flags`. **Матрица покрывает 6% решающих признаков.**

| | количество |
|---|---|
| шаблонов в матрице | 79 (→446 после разворота по ТФ и старшим) |
| ключей в features_json боевых сделок | 230 |
| из них покрыто матрицей | **14** |
| 🔴 ВНЕ МАТРИЦЫ | **216** |
| Группа вне матрицы | Признаков | Примеры | Мерилось? |
|---|---|---|---|
| прочее (не классифицировано) | 125 | entry_priority · atr_trend_1h_bias · htf_wt1_1h · wt1_at_signal · confirmations · market_event · trigger_source · sideways_mode | ❌ нет |
| | | | |
| магниты и уровни | 21 | radar_magnet_above/below_pct · pivot_real_touch · pivot_close_rejection · pivot_volume_z · near_pivot_source | ❌ нет |
| | | | |
| маршрутизация и риск | 21 | soft_penalties · router_final_strength · gate_features · smc_verdict · verdict_gate · weekly_gate_would_block | ❌ нет |
| | | | |
| механика impulse (if_*) | 15 | if_age · if_amp_pct · if_vratio · if_score · if_size_mult · rr_at_entry | 🟡 частично (амплитуда) |
| | | | |
| рыночный контекст | 14 | phase · mkt_ac_regime · mtf_regime · btc_4h_regime · ud_d30/d90/d180 · ud_slope | 🟡 частично (дрейф) |
| | | | |
| ML и советники | 9 | ds_feature_mult · ds_confidence · wl_score · weekly_context_score · tp_selector_tp2_score | ❌ нет |
| | | | |
| исполнение и лаг | 8 | session · entry_lag_seconds · shadow_scan_loop_late · entry_price_lag_pct · data_era | ❌ нет |
| | | | |
| деривативы | 6 | radar_oi_d5 · radar_oi_d15 · radar_funding · radar_oi_px_quadrant · mkt_funding | ❌ нет |
| | | | |
| управление позицией | 3 в боевых, 15 методов в коде | conf_f_tsl_cross_up/down · tsl_degraded | ❌ нет |

### Модули с логикой решений (86 файлов, в матрицу входит один)

| Папка | Файлов | Примеры |
|---|---|---|
| core/smc | 27 | choch_wavec · confluence · dc_legs · fibonacci · fvg · impulse_assembly · liquidity |
| | | |
| core/intelligence | 20 | decision_fusion · entry_matrix · confidence_calibrator · feature_snapshot · advisor_connector |
| | | |
| core/signals | 13 | atr_change_detector · funding_detector · htf_detectors · liquidity_sweep_detector · ote_detector |
| | | |
| core/context | 11 | market_drift · marketcap_engine · phase_sphere · sphere_registry · trigger_bus |
| | | |
| core/indicators | 8 | anomaly_model · bounce_detector · divergence_detector · dynamic_thresholds · market_regime |
| | | |
| core/ml | 7 | ml_predictor · mtf_smc_specialist · mtf_wt_specialist · outcome_predictor · r_predictor · rl_exit_agent |
| | | |
| core/calculators | 2 | **combinator_core (это и есть матрица)** · swing_bridge |

### 🔴 Задача: свести матрицу воедино

| ID | Ст | Краткое | Роль |
|---|---|---|---|
| [MATRIX-FULL](#matrix-full) | 🔴 | Матрица покрывает 6% решающих признаков — 216 вне её, 86 модулей мимо замеров | DEV |

### 🔴 ПЛАН ПЕРЕПРОВЕРКИ — что мерить, в каком порядке (обновлено 27.08)

> Ст: 🔴 срочно · 🟡 важно · 🟢 в плане · 🔵 бэклог · 🔄 в работе · ✅ закрыто
> Отмечать по мере прохождения. Порядок = приоритет.

#### Слой 0 — БЛОКИРУЮЩЕЕ (без этого замеры не имеют смысла)

| # | Ст | Что перепроверить | Почему важно | Роль |
|---|---|---|---|---|
| 0.1 | ✅ | ~~биржевой стоп-ордер: 22% позиций без него~~ → **ЗАКРЫТА 28.08: это был ДЕФЕКТ УЧЁТА, а не отсутствие защиты.** Стоп ставился и срабатывал, а `repair_missing_sl` стирал `exchange_sl_order_id` **до** проверки живой позиции — то есть уже ПОСЛЕ срабатывания. Доказано посекундно (MOVR #58528: `06:18:06` стоп `…785` TRIGGERED `ap=0.72864` → `06:18:27` id стёрт). **«−15R» тоже фикция**: лимитка 389.9879 залилась тремя порциями (14.32→157.42→389.99) по одной цене, а защита от pa-глюка BingX стояла на посылке «добор сдвинул бы `ep`» — для лимитки ложной → store замёрз на 14.32, `CR-DELTA` поделил `Δcr` на него и выдал `exit=1.4138 / −101%` вместо `ap=0.7286 / ≈−1.2R`; тем же qty `sphere.close()` закрыл бы 14.32 из 389.99. Разрез: 39.9% «без sl_oid» включали `CANCELLED`-лимитки (позиции не было); по реально открытым 23.2%; из 24 пробоев хуже −1.05R у **23 из 24** выход в пределах 1.05–2.3 стопа. Сделано: порядок проверок · `_order_qty` в `PositionStore` (частичный филл проходит, глюк 52.2→522.0 ловится) · физический предохранитель `|Δcr| ≥ нотионал → каскад REST`. Регрессии `test_repair_missing_sl` 5/5 + `test_partial_fill_qty` 7/7, весь execution-слой **71 passed**; на старом коде падают (`git stash`). История НЕ переписана — `ledger_audit --mark` пометил **60 строк** (решение Егора 08.07 «пометить, не переписывать»). Рестарт + **SelfTest 12/12**. 🔴 Глубже 30 дней леджер не отдаёт — июньские 3123 записи не проверены | DEV |
| | | | | |
| | | | | |
| 0.3 | 🔄 | **MATRIX-FULL — идёт 28.08.** ✅ Создан [`docs/MATRIX_REGISTRY.md`](docs/MATRIX_REGISTRY.md) — первая полная карта признаков проекта: **87 модулей решений** → 34 ЧИСТЫХ / 18 гибридных / 34 живых · **15 дублей** (`detect_fvg` в ТРЁХ версиях) · **631 ключ** `features_json` с воспроизводимостью и явным списком «не вносить» (циркулярность). Классификация сверена **AST: 65/66 утверждений точны**. Связан из шапки `SIGNAL_BUS_CUBE_MAP.md` и `REGISTRY.md` §3. ✅ `scripts/matrix_full.py` — +124 признака, которых не было: фандинг (1.56 млн строк) · ширина/дрейф вселенной из кэша 4h · непрерывные дистанции до магнитов · СОСТОЯНИЕ осцилляторов вместо булевых событий. Причинность проверена прогоном (`wt1_val[i] == wavetrend[i-1]`). ✅ `scripts/matrix_global_run.py` — прогон на **565 признаках** (429 булевых + 136 числовых). 🔑 **Находка: `trade_features` (41 072 строки) УЖЕ хранит причинный снимок матрицы с 31.05** — пересчитывать не нужно. ❌ **История OI не существует физически** (`oi_fast_poller.py:1101`: `PRIMARY KEY` + `INSERT OR REPLACE` = только текущий снимок) — направление закрыто. 🔴 **ДВА ДЕФЕКТА ИНСТРУМЕНТА:** (1) `blind_select` проверял любой признак как `f > 0` — для 136 числовых это единственный порог «ноль» → добавлен `blind_select_num` с децилями в обе стороны; (2) порог `pf > 1.2` АБСОЛЮТНЫЙ, а база бывает 1.28 → пропускались подвыборки ХУЖЕ базы; сквозной перестановочный контроль показал **136 «кандидатов» из 136 на перемешанном pnl** → порог сделан относительным (`> base × 1.15`). ✅ Опровергнуто прогоном: гипотеза о выпадении MTF-признаков из-за `dtype == object` НЕ подтвердилась, все 435 доходят | DEV |

#### Слой 0.5 — ФОРВАРД-ТЕСТ ЛИМИТНОГО ВХОДА (открыт 28.08)

| # | Ст | Что | Почему важно | Роль |
|---|---|---|---|---|
| 0.4 | 🔄 | **ote_nested на ЛИМИТНОМ входе — наблюдение** | 🔴🔴 Вскрыто 28.08: `entry_order_type: LIMIT` стоял у источника **ещё до 25.07**, но `signal_router.enabled` был false до 25.07 02:09 (`e7713cf`) и старый путь ставил ордера **МИМО политики**, рыночными. Источник торговал 04.06→24.07, роутер включили 25.07 — окна пересечения НЕТ. **Все 5008 биржевых сделок прошли рыночным входом вопреки объявленной политике** ([[bug_source_policies_deadpath_router_off]]). Замер спреда песочницы (4326 сделок, эталон — реальная свеча 15m): филл вне бара против нас **24.6:1** при контроле 0.3:1; **лимитные источники обложены в 1.4%, рыночные в 43.6%**. Сделано: `pending_lifecycle`+`entry_ttl_bars: 4`+`entry_tf: 1h` · `_mark_pending` в `_register_ote_trade` (переиспользован лайфцикл `impulse_fib_runner`) · `min_sl_dist_per_strategy.ote_nested: 0.3` (🔴 preflight поймал: глобальные 4.0% при медианном стопе 0.63% резали источник целиком) · `exchange_enabled: true` · `ote.vst_trading.enabled: true`. Проверки: pydantic strict · preflight чист · `test_ote_limit_entry.py` 6/6 · SelfTest 12/12. **Ожидаемый поток:** единственный enabled-сетап `4h_1h_pull`, на биржу идёт только премиум (`fvg_held`) — исторически 808 сделок за 45 дней ≈ 18/день, минус каскад-гейт ≈ 9/день. Историческая премиум-выборка на РЫНОЧНОМ входе: n=808 WR 54.2% PF 1.48 ср **+0.395%** — 🔴 но безтоп10% **−150**, то есть плюс держится на верхних 10%. ⬅ **ЧТО СМОТРЕТЬ:** доля филов лимиток (если ~0 — TTL 4 ч мал), слип на филе против рыночной эпохи, безтоп10% на боевых | DEV |
| | | | | |
| 0.5 | 🟢 | сократить задержку сигнала (FIRE по кэшу до ~10 мин) | 🔴 Замерено 28.08: `entry_lag_seconds` медиана **3.0 с**, Spearman(лаг, слип) **+0.081**, даже при мгновенном входе слип +0.234% → потолок оптимизации лага ≈**0.12 п.п.**, гнаться не за чем. Настоящая задержка — возраст кэша в `ote_observer_loop` (интервал 600 с, ARMED-вотчер 12 с). Делать ТОЛЬКО если лимитный вход себя покажет | DEV |

#### Слой 1 — ВХОД (что уже мерилось, требует доработки)

| # | Ст | Что перепроверить | Почему важно | Роль |
|---|---|---|---|---|
| 1.1 | 🟡 | слепой отбор ПОВЕРХ дрейф-гейта | харнесс гоняет на общей базе, где кандидаты слабее — нужна доработка харнесса | DEV |
| | | | | |
| 1.2 | 🟡 | конфлюэнция ПО ЭТАЖАМ 15m/1h/4h | 290 признаков старших ТФ мерились поодиночке, набором — ни разу | DEV |
| | | | | |
| 1.3 | 🟡 | свежесть WT + медиана SMA(50) в shadow | подтверждены на боевой базе, независимой проверки протоколом нет | DEV |
| | | | | |
| 1.4 | 🟡 | дистанция до ERL в shadow | слепой прогон пройден, но в бою не наблюдалась | DEV |
| | | | | |
| 1.5 | 🟢 | амплитуда 8.5% на третьей выборке | нестабильна: OOS 7.66 против 3.44 — решить, живой признак или шум | DEV |
| | | | | |
| 1.6 | 🟢 | 5m как младший этаж | 449 символов в кэше, не трогали вовсе | DEV |
| | | | | |
| 1.7 | 🔵 | short на 1h | всего 57 сделок — выборки не хватило для вердикта | DEV |

#### Слой 2 — ВЫХОД (15 методов, мерены 3)

| # | Ст | Что перепроверить | Почему важно | Роль |
|---|---|---|---|---|
| 2.1 | 🔴 | КАСКАД по ТФ + ДЕЭСКАЛАЦИЯ по R-градиенту | простой TSL обрубает ход (мерено), каскадный — НЕ мерен; 75% прибыли даёт ход к цели | DEV |
| | | | | |
| 2.2 | 🟡 | cap каскада после TP1 · anti-degradation R≥8 | гейты каскада включены и работают вслепую | DEV |
| | | | | |
| 2.3 | 🟡 | force close в adverse OB (DEV-221) | закрывает позиции, эффект не мерен | DEV |
| | | | | |
| 2.4 | 🟡 | продление EXPIRED (120ч) + конверсия в TSL | влияет на исход зависших сделок, не мерено | DEV |
| | | | | |
| 2.5 | 🟢 | динамический ATR для SL · структурный SL | expand 1.3 / contract 0.8 — пороги вслепую | DEV |
| | | | | |
| 2.6 | 🟢 | BE после TP1 · частичная фиксация 20% | BE мерен как общий (вредит в плюс), после TP1 — нет | DEV |

#### Слой 3 — КОНТЕКСТ И ДАННЫЕ (вне матрицы, влияет на решения)

| # | Ст | Что перепроверить | Почему важно | Роль |
|---|---|---|---|---|
| 3.1 | 🟡 | деривативы: OI d5/d15 · funding · oi_px_quadrant | 141 сделка с этими признаками, ни разу не мерены | DEV |
| | | | | |
| 3.2 | 🟡 | магниты: magnet_above/below · pivot_real_touch · pivot_volume_z | 21 признак, в матрице нет | DEV |
| | | | | |
| 3.3 | 🟡 | фазы и режимы: phase · mkt_ac_regime · btc_4h_regime | phase есть в 400 сделках из 400 — и не мерен | DEV |
| | | | | |
| 3.4 | 🟢 | ML-слой: ds_confidence · wl_score · tp_selector | 9 признаков, влияют на размер и выбор цели | DEV |
| | | | | |
| 3.5 | 🟢 | 125 неклассифицированных признаков | entry_priority · atr_trend_1h_bias · confirmations · trigger_source | DEV |

#### Слой 4 — ИСПОЛНЕНИЕ И РИСК

| # | Ст | Что перепроверить | Почему важно | Роль |
|---|---|---|---|---|
| 4.1 | 🟡 | лаг исполнения: entry_lag_seconds · scan_loop_late · entry_price_lag_pct | 400 из 400 сделок помечены, эффект на результат не мерен | DEV |
| | | | | |
| 4.2 | 🟡 | событийный вход вместо лимитного | открывает кластер филлов (+3.53%/сд) и позицию в диапазоне | ARCH |
| | | | | |
| 4.3 | 🟢 | параллельный фетч + расширение вселенной до 478 | цикл 26→16 мин, сделок +57%, спреды в хвосте не хуже | DEV |
| | | | | |
| 4.4 | 🟢 | circuit_breaker · dedup · sl_cooldown · лимит на монету | режут поток, на деньгах не мерены | DEV |
| | | | | |
| 4.5 | 🔵 | спреды в моменты волатильности | замерен мгновенный снимок, а входим мы в движении | DEV |

#### Слой 5 — ЧИСТКА

| # | Ст | Что перепроверить | Почему важно | Роль |
|---|---|---|---|---|
| 5.1 | 🟡 | watch_list_breach · wt_sideways · atr_change · confluence | 28+ тысяч сделок с отрицательным R — закрыть или перемерить | ARCH |
| | | | | |
| 5.2 | 🟢 | rangefade / rangefade4h / ds_advisor: почему молчат | включены в конфиге, сделок нет с 13.08 | DEV |


---

