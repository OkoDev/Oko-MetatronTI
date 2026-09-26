# 📖 FEATURE CATALOG — ЕДИНЫЙ каталог признаков

> 🔴 **Это единственный каталог набора признаков в проекте.** Другие документы
> описывают ИСТОРИЮ решений, а не действующий набор, и ссылаются сюда:
> `FEATURES_JSON_AUDIT.md` (почему набор такой — разбор ARCH-118, 30.05),
> `MATRIX_REGISTRY.md` (карта модулей-ИСТОЧНИКОВ, 28.08),
> `REGISTRY.md` (указатель инструментов). Дублировать перечни признаков в них — запрещено.
>
> Составлено 21.06.2026, **перемерено 02.09.2026** на 4 757 живых сделках (авг–сент).

## СКОЛЬКО ПРИЗНАКОВ И ГДЕ (замер 02.09.2026)

**Считает их ОДИН калькулятор** — `combinator_core.compute_flags` (инвариант ARCH-118).
Разные числа ниже — это не разные наборы, а один набор на разном числе ТФ:

| | признаков | что это |
|---|---|---|
| `compute_flags(df, tf)` | **155** на ТФ | 79 индикаторных + 76 пивотных — базовая единица |
| `mtf_flags` (research_harness) | **447** | 149 × (свой ТФ + два старших), после причинного blacklist |
| `trade_features` (БД, живые сделки) | **488** имён, медиана **362** на сделку | снимок нескольких ТФ + числовые pivot + meta/signal |
| `features_json` (БД) | 379 имён, медиана **42** | другой слой — мета решения, не рынок |

Проверить состав в любой момент, не доверяя документу:
```python
from core.calculators.combinator_core import compute_flags
sorted(compute_flags(df, "1h", include_pivots=True).columns)   # 155
```

---

## Где живёт — ДВА слоя, они НЕ дублируют друг друга

Замер 02.09: пересечение имён между слоями — **1 из 305/488**. Это не дубли, а разные вопросы.

| Слой | Что отвечает | Листьев | Покрытие |
|---|---|---|---|
| **`trade_features`** (ARCH-118, канон) | **рыночный контекст** на входе: combinator-флаги SMC/WT/RSI/ATR/EMA/pivot по TF | **488** | **98–100%** с июня |
| `simulated_trades.features_json` | **мета решения**: тайминги, роутинг, гейты, macro, `ds_*`, `soft_penalties` + блоки `smc_snap`/`wt_snap` | 379 | мета 100%, snap-блоки 10% |

**Для майнинга рыночных признаков брать `trade_features`.** `features_json` отвечает
на вопрос «как принималось решение», а не «что было на рынке».

- **Один калькулятор** (инвариант ARCH-118): combinator и сферы Bus считают признак ОДНОЙ формулой.
  Исследование (`research_harness` → `compute_flags`) идёт тем же калькулятором по истории — parity сохраняется.
- **schema_version** обязателен при обучении: v3 → v4 (17.08, pivot на всех TF) → **v5** (02.09,
  двухслойная структура). Смешивать версии в одном `fit` нельзя.

## Объём

### 🔴 ПОТОЛОК ≠ ТИПИЧНАЯ СДЕЛКА (замер 02.09.2026, 18 054 сделки за 07–09)

Числа ниже — из **богатейшего** снимка. Реальная сделка вдвое беднее:

| | top-level | листьев |
|---|---|---|
| потолок (что обещает каталог) | 133 | 228 |
| **медиана (что реально майнится)** | **42** | **49** |
| union по всем сделкам | 281 | — |

Разрыв не случаен — он **ровно по каналу регистрации**:

| источник | сделок | медиана ключей |
|---|---|---|
| confluence · pivot_reversal · monitoring | 1 432 | **99–108** |
| atr_change | 4 794 | 44 |
| ote_nested | 1 810 | 50 |
| wl_breach | 2 083 | 35 |
| wt_sideways | 3 773 | 29 |

**Корень:** блоки `smc_snap`, `wt_snap`, `narrative` и плоские SMC-поля кладёт в
`recommendation.metadata` ТОЛЬКО `analyze_symbol` (`trading_intelligence.py:1115`).
Стратегии, идущие через `trade_router` со своим `recommendation`, приносят metadata
без них → все четыре блока отсутствуют **синхронно**. Покрытие `smc_snap`:
апрель 62.7% → май 29.2% → июнь 4.2% → июль 12.2% → август 15.9% → **сентябрь 0%**
(в сентябре торгуют только необогащённые пути). За 07–09: **10.2% сделок обогащены, 89.8% нет.**

🔴 Следствие для ре-майнинга: майнить по медиане, а не по каталогу. Если признака
нет у 90% сделок — «находок нет» означает НЕТ ПРИЗНАКА, а не нет явления
(закон `law_no_finding_means_no_feature`).

- ⚠️ **Набор зависит от signal_type:** OTE-сделки несут блок `ote_*` (~13 ключей), другие — нет.

---

## 📊 СЕМЕЙСТВА и их реальное присутствие (`trade_features`, 4 757 сделок, авг–сент)

Присутствие = хотя бы один ключ семейства записан в снимке сделки.

| Семейство | присутствие | комментарий |
|---|---|---|
| ATR/trend · WT · pivot · Donchian | **100%** | скелет снимка, есть всегда |
| RSI | 92.7% | |
| CMA (скользящие) | 88.5% | |
| FVG | 88.1% | на этом семействе построены почти все 200 паттернов arch104 |
| Order Blocks | 36.4% | |
| OTE / premium / discount | 19.6% | |
| EQH/EQL · sweep | 3.4% | |
| **BOS/CHoCH (до 02.09)** | **1.3%** 🔴 | **причина «структурной слепоты»** |

🔴 **Диагноз 02.09 (закрывает C-01).** Структура была фактически невидима для майнинга:
`bull_bos_1h` срабатывал 1 раз на 3 000 баров (0.03%). Поэтому из **75 уникальных
флагов**, набравших статистику в 200 паттернах arch104, **структурных — ноль**;
топ занимают `bull_fvg_1d` (46), `bear_fvg_1h` (44), pivot и rsi. Это не свойство
рынка, а свойство прибора: `swing_bridge` брал только старший слой (`choch_length=50`)
и подмешивал туда `zigzag_atr`.

✅ **Исправлено:** один двухслойный эталон OKO-SM. Старший слой сохранил семантику,
добавлены `bull_bos_i` / `bear_bos_i` / `bull_choch_i` / `bear_choch_i` (микроструктура, len=5)
на каждом TF. Событий **×9.8** (0.59% → 5.21% баров), стоимость **вдвое ниже**
(19.8 → 9.8 мс на 3 000 баров). `SCHEMA_VERSION` 4 → 5.

⚠️ Ре-майнинг структурных паттернов имеет смысл **только на v5** — на v3/v4 признака
в данных фактически нет (закон: «находок нет» = НЕТ ПРИЗНАКА, а не нет явления).

---

## ⚠️ ОМОНИМИЯ «КЛАСТЕР» (04.09.2026)

Слово значило в проекте ТРИ разных вещи, и знаки у них расходились:

| явление | окно | знак | как теперь зовётся |
|---|---|---|---|
| сколько МОНЕТ льёт одновременно | бар / сутки | **+2.24 / +3.27** | **breadth** (ширина рынка) |
| сколько СЕТАПОВ выдала механика | час | **−0.49** | **density** (плотность сетапов) |
| скопление свингов на ценовом уровне | — | — | `cluster` (канон SMC, оставлен) |

Первые два — РАЗНЫЕ ЯВЛЕНИЯ: одно про рынок (корреляционное падение отскакивает),
другое про перегрев нашего детектора. Противоречия «трёх определений» не было — была
омонимия. Конфиг: `min_cluster` → **`min_breadth`** (старый ключ читается запасным).

🔴 **Поля данных НЕ переименованы намеренно:** `rf_cluster_size` и `rf_cluster_families`
уже записаны в `features_json` исторических сделок. Переименование колонки разорвало бы
сравнимость с прошлыми замерами — читать их как «ширина рынка».

---

## 🌳 Структура (по группам)

### Nested: `wt_snap[tf]` — WT по 6 ТФ
ТФ: **3m, 5m, 15m, 1h, 4h, 1d** · листья каждого: `trend, wt1, wt2, wt_cross, zone` → **30 листьев**

### Nested: `smc_snap[tf]` — SMC по 4 ТФ
ТФ: **15m, 1h, 4h, 1d**

- **`_v=1`** (всё, что в БД по 02.09 — 7 857 записей): 9 **булевых** листьев —
  `bos, choch, eqh_near, eql_near, fvg_open, liquidity_above, ob_bull, ob_distance_pct, ote_zone` → 36 листьев
- **`_v=2`** (с 02.09, ARCH-137.6): те же 9 + до 18 **непрерывных** — расстояния в ATR,
  размеры зон, возраст события: `ob_bull_dist_atr, ob_bull_age, ob_bear_dist_atr,
  fvg_dist_atr, fvg_size_atr, fvg_age, fvg_fill_pct, brk_age, brk_dist_atr, brk_strength,
  brk_internal, fib_pos, ote_dist_atr, fib_dir_long, eqh_dist_atr, eql_dist_atr,
  liq_buy_dist_atr, liq_sell_dist_atr` → до 112 листьев

🔴 Версии **нельзя смешивать в одном обучении** — `fit()` фильтрует по `_v`
(`mtf_smc_specialist.py:376`). Причина перехода: после починки детекторов булево
`fvg_open` стало True почти всегда — «есть ли зона» перестало различать.
🔴 Не путать с `state.smc_snap` в **шине** — там ДРУГАЯ схема (плоская + `by_tf`),
источник `build_smc_snapshot`, а не `_build_smc_snap_from_df`.

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
