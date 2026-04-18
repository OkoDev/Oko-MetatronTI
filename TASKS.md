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

**Статусы:** 🔴 срочно | 🟡 важно | 🟢 в плане | 🔵 бэклог | 🔄 в работе | ⏸ отложено

| ID | Ст | Описание | Роль |
|---|---|---|---|
| **🚀 СПРИНТ «ЗАМЫКАНИЕ РАЗРЫВОВ» (19.04–26.04.2026)** | | | |
| [ARCH-88](#arch-88) | ✅ | Per-pair Loss Memory: код merged 19.04, shadow активен (48ч наблюдение до ~21.04) | DEV (yogoru) |
| [ARCH-89](#arch-89) | ✅ | SMC_SNAP_UPDATED издатель merged 19.04: smc_snapshot.py + scan_loop publish. Benchmark 56.9мс (synthetic) — real-time замер после первого цикла | DEV (yogoru) |
| [ARCH-90](#arch-90) | ✅ | NarrativeBuilder читает smc_snap + 4 SMC-фичи в OutcomePredictor (27-вектор) — merged 19.04, тесты 9/9 PASS | DEV (yogoru) |
| [ARCH-91](#arch-91) | ✅ | Narrative TG-блок + classify_lost_reason + narrative_outcome feedback — merged 19.04, тесты 10/10 PASS | ARCH (oko.webdev) |
| [DEV-172-FIX](#dev-172-fix) | ✅ | Диагностика priority=None: NOT-A-BUG — матрица работает (P1/P2/P3 распределение 49/280/176/198 за 4д, DEV-169 fallback закрыл баг) | ARCH (oko.webdev) |
| [ARCH-92](#arch-92) | 🟢 | Анализ WR/avgR по Entry Priority (P1/P2/P3) на 200+ закрытых сделках (~22.04). Решение: P3→WATCH или оставить shadow | ARCH |
| **DASHBOARD** | | | |
| [DEV-144](#dev-144) | 🟡 | Полный редизайн дашборда: Live Control + Analytics + Settings | DEV |
| [DEV-144f](#dev-144f) | 🟢 | P6: Единый CSS — тёмная тема, виджет-карточки, responsive grid | DEV |
| [DEV-179](#dev-179) | 🟡 | Метрики стратегий: n/WR/median/Sharpe/p90/top20 вместо avg_R-only (урок 1 AUDIT_LESSONS) | DEV |
| **СТРАТЕГИЯ / СИГНАЛЫ** | | | |
| [DEV-178](#dev-178) | ✅ | Data integrity: 6835 сделок размечены data_era, ML фильтр применён (18.04) | DEV |
| [ARCH-83](#arch-83) | ✅ | Убрать wt_entry из active_strategies (WR 20%→5%, деградация) — выполнено 18.04 | ARCH/DEV |
| [ARCH-84](#arch-84) | 🔄 | MTF gate shadow активен (18.04) — ждём 2 дня данных WOULD_BLOCK до активации | ARCH/DEV |
| [DEV-172](#dev-172) | 🟢 | Entry Priority Matrix shadow: P1/P2/P3 пишется в features_json (200+ сделок → анализ) | DEV |
| [DEV-171](#dev-171) | ✅ | confluence полный стоп: `enabled: false` (14.04) — было 6 combos, теперь всё | DEV |
| [DEV-170](#dev-170) | ✅ | Time-of-day gate: блок входов вне 09:00–18:00 UTC, wt_signal=04:00–18:00 | DEV |
| [DEV-169](#dev-169) | ✅ | atr_trend_1h_bias: UP/DOWN записывается в features_json (сбор данных) | DEV |
| [DEV-168](#dev-168) | ✅ | LIVE-GUARD лог спам: cooldown 1ч/пара добавлен в trade_simulator.py | DEV |
| [DEV-111act](#dev-111act) | ⏸ | BTC 4h gate production: отложен — риск блокировки alt-pumps при BTC боковике | DEV |
| [DEV-88](#dev-88) | 🟡 | OTE Step2: C1 (4h+CHoCH) Sharpe=2.68 ✅, WR=41.7%. Нужна расширенная выборка | DEV |
| [DEV-89](#dev-89) | 🟢 | OTE C1 shadow: 20 пар / 90 дней. Критерий: WR≥40% ∧ Sharpe≥1.5 ∧ n≥150 | DEV |
| [DEV-121](#dev-121) | ✅ | Self-diagnostics suite: L13/L14/L15 Куб реализован (16.04) | DEV |
| [DEV-104](#dev-104) | 🔵 | Dead-Man Timer: emergency close all (Слой 3 ARCH-65) — только перед LIVE | DEV |
| **ML / АНАЛИТИКА** | | | |
| [ARCH-45](#arch-45) | ✅ | OutcomePredictor Этап A: AUC 0.41→0.582 (18.04). use_outcome_predictor: true активирован. Этап B при деградации. | ARCH/DEV |
| [DEV-177](#dev-177) | 🟢 | Adaptive weights: EMA (half-life 50-100) вместо full-history avgR | DEV |
| [DEV-162](#dev-162) | 🔵 | derive_wt_verdict: динамический confidence вместо статического (триггер: 200+ BLOCK) | DEV |
| **КУБ МЕТАТРОНА** | | | |
| [ARCH-77](#arch-77) | ⏸ | Миникуб WTMTF: ЗАМОРОЖЕН до Sharpe>1 в проде (множитель к убытку бесполезен) | ARCH/DEV |
| [ARCH-78](#arch-78) | ✅ | S5 BTC gate → S7/S13: BTCRegimeProvider → market_context + NarrativeBuilder (16.04) | DEV |
| [ARCH-79](#arch-79) | 🔵 | S10→S11: PostTradeAnalyser → NarrativeBuilder feedback (narrative_outcome в PairCtx) | DEV |
| [ARCH-55-VAL](#arch-55-val) | 🔄 | RANGE BOUNCE валидация: shadow перезапущен 16.04 (фикс: pivot_reversal теперь использует range_bounce SL/TP). Новый дедлайн: 23.04 | ARCH/DEV |
| **АРХИТЕКТУРА** | | | |
| [ARCH-87](#arch-87) | 🔵 | Fibonacci контекст в PairState: swing H/L + 0.618/0.705/0.79 в features_json для ML. Триггер: 50+ OTE сделок | ARCH/DEV |
| [ARCH-85](#arch-85) | 🟡 | Формализация статусов стратегий (ACTIVE/SHADOW/DEPRECATED/REMOVED) + deprecated confluence/multi_signal (урок 2 AUDIT_LESSONS) — после спринта | ARCH |
| [ARCH-86](#arch-86) | 🟢 | ROADMAP: строки «invalidates data pre-YYYY-MM-DD» для DEV-157/171/174/175 (урок 3 AUDIT_LESSONS) | ARCH |
| [ARCH-80](#arch-80) | 🔵 | MarketRegime hysteresis + метрика regime_changes_per_day | ARCH |
| [ARCH-81](#arch-81) | 🔵 | Rolling Correlation Guard + portfolio_beta_to_btc (замена hardcoded) | ARCH/DEV |
| [ARCH-82](#arch-82) | 🔵 | L3 checker v2: regime-aware portfolio limits (TREND_UP: 3L+1S) | ARCH/DEV |
| [DEV-176](#dev-176) | 🔵 | SL cooldown per-TF калибровка (15m→2ч, 1h→4ч, 4h→12ч) | DEV |
| [ARCH-73](#arch-73) | 🔵 | Разбивка trading_intelligence.py (2578 строк): MLSpecialist + StrengthAggregator | ARCH/DEV |
| [ARCH-74](#arch-74) | 🔵 | Разбивка trade_simulator.py (1978 строк): TSLManager + MFETracker + ExchangeSyncGuard | ARCH/DEV |
| [ARCH-75](#arch-75) | 🔵 | Разбивка monitoring.py (1436 строк): SignalFilter + MessageDispatcher | ARCH/DEV |
| [ARCH-76](#arch-76) | 🔵 | CubeNode интерфейс: Фрактальный Куб (триггер: LIVE + прибыль 30+ дней) | ARCH |
| [ARCH-57](#arch-57) | 🔵 | Confluence TRADER/RANGE tier parameter | ARCH |
| [ARCH-67](#arch-67) | 🔵 | USDT.D macro gate: CoinGecko API + shadow (бэклог май) | ARCH |
| [ARCH-69](#arch-69) | 🔵 | Перенести verbose-секции CLAUDE.md → ENCYCLOPEDIA.md | ARCH |
| [ARCH-44](#arch-44) | 🔵 | Добавить роль DATA (триггер: AUC > 0.55) | ARCH |
| [ARCH-47](#arch-47) | 🔵 | SMC contradiction filter: SHORT при нулевых медвежьих сигналах | ARCH |
| **TRADER** | | | |
| [TR-001](#tr-001) | 🔄 | Ежедневный разбор Watch List с живыми свечами | TRADER |
| [TRADER-AUDIT-002](#trader-audit-002) | 🟢 | Аудит DUAL_TSL split 10%/90%: grid search после 500+ новых DUAL_TSL сделок (~30.04) | TRADER |

---

## 📝 Описания активных задач

### DEV-144 — Полный редизайн дашборда 🟡
**Выполнено:**
- ✅ 144a — Риск-менеджмент в settings UI (deposit/risk_pct/leverage + live preview)
- ✅ 144b — SL/TP цены из simulated_trades в /api/live_orders (JOIN)
- ✅ 144c — /api/live: баланс BingX + реальные позиции с биржи (positionSide fix)
- ✅ 144d — Hero-grid на главной: 3 карточки (BingX Equity + Risk Exposure + WR), equity curve
- ✅ 144e — Analytics: SVG donut chart сигналов + режимов рынка вверху страницы
- 🟢 **144f** — Единый CSS: тёмная тема #0d1117, карточки #161b22, green/red/blue (responsive)

**Ссылка на спек:** DISCUSSION.md [05.04.2026] ARCH — DEV-144

---

### DEV-168 — LIVE-GUARD лог спам 🟡
**Файл:** `core/trading/trade_simulator.py` — блок `[LIVE-GUARD]`
**Симптом:** 34967 WARNING строк за 2 дня (4 позиции × каждую минуту). Засоряет лог, скрывает реальные проблемы.
**Фикс:** добавить dict `_live_guard_logged: dict[trade_id, datetime]` — логировать WARNING не чаще раза в 60 мин на позицию.
```python
_last = self._live_guard_logged.get(trade_id)
if _last is None or (now - _last).total_seconds() > 3600:
    logger.warning("[LIVE-GUARD] %s #%s: SL detected...", symbol, trade_id)
    self._live_guard_logged[trade_id] = now
```

---

### DEV-111act — BTC 4h gate production ⏸
**Отложен** — gate молчал всю неделю shadow. Риск: при BTC боковике блокирует alt-pumps в LONG.
**Условие активации:** после 5 дней WOULD_BLOCK данных, убедиться что gate блокирует >15% LONG в медвежьих условиях.

---

### DEV-172 — Entry Priority Matrix shadow 🟢

**Файл:** `core/intelligence/entry_matrix.py` (создан 14.04.2026)
**Суть:** оценка качества входа по трём критериям из `wt_snap`:
- `bias_ok` — ATR Trend на 1h согласован с направлением
- `zone_ok` — цена в OS/OB на 1h или 4h
- `trigger` — WT кросс на 15m в правильную сторону

**Вызов:** `trade_simulator.py` → `register_trade_async()` → пишет `entry_priority` + `entry_priority_reason` в `features_json`.
**Критерий:** после 200+ сделок смотрим WR по P1/P2/P3/None. Если P1 WR≥35% → переключаем как основной фильтр.
**Статус:** shadow, не блокирует.

---

### DEV-88 — OTE Step2 фильтры 🟡
**Результаты бэктеста (5 пар, 60 дней, 12.04.2026):**

| # | Конфиг | N | WR | AvgR | Sharpe | MaxDD |
|---|---|---|---|---|---|---|
| C0 | baseline [0.705-0.786] | 171 | 36.3% | +0.088 | 0.97 | -14.0R |
| **C1** | **[0.705]+4h+CHoCH** | **72** | **41.7%** | **+0.250** | **2.68 ✅** | **-7.0R** |
| C2 | 0.618+OB/OS+4h+CHoCH | 22 | 36.4% | +0.091 | 1.00 | -5.0R |

**Следующий шаг:** DEV-89 — shadow 20 пар / 90 дней с C1.
**Интеграция в прод:** не активировано, ждём данных DEV-89.

---

### DEV-89 — OTE C1 Shadow: 20 пар / 90 дней 🟢
**Конфиг C1:** `min_zone_tf: "4h"` + `require_choch: true`, зона [0.705-0.786]
**Критерий успеха (~26.04.2026):** WR ≥ 40% ∧ Sharpe ≥ 1.5 ∧ n ≥ 150
**Пары:** BTC ETH SOL BNB XRP ADA AVAX DOT LINK MATIC DOGE SHIB UNI ATOM INJ ARB OP NEAR FTM TRX

---

### DEV-121 — Self-Diagnostics Suite ✅ (16.04.2026)
**Суть:** скрипты глубокой проверки: импорты, DB-схема, API connectivity, config integrity, TSL pipeline
**Файл:** `core/selftest.py` (L1-L12) + `core/selftest_cube.py` (L13-L15)
**Реализовано:**
- L13: 13 сфер Куба Метатрона (ACTIVE/SHADOW/MISSING)
- L14: 10 рёбер (связи между сферами)
- L15: 4 feedback loop (adaptive_weights, cascade, narrative, ml_retrain)
- Интеграция: `run_all()` вызывает `run_cube_selftest(bot)`, результат в `SelfTestReport.cube_text`
- Автономный запуск: `python core/selftest_cube.py`

---

### ARCH-45 — OutcomePredictor ревью 🔄

**Статус:** Этап A выполнен 18.04. Этапы B+C — после замера AUC.

**Этап A — выполнено 18.04:**
- ✅ SQL фильтр: `>= '2026-03-15'` → `>= '2026-04-15'` (post-TSL-fix данные, DEV-174)
- ✅ features_dict при predict: добавлены `wt_snap`, `reversal_mode`, `distance_to_sl_pct`, `sl_atr_ratio`, `regime` (fix feature mismatch: 2/23 → 23/23 признаков)

**Этап B — после замера AUC (если < 0.55):**
- ⏳ `hour_utc` (sin/cos) → добавить в features_json + `_build_feature_vector`
- ⏳ `bias_strength` из `metadata["mtf_context"]`
- ⏳ `sl_source` categorical (atr_14 / atr_1.5 / tsl_line / range_bounce)

**Этап C — после B (если AUC всё ещё < 0.55):**
- ⏳ Split long/short: два отдельных предиктора
- ⏳ GradientBoosting вместо RandomForest

**Критерий активации:** AUC > 0.55 на CV → `use_outcome_predictor: true`
**Текущий AUC:** 0.41 (до фикса). После рестарта — автоматически переобучится, см. лог.

**Расширение (аудит 18.04):**
1. **Split long/short** — direction уже предсказатель (SHORT WR=33%, LONG=67%). Разделить на `long_predictor` + `short_predictor` — 2-3 часа, 3200+ сделок достаточно.
2. **ML ablation** — корреляция выходов OutcomePredictor / MLPredictor / RPredictor. Если `corr > 0.8` — модели дублируют, оставить одну.
3. **Calibration check** — при P(win)=0.7, реально ли 70% TP? Если нет — модель смещена.
4. **Data era** — после DEV-178, обучать только на данных post-15.04 (до этого TSL был сломан).

---

### DEV-162 — derive_wt_verdict: динамический confidence 🔵
**Файл:** `core/intelligence/wt_specialist.py`
**Задача:** вместо статического conf возвращать `(label, confidence)`:
- `EXHAUSTION`: `conf = 0.60 + (ob_count + os_count) / len(tfs) * 0.30` → 2/4 TF = 0.75, 4/4 = 0.90
- `REVERSAL_SETUP`: кросс на `4h` → `conf = 0.80`, на `1h` → `conf = 0.70`
**Триггер:** после 200+ BLOCK событий в логах.

---

### ARCH-77 — Миникуб WTMTF 🟡

**Идея:** WT данные по 6 ТФ уже собраны в `wt_snap`. Иерархические веса уже есть в `mtf_interpreter.py`. Но три ребра куба отсутствуют — данные есть, связи не используются.

**Три недостающих ребра:**

**1. Cross-TF WT Divergence** — когда ТФ расходятся, это информация
```
4h в OS + 1h уже разворачивается UP → bullish structure смены тренда
4h в OB + 1h ещё идёт UP → риск разворота, вход опасен
Сейчас: оба просто голосуют в alignment — связь между ними теряется
```

**2. Momentum Flow** — порядок смены тренда по ТФ
```
Здоровый сигнал: 4H разворот → 1H следует → 15m → 3m trigger
Ложный сигнал:  3m и 15m уже UP, но 4H ещё DOWN → преждевременный вход
Сейчас: временная последовательность не отслеживается
```

**3. Zone Depth** — глубина зоны OS/OB
```
wt1 = -85 (экстремальная OS) ≠ wt1 = -62 (только зашли в OS)
Глубина определяет силу потенциального отскока
Сейчас: zone = "OS" бинарно для обоих, wt1 значение есть но не используется как intensity
```

**Что НЕ нужно:** никаких новых данных, никаких новых API запросов. Всё строится из уже собранного `wt_snap`.

**Файлы:**
- `core/intelligence/wt_specialist.py` — `derive_wt_verdict()` расширить на 3 ребра
- `core/mtf/mtf_interpreter.py` — `interpret()` добавить divergence + flow check
- `core/signals/signal_models.py` — `MTFContext` добавить поля: `cross_tf_divergence`, `momentum_flow_ok`, `zone_depth_score`

**Критерий готовности:** shadow mode, вердикт пишется в `recommendation.metadata`. Блокировки нет. Оцениваем корреляцию с исходами через 200+ сделок.

**Зависимости:** нет. Можно начинать параллельно с другими задачами.

---

### ARCH-55-VAL — RANGE BOUNCE валидация 🟢
**Shadow активирован 12.04.2026.** Период: 12.04→19.04, нужно 20+ сделок.
**Метрики:** WR и avgR vs стандартный SL/TP.

---

### ARCH-73 — Разбивка trading_intelligence.py 🔵
**Размер:** 2578 строк.
**Что вынести:**
- `MLSpecialist` (`core/specialists/ml_specialist.py`) — `_enhance_analysis_with_ml()` (~стр. 750-820)
- `StrengthAggregator` (`core/specialists/strength_aggregator.py`) — `_calculate_adaptive_weighted_strength()`
- **Оставить:** `analyze_symbol()` как оркестратор + адаптивные веса.
**Предусловие:** ARCH-76 (CubeNode интерфейс) готов. Триггер: ~27.04.2026.
**Спек:** DISCUSSION.md [13.04.2026] ARCH

---

### ARCH-74 — Разбивка trade_simulator.py 🔵
**Размер:** 1978 строк.
**Что вынести:**
- `TSLManager` (`core/trading/tsl_manager.py`) — вся логика TSL update (~стр. 1680-1750)
- `MFETracker` (`core/trading/mfe_tracker.py`) — обновление max_price/min_price/max_R_possible
- `ExchangeSyncGuard` (`core/exchange/sync_guard.py`) — LIVE-GUARD логика (~стр. 1961-1968)
- **Оставить:** `register_trade_async()`, `_check_trade_exits()` как оркестратор.
**Триггер:** после стабилизации VST + DEV-148, не раньше 20.04.2026.
**Спек:** DISCUSSION.md [13.04.2026] ARCH

---

### ARCH-75 — Разбивка monitoring.py 🔵
**Размер:** 1436 строк.
**Что вынести:**
- `SignalFilter` (`bot/filters/signal_filter.py`) — `is_actionable()` + circuit_breaker + min_strength
- `MessageDispatcher` (`bot/dispatch/message_dispatcher.py`) — форматирование TG + отправка
- **Оставить:** основной цикл мониторинга.
**Триггер:** после ARCH-74. Не раньше 01.05.2026.
**Спек:** DISCUSSION.md [13.04.2026] ARCH

---

### ARCH-76 — CubeNode интерфейс: Фрактальный Куб 🔵
**Триггер:** LIVE режим + стабильная прибыль 30+ дней.
```python
class CubeNode:
    def subscribe(self, event_type, handler): ...
    def publish(self, event): ...
    def get_state(self) -> dict: ...
    def as_sphere(self) -> dict: ...
```
**Предусловия:** ARCH-73+74+75 завершены, AUC>0.55, ≥5000 сделок в БД.
**Спек:** DISCUSSION.md [13.04.2026] ARCH

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

### TRADER-AUDIT-002 — Аудит DUAL_TSL split 🟢
**Триггер:** 500+ закрытых сделок с `strategy_type=DUAL_TSL` в БД (~30.04.2026)
**Задача:** grid search соотношений 5..95% → пересчитать TSL_CAPTURE_RATE → сравнить с 10%/90%.
**SQL:** `SELECT COUNT(*) FROM simulated_trades WHERE strategy_type='DUAL_TSL' AND status != 'OPEN'`

---

## 🚀 Спринт «Замыкание разрывов» (19.04–26.04.2026)

> **Цель:** Куб Метатрона собирает 80% нужных данных, но они не доходят до точки решения. Спринт замыкает 5 критических цепочек. Источник: [`/root/.claude/plans/binary-jingling-sketch.md`](../../root/.claude/plans/binary-jingling-sketch.md) (18.04).
>
> **Координация:** DEV (yogoru) в agent-loop берёт задачи последовательно (88→89→90→91). Триггер смены: пин в DISCUSSION.md `→ ARCH:`. DEV-172-FIX параллельно делает ARCH (oko.webdev).
> **Ветки:** одна ветка на задачу (`arch-88`, `arch-89`, ...). Merge после review ARCH.
> **Правило:** одно изменение за раз, shadow 48ч перед активацией gate-ов.

---

### ARCH-88 — Per-pair Loss Memory 🔴

**Почему первое:** API3 получил 8 SL подряд — ни одного автоматического защитного действия. Защитный контур должен работать раньше оптимизации качества сигналов.

**Файлы:**
- `core/context/pair_context.py` — PairState расширение (строки 136-142)
- `core/trading/post_trade_analyser.py` — обновление при `POSITION_CLOSED`
- `bot/monitoring.py` — новый gate после секции 5.3b (ARCH-84)
- `config.yaml` — блок `signal_quality` (строки ~175-180)

**Что добавить в PairState (после `avg_r_cascade`):**
```python
from collections import deque

# ── Спринт «Замыкание разрывов» — ARCH-88 ────────────────────────────
sl_streak_count: int = 0                    # сбрасывается при TP/TSL с R>0
last_n_outcomes: deque = field(default_factory=lambda: deque(maxlen=10))
pair_avg_r_last_20: float = 0.0
last_sl_at: Optional[datetime] = None
pair_cooldown_until: Optional[datetime] = None  # если gate заблокировал
```

**Логика в `PostTradeAnalyser`:**
- при `status == "SL"`: `sl_streak_count += 1`, `last_sl_at = now()`
- при `status in ("TP", "TSL")` и `R_multiple > 0`: `sl_streak_count = 0`
- всегда: `last_n_outcomes.append(status)`, пересчёт `pair_avg_r_last_20` из БД (окно 20)

**Gate в `bot/monitoring.py`** (после ARCH-84 блока, ~строка 900):
```python
# ARCH-88 — PAIR-COOLDOWN gate: блок при серии SL подряд
_cooldown_cfg = bot.config.get("signal_quality", {})
_streak_limit = _cooldown_cfg.get("pair_cooldown_sl_streak", 5)
_cooldown_shadow = _cooldown_cfg.get("pair_cooldown_shadow", True)
if pair_state is not None and pair_state.sl_streak_count >= _streak_limit:
    if _cooldown_shadow:
        logger.info("[PAIR-COOLDOWN SHADOW WOULD_BLOCK] %s: streak=%d >= %d",
                    symbol, pair_state.sl_streak_count, _streak_limit)
    else:
        logger.warning("[PAIR-COOLDOWN] %s: %d SL подряд, блок на 4ч",
                       symbol, pair_state.sl_streak_count)
        return
```

**Config (`config.yaml → signal_quality`):**
```yaml
signal_quality:
  pair_cooldown_sl_streak: 5       # порог SL подряд для блока
  pair_cooldown_shadow: true       # первые 48ч — только лог
```

**Acceptance criteria:**
1. ✅ PairState содержит 5 новых полей; default values корректны при создании
2. ✅ После POSITION_CLOSED поля обновляются; проверка на 3 сделках разных статусов
3. ✅ SQL: `SELECT symbol, COUNT(*) FROM simulated_trades WHERE status='SL' AND created_at > datetime('now','-24 hours') GROUP BY symbol HAVING COUNT(*)>=5` — после 48ч shadow видим логи `[PAIR-COOLDOWN SHADOW WOULD_BLOCK]` для этих пар
4. ✅ Shadow 48ч → если блокирует <10% сигналов → `pair_cooldown_shadow: false`

**Верификация в прод:** через 48ч после активации (не shadow) — в БД ни одна пара не даёт >5 SL/24ч.

**Пин в DISCUSSION.md:** после merge → `→ ARCH: ARCH-88 готово, shadow активен, следующая ARCH-89`.

---

### ARCH-89 — SMC_SNAP_UPDATED издатель 🔴

**Почему:** `SphereEvent.SMC_SNAP_UPDATED` объявлен (pair_context.py:45), обработчик в `_auto_update_state` готов, но **никто не публикует**. FVG/OB/BOS живут только внутри OTE пайплайна, не попадают в PairState. Narrative строится без структурного контекста.

**Файлы:**
- `bot/loops/scan_loop.py` — публикация после расчёта SMC в цикле (секция «КУБ МЕТАТРОНА» ~стр. 400)
- `core/smc/` — экспортная функция-агрегатор (например `core/smc/smc_snapshot.py` — новый файл)
- `core/context/pair_context.py` — проверить что `_auto_update_state` для `SMC_SNAP_UPDATED` действительно пишет в `state.smc_snap`

**Payload события (dict):**
```python
smc_snap = {
    "timestamp": datetime.utcnow().isoformat(),
    "tfs_processed": ["15m", "1h", "4h", "1d"],
    "nearest_bull_ob": {                       # ближайший к цене bull OB
        "tf": "1h",
        "top": 0.4512, "bottom": 0.4489,
        "strength": 78.5,                       # 0..100 из OrderBlock.strength()
        "distance_pct": -0.85,                  # знак: + если выше цены, − если ниже
        "age_bars": 12,
    },
    "nearest_bear_ob": {...},                  # аналогично, или None
    "bull_fvg_active": [                       # все unmitigated bull FVG
        {"tf": "1h", "top": 0.455, "bottom": 0.451, "mitigation_pct": 20},
        ...
    ],
    "bear_fvg_active": [...],
    "last_bos": {"tf": "1h", "direction": "UP", "age_bars": 5},
    "last_choch": {"tf": "1h", "direction": "DOWN", "age_bars": 2},
    "swing_high": {"tf": "4h", "price": 0.4785, "age_bars": 18},
    "swing_low":  {"tf": "4h", "price": 0.1703, "age_bars": 145},
    "fib_levels": {
        "0.382": 0.3605,
        "0.500": 0.3244,
        "0.618": 0.2880,
        "0.705": 0.2612,   # OTE верх
        "0.79":  0.2350,   # OTE низ
        "0.886": 0.2054,
    },
    "price_in_ote": True,                      # bool — цена в [0.705..0.79]
    "current_retracement": 65.6,               # % отката от swing
}
```

**Существующие утилиты для переиспользования:**
- `core/smc/fvg.py::_detect_raw_fvgs()`, `_track_mitigation()` — готовы, возвращают список FVG с `mitigation_pct`
- `core/smc/order_blocks.py::OrderBlock.strength()` — готов
- `core/smc/swing.py` — swing high/low (проверить наличие)
- `core/smc/bos_choch.py` — BOS/CHoCH детектор
- Fibonacci — есть `core/pivot_levels.py`, но для OTE используем `swing_high/swing_low` напрямую

**Создать `core/smc/smc_snapshot.py`:**
```python
def build_smc_snapshot(symbol: str, ohlcv_by_tf: dict[str, pd.DataFrame]) -> dict:
    """Агрегирует FVG/OB/BOS/Fib по TF в единый snap для PairState."""
    ...
```

**Публикация в `scan_loop.py`** (в блоке где уже публикуются WT_SNAP_UPDATED):
```python
from core.smc.smc_snapshot import build_smc_snapshot
from core.context.pair_context import SphereEvent

smc_snap = build_smc_snapshot(symbol, ohlcv_by_tf)
if smc_snap:
    bot.pair_context.publish(symbol, SphereEvent.SMC_SNAP_UPDATED, smc_snap)
    logger.info("[SMC_SNAP] %s: OB_bull=%s OB_bear=%s BOS=%s in_OTE=%s",
                symbol,
                bool(smc_snap.get("nearest_bull_ob")),
                bool(smc_snap.get("nearest_bear_ob")),
                (smc_snap.get("last_bos") or {}).get("direction"),
                smc_snap.get("price_in_ote"))
```

**Acceptance criteria:**
1. ✅ `/api/cube/context/BTC%2FUSDT%3AUSDT` → `smc_snap` не `null`, содержит все ключи из payload выше
2. ✅ `selftest_cube.py` L13 Сфера 4 — статус ACTIVE (не MISSING)
3. ✅ В логах `[SMC_SNAP]` появляется для каждой пары раз в цикл (~30 сек)
4. ✅ Селфтест L14 — ребро `WT_SNAP → NARRATIVE` + `SMC_SNAP → NARRATIVE` оба ACTIVE
5. ✅ Время вычисления `build_smc_snapshot` < 50мс на пару (бенчмарк)

**Зависимость:** после ARCH-88 (merge в main).

**Пин:** `→ ARCH: ARCH-89 готово, smc_snap заполняется, следующая ARCH-90`.

---

### ARCH-90 — NarrativeBuilder читает smc_snap + Fibonacci 🔴

**Почему:** без этого шага данные ARCH-89 «лежат в state, но не используются». Narrative получает структурный контекст, OutcomePredictor — новые предикторы.

**Файлы:**
- `core/intelligence/narrative_builder.py`
- `core/trading/trade_simulator.py` — расширить `features_json` новыми полями
- `core/ml/outcome_predictor.py` — добавить 5 фич в `_build_feature_vector` (shadow: AUC не активируем, просто копим)

**Что добавить в NarrativeBuilder.build():**
- читать `state.smc_snap`
- формировать текстовые факторы (приоритет показа — от сильного к слабому):
  - если `price_in_ote=True`: `"✅ Цена в OTE 61.8-79% от swing (Fib 0.705 = X.XX)"`
  - если `nearest_bull_ob.distance_pct ∈ [-2%, -0.1%]` и `direction==LONG`: `"🟢 Bull OB на 1h в 0.8% ниже entry (strength=78)"`
  - если `bull_fvg_active[0].mitigation_pct > 60`: `"⚠️ Bull FVG mitigated 70% — support слабеет"`
  - если `last_bos.direction == "UP"` и `direction==LONG`: `"✅ BOS вверх на 1h (5 баров назад)"`
  - если `last_choch.direction ≠ direction`: `"⚠️ Последний CHoCH против направления"`
- `metadata["narrative"]["smc_factors"]` — список этих строк
- сводный skill-бонус `narrative["smc_score"] = +10..−10` (для последующей интеграции в confidence, пока shadow)

**Новые поля в `features_json`** (для ML):
```python
features_json_additions = {
    "fib_retracement_pct": smc_snap.get("current_retracement"),   # 0..100
    "price_in_ote": int(smc_snap.get("price_in_ote", False)),     # 0/1
    "ob_distance_pct": smc_snap["nearest_bull_ob"]["distance_pct"]
                        if smc_snap.get("nearest_bull_ob") else 0.0,
    "ob_strength": smc_snap["nearest_bull_ob"]["strength"]
                   if smc_snap.get("nearest_bull_ob") else 0.0,
    "fvg_mitigation_pct_max": max((f["mitigation_pct"]
                                    for f in smc_snap.get("bull_fvg_active", [])), default=0.0),
    "bos_aligned": int((smc_snap.get("last_bos") or {}).get("direction") ==
                       ("UP" if direction=="LONG" else "DOWN")),
    "choch_against": int((smc_snap.get("last_choch") or {}).get("direction") !=
                         ("UP" if direction=="LONG" else "DOWN")),
}
```

**Acceptance criteria:**
1. ✅ `/intelligence BTC/USDT` → блок нарратива содержит минимум 1 SMC-фактор (при наличии smc_snap)
2. ✅ После 50+ сделок: `SELECT COUNT(*) FROM simulated_trades WHERE features_json LIKE '%fib_retracement_pct%'` ≥ 50
3. ✅ ML: `outcome_predictor.info()` показывает 30 фич (было 23 — добавили 7)
4. ✅ NARRATIVE_BUILT event содержит `smc_score` в payload (проверка через sphere_registry log)
5. ✅ Пустой smc_snap → фолбэк на прежний нарратив без ошибок (NONE-safe)

**Зависимость:** ARCH-89 merged.

**Пин:** `→ ARCH: ARCH-90 готово, копим фичи 50+ сделок, следующая ARCH-91`.

---

### ARCH-91 — Narrative в TG + lost_reason feedback 🔴

**Почему:** нарратив строится, но **невидим трейдеру** — он живёт только в features_json. После закрытия сделки нарратив не обновляется — нет feedback loop (ARCH-79 в бэклоге с 🔵). Задача активирует обе вещи разом.

**Файлы:**
- `config.yaml` — новый блок `trading.narrative`
- `bot/monitoring.py` — добавить блок «📖 Нарратив» в TG-сообщение сигнала
- `core/trading/post_trade_analyser.py` — классификатор `lost_reason` + запись `narrative_outcome` в PairState
- `core/context/pair_context.py` — поле `last_narrative_outcome: Optional[dict]`
- `core/intelligence/narrative_builder.py` — читать `last_narrative_outcome` и добавлять «Прошлый вход: SL через SL_GAPPED 3ч назад»

**Config:**
```yaml
trading:
  narrative:
    enabled: true                  # включить NarrativeBuilder
    include_in_tg: true            # показывать в TG сигналах
    max_factors_in_tg: 4           # не более N строк в нарративе
    include_past_outcome: true     # упоминать прошлый исход на паре
```

**Классификатор `lost_reason`** (`post_trade_analyser.py`):
```python
def classify_lost_reason(trade: dict) -> str | None:
    """Определяет причину потери (только для status=SL/EXPIRED)."""
    if trade["status"] == "TP":
        return None
    if trade["status"] == "EXPIRED":
        return "TIMEOUT"
    r = trade.get("R_multiple", 0)
    max_r = trade.get("max_R_possible", 0)
    if r < -2.0:
        return "SL_GAPPED"                      # slippage/gap
    if max_r > 1.0 and trade["status"] == "SL":
        return "TSL_LATE"                       # профит был, TSL не защитил
    if -1.1 <= r <= -0.9 and not trade.get("tp1_hit"):
        return "BAD_ENTRY"                      # стандартный SL без движения
    return "SL_STANDARD"
```

**TG-блок в `monitoring.py`:**
```python
if bot.config.get("trading.narrative.include_in_tg", False):
    narr = (recommendation.metadata or {}).get("narrative") or {}
    factors = narr.get("smc_factors", []) + narr.get("wt_factors", [])
    if factors:
        max_n = bot.config.get("trading.narrative.max_factors_in_tg", 4)
        msg_parts.append("\n📖 <b>Нарратив:</b>\n" + "\n".join(f"• {f}" for f in factors[:max_n]))
    past = (narr.get("past_outcome") or {})
    if past:
        msg_parts.append(f"\n📜 Прошлый вход: {past['status']} @ R={past['R']:.1f} "
                         f"({past['lost_reason']}) — {past['age_min']} мин назад")
```

**Feedback в `post_trade_analyser.py` при POSITION_CLOSED:**
```python
lost_reason = classify_lost_reason(trade)
pair_state.last_narrative_outcome = {
    "status": trade["status"],
    "R": trade["R_multiple"],
    "lost_reason": lost_reason,
    "closed_at": datetime.utcnow(),
}
# lost_reason также сохраняется в features_json для SQL-анализа
```

**Acceptance criteria:**
1. ✅ TG сигнал содержит блок «📖 Нарратив:» с 1-4 факторами
2. ✅ Повторный сигнал на паре в течение 4ч содержит блок «📜 Прошлый вход»
3. ✅ SQL: `SELECT lost_reason, COUNT(*) FROM simulated_trades WHERE features_json LIKE '%lost_reason%' GROUP BY lost_reason` — распределение по 4 категориям после 50+ закрытых сделок
4. ✅ `classify_lost_reason()` покрыт unit-тестом (4 кейса: TP/SL_GAPPED/TSL_LATE/BAD_ENTRY)
5. ✅ Если `trading.narrative.enabled=false` — TG сообщения возвращаются к старому формату без ошибок

**Зависимость:** ARCH-90 merged.

**Пин:** `→ ARCH: ARCH-91 готово, нарратив видим, feedback замкнут. Спринт закрывается.`

---

### DEV-172-FIX — Диагностика `priority=None` ✅ CLOSED: NOT-A-BUG (19.04.2026)

**Исходная гипотеза:** 335 сделок за 4+ дня имеют `entry_priority = None`. Матрица не пишет.

**Фактические данные (ARCH проверил по БД 14–18.04, 703 сделки с `features_json`):**

| priority | count | % |
|---|---|---|
| 1 | 49  | 7% |
| 2 | 280 | 40% |
| 3 | 176 | 25% |
| None | 198 | 28% |

Распределение reasons у `None`: `no_wt_snap=135`, `no_trigger=43`, `no_signal=15`.

**Вывод:** матрица работает. Вероятно DEV-169 (`atr_trend_1h_bias` в features_json → fallback в [entry_matrix.py:56-57](core/intelligence/entry_matrix.py#L56-L57)) закрыл изначальный баг ещё до постановки DEV-172-FIX.

**Остаточные наблюдения (не блокеры, не фиксим сейчас):**
- 19% сделок (135/703) — `no_wt_snap` (таймаут `_build_mtf_context` 30с или пустой `wt_snap`). Отдельная задача «wt_snap coverage» — не про матрицу.
- [entry_matrix.py:53](core/intelligence/entry_matrix.py#L53) читает несуществующий ключ `atr_trend`, а [mtf_checker.py:40-46](core/mtf/mtf_checker.py#L40-L46) пишет `trend`. Мёртвая ветка `bias_from_atr` — спасает fallback DEV-169. Косметика, не баг.

**Следующий шаг:** [ARCH-92](#arch-92) — через 2-3 дня анализ WR по приоритетам.

---

### ARCH-92 — Анализ WR/avgR по Entry Priority 🟢

**Триггер:** 200+ **закрытых** сделок с `entry_priority ∈ {1,2,3}` (ожидается ~22.04).

**Цель:** проверить shadow-гипотезу `P1 WR ≥ 35% ∧ P3 WR ≤ 20%`. Если подтверждается — активировать правило «P3 → WATCH» (не блок, понижение действия до наблюдения).

**SQL для анализа:**
```sql
SELECT
  json_extract(features_json, '$.entry_priority') AS priority,
  COUNT(*) AS n,
  ROUND(100.0 * SUM(CASE WHEN status='TP' THEN 1 ELSE 0 END) / COUNT(*), 1) AS wr_pct,
  ROUND(AVG(R_multiple), 3) AS avg_r,
  ROUND(SUM(R_multiple), 2) AS sum_r
FROM simulated_trades
WHERE status IN ('TP','SL','TSL','EXPIRED')
  AND features_json IS NOT NULL
  AND json_extract(features_json, '$.entry_priority') IS NOT NULL
  AND created_at > '2026-04-14'
GROUP BY priority
ORDER BY priority;
```

**Дополнительно:**
- Разрез по reason (bias+zone+trigger / trigger+bias / trigger+zone / trigger_in_zone / trigger_only) — где edge
- Разрез по `strategy_name` × priority — подозрение что `ote_c1` ведёт себя иначе чем `pivot_reversal`

**Решение по результатам:**
- `P1 WR ≥ 35% ∧ P3 WR ≤ 20%` (разрыв ≥15п.п.) → активировать понижение P3 до WATCH в monitoring.py
- Разрыв <10п.п. → матрица не даёт сигнала, deprecate или расширить критерии
- Промежуточный — продолжать shadow ещё 200 сделок

**Deliverable:** отчёт в DISCUSSION.md (таблица + рекомендация). Код менять только при явном edge.

---



> Источник: [`docs/CUBE_AUDIT_18APR.md`](docs/CUBE_AUDIT_18APR.md)

### ARCH-83 — Убрать wt_entry из active_strategies 🔴
**Проблема:** wt_entry деградирует по траектории WR=20% → 19.3% → **4.7%** (15.04+, n=64). Стратегия не реагирует на фиксы в остальной системе — edge исчерпан. Добавлять MTF gate = продление агонии.
**Данные:**
```
wt_entry 15-31.03:  n=1289  WR=20.0%  avgR=-0.110
wt_entry 01-14.04:  n= 834  WR=19.3%  avgR=-0.376
wt_entry 15.04+:    n=  64  WR= 4.7%  avgR=-0.937  ← катастрофа
```
**Действие:** убрать `wt_entry` из `config.yaml → trading.active_strategies`. Не понижать до priority-3 — деградирующая стратегия на любом приоритете продолжает терять.
**Файлы:** `config.yaml:191`, `core/trading_intelligence.py:377-400`
**Зависимость:** DEV-178 (подтвердить что post-15.04 не аномалия)

---

### ARCH-84 — Жёсткий MTF gate вместо soft multipliers 🔴
**Проблема:** Этап 10 ввёл ослабление SHORT на бычьем рынке, но **не запрет**. WR SHORT=33.5% не изменился.
**Суть:** если MTFContext.direction_bias = LONG и bias_strength > 0.7 → SHORT-сигналы блокируются полностью (не ослабляются).
**Исключение:** pivot_reversal от уровня (уже реализовано в ARCH-78 для BTC gate)
**Файлы:** `bot/monitoring.py` (секция 5.3), `core/trading_intelligence.py`
**Данные:** 82% SHORT, WR SHORT=33.5% vs LONG=67.6% (ROADMAP:213, 16.03)
**Ожидаемый эффект:** если отключить половину SHORT → средний WR с 25% до ~40%

---

### DEV-178 — Data integrity: split pre/post 15.04 🔴
**ПЕРВЫЙ ПРИОРИТЕТ.** Без чистого среза все решения опасны.

**Причина:** DEV-174 (TSL 3 бага) + DEV-175 (slippage) + DEV-157 (min_sl_dist_pct) — значительная часть из 6700 сделок закрывалась по сломанным правилам. Исторические метрики **заражены**:
- 180/511 multi_signal сделок имели SL<0.2% (micro-SL артефакт → R=+112 на обычном пампе)
- avgR=+3.486 MultiSignal — полная иллюзия (без micro-SL: avgR=-0.348)
- pivot_reversal WR=56.2% (01-14.04) vs WR=34% (all time) — неизвестно что правда

**Шаги:**
1. SQL-скрипт: метрики (WR, avgR, medianR, Sharpe) отдельно для каждой эры:
   - `< 2026-03-15` (до DEV-157 min_sl_dist)
   - `2026-03-15 .. 2026-04-14` (post-DEV-157, pre-TSL fix)
   - `>= 2026-04-15` (post-TSL fix — чистые данные)
2. Пометить сделки с SL dist < min_sl_dist_pct как `data_era: 'pre_157'`
3. ML: обучать только на `>= 2026-04-15` (или `>= 2026-03-15` с фильтром micro-SL)
4. Добавить `data_era` в features_json для будущих сделок

**Правило:** артефакты данных живут дольше фиксов в коде. Пока нет маркера — мёртвая стратегия с avg_R=+3.48 будет продолжать искажать решения.
**Файлы:** новый скрипт `scripts/data_integrity_audit.py`, `core/trading/trade_simulator.py` (data_era)

---

### DEV-177 — Adaptive weights: EMA dampening 🟢
**Проблема:** `trading_intelligence.py:277` — `avgR` по всей истории. Тяжёлая инерция, нет адаптации к смене рынка.
**Фикс:** заменить `by_signal_type()` all-history на EMA с half-life 50-100 сделок.
**Доп:** логировать траекторию весов каждого детектора (JSON в `features_json` или отдельная таблица).
**Файлы:** `core/trading_intelligence.py:246-292`, `core/trading/performance_engine.py`

---

### ARCH-80 — MarketRegime hysteresis + метрика стабильности 🔵
**Проблема:** MarketRegime влияет на 5 активных решений, но ADX+ATR+EMA даёт запаздывающий/нервный сигнал на переходных состояниях.
**Шаги:**
1. Hysteresis: не переключать режим пока новое состояние не подтвердится N свечами (3-5)
2. Метрика `regime_changes_per_day` — если >5 → лог warning «классификатор нервный»
3. Запуск в shadow перед активацией
**Файлы:** `core/market_regime.py`

---

### ARCH-81 — Rolling Correlation Guard 🔵
**Проблема:** hardcoded 3 группы (`trade_simulator.py:632`). Нет защиты от коррелированных альтов (29 SHORT выбиты одним пампом, ROADMAP:215).
**Шаги:**
1. Rolling correlation всех открытых позиций к BTC (30 дней, пересчёт 1 раз/час)
2. Метрика `portfolio_beta_to_btc` — если >3.0, не открывать новые лонги
3. Pandas + numpy, без ML
**Файлы:** `core/trading/trade_simulator.py:632-651`
**Приоритет:** перед LIVE

---

### ARCH-82 — L3 checker v2: regime-aware limits 🔵
**Проблема:** текущий L3 DISABLED (блокирует всё). Фиксированные 2L+2S+4total не адаптируются.
**Фикс:**
- TREND_UP: 3L + 1S + total=4
- TREND_DOWN: 1L + 3S + total=4
- HIGH_VOL: total=2
**Зависимость:** ARCH-80 (MarketRegime hysteresis — без стабильного режима нет смысла)
**Файлы:** `core/trading/trade_simulator.py:804-831`, `config.yaml`

---

### DEV-176 — SL cooldown per-TF калибровка 🔵
**Проблема:** `sl_cooldown_hours=2.0` глобально per symbol (`monitoring.py:599`). На 4h — 0.5 свечи (бесполезно).
**Шаги:**
1. Backtest: распределение времени до следующего валидного сигнала после SL
2. Cooldown по TF: 15m→2ч, 1h→4ч, 4h→12ч (гипотеза, проверить backtestом)
**Файлы:** `bot/monitoring.py:599-614`, `config.yaml`

---

## 📋 Задачи из аудита AUDIT_LESSONS_18APR

> Источник: [`docs/AUDIT_LESSONS_18APR.md`](docs/AUDIT_LESSONS_18APR.md)
> Контекст: методологические уроки из SQL-среза MultiSignal (511 сделок, 18.04). Закрывают причину — а не симптом.

### ARCH-85 — Формализация статусов стратегий 🔴
**Урок 2:** мёртвые стратегии молча искажают решения. `MultiSignalStrategy` 0 сделок с 01.04, но avg_R=+3.486 по-прежнему в БД и на дашборде. Через полгода кто-то (даже я сам) решит «вернуть стратегию с таким avg_R».

**Суть:** ввести 4 статуса без промежуточных состояний:

| Статус | Код | В арбитре | В метриках | Маркер |
|---|---|---|---|---|
| ACTIVE | жив | да | да | — |
| SHADOW | жив | нет, только лог | да, отдельно | `shadow: true` |
| DEPRECATED | жив | нет | **заархивированы** | `deprecated_at` |
| REMOVED | удалён | нет | заархивированы | git history |

**Шаги:**
1. Добавить поле `status` + `deprecated_at` в конфиг стратегий (`config.yaml` → `strategies.*`)
2. Пометить `confluence` и `multi_signal` как `deprecated_at: 2026-04-14`
3. `performance_engine.by_signal_type()` — исключать DEPRECATED из активных метрик, добавить отдельную секцию «архив»
4. Убрать DEPRECATED из активных виджетов дашборда
5. Ежемесячная ревизия: SQL по всем стратегиям, 0 сделок за 30 дней → автопометка DEPRECATED

**Файлы:** `config.yaml`, `core/trading/performance_engine.py`, `web/dashboard_server.py`, `strategies/registry.py`
**Критерий готовности:** `confluence` и `multi_signal` не видны в активных метриках, их история доступна только в архивном разделе с пометкой.

---

### DEV-179 — Метрики стратегий: распределение вместо avg_R 🟡
**Урок 1:** avg_R без распределения это ложь. MultiSignal avg_R=+3.486 (красивая цифра) скрывал median_R=-1.000 и Sharpe=0.261 — 20 сделок из 511 дали 65% прибыли.

**Суть:** везде, где выводятся метрики стратегий, обязательный набор колонок — `n · WR · median_R · Sharpe · p90_R · top20_share`. Одной метрики avg_R в публичных документах быть не должно.

**Пороги доверия к цифре (из урока 1):**
- n < 100 — любые выводы шумовые
- Sharpe < 0.5 — стратегия живёт на удаче или хвосте
- `median_R` сильно отличается от `avg_R` — тяжёлый хвост, среднее неинформативно
- top-20 сделок дают >50% прибыли — проверить, не одно ли это рыночное событие

**Шаги:**
1. `performance_engine.by_signal_type()` — расширить возвращаемую структуру: добавить `median_R`, `sharpe`, `p90_R`, `top20_share`
2. Дашборд (`web/dashboard_server.py` + `web/static/index.html`): заменить avg_R-only карточки/таблицы на расширенный набор
3. В TG-отчётах `/intelligence` и `/scan` — такой же набор
4. Подсветка: если `n<100` или `Sharpe<0.5` или `median_R<<avg_R` — визуальная warning-метка

**Файлы:** `core/trading/performance_engine.py`, `web/dashboard_server.py`, `web/static/index.html`, `bot/handlers/scan_handlers.py`, `bot/handlers/analysis_handlers.py`
**Связь:** логически часть DEV-144 (редизайн дашборда) — можно интегрировать в 144f.

---

### ARCH-86 — ROADMAP: маркеры инвалидации данных 🟢
**Урок 3:** артефакты данных живут дольше фиксов в коде. DEV-157 (min_sl_dist) и DEV-174/175 (TSL-баги) исправили поведение, но в БД осталось 180+ сделок с SL<0.2% и неизвестное число TSL-закрытий по неверным правилам.

**Суть:** в ROADMAP для каждого фикса регистрации/закрытия добавить строку «invalidates data pre-YYYY-MM-DD». Это institutional memory — без неё через 3-6 месяцев никто не вспомнит, что данные до такой-то даты нельзя использовать в ML/анализе.

**Шаги:**
1. ROADMAP.md — добавить строки для DEV-157 (15.03), DEV-171 (14.04), DEV-174 (15.04), DEV-175 (15.04)
2. Формат: `DEV-XXX (DD.MM) — описание. Invalidates data pre-YYYY-MM-DD: <причина>`
3. Добавить правило в `.claude/CLAUDE.md`: любой фикс регистрации/закрытия сделок — обязательна строка в ROADMAP с датой инвалидации
4. Расширить `data_era` (DEV-178) версионированием: `v1` (pre-DEV-157), `v2` (post-DEV-157, pre-TSL-fix), `v3` (post-DEV-174/175)

**Файлы:** `ROADMAP.md`, `.claude/CLAUDE.md`, `core/trading/trade_simulator.py` (константа `DATA_ERA_VERSION`)
**Связь:** надстройка над DEV-178 (✅). Без ARCH-86 маркер `data_era` есть, но без справочника «что означает каждая эра».

---
