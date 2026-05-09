# Current State

> Последние 3 сессии. Старые записи удалены — история в git log.

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
