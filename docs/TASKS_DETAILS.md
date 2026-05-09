# 📝 Детальные описания задач

> Этот файл содержит полные спецификации задач из TASKS.md.
> Таблица активных задач и статусы — в [TASKS.md](../TASKS.md)
> Обновляется вместе с TASKS.md при добавлении новых задач.

---

# 🚀 СПРИНТ «CONFIRMATION-DRIVEN ARCHITECTURE» (09.05–23.05.2026)

> Полное обоснование: [DISCUSSION.md → запись 09.05.2026 TRADER → DEV/ARCH](../DISCUSSION.md)
> Backtest данные: R1–R8 в `e:\tmp\` (90 дней, 10 топ-пар, реальный OHLCV BingX)

## DEV-199 — ATR Trend Change events publisher 🔴

**Цель:** publishevent на момент cross supertrend линии для 15m/1h/4h ТФ.

**Файлы:**
- `core/signals/atr_change_detector.py` (НОВЫЙ)
- `bot/loops/scan_loop.py` (РАСШИРЕНИЕ)
- `core/context/event_bus.py` (УЖЕ ЕСТЬ — `trend_change_15m/1h/4h` зарегистрированы, но не публикуются)

**Алгоритм:**
```python
class ATRChangeDetector:
    def __init__(self, atr_period=43, factor=1.25):
        self.last_trend = {}  # symbol+tf → trend (+1/-1)

    def detect(self, symbol, tf, df_ohlcv):
        df = calculate_trend(df_ohlcv, atr_period=self.atr_period, factor=self.factor)
        current = int(df['trend'].iloc[-1])
        prev = self.last_trend.get((symbol, tf))
        if prev is not None and prev != current:
            side = 'UP' if current == 1 else 'DOWN'
            return {'symbol': symbol, 'tf': tf, 'side': side,
                    'price': float(df['close'].iloc[-1]),
                    'wt1': float(df['wt1'].iloc[-1]),
                    'zone': df['zone'].iloc[-1]}
        self.last_trend[(symbol, tf)] = current
        return None
```

**Публикация в EventBus:**
- `atr_change_15m` priority=2
- `atr_change_1h` priority=1
- `atr_change_4h` priority=1
- НЕ публиковать `atr_change_1d` (R8: avgR=−0.4, WR=20%)

**Acceptance:**
- ✅ За 24h после рестарта в БД появляются события всех 3 ТФ (`event_log` или signal_drops)
- ✅ Не дублирует event при том же баре (debouncing per symbol+tf)
- ✅ pytest на синтетическом OHLCV — детектирует cross корректно

**Зависимости:**
- → opens: DEV-200, DEV-201

**Effort:** S (1-2 дня)

---

## DEV-200 — ConfirmationRegistry 🔴

**Цель:** каталог confirmation типов с весами + dataclass для публикации.

**Файлы:**
- `core/confirmations/__init__.py` (НОВЫЙ)
- `core/confirmations/registry.py` (НОВЫЙ)
- `core/confirmations/models.py` (НОВЫЙ)
- `tests/test_confirmations.py` (НОВЫЙ)

**Структура:**

```python
# core/confirmations/models.py
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class Confirmation:
    source: str           # "atr_change_1h", "zone_OS_4h", "div_regular_15m" и т.д.
    symbol: str
    side: Literal['LONG', 'SHORT']
    weight: int           # стартовый вес из реестра (0-20)
    confidence: float     # 0.5-1.0, насколько чёткое подтверждение
    evidence: dict        # доказательства (close, wt1, level, и т.д.)
    ts_ms: int            # timestamp события
    tf: str               # таймфрейм источника


# core/confirmations/registry.py
CONFIRMATION_WEIGHTS = {
    # ── БАЗОВЫЕ TRIGGERS ──
    'atr_change_15m':    {'LONG': 8, 'SHORT': 8, 'is_trigger': True},
    'atr_change_1h':     {'LONG': 15, 'SHORT': 15, 'is_trigger': True},
    'atr_change_4h':     {'LONG': 18, 'SHORT': 18, 'is_trigger': True},

    # ── ZONE подтверждения ──
    'zone_OS_1h':        {'LONG': 10, 'SHORT': 0,  'is_trigger': False},
    'zone_OB_1h':        {'LONG': 0,  'SHORT': 5,  'is_trigger': False},
    'zone_OS_4h':        {'LONG': 8,  'SHORT': 0,  'is_trigger': False},
    'zone_OB_4h':        {'LONG': 0,  'SHORT': 5,  'is_trigger': False},

    # ── CASCADE ──
    'atr_change_15m_pre_1h':  {'LONG': 2, 'SHORT': 5, 'is_trigger': False},
    'atr_change_5m_pre_1h':   {'LONG': 1, 'SHORT': 2, 'is_trigger': False},

    # ── WT ──
    'wt_cross_same_dir':      {'LONG': 3, 'SHORT': 3, 'is_trigger': False},

    # ── SMC ──
    'smc_choch_1h':           {'LONG': 6, 'SHORT': 6, 'is_trigger': False},
    'smc_choch_4h':           {'LONG': 8, 'SHORT': 8, 'is_trigger': False},
    'smc_bos_1h':             {'LONG': 4, 'SHORT': 4, 'is_trigger': False},
    'smc_eql_swept':          {'LONG': 5, 'SHORT': 0, 'is_trigger': False},
    'smc_eqh_swept':          {'LONG': 0, 'SHORT': 5, 'is_trigger': False},
    'fvg_fill':               {'LONG': 4, 'SHORT': 4, 'is_trigger': False},
    'ote_zone':               {'LONG': 7, 'SHORT': 7, 'is_trigger': False},

    # ── PIVOTS ──
    'pivot_touch_within_03':  {'LONG': 4, 'SHORT': 4, 'is_trigger': False},
    'pivot_confluence_2plus': {'LONG': 6, 'SHORT': 6, 'is_trigger': False},

    # ── VOLUME ──
    'volume_spike_z25':       {'LONG': 5, 'SHORT': 5, 'is_trigger': False},

    # ── DIVERGENCES ──
    'div_regular_bull_15m':   {'LONG': 6, 'SHORT': 0, 'is_trigger': False},
    'div_regular_bear_15m':   {'LONG': 0, 'SHORT': 6, 'is_trigger': False},
    'div_hidden_bull_15m':    {'LONG': 5, 'SHORT': 0, 'is_trigger': False},
    'div_hidden_bear_15m':    {'LONG': 0, 'SHORT': 5, 'is_trigger': False},
    'div_cascade_1h_15m':     {'LONG': 8, 'SHORT': 8, 'is_trigger': False},
}


def get_weight(source: str, side: str) -> int:
    return CONFIRMATION_WEIGHTS.get(source, {}).get(side, 0)


def is_trigger(source: str) -> bool:
    return CONFIRMATION_WEIGHTS.get(source, {}).get('is_trigger', False)
```

**Acceptance:**
- ✅ 22+ confirmation типа в реестре с правильными весами
- ✅ pytest: каждый source выдаёт корректный weight для LONG и SHORT
- ✅ Реестр импортируется без circular dependencies

**Зависимости:**
- ← DEV-199
- → opens: DEV-201, DEV-202, DEV-204, TR-003, ARCH-112

**Effort:** M (2-3 дня)

---

## DEV-201 — SignalAggregator v2 🔴

**Цель:** заменить хардкод формулу strength на Σ weight × confidence.

**Файлы:**
- `core/intelligence/signal_aggregator.py` (РЕФАКТОР)
- `core/intelligence/confidence_calculator.py` (РАСШИРЕНИЕ)

**Алгоритм:**

```python
class ConfirmationAggregator:
    def __init__(self, window_seconds: int = 600):
        self.pending = defaultdict(list)  # (symbol, side) → list[Confirmation]
        self.window = window_seconds

    def on_confirmation(self, conf: Confirmation):
        key = (conf.symbol, conf.side)
        self.pending[key].append(conf)
        # Cleanup expired
        cutoff = conf.ts_ms - self.window * 1000
        self.pending[key] = [c for c in self.pending[key] if c.ts_ms >= cutoff]

    def aggregate(self, symbol: str, side: str) -> dict:
        key = (symbol, side)
        confirmations = self.pending.get(key, [])
        if not confirmations:
            return {'strength': 0, 'confirmations': []}

        # Должен быть хотя бы один trigger
        has_trigger = any(is_trigger(c.source) for c in confirmations)
        if not has_trigger:
            return {'strength': 0, 'confirmations': []}

        strength = sum(c.weight * c.confidence for c in confirmations)
        return {
            'strength': min(int(strength), 100),
            'confirmations': [
                {'source': c.source, 'weight': c.weight, 'confidence': c.confidence,
                 'ts_ms': c.ts_ms, 'evidence': c.evidence}
                for c in confirmations
            ],
            'signal_mode': self._classify_mode(confirmations),
        }

    def _classify_mode(self, confirmations):
        """REVERSAL / CASCADE / MOMENTUM (для analytics, не gate)."""
        sources = {c.source for c in confirmations}
        if 'atr_change_4h' in sources and ('zone_OS_4h' in sources or 'zone_OB_4h' in sources):
            return 'reversal'
        if 'atr_change_1h' in sources and 'atr_change_15m_pre_1h' in sources:
            return 'cascade'
        if 'atr_change_1h' in sources or 'atr_change_4h' in sources:
            return 'momentum'
        return 'unknown'
```

**Acceptance:**
- ✅ Новые сделки имеют поле `signal_mode` ∈ {'reversal', 'cascade', 'momentum', 'unknown'}
- ✅ Distribution не вырожден (нет одного режима в 100%)
- ✅ strength диапазон 0-100, не более 50% сделок имеют strength=50 (no clip)
- ✅ Backward-compat: старая `_compute_overall_strength` остаётся как fallback

**Зависимости:**
- ← DEV-199, DEV-200
- → opens: ARCH-112, DEV-204

**Effort:** M (3-4 дня)

---

## DEV-202 — features_json: confirmations[] 🟡

**Цель:** гранулярная запись всех подтверждений в БД для будущего ML.

**Файлы:**
- `core/trading/trade_simulator.py` (РАСШИРЕНИЕ — `register_trade_async`)
- `core/db/migrations.py` (миграция: добавить индекс по features_json IF needed)

**Структура features_json:**
```json
{
  "all_signal_types": [...],
  "...other existing fields...": "...",
  "signal_mode": "cascade",
  "confirmations": [
    {"source": "atr_change_1h", "weight": 15, "confidence": 1.0, "ts_offset_s": 0,
     "evidence": {"close": 0.123, "wt1": -45.2, "zone": "N"}},
    {"source": "atr_change_15m_pre_1h", "weight": 5, "confidence": 0.9, "ts_offset_s": -3600,
     "evidence": {"close": 0.121, "wt1": -50.1}},
    {"source": "zone_OS_4h", "weight": 8, "confidence": 1.0, "ts_offset_s": 0,
     "evidence": {"wt1_4h": -68.3}}
  ],
  "strength_breakdown": {
    "trigger": 15,
    "confirmations_total": 13,
    "final": 28
  }
}
```

**Acceptance:**
- ✅ 100% новых сделок имеют поле `confirmations: list[dict]`
- ✅ Минимум 1 confirmation на сделку (trigger)
- ✅ Среднее число confirmations на сделку ≥ 2.5 (для будущего ML)

**Зависимости:**
- ← DEV-200
- → opens: DEV-204 (ML retrain нуждается в этих данных)

**Effort:** S (1 день)

---

## DEV-203 — DecisionTrace в gates 🟡

**Цель:** видимость 96% сигналов которые теряются молча. Параллельно с MTF v2.

**Файлы:**
- `core/observability/decision_trace.py` (НОВЫЙ — частично готов из Phase 0 Stabilization)
- `bot/monitoring.py` — внедрение в 14 gates
- `core/db/subscription_manager.py` — таблица `signal_drops`
- `web/dashboard_server.py` — endpoint `/dropped`

**Схема таблицы:**
```sql
CREATE TABLE signal_drops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    signal_type TEXT,
    direction TEXT,
    strength INTEGER,
    gate_name TEXT NOT NULL,         -- "min_strength", "sl_cooldown", "min_volume" и т.д.
    drop_reason TEXT NOT NULL,
    features_json TEXT,
    dropped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_drops_gate ON signal_drops(gate_name, dropped_at);
```

**14 gates:**
1. `min_strength` (50)
2. `min_strength_register` (40)
3. `min_volume_usd` (5M)
4. `sl_cooldown_hours`
5. `dedup_minutes`
6. `min_strength_register_fallback`
7. `weekly_bias_blocked`
8. `entry_priority_P3_to_WATCH`
9. `mtf_gate_shadow_block`
10. `regime_gate_block` (RANGE/HIGH_VOL для wt_signal)
11. `divergence_count_zero`
12. `volume_spike_required`
13. `direction_neutral`
14. `is_actionable_false`

**Acceptance:**
- ✅ За 24h после рестарта в `signal_drops` 5000+ записей
- ✅ Дашборд `/dropped` показывает топ-10 reasons
- ✅ Каждый gate-block логирует причину перед drop

**Зависимости:**
- → opens: DEV-205 (audit_mode shadow на основе drops)

**Effort:** M (2-3 дня)

---

## DEV-204 — ML Outcome retrain weights 🟢

**Цель:** переобучить веса confirmations через RandomForest feature importance.

**Триггеры запуска:**
- 200+ закрытых сделок с features_json.confirmations[]
- 7 дней стабильного DecisionTrace (без новых багов)
- Acceptance criteria DEV-201 пройдены

**Файлы:**
- `core/ml/outcome_predictor.py` (РАСШИРЕНИЕ)
- `core/ml/confirmation_weight_tuner.py` (НОВЫЙ)

**Алгоритм:**
```python
def retrain_weights(min_trades=200):
    # 1. Загрузить все закрытые сделки с confirmations[]
    trades = load_trades_with_confirmations()
    if len(trades) < min_trades:
        return None

    # 2. Построить feature matrix:
    #    rows = trades
    #    columns = confirmation sources (one-hot или count)
    X, y = build_feature_matrix(trades)  # y = R_multiple

    # 3. RandomForest регрессия
    rf = RandomForestRegressor(n_estimators=300, max_depth=8, random_state=42)
    rf.fit(X, y)

    # 4. Веса из feature_importances_ × средний R по этому feature
    new_weights = {}
    for src, importance in zip(X.columns, rf.feature_importances_):
        # Средний R для сделок где это confirmation присутствовал
        mask = X[src] > 0
        if mask.sum() < 20:
            continue
        avg_r_with = y[mask].mean()
        # Скейлим: importance * avg_r_with * 30
        new_weights[src] = max(0, min(20, int(importance * avg_r_with * 30)))

    return new_weights


# Применение: shadow 7 дней → production
def apply_weights_shadow(new_weights):
    save_to_signal_weights_history(new_weights, status='shadow')
    # Старые веса остаются активными
```

**Acceptance:**
- ✅ После 200+ trades — выводится shadow таблица new_weights
- ✅ Сравнение old vs new weights (delta > 30% для топ-5 confirmations)
- ✅ После 7 дней shadow → перевод в production через config flag

**Зависимости:**
- ← DEV-200, DEV-202
- → opens: ARCH-103 reversal_mode production

**Effort:** S (1-2 дня после накопления данных)

---

## DEV-205 — audit_mode shadow + audit_trades 🟢

**Цель:** Phase 1+2 из исходного Stabilization Sprint — расширение DecisionTrace.

**Описание:** оригинальный план в `/root/.claude/plans/fluttering-snacking-whale.md`:
- audit_mode: shadow-симуляция dropped сигналов
- audit_trades таблица с виртуальными trades
- alerts на коллапс данных
- ML skipped-rows visibility

**Зависимости:**
- ← DEV-203 (DecisionTrace должен работать)

**Effort:** L (5-7 дней)

---

## TR-003 — TRADER валидация Confirmation Registry 🟡

**Цель:** ручной разбор 20 SHADOW-сделок по новой v2 логике.

**Процедура:**
1. После 50+ сделок с confirmations[] → выгрузить из БД
2. Случайные 10 winners (R > +1) и 10 losers (R < −0.5)
3. Для каждой проверить:
   - Соответствуют ли confirmations ожиданиям?
   - Есть ли missing confirmations (что должно было сработать но не сработало)?
   - Адекватны ли веса?
4. Отчёт в DISCUSSION.md → DEV для корректировки

**Acceptance:**
- ✅ Отчёт `tr_003_validation.md` с разбором 20 сделок
- ✅ Список predлагаемых правок весов (с обоснованием)

**Зависимости:**
- ← DEV-200, DEV-202

**Effort:** S (1 день после 50 сделок)

---

## ARCH-112 — Архитектурный аудит Confirmation Registry 🟢

**Цель:** проверить соответствие Кубу Метатрана.

**Вопросы:**
1. Каждое Confirmation = ребро от какой сферы к центральной шине?
2. Нет ли дублирования (одно подтверждение публикуется 2-3 раза разными источниками)?
3. Корреляции confirmations между собой — какие действительно независимые?
4. Какие сферы Куба остались без выхода в Confirmation? (sgнал, что они в shadow)

**Output:** обновление `docs/SIGNAL_BUS_CUBE_MAP.md` — карта confirmations × сфер.

**Зависимости:**
- ← DEV-200, DEV-201, DEV-202

**Effort:** M (2-3 дня)

---



**Выполнено:**
- ✅ 144a — Риск-менеджмент в settings UI (deposit/risk_pct/leverage + live preview)
- ✅ 144b — SL/TP цены из simulated_trades в /api/live_orders (JOIN)
- ✅ 144c — /api/live: баланс BingX + реальные позиции с биржи (positionSide fix)
- ✅ 144d — Hero-grid на главной: 3 карточки (BingX Equity + Risk Exposure + WR), equity curve
- ✅ 144e — Analytics: SVG donut chart сигналов + режимов рынка вверху страницы
- 🟢 **144f** — Единый CSS: тёмная тема #0d1117, карточки #161b22, green/red/blue (responsive)

**Ссылка на спек:** DISCUSSION.md [05.04.2026] ARCH — DEV-144

---

## DEV-168 — LIVE-GUARD лог спам 🟡

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

## DEV-111act — BTC 4h gate production ⏸

**Отложен** — gate молчал всю неделю shadow. Риск: при BTC боковике блокирует alt-pumps в LONG.
**Условие активации:** после 5 дней WOULD_BLOCK данных, убедиться что gate блокирует >15% LONG в медвежьих условиях.

---

## DEV-172 — Entry Priority Matrix shadow 🟢

**Файл:** `core/intelligence/entry_matrix.py` (создан 14.04.2026)
**Суть:** оценка качества входа по трём критериям из `wt_snap`:
- `bias_ok` — ATR Trend на 1h согласован с направлением
- `zone_ok` — цена в OS/OB на 1h или 4h
- `trigger` — WT кросс на 15m в правильную сторону

**Вызов:** `trade_simulator.py` → `register_trade_async()` → пишет `entry_priority` + `entry_priority_reason` в `features_json`.
**Критерий:** после 200+ сделок смотрим WR по P1/P2/P3/None. Если P1 WR≥35% → переключаем как основной фильтр.
**Статус:** shadow, не блокирует.

---

## DEV-88 — OTE Step2 фильтры 🟡

**Результаты бэктеста (5 пар, 60 дней, 12.04.2026):**

| # | Конфиг | N | WR | AvgR | Sharpe | MaxDD |
|---|---|---|---|---|---|---|
| C0 | baseline [0.705-0.786] | 171 | 36.3% | +0.088 | 0.97 | -14.0R |
| **C1** | **[0.705]+4h+CHoCH** | **72** | **41.7%** | **+0.250** | **2.68 ✅** | **-7.0R** |
| C2 | 0.618+OB/OS+4h+CHoCH | 22 | 36.4% | +0.091 | 1.00 | -5.0R |

**Следующий шаг:** DEV-89 — shadow 20 пар / 90 дней с C1.
**Интеграция в прод:** не активировано, ждём данных DEV-89.

---

## DEV-89 — OTE C1 Shadow: 20 пар / 90 дней 🟢

**Конфиг C1:** `min_zone_tf: "4h"` + `require_choch: true`, зона [0.705-0.786]
**Критерий успеха (~26.04.2026):** WR ≥ 40% ∧ Sharpe ≥ 1.5 ∧ n ≥ 150
**Пары:** BTC ETH SOL BNB XRP ADA AVAX DOT LINK MATIC DOGE SHIB UNI ATOM INJ ARB OP NEAR FTM TRX

---

## DEV-121 — Self-Diagnostics Suite ✅ (16.04.2026)

**Суть:** скрипты глубокой проверки: импорты, DB-схема, API connectivity, config integrity, TSL pipeline
**Файл:** `core/selftest.py` (L1-L12) + `core/selftest_cube.py` (L13-L15)
**Реализовано:**
- L13: 13 сфер Куба Метатрана (ACTIVE/SHADOW/MISSING)
- L14: 10 рёбер (связи между сферами)
- L15: 4 feedback loop (adaptive_weights, cascade, narrative, ml_retrain)
- Интеграция: `run_all()` вызывает `run_cube_selftest(bot)`, результат в `SelfTestReport.cube_text`
- Автономный запуск: `python core/selftest_cube.py`

---

## ARCH-45 — OutcomePredictor ревью 🔄

**Статус:** Этап A выполнен 18.04. Этапы B+C — после замера AUC.

**Этап A — выполнено 18.04:**
- ✅ SQL фильтр: `>= '2026-03-15'` → `>= '2026-04-15'` (post-TSL-fix данные, DEV-174)
- ✅ features_dict при predict: добавлены `wt_snap`, `reversal_mode`, `distance_to_sl_pct`, `sl_atr_ratio`, `regime` (fix feature mismatch: 2/23 → 23/23 признаков)

**Этап B — после замера AUC (если < 0.55):**
- ⏳ `hour_utc` (sin/cos) → добавить в features_json + `_build_feature_vector`
- ⏳ `bias_strength` из `metadata["mtf_context"]`
- ⏳ `sl_source` categorical (atr_14 / atr_1.5 / tsl_line / range_bounce)

---

## ARCH-77 — Миникуб WTMTF ⏸

**Статус:** ЗАМОРОЖЕН до Sharpe>1 в проде.
**Причина:** пока avgR отрицательный — любой множитель к убытку только ухудшает результат. Бессмысленно добавлять ML-веса на ухудшение.
**Условие разморозки:** pivot_reversal или wt_signal avgR ≥ +0.10R в течение 2 недель подряд.

---

## ARCH-55-VAL — RANGE BOUNCE валидация 🔄

**Статус:** shadow перезапущен 16.04 (фикс: pivot_reversal теперь использует range_bounce SL/TP).
**Дедлайн:** 23.04.2026.
**Критерий:** 50+ RANGE сделок post-fix с WR ≥ 40%.

---

## ARCH-73 — Разбивка trading_intelligence.py 🔵

**Проблема:** 2578 строк в одном файле. Сложная тестируемость, долгие импорты.
**Декомпозиция:**
- `core/intelligence/ml_specialist.py` — OutcomePredictor, AdaptiveWeights
- `core/intelligence/strength_aggregator.py` — весовая агрегация сигналов
- `core/intelligence/recommendation_generator.py` — финальный вердикт
**Триггер:** после стабилизации спринта «Реальные убийцы».

---

## ARCH-74 — Разбивка trade_simulator.py 🔵

**Проблема:** монолит ~2200 строк.
**Декомпозиция:**
- `core/trading/tsl_manager.py` — TSLManager: вся логика TSL activation + floor + move
- `core/trading/mfe_tracker.py` — MFETracker: max_high/min_low tracking + captured_R_pct
- `core/trading/exchange_sync_guard.py` — ExchangeSyncGuard: LIVE-GUARD + position_sync интеграция

---

## ARCH-74-EXT — Smart TSL (расширение ARCH-74) 🔵

**Суть:** после разбивки ARCH-74 — TSLManager становится "brain" Сферы 10 (Exit Manager).

**Концепция:**
- Адаптивные параметры TSL per-pair: разные activation_r и step_pct для волатильных vs стабильных пар
- Per-regime параметры: TREND_UP — более агрессивный TSL (быстрее догоняет), RANGE — консервативный
- RL-slot для будущего: состояние `(trade_R, regime, pair_vol)` → действие `(move_sl_to_X)` → reward по captured_R

**Связь с Кубом:**
- Сфера 10 (Exit Manager) получает brain — TSLManager с ML-слотом
- Ребро S10→S6 (MarketRegime) — TSL читает текущий режим
- Ребро S10→S11 (PostTradeAnalyser) — TSL-статистика для обратной связи

**Данные для активации:** после 500+ tsl_activated=1 сделок с captured_R_pct (≈середина мая).

---

## ARCH-75 — Разбивка monitoring.py 🔵

**Проблема:** 1436 строк, смешивает фильтрацию сигналов и TG-отправку.
**Декомпозиция:**
- `bot/filters/signal_filter.py` — SignalFilter: dedup, cooldown, strength gates
- `bot/dispatchers/message_dispatcher.py` — MessageDispatcher: TG-форматирование и отправка

---

## ARCH-76 — CubeNode интерфейс 🔵

**Суть:** каждая сфера Куба реализует интерфейс `CubeNode` — единый lifecycle.
**Триггер:** LIVE + стабильная прибыль 30+ дней (не раньше).
**Интерфейс:**
```python
class CubeNode(ABC):
    sphere_id: int
    sphere_name: str
    async def initialize(self, context: SharedContext) -> None: ...
    async def process(self, event: CubeEvent) -> list[CubeEvent]: ...
    def health_check(self) -> HealthStatus: ...
```

---

## ARCH-103 — reversal_mode (classify_mode) production 🟢

**Источник:** `docs/SIGNAL_BUS_CUBE_MAP.md` § Слой 0 / Слой 4 S6 / GAP #3.

**Проблема:** `MarketRegimeClassifier.classify_mode` (`core/indicators/market_regime.py:215`) вычисляет `TREND / REVERSAL / UNCLEAR` (WT 4h extreme + ADX 1h slope + CHoCH 1h/15m), но в production **не используется**. Поле `PairState.reversal_mode` декларировано, заполняется только в shadow-логах.

**Эффект на торговлю** (по ENCYCLOPEDIA):
- `mode=TREND` → confluence главный, pivot_reversal подавлен (-20 strength)
- `mode=REVERSAL` → pivot_reversal главный, confluence подавлен (-20 strength)

Данные подтверждают: 27-29.03 confluence avg_R=+0.49 (тренд), 01.04 pivot_reversal avg_R=+0.81 (разворот). Система не знала о смене → теряла деньги в переходный период.

**Реализация:**
1. В `bot/loops/scan_loop.py` после `pair_regime` вычислить `reversal_mode = classifier.classify_mode(...)` и записать в PairState.
2. В TradingIntelligence — применить вес-модификатор по mode (см. ENCYCLOPEDIA «Сфера 6 → Decision Core»).
3. Shadow-период 1 неделя: лог `[REVERSAL_MODE] {mode}: {weight_diff}R`. Если +R suggest по shadow — production.

**Зависит от:** Фаза 0 спринта закрыта (avgR pivot_reversal ≥ −0.10R).

**Acceptance:** PairState.reversal_mode заполнен production-кодом. В отчёте `sprint_phase1_report` колонка `mode_aware_weight_delta` показывает положительный эффект.

---

## TR-001 — Ежедневный разбор Watch List 🔄

**Суть:** TRADER просматривает текущие открытые позиции и WL-пары с живыми свечами (через TG `/watchlist` + `/pivots`).
**Результат:** фиксирует в DISCUSSION.md наблюдения: какие сигналы совпали с рынком, где входили поздно, какие пары под наблюдением.
**Частота:** ежедневно в период активной торговли.

---

## TRADER-AUDIT-002 — Аудит DUAL_TSL split 10%/90% 🟢

**Контекст:** текущий DUAL_TSL закрывает 10% на TP1 и 90% под TSL. Этот split не тестировался — выбран эвристически.
**Задача:** после 500+ новых DUAL_TSL сделок (~30.04.2026) — grid search по split ratios:
- [10/90] текущий
- [20/80]
- [30/70]
- [50/50]
**Метрика:** avg_R × n (total captured R) + max_drawdown.
**Файл:** новый скрипт `scripts/audit_dual_tsl_split.py`

---

## ARCH-88 — NarrativeBuilder MVP ✅ CLOSED (19.04.2026)

**Реализовано:** `core/intelligence/narrative_builder.py` — MVP с 8 факторами (SMC и WT).
**Интеграция:** вызывается из `TradingIntelligence.analyze_symbol()`, результат в `recommendation.metadata["narrative"]`.
**Shadow-режим:** `trading.narrative.enabled: true` в config.yaml. В TG не отправляется пока.

---

## ARCH-89 — PairContextBus: event routing ✅ CLOSED (19.04.2026)

**Реализовано:** `core/context/pair_context_bus.py` — PairContextBus + PairState (18 полей).
**Интеграция:** scan_loop.py публикует события в шину. TradingIntelligence читает из PairState.
**Поддерживаемые события:** SIGNAL_DETECTED, REGIME_CHANGE, TSL_MOVED, POSITION_CLOSED, NARRATIVE_GENERATED.

---

## ARCH-90 — PostTradeAnalyser: feedback → PairCtx ✅ CLOSED (19.04.2026)

**Реализовано:** `core/intelligence/post_trade_analyser.py` — анализирует закрытые сделки.
**Feedback:** при POSITION_CLOSED → обновляет `PairState.last_narrative_outcome` + `pair_win_rate_14d`.
**Integration:** `trade_tracker.py` вызывает analyser при смене статуса.

---

## ARCH-91 — NarrativeBuilder full: smc_factors + lost_reason feedback 🟢

**Расширение ARCH-88** — добавить полный набор SMC-факторов и feedback-петлю.

**Новые SMC-факторы в NarrativeBuilder:**
- `bos_confirmed` — Break of Structure подтверждён на LTF (15m)
- `choch_alignment` — CHoCH на 4h согласован с направлением сделки
- `fvg_nearby` — FVG в пределах 1.5% от entry_price
- `ote_zone_active` — entry в зоне OTE [0.705-0.786 fib]
- `liquidity_swept` — ликвидность swept перед входом (EQH/EQL)
- `confluence_count` — число совпавших SMC + WT факторов

**Классификатор `lost_reason`** (`post_trade_analyser.py`):
```python
def classify_lost_reason(trade: dict) -> str | None:
    if trade["status"] == "TP":
        return None
    if trade["status"] == "EXPIRED":
        return "TIMEOUT"
    r = trade.get("R_multiple", 0)
    max_r = trade.get("max_R_possible", 0)
    if r < -2.0:
        return "SL_GAPPED"
    if max_r > 1.0 and trade["status"] == "SL":
        return "TSL_LATE"
    if -1.1 <= r <= -0.9 and not trade.get("tp1_hit"):
        return "BAD_ENTRY"
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

**Acceptance criteria:**
1. TG сигнал содержит блок «📖 Нарратив:» с 1-4 факторами
2. Повторный сигнал на паре в течение 4ч содержит блок «📜 Прошлый вход»
3. SQL: распределение по 4 категориям после 50+ закрытых сделок
4. `classify_lost_reason()` покрыт unit-тестом (4 кейса: TP/SL_GAPPED/TSL_LATE/BAD_ENTRY)

---

## DEV-172-FIX — Диагностика `priority=None` ✅ CLOSED: NOT-A-BUG (19.04.2026)

**Исходная гипотеза:** 335 сделок имеют `entry_priority = None`. Матрица не пишет.

**Фактические данные (703 сделки с `features_json`):**

| priority | count | % |
|---|---|---|
| 1 | 49  | 7% |
| 2 | 280 | 40% |
| 3 | 176 | 25% |
| None | 198 | 28% |

Распределение reasons у `None`: `no_wt_snap=135`, `no_trigger=43`, `no_signal=15`.

**Вывод:** матрица работает. Остаточные наблюдения (не блокеры):
- 19% сделок (135/703) — `no_wt_snap` (таймаут или пустой `wt_snap`). Отдельная задача.
- [entry_matrix.py:53](core/intelligence/entry_matrix.py#L53) читает несуществующий ключ `atr_trend`, а mtf_checker пишет `trend`. Мёртвая ветка — спасает fallback DEV-169. Косметика, не баг.

---

## ARCH-92 — Анализ WR/avgR по Entry Priority 🟢

**Триггер:** 200+ **закрытых** сделок с `entry_priority ∈ {1,2,3}` (ожидается ~22.04).

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

**Решение по результатам:**
- `P1 WR ≥ 35% ∧ P3 WR ≤ 20%` (разрыв ≥15п.п.) → активировать понижение P3 до WATCH в monitoring.py
- Разрыв <10п.п. → deprecate или расширить критерии

---

## ARCH-94 — Полный аудит TP-lifecycle 🔴

**Контекст (20.04.2026):** CAKE SHORT #7291 — в БД статус TP (+1.62%), на бирже позиция закрылась по SL −1.0096 USDT через 16 часов после "TP" в БД.

**Мини-фикс (20.04.2026 ✅ сделано):**
- `exchange_tp_order_id TEXT` — добавлен в схему БД + миграция
- `set_exchange_tp_order_id()` — добавлен в TradeSimulator
- `order_manager.open_bracket` — извлекает `takeProfit.orderId` и `stopLoss.orderId`
- `monitoring.py`, `scan_loop.py` — сохраняют tp_order_id сразу при открытии

**Полный аудит (ещё не сделано):**
1. Верификация структуры bracket-ответа BingX — убедиться что `order_data["takeProfit"]["orderId"]` реально приходит
2. TSL-активация отменяет TP — когда TSL активируется: `tsl_updater` → где отменяется TP-ордер?
3. DUAL_TSL рассинхрон — если TP1 на бирже не исполнился, но симулятор посчитал TP → неверный статус
4. `position_sync.py` — есть `TAKE_PROFIT_MARKET → TP` маппинг (строка 26). Проверить что реально работает
5. Orphan-детектор — позиция на бирже OPEN, в БД — нет OPEN сделки → алерт в TG

**Критерий готовности к LIVE:** каждая OPEN-сделка в БД имеет `exchange_tp_order_id` (не NULL) или явную причину почему его нет.

---

## ARCH-95 — Глобальное расследование: почему торгуем в минус 🔴

**Контекст (25.04.2026):** гипотезы о причинах убытков.

**Гипотезы:**
- **H1.** Поздние входы — сигнал на close 15m, импульс уже произошёл
- **H2.** SL слишком тесный после позднего входа — ATR×1.5 от текущего ATR не покрывает откат
- **H3.** Pivot direction несогласован — LONG у R1 / SHORT у S1 (баг классификации уровня)
- **H4.** Куб не замкнут — smc_verdict ≠ narrative ≠ факт
- **H5.** Detector price ≠ entry price — задержка между генерацией и регистрацией
- **H6.** MTF alignment отсутствует — 15m LONG при 1h/4h DOWN
- **H7.** Адаптивные веса инерционны (full-history) — переоценка деградирующих типов

**6 read-only скриптов:**
1. `scripts/audit_entry_timing.py` — H1+H2
2. `scripts/audit_pivot_direction.py` — H3
3. `scripts/audit_cube_snapshots.py` — H4
4. `scripts/audit_entry_slippage.py` — H5
5. `scripts/audit_mtf_alignment.py` — H6
6. `scripts/audit_signal_performance_ema.py` — H7

**Решения (25.04):** per signal_type сначала, только post-fix (>=15.04), H1+H2 первыми.
**Параллельно:** реестр входных триггеров → `docs/STRATEGY_TRIGGERS.md`.

---

## ARCH-96 — Execution Sphere (Сфера 14) 🔴

**Полный спек:** `e:/tmp/ARCH-94_ExecutionSphere.md`

**Контекст:** SL-дубликаты 20.04 (CAKE 30 ордеров, PUMPBTC 24) и slippage-катастрофа 16.04.

**Главные компоненты:**
- `core/execution/idempotency_guard.py` + таблица `active_orders` с UNIQUE constraint → SL-дубликаты архитектурно невозможны
- `core/execution/slippage_predictor.py` — v1 rules-based (predicted_bps до отправки)
- `core/execution/order_type_selector.py` — decision table MARKET/LIMIT/STOP_LIMIT по liquidity tier
- `core/execution/execution_tracker.py` — slippage_bps, time_to_fill_ms, fill_rate, fee_bps

**Декомпозиция (DEV-184..191):**
- DEV-184 🔴 IdempotencyGuard + active_orders table (3-4 дня) — блокирует LIVE
- DEV-185 перенос order_manager + position_sync в `core/execution/` (2-3 дня)
- DEV-186 ExecutionTracker + features_json.execution_quality (2 дня)
- DEV-187 SlippagePredictor v1 rules-based (1-2 дня)
- DEV-188 OrderTypeSelector v1 decision table (1 день)
- DEV-189 SlippagePredictor v2 ML (3-4 дня, после 500+ сделок с qual)
- DEV-190 OrderTypeSelector v2 ML (3-4 дня)
- DEV-191 Dashboard секция Execution Quality (2 дня)

**Критический путь:** DEV-184 — единственное что блокирует LIVE. Остальное инкрементально.

---

## ARCH-97 — Anomaly Detection Sphere (Сфера 15) 🟡

**Полный спек:** `e:/tmp/ARCH-95_AnomalyDetectionSphere.md`

**Контекст:** observability для самого Куба. DEV-174 (3 TSL-бага) обнаружены неделями позже.

**Главные компоненты:**
- `core/monitoring/metric_baseline.py` — windows 7d/30d/90d с EMA, KS test, Cohen's d
- `core/monitoring/drift_detectors.py` — Group A (execution), Group B (trading), Group C (ML)
- `core/monitoring/alerter.py` — TG (HIGH only, throttle 1/час/метрика), dashboard (MEDIUM+)
- `bot/loops/anomaly_loop.py` — scheduler 5min/1h/1d

**Декомпозиция (DEV-192..199):**
- DEV-192 MetricBaseline + таблица + API (2 дня)
- DEV-193 DistributionTests (scipy wrappers) (1 день)
- DEV-194 Group A detectors execution (2-3 дня) — зависит от DEV-186 ExecutionTracker
- DEV-195 Group B detectors trading logic (2 дня)
- DEV-196 Group C detectors ML (2 дня)
- DEV-197 Alerter logs+TG+dashboard (2 дня)
- DEV-198 anomaly_loop планировщик (1 день)
- DEV-199 Dashboard секция System Health (2-3 дня)

**Критический путь:** DEV-192 → DEV-194 → DEV-197 → DEV-198 ≈ 10 дней до первого alert.
**Retrospective validation:** прогон по 15-20.04 поймал бы DEV-174 за 48-72ч, DEV-175 за 4-8ч.

---

## ARCH-98 — Portfolio Manager Sphere (Сфера 16) 🟡

**Полный спек:** `e:/tmp/ARCH-96_PortfolioManagerSphere.md`

**Главные компоненты:**
- `core/portfolio/exposure_calculator.py` — gross/net notional, β to BTC/ETH, sectoral
- `core/portfolio/drawdown_guardian.py` — 3 horizon: intraday (5%), 24h (8%), 7d (15%)
- `core/portfolio/correlation_matrix.py` — 50×50 rolling 30d, refresh hourly
- `core/portfolio/portfolio_manager.py` — `evaluate(execution_request) → VetoDecision`

**Декомпозиция (DEV-200..208):**
- DEV-200 ExposureCalculator + PortfolioState model (2 дня)
- DEV-201 DrawdownGuardian 3 horizon (2 дня)
- DEV-202 CorrelationMatrix + cache (2-3 дня)
- DEV-203 PortfolioManager.evaluate() rules-based v1 (2 дня)
- DEV-204 Sector mapping YAML + concentration check (1 день)
- DEV-205 Интеграция в trade flow (2 дня)
- DEV-206 Emergency mode + config knobs (1 день)
- DEV-207 Dashboard Portfolio Health секция (2-3 дня)

**Триггер:** после DEV-180 Risk Sphere v1 в shadow (≈26.04).

---

## ARCH-99 — Meta-Learning Sphere (Сфера 17) 🟢

**Полный спек:** `e:/tmp/ARCH-97_MetaLearningSphere.md`

**Контекст:** ARCH-95 H7 рекомендует hard-kill порог EMA<-0.5 — Meta-Learning расширяет это до контекстуального решения.

**Главные компоненты:**
- `core/meta_learning/context_encoder.py` — ~20 фичей: regime, btc_regime, hour_utc, weekday, fear_greed_index, funding_rate_btc, etc.
- `core/meta_learning/strategy_ranker.py` — XGBoost `f(context, signal_type) → E[R]` + CI
- `core/meta_learning/application_layer.py` — Mode C shadow → Mode B multiplier [0.7-1.3] → Mode A reject

**Декомпозиция (DEV-209..217):**
- DEV-209 ContextEncoder + ContextSnapshot model (2 дня)
- DEV-210 StrategyRanker v1 XGBoost train+predict (2-3 дня)
- DEV-211 ApplicationLayer Mode C shadow only (1 день)
- DEV-212 Интеграция в trading_intelligence (shadow) (1-2 дня)
- DEV-213 Mode B multiplier [0.7-1.3] (1 день, после 3 нед. shadow)
- DEV-214 Continuous learning loop + weekly retrain (1-2 дня)
- DEV-215 Mode A REJECT (1 день, после 1 мес. данных)

**Не блокировано ничем.** Данных хватает (1379 post-fix сделок).

---

## ARCH-101 — Mesh шины: детекторы → EventBus.publish 🟡

**Источник:** `docs/SIGNAL_BUS_CUBE_MAP.md` § Слой 3 / GAP #1.

**Проблема:** 11 из 16 детекторов не публикуют `signal_detected` в EventBus.

**Нужно publish:** ANOMALY, WT_SIGNAL, WT_B_SIGNAL, MTF_BIAS, SMC_STRUCTURE, MTF_DIVERGENCE, MTF_ALERT, TREND_SIGNAL, PIVOT_REVERSAL, WATCH_LIST_BREACH, OTE_SIGNAL.

**Реализация:** одна точка вставки в `_broadcast_intelligence_alert` после `is_actionable=True`:
```python
await self.event_bus.publish(symbol, "signal_detected", {
    "signal_type": rec.signal_type,
    "direction": rec.direction,
    "strength": rec.strength,
    "tf": rec.timeframe,
})
```

**Acceptance:** `python core/selftest_cube.py` показывает `_edge_detectors_to_eventbus` → `OK ✅`.

---

## ARCH-102 — BTCRegimeProvider → cross_market publish 🟡

**Источник:** `docs/SIGNAL_BUS_CUBE_MAP.md` § Слой 0 / GAP #2.

**Реализация:**
- В `_fetch_and_compute()` после расчёта режима — если режим **изменился**: `pair_context.publish(symbol="*GLOBAL*", event_type="cross_market", data=...)`
- Также `EventBus.publish("btc_macro", ...)` при `abs(btc_move_pct) > 2.5%`

---

## ARCH-104 — Унификация двух нумераций сфер 🔵

**Проблема:** две несовместимые нумерации:
- `sphere_registry.SPHERE_NAMES`: S7=Signal Detectors, S9=Narrative Builder, S10=Exit Manager
- `selftest_cube`: S7=TradingIntelligence, S8=TradeSimulator, S9=Exit Manager, S11=NarrativeBuilder

**Решение:** выбрать **первую** (она в ENCYCLOPEDIA + двух Mermaid-диаграммах) и привести selftest к ней.
**Приоритет 🔵** — выполнить до ARCH-96 (чтобы новые сферы регистрировались правильно).

---

## ARCH-105 — Order Flow & Macro data sources 🟡

**Источник:** `docs/TRADER_VISION_PREDICTIVE_SETUPS.md` § 6.

**По приоритетам:**
1. 🔴 **Funding history (30 дней)** — BingX `fapi/v1/fundingRate?symbol=...&limit=240`
2. 🔴 **Open Interest** — BingX `fapi/v1/openInterest`. Дивергенция OI vs цена → false-break detection
3. 🟡 **Liquidations** — BingX `fapi/v1/forceOrders`. Каскад ликвидаций → reverse setup
4. 🟡 **USDT.D / BTC.D** — CoinGecko Pro API
5. 🟢 **DXY / VIX** — Yahoo Finance API (бесплатный)
6. 🟢 **Fear & Greed Index** — alternative.me API (для ARCH-99)

**Реализация:**
- `core/cross_market/orderflow_provider.py` + ttl-кеш
- `core/cross_market/macro_provider.py`
- Обновить `PairState` — поля `oi_24h_change_pct`, `funding_24h_avg`, `liquidations_15m_usd`

---

## ARCH-106 — TriggerBus + persistence 🟡

**Источник:** `docs/TRADER_VISION_PREDICTIVE_SETUPS.md` § 3+5.

**Реализация:**
- `core/context/trigger_bus.py` — расширить до полноценной ленты атомарных событий
- `class TriggerEvent` dataclass: trigger_type, event_kind, symbol, tf, timestamp, price_at_trigger, strength_score, direction_hint, raw_data
- Hot-storage: `deque(maxlen=200)` per symbol + persistence в SQLite `trigger_events`
- Outcome computation: при каждом новом OHLCV — обновлять `outcome_1h/4h/24h_pct`

**Schema `trigger_events`:**
```sql
CREATE TABLE trigger_events (
    trigger_id TEXT PRIMARY KEY,
    trigger_type TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    tf TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    price_at_trigger REAL NOT NULL,
    strength_score INTEGER,
    direction_hint TEXT,
    raw_data_json TEXT,
    outcome_1h_pct REAL,
    outcome_4h_pct REAL,
    outcome_24h_pct REAL
);
```

**Acceptance:** через 30 дней `trigger_events` содержит ≥ 100k строк с marginal value по trigger_type.
**Зависит от:** ARCH-101 (детекторы → EventBus, потом расширяем в TriggerBus).

---

## ARCH-107 — Setup Engine v1 (Сфера 18) 🟢

**Источник:** `docs/TRADER_VISION_PREDICTIVE_SETUPS.md` § 2.

**Реализация v1 (минимальная, но полезная):**
- `core/setup/setup_engine.py` — новая сфера S18
- `class TradingSetup` — state machine: DRAFT → ARMED → TRIGGERED → ACTIVE → CLOSED / INVALIDATED / EXPIRED
- В v1 entry остаётся market (как сейчас) — изменения только в persistence + structure
- Setup создаётся в `_broadcast_intelligence_alert` после `is_actionable=True`

**Schema `trading_setups`** — см. `docs/TRADER_VISION_PREDICTIVE_SETUPS.md` § 5.

**Что даёт:**
- KPI: `fill_rate, time_to_fill, invalidation_rate, expired_rate`
- ML видит полную выборку включая отклонённые сетапы
- Подготовка к v2 (ARCH-108): predictive entries

---

## ARCH-108 — Predictive entries (ladder limit orders) 🟢

**Источник:** `docs/TRADER_VISION_PREDICTIVE_SETUPS.md` § 1+2 — режим B Predictive.
**Зависит от:** ARCH-107 (Setup Engine v1) + **ARCH-96 (Execution Sphere — bracket orders)**.

**`class EntryPredictor`** — entry_zone per setup_type:
- `OTE_REVERSAL`: zone = [0.705 fib, 0.786 fib]
- `LIQ_SWEEP_BOUNCE`: zone = [sweep_wick + 0.382 retrace, swing_mid]
- `WT_TSL_CROSS`: zone = [last_close − 0.3%, last_close + 0.0%]

**`class LadderLimitPlacer`** — 1–3 limit orders в зоне + TTL invalidation.

**KPI:**
- `limit_fill_rate ≥ 55%`
- `avg_slippage_pct ≤ 0.1%`
- A/B-test 30 дней vs market baseline

---

## ARCH-109 — Strategy DSL (yaml-стратегии) 🔵

**Цель:** TRADER добавляет новые стратегии без программирования — описанием в yaml.
**Зависит от:** ARCH-106 (TriggerBus) + ARCH-107 (Setup Engine v1).

**Реализация:**
- `core/strategy/dsl_loader.py` — парсер yaml → `StrategySpec`
- `strategies/declarative/*.yaml` — примеры: HTF_CHoCH_OTE, LIQ_SWEEP_BOUNCE, FUNDING_SQUEEZE

**Acceptance:** ≥ 3 yaml-стратегии работают в production. Добавление новой = только yaml-файл.

---

## ARCH-110 — Volume Profile + CVD 🔵

**Источник:** `docs/TRADER_VISION_PREDICTIVE_SETUPS.md` § 6 Группа C — гипотеза H9.

**Что добавить:**
- VPVR — агрегация trades по уровням цены за период (1d/1w). POC, VAH, VAL.
- CVD — разница buy/sell volume по trade stream. Дивергенции CVD vs price = ранний сигнал разворота.
- Новые триггеры: `vah_break_with_retest`, `poc_magnet_pull`, `cvd_divergence_15m`

**Сложность:** требует WS trade stream (тяжёлый) или агрегацию OHLCV+volume (легче).
**Acceptance:** H9 валидирована (WR ≥ 55% на 100+ сделках после VAH-retest setup).

---

## ARCH-111 — Setup-aware Meta-Learning 🔵

**Источник:** `docs/TRADER_VISION_PREDICTIVE_SETUPS.md` § 9 Фаза 7. Расширение ARCH-99.

**Вход:** `(context, setup_type, trigger_chain[3-5 last triggers])`
**Выход:** `P(setup_will_trigger)` и `P(setup_will_be_profitable | triggered)` отдельно.

**Зависит от:** ARCH-106 + ARCH-107. Нужно ≥ 30 дней данных.
**Acceptance:** AUC ≥ 0.65 (vs текущий 0.41 на closed_trades).

---

## TR-002 — Бэктест-валидация гипотез H1–H10 🟢

**Источник:** `docs/TRADER_VISION_PREDICTIVE_SETUPS.md` § 7.
**Зависит от:** ARCH-106 (TriggerBus с outcome_1h/4h/24h).

| # | Гипотеза | Acceptance |
|---|---|---|
| H1 | EQH/EQL sweep+reclaim → reversal | WR ≥ 60%, n ≥ 100, 90 дней |
| H2 | HTF CHoCH + LTF OTE retrace | Sharpe ≥ 1.5, WR ≥ 40%, RR ≥ 3, n ≥ 150 |
| H3 | Volume divergence + WT extremum | WR ≥ 60%, время ≤ 8 свечей |
| H4 | HTF WT cross + LTF FVG fill | Sharpe ≥ 2.0 |
| H5 | Funding squeeze (требует ARCH-105) | WR ≥ 55%, 30 пар × 90 дней |
| H6 | Liquidation cascade reversal | WR ≥ 65%, RR ≥ 1.5 |
| H7 | Session edge (London/NY open) | Один час с avg_R значимо выше (p < 0.05) |
| H8 | Multi-TF cascade divergence | пересчитать на текущих данных |
| H9 | VAH/POC magnet (требует ARCH-110) | WR ≥ 55% |
| H10 | BTC dominance flip → альт-сектор | глобальный bias factor |

**Скрипт:** `scripts/validate_hypothesis_H1_to_H10.py`

---

## ARCH-93 — Research: Future pivots touch→reaction 🟢

**Контекст (20.04.2026):** DEV-36 Future PP score modifier использует `get_future_daily/weekly/monthly_pivots`, но в `features_json` не персистируется. Прежде чем добавлять как feature — проверить что уровни реально работают.

**Дизайн:**
- 20 ликвидных пар, период 60–90 дней, 15m свечи
- Touch: цена коснулась уровня в пределах 0.15%
- Следующие K=4 свечи: `reaction` (отскок ≥0.3%) / `break` / `neutral`

**Deliverable:** `scripts/research_future_pivots.py` + таблица WR по reaction/break/neutral.

**Решение:** `reaction% > 55%` → добавить `future_pp_daily/weekly` + `distance_to_future_pp_pct` в features_json. `~50/50` → шум, не добавлять.

---

## ARCH-83 — Убрать wt_entry из active_strategies 🔴

**Данные:**
```
wt_entry 15-31.03:  n=1289  WR=20.0%  avgR=-0.110
wt_entry 01-14.04:  n= 834  WR=19.3%  avgR=-0.376
wt_entry 15.04+:    n=  64  WR= 4.7%  avgR=-0.937  ← катастрофа
```

**Действие:** убрать `wt_entry` из `config.yaml → trading.active_strategies`. Не понижать до priority-3 — деградирующая стратегия на любом приоритете продолжает терять.
**Файлы:** `config.yaml:191`, `core/trading_intelligence.py:377-400`

---

## ARCH-84 — Жёсткий MTF gate вместо soft multipliers 🔴

**Суть:** если MTFContext.direction_bias = LONG и bias_strength > 0.7 → SHORT-сигналы блокируются полностью.
**Исключение:** pivot_reversal от уровня (уже реализовано в ARCH-78 для BTC gate).
**Данные:** 82% SHORT, WR SHORT=33.5% vs LONG=67.6%.

---

## DEV-178 — Data integrity: split pre/post 15.04 🔴

**Шаги:**
1. SQL-скрипт: метрики отдельно для каждой эры:
   - `< 2026-03-15` (до DEV-157 min_sl_dist)
   - `2026-03-15 .. 2026-04-14` (post-DEV-157, pre-TSL fix)
   - `>= 2026-04-15` (post-TSL fix — чистые данные)
2. Пометить сделки с SL dist < min_sl_dist_pct как `data_era: 'pre_157'`
3. ML: обучать только на `>= 2026-04-15`
4. Добавить `data_era` в features_json для будущих сделок

---

## DEV-177 — Adaptive weights: EMA dampening 🟢

**Проблема:** `avgR` по всей истории — тяжёлая инерция, нет адаптации к смене рынка.
**Фикс:** заменить `by_signal_type()` all-history на EMA с half-life 50-100 сделок.
**Доп:** логировать траекторию весов каждого детектора.
**Файлы:** `core/trading_intelligence.py:246-292`, `core/trading/performance_engine.py`

---

## ARCH-80 — MarketRegime hysteresis + метрика стабильности 🔵

**Шаги:**
1. Hysteresis: не переключать режим пока новое состояние не подтвердится N=3-5 свечами
2. Метрика `regime_changes_per_day` — если >5 → warning «классификатор нервный»
**Файлы:** `core/market_regime.py`

---

## ARCH-81 — Rolling Correlation Guard 🔵

**Шаги:**
1. Rolling correlation всех открытых позиций к BTC (30 дней, пересчёт 1 раз/час)
2. Метрика `portfolio_beta_to_btc` — если >3.0, не открывать новые лонги
**Файлы:** `core/trading/trade_simulator.py:632-651`
**Приоритет:** перед LIVE.

---

## ARCH-82 — L3 checker v2: regime-aware limits 🔵

**Фикс:**
- TREND_UP: 3L + 1S + total=4
- TREND_DOWN: 1L + 3S + total=4
- HIGH_VOL: total=2
**Зависимость:** ARCH-80 (MarketRegime hysteresis).

---

## DEV-176 — SL cooldown per-TF калибровка 🔵

**Шаги:**
1. Backtest: распределение времени до следующего валидного сигнала после SL
2. Cooldown по TF: 15m→2ч, 1h→4ч, 4h→12ч (гипотеза, проверить backtestом)

---

## ARCH-85 — Формализация статусов стратегий 🟡

**Источник:** `docs/AUDIT_LESSONS_18APR.md` — Урок 2.

**Статусы:**
| Статус | В арбитре | В метриках |
|---|---|---|
| ACTIVE | да | да |
| SHADOW | нет, только лог | да, отдельно |
| DEPRECATED | нет | заархивированы |
| REMOVED | удалён | git history |

**Шаги:**
1. Добавить поле `status` + `deprecated_at` в конфиг стратегий
2. Пометить `confluence` и `multi_signal` как `deprecated_at: 2026-04-14`
3. `performance_engine.by_signal_type()` — исключать DEPRECATED из активных метрик

---

## ARCH-86 — ROADMAP: маркеры инвалидации данных 🟢

**Источник:** `docs/AUDIT_LESSONS_18APR.md` — Урок 3.

**Шаги:**
1. ROADMAP.md — добавить строки для DEV-157 (15.03), DEV-171 (14.04), DEV-174 (15.04), DEV-175 (15.04)
2. Формат: `DEV-XXX (DD.MM) — описание. Invalidates data pre-YYYY-MM-DD: <причина>`
3. Расширить `data_era`: v1 (pre-DEV-157), v2 (post-157, pre-TSL-fix), v3 (post-DEV-174/175)

---

## DEV-179 — Метрики стратегий: распределение вместо avg_R 🟡

**Источник:** `docs/AUDIT_LESSONS_18APR.md` — Урок 1.

**Обязательный набор метрик:** `n · WR · median_R · Sharpe · p90_R · top20_share`

**Пороги доверия:**
- n < 100 — выводы шумовые
- Sharpe < 0.5 — стратегия живёт на удаче
- median_R сильно ≠ avg_R — тяжёлый хвост
- top-20 сделок дают >50% прибыли — проверить

**Шаги:**
1. `performance_engine.by_signal_type()` — добавить `median_R`, `sharpe`, `p90_R`, `top20_share`
2. Дашборд: заменить avg_R-only карточки на расширенный набор
3. Подсветка warning если n<100 или Sharpe<0.5

---

## СПРИНТ «РЕАЛЬНЫЕ УБИЙЦЫ» (25.04–02.05.2026)

**Контекст:** D1 + RE-AUDIT показали 5 реальных убийц прибыли (−780R/10дней):
1. Catastrophic slippage: −375R (DEV-185)
2. DUAL_TSL хуже SINGLE: −290R (DEV-184)
3. wt_signal в TREND_UP: −24R (DEV-186)
4. wt_b мягкие пороги: −17R (DEV-187)
5. pivot_reversal SHORT TREND_DOWN: −72R (DEV-188)

**Главное про TSL:** работает технически (32% активаций успешные). Прежние выводы «TSL=70% потеря» — ложные из-за неверных метрик (B2: status='SL' вместо 'TSL' для VST).

---

## DEV-184 — Отключить DUAL_TSL strategy_type 🔴

**Проблема:** DUAL_TSL для одного signal_type даёт −0.4R хуже SINGLE. pivot_reversal SINGLE avgR=−0.13 (453), DUAL_TSL avgR=−0.56 (289).

**Шаги:**
1. Найти где выбирается `strategy_type` (вероятно `core/intelligence/recommendation_generator.py`)
2. Добавить `trading.strategy_type.dual_tsl_enabled: false`
3. Если флаг false — DUAL_TSL → даунгрейд в SINGLE
4. Логировать: `[DEV-184] {symbol} downgrade DUAL_TSL → SINGLE`

**Acceptance:** 0 новых DUAL_TSL сделок за 24ч. DUAL_TP и SINGLE продолжают работать.

---

## DEV-185 — Catastrophic slippage расследование + защита 🔴

**Проблема:** 139 VST сделок (16%) — slippage > 1R. 10 худших: R от −7 до −15.

**Примеры:**
- #6622 MINA pivot_reversal TREND_UP: maxR=17.56, R=−15.00, profit=−2.1%
- #7298 GMX pivot_reversal TREND_DOWN: R=−10.08, profit=−7.3%
- #7160 ARB watch_list_breach TREND_DOWN: R=−9.38, profit=−12.9%

**Гипотезы:** delisting/halt; STOP_MARKET без max_slippage; малая ликвидность; gap на малой волатильности.

**Шаги:**
1. `scripts/audit_slippage_root_cause.py` — для 10 худших сделок: get_filled_orders + klines ±5 мин
2. Проверить BingX API: есть ли `stopPrice + workingType` параметры
3. Коррелирует ли slippage с volume_24h пары?
4. Если max_slippage есть → добавить в bracket-ордер (3% макс)
5. Volume whitelist: volume_24h < 1M USDT → не открываться

---

## DEV-186 — wt_signal regime gate (SHORT block в TREND_UP) 🟡

**Проблема:** wt_signal SHORT в TREND_UP — 22 сделки avgR=−1.12.

**Шаги:**
1. Найти место регистрации wt_signal (~`bot/monitoring.py` около `is_actionable`)
2. Gate: `if signal_type='wt_signal' AND direction='SHORT' AND regime='TREND_UP' → action=WATCH`
3. То же для HIGH_VOL
4. Симметричный gate для LONG в TREND_DOWN
5. Лог: `[DEV-186] {symbol} wt_signal {direction} blocked: regime={regime}`

**Acceptance:** 0 новых wt_signal SHORT с regime in ('TREND_UP', 'HIGH_VOL') за 48ч.

---

## DEV-187 — wt_b жёсткий floor для порогов 🟡

**Проблема:** адаптивные пороги `os_/ob = p10/p90` на тренде падают к нулю → входы в нейтральной зоне. 7 SHORT в N-зоне avgR=−2.44.

**Где:** [signal_checkers.py:340-341](core/signals/signal_checkers.py#L340)
```python
os_ = float(np.percentile(wt1_arr, 10))
ob  = float(np.percentile(wt1_arr, 90))
```

**Фикс:**
```python
os_ = min(os_, -30.0)   # не выше -30 даже на тренде
ob  = max(ob,  +30.0)   # не ниже +30 даже на тренде
```
Config: `analysis.wt_b.os_floor=-30, ob_floor=+30`

---

## DEV-188 — pivot_reversal SHORT TREND_DOWN: проверка касания 🟡

**Проблема:** 93 SHORT в TREND_DOWN avgR=−0.77. Детектор не проверяет реальное касание уровня.

**Шаги:**
1. Для SHORT — проверять что high последних 2-3 баров касался уровня (`high >= level_price * 0.999`), а close ниже
2. `volume_z = volume_last / volume_avg_20`. Триггер только если volume_z >= 1.2
3. Записать в features_json: `real_touch=1/0`, `volume_z`
4. Сначала shadow — после 50 SHORT сделок сравнить WR(real_touch=1) vs WR(real_touch=0)
5. Если real_touch=1 даёт WR > 35% → включить как hard gate (DEV-188.2)

---

## DEV-189 — B3 фикс: UPDATE stop_loss отдельно от exchange notify 🟢

**Проблема:** [trade_simulator.py:1980](core/trading/trade_simulator.py#L1980) — условие `_is_real_move` объединяет запись в БД и отправку на биржу.

**Фикс:**
```python
_sl_changed = tsl_price and _old_sl > 0 and abs(tsl_price - _old_sl) / _old_sl * 100 >= _min_move
_is_real_move = _sl_changed and _exch_order_id  # для биржи

if _sl_changed:
    # UPDATE stop_loss в БД — для всех сделок
    with self._db_connect() as _tsl_conn:
        _tsl_conn.execute("UPDATE simulated_trades SET stop_loss=? WHERE id=? AND status='OPEN'", ...)

if _is_real_move:
    tsl_moved.append(...)  # только для биржевых
```

---

## DEV-190 — effective_status в дашборде и аналитике 🟢 ✅ (27.04.2026)

**Проблема:** 32% TSL exits скрыты под status='SL' для VST (нет TRAILING_STOP_MARKET ордеров).

**Реализован `effective_status(row)`:**
```python
def effective_status(row):
    s = row['status']
    r = row['R_multiple'] or 0
    if s == 'OPEN': return 'OPEN'
    if s == 'TP': return 'TP'
    if s == 'TSL': return 'TSL'
    if s == 'SL' and row.get('tsl_activated') == 1:
        if r > 0.1: return 'TSL_hidden_win'
        if -0.2 <= r <= 0.1: return 'BE_area'
        if r < -1.05: return 'SL_slipped'
        return 'SL_clean'
    return s
```

**Интегрирован:** performance_engine, circuit_breaker, outcome_predictor, mtf_wt/smc_specialist, auto_calibrator, confidence_calibrator, dashboard.

---

## DEV-191 — wt1_at_trigger_tf поле в features_json 🟢

**Проблема:** для wt_b_signal (детектор на 1h) `wt1_value` записывается из 15m данных.

**Фикс:** в `bot/monitoring.py:1206` добавить запись wt1 на правильном TF:
```python
detector_tf_map = {
    'wt_b_signal': '1h',
    'wt_signal': '15m',
    'pivot_reversal': '15m',
    'mtf_bias': '4h',
}
```

---

## DEV-192 — entry_to_trigger_distance_pct для pivot_reversal 🟢

**Проблема:** `distance_to_pivot_pct` в БД = TP distance. Аудит proximity невозможен.

**Фикс:** добавить `entry_to_trigger_distance_pct = abs(entry_price - level_price) / entry_price * 100` и `trigger_level_name` в features_json при регистрации pivot_reversal сделки.

---

## ARCH-100 — Финальный re-audit на effective_status 🟢

**Контекст:** после Фазы 1+2+3 спринта — переоткрыть все ключевые аудиты на корректных метриках.

**Что пересчитать:**
1. TSL effectiveness на effective_status — реальный WR/avgR при tsl_activated
2. MFE/captured_R — отсечь SL_slipped
3. Strategy WR для pivot_reversal/wt_signal/wt_b после новых gate'ов
4. Slippage residual — сколько slip% осталось после DEV-185
5. Cumulative R до/после спринта (baseline 25.04 vs финал 02.05)

**Скрипт:** `scripts/post_sprint_audit.py`
**Acceptance:** отчёт PROJECT-LOG.md. Подтверждение pivot_reversal avgR ≥ +0.10 (целевое).
