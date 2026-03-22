# Current State

## [22.03.2026 сессия 10] Агент: Developer
- ✅ ARCH-28 интегрирован: FVG + Pivot Confluence в `bot/monitoring.py`
  - После `analyze_symbol()`: берём `smc_context.fvg` + `pivot_cache[symbol]` → `find_fvg_pivot_confluences()`
  - Бонус strength если цена ВНУТРИ FVG зоны конфлюэнции (`fvg.bottom <= price <= fvg.top`)
  - Все зоны сохраняются в `features_json["fvg_confluences"]` для аналитики
- ✅ Планы почищены: удалены squishy-brewing-church.md (безубыток отменён) и replicated-crunching-spark.md (карта путей закрыта)
- ✅ MEMORY.md обновлён: правило русского языка + команда say

**Незакоммиченные изменения:**
- bot/monitoring.py (ARCH-28 интеграция)
- + все изменения из сессий 7-9 (smc_ob_pairs, chart_builder, FVG fix и др.)

## [22.03.2026 сессия 9] Агент: Developer
- ✅ smc_ob_pairs реализован полностью (BacktestConfig + run_backtest + run_bot_backtest + run_smc_experiment)
  - BacktestConfig.smc_ob_pairs: list = None — None=все, список=per-asset
  - run_bot_backtest() теперь принимает smc_ob_pairs и передаёт в BacktestConfig
  - run_smc_experiment.py: аргумент --ob-pairs для per-asset OB-фильтра
- ✅ TASKS.md обновлён — DEV→ARCH отчёт о реализации smc_ob_pairs
- ✅ 30-символьный бэктест завершён (task btzlnl2xq)
  - 23 из 30 символов (7 не найдено на Binance)
  - Медиана WR=43.4%, AvgR=0.10 — стратегия работает, edge мал
  - 0 символов с WR>50%; 8 с WR>45% (все крупные: ETH/AVAX/ADA/XRP/SOL/DOGE)
  - Мелкие альты (ICP/SHIB/TON/NEAR) убыточны: WR=34-37%, AvgR<0
  - Отчёт: data/universe_backtest_20260322_055259.json
  - Вывод в TASKS.md: нужен swing SL → подтверждает приоритет Каскадного SL

**Незакоммиченные изменения:**
- scripts/backtesting_engine.py (use_smc params + smc_ob_pairs в run_bot_backtest и BacktestConfig)
- scripts/run_smc_experiment.py (новый файл + smc_ob_pairs + --ob-pairs CLI)
- core/smc/fvg.py (п.7 fix: start_bar = fvg.index + 1)
- bot/monitoring.py (п.6 Вариант C: require_pivot_tp)
- config.yaml (require_pivot_tp)
- scripts/run_universe_backtest.py (новый файл)
- scripts/universe_builder.py (новый файл)
- scripts/multi_source_ohlcv.py (новый файл)

**Следующие задачи:**
1. Дождаться результатов 30-символьного бэктеста (btzlnl2xq) → отчёт в TASKS.md
2. Каскадный SL (план в plans/squishy-brewing-church.md) — Этап A не начат
3. Коммит всех изменений текущего спринта

## [22.03.2026 сессия 8] Агент: Developer
- ✅ п.4 (infrastructure): run_universe_backtest.py запущен
  - 3-символьный тест (ETH/SOL/BNB, Binance 2023-2024): WR=46.8% (медиана), AvgR=0.10
  - 30-символьный тест запущен, не дождался завершения (~1-2ч). Данные закэшированы.
  - Отчёт: data/universe_backtest_20260322_003503.json
- ✅ п.5: SMC эксперимент cfg1/cfg2/cfg3 (ETH/SOL/BNB, Binance 2023-2024)
  - scripts/run_smc_experiment.py — новый файл
  - run_bot_backtest() — добавлены параметры use_smc, smc_require_ob, smc_require_fvg
  - ETH: OB-фильтр даёт WR+5.4% (47.7%→53.1%), AvgR+0.200. SOL/BNB — не помогает.
  - Отчёт: data/smc_experiment_20260322_012439.json
- ✅ п.6: Confluence без pivot TP → skip (Вариант C)
  - bot/monitoring.py: если require_pivot_tp=true и pivot_result=None → recommendation=None
  - config.yaml: trading.sl_tp.require_pivot_tp: false (по умолчанию выключен)
- ✅ п.7: FVG immediate mitigation fix
  - core/smc/fvg.py: start_bar = fvg.index + 2 → fvg.index + 1
  - Тест подтверждён: немедленная mitigation детектируется корректно

## [22.03.2026 сессия 7] Агент: Developer
- ✅ DEV-35 п.1: data_source="binance" добавлен в BacktestConfig + __init__
  - ccxt_async.binance({'enableRateLimit': True}) при data_source=="binance"
  - _to_source_symbol(): binance → spot формат (как cryptocom)
- ✅ DEV-35 п.2: scripts/universe_builder.py — выборка топ-200 для бэктеста
  - CoinGecko /coins/markets → топ-250, кэш 24ч в data/universe_cache.json
  - Фильтр: стейблы, wrapped, BTC, тикеры >10 символов. ETH включён.
  - Стратификация 10+10+10, random.Random(seed) — воспроизводимо
  - CLI: python scripts/universe_builder.py --n 30 --seed 42
- ✅ DEV-35 п.3: scripts/multi_source_ohlcv.py — автовыбор источника
  - PRIORITY = ["binance", "cryptocom", "bingx"]
  - probe_earliest_date() — параллельный probe всех источников
  - MultiSourceOHLCV.fetch() — авто-выбор + SQLite кэш + exchange
  - Context manager, CLI

## [22.03.2026 сессия 6] Агент: Developer
- ✅ DEV-35: Crypto.com как альтернативный источник данных для бэктеста
  - BacktestConfig: data_source: str = "bingx" (варианты: "bingx", "cryptocom")
  - __init__: при data_source=="cryptocom" создаёт ccxt.cryptocom(enableRateLimit=True)
  - _to_source_symbol(): BingX→"BTC/USDT:USDT" (swap), Crypto.com→"BTC/USDT" (strip ':USDT')
  - _cache_symbol_key(): f"{data_source}:{source_symbol}" — уникальные ключи без коллизий
  - _fetch_ohlcv_swap: использует source_symbol и cache_key вместо swap_symbol
  - Rate limit 100410 retry — только для BingX (data_source=="bingx")
  - Глубина истории: Crypto.com с 2018 vs BingX только с даты листинга

## [22.03.2026 сессия 5] Агент: Developer
- ✅ DEV-34: SMC интеграция в backtesting_engine
  - BacktestConfig: use_smc, smc_require_ob, smc_require_fvg, smc_ob_tf
  - analyze_smc() per-bar (1 раз, до inner-loop по сигналам)
  - Фильтр 6: OB ±0.5% от цены + FVG presence
  - BacktestTrade.smc_ob / smc_fvg флаги
  - _calc_smc_stats(): ob/fvg/ob_fvg статистика WR и avg_R

## [22.03.2026 сессия 4] Агент: Developer
- ✅ DEV-33: leverage параметр в BacktestConfig + комиссия наконец применяется
  - BacktestConfig: leverage: int = 1
  - _trade_pnl(): position_size = margin × leverage, commission round-trip
  - calculate_metrics(): Sharpe/drawdown/profit_factor на account-level returns
  - Liquidation guard: убыток не превышает margin

## [22.03.2026 сессия 3] Агент: Developer
- ✅ DEV-32: OHLCV SQLite кэш для бэктеста
  - scripts/ohlcv_cache.py: OHLCVCache + get_cache() singleton
  - backtesting_engine.py _fetch_ohlcv_swap: cache HIT/PARTIAL/MISS с инкрементальным обновлением
  - Файл кэша: ohlcv_cache.db в корне проекта
- ✅ DEV-21 расширение: SMC строка + PIVOT_CONFLUENCE строка в intelligence_formatter.py

## [22.03.2026 сессия 2] Агент: Developer
- ✅ DEV-21 расширение: SMC + PIVOT_CONFLUENCE строки в intelligence_formatter.py
  - format_intelligence_message(): SMC блок `📐 SMC: 🟢 BULLISH | OB+FVG ✅ | OTE ✅`
    (из recommendation.metadata["smc_context"] dict, только если есть значимые факторы)
  - format_signal_message(): PIVOT_CONFLUENCE строка `📐 Конфлюэнция: 1W_S1+1D_S1≈0.949`
    (из data["pivot_confluence"], заполняется ARCH-27 в wt_15m_reversal_scanner)
  - _REVERSAL_FACTOR_INLINE: добавлен "PIVOT_CONFLUENCE": "📐 Конфл."
- ✅ DEV-30: pivot SL = level_price × 0.997/1.003 (Вариант A, EV=0.256 vs 0.115 baseline)
  - core/pivot_reversal.py: _sl_long_pivot/_sl_short_pivot, sl_source = f'pivot_{level_name}:0.3%'
- ✅ DEV-31b: mtf_alert убран (WR=4.4%, 137 сделок)
- ⚠️ Требует перезапуска бота

## [22.03.2026] Агент: Developer
- ✅ DEV-31b: mtf_alert убран из TG и регистрации
  - config.yaml: `signals.mtf_alert_enabled: false`
  - bot/monitoring.py: guard `if not mtf_alert_enabled: return` в check_mtf_alerts()
- ✅ DEV-28b: cascade_tsl_deescalation_r уже был 2.5 (сделано ранее)
- ⚠️ Требует перезапуска бота

## [21.03.2026 сессия 3] Агент: Developer
- ✅ ARCH-26: Gate по 4h WT momentum в wt_15m_reversal_scanner.py
  - LONG блокируется если 4h wt1 < wt2 (DOWN direction)
  - SHORT блокируется если 4h wt1 > wt2 (UP direction)
  - 4h данные записываются в data_long/data_short (mtf_4h_trend/wt/zone)
  - Удалён дублирующий post-processing 4h блок (строки ~373-389)
  - config.yaml: добавлен `4h_gate_enabled: true` в analysis.confluence
  - 574 тестов passed, 1 pre-existing fail (aiogram)
- ✅ DEV-21: Унификация форматирования — mtf_bias_message() и reversal_message() стали thin wrappers над format_signal_message()
  - Plugin-архитектура: специфичные блоки (mtf_bias, reversal) встроены в унифицированный скелет
  - _mtf_context_lines() — новый helper с ⚠️ против тренда
- ✅ DEV-31: MTF_SIGNAL удалён из 15+ файлов

## [21.03.2026 сессия 2] Агент: Developer
- ✅ DEV-30: WT momentum вместо ATR trailing stop в mtf_checker.py, signal_checkers.py, wt_15m_reversal_scanner.py
- ✅ DEV-31: MTF_SIGNAL полностью удалён из кодовой базы
  - keyboards.py: удалена кнопка "🔄 MTF анализ" из ReplyKeyboard и InlineKeyboard
  - menus/handler.py: убраны "MTF анализ" из _detect_menu_type
  - Ранее: check_mtf_signals(), вес, вызовы, меню, подписки, стратегии, тесты
- ✅ README.md: полностью переписан (таблица сигналов с специализацией, актуальная архитектура, TSL, ML, параметры config.yaml)
- ✅ config.yaml: sl_cooldown 0.75→4.0h, min_strength_register 40→65, confluence confidence 0.55→0.68
- ⚠️ Требует перезапуска бота: config.yaml + core/*.py (mtf_checker, signal_checkers, wt_15m_reversal_scanner)

## [21.03.2026] Агент: Developer
- ✅ Сделано: DEV-31 завершён — MTF_SIGNAL полностью удалён из кодовой базы
  - Удалены: check_mtf_signals(), вес, вызовы, меню, подписки, стратегии, тесты
  - Сохранено: SignalType.MTF_SIGNAL в enum (DB backward compat)
  - 105 тестов → все passed
- ✅ Сделано: ARCH-17 шаги 8-10 завершены в предыдущей сессии (SMCContext интеграция)
- ⬜ Следующее: ответить на вопрос пользователя о POB и DEMAND в SMC

---

## [21.03.2026] Диагностика WR коллапса — confluence flood

### 🔴 Проблема
WR упал с 20% (14.03) до 0.9% (20.03) и продолжает падать.
Статистика: WR=21.9%, TP=134, TSL=460, SL=2122. Сделки выходят по SL в первые ~200 минут.

### 📊 Корневые причины (по данным БД)

**1. Флуд confluence сделок**
- 108-113 confluence сделок/день (19-20.03) vs ~45 раньше
- confluence WR=18.7% всего (из 1510 сделок), за 19-21.03 = 0.9-1.8%
- `min_strength_register: 40` — слишком низкий, всё мусорное проходит

**2. sl_cooldown слишком мал**
- `sl_cooldown_hours: 0.75` (45 минут) — пара после SL сразу возвращается в торговлю
- Цикл: SL → 45 мин → новый сигнал → SL → повтор

**3. confluence min_confidence слишком мягкий**
- `confluence: 0.55` — не отсекает слабые сигналы
- WR=13% даже на strength 60-80 (757 сделок)

**4. mtf_bias использовал ATR тренд** (исправлено 21.03)
- `collect_mtf_data` использовал `calculate_trend` (ATR trailing stop) для MTF alignment
- Лагающий индикатор → ложные сигналы при разворотах
- Исправлено: `trend = "UP" if wt1 > wt2 else "DOWN"`

### ✅ Рекомендуемые изменения config.yaml
```yaml
signal_quality:
  min_strength_register: 65    # было 40 — убрать мусор
  sl_cooldown_hours: 4.0       # было 0.75 — защита от повторных SL

analysis:
  signals:
    min_confidence_by_type:
      confluence: 0.68          # было 0.55 — отсечь слабые
```

### ✅ Статус
- `config.yaml` применён: min_strength_register=65, sl_cooldown=4h, confluence confidence=0.68
- `core/mtf_checker.py`: trend = WT momentum (wt1>wt2) вместо ATR trailing stop
- Требуется рестарт бота

### 🔄 Задачи в TASKS Backlog (21.03.2026)
- **ARCH-25** — Унификация пивотных расчётов (единый `_find_all_confluences`)
- **ARCH-26** — Gate по 4h тренду в Confluence (убрать контртрендовые входы)
- **ARCH-27** — Конфлюэнция пивотов в Confluence сканере (приоритет уровней)
- **DEV-30** ✅ ГОТОВО — WT momentum в MTF_SIGNAL + wt_15m_reversal_scanner (1h и 4h контекст)

---

## [20.03.2026] Агент: Architect — ARCH-17 SMC Layer (ВСЕ 10 ШАГОВ ГОТОВЫ)

### ✅ Сделано
- **ARCH-17 шаги 1-7:** полный пакет `core/smc/` (6 модулей + models + __init__)
  - `swing_points.py` — Swing H/L с чередованием H-L-H-L, классификация HH/HL/LH/LL, структурный тренд
  - `fvg.py` — Fair Value Gaps: detection + mitigation tracking + consecutive join + min_size filter
  - `structure.py` — BOS/CHoCH: multi-bar confirmation по close, Breaker Blocks, active support/resistance
  - `order_blocks.py` — Order Blocks: последняя противотрендовая свеча перед BOS/CHoCH, volume ratio, FVG overlap
  - `liquidity.py` — Кластеры ликвидности: buy-side/sell-side, sweep tracking, strength по swing_count
  - `fibonacci.py` — OTE зона 0.618-0.786, полный набор Fib уровней, price_in_ote
  - `models.py` — SMCContext dataclass: 19 derived properties, `to_features()` для ML, `summary()` для логов
  - `__init__.py` — экспорт: `analyze_smc()`, `SMCContext`
- **44/44 тестов** в `tests/unit/test_smc_layer.py`
- **docs/SMC_LAYER.md** — подробная документация (архитектура, алгоритмы, примеры, ML-фичи)

- **ARCH-17 шаги 8-10:** интеграция SMC в пайплайн
  - `MarketContext.smc_context` — новое поле в `core/signal_models.py`
  - `analyze_smc(df_entry)` вызывается в `analyze_symbol()` после OHLCV
  - 19 SMC-фичей (`smc_*`) добавляются в `features_json` через `trade_simulator.py`
  - SMC бонусы: ReversalStrategy (CHoCH +0.05, OB+FVG +0.07, OTE +0.04), TrendFollowing (BOS +0.04, OTE +0.05, OB+FVG +0.06)
  - SMC OB-based SL (приоритет 2.5 между FVG и TSL) в `recommendation_generator.py`

---

## [20.03.2026] Агент: Developer — DEV-12 шаги 8.4.7–8.4.9 ЗАВЕРШЕНЫ

### ✅ Сделано
- **8.4.7 Confidence Calibrator:** `core/intelligence/confidence_calibrator.py` (новый)
  - `ConfidenceCalibrator.fit(db_path)` — isotonic/platt/bin-based по 20+ сделок
  - `calibrate(raw_confidence)` → откалиброванная вероятность TP
  - `reliability_curve()` → bins для дашборда, `calibration_error()` → ECE
  - `summary_text()` → TG-форматированный отчёт (топ-3 перекоса)
  - Интегрирован в `OutcomePredictor`: `calibrate_confidence()` метод, автообучение в `fit()`
- **8.4.8 Replay Decisions:** `scripts/replay_decisions.py` (новый)
  - `python scripts/replay_decisions.py [--days N] [--status SL]`
  - Анализ фильтров, MTF-множителей, ML-корректировок, WR по signal_type/regime
  - Graceful fallback: если decision_trace_json не заполнен — поясняет почему
- **8.4.9 Auto-review loop:** `auto_review_loop()` в `bot/loops/ml_loop.py`
  - Раз в 7 дней: WR по signal_type + regime drift + ECE + общая сводка
  - Логирует + отправляет администратору в TG
  - Зарегистрирован в `bot/core/bot.py` через `asyncio.create_task`

### 🔄 Следующие задачи
- **ARCH-17** SMC Layer — спроектировано, не реализовано (задача для ARCH)
- **DEV-29** SMC Phase 2 (Order Block + Fibonacci) — после ARCH-17
- **ARCH-24** ML на MTF фичах — после 300+ MTF-сделок

---

## [20.03.2026] Агент: Developer — Ревизия ROADMAP + TASKS

### ✅ Сделано
- ROADMAP.md: Этап 11 → ✅ (ARCH-13 был ✅ ГОТОВО ещё с 16.03)
- ROADMAP.md: история 19-20.03 дописана (DEV-23, DEV-26/27/28/21, UX-19.03a/b)
- TASKS.md: 3 новые задачи в Backlog:
  - **DEV-29** — SMC Phase 2 (Order Block + Fibonacci 0.618 + smc_strategy)
  - **ARCH-23** — Strategy Pattern Phase 2 (EnsembleStrategy + RuleEngine + hot-reload)
  - **ARCH-24** — ML на MTF фичах (шаг 5 Этапа 10, ждёт 300+ MTF-сделок)
- TASKS.md: таблица ✅ ГОТОВО дополнена DEV-19/20/22/23/24/28/21

### 🔄 Следующие задачи (по приоритету)
1. **DEV-12** шаги 8.4.7–8.4.9 (Confidence calibrator, replay, auto-review) — уже в В РАБОТЕ
2. **ARCH-17** SMC Layer — спроектировано, не реализовано
3. **DEV-29** SMC Phase 2 (после ARCH-17)
4. **ARCH-24** ML на MTF фичах (после 300+ сделок)

---

## [20.03.2026] Агент: Developer — DEV-21 (Unified Message Generator)

### ✅ Сделано
- **DEV-21:** `format_signal_message()` добавлена в `core/intelligence_formatter.py` (конец файла)
  - Поддерживает типы: `confluence`, `wt_b_signal`, `mtf_bias`, `pivot_reversal`, `wt_signal`
  - Стандартные секции: заголовок · шкала · блок типа · MTF контекст · пивот · дивергенция · футер
  - Хелперы: `_fire()`, `_mtf_trend_line()`, `_SIGNAL_TYPE_ICON`, `_REVERSAL_FACTOR_EMOJI`
  - Старые функции (`reversal_message`, `wt_b_message`, `mtf_bias_message`) — **ещё не обновлены** как thin wrappers (следующий шаг)
- TASKS.md: DEV-21 → ✅ ГОТОВО

### 🔄 Следующий шаг
- DEV-12 шаги 8.4.7–8.4.9 (Confidence calibrator, replay tests, auto-review metrics)
- Опционально: обновить `reversal_message` / `wt_b_message` / `mtf_bias_message` как thin wrappers вокруг `format_signal_message`

---

## [20.03.2026] Агент: Developer — DEV-28 (Двунаправленный cascade TSL)

### ✅ Сделано
- **DEV-28:** Де-эскалация каскадного TSL при истощении импульса
  - `core/trade_simulator.py` — блок `cascade_tsl` расширен:
    - Читает `tsl_degraded` из `features_json` сделки
    - Если `tsl_degraded=True` → не эскалирует (использует сохранённый ТФ)
    - Если нет → нормальная эскалация, затем проверка де-эскалации:
      1. `current_r >= cascade_tsl_deescalation_r` (default 5.0)
      2. WT на текущем TSL-ТФ в зоне (OS для SHORT, OB для LONG)
      3. TSL на младшем ТФ тесней (SHORT: trendup ниже; LONG: trenddown выше)
    - При де-эскалации: записывает `tsl_degraded=True` в features_json, обновляет tsl_tf
    - Лог: `[cascade_tsl] SYMBOL: de-escalate 4h → 1h (R=X.XR, WT=Y.Y, TSL tight)`
  - `config.yaml` — новый ключ `trading.cascade_tsl_deescalation_r: 5.0`

### ⚠️ Важно
- Порог 5.0R — консервативный, только на больших сделках (+10R типа #2341)
- Требует накопления данных для валидации порога (50+ сделок с cascade_tsl)
- `tsl_degraded` хранится в `features_json` (не новая колонка)

---

## [19.03.2026] Агент: Developer — DEV-23 (Динамические пороги OB/OS)

### ✅ Сделано
- **DEV-23:** Shadow mode для динамических порогов OB/OS
  - `core/dynamic_thresholds.py` (новый): `compute_dynamic_thresholds(wt1_series, k, window)` — mean±k*std
  - `core/wt_15m_reversal_scanner.py`: рефакторинг — инлайн-код заменён вызовом модуля; импорт `os_method_label`; `_dyn_computed` флаг
  - `core/signal_checkers.py` `check_wt_signals`: shadow-mode блок — считает dynamic thresholds при `dynamic_os_enabled=True`, логирует diff vs fixed, добавляет `os_method` ("fixed"/"dynamic"/"both") в `sig.data` — gate не изменён (по-прежнему `wt1_last < os_`)
  - config: `dynamic_os_enabled: false` (уже было), shadow только при `true` — не трогать до backtesting

### 🔄 Следующие задачи
- Запустить бэктест с `dynamic_os_enabled: true` на исторических данных для сравнения WR по `os_method`
- Посмотреть на следующую задачу из TASKS.md

---

## [19.03.2026] Агент: Developer — DEV-22 (WATCH LIST)

### ✅ Сделано
- **DEV-22:** WATCH LIST — автоматическое наблюдение + эскалация
  - `core/signal_watch_list.py` (новый) — `SignalWatchList`:
    - `add()`, `has()`, `remove()`, `check_escalation()`, `check_breach()`, `check_against_direction()`, `cleanup_expired()`, `get_all()`
    - TTL 4h (из конфига `watch_list_ttl_hours`)
    - Эскалация: score+5, новая дивергенция, MTF сдвинулся
    - Пробой: price < pivot_level * (1 - breach_pct%) для LONG
  - `bot/core/bot.py` — `self.signal_watch_list = SignalWatchList(ttl_hours=4)`
  - `bot/monitoring.py` — интеграция в `_broadcast_intelligence_alert`:
    - action=WATCH → add/update in WL
    - already in WL → check_escalation → if True → override action=BUY/SELL
  - `bot/loops/scan_loop.py` — в scan_one: check_breach каждый цикл; cleanup_expired каждый цикл
  - `bot/handlers/core_handlers.py` — команда `/wl`
  - `config.yaml` — новые ключи: `watch_list_ttl_hours`, `watch_list_breach_pct`

---

## [19.03.2026] Агент: Developer — DEV-20 (BUG pivot timezone)

### ✅ Сделано
- **DEV-20:** Фикс дневного пивота — неверная свеча (0.27% смещение)
  - `core/pivot_calculator_fixed.py` — `get_daily_pivots()`:
    - Заменён datetime-фильтр (`df["datetime"] >= ...`) на ms-int фильтр (`df["time"] >= prev_start_ms`)
    - Добавлен fallback для close-timestamp (BingX может отдавать `time = today_ms`)
    - Добавлен `[daily_pivot]` DEBUG-лог с H/L/C/dt выбранной свечи
    - INFO-лог расширен: показывает R1, S1, candle datetime UTC
    - 1h-fallback тоже исправлен: убран `_df_with_datetime`, прямое ms-сравнение

---

## [19.03.2026] Агент: Developer — DEV-19 завершён

### ✅ Сделано
- **DEV-19 закрыт:** Confluence State Machine переписан под wt_15m_reversal_scanner
  - `core/confluence_state_machine.py` — новая логика:
    - Убраны `_SCORE_PP_CONFIRM`, `_SCORE_TREND_1H`, `_SCORE_DUAL_CROSS`
    - Импортированы из wt_15m_reversal_scanner: `_SCORE_WT_CROSS_IN_ZONE(25)`, `_SCORE_TSL_CROSS(25)`, `_SCORE_PIVOT_TOUCH(25)`, `_SCORE_DIVERGENCE(20)`
    - Новый `_step()`: TSL_CROSS/NEAR_PIVOT/DIVERGENCE объединены — накапливают опциональные факторы, WT_CROSS — финальный триггер
    - `pivot_touch_pct: 0.15%` (было `pivot_proximity_pct: 0.5%`)
    - `cross_fresh_bars: 8` (было 10)
    - Разделены окна: 50 баров для divergence/pivot detection, 8 баров для TSL/WT кросса

---

## [19.03.2026] Агент: Developer — DEV-18 скелет

### ✅ Сделано
- **DEV-18 закрыт (скелет):** Multi-Agent System
  - `core/agents/base.py` — `BaseAgent`, `AgentContext`, `AgentResult`
  - `core/agents/scout.py` — `ScoutAgent` stub (Phase 3: LLM с MTFContext как tools)
  - `core/agents/risk.py` — `RiskAgent` stub (Phase 3: portfolio-aware risk check)
  - `core/agents/analyst.py` — `AnalystAgent` работающий (оборачивает TradeAnalyzer/DEV-15)
  - Phase 3 реализация: после стабилизации архитектуры + Claude Agent SDK

---

## [19.03.2026] Агент: Developer — DEV-17 завершён

### ✅ Сделано
- **DEV-17 закрыт:** Isolation Forest anomaly detection
  - `core/anomaly_model.py` (новый) — `AnomalyModel`:
    - 5 признаков: volume_zscore, price_change_pct, price_volatility, hl_spread, volume_ma_ratio
    - `fit(df)` — ленивое обучение на последних 200 барах (n_estimators=50, contamination=0.05)
    - `score(df)` → float (-1..+0.3), `anomaly_strength(score)` → 0..100
    - Не заменяет rule-based — дополняет: блендинг 60%+40%
  - `core/signal_checkers.py` — per-symbol `_anomaly_models` кеш, ленивая инициализация
  - Включается через `detectors.anomaly.use_isolation_forest: true` (default)
  - Fallback на sklearn absent: rule-based без изменений

---

## [19.03.2026] Агент: Developer — DEV-16 (скелет)

### ✅ Сделано
- **DEV-16:** RL Exit Strategy скелет создан
  - `core/rl_exit_agent.py` — `RLExitAgent` stub: `predict()` → HOLD, `train()` → заглушка с TODO
  - `mfe_ready_count(db_path)` + `is_rl_ready()` — data readiness check (~2375 из 3000)
  - `core/performance_engine.py` → `mfe_ready_count()` добавлен
  - Полная реализация PPO — задача ARCH после накопления данных
- Статус: 🕐 ЗАБЛОКИРОВАНО (нужно ещё ~625 MFE-сделок)

---

## [19.03.2026] Агент: Developer — DEV-15 завершён

### ✅ Сделано
- **DEV-15 закрыт:** LLM-разбор SL-сделок (Claude API)
  - `core/trade_analyzer.py` (новый) — `TradeAnalyzer`:
    - `analyze_sl_trade(trade_id)` — читает features_json + decision_trace_json → строит prompt → вызывает claude-haiku-4-5 → сохраняет в `trade_analysis`
    - Ленивая инициализация: если нет ANTHROPIC_API_KEY → тихо отключается
    - `anthropic.enabled: false` в config отключает полностью
  - `core/subscription_manager.py` — миграция таблицы `trade_analysis` (trade_id, analysis, model, prompt_tokens, created_at)
  - `core/trade_simulator.py`:
    - `_trade_analyzer` + `_trade_analyzer_init` в `__init__`
    - `_get_trade_analyzer()` — ленивая инициализация
    - В `check_open_trades_with_tsl` после `close_trade(STATUS_SL)` → `asyncio.create_task(analyzer.analyze_sl_trade(trade_id))`

### 📝 Активация
Требуется `ANTHROPIC_API_KEY` в окружении или `anthropic.api_key` в config.yaml.
`pip install anthropic` если не установлен.

---

## [19.03.2026] Агент: Developer — DEV-14 завершён

### ✅ Сделано
- **DEV-14 закрыт:** Correlation Guard
  - `config.yaml` → `trading.max_positions_per_direction: 5` (0 = отключено)
  - `core/trade_simulator.py` → в `register_trade()` после dedup-блока:
    `SELECT COUNT(*) WHERE status='OPEN' AND direction=?` → если ≥ лимита → лог + `return None`
  - Защита от 29 SHORT одновременно при памп-сценарии

---

## [19.03.2026] Агент: Developer — DEV-27 завершён

### ✅ Сделано
- **DEV-27 закрыт:** Rolling WR degradation detector
  - `core/performance_engine.py` → `rolling_win_rate(window=50)` + `check_wr_degradation(warn=40%, critical=30%)`
  - `bot/loops/ml_loop.py` → `wr_health_check_loop` (каждые 6ч, 5мин задержка при старте)
    - warn < 40%: WARNING лог
    - critical < 30%: CRITICAL лог + TG уведомление всем подписчикам
  - `bot/core/bot.py` → `create_task(wr_health_check_loop(self))`
  - Пороги из config: `monitoring.wr_check_window`, `wr_warn_threshold`, `wr_critical_threshold`

### 📊 Следующий приоритет (для ARCH агента)
**ARCH-18** 🔴 ВЫСОКИЙ — pre-compute df в scan_one, убрать 45m из mtf_checker

---

## [19.03.2026] Агент: Developer — DEV-26 + ARCH-18/22 добавлены

### ✅ Сделано
- **DEV-26 закрыт:** Per-signal-type confidence thresholds
  - `config.yaml` → `analysis.signals.min_confidence_by_type`: wt_b=0.50, wt/pivot=0.52, confluence/mtf_bias=0.55, anomaly=0.60
  - `core/trading_intelligence.py` → confidence gate использует тип доминирующего сигнала (max strength из `supporting_signals`)
- **ARCH-18 формализована** в Backlog: pre-compute индикаторов в scan_one (8400 дублирующих вычислений/цикл → 1 вычисление)
- **ARCH-22 добавлена** в Backlog: автокалибровка per-signal-type порогов из реальных WR данных

### 📊 Следующий приоритет (для ARCH агента)
**ARCH-18** — 🔴 ВЫСОКИЙ — pre-compute df в scan_one, убрать 45m из mtf_checker, 6 TF набор

---

## [19.03.2026] Агент: Developer — DEV-25 завершён

### ✅ Сделано
- **DEV-25 закрыт:** `config.yaml` → `analysis.signals.min_confidence: 0.50 → 0.55`
  - Хотфикс от 19.03 (снизили для BSB confidence=0.547) откачен обратно
  - DEV-13 завершён, OutcomePredictor обучается на чистых типах → порог можно вернуть

### 📊 Следующий приоритет
**ARCH-19** (для ARCH агента) — дифференцированные MTF множители в `_apply_mtf_context()`
**DEV-26** — per-signal-type confidence thresholds (зависит от DEV-25 ✅)

---

## [19.03.2026] Агент: Developer — DEV-24 завершён

### ✅ Сделано
- **DEV-24 закрыт:** WT-B Signal реанимирован (WR=85%)
  - `core/message_builder.py` — добавлен `wt_b_message()` (синяя 🔵 карточка, 1h ТФ)
  - `bot/loops/scan_loop.py` — секция 5: вызов `check_wt_b_signals(sym, df_1h)` + broadcast
  - `core/trading_intelligence.py` — вес `WT_B_SIGNAL`: 0.15 → 0.35
- WT-B теперь: при strength=80 → 80×0.35=28 (ещё не 60, но strength сигнала обычно 70-90 из бэктеста)
  - Правильный путь: через `analyze_symbol` → MTF filter → регистрация

### 📊 Следующий приоритет
**ARCH-19** — дифференцированные MTF множители в `_apply_mtf_context()` (interim if-else):
- noise → ×0.40, div+score≥65 → ×0.75, senior_reversal → ×1.00
Ждёт ARCH агента.

**DEV-25** — `min_confidence: 0.55` — заблокирована, нужно ≥300 чистых записей (сейчас ~152).

---

## [19.03.2026] Агент: Developer — DEV-13 + DEV-15 завершены

### ✅ Сделано
- **DEV-13 закрыт:** OutcomePredictor `_SIG_ORDER` исправлен
  - Было: `["pivot_reversal", "trend_signal", "wt_signal", "confluence", "anomaly", "divergence", "wt_b"]` — divergence/wt_b отсутствуют в БД
  - Стало: `["pivot_reversal", "trend_signal", "wt_signal", "confluence", "anomaly", "mtf_alert", "mtf_bias"]` — реальные типы
  - TSL=win — уже было в коде (строка 116)
  - regime из MTFContext — уже работало (id 2450+ с NOT NULL)
  - `outcome_model.pkl` удалён → переобучится при следующем старте бота
  - Текущий CV AUC=0.31 (плохо, улучшится когда наберётся 300+ чистых записей)
- **DEV-15 закрыт:** 15/15 интеграционных тестов зелёные

### 📊 Следующий приоритет
**DEV-25** разблокирована после DEV-13, но триггер — 300 чистых записей (сейчас ~149).
Сейчас: 149 NOT NULL записей. Ждём ~300 для DEV-25.

---

## [19.03.2026] Агент: Developer — DEV-15 завершён

### ✅ Сделано
- **DEV-15 закрыт:** `tests/integration/test_reversal_scanner_e2e.py` — 15/15 тестов
  - TestScannerEndToEnd (5 тестов) — реальные индикаторы без патча
  - TestConfidenceGate (6 тестов) — регрессия BSB confidence=0.547
  - TestConfigParams (3 теста) — lookback_bars 5→8, pivot_touch_pct ключ, max_per_cycle
  - TestSignalStructure (1 тест) — confidence = score/100
- **Ключевой баг в тесте:** `_make_cfg` возвращал MagicMock-прокси для `analysis.confluence`, но `_get_cfg()` в сканере проверяет `isinstance(block, dict)` → MagicMock не dict → fallback {} → lookback=8 всегда. Фикс: возвращать dict напрямую.
- **Добавлены задачи в TASKS.md Backlog:** ARCH-19, ARCH-20, ARCH-21, DEV-25, DEV-26, DEV-27 (из Discussion сессии)
- **DEV-15 перемещён** из Backlog в таблицу ГОТОВО

### 📊 Следующий приоритет
**DEV-13** — `regime=NULL` в 100% сделок → ML обучается на мусоре. Самый критичный.

---

## [19.03.2026 ~UTC] Агент: Architect — Глубокий разбор mtf_bias

### ✅ Сделано
- **Расследована сделка #1997 GUA/USDT LONG** (mtf_bias, str=100, SL): ложный LONG при vol=0.14%
- **Найдены 5 корневых проблем** mtf_bias:
  1. `trend` = ATR trailing stop (лагающий), не WT momentum (ведущий)
  2. `wt_cross` без gap-фильтра в `mtf_checker.py`
  3. `regime=None` всегда → RANGE penalty не работает
  4. Нет volatility filter → str=100 при vol=0.14%
  5. Zone filter только на entry_tf, не на seniors
- **Подтверждено направление**: переписать mtf_bias на WT-based trend (ARCH-09 п.6)
- Обновлён `whats-next.md` с 5-шаговым планом переписки

### ⚠️ Ключевой вывод
ATR-based `calculate_trend()` НЕ подходит для определения рыночного направления.
Подходит только для TSL-линий. Для MTF alignment нужен WT-based trend.

---

## [18.03.2026 ~05:00 UTC] Агент: Developer — Критические багфиксы + SELFTEST L12

### ✅ Сделано
- **Баг #1 (trade_simulator.py):** `import json` внутри `if trade_mode:` (строка 204) затеняло модульный импорт → `UnboundLocalError` при `json.dumps(features)` → 100% сделок не регистрировались. Удалён локальный import.
- **Баг #2 (market_regime.py):** `if not ohlcv` падало при DataFrame (ValueError: ambiguous truth value). Заменено на `if ohlcv is None` + `hasattr(ohlcv, "values")` → `.values.tolist()`.
- **SELFTEST L12 (selftest.py):** Новый критический тест Trade Lifecycle — полный цикл register → verify OPEN → close(TP) → verify closed → cleanup. Проверяет profit_pct≈15%, R≈3.0.
- **Performance:** `api_semaphore_size` 5→20, `api_rps` 8→15 в config.yaml и config_loader.py (OHLCV тормозили 7+ сек при 436 парах)
- **Cleanup:** Удалены stale risk_manager.cpython-312/313.pyc (risk_manager.py уже был удалён ранее)

### ⚠️ Незакоммиченные изменения
- `core/trade_simulator.py` — удалён shadowing `import json`
- `core/market_regime.py` — fix DataFrame truthiness
- `core/selftest.py` — добавлен L12 Trade Lifecycle
- `config.yaml` — api_semaphore_size=20, api_rps=15
- `core/config_loader.py` — обновлены дефолты semaphore/rps

### 📊 Ключевые решения сессии
1. **Оба бага вместе блокировали 100% регистраций** — сигналы генерировались и отправлялись в ТГ, но ни одна сделка не сохранялась
2. **L12 — критический тест** — если register_trade или close_trade сломаны, бот не стартует
3. **Semaphore 20 + RPS 15** — если BingX начнёт банить, откатить до semaphore=10, rps=10

### ⚠️ Нерешённые проблемы из ТГ-лога
- Дубль "Цена у уровней" при нажатии "Все сигналы" (вероятно Telegram retry из-за долгого ответа)
- DEGO anomaly spam — дедупликация не работает для аномалий
- MBOX R:R=0.58 отправлен в ТГ, но не зарегистрирован (фильтр только на регистрацию)
- `pivot_alert` в signal_weights — неизвестный тип сигнала
- GRT AI analysis — `/ai` должен возвращать обзор даже без сигнала

---

## [16.03.2026 ~UTC] Агент: Architect — Анализ BE/SL/TP/Режим рынка

### ✅ Сделано
- **Анализ безубытка (BE)**: протестированы ВСЕ варианты на 1595 сделках — BE вреден при любых параметрах (delta от -232R до -665R). Решение: `use_breakeven: false`
- **Частичная фиксация**: все варианты (50/50, 33/67, SL→entry при TP1) — отрицательные. SL→TP1 при TP1 = +127R, но 97% exit rate режет потенциал
- **Выявлен хардкод TP**: `tp1_pct = sl_pct * 3.0` в `recommendation_generator.py:202` — TP всегда 3×SL, игнорирует пивоты
- **Спроектирована pivot-based TP иерархия**: конфлюенции 1M+1W > 1M > 1W+1D > 1W > 1D > Swing > ATR fallback
- **Спроектирован новый режим рынка**: MTF Bias + WT momentum + ATR вместо ADX + EMA slope
- **BTC фильтр**: shadow mode (логирует без блокировки) для сбора данных
- **TASKS.md обновлён**: ARCH-09 расширен до 8 подзадач

### ⚠️ Незакоммиченные изменения
- `TASKS.md` — обновлён ARCH-09 (8 подзадач)
- `config.yaml` — возможно мелкие правки
- `bot/monitoring.py` — в git status как modified
- `core/indicators.py` — в git status как modified

### 📊 Ключевые решения сессии
1. **BE = OFF** — все данные говорят против
2. **TP = pivot-based** — заменить хардкод 3R на реальные уровни пивотов
3. **Режим = MTF Bias + WT + ATR** — пользователь подтвердил, убираем ADX
4. **BTC фильтр = shadow** — собираем данные, не блокируем
5. **Strategy-TP**: ReversalStrategy → ближайший пивот, TrendStrategy → multi-level

---

## [15.03.2026 09:59 UTC] Агент: Developer — Баги APR/USDT флэш-краш

### ✅ Сделано
- **Расследован инцидент**: сделка #1910 APR/USDT LONG застряла OPEN при цене -21% ниже SL
- **Причина #1 (критическая)**: системные часы Windows были сдвинуты на +3 часа — бот хранил UTC+3 как UTC в `created_at`. После NTP-коррекции все реальные свечи стали "старше" чем `created_at` → фильтр `df[time >= created_at]` возвращал пустой df → `continue` → SL никогда не проверялся
- **Причина #2**: WT_CROSS_UP сгенерировал LONG-сигнал во время флэш-краша (-25%) — gap WT1-WT2 был слишком мал (разовый тик, сразу развернулся вниз)
- **Фикс #1** (`core/trade_simulator.py`): если фильтр по created_at даёт пустой df — берём последние 5 свечей как фолбэк (защита от смещения часов)
- **Фикс #2** (`core/signal_checkers.py`): требуем `wt1-wt2 >= 3` при cross_up и `wt2-wt1 >= 3` при cross_down — однократные мелкие пересечения игнорируются
- **Часы синхронизированы**: `w32tm /resync /force` + `w32tm /config /syncfromflags:DOMHIER /update`
- **Сделка #1910 закрыта вручную** по SL-цене (0.15999, -1R, -2.18%) вместо -9.74R

### ⚠️ Незакоммиченные изменения
- `core/trade_simulator.py` — фолбэк при пустом df
- `core/signal_checkers.py` — gap-фильтр для WT кросса

---

## [15.03.2026 ~UTC] Агент: Developer
- ✅ Сделано: Swing SL как первый приоритет в calculate_levels (коммит be82031)
  - Иерархия: swing_low/high → S1 pivot → FVG → TSL-линия → ATR
  - sl_source: "swing_low:PRICE" | "swing_high:PRICE"
  - 247/253 тестов прошли (6 failing — confluence_state_machine, не связаны)
- ✅ Безубыток (breakeven при +0.5R) уже был реализован ранее
- ⚠️ 6 тестов в test_confluence_state_machine.py сломаны — нужна работа архитектора

---

## [14.03.2026] Агент: Architect

### ✅ Сделано в этой сессии

**ARCH-01 — Рефакторинг bot/monitoring.py → bot/loops/ (коммит b4768ca)**
- `bot/core/bot.py` — TradingAlertBot класс
- `bot/loops/scan_loop.py` — scan_all_pairs + monitor_market + _prefetch_pivots
- `bot/loops/ml_loop.py` — ml_training_loop + weekly_report_loop
- `bot/loops/trade_tracker.py` — trade_tracker_loop
- `bot_with_subscriptions.py` — только точка входа (75 строк)
- Circular import решён через lazy import внутри `start_monitoring()`

**ARCH-02 — Рефакторинг core/trading_intelligence.py → core/intelligence/ (коммит b82214a)**
- `core/intelligence/signal_aggregator.py` — analyze_signals_advanced, calculate_adaptive_weighted_strength
- `core/intelligence/confidence_calculator.py` — calculate_advanced_confidence
- `core/intelligence/recommendation_generator.py` — generate_recommendation, determine_risk_level, generate_reasoning, calculate_levels
- `core/intelligence/ml_enhancer.py` — enhance_analysis_with_ml, apply_ml_corrections
- trading_intelligence.py: 1536 → 1061 строк

**Developer сессия (15.03.2026, DEV-01, коммит 02c8e4b)**
- `core/structure_detector.py`: detect_swing_highs_lows(), detect_choch(), detect_bos(), detect_structure()
- Делегирует в indicators.find_swing_highs/lows
- BOS > CHoCH по приоритету, strength 55/65
- 25/25 тестов passed
- Следующий шаг: DEV-01b — интеграция в signal_checkers.py

### 🔄 Незакоммиченные изменения
Нет — все изменения закоммичены.

### ⚠️ Следующие задачи

**DEV-01b (Developer) — Интеграция structure_detector → signal_checkers.py**
- check_structure_signals() → вызывает detect_structure()
- SignalType.SMC_SIGNAL в signal_models.py
- вес ~0.25 в trading_intelligence.py
- вызов в analyze_symbol()

**DEV-02 (Developer) — Тесты для signal_checkers.py**

**ARCH-03 (Architect, низкий приоритет) — State Machine для confluence**
- Ждёт 2+ недели данных от confluence_scanner

**ARCH-04 (Architect, низкий приоритет) — Адаптивный выбор стратегии**
- Ждёт DEV-07 + ARCH-03

### 📊 Схема Confluence (актуально)

| # | Фактор | Очки |
|---|--------|------|
| 1 | WT в OS/OB зоне | +20 |
| 2 | TSL CROSS в нужном направлении | +20 |
| 2b | WT CROSS в зоне OS/OB (**обязателен**) | +15 |
| 3 | Цена у пивота S/R | +25 |
| 4 | Дивергенция WT | +20 |
| 5 | Цена выше/ниже дневного PP | +15 |
| 6 | Тренд 1h подтверждает (бонус) | +10 |
| 7 | DUAL_CROSS: TSL+WT вместе (бонус) | +10 |

Макс. возможный score: 135 (clamp до 100). Порог сигнала: 60.
