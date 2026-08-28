# SIGNAL ⇄ BUS ⇄ CUBE — Карта запуска шины и Куба Метатрона

> **Версия:** 1.1 · **Дата:** 2026-04-27 · **Автор:** TRADER (Claude)
> **Цель:** единый справочник для запуска шины и Куба Метатрона полностью.
> Карта живёт по слоям: RAW → детекторы → контекст → шина → сферы → feedback.
> Каждый блок помечен статусом ✅ ACTIVE / ⚠️ SHADOW / ⛔ STOPPED / ❌ MISSING / 🔌 NOT WIRED.
> Для текущего pipeline запуска бота — см. [BOT_SIGNAL_MAP.md](../BOT_SIGNAL_MAP.md).
> Для теории Куба — [docs/ENCYCLOPEDIA.md](ENCYCLOPEDIA.md) (раздел «Куб Метатрона»).
> Для Mermaid-схем — [docs/CUBE_ARCHITECTURE.md](CUBE_ARCHITECTURE.md).
> **🔮 Predictive Setup Engine (65 триггеров → лимитные ордера):** [docs/TRADER_VISION_PREDICTIVE_SETUPS.md](TRADER_VISION_PREDICTIVE_SETUPS.md).
>
> 🔬🔴 **РЕЕСТР ДЕТЕКТОРОВ И ИХ ПРОВЕРОК — [docs/DETECTOR_REGISTRY.md](DETECTOR_REGISTRY.md)** (28.08.2026).
> Верен ли прибор, а не выгоден ли. Стенд `scripts/detector_bench.py` из четырёх проверок,
> ни одна не смотрит на прибыль. 🔴 Живое рассогласование C-01: BOS/CHoCH в матрице
> считаются с `length=50` вместо эталонных 5 → в **7.5× меньше** сломов, лаг 323 бара на 15m.
>
> 🧮🔴 **ПОЛНАЯ МАТРИЦА ПРИЗНАКОВ — [docs/MATRIX_REGISTRY.md](MATRIX_REGISTRY.md)** (28.08.2026).
> Эта карта описывает, что ТЕЧЁТ по слоям; реестр матрицы — что из этого МОЖНО ИЗМЕРИТЬ
> на истории. 87 модулей решений разложены на ЧИСТЫЕ (34, пересчитываются на истории) /
> ГИБРИДНЫЕ (18) / ЖИВЫЕ (34, не воспроизводимы), плюс 15 дублей одного смысла
> (`detect_fvg` в трёх версиях) и 631 ключ `features_json` с пометкой «что НЕ вносить
> и почему» (циркулярность маршрутизации, гейтов, ML и постфактума).
> 🔑 До 28.08 такой карты не существовало: исследования шли по одному модулю из 87.

---

## Критерий «Куб запущен полностью»

Куб считается полностью запущенным, когда выполнены **все** условия:

```
[ ] L13 selftest: 13/13 текущих сфер ACTIVE + 4 новых (S14–S17) реализованы
[ ] L14 selftest: ≥18 рёбер ACTIVE, 0 NOT WIRED
[ ] L15 selftest: 4/4 feedback loops ACTIVE
[ ] EventBus shadow=false (уже сделано — 27.04 ✅)
[ ] Все детекторы публикуют SIGNAL_DETECTED в шину
[ ] PairState 38 полей заполнены production-кодом (нет declared-only)
[ ] reversal_mode в production
[ ] OutcomePredictor AUC ≥ 0.55
[ ] WT/SMC specialists fitted (MIN_TRADES=50 пройден)
[ ] Execution Sphere (S14) с IdempotencyGuard production
[ ] LIVE-режим включён, 0 SL-дублей за 7 дней
[ ] avgR/неделю ≥ +0.1R на 200+ сделок
```

Текущий статус (27.04.2026): ≈ **6/12** ✅ выполнено.

---

# СЛОЙ 0 — RAW-индикаторы

Атомарные вычисления. Один источник истины для всех детекторов.

## WT-семейство (WaveTrend)

| Функция | Файл:строка | Параметры | Выход | Потребляется |
|---|---|---|---|---|
| `calculate_wt` | [core/indicators/indicators.py:5](../core/indicators/indicators.py#L5) | `n1=10, n2=21` | DataFrame.col `wt1, wt2` | все WT-детекторы, divergence, MTF |
| `get_zone` | [indicators.py:194](../core/indicators/indicators.py#L194) | `ob1=60, os1=-60` | "OB" / "OS" / "N" | TREND_SIGNAL, CONFLUENCE, MarketRegime |
| `derive_wt_verdict` | [core/intelligence/wt_specialist.py:37](../core/intelligence/wt_specialist.py#L37) | `wt_snap` | EXHAUSTION / REVERSAL_SETUP / TREND_CONTINUATION / UNCLEAR + conf | MTF_BIAS, PairState.wt_verdict |
| `_wt_cross` | [core/signals/funding_detector.py:40](../core/signals/funding_detector.py#L40) | `os=-40, ob=+40` | bool cross + zone | FUNDING_EXTREME |

**Конфиг** ([config.yaml](../config.yaml#L24)): `wavetrend.n1: 10`, `n2: 21`, `ob_threshold: 60`, `os_threshold: -60`.

## Trend / TSL / ATR-семейство

| Функция | Файл:строка | Параметры | Выход |
|---|---|---|---|
| `calculate_trend` | [indicators.py:98](../core/indicators/indicators.py#L98) | `atr_period=43, factor=1.0` | DataFrame.col `trend, trendup, trenddown, tsl` |
| `true_range_series` | [indicators.py:295](../core/indicators/indicators.py#L295) | — | TR-серия |
| `compute_atr_values` | [indicators.py:303](../core/indicators/indicators.py#L303) | `period=14` | List[float] (Wilder's RMA) |
| `compute_atr` | [indicators.py:329](../core/indicators/indicators.py#L329) | `period=14` | float (последнее значение) |
| `get_trend_info` | [indicators.py:243](../core/indicators/indicators.py#L243) | df с trend | `{direction, length, tsl, distance_to_tsl_percent, is_strong}` |
| `calculate_trend_strength` | [indicators.py:222](../core/indicators/indicators.py#L222) | — | trend_strength (consecutive bars) |

**TSL — это ATR Supertrend линия** (`trendup` / `trenddown`). Используется и как стоп, и как фильтр направления.

## ADX / EMA / RSI / Volume / Volatility

| Функция | Файл:строка | Период | Потребляется |
|---|---|---|---|
| `compute_adx` | [indicators.py:437](../core/indicators/indicators.py#L437) | 14 | MarketRegime gate (TREND_UP/DOWN) |
| `compute_ema_values` / `compute_ema` | [indicators.py:356/378](../core/indicators/indicators.py#L356) | 20 | MarketRegime EMA-slope |
| `compute_rsi` | [indicators.py:481](../core/indicators/indicators.py#L481) | 14 | ml_predictor features |
| `compute_volume_ratio` | [indicators.py:513](../core/indicators/indicators.py#L513) | 20 | ANOMALY, ml_predictor |
| `compute_volatility` | [indicators.py:401](../core/indicators/indicators.py#L401) | 20 | SL-расчёт, ML features |
| `compute_sma` | [indicators.py:387](../core/indicators/indicators.py#L387) | любой | internal |

## Swing points / Structure (SMC)

| Функция | Файл:строка | Параметры | Выход |
|---|---|---|---|
| `detect_swing_points` | [core/smc/swing_points.py:252](../core/smc/swing_points.py#L252) | `period=5, trend_lookback=6` | SwingAnalysis (HH/HL/LH/LL + trend) |
| `detect_structure` | [core/smc/structure.py:342](../core/smc/structure.py#L342) | swings | StructureAnalysis (BOS / CHoCH / breaker_blocks) |
| `find_swing_highs` / `find_swing_lows` | [indicators.py:534/555](../core/indicators/indicators.py#L534) | period=5 | List[(idx, val)] для divergence |

## SMC: FVG / OB / Fibonacci OTE / Liquidity / EQH/EQL

| Функция | Файл:строка | Выход |
|---|---|---|
| `detect_fvg` (мини) | [indicators.py:206](../core/indicators/indicators.py#L206) | (BULL/BEAR FVG, entry_price) — 3 свечи |
| `detect_fvg` (полный) | [core/smc/fvg.py:259](../core/smc/fvg.py#L259) | FVGAnalysis (active_bull, active_bear, mitigation %) |
| `detect_order_blocks` | [core/smc/order_blocks.py:228](../core/smc/order_blocks.py#L228) | OBAnalysis (bull/bear OB + strength 0–100) |
| `detect_fibonacci` | [core/smc/fibonacci.py:154](../core/smc/fibonacci.py#L154) | List[FibZone] (OTE 0.618–0.786) |
| `detect_liquidity` | [core/smc/liquidity.py:170](../core/smc/liquidity.py#L170) | LiquidityAnalysis (buy/sell-side кластеры + sweep tracking) |
| `detect_equal_highs_lows` ⭐ | [core/smc/liquidity.py:240](../core/smc/liquidity.py#L240) | `{eqh_near, eql_near, eqh_level, eql_level}` (DEV-140) |

**EQH/EQL** ✅ есть в коде (DEV-140) — раньше в ENCYCLOPEDIA числились как ❌ MISSING.

## Pivot Levels

| Функция | Файл:строка | Период | Выход |
|---|---|---|---|
| `calculate_pivot_points` | [indicators.py:576](../core/indicators/indicators.py#L576) | 1D / 1W | `{PP, S1–S5, R1–R5}` (Traditional) |
| `PivotLevels.get_pivot_levels` | [core/pivots/pivot_levels.py:25](../core/pivots/pivot_levels.py#L25) | 1D / 1W / 1M | dict |
| `PivotLevels.get_multi_timeframe_pivots` | [pivot_levels.py:64](../core/pivots/pivot_levels.py#L64) | 1W приоритет | `{1W, 1D, confluence}` |
| `PivotLevels.get_nearest_level` | [pivot_levels.py:98](../core/pivots/pivot_levels.py#L98) | — | `{support, resistance, distances}` |

S1 = pp×2.003 − high, R1 = pp×1.997 − low (формула проверена, **не менять**).

## MarketRegime classifier

| Метод | Файл:строка | Вход | Выход |
|---|---|---|---|
| `classify_from_ohlcv` | [core/indicators/market_regime.py:68](../core/indicators/market_regime.py#L68) | df + ADX/EMA | TREND_UP / TREND_DOWN / RANGE / HIGH_VOL |
| `classify_from_dataframes` ✅ | [market_regime.py:136](../core/indicators/market_regime.py#L136) | 15m+1h+4h | то же (ARCH-09 п.6, MTF) |
| `classify_mode` ⚠️ SHADOW | [market_regime.py:215](../core/indicators/market_regime.py#L215) | WT 4h + ADX 1h + CHoCH | TREND / REVERSAL / UNCLEAR |
| `classify_v2` ⚠️ SHADOW | [market_regime.py:290](../core/indicators/market_regime.py#L290) | spike_guard + structure + MTF | трёхслойный |

## BTCRegimeProvider (Cross-Market, ARCH-78)

| Метод | Файл:строка | TF | Выход |
|---|---|---|---|
| `BTCRegimeProvider.get_btc_mode` | [core/exchange/btc_regime_provider.py:40](../core/exchange/btc_regime_provider.py#L40) | BTC 4h | BULL / BEAR / NEUTRAL |
| `_fetch_and_compute` | [btc_regime_provider.py:64](../core/exchange/btc_regime_provider.py#L64) | — | calculate_trend(BTC 4h, atr=43, factor=1.25) |

Singleton, TTL = 300 сек. Используется напрямую в [bot/monitoring.py](../bot/monitoring.py) — gate SHORT при BTC BULL str<75.
**🔌 NOT WIRED:** не публикует CROSS_MARKET в шину.

## Funding rate

| Функция | Файл:строка | Условие | Выход |
|---|---|---|---|
| `detect_funding_extreme` | [core/signals/funding_detector.py:63](../core/signals/funding_detector.py#L63) | `|funding| > 0.0005` + WT cross OS/OB | FUNDING_EXTREME ⚠️ SHADOW (DEV-81) |

**🔴 ИСПРАВЛЕНО 27.08.2026: история funding ЕСТЬ.** `ohlcv_cache.db` → таблица
`funding_rates`: **1 557 170 строк, 2022-01 → 2026-06** (symbol · time · interval_hours · rate).
Прежняя запись «истории нет» была неверна и стоила дорого: фандинг НИ РАЗУ не
использовался в замерах, потому что по карте его «не существовало».
**🔌 NOT WIRED:** в шину не публикуется — сферы истории фандинга не видят.

## Pre-compute (ARCH-18)

В [bot/loops/scan_loop.py:549–568](../bot/loops/scan_loop.py#L549) `calculate_wt` + `calculate_trend` вычисляются **один раз** для df_3m / df_15m / df_1h / df_4h / df_1d. Все детекторы должны читать `df["wt1"], df["trend"]` без пересчёта.

**Нарушители принципа SSoT** (пересчитывают локально):
- TREND_SIGNAL пересчитывает `calculate_trend(df_4h)` независимо.
- DIVERGENCE считает свинги отдельно вместо чтения SwingAnalysis из SMC.
- Старый `confluence_scanner` (CONFLUENCE) тянет WT/TSL напрямую из collector.

## ❌ Отсутствует в RAW (выверено 27.08.2026)

**Действительно нет:**
- Camarilla pivots · Woodie pivots · Hurst exponent
- BTC.D (BTC Dominance) · COT (Commitment of Traders)
- RSI-divergence (есть только WT-divergence)
- ATR-percentile / volatility regime (только абсолютный ATR)

**🔴 БЫЛО ОШИБОЧНО ЗАПИСАНО КАК ОТСУТСТВУЮЩЕЕ — данные ЕСТЬ:**

| данные | где лежит | объём | в шине |
|---|---|---|---|
| история funding | `ohlcv_cache.db` → `funding_rates` | **1 557 170 строк, 2022-2026** | 🔌 NOT WIRED |
| USDT.D | `usdtd` · `usdtd_1h` · `usdtd_cg` | 2 617 строк (с 2025-09) | 🔌 NOT WIRED |
| капитализация / supply | `mcap_supply` · `mcap_meta` | 15 948 строк | 🔌 NOT WIRED |
| onchain-события (киты, переводы) | `onchain_events` | 10 029 строк | 🔌 NOT WIRED |
| открытый интерес (OI) | live с Bybit, `radar_oi_d5/d15` | без истории | 🔌 NOT WIRED |
| дрейф вселенной | `subscriptions.db` → `universe_drift` + считается в замерах | 225 дней | 🔌 NOT WIRED |

🔴 **Следствие:** 213 из 230 признаков боевых решений идут МИМО шины — Куб видит
только свечи. Задача: `ARCH-129` Market Data Sphere (19). Подробно: `docs/REGISTRY.md` § 3.5.

---

# СЛОЙ 1 — Детекторы сигналов

15 значений `SignalType` enum ([core/signals/signal_models.py:10](../core/signals/signal_models.py#L10)) + 1 фильтр (BOUNCE) + 1 эскалация (WatchListBreach через DB).

## Сводная таблица детекторов

| # | Детектор | Файл:строка | Статус | Вес | TF | publish? |
|---|---|---|---|---|---|---|
| 1 | ANOMALY | [signal_checkers.py:89](../core/signals/signal_checkers.py#L89) | ✅ ACTIVE | 0.03 | 15m | 🔌 |
| 2 | WT_SIGNAL | [signal_checkers.py:163](../core/signals/signal_checkers.py#L163) | ✅ ACTIVE | 0.133 | 15m + 1h фильтр | 🔌 |
| 3 | WT_B_SIGNAL ⭐ | [signal_checkers.py:311](../core/signals/signal_checkers.py#L311) | ✅ ACTIVE (WR=85%) | 0.15 | 1h | 🔌 |
| 4 | CONFLUENCE | [wt_15m_reversal_scanner.py](../core/signals/wt_15m_reversal_scanner.py) | ⛔ STOPPED (DEV-171) | 0.15 | 15m | — |
| 5 | MTF_BIAS / WT_VERDICT | [signal_checkers.py:488](../core/signals/signal_checkers.py#L488) + [wt_specialist.py](../core/intelligence/wt_specialist.py) | ✅ ACTIVE ⭐ ядро | **0.50** | 6 TF | 🔌 |
| 6 | SMC_STRUCTURE | [structure_detector.py](../core/signals/structure_detector.py) | ✅ ACTIVE | 0.12 | 15m | 🔌 |
| 7 | DIVERGENCE | [core/indicators/divergence_detector.py](../core/indicators/divergence_detector.py) | ✅ ACTIVE | 0.10 | 1h | ✅ (`divergence_found`) |
| 8 | MTF_DIVERGENCE | divergence_detector.detect_cascade | ✅ ACTIVE | бонус | 4h→1h, 1h→15m | ✅ |
| 9 | MTF_ALERT (7 TF) | [core/mtf/mtf_checker.py](../core/mtf/mtf_checker.py) | ✅ ACTIVE (фон 5 мин) | — | 3m/5m/15m/45m/1h/4h/1d | 🔌 |
| 10 | TREND_SIGNAL | [core/indicators/trend_signals.py](../core/indicators/trend_signals.py) | ✅ ACTIVE | 0.04 (avg_R=−0.50) | 4h+1h+15m+5m | 🔌 |
| 11 | PIVOT_REVERSAL ⭐ | [core/pivots/pivot_reversal.py](../core/pivots/pivot_reversal.py) | ✅ ACTIVE (best avg_R=+0.50) | **0.24** | 15m + 1W пивоты + 3m FVG | 🔌 |
| 12 | WATCH_LIST_BREACH | [core/db/signal_watch_list.py](../core/db/signal_watch_list.py) | ✅ ACTIVE | — | 60-сек цикл | 🔌 |
| 13 | OTE_SIGNAL | [core/signals/ote_detector.py](../core/signals/ote_detector.py) | ⚠️ SHADOW (DEV-89) | — | 1h/4h/1d + 15m триггер | 🔌 |
| 14 | FUNDING_EXTREME | [core/signals/funding_detector.py](../core/signals/funding_detector.py) | ⚠️ SHADOW (DEV-81) | — | 8h funding + 15m | ✅ (`funding_extreme`) |
| 15 | LIQUIDITY_SWEEP | [core/signals/liquidity_sweep_detector.py](../core/signals/liquidity_sweep_detector.py) | ⚠️ SHADOW (DEV-82) | — | 1h | ✅ (`liquidity_sweep`) |
| 16 | BOUNCE (фильтр) | [core/indicators/bounce_detector.py](../core/indicators/bounce_detector.py) | ⚠️ FILTER | — | старший+младший TF | — |

**Также (HTF EventBus triggers):** [core/signals/htf_detectors.py](../core/signals/htf_detectors.py) — `wt_cross_4h`, `wt_cross_1d`, `trend_change_1h`. Эти публикуют в EventBus как Full CALL триггеры (приоритет 1–2).

## Карточки детекторов (краткие)

### 1. ANOMALY
- Условие: `volume_ratio > 3.0×` (vs 20-свечного MA), направление по close.
- Strength: `min(volume_ratio × 10, 100)`. + Isolation Forest blend (60% rule + 40% IF).
- Конфиг: [config.yaml:18](../config.yaml#L18) `volume_multiplier: 4.0`.

### 2. WT_SIGNAL (15m WT cross)
- LONG: cross_up + `wt1 < -60` + gap≥3, NOT (`wt1_1h > +60`).
- SHORT: cross_down + `wt1 > +60` + gap≥3, NOT (`wt1_1h < -60`).
- Strength: 55–85 по глубине, +5 за gap≥10. ARCH-23 апгрейд: ±1% от пивота → CONFLUENCE +20str.
- Time gate (DEV-170): только 04:00–18:00 UTC.
- DEV-186 (26.04): SHORT block в TREND_UP / HIGH_VOL.

### 3. WT_B_SIGNAL ⭐ (1h WT-divergence в OS/OB)
- LONG: cross_up + `wt1_last < adaptive p10` + `div_strength ∈ [3, 20]` (min2_wt > min1_wt).
- SHORT: cross_down + `wt1_last > adaptive p90` + `div_strength ∈ [3, 20]` (max2_wt < max1_wt).
- Strength: 70–90 по `div_strength`, +5 за depth<−70.
- Бэктест: WR=84.9%, avgRet=+4.82% (180 дней, 103 пары, n=59).
- DEV-187 (26.04) floor: `os_floor=-30, ob_floor=+30` (защита от тренда, [signal_checkers.py:340](../core/signals/signal_checkers.py#L340)).

### 4. CONFLUENCE ⛔ (DEV-171)
- Lookback 8 баров, gate: WT cross + TSL cross.
- Стопнут с 14.04 (`analysis.confluence.enabled: false`) — суммарный убыток −348R.

### 5. MTF_BIAS / WT_VERDICT ⭐
- Consensus 6 TF (3m/15m/45m/1h/4h/1d): ≥4/6 → bias.
- EXHAUSTION (все в OS/OB) → conf=0.80, gate=BLOCK.
- Time gate (DEV-170): 09:00–18:00 UTC.
- **Главное ядро:** при strength≥70 фиксирует итоговое направление.

### 6. SMC_STRUCTURE (BOS / CHoCH)
- LONG-BOS: пробой выше последнего swing high после разворота.
- LONG-CHoCH: первый разворот после даун-структуры.
- Strength: BOS=65, CHoCH=55.

### 7. DIVERGENCE (4 типа)
- Regular Bull: цена LL + WT HL (оба в OS).
- Regular Bear: цена HH + WT LH (оба в OB).
- Hidden Bull/Bear: продолжение тренда.
- Strength 0–100: расстояние / Δwt / Δцена / зона + бонус двойная +15, тройная +25.
- Внешние фильтры [bot/monitoring.py](../bot/monitoring.py): `_div_passes_filters` — wt-zone + pivot proximity 2%.

### 8. MTF_DIVERGENCE (cascade)
- Hidden на старшем + Regular на младшем в одну сторону.
- Бонус: 1W→1D +25, 1D→4h +20, 4h→1h +15, 1h→15m +10.
- Приоритет: проверяется первой.

### 9. MTF_ALERT (7 TF)
- ≥3 TF в одной зоне (OS / OB) → сигнал. Strength 40–100. Фон 5 мин (Sem 10).

### 10. TREND_SIGNAL
- Классический откат: 15m в OS + cross_up + 5m UP — HIGH conf.
- Агрессивный (1h в OS + 15m UP без cross) — MEDIUM ⚠️.
- Консервативный (все UP + 5m из OS) — VERY_HIGH.
- avg_R = −0.50 → вес деградировал с 0.10 до 0.04.

### 11. PIVOT_REVERSAL ⭐ (best real)
- LONG: цена в ±0.5% от S1/S2/PP + WT cross_up + trend_15m=UP.
- SHORT аналог в ±0.5% от R1/R2/PP.
- Strength: 60 base + 10 за каждый из {WT, trend, FVG, confluence} = max 100.
- SL: ATR(14)×1.5, зажат [1%, 4%]. TP: следующий уровень иерархии.
- BTC gate исключение: всегда проходит SHORT-блок при BTC BULL.
- DEV-188 в работе: проверка реального касания (wick через уровень) + объёма.

### 12. WATCH_LIST_BREACH
- Сигнал WATCH+направление → ждёт пробоя уровня 60 сек/тик → AUTO-ENTRY.
- min_strength_register=75 (DEV-68) перед регистрацией.

### 13. OTE_SIGNAL ⚠️ SHADOW (DEV-89)
- 1h/4h/1d OTE зона 0.705–0.786 + 15m WT cross внутри зоны.
- Backtest C1 (4h+CHoCH): WR=41.7%, Sharpe=2.68, n=72.
- Shadow 20 пар / 90 дней. Дедлайн ~26.04, критерий: WR≥40% ∧ Sharpe≥1.5 ∧ n≥150.

### 14. FUNDING_EXTREME ⚠️ SHADOW (DEV-81)
- LONG: `funding < −0.0005` + WT cross_up в OS.
- SHORT: `funding > +0.0005` + WT cross_down в OB.

### 15. LIQUIDITY_SWEEP ⚠️ SHADOW (DEV-82)
- 1h-бар снимает кластер ликвидности и закрывается обратно.
- Условие: `depth ≥ 0.12%` + `reclaim ≥ 0.05%`. Bonus: weekly pivot совпадает → +15 strength.

### 16. BOUNCE (фильтр)
- Валидирует контртренд-сигналы: «волна 2/4 коррекции в импульсе старшего TF».
- Используется в MTFResolver, не публикует SignalData.

## Watchlist + Entry Priority Matrix

- **WatchList:** [core/db/signal_watch_list.py](../core/db/signal_watch_list.py) — пара в режиме «ожидание пробоя», эскалация по углублению дивергенции.
- **EntryMatrix (DEV-172):** [core/intelligence/entry_matrix.py](../core/intelligence/entry_matrix.py) — P1/P2/P3 на основе `bias_ok` (ATR 1h согласован) + `zone_ok` (OS/OB на 1h/4h) + `trigger` (WT cross 15m).
  - ⚠️ БАГ: priority=None для всех 335+ shadow-сделок (см. [whats-next.md](../whats-next.md)). `wt_snap` не доходит до `evaluate_entry_priority()`.

---

# СЛОЙ 1.5 — Триггеры входа (механика события)

> **Зачем:** детектор = «комбинация условий». Триггер = **атомарное событие на свече**, которое замыкает вход. Один и тот же триггер используется в нескольких детекторах. Ниже — справочник: какие именно события мы умеем ловить и из какого RAW-источника.

## Восемь типов триггерных событий

| Тип | Что значит | Пример | Псевдокод |
|---|---|---|---|
| **CROSS** | Два ряда меняются местами | WT cross, TSL cross | `prev[A] < prev[B] AND last[A] > last[B]` |
| **TOUCH** | Цена в ±N% от уровня | Pivot touch, OB touch | `abs(price - level) / level ≤ threshold` |
| **BREAK** | Закрытие за уровнем | BOS, Watch List Breach | `close > level AND prev_close ≤ level` |
| **CHANGE** | Атрибут поменялся | CHoCH, regime flip, zone change | `prev_state ≠ last_state` |
| **SWEEP + RECLAIM** | Wick за уровень + close обратно | Liquidity sweep, stop-hunt | `low < level − depth AND close > level + reclaim` |
| **ZONE ENTER** | Цена вошла в зону | OTE, FVG, OB | `zone_low ≤ price ≤ zone_high` |
| **FORM** | Появился новый паттерн | Divergence, new swing, new OB | `pattern.detect() returns NEW item` |
| **THRESHOLD** | Атомарное число пересекло порог | Volume spike, funding extreme, ADX rising | `value > threshold AND prev_value ≤ threshold` |

## Полная таблица триггеров

> Колонка **«Сам?»** — можно ли использовать этот триггер как самостоятельный сигнал входа (без полного `analyze_symbol`).
> 🟢 = да, минимум обвязки. 🟡 = да, но нужен фильтр контекста. 🔴 = нет, только в составе детектора.

### CROSS (пересечения)

| # | Триггер | Условие | RAW-источник | TF | Используется в | Сам? |
|---|---|---|---|---|---|---|
| 1 | **WT bullish cross** | `wt1[-2] < wt2[-2] AND wt1[-1] > wt2[-1]` | `calculate_wt` | 15m / 1h / 4h / 1d | WT_SIGNAL, WT_B_SIGNAL, CONFLUENCE, PIVOT_REVERSAL, TREND_SIGNAL, OTE_SIGNAL, FUNDING_EXTREME | 🟡 (нужен zone+gap) |
| 2 | **WT bearish cross** | `wt1[-2] > wt2[-2] AND wt1[-1] < wt2[-1]` | `calculate_wt` | те же | те же | 🟡 |
| 3 | **WT cross в OS** | (1) + `wt1[-1] < -60` | `calculate_wt` + `get_zone` | 15m / 1h | WT_SIGNAL gate | 🟢 |
| 4 | **WT cross в OB** | (2) + `wt1[-1] > +60` | те же | те же | те же | 🟢 |
| 5 | **WT cross на adaptive p10/p90** | cross + `wt1 < p10` (LONG) / `> p90` (SHORT) | `np.percentile(wt1)` 50 баров | 1h | WT_B_SIGNAL | 🟢 |
| 6 | **TSL cross UP** | `close[-1] > trendup[-1] AND close[-2] ≤ trendup[-2]` | `calculate_trend` | 15m / 1h | CONFLUENCE gate, PIVOT_REVERSAL | 🟢 |
| 7 | **TSL cross DOWN** | `close[-1] < trenddown[-1] AND close[-2] ≥ trenddown[-2]` | `calculate_trend` | те же | те же | 🟢 |
| 8 | **EMA fast × slow cross** | EMA(fast) пересекает EMA(slow) | `compute_ema_values` | 15m / 1h | TREND_SIGNAL (косвенно через trend) | 🟡 |
| 9 | **HTF WT cross 4h** | WT cross на 4h в OS/OB | `calculate_wt` | 4h | HTF detectors → EventBus | 🟢 |
| 10 | **HTF WT cross 1d** | то же на 1d | `calculate_wt` | 1d | HTF detectors → EventBus (priority 1) | 🟢 |

### TOUCH (касания уровня)

| # | Триггер | Условие | RAW-источник | TF | Используется в | Сам? |
|---|---|---|---|---|---|---|
| 11 | **Pivot touch ±0.15%** | `abs(close − pivot)/pivot ≤ 0.0015` | `calculate_pivot_points` | 1W/1D/1M пивоты на 15m цене | CONFLUENCE bonus | 🟡 |
| 12 | **Pivot touch ±0.5%** | `abs(close − pivot)/pivot ≤ 0.005` | те же | те же | PIVOT_REVERSAL gate | 🟢 |
| 13 | **Pivot touch ±1%** | `abs(close − pivot)/pivot ≤ 0.01` | те же | те же | ARCH-23 апгрейд WT_SIGNAL → CONFLUENCE | 🟡 |
| 14 | **OB touch (внутри зоны)** | `ob_low ≤ price ≤ ob_high` | `detect_order_blocks` | 15m / 1h / 4h | mtf_smc_specialist features, OTE_SIGNAL | 🟡 |
| 15 | **FVG touch** | цена коснулась края неполного FVG | `detect_fvg` | 15m / 1h / 3m | PIVOT_REVERSAL bonus, OTE | 🟡 |
| 16 | **EQH near (≤1%)** | `abs(price − eqh_level)/price ≤ 0.01` | `detect_equal_highs_lows` | 1h / 4h | mtf_smc_specialist (`eqh_near`) | 🟡 |
| 17 | **EQL near (≤1%)** | `abs(price − eql_level)/price ≤ 0.01` | те же | те же | те же | 🟡 |

### BREAK (пробой / закрытие за уровнем)

| # | Триггер | Условие | RAW-источник | TF | Используется в | Сам? |
|---|---|---|---|---|---|---|
| 18 | **BOS bullish** | close > последний swing_high после разворота вверх | `detect_swing_points` + `detect_structure` | 15m / 1h / 4h / 1d | SMC_STRUCTURE, OTE origin, PairState.smc_snap | 🟢 |
| 19 | **BOS bearish** | close < последний swing_low после разворота вниз | те же | те же | те же | 🟢 |
| 20 | **Watch List breach** | пробой ранее зафиксированного уровня + str≥75 | DB watchlist + close | 15m | WATCH_LIST_BREACH (auto-entry) | 🟢 |
| 21 | **FVG fill (mitigation)** | цена закрылась внутри FVG на 100% | `detect_fvg.mitigation_pct` | 15m / 1h | mtf_smc_specialist | 🔴 |

### CHANGE (изменение состояния)

| # | Триггер | Условие | RAW-источник | TF | Используется в | Сам? |
|---|---|---|---|---|---|---|
| 22 | **CHoCH bullish** | первая смена структуры после серии LL → новый HH | `detect_structure` | 15m / 1h / 4h | SMC_STRUCTURE, OTE_SIGNAL gate, MarketRegime.classify_mode | 🟢 |
| 23 | **CHoCH bearish** | зеркально | те же | те же | те же | 🟢 |
| 24 | **Trend flip** | `prev_trend = +1, last_trend = −1` (или наоборот) | `calculate_trend` | 15m / 1h / 4h | EventBus `trend_change_1h` (priority 2) | 🟢 |
| 25 | **WT zone change** | `prev_zone ≠ last_zone` (OS → N → OB) | `get_zone` | 15m / 1h | внутри detectors | 🟡 |
| 26 | **Regime change** | `prev_regime ≠ last_regime` (TREND_UP → RANGE) | `MarketRegimeClassifier` | 15m+1h+4h MTF | EventBus `regime_change` (priority 3) | 🟡 |
| 27 | **BTC regime flip** | BULL ↔ BEAR на 4h Supertrend | `BTCRegimeProvider` | BTC 4h | BTC gate в monitoring (🔌 ARCH-102 publish) | 🟢 |
| 28 | **Reversal mode flip** | TREND ↔ REVERSAL | `classify_mode` (WT 4h + ADX 1h slope + CHoCH) | MTF | ⚠️ SHADOW (ARCH-103) | 🟡 |

### SWEEP + RECLAIM (снятие ликвидности и возврат)

| # | Триггер | Условие | RAW-источник | TF | Используется в | Сам? |
|---|---|---|---|---|---|---|
| 29 | **Sell-side sweep + reclaim** | `low < sell_liq_level − 0.0012 AND close > sell_liq_level + 0.0005` | `detect_liquidity` (cluster ≥2 swing lows) + close | 1h | LIQUIDITY_SWEEP (⚠️ shadow DEV-82), EventBus priority 1 | 🟢 |
| 30 | **Buy-side sweep + reclaim** | зеркально через `buy_liq_level` | те же | те же | те же | 🟢 |
| 31 | **EQH sweep** | wick через EQH + close ниже | `detect_equal_highs_lows` | 1h / 4h | mtf_smc_specialist (паттерн stop-hunt) | 🟡 |
| 32 | **EQL sweep** | wick через EQL + close выше | те же | те же | те же | 🟡 |
| 33 | **Pivot sweep** | wick через 1W S1/R1 + reclaim | pivots + price | 15m | LIQUIDITY_SWEEP bonus +15 strength | 🟡 |

### ZONE ENTER (вход в зону)

| # | Триггер | Условие | RAW-источник | TF | Используется в | Сам? |
|---|---|---|---|---|---|---|
| 34 | **OTE zone enter** | `0.705 ≤ fib_retrace ≤ 0.786` | `detect_fibonacci` | 1h / 4h / 1d | OTE_SIGNAL gate | 🟢 |
| 35 | **OTE wide enter** | `0.618 ≤ fib_retrace ≤ 0.786` | те же | те же | OTE_SIGNAL extended | 🟡 |
| 36 | **OB zone enter** | цена впервые внутри активного OB | `detect_order_blocks` | 1h / 4h | mtf_smc_specialist | 🟡 |
| 37 | **FVG zone enter** | цена впервые внутри неполного FVG | `detect_fvg` | 15m / 1h | mtf_smc_specialist | 🟡 |

### FORM (формирование паттерна)

| # | Триггер | Условие | RAW-источник | TF | Используется в | Сам? |
|---|---|---|---|---|---|---|
| 38 | **Regular bull divergence** | цена LL + WT HL (оба пивота wt < −60) | `find_swing_lows` + `calculate_wt` | 1h | DIVERGENCE, WT_B_SIGNAL | 🟢 |
| 39 | **Regular bear divergence** | цена HH + WT LH (оба пивота wt > +60) | те же | 1h | те же | 🟢 |
| 40 | **Hidden bull divergence** | цена HL + WT LL | те же | 1h | DIVERGENCE | 🟡 |
| 41 | **Hidden bear divergence** | цена LH + WT HH | те же | 1h | те же | 🟡 |
| 42 | **Double divergence** | две последовательные дивергенции одного типа | `DivergenceDetector` | 1h | DIVERGENCE +15 strength | 🟢 |
| 43 | **Triple divergence** | три | те же | те же | DIVERGENCE +25 strength | 🟢 |
| 44 | **Cascade divergence** | Hidden на 1h + Regular на 15m в одну сторону | `detect_cascade_divergence` | 1h+15m / 4h+1h | MTF_DIVERGENCE | 🟢 |
| 45 | **New swing high/low** | формируется новый pivot ±5 баров | `detect_swing_points` | любой | SMC, divergence | 🔴 |
| 46 | **New OB** | новая OB-свеча перед BOS | `detect_order_blocks` | те же | mtf_smc_specialist | 🔴 |

### THRESHOLD (порог)

| # | Триггер | Условие | RAW-источник | TF | Используется в | Сам? |
|---|---|---|---|---|---|---|
| 47 | **Volume spike** | `volume[-1] / SMA(volume, 20) > 3.0` | `compute_volume_ratio` | 15m | ANOMALY, EventBus `anomaly_volume` (priority 4) | 🟡 |
| 48 | **Volume spike против тренда** | (47) + цена в противоположной стороне | volume + close diff | 15m | ANOMALY (множитель 8 vs 12) | 🟡 |
| 49 | **Funding extreme LONG side** | `funding < −0.0005` | ccxt `fetchFundingRate` | 8h | FUNDING_EXTREME (⚠️ shadow), EventBus priority 2 | 🟢 |
| 50 | **Funding extreme SHORT side** | `funding > +0.0005` | те же | те же | те же | 🟢 |
| 51 | **ADX rising** | `ADX[-1] > 25 AND ADX[-1] > ADX[-3]` | `compute_adx` | 15m / 1h | MarketRegime gate (TREND_UP/DOWN) | 🟡 |
| 52 | **ADX falling** | `ADX[-1] < 25 AND ADX[-1] < ADX[-3]` | те же | 1h | classify_mode (REVERSAL индикатор) | 🟡 |
| 53 | **Volatility spike (ATR%)** | `compute_volatility() > N×median` | `compute_volatility` | 15m / 1h | MarketRegime → HIGH_VOL | 🔴 |
| 54 | **WT extremum hit** | `wt1 < −80` (deep OS) / `wt1 > +80` (deep OB) | `calculate_wt` | 15m / 1h / 4h | WT_B bonus +5 strength, EXHAUSTION gate | 🟡 |
| 55 | **div_strength в окне** | `3 ≤ div_strength ≤ 20` (расстояние между WT-пивотами) | `DivergenceDetector` | 1h | WT_B_SIGNAL (>20 = антисигнал) | 🟢 |
| 56 | **MTF alignment ≥4/6** | ≥4 из 6 TF в одной зоне (OS/OB) | `MTFInterpreter` | 3m/15m/45m/1h/4h/1d | MTF_BIAS, MTF_ALERT | 🟢 |
| 57 | **MTF EXHAUSTION** | все 6 TF в OS (LONG) или OB (SHORT) | те же | те же | derive_wt_verdict gate | 🟢 |
| 58 | **BTC shock** | `abs(BTC 1h move) > 2.5%` | BTC цена | BTC 1h | EventBus `btc_macro` (priority 4) | 🟢 |

### Композитные / временные триггеры

| # | Триггер | Условие | RAW-источник | TF | Используется в | Сам? |
|---|---|---|---|---|---|---|
| 59 | **WT cross + TSL cross в одной свече** | (1/2) AND (6/7) на той же свече | wt + trend | 15m | CONFLUENCE gate (оба обязательны) | 🟢 |
| 60 | **WT cross + pivot touch** | (1/2) + (12) на той же свече | wt + pivots | 15m | PIVOT_REVERSAL gate | 🟢 |
| 61 | **Time gate window** | `09 ≤ hour_utc ≤ 18` (или 04–18 для wt_signal) | datetime | — | DEV-170 фильтр на MTF_BIAS / WT_SIGNAL | 🟢 |
| 62 | **SL cooldown expired** | `now − last_sl > 4h` (per pair) | DB `simulated_trades` | — | _is_in_sl_cooldown filter | 🟢 |
| 63 | **Dedup expired** | `now − last_signal > 30 мин` (per pair) | DB | — | _is_duplicate_signal filter | 🟢 |
| 64 | **Pair cooldown expired (ARCH-88)** | `now > pair_cooldown_until` (sl_streak ≥ 3) | PairState | — | loss memory gate | 🟢 |
| 65 | **New 1W/1D period** | начался новый недельный/дневной период (UTC) | datetime | — | пивоты пересчитываются | 🔴 |

## Как использовать таблицу

**Для трейдера:**
- Триггеры **🟢 «сам»** можно собрать в кастомную мини-стратегию (1–2 условия + фильтр контекста). Минимум зависимостей.
- Триггеры **🟡** требуют как минимум фильтр режима (regime) или направления тренда.
- Триггеры **🔴** нельзя выдёргивать в самостоятельный сигнал — они только промежуточные данные внутри детектора.

**Для DEV (при добавлении нового детектора):**
- Сначала выбрать **тип события** из 8 (CROSS / TOUCH / BREAK / CHANGE / SWEEP / ZONE_ENTER / FORM / THRESHOLD).
- Затем найти существующий триггер в таблице — переиспользовать функцию из RAW-источника.
- Опубликовать в `EventBus` событие соответствующего типа.

**Для шины:**
- Каждый триггер должен мапиться на одно из 22 событий [SphereEvent](../core/context/pair_context.py#L31). Если не мапится — повод расширить enum.
- HTF-триггеры (#9, #10, #24, #27) уже публикуют в EventBus с высоким приоритетом — их можно использовать как Full CALL.

## Пробелы (что нельзя триггерить, потому что не считается)

- ❌ **RSI cross / RSI divergence** — RSI считается, но triggers нет.
- ❌ **MACD cross / histogram zero** — MACD не считается.
- ❌ **Bollinger Bands touch / squeeze** — BB не считаются.
- ❌ **Funding rate change** — есть только текущее значение, истории нет.
- ❌ **USDT.D / BTC.D change** — данных нет.
- ❌ **Open Interest spike** — OI не загружается.
- ❌ **Camarilla H4/L4 touch** — Camarilla pivots не считаются.

---

# СЛОЙ 2 — Контекст (фильтры верхнего уровня)

| Параметр | Источник | Куда влияет |
|---|---|---|
| `regime` (TREND_UP/DOWN/RANGE/HIGH_VOL) | MarketRegimeClassifier.classify_from_dataframes | min_strength по режиму (DEV-155 HIGH_VOL=85, LONG_RANGE=78), regime gate (DEV-64B) |
| `reversal_mode` (TREND/REVERSAL/UNCLEAR) | MarketRegimeClassifier.classify_mode | ⚠️ SHADOW — должен влиять на confluence/pivot_reversal вес |
| `btc_regime` (BULL/BEAR/NEUTRAL) | BTCRegimeProvider (4h Supertrend) | BTC gate: SHORT при BULL str<75 → BLOCK (кроме pivot_reversal) |
| Time gates (DEV-170) | hour_utc | wt_signal 04:00–18:00 UTC, MTF_BIAS 09:00–18:00 UTC |
| Adaptive weights | PerformanceEngine.by_signal_type | `new = base × clamp(1 + avgR×0.4, 0.5, 2.0)`, минимум 20 сделок |
| CircuitBreaker (DEV-156) | rolling 50 trades | WR<15% → +10 к min_strength |

**Полная цепочка фильтров до TG/БД** — см. [BOT_SIGNAL_MAP.md § «Цепочка фильтров»](../BOT_SIGNAL_MAP.md).

---

# СЛОЙ 3 — Шина

В проекте **две шины**, у них разные роли:

## 3.1 PairContextBus — sync state sharing

[core/context/pair_context.py](../core/context/pair_context.py)

- Per-pair хранилище `PairState` + sync pub/sub (`subscribe` 207, `publish` 216).
- При публикации авто-обновляет поля `PairState` через `_auto_update_state` (244–328).
- 22 типа событий ([SphereEvent](../core/context/pair_context.py#L31)):

```
S1  ohlcv_updated
S2  tick_price, volume_spike
S3  wt_verdict, wt_snap_updated
S4  smc_verdict, smc_snap_updated
S5  cross_market
S6  regime_updated
S7  signal_detected, anomaly_detected, divergence_found, pivot_touch
S8  pivot_snap_updated
S9  narrative_built
S10 tsl_moved, tp1_hit, position_closed
S11 trade_closed, cascade_updated, ote_zone_set
S12 sphere_health
```

## 3.2 EventBus — async Full CALL queue

[core/context/event_bus.py](../core/context/event_bus.py)

- Async приоритетная очередь (heapq), дедуп (cooldown 30 мин/пара), семафор max=3.
- 14 типов событий с приоритетами ([event_bus.py:33](../core/context/event_bus.py#L33)):

```
priority 1: liquidity_sweep, wt_cross_1d
priority 2: pivot_touch, funding_extreme, wt_cross_4h, trend_change_1h
priority 3: wt_confluence, ote_reentry, cascade, ml_verdict, regime_change
priority 4: anomaly_volume, btc_macro
priority 5: trade_closed
```

- **Конфиг ([config.yaml:306](../config.yaml#L306)): `event_bus.shadow: false`** ✅ — production с 27.04 (раньше был WOULD_FIRE-only).
- Единственный потребитель: `_fire_analysis()` → `analyze_symbol()` → `register_trade_async()`.

## 3.3 PairState (38 полей)

| Группа | Поля |
|---|---|
| S1 DataCollector | `last_ohlcv_time, ohlcv_tfs_loaded` |
| S2 WSFeed | `tick_price, tick_time` |
| S3 WT specialist | `wt_verdict, wt_confidence, wt_snap` |
| S4 SMC specialist | `smc_verdict, smc_confidence, smc_snap` |
| S5 Cross-Market | `btc_regime, btc_move_pct, cross_market_time` |
| S6 Regime | `regime, reversal_mode` |
| S7 Detectors | `last_signal_type, last_signal_direction, last_signal_strength, last_signal_time, active_divergence, anomaly_active` |
| S8 Pivots | `pivot_snap, near_pivot` |
| S9 Narrative | `last_narrative, last_narrative_time, last_p_win` |
| S10 Exit | `open_trade_id, tsl_active, tp1_hit` |
| S11 Post-Trade | `cascade_count, last_direction, last_close_status, last_close_time, avg_r_cascade, post_tsl_data` |
| ARCH-88 loss memory | `sl_streak_count, last_n_outcomes, pair_avg_r_last_20, last_sl_at, pair_cooldown_until` |
| ARCH-91 narrative feedback | `last_narrative_outcome` |
| S12 Diagnostics | `spheres_ok, last_diagnostic_time` |

## 3.4 TriggerBus

[core/context/trigger_bus.py](../core/context/trigger_bus.py) — отдельная сущность для re-entry триггеров после OTE-зон / TSL-выходов. Заполняется PostTradeAnalyser._on_tsl().

## 🔴 Главный архитектурный долг шины

**11 из 16 детекторов не публикуют SIGNAL_DETECTED в EventBus.** Их результаты обрабатываются in-line в `_broadcast_intelligence_alert`. Это значит: Narrative Builder, Anomaly Sphere (S15), Exit Manager не видят сигналы в момент детекции — они получают агрегированный `recommendation` от TradingIntelligence.

ENCYCLOPEDIA обещает «12/12 сфер publish-ят». Реально — публикуют только: PostTradeAnalyser (`trade_closed`), TradingIntelligence (`wt_verdict_strong`), DivergenceDetector (`_fire_analysis`), HTF detectors.

---

# СЛОЙ 4 — Сферы Куба

> 🧭 **ЭТО ЕДИНАЯ КАРТА СФЕР. Другие документы на неё ССЫЛАЮТСЯ, а не дублируют**
> (правило [[principle_reuse_not_duplication]]). Сведено 27.08.2026 — до этого карт
> было ЧЕТЫРЕ с разной нумерацией, и это была механическая причина, по которой
> «забывали, что в Кубе есть».

**Источник истины — КОД:** [`sphere_registry.py:49`](../core/context/sphere_registry.py#L49)
`SPHERE_NAMES`. Всё остальное сверяется с ним.

**Расхождения, которые были (устранены ссылками, номера НЕ переиспользовать):**

| Источник | Что утверждал | Решение |
|---|---|---|
| `selftest_cube.py` | своя нумерация: S7=TradingIntelligence · S13=PairContextBus | это ПРОВЕРКИ, не сферы — сверять по имени, не по номеру |
| `obsidian/Concepts/Cube-Metatron.md` | 17 сфер, S2=Regime · S13=Portfolio · S16=PositionSync | ⚠️ устарело → ссылается сюда |
| `docs/ENCYCLOPEDIA.md` | 13 сфер + S14=WaveService | канон 13 = сакральная геометрия; 14+ = расширение |
| `TASKS.md` ARCH-121 | WaveService = «Сфера 14» | 🔴 конфликт с ARCH-96 → `FIX-SPHERE-NUM` |

## Текущие сферы S1–S13

| # | Сфера | Файл / Класс | Статус | Что не так / план |
|---|---|---|---|---|
| 1 | DataCollector | [core/infra/data_collector.py](../core/infra/data_collector.py) | ✅ ACTIVE | polling 60 сек, не WS-driven |
| 2 | WSFeed | [core/infra/ws_feed.py](../core/infra/ws_feed.py) | ✅ ACTIVE | подключён, real-time тикеры |
| 3 | MTF WT Specialist (ML) | [core/ml/mtf_wt_specialist.py](../core/ml/mtf_wt_specialist.py) | ⚠️ SHADOW | 35 фич (7 TF × {wt1, wt2, zone, cross, atr_trend}), MIN_TRADES=50, не fitted |
| 4 | MTF SMC Specialist (ML) | [core/ml/mtf_smc_specialist.py](../core/ml/mtf_smc_specialist.py) | ⚠️ SHADOW | 36 фич (4 TF × 9), MIN_TRADES=50 |
| 5 | Cross-Market Node | [core/exchange/btc_regime_provider.py](../core/exchange/btc_regime_provider.py) | ⚠️ SHADOW | gate работает, но не публикует CROSS_MARKET. USDT.D / BTC.D ❌ нет |
| 6 | Market Regime | [core/indicators/market_regime.py](../core/indicators/market_regime.py) | ✅ ACTIVE | reversal_mode SHADOW (`classify_mode`) |
| 7 | Signal Detectors | [core/signals/](../core/signals/), [core/indicators/](../core/indicators/) | ✅ ACTIVE | большинство не публикуют в EventBus |
| 8 | Pivot Levels | [core/pivots/](../core/pivots/) | ✅ ACTIVE | Camarilla / Woodie ❌ нет |
| 9 | Narrative Builder | [core/intelligence/narrative_builder.py:368](../core/intelligence/narrative_builder.py#L368) | ✅ ACTIVE | вызывается, narrative_outcome feedback in progress (ARCH-91) |
| 10 | Exit Manager | [core/trading/trade_simulator.py](../core/trading/trade_simulator.py) (1978 строк) | ⚠️ MONOLITH | в монолите, ARCH-74 разбивка в backlog |
| 11 | Post-Trade Analyser | [core/trading/post_trade_analyser.py](../core/trading/post_trade_analyser.py) | ✅ ACTIVE | 3/4 feedback loops работают |
| 12 | Self-Diagnostics | [core/selftest_cube.py](../core/selftest_cube.py) | ✅ ACTIVE | L13/L14/L15, автономный запуск |
| 13 | PairContextBus | [core/context/pair_context.py](../core/context/pair_context.py) | ✅ ACTIVE | 38 полей, sync pub/sub, 22 типа событий |

## Сферы S13+ — расширение за канон (TASKS.md)

🔴 **Перед добавлением новой сферы свериться с этой таблицей** — иначе номер уйдёт в дубль
(так уже случилось с 14).

| # | Сфера | Задача | Статус | Драйвер |
|---|---|---|---|---|
| 13 | Фаза / Decision Core | — | ⚠️ SHADOW | [`core/context/phase_sphere.py`](../core/context/phase_sphere.py) — композит доказанных сепараторов, логирует не гейтит |
| 14 | Execution Sphere | [ARCH-96](../TASKS.md) | ❌ MISSING — 🔴 критично перед LIVE | IdempotencyGuard, SlippagePredictor, OrderTypeSelector, ExecutionTracker; закроет SL-дубли архитектурно |
| 14? | WaveService | [ARCH-121](../TASKS.md) | 🔴 КОНФЛИКТ НОМЕРА с ARCH-96 | Elliott Wave прокси → `FIX-SPHERE-NUM` |
| 15 | Anomaly Detection | [ARCH-97](../TASKS.md) | ❌ MISSING | Self-observability на execution / trading / ML drift; поймала бы DEV-174/175 за 1–72ч |
| 16 | Portfolio Manager | [ARCH-98](../TASKS.md) | ❌ MISSING | β-exposure к BTC/ETH, sector concentration, rolling DD (5%/8%/15%) |
| 17 | Meta-Learning | [ARCH-99](../TASKS.md) | ❌ MISSING | XGBoost f(context, signal_type) → E[R] контекстуальный фильтр |
| 18 | Setup Engine | [ARCH-107](../TASKS.md) | ❌ MISSING | `TradingSetup` dataclass + state machine + таблица `trading_setups` |
| **19** | **Market Data** | [ARCH-129](../TASKS.md) | ❌ MISSING — 🆕 27.08 | фандинг · OI · доминация · onchain · mcap · магниты · фазы · дрейф → В ШИНУ. Сейчас 213 из 230 признаков решений идут МИМО Куба |

**Занято: 1–19.** Следующая свободная — 20.

## Рёбра (что проверяет L14)

[core/selftest_cube.py](../core/selftest_cube.py) — 16 рёбер:

```
✅ ts → pta              (close_trade callback)
✅ pta → pairctx         (cascade / ote_zone_set / loss memory)
✅ pta → intel           (update_signal_weights каждые 50)
✅ pta → eventbus        (trade_closed publish, ARCH-72)
✅ ti → eventbus         (wt_verdict_strong)
✅ eventbus → consumer   (_fire_analysis)
✅ dc → mr               (classify_from_dataframes)
✅ ti → ts               (register_trade_async)
✅ ws → dc               (real-time прайс)
✅ ts → wt specialist    (wt_snap → train)
✅ ts → smc specialist   (smc_snap → train)
✅ wt → ti               (verdict в metadata)
✅ smc → ti              (verdict в metadata)
✅ mr → ti               (regime в analysis)
✅ ti → pairctx          (last_signal_*)
🔌 detectors → eventbus  (только divergence + HTF + funding/sweep — остальные не публикуют)
```

---

# СЛОЙ 5 — Feedback loops

[core/selftest_cube.py L15](../core/selftest_cube.py)

| # | Loop | Триггер | Эффект | Статус |
|---|---|---|---|---|
| 1 | adaptive_weights | close_trade | PTA → TI.update_signal_weights() каждые 50 закрытий, формула `× clamp(1+avgR×0.4, 0.5, 2.0)` | ✅ ACTIVE |
| 2 | cascade | TSL/TP closed | cascade_count++, post_tsl_data → TriggerBus | ✅ ACTIVE |
| 3 | ml_retrain | каждые 10 закрытий | EventBus → переобучение OutcomePredictor + WT + SMC специалистов | ✅ ACTIVE (ARCH-72) |
| 4 | narrative_outcome | close_trade | `last_narrative_outcome` → NarrativeBuilder.update_weights() | ⏳ ARCH-91 in progress |

---

# Сводная матрица Куба

| Слой | ✅ Работает | ⚠️ В shadow / частично | ❌ Отсутствует |
|---|---|---|---|
| **0 RAW** | WT, ATR/Trend/TSL, ADX/EMA, RSI/Vol, Pivots Trad, Swing/Structure, FVG, OB, Fib OTE, Liq, EQH/EQL ⭐, BTC 4h Supertrend, MarketRegime v1 | reversal_mode (`classify_mode`), MarketRegime v2 | Camarilla, Woodie, USDT.D, BTC.D, Hurst, funding history, RSI-divergence |
| **1 Детекторы** | 11 ACTIVE (ANOMALY/WT/WT_B⭐/MTF_BIAS⭐/SMC/DIV/MTFDIV/MTF_ALERT/TREND/PIVOT_REV⭐/WATCH_LIST) | OTE, FUNDING_EXTREME, LIQUIDITY_SWEEP (3 SHADOW), BOUNCE (фильтр) | CONFLUENCE ⛔ STOPPED (DEV-171), Entry Priority bug (priority=None) |
| **2 Контекст** | regime, BTC gate (production), time gates, adaptive weights, CircuitBreaker, DEV-186 wt_signal regime gate | reversal_mode shadow, mtf_gate_shadow | rolling correlation, USDT.D macro gate (ARCH-67) |
| **3 Шина** | PairContextBus (sync, 22 события), EventBus production (`shadow: false`), TriggerBus, 38 полей PairState | DEV-172 priority=None баг | SIGNAL_DETECTED publish от 11 детекторов |
| **4 Сферы** | S1, S2, S6, S7, S8, S9, S11, S12, S13 (9/13) | S3, S4 ML specialists; S5 Cross-Market; S10 Exit (монолит) | S14 Execution (ARCH-96), S15 Anomaly (ARCH-97), S16 Portfolio (ARCH-98), S17 Meta-Learning (ARCH-99) |
| **5 Feedback** | adaptive_weights, cascade, ml_retrain (3/4) | narrative_outcome (ARCH-91 in progress) | — |

---

# GAP-анализ — что мешает «полному запуску»

Список с привязкой к существующим задачам.

| # | Проблема | Эффект | Связано |
|---|---|---|---|
| 1 | **11 детекторов не публикуют `SIGNAL_DETECTED`** | NarrativeBuilder, Anomaly Sphere, Exit Manager слепы в момент детекции | ARCH-67 mesh, новый под-таск |
| 2 | **BTCRegimeProvider не публикует `CROSS_MARKET`** | смена BULL↔BEAR не доходит до Куба per-pair | ARCH-78 расширение |
| 3 | **reversal_mode shadow** | confluence/pivot_reversal не подавляются в неподходящем режиме (теряем точность) | Активация classify_mode в monitoring.py |
| 4 | **DEV-172 priority=None** | Entry Priority Matrix пустой → ML-фильтр входов мёртв | DEV-172 fix (`wt_snap` не доходит) |
| 5 | **WT/SMC specialists не fitted** | 71 фича Куба не используется ML | дождаться MIN_TRADES=50 после рестарта DEV-190 |
| 6 | **OutcomePredictor AUC=0.41** | P(win) ниже базовой линии — блендинг ухудшает confidence | ARCH-45 этап B/C |
| 7 | **Execution Sphere (S14)** | дубли SL, slippage, broken bracket-orders | ARCH-96 — критично перед LIVE |
| 8 | **Anomaly Sphere (S15)** | DEV-174/175-класс багов виден только глазом | ARCH-97 |
| 9 | **narrative_outcome feedback** | NarrativeBuilder не учится на исходах | ARCH-91 |
| 10 | **Portfolio Manager (S16)** | портфель растёт по β BTC незаметно | ARCH-98 (после Risk Sphere) |
| 11 | **Meta-Learning (S17)** | контекстуальный фильтр E[R\|context, signal] отсутствует | ARCH-99 |
| 12 | **Расширение RAW** | Camarilla/Woodie/USDT.D — потенциал ARCH-93 | ARCH-67 / ARCH-87 в backlog |

---

# Roadmap по фазам

## Фаза 0 — Стабилизация (текущий спринт «Реальные убийцы», 25.04–02.05)

Закрыть базовую убыточность перед расширением Куба.

- [DEV-184](../TASKS.md) ✅ DUAL_TSL → DUAL_TP (config)
- [DEV-185](../TASKS.md) STOP-LIMIT slippage (Шаг 1 = buffer 1.0; ждём T+72h для buffer 2.0)
- [DEV-186](../TASKS.md) ✅ wt_signal regime gate
- [DEV-187](../TASKS.md) ✅ wt_b floor ±30
- [DEV-188](../TASKS.md) pivot_reversal SHORT TREND_DOWN — фактическое касание + объём
- [DEV-189](../TASKS.md) B3 фикс UPDATE stop_loss
- [DEV-190](../TASKS.md) ✅ effective_status helper
- [DEV-191/192](../TASKS.md) wt1_at_trigger_tf + entry_to_trigger_distance_pct в features_json
- [ARCH-100](../TASKS.md) финальный re-audit T+72h

**Критерий выхода:** `avgR pivot_reversal ≥ −0.10R` на отчёте T+72h.

## Фаза 1 — Шина publishes (~1–2 недели)

Привести шину к полному mesh.

1. **Детекторы → `event_bus.publish("signal_detected", ...)`** в [bot/monitoring.py](../bot/monitoring.py) `_broadcast_intelligence_alert` после каждого `is_actionable=True`.
2. **BTCRegimeProvider.publish(`cross_market`)** при смене режима (TTL hook в [btc_regime_provider.py](../core/exchange/btc_regime_provider.py)).
3. **Активация `classify_mode`** — переход `reversal_mode` из shadow в production, запись в PairState.
4. **DEV-172 entry_matrix priority bug fix** — найти, почему `wt_snap` не доходит до `evaluate_entry_priority()`.
5. **HTF detectors** — убедиться, что `wt_cross_4h, wt_cross_1d, trend_change_1h` стабильно публикуются.

**Критерий выхода:** L14 selftest показывает ≥18 рёбер ACTIVE, 0 NOT WIRED. priority=P1/P2/P3 для ≥80% сделок.

## Фаза 2 — ML Specialists production (~2–4 недели)

- [ARCH-45](../TASKS.md) OutcomePredictor этап B/C (split long/short, GradientBoosting). Цель AUC ≥ 0.55.
- [DEV-162](../TASKS.md) `derive_wt_verdict` динамический confidence (триггер: 200+ BLOCK).
- WT/SMC specialists: дождаться MIN_TRADES=50 после рестарта DEV-190 → `fitted=True` → активация в TI.
- [ARCH-99](../TASKS.md) Meta-Learning S17 (XGBoost f(context, signal_type) → E[R]).

**Критерий выхода:** 3 specialist'а fitted, AUC OutcomePredictor ≥ 0.55, contextual filter в TI.

## Фаза 3 — Execution Sphere перед LIVE (🔴 критично)

- [ARCH-96](../TASKS.md) Execution Sphere S14:
  - IdempotencyGuard (по `client_order_id`, закроет SL-дубли архитектурно)
  - SlippagePredictor (предсказание из ATR + spread + recent overshoot)
  - OrderTypeSelector (MARKET vs STOP-LIMIT vs LIMIT в зависимости от volatility)
  - ExecutionTracker (placement / fill / non-execution)
- [DEV-104](../TASKS.md) Dead-Man Timer — emergency close all (Слой 3 ARCH-65).
- [DEV-185.2](../TASKS.md) watchdog STOP-LIMIT non-execution.

**Критерий выхода:** 0 SL-дублей за 7 дней + emergency-close all протестирован end-to-end.

## Фаза 4 — Self-Observability + Portfolio

- [ARCH-97](../TASKS.md) Anomaly Detection Sphere S15 (drift execution / trading / ML).
- [ARCH-98](../TASKS.md) Portfolio Manager S16 (β-exposure, rolling DD 5%/8%/15%).
- [ARCH-79/91](../TASKS.md) narrative_outcome → NarrativeBuilder feedback (закрывает 4-й loop).

**Критерий выхода:** L15 selftest = 4/4 feedback loops. Sphere health green ≥ 95%.

## Фаза 5 — Расширение RAW и Фрактальный Куб (опционально)

- [ARCH-87](../TASKS.md) Fibonacci контекст в PairState (после 50+ OTE сделок).
- [ARCH-67](../TASKS.md) USDT.D macro gate.
- [ARCH-93](../TASKS.md) Future pivots touch / reaction research.
- Camarilla / Woodie pivots — если ARCH-93 покажет ценность.
- [ARCH-76](../TASKS.md) Фрактальный Куб (CubeNode интерфейс) — после LIVE 30+ дней прибыли.

---

# Verification

Как проверить, что эта карта актуальна:

1. **Selftest:** `python core/selftest_cube.py` (или `curl http://localhost:8000/api/cube/selftest`)
   → сравнить L13/L14/L15 с разделом «Слой 4». Бот должен быть запущен: без него отчёт пустой,
   а `--stub` печатает всё MISSING — это каркас проверок, а не статус сфер.
2. **EventBus shadow:** `grep "shadow:" config.yaml` → убедиться, что `event_bus.shadow: false`.
3. **PairState поля:** [core/context/pair_context.py:80–160](../core/context/pair_context.py#L80) пересчитать поля.
4. **SignalType enum:** [core/signals/signal_models.py:10](../core/signals/signal_models.py#L10) — 15 значений.
5. **Sphere event types:** [core/context/pair_context.py:31](../core/context/pair_context.py#L31) `SphereEvent` — 22 типа.
6. **EventBus priorities:** [core/context/event_bus.py:33](../core/context/event_bus.py#L33) `EVENT_PRIORITY` — 14 типов.

При обновлении бота / прохождении задачи спринта — сверять статусы в этом файле и обновлять дату в шапке.

---

# Связанные документы

- [BOT_SIGNAL_MAP.md](../BOT_SIGNAL_MAP.md) — pipeline сигналов: что вызывает кого в одном цикле скана.
- [docs/ENCYCLOPEDIA.md](ENCYCLOPEDIA.md) — теория Куба, типы сигналов в деталях, стратегии.
- [docs/CUBE_ARCHITECTURE.md](CUBE_ARCHITECTURE.md) — Mermaid-диаграммы (8 шт.).
- [TASKS.md](../TASKS.md) — текущие задачи DEV / ARCH / TRADER.
- [whats-next.md](../whats-next.md) — handoff между сессиями.
- [memory/MEMORY.md](../memory/MEMORY.md) — long-term память агента.
