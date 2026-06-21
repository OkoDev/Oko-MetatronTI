# 📖 FEATURE CATALOG — карта всех признаков (майнинг-поверхность)

> Составлено 21.06.2026 (Даат) эмпирически из БД. Референс для OTE-RE-MINE.
> Метод: разбор `features_json` живых сделок (взят снимок с макс. числом ключей) + рекурсивный обход nested.

## Где живёт
- **`simulated_trades.features_json`** — снимок признаков на момент входа (per-trade).
- **`trade_features`** (16 783 строки, ARCH-118) — канонический стор: `trade_id, schema_version, source, entry_tf, snapshot_ts, n_true, n_total, features_json`.
- **Один калькулятор** (ARCH-118 инвариант): combinator и сферы Bus считают признак ОДНОЙ формулой.

## Объём
- **99 top-level ключей** (макс. в одном снимке) + вложенные объекты → **168 листьев** в богатом снимке.
- ⚠️ **Набор зависит от signal_type:** OTE-сделки несут блок `ote_*` (~13 ключей), другие — нет. Полный union по всем типам > 99.

---

## 🌳 Структура (по группам)

### Nested: `wt_snap[tf]` — WT по 6 ТФ
ТФ: **3m, 5m, 15m, 1h, 4h, 1d** · листья каждого: `trend, wt1, wt2, wt_cross, zone` → **30 листьев**

### Nested: `smc_snap[tf]` — SMC по 4 ТФ
ТФ: **15m, 1h, 4h, 1d** · листья каждого: `bos, choch, eqh_near, eql_near, fvg_open, liquidity_above, ob_bull, ob_distance_pct, ote_zone` → **36 листьев**

### MTF (выравнивание/доминанта)
`atr_trend_1h_bias, mtf_aligned_pct, mtf_bull_pct, mtf_bear_pct, mtf_bias, mtf_bias_strength, mtf_direction_bias, mtf_price_zone, mtf_regime, mtf_senior_matches, mtf_sr_direction, mtf_sr_strength, mtf_sr_tf, mtf_wt_spread_1h, mtf_wt_spread_4h, mtf_wt_spread_1d`

### SMC (плоские агрегаты)
`smc_active_bull_ob_count, smc_active_bear_ob_count, smc_active_bull_fvg_count, smc_active_bear_fvg_count, smc_active_support, smc_active_resistance, smc_bull_ob_fvg_overlap, smc_bear_ob_fvg_overlap, smc_buy_liq_count, smc_sell_liq_count, smc_nearest_buy_liq_strength, smc_nearest_sell_liq_strength, smc_has_bos, smc_has_choch, smc_has_bullish_bos, smc_has_bearish_bos, smc_has_bullish_choch, smc_has_bearish_choch, smc_last_break_type, smc_last_break_strength, smc_ote_direction, smc_price_in_ote, smc_trend, nearest_ob_strength, fvg_confluences`

### Pivots
`distance_to_pivot_pct, near_pivot_pct, distance_to_sl_pct`

### Дивергенция
`div_count, hidden_div`

### Режим / контекст
`btc_4h_regime, reversal_mode, weekly_bias, weekly_bias_blocked, weekly_context_score, weekly_gate_would_block, session, volatility, price_change_24h, volume_24h`

### Вход-мета
`entry_priority, entry_priority_reason, entry_tf, rr_at_entry, sl_atr_ratio, current_retracement, price_in_ote, entry_lag_seconds, entry_price_lag_pct, n_supporting, all_signal_types, data_era`

### OTE-блок (только OTE-сделки)
`ote_setup_id, ote_type, ote_tier, ote_htf, ote_ltf, ote_trigger, ote_confirmations, ote_conf_score, ote_zone_lo, ote_zone_hi, ote_tp1, ote_unconfirmed, ote_atr_trend_up`

### Гейты / роутер
`gate_features` {`market_stress, pair_cooldown_streak, regime_safety, strength_threshold`} · `soft_penalties[]` · `source_router, router_version, router_final_strength, shadow_signal_type, shadow_scan_loop_duration_s, shadow_scan_loop_late`

### TP-селектор (ARCH-122)
`tp_selector_mode, tp_selector_clusters_count, tp_selector_magnets_count, tp_selector_sl_dist_pct, tp_selector_tp1_found, tp_selector_tp2_found, tp_selector_tp2_price, tp_selector_tp2_label, tp_selector_tp2_dist_R, tp_selector_tp2_score, tp_selector_tp2_n_sources, tp_selector_actual_tp, tp_selector_actual_tp_source, tp_selector_skip_reason, tp_selector_elapsed_ms`

### Мета/прочее
`narrative` {`smc_factors`}, `detector_price, detector_ts, register_ts, lost_reason`

---

## ✅ AUGMENT — закрытые пробелы (ARCH-128, 21.06)

Условные edge из памяти РАНЬШЕ не попадали в снимок (не было переменных). **Добавлены** через
единый `core/indicators/augment_snap.py::compute_augment_snap(df)` — reuse существующих детекторов,
инвариант ARCH-118 «один калькулятор». Проводка: **A** live = `monitoring.py` register-time per
**5m/15m/1h/4h**; **B** backtest = ТОТ ЖЕ вызов (ре-майн, backfill истории).

**Блок `features_json.augment.{5m,15m,1h,4h}`:**
| Поле | Источник | Зачем |
|---|---|---|
| `adx` | `indicators.compute_adx` | wt_b edge ADX<25 |
| `rsi` | `indicators.compute_rsi` | классич. OB/OS (отдельно от WT) |
| `n_down`, `n_up` | `calculate_n_down/up` (swing) | прокси волны Эллиотта (n=3-4 SHORT/LONG) |
| `elliott{direction,scale,w2/w4_retr,w3_ext,textbook,n_impulses}` | `smc_engine.detect_elliott_mtf` | импульс + **мультиструктура** (scale=степень, n_impulses=фрактал) |
| `fib_retracement`, `in_ote` | swing-диапазон (50 баров) | позиция в фибо/OTE-зоне |

⚠️ **Going-forward:** live даёт augment на НОВЫХ сделках после рестарта; историю покрывает только бэктест (B).

---

## ⚠️ Правила использования (метрики-гигиена)
- **Вход мерить в %ЦЕНЫ** (`max_R_possible × |entry−sl|/entry`), НЕ в R — R зависит от SL и искажает сравнение стратегий (см. находку 21.06: atr_change лучший вход, убит из-за широкого SL).
- **R_multiple в БД = фикция** (узкий SL раздувает + fake-R). Истина выхода = income-$/`o.rp`. MFE/`max_R_possible` = правда входа.
- **Покрытие варьируется** по `data_era` — старые сделки несут меньше ключей; мерить по эрам.
- Снимок = ЖИВОЙ пайплайн. Для бэктест-ре-майна OTE-генератор пересчитывает признаки сам.

## Связь
[[bus_catalog_data_menu]] (идея «меню данных»), [[arch118_snapshot_decision]] (один калькулятор), OTE-RE-MINE спека.
