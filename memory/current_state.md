# Current State

> Последние 3 сессии. Старые записи удалены — история в git log.

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
