# Current State

> Последние 3 сессии. Старые записи удалены — история в git log.

---

## [04.04.2026] Агент: DEV — DEV-126 выполнен

- ✅ **DEV-126**: features_json fix — WL breach + other_recs теперь пишут weekly_bias, htf_wt
  - `scan_loop.py`: `_handle_wl_breach_entry` → полный extra_features (weekly_bias через pivot_calculator, htf_wt1_1h через async fetch 1h, wt1_value из df_entry)
  - `monitoring.py`: `other_recs` block → передаёт weekly_bias/htf_wt из recommendation.metadata + pre_fetched_dfs
- 🔄 **Следующие**: DEV-127 (SMC None gate shadow), DEV-128 (weekly_bias gate pivot_reversal)

---

## [02.04.2026] Агент: TRADER — TR-007 + TR-001 выполнены

- ✅ **SMC gate**: `smc_has_bos OR smc_has_choch` — 254 сделки без SMC = WR=2% EV=−0.818R → shadow gate предложен DEV
- ✅ **session="?" баг**: 745/1401 (53%) сделок = неполный features_json (session+htf_wt+RR = одно множество)
- ✅ **HTF alignment**: +0.468R EV разница, но данные только у 47% — нужен fix заполнения
- ✅ **Мёртвые детекторы**: wt_signal (0% WR), anomaly (0% WR) → предложено убрать
- ✅ **pivot_reversal LONG TREND_DOWN**: −0.929R → предложено заблокировать
- ✅ **TR-001**: WR=37.5% сегодня, EV≈+0.54R, 25 открытых позиций. OKB/KAITO >45ч.
- ✅ **PairFullState валидация**: концепция верна, но fix заполнения данных = prerequisite для ML специалистов
- ✅ **trader_analyses/2026-04-02.md** создан

**Критический вывод**: fix session+htf_wt в register_trade_async — необходимо перед ARCH-68 (ML специалисты).

---

## [02.04.2026] Агент: ARCH — Куб Метатрона зафиксирован в ENCYCLOPEDIA

- ✅ **docs/ENCYCLOPEDIA.md**: добавлен раздел "Архитектурная концепция: Куб Метатрона"
  - 13 сфер с детальным описанием каждой (статус, файл, признаки, зависимости)
  - 5 Платоновых тел — уровни абстракции системы
  - PairFullState dataclass с полным набором полей шины
  - MTF WT Specialist: **35 признаков** (7TF × wt1/wt2/zone/cross/**atr_trend**)
  - MTF SMC Specialist: 36 признаков (4TF × 9 включая EQH/EQL)
  - Дорожная карта Фаза 0→4
  - Правило: любая задача должна соответствовать Кубу
- ✅ **CLAUDE.md**: добавлено обязательное чтение ENCYCLOPEDIA + архитектурное правило Куба
- ✅ **TASKS.md**: добавлена ARCH-68 (Куб Фаза 2: ML специалисты + Narrative Builder)
- ✅ **DISCUSSION.md**: зафиксирована концепция + уточнение ATR-trend в MTF WT Specialist

**Следующие приоритеты:**
1. 🔥 ARCH-62: Exit Manager (разделить монолит trade_simulator.py) — блокирует Фазу 2
2. 🟢 DEV-121: Self-Diagnostics Suite
3. 🔥 DEV-111: BTC 4h gate shadow

---

## [02.04.2026] Агент: TRADER — TR-001 + ответы DEV/ARCH

- ✅ **Ответ DEV**: avg_R=+0.21 при SL-статусе = DUAL_TP tp1_hit механизм (30/31 хитнули TP1, 0.70×R_tp1 + 0.30×(-1R) ≈ +0.21R). TSL gap риск, не баг.
- ✅ **48ч ревью DUAL_TSL/TP2**: TSL exits = avg_R +3.0-3.2R, TP2 = 14 сделок +2.288R. Механизм корректен.
- ✅ **WR нормализована**: сегодня (02.04) WR=37.5%, EV≈+0.54R. Фиксы dynamic_os+bounce работают.
- ✅ **Ответ ARCH**: горизонт пользователей = 50-200, SQLite достаточно, WAL при ~50 usr.
- ✅ **TR-001**: 25 открытых, ⚠️ OKB/KAITO >45ч (EXPIRED скоро), MMT tsl=0 за 29ч.
- ✅ **Trader analysis**: memory/trader_analyses/2026-04-02.md создан.

**Текущее состояние системы:** стабильна. WR нормализована.

---

## [01.04.2026] Агент: DEV — Аудит SL конвейера + полный map TP/SL/TSL

- ✅ **Диагноз SL конвейера**: DEV-108 (dynamic_os в RANGE) = root cause. Фикс: `dynamic_os_enabled: false` в config.yaml
- ✅ **4 dead trades** (NULL take_profit от bounce_mode): закрыты как EXPIRED (id 4479, 4485, 4625, 4760)
- ✅ **trigger_bus**: вернут в `shadow: true` (только 1 сделка за 3 дня — недостаточно данных)
- ✅ **bounce_mode**: `enabled: false` — создавал take_profit=NULL сделки без механизма выхода
- ✅ **Полный аудит check_open_trades** (строки 1050-1665): задокументирована карта всех решений
- ✅ **TASKS.md**: добавлена DEV-121 (Self-Diagnostics Suite) + ARCH-62 в сводной таблице
- ✅ **DISCUSSION.md**: полный map TP/SL аудита + список 6 критических проблем

**Критические проблемы (из аудита):**
1. `tsl_tf DEFAULT '15m'` — TSL стартует слишком рано для 15m сделок → ARCH-62 fix
2. После tp1_hit нет `cap_tf` — 4h TSL слишком широкий → ARCH-62 cap_tf="1h"
3. `tp1_fix_pct=20` (config) — только 20% фиксируется на TP1, 80% идёт на TSL
4. bounce trades (NULL TP) — виснут до EXPIRED — ARCH-62 exit_manager bounce mode
5. DEV-91 R-gradient shadow — не де-эскалирует, только логирует

**Незакоммиченные изменения:** config.yaml (dynamic_os, bounce_mode, trigger_bus), DISCUSSION.md, TASKS.md
**⚠️ НЕ КОММИТИТЬ** — система не полностью стабильна (RANGE WR=19%, все режимы убыточны)

**Следующие приоритеты:**
1. 🔥 ARCH-62: разделить trade_simulator.py → exit_manager + cascade_tsl + levels_calculator
2. 🟢 DEV-121: написать скрипты self-diagnostics (эталонные кейсы TP/SL/TSL)
3. 🔥 DEV-111: BTC 4h gate shadow mode

---

## [30.03.2026] Агент: ARCH — DEV-118/119/120: TP стратегия, DUAL_TSL, фикс open-trades

- ✅ **DEV-118**: Фикс дублирования `analyze_symbol` — выбор лучшего signal_type по приоритету (`max()`)
  - `scan_loop.py`: `_SIGNAL_PRIORITY = {confluence:100, wt_b:90, wt_signal:80, ...}`
  - Один `analyze_symbol` на пару за цикл вместо N дублей
- ✅ **DEV-119**: TRIPLE_TP_TSL убран, DUAL_TP на пивотах
  - `pivot_calculator_fixed.py`: добавлен `get_next_tp_by_hierarchy(tp1_price, ...)` — второй пивот по иерархии
  - `trade_simulator.py`: TP1 = первый пивот (`take_profit`), TP2 рассчитывается async через новую функцию
  - Баг TP2 exit исправлен: после TP2 hit устанавливается `exit_status = STATUS_TP`
  - `regime_strategy.py`: RANGE `max_strategy_type = "SINGLE"` (было DUAL_TP)
  - `config.yaml`: добавлен блок `trading.dual_tp: {enabled: true, tp1_fix_pct: 70}`
  - `dashboard_server.py`: toggle «DUAL TP» + слайдер «TP1 fix %»
- ✅ **DEV-120**: DUAL_TSL для обоих TREND режимов (данные из БД 119 сделок)
  - `TREND_UP` TSL avg=**4.6R** vs TP avg=2.1R → DUAL_TSL выгоднее на +0.6R/сделку
  - `regime_strategy.py`: `_STRATEGY_ORDER = ["SINGLE","DUAL_TP","DUAL_TSL"]`; TREND min=`DUAL_TSL`
  - `close_trade()`: взвешенный R = `tp1_fix_pct × R_tp1 + (1-tp1_fix_pct) × R_exit` (было хардкод 0.5)
  - `config.yaml`: `trend_strategy_type: DUAL_TSL`
- ⚠️ **Нужен рестарт бота** для применения изменений
- 🔄 **Следующий приоритет**: DEV-103 (Exchange Health Loop) — блокирует VST

---

## [30.03.2026] Агент: ARCH — Спеки ARCH-63 + ARCH-66 + приоритеты DEV

- ✅ **ARCH-63 спек** готов: BTC 4h market gate в DISCUSSION.md
  - Место: `trading_intelligence.analyze_symbol()` новый параметр `btc_market_regime`
  - Shadow mode сначала, блокирует LONG при BTC 4h TREND_DOWN
  - Исключение: pivot_reversal + weekly_bias=BULLISH
  - Config: `trading.btc_market_gate.enabled: true, shadow_mode: true`
- ✅ **ARCH-66 спек** готов: RANGE BOUNCE SL/TP calculator в DISCUSSION.md
  - `calc_range_bounce_sl_tp()` в `core/smc/sl_tp_calculator.py`
  - Фильтры: regime=RANGE, 15m, confluence/wl_breach, entry≤2% от пивота, TP_R≥3.5
  - Config: `trading.range_bounce.enabled: false` (включить после теста)
- ✅ **TASKS.md** обновлён: ARCH-63→✅, ARCH-66→✅, DEV-111 добавлен 🟡
- ✅ **PROJECT-LOG.md** обновлён
- 🔄 **Ждём DEV**: DEV-103 (Health Loop) → DEV-111 (BTC 4h gate) → DEV-110 (RANGE BOUNCE)
- ❓ **Ждём TRADER**: валидация — SHORT в RANGE структурно лучше LONG или артефакт медвежьего рынка?

---

## [29.03.2026 ~00:30 UTC] Агент: ARCH (сессия 35) — Trade Dashboard аудит

- ✅ **DISCUSSION.md**: Полный аудит Trade Dashboard — 6 разделов:
  - Текущее состояние (страницы, виджеты, технологии)
  - 20+ пробелов по открытым позициям, закрытым сделкам, аналитике, real-time
  - Приоритеты редизайна (Quick wins / Аналитика / VST readiness)
  - Референсы: Grafana, Bybit Pro, 3Commas, TradingView
  - VST checklist (9 пунктов)
  - Технический долг + вопросы к DEV и TRADER
- ✅ **PROJECT-LOG.md**: добавлена запись аудита
- 🔄 **Ждём**: TRADER → приоритет метрик для VST; DEV → выбор приоритета редизайна

---

## [29.03.2026] Агент: DEV (сессия 34) — DEV-95/77/78 завершены

- ✅ **DEV-95**: TriggerBus — `core/context/trigger_bus.py` + `bot/loops/trigger_loop.py`
  - OteReentryTrigger, CascadeTrigger; интеграция в `bot/core/bot.py` (pair_context + post_analyser + trigger_loop task)
  - `config.yaml`: `trigger_bus: {shadow: true, cascade_min: 3, interval_sec: 120}`
- ✅ **DEV-77**: OrderExecutor — `core/trading/order_executor.py`
  - Режимы: SIM_ONLY / VST / LIVE; bracket-ордер + partial_close (20%); min_notional check
  - `config.yaml`: `trading.execution_mode: sim_only`, `trading.tp1_close_pct: 0.20`
- ✅ **DEV-78**: PositionManager + PositionSizer + OrderReconciler
  - `core/trading/position_sizer.py`: qty = deposit×risk% / (sl_dist × entry_price)
  - `core/trading/position_manager.py`: live_orders таблица, has_open_position(), sync_with_exchange()
  - `core/trading/order_reconciler.py`: reconcile() при старте бота — детектирует ORPHAN позиции

⚠️ **Нужен рестарт бота** — все изменения незакоммичены

---

## [29.03.2026] Агент: DEV (сессия 33) — Куб Метатрона Фаза 1 + ARCH-58 + DEV-96

- ✅ **ARCH-58**: TP Architecture — все пути регистрации теперь используют `get_tp_by_hierarchy()`
  - `recommendation_generator.py`: переименован ATR fallback tp_source → `"atr_fallback"`
  - `bot/loops/scan_loop.py`: то же переименование
  - `bot/monitoring.py:962`: добавлен `get_tp_by_hierarchy()` для пути `other_recs`
  - `core/ui/intelligence_formatter.py`: добавлен `"atr_fallback": "ATR"` в `_TP_TF` dict
- ✅ **DEV-90 (ARCH-59)**: `classify_v2()` shadow mode
  - `core/signals/structure_detector.py`: добавлен `detect_structural_regime(df, period=5)` — HH/HL паттерн
  - `core/indicators/market_regime.py`: добавлен `classify_v2(df_15m, df_1h)` — 3 слоя (spike guard → structural → MTF)
  - `config.yaml`: добавлен `market_regime: use_v2: false` (shadow only)
- ✅ **DEV-92**: `_post_tsl_queue` в TradeSimulator — TTL=8h + impulse breach invalidation
- ✅ **DEV-93**: `PairContextBus` — `core/context/pair_context.py` + `core/context/__init__.py`
- ✅ **DEV-94**: `PostTradeAnalyser` — `core/trading/post_trade_analyser.py` (shadow mode)
  - Реагирует на SL/TSL/TP через callback; вычисляет OTE зону [0.705, 0.786] для re-entry
- ✅ **DEV-96**: SMC флаги — 4 направленных флага в `SMCContext.to_features()`
  - `has_bullish_bos`, `has_bearish_bos`, `has_bullish_choch`, `has_bearish_choch`
- ⚠️ **DEV-95** 🔵: TriggerBus — ARCH-61 спек готов (✅), задача в бэклоге
- ⚠️ **DEV-97** 🔵: weekly_bias gate штраф — ЗАБЛОКИРОВАНО, нужны данные n≥30

⚠️ **Нужен рестарт бота** — все изменения незакоммичены

---

## [28.03.2026 ~23:45] Агент: TRADER — Стратегическое видение записано

- ✅ **DISCUSSION.md** — добавлена запись «Куб Метатрона»: полная архитектура полносвязной системы
  - Текущая архитектура vs. Cuб Метатрона (диаграмма узлов)
  - Каскадные данные: A2Z(+86R), PIPPIN(0% SL), SUN(82% WR)
  - Cap% проблема: 4-7R bucket = 48% захват, дают обратно 7.79R avg
  - Shared Context Bus, Trigger System, Post-Trade Analyser — концепции
  - Фазы реализации 1/2/3
  - Открытые вопросы → ARCH (Shared Context архитектура) + DEV (TR-010 совместимость)
- ✅ **DISCUSSION.md** — TR-010 Post-TSL OTE Re-entry (из пред. записи сессии)
- ✅ **DISCUSSION.md** — TR-009 R-gradient де-эскалация + бэктест (из пред. записи сессии)
- ✅ **TASKS.md** — TR-009, TR-010 добавлены

**Следующий шаг:** ответ ARCH на вопросы в Кубе Метатрона → реализация TR-009/TR-010

---

## [28.03.2026 #7] Агент: DEV — DEV-89 завершён

- ✅ **DEV-89** — Cascade TSL: OR-логика 4h+1h WT + weekly pivot touch
  - `core/trading/trade_simulator.py` строки ~1061-1120:
    - Фетч 1h WT (`df_1h_wt89`), OR логика: `_wt_exhausted = _wt_4h_exh or _wt_1h_exh`
    - Weekly pivot touch через `PivotCalculatorFixed().get_weekly_pivots()` при `current_r >= _de_esc_r`
    - SHORT: S1/S2/S3/PP; LONG: R1/R2/R3/PP; порог 1.5%
    - `if _wt_exhausted or _near_weekly:` → de-escalate
    - Лог: `(R=%.1fR, WT4h=X.X 1h=X.X near_w=True/False, TSL тесней)`
  - **DEV-89 sub-task**: `core/trading_intelligence.py` строки ~1308-1319:
    - tp_source weekly exception в DEV-58 блоке
    - `if "1W" in tp_source` → `_near_s=True` (LONG) / `_near_r=True` (SHORT)
- ✅ TASKS.md: DEV-89 → ✅

⚠️ Нужен рестарт бота

**Следующий шаг:** DEV-90 (ARCH-59: detect_structural_regime + classify_v2 shadow mode) или другие задачи

---

## [28.03.2026 #6] Агент: DEV — DEV-87/88 + переименования + энциклопедия

- ✅ **DEV-88**: SL по CLOSE (не LOW) для `sl_source` начинающихся с `tsl_line`/`wl_pivot_tsl` — `core/trading/trade_simulator.py`
- ✅ **Переименования стратегий**: `reversal_scanner`→`wt_entry` (WtEntryStrategy), `confluence`→`multi_signal` (MultiSignalStrategy)
  - `strategies/built_in/reversal_scanner_strategy.py`, `strategies/built_in/confluence.py`
  - `core/trading_intelligence.py`: `_STRATEGY_PRIORITY`, `active_strategy_name`, `_pick_best_recommendation()`
  - `config.yaml`: `active_strategy`, `active_strategies`, `strategies.*`
  - `tests/unit/`: sed-замена строковых имён
  - **БД мигрирована**: 511 `confluence`→`multi_signal`, 729 `reversal_scanner`→`wt_entry` в `simulated_trades.strategy_name`
- ✅ **pivot_reversal.sl_buffer_pct убран**: из `config.yaml` и `strategies/built_in/pivot_reversal_strategy.py`
- ✅ **DISCUSSION.md**: ответ TRADER по unswept_liquidity (DEV вопрос)
- ✅ **docs/ENCYCLOPEDIA.md** создана: SignalType.CONFLUENCE, WtEntryStrategy, MultiSignalStrategy, TSL, WL Breach, SL CLOSE vs LOW
- ✅ **memory/arch_signal_types.md** создан: типы сигналов, стратегии, веса, DEV-88
- ✅ **memory/MEMORY.md**: добавлена секция "Типы сигналов и стратегии"

⚠️ **Незакоммиченные изменения**: DEV-87 (factor=1.25 везде в calculate_trend), DEV-88 (CLOSE check), переименования, конфиг, миграция БД, ENCYCLOPEDIA.md
⚠️ **Нужен рестарт бота** для применения изменений

---

## [28.03.2026 #5] Агент: DEV — DEV-83 завершён (ARCH-56 Phase B)

- ✅ **DEV-83 Step 1** (`core/signals/signal_models.py`): 7 новых полей в MTFContext (phase, zone_state, avoid_reason, pattern_name, pattern_confidence, unswept_highs, unswept_lows)
- ✅ **DEV-83 Step 2-3** (`core/mtf/mtf_interpreter.py`): 5 функций (_detect_phase, _detect_zone_cascade, _detect_avoid_reason, _detect_pattern, _extract_unswept_liquidity) + обновлён analyze_context(df_1h, df_4h)
- ✅ **DEV-83 Step 4** (`core/trading_intelligence.py`): _build_mtf_context() теперь фетчит df_4h и передаёт df_1h+df_4h в analyze_context()
- ✅ **DEV-83 Step 5** (trading_intelligence.py): shadow-mode лог [phase56] symbol phase=X zone=Y pattern=Z avoid=W
- ✅ **DEV-83 Step 6** (`core/ui/intelligence_formatter.py`): строка "🧭 Фаза: <phase> · <pattern> ⚠️ <avoid>" в TG-сообщении
- ✅ **DEV-83 Step 7** (`config.yaml`): `mtf.phase_guard_enabled: false` добавлен
- ✅ TASKS.md: DEV-83 → ✅

⚠️ Нужен рестарт бота (DEV-83 + DEV-84 + DEV-85 + weekly_bias_filter=true)

**Следующий шаг:** DEV-87 (backtest OTE v2 ~11.04), или другие DEV-задачи

---

## [28.03.2026 #4] Агент: DEV — DEV-84 завершён

- ✅ **DEV-84** (Фаза C shadow logging): `core/trading_intelligence.py` строки 1197-1223
  - Внутри блока `if _l3_52:`, после DEV-52-L3 сводного лога
  - cond_c1: FVG support/resistance из `mtf_context.smc_h4` (4h snapshot)
  - cond_c2: active OTE из `smc_context.fibonacci.active_ote`
  - Лог: `[SYM] DEV-84-L3C cond_c1=T/F(4h_fvg_sup=Y/N) cond_c2=T/F(ote=Y/N)`
  - Всё в try/except — shadow mode, production flow не затронут
- ✅ TASKS.md: DEV-84 → ✅

⚠️ Нужен рестарт бота (активировать DEV-84 + DEV-85)

**Следующий шаг:** DEV-83 (ARCH-56 реализация) — ждёт спека или другие задачи
**Доступно:** DEV-87 (backtest OTE v2 ~11.04)

---

## [28.03.2026 #3] Агент: DEV — DEV-85 полностью завершён

- ✅ **DEV-85 Step 0** (`cb4248e`): `core/smc/fibonacci.py` — price-invalidation stale fix
  - LONG: `current_price < impulse_low` → `price_in_ote=False` (BOS провалился)
  - SHORT: `current_price > impulse_high` → `price_in_ote=False`
- ✅ **DEV-85 Step 1** (`8731937`): `core/signals/ote_detector.py` — wide gate + ATR-trend gate
  - Wide only [0.705-0.786], tight бонус убран, df_trend_ref параметр
- ✅ DISCUSSION.md: ответ TRADER по unswept_liquidity (~50-70 строк, ждёт ARCH-56 спек)
- ✅ Тесты: 545/570 unit (16 pre-existing, no regression)
- ⚠️ Нужен рестарт бота

---

## [28.03.2026 #2] Агент: TRADER — TR-001 daily analysis + DEV-75/DEV-86 already done + Fib TP verdict

- ✅ **TR-001 анализ 28.03.2026** → `memory/trader_analyses/2026-03-28.md`
  - 20 открытых сделок, рынок медвежий, vol 0.2-0.3x avg
  - STG SHORT +0.97R (лучший), LTC SHORT +0.78R, TRX LONG +0.52R
  - WL: ENA RSI=12, JUP RSI=18 — экстремальный oversold, ждать WT crossup
  - Win Rate 7д: 15.0%, avgR=-0.27 ⚠️ (медвежий рынок + OTE stale zones)
- ✅ **Fib Extension TP — ЗАКРЫТ** (бэктест 27-28.03.2026):
  - Hit rate 5-15% на 15m, 3-6% на 1h — слишком далеко от входа
  - TSL = единственный надёжный выход. Вопросы в DISCUSSION закрыты.
  - `get_tp_by_hierarchy()` — Fib step 6 УДАЛЁН из кода
- ✅ **DEV-75** (pivot hierarchy) и **DEV-86** (убрать R4-S4) — оба уже были в коде ДО этой сессии
  - DEV-75: порядок 1D→1W→confluence(1W+1D)→confluence(1M+1W)→1M ✓
  - DEV-86: `range(1,4)` = R1,R2,R3 / S1,S2,S3 ✓
  - TASKS.md обновлён → оба ✅

**Следующие задачи (по приоритету):**
1. **DEV-85** 🟡 — OTE stale zones фикс (TTL + price-invalidation) — ГЛАВНЫЙ приоритет для WR
2. **DEV-83** 🟢 — MTF Interpreter Phase B (ARCH-56 спек готов)
3. **DEV-84** 🟢 — L3 Phase C FVG/OB + OTE conditions

---

## [28.03.2026] Агент: ARCH — ARCH-56 спек + ответы в DISCUSSION + DEV-86/DEV-75

- ✅ **ARCH-56 Phase B спек** написан в TASKS.md (разблокирует DEV-83):
  - 4 новые функции в `mtf_interpreter.py`: `_detect_phase`, `_detect_zone_cascade`, `_detect_avoid_reason`, `_detect_pattern`
  - 7 новых полей в `MTFContext`: phase, zone_state, avoid_reason, pattern_name, pattern_confidence, unswept_highs, unswept_lows
  - Фазы: impulse_up/down, correction_*_in_*, reversal_*, range
  - Pattern names: IMPULSE_UP/DOWN, WAVE_3_RELOAD, BEARISH_CORRECTION_FADE, CASCADE_*_REVERSAL, REVERSAL_*, RANGE_PLAY
  - shadow mode (avoid_reason только лог, phase_guard_enabled: false)
- ✅ **ARCH-56** → статус ✅ в TASKS.md
- ✅ **DEV-75** → статус ✅ в TASKS.md (был 🔴, но уже сделан: commit adaa77c)
- ✅ **DEV-86** создана в TASKS.md: убрать R4-R5/S4-S5 из get_tp_by_hierarchy() — 1 строка
- ✅ **DISCUSSION.md** — ответы ARCH на 3 открытых блока:
  - OTE stale zones: TTL=30 баров, price-invalidation, stale = баг-фикс до DEV-85
  - TP через SMC: последовательность подтверждена, unswept_liquidity добавить в ARCH-56
  - Критический баг TP: DEV-75 исправил порядок, DEV-86 уберёт R4/S4 — два шага фикса

**Следующие задачи DEV:**
1. **DEV-86** 🟡 — 1 строка в pivot_calculator_fixed.py (быстро, фиксит real bug)
2. **DEV-83** 🟢 — реализация ARCH-56 Phase B (5 файлов, spec готов)
3. **DEV-77** 🟢 — OrderExecutor (после DEV-83 или параллельно)

---

## [27.03.2026] Агент: ARCH+DEV — ARCH-58 шаг 1 + решения по TP

- ✅ `config.yaml`: `scan_cycle_warning_threshold_sec` 55→70, `ohlcv_slow_threshold_sec` 5→8
- ✅ `core/infra/api_engine.py` + `data_collector.py`: TTL 4h 300→900s, 1d 600→1800s (фикс бурста кеша)
- ✅ **ARCH-58 шаг 1**: Fib extension tier добавлен в `get_tp_by_hierarchy()` (`pivot_calculator_fixed.py`)
  - Новые параметры: `impulse_high`, `impulse_low`
  - Tier 6: Fib 1.272 → Fib 1.618 (когда пивот не найден)
  - `monitoring.py`: извлекает `impulse_high/low` из `recommendation.metadata` и передаёт
  - OTE detector уже пишет эти поля в metadata → автоматически работает
- ✅ 21/21 unit тестов pivot TP прошли
- ✅ **Симуляция 20% на TP1** (683 сделки с TP1 hit):
  - SL после TP1: +0.876R → +1.243R (+0.367R страховка) ✅
  - TSL: +5.998R → +5.878R (-0.12R, цена страховки)
  - Итого: +3.889R → +3.951R (+0.062R, нейтрально)

**Решения зафиксированы в TASKS.md + DISCUSSION.md:**
- TP1 = 20% фиксация (утверждено TRADER)
- Двунаправленный OTE (SHORT→OTE + LONG из OTE) → DEV-85 v2, нужен бэктест
- Иерархия TP1: Пивот 1D/1W → Fib 1.272 → Fib 1.618 → ATR fallback

⚠️ **Нужен рестарт бота** для применения: TTL фикс, config.yaml пороги

---

## [26.03.2026] Агент: DEV — ARCH-53 Backtest завершён (scripts/backtest_ote_mtf.py)

- ✅ `scripts/backtest_ote_mtf.py` создан и отлажен: 5 TF × 20 пар × N дней
- ✅ Фиксы в процессе: OHLCVCache интеграция, `enableRateLimit=False`, precompute zone SMC (`_fast_zone_ctx`), DatetimeIndex восстановление после `calculate_wt`, `cross_up/cross_down` добавление, `zone_tf_priority` параметр в `detect_ote_signal()`
- ✅ Изменены файлы: `core/signals/ote_detector.py` (добавлен параметр `zone_tf_priority`)
- ✅ Результаты бэктеста (10 пар / 30 дней / 416 swing + 248 scalp сделок):

**SWING [1h/4h/1d→15m]: 🔴 ОТКАЗ**
  - WR=28.8%, AvgR=-0.136, Sharpe=-1.59, MaxDD=-66R
  - 4h зона: 69% сделок, WR=27.8% — ГЛАВНАЯ ПРОБЛЕМА
  - 1h зона: WR=32.9%, AvgR=-0.01 — нейтральная (почти безубыточна)
  - Tight OTE [0.618–0.705]: WR=18.2% — ХУЖЕ! Wide [0.705–0.786]: WR=39.5%, AvgR=+0.184 — лучше
  - Конфлюенция 2TF не помогает (WR=24.2% < 1TF 29.2%)

**SCALP [15m→3m]: 🔴 ОТКАЗ**
  - WR=33.9%, AvgR=+0.017, Sharpe=0.19, MaxDD=-15R

**Финальные результаты (20 пар):**
  - SWING: WR=26.8%, AvgR=-0.197, Sharpe=-2.35, MaxDD=-139R → ОТКАЗ
  - SCALP: WR=32.7%, AvgR=-0.02, Sharpe=-0.23, MaxDD=-30R → ОТКАЗ
  - Wide OTE [0.705-0.786]: WR=33.5%, AvgR=+0.006 → почти безубыточна (потенциал!)
  - Tight OTE [0.618-0.705]: WR=20.5% → антипаттерн, убрать
  - MATIC делистирован на Binance (пропущена)
  - INJ: WR=47.1%, AvgR=+0.412 (17 сд) — единственная зелёная пара

**Следующие шаги (DEV-77):**
  - DEV-77: OTE v2 — убрать tight зону + добавить ATR-trend direction gate
  - Цель: WR≥40%, Sharpe≥1.0
  - Shadow mode продолжить ≥2 недели

---

## [26.03.2026] Агент: DEV — DEV-79/80/81/82 завершены

- ✅ DEV-79: web/static/ рефакторинг — 4 HTML-константы вынесены в файлы (index/settings/backtest/operations.html). dashboard_server.py 3266→985 строк
- ✅ DEV-80: Trading Panel `/trading` — Position Sizer (deposit/risk/leverage/entry/sl), TP таблица 1R-5R, min_notional check. Файл `web/static/trading.html`
- ✅ DEV-81: FUNDING_EXTREME detector — `core/signals/funding_detector.py`, shadow mode (лог only, не в TG). Интеграция: `data_collector.get_funding_rate()` (TTL 30мин) + scan_loop.py 1a блок
- ✅ DEV-82: LIQUIDITY_SWEEP detector — `core/signals/liquidity_sweep_detector.py`. Интеграция: scan_loop.py 1b блок, broadcast в TG. Форматтеры добавлены в `core/ui/message_builder.py`
- ✅ Stop hooks: settings.json — оба хука DEVELOPER + TRADER
- ⚠️ Нужен рестарт бота для активации новых детекторов

---

## [29.03.2026] Агент: ARCH — ARCH-51 спек + DEV-63 создана

- ✅ ARCH-51 добавлена в TASKS.md (была только в DISCUSSION.md — задача «потерялась»)
- ✅ Аудит SMC-кода: 4 бага в старом спеке (поля `bullish_obs`/`bullish_fvgs` → `active_bull`/`active_bear`, `fvg.high`→`fvg.top`, строковый матч→`is_choch`/`is_bos`)
- ✅ Исправленный спек записан в DISCUSSION.md [29.03.2026 ARCH — ARCH-51 DEV-спек]
- ✅ DEV-63 создана в TASKS.md (🟡, 3 файла, 4 шага, shadow only)
- Вставочные точки: trading_intelligence.py:623 (snapshots) и ~715 (shadow logging)

---

## [29.03.2026] Агент: DEV (сессия 32) — DEV-76 завершён

- ✅ `core/signals/signal_models.py` — `SignalType.OTE_SIGNAL = "ote_signal"`
- ✅ `core/signals/ote_detector.py` создан (~120 строк): `detect_ote_signal()` читает `smc_ctx.fibonacci.active_ote`, WT cross trigger, tight OTE бонус
- ✅ `core/trading_intelligence.py` — OTE вызов после ARCH-51 (строка ~645), shadow metadata (строка ~808)
- ✅ `config.yaml` — `ote_shadow_mode: true`
- ✅ Import-тест: ALL OK
- ⚠️ Нужен рестарт бота для активации OTE shadow logging
- ⏳ ARCH ревьюирует логи через 2 недели, переключает `ote_shadow_mode: false`

---

## [29.03.2026] Агент: ARCH (сессия 31) — ARCH-53 спек + DEV-76 создана

- ✅ Аудит SMC инфраструктуры: `fibonacci.py` уже содержит `FibZone.price_in_ote` + `FibAnalysis.active_ote`
- ✅ ARCH-53 спек записан в DISCUSSION.md: `detect_ote_signal()` читает `smc_ctx.fibonacci.active_ote`, триггер WT cross в зоне
- ✅ DEV-76 создана в TASKS.md (🟡, 3 файла, 5 шагов, shadow only)
- ✅ ARCH-53 закрыт (спек готов), DEV-76 в очереди
- Вставочные точки: trading_intelligence.py ~280-320 (сбор сигналов) + ~780 (shadow metadata)

---

## [29.03.2026] Агент: DEV (сессия 31) — DEV-63 завершён

- ✅ DEV-63 Шаг 1: `core/signals/signal_models.py` — `MTFSMCSnapshot` dataclass + `smc_h4`/`smc_d1` в `MTFContext`
- ✅ DEV-63 Шаг 2: `core/smc/models.py` — `build_mtf_smc_snapshot()` после `_mark_fvg_overlap`
- ✅ DEV-63 Шаг 3: `core/trading_intelligence.py:623` — вызов snapshots для 4h + 1d
- ✅ DEV-63 Шаг 4: `core/trading_intelligence.py:~780` — shadow logging в `metadata["arch51_4h"]` / `metadata["arch51_1d"]`
- ✅ Import-тест: ALL OK
- ⚠️ Нужен рестарт бота для активации shadow logging
- ⏳ Следующее: TR-008 (TRADER валидирует /scan), ARCH-53 разблокирован (OTE детектор)

---

## [29.03.2026] Агент: DEV (сессия 30) — 4 критических фикса trade_simulator.py

- ✅ DEV-73: `_tsl_gate` = `current_r >= tsl_activation_r` для ВСЕХ стратегий (был: DUAL/TRIPLE ждали tp1_hit_at)
- ✅ DEV-67: cascade TSL fallback к `prev_tsl_tf` при развороте тренда (вставлено после строки 1052)
- ✅ DEV-64B: Guard 3 `signal_regime_block` — читает `signal_quality.signal_regime_block` из config, pivot_reversal+RANGE/TREND_DOWN блокируется
- ✅ ARCH-04: `_grp_412 = get_regime_params(regime, cfg=_cfg_rs)` — `regime_params` NameError устранён
- ✅ import-тест: ALL OK
- ✅ Верификация: ALL FIXES OK
- ✅ Бот перезапущен ARCH (PID 494440 → 21440), дашборд 200 OK
- ⏳ TR-008 — TRADER валидирует /scan + /intelligence

---

## [29.03.2026] Агент: DEV (сессия 29) — post-ARCH-54 runtime фиксы
- ✅ `core/ui/intelligence_formatter.py`: добавлен параметр `show_fvg_confluences: bool = False` в `format_intelligence_message()`
- ✅ `core/ui/chart_builder.py`: добавлены параметры `bot=None`, `fvg_zones=None` в `build_signal_chart()`
- Причина: git restore вернул старые версии файлов (до uncommitted changes), недостающие kwargs вызывали TypeError в bot/monitoring.py:936,971
- 🔴 Нужен рестарт бота для проверки всех фиксов

---

## [26.03.2026] Агент: ARCH (сессия 27) — DEV-71 ревью __init__.py
- ✅ Ревью __init__.py: db/ ✅, ui/ ✅ (опц: message_composer), ml/ ✅ (опц: r/rl/auto), indicators/ 🔴 fix
- ✅ Исправлен indicators/__init__.py: убран `from core.indicators.indicators import *` (дублирование)
- ✅ DISCUSSION.md: добавлен ревью-пост ARCH с конкретными действиями для DEV
- ✅ Зафиксировано разделение зон: DEV = signals/pivots/mtf/infra/trading/confluence, ARCH = ревью db/ui/ml/indicators
- ⚠️ Хук AGENT_ROLE=DEVELOPER срабатывает в ARCH-сессии — DEV-71 статус 🔄 должен его блокировать, если нет — проверить TASKS.md

## [26.03.2026] Агент: ARCH (сессия 26) — ревью ARCH-04 + ответы TRADER
- ✅ Ответил на все открытые вопросы TRADER (A: LIQUIDITY_SWEEP, B: OTE, C: Confluence split, H: WL breach+CHoCH) в DISCUSSION.md
- ✅ Архитектурный ревью `core/regime_strategy.py` (ARCH-04): два gap
  - Gap 1: `sl_factor` не применяется → комментарий (намеренно)
  - Gap 2: `cfg` не передаётся в `get_regime_params()` → config-секция мёртвая
- ✅ DEV-70 создана (TASKS.md + DISCUSSION.md)
- ✅ ARCH-53 добавлена в бэклог (OTE детектор, апрель)
- ✅ DEV-69 ✅ (уже реализована DEV в сессии 25) — исправил статус в TASKS.md

## [29.03.2026] Агент: DEV (сессия 28) — DEV-71/72 завершены
- ✅ DEV-71: ARCH-54 Фаза 1 — 10 папок созданы, 40 файлов перемещены, stubs работают (18/18)
- ✅ DEV-72: CLAUDE.md обновлён — новая структура core/ с подпапками
- ✅ DEV-70 re-applied к core/trading/trade_simulator.py + core/trading/regime_strategy.py
- ✅ Circular import ui/__init__.py пофикшен (убраны eager imports)
- 🔴 Нужен рестарт бота
- ⏳ TR-008 — TRADER валидирует /scan после рестарта

## [29.03.2026] Агент: DEV (сессия 25)
- ✅ DEV-69: `min_strength_wl_breach: 45` в config.yaml + fallback логика в scan_loop.py:54
- ✅ DEV-70: cfg передан в apply_regime_to_strategy() + комментарий sl_factor в regime_strategy.py

## [28.03.2026] Агент: DEV (сессия 24)
- ✅ Ответы на открытые вопросы TRADER/ARCH 24-25.03 — добавлено в DISCUSSION.md
- ✅ fetch_funding_rate() → поддерживается ccxt/BingX (fetch_funding_rate + fetch_funding_rates)
- ✅ MTF divergence complexity → низкая, инфраструктура есть (detect_cascade_divergence), нужен dual_tf (regular+regular)
- ✅ Fib для OTE → НЕ из pivot_levels.py (там нет Fib), нужен отдельный ote_detector.py
- ✅ WL breach min_strength → сейчас 75 (CHECK str=56 не пройдёт), предложен DEV-69: отдельный `min_strength_wl_breach=45`
- ⏳ DEV-69 ждёт одобрения ARCH

## [27.03.2026] Агент: ARCH (сессия 23) — документация + DEV-56 bugfix
- ✅ ARCH-52 завершён: BOT_SIGNAL_MAP.md обновлён (дата, порог 75, WL breach, quality gates, Cascade TSL, диагностика)
- ✅ DEV-59 закрыт через DEV-64A: код подтверждён — pivot_reversal идёт через register_trade_async, DEV-64A cap применяется
- ✅ DEV-56 bugfix: weekly_bias не сохранялся в features_json (был только в metadata) — исправлено в monitoring.py (3 поля в extra_features)
- ⚠️ DEV-58 сдвинут на ≈30.03–06.04 — нужны новые данные после рестарта бота с фиксом

## [27.03.2026] Агент: TRADER (сессия 21)
- ✅ DEV-65 вердикт TRADER: tsl_line остаётся, DEV-64C закрыт (wl_pivot_tsl_line WR=21.2%)
- ✅ Бот перезапущен — DEV-64A (max_rr=3.0) + DEV-64B (signal_regime_block) + DEV-66 (factor=1.25) активны
- **DEV-59 🔴 следующий приоритет** — pivot_reversal R:R cap (WR=9.1% из-за RR=17-23x)

---

## [26.03.2026] Агент: Developer (сессия 20)
- ✅ DEV-66: factor 1.25 в config.yaml (было 1.1, бэктест +0.041R)
- ✅ DEV-64A реализован: global max_rr=3.0 enforce в trade_simulator.py + scan_loop.py
- ✅ DEV-64B реализован: signal_regime_block в config.yaml + trade_simulator.py
- ✅ DEV-65 выполнен: tsl_line WR=4.4% avg_rr=18.2x = atr WR=3.8% avg_rr=18.4x → проблема в RR, не SL
- ✅ DEV-64C закрыт: не нужен, DEV-64A устраняет первопричину
- **DEV-59 всё ещё не реализован** — следующий после 64C

---

## [25.03.2026] Агент: Developer (сессия 22)
- ✅ DEV-67: Cascade TSL fallback при развороте тренда — trade_simulator.py:1055-1072
- ✅ DEV-68: WL breach min_strength guard (DOGE str=18 баг)
- ✅ DEV-53: L3 Фаза B — cond4 (WT freshness + near_pivot) + CHoCH soft penalty (-8)
- ✅ TASKS.md обновлён: DEV-67/68/53 помечены ✅
- ⏳ Следующее: рестарт бота → DEV-58 Фаза B (≈27-29.03)

---

## 📊 Текущее состояние системы (27.03.2026)

**Бот:** запущен, 427 пар в мониторинге

**Активные фильтры:**
- max_rr = 3.0 (DEV-64A) — глобальный cap R:R
- signal_regime_block (DEV-64B) — блок контр-тренд входов
- factor = 1.25 (DEV-66) — TSL немного шире
- Cascade TSL fallback (DEV-67) — не "падает" при развороте тренда
- L3 shadow mode (DEV-52/53) — 6-условный чеклист, только логирование

**В shadow mode (данные копятся, не блокируют):**
- Weekly Bias Filter (DEV-56) — ⚠️ баг исправлен 27.03: данные теперь пишутся в features_json → DEV-58 production ≈30.03–06.04
- Market Stress Gate (DEV-48)
- Dynamic OS (ARCH-49) — 30 дней наблюдения
- ARCH-51-pre logging — конфликты 15m SMC vs 4h OB

**Следующие задачи по приоритету:**
1. ~~DEV-59~~ ✅ закрыт через DEV-64A (cap применяется в register_trade_async)
2. **Рестарт бота** 🔴 — применить DEV-56 bugfix (weekly_bias в features_json)
3. DEV-58 🔄 — Weekly Bias production gate (≈30.03–06.04 после накопления данных)
4. ARCH-45 🔄 — плановый ревью OutcomePredictor AUC ≈06.04
5. DEV-63 🟡 — Multi-TF SMC snapshot (≈06-08.04)
