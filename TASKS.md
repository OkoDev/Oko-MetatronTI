# 📋 TASKS — Координация агентов

Файл координации между агентами проекта.

## 👥 Роли

| Роль | Кто | Зона ответственности |
|---|---|---|
| **ARCH** | yogoru | Архитектура системы, постановка задач, review, приоритеты |
| **DEV** | oko.webdev | Разработка, интеграция, бэктест, анализ данных |
| **TRADER** | Claude (TRADER) | Торговая экспертиза, разбор сигналов, валидация стратегий, живой анализ рынка, видение автоматизации |

**Workflow:** ARCH ставит задачу → DEV берёт в работу → ARCH делает review → TRADER валидирует с точки зрения реальной торговли

**Коммуникация между ролями:** любая роль **задаёт вопросы** другим ролям когда нужно уточнение, решение или экспертиза. Вопросы пишутся в [DISCUSSION.md](DISCUSSION.md) с явным тегом получателя.

| От \ К | → ARCH | → DEV | → TRADER |
|---|---|---|---|
| **ARCH** | — | Уточнения по реализации, оценка сложности | Валидация стратегии, приоритет фичи с торговой точки зрения |
| **DEV** | Неясность в спеке, архитектурный выбор, приоритет | — | Как это поведение выглядит в реальной торговле? |
| **TRADER** | Как реализована логика X? Что планируется в Фазе N? | Нужна команда Y, данные Z для анализа | — |

**Формат вопроса в DISCUSSION.md:**
```
→ ARCH: [вопрос]
→ DEV: [вопрос]
→ TRADER: [вопрос]
```

---

## 💬 Discussion — живой диалог агентов

> Хронологический лог перенесён в **[DISCUSSION.md](DISCUSSION.md)** (файл стал слишком большим).
> Новые сообщения добавлять туда же.

---

## 🎯 Задачи TRADER

> Торговые задачи — исследования, спецификации, валидации. Выполняются в [DISCUSSION.md](DISCUSSION.md) или отдельными постами.
> **Статусы:** 🔴 срочно | 🟡 важно | 🟢 в плане | 🔵 backlog | ✅ выполнено

---

## 📊 Активные задачи — сводная таблица

| ID | Ст | Описание | Роль |
|---|---|---|---|
| [DEV-64A](#dev-64a) | ✅ | Global max_rr=3.0 enforce в register_trade() + WL breach (исправлено 29.03) | DEV |
| [DEV-64B](#dev-64b) | ✅ | signal_regime_block: pivot_reversal block в RANGE/TREND_DOWN | DEV |
| [DEV-74](#dev-74) | ✅ | DUAL_TP в RANGE деактивировать → SINGLE (TRADER 29.03, avg_R=-0.942) | DEV |
| [DEV-75](#dev-75) | ✅ | Перевернуть иерархию TP: 1D→1W→confluence→1M в get_tp_by_hierarchy() | DEV |
| [ARCH-55](#arch-55) | 🟢 | sl_tp_calculator.py — единая точка SL/TP (TRADER 29.03, бэклог апрель) | ARCH |
| [DEV-66](#dev-66) | ✅ | factor 1.1 → 1.25 в config.yaml (бэктест подтвердил) | DEV |
| [DEV-65](#dev-65) | ✅ | Бэктест: tsl_line vs ATR×1.5 — проблема в RR=18x, не в SL | DEV |
| [DEV-64C](#dev-64c) | ✅ | Отменено: не нужно после DEV-64A (max_rr=3.0 устраняет первопричину) | DEV |
| [DEV-59](#dev-59) | ✅ | Закрыто через DEV-64A: global max_rr=3.0 кепает pivot_reversal | DEV |
| [DEV-67](#dev-67) | ✅ | Cascade TSL fallback: prev_tsl_tf при развороте тренда | DEV |
| [DEV-68](#dev-68) | ✅ | WL breach min_strength guard (DOGE str=18 баг) | DEV |
| [DEV-53](#dev-53) | ✅ | L3 Фаза B: cond4 WT freshness + CHoCH penalty (-8) | DEV |
| [ARCH-52](#arch-52) | ✅ | Ретроспектива PROJECT-LOG.md по архивным задачам (55 шт) | ARCH |
| [ARCH-45](#arch-45) | 🔄 | Плановый ревью: OutcomePredictor AUC + adaptive weights… | ARCH |
| [ARCH-48](#arch-48) | ✅ | Weekly Pivot Bias Filter: Phase B включена 28.03 (WR blocked=17% vs allowed=22%) | ARCH |
| [TR-001](#tr-001) | 🔄 | Ежедневный разбор Watch List с живыми свечами | TRADER |
| [TR-007](#tr-007) | 🔄 | Валидация новых детекторов перед внедрением | TRADER |
| [DEV-61](#dev-61) | ✅ | RANGE-специфичный RR cap + min_strength_by_regime | DEV |
| [DEV-62](#dev-62) | ✅ | Tiered EXPIRED: конвертация прибыльных TREND позиций в … | DEV |
| [DEV-69](#dev-69) | ✅ | WL breach min_strength_wl_breach: 45 — реализовано 29.03 | DEV |
| [DEV-70](#dev-70) | ✅ | ARCH-04 gap: cfg передать в get_regime_params() + комментарий sl_factor | DEV |
| [DEV-73](#dev-73) | ✅ | TSL gate fix: активировать при +1R для DUAL/TRIPLE (не ждать TP1 hit) | DEV |
| [ARCH-54](#arch-54) | ✅ | Рефакторинг core/ — разбивка по подпапкам, валидация TR-008 ✅ 27.03.2026 | ARCH+DEV+TRADER |
| [DEV-71](#dev-71) | ✅ | ARCH-54 Фаза 1: создать папки + переместить файлы + stub re-exports | DEV |
| [DEV-72](#dev-72) | ✅ | ARCH-54 Фаза 2: обновить CLAUDE.md структуру проекта | DEV |
| [TR-008](#tr-008) | ✅ | ARCH-54 Фаза 3: валидация — 31/31 модулей ОК, ImportError нет (27.03.2026) | TRADER |
| [ARCH-51](#arch-51) | ✅ | MTFSMCSnapshot: smc_h4/smc_d1 в MTFContext — shadow mode активен | ARCH→DEV |
| [DEV-63](#dev-63) | ✅ | ARCH-51 Фаза 1: реализация MTFSMCSnapshot + shadow logging | DEV |
| [ARCH-53](#arch-53) | ✅ | OTE детектор: спек готов → DEV-76 | ARCH |
| [DEV-76](#dev-76) | ✅ | ARCH-53: `core/signals/ote_detector.py` + shadow mode | DEV |
| [ARCH-44](#arch-44) | 🔵 | Добавить роль DATA в команду | ARCH |
| [ARCH-47](#arch-47) | 🔵 | SMC contradiction filter: SHORT при нулевых медвежьих S… | ARCH |
| [ARCH-56](#arch-56) | ✅ | MTF Interpreter v2 Phase B: phase/cascade/avoid_reason/named_pattern спек | ARCH |
| [ARCH-57](#arch-57) | 🔵 | Confluence TRADER/RANGE tier parameter (April backlog) | ARCH |
| [ARCH-58](#arch-58) | 🔴 | TP Architecture: все детекторы → только entry+SL, TP через get_tp_by_hierarchy() централизованно | ARCH |
| [DEV-77](#dev-77) | 🟢 | OrderExecutor: core/trading/order_executor.py (VST/SIM execution) | DEV |
| [DEV-78](#dev-78) | 🟢 | PositionManager + PositionSizer + live_orders table + order_reconciler | DEV |
| [DEV-79](#dev-79) | ✅ | Trading Panel: web/static/ рефакторинг (HTML/CSS/JS из dashboard_server.py) | DEV |
| [DEV-80](#dev-80) | ✅ | Trading Panel: /trading page + Position Sizer UI + badge SIM/VST/LIVE | DEV |
| [DEV-81](#dev-81) | ✅ | FUNDING_EXTREME detector: core/signals/funding_detector.py | DEV |
| [DEV-82](#dev-82) | ✅ | LIQUIDITY_SWEEP detector: core/signals/liquidity_sweep_detector.py | DEV |
| [DEV-83](#dev-83) | ✅ | ARCH-56 реализация: phase_detector + zone_cascade + avoid_reason + named_pattern | DEV |
| [DEV-84](#dev-84) | ✅ | L3 Фаза C: FVG/OB + OTE shadow logging — реализовано 28.03 | DEV |
| [DEV-85](#dev-85) | ✅ | OTE v2: Step0 stale-invalidation + Step1 wide [0.705-0.786] + ATR-trend gate | DEV |
| [DEV-86](#dev-86) | ✅ | `get_tp_by_hierarchy()`: убрать R4–R5/S4–S5 расширенные уровни | DEV |
| [DEV-87](#dev-87) | 🟢 | OTE backtest v2: проверить WR после Step0+Step1 фильтров (ждёт shadow данных ~11.04) | DEV |

---

### ARCH-54 — Рефакторинг core/ — разбивка по папкам ✅
**Статус:** ✅ Завершён — DEV-71/72 ✅, TR-008 ✅ 27.03.2026
**Агент:** ARCH+DEV+TRADER
**Источник:** ARCH 29.03.2026

**Полный спек:** [DISCUSSION.md — ARCH-54](DISCUSSION.md#2903-arch--arch-54-рефакторинг-core--разбивка-по-папкам)

**9 новых папок:** infra, indicators, signals, pivots, mtf, trading, ml, confluence, ui, db
**Стратегия:** stub re-exports → 132 файла с импортами не трогаем
**Порядок:** db → ui → ml → indicators → pivots → signals → mtf → infra → trading → confluence

---

### DEV-73 — TSL gate fix: активировать при +1R для DUAL/TRIPLE ✅
**Статус:** ✅ реализовано 29.03.2026
**Агент:** DEV (фикс) + ARCH (ревью решения)
**Источник:** TRADER 29.03.2026

**Проблема:** `trade_simulator.py:995` — TSL для DUAL_TP/TRIPLE_TP_TSL активируется только после TP1 hit.
Для SINGLE — при +1R. Результат: 83.6% TRIPLE и 69.5% DUAL сделок уходят в полный SL без TSL защиты.

**Данные:**
- DUAL_TP avg_R при TP1 hit = **+0.646** (vs SINGLE = **+6.211**)
- TRIPLE_TP_TSL: 602 из 720 сделок → полный SL без TP1

**Фикс (одна строка):**
```python
# trade_simulator.py:995
# БЫЛО:
_tsl_gate = (tp1_hit_at is not None) if _is_multi_tp else (current_r >= tsl_activation_r)
# СТАЛО:
_tsl_gate = (current_r is not None and current_r >= tsl_activation_r)
```

**→ ARCH:** нужен approve — DEV-40 вводил gate намеренно. Данные показывают что gate вредит.

---

### DEV-71 — ARCH-54 Фаза 1: создать папки + переместить + stubs 🔄
**Статус:** 🔄 в работе — структура создана, есть проблема с circular imports
**Агент:** DEV
**Зависит от:** ARCH-54 спек (готов)

Что сделано: все 10 папок созданы (db, ui, ml, indicators, pivots, signals, mtf, infra, trading, confluence).
Все stub-файлы в core/ существуют.
⚠️ Проблема: часть файлов в подпапках являются stubs (git HEAD уже содержал stubs при копировании).
⚠️ core/ui/__init__.py создавал circular import через intelligence_formatter → исправлено.
Следующий шаг: восстановить реальные файлы в подпапках + убрать eager imports из __init__.py.

---

### DEV-72 — ARCH-54 Фаза 2: обновить документацию ⛔
**Статус:** ⛔ заблокирована DEV-71 (DEV-71 ещё не завершена)
**Агент:** DEV

Обновить: CLAUDE.md (раздел "Структура проекта"), docs/ARCHITECTURE.md.

---

### TR-008 — ARCH-54 Валидация: сигналы работают после рестарта ✅
**Статус:** ✅ Завершён — TRADER 27.03.2026
**Агент:** TRADER

**Результаты импорт-теста (27.03.2026):**
- 31/31 модулей из новых подпапок core/ — OK
- bot_with_subscriptions.py — OK (без ошибок)
- bot.loops.scan_loop, bot.loops.trade_tracker — OK
- Все stub re-exports работают корректно

**Итог: ARCH-54 полностью завершён.**

---

### DEV-70 — ARCH-04 gaps: cfg + sl_factor комментарий ✅
**Статус:** ✅ реализовано 29.03.2026
**Агент:** DEV
**Источник:** ARCH ревью 26.03.2026

**Gap 1 (sl_factor):** добавить комментарий в `regime_strategy.py` и `trade_simulator.py` — `sl_factor` reserved, в симуляторе не применяется намеренно (SL рассчитывается в trading_intelligence.py).

**Gap 2 (cfg):** `trade_simulator.py:451` вызывает `get_regime_params(regime)` без cfg → config-секция `risk_management.regime_strategy` в production игнорируется. Фикс — одна строка:
```python
from core.config_loader import config as _cfg_rs
regime_params = get_regime_params(regime, cfg=_cfg_rs)
```

---

### DEV-69 — WL breach min_strength_wl_breach: 45 ✅
**Статус:** ✅ реализовано 29.03.2026 (config.yaml + scan_loop.py:54)
**Агент:** DEV
**Источник:** TRADER (CHECK str=56 не прошёл бы после DEV-68)

Добавить в `config.yaml` под `signal_quality`: `min_strength_wl_breach: 45`.
В `scan_loop.py:54` читать `min_strength_wl_breach` с fallback на `min_strength_register`.
После рестарта проверить SQL: `SELECT AVG(strength) FROM simulated_trades WHERE signal_type='watch_list_breach'`.

---

### ARCH-51 — MTFSMCSnapshot в MTFContext 🟡
**Статус:** 🔥 В РАБОТЕ — ARCH 29.03.2026, DEV-спек готов → создана DEV-63
**Агент:** ARCH → DEV
**Источник:** ARCH (25.03.2026, DISCUSSION.md)
**Зависит от:** ничего
**Блокирует:** ARCH-53 (OTE детектор), DEV-63 (Multi-TF SMC snapshot)

Добавить `MTFSMCSnapshot` dataclass в `core/signals/signal_models.py` и поля `smc_h4 / smc_d1` в `MTFContext`.
Реализовать `build_mtf_smc_snapshot()` в `core/smc/models.py`.
Shadow mode: логировать конфликты 15m vs 4h OB в `features_json["arch51_*"]`.

**Полный спек:** [DISCUSSION.md — ARCH-51 + DEV-63](DISCUSSION.md) — финальный исправленный спек 29.03.2026

---

### DEV-63 — ARCH-51 Фаза 1: MTFSMCSnapshot реализация ✅
**Статус:** ✅ Завершён — DEV 29.03.2026
**Агент:** DEV
**Источник:** ARCH-51 (29.03.2026)
**Зависит от:** ничего (SMC модули полностью готовы)
**Блокирует:** ARCH-53 (OTE), Фаза 2 score-модификаторы

**3 файла, 4 шага:**

1. `core/signals/signal_models.py` — добавить `MTFSMCSnapshot` dataclass + поля `smc_h4`/`smc_d1` в `MTFContext`
2. `core/smc/models.py` — добавить `build_mtf_smc_snapshot()` после `analyze_smc()`
3. `core/trading_intelligence.py:623` — вызов snapshots (4h + 1d)
4. `core/trading_intelligence.py:~715` — shadow logging в `recommendation.metadata["arch51_*"]`

**⚠️ Фаза 1 = shadow only. НЕ менять overall_strength, НЕ блокировать сигналы.**

**Полный спек с кодом:** DISCUSSION.md → `[29.03.2026] ARCH — ARCH-51 DEV-спек`

---

### ARCH-53 — OTE детектор ✅
**Статус:** ✅ Спек готов — ARCH 29.03.2026 → DEV-76 создан
**Агент:** ARCH → DEV
**Источник:** TRADER (24.03.2026)

Спек записан в DISCUSSION.md [29.03.2026 ARCH — ARCH-53 DEV-спек].
Вся инфраструктура готова (fibonacci.py, structure.py, swing_points.py).
Реализация: DEV-76.

---

### DEV-76 — ARCH-53: OTE Detector ✅
**Статус:** ✅ Завершён — DEV 29.03.2026 | Бэктест: 26.03.2026
**Агент:** DEV
**Источник:** ARCH-53 (29.03.2026)
**Зависит от:** DEV-63 ✅ (smc_context доступен в trading_intelligence)
**Блокирует:** ничего (shadow mode) | **Разблокирует:** DEV-77 (OTE v2)

**Результаты бэктеста** (20 пар / 30 дней / `scripts/backtest_ote_mtf.py`):
- SWING [1h/4h/1d→15m]: WR=26.8%, AvgR=-0.197, Sharpe=-2.35 → **ОТКАЗ**
- SCALP [15m→3m]: WR=32.7%, AvgR=-0.02, Sharpe=-0.23 → **ОТКАЗ**
- Wide OTE [0.705–0.786]: WR=33.5%, AvgR=+0.006 → потенциал при добавлении тренд-фильтра
- Tight OTE [0.618–0.705]: WR=20.5% → **антипаттерн**, убрать

**⚠️ shadow_mode=True. НЕ добавлять в production до DEV-77 (тренд-фильтр + Wide only).**

---

### DEV-67 — Cascade TSL fallback при развороте тренда ✅
**Статус:** ✅ реализовано 25.03.2026 — trade_simulator.py:1055-1072
**Агент:** DEV
**Источник:** ARCH (анализ DOT id=3043)

**Проблема:** Cascade TSL при развороте тренда теряет эскалированный TF (4h) и падает на entry TF (15m). DOT был открыт LONG, TSL эскалировал до 4h (trenddown=1.4272), но после разворота тренда на DOWN cascade не нашёл ни одного подтверждённого TF → fallback на 15m (trenddown=1.3976) → TSL не закрыл позицию.

**Решение (Вариант B от ARCH):**
После основного цикла эскалации добавить защитный fallback:
```python
# В trade_simulator.py после строки ~1053
if df_tsl is None and prev_tsl_tf != DEFAULT_TIMEFRAME:
    try:
        df_fallback = await data_collector.get_ohlcv(symbol, timeframe=prev_tsl_tf, limit=100)
        if df_fallback is not None and len(df_fallback) >= 50:
            df_tsl = calculate_trend(df_fallback)
            tsl_tf_used = prev_tsl_tf
            logger.info("[cascade_tsl] %s: trend reversed, fallback to prev_tsl_tf=%s",
                        symbol, prev_tsl_tf)
    except Exception:
        pass
```

**Файл:** `core/trade_simulator.py` (~строка 1053, после цикла эскалации)

---

### DEV-68 — WL breach min_strength guard ✅
**Статус:** ✅ реализовано (в uncommitted) — scan_loop.py:53-57
**Агент:** DEV
**Источник:** TRADER анализ 25.03.2026 (DOGE id=3237 str=18 в OPEN)

**Проблема:** `_handle_wl_breach_entry()` не проверял `strength` перед регистрацией — WL breach сделки регистрировались с любым score, обходя `min_strength=50` из `is_actionable`.

**Решение:** Gate 0 в начале функции — проверка `score < min_strength_register` (из config, default=75).

---

### DEV-53 — L3 Фаза B: cond4 WT freshness + CHoCH soft penalty ✅
**Статус:** ✅ реализовано 25.03.2026
**Агент:** DEV
**Источник:** TR-006 спек (TRADER 23.03), TR-007 CHoCH gap (24.03)

**Что добавлено:**
1. `signal_checkers.py` — `wt_cross_bar_index = len(df_wt) - 1` в data WT сигналов (LONG + SHORT)
2. `trading_intelligence.py` DEV-37 блок — сохранение `dist_pivot_pct` и `tier1_pct` в `recommendation.metadata`
3. `trading_intelligence.py` DEV-52-L3 блок — cond4 (WT freshness ≤3 bars + near_pivot) + CHoCH soft penalty -8

**CHoCH penalty:** активен всегда при наличии `l3_checker` конфига. BOS блок — только при `enabled: true`.
**Лог:** `[DEV-52-L3] cond3=... cond4=... cond5=... choch_pen=... met=N/3`

---

### ARCH-52 — Ретроспектива PROJECT-LOG.md ✅
**Статус:** ✅ выполнено 25.03.2026
**Агент:** ARCH (DEV)

**Что сделать:** Прочитать `TASKS-ARCHIVE.md` (55 выполненных задач) и для каждой
значимой задачи добавить запись в `/workspace/PROJECT-LOG.md` в раздел `## 📅 История изменений`.

**Критерий значимости** — пропускать мелкие технические фиксы, писать о:
- новых функциях и компонентах
- исправлении багов которые влияли на торговлю
- архитектурных решениях
- изменениях в логике сигналов или фильтрации

**Стиль:** Проблема → Решение → Результат. Простым языком, 4-6 строк на запись.
Технические термины — с коротким пояснением. Новые компоненты — в раздел `## 🧩 Компоненты системы`.

**Источник:** `TASKS-ARCHIVE.md`
**Результат:** `PROJECT-LOG.md` с историей ~20-30 ключевых изменений проекта.

---

### TR-001 — Ежедневный разбор Watch List с живыми свечами
**Статус:** 🔄 периодическая
**Последний разбор:** 28.03.2026 | 20 открытых сделок | STG SHORT +0.97R, LTC SHORT +0.78R | WL: ENA RSI=12, JUP RSI=18 — extreme oversold, ждём bounce сигнал | → memory/trader_analyses/2026-03-28.md
**Следующий:** 29.03.2026

**Что делать:** взять 4-6 пар из Watch List или свежих сигналов, посмотреть живые свечи (WT, тренд, wick structure), дать оценку: подтверждает рынок сигнал или нет?

**Периодичность:** не реже 3 раз в неделю.

**Почему важно:** DEV смотрит на цифры, TRADER смотрит на свечи. BEAT с wick↑=1.54% при теле 0.45% виден сразу на графике — в логе нужно считать.

#### Где хранить разборы

**Файл:** `memory/trader_analyses/YYYY-MM-DD.md` — один файл в день.

В TASKS.md Discussion — только краткая ссылка:
```
TRADER 22.03 — разбор 5 пар live → memory/trader_analyses/2026-03-22.md
```

Почему не в TASKS.md напрямую: TASKS уже большой. Отдельные файлы — поиск по дате тривиален, в будущем можно агрегировать скриптом для паттерн-анализа или ML-разметки.

#### Что включать в разбор (шаблон)

```markdown
## [YYYY-MM-DD HH:MM UTC] TRADER — Разбор N пар live

### СИМВОЛ/USDT
- **Цена:** X.XXX (+Y.Y% за 24ч)
- **Режим:** TREND_UP / RANGE / HIGH_VOL
- **ATR:** 0.XXX (Y.Y% от цены)
- **WT1/WT2:** -32 / -28 (нейтраль, выходит из OS)
- **Тренд:** UP / DOWN (supertrend не пробит / пробит)
- **Пивоты:** PP=X.XX (-1.9%), R1=X.XX (+3.4%), S1=X.XX (-5.6%)
- **В WL с:** 21.03 19:42 UTC | Причина: wt_b_signal str=78 conf=0.61
- **Сделка в БД:** OPEN (entry=X.XX, SL=X.XX, TP=X.XX, R текущий=+0.7)
  — или: нет открытой сделки
- **Свечная картина (4h/1h):** описание — FVG, wicks, структура
- **Вывод:** держу / выхожу / идея отработана / жду пробой
```

**Минимум без которого разбор неполный:**
1. Режим — TREND_UP/RANGE/HIGH_VOL
2. WT1/WT2 числами (не только OS/OB/N)
3. % до ближайшего пивота (фильтр входа)
4. Когда попало в WL и почему (signal_type + strength + conf)
5. Есть ли открытая сделка и текущий R

**Данные берём:** `/intelligence SYMBOL` в боте + таблица open_trades на дашборде.

---

### TR-007 — Валидация новых детекторов перед внедрением
**Статус:** 🔄 постоянная задача

**Когда включается:** когда DEV или ARCH говорит "→ TRADER: проверь работает ли это в реальной торговле?"

**Формат:** TRADER смотрит на 5-10 живых примеров сигнала детектора и даёт вердикт: "Вижу смысл", "Вижу ложный сигнал потому что...", "Нужна доработка условия N".

**Текущая очередь:**
- [x] ✅ 23.03 — `use_outcome_predictor: false` подтверждён: p_win нет в features_json, сигналы регистрируются без фильтра
- [x] ✅ 23.03 — Pivot Proximity Filter (DEV-37): WR near=9% → very_far=5%. Важное: pivot_reversal без PPF WR=53%. Вопрос закрыт 24.03 ARCH: `_ppf_skip_pivot_reversal` реализован корректно — composite с wt_b/mtf/confluence применяет PPF, чистый pivot_reversal — пропускает. Изменений не требуется.
- [x] ✅ 23.03 — Q-ARCH-TRADER-1/3 закрыты: DASH/FIL по тренду, SKYAI контр-тренд в RANGE; одно изменение = блок LONG при TREND_DOWN
- [x] ✅ 23.03 — RANGE+BEARISH soft block: данные говорят за (WR=0% в RANGE/BEARISH/LONG). Рекомендован score -=20 в shadow mode. Ждём одобрения ARCH.
- [x] ✅ 24.03 — DEV-55 staleness: логика верна для reversal_scanner. ⚠️ signal_checkers.py::check_pivot_touch() не пишет pivot_bars_ago → penalty не работает для pivot_reversal. → DEV: добавить
- [x] ✅ 24.03 — DEV-52 L3 shadow cond3+5: GPS SHORT заблокирован ✓, GRT LONG пропущен ✓. ⚠️ CHoCH soft penalty не реализован → добавить в DEV-53 (Фаза B)
- [x] ✅ 24.03 — DEV-56 weekly_bias валидация: pivot_reversal LONG TREND_UP WR=9.1% (1/11) — подтверждает необходимость weekly gate. КРИТИЧЕСКИЙ GAP: DEV-35 R:R cap не применяется к pivot_reversal (XMR=17.7x, SQD=23.6x) → DEV-59 создан
- [x] ⏳ 06.04 — SMC-структура как фильтр: ОТЛОЖЕНО до 06.04 (нужно 200+ чистых сделок после DEV-32/49)

**Статус очереди:** ✅ все задачи 24.03 выполнены. Следующая активация: 27-29.03.2026 (проверка features_json weekly_bias данных после 3-5 дней накопления).

---

### ARCH-48 — Weekly Pivot Bias Filter: top-down контекст для направления входа ✅
**Статус:** ✅ Phase B активирована 28.03.2026 — n=67 blocked WR=17% vs n=79 allowed WR=22% → фильтр работает
**Источник:** TRADER 24.03.2026 — анализ 23 SHORT в день памп, DOT #3043 LONG в тройном медвежьем контексте

**Проблема:** Бот принимает решение о направлении (LONG/SHORT) без учёта macro-контекста пары. 23.03: 23 SHORT открыты при цене выше Weekly PP → все по SL (-1R). Одновременно трейдер вручную взял +300-560% на GRT (LONG, выше weekly PP) и SHIB (SHORT, ниже weekly PP). Каждая пара в своём контексте.

**Принцип:** `price > weekly_PP` → BULLISH bias для пары → торговать LONG. `price < weekly_PP` → BEARISH bias → торговать SHORT. Исключение: контр-тренд разрешён только у Weekly R/S уровней (confluence).

**Архитектурная точка вставки:** `analyze_symbol()` → после `_calculate_adaptive_weighted_strength()`, перед `_generate_recommendation()`. Аналогично DEV-32 (regime_direction_block) по паттерну.

**Источник данных:** `mtf_context.weekly_pivots` (уже загружается в `_build_mtf_context()`). Новых API-запросов не нужно.

#### Фаза A: Shadow mode (DEV-56 — 🔴 немедленно)
```python
# В analyze_symbol(), после score-вычислений:
weekly_pp = getattr(mtf_context, "weekly_pivots", {}).get("PP") if mtf_context else None
if weekly_pp and current_price:
    weekly_bias = "BULLISH" if current_price > weekly_pp else "BEARISH"

    # multi_tf context score (0-3): сколько PP-уровней цена ниже (для LONG-анализа)
    monthly_pp = getattr(mtf_context, "monthly_pivots", {}).get("PP") if mtf_context else None
    daily_pp = getattr(mtf_context, "daily_pivots", {}).get("PP") if mtf_context else None
    ctx_score = sum([
        monthly_pp and current_price < monthly_pp,
        weekly_pp  and current_price < weekly_pp,
        daily_pp   and current_price < daily_pp,
    ])

    direction_str = direction.value if hasattr(direction, "value") else str(direction)
    gate_would_block = (
        (direction_str == "LONG"  and weekly_bias == "BEARISH") or
        (direction_str == "SHORT" and weekly_bias == "BULLISH")
    )

    # Shadow: только лог + запись в features_json
    if gate_would_block:
        logger.info("[ARCH-48 shadow] %s: direction=%s blocked by weekly_bias=%s (ctx_score=%d)",
                    symbol, direction_str, weekly_bias, ctx_score)

    # Записать в recommendation.data или pass через для features_json:
    weekly_bias_data = {
        "weekly_bias": weekly_bias,
        "weekly_context_score": ctx_score,
        "weekly_gate_would_block": gate_would_block,
    }
```

**features_json записывать:** `weekly_bias`, `weekly_context_score`, `weekly_gate_would_block`

#### Фаза B: Production gate (DEV-58 — после 3-5 дней данных Фазы A)
```python
if gate_would_block:
    weekly_r1 = getattr(mtf_context, "weekly_pivots", {}).get("R1") if mtf_context else None
    weekly_s1 = getattr(mtf_context, "weekly_pivots", {}).get("S1") if mtf_context else None
    near_weekly_r = weekly_r1 and abs(current_price - weekly_r1) / current_price < 0.015
    near_weekly_s = weekly_s1 and abs(current_price - weekly_s1) / current_price < 0.015

    if direction_str == "SHORT" and weekly_bias == "BULLISH" and not near_weekly_r:
        overall_strength -= 25  # short в bullish без confluence с weekly R
    elif direction_str == "LONG" and weekly_bias == "BEARISH" and not near_weekly_s:
        if ctx_score == 3:
            # Тройной медвежий (Monthly+Weekly+Daily все выше) → hard block
            action = "WATCH"
            logger.info("[ARCH-48] %s: hard block — тройной медвежий ctx_score=3, direction=LONG", symbol)
        else:
            overall_strength -= 25
```

#### Конфиг:
```yaml
trading:
  weekly_bias_filter:
    enabled: false           # Фаза A: false (shadow). Фаза B: true
    soft_penalty: 25         # score penalty при направлении против bias
    hard_block_ctx_score: 3  # hard block при тройном контрастном контексте
    near_level_pct: 1.5      # % от уровня = "рядом с Weekly R/S" (исключение из блока)
```

**→ DEV-56:** Фаза A shadow. ✅ выполнено 24.03.2026
⚠️ **Баг исправлен 27.03:** `weekly_bias` вычислялся в trading_intelligence.py и сохранялся только в `recommendation.metadata`, но НЕ передавался в `features_json`. В `bot/monitoring.py` добавлена передача трёх полей (`weekly_bias`, `weekly_context_score`, `weekly_gate_would_block`) в `extra_features`. До рестарта бота данные не накапливались.
**→ DEV-58:** ✅ Фаза B production активирована 28.03.2026 (config `enabled: true`).
- soft_penalty=25 (LONG/BEARISH без уровня → strength-25)
- hard_block ctx≥3 → action=WATCH
- Исключение расширено 28.03: S1+**S2+PP** для LONG, R1+**R2+PP** для SHORT (было только S1/R1)
- near_level_pct=1.5% подтверждён данными (реальные расстояния 3-9%, порог не слишком широк)

---

### ARCH-47 — SMC contradiction filter: SHORT при нулевых медвежьих SMC 🔵
**Статус:** 🔵 заблокировано до 06.04.2026 — недостаточно данных (50–87/категорию при медвежьем рынке)
**Источник:** TRADER 23.03.2026 — GPS/USDT SHORT при BULLISH SMC

**Идея:** при LONG отсутствии подтверждения SMC (`smc_active_bear_ob_count=0 + smc_trend=BULLISH + BULLISH_BOS`) → SHORT требует `score ≥ 85` вместо 75.

**Условие активации:** 06.04.2026:
- N ≥ 200 на категорию (aligned/conflict)
- WR aligned > WR hard_conflict (фильтр логически работает)
- Нейтральный/бычий рынок для чистоты статистики

---

### ARCH-45 — Плановый ревью: OutcomePredictor AUC + adaptive weights после чистых данных 🔄
**Статус:** 🔄 в работе — baseline снят 23.03.2026, финальный ревью ≈ 06.04.2026
**Источник:** Сессия 23.03.2026 — система стабилизирована после DEV-49/50

**Цель:** оценить качество ML и adaptive_weights после 2 недель чистых данных (post DEV-32/33/49).

#### 📊 BASELINE (23.03.2026)

**OutcomePredictor:** ❌ не обучен — `sklearn не установлен` в текущем окружении. → DEV-51

**WR baseline (2066 чистых сделок):** 29.4% (TP+TSL)

**Adaptive weights (чистые):**
| Signal Type | n | avg_R |
|---|---|---|
| confluence | 1188 | +1.52 |
| wt_signal | 423 | +0.39 |
| pivot_reversal | 353 | **+0.29** ← (было +0.50) |
| trend_signal | 43 | -0.25 |
| watch_list_breach | 11 | -0.31 |

**Guards эффект (id>3100, сделки после guards):**
- TREND_DOWN/LONG пробросов после рестарта: **0** ✅ (3 сделки 02:28 UTC = до рестарта)
- HIGH_VOL пробросов: **0** ✅ DEV-33 работает
- WR последних 49 сделок: 13-25% — медвежий рынок, ожидаемо

**⚠️ Критическая находка:** `sklearn` не установлен → OutcomePredictor, R-predictor, ML pipeline полностью отключены. → Создана DEV-51.

#### Чеклист для финального ревью (≈06.04.2026):

1. **OutcomePredictor AUC** (после установки sklearn + DEV-51):
   - AUC > 0.55 → активировать ARCH-21 (sliding window training_window=500)
   - AUC < 0.50 → ищем новые признаки (MTF bias, price_zone?)

2. **Adaptive weights pivot_reversal trend**:
   - Если avg_R pivot_reversal > 0 после 2 недель → wt_signal лучший кандидат на повышение веса
   - Если avg_R trend_signal стабильно < 0 → рассмотреть отключение или ограничение до 1 типа

3. **WR post-fix** (сделки после 25.03.2026):
   - Ожидаем ↑ с 29% к 40%+ (убрали 52% контр-тренд LONG/TREND_DOWN)

4. **TR-008 повторный** — 50 SL-сделок из новых данных → передать TRADER

**Если к 06.04 < 200 новых сделок:** перенести на 13.04, не форсировать.

---

### ARCH-44 — Добавить роль DATA в команду 🔵
**Статус:** 🔵 отложено — триггер: CV AUC > 0.55 или ML становится основным источником решений
**Источник:** обсуждение команды 24.03.2026

**Контекст:**
Текущая команда (ARCH/DEV/TRADER) не имеет явного владельца ML/статистики. Пробел закрывается добавлением роли DATA когда наступит триггер.

**Зона ответственности DATA:**
- Качество ML-моделей: feature engineering, CV AUC, переобучение
- Статистическая валидность выводов (достаточно ли N сделок?)
- Решения: когда переобучать, что добавить в features
- Диагностика деградации: win_rate падает → почему?

**Триггеры для активации роли:**
1. CV AUC OutcomePredictor > 0.55 (сейчас ~0.33 — хуже случайного)
2. ML становится основным источником входов (сейчас отключён)
3. Накопление 500+ закрытых сделок с заполненным `regime`

**До триггера:** ML-вопросы делятся между DEV (код) и TRADER (интерпретация).

---

### DEV-62 — Tiered EXPIRED: конвертация прибыльных TREND позиций в TSL ✅
**Статус:** ✅ реализовано 25.03.2026
**Источник:** TRADER TR-001 25.03 (19 EXPIRED avg_R=+3.81) + ARCH решение 25.03

**Проблема:** позиции в TREND режиме закрываются по TTL (EXPIRED) когда уже значительно в прибыли (+3.81R avg), потому что TP на высоком RR недостижимо за 4h. Прибыль теряется.

**Решение:**
```python
# core/trade_simulator.py → при проверке EXPIRED статуса (check_open_trades_with_tsl):
cfg_expired = config.get("trading", {}).get("expired_management", {})
min_r = cfg_expired.get("tsl_convert_min_r", 1.5)
tsl_regimes = cfg_expired.get("tsl_convert_regimes", ["TREND_UP", "TREND_DOWN"])

if current_r is not None and current_r >= min_r and regime in tsl_regimes:
    # Не закрывать — убрать TP, TSL продолжает работать
    trade.tp_price = None
    trade.metadata["expired_converted_to_tsl"] = True
    logger.info("[EXPIRED-CONVERT] %s R=%.2f → TSL mode (TP removed)", symbol, current_r)
    return  # не закрывать
else:
    # Обычное EXPIRED
    close_trade(status="EXPIRED", ...)
```

```yaml
trading:
  expired_management:
    tsl_convert_min_r: 1.5
    tsl_convert_regimes: [TREND_UP, TREND_DOWN]
    # RANGE: не конвертировать (возможен быстрый возврат в диапазон)
```

**Файлы:** `config.yaml`, `core/trade_simulator.py`
**Приоритет:** 🟡 — после DEV-61

---

### DEV-61 — RANGE-специфичный RR cap + min_strength_by_regime ✅
**Статус:** ✅ реализовано 25.03.2026
**Источник:** TRADER TR-001 (47/68 OPEN=RANGE, 100% SL) + ARCH решение 25.03

**Проблема:** RANGE режим = SL-фабрика. Две причины: (1) нереальный RR (ATH 49.8x, COOKIE 69.5x), (2) слабые сигналы (str=18, str=49 открываются в RANGE). Текущий global max_rr=6.0 не защищает — среднее RANGE движение = 2.0–2.5x.

**Решение: два параметра в config, применять во ВСЕХ code paths.**

```yaml
signal_quality:
  min_strength: 50          # global (не меняется)
  min_strength_by_regime:   # НОВОЕ — override per regime
    RANGE: 70
    HIGH_VOL: 80
    # TREND_UP/DOWN: используют global min_strength=50

trading:
  sl_management:
    max_rr: 6.0             # global (не меняется)
    max_rr_range: 2.5       # НОВОЕ — override для RANGE
```

**Реализация в `core/trade_simulator.py` → `register_trade()` или `register_trade_async()`:**
```python
# min_strength per regime
min_str_map = cfg_quality.get("min_strength_by_regime", {})
effective_min_str = min_str_map.get(regime, cfg_quality.get("min_strength", 50))
if strength < effective_min_str:
    logger.info("[DEV-61] %s заблокирован: strength=%d < min_strength[%s]=%d",
                symbol, strength, regime, effective_min_str)
    return None

# max_rr per regime
if regime == "RANGE":
    max_rr_effective = cfg_sl.get("max_rr_range", 2.5)
else:
    max_rr_effective = cfg_sl.get("max_rr", 6.0)

if tp_price and sl_price and entry_price:
    rr = abs(tp_price - entry_price) / abs(entry_price - sl_price + 1e-9)
    if rr > max_rr_effective:
        sign = 1 if is_long else -1
        tp_price = entry_price + sign * max_rr_effective * abs(entry_price - sl_price)
```

**Важно:** DEV-61 также нужен в `bot/loops/scan_loop.py::_handle_wl_breach_entry()` — там своя логика RR, не проходит через `register_trade()`.

**Файлы:** `config.yaml`, `core/trade_simulator.py`, `bot/loops/scan_loop.py`
**Приоритет:** 🔴 — первый после рестарта бота

---

### DEV-64A — Global max_rr=3.0 enforce в register_trade() 🆕
**Статус:** ✅ реализовано 26.03.2026
**Источник:** DEV анализ 26.03.2026 — avg_rr_set=20x при WR=5-9%

**Проблема:** `sl_tp.max_rr: 6.0` в config.yaml НЕ применяется в `register_trade()` для не-RANGE режимов. DEV-61 добавил кеп только для RANGE. Итог: TREND/HIGH_VOL сделки регистрируются с RR=10-80x → WR=5% при RR>10x.

**Решение:**
```yaml
trading:
  sl_management:
    max_rr: 3.0          # ← было 6.0, снижаем (оптимум по данным: RR 1-3x WR=59%)
    max_rr_range: 2.5    # RANGE — без изменений (DEV-61)
```

```python
# core/trade_simulator.py → register_trade() — применять ко ВСЕМ режимам:
if regime == "RANGE":
    max_rr_effective = cfg_sl.get("max_rr_range", 2.5)
else:
    max_rr_effective = cfg_sl.get("max_rr", 3.0)  # ← enforce global

if tp_price and sl_price and entry_price:
    rr = abs(tp_price - entry_price) / abs(entry_price - sl_price + 1e-9)
    if rr > max_rr_effective:
        sign = 1 if is_long else -1
        tp_price = entry_price + sign * max_rr_effective * abs(entry_price - sl_price)
        logger.info("[DEV-64A] %s: RR capped %.1f→%.1f (regime=%s)", symbol, rr, max_rr_effective, regime)
```

**Также:** проверить `bot/loops/scan_loop.py::_handle_wl_breach_entry()` на отдельный RR path.
**Файлы:** `config.yaml`, `core/trade_simulator.py`, `bot/loops/scan_loop.py`
**Рестарт бота после реализации.**

---

### DEV-64B — signal_regime_block: заблокировать мёртвые комбинации 🆕
**Статус:** ✅ реализовано 26.03.2026
**Источник:** DEV анализ 26.03.2026 — pivot_reversal+RANGE = 0% WR (33 сделки)

**Данные:**
```
pivot_reversal + RANGE:      33 сделки, WR=0%, avg_R=-1.0  → hard block
pivot_reversal + TREND_DOWN:  8 сделок, WR=0%, avg_R=-1.0  → hard block
confluence + RANGE:          32 сделки, WR=6%              → НЕ блокировать (мало данных)
confluence + TREND_DOWN:     49 сделок, WR=10%             → НЕ блокировать (мало данных)
```

**Конфиг:**
```yaml
signal_quality:
  signal_regime_block:
    pivot_reversal:
      blocked_regimes: [RANGE, TREND_DOWN]
```

**Реализация в `register_trade()` после `regime` определён:**
```python
srb_cfg = cfg_quality.get("signal_regime_block", {})
blocked_for_type = srb_cfg.get(signal_type, {}).get("blocked_regimes", [])
if regime in blocked_for_type:
    logger.info("[DEV-64B] %s заблокирован: %s+%s dead combo", symbol, signal_type, regime)
    return None
```

**Файлы:** `config.yaml`, `core/trade_simulator.py`

---

### DEV-64C — Ревизия приоритета SL-источников
**Статус:** ✅ закрыто 26.03.2026 — DEV-65 показал: проблема в RR=18x (не в SL). DEV-64A устраняет первопричину.
**Источник:** DEV анализ 26.03.2026 — tsl_line как initial SL → инвертированный SL → RR=100x

**Проблема:** коммит `96b0a3a` (14.03) "Swing SL + BE + обязательный MTF_BIAS кросс" поставил `tsl_line` в список кандидатов на initial SL. TSL линия (Supertrend/ATR trailing) рассчитана как **динамический** стоп. В растущем тренде tsl_line > entry для LONG → SL инвертирован → "риск" = 0.01% → RR = 100x. Это был механизм ARIA 112R.

**Правильный порядок SL-источников (initial):**
```
1. swing_low/swing_high (локальный экстремум за N баров)  ← основной
2. pivot уровень (S1/S2 для LONG, R1/R2 для SHORT)        ← если swing не найден в диапазоне
3. ATR-based (entry ± atr_multiplier * ATR)               ← fallback
4. fixed pct из config (sl_pct)                           ← последний resort
[tsl_line → только после активации TSL (+1R), не в initial]
```

**Действия:**
1. Найти в `core/signal_checkers.py` и `core/trading_intelligence.py` где формируется initial SL
2. Удалить/заблокировать `tsl_line` как источник initial SL
3. Добавить guard: если `sl_side_correct()` = False (SL инвертирован) → `sl = entry ± sl_pct`
4. `sl_min_pct: 1.0%` (f06362d) должен быть включён — проверить

**Файлы:** `core/signal_checkers.py`, `core/trading_intelligence.py`, возможно `core/trade_simulator.py`
**Зависимость:** DEV-65 (бэктест) — реализовать только после получения данных

---

### DEV-65 — Бэктест: tsl_line vs ATR×1.5 как initial SL 🟡
**Статус:** ✅ выполнено 26.03.2026
**Источник:** ARCH 26.03.2026 — TRADER инсайт + вопрос DEV-64C Q3

**Цель:** определить данными — tsl_line или ATR×1.5 лучше как initial SL. Результат определяет судьбу DEV-64C.

**Задача:** запустить SQL-анализ на `subscriptions.db`, опубликовать в DISCUSSION.md.

```sql
SELECT
    CASE
        WHEN sl_source LIKE 'tsl_line%' THEN 'tsl_line'
        WHEN sl_source LIKE 'atr%'      THEN 'atr'
        WHEN sl_source LIKE 'swing%'    THEN 'swing'
        WHEN sl_source LIKE 's1:%' OR sl_source LIKE 'pivot%' THEN 'pivot'
        ELSE 'other'
    END as sl_group,
    COUNT(*) as n,
    ROUND(AVG(CASE WHEN status IN ('TP','TSL') THEN 1.0 ELSE 0.0 END)*100, 1) as wr_pct,
    ROUND(AVG(R_multiple), 2) as avg_R,
    ROUND(AVG(CASE WHEN take_profit AND stop_loss AND entry_price
        THEN ABS(take_profit - entry_price) / ABS(entry_price - stop_loss + 1e-9)
        END), 1) as avg_rr_set,
    ROUND(AVG(duration_minutes), 0) as avg_dur_min
FROM simulated_trades
WHERE status != 'OPEN'
  AND created_at > '2026-03-20'
GROUP BY sl_group
ORDER BY n DESC;
```

**Интерпретация результата → решение по DEV-64C:**

| Результат | Решение |
|---|---|
| tsl_line WR ≥ swing/atr | Оставить tsl_line. DEV-64C → закрыть как "не нужно" |
| tsl_line avg_R хуже, avg_rr_set высокий | Проблема в RR (уже фикс DEV-64A), не в SL. DEV-64C → закрыть |
| swing WR и avg_R лучше tsl_line | Переставить приоритет: swing первым, tsl_line fallback |
| tsl_line WR < 20% и avg_R < -0.5 | Убрать tsl_line из initial SL полностью |

**Файлы:** только `subscriptions.db` (read-only SQL)
**Результат опубликовать:** DISCUSSION.md как пост DEV

---

### DEV-66 — TSL factor 1.1 → 1.25 в config.yaml 🟡
**Статус:** ✅ реализовано 26.03.2026
**Источник:** ARCH 26.03.2026 — бэктест DEV-65 + одобрение

**Обоснование:**
- Бэктест (BTC/ETH/SOL/XRP/BNB, 30 дней): F=1.1 avg_R=-0.032, F=1.25 avg_R=+0.009 (+0.041R)
- F=1.1 слишком тесный — TSL преждевременно выбивает позиции
- История: DEV-34 снизил 1.25→1.1 ("меньше ложных выходов"), но данные показали обратное
- TRADER подтверждает: "TSL даёт + даже при неверном направлении"

**Изменение (одна строка):**
```yaml
# config.yaml → analysis.indicators.trend:
factor: 1.25   # DEV-66: было 1.1 (DEV-34), бэктест показал +0.041R при 1.25 vs 1.1
```

**Файлы:** только `config.yaml`
**После изменения:** перезапустить бота (новый factor применится к calculate_trend())

---



### ARCH-56 — MTF Interpreter v2 Phase B: спек phase/cascade/avoid_reason ✅
**Статус:** ✅ Спек написан — 28.03.2026
**Агент:** ARCH
**Источник:** ARCH-50 Phase A ✅ (24.03.2026) + TRADER верификация + аудит 26.03.2026
**Блокирует:** DEV-83

---

#### Шаг 1 — Новые поля в MTFContext (`core/signals/signal_models.py`)

```python
@dataclass
class MTFContext:
    # ... существующие поля без изменений ...

    # ARCH-56 Phase B: новые поля
    phase: Optional[str] = None
    # Значения: "impulse_up" | "impulse_down" |
    #           "correction_down_in_bull" | "correction_up_in_bear" |
    #           "reversal_up" | "reversal_down" | "range"

    zone_state: Optional[str] = None
    # Значения: "cascade_os" | "cascade_ob" |
    #           "partial_os" | "partial_ob" | "neutral"

    avoid_reason: Optional[str] = None
    # Значения: "correction_active" | "cascade_ob_short_only" | "cascade_os_long_only" |
    #           "high_vol_no_trade" | None (= торговать можно)

    pattern_name: Optional[str] = None
    # Значения: "IMPULSE_UP" | "IMPULSE_DOWN" | "WAVE_3_RELOAD" |
    #           "BEARISH_CORRECTION_FADE" | "CASCADE_OS_REVERSAL" |
    #           "CASCADE_OB_REVERSAL" | "REVERSAL_UP" | "REVERSAL_DOWN" | "RANGE_PLAY"

    pattern_confidence: float = 0.0   # 0.0–1.0

    unswept_highs: List[float] = field(default_factory=list)
    # sell-side liquidity: нетронутые swing highs с 1h/4h за последние 20 баров
    unswept_lows: List[float] = field(default_factory=list)
    # buy-side liquidity: нетронутые swing lows с 1h/4h за последние 20 баров
```

---

#### Шаг 2 — Новые функции в `core/mtf/mtf_interpreter.py`

```python
def _detect_phase(
    snapshot: Dict[str, Any],
    smc_h4: Optional["MTFSMCSnapshot"],
    smc_d1: Optional["MTFSMCSnapshot"],
) -> tuple[str, float]:
    """
    Определяет фазу рынка по иерархии TF + SMC контексту.
    Returns: (phase_str, confidence: 0.0-1.0)
    """
    d1_trend = snapshot.get("1d", {}).get("trend")
    h4_trend = snapshot.get("4h", {}).get("trend")
    h1_trend = snapshot.get("1h", {}).get("trend")

    d1_bos  = smc_d1.bos_direction  if smc_d1 else "none"
    h4_bos  = smc_h4.bos_direction  if smc_h4 else "none"
    h4_choch = smc_h4.choch_direction if smc_h4 else "none"

    # IMPULSE: все старшие TF в одном направлении
    if d1_trend == "UP" and h4_trend == "UP" and h1_trend == "UP":
        conf = 0.9 if (d1_bos == "bullish" or h4_bos == "bullish") else 0.7
        return "impulse_up", conf
    if d1_trend == "DOWN" and h4_trend == "DOWN" and h1_trend == "DOWN":
        conf = 0.9 if (d1_bos == "bearish" or h4_bos == "bearish") else 0.7
        return "impulse_down", conf

    # CORRECTION: 1D/4H одно направление, 1H — противоположное
    if d1_trend == "UP" and h4_trend == "UP" and h1_trend == "DOWN":
        return "correction_down_in_bull", 0.8
    if d1_trend == "DOWN" and h4_trend == "DOWN" and h1_trend == "UP":
        return "correction_up_in_bear", 0.8

    # REVERSAL: CHoCH на 4H противоречит тренду 1D
    if d1_trend == "DOWN" and h4_choch == "bullish" and h1_trend == "UP":
        return "reversal_up", 0.6
    if d1_trend == "UP" and h4_choch == "bearish" and h1_trend == "DOWN":
        return "reversal_down", 0.6

    return "range", 0.4


def _detect_zone_cascade(snapshot: Dict[str, Any]) -> str:
    """
    Определяет состояние WT-зон на старших TF.
    cascade_os/ob = 2 senior TF (1d+4h) в OS/OB одновременно.
    """
    d1_zone = snapshot.get("1d", {}).get("zone", "N")
    h4_zone = snapshot.get("4h", {}).get("zone", "N")

    if d1_zone == "OS" and h4_zone == "OS":
        return "cascade_os"   # сильная зона покупки
    if d1_zone == "OB" and h4_zone == "OB":
        return "cascade_ob"   # сильная зона продажи
    if d1_zone == "OS" or h4_zone == "OS":
        return "partial_os"
    if d1_zone == "OB" or h4_zone == "OB":
        return "partial_ob"
    return "neutral"


def _detect_avoid_reason(
    phase: str,
    zone_state: str,
    direction_bias: "SignalDirection",
    regime: Optional[str],
) -> Optional[str]:
    """
    Soft-block: причина НЕ торговать сейчас.
    Возвращает строку или None (= торговать можно).
    Использование: только логирование, НЕ hard-block.
    """
    LONG  = SignalDirection.LONG
    SHORT = SignalDirection.SHORT

    # Коррекции: не входим по направлению коррекции (против тренда)
    if phase == "correction_up_in_bear" and direction_bias == LONG:
        return "correction_active"   # подскок вверх в медвежьем — не LONG
    if phase == "correction_down_in_bull" and direction_bias == SHORT:
        return "correction_active"   # откат вниз в бычьем — не SHORT

    # Cascade zone против направления
    if zone_state == "cascade_ob" and direction_bias == LONG:
        return "cascade_ob_short_only"  # 1D+4H в OB — только SHORT здесь
    if zone_state == "cascade_os" and direction_bias == SHORT:
        return "cascade_os_long_only"   # 1D+4H в OS — только LONG здесь

    if regime == "HIGH_VOL":
        return "high_vol_no_trade"

    return None


def _detect_pattern(
    phase: str,
    zone_state: str,
    senior_matches: int,
) -> tuple[str, float]:
    """
    Определяет named pattern для сигнала.
    Returns: (pattern_name, confidence)
    """
    if phase == "impulse_up" and senior_matches == 3:
        return "IMPULSE_UP", 0.85
    if phase == "impulse_down" and senior_matches == 3:
        return "IMPULSE_DOWN", 0.85
    if phase == "correction_down_in_bull" and zone_state in ("cascade_os", "partial_os"):
        return "WAVE_3_RELOAD", 0.75    # откат в бычьем + OS = откуп импульса
    if phase == "correction_up_in_bear" and zone_state in ("cascade_ob", "partial_ob"):
        return "BEARISH_CORRECTION_FADE", 0.70  # подскок в медвежьем + OB = шорт
    if zone_state == "cascade_os" and phase != "impulse_up":
        return "CASCADE_OS_REVERSAL", 0.65
    if zone_state == "cascade_ob" and phase != "impulse_down":
        return "CASCADE_OB_REVERSAL", 0.65
    if phase == "reversal_up":
        return "REVERSAL_UP", 0.60
    if phase == "reversal_down":
        return "REVERSAL_DOWN", 0.60
    return "RANGE_PLAY", 0.40
```

---

#### Шаг 3 — Обновить `analyze_context()` в `mtf_interpreter.py`

Добавить параметры и вызовы новых функций:

```python
def analyze_context(
    snapshot,
    current_price=0.0,
    weekly_pivots=None,
    regime=None,
    smc_h4=None,         # ← новый параметр (Optional[MTFSMCSnapshot])
    smc_d1=None,         # ← новый параметр (Optional[MTFSMCSnapshot])
    df_1h=None,          # ← новый параметр (для unswept liquidity)
    df_4h=None,          # ← новый параметр (для unswept liquidity)
) -> MTFContext:
    ...
    # после вычисления existing полей:
    phase, phase_conf = _detect_phase(snapshot, smc_h4, smc_d1)
    zone_state = _detect_zone_cascade(snapshot)
    avoid_reason = _detect_avoid_reason(phase, zone_state, direction_bias, regime)
    pattern_name, pattern_conf = _detect_pattern(phase, zone_state, senior_matches)
    unswept_highs, unswept_lows = _extract_unswept_liquidity(df_1h, df_4h)

    ctx = MTFContext(
        # ... existing fields ...
        smc_h4=smc_h4,
        smc_d1=smc_d1,
        phase=phase,
        zone_state=zone_state,
        avoid_reason=avoid_reason,
        pattern_name=pattern_name,
        pattern_confidence=phase_conf,
        unswept_highs=unswept_highs,
        unswept_lows=unswept_lows,
    )
```

```python
def _extract_unswept_liquidity(
    df_1h: Optional[pd.DataFrame],
    df_4h: Optional[pd.DataFrame],
    lookback: int = 20,
) -> tuple[list[float], list[float]]:
    """
    Из swing H/L 1h и 4h извлекает нетронутые уровни ликвидности.
    Swing High "unswept" = за последние lookback баров никто не торговал выше него.
    Sources: calculate_trend() → df["trend"] содержит swing points через SMA/crossover.

    NOTE: Простая версия — берём max rolling high / min rolling low за lookback баров
    как приближение к реальным swing H/L. Полноценные swing points = DEV-83 улучшение.
    """
    highs, lows = [], []
    for df in (df_1h, df_4h):
        if df is None or len(df) < lookback:
            continue
        tail = df.tail(lookback * 2)  # последние 40 баров для контекста
        recent = tail.tail(lookback)   # последние 20 баров = "текущая зона"
        recent_high = recent["high"].max() if "high" in recent.columns else 0
        overall_max = tail["high"].max() if "high" in tail.columns else 0
        overall_min = tail["low"].min() if "low" in tail.columns else 0
        recent_low = recent["low"].min() if "low" in recent.columns else 0

        # Unswept high: выше текущего диапазона (никто не брал стопы там)
        if overall_max > recent_high > 0:
            highs.append(round(overall_max, 8))
        # Unswept low: ниже текущего диапазона
        if overall_min < recent_low and overall_min > 0:
            lows.append(round(overall_min, 8))

    return sorted(set(highs), reverse=True), sorted(set(lows))
```

---

#### Шаг 4 — Обновить caller в `trading_intelligence.py`

Найти вызов `analyze_context(snapshot, ...)` и передать новые аргументы:
```python
mtf_ctx = mtf_interpreter.analyze_context(
    snapshot=mtf_snapshot,
    current_price=current_price,
    weekly_pivots=weekly_pivots,
    regime=regime,
    smc_h4=smc_h4_snapshot,   # из ARCH-51 shadow mode
    smc_d1=smc_d1_snapshot,   # из ARCH-51 shadow mode
    df_1h=df_1h,
    df_4h=df_4h,
)
```

---

#### Шаг 5 — Soft-block логика в `trading_intelligence.py`

**Phase B = shadow mode по умолчанию** (`phase_guard_enabled: false` в config.yaml).

```python
if mtf_ctx.avoid_reason:
    logger.info(
        "[phase_guard] %s: avoid_reason=%s pattern=%s phase=%s",
        symbol, mtf_ctx.avoid_reason, mtf_ctx.pattern_name, mtf_ctx.phase
    )
    # SHADOW MODE: только лог, не блокирует сигнал
    # После накопления данных (2 недели) → включить hard block через config
```

---

#### Шаг 6 — Форматтер (`core/ui/intelligence_formatter.py`)

Добавить в Telegram-вывод:
```
📊 MTF Phase: WAVE_3_RELOAD (conf=75%)
⚠️ Avoid: correction_active
```
Только если `pattern_name` и `avoid_reason` не None.

---

#### Файлы для изменения (DEV-83):
1. `core/signals/signal_models.py` — новые поля в MTFContext (backward-compat: всё Optional/default)
2. `core/mtf/mtf_interpreter.py` — 4 новые функции + обновить `analyze_context()`
3. `core/trading_intelligence.py` — обновить вызов `analyze_context()` + soft-block лог
4. `core/ui/intelligence_formatter.py` — показывать phase/pattern/avoid_reason
5. `config.yaml` — `mtf.phase_guard_enabled: false`

**Критерий готовности:**
- В логах появляется `[phase_guard]` при coorrection/cascade противоречиях
- `avoid_reason` виден в Telegram для MTF_BIAS сигналов
- 0 регрессий в существующих тестах

---

### DEV-83 — ARCH-56: MTF Interpreter Phase B реализация ✅
**Статус:** ✅ реализован 28.03.2026
**Агент:** DEV
**Источник:** аудит 26.03.2026
**Зависит от:** ARCH-56 (спек)

**3 файла, 5 шагов:**
1. `core/signals/signal_models.py` — добавить поля phase, zone_state, pattern_name, avoid_reason, pattern_confidence в MTFContext
2. `core/mtf/mtf_interpreter.py` — реализовать _detect_phase() + _detect_zone_cascade()
3. `core/trading_intelligence.py` — использовать avoid_reason для soft-block (только лог, не запрет)
4. `core/ui/intelligence_formatter.py` — показывать pattern_name в Telegram
5. `config.yaml` — phase_guard_enabled: false (shadow mode при запуске)

---

### DEV-77 — OrderExecutor: VST/SIM execution layer 🟢
**Статус:** 🟢 в плане
**Агент:** DEV
**Источник:** RFC ARCH 29.03.2026 + аудит 26.03.2026
**Зависит от:** TR-008 ✅ (bot стабилен)
**Блокирует:** DEV-78

**Что создать:** `core/trading/order_executor.py`
Mode: SIM_ONLY (текущее поведение) | VST (BingX sandbox) | LIVE
config: `trading.execution_mode: sim_only` по умолчанию

**Bracket ордер:**
```python
await exchange.create_order(symbol, type="MARKET", side="buy", amount=qty,
    params={"stopLoss": {"type": "MARKET", "triggerPrice": sl},
            "takeProfit": {"type": "MARKET", "triggerPrice": tp}})
```

**Схема частичной фиксации (утверждено TRADER 27.03.2026):**
- **TP1 hit → закрыть 20% позиции** (reduce order на бирже)
- Оставшиеся 80% продолжают с TSL
- Математика: при возврате к BU итог = +0.20–0.50R вместо 0R → страховка от нулевых сделок
- При полном runner (3R): итог = +2.70R vs +3.0R → стоимость страховки 0.30R
- `tp1_close_pct: 0.20` в config.yaml

**Требования:** min_notional=5 USDT check, не менять TradeSimulator, параллельный слой.

---

### DEV-78 — PositionManager + PositionSizer + live_orders 🟢
**Статус:** 🟢 в плане
**Агент:** DEV
**Источник:** RFC ARCH 29.03.2026 + аудит 26.03.2026
**Зависит от:** DEV-77

**Компоненты:**
- `core/trading/position_manager.py` — has_open_position(), sync_with_exchange()
- `core/trading/position_sizer.py` — deposit × risk_pct / sl_pct × leverage → qty
- SQLite таблица `live_orders`: sim_trade_id, exchange_order_id, symbol, side, qty, sl_order_id, tp_order_id, status, slip_pct
- `core/trading/order_reconciler.py` — orphan синхронизация при рестарте

---

### DEV-79 — Trading Panel: web/static/ рефакторинг ✅
**Статус:** ✅ ВЫПОЛНЕНО — DEV 26.03.2026
**Агент:** DEV
**Источник:** RFC ARCH 29.03.2026 + аудит 26.03.2026
**Блокирует:** DEV-80

**Цель:** вынести inline HTML/CSS/JS из dashboard_server.py (165 KB) в web/static/.
Структура: web/static/index.html + style.css + app.js
dashboard_server.py должен стать < 400 строк (только Python/routes).
aiohttp: `app.router.add_static('/static', Path(__file__).parent / 'static')`

---

### DEV-80 — Trading Panel: /trading страница + Position Sizer UI ✅
**Статус:** ✅ ВЫПОЛНЕНО — DEV 26.03.2026
**Агент:** DEV
**Источник:** RFC ARCH 29.03.2026 + TRADER концепция 3
**Зависит от:** DEV-79

**Что создать:** web/static/trading.html + web/static/trading.js
- Топбар (все страницы): [SIM/VST/LIVE] Risk% Lev TSL — только статус, клик → /trading
- Badge: SIM=серый, VST=синий, LIVE=зелёный/красный
- Position Sizer: чистый JS без серверных roundtrip, GET /api/trading/instrument_info для min_notional

---

### DEV-81 — FUNDING_EXTREME detector ✅
**Статус:** ✅ ВЫПОЛНЕНО 26.03.2026
**Агент:** DEV
**Источник:** TRADER 24.03.2026 + DEV подтвердил ccxt BingX fetchFundingRate=True

**Файл:** `core/signals/funding_detector.py`
Логика: funding_rate < -0.0005 + near support + wt cross up → LONG (и наоборот SHORT)
Интеграция: data_collector.get_funding_rate() + scan_one() + SignalType.FUNDING_EXTREME
Shadow mode: первые 2 недели только INFO лог.

---

### DEV-82 — LIQUIDITY_SWEEP detector ✅
**Статус:** ✅ ВЫПОЛНЕНО 26.03.2026
**Агент:** DEV
**Источник:** TRADER 24.03.2026 + ARCH архитектурное решение 26.03.2026

**Паттерн:** свеча пробивает W:S1/swing_low → но закрывается обратно выше + WT в OS (<-40) → LONG
**Файл:** `core/signals/liquidity_sweep_detector.py`
Зависимости: pivot_levels (уже есть) + swing_points из core/smc/
Интеграция: scan_one() рядом с anomaly_detector. Образец: anomaly_detector.py

---

### DEV-84 — L3 Фаза C: FVG/OB + OTE условия 🟢
**Статус:** 🟢 в плане (ждёт 2 недели OTE shadow данных)
**Агент:** DEV
**Источник:** TR-006 спек (23.03) + аудит 26.03.2026
**Зависит от:** DEV-63 ✅, DEV-76 ✅ (нужны данные shadow ~2 недели)

**Условия Фазы C добавить к DEV-52/53:**
- cond1: smc_h4.fvg_support == True (Bull FVG под ценой)
- cond2: OTE shadow показывает price_in_ote == True
Файл: core/trading_intelligence.py блок DEV-52 L3 (~строка 1157)

---

### ARCH-57 — Confluence TRADER/RANGE tier parameter 🔵
**Статус:** 🔵 backlog апрель (после 100+ новых confluence сделок)
**Агент:** ARCH
**Источник:** TRADER 24.03.2026

**Решение:** внутренний параметр confluence_tier: "trend" | "range" в SignalData.metadata.
- TREND_CONFLUENCE: direction==4h_trend AND str≥60 → max_rr=8
- RANGE_CONFLUENCE: str≥75 AND volume_ok → max_rr=3
Не создавать отдельный signal_type (мало данных для адаптивных весов).

---

### DEV-85 — OTE v2: Wide + ATR-trend filter 🟢
**Статус:** 🟢 в плане (после 2 недель shadow данных DEV-76)
**Агент:** DEV
**Источник:** Бэктест ARCH-53 26.03.2026 (20 пар / 30 дней)
**Зависит от:** DEV-76 ✅, shadow данные ≥2 недели (~11.04.2026)
**Цель:** WR≥40%, Sharpe≥1.0 для SWING OTE

**Проблемы текущей реализации (из бэктеста):**
1. Tight OTE [0.618–0.705]: WR=20.5% — убрать или штрафовать
2. Нет тренд-фильтра — Random Entry без него
3. Wide [0.705–0.786] нейтральная (WR=33.5%) — базис для улучшения

**3 изменения:**
1. `core/signals/ote_detector.py` — убрать `tight_ote` strength бонус +10; добавить штраф -5 за tight
2. `core/signals/ote_detector.py` — добавить `trend_direction` параметр: пропускать сигналы против тренда (ATR-trend из df_trigger)
3. `scripts/backtest_ote_mtf.py` — добавить `--mode wide_only` флаг для проверки Wide без Tight

**Критерий готовности:** бэктест Wide + trend_filter ≥ WR=40% AND Sharpe≥1.0 на 10+ парах

**Идея для DEV-85 v2 (после основного бэктеста):** Двунаправленный OTE
- **SHORT в OTE:** цена выше 0.5 + перекупленность на trigger TF → шорт с TP в OTE (0.62–0.705)
- **LONG из OTE:** цена в зоне + WT кросс вверх → лонг (текущая логика)
- Живой пример: TUT/USDT 15m 27.03.2026 — шорт от 0.00863 со стопом за HIGH (0.00868), TP в OTE (0.00846)
- ⚠️ WR таких сетапов на истории неизвестен — **обязательный бэктест перед реализацией**
- Частота сетапов зависит от TF — нужна раздельная статистика по 3m/15m/1h/4h

---

### ARCH-58 — TP Architecture: централизованный расчёт через скопление факторов 🔴
**Статус:** 🔴 критический архитектурный долг
**Агент:** ARCH → DEV
**Источник:** TRADER (повторно поднималось 5+ раз в дискуссиях с 03.2026)
**Приоритет:** высокий — блокирует качество всех новых детекторов

**Проблема:**
Каждый детектор сигналов (`ote_detector.py`, `wt_15m_reversal_scanner.py` и др.) считает TP самостоятельно через `ATR × multiplier` — "каменный топор". Инфраструктура для правильного TP существует (`get_tp_by_hierarchy()` в `pivot_calculator_fixed.py`), но детекторы к ней не имеют доступа — они в `core/signals/`, без пивотов.

**Принцип (позиция TRADER):**
TP должен определяться из скопления факторов в одной зоне:
1. Ближайший пивот (1D/1W/confluence) на пути цены
2. FVG / OB / зона ликвидности
3. Fib extension (1.272 / 1.618 / 2.618 от импульса)
Не фиксированный R, не ATR × N — это всегда "в пустоте".

**Текущее состояние:**
- `get_tp_by_hierarchy()` ✅ существует, уже вызывается в `bot/monitoring.py:789` и `scan_loop.py:149`
- НО: только для части сигналов, остальные получают ATR-TP из детектора
- Fib extension (1.618/2.618) пока нигде не реализован

**Архитектурное решение (спек для DEV):**
```
ДО (сейчас):
  detector.py → entry + SL + TP(ATR) → monitoring.py → register

ПОСЛЕ:
  detector.py → entry + SL only (TP=None)
  monitoring.py → get_tp_by_hierarchy(entry, SL, symbol, direction)
               → если нет пивота → Fib extension (1.272 как min, 1.618 как default)
               → если нет ничего → ATR как последний fallback (с меткой tp_source="atr_fallback")
```

**Задачи DEV:**
1. `core/pivots/pivot_calculator_fixed.py` — добавить Fib extension в `get_tp_by_hierarchy()`: если пивот не найден → считать 1.272/1.618 от impulse_high (для LONG)
2. `bot/monitoring.py` — применять `get_tp_by_hierarchy()` ДЛЯ ВСЕХ сигналов, не только части
3. Все детекторы в `core/signals/` — убрать расчёт TP, оставить только entry + SL
4. `tp_source` в БД должен чётко показывать откуда TP: `"pivot_1D_R1"`, `"fib_1.618"`, `"atr_fallback"`

**Критерий готовности:** 0 сигналов с `tp_source = "atr_*"` кроме явного fallback-случая (нет пивота И нет Fib зоны)

---

### DEV-86 — `get_tp_by_hierarchy()`: убрать расширенные уровни R4–R5/S4–S5 ✅
**Статус:** ✅ реализовано — строка 968 pivot_calculator_fixed.py уже содержит range(1,4)
**Агент:** DEV
**Источник:** TRADER 29.03.2026 — баг ONT/USDT SHORT #3523, `tp_source: pivot_1W_R4`
**Зависит от:** —
**Файл:** `core/pivots/pivot_calculator_fixed.py:967`

**Проблема:**
`all_lvls` включает R1–R5/S1–S5. Уровни R4/R5/S4/S5 — расширенные (Woodie R4 = PP + 3×(H-C), очень далеко). В RANGE/HIGH_VOL режиме они нереальны. `_qualifies()` проверяет только `min_r`, не ограничивает по типу уровня.

**Фикс (1 строка):**
```python
# Было:
all_lvls = ["PP"] + [f"R{i}" for i in range(1, 6)] + [f"S{i}" for i in range(1, 6)]

# Стало (R4-R5 / S4-S5 убраны):
all_lvls = ["PP"] + [f"R{i}" for i in range(1, 4)] + [f"S{i}" for i in range(1, 4)]
```

Применить в tier 1 (1D), tier 2 (1W), tier 5 (1M) — везде где используется `all_lvls`.

**Критерий готовности:** `tp_source` в новых сделках не содержит R4/S4/R5/S5 уровней.

---
