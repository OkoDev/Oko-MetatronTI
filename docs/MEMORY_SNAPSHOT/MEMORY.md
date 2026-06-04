# Crypto Volume Bot — Hot Memory Index

> Hot index ≤15 KB, auto-load каждую сессию. Детали → topic files / Obsidian (cold).
> Sweep 21.05.2026: 5 cold-файлов перенесены в Obsidian, 2 дубля объединены.

## ⚡ ЧИТАЙ ПЕРВЫМ
→ [OTE nested MTF стратегия](ote_nested_mtf_strategy.md) — 🎯 КАРКАС 03.06: вход 5m в 4h-OTE → риск ×10, maxR+16. Частичный TP1=1R(50%)+runner: avgR +0.152→+0.415, WR→66%. SHORT работает, LONG нужен фильтр тренда
→ [Рой = AdvisorPort](swarm-advisorport-decision.md) — решение 31.05: team_ask в Куб через AdvisorPort (ARCH-125), не фоновый hook; проектирование отложено на отдельную сессию
→ `memory/current_state.md` — что сделано, незакоммиченные изменения, next tasks
→ `memory/last_sessions_2026-05-27_30.md` — **WS Phase A/B fix, ARCH-117 ph1+2 готовы, DEV-233-236 (golden просел +1.89→+0.46 на исправленных div), 28 паттернов изолировано, 215→187**

## 🏛️ MILESTONE: Memory System Redesign (21.05.2026)
→ `memory/session_2026-05-21_memory_redesign.md` — детальная история и уроки
→ Hot/cold split, triggers frontmatter, preflight checklists, memory_lint.py
→ `obsidian/Meta/Memory-System.md` — карта архитектуры памяти
→ Запускай `python tools/memory_lint.py` при подозрении на дубли/blowt

---

## 🔴 АКТИВНЫЙ ЭПИК: ARCH-104 Pattern Mining + Risk Intelligence

**Главное:** Phase 1-7 завершены, Stage 1 VST observer запущен 21.05.2026 в 02:55 UTC на 241 паре.

→ `obsidian/Architecture/ARCH-104-Pattern-Mining-RiskIntel/` (13 файлов эпика)
→ `docs/PATTERN_MINING_2026-05-19.md` — корневое исследование
→ `docs/MIGRATION_ARCH104.md` — 5-stage capital ramp 10→20→30→50→100%

**187 активных паттернов** в `config/arch104_patterns.yaml` (DEV-236, 30.05: 28 изолировано из 215 — деградация ≥0.5R на исправленных div). LONG-golden просел +1.89→+0.46 на пересчёте (DEV-235 ретробэктест n=88). SHORT (S1-S8) устойчивы. **Старые golden-метрики были завышены ложными div** (DEV-233 lookahead fix).

**Validated insights:**
- `pattern_golden_long_validated.md` — bull_div_1d+bull_fvg_4h+wt_os_4h (test n=29 avgR+1.89 WR=100%)
- `pattern_nested_15m_walkforward_validated.md` — 53/53 LTF паттерна WR=100%
- `pattern_nested_ltf_validated.md` — LTF entries inside HTF regime
- `pattern_1h_wt_os_smc_long.md` — 1h baseline (WR=59%)
- `tsl_no_trail_insight.md` — TSL ВРЕДИТ на validated паттернах (no_trail+24h time exit лучше)
- `tsl_optimizer_results.md` — fixed TSL act=2R trail=2R baseline
- `backtest_lookahead_bug.md` — MTF reindex `Timedelta` shift fix

---

## 🔴🔴 ARCH-118 ЗАВЕРШЁН — Единый снимок признаков (31.05.2026, ВЫСШИЙ УРОВЕНЬ)
→ `memory/arch118_snapshot_decision.md` — ПОЛНОЕ решение+реализация. Читать ПЕРЕД работой с features_json/combinator/ML.
**Статус:** Шаги 1-5 готовы (b1fe5d8→97918ce). PARITY достигнут (0 расхождений; рой 7/7: канон independent-last `snapshot_features_at` + `HTFHistoryCache`≥4320). Свёртка pivot (рой 6/7 вариант B: числовые ∥ булевым). Снимок в таблице `trade_features`(FK), config `arch118.write_table`. Готов для ML/re-mining. `scripts/arch118_parity_check.py`.
**Хранение:** отдельная таблица `trade_features`(FK) + вложенный JSON по доменам + **sparse-булевы** (только true, false из схемы) + **generated-колонки** (json_extract+индекс). Цифры: dense 770=207MB ❌ → sparse=22MB ✅. Pivot 490→свёртка nearest_level+distance_pct+relation. schema_version=2.
**Куб:** снимок = persistence-проекция `PairFullState`, домены ⟷ `*_snap` 1:1. `trade_features`=архивный слой (НЕ сфера). Замыкает feedback loop Сферы 11. → `docs/ENCYCLOPEDIA.md` ИНВАРИАНТ ВЫСШЕГО УРОВНЯ.
**🔴 ИНВАРИАНТ «ОДИН КАЛЬКУЛЯТОР»:** combinator и сферы Bus = ОДНА формула на признак. Вариант B=переходный мост до ARCH-117. ЗАПРЕТ двух независимых путей расчёта (корень самоподтверждения).

---

## 🔑 ФУНДАМЕНТАЛЬНЫЙ ПРИНЦИП ПРОЕКТА
→ `project_confluence_principle.md` — **Конфлюенция** как ядро. Данные: n=16877 дней, score=gravity/dist^1.5.
  Применяется везде: вход/SL/TP/режим/фильтры. Куб Метатрона = конфлюенция 11 сфер.

---

## 🔴 ПОМНИТЬ ВСЕГДА: Волновая теория Эллиотта (обновлено 28.05.2026, n=3597)

→ `obsidian/Concepts/Elliott-Wave.md` — overview + бэктест n=3597
→ `obsidian/Concepts/Elliott-Wave-Labeling.md` — правила разметки, SMC↔Elliott карта, trading setups, checklists
→ `obsidian/Concepts/Elliott-Wave-Fibonacci-Tools.md` — формулы TP targets, Fibonacci clusters, OTE Python алгоритм, liquidity sweep
→ `obsidian/Concepts/Elliott-Wave-Crypto-Practice.md` — крипто-специфика, ошибки разметки, волна 3 vs C

**Прокси в боте:** `n_down` = число consecutive снижающихся swing highs на HTF ≈ номер нисходящей волны.

**⚠️ СИГНАЛ-СПЕЦИФИЧНОСТЬ (полный бэктест n=3597):**

| signal_type | Лучший n_down для SHORT | Результат |
|-------------|------------------------|-----------|
| **atr_change** | n=2-3 (нейтрально), n≥4 = ЛОВУШКА | avgR=-0.904 при n=4 |
| **divergence** | n=**3-4** — ОПТИМАЛЬНО | avgR=+3.372 WR=79% при n=4! |
| **wt_b_signal** | n=3-4 — хорошо | avgR=+1.371/+2.456 |
| **confluence** | УБЫТОЧЕН везде | не использовать |

**Лучший SHORT КОМБО:** `4h n_down=4 + 1h n_down=0` → avgR=+1.403, WR=51.6%, n=93. (HTF тренд устойчивый + MTF отскок)

**Правила (универсальные):**
1. `above daily PP` — цена выше дневного PP → блок SHORT ниже PP
2. `ChoCH bullish + n_down ≥ 3` = конец 5 волн → **STOP SHORT** (avgR=-2.181)
3. Ближайший уровень S1/S2 при входе = WR 2.8% → BLOCK

**Для LONG:** deep LTF pullback (n_down_1h=6-8) → LONG прибылен. n_up_4h=1 — лучший массовый LONG.

**DEV-225** — shadow поля: `pvt_above_daily_pp`, `pvt_nearest_level`, `elliott_down_waves`, `smc_htf_last_break`, `htf_price_dir`.

---

## 🔴 ПОМНИТЬ: ARCH-124 классификатор RANGE МЕШАЕТ (30.05.2026)
→ `memory/arch124_regime_audit.md` — спот-чек: **78% RANGE-сделок реально тренды** (мислейбл). TREND требует 15m+1h+4h синхронность → крипта-шум → тренды в RANGE. SHORT-фильтр гейтит только atr_change (-178R утечки). Вердикт: свернуть regime-гейт → прямые htf_dir фильтры.

---

## 🔴 ПОМНИТЬ: ARCH-117 WT/RSI аудит (29.05.2026)
→ `memory/arch117_wt_audit.md` — ПОЛНЫЙ аудит: 4 разных порога зоны, 3 разных момента проверки, wt2 EWM≠SMA, WT_X vs LonesomeTheBlue. Читать ПЕРЕД любой работой с WT.
→ `memory/feedback_wt_cross_zone.md` — краткое: scan_loop сырой cross, WTSpecialist добавляет zone сам.

---

## 🔴 РАБОЧИЕ ПРАВИЛА (feedback)

| Триггер | Правило | File |
|---|---|---|
| вызов `obj.method()` где obj незнаком | **grep before claim** | `feedback_no_fabricated_apis.md` |
| утверждаю порядок tuple / поля / сигнатуру return | grep сам `return`, не по памяти (даже свою функцию) | `feedback_grep_return_shape.md` |
| утверждение "N% сделок плохие по X" | проверить семантику поля в БД | `feedback_verify_metric_semantics.md` |
| метрика без распределения | avgR + median + Sharpe + гистограмма + DEAD/data-era | `feedback_metrics_hygiene.md` |
| любой ответ, любое thinking | **на русском, без исключений** | `feedback_think_russian.md` |
| завершение задачи | TTS через SAY (Microsoft Irina) | `feedback_say_command.md` |
| закрытие сессии | проверить логи/БД + статус рестарта бота до финального TTS | `feedback_session_close_checklist.md` |
| фикс/рефактор/идея | сначала обсудить → проверить данными → действовать | `feedback_discuss_before_act.md` |
| любая правка кода | чек-лист "до/после, что сломает" | `feedback_fix_checklist.md` |
| вывод по паре/стратегии | data-era split (post-15.04 only, min 10 trades) | `feedback_data_era_first.md` |
| фильтр БД по времени из лога | лог=МСК(+3), created_at=UTC → −3ч или `datetime('now')` | `feedback_db_query_utc.md` |
| правка register_trade/INSERT | ast.parse НЕ ловит scope → runtime L12 на копии боевой БД до коммита | `feedback_ast_parse_no_scope.md` |
| биржевая задача (orders, params) | сначала BingX docs, потом гипотезы | `feedback_read_bingx_docs.md` |
| блокировка сигнала | НЕ блокировать без крайней нужды | `feedback_no_blocking.md` |
| skill vs code | разделять слои чат vs торговля | `feedback_skill_vs_code.md` |
| bash команда | выполнять автоматически (кроме destructive) | `feedback_bash_auto.md` |
| закрытие задачи | сразу обновить TASKS.md, не висеть с 🔴/🔄 | `feedback_close_tasks.md` |
| любая работа | стиль торговли пользователя | `user_trading_style.md` |
| сверка чарта с эталоном TradingView | синхронизировать ДЕНЬ+символ (since по дате скрина) | `feedback_chart_sync_etalon.md` |
| находка/закрытие сессии/research | **снапшот auto-memory → git** (`docs/MEMORY_SNAPSHOT/`), сырьё в `data/research/` НЕ /tmp; auto-memory вне git=эфемерна | `feedback_memory_persistence.md` |

---

## 🚦 PRE-FLIGHT CHECKLISTS (читать ПЕРЕД task-классом)

| Триггер задачи | Чек-лист |
|---|---|
| новый async loop в bot/loops/ | `preflight_new_loop.md` |
| новый detector / signal source | `preflight_new_detector.md` |
| ALTER TABLE / новое поле в БД | `preflight_db_change.md` |
| BingX / ccxt / order / VST | `preflight_exchange_task.md` |
| бэктест / walkforward / data analysis | `preflight_backtest_research.md` |

---

## 🔴 АРХИТЕКТУРА: Куб Метатрона

→ `docs/ENCYCLOPEDIA.md` → "Архитектурная концепция: Куб Метатрона"

**Перед любой архитектурной задачей** — задать 4 вопроса:
1. Это строит/улучшает одну из 12 сфер?
2. Это усиливает Shared Context Bus (центр)?
3. Это добавляет ребро между сферами?
4. Это feedback loop (одна сфера обучается от другой)?

Статус: 11/12 сфер активны. Shadow: Сфера 4 (MTF SMC Specialist, ждёт 200+ SMC сделок).

**Новые сферы (29-30.05.2026):**
- **Сфера 14: WTService + RSIService** (ARCH-117) — ✅ **Phase 1+2 ГОТОВЫ (30.05)**. `core/intelligence/{wt,rsi}_service.py` единый источник. extended_indicators.py удалён, 26 тестов ✅.
- **Сфера 8 PivotSphere** (ARCH-123) — ✅ Phase 1 (f7ce4fe) — Singleton + fibonacci_equiv.
- **Сфера 6 v2 Reversal Mode** (ARCH-119) — WT OS/OB + ADX down + CHoCH = Волна 5→ABC. ЗАПРЕТ SHORT.
- **SMC Sub-куб** (ARCH-120) — ✅ Phase 1 (2fd6cef) единый вход + liquidity в snapshot. Первый фрактальный куб.
- **TPSelector магниты** (ARCH-122) — ✅ Часть 1a+2 (4bdaaa3+47b712e) — tp2 из Bus smc_snap.
- **features_json snapshot** (ARCH-118) — 🟡 Вариант B принят: `combinator.compute_flags()` ОДНИМ кодом в live+бэктест → parity. До ML/re-mining.
- **Elliott-Pivot Sub-куб** (vision) — WaveService + PivotSphere + FibClusters → PricePositionContext.

**Порядок реализации новых сфер:** PivotSphere → RegimeV2 → WaveService (каждая prerequisite для следующей).

**Архитектурные принципы (приняты, hot):**
- `arch_timeframe.md` — ТФ всегда из данных, не хардкод
- `arch_indicator_precompute.md` — pre-compute WT+trend в scan_one, детекторы читают колонки
- WaveService = синхронный вызов в scan_loop, запись в Bus, НЕ полный async EventBus до Этапа 21

**Архитектурные решения (cold, читать при работе с темой):**
- `obsidian/Architecture/Signal-Types-Reference.md` — SignalType vs стратегии (28.03)
- `obsidian/Architecture/Cascade-TSL-Pyramiding-Vision.md` — vision: каскадный TSL + пирамидинг

---

## 🛠️ TOOLING

| Скрипт | Назначение | Output |
|---|---|---|
| `tools/team_ask.py` | рой LLM с meta-синтезом (6 актив + sambanova/nvidia при ключах) | `obsidian/Team-Discussions/<date>-<slug>.md` |
| `tools/llm_ask.py` | один LLM с auto-routing | stdout |
| `tools/llm_delegator` | разгрузка контекста через Groq/Gemini | summary |
| `tools/daily_pipeline.py` | daily Gemini (trade_review + log_digest + brief) | `memory/last_*.md` |
| `tools/project_timeline.py` | хронология проекта | `memory/project_timeline.md` |
| `tools/obsidian_enrich.py` | досье на задачу `DEV-X/ARCH-Y/TR-Z` | `obsidian/Tasks/<ID>.md` |
| `tools/obsidian_indexer.py` | TIMELINE индекс | `obsidian/Index/TIMELINE.md` |

→ `memory/llm-swarm-config.md` — конфиг роя (модели/провайдеры, проверено 30.05.2026) + факт: free Claude API НЕТ, аналоги Opus = DeepSeek-R1/GLM-4.7/Nemotron
→ `memory/arch125-metatron-kernel.md` — ARCH-125 (ВЫСШИЙ): Куб→переносимый скелет `metatron-core` + примитив AdvisorPort (подключение, не встраивание); рой→standalone swarm-service. Док `docs/METATRON-KERNEL.md` + ADR-001
→ `memory/team-topology.md` — кто есть кто: «DS-сессия»=Opus 4.8 (НЕ DeepSeek!); DeepSeek-flash=дирижёр-инструмент, DeepSeek-pro(DeepCode)=подключаемый агент. Не путать.
→ `memory/reference_context_pipeline.md` — 3-уровневая память (auto / timeline / enrich)
→ `memory/reference_daily_pipeline.md` — что запускается при старте бота
→ `memory/reference_llm_delegator.md` — когда делегировать в Gemini/Groq
→ `memory/reference_vue_dashboard_build.md` — `docker run node:lts npm run build` для Vue v2 (нет глобального Node)
→ `memory/order_book_backlog.md` — 🔵 БЭКЛОГ order-book данных (стакан китов, магниты цены). Binance spot depth=5000 (лучший источник, без ключа), скрипты в `e:/tmp/`, идея OrderBookSphere. Задача OB-DATA в TASKS.md

**Slash commands** (в `.claude/commands/`): `/team`, `/team-ask`, `/ask`, `/brief`, `/timeline`, `/postmortem`, `/enrich`, `/llm-keys`

---

## 📁 PROJECT PATHS

- Корень: `e:/MTF BOT/CURSOR/crypto_volume_bot/`
- Entry: `oko_mtf.py` (бывш. `bot_with_subscriptions.py`, шим есть)
- Python: `C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe` (3.12 — единственный с aiogram)
- БД: `subscriptions.db` (главная таблица `simulated_trades`, поля см. `obsidian/Reference/`)
- Дашборд: `http://localhost:8000`

**Stack:** aiogram 3.4.1, ccxt 4.2.85, aiohttp 3.9.3, pandas, scikit-learn, yaml

---

## 📚 OBSIDIAN VAULT (cold storage)

→ `obsidian/Project-MOC.md` — главный хаб
→ `obsidian/OBSIDIAN-RULES.md` — правила (wikilinks vs tags, frontmatter format)
→ `obsidian/Tasks/Tasks.md`, `obsidian/Discussions/Discussions.md` — индексы

**Архивы из памяти (21.05.2026 sweep):**
- `obsidian/Research/2026-05-08-Classifier-Cascade-Research.md`
- `obsidian/Architecture/Signal-Types-Reference.md`
- `obsidian/Architecture/Cascade-TSL-Pyramiding-Vision.md`
- `obsidian/Project-Log/Bugs-March-2026.md`
- `obsidian/Reference/BingX-PlaceOrder-Response.md`
- `memory/memory_audit_plan.md` — план дальнейших шагов B/C/D
- `obsidian/Meta/Memory-System.md` — карта моей памяти (создаётся)

---

## 🔴 ОБЯЗАТЕЛЬНО: ведение MD во время работы

- После задачи → обновить `current_state.md`
- При завершении сессии → полное обновление `current_state.md` + затронутые разделы `MEMORY.md`
- При компакте контекста → промежуточный статус в `current_state.md`, раздел "В ПРОЦЕССЕ (прерван компактом)"
- Формат: `## [HH:MM UTC] Агент: <Developer|Architect|TRADER>` + ✅/🔄/⚠️

---

## 💡 ОТЛОЖЕННЫЕ ИДЕИ

- [Vector Pattern Search](project_idea_vector_pattern_search.md) — HNSW soft-matching паттернов, риск-скоринг через исторических соседей. Вернуться когда VST-observer накопит 500+ сделок на паттерн.
- [Dashboard charts ideas](project_idea_dashboard_charts.md) — 4 идеи action-able визуализаций (MFE captured ratio / time-to-MFE / leak heatmap / strategy timeline). Отложено 26.05 после D-075, trader сказал "после вернёмся".

---

## 📌 NOTES

- Live stats обновляются Gemini в `memory/last_*.md` (не дублировать в MEMORY.md)
- Bugs/incidents → `obsidian/Project-Log/`, не в hot memory
- Старые "Этапы N" реализации (Этап 4.4 MFE, Этап 7 watchlist и т.д.) — давно в проде, не для MEMORY
- ML/SL/TP детали — `core/` грепом, не пересказывать в индексе
