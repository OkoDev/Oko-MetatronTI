====================================================================================================
# МЕНЮ ДАННЫХ Oko MTF — что можно спрашивать
====================================================================================================

### СВЕЧНОЙ КЭШ ohlcv_cache.db — покрытие по ТФ
  3m   символов=  42  свечей=  12,151,121  [2022-01-01 → 2026-04-12]
  5m   символов= 449  свечей=  53,335,134  [2025-01-01 → 2026-05-31]
  15m  символов= 472  свечей=  26,778,585  [2022-01-01 → 2026-05-31]
  1h   символов= 490  свечей=   8,747,416  [2022-01-01 → 2026-05-31]
  4h   символов= 467  свечей=   2,025,887  [2022-01-01 → 2026-05-31]
  1d   символов=  19  свечей=       2,280  [2026-01-05 → 2026-05-04]
  поля свечи: symbol, timeframe, time(ms), open, high, low, close, volume
  доп.таблица usdtd          n=     300  поля: time, open, high, low, close
  доп.таблица usdtd_1h       n=   1,592  поля: time, close
  доп.таблица usdtd_cg       n=      30  поля: date, value
  доп.таблица mcap_supply    n=   3,482  поля: date, symbol, supply, cmc_price, cmc_mcap
  доп.таблица mcap_meta      n=       7  поля: date, ts, tail, usdt_mcap, total_snapshot, n
  доп.таблица funding_rates  n=1,557,170  поля: symbol, time, interval_hours, rate
  доп.таблица onchain_events n=   5,181  поля: ts, kind, source, symbol, amount_usd, direction, raw

### БД СДЕЛОК subscriptions.db  (828 MB)
  account_routing          n=       564
      поля: symbol, account_id, mode, assigned_at
  accounts                 n=         2  [2026-06-13 → 2026-06-13]
      поля: id, exchange_id, name, api_env, is_active, created_at
  balance_snapshots        n=    12,299  [2026-06-12 → 2026-07-31]
      поля: id, account_id, exchange, timestamp, equity, available, used_margin, unrealized_pnl, source, created_at
  confluence_states        n=        26
      поля: symbol, direction, state, entered_at, score, factors, data_json, updated_at
  db_migrations            n=         2
      поля: name, applied_at
  ds_signals               n=       936  [2026-07-24 → 2026-07-26]
      поля: id, created_at, symbol, direction, entry_price, stop_loss, take_profit, ttl_min, thesis, confidence, processed, trade_id, error
  exchanges                n=         1  [2026-06-13 → 2026-06-13]
      поля: id, name, is_active, created_at
  feature_weights          n=        10
      поля: feature, regime, delta_pct, n, weight, validated, updated_at
  forward_verdicts         n=        71  [2026-07-12 → 2026-07-26]
      поля: ts, cohort, exec_mode, n, wr, net, verdict
  live_orders              n=    19,069  [2026-04-04 → 2026-07-31]
      поля: id, sim_trade_id, exchange_order_id, symbol, side, qty, sl_order_id, tp_order_id, status, slip_pct, created_at, updated_at
  pattern_lifecycle        n=         0
      поля: pattern_id, status, baseline_avgR, last_check_ts, runtime_avgR_30d, runtime_wr_30d, n_trades_30d, consecutive_losses, decision_reason, champion_or_challenger
  phase_state              n=     5,439  [2026-07-21 → 2026-07-31]
      поля: ts, level, symbol, phase, side, strategy_class, concordance, confidence, detail
  pivot_cache              n=     3,117
      поля: symbol, timeframe, period_start, pp, s1, s2, s3, s4, s5, r1, r2, r3, r4, r5, period_label, method, updated_at
  positions                n=         8
      поля: account_id, symbol, side, qty, entry_price, unrealized_pnl, margin, updated_at, mark_price
  risk_decisions_log       n=   214,515  [2026-05-20 → 2026-07-31]
      поля: id, ts, symbol, direction, pattern_id, matched_patterns, apply, risk_pct, leverage, sl_price, time_exit_hours, tp_strategy, skip_reason, v1_allow, v1_abort_reasons, v2_p_win, active_flags_json, reasoning
  screener_state           n=        49  [2026-07-25 → 2026-07-31]
      поля: symbol, ts, trend, origin, extreme, px, retr, in_zone, approach, noise, conf_score, hits, wt, wt_ma, div, itrend_sync, fib618, fib705, fib786, fib100, res_lvl, res_touches, res_dist, sup_lvl, sup_touches, sup_dist
  signal_drops             n=   474,551
      поля: id, symbol, signal_type, direction, strength, gate_name, drop_reason, features_json, dropped_at
  signal_stats             n=   140,683
      поля: id, user_id, signal_type, sent_at
  signal_weights_history   n=     8,298
      поля: id, signal_type, ema_avg_r, full_avg_r, adapted_weight, base_weight, n_trades, half_life, method, computed_at
  simulated_trades         n=    52,185  [2026-03-01 → 2026-07-31]
      поля: id, symbol, timeframe, signal_type, direction, entry_price, stop_loss, take_profit, strength, confidence, regime, created_at, status, exit_price, profit_pct, R_multiple, closed_at, duration_minutes, features_json, max_price, min_price, max_R_possible, captured_R_pct, tp1_price, tp1_hit_at, tsl_activated, tp2_price, tp2_hit_at, tp3_price, tp3_hit_at, sl_source, tp_source, strategy_name, tsl_tf, strategy_type, be_activated, first_profit_r, first_drawdown_r, decision_trace_json, exchange_order_id, exchange_sl_order_id, qty, original_sl, actual_entry_price, exchange_tp_order_id, source_router, magnet_tp_price, magnet_tp_rr, magnet_tp_src, regime_v2, account_id, execution_mode, exchange, total_fee, position_id, fakeR_quarantine, leverage, choch_sl_moved, costs_pct
  sqlite_sequence          n=        12
      поля: name, seq
  sqlite_stat1             n=         7
      поля: tbl, idx, stat
  subscriptions            n=         5
      поля: id, user_id, tier, start_date, end_date, is_active, payment_id
  tg_messages              n=         3
      поля: trade_id, user_id, message_id
  trade_analysis           n=     6,813  [2026-04-07 → 2026-07-31]
      поля: id, trade_id, analysis, model, prompt_tokens, created_at
  trade_features           n=    36,305  [2026-05-31 → 2026-07-31]
      поля: trade_id, schema_version, source, entry_tf, snapshot_ts, n_true, n_total, features_json, created_at
  user_settings            n=         0
      поля: user_id, deposit_usdt, leverage, risk_pct, sl_pct, tp_pct, auto_sizing, updated_at
  users                    n=         5  [2025-10-28 → 2026-07-30]
      поля: user_id, username, first_name, last_name, created_at, is_active
  watchlist                n=        12
      поля: user_id, symbol, added_at
  weekly_hypothesis        n=     1,025  [2026-07-13 → 2026-07-30]
      поля: symbol, week_start, regime, open_zone, hypo_code, side, target, stretch, inval, prob, hypo_text, status, created_at, resolved_at
  weekly_pivot_open        n=     1,060  [2026-07-13 → 2026-07-30]
      поля: symbol, week_start, open_price, open_zone, ts
  weekly_pivot_touch       n=     1,156  [2026-07-13 → 2026-07-30]
      поля: id, symbol, week_start, level, touch_price, pivot_val, open_zone, ts

### ВНЕШНИЙ ФИД oko_feed/external_data.db  (31 MB)
  accum_candidates         n=       854  [2026-07-11 → 2026-07-30]
      поля: ts, symbol, score, price, meta
  alert_log                n=       942  [2026-07-03 → 2026-07-31]
      поля: key, ts
  build_ambush             n=       203  [2026-07-14 → 2026-07-31]
      поля: symbol, ts, hi, lo, expire, fired
  build_signals            n=     7,471  [2026-07-03 → 2026-07-31]
      поля: ts, symbol, d_oi5, funding, side, px, sl, targets_json
  cg_trending              n=       625  [2026-07-08 → 2026-07-30]
      поля: ts, coins
  compass_log              n=       497  [2026-07-08 → 2026-07-30]
      поля: ts, bias, confidence, reasoning, swarm_bias, swarm_conf, swarm_votes
  depth_snap               n=     9,105  [2026-07-09 → 2026-07-31]
      поля: ts, symbol, px, bid_usd, ask_usd, bid_wall_px, bid_wall_usd, ask_wall_px, ask_wall_usd, note
  dominance                n=         3  [2026-07-02 → 2026-07-02]
      поля: asset, date, value, source
  liq_events               n=   129,746  [2026-07-03 → 2026-07-31]
      поля: ts, symbol, side, usd, px, source
  magnet_snapshots         n=     1,378  [2026-07-03 → 2026-07-30]
      поля: date, ts, symbol, px, tot_above, tot_below, above_json, below_json
  method_shadow            n=       109  [2026-07-05 → 2026-07-31]
      поля: ts, symbol, direction, entry, sl, tp1, tp2, tp3, htf_trend, pos, funding, oi_d5, oi_d15, fuel, resolved, outcome
  news_items               n=     9,067  [2026-07-08 → 2026-07-30]
      поля: link, ts, source, title, category, tone, importance, assets, summary_ru, alerted, digested
  oi_anchor                n=       264  [2026-07-12 → 2026-07-31]
      поля: symbol, date, oi
  oi_snapshots             n=    69,040  [2026-07-02 → 2026-07-31]
      поля: symbol, ts, oi_coins, oi_usd
  onchain_events           n=     9,726  [2026-07-03 → 2026-07-31]
      поля: ts, kind, source, symbol, amount_usd, direction, raw
  pump_signals             n=       735  [2026-07-03 → 2026-07-31]
      поля: ts, symbol, side, d_px, vol_ratio, rsi, d_oi, grade, entry, sl, tp1, tp2, tp3, targets_json, wave_leg
  radar_orders             n=     9,099  [2026-07-03 → 2026-07-31]
      поля: ts, symbol, sig_type, side, entry, sl, tp1, tp2, tp3, grade, starred, targets_json, status, taken_ts, note, chain, wave_leg, tg_msg_id, phase_json
  radar_state              n=       264  [2026-07-12 → 2026-07-31]
      поля: symbol, ts, px, oi_d5, oi_d15, funding, oi_d1d, quadrant, is_hot
  spring_signals           n=       956  [2026-07-03 → 2026-07-31]
      поля: ts, symbol, d_oi15, range_pct, funding, dir, px, targets_json
  tg_posts                 n=     2,878  [2026-07-08 → 2026-07-30]
      поля: channel_id, msg_id, ts, channel, username, text, link, classified

### FEATURES_JSON — реальные ключи (что бот пишет по каждой сделке)
  проанализировано сделок: 4000, уникальных ключей: 227
    entry_priority                         в 100.0% сделок
    entry_priority_reason                  в 100.0% сделок
    entry_tf                               в 100.0% сделок
    rr_at_entry                            в 100.0% сделок
    distance_to_sl_pct                     в 100.0% сделок
    session                                в 100.0% сделок
    data_era                               в 100.0% сделок
    shadow_signal_type                     в  99.9% сделок
    detector_ts                            в  99.9% сделок
    register_ts                            в  99.9% сделок
    entry_lag_seconds                      в  99.9% сделок
    ds_feature_mult                        в  99.8% сделок
    phase                                  в  99.7% сделок
    atr_trend_1h_bias                      в  99.2% сделок
    shadow_scan_loop_late                  в  98.7% сделок
    shadow_scan_loop_duration_s            в  98.7% сделок
    lost_reason                            в  96.6% сделок
    all_signal_types                       в  90.0% сделок
    n_supporting                           в  90.0% сделок
    soft_penalties                         в  64.8% сделок
    source_router                          в  64.8% сделок
    router_version                         в  64.8% сделок
    router_final_strength                  в  64.8% сделок
    gate_features                          в  60.8% сделок
    trade_mode                             в  53.5% сделок
    sideways_mode                          в  46.5% сделок
    wt1_at_signal                          в  46.5% сделок
    sideways_bars                          в  46.5% сделок
    weekly_bias                            в  43.6% сделок
    htf_wt1_1h                             в  43.0% сделок
    htf_wt2_1h                             в  43.0% сделок
    market_event                           в  41.6% сделок
    confirmations                          в  39.3% сделок
    confirmations_no_trigger               в  39.3% сделок
    wt1_value                              в  39.2% сделок
    wt2_value                              в  39.2% сделок
    wt_zone                                в  39.2% сделок
    volume_24h                             в  33.5% сделок
    price_change_24h                       в  33.5% сделок
    volatility                             в  33.5% сделок
    sl_atr_ratio                           в  23.7% сделок
    weekly_context_score                   в  23.7% сделок
    htf_wt1_4h                             в  23.1% сделок
    htf_wt2_4h                             в  23.1% сделок
    smc_trend                              в  19.9% сделок
    smc_has_choch                          в  19.9% сделок
    smc_has_bos                            в  19.9% сделок
    smc_has_bullish_bos                    в  19.9% сделок
    smc_has_bearish_bos                    в  19.9% сделок
    smc_has_bullish_choch                  в  19.9% сделок
    smc_has_bearish_choch                  в  19.9% сделок
    smc_last_break_type                    в  19.9% сделок
    smc_last_break_strength                в  19.9% сделок
    smc_active_resistance                  в  19.9% сделок
    smc_active_support                     в  19.9% сделок
    smc_active_bull_fvg_count              в  19.9% сделок
    smc_active_bear_fvg_count              в  19.9% сделок
    smc_active_bull_ob_count               в  19.9% сделок
    smc_active_bear_ob_count               в  19.9% сделок
    smc_bull_ob_fvg_overlap                в  19.9% сделок
    smc_bear_ob_fvg_overlap                в  19.9% сделок
    smc_price_in_ote                       в  19.9% сделок
    smc_ote_direction                      в  19.9% сделок
    smc_buy_liq_count                      в  19.9% сделок
    smc_sell_liq_count                     в  19.9% сделок
    smc_nearest_buy_liq_strength           в  19.9% сделок
    smc_nearest_sell_liq_strength          в  19.9% сделок
    nearest_ob_strength                    в  19.9% сделок
    price_in_ote                           в  19.9% сделок
    current_retracement                    в  19.9% сделок
    last_bos_direction                     в  19.9% сделок
    detector_price                         в  19.9% сделок
    entry_price_lag_pct                    в  19.9% сделок
    distance_to_pivot_pct                  в  19.9% сделок
    mtf_bias_strength                      в  19.9% сделок
    btc_4h_regime                          в  19.9% сделок
    weekly_gate_would_block                в  19.9% сделок
    weekly_bias_blocked                    в  19.9% сделок
    div_count                              в  19.9% сделок
    hidden_div                             в  19.9% сделок
    near_pivot_pct                         в  19.9% сделок
    mtf_direction_bias                     в  19.9% сделок
    mtf_price_zone                         в  19.9% сделок
    mtf_aligned_pct                        в  19.9% сделок
    mtf_senior_matches                     в  19.9% сделок
    mtf_regime                             в  19.9% сделок
    mtf_bull_pct                           в  19.9% сделок
    mtf_bear_pct                           в  19.9% сделок
    mtf_wt_spread_1h                       в  19.9% сделок
    mtf_wt_spread_4h                       в  19.9% сделок
    mtf_wt_spread_1d                       в  19.9% сделок
    wt_snap                                в  19.9% сделок
    smc_snap                               в  19.9% сделок
    reversal_mode                          в  19.9% сделок
    wl_pivot_key                           в  19.9% сделок
    wl_score                               в  19.9% сделок
    radar_oi_d5                            в  19.9% сделок
    radar_oi_d15                           в  19.9% сделок
    radar_funding                          в  19.9% сделок
    mtf_bias                               в  19.9% сделок
    narrative                              в  19.9% сделок
    radar_oi_px_quadrant                   в  19.8% сделок
    augment                                в  19.4% сделок
    near_pivot_level                       в  18.8% сделок
    near_pivot_source                      в  18.8% сделок
    fvg_confluences                        в  18.8% сделок
    ds_features_hit                        в  15.8% сделок
    pivot_real_touch                       в  12.5% сделок
    pivot_close_rejection                  в  12.5% сделок
    pivot_volume_z                         в  12.5% сделок
    pivot_level                            в  12.5% сделок
    pivot_type                             в  12.5% сделок
    pivot_trend_changed                    в  12.5% сделок
    signal_mode                            в  10.2% сделок
    strength_breakdown                     в  10.2% сделок
    radar_magnet_above_pct                 в  10.1% сделок
    radar_magnet_below_pct                 в   9.9% сделок
    signal_type_override                   в   9.9% сделок
    trigger_source                         в   9.5% сделок
    shadow_confluence_div_count            в   7.0% сделок
    shadow_confluence_would_pass           в   7.0% сделок
    confluence_factors                     в   6.9% сделок
    wt_cross_quality                       в   6.9% сделок
    mtf_4h_trend                           в   6.9% сделок
    mtf_4h_wt                              в   6.9% сделок
    mtf_4h_zone                            в   6.9% сделок
    conf_f_pivot_touch                     в   6.8% сделок
    ledger_mismatch                        в   6.6% сделок
    ote_direction                          в   6.1% сделок
    ote_tf                                 в   6.1% сделок
    ote_setup_id                           в   5.0% сделок
    ote_tier                               в   5.0% сделок
    ote_type                               в   5.0% сделок
    ote_htf                                в   5.0% сделок
    ote_ltf                                в   5.0% сделок
    ote_trigger                            в   5.0% сделок
    ote_tp1                                в   5.0% сделок
    ote_zone_lo                            в   5.0% сделок
    ote_zone_hi                            в   5.0% сделок
    ote_unconfirmed                        в   5.0% сделок
    ote_atr_trend_up                       в   5.0% сделок
    ote_confirmations                      в   5.0% сделок
    ote_conf_score                         в   5.0% сделок
    ote_trg_fvg                            в   5.0% сделок
    ote_trg_ob                             в   5.0% сделок
    ote_trg_eql                            в   5.0% сделок
    ote_trg_sc                             в   5.0% сделок
    ote_trg_sc_star                        в   5.0% сделок
    ote_trg_strength                       в   5.0% сделок
    ote_cf_atr                             в   5.0% сделок
    ote_cf_wt_cross                        в   5.0% сделок
    ote_cf_fvg_held                        в   5.0% сделок
    ote_cf_div                             в   5.0% сделок
    ote_cf_vol                             в   5.0% сделок
    ote_div_4h                             в   5.0% сделок
    ote_div_1h                             в   5.0% сделок
    ote_div_cascade                        в   5.0% сделок
    radar_ts                               в   4.0% сделок
    radar_grade                            в   4.0% сделок
    radar_starred                          в   4.0% сделок
    radar_tps                              в   4.0% сделок
    radar_tg_msg_id                        в   4.0% сделок
    radar_build_chain_n                    в   4.0% сделок
    radar_ltf_hh_progress                  в   4.0% сделок
    radar_ltf_peak_dist_pct                в   4.0% сделок
    conf_f_tsl_cross_down                  в   4.0% сделок
    mtf_sr_direction                       в   3.9% сделок
    mtf_sr_tf                              в   3.9% сделок
    mtf_sr_strength                        в   3.9% сделок
    conf_f_wt_cross_in_ob                  в   3.9% сделок
    conf_f_pivot_confluence                в   2.9% сделок
    conf_f_tsl_cross_up                    в   2.9% сделок
    conf_f_wt_cross_in_os                  в   2.9% сделок
    tp_selector_mode                       в   2.7% сделок
    tp_selector_actual_tp_source           в   2.7% сделок
    tp_selector_actual_tp                  в   2.7% сделок
    tp_selector_sl_dist_pct                в   2.7% сделок
    tp_selector_magnets_count              в   2.7% сделок
    tp_selector_clusters_count             в   2.7% сделок
    tp_selector_tp1_found                  в   2.7% сделок
    tp_selector_tp2_found                  в   2.7% сделок
    tp_selector_skip_reason                в   2.7% сделок
    tp_selector_elapsed_ms                 в   2.7% сделок
    tp_selector_tp2_price                  в   2.7% сделок
    tp_selector_tp2_dist_R                 в   2.7% сделок
    tp_selector_tp2_score                  в   2.7% сделок
    tp_selector_tp2_label                  в   2.7% сделок
    tp_selector_tp2_n_sources              в   2.7% сделок
    entry_tg_msg_id                        в   1.9% сделок
    radar_tp_oids                          в   1.9% сделок
    radar_tp_final                         в   1.9% сделок
    closed_notified                        в   1.9% сделок
    ledger_usd                             в   1.8% сделок
    runner_ceiling                         в   0.7% сделок
    runner_ceiling_src                     в   0.6% сделок
    ds_thesis                              в   0.5% сделок
    ds_confidence                          в   0.5% сделок
    ds_signal_id                           в   0.4% сделок
    rf_tf                                  в   0.3% сделок
    rf_wt1                                 в   0.3% сделок

### ЖИВАЯ ШИНА (PairState) — полный JSON по реальной паре
  пар в шине: 521 · пример: BTC/USDT:USDT
  поля верхнего уровня: active_divergence, anomaly_active, avg_r_cascade, btc_regime, cascade_count, cross_market_time, last_close_status, last_direction, last_narrative, last_ohlcv_time, last_p_win, last_signal_direction, last_signal_strength, last_signal_type, near_pivot, open_trade_id, ote_ltf_direction, ote_ltf_entry, ote_ltf_min, ote_ltf_score, ote_ltf_setup, ote_ltf_sl, ote_ltf_status, ote_ltf_tp, ote_ltf_tp1, ote_ltf_trigger, pivot_snap, post_tsl_data, regime, reversal_mode, smc_confidence, smc_snap, smc_verdict, spheres_ok, tick_price, tp1_hit, tsl_active, watchlist, wt_confidence, wt_snap, wt_verdict
    active_divergence: null
    anomaly_active: false
    avg_r_cascade: 0.0
    btc_regime: null
    cascade_count: 0
    cross_market_time: null
    last_close_status: null
    last_direction: null
    last_narrative: null
    last_ohlcv_time: "2026-07-31 00:24:01.622957+00:00"
    last_p_win: 0.0
    last_signal_direction: null
    last_signal_strength: 0.0
    last_signal_type: null
    near_pivot: null
    open_trade_id: null
    ote_ltf_direction: "long"
    ote_ltf_entry: 64865.1
    ote_ltf_min: 3
    ote_ltf_score: 0
    ote_ltf_setup: "4h_1h_pull"
    ote_ltf_sl: 63634.8044
    ote_ltf_status: "ARMED"
    ote_ltf_tp: 68900.144
    ote_ltf_tp1: 68900.144
    ote_ltf_trigger: null
    pivot_snap: dict[1W, 1D, 1M, fibonacci_equiv]
        pivot_snap.1W: {"PP": 65335.966666666674, "S1": 63946.341233333354, "S2": 62124.36666666667, "S3": 60538.73333333334, "R1": 66765.92543333335, "R2": 68547.56666666668, "R3": 70173.53333333335}
        pivot_snap.1D: {"PP": 64493.4, "S1": 64030.28020000001, "S2": 62921.6, "S3": 62265.0, "R1": 65215.119800000015, "R2": 66065.20000000001, "R3": 66980.40000000001}
        pivot_snap.1M: {"PP": 63889.13333333333, "S1": 53906.034066666674, "S2": 47898.23333333334, "S3": 37723.466666666674, "R1": 69513.59926666667, "R2": 79880.03333333333, "R3": 85696.16666666666}
    post_tsl_data: null
    regime: "RANGE"
    reversal_mode: "UNCLEAR"
    smc_confidence: 0.5
    smc_snap: dict[timestamp, tfs_processed, nearest_bull_ob, nearest_bear_ob, bull_fvg_active, bear_fvg_active, last_bos, last_choch, swing_high, swing_low, fib_levels, price_in_ote, current_retracement, ote_direction]
        smc_snap.nearest_bull_ob: {"tf": "4h", "top": 64167.6, "bottom": 63881.9, "strength": 75, "distance_pct": -1.186, "age_bars": 5}
    smc_verdict: "STRONG_BULL_ZONE"
    spheres_ok: 5
    tick_price: 64793.0
    tp1_hit: false
    tsl_active: false
    watchlist: {}
    wt_confidence: 0.6
    wt_snap: dict[15m, 1h, 4h]
        wt_snap.15m: {"wt1": 7.35, "wt2": 15.99, "zone": "N", "wt_cross": 0, "cross_in_zone": 0, "trend": "UP", "atr_trend": 1}
        wt_snap.1h: {"wt1": 42.44, "wt2": 42.51, "zone": "N", "wt_cross": 0, "cross_in_zone": 0, "trend": "UP", "atr_trend": 1}
        wt_snap.4h: {"wt1": 28.71, "wt2": 21.76, "zone": "N", "wt_cross": 0, "cross_in_zone": 0, "trend": "UP", "atr_trend": 1}
    wt_verdict: "TREND_CONTINUATION"