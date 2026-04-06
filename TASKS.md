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
| [DEV-147](#dev-147) | ✅ | TSL SL накопление: update_sl() → cancel ALL open STOP_MARKET → place one | DEV |
| [DEV-148](#dev-148) | ✅ | SQLite WAL mode + busy_timeout=10000 (database is locked фикс) | DEV |
| [DEV-111act](#dev-111act) | 🟡 | BTC 4h gate shadow→production: активировать ~09.04 (7 дней WOULD_BLOCK с 02.04) | DEV |
| [DEV-104](#dev-104) | 🔵 | Dead-Man Timer: emergency close all (Слой 3 ARCH-65) — только перед LIVE | DEV |
| **СТРАТЕГИЯ / СИГНАЛЫ** | | | |
| [DEV-110](#dev-110) | 🟡 | RANGE BOUNCE: calc_range_bounce_sl_tp() в sl_tp_calculator.py | DEV |
| [DEV-127](#dev-127) | ✅ | SMC None gate: smc_has_bos OR smc_has_choch (shadow) в wt_15m_reversal_scanner | DEV |
| [DEV-100](#dev-100) | ✅ | chart_builder: try/except + blacklist малоликвидных пар (GAIB, BANANA) | DEV |
| [DEV-87](#dev-87) | 🟢 | OTE backtest v2: WR после Step0+Step1 фильтров (ждёт данных ~11.04) | DEV |
| [DEV-121](#dev-121) | 🟢 | Self-diagnostics suite: глубокая проверка всех узлов системы | DEV |
| **ML / АНАЛИТИКА** | | | |
| [ARCH-45](#arch-45) | ✅ | Плановый ревью: AUC=0.41 (не активировать), WR=27.1%, следующий ревью 20.04 | ARCH |
| [DEV-149](#dev-149) | 🟡 | OutcomePredictor: добавить фичи distance_to_sl_pct + atr_multiple + wt_snap + reversal_mode | DEV |
| [ARCH-68](#arch-68) | 🔄 | Куб Метатрона Фаза 2: MTF WT/SMC Specialists → production integration | ARCH |
| [DEV-146](#dev-146) | ✅ | VerdictAggregator: WTVerdict+SMCVerdict → gate/strength (shadow, активировать при 200+ сделках) | DEV |
| **АРХИТЕКТУРА** | | | |
| [ARCH-70](#arch-70) | ✅ | EventBus Фаза 1+2+3: шина Full CALL — 6 триггеров включая wt_verdict_strong + btc_macro_shock | ARCH |
| [ARCH-62](#arch-62) | 🔵 | Trade Simulator рефакторинг: exit_manager + cascade_tsl + levels_calculator | ARCH |
| [ARCH-55](#arch-55) | 🟢 | sl_tp_calculator.py — единая точка SL/TP (бэклог апрель) | ARCH |
| [ARCH-57](#arch-57) | 🔵 | Confluence TRADER/RANGE tier parameter | ARCH |
| [ARCH-64](#arch-64) | 🔵 | pivot_reversal daily bias: штраф -20 / near W_S1/S2 → -10 | ARCH |
| [ARCH-67](#arch-67) | 🔵 | USDT.D macro gate: CoinGecko API + shadow (бэклог май) | ARCH |
| [ARCH-69](#arch-69) | 🔵 | Перенести verbose-секции CLAUDE.md → ENCYCLOPEDIA.md | ARCH |
| [ARCH-44](#arch-44) | 🔵 | Добавить роль DATA (триггер: AUC > 0.55) | ARCH |
| [ARCH-47](#arch-47) | 🔵 | SMC contradiction filter: SHORT при нулевых медвежьих S… | ARCH |
| **TRADER** | | | |
| [TR-001](#tr-001) | 🔄 | Ежедневный разбор Watch List с живыми свечами | TRADER |
| [TR-007](#tr-007) | 🔄 | Валидация новых детекторов перед внедрением | TRADER |

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

### DEV-111act — BTC 4h gate production 🟡
**Срок:** ~09.04.2026 (7 дней shadow с 02.04)
**Действие:** в monitoring.py изменить `btc_filter_mode: "shadow"` → `"block"` в config.yaml
**Условие:** просмотреть WOULD_BLOCK логи — если блокирует > 30% пар в боковике → отложить

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

### DEV-87 — OTE backtest v2 🟢
**Срок:** ~11.04.2026 (ждёт shadow данных)
**Суть:** проверить WR после Step0 (stale-invalidation) + Step1 (wide [0.705-0.786] + ATR gate)
**Метрика:** нужно ≥ 30 OTE сделок для статистической значимости

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

### DEV-149 — OutcomePredictor новые фичи 🟡
**Файлы:** `core/ml/outcome_predictor.py` (функция `_build_feature_vector`) + `core/trading/trade_simulator.py` (`register_trade_async` — запись в features_json)
**Суть:** текущие 12 фич не дифференцируют winners/losers (conf и strength почти одинаковые). Добавить:
- `distance_to_sl_pct` — расстояние entry→SL в % при открытии
- `atr_multiple` — SL в единицах ATR (широкий SL = хуже)
- `wt1_15m`, `wt2_15m` из `wt_snap` (DEV-138, уже пишется в metadata)
- `reversal_mode` (TREND/REVERSAL/UNCLEAR из DEV-137, уже в metadata)
**После:** переобучить модель, проверить AUC → цель > 0.55

---

### ARCH-68 — Куб Метатрона Фаза 2 🔄
**Выполнено:** DEV-137..142 — все компоненты реализованы в shadow mode
**DEV-146 выполнен:** VerdictAggregator создан (`core/intelligence/verdict_aggregator.py`), интегрирован в trading_intelligence.py, config добавлен (verdict_gate.enabled: false)
**Следующий шаг:** накопить 200+ сделок с wt_snap/smc_snap → обучить модели → включить `verdict_gate.enabled: true`

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

### TR-007 — Валидация новых детекторов 🔄
**Текущий фокус:** MTF WT Specialist + MTF SMC Specialist (DEV-138/139) — shadow данные накапливаются
**Задача TRADER:** через 1 неделю (после ~12.04) — оценить WTVerdict vs реальные входы

---

### ARCH-55 — sl_tp_calculator.py единая точка 🟢
**Суть:** сейчас SL/TP рассчитывается в 3 местах (trading_intelligence, trade_simulator, sl_tp_calculator). Нужна одна точка.
**Статус:** бэклог апрель — после рефакторинга ARCH-62

---

## 🔵 Бэклог (подробные спецификации не нужны сейчас)

| ID | Описание | Триггер для активации |
|---|---|---|
| ARCH-70 | EventBus: централизованная шина Full CALL (все детекторы → единая очередь → analyze_symbol) | После DEV-144 дашборда |
| ARCH-44 | Роль DATA в команде | CV AUC > 0.55 |
| ARCH-47 | SMC contradiction filter | После накопления SMC данных в shadow |
| ARCH-57 | Confluence TRADER/RANGE tier | После анализа confluence WR по режимам |
| ARCH-64 | pivot_reversal daily bias штраф | Спек готов, нужен DEV |
| ARCH-67 | USDT.D macro gate | Бэклог май — после BTC gate production |
| ARCH-69 | ENCYCLOPEDIA.md (verbose-секции из CLAUDE.md) | Когда CLAUDE.md > 500 строк |
| DEV-104 | Dead-Man Timer emergency close | Только перед переходом в LIVE |
| DEV-117 | Dashboard P3: /performance + SSE | После 144d-f |
