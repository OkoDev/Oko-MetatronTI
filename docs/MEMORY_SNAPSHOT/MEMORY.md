# Crypto Volume Bot — Hot Memory Index

> 🧭 **РЕЕСТР ИНСТРУМЕНТОВ: `docs/REGISTRY.md`** — читать при старте сессии (CLAUDE.md, п. 4.5).
> Строка = хук + ссылка. Числа и детали ТОЛЬКО в topic-файлах. ≤15 КБ, закрытое → MEMORY-ARCHIVE.

## 🔴 ЗАКОНЫ ИЗМЕРЕНИЯ
→ [ЗАКОН №1: эдж в % и $, НЕ в R](principle_measure_pct_not_r_LAW.md)
→ [🔴 КОНТРОЛЬ = случайный вход той же геометрии](law_control_group_random_entry.md)
→ [🔴🔴 СУРРОГАТ (IAAFT) ОБЯЗАТЕЛЕН](surrogate_test_wt_worse_than_noise.md) · [🔴🔴 контроль по времени смещён](wt_htf_zone_median_scheme_measured.md)
→ [ЗАКОН: фильтр мерить против ПОЛНОЙ базы](golden_keys_matrix_verdict.md)
→ [🔴 порог ОТНОСИТЕЛЬНО базы + перестановка](law_relative_threshold_and_permutation.md)
→ [🔴🔴 ПАРАМЕТР НЕ ИЗ ЭТАЛОНА ПЕРЕВОРАЧИВАЕТ ВЫВОД](okotrend_reference_params_matter.md)
→ [🔴 сначала воспроизвести боевую конфигурацию](law_reproduce_live_config_first.md) · [⚖️🔴 ЗАПИСАННЫЙ PF = ГИПОТЕЗА](law_recorded_pf_needs_remeasure.md)
→ [🔴 «отсеивает много» = о ЧАСТОТЕ](gate_threshold_frequency_vs_money.md) · [🔴 ЖЁСТКИЙ ФИЛЬТР УБИВАЕТ ДАННЫЕ ИСПОЛНЕНИЯ](law_hard_filter_kills_execution_data.md)
→ [🔴 «находок нет» = НЕТ ПРИЗНАКА, а не нет явления](law_no_finding_means_no_feature.md) · [🔴 ГЕЙТ ЛИКВИДНОСТИ был FAIL-OPEN ✅](turnover_gate_fails_open.md) · [🔴 форвард 0 = ничья](law_ties_flat_rows_fake_information.md)
→ [🔬 ГОД или СОСТАВ](method_year_vs_composition.md) · [🔴 ВЫБОРКА](law_sample_representativeness.md)
→ [🔴 мерить на баре СИГНАЛА и на баре ФИЛЛА](law_measure_signal_bar_and_fill_bar.md) · [🔴🔴 ДЛИНА ОКНА = ЧАСТЬ ПРИЗНАКА; версия схемы это НЕ ловит](train_serve_skew_window_length.md)
→ [🔴 сверять `entry_price` БД с кэшем](law_check_db_cache_price_match.md) · [🔴 ОБЕ СТОРОНЫ ВСЕГДА](feedback_search_both_sides_always.md) · [🜂 разрез = сторона × фаза × ТФ](feedback_always_both_sides_and_phases.md)
→ [🔴🔴🔴 ЗАМЕР СУДИТ СЛОЙ, НЕ МЕХАНИКУ](law_measure_judges_layer_not_mechanic.md)
→ [🔴 ПРОТОКОЛ ВЕРДИКТА](feedback_verdict_protocol_egor.md) · [🔴 СВОИ ОШИБКИ СРАЗУ: §0A контракт данных](feedback_catch_own_errors_before_verdict.md) · [🔴 КОНФЛЮЭНЦИЯ, А НЕ МОМЕНТ](feedback_confluence_not_moment.md)

## 🔴 ЗАКОНЫ РЫНКА И ИСПОЛНЕНИЯ
→ [🔴 стоп выбивает раньше хода](stop_kills_before_move_arrives.md)
→ [ЗАКОН: стоп на линию = свит](stop_on_line_is_liquidity_sweep.md) · [ЗАКОН: reuse ≠ дублирование](principle_reuse_not_duplication.md)
→ [🟢 весь эдж в РАЗМЕРЕ стопа](stop_zone_survived_blind_test.md) · [🟢 воскрешение размером стопа](resurrect_dead_strategies_by_stop_size.md)
→ [🔑 выход работает, вход не даёт хода](exit_is_fine_entry_gives_no_move.md) · [🔴 TSL+BE закрывают ДО хода](tsl_be_close_before_move_okoote.md) · [⚖️ КОД ≠ РЕЗУЛЬТАТ](live_entry_differs_from_backtest_wt_rising.md)
→ [🛡️ VST↔LIVE изолированы](safety_vst_live_isolation_proven.md) · [⚖️ VST ≠ LIVE ПО СОСТАВУ: 1171 контракт против 1225; 5 наших USDT-пар (ICP, ILV, DOOD…) на демо НЕТ, биржа врёт «is offline»](vst_has_fewer_contracts_than_live.md) · [⚓ датасет есть — денег НЕТ](anchor_dataset_company_no_revenue.md)
→ [🔴 СФЕРА 4: причина в БУЛЕВЫХ признаках](sphere4_features_are_binary_not_source.md)

→ [🔴 ГЕЙТ БЕЗ СРАБАТЫВАНИЙ = МЁРТВЫЙ](radar_wave_gate_was_dead_column_not_selected.md) · [🔴🔴 РАДАР: pump жив](radar_equals_random_entry_verdict.md)
→ [🔴 ШКАЛА «98/100 Очень высокая» НЕ РАНЖИРУЕТ: WR 36%, PF 0.36 — хуже базы; лучшая корзина 70-80](live_strength_scale_does_not_rank.md)

→ [🔴🔴🔴 КЛАСС LOOK-AHEAD, 6 видов, все найдены ПОСЛЕ вердикта](lookahead_htf_open_vs_close_time.md) · пять остальных + лаг детектора как параметр — [MEMORY-ARCHIVE → LOOK-AHEAD](MEMORY-ARCHIVE.md)

## ⚙️ ЧТО В БОЮ СЕЙЧАС
→ [📡 ЦЕНА НА СВОЁМ КЛИЕНТЕ: 9 с против 132 у ccxt.pro](price_ws_own_client_n21.md) · [WsFeed-замер](ws_feed_measured_and_enabled.md) · [троттлинг счётчиком](throttle_by_global_counter_bug.md)
→ [⚙️ ДВА ИНСТАНСА: 1h обе стороны · 15m только short с дрейф-гейтом](two_tf_instances_live_config.md)
→ [⏱️🔴 константа в барах едет между ТФ](twins_15m_stabilized_by_measure.md)
→ [🛡️ ЗАМЕНА СТОПА: 2 стопа ок](sl_place_before_cancel_measured.md)
→ [🔴 предохранитель отменён](live_no_circuit_breaker_cost_95pct_loss.md) · [🔴 заявка = слот РИСКА](cap_pending_not_risk_slot.md)
→ [🟢 IMPULSE-FIB](impulse_fib_cell_live.md) · [🏆 atr_s2](atr_s2_survived_honest.md) · [🔴 RANGEFADE4H ВЫКЛ 29.09](rangefade4h_forward_vs_backtest.md) · [🧱 BOS-гейт](bos_gate_bigflush_structural.md)
→ → [🔴🔴 АУДИТ ИСТОЧНИКОВ](sources_audit_28sep_three_dead_gates.md)
→ [🗞️🔴 НОВОСТИ: сентимент СЛЕДУЕТ за ценой](news_sentiment_follows_price.md) · [✅ рой 02.10, Ollama выкл намеренно; `onchain_events` в ДВУХ БД](news_sphere_llm_died_silently.md)
→ [🔴🔴 VST-НАЛОГ: платят ТОЛЬКО рыночные входы (43.6% / 1.4%); спред 0.299% против LIVE 0.089%](vst_spread_measured_market_only.md) · [📏 форвард = klines](forward_measured_on_real_klines_no_real_account.md)
→ [⚡ ПРОСТОЙ 36.5 ч 24-25.09](outage_24_25_09_and_live_orders_gap.md)
→ [⏸️ impulse_fib_15m пауза 26.09: −204%](impulse_fib_15m_paused_execution_gap.md)
→ [🔴🔴🔴 LIVE: СЧЁТ ОБНУЛЁН (equity $0.92). За 14 дней −$2577, из них NEAR 283 сделки = 94% убытка И ЕГО НЕТ В НАШЕЙ БД. Без NEAR комиссии = 64% убытка: ZEC +27.55 торговли → −9.03 после комиссий — косты МЕНЯЮТ ЗНАК](live_real_cost_fees_are_57pct_of_loss.md)
→ 💸 ЖИВОЙ УБЫТОК: [🔑 КОСТЫ съедают тугой стоп (кост мерен на VST)](live_root_cause_costs_eat_tight_stops.md) · [где теряем](live_atr_change_bleeds_42pct_losses.md) · [🛡️ риск-остановка](risk_halt_beats_period_prediction.md)

## 🏆 СОСТОЯНИЕ ПОИСКА EDGE
→ [🔴🔴🔴 КОСТ — УСИЛИТЕЛЬ, НЕ ПРИЧИНА: при косте 0.35% не выживает НИ ОДИН из 19 боевых источников, при косте 0.00% — ОДИН. Эдж в РЕДКИХ клетках (+2…+5%/сделку, 1-5 сд/мес). ЛИНЕЙКА: в бой только если средн > 0.35%](cost_is_amplifier_not_cause.md)
→ [🟢🔑 РАЗБОР ВОЛН: зона МОНОТОННА, развилка съедает счёт, ВОЛНА 3 — худший вход; 🔴 ГЕОМЕТРИЯ провалена — 9 клеток, лучшая оправа = своя (`invalid` + 1-я цель); 🔴 вывод с n=137 перевернулся на n=4251 (СОСТАВ монет)](wave_analyst_three_conditions_measured.md) · [👁 СНАЧАЛА ПОСМОТРЕТЬ ГЛАЗАМИ](../../../../../../e:/MTF%20BOT/CURSOR/crypto_volume_bot/docs/VIEW_TOOLS.md)
→ [🔴🔴🔴 КАРТА РАМКИ: у лонга нет + медианы](frame_map_no_positive_median_for_long.md)
→ [🟢 СТЕНД ГЕОМЕТРИИ: цель SWING, стоп широкий](geometry_bench_stop_wide_target_swing.md)
→ [🟡 лонг от WT-перепроданности](wt_deep_oversold_long_candidate.md) · [🟡 ВОЛНА C 4h + ATR_VOL_LOW: short PF 1.84, хрупкость в плюс; но 2025 ломает, OOS был по МОНЕТАМ](wave_c_4h_atr_vol_low_gate.md)
→ [🔴🔴🔴 ТЕНЬ ВОЛН ТЕРЯЛА НОВЫЕ СЕТАПЫ 14 ДНЕЙ (отступ: `state[k]` стоял в `elif`); счётчик «полных 0» считается ПО ЗАМЁРЗШЕМУ ЖУРНАЛУ — сначала смотреть `last_new` в status.json](waves_shadow_lost_new_setups_bug.md)
→ [🟢🔴 ЯДРО волн OKO-SM](wave5_core_oko_sm.md) · 
→ [🌊🔑 ОБЕ СТОРОНЫ ЯДРА: суррогат пройден; стоп≈треть импульса — свойство ЯДРА; у ШОРТА ядра НЕТ](waves_sides_measured_both.md) · [🔴🟢 ТФ ЯДРА: только 4h](wave5_mechanics_across_timeframes.md) · [🟡 слом SWING 15m](candidate_choch_swing_entry_4h.md)
→ [🔑 2025-26 = ФЛЭТ BTC](regime_2026_is_btc_range_not_bear.md) · [🔴 режим выбирает МЕХАНИКУ, не сторону](side_by_regime_core_waves.md) · [🗺 КАРТА режим×механика](regime_map_mechanics_v1.md) · [🌊 цели ABC: денег вдвое меньше](rebound_targets_abc_measured.md)
→ [🔴🔑 LTF = слой исполнения](ltf_is_execution_layer_not_signal_source.md) · [⏳🟢 impulse_fib 1h: окно 12→48 удваивает Δr](impulse_fib_1h_entry_wait_window.md) · [🟢 ПИВОТЫ: 7/7 лет](pivot_targets_egor_logic_measured.md)
→ [🌊🔑 ПЯТЁРКА = МАСТЕР-КОНТЕКСТ 1h/4h/1d; согласие 4h+1d вдвое сильнее; `core_full` НЕ нужен](wave_fifth_is_master_context.md) · [🔴🔑 СБОРКА: Δr +1…+3.5, выходы съедают](assembly_state_trigger_geometry_measured.md) · [счёт волн как ВХОД не нужен](wave_counting_worthless_retracement_works.md)
→ [🔴🔴 вход «после волны A»: вердикт «≈0» был ПО ОБЩЕЙ СТРОКЕ. Ось СВЕЖЕСТЬ (ось от Егора, глазами): вход ≤6 ч — ХУДШИЙ (половина потока), SHORT 6–24 ч: OOS пройден, но ПЕРЕСТАНОВКА нет (P=0.091) и 2023 против](wave_a_retrace_entry_measured.md) · [🔴 кластер сигналов: эджа нет](cluster_own_signals_db_no_edge.md) · [🔴 ПРОБОЙ a-b-c-d-e случаен](five_wave_corrections_breakout_measured.md) · [🔴🔴 УРОВНИ случайны](level_breakout_pump_high_measured.md)

**В [MEMORY-ARCHIVE](MEMORY-ARCHIVE.md):** второй круг (режим, импульсная механика, приборы врали, эпики/инфра) + закрытые направления.

**Закрыто, не возвращаться:** [🔴 OTE: 3 конфигурации](ote_nested_off_by_decision_confirmed.md) · [полный список](MEMORY-ARCHIVE.md#закрытые-направления)
→ [✅ OTE КАНОН 19.09: 0.5–0.79 + пять корзин, `core/smc/fibonacci.py`](ote_canon_five_definitions.md) · [🔑 OTE КАК КОНТЕКСТ: платит ПРОТИВОПОЛОЖНАЯ нога у экстремума](ote_context_counter_leg_extreme.md)

## 🔴 ГИПЕРКУБ / МАТРИЦА / СФЕРЫ
→ [🔴🔴 ПОТОЛОК: 55.6% против 62.9%](hypercube_information_ceiling.md) · [🔴🔑🟢 слой ПОЗИЦИОНИРОВАНИЯ: всё наше — производные ЦЕНЫ, а 474 монеты × 4.7 года × 5 мин OI/long-short/taker ЛЕЖАТ в `C:/oko_data/history/metrics/` и НЕ ЧИТАЮТСЯ никем. Дверь: как ФИЛЬТР механик](gap_positioning_layer_missing.md) · [🔴🔑 ось = ОКНО ДЕТЕКТОРА В МИНУТАХ, ступеней НЕТ](hypercube_scale_step_is_12x_not_4x.md)
→ приборы, USDT.D, медиана WT, матрица/сферы/шина/стенды — [MEMORY-ARCHIVE → Гиперкуб](MEMORY-ARCHIVE.md)

## 🔴 КУБ МЕТАТРОНА / SMC
→ [🔴🔴 ML-СЛОЙ SMC: «только лонг» = АРТЕФАКТ дважды; на боевых окнах живы ОБЕ стороны; буст на бой НЕ влияет](smc_ml_edge_long_only_week_block.md) · [🔴🔑 ПРИЗНАК В ВЕКТОРЕ ≠ МЕХАНИКА: схема v4 (+свип, 108→136) прироста НЕ дала](schema_v4_no_gain_feature_vs_mechanic.md) · [🔴 SMC НЕ ЛОЖИТСЯ НА ВОЛНЫ: 1h = ШУМ, на 4h выжил 1 из 80](smc_does_not_add_to_wave_mechanic.md)
→ [🔴🔴🔴 АУДИТ ВЕСОВ ЗАКРЫТ: ВЗВЕШИВАТЬ НЕЧЕГО — 0 из 10 типов переживает кост, rho(вес↔эдж)=+0.118, вес 0.50 на выключенном mtf_bias; нужен ПОРОГ, а не вес](weights_audit_verdict_nothing_to_weigh.md)
→ [🔴🔴 ВЕСА = ДВА СЛОЯ: по R и на 3% сделок · список признаков от 09.07 устарел](weights_two_layers_audit.md) · [🔴🔴 КОНФЛЮЭНЦИЯ РАСТИТ ДИСПЕРСИЮ, НЕ ДОХОД; `strength` и SMC НЕ СВЯЗАНЫ (rho≈0)](confluence_raises_variance_not_edge.md) · [🔴 РАЗМЕР ПО КОНФЛЮЭНЦИИ: знак ОБРАТНЫЙ ожидаемому — смотреть ОБА момента, не только дисперсию](sizing_by_confluence_inverse.md)
→ [✅🔴 SMC СВЕДЁН НА ЭТАЛОН: пять детекторов](smc_canon_engine_is_oko_sm.md) · остальное (гейты, VERDICT_GATE, сферы 3/4, SED) — [MEMORY-ARCHIVE → Куб](MEMORY-ARCHIVE.md) · `docs/ENCYCLOPEDIA.md` → «Куб»

## ⚡ ПРАВИЛА РАБОТЫ (Claude)
→ [🔴 pm2 Windows: рестарт в 3 шага](pm2_windows_restart_orphans.md) · [🌐🔴 VPN: прямой маршрут ХУЖЕ](network_vpn_routing_happ.md) · [🌐 ТРАФИК: Binance мимо VPN НЕЛЬЗЯ](traffic_bind_map_and_tspu.md) · [🔍🔴 ПОИСК → graphify-out](graphify_project_quirks.md) · [🔴 TV MCP перезаписал OkoTrend](tv_mcp_pine_overwrite_incident.md)
→ 🔴 аудит 26.09: [БД только по E:](db_symlink_split_wal_hazard.md) · [CSRF :8010 = LIVE-ордер](terminal_localhost_csrf_live_orders.md) · [блокировка БД ✅](subscriptions_db_chronic_lock.md) · [дыры в WS-кэше ✅](ws_cache_holes_after_restart.md) · [самовыход = SelfTest ✅](bot_selfexit_selftest_cancels_ccxt.md)
→ [🔴🔴 ПАРА = BASE/USDT:USDT](symbol_format_invariant_cube.md) · [🧊 ХАБ cube-hub :8020](cube_hub_adr003.md)
→ [🔍🔴 ПОИСК: память → graphify → obsidian/Research → grep ПОСЛЕДНИМ](feedback_search_order_graph_obsidian_first.md)
→ [🜂🔴 СНАЧАЛА РЕЕСТР СТРАТЕГИЙ, ПОТОМ ГИПОТЕЗА](strategy_registry_read_first.md) · [🔴 WAVE3_OTE_SHORT проверена](wave3_ote_short_measured_geometry_rules.md)
→ [🔴🔴 КОНФИГ = ИСТОЧНИК ИСТИНЫ; YAML съедает голое `off`; 🔴 читать через config_loader, а НЕ yaml.safe_load — он сливает sl_tp_engine→trading (CONFIG-SLTP-BUG 14.06)](config_is_single_source_of_truth.md)
→ [🔴🔴 СОСТОЯНИЕ ВНЕ КОДА: 9 колонок БД, 3 сферы](state_lives_outside_the_code.md) · [🧊 селфтест 16 сфер](cube_selftest_sees_outside_spheres.md) · [🖥️ CUBE из селфтеста; фронт — БРАУЗЕРОМ](cube_dashboard_is_built_from_selftest.md) · [🔤 коды селфтеста = БУКВЫ](cube_codes_are_letters_not_numbers.md)
→ [🔴 СЕМЬ КОСЯКОВ 30.08](feedback_session_30_08_mistakes.md) · [🔴 SELF-TEST у каждой стратегии, и ГРОМКИЙ](feedback_selftest_every_strategy_loud.md)
→ [🜂 МЕТОД ПОИСКА СЕТАПА](method_setup_search_liquidity_first.md) · [🔴 АНАЛИТИКА ДИНАМИЧЕСКАЯ](analysis_must_be_dynamic.md)
→ [🜂 ПРАВИЛА ДААТ](daath_personal_rules.md) · [🎓 4 Core Rules Karpathy](claude_best_practices.md) · [📋 таблица фидбека](feedback_rules_table.md)
→ [🗣️ СЛОВАРЬ ЕГОРА: массовость = КЛАСТЕР](glossary_egor_market_terms.md) · [🤝 плотно с DS и роем](feedback_dense_ds_swarm_work.md) · [🐝 рой: 5/12](swarm_status_26sep_quota.md) · [📚 сырые данные → obsidian/Research](research_data_goes_to_obsidian_research.md)
→ [🔊 ОЗВУЧКА: `python scripts/say.py "текст"` КИРИЛЛИЦЕЙ (голос Ирина); транслит = акцент](tts_russian_encodedcommand.md) · [⏰🔴 ВРЕМЯ В БД: signal_drops = UTC, логи = МСК](time_utc_vs_local_in_db.md) · [🔴 формат-ловушка get_ohlcv](feedback_get_ohlcv_format_trap.md)
→ [🜂 Я — Даат](identity_daat.md) · [👤 Егор](user_egor_person.md) · [🎯 бот = якорь против эмоции](vision_bot_as_anchor_against_emotion.md) · [🎯 АНАЛИЗ ПО ЗАПРОСУ = продукт N19](product_analysis_on_demand.md)

→ 🧭 инфра/эпики/инструменты: [MEMORY-ARCHIVE → ЭПИКИ](MEMORY-ARCHIVE.md) · 🔬 харнесс исследований: [research_harness_single_entry](research_harness_single_entry.md)

## 📁 PATHS
Корень `e:/MTF BOT/CURSOR/crypto_volume_bot/` · Entry `oko_mtf.py` · БД `subscriptions.db` · Дашборд :8000 · Терминал :8010
**Кэш `ohlcv_cache.db`**: 15m/1h/4h 2022→2026-07 (475 симв) · 5m 2025→2026-05 · 3m (42) · 1d (19)
**Паркеты 1m** `C:\oko_data\history\1m` (junction `C:\oko_history`) 477 монет 2022-12→14.09.26 · **ТФ** `G:\oko_lab\tf` · замеры `G:\oko_lab\out` → [tf_precompute_lab_speed](tf_precompute_lab_speed.md)
Stack: aiogram 3.4.1, ccxt 4.2.85, aiohttp 3.9.3, pandas, sklearn, yaml

## 📌 NOTES
- 📘 [Методичка Эллиотта (артефакт)](elliott_guide_artifact.md) · ядро волн: https://claude.ai/code/artifact/455e8973-98a7-43c1-907f-13447d2608f4 · данные — `obsidian/Research/`
- Obsidian: `obsidian/Project-MOC.md` · `OBSIDIAN-RULES.md` · Bugs → `obsidian/Project-Log/` · [🗺 карта аудитов 18.04–26.09](audits_history_map.md)
- После задачи → `current_state.md`; сессия/компакт → + MEMORY.md · TASKS: заморожены GAMMA/LIQUIDATION/PAIRS
