# PROJECT LOG — Oko MTF TG Bot

> Живой документ проекта. Написан для людей — не для машин.
> Хронология изменений + описание ключевых компонентов системы.

---

## 🧩 Компоненты системы

Описания появляются здесь при первом упоминании в истории изменений.

---

### TradeSimulator
Регистрирует каждый торговый сигнал как симулированную сделку в базе данных.
Следит за ней до закрытия: по Take Profit, Stop Loss, Trailing Stop или истечению времени.
Все результаты сохраняются — это основа для обучения и аналитики.

---

## 📅 История изменений

### [06.04.2026] ARCH-64: pivot_reversal weekly_bias gate (shadow)

**Проблема:** 62% сделок pivot_reversal имеют `weekly_bias=UNKNOWN` — самые убыточные (EV -0.76R). LONG+BEARISH / SHORT+BULLISH без поддержки W_S/R тоже убыточны.
**Решение:** В `trading_intelligence.py` добавлен блок ARCH-64 после ARCH-48. Кейс 1: `weekly_bias=UNKNOWN` → WOULD_BLOCK (shadow). Кейс 2: против bias → WOULD_PENALIZE -20, исключение если near W_S1/S2 (≤1.5%). W_S1/S2/R1/R2 теперь сохраняются в metadata ARCH-48 — без лишних API запросов. Config: `trading.pivot_reversal_bias.enabled: false`.
**Результат:** Shadow gate активен. Включить через 3-5 дней после WOULD_BLOCK логов.

---

### [07.04.2026] TSL Supremacy: TP больше не режет ракеты при активном TSL

**Проблема:** Критический архитектурный баг — фиксированный TP=3R срабатывал даже когда TSL уже вёл сделку. 275 сделок с активным TSL закрыты по TP; 106 упустили >1R. Примеры: HANA/USDT упустил 46.5R, RIVER/USDT — 22.7R. Данные: TSL avg R=4.45 vs TP avg R=2.73 (+62%).
**Решение:** `core/trading/trade_simulator.py` — добавлена проверка `_tsl_is_active = bool(trade.get("tsl_activated"))` в оба блока (LONG/SHORT). `hit_tp` вычисляется как `False` если TSL активен. TP остаётся только как страховка до активации TSL. `config.yaml` — де-эскалация cascade TSL агрессивнее: `no_degrade_above_r 5.0→3.0`, `r_gradient_peak_min_r 3.0→2.0`, `r_gradient_rollback_pct 0.85→0.75`.
**Результат:** Ракеты больше не режутся на 3R. Ожидаем рост avg captured_R_pct с 57.5% до 65%+, avg R TSL-сделок вырастет. Проверить через 3-5 дней.

---

### [07.04.2026] DEV-148 финальный фикс: busy_timeout в subscription_manager.py

**Проблема:** `database is locked` продолжал появляться в логах (`close_trade`). Предыдущий фикс добавил `_db_connect()` только в `trade_simulator.py`, но `subscription_manager.py` (6 методов) всё ещё использовал прямой `sqlite3.connect()` без timeout.
**Решение:** В `core/db/subscription_manager.py` добавлен `_db_connect()` helper с `PRAGMA busy_timeout=10000`. Все 6 методов (`init_database`, `add_user`, `get_user_subscription`, `create_subscription`, `get_daily_signal_count`, `record_signal_sent`) переведены на helper.
**Результат:** Теперь каждое соединение с БД во всём проекте ждёт до 10 секунд перед ошибкой. Ошибок `database is locked` быть не должно.

---

### [06.04.2026] DEV-149: OutcomePredictor — вектор признаков 16→23

**Проблема:** AUC=0.41 (хуже случайного). Confidence и strength у winners и losers почти идентичны — текущие 16 фич не дифференцируют исходы.
**Решение:** `core/ml/outcome_predictor.py` — вектор расширен до 23 признаков. Добавлено 7 новых: `distance_to_sl_pct` (нормирован / 5%), `sl_atr_ratio` (извлечение из features_dict), `wt1_15m`/`wt2_15m` из `wt_snap["15m"]`, `reversal_mode` one-hot (TREND/REVERSAL/UNCLEAR). `core/trading/trade_simulator.py` — добавлен расчёт `distance_to_sl_pct = |entry-SL|/entry×100` при регистрации сделки.
**Результат:** При следующем `ml_training_loop` модель переобучится с новыми признаками. Ожидаем рост AUC с 0.41 → цель >0.55. Новые фичи уже пишутся в features_json для всех новых сделок.

---

### [06.04.2026] ARCH-68 закрыта + ARCH-55 спек (DEV-110 интеграция)

**Проблема:** ARCH-68 технически завершена (все 6 триггеров EventBus подключены), но не была официально закрыта. DEV-110 (`calc_range_bounce_sl_tp`) реализован, но не интегрирован — непонятно куда подключить (pivot_cache недоступен в calculate_levels).
**Решение:** ARCH-68 → ✅. Для DEV-110: архитектурный выбор Вариант C — добавить `pivot_cache_1d_1w: dict` и `regime: str` в `MarketContext`, тогда `calculate_levels()` сможет вызывать RANGE BOUNCE без изменения API. Полный спек из 5 шагов записан в DISCUSSION.md и TASKS.md (ARCH-55 🟡).
**Результат:** DEV получил готовый спек. ARCH-55 переведена из бэклога в активные задачи — это ключ к корректному SL/TP в RANGE режиме.

---

### [06.04.2026] ARCH-70: wt_verdict_strong + btc_macro_shock триггеры EventBus

**Проблема:** EventBus шина работала с 4 триггерами (anomaly, funding, liquidity_sweep, wt_confluence). Два оставшихся из спека не были подключены.
**Решение:** `core/trading_intelligence.py` — после блока DEV-138 (wt_specialist.predict) добавлен publish `wt_verdict_strong` при label=REVERSAL_SETUP conf≥0.7. `bot/loops/scan_loop.py` — функция `_check_btc_macro_shock()` + вызов в начале каждого цикла `monitor_market()`, проверяет BTC/USDT 15m свечу на движение >2.5%. `bot/core/bot.py` — `trading_intelligence._event_bus = self.event_bus` для связи. `config.yaml` — добавлен `btc_macro_shock_pct: 2.5`.
**Результат:** EventBus покрывает все 6 триггеров из спека ARCH-70. Любой новый детектор добавляется одной строкой `_eb.publish(sym, "event_type")`.

---

### [06.04.2026] DEV-144d+144e: Hero grid + donut charts на дашборде

**Проблема:** Главная страница не показывала BingX баланс и risk exposure в удобном виде. Аналитика не давала быстрого визуального обзора распределения сигналов и режимов рынка.
**Решение:** `web/static/index.html` — добавлен hero-grid (3 карточки вверху главной: BingX Equity, Risk Exposure с прогресс-баром, Позиций/WR). Карточка BingX заполняется через `loadLive()`. На странице Аналитика добавлены SVG donut charts (сигналы и режимы) с легендой avg R / WR. Добавлен responsive breakpoint @860px.
**Результат:** Главная страница теперь даёт мгновенный обзор состояния торговли — баланс биржи, риск и статистика видны с первого взгляда. Donut charts на аналитике показывают распределение без таблиц.

---

### [06.04.2026] DEV-100 + DEV-127 + DEV-148 доп.: chart blacklist, SMC gate, SQLite helper

**DEV-100 (chart_builder blacklist):** `core/ui/chart_builder.py` — добавлен `_CHART_BLACKLIST_BASE` (GAIB, BANANA и др.) + проверка в `build_signal_chart` в начале функции. Добавлена валидация OHLCV (нулевые/NaN close). Список расширяем через `signals.chart_blacklist` в config.yaml. Предотвращает краш mplfinance на малоликвидных парах с нестандартными данными.

**DEV-127 (SMC None gate, shadow):** `core/signals/wt_15m_reversal_scanner.py` — добавлен параметр `smc_context`, при `has_bos=False AND has_choch=False` логируется `[DEV-127][SHADOW] WOULD_BLOCK`. Флаг `analysis.smc_none_gate.enabled: false` — shadow по умолчанию. `bot/loops/scan_loop.py` — перед вызовом scanner вычисляем `analyze_smc(df_entry)` и передаём как `smc_context`.

**DEV-148 доп.:** `core/trading/trade_simulator.py` — добавлен `_db_connect()` helper, который применяет `busy_timeout=10000` ко ВСЕМ 16 соединениям (ранее только к `init_database`). `core/trading/performance_engine.py` — аналогичный фикс в `_conn()`.

**Результат:** Больше нет graphical crash на мусорных парах. WOULD_BLOCK статистика SMC gate накапливается. `database is locked` устранён на всех write-путях.

---

### [05.04.2026] DEV-147 + DEV-148: TSL SL накопление и SQLite lock фиксы

**Проблема:** TSL обновлял SL на бирже через cancel-by-ID, но при таймауте `place_sl_order()` возвращал None → ID в БД не обновлялся → следующий цикл отменял мёртвый ордер и ставил ещё один. За ночь накапливалось до 14 SL-ордеров на пару. Параллельно: `trade_tracker` и `monitoring` писали в SQLite одновременно → `database is locked`.

**Решение DEV-147:** `order_manager.py → update_sl()` — вместо cancel-by-ID теперь получаем `get_open_orders()` → отменяем ВСЕ STOP_MARKET по символу+pos_side → ставим один новый. Fallback на cancel-by-ID если биржа недоступна.

**Решение DEV-148:** `trade_simulator.py` и `db/subscription_manager.py` — добавлен `PRAGMA busy_timeout=10000` (ждать до 10 сек). `position_sync.py` — добавлены timeout=10 и busy_timeout для write-коннектов.

**Результат:** Ордера больше не накапливаются даже при нестабильном соединении. SQLite lock заменяется ожиданием вместо падения.

---

### OutcomePredictor
Модель машинного обучения (RandomForest), которая учится на истории закрытых сделок.
По 12 признакам (сила сигнала, режим рынка, тип сигнала и др.) предсказывает
вероятность прибыли P(win) для новой сделки.
Точность растёт по мере накопления данных — нужно минимум ~200 закрытых сделок
для стабильных предсказаний.

---

### TSL (Trailing Stop Loss)
Динамический стоп-лосс, который следует за ценой и защищает накопленную прибыль.
Активируется после достижения +1R прибыли. Использует линию тренда (`trenddown` / `trendup`)
как уровень закрытия — цена пробила линию → сделка закрыта.

**Каскадный TSL:** автоматически переключается на старший таймфрейм (15m → 1h → 4h)
когда тренд подтверждён на нём. Старший TF даёт более широкий стоп и позволяет
тренду развиваться дольше.

---

### Adaptive Weights (адаптивные веса сигналов)
Система автоматически регулирует доверие к каждому типу сигнала на основе
реальных результатов. Если `wt_signal` в среднем даёт +0.83R — его вес растёт.
Если `trend_signal` даёт −0.5R — вес снижается. Обновляется при каждом перезапуске.

---

### Market Regime (режим рынка)
Классификатор, который определяет текущее состояние рынка по паре:
`TREND_UP`, `TREND_DOWN`, `RANGE`, `HIGH_VOL`.
Используется для фильтрации сигналов — например, не открывать LONG при `TREND_DOWN`.

---

### PivotCalculatorFixed (singleton)
Вычисляет классические пивоты (Daily, Weekly, Monthly) в UTC, метод Woodie.
Один экземпляр на весь бот, кеш живёт весь цикл — ~600 лишних инстансов/час устранены.
Future PP — прогноз уровня на следующий день (используется для score modifier).

---

### Weekly Bias Filter (ARCH-48)
Top-down контекст для каждой пары: `price > weekly_PP` → бычий bias (торговать LONG),
`price < weekly_PP` → медвежий bias (торговать SHORT). Исключение — входы у Weekly R1/S1.
Три уровня строгости: monthly + weekly + daily PP все против → hard block (ctx_score=3).

---

### L3 Checker (DEV-52/53, TR-006 спек)
6-условный чеклист входа TRADER-а реализован как shadow mode наблюдатель.
Условие 3: 1h структура (BOS блок, CHoCH -8 score). Условие 4: WT кросс свежий ≤3 баров И вблизи пивота.
Условие 5: score ≥ 85. Условие 6: портфельный лимит (2+2+4).
Когда накопится статистика — включить как production gate.

---

### MFE (Maximum Favorable Excursion)
Для каждой сделки записывается максимально достижимый экстремум: `max_price`/`min_price`.
`max_R_possible` — лучший теоретический R, `captured_R_pct` — сколько % захватил TSL.
Отвечает на вопрос: "TSL работает хорошо или закрывает слишком рано?"

---

### Correlation Guard
Список групп коррелированных активов (золото: PAXG/XAUT; BTC/WBTC; ETH/STETH/WETH).
При попытке открыть вторую позицию из той же группы — тихий блок в `register_trade_async()`.
Предотвращает двойное накопление риска на фактически одном активе.

---

### MTF Interpreter (Phase Detector)
Читает структуру рынка по связке 1D+4H. Различает: `IMPULSE_UP/DOWN` (тренд идёт),
`CORRECTION_*_IN_*` (откат против старшего тренда), `CASCADE_OS/OB_REVERSAL` (2+ TF в перекупленности/перепроданности).
Добавляет поля `phase`, `zone_state`, `pattern_name`, `avoid_reason` в MTFContext.

---

### Pivot Proximity Filter
ATR-адаптивный фильтр близости к пивоту: `tier1 = max(1%, min(ATR×1.5, 5%))`.
Далеко от Daily/Weekly PP → score -10. Очень далеко (>tier1×2) → action=WATCH.
Принцип: пивоты — зоны где цена встречает поддержку/сопротивление; вдали от них — воздух.

---

## 📅 История изменений

---

### [06.04.2026] ARCH-45 — Ревью OutcomePredictor + Adaptive Weights

**Проблема:** плановый ревью ML-слоя (срок 06.04) — решить активировать ли OutcomePredictor и пересчитать ли адаптивные веса.
**Результат:** CV AUC=0.41 — модель не активируется. Причина диагностирована: confidence/strength у winners и losers идентичны (нет дифференцирующих фичей). pivot_reversal avg_R=-0.153 → вес 0.94x. WR post-fix=27.1% (было 4.9% в недели бага). Текущая неделя 45.5%. Создана DEV-149 — добавить distance_to_sl_pct, atr_multiple, wt_snap в feature_vector. Следующий ревью: 20.04.2026.

---

### [06.04.2026] ARCH-70 — EventBus: централизованная шина Full CALL

**Проблема:** 10+ детекторов (anomaly, funding, liquidity sweep, confluence) обнаруживают сигналы и делают broadcast в TG, но не вызывают `analyze_symbol()`. Full CALL (→ register_trade) происходил только из TriggerLoop по 3 сценариям. 75% событий "терялись" без торгового решения.
**Решение:** `core/context/event_bus.py` — приоритетная очередь (heapq) с cooldown 30 мин/пара и семафором max_concurrent=3. Детекторы публикуют `event_bus.publish(symbol, event_type)` после обнаружения сигнала. consume_loop читает очередь → `_fire_analysis()` → `analyze_symbol()`. Shadow mode (`event_bus.shadow: true`) — только WOULD_FIRE логи. Подключены: anomaly (prio=4), liquidity_sweep (prio=1), funding_extreme (prio=2), wt_confluence (prio=3).
**Результат:** система реагирует на рынок событийно. Liquidity Sweep → немедленный Full CALL (высший приоритет). Cooldown защищает от шума. После 3-5 дней наблюдения: переключить `event_bus.shadow: false`.

---

### [06.04.2026] DEV-146 — VerdictAggregator: WTVerdict + SMCVerdict → gate (ARCH-68 Фаза 2)

**Проблема:** Компоненты Куба Метатрона (DEV-137..142) накапливали WTVerdict и SMCVerdict в metadata, но никак не влияли на решение — данные "висели в воздухе".
**Решение:** `core/intelligence/verdict_aggregator.py` — агрегирует два вердикта в `VerdictGate`: блокировка при SMC=STRONG_BEAR+LONG (или SMC=STRONG_BULL+SHORT, conf ≥ 0.65), блокировка при WT=EXHAUSTION (conf ≥ 0.65), буст +5 к strength при совпадении. Интегрирован в `trading_intelligence.py` после секции DEV-138/139. Конфиг: `trading.verdict_gate.enabled: false` (shadow mode, только WOULD_BLOCK логи).
**Результат:** система логирует когда вердикты противоречат направлению; при `enabled: true` — реальный gate. Активировать после накопления 200+ сделок с wt_snap/smc_snap.

---

### [06.04.2026] DEV-145 — BingX timestamp invalid + position_sync рефакторинг

**Проблема:** Все VST ордера падали с `code: 109400 — timestamp is invalid` — системное время WSL отставало от BingX на ~4.7с (допуск ±1с). Следствие: `get_balance()` возвращал 0 → qty=0 → ордер не ставился. Плюс `position_sync` угадывал статус закрытой сделки по текущей цене — давал R=0.
**Решение:** (1) `BingXClient.sync_time()` — получает серверное время BingX и сохраняет offset; `_ts()` корректирует timestamp на offset. `OrderManager._get_client_synced()` вызывает sync один раз lazy. (2) `position_sync.sync_positions()` переведён на `_get_client_synced()` + читает `get_filled_orders()` для реального exit_price и типа ордера (STOP_MARKET→SL, TAKE_PROFIT_MARKET→TP). (3) Добавлен `fix_zero_r_trades()` — ретроспективная чистка 106 нулевых VST записей: ищет реальный exit через API, иначе помечает UNKNOWN.
**Результат:** ордера будут ставиться корректно; position_sync пишет реальный exit_price; есть инструмент для чистки исторического мусора.

---

### [05.04.2026] DEV-129 — PivotTouchTrigger: событийный вход при касании пивотов

**Проблема:** polling каждые 2 минуты → потеря до 1R при касании пивотного уровня R1/R2/S1/S2 в промежутке между сканами.
**Решение:** `PivotTouchTrigger` в `core/context/trigger_bus.py` — проверяет расстояние до R1/R2/S1/S2 на 1D и 1W (порог 0.3%). Cooldown 60 мин/пара. `trigger_loop.py` расширен: `_check_pivot_touches()` читает `pivot_cache` без лишних API-запросов. Shadow mode (логирует `PIVOT_TOUCH WOULD_FIRE`). Включить production через `trigger_bus.shadow: false` в config.
**Результат:** событийный анализ при касании ключевых уровней — без изменения scan_loop, минимальный diff.

---

### [05.04.2026] Куб Метатрона Фаза 2 — все 6 компонентов реализованы (DEV-137..142)

**Проблема:** 6 задач ARCH-68 не были реализованы — system не различала REVERSAL vs TREND режим, не имела ML специалистов по WT/SMC, не собирала EQH/EQL уровни, не генерировала торговых нарративов.
**Решение:** Реализованы все 6 компонентов в shadow mode за одну сессию:
- DEV-137: `classify_mode()` в MarketRegimeClassifier — WT 4h + ADX slope + CHoCH → REVERSAL/TREND/UNCLEAR
- DEV-138: `MTFWTSpecialist` (35 признаков, 7 TF) — RandomForest на wt_snap из features_json
- DEV-139: `MTFSMCSpecialist` (36 признаков, 4 TF) — RandomForest на smc_snap
- DEV-140: `detect_equal_highs_lows()` в liquidity.py — поиск EQH/EQL как liquidity magnets
- DEV-141: `NarrativeBuilder` — синтезирует TradingNarrative (текст + P(win) + key_factors)
- DEV-142: PairContextBus pub/sub — `publish/subscribe/get_full_state`, новые поля PairState
**Результат:** данные собираются (wt_snap/smc_snap/reversal_mode в features_json), shadow логируются, ML обучится автоматически по накоплении 50+ сделок с нужными снимками.

---

### [05.04.2026] DEV-143 — position_sync.py фикс: реальный exit_price для VST сделок

**Проблема:** `position_sync.py:59` — `get_current_price()` возвращает None для большинства пар (не в WS-фиде) → fallback = entry_price → status всегда "TP" → 100% VST TP с R=0.
**Решение:** Добавлен промежуточный fallback через `get_ticker()` (REST-запрос) перед финальным fallback на entry_price. Только если тикер тоже недоступен → старый fallback.
**Результат:** VST-сделки теперь закрываются с реальным exit_price и корректным статусом SL/TP.

---

### [04.04.2026] TRADER: DEV-142 — position_sync.py баг, 86 VST TP с R=0

**Проблема:** В VST режиме 86/91 TP сегодня имели R=0 (exit=entry). Реальная производительность дня (WR=16%, -21.6R) была скрыта за нулевыми записями.
**Решение:** Найдена корневая причина в `core/exchange/position_sync.py:59`. Метод `get_current_price()` (WS-only) возвращает None для большинства пар → fallback = `entry_price`. Дальше статус-проверка всегда даёт "TP" (entry > sl). Фикс: заменить на `get_ticker()` как fallback. Создан DEV-142 🔥.
**Результат:** После фикса VST-сделки будут корректно записываться с реальным exit_price и правильным статусом SL/TP.

---

### [04.04.2026] ARCH-68: Куб Метатрона Фаза 2 — архитектурный план (ARCH-68)

**Проблема:** система хорошо классифицирует режим (TREND/RANGE), но не различает внутри режима фазу рынка: идёт тренд или назревает разворот? ML-модели обучены на общих признаках, без специализации на WT и SMC данных.
**Решение:** разработан план 6 компонентов: (1) Reversal Mode Detector — расширение MarketRegimeClassifier, определяет "TREND vs REVERSAL" по WT 4h зоне + ADX slope + CHoCH; (2) MTF WT Specialist — ML модель на 35 WT признаках по 7 TF; (3) EQH/EQL детектор — поиск Equal Highs/Lows как уровней ликвидности; (4) MTF SMC Specialist — ML на 36 SMC признаках по 4 TF; (5) Narrative Builder — синтезирует всё в TradingNarrative с P(win) и текстом для TG; (6) PairContextBus pub/sub — расширение шины состояния. Все компоненты в shadow mode.
**Результат:** DEV-137..142 добавлены в TASKS.md. Начинаем с DEV-137 (Reversal Mode) — самый быстрый, не зависит от ARCH-62, сразу улучшает DEV-128ext (confluence блокировка в правильном mode).

---

### [30.03.2026] DEV-120: DUAL_TSL для TREND — 70% на пивоте, 30% под TSL

**Проблема:** TP-стратегия фиксировала всю позицию на первом пивоте, хотя данные показывают что TSL-сделки в TREND дают 4.6R avg vs 2.1R у TP. 30% остатка под TSL добавляет ~+0.6R на сделку в TREND_UP.
**Решение:** новый strategy_type `DUAL_TSL` — TP1 закрывает 70% на первом пивоте, 30% продолжают жить под Trailing Stop. `close_trade()` считает взвешенный R: `0.70 × R_tp1 + 0.30 × R_tsl`. Процент читается из `trading.dual_tp.tp1_fix_pct` (управляется из дашборда). RANGE остался SINGLE.
**Результат:** оба TREND режима теперь захватывают продолжение тренда на 30% позиции, не жертвуя надёжностью на основной части. Если TSL выбьет после TP1 по −0.5R — итог всё равно +1.25R.

### [30.03.2026] DEV-119: TP стратегия упрощена — убран TRIPLE, DUAL_TP на пивотах

**Проблема:** открытые сделки не закрывались при достижении TP — цена шла через TP, но статус оставался OPEN. Причина: баг в guard `tp1_hit_at is None` блокировал детекцию TP2. Плюс TRIPLE_TP_TSL создавал произвольные уровни (1/3 и 2/3 от tp_dist) без привязки к рынку.
**Решение:** (1) TRIPLE убран полностью — только SINGLE и DUAL_TP. (2) TP1 = первый пивот из иерархии (уже рассчитан `get_tp_by_hierarchy()`). (3) TP2 = следующий пивот — новая функция `get_next_tp_by_hierarchy()` вычисляет его асинхронно после регистрации. (4) Баг exit исправлен: TP2 hit теперь ставит `exit_status = TP`. (5) RANGE → всегда SINGLE через `regime_strategy.py`. (6) Dashboard: toggle DUAL TP + слайдер TP1 fix %.
**Результат:** сделки закрываются корректно, TP2 привязан к реальным уровням рынка, а не к произвольным коэффициентам. Быстрое управление через дашборд без рестарта.

### [30.03.2026] DEV-118: Фикс дублирования analyze_symbol на пару за цикл

**Проблема:** если за один цикл скана у пары нашлись `confluence` + `wt_signal`, создавались два `create_task` → оба делали полный `analyze_symbol` (~27+19 сек CPU зря). Race condition: dedup по `_last_signal` срабатывал по времени завершения, не начала.
**Решение:** в `scan_loop.py` заменён `for` на `max()` по приоритету — выбирается один лучший signal_type (confluence > wt_b > wt_signal > liquidity_sweep > anomaly). `pre_signals` (все сигналы) передаётся полным — контекст анализа не теряется.
**Результат:** одно `analyze_symbol` на пару за цикл вместо N. CPU нагрузка снижается при наличии нескольких сигналов. Изменение в 1 строке логики, минимальный риск регрессии.

### [30.03.2026] DEV-113–117: Задачи Dashboard редизайна для VST (ARCH)

**Проблема:** дашборд — это журнал истории, а для VST нужен live-монитор риска. Отсутствовали: Risk Exposure, Open P&L, BTC 4h badge, cascade badge, auto-refresh.
**Решение:** поставлены задачи в 3 приоритета: P1 (DEV-113/114/115, 🔥 критично для VST) — auto-refresh 30s, BTC 4h badge, Risk Exposure карточка, cascade badge в open trades; P2 (DEV-116, 🔵) — аналитические графики; P3 (DEV-117, 🔵) — новые страницы /performance + SSE.
**Результат:** DEV-113 + DEV-114 реализуют Приоритет 1 TRADER (5 метрик которые нужны перед VST).

### [30.03.2026] ARCH-63 + ARCH-66: Спеки BTC 4h Gate и RANGE BOUNCE стратегии (ARCH)

**Проблема:** 73% SL-сделок за медвежий день (29.03) — LONG в RANGE против медвежьего BTC. RANGE WR=16%, EV=-0.12R. Входы в середине диапазона без реального SL/TP уровня.
**Решение:** два спека. ARCH-63: BTC 4h gate в `trading_intelligence.analyze_symbol()` — shadow mode сначала, логирует WOULD_BLOCK LONG при BTC 4h TREND_DOWN. ARCH-66: RANGE BOUNCE — SL у ближайшего пивота (≤2% от entry), TP у противоположного (TP_R≥3.5), только 15m confluence/wl_breach.
**Результат:** DEV-111 (shadow gate) и DEV-110 (RANGE SL/TP) готовы к реализации. Данные анализа: confluence SHORT в RANGE = WR 63.6%, avg_R +2.67R (33 сделки).

### [30.03.2026] DEV-107: Фикс критического бага — cascade WT де-эскалация никогда не работала (DEV)

**Проблема:** `trade_simulator.py` строка 1255: `_CASCADE_TFS.index(df_tsl)` — передавался DataFrame вместо строки таймфрейма. `list.index(DataFrame)` всегда вызывал `ValueError` → весь блок де-эскалации TSL по WT (DEV-28/DEV-89) молча падал и никогда не срабатывал в продакшне.
**Решение:** заменено на `_CASCADE_TFS.index(best_tsl_tf)` — `best_tsl_tf` это строка `"4h"`, `"1h"` и т.д.
**Результат:** каскадная де-эскалация (4h→1h→15m при истощении WT + касание недельных пивотов) заработала впервые. Защита прибыли в TSL теперь реально переходит на более тесный стоп при развороте.

### [30.03.2026] DEV-108: dynamic_os активирован только в RANGE режиме (DEV)

**Проблема:** в RANGE WT гуляет в [-30,+30], фиксированный порог -60 не достигается → 52% SL сделок даже не двигались в нашу сторону. WR в RANGE = 1.1% (842 сделки).
**Решение:** `check_wt_signals()` и `scan_wt_15m_reversal()` получили параметр `market_regime`. Если `regime == RANGE`: dynamic_os (`mean±0.8*std`) используется как реальный gate (не shadow). В TREND/HIGH_VOL — без изменений, фиксированный -60/+60. Логирование `[DEV-108] SYMBOL RANGE: dyn_os=-13.x → ACTIVE`. Вычисление `_pair_regime` перенесено в начало скана (один раз на пару, используется всеми детекторами).

### [30.03.2026] DEV-82 v2: LiquiditySweep 15m→1h, period 5→10, min_bars 30→50 (DEV)

**Проблема:** детектор на 15m с period=5 генерировал слишком частые сигналы (локальные флипы, нет реальной ликвидности). Задача — искать только значимые sweep-уровни.
**Решение:** `_MIN_BARS 30→50`, `period 5→10` в `detect_swing_points`, `timeframe "15m"→"1h"` в SignalData. В `scan_loop.py` передаём `df_1h` вместо `_df_tf`. `df_1h` уже грузится параллельно для каждой пары.
**Результат:** детектор теперь ищет свинги на 1h с периодом 10 (200 баров истории = 8+ дней). Сигналы будут реже но значимее — реальные уровни накопления ликвидности.

### [30.03.2026] TriggerLoop активирован в production (DEV)

**Было:** `trigger_bus.shadow: true` → только логи `[TriggerLoop][SHADOW]`, сделки не регистрировались.
**Стало:** `shadow: false` → при OTE re-entry или Cascade trigger реально запускается `analyze_symbol()` + `register_trade_async()`.

### [30.03.2026] DEV-106: Pivot Touch Fast Exit — force 15m TSL у W/M уровней (DEV)

**Проблема:** TSL-сделки захватывают в среднем только 58% от пика (avg 4.1R из 7.8R max). Анализ 512 TSL-закрытых сделок показал: 181 сделка касалась weekly или monthly пивота — и именно там разворот происходил резче всего. Captured в этой группе всего 55-64%.
**Решение:** добавлен блок DEV-106 в `trade_simulator.py`. При касании weekly (PP/S1/S2/S3/R1/R2/R3) или monthly (PP/S для SHORT, PP для LONG) пивота + R≥2.0 → принудительный прыжок на 15m TSL минуя cascade. Флаг `pivot_tsl_15m` предотвращает повторное срабатывание. 1M R1/R2/R3 для LONG исключены — данные показали cap=105% (пробойные, не разворотные).
**Результат:** по бэктесту на 181 pivot-touch сделке: avg 4.09R → 6.53R (+2.44R), лучше=165 сделок, хуже только 16.

### [30.03.2026] Обнаружен баг DEV-107: cascade деэскалация по WT никогда не работала (DEV)

**Проблема:** `_CASCADE_TFS.index(df_tsl)` — в списке строк ищется DataFrame → всегда ValueError → весь блок WT-деэскалации (DEV-28/DEV-89) никогда не срабатывал в продакшн. Создана задача DEV-107 на исправление.

### [30.03.2026] Откат scan_semaphore 20→10 + WsFeed Phase 2 отключена (DEV)

**Проблема:** после DEV-99 (semaphore 10→20) OHLCV запросы стали занимать 10-35 сек вместо 2-5 сек. Больше параллельных запросов → BingX throttlit весь IP → все запросы замедляются. WsFeed Phase 2 (50 OHLCV-подписок одновременно) добавила 389K ошибок за 5 минут — BingX временно забанил IP.
**Решение:** `scan_semaphore_size: 20→10`, `analyze_semaphore_size: 5→3`. WsFeed Phase 2 (watch_ohlcv) закомментирована до отладки формата подписок. Phase 1 (watch_ticker, 534 пары, 6 батчей) работает штатно.
**Результат:** цикл скана вернулся к норме, `OHLCV медленно` предупреждения исчезли.

### [30.03.2026] WsFeed: батчи восстановлены + Phase 2 OHLCV добавлена (DEV)

**Проблема:** упрощение WsFeed (убрать батчи) нарушало изоляцию — падение одного WS = все 534 пары без данных. BingX лимитирует подписки на соединение (~200-300).
**Решение:** возврат батчей по 100 пар (6 батчей для 534 пар). Добавлена задержка 2 сек между батчами при старте. Phase 2 watch_ohlcv для priority_pairs (открытые сделки, до 50 пар) добавлена в архитектуру — временно отключена.
**Результат:** WsFeed стабилен, priority_pairs корректно передаются (92 пары из open trades).

### [30.03.2026] ARCH-65: Exchange Health Guard спек (ARCH)

**Проблема:** нет защиты сделок при падении биржи — для VST/LIVE критично.
**Решение:** спек трёх слоёв: health_loop (ping каждые 30 сек), TG алерт (DEGRADED/DOWN), dead-man timer (LIVE >30 мин DOWN → emergency close). Файл: `bot/loops/health_loop.py`.
**Результат:** DEV-103 (Слои 1+2) и DEV-104 (Слой 3) созданы в TASKS.

### [29.03.2026] Trade Dashboard — полный аудит + план редизайна (ARCH)

**Проблема:** Дашборд не показывает ключевые метрики торговой системы: нет cascade level, нет MFE/cap%, нет live-обновления, нет аналитических графиков. При переходе на VST необходим risk exposure и position sizing.

**Решение:** Проведён полный аудит в DISCUSSION.md. Выявлено 20+ пробелов, составлен план из 3 приоритетов. Quick wins (auto-refresh, cascade badge, cap%, сортировка) — 1 день. Аналитика (heatmaps, scatter, histogram) — 3-5 дней. VST readiness (risk exposure, position sizing, drill-down) — 5-10 дней.

**Результат:** Roadmap редизайна согласован. DEV знает что делать в первую очередь. TRADER запрошен приоритет метрик для VST запуска.

---

### [29.03.2026] Execution Layer: TriggerBus + OrderExecutor + PositionManager (DEV-95/77/78)

**Проблема:** после реализации PostTradeAnalyser и PairContextBus система умела _помнить_ состояние,
но не умела _реагировать_ на него. Кроме того, отсутствовал execution layer для реальных ордеров.

**Решение:**
- `core/context/trigger_bus.py` + `bot/loops/trigger_loop.py` — TriggerBus: asyncio цикл каждые 2 мин
  проверяет «горячие» пары и запускает анализ при OTE re-entry или накоплении cascade≥3.
  Shadow mode по умолчанию — только логи.
- `core/trading/order_executor.py` — OrderExecutor: SIM/VST/LIVE режимы, bracket-ордер,
  partial close 20% при TP1 hit, min_notional=5 USDT guard.
- `core/trading/position_sizer.py` — PositionSizer: qty = deposit×risk% / (sl_dist × entry_price).
- `core/trading/position_manager.py` — live_orders таблица в SQLite, has_open_position(), sync.
- `core/trading/order_reconciler.py` — ORPHAN детектор при рестарте бота.

**Результат:** Куб Метатрона Фаза 1+2 завершён. Все компоненты в shadow mode,
подготовлена инфраструктура для LIVE-исполнения.

---

### [29.03.2026] Reactive Graph Фаза 1: PostTradeAnalyser + PairContextBus + TSL очередь (DEV-90/92/93/94)

**Проблема:** система была полностью stateless — каждый проход по паре начинался с нуля.
Серийные прибыльные сделки (PIPPIN, A2Z) обнаруживались случайно, без памяти о паттерне.
Market Regime v2 оставался нереализованным несмотря на готовый спек.

**Решение (4 компонента):**
1. `classify_v2()` в `market_regime.py` — гибридный режим: Spike Guard + HH/HL структура (1h) + MTF. Shadow через конфиг.
2. `_post_tsl_queue` в `trade_simulator.py` — TSL событие → сохраняет impulse зону с TTL 8h. Основа для OTE Re-entry.
3. `core/context/pair_context.py` — `PairContextBus`: хранит cascade_count, avg_r_cascade, post_tsl_data per symbol.
4. `core/trading/post_trade_analyser.py` — реагирует на SL/TSL/TP через callback, обновляет PairContextBus. Shadow режим логирует divergence check и OTE зоны.

**Результат:** архитектура «Куб Метатрона» Фаза 1 построена. Система теперь помнит исход предыдущей сделки по паре. Следующий шаг — ARCH-61 спек → DEV-95 TriggerBus.

---

### [28.03.2026] Стратегический анализ: «Куб Метатрона» + каскадные сделки (TRADER сессия)

**Проблема:** Система работает как линейный пайплайн: данные → детекторы → решение → DB → забыто.
TSL не знает о пивотах. OTE detector не знает что пара только что закрылась по TSL. Cascade паттерн
(PIPPIN: 6 входов 0 SL, A2Z: 13 входов +86R) обнаружен случайно, а не целенаправленно.

**Решение:** Сформулировано стратегическое видение «Куб Метатрона» — полносвязная архитектура,
где каждый инструмент (ML, SMC, OTE, Regime, Post-Trade, Trigger) знает о состоянии всех остальных.
Ключевые концепции: Shared Context Bus (per-pair), Trigger System (событийный анализ vs. равномерный опрос),
Post-Trade Analyser (обработка после SL/TSL/TP). Записано в DISCUSSION.md (28.03.2026 ~23:45).

**Результат:** Два конкретных первых шага: TR-009 (R-gradient де-эскалация, бэктест +2.18R/trade),
TR-010 (OTE Re-entry после TSL). Остальные узлы уже построены в shadow mode — нужно соединить.

---

### [29.03.2026] TP Architecture: единый источник цели для всех путей (ARCH-58)

**Проблема:** Цель сделки (Take Profit) вычислялась не централизованно. Часть путей регистрации
сделок обходила функцию `get_tp_by_hierarchy()` и сохраняла TP с меткой `"atr_fallback_rr_3.0:4.2%"` —
трудночитаемой, без смысловой пользы. Путь "other_recs" (другие стратегии) вообще не искал пивотный TP.

**Решение:** 4 точечных изменения:
1. `recommendation_generator.py` — базовая метка `"atr_fallback"` (вместо `"atr_fallback_rr_3.0:4.2%"`).
2. `scan_loop.py` — ATR fallback в WL-breach тоже `"atr_fallback"`.
3. `monitoring.py` — other_recs теперь ищет пивотный TP через `get_tp_by_hierarchy()` перед записью в БД.
4. `intelligence_formatter.py` — добавлен маппинг `"atr_fallback"` → "ATR" для отображения в TG.

**Результат:** Все регистрируемые сделки теперь стараются найти пивотный TP. ATR-fallback — явный и однозначный,
позволяет фильтровать в аналитике: `tp_source LIKE 'pivot_%'`.

---

### [27.03.2026] Исправлен баг: weekly_bias не сохранялся в БД (DEV-56 bugfix)

**Проблема:** Weekly Bias Filter (DEV-56) вычислял `weekly_bias` (BULLISH/BEARISH) в `trading_intelligence.py`
и сохранял его в `recommendation.metadata`. Но `features_json` в БД собирается из отдельного словаря `extra_features`,
в который metadata не передавалась. В итоге за 3 дня наблюдения shadow mode не накопил ни одной записи в БД —
данных для включения production gate (DEV-58) не было.

**Решение:** В `bot/monitoring.py` добавлена явная передача трёх полей из metadata в extra_features:
`weekly_bias`, `weekly_context_score`, `weekly_gate_would_block`. Теперь каждая зарегистрированная сделка
содержит эти поля — можно анализировать WR по направлению биас.

**Результат:** DEV-58 (production gate) перенесён на ≈30.03–06.04 — потребуется новые 3-5 дней данных после рестарта.

---

### [23.03.2026] Запустили ML-предсказание исходов сделок (DEV-51)

**Проблема:** `OutcomePredictor` был написан, но не запускался — в окружении
отсутствовал `scikit-learn`. P(win) не вычислялся, ML-pipeline молчал.

**Решение:** Установили `scikit-learn`, добавили в `requirements.txt`.

**Результат:** Каждая новая сделка получает оценку P(win).
Текущий CV AUC ≈ 0.56 — чуть лучше случайного угадывания. Вырастет с накоплением данных.

---

### [23.03.2026] Исправлен timezone-баг в базе данных (DEV-49)

**Проблема:** Все сделки записывались с временем UTC+3 вместо UTC.
948 исторических сделок помечены как `data_quality=bug_timezone`.

**Решение:** Исправлен источник времени в `TradeSimulator` — теперь используется
`datetime.now(timezone.utc)`. Добавлен fallback для старых записей.

**Результат:** Новые сделки пишутся с правильным UTC. Старые помечены флагом
и исключены из обучения ML-моделей.

---

### [23.03.2026] Singleton PivotCalculatorFixed — снижена нагрузка на биржу (DEV-45)

**Проблема:** Каждый анализ символа создавал отдельный экземпляр `PivotCalculatorFixed`,
что приводило к ~600–1200 лишних запросов в час к бирже.

**Решение:** Один экземпляр на весь бот, передаётся во все компоненты через параметр.

**Результат:** Нагрузка на API BingX снизилась вдвое. Кеш пивотов теперь общий.

---

### [22.03.2026] Добавлен фильтр Watch List breach (DEV-32/41)

**Проблема:** Бот открывал LONG-сделки на активах в нисходящем тренде (`TREND_DOWN`),
что давало заведомо плохой ожидаемый результат.

**Решение:** Добавлен `regime_direction_block` — блокирует LONG при `TREND_DOWN`
и SHORT при `TREND_UP`. Исправлен code path для `watch_list_breach` сигналов.

**Результат:** 22 "плохих" позиции открытые до фикса постепенно закрываются по SL/TSL.
Новые сделки фильтруются корректно.

---

### [25.03.2026] L3 Фаза B: свежесть сигнала и CHoCH штраф (DEV-53)

**Проблема:** L3-checker (shadow mode, DEV-52) видел структуру рынка, но
не проверял свежесть WT сигнала и мягкие структурные конфликты (CHoCH).
Сигнал 3-часовой давности засчитывался так же как только что сгенерированный.

**Решение:** Добавлено два улучшения.

Условие 4: WT кросс должен быть свежим (≤3 баров 15m = 45 минут) И цена
вблизи пивота (< ATR×1.5). Данные о времени кросса теперь хранятся
в `wt_cross_bar_index` внутри SignalData.

CHoCH penalty: если 1h структура показывает CHoCH (изменение характера,
более слабый сигнал чем BOS) против направления — score снижается на -8.
BOS против направления блокирует жёстко, CHoCH — мягко.

---

### [25.03.2026] Исправлен баг при развороте тренда в каскадном TSL (DEV-67)

**Проблема:** Когда тренд разворачивался против открытой позиции,
каскадный TSL "забывал" что уже эскалировал до 4h и падал обратно на 15m.

Пример — DOT LONG: TSL эскалировал до 4h (trenddown=1.427). После разворота
тренда на DOWN — цикл эскалации не нашёл ни одного TF с совпадающим трендом
→ упал на entry TF (15m, trenddown=1.397). Сделка не закрылась.
На 4h цена давно пробила защитный уровень, но бот его не использовал.

**Решение:** Защитный fallback: если эскалация не нашла подходящий TF, но
в базе данных сохранён более старший TF (prev_tsl_tf) — использовать его
без проверки направления тренда. trenddown на 4h уже выше цены и защищает профит.

---

### [24.03.2026] Глобальный cap R:R = 3.0 для всех новых сделок (DEV-64A)

**Проблема:** Ряд сделок открывался с нереальным R:R — ATH RANGE SHORT с R:R=49,
COOKIE LONG R:R=69, KAVA SHORT R:R=23. Такие TP недостижимы в реальных условиях,
сделки гарантированно закрывались по SL после первого отката.

**Решение:** Глобальное ограничение `max_rr=3.0` применяется при регистрации
любой сделки. Если вычисленный R:R превышает порог — TP пересчитывается.
Также закрыт обходной путь через WL breach, который ранее игнорировал cap.

**Результат:** Сделки с R:R > 3.0 больше не регистрируются. Pivot_reversal,
который раньше давал WR=9.1% из-за RR=17-23x, теперь работает в реалистичном диапазоне.

---

### [24.03.2026] Блокировка контр-трендовых входов (DEV-64B)

**Проблема:** Система открывала LONG при `pivot_reversal` в режиме RANGE
и TREND_DOWN, а SHORT в TREND_UP — контр-тренд с заведомо плохим ожидаемым результатом.

**Решение:** `signal_regime_block` в конфиге — явный список запрещённых пар
(режим + направление). Блокируются на уровне регистрации сделки.

---

### [24.03.2026] Weekly Bias Filter: macro-контекст для каждой пары (DEV-56, ARCH-48)

**Проблема:** 23.03 было открыто 23 SHORT позиции когда цена находилась ВЫШЕ
Weekly Pivot Point → все закрылись по SL (-1R). Система не учитывала,
что "выше weekly PP" = бычий макро-контекст для пары, и SHORT там плохая идея.

**Принцип:** `цена > weekly PP` → бычий bias → торговать LONG.
`цена < weekly PP` → медвежий bias → торговать SHORT.
Исключение только у уровней R1/S1 (разворотные зоны).

**Статус:** Фаза A (shadow mode) — данные записываются в `features_json`
каждой сделки для последующего анализа. Фаза B (production gate) запланирована
на 27-29.03 после накопления 3-5 дней данных.

---

### [24.03.2026] Исправлен Breakeven когда TP1 был взят до запуска трекера (DEV-57)

**Проблема:** Если бот перезапускался после того, как TP1 уже был достигнут,
трекер не видел `tp1_hit_at` → `be_activated` оставалась 0 → позиция
не переводилась в безубыток. Пример: UMA id=3163, TP1 hit 15:00, SL 20:37.

**Решение:** Добавлена проверка `tp1_hit_at is not None` как безусловный
триггер BE для MULTI_TP стратегий, независимо от текущего R.

---

### [24.03.2026] Shadow mode: рыночный стресс-гейт (DEV-48, ARCH-42)

**Проблема:** Во время массовых SL (5+ за 30 минут) — признак рыночного события
(памп/дамп, ликвидации) — система продолжала открывать новые сделки.

**Решение:** Rolling window gate: если 5+ SL за 30 минут → блокировать
новые входы. Gate закрывается сам как только старые SL "протекли" из окна.
Запущен в shadow mode (только логирование).

---

### [24.03.2026] Guards для всех code-paths через register_trade_async() (DEV-44/46, ARCH-37)

**Проблема:** Проверки направления и режима (DEV-32/33) работали в `analyze_symbol`,
но WL breach и другие пути входа их обходили — попадали в БД контр-трендовые сделки.

**Решение:** "Второй рубеж" в `register_trade_async()` — дублирующая проверка режима
и направления. Срабатывает тихо (return None + INFO лог) только если первый уровень
пропустил. Порядок guards: Market Stress → Correlation → Regime → DEV-44 → DEV-52 → регистрация.

---

### [24.03.2026] L3 Фаза A: shadow mode для 6-условного чеклиста (DEV-52)

**Откуда:** TRADER описал 6 условий для "качественного" входа (TR-006 спек).
Реализовывать все сразу рискованно — лучше сначала понаблюдать.

**Что сделано:** Shadow mode — логирует сколько из 6 условий выполнено
для каждого сигнала. Условия 3 (1h структура не против), 5 (score ≥ 85),
6 (портфельный лимит). Не блокирует — только собирает данные.

---

### [23.03.2026] Correlation Guard: не открываем дубли коррелированных активов (DEV-38, ARCH-35)

**Проблема:** Bот мог одновременно открыть LONG PAXG/USDT и LONG XAUT/USDT —
по сути два входа на одном активе (оба = золото). Убыток умножается, а не диверсифицируется.

**Решение:** Список групп коррелированных активов в конфиге. При попытке открыть
сделку — проверяем, есть ли уже открытая из той же группы. Если есть — не регистрируем.

---

### [23.03.2026] Фильтры качества: сила сигнала, дедупликация, cooldown (Этап 5.1)

**Проблема:** Регистрировались слабые сигналы (strength < 50), дубли одного сигнала
за 30 минут, и сделки на парах сразу после SL-закрытия.

**Решение:** Три фильтра в `is_actionable`:
- `min_strength: 50` — слабые сигналы пропускаются
- `dedup_minutes: 30` — один сигнал на пару за период
- `sl_cooldown_hours: 4` — пауза после SL на паре

---

### [23.03.2026] Score modifier по Future Daily Pivot Point (DEV-36, ARCH-33)

**Смысл:** Future PP — это прогнозный уровень на следующий торговый день.
LONG ниже Future PP (в "discount") → более выгодная цена входа, score +5.
LONG выше Future PP (в "premium") → невыгодная, score -10. SHORT зеркально.

Дополнительно: если Weekly PP и Daily PP "противоречат" направлению → score -5.

---

### [23.03.2026] Pivot Proximity Filter: не входить далеко от пивотов (DEV-37, ARCH-34)

**Смысл:** Вход далеко от пивотных уровней — плохой тайминг. Пивоты — это зоны
где цена встречает поддержку/сопротивление. Далеко от них — в "воздухе".

**Реализация:** ATR-adaptive пороги (`tier1 = max(1.0%, ATR×1.5)`).
Умеренно далеко → score -10. Очень далеко (>tier1×2) → action=WATCH.
Shadow mode — первые дни только логирование.

---

### [23.03.2026] PIVOT_TOUCH staleness: штраф за старое касание пивота (DEV-55, ARCH-46)

**Проблема:** `check_pivot_touch()` засчитывал касание пивота если ЛЮБОЙ бар
в окне касался уровня. Сигнал от 10 баров назад (2.5 часа) выглядел как свежий.

**Решение:** `pivot_bar_index` в SignalData → penalty -10 если касание было
более 5 баров назад (75 минут). Сигнал остаётся, но с меньшим весом.

---

### [24.03.2026] MTF интерпретатор v2: фаза рынка и каскадные зоны (ARCH-50)

**Проблема:** MTF система считала "45% таймфреймов вверх" — число без контекста.
Коррекция в бычьем тренде и импульс вниз давали одинаковый процент, хотя это противоположные ситуации.

**Решение:** Добавлены структурные паттерны: `IMPULSE_UP/DOWN` (все TF согласованы),
`CORRECTION_UP_IN_BEAR` (4h идёт против 1d), `CASCADE_OS_REVERSAL` (2+ старших TF в перепроданности).
Phase detector смотрит на связку 1D+4H и делает вывод о фазе цикла.

**Результат:** Каждый сигнал получает контекст "фаза рынка" — видно не просто направление,
а ситуацию: откат в тренде (хорошая точка входа) или контртренд (опасно).

---

### [24.03.2026] Dynamic OS порог — shadow наблюдение 30 дней (ARCH-49)

**Проблема:** Бэктест на 15m показал: dynamic OS (порог -47 вместо фиксированных -60) даёт avg_R=+0.51
против avg_R=-0.18 у фиксированного. Результат значительный, но методология бэктеста вызывала сомнения.

**Решение:** Запущен shadow mode — логирует когда dynamic порог отличался бы от фиксированного,
без реального влияния на сделки. Критерии включения через 30 дней: n≥50 расходящихся случаев + WR>35%.

**Результат:** Накапливаем live-данные для объективного сравнения перед включением.

---

### [23.03.2026] wt_signal у пивота — буст силы сигнала +20 (DEV-41b)

**Проблема:** WT сигнал без пивота давал avg_R=+0.32. WT сигнал У пивота (±1%) — avg_R=+1.27.
Система не различала эти два случая — оба регистрировались с одинаковым весом.

**Решение:** Если `wt_signal` срабатывает в пределах 1% от Daily или Weekly пивота — strength +20.
Без дублирования с `confluence` (если confluence уже есть — не буcтим).

**Результат:** WT сигналы у пивотов статистически лучше отрабатывают и теперь получают больший вес.

---

### [23.03.2026] Запрет входов в HIGH_VOL режиме (DEV-33)

**Проблема:** В режиме `HIGH_VOL` (высокая волатильность, аномальный объём) Win Rate = 0%, avg_R = -0.25.
Система продолжала открывать сделки несмотря на явно плохую статистику.

**Решение:** `HIGH_VOL` добавлен в `blocked_regimes` в config. При определении режима HIGH_VOL
рекомендация переключается в WATCH — сделка не регистрируется.

**Результат:** Нулевой Win Rate режима устранён из статистики. Бот "знает когда не торговать".

---

### [23.03.2026] TSL стал мягче — меньше ложных выходов на откатах (DEV-34)

**Проблема:** ATR factor 1.25 давал слишком тесный TSL на волатильных парах — нормальный откат
на 1-2% закрывал позицию прежде чем тренд продолжался.

**Решение:** ATR factor снижен: `1.25 → 1.1`. Одна строка в config.yaml.

**Результат:** TSL даёт немного больше пространства для дыхания. Меньше закрытий на откатах.

---

### [23.03.2026] R:R cap 6.0 — первый ограничитель нереальных целей (DEV-35)

**Проблема:** PAXG TP=Monthly Pivot (24.6x R:R), CRCLX TP=32.1x — такие цели теоретически возможны,
но практически недостижимы. 100% сделок с R:R>10 закрывались по SL на первом откате.

**Решение:** Cap `max_rr=6.0` в `recommendation_generator.py`. При превышении TP пересчитывается.
Источник TP помечается `|capped_rr_6.0` для диагностики в логах.

**Результат:** Первый шаг к реалистичным целям. Позже снижен до 3.0 (DEV-64A) после анализа pivot_reversal.

---

### [22.03.2026] Watch List breach: автовход при пробое пивотного уровня (DEV-WL-BREACH)

**Смысл:** Если актив в Watch List и цена пробивает уровень пивота В НАПРАВЛЕНИИ
наблюдения — это триггер входа. Раньше нужно было ждать следующего полного анализа.

**Что реализовано:** `_handle_wl_breach_entry()` в `scan_loop.py` — при пробое строит
рекомендацию: SL = пробитый уровень ± 0.5%, TP = следующий пивот ≤5%, min R:R=1.5.
Gates: HIGH_VOL блок, SL cooldown, regime_direction_block, rate-limit 3/30мин.

---

### [22.03.2026] RANGE-специфичный cap + min_strength по режиму (DEV-61)

**Проблема:** RANGE режим = боковик. Открывать позиции с R:R=49 (как ATH SHORT)
в боковике — гарантированный SL. 69% открытых позиций были в RANGE.

**Решение:** `max_rr_range: 2.5` — более жёсткий cap специально для RANGE.
`min_strength_by_regime` — можно задать разный минимальный score по режиму.

---

### [22.03.2026] EXPIRED с прибылью → TSL вместо принудительного закрытия (DEV-62)

**Проблема:** 19 позиций за 7 дней закрылись по EXPIRED со средним +3.81R —
система принудительно закрыла прибыльные сделки по истечению TTL.

**Решение:** Tiered EXPIRED. Если позиция в TREND режиме и R ≥ 1.5 — не закрывать,
переводить в TSL режим и продолжать следить. Только невыгодные или RANGE позиции
закрываются по истечению времени.

---

### [22.03.2026] Двухступенчатый выход: TP1 фиксирует прибыль, TSL ведёт остаток (DEV-40)

**Проблема:** Единый TP был слишком далеко (часто 3–6R), большинство сделок его не достигало.
Позиции держались на жёстком стопе без промежуточной фиксации — либо всё, либо ничего.

**Решение:** Стратегия `DUAL_TP`: TP1 = 1×ATR от входа (ближняя цель, "half off"),
после TP1 hit — TSL защищает оставшуюся часть. `TRIPLE_TP_TSL` — тройной выход.
ATR таймфрейм маппится к entry TF: 15m→15m, 1h→1h, cap на 1h для старших.

**Результат:** Прибыль фиксируется раньше, остаток идёт на полный тренд. Психологически
и статистически лучше чем "всё или ничего" с далёким TP.

---

### [22.03.2026] MFE: видно сколько потенциала захватывает TSL (ARCH-50)

**Проблема:** Не было способа оценить насколько хорошо работает TSL. Закрылась по TSL — это
хорошо или мы упустили ещё 50% движения? Ответа не было.

**Решение:** Добавлены поля MFE (Maximum Favorable Excursion) в каждую сделку: `max_price`,
`min_price` (экстремумы за всё время жизни позиции), `max_R_possible` и `captured_R_pct`
(сколько % от максимально возможного движения захватил TSL).

**Результат:** Дашборд показывает реальную эффективность TSL. Пример: `captured_R_pct=68%` —
TSL захватил 68% от доступного движения, упустил 32%. Видно где TSL закрывает слишком рано.

---

### [24.03.2026] Оптимизация TASKS.md: навигационная таблица + архив (ARCH-52)

**Проблема:** TASKS.md разросся до 2074 строк — 55 выполненных задач смешаны с активными.
Найти нужную задачу = пролистать весь файл. Агентам тратилось время на чтение мёртвых записей.

**Решение:** Все 55 завершённых задач перенесены в [TASKS-ARCHIVE.md](TASKS-ARCHIVE.md).
В шапке TASKS.md добавлена навигационная таблица с номерами, статусами и ссылками.

**Результат:** TASKS.md похудел с 2074 до ~400 строк. Архив сохранён — история задач не потеряна.
Агенты теперь видят только активные задачи, навигация в один взгляд.

---

### [22.03.2026] Большой спринт: SMC layer, бэктестинг, ARCH-28 (сессии 7–10)

**Что было сделано:** Несколько сессий слились в один коммит. Ключевые изменения:
`OutcomePredictor` временно отключён (AUC=0.329 — хуже случайного), `min_strength_register` поднят 65→75
для снижения потока слабых сделок. SMC слой (`core/smc/`) подключён к pipeline.
Добавлена система бэктестинга (`backtesting_engine.py`, `test_indicators.py`, `strategy_comparison.py`).

**Результат:** Слабые сигналы отфильтрованы ещё до регистрации. ML будет переобучен после накопления
чистых данных. Бэктест позволяет проверять параметры на исторических данных без риска.

---

### [16.03.2026] wt_b_signal — новый тип сигнала на разворот (сессия 6)

**Проблема:** Стандартный WT сигнал срабатывал при любом пересечении. Не различались "слабый кросс"
и "B-сигнал" — особый паттерн WT когда вторая волна не уходит глубже первой (дивергенция по WT).

**Решение:** Реализован `wt_b_signal` с state machine (отслеживает паттерн через 2-3 бара).
Добавлен параметр `confidence` для всех сигналов — учитывает силу паттерна, не только пересечение.

**Результат:** Более качественные разворотные сигналы. Меньше ложных входов по слабым кроссам.

---

### [15.03.2026] Swing SL, безубыток и аналитика движения сделки (сессии 4–5)

**Проблема:** SL ставился только по ATR — без учёта структуры рынка. Безубыток не работал на практике
(BE activation был заглушкой). Непонятно как сделка двигалась до закрытия.

**Решение:**
- **Swing SL** теперь первый приоритет: SL = последний swing high/low, ATR как fallback
- **Breakeven** активирован: порог оптимизирован по БД — 0.5R → 0.8R (меньше ложных активаций)
- **first_profit_r / first_drawdown_r** — запись когда сделка впервые ушла в плюс/минус

**Результат:** Структурные стопы дают больше места тренду и реже выносятся "по шуму".
Аналитика движения позволяет понять характер каждой сделки.

---

### [14.03.2026] Разбивка монолита: bot/ + core/ + SMC структура (ARCH-01/02, DEV-01)

**Проблема:** `bot_with_subscriptions.py` (1500+ строк) и `trading_intelligence.py` (1800+ строк) —
оба монолита. Добавлять новое = рисковать сломать всё. Тесты практически невозможны.

**Решение:** Рефакторинг в 5 шагов: выделены `bot/handlers/`, `bot/loops/`, `bot/menus/`.
Тяжёлые методы `trading_intelligence.py` вынесены в `core/intelligence/`.
Добавлен `core/structure_detector.py` — определяет Swing H/L, CHoCH, BOS по 15m свечам.

**Результат:** Каждый модуль теперь тестируется отдельно. SMC-структура стала отдельным компонентом
и доступна всем частям системы.

---

### [13.03.2026] 4 торговые стратегии + MTF_BIAS как главный фильтр (сессия 3)

**Проблема:** Бот торговал всё подряд — один набор параметров для трендовых и разворотных ситуаций.
MTF анализ был вспомогательным, не основным.

**Решение:** Добавлены 4 стратегии (`STRAT-01..04`): Confluence, MTF_Bias, Conservative, Aggressive.
MTF_BIAS получил вес 0.50 — стал главным голосом в решении. WT кросс теперь обязателен в Confluence
(без него сигнал не выдаётся — устранён источник ложных сигналов).

**Результат:** Сигналы теперь имеют тип стратегии. Статистика считается отдельно по каждой.
Первые данные: Confluence WR=42%, MTF_Bias WR=38%, Conservative WR=51%.

---

### [12.03.2026] Централизация вычислений в indicators.py (большой рефакторинг)

**Проблема:** ATR, EMA, SMA, ADX, RSI, TSL, пивоты — каждый компонент считал по-своему.
ATR в одном месте = 14-периодный, в другом = 20-периодный. Баги из расхождений.

**Решение:** Все технические индикаторы централизованы в `core/indicators.py`. Один источник правды:
`compute_atr()`, `compute_ema()`, `compute_volatility()`, `calculate_trend()`.
Дублирующий код удалён из 6+ файлов.

**Результат:** Все компоненты используют одинаковые значения. Изменение параметра в одном месте
применяется везде. Меньше расхождений и трудных для поиска багов.

---

### [10.03.2026] Этапы 8.4-8.5: качество данных и стратегии (сессия 2)

**Что добавлено:**
- **8.4.1**: Проверка качества OHLCV до анализа — пустые данные или аномалии → пропуск пары
- **8.4.2**: `snapshot_time` — время сбора данных записывается в каждую сделку
- **8.4.4**: Дедупликация `(symbol, signal_type, direction)` — один тип сигнала на пару за период
- **8.4.5**: Hidden divergence фильтр — в RANGE/HIGH_VOL режиме скрытые дивергенции подавляются
- **8.5**: Strategy Pattern — confluence/mtf_bias/conservative как отдельные объекты с параметрами

**Результат:** Система перестала работать на мусорных данных. Дублирующие сигналы устранены.

---

### [09.03.2026] Confluence Scanner — первая версия (сессия 2)

**Идея:** Лучшие входы — когда несколько независимых сигналов совпадают в одной точке.
WT кросс + пивотный уровень + MTF согласование = confluence (конфлюэнция).

**Что реализовано:** `wt_15m_reversal_scanner.py` — ищет WT кросс вблизи пивота на 15m.
Dynamic SL/TP на основе swing levels. `tp1_price` как промежуточная цель.
Компактный форматтер сообщений (меньше текста, больше цифр).

**Результат:** Первый специализированный сканер конфлюэнций. База для всей дальнейшей работы с пивотами.

---

### [07-08.03.2026] Этапы 6–7: динамический TP, /scan, дашборд настроек (сессия 1)

**Этап 6 — Pivot TP:** TP теперь ставится на ближайший пивотный уровень в направлении сигнала
(не просто ATR × мультипликатор). `/intelligence SYMBOL` показывает эти уровни.

**Этап 7 — /scan и Watch List:** Команда `/scan` запускает анализ всех пар.
Результаты фильтруются — только сильные сигналы. Watch List — персональный список пар для мониторинга.
Подключён `RPredictor` — ML-модель для оценки ожидаемого R.

**Дашборд:** Вынесены все настройки бота на страницу `/settings`. Разделён порог алерта
(что показывать в TG) и порог регистрации (что писать в БД для ML).

**Результат:** Пользователь контролирует "чувствительность" бота без правки кода.

---

### [06.03.2026] Этап 5: фильтры качества, BTC-контекст, отчёты (сессия 1)

**5.1 — Фильтры качества:**
- `min_volume_usd: 1 000 000` — пары с объёмом < $1M не мониторируются
- `dedup_minutes: 30` — дедупликация одинаковых сигналов
- `sl_cooldown_hours: 4` — пауза после SL-закрытия на паре
- `min_strength: 50` — слабые сигналы игнорируются

**5.2 — BTC-фильтр:** Если BTC в сильном тренде вниз и сигнал LONG на альткоине —
дополнительный penalty (альты падают вместе с BTC).

**5.3 — Еженедельный отчёт:** Автоматический дайджест по понедельникам:
Win Rate, avg_R, лучшие/худшие пары за неделю.

---

### [04-05.03.2026] Рефакторинг: разбивка монолита на модули

**Проблема:** Весь бот жил в одном файле `bot_with_subscriptions.py`.
Меню, обработчики, логика, индикаторы — всё вместе. Невозможно тестировать и развивать.

**Решение:** 5 шагов рефакторинга: `bot/handlers/`, `bot/menus/`, `bot/loops/`,
`core/` для бизнес-логики, `web/` для дашборда.
`trading_intelligence.py` разбит на специализированные модули в `core/intelligence/`.

**Результат:** Каждый модуль можно читать и изменять независимо.
Структура проекта — такая как описана в CLAUDE.md.

---

### [03.03.2026] Первый запуск — бот начал работать

**Что было:** Telegram-бот с базовым анализом крипто-пар. Индикаторы WT (WaveTrend),
RSI, простые сигналы. SQLite база данных для пользователей и подписок.
Симуляция сделок — регистрация сигнала как "открытой позиции" с SL/TP.

**Стек:** aiogram + ccxt (BingX) + pandas + aiohttp (дашборд на localhost:8000).

**Результат:** Работающий прототип. Первые симулированные сделки в базе данных.

---

### [22.03.2026] Каскадный TSL: позиция удерживается дольше при сильном тренде (ARCH-51)

**Проблема:** 15m TSL слишком тесный на крупных трендовых движениях — закрывал позицию при
каждом нормальном откате, хотя тренд на 4h оставался сильным.

**Решение:** Каскадный алгоритм: после активации TSL проверяются старшие таймфреймы (1h → 4h).
Если тренд подтверждён на старшем TF — TSL переключается на него. Более широкий стоп даёт
пространство для дыхания и позволяет продержаться на тренде дольше.

**Результат:** На трендовых движениях `captured_R_pct` вырос. Актуальный баг (DEV-67): при
развороте тренда TSL "падает" обратно на 15m — исправляется отдельным фиксом.

---

### [29.03.2026] WsFeed + TSL pre-filter — WebSocket слой (DEV-99 продолжение)

**Проблема:** REST polling каждые 60 сек для 534 пар = нагрузка на API, медленный TSL-трекинг.
**Решение:** `core/infra/ws_feed.py` — WsFeed подписывается на BingX тикеры через ccxt.pro WebSocket. TSL-трекер получает цену из WS (instant), пропускает REST если цена далеко от SL/TP/TSL.
**Результат:** REST вызовы в trade_tracker снизятся на ~70% при спокойном рынке. WsFeed обновляет цены каждые секунды без опроса. После рестарта бота — подключение к WS автоматически.
