# Current State

> Последние 3 сессии. Старые записи удалены — история в git log.

---

## [27.05.2026 ~19:27 UTC] Агент: Developer — ARCH-104 расследование + D-051 observability (D-073 ✅)

### ✅ Расследование (data-аудит за 7 дней с 2026-05-20)

- **arch104: 88 сделок** (vs confluence 591, ×6.7 меньше), avgR=+0.45 — 4-е место по качеству среди массовых источников.
- **31/215 паттернов задействовано (14%)**, 21 паттерн с n=1 (шум), только 3 паттерна с n>10.
- **Главный душитель — D-051 wt_cross hard gate** (введён 26.05 коммит 3348afa): поток упал с 20/день до 1-3/день.
- **T5_L_02 avgR=+6.41 — артефакт SWARMS+AIN pump-кластера** (4 сделки SWARMS подряд за 2.5ч по +15R). Без них: avgR=−0.71R на n=5. Это не паттерн работает.
- **D2_L_L3_15m_03 — лидер шума:** n=17 avgR=−0.41 WR_TP=0%.
- **RI v1 НЕ режет:** 828/829 apply=1 (99%). 90% потерь — между risk_decisions_log и register_trade (router gates / dedup / strength).
- **D-051 was a blind spot:** silent `return` без логирования в БД.

### ✅ Коммиты (3)
- `f7356ac` — `bot/loops/arch104_observer_loop.py` +17 строк: `await record_drop(gate_name='arch104_d051_no_wt_cross', ...)` с pattern_id/det_tf/required_flag/anchor_factors/active_flags_count.
- `05b2b5e` — TASKS.md: D-073 ✅, D-074/075/076 в плане.
- `cc3d17e` — TASKS.md: D-073-FOLLOWUP action plan с дедлайном.

### 🚀 Рестарт бота: 27.05.2026 ~19:27 UTC
- D-073 patch активирован — за первые 2.5 часа (до ~21:48 UTC) накоплено **20 записей** `arch104_d051_no_wt_cross`.
- За последние 30 мин — 4-й по объёму gate (выше только dedup/dedup_open/validate_inputs/strength_too_low).
- **Per-pattern первый срез:** L2_wt_double_fvg=7, T2L_L_L2_15m_05=4, T2_L_10=4, T7_S_A3_15m_01=4, T2L_L_L3_15m_08=1.
- **По TF:** 1h=11, 15m=9 (примерно 50/50 — TF-зависимый soft вариант D-074 потенциально оправдан).
- **По направлению:** LONG=16, SHORT=4.

### 🔄 Следующие задачи (D-073-FOLLOWUP в TASKS)
- **Дедлайн 31.05.2026** (через 3 дня от рестарта 28.05) — прогнать SQL по `signal_drops` + per-pattern + per-TF breakdown → решить D-074 (soft / TF-зависимый / keep hard).
- Если за это время на одной паре появится 3+ arch104 сделок за <6h — D-076 → 🔴 (single-position guard, защита от SWARMS-pyramid).
- D-075 (disable D2_L_L3_15m_03) — пока ждём, n=17 на грани значимости.

---

## [27.05.2026 ~11:00 UTC] Агент: Developer — Stability hotfixes + ARCH-113 + Signal Quality Shadow

### ✅ Сессия 26-27.05: 16 коммитов в 3 волны

**Волна 1 — Stability hotfixes (26.05 вечер, 7 коммитов):**
- `7d413a5` **D-073**: WsFeed rollback к Phase A/B (был cascade с 1006 timeouts/день, рой 5/5 рекомендовал)
- `e664120` **D-074**: BingX thundering herd (asyncio.Lock в OrderManager.get_balance) + sync_time soft-fail
- `58af9ab` **D-074**: dashboard safety — `/api/live` timeout 5s + `/v2/` disabled + JOIN через live_orders (фикс "——" зомби)
- `f2c932d` `api_engine`: stale-on-error fallback при BingX DEGRADED
- `2d48f67` **ARCH-113**: fix tp2_candidate в 2 early-exit return (6→7 unpack)
- `731e7a4` `trade_simulator`: убран 48h EXPIRED таймаут (зомби позиции)
- `575d749` `scan_loop`: EventLoop lag probe + TP order_id fetch fallback

**Волна 2 — Подхватили чужие изменения и закоммитили (27.05 утро, 6 коммитов):**
- `2e1aa00` **D-063/ARCH-18**: reuse pre-computed indicators в детекторах (confluence/divergence/trend)
- `e3d3193` **D-061+D-070**: cached positions через OrderManager + orphan detector
- `5832619` **D-066/D-071**: TTL cache = длина свечи + ccxt fetchMarketsThrottle
- `b712e3e` **TP order_id fallback** в tsl_updater + monitoring + trade_router
- `02b0823` **ARCH-OBS**: расширение obsidian daily/weekly pipeline (5 новых скриптов)
- `d37947a` **D-067**: Dashboard Quick Wins (Critical Alerts + Collapsible + Drops card)

**Между ними:** `07663bd` пользователь — DEV-222 arch104 исключён из blocked_regimes HIGH_VOL

**Волна 3 — ARCH-113 Shadow + Signal Quality Shadow (27.05 ~10:00, 3 коммита):**
- `49eafbc` **ARCH-113** TPSelector Shadow Mode + diagnostics — `tp_selector_shadow: true` в config, вычисляем но не применяем, пишем `tp_selector_*` поля в features_json
- `e843315` `pivot_cache` грузится в shadow mode (был bug — только при `enabled=true`)
- `eb3f0d0` **Signal Quality Shadow** — 4 правки роя (5/5 моделей): pivot real_touch+volume, wt confirmation aggregation, confluence divergence, timing-guard scan>250s. Все shadow в `features_json["shadow_*"]`.

### 🔬 Источник правок: рой 5/5 LLM (27.05)
`obsidian/Team-Discussions/2026-05-27-улучшить-триггеры-входа-3-убыточных-стратегий-дета.md`

Корень убытков (post-15.04, n=8409 закрытых):
- confluence -654R (n=1206, WR=39.6%, avgR=-0.543)
- pivot_reversal -405R (n=1787, WR=15.4%, avgR=-0.226)
- wt_signal -152R (n=323, WR=29.4%, avgR=-0.470)

Прибыльный для сравнения: divergence +0.714R (n=176, WR=41.5%).

### 📊 Что собирает shadow в features_json (после рестарта 27.05 утром)

**ARCH-113 TPSelector shadow:**
`tp_selector_mode/magnets_count/clusters_count/tp1_price/tp1_dist_R/tp1_score/tp1_label/tp1_n_sources/tp2_*` + `elapsed_ms`.

**Signal Quality shadow:**
- `shadow_pivot_real_touch` (wick через level + close возврат)
- `shadow_pivot_volume_spike` (vol[-1] > avg[-20]×1.3)
- `shadow_pivot_would_pass` (real_touch AND volume)
- `shadow_wt_confirm_sources/count/would_pass` (≥1 из SMC/OTE/pivot/div)
- `shadow_confluence_div_count/would_pass`
- `shadow_scan_loop_late/duration_s` (>250s)

### 🎯 Следующая задача (поставлена в TASKS.md)
Через 24-48ч (50-100 закрытых сделок) — A/B анализ shadow данных, решение про production hard gate. См. **DEV-224** в TASKS.md.

**NB:** Параллельно (27.05 ~19:00 UTC) пользователь уже перевёл **pivot_reversal SHORT real_touch** в production HARD через DEV-188 (commit 2e7abc8): wick должен достичь `level*0.999`, volume_z<0.8 → +10 penalty. То есть shadow для pivot_reversal SHORT уже отыграл — остался LONG + другие стратегии.

### ⚠️ Что НЕ закоммичено (правки пользователя в config.yaml)
Пользователь параллельно правит config.yaml (D-055/D-056 пороги, DEV-222 exception). Не трогаю — это его решения.

### 🔴 НЕ закоммичено мной (не моё):
В рабочей копии остались некоторые правки других сессий (если есть). `git status` покажет.

---

## [27.05.2026 ~02:30 UTC] Агент: Developer — DRY-рефакторинг helper-модулей + 53 unit-теста

### ✅ Создано 6 helper-модулей (single source of truth)
1. **`core/trading/r_math.py`** (`91c8622`) — compute_one_r/compute_r/clamp_r/compute_unrealized_r.
   1R всегда = `|entry - original_sl|`, fallback на текущий sl, sanity clamp [-15,+15].
   До этого расчёт R дублировался в trade_simulator/dashboard/position_sync.
2. **`core/exchange/position_parser.py`** (`666cec4`) — parse_position/parse_positions/by_symbol_side.
   Hedge-aware: direction всегда из `positionSide`, не из знака qty.
   Закрыт класс багов (трижды фиксили: order_manager/position_sync/adopt_orphans).
3. **`bingx_client.to_bingx_symbol / from_bingx_symbol`** (`7986d6d`) — заменено 11+9 inline `.replace(...)`.
4. **`core/infra/trading_settings.py`** (`90db4eb`) — get_deposit/risk_pct/leverage/is_live + TradingSettings dataclass.
   Единые defaults (1000/1.0/5/sim_only); LIVE_MODES=(vst,live).
5. **`signal_models.to_direction()`** (`92c5854`) — норм direction (LONG/SHORT/NEUTRAL) с поддержкой BUY/SELL/enum/None.
   До этого `_direction_str` дублировался в trade_simulator и trade_router с разной логикой.
6. **`core/infra/time_utils.py`** (`cb1c0e1`) — utc_now/utc_iso/parse_iso_utc/ensure_utc.
   Helper для будущего кода; massive replace 29+ мест не делал — слишком инвазивно.

### ✅ Сопутствующие баг-фиксы по пути
- **`position_sync` основной цикл** (`666cec4`): lookup по `(sym, direction)` вместо просто `sym` — раньше для hedge противоположный direction мешал.
- **`position_sync` dust-close** (`666cec4`): `side="BUY"/"SELL"` из `positionSide` (был hedge bug: BUY на SHORT).
- **`_detect_orphans`**: hedge-aware (теперь positionSide вместо знака qty).
- **`bingx_client` POST/DELETE timestamp retry** (`e1bc283`): асимметрия с GET — POST не имел retry на `code=109400 timestamp invalid` → wl_breach попадали в SIM. Добавлен симметричный retry.
- **TP overshoot warning** (`69b1c37`): `position_sync` логирует если status=TP и R > tp_rr+1 (VST artefact как #15191 FHE R=+15).

### ✅ Тесты (`0f19503`): 53 unit-теста для всех helper'ов
- `test_r_math.py` — 18 (compute_one_r/r/clamp + SWARMS artefact scenario)
- `test_position_parser.py` — 11 (LONG/SHORT hedge mode, one-way fallback, margin estimate)
- `test_dry_helpers.py` — 24 (symbol round-trip, TradingSettings, to_direction, time_utils)
- Запуск: `pytest tests/unit/test_r_math.py tests/unit/test_position_parser.py tests/unit/test_dry_helpers.py`

### 📊 Эффект сессии
- **+15R за 27.05** на P&L календаре (vs -0.94 .. +0.95 за предыдущие дни)
- 7 регистраций за 30 минут после рестарта, **5/7 на бирже** (раньше 2/11)
- 0 `register_returned_none` за 30 мин (раньше 105 за 6ч)
- 25 OPEN+exch=биржа sync восстановлен

### ⚠️ Что не доделано (необязательное)
- `time_utils` helpers есть, но 29+ мест ещё используют raw `datetime.now(timezone.utc)`. Будущий код должен использовать helpers.
- `position_sync.open_on_exchange` legacy dict передаётся в `_detect_orphans` — можно заменить на `open_pairs (sym, side)` для полной hedge-чистоты.

---

## [27.05.2026 ~01:30 UTC] Агент: Developer — adopt_orphans + hedge mode bugfix + EXPIRED root cause

### ✅ Сделано (две итерации)
1. **Скрипт `scripts/adopt_orphans.py`**: adopt orphan-позиций в БД с правильным direction
   - **Hedge mode**: BingX возвращает `positionAmt` как абсолютное значение, direction берётся из поля `positionSide`. Первая версия скрипта (`direction = LONG if qty>0 else SHORT`) была НЕВЕРНА → создала 10 записей с противоположным direction. Откачено `DELETE WHERE id BETWEEN 15149 AND 15158`
   - **Ключ orphan** = `(symbol, side)` а не `symbol` (одна пара может быть и LONG и SHORT одновременно в hedge)
   - **Финальный adopt**: trade_ids 15159-15168 — BANK SHORT, BARD SHORT, BROCCOLI SHORT, COW SHORT, FF LONG, PI SHORT, SOLV SHORT, THE SHORT, TOSHI SHORT, WET SHORT
   - У ВСЕХ 10 уже был SL на бирже (просто `get_sl_order_id` искал не для того direction в diagnostic-фазе)
   - **Sync восстановлен**: OPEN+exch = 23 = биржа

2. **EXPIRED ложное закрытие — root cause фикс** в [tsl_updater.py:148-163](core/exchange/tsl_updater.py#L148-L163):
   - Было: `if not real_qty: ts.close_trade(trade_id, "EXPIRED", ...)`
   - Проблема: `get_position_qty` использует `_get_positions_cached` (TTL 15s). Пустой snapshot от BingX (rate-limit/glitch) попадал в кеш на 15с → все OPEN с tsl_moved за эти 15с массово закрывались EXPIRED, позиции на бирже жили дальше → orphan
   - Фикс: убран `close_trade(EXPIRED)`, остался warning + continue. `position_sync` сам разберётся через `_resolve_exit + filled_orders` + DEV-149 (2-snapshot guard)
   - Это второй EXPIRED-источник (первый = 48h timeout в trade_simulator, убран commit `0000341`)

### ⚠️ Известный косметический баг
- `_detect_orphans` в [position_sync.py:461](core/exchange/position_sync.py#L461): `side = "LONG" if qty > 0 else "SHORT"` — тот же hedge-mode баг, что был в adopt-скрипте. D-070 TG-алерты показывали все позиции как LONG, реально 9 из них SHORT. Текстовая косметика, но желательно пофиксить через `positionSide`

### 🔥 Root cause найден и пофикшен
- `tsl_updater.update_tsl_on_exchange:148-163` закрывал OPEN сделки как EXPIRED при `get_position_qty=0`
- `get_position_qty` использует `_get_positions_cached` (TTL 15s) — пустой snapshot от BingX (rate-limit/glitch) попадал в кеш на 15с
- Все OPEN с tsl_moved за эти 15с массово получали `close_trade(EXPIRED)`, а позиции на бирже жили дальше → orphan
- **Фикс**: убран `close_trade(EXPIRED)`, остался только warning + continue. `position_sync` сам разберётся через `_resolve_exit + filled_orders` (надёжнее) + DEV-149 (2-snapshot guard)
- Пользователь подтвердил: "это EXPIRED и именно поэтому я его убрал вообще" (имел в виду commit 0000341 — 48h timeout в trade_simulator). Это второй EXPIRED-источник

---

## [26.05.2026 ~17:30 UTC] Агент: Developer — D-051 wt_cross HARD gate + soft_gates отключены

### ✅ Сделано
- **Бэктест подтверждён**: wt_cross_up (LONG) / wt_cross_down (SHORT) дают +183% avg_R на 15m, +78% на 1h
- **D-051 реализован как hard gate** в `bot/loops/arch104_observer_loop.py:397-407`
  - Без `wt_cross_{dir}_{det_tf}` в active_flags → trade не регистрируется
  - Shadow logging убран (гипотеза доказана)
- **Soft gates отключены для arch104** в `config.yaml:546`
  - `soft_gates_enabled: []` — arch104 имеет RI v1 + lifecycle check внутри
- **config.yaml:585**: `shadow_trigger_check.enabled: false` (устарело)

### 🔄 Следующие задачи

---

## [26.05.2026 ~14:00 UTC] Агент: Developer — SL/TP orderId crisis fix + root cause

### ✅ Сделано (сессия: live positions без SL/TP)

**Проблема**: 53 из 53 OPEN позиций в live_orders имели NULL sl_order_id. BingX API 3062ms при старте — bracket response приходил с пустыми orderId.

**Результат** (все 53 исправлены):
- **36 позиций**: get_sl_order_id()/get_tp_order_id() нашли orderId на бирже → записаны в БД
- **16 призраков** (qty=0 на бирже): status='CLOSED' в live_orders (ids: 4248,4257,4264,4516,4519,4523,4573,4615,4617,4627,4639,4667,4679,4683,4685,4689)
- **2 позиции** (SPK id=4270, BANK id=4350): SL выставлен вручную через place_sl_order → orderId записан

**Root cause fix** (предотвращение повторения):
- Добавлена `fetch_and_save_tp_order_id()` в `core/exchange/tsl_updater.py` (аналог SL: 3 retry + ручное place_tp_order)
- Добавлены вызовы в `bot/loops/scan_loop.py` (2 места: WL breach + sideways), `bot/monitoring.py`, `core/trading/trade_router.py`
- Обновлён `core/exchange/__init__.py` — экспорт новой функции

**Скрипты** (в e:\tmp\): `diag_live_orders.py`, `check_exchange_orders.py`, `fix_sl_tp_orders.py`, `check_positions_alive.py`, `close_ghost_positions.py`, `fix_remaining_sl.py`

### 🔄 Следующие задачи
1. **D-047** 🔴 — Integrate wt_cross_*_1h gate (walkforward avgR=+1.55 WR=85%)
2. **ARCH-113 Phase 2** — SLSelector: OB edge + CHoCH/BOS confirmation
3. **D-054** 🟡 — API throttling minor pairs
4. Наблюдение: накопить 200+ новых сделок post-26.05 → SQL анализ эффекта фильтров
5. **BingX 3062ms latency** — исследовать причину медленного старта API

---

## [26.05.2026 ~11:00 UTC] Агент: Developer — Signal filter + BE engine (D-055, D-056, D-057)

### ✅ Сделано (сессия: сигнальная фильтрация + усиление прибыльных)

**Все изменения только в `config.yaml`, код не менялся. Бот перезапущен — 242 пары в мониторинге.**

**D-055 — Noise mute (source_policies min_strength 50→80):**
- `pivot_reversal`: 50→80 (avg=-0.22R, WR=29%, n=1781)
- `wt_signal`: 50→80 (avg=-0.48R, WR=32%, n=321)
- `confluence`: 50→80 (avg=-0.58R, WR=31%, n=1147)

**D-056 — BE engine активирован:**
- `use_breakeven: true` (было false, код DEV-40 уже был готов)
- `breakeven_activation_r: 0.5` (добавлено явно)
- Порядок: BE при +0.5R → SL в entry; TSL при +1.0R → трейлинг (current_r от original_sl, не ломается)

**D-057 — Усиление прибыльных (source_policies min_strength 50→40):**
- `divergence`: 50→40 (avg=+0.74R, WR=52%, n=174)
- `arch104`: 50→40 (avg=+0.60R, WR=40%, n=77)
- `min_strength_register`: 60→50 (bonus: liquidity_sweep base_strength=55 теперь полностью проходит)
- `liquidity_sweep` отдельной секции в source_policies нет — идёт прямым каналом через all_scan_signals

**Данные A/B теста (основа решений):** 8163 сделок post-15.04.2026

### 🔄 Следующие задачи
1. **D-047** 🔴 — Integrate wt_cross_*_1h gate (walkforward avgR=+1.55 WR=85%)
2. **ARCH-113 Phase 2** — SLSelector: OB edge + CHoCH/BOS confirmation
3. **D-054** 🟡 — API throttling minor pairs
4. Наблюдение: накопить 200+ новых сделок post-26.05 → SQL анализ эффекта фильтров

---

## [26.05.2026 ~00:00 UTC] Агент: Developer — ARCH-113 Phase 1 РЕАЛИЗОВАН И ЗАКОММИЧЕН

### ✅ Сделано (сессия ARCH-113 Phase 1 Implementation)

**Коммит: `01d4e4d` feat(ARCH-113): TPSelector — Intelligent TP Gravity Engine (Phase 1)**

- `core/smc/tp_selector.py` **СОЗДАН** (301 строка): TPSelector класс с gravity scoring, кластеризацией ±0.5%, _WEIGHTS FVG/PDH/PWH/psycho
- `core/intelligence/recommendation_generator.py`: `calculate_levels()` возвращает 7 значений (+ tp2_candidate), интеграция TPSelector
- `core/signals/signal_models.py`: TradingRecommendation.tp2_price + tp2_source
- `core/trading_intelligence.py`: pivot_cache загружается при `tp_selector_enabled` (не только RANGE)
- `config.yaml`: новая секция `sl_tp_engine` с A/B флагом `tp_selector_enabled: false`

**Тесты пройдены:**
- import OK, smoke test OK (7-значный return, backward compat)
- TPSelector: TP1=68120 (pdh+psycho@68120, 0.93R), TP2=69971 (psycho+pwh+std_r2@69971, 2.46R) ✓

**Включить в проде:** `config.yaml → sl_tp_engine.tp_selector_enabled: true`

**Следующие шаги (Phase 2):**
- Добавить FVG multi-TF источники (smc_snap → 4h/1h FVG) для TP1 магнитов
- SLSelector: OB edge, CHoCH/BOS confirmation, параметрический буфер
- Pyramiding: PYRAMID_ADD signal при достижении TP1

---

## [25.05.2026 ~18:00 UTC] Агент: Architect — ARCH-113 ПОЛНОЕ ИССЛЕДОВАНИЕ ЗАВЕРШЕНО

### ✅ Сделано (сессия ARCH-113 TPSelector Research)

**7 исследовательских скриптов, 156K+ уровней, 20 пар, 2.4 года:**
- `scripts/pivot_comparison_test.py` → Woodie/Camarilla EXCLUDED (overlap 89.5%, 0%)
- `scripts/tp_levels_comprehensive_test.py` → Psycho>>PDH>>STD при dist<0.5R
- `scripts/gravity_cluster_test.py` → кластер 2+ источников: +14-21% lift
- `scripts/gravity_alpha_optimizer.py` → **alpha=1.5 доказан** (top10%=83% reach)
- `scripts/tp_atr_normalized_test.py` → ATR avg=7%, FVG decay по TF
- `scripts/tp_reach_over_time.py` → нет плато до 3 недель, TSL управляет
- `scripts/mtf_pyramid_test.py` → **P(4h FVG|15m FVG hit) = 65.8% vs 51.3%, Lift +14-21%**

**Данные из БД (14502 сделки):**
- 42% SL сделок имели max_R_possible>0.5R — конвертируемый потенциал
- FVG магнит WR=70-85% при dist 0.3-0.5R → expectancy +0.75R (vs текущий -0.44R)

**Рой (4/6 моделей, 25.05.2026 вечер):**
- Синтез: начать с TPSelector Phase 1, MVP: FVG(young)+PDH+psycho
- Plugin-layer через apply_tp_selector() + config флаг
- Pyramiding: новый signal type PYRAMID_ADD → monitoring.py
- Файл: `obsidian/Team-Discussions/2026-05-25-arch-113-tpselector-plan-реализации-intelligent-sl.md`

**Задокументировано:**
- `obsidian/Tasks/ARCH-113.md` — ОБНОВЛЁН: полные данные, 3 фазы, acceptance criteria, базовые веса, A/B план
- `obsidian/Research/ARCH-113-TPSelector-Research-2026-05-25.md` — СОЗДАН: полное досье исследования (7 экспериментов)
- `TASKS.md` — ARCH-113 обновлён с полным планом
- `memory/project_confluence_principle.md` — СОЗДАН: confluence как ядро проекта

### 🔄 Следующие задачи (приоритет)

1. **D-053** 🔴 CRITICAL — WsFeed cascade crash → scan_loop dies (105 случаев/3д) [отдельная сессия]
2. **ARCH-113 Phase 1** 🔴 — TPSelector: создать `core/smc/tp_selector.py` (исследование завершено, данные подтверждены)
3. **D-047** 🔴 — Integrate wt_cross_*_1h gate (walkforward avgR=+1.55 WR=85%)
4. **D-054** 🟡 — API throttling minor pairs

### ⚠️ Незакоммиченные изменения (после сессии)

- `TASKS.md` — ARCH-113 обновлён с полным планом Phase 1/2/3
- `obsidian/Tasks/ARCH-113.md` — полное обновление
- `obsidian/Research/ARCH-113-TPSelector-Research-2026-05-25.md` — новый файл
- `memory/project_confluence_principle.md` — новый файл
- `scripts/` — 7 новых исследовательских скриптов (pivot_comparison, tp_levels_comprehensive, gravity_cluster, gravity_alpha_optimizer, tp_atr_normalized, tp_reach_over_time, mtf_pyramid_test)

---

## [25.05.2026 ev+++++++ UTC] Агент: Developer — **DEV-144 ЗАКРЫТА ✅** (Stage 6 finale)

### ✅ Сделано

**DEV-144 полностью закрыта.** Все 6 stages свёрнуты в одну сессию благодаря делегированию рою.

**Stage 6 файлы:**
- `src/components/CommandPalette.vue` (~140 строк, делегат cerebras 1599 out + правка нативный listener вместо useMagicKeys для preventDefault) — Cmd+K/Ctrl+K глобальный поиск по 7 страницам + open_trades + 215 patterns.
- `src/composables/useDensity.js` (~15 строк, сам) — singleton density ref + localStorage.
- `src/components/Sparkline.vue` (~60 строк, сам) — мини SVG chart готов.
- `src/assets/main.css` дополнен `.density-compact` каскадом.
- `src/App.vue` — подключение CommandPalette + density-кнопка в topbar + ⌘K hint badge.

### 📊 Итог DEV-144

**Структура `web/dashboard/`:**
- 7 страниц: Summary, OpenPositions, History, Analytics, Drops, Patterns, DecisionTimeline
- 9 компонентов: CriticalAlerts, HeroGrid, EquityCurve, StrategyMetrics, ATRChange, OpenPositionsTable, ClosedTradesTable, CommandPalette, Sparkline
- 3 stores: dashboardStore (SSE), liveStore (polling), closedTradesStore (pagination)
- 2 composables: useSSE, useDensity
- 8 routes
- main.css с CSS-переменными палитры + .density-compact каскадом

**Backend (Python):**
- Новый endpoint `/api/patterns` в `web/dashboard_server.py` (читает `config/arch104_patterns.yaml` → 215 production patterns с walkforward статами)

**Production build (финальный):** 3.26s, 49 модулей, 0 ошибок, **57 KB gzipped** (план 80-120 KB).

**Сэкономлено на делегировании в cerebras gpt-oss-120b:**
- CriticalAlerts 616 + HeroGrid 1690 + EquityCurve 1492 + StrategyMetrics 1183 + ATRChange 1071 = 6052 out tok (Stage 2)
- OpenPositionsTable 1564 + ClosedTradesTable 1909 = 3473 out tok (Stage 4)
- dashboardStore 1032 (Stage 3)
- Patterns 1806 + DecisionTimeline 1746 = 3552 out tok (Stage 5)
- CommandPalette 1599 (Stage 6)
- **Всего ~15700 output tokens** ушли на Cerebras, мой контекст работал только на брифах/ревью/интеграции.

**Типовые правки роя (паттерны выявленные):**
1. Ложный `import { defineProps/defineEmits }` (это compiler macros, не импортируются)
2. Markdown-фенсинг вокруг ответа (несмотря на явное "без фенсинга" в брифе)
3. `:style="{color:'green'}"` (CSS named color) → `:class="['green']"` (палитра `--green` из main.css)
4. `sortClass` возвращал `'asc'/'desc'` → `'sort-asc'/'sort-desc'` для CSS стрелочек ▲/▼
5. `router.replace({params})` без named route → path-based `router.replace('/trades/'+id)`
6. `useMagicKeys` без preventDefault → нативный listener с e.preventDefault для глобальных шорткатов
7. Polling-flash `loading=true` на каждом тике → только до первой загрузки
8. profitClass `val>=0` ловил null → явная null-проверка

### 🔄 Следующие задачи

1. **Git commit** — за все 6 stages накопилось много изменений (`web/dashboard/` целиком + `web/dashboard_server.py` патч + 3 MD файла + memory)
2. **Live integration test** — нужно запустить бота из контейнера или netsh portproxy в Windows. После запуска: открыть localhost:5173, увидеть реалтайм через SSE, проверить Cmd+K с реальными paterns/trades, перейти на History и протестировать пагинацию.
3. **Per-pattern drill-down** (Patterns) — модалка с per-pattern equity curve + R histogram. Сейчас клик на pattern в Cmd+K просто переходит на `/patterns`. TODO.
4. **Pattern stats from БД** — extension endpoint `_handle_patterns` чтобы джойнить с simulated_trades через `features_json.pattern_id` (требует чтобы бот **писал** pattern_id в features_json — TODO бэкенд)

---

## [25.05.2026 ev++++++ UTC] Агент: Developer — DEV-144 Stage 5 ✅ (Patterns + DecisionTimeline)

### ✅ Сделано

**Stage 5 закрыт.** Inspect-debugger автономного бота реализован.

**Backend:**
- `web/dashboard_server.py` — добавлен `_handle_patterns` (~50 строк): читает `config/arch104_patterns.yaml`, парсит словарь patterns (215 production patterns), возвращает per-pattern walkforward статы. Route `/api/patterns` зарегистрирован.

**Frontend:**
- `src/pages/Patterns.vue` (~230 строк, делегат cerebras 1806 out + правка `sortClass` для CSS стрелочек) — таблица 215 паттернов с фильтрами direction/search/min-R, sortable headers, anchor-factors chips.
- `src/pages/DecisionTimeline.vue` (~165 строк, делегат cerebras 1746 out + правка path-based router.replace) — route `/trades/:id?`, fetch /api/trades/{id}/trace, 4 секции: header-карточка / gates timeline / confirmations таблица / raw features_json в collapsible.
- `src/router/index.js` — `/patterns`, `/trades/:id?` добавлены
- `src/App.vue` — sidebar расширен (Паттерны 🧩, Decision Trace 🔬)

**Production build:** 3.02s, 0 ошибок. Bundle 53 KB gzipped (было 45 KB после Stage 3). Все 7 страниц компилируются в отдельные code-split chunks (Summary 16 KB, History 7 KB, DecisionTimeline 6 KB, Patterns 5 KB, OpenPositions 4 KB, Drops/Analytics ~0.5 KB).

### 🔄 Следующие задачи

- **Stage 6** (последний) — Cmd+K Command Palette (`vue-command-palette`), sparklines в таблицах (Trends WR/avgR), Compact/Comfort toggle, tick animations (Robinhood-style update flashes). Drag-and-drop виджетов опционально.
- **Git commit** — за все 5 этапов накопилось много изменений.
- **Live integration test** — требует запуск бота из контейнера или netsh portproxy.

---

## [25.05.2026 ev+++++ UTC] Агент: Developer — DEV-144 Stage 4 ✅ (таблицы)

### ✅ Сделано

**Stage 4 закрыт.** Страницы «Открытые» и «История» наполнены sortable таблицами.

**Файлы:**
- `src/components/OpenPositionsTable.vue` (~140 строк, делегат cerebras 1564 out + правки) — 15 sortable колонок. Использует ready-классы main.css (.sortable, .green, .red, .mono). Источник: `dashboardStore.stats.open_trades` (SSE).
- `src/components/ClosedTradesTable.vue` (~190 строк, делегат cerebras 1909 out + правки) — 16 sortable колонок + status badge через v-html (.badge-tp/sl/tsl/exp) + длительность h/m + emit-based pagination panel.
- `src/stores/closedTradesStore.js` (~45 строк, сам) — Pinia: state(rows/page/perPage/total/totalPages/loading/error) + actions(fetchPage, nextPage, prevPage, setPerPage). Endpoint `/api/closed_trades?page&per_page` (уже существует на бэкенде).
- `src/pages/OpenPositions.vue` и `src/pages/History.vue` — thin координаторы со storeToRefs.

Правки роя в Stage 4: те же типовые (ложный import defineProps, markdown-фенсинг, `:style="{color:'green'}"` → `:class="['green']"` чтоб попасть в палитру `--green` из main.css вместо CSS named color, `profitClass(val)` через `>=0` ловил null → починил с явной null-проверкой).

**Smoke-тест:** Vite HMR подхватил 5 файлов, HTTP 200 на каждом. Vite log clean. Бэкенд недоступен (бот на Windows host, не достижим из контейнера) — таблицы покажут empty states.

### 🔄 Что протестировано на текущем дашборде в браузере

Пользователь увидел:
- ✅ HeroGrid 4/4 карточки: BingX "SIM" / Risk "нет данных" / Позиции 0/0 / Drops "ошибка загрузки"
- ✅ EquityCurve empty state "Нет закрытых сделок"
- ✅ StrategyMetrics 4 карточки с дефолтами (EV 0.00R / PF "—" / AvgR +0.00/0.00 / Open P&L "—")
- ✅ ATRChange error state "Ошибка загрузки ATR метрик"
- ✅ Footer "⚠ SSE отключён · работаем по polling-fallback live: HTTP 500"

Все 5 компонентов в правильных fallback/error/empty состояниях. `live: HTTP 500` — это Vite proxy error при недостижимом target, не реальный 500 от бэкенда.

### ⚠️ Технический момент

Бот работает на Windows host (`localhost:8000` в Windows-браузере), а Vite в Docker-контейнере не может туда достучаться (ни через `host.docker.internal`, ни через gateway `172.18.0.1`). Это нормально для dev-контейнера. В прод-сценарии (single host) `vite.config.js` `target: 'http://localhost:8000'` правильный — proxy не трогать. Для интеграционного теста из контейнера — запустить бота **внутри** контейнера или сделать `netsh interface portproxy` в Windows.

### 📌 Следующие задачи

1. **Stage 5** — `Patterns.vue` (215 ARCH-104 паттернов с таблицей + Heatmap), `DecisionTimeline.vue` ("Why did bot do X?" — `/api/trades/{id}/trace`)
2. **Stage 6** — Cmd+K палитра + sparklines + polish
3. **Git commit** — пора зафиксировать Stage 1-4 в репозитории

---

## [25.05.2026 ev++++ UTC] Агент: Developer — DEV-144 smoke-тест прошёл ✅

### ✅ Сделано

**Smoke-тест Stage 1+2+3:**
- `npm install` — 31 пакетов, 39M `node_modules` (первый запуск через `run_in_background` тихо упал — npm не любит непрямой stdin от harness; второй запуск через `timeout 120 npm install` синхронно прошёл за 8 сек)
- `npm run build` — **production сборка 0 ошибок**: 42 модуля transformed, 2.69s, размеры:
  - `index-*.js` (Vue + Pinia + Router + общий код) = 96.79 KB raw / **38.06 KB gzipped**
  - `Summary-*.js` (все 5 компонентов Stage 2) = 18.04 KB raw / 7.04 KB gzipped
  - `OpenPositions/History/Analytics/Drops` = 0.3-0.5 KB каждая (placeholder'ы, code-split)
  - `main.css` (палитра + 30 базовых блоков) = 8.94 KB / 2.35 KB gzipped
  - **Итого 45 KB gzipped** — в плановом бюджете 80-120 KB (`obsidian/Architecture/DEV-144-Dashboard-Redesign-Plan.md`)
- `npm run dev` — Vite 5.4.21 ready in 2с, HMR работает. Все 7 файлов источника отдают HTTP 200 при probe через curl: main.js, App.vue, CriticalAlerts/HeroGrid/EquityCurve/StrategyMetrics/ATRChange.vue, dashboardStore.js, liveStore.js, useSSE.js, 5 страниц, main.css.

**Никаких build-time errors, никаких vite warnings.** Source maps генерируются.

### 🔄 Что НЕ протестировано

- **Runtime в браузере** — нужен браузер (нет в WSL CLI). Headless через Puppeteer/JSDOM не делал.
- **Интеграция с backend** — бот на :8000 не запущен. Vite proxy `/api/*` → :8000 настроен корректно (vite.config.js), сработает когда бот будет запущен.

### 📌 Следующие шаги (пользователь)

1. Запустить бота: `python3 oko_mtf.py` (или альтернативная точка входа)
2. В отдельном терминале: `cd web/dashboard && npm run dev`
3. Открыть `http://localhost:5173/` в браузере → должна загрузиться страница «Сводка» с реалтайм-данными
4. Проверить в DevTools Network → `/api/events?dashboard=1` (EventSource, должен быть в state `eventsource`)
5. Если SSE не подключается — индикатор «⚠ SSE отключён · polling-fallback» появится внизу страницы

### 🔄 Stage 4+

- Stage 4 — sortable таблицы (OpenPositions / History)
- Stage 5 — Patterns / DecisionTimeline страницы
- Stage 6 — Cmd+K палитра + sparklines

---

## [25.05.2026 ev+++ UTC] Агент: Developer — DEV-144 Stage 3 ✅ (Pinia + SSE)

### ✅ Сделано

**Stage 3 закрыт.** Polling-таймеры заменены на SSE через Pinia stores. Критический фикс: компоненты Stage 2 фетчили несуществующий `/api/summary` — переключил на правильный `/api/stats` через SSE.

**Файлы:**
- `src/composables/useSSE.js` — обёртка EventSource с auto-reconnect, exponential backoff 1s→30s. Caller сам делает `disconnect()` (composable нейтрален к component lifecycle — нужно для Pinia setup, где `onUnmounted` не сработал бы).
- `src/stores/dashboardStore.js` (Pinia composition, ~95 строк, делегирован cerebras ~1032 out tok с 3 правками: named import useSSE, опечатка breakeen, неверный API close/onError) — SSE `/api/events?dashboard=1`, слушает `event: dashboard` (5s, полный payload) и `event: stats` (5s, мерж в `stats.summary`). Дополнительный polling `/api/dashboard` каждые 10s для status (scan_health/monitored_pairs/is_monitoring — этих полей нет в SSE).
- `src/stores/liveStore.js` (~40 строк, написал сам) — polling `/api/live` 5s. SSE не покрывает баланс биржи.
- `src/pages/Summary.vue` — сократился с 75 до 30 строк: `dashboard.connect() + live.start()` в onMounted, `storeToRefs` для реактивности, индикатор «⚠ SSE отключён» при offline.

**Все Stage 2 компоненты работают без правок** — контракт props не менялся, только Summary читает из стора.

### 🔄 Следующие задачи

- **Smoke-тест:** `npm install && npm run dev` — нужно Node-окружение. Тогда увидим:
  - SSE подключение (`isLive=true`)
  - реалтайм обновление HeroGrid/StrategyMetrics
  - что carddrops/ATR endpoint'ы возвращают (моя гипотеза основана на чтении старого кода)
- **Stage 4** — sortable/filterable Vue-таблицы для OpenPositions.vue, History.vue. Источник данных: `/api/stats.open_trades` (уже в сторе) и `/api/closed_trades`.
- **Stage 5** — Patterns / DecisionTimeline страницы.
- **Stage 6** — Cmd+K палитра, sparklines.

### ⚠️ Проблемы / гипотезы

- SSE `event: trade_closed` пока игнорируется. В Stage 6 — показывать toast-уведомление.
- В SSE event:dashboard payload `equity` уже идёт массивом — отдельный polling /api/equity не нужен (он остался в Stage 2 Summary но Stage 3 убрал его).
- `scan_health=DEAD` детектируется backend'ом через 15 мин age — это медленный сигнал. SSE мог бы дать быстрее, но `_handle_sse` сам падает при cascade — нужен `event: scan_dead` который мы пока не реализуем.

---

## [25.05.2026 ev++ UTC] Агент: Developer — DEV-144 Stage 2 ✅ ВСЕ 5/5 готовы

### ✅ Сделано

**Stage 2 закрыт.** Все 5 компонентов делегированы в cerebras gpt-oss-120b через `python3 tools/llm_ask.py` (паттерн: бриф в `/tmp/<name>_brief.md` → `--provider cerebras --out` → ревью + правки → `Write`). Суммарно ~5500 output tokens у Cerebras — мой контекст шёл только на брифы/ревью/интеграцию.

**Компоненты** (все в `web/dashboard/src/components/`):
1. **`CriticalAlerts.vue`** — 5 правил баннеров (BingX DOWN/DEGRADED/latency>3s, Scan DEAD/delayed, Pairs=0). `v-if` на section — пустой рендер если деградаций нет.
2. **`HeroGrid.vue`** — 4 карточки (BingX Equity / Risk Exposure / Позиции-WR / Drops). Drops сама фетчит `/api/dropped?hours=1&limit=3` setInterval 60s. **Правки:** убрал ложный `import { defineProps }` (macro), починил placeholder `MODE` → `props.live.mode`, **второй проход после StrategyMetrics:** счётчики и WR живут в `summary.summary.<x>` (вложенный объект бэкенда), не top-level.
3. **`EquityCurve.vue`** — самописный SVG cumulative R curve (W=800/H=240 viewBox, padding top:20/right:50/bottom:30/left:60). Grid + zero-line dash + area-под-кривой + line + 4 корнер-лейбла (Equity / lastVal / "N сделок" / "min·max"). Цвет = по знаку финала. Empty state без SVG. **Без Chart.js** — самописный.
4. **`StrategyMetrics.vue`** — 4 KPI карточки (EV/сделку с порогом, PF с порогами 1.0/1.5/1.2, Avg R Win/Loss, Open P&L). Правка: убрал `defineProps` из импорта.
5. **`ATRChange.vue`** — 3 карточки 1h/4h/15m из `/api/atr_stats` (сама фетчит, setInterval 30s). Цвета акцента 1h=#f8c400, 4h=#2ea043, 15m=#58a6ff. Правка: убрал markdown-фенсинг от роя; убрал `loading=true` из polling (только до первой загрузки — чтобы не мигало «Загрузка…»).

**`Summary.vue`** — подключает все 5, polling 5s (/api/summary, /api/live) + 30s (/api/equity), clearInterval в onUnmounted.

TASKS.md, PROJECT-LOG.md обновлены.

**Паттерн делегирования закрепился:**
- бриф (props контракт + бизнес-логика + CSS-классы из main.css + формат ответа)
- `python3 tools/llm_ask.py --provider cerebras --max-tokens N --out /tmp/X.vue.raw --file /tmp/X_brief.md "..."`
- ревью → Write. Типичные правки: ложный импорт `defineProps`, markdown-фенсинг вокруг ответа, polling-flash loading.
- Дешёво и быстро — Cerebras gpt-oss-120b ~2200 tok/s.

### 🔄 Следующие задачи

1. **Stage 3** — Pinia stores (`dashboardStore`, `liveStore`, `dropsStore`) + `useSSE()` composable вместо polling. Композиция: один SSE-канал `/api/events` (он уже существует в aiohttp), стор подписывается, компоненты читают из стора.
2. **`npm install && npm run dev`** smoke-тест — нужно Node-окружение. Перед запуском проверить что бэкенд возвращает все ожидаемые поля.
3. **Stage 4** — sortable/filterable таблицы (OpenPositions / History страницы).
4. **Stage 5** — Patterns / DecisionTimeline страницы.
5. **Stage 6** — Cmd+K палитра, sparklines.

### ⚠️ Проблемы / гипотезы

- В HeroGrid и StrategyMetrics предполагается схема `summary.summary.{open_count,tp_count,tsl_count,sl_count,total,win_rate,avg_r_win,avg_r_loss,closed_per_day,days_active}` и top-level `{risk_exposure_pct,risk_exposure_usdt,deposit_usdt,open_pnl_r,exchange_health,exchange_latency_ms,status}` — это **из чтения старого index.html**. Если бэкенд `/api/summary` отдаёт иначе — компоненты молча покажут дефолты. Smoke-тест выявит.
- `/api/live` для SIM режима возвращает `mode='SIM'` без balance — HeroGrid карточка 1 покажет "SIM" + дефолтный border. Это ожидаемо.

---

## [25.05.2026 ev. UTC] Агент: Developer — DEV-144 Stage 1 (Vite + Vue 3 setup)

### ✅ Сделано

**Создан `web/dashboard/`** — параллельный фронтенд на Vue 3 + Vite, по плану `obsidian/Architecture/DEV-144-Dashboard-Redesign-Plan.md`. Старый `web/static/index.html` (2981 стр.) не тронут, работает как был.

Файлы:
- `package.json` — vue 3.4 / pinia 2.1 / vue-router 4.2 / @vueuse/core 10.7 / vite 5.0 / @vitejs/plugin-vue 5.0
- `vite.config.js` — порт 5173, proxy `/api/*` и `/sse/*` → `localhost:8000`, alias `@` → `src/`
- `index.html` — entrypoint
- `src/main.js` — createApp + Pinia + router
- `src/App.vue` — sidebar (5 RouterLink + 4 external tool-link) + topbar + RouterView
- `src/router/index.js` — 5 маршрутов с code-splitting через `() => import()`
- `src/pages/{Summary,OpenPositions,History,Analytics,Drops}.vue` — placeholder'ы
- `src/assets/main.css` — палитра через CSS-переменные (`--bg-app`, `--green`, `--blue`, ~30 токенов), все базовые блоки перенесены: sidebar, topbar, hero-grid (4 col + media), critical-alerts с pulse-keyframes, collapsible details, badges, tables, donut-wrap, risk-panel
- `.gitignore` + `README.md`

TASKS.md, PROJECT-LOG.md обновлены.

### 🔄 В процессе / 🟡 ждёт

- **Stage 2** (компоненты): `HeroGrid`, `CriticalAlerts`, `EquityCurve`, `StrategyMetrics`, `ATRChange` — выносить из `web/static/index.html`. Решено делегировать через `python tools/llm_ask.py` (Cerebras gpt-oss-120b для boilerplate, magistral-medium для сложной логики, Gemini для full-context). Это сэкономит контекст под склейку.
- **Stage 3+** ждут (Pinia stores + SSE composable + tables + Patterns/DecisionTimeline pages + Cmd+K)

### ⚠️ Проблемы

- `npm install` не запускался в этой сессии (Node на хосте — TBD при первом локальном тесте). Все файлы — валидный синтаксис.
- Backend `web/dashboard_server.py` обслуживает `/api/*` корректно — проверка реальной интеграции SSE/auth/CORS откладывается на Stage 2.

### 📌 Следующие задачи

1. Stage 2: первый компонент — `CriticalAlerts.vue` (он же D-067 QW1, самый автономный, малый объём — идеальный warm-up для LLM-делегирования).
2. После Stage 2 — Pinia store + SSE composable (Stage 3).
3. Параллельно: `npm install` + smoke-test `npm run dev` в локальном WSL-окружении.

---

## [23.05.2026 ~14:30 UTC] Агент: Developer — ARCH-OBS-01..06 реализованы

### ✅ Сделано

**ARCH-OBS-01:** `tools/obsidian_status_sync.py` + `.git/hooks/post-commit`
- Парсит TASKS.md, синхронизирует status/tags в obsidian/Tasks/*.md
- 23 файла обновлено при первом прогоне (✅→done, 🔴→critical и т.д.)

**ARCH-OBS-02:** `tools/vault_health.py` → `obsidian/Meta/HEALTH.md`
- Orphans 65%, broken links 17% (placeholder'ы исключены), untagged tasks 2.1%
- Подключён в obsidian_loop.py (daily)

**ARCH-OBS-03:** `tools/obsidian_autolink.py` + `.git/hooks/post-merge`
- 164 known IDs, 2779 потенциальных wikilinks в vault
- Dry-run: +76 в TASKS.md, +153 в DISCUSSION.md, +170 в TASKS-ARCHIVE.md

**ARCH-OBS-04:** `tools/obsidian_weekly_digest.py`
- Собирает Discussion + Tasks + git log + DB → Gemini → `obsidian/Index/WEEKLY-*.md`
- Weekly в obsidian_loop (воскресенье)

**ARCH-OBS-05:** `tools/obsidian_dedup_discussions.py`
- Groq→Gemini семантический dedup → `obsidian/Meta/DEDUP-REPORT.md`
- `--apply` флаг для пометки дублей deprecated

**ARCH-OBS-06:** `tools/obsidian_archive.py`
- Файлы >90 дней без входящих ссылок → `_archive/` (не удаляет)
- Сейчас кандидатов нет (vault свежий)

**obsidian_loop.py обновлён:**
- Daily: status_sync + vault_health
- Weekly (воскресенье): weekly_digest + dedup + archive

**TASKS.md:** все 6 ARCH-OBS → ✅

### 📋 Следующие задачи
- D-047: walkforward wt_cross_*_1h gate (🔄 в работе)
- DEV-200: ConfirmationRegistry — все 25 типов публикуются?
- D-049: SL exit_price bug (закрыт в прошлой сессии — проверить)

---

## [22.05.2026 ~04:30 UTC] Агент: Developer — Cascade TSL де-эскалация фикс + SL аудит открытых

### ✅ Сделано

**SL аудит открытых позиций (108 шт):**
- `scripts/fix_sl_audit.py` — создан и запущен. Найдено: 28 позиций с SL > initial_sl (TSL баг)
- 11 SIM + 17 VST обновлены в БД (stop_loss восстановлен из sl_source)
- LONG: 0 проблем. BILL (12.5%) и RUNE (5.08%) — ATR-based, оставлены как есть
- `scripts/repair_vst_sl.py` — создан для обновления exchange SL-ордеров у 17 VST позиций
  - Статус: скрипт готов, но ошибка `bingx requires "secret" credential"` — нужен .env с BINGX_VST_* ключами

**Cascade TSL де-эскалация — диагностика + фикс:**
- Найден конфликт параметров: `cascade_tsl_deescalation_r: 2.5` vs `no_degrade_above_r: 3.0`
- Окно де-эскалации было только 0.5R — позиции ≥3R заблокированы навсегда
- CATI +5.38R (из скрина) никогда не де-эскалировалась несмотря на истощённый WT
- Фикс в `config.yaml`:
  - `no_degrade_above_r: 3.0 → 8.0` (защищать только реальные ракеты 8R+)
  - `r_gradient_rollback_pct: 0.25 → 0.40` (триггер при -60% от пика, не -75%)

### ⚠️ Требует внимания
- **17 VST exchange SL ордеров**: DB исправлена, но биржевые ордера всё ещё имеют старые (завышенные) SL.
  Разница ~0.3%. При следующем TSL цикле бот автоматически обнаружит расхождение и cancel+replace.
  repair_vst_sl.py готов если нужно принудительно исправить (с остановленным ботом).
- **Бот запущен** — cascade TSL фикс (config.yaml) применится без рестарта при следующем reload

### 📋 Следующие задачи
1. Наблюдать CATI/IDOL/RESOLV/TRX — должны де-эскалировать при истощении WT
2. DEV-193: sl_min 0.5% не применяется к range_bounce:pivot (REDSTONE 0.028%)
3. ARCH-95-EXEC: H1-H5 расследование убытков
4. ARCH-94: orphan-detector (open trades без exchange position → TG alert)

---

## [22.05.2026 ~02:00 UTC] Агент: Developer — TSL SHORT bug fix + аудит TASKS + obsidian loop

### ✅ Сделано

**TSL SHORT баг (критический) — исправлен:**
- Root cause: `trade_simulator.py:2212` — `_sl_changed` не проверял `is_tighter`
- При росте цены против SHORT: `apply_floor = current_price * 1.003` поднимался вверх
- БД обновлялась с `stop_loss > entry` → TSL закрывал SHORT с гарантированным убытком
- Данные подтверждали: 120/129 проигравших TSL шортов (92%), 77% имели `stop_loss > entry`
- **Фикс:** добавлен `_tsl_is_tighter_upd(direction, tsl_price, old_sl)` в условие `_sl_changed`
- `core/trading/trade_simulator.py` ~строка 2210 — 3 строки добавлены

**Obsidian Daily Loop — создан:**
- Новый файл: `bot/loops/obsidian_loop.py` — запускает 4 скрипта последовательно в 00:05 UTC
- `bot/core/bot.py` — добавлен `asyncio.create_task(obsidian_daily_loop(self))`

**TASKS.md аудит — 12 задач закрыты:**
- DEV-199/184/185/186/187/209/172/180/88/89/181/182 → ✅
- ARCH-94 → 🟡 (orphan-detector остался)
- Добавлен блок архитектурных ссылок в начало TASKS.md

**docs/CURRENT_ARCHITECTURE.md — создан:**
- Два параллельных потока A (Reactive Bot) + B (ARCH-104 Pattern-Driven)
- Куб Метатрона — статус 21.05.2026 + 4 новых ребра ARCH-104

**ENCYCLOPEDIA.md обновлён:**
- "Куб Метатрана" раздел: Phase 3 активна, Phase 4 заморожена, 4 новых ребра

### ⚠️ Незакоммичено
- `core/trading/trade_simulator.py` — TSL is_tighter fix (DEV-TSL-ONESIDED)
- `bot/loops/obsidian_loop.py` — новый файл
- `bot/core/bot.py` — obsidian_daily_loop
- `TASKS.md` — 12 задач закрыты + архитектурный блок
- `docs/CURRENT_ARCHITECTURE.md` — новый файл
- `docs/ENCYCLOPEDIA.md` — обновлён Куб Метатрана

### 📋 Следующие задачи
1. **Перезапустить бота** — TSL фикс требует рестарта
2. Наблюдать 2-3 дня: TSL SHORT не должен больше писать `stop_loss > entry`
3. Закоммитить накопленное (все файлы выше)
4. DEV-193: sl_min 0.5% не применяется к range_bounce:pivot sl_source (REDSTONE 0.028%)
5. ARCH-95-EXEC: H1-H5 расследование убытков

---

## [18.05.2026 ~00:00 UTC] Агент: TRADER — Аналитика TAIKO/USDT: watchlist + пивоты + WPP

### ✅ Сделано

**Вопрос: куда попадает action=WATCH — в watchlist или теряется?**
- Подтверждено кодом ([monitoring.py:1230-1252](bot/monitoring.py)): WATCH + direction → `_wl.add()`, TTL 4h
- pivot_level = stop_loss рекомендации (не пивот как таковой, а граница идеи)
- Эскалация: score +5, новая дивергенция, MTF NEUTRAL→совпал → action→BUY/SELL

**Реальные пивоты TAIKO/USDT из PivotCalculatorFixed (17.05 ~19:30 UTC):**
- Цена: 0.11000 — прямо на D:PP=0.11007 (+0.06%)
- Конфлюенции: W:S1/D:R3=0.116 (0.20%), D:R1/W:source_low=0.112 (0.53%), W:S2/D:S1=0.107 (0.80%)
- W:PP = 0.12180 — дистанция 9.7% → как TP нельзя (EV отрицательный по таблице >3%)

**Записано в DISCUSSION.md** — блок [17.05.2026] TRADER — TAIKO/USDT: анализ пивотов

### ⚠️ Незакоммичено
- `DISCUSSION.md` — добавлен блок TAIKO анализа (остальные изменения без изменений)
- Все 36+ файлов из предыдущих сессий по-прежнему не закоммичены

### 📋 Следующая сессия — порядок
- Закоммитить накопленное (36+ файлов)
- Проверить 24ч данных после pivot_cache bug fix → реализовать 3 действия роя если подтверждены
- Этап 1.Е TradeRouter — cleanup дублей в trade_simulator.py (не ранее 18.05 ~12:39)
- Отслеживать TAIKO watchlist — эскалировал ли в BUY

---

## [17.05.2026 поздний вечер] Агент: TRADER/Developer — Расследование пропущенных + Рой (2 раунда)

### ✅ Сделано

**Расследование `register_returned_none` (88 случаев/24ч):**
- Причина: DEV-44 HIGH_VOL HARD block в `trade_simulator.py` — корректное поведение
- Вторичная: DEV-155 min_strength_by_direction_regime (SHORT/TREND_DOWN требует ≥60)
- НЕ утечка сигналов — фильтры работают как задумано

**Расследование FHE +7.9% пропущен:**
- Root cause: новый листинг, 111 баров < 160 MIN_BARS для divergence детектора
- `core/infra/data_quality.py`: `MIN_BARS = {"divergence": 160, ...}`
- Не баг — защита от недостаточных исторических данных

**Расследование KAITO +14% пропущен (16.05):**
- 10:07: TriggerLoop PIVOT_TOUCH 1W_S2 → analyze_symbol returned None (pre_collected=False)
- 10:16: zone_enter_os → MTF SHORT 3/3, SMC=STRONG_BEAR_ZONE, BTC=BEAR, Режим=HIGH_VOL → DEV-44 HARD BLOCK
- 11:13: wt_cross_15m LONG in OS — уже поздно
- "Парадокс дна": у любого дна контекст ВСЕГДА медвежий → тренд-следящий бот не входит

**pivot_cache bug исправлен (4 места):**
- `pivot_cache.get(symbol)` → `pivot_cache.get(f"{symbol}_1W")` в 4 местах кода
- FVG+pivot confluence bonus НИКОГДА не работал до сегодня
- После рестарта бонус начнёт применяться → нужно 24ч наблюдения

**Рой раунд 1 ("Парадокс дна"):**
- Вопрос: HIGH_VOL exception для W:S1/S2 + WT OS
- Консенсус 5/5: HIGH_VOL shadow на 2 недели с исключением у W:S1/S2 + WT OS

**Рой раунд 2 (с данными из DISCUSSION.md):**
- Новые данные: pivot_reversal убыточен везде (n=3136, все 4 контекста avgR<0)
- atr_change LONG = -56.9R/7дн (WR=8.8%), SHORT = +26.3R (WR=63.2%)
- atr_change SHORT @ W:S1 (±1%) = avgR+0.637, WR=80% — PREMIUM паттерн
- Золотой паттерн: confluence W_UP + D_above_PP = avgR+0.978, n=888, WR=32.7%
- Консенсус 5/5 на 3 действия (НЕ РЕАЛИЗОВАНЫ — ждут 24ч наблюдения)

### 🔄 ОЖИДАЕТ РЕАЛИЗАЦИИ (после 24ч наблюдения)

**Три действия от роя (утверждены 5/5, ждут данных после pivot_cache fix):**
1. `pivot_reversal: min_strength: 100` или `enabled: false` — убыточен везде n=3136
2. `atr_change LONG = off` (или strength penalty -30) + SHORT только в TREND_DOWN
3. confluence W_UP + D_above_PP: strength += 20 (золотой паттерн +0.978R)

**Решение по 24 открытым atr_change LONG:** Mistral говорит закрыть (сохранить ~17R), Nemotron — дать доживать. Пользователь не принял решение.

**TAIKO str=94 WATCH:** MTF=68% не дотянул до BUY. Рассмотреть снижение порога до 65%.

### ⚠️ НЕ ЗАКОММИЧЕНО

Все предыдущие незакоммиченные файлы + `core/pivots/pivot_reversal.py` (pivot_cache bug fix 4 места).
Итого 37+ файлов незакоммичено.

### 📋 Следующая сессия — порядок

1. Проверить логи бота после 24ч: появились ли FVG+pivot confluence бонусы?
2. Проверить статистику atr_change LONG/SHORT за сутки
3. Если данные подтверждают → реализовать 3 действия роя
4. Закоммитить всё накопленное (37+ файлов)
5. Решить по открытым atr_change LONG позициям

---

## [17.05.2026 вечер] Агент: Developer — wt_sideways off + swing SL + Куб статус

### ✅ Сделано

**DEV-213: wt_sideways отключён**
- `config.yaml` строка 129: `sideways_mode.enabled: false`
- Причина: -131R/24ч, 50% убыточного сигнал-флоу (решение команды + пользователя)
- Возврат: включить обратно если данные изменятся (бычий цикл)

**DEV-214: Swing SL реализован в pivot_reversal.py**
- `core/pivots/pivot_reversal.py`: swing_low (LONG) / swing_high (SHORT) как primary SL
- Алгоритм: wing=4, lookback=30 свечей 15m, берём min(lows_below_price) / max(highs_above_price)
- Fallback → pivot±0.3% если swing не найден или >5% от уровня
- sl_source: `swing_low:X.XXX` / `swing_high:X.XXX` / `pivot_LEVEL:0.3%`
- Данные: avgR(swing_high)=+0.846 n=41 — значительно лучше atr_14

**DEV-210: уточнение** — реализовано как SOFT PENALTY (не hard block):
- TREND_UP LONG: `_regime_str_penalty = 25` (strength -= 25)
- RANGE no_rejection: `_regime_str_penalty = 15` (strength -= 15)
- Философия: рынок цикличен, hard block рискует пропустить бычий разворот

**Куб Метатрона — текущий статус:**
- 11/12 сфер активны (согласно ENCYCLOPEDIA от 11.04.2026)
- Единственная в shadow: Сфера 4 (MTF SMC Specialist) — ждёт 200+ SMC сделок для ML
- Решение: оставить как концепцию, не упрощать до Event-driven

**DEV-215: datetime timezone bug (критический) — исправлен**
- Root cause: `closed_at` в `simulated_trades` хранится как ISO `2026-05-17T01:03:24+00:00`
- `market_stress.py` и `sl_cooldown.py` использовали `strftime("%Y-%m-%d %H:%M:%S")` — пробел вместо 'T'
- SQLite string compare: 'T'(84) > ' '(32) → все ISO timestamps ВСЕГДА >= любого naive cutoff
- Следствие: market_stress ВСЕГДА давал penalty=12 (15-12=3, 18-12=6) + sl_cooldown ВСЕГДА блокировал
- Фикс: `datetime(closed_at)>=datetime(?)` + cutoff в формате `%Y-%m-%dT%H:%M:%S`
- 3 файла: `core/trading/gates/market_stress.py`, `core/trading/gates/sl_cooldown.py`, `bot/monitoring.py`
- Эффект: 269 ложных дропов `below_min_strength` + 208 ложных `sl_cooldown` дропов исчезнут

### ⚠️ Незакоммичено (36+ файлов)
- `core/pivots/pivot_reversal.py` — DEV-210 + DEV-214
- `config.yaml` — wt_sideways off + другие изменения сессии
- `TASKS.md`, `memory/current_state.md`, `DISCUSSION.md`
- `core/trading/trade_router.py` — pre-registration strength check
- `core/trading/gates/market_stress.py` — DEV-215 datetime fix
- `core/trading/gates/sl_cooldown.py` — DEV-215 datetime fix
- `bot/monitoring.py` — DEV-215 datetime fix

### 🔄 Следующие задачи
1. **Закоммитить всё** — DEV-210/213/214/215 + TradeRouter + gate fixes
2. **Рестарт бота** — DEV-215 требует рестарта для применения фикса
3. **Наблюдение 7 дней** → avgR pivot_reversal должен улучшиться; sl_cooldown корректно работает
4. **DEV-212** — pivot_confluence_2plus после 50+ fvg_pivot_zones записей
5. **DEV-211** — MTFPivotAnalyzer deprecated

---

## [16.05.2026 ~12:53 UTC] Агент: Developer — TradeRouter Phase 1 завершена

### ✅ Сделано

**TradeRouter Этапы 1.А–1.Г — полностью реализованы и подтверждены данными:**

- Единый узел маршрутизации для всех 8 точек входа сигналов
- `source_router` записывается в БД у всех сделок (поле корректное)
- 303 сделки за 15 минут после рестарта 12:38:58 — все через router

**Распределение по source_router (первые 15 мин):**
```
wt_sideways      151 (50%) — 28 open, 123 закрыты быстро
atr_change       116 (38%) — 49 open
wt_signal         19 (6%)  — 1 open
wl_breach         13 (4%)  — 3 open
other_strategy     2 (<1%) — pivot_reversal
pivot_reversal     1 (<1%)
trend_signal       1 (<1%) — 1 open
```

**Drops (всё корректно):**
- dedup: 8 (старый monitoring dedup, до router — норма)
- sl_cooldown: 8 (HARD gate в router — корректно)
- dedup_open: 1 (HARD gate в router — корректно)

**Скорость:** ~1200 сделок/час — норма для активного рынка.

### 🔄 Pending

- **Этап 1.Е** — cleanup дублей gates в `trade_simulator.py` — ТОЛЬКО после 48ч стабильности (не ранее 16.05.2026 ~12:39 + 48ч = 18.05.2026 ~12:39)
- **Данные через 24-48ч** → первые avgR по source_router → решение что включать на VST, что отключать

### ⚠️ Проблемы

Нет новых проблем. Бот стабилен.

---

## [14.05.2026 ~12:00 UTC] Агент: Developer — Бэктесты A1+B + 2 фикса

### ✅ Сделано

**Бэктест A1** (`e:/tmp/A1_min_strength_backtest.py`, 15 пар, 60 дней):
- 1h LONG avgR=+0.120 (n=757), 4h LONG avgR=+0.275 (n=192) ← прибыльны
- 1h SHORT avgR=-0.179, 4h SHORT avgR=-0.438 ← убыточны в текущем бычьем рынке
- По неделям: 1h LONG нестабилен (−0.805 в W11, +0.812 в W18)
- **Решение:** min_strength_atr_change=15 (торгуем все crosses, наблюдаем)

**Бэктест B1** (`e:/tmp/B1_wt_sideways_tsl.py`, 2118 сделок):
- SHORT в TREND_UP: n=891, avgR=+0.211, totalR=+187.7 ← gate 3e1ca17 блокировал это!
- Pre-gate avgR=+0.050 vs post-gate avgR=−0.046
- TSL activated avgR=+0.982 vs TSL NOT activated avgR=−0.797
- 680 SL сделок с MFE>0.5R → потенциал TSL@0.5R

**Коммит a6fb69e** `fix(A1+B)`:
1. `config.yaml`: `min_strength_atr_change: 15`
2. `scan_loop._execute_atr_change_signal`: читает `min_strength_atr_change`
3. `wt_sideways_strategy.py`: gate atr_trend_1h_bias убран, bias только в metadata

**Коммит 3e152ec** `fix(TRADER-14.05)`:
1. `trade_simulator.py`: signal_type_override обрабатывается → atr_change не composite
2. `scan_loop._select_optimal_sl_long/short`: SL candidates logging INFO

### ⚠️ ТРЕБУЕТСЯ РЕСТАРТ

После рестарта ожидать:
- atr_change сделок с signal_type='atr_change' (не composite)
- wt_sideways сделок без gate (SHORT в TREND_UP разрешены)
- SL кандидаты в логах (INFO [SL_SELECT LONG/SHORT])

### 🔄 Pending

- **C**: бэктест TP variants (3R vs pivot) — ждёт накопления atr_change сделок при min=15
- **TSL@0.5R wt_sideways**: отдельная задача после 24ч данных
- **E**: DEV-207 metadata SQL+JSON скетч

---

## [14.05.2026 ~10:00 UTC] Агент: Developer — TRADER fixes + аудит за ночь

### ✅ Сделано

1. **Аудит данных за ночь (30ч, БД + crypto_bot.log):**
   - signal_drops собран: 1313 записей, top reasons: dedup 981, strength_too_low 241, sl_cooldown 81
   - **atr_change drops: 123 (1h) + 101 (4h) + 17 (15m) — ВСЕ strength_too_low**
   - Дистрибуция strength: 130×15 (чистый 1h), 91×18 (чистый 4h), 18 случаев 20-26 (с confluence). **0 случаев strength≥30** → confluence не накапливает много.
   - 12 composite сделок 13.05 ДО дедупа (c948be4), 9/12 SL. После c948be4 → 0 atr_change сделок за 36ч (отсекаются по min_strength_register=40)
   - **wt_signal катастрофа**: 47 сделок SHORT (нет LONG), avgR=-1.23. RANGE 26 сделок avgR=-1.69 — главный убийца ночи
   - watch_list_breach +0.29 ✅, mtf_bias +2.07 ✅, pivot_reversal -0.25

2. **Расследование DEV-209 OTE confluence:**
   - В логах: 19+ `[ATRChange] 15m в OTE — разрешён прямой вход` за ночь
   - OTE логика работает: `price_in_ote=True` ~4% сканов, `ote_zone` confirmation добавляется
   - **Проблема не в DEV-209** — strength = trigger(8/15/18) + ote_zone(7) = 15-25 < min=40
   - → задача A1 (калибровка min_strength_atr_change по данным)

3. **Коммит 3e152ec `fix(TRADER-14.05)`:**
   - `signal_type_override` обрабатывается в `trade_simulator.py:401-402` (раньше игнорировалось → composite вместо atr_change)
   - `_select_optimal_sl_long/short`: SL candidates logging повышен debug→INFO, добавлен список отброшенных + причина (dist<0.3% / dist>10%)
   - Эффект: новые atr_change сделки в БД получат `signal_type='atr_change'`, TRADER TR-003 сможет фильтровать. SL логи покажут почему swing_low/atr14_2x отбрасываются (для решения по max_dist 10%→15%)

### 🔄 Pending (от 14.05 ~01:00)

Без изменений:
- **A1**: после 24-48ч сбора drops → калибровка min_strength_atr_change (15/25/30/40) по данным
- **B**: откат wt_sideways gate (3e1ca17) + tsl_activation_r=0 + бэктесты
- **C**: бэктест TP variants (фикс 3R vs PivotCalculatorFixed.get_pivot_tp DEV-110)
- **E**: DEV-207 metadata SQL+JSON скетч для веб-разработчика

### ⚠️ Накопленные проблемы (требуют решения после данных)

- **wt_signal SHORT в RANGE**: 26 сделок avgR=-1.69 за 30ч. Пользователь сказал «никаких блоков» — нужно искать другой подход (веса, soft penalty)
- **wt_sideways 1 сделка за 30ч** — gate 3e1ca17 чрезмерно жёсткий, ждёт B
- **0 exchange сделок за 30ч** — бот в SIM-only? Или поле другое. Проверить

### Незакоммиченные изменения (для отдельной задачи)

- `core/confirmations/registry.py`: `atr_change_15m SHORT` 8→5 — кто-то правил, не моя сессия
- DISCUSSION.md, TASKS.md, monitoring.py и др. — не трогал, оставлены как есть

---

## [14.05.2026 ~01:00 UTC] Агент: Developer — DEV-209 серия фиксов + observability

### ✅ Сделано (коммиты по порядку)

1. **4790f06** `fix(atr_change_detector)` — cross на закрытой свече iloc[-2] (симуляционный TSL паттерн). Решил false flip-flop SHORT/LONG/SHORT каждые 10 мин на 4h. Тест: 39 false drops/день/пара → 0.

2. **88beec8** `feat(DEV-209)` — per-source window aggregator (atr_change_15m/1h=1800s, 4h=3600s), параметризация _execute_atr_change_signal LONG/SHORT, 15m+OTE условие, auto ote_zone confirmation, _select_optimal_sl_short, ote_direction/ote_tf в snap.

3. **3e1ca17** `fix(wt_sideways)` — cross-gate atr_trend_1h_bias через df_1h. Откатить если 0 wt_sideways сделок продолжается (сейчас наблюдается слишком жёсткий блок).

4. **752a6a0** `fix(DEV-189)` — TSL UPDATE stop_loss для SIM сделок. Отделено `_sl_changed` от `_needs_exchange_update`. Эффект: SIM avgR -0.63 → -0.40, TSL captured% 50→207.

5. **b3e06bc** `fix(DEV-209)` — ote_direction/ote_tf через `_extract_smc_narrative` → features_json (для DEV-208 аудита).

6. **c948be4** `fix(DEV-209)` — дедупликация source в ConfirmationAggregator. До: 4×atr_change_4h в окне → trigger=72 → ложные сделки (7/7 SL 13.05). После: один source = один вес.

7. **3787aea** `fix(DEV-209/A2)` — record_drop в silent skip ветках `_execute_atr_change_signal` (strength_too_low/invalid_sl/register_returned_none/exception). Observability для калибровки min_strength_atr_change по данным.

### 🔄 В ПРОЦЕССЕ (прерван компактом)

**Ожидается рестарт пользователем** для сбора данных signal_drops с новым A2 record_drop.

**TODO следующих шагов:**
- **A1 (бэктест)**: после 24-48ч сбора drops → определить оптимальный min_strength_atr_change (15/25/30/40) по данным
- **B**: откат wt_sideways gate (3e1ca17) + tsl_activation_r=0 (TSL@entry) + бэктесты
- **C**: бэктесты вариантов TP — фиксированный 3R vs `PivotCalculatorFixed.get_pivot_tp()` (узел уже есть, DEV-110/Этап 7 ROADMAP)
- **E**: DEV-207 metadata SQL+JSON скетч для веб-разработчика (match exchange↔БД)

### 🔍 Контекст диагностики 14.05

Реальные cross supertrend(43,1.25) на 1h:
- ENA: 3 cross за 24-48ч (12-13.05)
- GRT: 3 cross
- BTC: 3 cross (включая 13.05 18:00 UP)

В БД: **0 atr_change_1h сделок за 48ч**. Корень — `min_strength_register=40` отрезает чистые atr_change (вес 15-25 < 40). До дедупа (c948be4) проходили только за счёт 4×inflate.

После c948be4 + рестарта: atr_change pipeline даст 0 сделок пока не снизим порог или не накопится confluence. A2 record_drop покажет в БД сколько теряется.

**Артефакты от старого пайплайна** (12 atr_change_4h сделок 13.05, 7/7 SL) — следствие dedup bug. После рестарта не повторится.

### ⚠️ Проблемы накопленные

- **115 → 33 → ? открытых позиций** — потенциальная перегрузка risk_management
- **wt_sideways 0 за 10 мин после 3e1ca17** — gate слишком жёсткий, нужен откат + soft penalty
- **ote_direction=None в features_json** до b3e06bc — теперь должен заполняться (после рестарта)
- **TASKS.md модифицирован пользователем** — DEV-199/200/201 статусы 🔴 (видимо хочет пересмотреть), DEV-189 ✅

### Следующая сессия

1. Прочитать `current_state.md` (этот файл)
2. Проверить через SQL signal_drops за период с момента рестарта — сколько atr_change cross теряем по strength_too_low
3. На основе данных → A1 решение по min_strength_atr_change
4. После — B/C бэктесты

История коммитов:
```
3787aea fix(DEV-209/A2): record_drop в silent skip ветках
c948be4 fix(DEV-209): дедупликация source в ConfirmationAggregator
b3e06bc fix(DEV-209): ote_direction/ote_tf через narrative → features_json
752a6a0 fix(DEV-189): TSL UPDATE stop_loss для SIM сделок
3e1ca17 fix(wt_sideways): cross-gate atr_trend_1h_bias
88beec8 feat(DEV-209): ATR change 15m в OTE + per-source window + LONG/SHORT
4790f06 fix(atr_change_detector): cross только на закрытой свече
3502de8 fix(tasks): сохранить DEV-209 (ARCH-112 update) после revert
ef24889 Revert "feat(confirmation-driven)..."
0d6a394 (revert'ed)
```

---

## [09.05.2026 ~15:30 UTC] Агент: Developer — DEV-199/200/201/203 завершены (параллельные субагенты)

### ✅ Сделано

**DEV-199 — ATRChangeDetector:**
- Создан `core/signals/atr_change_detector.py` — класс `ATRChangeDetector(atr_period=43, factor=1.25)` + `ATRChangeEvent` dataclass
- `bot/core/bot.py` — добавлен `self.atr_change_detector = ATRChangeDetector()`
- `bot/loops/scan_loop.py` — подключён в scan_one для 15m(prio=2)/1h(prio=1)/4h(prio=1), 1d не публикуется
- `core/context/event_bus.py` — добавлены `atr_change_15m/1h/4h` в EVENT_PRIORITY
- ✅ `from core.signals.atr_change_detector import ATRChangeDetector` — OK

**DEV-200 — ConfirmationRegistry:**
- Создан пакет `core/confirmations/` (`__init__.py` + `models.py` + `registry.py`)
- 25 confirmation типов: 3 trigger + 22 confirmation, веса 1-18
- `tests/test_confirmations.py` — 58/58 тестов PASSED
- ✅ `from core.confirmations import Confirmation, get_weight, is_trigger` → `OK 15`

**DEV-201 — ConfirmationAggregator:**
- Добавлен класс `ConfirmationAggregator` в `core/intelligence/signal_aggregator.py`
- `strength = Σ weight × confidence`, режимы reversal/cascade/momentum/unknown
- `strength_breakdown` — breakdown по trigger vs confirmations
- Старый `calculate_adaptive_weighted_strength` сохранён как fallback
- ✅ Тест: trigger=15 + zone_OS_4h=8 → strength=23, mode=momentum

**DEV-203 — DecisionTrace:**
- Создан пакет `core/observability/` (`__init__.py` + `decision_trace.py`)
- Таблица `signal_drops` + 2 индекса в `core/db/subscription_manager.py`
- `bot/monitoring.py` — 6 gates покрыты
- `bot/core/bot.py` — `configure()` + `flush_periodically(30)`
- `web/dashboard_server.py` — endpoint `GET /api/dropped`
- ✅ `from core.observability.decision_trace import record_drop` — OK

### ✅ DEV-202 — confirmations[] в features_json (завершено)

**Изменения:**
- `bot/core/bot.py` — `self.confirmation_aggregator = ConfirmationAggregator(window_seconds=600)`
- `bot/loops/scan_loop.py` — после atr_change publish → `on_confirmation()` + zone OS/OB как доп. confirmation
- `bot/monitoring.py` — перед `register_trade_async` → `aggregate(symbol, side)` → `extra['confirmations']`, `extra['signal_mode']`, `extra['strength_breakdown']`; после регистрации → `clear(symbol, side)`
- Поток: ATR 1h cross UP + zone OS_1h → strength=25, mode=momentum, 2 confirmations в features_json
- ✅ Все 4 файла синтаксически чистые

### 🔄 Следующие задачи

- DEV-204: ML retrain weights (после 200+ сделок с confirmations[]) — ждёт накопления данных
- DEV-205: audit_mode shadow + audit_trades
- ARCH-112: аудит соответствия Кубу
- TR-003: TRADER валидация 20 SHADOW сделок
- **Немедленно:** можно запустить бот и наблюдать signal_drops + confirmations в БД

---

## [09.05.2026 ~14:00 UTC] Агент: Developer — DEV-203: DecisionTrace infrastructure

### ✅ Сделано

- Создан пакет `core/observability/` (`__init__.py` + `decision_trace.py`)
- Таблица `signal_drops` + 2 индекса добавлены в `core/db/subscription_manager.py` (строки 189–212)
- `bot/monitoring.py` — подключён `decision_trace`, покрыты 6 gates:
  1. `dedup` — дубликат сигнала в dedup window
  2. `sl_cooldown` — пара в SL-cooldown
  3. `btc_counter_trend` — BTC block mode + strength < threshold
  4. `watch_neutral` — action=WATCH/HOLD + direction=NEUTRAL
  5. `min_strength_register` — strength ниже порога регистрации
  6. `min_strength` — зарегистрирован но не actionable
- `bot/core/bot.py` — `_dt.configure()` + `asyncio.create_task(_dt.flush_periodically(30))` (строки 336–340)
- `web/dashboard_server.py` — endpoint `GET /api/dropped` (параметры: hours, limit, detail=1 для recent view)

### ⚠️ Синтаксис

Bash/PowerShell недоступны для запуска проверки. Все файлы проверены через Read — синтаксических ошибок нет. Рекомендуется запустить вручную:
```
python -c "from core.observability.decision_trace import record_drop; print('OK')"
```

---

## [09.05.2026 ~04:00 UTC] Агент: TRADER (Claude/Sonnet) — Спринт «Confirmation-Driven Architecture» утверждён

### ✅ Сделано (исследовательская сессия 8 backtest'ов)

**8 тестов на исторических данных (90 дней, 10 топ-пар, реальный OHLCV BingX):**

1. **R1** — DEEP_CASCADE на WT cross 3m+5m+15m: ОПРОВЕРГНУТ. DEEP_LONG=0 событий, SHORT avgR=−0.131. CASCADE_15m_LONG +0.641 (n=14), REVERSAL_4h_LONG +0.940 (n=11) — рабочие.
2. **R2** — Trend-only alignment без zone: НЕ работает. 1h_cross+4h_t UP = +0.372 (золото).
3. **R4** — Trend matrix 3⁵: alignment не даёт edge.
4. **R5** — Pivot×CASCADE: cascade SHORT (htf_wt1≥60 на 1h+4h) даёт avgR=+0.548 vs контроль −0.345 (9× лучше).
5. **R6** — ATR Trend Change cascade (бычий): 5m→4h 100% покрытие, lead 22.5h. 1h_LONG +0.281 (n=733).
6. **R7** — ATR Change в медведь: ОБЕ стороны positive (LONG +0.034..+0.511, SHORT +0.075..+0.588). Старшие ТФ доминируют.
7. **R8** — Финал, 90 дней: 1h_LONG +0.281, 4h_SHORT +0.287, 1d_LONG/SHORT −0.378/−0.489 (НЕ работает).
   - Stability: 1h_LONG positive 7/7 двухнедельных окон.
   - Zone OS confluence: 1h_LONG в zone=OS → avgR=+0.701 vs +0.273 без zone (Δ=+0.428).
   - Cascade 15m predecessor: Δ=+0.014..+0.148 (слабо).

### 🎯 ПРИНЯТО архитектурное решение

**Confirmation-Driven Architecture (ЗАКОН: чем больше подтверждений — тем лучше сигнал).**

- `strength = base_trigger_weight + Σ confirmation.weight × confidence` (вместо хардкод формулы)
- НЕТ regime gate. Бот не молчит.
- 1h ATR change = universal trigger (вес 15)
- 4h ATR change = премиум trigger (вес 18)
- 15m ATR change = entry trigger (вес 8)
- 1d ATR change НЕ использовать как trigger (avgR=−0.4)
- 16+ Confirmation типов: zone/cascade/WT/SMC/pivot/volume/divergence

### 📋 Спринт DEV-199..205 + ARCH-112 + TR-003 (09.05–23.05)

**Документация:**
- TASKS.md — добавлен заголовок спринта + 7 задач
- docs/TASKS_DETAILS.md — полные спецификации DEV-199..205 + ARCH-112 + TR-003
- DISCUSSION.md — запись 09.05 с обоснованием
- Скрипты исследований: `e:\tmp\R1..R8_*.py`

**Acceptance criteria спринта:**
1. DEV-199: за 24h после рестарта в БД события atr_change_15m/1h/4h
2. DEV-200: ConfirmationRegistry с 22+ типами + pytest
3. DEV-201: signal_mode разнообразный (cascade/reversal/momentum)
4. DEV-202: 100% новых сделок имеют features_json.confirmations[]
5. DEV-203: signal_drops таблица + дашборд /dropped
6. Регрессия: 7 дней без падения avgR ниже −0.437
7. Прогресс: avgR за 14 дней → ≥ −0.10

### 🔄 Следующая сессия

- DEV-199 первым (фундамент): `core/signals/atr_change_detector.py` + EventBus publish
- DEV-200 параллельно: `core/confirmations/registry.py` + dataclass + pytest
- DEV-203 параллельно (Phase 0 Stabilization): DecisionTrace в 14 gates

### ❌ Удалено из плана (опровергнуто данными)

- DEEP_CASCADE с 3m WT cross
- Adaptive entry TF от regime
- 1d direction filter
- atr_change_1d как trigger
- Cascade-фильтр (требовать 15m predecessor) как обязательный

---

## [05.05.2026 ~10:00 UTC] Агент: DEV (Claude) — Sideways Mode (RANGE параллельный режим)

### ✅ Сделано

**Sideways Mode — параллельный режим для боковика:**
- Диагностика: avgR=-0.4 из-за RANGE рынка с сер. апреля. Бэктест выявил wt_os45 на 30m avgR=+0.184, n=584
- Реализованы 5 файлов:

1. `core/signals/signal_models.py` — добавлен `SignalType.WT_SIDEWAYS = "wt_sideways"`
2. `core/context/pair_context.py` — добавлены поля `sideways_bars: int = 0` и `sideways_mode_active: bool = False` в `PairState`; обработчик `REGIME_UPDATED` теперь инкрементирует/сбрасывает счётчик и ставит флаг при `≥ min_sideways_bars` (default=3) последовательных RANGE-циклов
3. `strategies/built_in/wt_sideways_strategy.py` — НОВЫЙ ФАЙЛ: `analyze_sideways(symbol, df_30m, min_strength)` → возвращает duck-typed recommendation с `signal_type=wt_sideways`, SL=ATR trendline factor=1.25, TP=2R
4. `bot/loops/scan_loop.py` — после REGIME_UPDATED: читает `sideways_mode_active`, фетчит 30m df, вызывает `analyze_sideways`, при сигнале — `asyncio.create_task(register_trade_async)`. Также передаёт `sideways_threshold` в REGIME_UPDATED event
5. `config.yaml` — добавлена секция `sideways_mode: {enabled, min_sideways_bars, timeframe, min_strength}`

### 📊 Проверено
- Счётчик: 3+ RANGE → active=True, TREND_UP → active=False (сброс в 0)
- `analyze_sideways` возвращает правильный объект с `signal_type=wt_sideways`
- Все файлы компилируются без ошибок

### 🔄 Следующие задачи
- Запустить бот и подождать 3+ цикла сканирования в RANGE режиме
- Проверить через БД: `SELECT signal_type, COUNT(*), AVG(R_multiple) FROM simulated_trades WHERE signal_type='wt_sideways' GROUP BY signal_type;`
- Убедиться что существующие стратегии продолжают работать нормально

---

## [05.05.2026 04:30 UTC] Агент: ARCH (Claude) — Полное подключение куба + баги EventBus + confluence

### ✅ Сделано

**EventBus — 5 новых событий:**
- `wt_extreme` prio=1 — WTExtremeDetector (новый класс в htf_detectors.py), wt1 < −80/+80, все 4 TF
- `smc_choch_detected` prio=1 — из bot._last_smc_snap[sym].last_choch, ключ (tf, direction)
- `smc_bos_detected` prio=2 — из bot._last_smc_snap[sym].last_bos, ключ (tf, direction)
- `fvg_touch` prio=2 — bull/bear_fvg_active, дедупликация per-FVG, фильтр нулевых FVG
- `regime_change` prio=3 — bot._prev_regimes[sym] diff per-symbol
- `volume_spike` → PairContextBus.VOLUME_SPIKE (рядом с ANOMALY_DETECTED)

**Критический баг EventBus — исправлен:**
- `_in_queue` был set → стал dict (symbol → priority)
- Priority upgrade: новый сигнал с меньшим prio вытесняет старый (priority=999 = инвалид)
- Причина: wt_extreme (prio=1) терялся если пара уже в очереди с zone_enter_ob (prio=2)

**Мелкие фиксы:**
- Дедупликация BOS/CHoCH: ключ `(tf, direction)` вместо `(direction, None, None)`
- Нулевые FVG отфильтрованы: `top - bottom < 1e-8` → skip
- ARCH-09 legacy fallback лог: не логируется на INFO если chosen="legacy"

**Confluence разблокирован:**
- `analysis.confluence.enabled: false → true`
- Решение: BIAS фильтрует направление, избыточные фильтры скрывают данные
- Март: avgR=+0.64 (2591 сд), апрель: -0.42 (937 сд) — слом в боковике
- Наблюдаем 3-5 дней

### 📊 Ключевые данные по качеству входов

| signal_type | N | WR% | avgR |
|------------|---|-----|------|
| confluence | 3528 | 20.2% | +0.36 ✅ |
| wt_signal | 626 | 27.0% | +0.13 ✅ |
| pivot_reversal | 3099 | 16.3% | -0.42 ❌ |
| wt_b_signal | 163 | 15.3% | -0.35 ❌ |

Лучший последние 30 дней: divergence LONG avgR=+1.02. SHORT везде убыточен.

### 📁 Изменённые файлы
- `core/signals/htf_detectors.py` — +WTExtremeDetector
- `core/context/event_bus.py` — priority upgrade + _in_queue dict + 5 событий в EVENT_PRIORITY
- `bot/core/bot.py` — +WTExtremeDetector в _htf_detectors
- `bot/loops/scan_loop.py` — wt_extreme, regime_change, smc_bos/choch, fvg_touch, volume_spike, _last_smc_snap кеш
- `core/trading_intelligence.py` — legacy лог понижен
- `config.yaml` — confluence.enabled: true

### ⚠️ Наблюдение
- scan_loop > 70 сек (3 раза) — перегрузка API от EventBus fires
- Если повторится — рассмотреть cooldown_minutes: 30 → 45

### 🔄 Следующие задачи
- Через 3-5 дней: проверить confluence WR с BIAS
- SHORT стратегия требует пересмотра

---

## [04.05.2026 ночь] Агент: ARCH+DEV (Claude) — Куб Метатрона: Вариант А

### ✅ Сделано
- Слой 1 детекторы → EventBus: WT-B (prio=1), Pivot Reversal (prio=2), Divergence (prio=3), MTF Alert/Trend Signal (prio=4)
- trend_change все TF (15m/1h/4h/1d), wt_cross все TF, ZoneEntryDetector (новый класс)
- pivot_touch → PairContextBus + EventBus (trigger_loop)
- OTE rollback: 0.5→0.705, ote_use_trend_gate: true (C4 WR=23.7% -588R/90д)
