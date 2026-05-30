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

---

## 🔧 NAMING CONVENTION (стандарт ДО упаковки) — 30.05

Аудит вскрыл **непоследовательность имён** — её надо устранить перед единым снимком.

### Проблема: дивергенции — 3 разные схемы
| Сейчас | Что | Дефект |
|---|---|---|
| `bull_div_{tf}` / `bear_div_{tf}` | RSI regular | нет `rsi_` префикса, нет типа |
| `rsi_div_bull_hidden_{tf}` | RSI hidden | OK |
| `wt_div_bull_reg_{tf}` | WT regular | `reg` сокращён (не `regular`) |
| `wt_div_bull_hidden_{tf}` | WT hidden | OK |

### СТАНДАРТ: `{indicator}_div_{dir}_{type}_{tf}`
- indicator: `rsi` \| `wt` \| (будущие: `mfi`, `macd`)
- dir: `bull` \| `bear`
- type: `regular` \| `hidden`
- tf: `5m`\|`15m`\|`1h`\|`4h`\|`1d`

**Переименования (4 базовых) — ✅ ВЫПОЛНЕНО 30.05 (вариант A):**
```
bull_div          → rsi_div_bull_regular   ✅
bear_div          → rsi_div_bear_regular   ✅
wt_div_bull_reg   → wt_div_bull_regular    ✅
wt_div_bear_reg   → wt_div_bear_regular    ✅
```
Синхронно: combinator_v2.py (out-ключи) + arch104_patterns.yaml (anchor_factors).
End-to-end проверено: combinator выдаёт новые имена, старые исчезли, registry 187
enabled, активный T6_L_03 (rsi_div_bull_regular_4h) матчится. **Требует рестарт.**

### Общие правила нейминга (для всех флагов)
| Категория | Шаблон | Пример |
|---|---|---|
| SMC structure | `{dir}_{type}_{tf}` | `bull_bos_1h`, `bear_fvg_4h` |
| SMC zone | `{zone}_{tf}` | `premium_1h`, `ote_long_4h` |
| WT/RSI зона | `{ind}_{zone}_{tf}` | `wt_os_1h`, `rsi_ob_4h` |
| дивергенция | `{ind}_div_{dir}_{type}_{tf}` | `rsi_div_bull_regular_1h` |
| pivot | `pivot_{rel}_{level}_{1D\|1W}` | `pivot_above_PP_1D` |
| числовое | `{ind}_value_{tf}` или `{ind}_{tf}` | `wt1_value_1h`, `rsi_1h` |

### TF-идентификация (ответ на вопрос)
- **SMC/индикаторные** (bos/choch/fvg/ob/div/wt/rsi/atr/ema) — суффикс `_{tf}`: 5m/15m/1h/4h/1d ✓
- **pivot** — суффикс `_{1D|1W}` (только дневные/недельные уровни, статика) ✓
- **числовые indicators.py** — суффикс `_{tf}` по необходимости

### ⚠️ Порядок (важно)
Стандартизировать нейминг → потом упаковывать в единый снимок. Иначе закодируем
бардак в схему. Переименование combinator+YAML = атомарная миграция (или alias-слой
старые→новые для обратной совместимости YAML).

**Связь:** делать в рамках ARCH-117 (единые сферы WT/RSI задают канонический нейминг
дивергенций) — там же alias для миграции без поломки активных паттернов.

---

## 🔴🔴 РЕШЕНИЕ (зафиксировано 30.05.2026 — высший уровень важности)

> Спор роя «вложенный JSON vs плоско vs отдельная таблица» разрешён на **реальных данных БД**
> (15539 сделок), а не на мнениях. Замеры: `subscriptions.db`, SQLite 3.45.3, JSON1 нативный.

### Замеры (факты, не оценки)

| Метрика | Значение |
|---|---|
| Текущий features_json | 26.6 MB, avg **1712 B**, median 1106, max 16868 |
| `json_extract` full-scan (15.5K строк, без индекса) | **~130 ms** (обычная колонка — 34 ms) |
| Целевой снимок 211 флагов — dense JSON | ~60 MB |
| Целевой снимок 770 флагов — **dense JSON** | **~207 MB ⚠️ (×8)** |
| Целевой снимок 770 — **sparse (только true)** | **~22.8 MB ✅** |
| Плоская таблица 770 колонок (INT 0/1) | ~14 MB, но ALTER на каждый индикатор |

### Вердикт хранения

**Отдельная таблица `trade_features` + вложенный JSON по доменам + sparse-булевы + generated-колонки.**

```sql
trade_features:
  trade_id        INTEGER FK → simulated_trades   -- индекс
  schema_version  INTEGER                          -- = 2 (схема задаёт дефолты)
  features_json   TEXT  -- вложенный по доменам, SPARSE (пишем только true + числовые):
                  -- { meta:{entry_tf,session,data_era,...},          ← 16 CORE
                  --   context:{ wt:{...}, rsi:{...}, smc:{...},
                  --             pivot:{nearest_level,distance_pct,relation},  ← свёртка 490→3
                  --             trend:{...} },
                  --   signal:{arch104_pattern_id, confirmations[]} }
  -- generated columns (индексируемые, для ML/дашборда):
  entry_tf  TEXT GENERATED ALWAYS AS (json_extract(features_json,'$.meta.entry_tf')) STORED
  data_era  TEXT GENERATED ALWAYS AS (...) STORED
  + индексы на горячие поля
```

**Почему так (разрешение ложной дихотомии):**
- **«Вложенный vs queryability» — ложный спор.** SQLite поддерживает **generated columns + индексы на `json_extract`** → JSON И быстрые запросы одновременно. Обе стороны роя удовлетворены.
- **Dense JSON на 770 = 207 MB неприемлемо.** Sparse (только взведённые флаги) = 22 MB. False восстанавливается из **версионированной схемы** (отсутствие ключа = false по `schema_version`). Полный вектор для ML — через декодер `snapshot → fixed vector`.
- **Плоская таблица 770 колонок отвергнута:** ALTER на каждый индикатор, потолок SQLite 2000 колонок близок при 1m/тиках, не ложится на доменную модель Куба.
- **Отдельная таблица** (openrouter): разгружает горячую `simulated_trades`, упрощает миграции/бэкап.

### Связь с Кубом Метатрона (см. `docs/ENCYCLOPEDIA.md` → ИНВАРИАНТ ВЫСШЕГО УРОВНЯ)

Снимок = **persistence-проекция центральной сферы** (`PairFullState`). Домены ⟷ `*_snap` шины 1:1.
Замыкает feedback loop Сферы 11 (`исход + снимок → обучение весов`), помеченный в энциклопедии `ОТСУТСТВУЕТ`.

**🔴 ИНВАРИАНТ «ОДИН КАЛЬКУЛЯТОР»:** `combinator.compute_flags()` и сферы Bus используют ОДНУ
формулу на признак. Вариант B (combinator одним кодом) = переходный мост до ARCH-117. Запрещено
два независимых пути расчёта одного признака — это корень самоподтверждения.

---

## 🔬 ШАГ 3 — СВЕРКА PARITY live↔backtest (30.05, скрипт `scripts/arch118_parity_check.py`)

> Один калькулятор (compute_flags) НЕ гарантирует parity сам по себе — расхождение даёт
> РАЗНЫЙ ВХОД (df) и РАЗНЫЙ МЕТОД ВЫРАВНИВАНИЯ. Проверено на 12 парах. Оба источника —
> ТОЛЬКО HTF (1d/4h/1W); LTF (1h/15m/5m) совпадают идеально.

**(2) ГЛУБИНА ИСТОРИИ [системно, приоритет 1]:**
live `build_df_by_tf` грузит 1h@300 → 1d resample ≈13 баров → `ema200_1d` недостоверна.
- `ema50_above/below_ema200_1d`: **10/12** расходятся · `wt_ob_1d`: 10/12 · `discount_1d`: 8/12.
- Фикс: грузить HTF (4h/1d) с достаточной глубиной — нативный fetch 1d@300/4h@300 или 1h@1500+.
  Бэктест (полная история) корректен → live должен догнать глубину, чтобы HTF-индикаторы сошлись.

**(1) МЕТОД ВЫРАВНИВАНИЯ [приоритет 2]:**
backtest `all_flags` = reindex+shift HTF на 1h-сетку (анти-lookahead `+Timedelta`) vs
live `snapshot_features` = independent `iloc[-1]` на каждом TF → расхождение на 1 HTF-период.
- `bear_mom_1d` 8/12 · `vol_spike_4h` 8/12 · `bull_ob_near_4h` 6/12.
- Нужно выбрать КАНОНИЧЕСКИЙ метод: independent-last семантичнее для live-входа (последняя
  закрытая HTF-свеча = что реально известно), shift обязателен в историческом бэктесте.

**Вывод:** ~12-15/211 флагов (только HTF) расходятся ДО фикса. Чинить в Шаге 4 ДО любого ML —
иначе модель учится на неконсистентных HTF-фичах (тот же класс ошибки, что самоподтверждение).

---

## ✅ ШАГ 4 — PARITY ДОСТИГНУТ (30.05, рой 7/7 консенсус)

> Сверка после фикса (`scripts/arch118_parity_check.py`): **0 расхождений** vs backtest-эталон
> (было 34 флага-расхождения на @300). Оба источника устранены.

**Рой team-ask (7 моделей):** консенсус 7/7 на `HTFHistoryCache` и bit-identity; 5/7 на
канон `independent-last`. Полный разбор: `memory/last_team_discussion.md`.

**(a) КАНОН `independent-last` (выравнивание):** `snapshot_features_at(df_by_tf, entry_ts,
closed_only=True)` — снимок на историческую точку = последняя ЗАКРЫТАЯ свеча каждого TF
(trade-time, не bar-time; БЕЗ lookahead). Идентично live `snapshot_features`. Заменяет
reindex+shift ДЛЯ СНИМКА-ФИЧИ. ⚠️ combinator-matching паттернов (`find_matching`) остаётся
на reindex+shift — это отдельный слой (matching ≠ feature-snapshot).

**(b) `HTFHistoryCache` (глубина, рой 7/7):** per-symbol кэш глубокого 1h ≥4320 баров
(3×1440 пагинация; BingX max 1440/запрос, код 109400 при >1440; TTL 1800с). 4h/1d =
resample(deep 1h) → достаточная глубина (1d≈167 баров, ema200_1d сходится) + resample-parity.
Замер сходимости: 1h@300→48 расхождений, @1000→23, @2000→14, **@4000→0**. Прод-путь:
4 get_ohlcv на сделку (раз в TTL), `build_df_by_tf(deep_htf=True)`.

**bit-identity:** `closed_only=True` исключает текущую формирующуюся свечу (приоритет рой 7/7:
identity > freshness).

**Итог:** live ≡ backtest по 211 флагам (0 расхождений). Снимок готов для ML/re-mining.
