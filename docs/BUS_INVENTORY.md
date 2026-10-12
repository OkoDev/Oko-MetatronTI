# 🧾 ОПИСЬ ШИНЫ — кто пишет, кто читает, чего нет, кто считает мимо

> Сгенерировано `scripts/bus_inventory.py` 12.10.2026 23:35 UTC (ARCH-142.1).
> Писатели — из `core/context/bus_catalog.py`. Читатели — по упоминаниям имени поля в коде: это ОЦЕНКА,
> у общих слов (`regime`, `watchlist`) она завышена. Правило ARCH-142: всё, что нужно «на сейчас», читается
> из шины; считать самому можно только замер на истории — теми же функциями ядра.

## 1. Сводка

- полей пары в коде: **96** · без описания в каталоге: **0**
- полей без единого упоминания вне определения: **24**
- в живом хабе у BTC полей: **96** · есть в коде, но не пришло: нет · пришло, но нет в коде: нет
- возраст состояния BTC в хабе: 3.6 с

## 2. Снимки и отметка времени (урок F01)

Снимок без отметки времени читатель не может проверить на свежесть.

| Поле-снимок | Ключи времени внутри | Отдельное поле времени |
|---|---|---|
| `wt_snap` | **нет** | — |
| `smc_snap` | timestamp | — |
| `pivot_snap` | **нет** | — |
| `wave_snap` | ts | `wave_recount_ts`, `wave_updated_at`, `wave_ctx_updated_at` |
| `wave_leg_up` | **нет** | `wave_recount_ts`, `wave_updated_at`, `wave_ctx_updated_at` |
| `wave_leg_dn` | **нет** | `wave_recount_ts`, `wave_updated_at`, `wave_ctx_updated_at` |

## 3. Поля пары: писатель и читатели

| Поле | Писатель | Упоминается в файлах | Где (до 3) |
|---|---|---|---|
| `last_ohlcv_time` | scan_loop (Сфера 1) | 0 | **никто** |
| `ohlcv_tfs_loaded` | scan_loop (Сфера 1) | 1 | core/observability/decision_trace.py |
| `tick_price` | WsFeed / scan_loop (OHLCV close) | 13 | core/context/context_factory.py, core/context/cube_mirror.py, core/context/cube_projection.py |
| `tick_time` | WsFeed / scan_loop | 0 | **никто** |
| `volume_24h` | scan_loop (Сфера 1) | 11 | core/trading_intelligence.py, core/context/context_factory.py, core/infra/ws_feed.py |
| `volume_24h_time` | scan_loop (Сфера 1) | 1 | core/context/context_factory.py |
| `price_change_24h` | scan_loop (Сфера 1) | 9 | core/trading_intelligence.py, core/context/context_factory.py, core/intelligence/confidence_calculator.py |
| `atr_pct` | scan_loop (Сфера 1) | 15 | core/context/cube_inbox.py, core/db/subscription_manager.py, core/observability/decision_trace.py |
| `atr_pct_time` | scan_loop (Сфера 1) | 0 | **никто** |
| `wt_verdict` | scan_loop (Сфера 3) | 9 | core/selftest_cube.py, core/trading_intelligence.py, core/context/shadow_consumers.py |
| `wt_confidence` | scan_loop (Сфера 3) | 2 | core/context/shadow_consumers.py, web/dashboard_server.py |
| `wt_snap` | scan_loop (Сфера 3) | 12 | core/trading_intelligence.py, core/context/cube_projection.py, core/context/shadow_consumers.py |
| `smc_verdict` | sub_cube (Сфера 4) | 10 | core/trading_intelligence.py, core/context/sphere_registry.py, core/intelligence/narrative_builder.py |
| `smc_confidence` | sub_cube (Сфера 4) | 1 | web/dashboard_server.py |
| `smc_snap` | sub_cube (Сфера 4) | 14 | core/trading_intelligence.py, core/context/cube_projection.py, core/intelligence/narrative_builder.py |
| `btc_regime` | scan_loop (Сфера 5) | 12 | core/trading_intelligence.py, core/context/cube_mirror.py, core/intelligence/arch104_signal_adapter.py |
| `btc_move_pct` | scan_loop (Сфера 5) | 1 | bot/loops/scan_loop.py |
| `cross_market_time` | scan_loop (Сфера 5) | 0 | **никто** |
| `regime` | scan_loop (Сфера 6) | 45 | core/trading_intelligence.py, core/context/cube_projection.py, core/context/shadow_consumers.py |
| `reversal_mode` | scan_loop (Сфера 6) | 7 | core/trading_intelligence.py, core/context/shadow_consumers.py, core/intelligence/narrative_builder.py |
| `sideways_bars` | scan_loop (Сфера 6) | 1 | bot/loops/scan_loop.py |
| `sideways_mode_active` | scan_loop (Сфера 6) | 1 | bot/loops/scan_loop.py |
| `last_signal_type` | scan_loop (Сфера 7) | 1 | web/dashboard_server.py |
| `last_signal_direction` | scan_loop (Сфера 7) | 1 | web/dashboard_server.py |
| `last_signal_strength` | scan_loop (Сфера 7) | 1 | web/dashboard_server.py |
| `last_signal_time` | scan_loop (Сфера 7) | 0 | **никто** |
| `active_divergence` | scan_loop (Сфера 7) | 3 | core/intelligence/narrative_builder.py, core/intelligence/wave_service.py, web/dashboard_server.py |
| `anomaly_active` | scan_loop (Сфера 7) | 2 | core/intelligence/narrative_builder.py, web/dashboard_server.py |
| `ote_ltf_status` | ote_observer | 2 | bot/loops/ote_observer_loop.py, web/dashboard_server.py |
| `ote_ltf_score` | ote_observer | 2 | bot/loops/ote_observer_loop.py, web/dashboard_server.py |
| `ote_ltf_min` | ote_observer | 2 | bot/loops/ote_observer_loop.py, web/dashboard_server.py |
| `ote_ltf_direction` | ote_observer | 2 | bot/loops/ote_observer_loop.py, web/dashboard_server.py |
| `ote_ltf_trigger` | ote_observer | 2 | bot/loops/ote_observer_loop.py, web/dashboard_server.py |
| `ote_ltf_entry` | ote_observer | 2 | bot/loops/ote_observer_loop.py, web/dashboard_server.py |
| `ote_ltf_sl` | ote_observer | 2 | bot/loops/ote_observer_loop.py, web/dashboard_server.py |
| `ote_ltf_tp1` | ote_observer | 2 | bot/loops/ote_observer_loop.py, web/dashboard_server.py |
| `ote_ltf_tp` | ote_observer | 2 | bot/loops/ote_observer_loop.py, web/dashboard_server.py |
| `ote_ltf_setup` | ote_observer | 2 | bot/loops/ote_observer_loop.py, web/dashboard_server.py |
| `ote_ltf_time` | ote_observer | 1 | bot/loops/ote_observer_loop.py |
| `watchlist` | bus.set_watchlist() из любой стратегии | 6 | core/db/watchlist_manager.py, core/infra/price_ws.py, core/infra/ws_feed.py |
| `pivot_snap` | scan_loop (Сфера 8) | 6 | core/context/cube_projection.py, core/intelligence/narrative_builder.py, core/pivots/pivot_sphere.py |
| `near_pivot` | scan_loop (Сфера 8) | 5 | core/trading_intelligence.py, core/intelligence/narrative_builder.py, bot/loops/scan_loop.py |
| `last_narrative` | trading_intelligence (Сфера 9) | 0 | **никто** |
| `last_narrative_time` | trading_intelligence (Сфера 9) | 0 | **никто** |
| `last_p_win` | trading_intelligence (Сфера 9) | 0 | **никто** |
| `open_trade_id` | trade_simulator (Сфера 10) | 3 | core/infra/price_ws.py, core/infra/ws_feed.py, web/dashboard_server.py |
| `tsl_active` | trade_simulator (Сфера 10) | 3 | core/intelligence/narrative_builder.py, web/dashboard_server.py, scripts/tsl_backtest.py |
| `tp1_hit` | trade_simulator (Сфера 10) | 1 | core/context/sphere_registry.py |
| `cascade_count` | trade_simulator (Сфера 11) | 6 | core/selftest_cube.py, core/context/sphere_registry.py, core/context/trigger_bus.py |
| `last_direction` | trade_simulator (Сфера 11) | 2 | core/context/trigger_bus.py, core/trading/post_trade_analyser.py |
| `last_close_status` | trade_simulator (Сфера 11) | 2 | core/context/trigger_bus.py, core/trading/post_trade_analyser.py |
| `last_close_time` | trade_simulator (Сфера 11) | 0 | **никто** |
| `avg_r_cascade` | trade_simulator (Сфера 11) | 3 | core/context/trigger_bus.py, core/intelligence/narrative_builder.py, core/trading/post_trade_analyser.py |
| `post_tsl_data` | trade_simulator (Сфера 11) | 3 | core/context/trigger_bus.py, core/intelligence/narrative_builder.py, bot/loops/trigger_loop.py |
| `sl_streak_count` | gates (ARCH-88) | 2 | core/trading/post_trade_analyser.py, bot/monitoring.py |
| `last_n_outcomes` | gates (ARCH-88) | 1 | core/trading/post_trade_analyser.py |
| `pair_avg_r_last_20` | gates (ARCH-88) | 1 | core/trading/post_trade_analyser.py |
| `last_sl_at` | gates (ARCH-88) | 1 | core/trading/post_trade_analyser.py |
| `pair_cooldown_until` | gates (ARCH-88) | 0 | **никто** |
| `last_narrative_outcome` | trade_simulator (ARCH-91) | 2 | core/intelligence/narrative_builder.py, core/trading/post_trade_analyser.py |
| `spheres_ok` | sphere_registry (Сфера 12) | 0 | **никто** |
| `last_diagnostic_time` | sphere_registry (Сфера 12) | 0 | **никто** |
| `elliott_n_down` | WaveService (wave_service.py) | 2 | bot/loops/scan_loop.py, bot/menus/coin_card.py |
| `elliott_n_up` | WaveService (wave_service.py) | 2 | bot/loops/scan_loop.py, bot/menus/coin_card.py |
| `elliott_phase` | WaveService (wave_service.py) | 1 | core/intelligence/wave_service.py |
| `elliott_conf` | WaveService (wave_service.py) | 0 | **никто** |
| `wave_snap` | WaveService (wave_service.py) | 0 | **никто** |
| `wave_recount_ts` | WaveService (wave_service.py) | 1 | core/intelligence/wave_service.py |
| `wave_recounts` | WaveService (wave_service.py) | 0 | **никто** |
| `wave_updated_at` | WaveService (wave_service.py) | 1 | core/selftest_cube.py |
| `leg_dir` | WaveService, двухмасштабная нога | 2 | core/intelligence/wave_service.py, bot/loops/wave_loop.py |
| `leg_span_bars` | WaveService, двухмасштабная нога | 2 | core/intelligence/wave_service.py, bot/loops/wave_loop.py |
| `leg_age_origin` | WaveService, двухмасштабная нога | 2 | core/intelligence/wave_service.py, bot/loops/wave_loop.py |
| `leg_pos` | WaveService, двухмасштабная нога | 2 | core/intelligence/wave_service.py, bot/loops/wave_loop.py |
| `leg_retr` | WaveService, двухмасштабная нога | 2 | core/intelligence/wave_service.py, bot/loops/wave_loop.py |
| `leg_minor_breaks` | WaveService, двухмасштабная нога | 2 | core/intelligence/wave_service.py, bot/loops/wave_loop.py |
| `leg_tf` | WaveService, двухмасштабная нога | 2 | core/intelligence/wave_service.py, bot/loops/wave_loop.py |
| `leg_updated_at` | WaveService, двухмасштабная нога | 1 | bot/loops/wave_loop.py |
| `wave_leg_up` | wave_loop → wave_analyst.wave_bus_context | 2 | core/waves/wave_analyst.py, bot/loops/wave_loop.py |
| `wave_leg_dn` | wave_loop → wave_analyst.wave_bus_context | 2 | core/waves/wave_analyst.py, bot/loops/wave_loop.py |
| `wave5_setup` | wave_loop → wave_analyst.wave_bus_context | 2 | core/waves/wave_analyst.py, bot/loops/wave_loop.py |
| `wave_ctx_updated_at` | wave_loop → wave_analyst.wave_bus_context | 2 | core/waves/wave_analyst.py, bot/loops/wave_loop.py |
| `funding_rate` | market_data_sphere (Сфера 19) | 2 | core/signals/funding_detector.py, core/ui/message_builder.py |
| `funding_interval_h` | market_data_sphere (Сфера 19) | 0 | **никто** |
| `funding_next_ts` | market_data_sphere (Сфера 19) | 0 | **никто** |
| `funding_source` | market_data_sphere (Сфера 19) | 0 | **никто** |
| `funding_pct_8h` | market_data_sphere (Сфера 19) | 4 | core/context/market_data_sphere.py, core/intelligence/arch104_signal_adapter.py, core/intelligence/risk_intelligence.py |
| `funding_streak` | market_data_sphere (Сфера 19) | 0 | **никто** |
| `funding_pctile_90d` | market_data_sphere (Сфера 19) | 0 | **никто** |
| `funding_cum_3d` | market_data_sphere (Сфера 19) | 0 | **никто** |
| `funding_updated_at` | market_data_sphere (Сфера 19) | 0 | **никто** |
| `oi_d5` | market_data_sphere (Сфера 19) | 3 | bot/menus/coin_card.py, scripts/dc_agent.py, scripts/method_shadow.py |
| `oi_d15` | market_data_sphere (Сфера 19) | 4 | bot/menus/coin_card.py, scripts/dc_agent.py, scripts/method_shadow.py |
| `oi_d1d` | market_data_sphere (Сфера 19) | 2 | bot/menus/coin_card.py, scripts/oi_info_ceiling.py |
| `oi_px_quadrant` | market_data_sphere (Сфера 19) | 0 | **никто** |
| `oi_updated_at` | market_data_sphere (Сфера 19) | 0 | **никто** |

## 4. Чего в шине нет

| Чего нет | Что есть вместо | Кому нужно |
|---|---|---|
| недельный ТФ в структуре | smc_snap считает 3m…1d | карточка зон (глобальный взгляд) |
| точки импульса 0–5 по каскаду ТФ | в шине только нога origin→ext и счётчики свингов | карточка, разбор волн, гипотезы |
| ABC после импульса | нет | карточка, гипотезы |
| профиль объёма (POC, узлы) | нет | карточка зон |
| полный список ордер-блоков | в smc_snap только ближайшие бычий и медвежий | карточка зон, цели |
| зоны схождения факторов | нет — это результат карточки | терминал, анализ по запросу, /moment |
| гипотезы (подтверждение, цель, отмена, переход) | нет | разбор волн, карточка |
| пивоты квартала и года | pivot_snap содержит 1D / 1W / 1M | карточка зон (глобальный взгляд) |

## 5. Кто считает структуру, волны или пивоты сам

Детекторы напрямую импортируют **95** файлов вне производителей шины (ещё 17 отсеяны как замеры на
истории по имени файла). Из них **работают «на сейчас»** — под pm2, в боте, вебе или ядре — **20**;
остальные 75 лежат в `scripts/` и запускаются руками: это в основном исследования, но имя файла — слабый
признак, разбирать по одному. Не всё здесь дубль: теневой журнал или терминал со своим источником свечей
считать вправе. Вопрос к каждому один — лежит ли уже в шине то, что он считает.

### 5.1. Работают «на сейчас»

| Файл | Под pm2 | Что считает сам |
|---|---|---|
| `bot/core/bot.py` | — | pivots.pivot_calculator_fixed |
| `bot/loops/impulse_fib_runner.py` | — | calculate_pivot_points, smc.smc_engine |
| `bot/loops/ote_observer_loop.py` | — | waves.wave_analyst |
| `bot/loops/radar_armed_loop.py` | — | smc.smc_engine, waves.wave_analyst |
| `bot/loops/rangefade_loop.py` | — | smc.oko_sm_engine |
| `bot/menus/pivots.py` | — | pivots.pivot_reversal |
| `bot/monitoring.py` | — | pivots.pivot_reversal |
| `core/calculators/swing_bridge.py` | — | smc.oko_sm_engine, smc.smc_engine |
| `core/ml/mtf_smc_specialist.py` | — | smc.smc_engine |
| `core/selftest.py` | — | pivots.pivot_calculator_fixed |
| `core/signals/wt_15m_reversal_scanner.py` | — | pivots.pivot_calculator_fixed |
| `core/trading/choch_sl_transfer.py` | — | smc.smc_engine |
| `core/trading_intelligence.py` | — | pivots.pivot_calculator_fixed |
| `core/ui/chart_builder.py` | — | smc.smc_engine |
| `scripts/oi_fast_poller.py` | да | smc.smc_engine |
| `scripts/oko_sm_watch.py` | да | smc.oko_sm_engine |
| `scripts/ote_cell_shadow.py` | да | smc.impulse_assembly, smc.oko_sm_engine |
| `scripts/usdtd_watch.py` | да | smc.oko_sm_engine |
| `scripts/wave5_shadow.py` | да | smc.oko_sm_engine, waves.wave5_core, waves.wave_analyst |
| `web/structure_terminal.py` | да | smc.oko_sm_engine, smc.smc_engine, waves.wave5_core, waves.wave_analyst |

### 5.2. Скрипты ручного запуска

`atr_change_ote_test.py`, `bos_gate_core.py`, `bos_gate_revision.py`, `bos_pullback_oos.py`, `break_vs_atrtrend.py`, `choch_combo_and_exits.py`, `choch_feature_boosters.py`, `choch_length_across_tf.py`, `choch_length_check.py`, `choch_magnets_sr_mtf.py`, `choch_magnets_targets.py`, `choch_oos_validation.py`, `choch_portfolio_slots.py`, `choch_pullback_real_leg.py`, `choch_universe_trail_hybrid.py`, `correction_phase_prosecutor.py`, `detector_confirmation_lag.py`, `detector_visual.py`, `ds326_all_filters.py`, `ds326_wtb_filters.py`, `egor_fib_grid.py`, `elliott_canon_remeasure.py`, `elliott_completion_test.py`, `geometry_bench.py`, `gravity_entry_test.py`, `gravity_tri_v3.py`, `impulse_decay_causal.py`, `impulse_decay_series.py`, `joint_state_journal.py`, `leg_compare_view.py`, `matrix_full.py`, `measure_breaker_filter.py`, `method_micro_trigger.py`, `mtf_rebuild.py`, `mtf_reversal_entry.py`, `mtf_wave_phase.py`, `mtf_zone_card.py`, `oko_context_locator.py`, `oko_ote_runner_test.py`, `ote_impulse_check.py`, `ote_impulse_vs_outcome.py`, `ote_matrix_layer2.py`, `ote_monitor_xlm.py`, `ote_nested_honest_test.py`, `ote_retest_causality.py`, `ote_reversal_exit_test.py`, `ote_wtzone_test.py`, `smc_confirmation_lags.py`, `struct_layers_geometry.py`, `struct_layers_run.py`, `test_bigflush_short_mirror_bos.py`, `test_bigflush_stacked_gates.py`, `test_bos_gate_bigflush.py`, `test_cell_both_sides_full_window.py`, `test_cell_filters_sweep.py`, `test_cell_filters_sweep_oos.py`, `test_ote_confluence_and_construction.py`, `test_ote_impulse_choch_bos.py`, `test_ote_leg_vs_reference.py`, `test_ote_on_reference_leg.py`, `test_ote_phase_bounce_vs_trend.py`, `test_ote_retest_honest.py`, `test_ote_short_hybrid_cluster.py`, `test_ote_short_size_law.py`, `test_ote_triggers_real_engine.py`, `test_ote_wave_assembled.py`, `test_pob.py`, `test_regime_causal_switch.py`, `test_regime_param_sweep.py`, `test_short_cell_ob_confluence.py`, `test_short_cell_stop_tightening.py`, `wave_analyst.py`, `wave_chart_send.py`, `wave_runner_3m_entry.py`, `wave_smc_entry.py`
