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

