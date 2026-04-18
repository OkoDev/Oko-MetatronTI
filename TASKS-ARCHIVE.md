# 📦 TASKS ARCHIVE — Завершённые задачи

> Все задачи со статусом ✅. Детальные спецификации — в git-истории и PROJECT-LOG.md.
> Последнее обновление: 05.04.2026.

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
