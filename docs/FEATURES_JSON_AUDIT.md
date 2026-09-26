# features_json AUDIT (ARCH-118) — 30.05.2026

> 📕 **ИСТОРИЧЕСКИЙ ДОКУМЕНТ — не каталог.** Это разбор состояния ДО стандартизации
> и обоснование решений ARCH-118. Числа ниже (170 ключей, 36–129 на тип) описывают
> **май 2026** и с тех пор неверны.
>
> 🔴 Действующий набор признаков — **только** в [`FEATURE_CATALOG.md`](FEATURE_CATALOG.md).
> Не берите перечни признаков отсюда: `features_json` перестал быть носителем
> рыночного контекста, когда ARCH-118 перенёс снимок в таблицу `trade_features`
> (`arch118.write_table: true` → «features_json НЕ дублируется», см. Шаг 5b ниже).
> Замер 02.09.2026 это подтвердил: `trade_features` покрывает 98–100% сделок с июня,
> `smc_snap` в `features_json` — 10%.
>
> Ценность документа сегодня — **почему** набор устроен так: разрешение спора о
> хранении (Шаг 5b), достижение parity live↔backtest (Шаги 3–4), инвариант
> «один калькулятор».

---

> Карта состояния `features_json` перед стандартизацией (май 2026).
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

## 📋 индикаторный каталог — ПЕРЕНЕСЁН

> 🗑️ **Перечень удалён 02.09.2026.** Он разошёлся с кодом и вводил в заблуждение:
> сверка с `compute_flags` показала **36 отсутствующих** признаков (46% реального
> набора — весь блок CMA/Donchian, breaker, fvg_overlap, ob_mitigated, elliott,
> микроструктура `*_bos_i`/`*_choch_i`) и **4 имени, которых в коде нет** —
> `bull_div`, `bear_div`, `wt_div_bull_reg`, `wt_div_bear_reg`, переименованные
> ещё 30.05 разделом NAMING CONVENTION ниже, в этом же документе.
>
> 🔴 Действующий перечень — **только** [`FEATURE_CATALOG.md`](FEATURE_CATALOG.md),
> и он строится замером, а не переписыванием руками. Актуальные числа (02.09):
> `compute_flags(tf)` = **155** признаков на ТФ (79 без пивотов, 76 пивотных),
> матрица исследований с MTF = **447** (149 × свой ТФ + два старших).
>
> Проверить состав в любой момент — одной командой, без документа:
> ```python
> from core.calculators.combinator_core import compute_flags
> sorted(compute_flags(df, "1h", include_pivots=True).columns)
> ```

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

---

## ✅ ШАГ 5a — свёртка pivot (вариант B, рой team-ask 6/7) — 30.05

> Рой (7 моделей): **Вариант B** (6/7) — расширить combinator числовыми pivot ПАРАЛЛЕЛЬНО
> булевым (гибрid). Консенсус 5/5: инвариант «один калькулятор» критичен, 187 паттернов не
> ломать, гранулярность ценна, вариант C (полная свёртка) рискован. Полный разбор:
> `memory/last_team_discussion.md`.

**Реализация:** `combinator.add_pivot_flags` теперь ДОПОЛНИТЕЛЬНО выдаёт 3 числовых поля
на TF (тот же калькулятор `pp_arr` → инвариант цел):
- `pivot_nearest_{1D|1W}` — ближайший уровень (PP/R1-3/S1-3)
- `pivot_dist_pct_{1D|1W}` — знаковое % до него (+выше / −ниже)
- `pivot_relation_{1D|1W}` — above/below/near

70 булевых pivot ОСТАЮТСЯ (для 187 паттернов + гранулярность). Числовые — для ML feature
importance. Снимок (`feature_snapshot._pack_context`) пишет value-колонки ЗНАЧЕНИЕМ (не sparse-bool).
Проверено: combinator-майнинг `astype(bool)` не падает, 0 ссылок на числовые pivot в 187
паттернах (matching не затронут), parity числовых live==backtest ✅.

---

## ✅ ШАГ 5b — таблица trade_features (материализация, финал ARCH-118) — 30.05

> Архивный слой Куба — persistence-проекция `PairFullState`. Снимок переехал из
> `features_json.arch118_snapshot` (legacy shadow) в отдельную таблицу `trade_features`.

**Схема** (`subscription_manager.py`, 1:1 с simulated_trades):
```sql
trade_features (
  trade_id INTEGER PRIMARY KEY,            -- FK → simulated_trades(id)
  schema_version INTEGER DEFAULT 2,
  source TEXT,                             -- live|backtest
  entry_tf TEXT, snapshot_ts TEXT, n_true INTEGER, n_total INTEGER,
  features_json TEXT,                      -- вложенный sparse снимок {meta,context,signal}
  created_at TEXT DEFAULT (datetime('now'))
)
INDEX idx_trade_features_schema(schema_version, entry_tf)
```
Горячие поля — top-level колонки (query/индекс); вложенные — через `json_extract`
(проверено: `$.context.pivot.pivot_nearest_1D` → 'S1').

**Запись:** `trade_simulator._write_trade_features(trade_id, snapshot)` после `register_trade`
(нужен trade_id). Конфиг `arch118.write_table: true` → prod-путь (таблица), `features_json`
НЕ дублируется. `shadow_enabled` — legacy дубль в features_json (пропускается при write_table).

**data-era граница:** backfill старых сделок невозможен (нет снимка) → таблица заполняется
с момента включения. Старые сделки — только в legacy features_json (где есть).

**Проверено на staging:** CREATE TABLE идемпотентен, запись/чтение/индекс/json_extract OK,
py_compile OK. Миграция применена к прод БД (требует рестарт для активации записи).

**ARCH-118 ЗАВЕРШЁН:** единый parity-консистентный снимок (211 булевых + числовые pivot +
глубокий HTF) материализуется в `trade_features`. Готов для ML/re-mining на чистых данных.
