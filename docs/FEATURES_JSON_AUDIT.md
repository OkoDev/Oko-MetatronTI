# features_json AUDIT (ARCH-118) — 30.05.2026

> Карта текущего разрозненного состояния `features_json` перед стандартизацией.
> Источник: 1500 последних сделок `simulated_trades`. Анализ: `python -c` по БД.

## 🔴 Главная проблема

**170 уникальных ключей**, и **каждый signal_type пишет СВОЙ набор** — нет единого снимка признаков на момент входа.

| signal_type | сделок | уникальных ключей |
|---|---|---|
| watch_list_breach | 566 | **36** |
| confluence | 444 | **129** |
| atr_change | 158 | 42 |
| arch104 | 131 | 40 |
| pivot_reversal | 75 | **107** |
| liquidity_sweep | 63 | **121** |
| divergence | 17 | 77 |
| wt_b_signal | 9 | 104 |
| wt_signal | 8 | 101 |
| mtf_alert | 5 | 112 |
| anomaly | 4 | 94 |
| mtf_bias | 3 | 76 |

→ watch_list_breach (самый частый) пишет 36 полей, confluence — 129. **Сделки несравнимы между собой.** ML не может обучаться консистентно: у каждой строки разный набор фич. Это и есть корень «самоподтверждения» — каждый детектор формирует свой контекст.

## 📊 Расслоение по покрытию

### CORE — универсальные (16 ключей, ≥1400/1500 сделок)
Пишутся почти всегда — это фактический «общий контракт»:
```
data_era, session, entry_tf, entry_priority, entry_priority_reason,
rr_at_entry, distance_to_sl_pct, detector_ts, register_ts, entry_lag_seconds,
atr_trend_1h_bias, soft_penalties, gate_features,
source_router, router_version, router_final_strength
```
**Вывод:** только meta-поля (тайминги, роутинг, entry-контекст) универсальны. Индикаторных/рыночных признаков в core НЕТ — они разбросаны по типам.

### MID — частичное покрытие (86 ключей, 400-1400)
WT/MTF (htf_wt1_1h, wt1_value, wt_zone, mtf_4h_*, mtf_aligned_pct...), SMC (smc_trend, smc_has_choch, smc_active_*, smc_price_in_ote — 24 ключа, только ~596 сделок), market (volume_24h, volatility), confirmations[], weekly_bias, OTE.

### RARE — специфичные (68 ключей, <400)
arch104_* (только arch104), pvt_* shadow (DEV-225), elliott_n_down/n_up, mtf_sr_* (45 сделок), shadow_* поля, signal_type_override, position_size_multiplier (5).

## 🗂️ Домены (170 ключей)

| Домен | ключей | примеры |
|---|---|---|
| OTHER (несгруппир.) | 69 | mtf_*, ote_*, narrative, market_event, shadow_* |
| SMC | 24 | smc_trend, smc_has_bos, smc_active_bull_fvg_count, smc_price_in_ote |
| WT/MTF | 23 | htf_wt1_1h, wt1_value, wt_zone, mtf_4h_wt |
| PIVOT | 12 | pvt_above_daily_pp, pvt_nearest_level, pivot_* |
| ENTRY-META | 12 | data_era, session, entry_tf, rr_at_entry, *_ts |
| ARCH104 | 9 | arch104_pattern_id, arch104_detection_tf, arch104_risk_pct |
| ELLIOTT | 7 | elliott_n_down, n_down_ltf, htf_price_dir |
| ROUTING/GATES | 7 | source_router, gate_features, lost_reason, soft_penalties |
| MARKET | 3 | volume_24h, price_change_24h, volatility |
| CONFIRMATIONS | 2 | confirmations[], conf_sources |
| INDICATOR | 2 | atr_trend_1h_bias, rsi_* |

## 🎯 Вывод для ARCH-118

**Текущее состояние = анти-паттерн:**
1. **Нет схемы** — features_json это «что попало положил детектор».
2. **Нет единого снимка** — combinator считает ~211 флагов, но в features_json попадает разрозненное подмножество, разное для каждого типа.
3. **Бэктест ≠ live** — combinator (бэктест) и детекторы (live) пишут разные наборы → нельзя обучать ML на live, валидируя на бэктесте. Это вскрыл DEV-235 (golden самоподтверждался).

**Цель стандартизации:**
- **Единый снимок** всех ~211 combinator-флагов + рыночный/MTF/SMC контекст на момент входа КАЖДОЙ сделки, ОДНИМ расчётом (live = бэктест).
- **Фиксированная схема** (versioned) — все сделки имеют одинаковый набор полей (NULL если неприменимо).
- **Реализация поверх ARCH-117** (единые сферы WT/RSI) — сферы публикуют в Shared Context Bus, снимок собирается из Bus.

**Кандидат схемы (3 слоя):**
1. `meta` — 16 CORE-полей (тайминги, роутинг, entry).
2. `context` — единый снимок 211 combinator-флагов (SMC/WT/RSI/pivot/ATR/EMA/div/cross) на всех TF.
3. `signal` — specifics типа (arch104_pattern_id и т.п.) + confirmations[].

**❓ Открытые вопросы:**
- Хранить 211 флагов как вложенный dict или плоско? (размер БД vs queryability)
- Версионирование схемы (features_schema_version) для миграций.
- Backfill старых сделок невозможен (нет снимка) → data-era граница на момент внедрения.

Полный список 170 ключей: `e:/tmp/features_keys.txt`.

---

## 📋 ПОЛНЫЙ РЕАЛЬНЫЙ индикаторный каталог (для context-слоя)

> Только то, что ДЕЙСТВИТЕЛЬНО вычисляется в живом потоке. `extended_indicators.py`
> (Bollinger/Ichimoku/MACD/Stochastic/VWAP/MFI — 64 ключа) был МЁРТВЫМ КОДОМ (никто
> не импортировал) → **удалён 30.05**. ADX живёт в `indicators.py` (market_regime).

### Источник 1 — `combinator_v2.compute_flags` (булевы флаги, ARCH-104)

**47 индикаторных базовых × TF** (5m/15m/1h/4h/1d, у каждого свой суффикс):
```
# Trend/ATR Supertrend
atr_up, atr_down, atr_cross_up, atr_cross_down
# EMA
above_ema50, below_ema50, above_ema200, below_ema200,
ema50_above_ema200, ema50_below_ema200
# SMC structure
bull_bos, bear_bos, bull_choch, bear_choch
bull_fvg, bear_fvg, bull_fvg_in, bear_fvg_in
bull_ob, bear_ob, bull_ob_near, bear_ob_near
# SMC zones
premium, discount, ote_long, ote_short
eqh_sweep, eql_sweep
# WT
wt_os, wt_ob, wt_cross_up, wt_cross_down,
wt_div_bull_reg, wt_div_bear_reg, wt_div_bull_hidden, wt_div_bear_hidden
# RSI
rsi_os, rsi_ob, rsi_cross50_up, rsi_cross50_down,
rsi_div_bull_hidden, rsi_div_bear_hidden
# Momentum/Volume
bull_mom, bear_mom, vol_spike
# Divergence (RSI regular)
bull_div, bear_div
```

**35 pivot базовых × {PP,R1,R2,R3,S1,S2,S3} × {1D,1W}** (статика, ~490 комбинаций):
```
pivot_above_*, pivot_below_*, pivot_near_*, pivot_bounce_up_*, pivot_bounce_down_*
```

### Источник 2 — `indicators.py` (ЧИСЛОВЫЕ значения, основной бот scan_loop)

Пишутся как значения (не булевы) — нужны для ML-фич:
```
wt1, wt2                    # WaveTrend (значения, не зоны)
trend, trendup, trenddown   # ATR Supertrend (направление + линии)
trend_strength              # сила тренда
rsi                         # RSI значение
atr                         # ATR значение
adx                         # ADX значение (market_regime: >25 тренд)
ema50, ema200               # EMA значения
volatility                  # волатильность
volume_ratio                # отношение объёма
n_down, n_up                # Elliott прокси (consecutive swings)
```

### Итоговая схема context-слоя (предложение)

| Группа | TF-зависимо | Кол-во база | Итого (×TF) |
|---|---|---|---|
| combinator индикаторные (булевы) | да (5 TF) | 47 | ~235 |
| combinator pivot (булевы) | нет (1D/1W) | 35×14 | ~490 |
| indicators.py числовые | да (по необходимости) | ~15 | ~45-75 |

**Полный единый снимок = ~770 признаков на сделку** (булевы combinator + числовые indicators).
Это и есть то, что должно писаться ОДИНАКОВО для каждой сделки (NULL где TF неприменим),
ОДНИМ расчётом (live = бэктест). Сейчас вместо этого — 36-129 разрозненных полей на тип.

**❓ Решения для схемы:**
- Все 5 TF для combinator-индикаторных или только релевантные (entry_tf + HTF 1h/4h/1d)?
- Числовые indicators.py — на каких TF? (15m entry + 1h/4h контекст?)
- pivot ~490 булевых — оставить как есть или свернуть в `nearest_pivot_level` + `distance`?
- Хранение: вложенный JSON по группам или плоско (queryability в SQL)?

Каталоги: `e:/tmp/combinator_flags_full.txt` (117 на 1h), `e:/tmp/full_ind_catalog.txt`.
