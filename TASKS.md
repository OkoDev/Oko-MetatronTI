# 📋 TASKS — Координация агентов

> **Архив завершённых задач:** [TASKS-ARCHIVE.md](TASKS-ARCHIVE.md)
> **Живой диалог агентов:** [DISCUSSION.md](DISCUSSION.md)

## 👥 Роли

| Роль | Кто | Зона ответственности |
|---|---|---|
| **ARCH** | yogoru | Архитектура, постановка задач, review, приоритеты |
| **DEV** | oko.webdev | Разработка, интеграция, бэктест |
| **TRADER** | Claude (TRADER) | Торговая экспертиза, валидация стратегий, живой анализ |

**Workflow:** ARCH ставит → DEV берёт → ARCH review → TRADER валидирует
**Вопросы между ролями:** писать в DISCUSSION.md с тегом `→ ARCH:` / `→ DEV:` / `→ TRADER:`

---

## 📊 Активные задачи

**Статусы:** 🔴 срочно | 🟡 важно | 🟢 в плане | 🔵 бэклог | 🔄 в работе | ✅ выполнено

| ID | Ст | Описание | Роль |
|---|---|---|---|
| **DASHBOARD** | | | |
| [DEV-144](#dev-144) | 🟡 | Полный редизайн дашборда: Live Control + Analytics + Settings | DEV |
| [DEV-144d](#dev-144d) | 🟢 | P4: Новая главная страница — баланс + exposure + equity curve + live таблица | DEV |
| [DEV-144e](#dev-144e) | 🟢 | P5: Analytics страница — donut сигналов + режимы + история с фильтром | DEV |
| [DEV-144f](#dev-144f) | 🟢 | P6: Единый CSS — тёмная тема, виджет-карточки, responsive grid | DEV |
| [DEV-117](#dev-117) | 🔵 | Dashboard P3: /performance + /pair/:symbol + SSE endpoint | DEV |
| **VST / БИРЖА** | | | |
| [DEV-155](#dev-155) | ✅ | min_strength_by_regime/direction: HIGH_VOL=85, LONG_RANGE=75 в config + is_actionable() | DEV |
| [DEV-156](#dev-156) | ✅ | Circuit Breaker: rolling WR<15% за 50 сделок → +10 к min_strength на 30 мин | DEV |
| [DEV-154](#dev-154) | ✅ | Position Sync fail-safe: get_positions error → skip cycle, не закрывать сделки | DEV |
| [DEV-147](#dev-147) | ✅ | TSL SL накопление: update_sl() → cancel ALL open STOP_MARKET → place one | DEV |
| [DEV-148](#dev-148) | 🔄 | SQLite WAL mode + busy_timeout=10000 — db locked на set_exchange_sl_order_id всё ещё есть | DEV |
| [DEV-111b](#dev-111b) | 🟡 | BTC 4h gate: HIGH_VOL в условие блока LONG + лог режима при каждом вызове | DEV |
| [DEV-111act](#dev-111act) | ⏸ | BTC 4h gate production: отложен до 14.04 (gate молчал при обвале — HIGH_VOL не блокировал) | DEV |
| [DEV-104](#dev-104) | 🔵 | Dead-Man Timer: emergency close all (Слой 3 ARCH-65) — только перед LIVE | DEV |
| **СТРАТЕГИЯ / СИГНАЛЫ** | | | |
| [DEV-151](#dev-151) | ✅ | Groq AI-комментарий к сигналам в TG (monitoring.py + TradeAnalyzer.analyze_signal) | DEV |
| [DEV-110](#dev-110) | ✅ | RANGE BOUNCE: calc_range_bounce_sl_tp() в sl_tp_calculator.py | DEV |
| [DEV-127](#dev-127) | ✅ | SMC None gate: smc_has_bos OR smc_has_choch (shadow) в wt_15m_reversal_scanner | DEV |
| [DEV-100](#dev-100) | ✅ | chart_builder: try/except + blacklist малоликвидных пар (GAIB, BANANA) | DEV |
| [DEV-87](#dev-87) | ✅ | OTE backtest v2: WR=35.1% SWING, 29.2% SCALP — 🔴 не готов к prod (нужны доп. фильтры) | DEV |
| [DEV-88](#dev-88) | 🔴 | OTE Step2 фильтры: min_zone_tf=4h + require_choch=true → пересчёт бэктеста | DEV |
| [DEV-121](#dev-121) | 🟢 | Self-diagnostics suite: глубокая проверка всех узлов системы | DEV |
| **ML / АНАЛИТИКА** | | | |
| [ARCH-45](#arch-45) | 🟢 | OutcomePredictor ревью: следующий 20.04 (AUC=0.41, цель >0.55) | ARCH |
| [DEV-149](#dev-149) | ✅ | OutcomePredictor: вектор 16→23 фич (distance_to_sl + sl_atr + wt1/2_15m + reversal_mode) | DEV |
| [ARCH-68](#arch-68) | ✅ | Куб Метатрона Фаза 2+3: все компоненты shadow + EventBus 6 триггеров | ARCH |
| [DEV-146](#dev-146) | ✅ | VerdictAggregator: WTVerdict+SMCVerdict → gate/strength (shadow, активировать при 200+ сделках) | DEV |
| **КУБ МЕТАТРОНА** | | | |
| [ARCH-71](#arch-71) | ✅ | Real Full CALL: _fire_analysis() загружает все 6 TF + дивергенции + pre_fetched_dfs | ARCH/DEV |
| [ARCH-72](#arch-72) | ✅ | Feedback Loop: PostTradeAnalyser → update_weights каждые 50 + EventBus trade_closed | ARCH/DEV |
| [DEV-152](#dev-152) | ✅ | EventBus диагностика: логи FIRE/CONSUMED/None — добавлены, работают | DEV |
| [DEV-153](#dev-153) | 🟡 | VerdictGate активация: verdict_gate.enabled: true (после проверки snap данных) | DEV |
| **АРХИТЕКТУРА** | | | |
| [ARCH-70](#arch-70) | ✅ | EventBus Фаза 1+2+3: шина Full CALL — 6 триггеров включая wt_verdict_strong + btc_macro_shock | ARCH |
| [ARCH-62](#arch-62) | 🔵 | Trade Simulator рефакторинг: exit_manager + cascade_tsl + levels_calculator | ARCH |
| [ARCH-55](#arch-55) | ✅ | DEV-110 интеграция: MarketContext.pivot_cache_1d_1w + RANGE BOUNCE в calculate_levels() | ARCH |
| [ARCH-57](#arch-57) | 🔵 | Confluence TRADER/RANGE tier parameter | ARCH |
| [ARCH-64](#arch-64) | ✅ | pivot_reversal weekly_bias gate: UNKNOWN→WATCH + против bias→-20 (shadow) | ARCH |
| [ARCH-67](#arch-67) | 🔵 | USDT.D macro gate: CoinGecko API + shadow (бэклог май) | ARCH |
| [ARCH-69](#arch-69) | 🔵 | Перенести verbose-секции CLAUDE.md → ENCYCLOPEDIA.md | ARCH |
| [ARCH-44](#arch-44) | 🔵 | Добавить роль DATA (триггер: AUC > 0.55) | ARCH |
| [ARCH-47](#arch-47) | 🔵 | SMC contradiction filter: SHORT при нулевых медвежьих S… | ARCH |
| **TRADER** | | | |
| [TR-001](#tr-001) | 🔄 | Ежедневный разбор Watch List с живыми свечами | TRADER |
| [TR-007](#tr-007) | 🔴 | Валидация MTF WT Specialist vs реальные входы (срок наступил 12.04) | TRADER |
| [TRADER-AUDIT-002](#trader-audit-002) | 🟢 | Аудит DUAL_TSL split 10%/90%: grid search после 500+ новых DUAL_TSL сделок (~30.04) | TRADER |
| [DEV-157](#dev-157) | ✅ | Фикс аномального SL: min_sl_dist_pct guard (ASR: -450R, XPIN: -81R — SL < 0.1% от цены) | DEV |

---

## 📝 Описания активных задач

### DEV-144 — Полный редизайн дашборда 🟡
**Выполнено:**
- ✅ 144a — Риск-менеджмент в settings UI (deposit/risk_pct/leverage + live preview)
- ✅ 144b — SL/TP цены из simulated_trades в /api/live_orders (JOIN)
- ✅ 144c — /api/live: баланс BingX + реальные позиции с биржи (positionSide fix)

**Выполнено (продолжение):**
- ✅ **144d** — Hero-grid на главной: 3 карточки (BingX Equity + Risk Exposure + Позиций/WR), equity curve, KPI метрики
- ✅ **144e** — Analytics: SVG donut chart сигналов + режимов рынка вверху страницы
- 🟢 **144f** — Единый CSS: тёмная тема #0d1117, карточки #161b22, green/red/blue (responsive — добавлен)

**Ссылка на спек:** DISCUSSION.md [05.04.2026] ARCH — DEV-144

---

### DEV-155 — min_strength по режиму/направлению 🔴
**Файлы:** `config.yaml`, `bot/monitoring.py` (`is_actionable()`), `core/trading/trade_simulator.py` (`register_trade_async()`)
**Суть:** добавить дифференцированные пороги силы сигнала по режиму и направлению:
- `HIGH_VOL: 85` — после 07-10.04 avgR=-1.553 в этом режиме
- `LONG_RANGE: 75` — хронически слабо (25.4% WR даже в нейтральный рынок)
**Config:**
```yaml
signal_quality:
  min_strength_by_regime:
    HIGH_VOL: 85
  min_strength_by_direction_regime:
    LONG_RANGE: 75
```
**Логика в `is_actionable()`:** сначала `min_strength_by_direction_regime`, потом `min_strength_by_regime`, потом дефолт.
**Спек:** DISCUSSION.md [12.04.2026] ARCH

---

### DEV-156 — Circuit Breaker 🔴
**Файл:** `core/trading/circuit_breaker.py` (новый) + `bot/monitoring.py`
**Суть:** если rolling WR за последние 50 закрытых сделок < 15% → поднять min_strength на +10 на 30 минут
**Алгоритм:**
1. Singleton `CircuitBreaker`, метод `check(db_path)` — SQL `SELECT COUNT(*) WHERE status IN ('TP','TSL') ORDER BY closed_at DESC LIMIT 50`
2. `strength_floor_bonus: int` — 0 в норме, +10 при активации
3. Сброс через 30 мин (или если WR вернулся > 20%)
4. Вызов каждые 15 мин в отдельной async задаче
5. `bot/monitoring.py` → `is_actionable()`: `effective_min = min_strength + cb.strength_floor_bonus`
**Лог:** `[CircuitBreaker] WR=8.4% < 15%, порог +10 на 30 мин` / `[CircuitBreaker] OFF — WR=32%`
**Спек:** DISCUSSION.md [12.04.2026] ARCH

---

### DEV-154 — Position Sync fail-safe 🔴
**Файлы:** `core/exchange/bingx_client.py`, `core/exchange/position_sync.py`, `core/trading/position_manager.py`
**Инцидент:** 07.04.2026 — BingX `timestamp is invalid` → `get_positions()` вернул `[]` → position_sync ложно закрыл 18 позиций как EXPIRED.
**Фикс (Вариант 1 — fail-closed):**
1. `bingx_client.py` → `get_positions()`: при ошибке API — бросать исключение, НЕ возвращать `[]`. При `109400` → сбросить `_time_synced = False`
2. `position_sync.py`: try/except → при ошибке skip цикла + счётчик `_consecutive_failures` (3+ → CRITICAL)
3. `position_manager.py`: использовать `_get_client_synced()`, при ошибке — skip
**Спек:** DISCUSSION.md [10.04.2026] ARCH

---

### DEV-147 — TSL SL накопление на бирже 🔴
**Файл:** `core/exchange/order_manager.py`, метод `update_sl()`
**Симптом:** SPACE/USDT накопил 14 открытых SL-ордеров. `place_sl_order()` возвращает None при ошибке → ID в БД не обновляется → следующий цикл отменяет мёртвый ID, ставит ещё один SL.
**Фикс:** заменить `cancel_order(old_id)` → получить `get_open_orders(symbol)` → отменить ВСЕ STOP_MARKET по pos_side → поставить один новый.
**Временная мера до фикса:** `trading.tsl_exchange_update: false` в config.yaml
**Спек:** DISCUSSION.md [06.04.2026] ARCH — Ответ TRADER

---

### DEV-148 — SQLite WAL mode + busy_timeout 🟡
**Файл:** `core/db/subscription_manager.py` (инициализация БД) + `core/trading/trade_simulator.py` (привести все connect к timeout=30)
**Симптом:** `database is locked` в trade_tracker при одновременной записи scan_loop + position_sync
**Фикс:** при CREATE TABLE добавить `PRAGMA journal_mode=WAL` и `PRAGMA busy_timeout=10000`
**Долгосрочно:** write-queue в ARCH-62

---

### DEV-111b — BTC 4h gate HIGH_VOL фикс 🟡
**Файл:** `bot/monitoring.py` (~строка 821) + `bot/monitoring.py` (~строка 663 `_get_btc_4h_regime`)
**Проблема:** gate блокирует только `TREND_DOWN`, но при обвале BTC классификатор возвращает `HIGH_VOL` (spike guard срабатывает на крупных свечах) — gate молчит.
**Фикс 1** — расширить условие блока LONG:
```python
# было:
if _btc_4h == "TREND_DOWN" and _dir4h == "LONG":
# стало:
if _btc_4h in ("TREND_DOWN", "HIGH_VOL") and _dir4h == "LONG":
```
**Фикс 2** — добавить лог режима в `_get_btc_4h_regime()` после расчёта:
```python
logger.info("[BTC4h] режим=%s close=%.0f", regime, ohlcv['close'].iloc[-1])
```
**Shadow остаётся:** `shadow_mode: true` — только логи, не блокировать. Наблюдать 5 дней после правки.
**Спек:** DISCUSSION.md [07.04.2026] ARCH

---

### DEV-111act — BTC 4h gate production ⏸
**Отложен до ~14.04.2026** (gate молчал всю неделю shadow — HIGH_VOL не блокировал LONG при тарифном обвале 04-06.04)
**Условие активации:** после DEV-111b + 5 дней WOULD_BLOCK данных, убедиться что gate блокирует >15% LONG в медвежьих условиях.

---

### DEV-110 — RANGE BOUNCE SL/TP Calculator 🟡
**Файлы:** `core/smc/sl_tp_calculator.py` + `core/trading/trade_simulator.py` + config.yaml
**Суть:** в RANGE+confluence/WL_breach использовать пивоты для SL/TP вместо ATR
**Алгоритм:** SL = ближайший пивот по ту сторону + 0.3% буфер; TP = противоположный пивот; фильтр: entry ≤2% от SL-пивота, TP_R ≥ 3.5R
**Config:** `trading.range_bounce.enabled: false` (включить после теста)
**Спек:** ARCH-66 в DISCUSSION.md [30.03.2026]

---

### DEV-127 — SMC None gate (shadow) 🟡
**Файл:** `core/signals/wt_15m_reversal_scanner.py`
**Суть:** блокировать вход если SMC не подтверждает (smc_has_bos=False AND smc_has_choch=False)
**Режим:** shadow — логировать WOULD_BLOCK, не блокировать
**Ожидание:** снижение ложных сигналов в RANGE без структуры

---

### DEV-100 — chart_builder blacklist 🟡
**Файл:** `core/ui/chart_builder.py` (или где находится)
**Суть:** try/except вокруг mplfinance + blacklist малоликвидных пар (GAIB/USDT, BANANA/USDT и др.)
**Симптом:** chart_builder падает на парах с нестандартными OHLCV → вся сессия крашится

---

### DEV-87 — OTE backtest v2 ✅
**Выполнено 12.04.2026.** Запущен `scripts/backtest_ote_mtf.py` — 5 пар (BTC/ETH/SOL/BNB/XRP), 60 дней, 180 SWING + 124 SCALP сделок.

**Результаты:**
- SWING WR=35.1%, AvgR=0.054, Sharpe=0.59, MaxDD=-14R → 🔴 ниже порога 45%
- SCALP WR=29.2%, AvgR=-0.125, Sharpe=-1.46 → 🔴 провал
- Лучший subgroup: 4h primary zone WR=37.7%, CHoCH WR=37.8%, ETH WR=45.5%
- BTC катастрофа: WR=20%, AvgR=-0.400
- Конфлюенция 3TF = 0 сигналов (слишком редко)

**Вывод:** Step0+Step1 недостаточно. Нужен Step2 — дополнительные фильтры для выхода на WR≥45%.
**Решение ARCH (12.04.2026):** A+B принято, C отложено, D отклонено. → DEV-88.

---

### DEV-88 — OTE Step2 фильтры (решение ARCH 12.04.2026) 🔴
**Файл:** `core/signals/ote_detector.py`, `config.yaml`

**Суть:** Добавить два фильтра в `detect_ote_signal()`:
1. `min_zone_tf: str = "4h"` — если primary TF меньше (1h) → `return None`
2. `require_choch: bool = False` — если `True` и `is_bos=True` → `return None`

**Конфиг** (`config.yaml`):
```yaml
signals:
  ote_min_zone_tf: "4h"
  ote_require_choch: true
```

**После реализации** — запустить бэктест:
```bash
python scripts/backtest_ote_mtf.py --pairs BTC ETH SOL BNB XRP --days 60
```

**Критерий успеха:** SWING WR ≥ 42% → создать DEV-89 "OTE shadow extended: 20 пар, 90 дней".
Если WR < 42% — отчитаться в DISCUSSION.md, ARCH пересматривает.

**Логика решения:** 1h zone слишком мелкая (OTE в ней = шум). BOS после 70%+ отката = структурная слабость, не вход. CHoCH + глубокий откат = ICT логика (первое движение нового тренда). Детали в DISCUSSION.md [12.04.2026 ARCH].

---

### DEV-121 — Self-Diagnostics Suite 🟢
**Суть:** скрипты глубокой проверки: импорты, DB-схема, API connectivity, config integrity, TSL pipeline
**Файл:** `core/selftest.py` (уже есть базовый) — расширить

---

### ARCH-45 — OutcomePredictor ревью ✅
**Выполнено 06.04.2026:**
- AUC=0.41 → **не активировать** (нужно > 0.55). Причина: confidence/strength у winners и losers идентичны — нужны новые фичи (DEV-149)
- pivot_reversal avg_R=-0.153 → вес 0.94x (снижен); adaptive weights пересчитаются автоматически в ml_training_loop
- WR post-fix=**27.1%** (511/1883 TP+TSL), avgR=+0.061. Неделя 06.04 показывает 45.5% — тенденция положительная
- Следующий ревью: **20.04.2026**

### DEV-149 — OutcomePredictor новые фичи ✅
**Файлы:** `core/ml/outcome_predictor.py` + `core/trading/trade_simulator.py`
**Выполнено 06.04.2026:**
- Вектор расширен 16 → **23 признака** (+7 DEV-149)
- `distance_to_sl_pct` — добавлен в `register_trade()` (trade_simulator.py)
- `sl_atr_ratio` — уже был, теперь извлекается в `_build_feature_vector`
- `wt1_15m`, `wt2_15m` — из `wt_snap["15m"]` в features_dict
- `reversal_mode` one-hot (TREND/REVERSAL/UNCLEAR) — из features_dict
- Модель переобучится автоматически в следующем `ml_training_loop`
**Цель:** AUC > 0.55 (сейчас 0.41)

---

### ARCH-68 — Куб Метатрона Фаза 2+3 ✅
**Завершена 06.04.2026.** Все 7 компонентов в shadow mode, EventBus покрывает 6 триггеров.
**Milestone активации:** 200+ сделок с wt_snap/smc_snap → обучить MTFWTSpecialist/MTFSMCSpecialist → включить `verdict_gate.enabled: true`
**TR-007:** с 13.04 проверить WOULD_BLOCK логи VerdictAggregator (DISCUSSION.md [06.04.2026])

---

### DEV-146 — VerdictAggregator (shadow) ✅
**Файл:** `core/intelligence/verdict_aggregator.py`
**Суть:** агрегирует WTVerdict + SMCVerdict → блокировка или strength delta
**Логика:**
- SMC=STRONG_BEAR + LONG направление → WOULD_BLOCK (conf ≥ 0.65)
- SMC=STRONG_BULL + SHORT направление → WOULD_BLOCK (conf ≥ 0.65)
- WT=EXHAUSTION → WOULD_BLOCK (conf ≥ 0.65)
- WT=REVERSAL_SETUP / TREND_CONTINUATION → strength +5/+2 bonus
**Config:** `trading.verdict_gate.enabled: false` → активировать после 200+ сделок с snap
**Статус:** ✅ реализован 06.04.2026, shadow mode

---

### ARCH-70 — Full CALL шина: подключить детекторы к PairContextBus ✅

**Контекст:** концепция зафиксирована в DISCUSSION.md [02.04.2026] ARCH-68 и [03.04.2026] BLUAI.
Инфраструктура уже есть: `PairContextBus.publish()` (DEV-142), `TriggerLoop._fire_analysis()` (DEV-95).
Осталось: соединить детекторы с шиной.

**Что делать DEV:**

1. Расширить `TriggerLoop` — подписаться на очередь из `PairContextBus`:
   ```python
   # В run_trigger_loop(): читать события из ctx._event_queue
   # event = (symbol, event_type, priority, data)
   # → _fire_analysis(bot, symbol, event_type)
   ```
   Добавить **cooldown 30 мин/пара** и **семафор max 5** параллельных Full CALL.

2. Добавить `await pair_context.publish(...)` в детекторы (по приоритету):

   | Детектор | Файл | event_type | Условие публикации |
   |---|---|---|---|
   | **Anomaly Volume** | `core/anomaly_model.py` | `anomaly_volume` | volume > 5× avg |
   | **Funding Extreme** | `core/signals/funding_detector.py` | `funding_extreme` | \|rate\| > 0.0005 |
   | **Liquidity Sweep** | `core/signals/liquidity_sweep_detector.py` | `liquidity_sweep` | sweep подтверждён |
   | **WT Confluence** | `core/signals/wt_15m_reversal_scanner.py` | `wt_confluence` | score ≥ 70 |
   | **WTVerdict** | `core/trading/trading_intelligence.py` | `wt_verdict_strong` | label=REVERSAL_SETUP conf≥0.7 |
   | **BTC macro** | новый мини-детектор в scan_loop | `btc_macro_shock` | BTC движение >2.5% за свечу |

3. **Приоритеты** в очереди (меньше = важнее):
   - `liquidity_sweep` + `pivot_touch` совпали на паре → priority=1
   - `funding_extreme` + `wt_verdict_strong` → priority=2
   - `wt_confluence`, `ote_reentry`, `cascade` → priority=3
   - `btc_macro_shock` → priority=4
   - `anomaly_volume` → priority=5

**Защита от шума (guardrails):**
- Cooldown 30 мин/пара — нельзя два Full CALL чаще
- Семафор 5 одновременных Full CALL — не перегружать scan
- Дедупликация: если событие для пары уже в очереди → обновить priority, не добавлять
- Full CALL регистрирует сделку только если `strength ≥ min_strength` (стандартный is_actionable)

**Shadow режим** (по умолчанию): `trigger_bus.full_call_shadow: true` → только логи `[FULL-CALL][SHADOW]`, анализ не запускается.

**Файлы:** `core/context/pair_context.py` (очередь), `bot/loops/trigger_loop.py` (consumer), детекторы выше.

---

### ARCH-70 — EventBus Full CALL шина ✅
**Реализовано (06.04.2026):**
- `core/context/event_bus.py` — приоритетная очередь (heapq), cooldown 30 мин/пара, семафор max_concurrent=3
- Фаза 1: consume_loop запущен как asyncio.Task в bot.run()
- Фаза 2: подключены к EventBus — anomaly (prio=4), funding_extreme (prio=2), liquidity_sweep (prio=1), wt_confluence (prio=3)
- Config: `event_bus.shadow: true` (только WOULD_FIRE логи) → переключить на `false` после 3-5 дней наблюдения

**Ещё не подключены (Фаза 3):**
- BTC macro trigger (>2.5% за свечу) → `/workspace/core/signals/btc_macro_detector.py` (не создан)
- WTVerdict/SMCVerdict события из trading_intelligence.py (можно добавить после DEV-146 validation)

---

### ARCH-71 — Real Full CALL 🔴
**Контекст:** EventBus Full CALL сейчас = повторный `analyze_symbol()` = тот же конвейер. За 2 дня работы: 3 сделки из тысяч событий.
**Суть:** Full CALL должен запускать **расширенный анализ** для пары:
1. Фетч ВСЕХ TF (3m, 5m, 15m, 1h, 4h, 1d)
2. Дивергенции на всех TF (сейчас только entry + 1h, и только каждый 3-й цикл)
3. OTE check (сейчас не вызывается в scan_one вообще)
4. SMC полный анализ на 1h + 4h (сейчас только entry TF для smc_context)
5. CHoCH/BOS актуальный check
6. Результаты → PairContextBus (для других модулей и NarrativeBuilder)
**Файлы:** `core/context/event_bus.py` (_fire_analysis), `bot/loops/scan_loop.py`
**Спек:** DISCUSSION.md [10.04.2026] DEV

---

### ARCH-72 — Feedback Loop 🟡
**Контекст:** PostTradeAnalyser существует но ничего не возвращает в систему. Цикл обратной связи разорван.
**Суть:** при закрытии сделки:
1. PostTradeAnalyser обновляет PairContextBus (avg_R, WR, последний статус для пары)
2. Вызывает update_signal_weights() (адаптивные веса)
3. Публикует "trade_closed" в EventBus → NarrativeBuilder создаёт нарратив
**Файлы:** `core/trading/post_trade_analyser.py`, `core/context/pair_context.py`, `core/context/event_bus.py`

---

### DEV-152 — EventBus диагностика 🔴
**Статус:** ✅ логи добавлены, ждёт рестарта
**Суть:** добавлены INFO-уровень логи в event_bus.py:
- `[EventBus] CONSUMED` — событие взято из очереди
- `[EventBus] FIRE` — начало _fire_analysis
- `[EventBus] -> analyze_symbol returned None` — сигнал не найден
- `[EventBus] -> not actionable` — повышен с DEBUG до INFO
**После рестарта:** наблюдать 1 час, собрать статистику FIRE vs None vs actionable.

---

### DEV-153 — VerdictGate активация 🟡
**Суть:** включить `verdict_gate.enabled: true` в config.yaml
**Условие:** 200+ сделок с wt_snap в features_json (проверить SQL)
**Эффект:** MTF WT Specialist и SMC Specialist начнут влиять на strength (бонус/штраф)
**Риск:** может заблокировать часть сигналов. Сначала проверить WOULD_BLOCK статистику.
**Config:** `trading.verdict_gate.enabled: false → true`

---

### ARCH-62 — Trade Simulator рефакторинг 🔵
**Суть:** монолит trade_simulator.py (1850 строк) → разбить:
- `exit_manager.py` — логика закрытия SL/TP/TSL/EXPIRED
- `cascade_tsl.py` — уже вынесен частично
- `levels_calculator.py` — расчёт SL/TP уровней
- `strategy_resolver.py` — выбор стратегии (SINGLE/DUAL/RANGE_BOUNCE)

**Приоритет:** после стабилизации VST (текущие задачи 144d-f, DEV-110, DEV-111act)

---

### TR-001 — Ежедневный разбор Watch List 🔄
**Формат:** TRADER добавляет анализ в DISCUSSION.md:
```
## [YYYY-MM-DD HH:MM UTC] TRADER — Разбор N пар live
### СИМВОЛ/USDT
- WT [15m/1h]: значения
- TSL [15m]: up/down
- Сигнал: ...
- Вывод: LONG/SHORT/HOLD, уровни входа/SL/TP
```

---

### TR-007 — Валидация MTF WT Specialist 🔴
**Срок наступил: 12.04.2026**
**Задача TRADER:** оценить WTVerdict vs реальные входы из логов и БД:
- Выгрузить WOULD_BLOCK записи VerdictAggregator (grep логов)
- Проверить: сколько заблокированных сигналов были бы прибыльными?
- Вывод: активировать `verdict_gate.enabled: true` или ждать ещё

---

### TRADER-AUDIT-002 — Аудит DUAL_TSL split 🟢
**Триггер:** 500+ закрытых сделок с `strategy_type=DUAL_TSL` в БД (~30.04.2026)
**Задача:**
1. Запустить grid search соотношений 5..95% (шаг 5%) на новых DUAL_TSL сделках
2. Пересчитать TSL_CAPTURE_RATE (сейчас 57.9% из 680 TSL-сделок)
3. Сравнить с текущим стандартом 10%/90%
4. Обновить `tp1_fix_pct` в config.yaml если оптимум сдвинулся

**SQL для мониторинга:** `SELECT COUNT(*) FROM simulated_trades WHERE strategy_type='DUAL_TSL' AND status != 'OPEN'`
**Зафиксировано:** PROJECT-LOG.md [12.04.2026], memory/project_dual_tsl_strategy.md

---

### DEV-157 — Фикс аномального SL 🔴
**Файлы:** `core/trading/trade_simulator.py` (`register_trade()`), `core/trading/sl_tp_calculator.py`
**Симптом:** ASR/USDT: -450R, XPIN/USDT: -81R — SL рассчитан в 0.002% от цены входа (вместо нормальных 1-3%).
**Причина:** при некоторых парах ATR или пивот-расчёт даёт SL практически равный entry → единица риска минимальна → любое движение = огромный R.
**Фикс:** добавить guard в `register_trade()`:
```python
sl_dist_pct = abs(entry - stop_loss) / entry * 100
if sl_dist_pct < 0.1:  # SL ближе 0.1% — явный баг расчёта
    logger.warning("[SL-GUARD] %s: sl_dist=%.4f%% < 0.1%% → пропуск регистрации", symbol, sl_dist_pct)
    return None
```
**Конфиг:** добавить `trading.min_sl_dist_pct: 0.1` (настраиваемый порог)
**Данные:** 15 сделок с |R|>10 в БД, из них 5 с |R|>20 — все баг SL

---

### ARCH-55 — DEV-110 интеграция: RANGE BOUNCE в calculate_levels() 🟡
**Спек (06.04.2026):** детальный алгоритм → DISCUSSION.md [06.04.2026] ARCH → ARCH-55

**Что делать DEV (5 шагов):**

1. **`core/signal_models.py`** — добавить в `MarketContext`:
   ```python
   pivot_cache_1d_1w: dict = field(default_factory=dict)
   regime: str = ""
   ```

2. **`core/intelligence/recommendation_generator.py`** — добавить шаг -1 в `calculate_levels()` (перед swing_low): RANGE BOUNCE ветка, вызывает `calc_range_bounce_sl_tp()`, при успехе возвращает сразу с `sl_source="range_bounce:pivot"`.

3. **`core/trading_intelligence.py`** — заполнить `market_context.regime = _regime or ""` перед вызовом `_generate_recommendation()`.

4. **`core/trading_intelligence.py`** — если `_regime == "RANGE"` и `range_bounce.enabled`, загрузить пивоты 1D/1W через `PivotCalculatorFixed` → записать в `market_context.pivot_cache_1d_1w`.

5. **`config.yaml`** — убедиться что есть:
   ```yaml
   trading:
     range_bounce:
       enabled: false
   ```

**После реализации:** `enabled: false` → смотреть что не падает → включить → накопить 20 сделок с `sl_source=range_bounce:pivot` → сравнить WR

---

## 🔵 Бэклог (подробные спецификации не нужны сейчас)

| ID | Описание | Триггер для активации |
|---|---|---|
| ARCH-70 | EventBus: централизованная шина Full CALL (все детекторы → единая очередь → analyze_symbol) | После DEV-144 дашборда |
| ARCH-44 | Роль DATA в команде | CV AUC > 0.55 |
| ARCH-47 | SMC contradiction filter | После накопления SMC данных в shadow |
| ARCH-57 | Confluence TRADER/RANGE tier | После анализа confluence WR по режимам |
| ARCH-64 | pivot_reversal weekly_bias gate ✅ | — |
| ARCH-67 | USDT.D macro gate | Бэклог май — после BTC gate production |
| ARCH-69 | ENCYCLOPEDIA.md (verbose-секции из CLAUDE.md) | Когда CLAUDE.md > 500 строк |
| DEV-104 | Dead-Man Timer emergency close | Только перед переходом в LIVE |
| DEV-117 | Dashboard P3: /performance + SSE | После 144d-f |
