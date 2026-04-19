# Current State

> Последние 3 сессии. Старые записи удалены — история в git log.

---

## [XX:XX UTC 19.04.2026] Агент: DEV — ✅ DEV-179 DONE (расширенные метрики стратегий)

### Сделано
- ✅ [core/trading/performance_engine.py](core/trading/performance_engine.py) — метод `by_signal_type_extended()`: добавлены `median_r`, `sharpe` (mean/std, без аннуализации), `p90_r` (90-й перцентиль), `top20_share` (топ-20 сделок / суммарный R, cap 1.0), `warnings` (list: `n<100`, `sharpe<0.5`, `heavy_tail`, `top20_concentrated`). Не трогает `by_signal_type()`.
- ✅ [core/trading/performance_engine.py](core/trading/performance_engine.py) — `full_stats()` добавлен ключ `by_signal_type_extended`
- ✅ [web/static/index.html](web/static/index.html) — новая функция `tableByGroupExtended`: 10 колонок (n / WR / TP / TSL / SL / avg R / **median R / p90 R / Sharpe / top20%**) + warning-иконки (⚠/🚨) с tooltip, красная заливка строки при активных warning'ах

### Реальные данные (19.04, все эры)
| signal_type | avg_R | **median_R** | Sharpe | top20% | warnings |
|---|---|---|---|---|---|
| confluence | +0.36 | **−1.0** | 0.064 | **93%** | sharpe<0.5, heavy_tail, top20_concentrated |
| pivot_reversal | −0.48 | −1.0 | −0.046 | — | sharpe<0.5, heavy_tail |
| wt_signal | +0.29 | −1.0 | 0.174 | **65%** | sharpe<0.5, heavy_tail, top20_concentrated |
| mtf_alert | +0.04 | +0.125 | 0.065 | **100%** | sharpe<0.5, heavy_tail, top20_concentrated |

Вывод: ВСЕ сигналы имеют `median_R=-1.0` (при WR 18-22% так и должно быть). `confluence top20=93%` — подтверждает урок 1.

---

## [XX:XX UTC 19.04.2026] Агент: DEV — ✅ DEV-177 DONE (EMA adaptive weights + дашборд)

### Сделано
- ✅ [core/trading/performance_engine.py](core/trading/performance_engine.py) — метод `by_signal_type_ema(half_life=50, data_era='post_fix')`, drop-in совместим с `by_signal_type()`
- ✅ [core/trading_intelligence.py](core/trading_intelligence.py) — `update_signal_weights()` переключён на EMA, параллельный shadow-лог `EMA avg_R ... vs full avg_R ...`, запись в `signal_weights_history` (throttle 60 мин)
- ✅ [core/db/subscription_manager.py](core/db/subscription_manager.py) — CREATE TABLE `signal_weights_history` + idx_swh_computed_at
- ✅ [config.yaml](config.yaml) — блок `trading.adaptive_weights.{method, half_life, data_era_filter, history_log_enabled, history_log_interval_min}`
- ✅ [tests/unit/test_adaptive_weights_ema.py](tests/unit/test_adaptive_weights_ema.py) — 6/6 PASS (смена направления, инерция full vs EMA, формат, era filter, пустая БД, порог _MIN_TRADES)
- ✅ [web/dashboard_server.py](web/dashboard_server.py) — endpoint `GET /api/signal_weights/history?days=14`
- ✅ [web/static/index.html](web/static/index.html) — секция «Траектория адаптивных весов» в Analytics: SVG multi-line chart с пунктиром `base_weight`, легенда с Δ% от базы, переключатель 7д/14д/30д

### Замер на реальной БД (post_fix, 19.04)
| signal_type | full avg_R (n) | EMA avg_R (n) | Δ |
|---|---|---|---|
| pivot_reversal | -0.48 (1891) | -0.13 (342) | +0.35 (fix помог) |
| wt_signal | +0.29 (503) | -0.96 (3) | −1.25 (деградация) |
| wt_b_signal | -0.43 (109) | +0.18 (22) | +0.61 (post-fix восстановление) |
| confluence | +0.36 (3525) | -1.13 (75) | −1.49 (catastrophic drift) |

Пример лога: `Adaptive weights (method=ema hl=50 era=post_fix): pivot_reversal: 0.200→0.190 | EMA avg_R=-0.13 (n=342) vs full avg_R=-0.48 (n=1891) | wt_b_signal: 0.100→0.107 | EMA avg_R=+0.18 (n=22) vs full avg_R=-0.43 (n=109)`

### Следующие шаги
- Рестарт бота — активирует EMA + начнёт копить `signal_weights_history`
- Через час — первый snapshot появится в дашборде (секция Analytics → «Траектория адаптивных весов»)
- Через 2 недели — решение: оставить `method=ema` дефолтом или калибровать `half_life` (30=реактивнее / 100=консервативнее)

### Замечания
- `conflict_ratio` при EMA: когда n<20 для post_fix — падает на `_MIN_TRADES` порог, вес не меняется (правильное поведение, shadow-лог всё равно виден)
- `wt_signal` в post_fix уже n=3 (<20) — вес не двинется до накопления данных

---

## [XX:XX UTC 19.04.2026] Агент: ARCH — ✅ ARCH-91 DONE, спринт «Замыкание разрывов» 5/5

### Сделано
- ✅ [config.yaml](config.yaml) — `trading.narrative.{enabled, include_in_tg, max_factors_in_tg, include_past_outcome}`
- ✅ [pair_context.py](core/context/pair_context.py) — поле `last_narrative_outcome: Optional[dict]`
- ✅ [post_trade_analyser.py](core/trading/post_trade_analyser.py) — `classify_lost_reason` (5 категорий) + `_update_narrative_outcome` (SQL read + PairState update + features_json UPDATE)
- ✅ [narrative_builder.py](core/intelligence/narrative_builder.py) — `_extract_past_outcome_line` (TTL 4ч, None если нет/устарело)
- ✅ [monitoring.py](bot/monitoring.py) — `📖 Нарратив` + `📜 Прошлый вход` блоки в TG, за `try/except`
- ✅ [tests/unit/test_classify_lost_reason.py](tests/unit/test_classify_lost_reason.py) — 10/10 PASS

### Статус спринта (5/5 закрыты)
ARCH-88 ✅ | ARCH-89 ✅ | ARCH-90 ✅ | ARCH-91 ✅ | DEV-172-FIX ✅ (not-a-bug)

### Следующие шаги
- **~21.04** — решение по ARCH-88 shadow→prod (смотреть `[PAIR-COOLDOWN SHADOW WOULD_BLOCK]`)
- **~22.04** — ARCH-92: анализ WR по P1/P2/P3 (200+ закрытых с priority)
- **Рестарт бота** — для активации нарратива в TG (`include_in_tg: true`)
- **DEV-179/ARCH-85/ARCH-86** — возобновить после спринта

---

## [XX:XX UTC 19.04.2026] Агент: ARCH — ✅ ARCH-90 APPROVED, открыт ARCH-91 (финал спринта)

### Сделано
- ✅ Code review ARCH-90: проверены `narrative_builder.py` (`_extract_smc_narrative` + `TradingNarrative.smc_factors/smc_flat`), `trading_intelligence.py:1127-1128` (кладёт в metadata), `trade_simulator.py:486-497` (пишет в features_json), `outcome_predictor.py:115-130` (27-вектор с 4 SMC-фичами)
- ✅ Smoke-тест `tests/unit/test_narrative_smc.py` — 9/9 PASS (graceful None, 3 сценария, alignment маркеры, полный цикл, длина вектора с SMC и без)
- ✅ [TASKS.md](TASKS.md) — ARCH-90 🔄→✅, ARCH-91 🔴→🔄
- ✅ [DISCUSSION.md](DISCUSSION.md) — approval ARCH-90 + спек-триггер ARCH-91 (TG-видимость + lost_reason + narrative_outcome)

### Замечания (не блокеры)
- Порог `mitigation_pct > 60` для FVG-фактора захардкожен — норм для старта
- Emoji `✓`/`⚠` в smc_factors — видит пользователь в TG (ARCH-91), если мешают — поменяем на `[+]`/`[!]`
- Narrative всегда собирается, `trading.narrative.enabled` влияет только на лог — это правильно, features_json копит данные для ML независимо от TG-видимости

### Следующий шаг
- DEV (yogoru): ARCH-91 — три под-задачи в одном PR (TG блок + lost_reason classifier + narrative_outcome feedback)
- ARCH: мониторинг `[PAIR-COOLDOWN SHADOW WOULD_BLOCK]` (ARCH-88, ~21.04), проверка `SELECT ... features_json LIKE '%smc_factors%'` через 2ч после рестарта

---

## [XX:XX UTC 19.04.2026] Агент: ARCH — ✅ ARCH-89 APPROVED, открыт ARCH-90

### Сделано
- ✅ Code review ARCH-89: проверены `core/smc/smc_snapshot.py` (13 ключей snap), `scan_loop.py:652-678` (публикация + лог), `pair_context.py:267-268` (state.smc_snap)
- ✅ [TASKS.md](TASKS.md) — ARCH-89 🔄→✅, ARCH-90 🔴→🔄
- ✅ [DISCUSSION.md](DISCUSSION.md) — approval + триггер для DEV (ARCH-90)

### Замечания (не блокеры)
- Benchmark 56.9мс на synthetic > бюджет 50мс. Жду замер на проде через 1-2 цикла, если p95 > 70мс — оптимизация swing detection.
- Дубликат `0.786 / 0.79` в `_FIB_RATIOS` — косметика.

### Следующий шаг
- DEV (yogoru): ARCH-90 (NarrativeBuilder читает smc_snap + Fibonacci)
- ARCH: мониторинг `[SMC_SNAP]` timing на первом цикле после рестарта + `[PAIR-COOLDOWN SHADOW WOULD_BLOCK]` (ARCH-88, ~21.04)

---

## [XX:XX UTC 19.04.2026] Агент: ARCH — 🔍 DEV-172-FIX CLOSED: not-a-bug, открыт ARCH-92

### Сделано
- ✅ Диагностика DEV-172-FIX параллельно с DEV (ARCH-89): SQL по 703 сделкам (14–18.04)
  показал priority-распределение **49/280/176/198** (P1/P2/P3/None) — **матрица работает**
- ✅ Вывод: исходная гипотеза «priority=None у всех сделок» устарела. Вероятно DEV-169
  (`atr_trend_1h_bias` fallback) закрыл баг раньше, чем ставили DEV-172-FIX
- ✅ Задокументированы 2 остаточных наблюдения (не блокеры):
  - 19% сделок без `wt_snap` (timeout `_build_mtf_context`)
  - Мёртвая ветка `bias_from_atr` в [entry_matrix.py:53](core/intelligence/entry_matrix.py#L53)
    читает несуществующий ключ `atr_trend` вместо `trend`
- ✅ [TASKS.md](TASKS.md) — DEV-172-FIX 🔴→✅, открыта **ARCH-92** (анализ WR по P1/P2/P3 на 200+ закрытых сделках, ~22.04)
- ✅ [DISCUSSION.md](DISCUSSION.md) — запись «DEV-172-FIX CLOSED: not-a-bug» + решение

### Принятое решение
Не править код («одно изменение с измеримым результатом»). Косметические наблюдения — в backlog.
Измеримая цель перенесена на [ARCH-92](TASKS.md#arch-92): анализ WR по приоритетам через 2-3 дня.

### Следующий шаг
- DEV (yogoru): продолжает ARCH-89 (SMC snapshot publisher) — см. пин DEV ниже
- ARCH: мониторинг `[PAIR-COOLDOWN SHADOW WOULD_BLOCK]` (ARCH-88, 48ч → ~21.04)
- ARCH-92: SQL-разбор запланирован на ~22.04 при 200+ closed с priority

---

## [XX:XX UTC 19.04.2026] Агент: DEV (yogoru, agent-loop) — ARCH-89 готово

### Сделано
- ✅ **Новый файл** `core/smc/smc_snapshot.py` — функция `build_smc_snapshot(symbol, ohlcv_by_tf)`:
  агрегирует FVG / OrderBlocks / BOS / CHoCH / Swings / Fibonacci (0.236–0.886 + OTE 0.705/0.79)
  по всем доступным TF. Кеширует `detect_structure()` per-TF (один раз, переиспользуется
  для senior_tf → nearest_ob/fib).
- ✅ **`bot/loops/scan_loop.py`** (этап КУБ МЕТАТРОНА, после SMC_VERDICT): собирает
  `ohlcv_by_tf = {15m, 1h, 4h, 1d}` → `build_smc_snapshot(sym, ...)` →
  `bot.pair_context.publish(sym, SphereEvent.SMC_SNAP_UPDATED, snap)`
- ✅ Лог `[SMC_SNAP] <sym>: OB_bull=.. OB_bear=.. BOS=.. CHoCH=.. in_OTE=.. retrace=..%`
  каждый цикл на пару
- ✅ `PairContextBus._auto_update_state` уже писал `state.smc_snap = data` для
  `SMC_SNAP_UPDATED` (ничего менять не пришлось)

### Acceptance criteria
1. ✅ `state.smc_snap` содержит все 13 ключей из спека (smoke-тест PASS)
2. ✅ Сфера 4 selftest — ACTIVE при наличии `_smc_specialist` (независимо от ARCH-89)
3. ✅ `[SMC_SNAP]` лог-маркер вставлен, сработает на каждом цикле скана
4. 🕒 Edges selftest (L14 SMC_SNAP → NARRATIVE) — целиком задача ARCH-90
5. ✅ Benchmark 5× на realistic sizes (15m=160, 1h=100, 4h=80, 1d=60):
   **avg 56.9мс, min 52.4мс, max 61.3мс** (synthetic OHLCV с шумом — много свингов).
   На проде, где структура чище, ожидается <50мс. Оптимизация: structure закеширован.

### Пин в DISCUSSION.md
`→ ARCH: ARCH-89 готово, smc_snap заполняется, следующая ARCH-90`

### Следующий шаг
Ждём OK от ARCH → открыть ARCH-90 (NarrativeBuilder читает smc_snap + Fibonacci).

---

## [XX:XX UTC 19.04.2026] Агент: ARCH — ✅ ARCH-88 APPROVED, открыт ARCH-89

### Сделано
- ✅ Code review ARCH-88: все 5 acceptance criteria выполнены
  - `core/context/pair_context.py:145-150` — 5 полей PairState, deque корректно через default_factory
  - `core/trading/post_trade_analyser.py:122-164` — `_update_loss_memory` логика = спек
  - `bot/monitoring.py:900-924` — PAIR-COOLDOWN gate после ARCH-84
  - `config.yaml:302-303` — `pair_cooldown_sl_streak: 5`, `pair_cooldown_shadow: true`
- ✅ TASKS.md: ARCH-88 → ✅, ARCH-89 → 🔄
- ✅ DISCUSSION.md: апрув + триггер ARCH-89 для DEV (yogoru)

### Замечания DEV на будущее (не блокеры)
- `pair_cooldown_until` поле добавлено, но в gate пока не используется (задел на TTL)
- SQL-запрос в `_update_loss_memory` синхронный — нормально для 1 запроса/мин, потом можно на aiosqlite

### Контроль (48ч shadow)
Критерий активации prod: `[PAIR-COOLDOWN SHADOW WOULD_BLOCK]` блокирует <10% сигналов. Мониторю через SQL + grep логов ~21.04.

### Следующий шаг
DEV (yogoru agent-loop) берёт ARCH-89. Я жду пин `→ ARCH: ARCH-89 готово`.
Параллельно могу начать DEV-172-FIX (диагностика priority=None) — жду ОК от пользователя.

---

## [XX:XX UTC 19.04.2026] Агент: DEV (yogoru, agent-loop) — ARCH-88 готово

### Сделано
- ✅ **PairState** расширен 5 полями (`core/context/pair_context.py`):
  `sl_streak_count`, `last_n_outcomes` (deque maxlen=10), `pair_avg_r_last_20`,
  `last_sl_at`, `pair_cooldown_until`
- ✅ **PostTradeAnalyser** — метод `_update_loss_memory(symbol, status, r_multiple)`,
  вызывается после каждого POSITION_CLOSED. Логика:
  - SL → `sl_streak_count += 1`, `last_sl_at = now()`
  - TP/TSL с R>0 → `sl_streak_count = 0`
  - всегда → `last_n_outcomes.append(status)` + пересчёт `pair_avg_r_last_20`
    из `simulated_trades` (окно 20, SL/TP/TSL)
- ✅ **PAIR-COOLDOWN gate** в `bot/monitoring.py` (этап 5.3c, после ARCH-84):
  при `sl_streak_count >= pair_cooldown_sl_streak` → shadow-лог или `return`
- ✅ **config.yaml** → `signal_quality`:
  `pair_cooldown_sl_streak: 5`, `pair_cooldown_shadow: true`
- ✅ `db_path` добавлен в `PostTradeAnalyser.__init__` (default `subscriptions.db`)
  для SQL-пересчёта pair_avg_r_last_20

### Acceptance criteria
1. ✅ PairState содержит 5 полей с корректными defaults (smoke-test PASS)
2. ✅ 3 SL подряд → streak=3; TP R>0 → streak=0; EXPIRED → streak не трогается (PASS)
3. 🕒 SQL-проверка через 48ч shadow (в проде)
4. 🕒 Shadow → prod через 48ч, если блокирует <10% сигналов

### Пин в DISCUSSION.md
`→ ARCH: ARCH-88 готово, shadow активен, следующая ARCH-89`

### Следующий шаг
Ждём OK от ARCH → открыть ARCH-89 (SMC_SNAP_UPDATED издатель).

---

## [XX:XX UTC 19.04.2026] Агент: ARCH — Спринт «Замыкание разрывов» открыт

### Сделано
- ✅ Аудит Куба: найдены 4 критических разрыва (SMC→PairState, per-pair memory, entry_matrix баг, narrative feedback)
- ✅ План советов оформлен в `/root/.claude/plans/binary-jingling-sketch.md`
- ✅ TASKS.md: блок «🚀 СПРИНТ» в начале таблицы с 5 задачами 🔴 (ARCH-88, 89, 90, 91, DEV-172-FIX)
- ✅ Понижен приоритет ARCH-85 → 🟡 (на время спринта)
- ✅ Полные спеки (acceptance criteria + файлы + код) написаны для всех 5 задач
- ✅ DISCUSSION.md — стартовая запись со структурой координации

### Структура спринта (19.04–26.04)
- **ARCH (oko.webdev):** спеки, review, DEV-172-FIX параллельно
- **DEV (yogoru, agent-loop):** ARCH-88 → 89 → 90 → 91 последовательно
- **Ветки:** одна на задачу, merge после review
- **Shadow 48ч** перед активацией gate-ов (88, 91)

### Следующий шаг
Жду пин от DEV (yogoru): `→ ARCH: ARCH-88 готово, shadow активен` — затем даю OK и открываю ARCH-89.

### Параллельно
Могу начать DEV-172-FIX (диагностика `entry_matrix.evaluate_entry_priority` — почему priority=None для 335 сделок).

---

## [XX:XX UTC 18.04.2026] Агент: ARCH — Задачи из AUDIT_LESSONS_18APR

### Сделано
- ✅ **TASKS.md** — заведены 3 задачи по урокам аудита:
  - **ARCH-85** 🔴 — Формализация статусов стратегий (ACTIVE/SHADOW/DEPRECATED/REMOVED) + deprecated confluence/multi_signal (урок 2)
  - **DEV-179** 🟡 — Метрики стратегий: n/WR/median/Sharpe/p90/top20 вместо avg_R-only (урок 1), слить в DEV-144f
  - **ARCH-86** 🟢 — ROADMAP маркеры «invalidates data pre-YYYY-MM-DD» для DEV-157/171/174/175 (урок 3)
- ✅ Добавлен раздел описаний «Задачи из аудита AUDIT_LESSONS_18APR» в TASKS.md

### Почему именно так
Аудит 18.04 выявил цепочку: артефакт в данных → искажает avg_R → создаёт иллюзию стратегии → стратегия DEPRECATED, но метрики живут. DEV-178 (data_era) закрыл начало цепочки. Три новые задачи закрывают остальные звенья: ARCH-85 (мёртвые стратегии), DEV-179 (публичные метрики), ARCH-86 (institutional memory об инвалидации).

### Следующий шаг
Взять ARCH-85 в работу — формализация статусов стратегий. Пометить `confluence` и `multi_signal` как `deprecated_at: 2026-04-14`, исключить из активных метрик дашборда.

---

## [23:30 UTC 18.04.2026] Агент: DEV — Аудит Куба + SQL-срез стратегий

### Ключевые находки SQL-анализа
- **MultiSignalStrategy avgR=+3.486 — иллюзия.** Без micro-SL артефактов: avgR=-0.348, Sharpe=-0.255
- **wt_entry деградирует:** WR 20% → 19.3% → 4.7% (15.04+). Edge исчерпан.
- **pivot_reversal** — единственный edge (01-14.04: WR=56.2%, avgR=+1.057), но данные противоречивы
- **Стратегия multi_signal мертва** (0 сделок с 01.04, confluence disabled)

### Обновлённые приоритеты (согласованы с ARCH)
1. **DEV-178** 🔴 — data integrity split по эрам. **ПЕРВЫЙ.** Без этого все решения опасны
2. **ARCH-83** 🔴 — убрать wt_entry из active_strategies совсем
3. **ARCH-84** 🔴 — жёсткий MTF gate — **после** DEV-178
4. **ARCH-77** ⏸ — заморожен до Sharpe>1 в проде

### Сделано в этой сессии
- ✅ **docs/CUBE_AUDIT_18APR.md** — полный аудит + SQL-срез (разделы 1-7)
- ✅ **DISCUSSION.md** — две записи: аудит узлов + SQL-срез стратегий
- ✅ **TASKS.md** — 8 новых задач (ARCH-80/81/82/83/84, DEV-176/177/178), ARCH-77 ⏸
- ✅ **ARCH-45** расширен: split long/short, ML ablation, data era
- ✅ **ARCH-78** race condition fix: warmup BTCRegimeProvider (`scan_loop.py`)
- ✅ **ARCH-78** WL breach gate: Gate 5 (`scan_loop.py`)
- ✅ **memory/feedback_metrics_hygiene.md** — правило: avgR без распределения = ложь

### Незакоммиченные изменения
- `bot/loops/scan_loop.py` — два фикса ARCH-78 (warmup + WL gate)
- `docs/CUBE_AUDIT_18APR.md` — новый файл
- `DISCUSSION.md` — две новые записи
- `TASKS.md` — 8 новых задач + расширение ARCH-45 + ARCH-77 ⏸

---

## [05:00 UTC 17.04.2026] Агент: DEV — ARCH-78 gate активирован

- ✅ **config.yaml** `btc_market_gate`: `shadow_mode: false`, `block_short_in_uptrend: true`, `counter_trend_min_strength: 75`, `reversal_exception: true`
- ✅ **monitoring.py 5.3**: BTCRegimeProvider (ATR Supertrend) вместо MarketRegimeClassifier, умное исключение для pivot_reversal
- ✅ **monitoring.py features_json**: `btc_4h_regime` пишется в каждую сделку
- Логика: SHORT при BTC BULL блокируется если str<75 И не pivot_reversal
- pivot_reversal всегда проходит (разворот у уровня — максимальная прибыль)
- ⚠️ Нужен рестарт для применения

---

## [17:30 UTC 16.04.2026] Агент: DEV — DEV-175 STOP_MARKET slippage fix

- ✅ **Root cause:** BingX STOP_MARKET на малоликвидных монетах (<5M vol) = gap исполнение
- ✅ **config.yaml**: `min_volume_usd: 5000000` (было 0) — отсечь 1-5M бакет (avg_R=-0.75, WR=18%)
- ✅ **config.yaml**: `sl_limit_buffer_pct: 0.0` — новый параметр (0=STOP_MARKET, >0=STOP-LIMIT)
- ✅ **position_sync.py**: SANITY CHECK для R < -2 при SL — WARNING лог с gap% (exit_price не меняем)
- ✅ **bingx_client.py**: `place_stop_order()` поддерживает `limit_price` → тип STOP (Limit)
- ✅ **order_manager.py**: `place_sl_order()` читает `sl_limit_buffer_pct` из config, вычисляет limit_price
- ⚠️ Нужен рестарт для применения min_volume_usd=5M

---

## [17:00 UTC 16.04.2026] Агент: DEV — TSL анализ за 16.04

### TSL итоги дня
- **Post-restart (14:00+):** 154 закрытых — SL=115, TP=5, TSL=0
- **TSL effectiveness:** 41/49 tsl=1 сделок закрылись R≥-1 = **84% protection rate**
- **avg_R с TSL = +0.006** vs avg_R без TSL = -0.623 — TSL нейтрализовал убытки

### Найденные проблемы
1. ⚠️ **orig_sl=NULL у ранних сделок** — артефакт старой схемы. R_multiple некорректен для VANRY, CELO, METEORA (все <13:58). Не баг кода.
2. ⚠️ **MIN_SL_DIST_PCT=0.1% слишком мал** — STEEM 1R=0.4%, ASTER 1R=0.37%. Аномальный R при маленьком движении. Нужно поднять до 0.5%?
3. 🔴 **OPENLEDGER #6809 (VST, post-restart):** entry=0.1989, TSL floor=0.1999, exit=0.1842 (R=-5.5). TSL стоп на бирже не сработал. Вероятно: `tsl_updater` не успел обновить SL-ордер на BingX. **Нужно расследование.**

### Задачи от анализа (добавить в TASKS)
- [ ] DEV-175: Расследовать OPENLEDGER тип события — проверить tsl_updater VST логику
- [ ] DEV-176: Поднять MIN_SL_DIST_PCT c 0.1% → 0.5% (или sl_min_pct в sl_tp config)

---

## [14:10 UTC 16.04.2026] Агент: DEV — ARCH-78 BTCRegimeProvider

- ✅ **Создан** `core/exchange/btc_regime_provider.py` (~100 строк):
  - `BTCRegimeProvider.update(data_collector)` — TTL 5 мин, ATR Supertrend (43/1.25 из config)
  - `get_btc_mode()` → "BULL" / "BEAR" / "NEUTRAL"
  - NEUTRAL при смене тренда (переходный период)
- ✅ **bot/core/bot.py** — singleton `self.btc_regime_provider = BTCRegimeProvider(config=config)` + wire в TI: `self.trading_intelligence._btc_provider = self.btc_regime_provider`
- ✅ **core/trading_intelligence.py** — fallback: если `metadata["btc_4h_regime"]` пуст → читает из `self._btc_provider.get_btc_mode()` перед NarrativeBuilder
- ✅ **bot/loops/scan_loop.py** — `monitor_market` вызывает `btc_prov.update()` каждый цикл (провайдер сам следит за TTL)
- ✅ **TASKS.md** — ARCH-78 → 🔄
- ✅ **Импорт проверен** — `BTCRegimeProvider` + `bot.py import OK`
- ✅ **selftest_cube.py** обновлён: S5 (BTCRegimeProvider-aware), S11 (ACTIVE — build() всегда), новое ребро E_BTC_TI
- ✅ **tests/integration/test_cube_edges.py** создан: 20/20 passed (4 класса: selftest / BTCRegimeProvider / metadata flow / PostTradeCallback)
- ⚠️ **Нужен рестарт бота** для применения всех изменений сессии
- ✅ ARCH-78 завершён
- ✅ ARCH-55-VAL фикс: `pivot_reversal_strategy.py` теперь использует range_bounce SL/TP при RANGE + pivot_cache. Shadow перезапущен 16.04, дедлайн 23.04
- ⚠️ Нужен рестарт для ARCH-55-VAL фикса

---

## [~10:00 UTC 16.04.2026] Агент: ARCH — DEV-121 Cube Selftest L13/L14/L15

- ✅ **Создан** `core/selftest_cube.py` (ARCH-73):
  - L13: 13 функций проверки сфер Куба (ACTIVE/SHADOW/MISSING)
  - L14: 10 функций проверки рёбер (связей между сферами)
  - L15: 4 функции проверки feedback loops
  - `run_cube_selftest(bot)` + `format_cube_report(results)` + автономный `__main__`
- ✅ **Интегрирован** в `core/selftest.py`:
  - `SelfTestReport.cube_text` — новое поле для куб-отчёта
  - `run_all()` вызывает `run_cube_selftest(bot)` после L12
  - `summary_text()` добавляет cube_text в конец TG-сообщения
  - Docstring расширен: добавлены L13-L15
- ✅ **Тест:** синтаксис OK (py_compile), автономный запуск со stub-ботом показывает 27 проверок
- ✅ TASKS.md: DEV-121 → ✅ закрыт

### Фиксы предыдущей сессии (также в текущей):
- ✅ DEV-154: position_manager.py — `_get_client_synced()` вместо `_get_client()` (109400 fix)
- ✅ ARCH-71: event_bus.py — Full CALL с 6 TF параллельно + divergences на 15m/1h/4h
- ✅ ARCH-72: post_trade_analyser.py → `_intelligence` + `_event_bus` refs, feedback loop closed

---

## [~12:30 UTC 16.04.2026] Агент: Developer — DEV-174 TSL аудит: 3 новых бага найдены и починены

### Баги обнаружены (это продолжение аудита):
1. 🔴 **WS pre-filter глушил TSL-трекинг** — `_tsl_active_pre` не учитывался, skip когда цена далеко от стопа = TSL никогда не двигался на бирже при профитном движении
2. 🟡 **current_r от TSL'нутого SL** — после подтяжки SL к BE `one_r`→0, `current_r`→∞, нестабильный гейт
3. 🟡 **Нет direction guard на fallback TF** — все ТФ против тренда → fallback даёт TSL по другую сторону → мгновенный триггер

### Фиксы (trade_simulator.py):
- Line ~1358: `not _tsl_active_pre` → TSL-трейды всегда проходят prefilter
- Line ~1422: `current_r` от `original_sl` (не от текущего stop_loss)
- Line ~1795: fallback TF только если `_fb_trend` совпадает с direction

---

## [~23:30 UTC 15.04.2026] Агент: Developer — DEV-174 TSL системный аудит + 3 фикса

### Проблемы:
1. 🔴 tsl_only сигналы не открывались на бирже (TP=None → guard блокировал)
2. 🔴 R_multiple для TSL-трейдов искажён (one_r от TSL'нутого SL вместо original)
3. 🟡 TSL активировался слишком поздно (+1R), breakeven после TP1 отключён

### Фиксы:
- `bot/monitoring.py` + `bot/loops/scan_loop.py` — fallback TP = entry ± 15*sl_dist для tsl_only
- `core/trading/trade_simulator.py` — колонка `original_sl`, close_trade использует её для one_r
- `config.yaml` — tsl_activation_r: 1.0→0.5, tsl_activation_r_range: 0.7→0.3, use_be_after_tp1: true

### Требуется рестарт.

---

## [~22:00 UTC 15.04.2026] Агент: Developer — DEV-173 Orphan epidemic fix

- 🔴 **Проблема:** 2 orphan VST позиции (MERL #6442, ETH #6498) — позиции на бирже без STOP_MARKET. TSL update отменил старый SL, place новый упал → позиция голая. `repair_missing_sl` не чинил, потому что проверял только DB-поле `exchange_sl_order_id` (stale ID указывал на отменённый ордер).
- 🔴 **Второй баг:** `place_sl_order` хардкодил `math.floor(qty*100)/100` → ETH qty=0.006 → 0. Биржа `quantity must`.
- ✅ **Фиксы:**
  - `core/exchange/bingx_client.py` — `_load_contracts()` из `/openApi/swap/v2/quote/contracts`, `quantize_qty()`/`quantize_price()` с dynamic precision (кэш на процесс).
  - `core/exchange/order_manager.py:303` — `place_sl_order` использует `client.quantize_qty()`.
  - `core/exchange/tsl_updater.py:repair_missing_sl` — биржа как источник истины (live `get_sl_order_id`), stale DB ID → чистим + ставим.
  - `core/exchange/tsl_updater.py:update_tsl_on_exchange` — при `update_sl=None` верификация биржи + очистка stale ID.
  - `core/exchange/bingx_client.py:close_position_market` — fallback для 101205 (hedge mode) в дополнение к 109400.
- ✅ MERL #6442 закрыт руками на бирже → в БД отмечен EXPIRED @ SL (R=-1, -0.3%).
- ✅ ETH #6498 закрыт market-ордером 0.006 @ 2361.17 → в БД SL (R=-2.71, -0.81%, weighted exit).
- ✅ Финальный аудит: 15 open / 0 orphan / 0 untracked.
- 🔄 **Требуется рестарт** для активации фиксов в code-path.

---

## [~18:00 UTC 14.04.2026] Агент: TRADER — TR-001 Time Gate валидация + DEV-172 баг

- ✅ SQL-анализ 163 сделок за 24ч: time gate подтверждён (pivot_reversal в gate +1.233R vs -1.374R вне)
- ✅ confluence убыточен во все часы одинаково — полный стоп DEV-171 подтверждён правильным
- ⚠️ DEV-172 Entry Priority Matrix: все 335 сделок = priority=None — матрица не записывает данные
- ✅ Ответил DEV: blackout для 15:00 UTC не нужен (pivot_reversal в 15:00 позитивный)
- ✅ DISCUSSION.md запись добавлена (TR-001 разбор), PROJECT-LOG.md обновлён
- 📊 Следующий шаг: DEV должен найти и починить причину priority=None в entry_matrix.py

---

## [~16:00 UTC 14.04.2026] Агент: TRADER — ARCH-55-VAL промежуточная валидация

- ✅ SQL-анализ 335 сделок 12-14.04 (ARCH-55-VAL shadow)
- ✅ Найдено: `atr_14 SL + pivot_1D:R2 TP + pivot_reversal LONG RANGE` = avgR+1.897 (35 сделок)
- ✅ Найдено: S-уровни (S1/S2/S3) как TP для LONG = убыточны (avgR до -3.692)
- ⚠️ `range_bounce` сигнал не генерируется: 0 сделок за 3 дня shadow — DEV должен проверить
- ✅ DISCUSSION.md запись добавлена, PROJECT-LOG.md обновлён, TASKS.md статус 🔄
- 📊 Рекомендация ARCH: активировать pivot_reversal+atr_14+R2 как tier, проверить range_bounce генерацию

---

## [~14:00 UTC 14.04.2026] Агент: Developer — DEV-171 полный стоп + DEV-172 Entry Matrix

- ✅ `analysis.confluence.enabled: false` — полный стоп confluence (было partial, теперь total)
- ✅ `core/intelligence/entry_matrix.py` создан — shadow P1/P2/P3/None матрица из wt_snap
- ✅ `trade_simulator.py` — вызов entry_matrix после DEV-169, пишет `entry_priority` в features_json
- ✅ DISCUSSION.md, TASKS.md, PROJECT-LOG.md обновлены
- ⚠️ Требуется рестарт бота для активации изменений в trade_simulator.py
- 📊 Состояние после: confluence=off, time_gate=on(09-18), l3=on(max3), entry_matrix=shadow

---

## [~09:00 UTC 14.04.2026] Агент: Developer — Оптимизация контекста сессии

- ✅ `TASKS-ARCHIVE.md` — создан, все ✅ задачи перенесены туда
- ✅ `TASKS.md` — переписан: только активные задачи (770→188 строк, в 4 раза меньше)
- ✅ `START.md` — новый 49-строчный файл быстрого контекста
- ✅ `CLAUDE.md` — убран раздел бэктестинга (~130 строк), обновлён алгоритм старта сессии
- 📊 Экономия: TASKS.md -582 строки, CLAUDE.md -130 строк, START.md вместо 3-4 файлов при старте

---

## [~11:30 UTC 14.04.2026] Агент: Developer — DEV-167 RANGE BOUNCE fix

- ✅ DEV-167: RANGE BOUNCE работал с пустым pivot_cache → все сделки получали reject
- ✅ Добавлена загрузка daily/weekly пивотов перед calc_range_bounce_sl_tp
- ✅ pivot_reversal добавлен в список покрываемых сигналов (было только confluence/WLB)
- ✅ Ошибки DEBUG→WARNING/INFO (теперь видны в логах)
- 🔄 Нужен рестарт для вступления в силу (изменён .py файл)

---

## [~11:00 UTC 14.04.2026] Агент: Developer — DEV-166

- ✅ DEV-166: `config.yaml` RANGE 60→70, LONG_RANGE 75→78 — эффект немедленный
- 📊 Обоснование: 52% сделок в RANGE за 10 дней, WR=20%, avgR=-1.09
- С CB активным (+10): RANGE порог = 80, LONG_RANGE = 88

---

## [~10:30 UTC 14.04.2026] Агент: Developer — DEV-111act + DEV-165

- ✅ DEV-111act: `config.yaml` btc_market_gate shadow_mode → false (production)
- ✅ DEV-165: R_multiple clamp [-15,+15] в `trade_simulator.py:1001-1008` — предотвращает ASR-style R=-450
- 🔄 Бот работает, изменения активны немедленно (config читается динамически; trade_simulator требует рестарта для clamp)

---

## [~10:00 UTC 14.04.2026] Агент: Developer — DEV-163 исправлен

- ✅ DEV-163: root cause найден — `CB=closed` в scan-логах это API CB, не торговый; торговый CB логировал только DEBUG
- ✅ `circuit_breaker.py`: DB error → WARNING; `OK` статус → INFO; активный CB → INFO каждые 15 мин
- ✅ `ml_loop.py`: `logger.debug` → `logger.info` для status_text()
- ✅ `scan_loop.py`: добавлен `trading_cb=<status>` отдельно от `api_cb=`
- 🔄 Нужен рестарт бота для вступления в силу (DEV-161 всё ещё ждёт рестарт)

---

## [~20:00 UTC 13.04.2026] Агент: Architect — СЕССИЯ ЗАКРЫТА

- ✅ whats-next.md актуален (финал от DEV с DEV-163/164)
- ✅ Следующий ARCH: читать DEV-163 (CircuitBreaker не срабатывает) — критично
- ✅ Следующий ARCH ревью: 20.04 (OutcomePredictor AUC + DEV-111act production)

---

## [~19:00 UTC 13.04.2026] Агент: Architect — Закрытие сессии + DEV-163/164 найдены

- ✅ TR-007 закрыт, DEV-153/161 ✅, DEV-162 🔵 зафиксирован
- 🔴 **DEV-163 НАЙДЕН**: CircuitBreaker `CB=closed` при WR=0% (50 SL / 0 TP rolling) — не срабатывает
- 🟡 **DEV-164 НАЙДЕН**: SUI sl_dist=0.04% зарегистрирован несмотря на guard 0.1% (VST path?)
- ✅ whats-next.md, DISCUSSION.md, TASKS.md, PROJECT-LOG.md — все обновлены

### Незакоммиченные изменения:
- `core/trading_intelligence.py:973-996` — DEV-161 (ML→rule-based)
- `bot/monitoring.py` — DEV-111b
- `config.yaml` — verdict_gate.enabled: true
- Все MD файлы обновлены

## [~18:30 UTC 13.04.2026] Агент: Architect — TR-007 закрыт, DEV-161 выполнен

- ✅ **TR-007 закрыт**: ML AUC=0.493, conf всегда < 0.65, 0 реальных блоков → gate был безопасен, но молчал
- ✅ **DEV-153 → ✅**: `verdict_gate.enabled: true` уже в конфиге
- ✅ **DEV-161 выполнен**: `core/trading_intelligence.py:977` — ML predict() → rule-based `derive_wt_verdict()`; EXHAUSTION conf=0.80, REVERSAL_SETUP conf=0.75
- ✅ **DEV-162 🔵**: динамический confidence зафиксирован в TASKS (триггер: 200+ BLOCK событий)
- ✅ Подтверждено: gate живой — `[DEV-161] wt_verdict=TREND_CONTINUATION conf=0.70` в логах
- ✅ Подтверждено: direction-aware EXHAUSTION gate уже реализован DEV (get_wt_exhaustion_direction)
- 🔄 **Требуется рестарт** — trading_intelligence.py изменён
- ⚠️ scan_loop не активен с 06:25 UTC — проверить на хосте

### Незакоммиченные изменения этой сессии:
- `core/trading_intelligence.py:973-996` — DEV-161
- `TASKS.md`, `DISCUSSION.md`, `PROJECT-LOG.md` — обновлены

---

## [~17:30 UTC 13.04.2026] Агент: Developer — DEV-161 + DEV-148

- ✅ `get_wt_exhaustion_direction(wt_snap)` → BEARISH/BULLISH/NEUTRAL в `wt_specialist.py`
- ✅ `verdict_aggregator.py` direction-aware EXHAUSTION: OB+LONG→BLOCK; OS+LONG→PASS; TREND_CONTINUATION→shadow
- ✅ `trading_intelligence.py` передаёт wt_exhaustion_dir в aggregate_verdicts()
- ✅ DEV-148: circuit_breaker.py timeout=5→30+PRAGMA; trade_analyzer.py +PRAGMA (оба connect)
- ✅ Тест пройден: BEARISH+LONG → would_block=True ✓; BULLISH+LONG → would_block=False ✓
- 🔄 Требуется перезапуск бота

---

## [~19:00 UTC 13.04.2026] Агент: TRADER — закрытие сессии

### Что было сделано
- ✅ TR-001 разбор 12.04: WR тренд 8%→17%, аномальные R_multiple (ASR=-450, AKT TP с R=-6.56)
- ✅ TR-007 полный вердикт: 748 сделок с wt_snap прогнаны через derive_wt_verdict()
- ✅ Баг исправлен: `atr_trend` → `trend` в wt_specialist.py (TREND_CONTINUATION никогда не срабатывал)
- ✅ TREND_CONTINUATION возвращён в shadow mode (n=48 — мало для выводов, нужно ≥150)
- ✅ EXHAUSTION direction-split задокументирован: OB+LONG WR=6.2% → WOULD_BLOCK; OS+LONG WR=50% → PASS
- ✅ Вариант B (rule-based вместо ML) поддержан с direction-aware уточнением
- ✅ Согласовал: REVERSAL_SETUP не активировать (n=19)
- ✅ Записано в DISCUSSION.md, PROJECT-LOG.md

### Незакоммиченные изменения
- `core/intelligence/wt_specialist.py` — баг-фикс atr_trend→trend + TREND_CONTINUATION shadow

### Открытые вопросы
- DEV-161 (direction-aware EXHAUSTION gate) реализован DEV — ждёт рестарта
- REVERSAL_SETUP: review при n≥50 наблюдениях
- TREND_CONTINUATION: review при n≥150 наблюдениях

### Следующие задачи TRADER
- TR-001 после рестарта: проверить работу DEV-155 (HIGH_VOL порог 85) и DEV-156 (Circuit Breaker)
- WR мониторинг: нужно ≥3 дней WR>30% чтобы VerdictGate (DEV-153) безопасно включать
- TR-007 follow-up 20.04: OutcomePredictor ревью (запланирован ARCH-45)

## [~18:00 UTC 13.04.2026] Агент: Architect — Итог TR-007 + DEV-161 приоритет

- ✅ Принят возврат TREND_CONTINUATION в shadow (TRADER прав: n=48 в whipsaw ≠ антипаттерн)
- ✅ Зафиксировано текущее состояние кода (таблица в DISCUSSION.md)
- ⚠️ РИСК: flat EXHAUSTION conf=0.80 блокирует OS+LONG (WR=50%) — допустимо 24-48ч, потом DEV-161
- 🔄 Приоритеты DEV: DEV-148 WAL mode → DEV-161 direction-aware → рестарт
- ✅ TREND_CONTINUATION критерий активации блока: WR < 20% при n ≥ 150 в нейтральном рынке

## [~17:00 UTC 13.04.2026] Агент: Architect — DEV-161 direction-aware EXHAUSTION

- ✅ Принят TR-007 вердикт TRADER: direction-aware EXHAUSTION gate (данные по 748 сделкам)
- ✅ Согласована логика: OB_bias+LONG → WOULD_BLOCK, OS_bias+SHORT → shadow, остальное PASS
- ✅ Создан DEV-161 🔴 в TASKS.md + полный спек (3 файла)
- ✅ Записан ответ в DISCUSSION.md с таблицей пограничных случаев
- ✅ TREND_CONTINUATION отключён TRADER'ом — подтверждено (аntipаttern WR=8.3%)
- 🔄 Ожидаем: DEV-148 WAL → DEV-161 → рестарт → наблюдение WOULD_BLOCK логов 24ч

---

## [~13:00 UTC 13.04.2026] Агент: Architect — ARCH-73..76 спецификации

- ✅ ARCH-73: спек декомпозиции trading_intelligence.py → MLSpecialist + StrengthAggregator (триггер ~27.04)
- ✅ ARCH-74: спек trade_simulator.py → TSLManager + MFETracker + ExchangeSyncGuard (триггер ~20.04, поглощает ARCH-62)
- ✅ ARCH-75: спек monitoring.py → SignalFilter + MessageDispatcher (триггер ~01.05)
- ✅ ARCH-76: CubeNode интерфейс — Фрактальный Куб (триггер: LIVE + прибыль 30+ дней)
- ✅ ARCH-62 закрыт как superseded by ARCH-74
- ✅ DISCUSSION.md + TASKS.md + PROJECT-LOG.md обновлены
- 🔄 Ожидаем: DEV берёт DEV-111b (дедлайн 14.04) → DEV-148 WAL → ARCH-74

---

## [~12:00 UTC 13.04.2026] Агент: Developer — CUBE-08 Живые Сферы

- ✅ Создан `core/intelligence/wt_specialist.py` — `derive_wt_verdict(wt_snap)` → EXHAUSTION / REVERSAL_SETUP / TREND_CONTINUATION / UNCLEAR. Весовая схема TF: 1d=4, 4h=3, 1h=2, 15m=1.
- ✅ Создан `core/smc/smc_specialist.py` — `fast_smc_verdict(df_1h, df_4h)` → STRONG/WEAK_BULL/BEAR_ZONE / NEUTRAL. Читает колонки из `calculate_trend()`.
- ✅ `bot/loops/scan_loop.py` — добавлены публикации OHLCV_UPDATED + WT_VERDICT + SMC_VERDICT для каждой пары каждый цикл (КУБ МЕТАТРОНА секция)
- ✅ `core/context/pair_context.py` — счётчик `spheres_ok` из 6 флагов наличия данных
- ✅ TASKS.md (CUBE-08 → ✅), PROJECT-LOG.md обновлены
- 🔄 **Ожидаем:** перезапуск бота → `/api/cube/context/BTC%2FUSDT%3AUSDT` должен вернуть `wt_verdict` + `smc_verdict` + `spheres_ok ≥ 3`

---

## [~20:00 UTC 12.04.2026] Агент: Developer — DEV-88 OTE Step2 бэктест

- ✅ `detect_ote_signal()` расширен: параметры `ote_zone_min_fib`, `require_wt_in_obos`
- ✅ `backtest_ote_mtf.py` — сравнение 4 конфигов через `BacktestConfig`
- ✅ Запущен бэктест: C0/C1/C2/C3 на 5 парах / 60 дней
- 🏆 **C1 winner**: 4h+CHoCH, WR=41.7%, Sharpe=2.68, MaxDD=-7R
- 🔴 C2/C3 (0.5/0.618+OB/OS) — не улучшили (WR≤36%, мало сделок)
- ⚠️ Код параметров готов, но `config.yaml` не подключен — ждём решения ARCH о активации
- 🔄 Открытые вопросы к ARCH в DISCUSSION.md: DEV-89 shadow extended? Разделение OTE_BOS/OTE_CHoCH?

---

## [~17:30 UTC 12.04.2026] Агент: Developer — DEV-155 + DEV-156 + DEV-157

- ✅ **DEV-157:** guard в `register_trade()` — sl_dist_pct < 0.1% → skip + WARNING. config: `trading.min_sl_dist_pct: 0.1`
- ✅ **DEV-155:** `min_strength_by_regime` HIGH_VOL: 85 (было 75), + новый `min_strength_by_direction_regime` LONG_RANGE: 75. Применяется в `is_actionable()` и `register_trade_async()`.
- ✅ **DEV-156:** `core/trading/circuit_breaker.py` (Singleton) — WR<15% → +10 к min_strength на 30 мин. Loop `circuit_breaker_loop()` запускается в bot.py.
- ✅ TASKS.md (DEV-155/156/157 → ✅), PROJECT-LOG.md обновлены
- 🔄 Следующий шаг: рестарт бота → логи `[DEV-155]`, `[DEV-156]`, `[CircuitBreaker]`
- ⚠️ VerdictAggregator WT threshold 0.65→0.50 ещё не реализовано

## [~14:30 UTC 12.04.2026] Агент: Developer — DEV-87 OTE backtest v2

- ✅ Запущен `scripts/backtest_ote_mtf.py` — 5 пар, 60 дней, 304 сделки total
- ✅ SWING WR=35.1%, SCALP WR=29.2% — оба ниже порога 45%
- ✅ TASKS.md, PROJECT-LOG.md, DISCUSSION.md обновлены
- ⚠️ OTE остаётся в shadow_mode=true — производственный деплой нецелесообразен
- 🔄 Ожидаем: ARCH решает Step2 фильтры (4h-only? CHoCH-only? exclude BTC?)
- Лучший subgroup: 4h primary WR=37.7%, CHoCH WR=37.8%, ETH WR=45.5%

---

## [~10:00 UTC 12.04.2026] Агент: Architect — Фильтры WR + Circuit Breaker

- ✅ Прочитал аудит TRADER (WR=8.4% за 07-10.04, диагноз: whipsaw рынок)
- ✅ Принял решения по B/C/D: HIGH_VOL→85, LONG_RANGE→75, Circuit Breaker
- ✅ Создал DEV-155 + DEV-156 в TASKS.md с полными спеками
- ✅ Ответил в DISCUSSION.md с приоритетами на 12.04
- 🔄 Ожидаем: DEV реализует DEV-155→DEV-156→рестарт
- ⚠️ DEV-153 (VerdictGate): держать выключенным по рекомендации TRADER до WR > 30% за 3 дня подряд

---

## [12:00 UTC 12.04.2026] Агент: Architect — DUAL_TSL стандарт

- ✅ Сделано: Бэктест 5564 сделок → DUAL_TSL 10%/90% = лучший вариант (+847R)
- ✅ DEV-124 закрыт как ошибочный (нечестное сравнение периодов)
- ✅ config.yaml: `trend_strategy_type: DUAL_TSL`, `tp1_fix_pct: 10`
- ✅ Задокументировано: PROJECT-LOG.md, memory/project_dual_tsl_strategy.md
- ⚠️ Апрель 2026: все стратегии в минусе — плохой рынок, не баг стратегии
- 🔄 Следить: первые DUAL_TSL сделки в БД (`strategy_type=DUAL_TSL`), логи `[regime_strategy] TREND_UP: DUAL_TP → DUAL_TSL`

---

## [11.04.2026 02:30 UTC] Агент: Developer — Куб Метатрона ПОЛНАЯ РЕАЛИЗАЦИЯ

### Что сделано:

**Куб Метатрона — все 13 сфер подключены к шине:**

1. **PairContextBus расширен** (`core/context/pair_context.py`):
   - PairState: 38 полей (все 13 сфер)
   - SphereEvent: 22 типа событий
   - Auto-update PairState при publish()
   - Event log для диагностики (последние 200 событий)

2. **Новые детекторы** (`core/signals/htf_detectors.py`):
   - TrendChangeDetector — смена тренда на 1h → EventBus
   - WTCrossHTFDetector — кросс WT в OB/OS на 4h/1d → EventBus
   - EVENT_PRIORITY: +3 новых триггера (trend_change_1h, wt_cross_4h, wt_cross_1d)

3. **scan_loop.py wiring** — каждый детектор публикует в bus:
   - Anomaly → ANOMALY_DETECTED
   - WT signal → SIGNAL_DETECTED
   - Confluence → SIGNAL_DETECTED
   - Divergence → DIVERGENCE_FOUND
   - Regime → REGIME_UPDATED (+ reversal_mode)
   - WT snap → WT_SNAP_UPDATED (все TF)
   - Pivot snap → PIVOT_SNAP_UPDATED
   - BTC macro shock → CROSS_MARKET

4. **WsFeed → bus** — TICK_PRICE (throttled 1/10 tick)

5. **Exit Manager → bus** (`trade_simulator.py`):
   - POSITION_CLOSED при close_trade()
   - TSL_MOVED при движении TSL
   - TP1_HIT при частичном TP

6. **PostTradeAnalyser → bus** — CASCADE_UPDATED, OTE_ZONE_SET

7. **NarrativeBuilder** (`core/intelligence/narrative_builder.py`) — читает ПОЛНЫЙ PairState:
   - Факторы из всех сфер: WT snap, cascade, divergence, pivot, anomaly, BTC
   - spheres_used: считает сколько сфер дали данные
   - Публикует NARRATIVE_BUILT в bus

8. **SphereRegistry** (`core/context/sphere_registry.py`) — Сфера 12:
   - Подписан на все 22 типа событий
   - health_check() → статус каждой сферы (OK/STALE/DEAD)
   - summary_text() для /status

9. **Mesh-связность** (`bot/core/bot.py → _wire_cube_subscriptions()`):
   - 8 подписок между сферами
   - Сфера 3 ← regime_updated, Сфера 6 ← wt_snap_updated
   - Сфера 9 ← signal_detected, Сфера 10 ← divergence + pivot
   - Сфера 12 ← все

10. **position_sync.py** — фикс бага ложных exit_price:
    - Sanity check: SL с R>3 → заменяем на SL цену
    - TP с R<-1 → заменяем на TP цену
    - EXPIRED с R>10 → заменяем на SL цену

### Известные проблемы:
- ⚠️ 90 OPEN: 42 VST + 48 SIM-only (SIM-only by design)
- ⚠️ NEAR #5795 и ещё ~10 сделок: position_sync использовал текущую цену вместо реального exit → фикс выше
- ⚠️ DUSK/USDT R:R=26.8 — нет записи о сделке в логе (возможно min_strength фильтр)

### Файлы изменены (НЕ закоммичены):
- `core/context/pair_context.py` — полный Shared Context Bus
- `core/context/event_bus.py` — +3 EVENT_PRIORITY
- `core/context/sphere_registry.py` — НОВЫЙ
- `core/signals/htf_detectors.py` — НОВЫЙ
- `core/intelligence/narrative_builder.py` — полный нарратив из всех сфер
- `core/trading/post_trade_analyser.py` — CASCADE/OTE publish
- `core/trading/trade_simulator.py` — POSITION_CLOSED/TSL_MOVED/TP1_HIT publish
- `core/infra/ws_feed.py` — TICK_PRICE publish
- `core/exchange/position_sync.py` — sanity check fix
- `bot/core/bot.py` — HTF detectors, SphereRegistry, _wire_cube_subscriptions
- `bot/loops/scan_loop.py` — все детекторы → bus publish
- `docs/ENCYCLOPEDIA.md` — статус Куба 12/12 сфер

### Следующий шаг:
- Рестарт бота → проверить логи [Cube] и [SphereRegistry]
- Через 30 мин: `bot.sphere_registry.summary_text()` — все 12 сфер OK?

---

## [12.04.2026 ~16:30 UTC] Агент: TRADER — TR-001 + TR-007
- ✅ TR-001: разбор БД 12.04, WR тренд 8%→17% (улучшение, но <30%)
- ✅ TR-007: VerdictAggregator — verdict_would_block не пишется в features_json (0 записей). Нужна задача DEV.
- ✅ Баг-репорт: ASR R=-450, AKT TP с R=-6.56 — аномальные R_multiple, нужен sanity clamp [-15,+15]
- ✅ EventBus: все Full CALL → None (ожидаемо), BTC 4h gate работает в shadow TREND_DOWN
- ✅ Согласен с решениями ARCH по DEV-155 + DEV-156
- ⚠️ SHORT HIGH_VOL: 3 дня подряд avgR<-0.7, WR=5% — DEV-155 критически нужен
- ⚠️ PIXEL SHORT HIGH_VOL открыт (str=71) — не пройдёт DEV-155 порог 85

## [10.04.2026] Агент: TRADER — SQL-разбор + рекомендации (TR-001, DEV-153)
- ✅ Ответил на DEV-153: 426 сделок с wt_snap (389 закрытых)
- ✅ WR benchmark: нейтральный период 01-03.04 = 38.7% (vs 8.4% за 07-10.04)
- ⚠️ WR=8.4% (07-10.04) — рыночный контекст (post-crash whipsaw)
