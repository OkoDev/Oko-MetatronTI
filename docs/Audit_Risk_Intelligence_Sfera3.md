# Аудит Risk Intelligence (Сфера 3 Куба Метатрона)

> **Дата аудита:** 05.06.2026  
> **Инициатор:** DS (DeepSeek/DeepCode)  
> **Статус:** SHADOW ONLY — не применяется в production

---

## 1. Назначение узла

**RiskIntelligenceV1** — узел Куба Метатрона, принимающий решение о **% риска, размере позиции и кредитном плече** на каждую сделку. Изначально задуман как **Сфера 3** — отдельная сфера Куба с собственным event'ом `risk_decision` на шине.

**Файл:** `core/intelligence/risk_intelligence.py` (338 строк)  
**Концепция:** пользователь спросил — «Может ли Куб сам управлять полным контуром риска, а не только сигнальной стороной?»

---

## 2. Хронология обсуждений

### 19.04.2026 — DEV (yogoru): «Размышление — Risk Intelligence как Сфера 3 Куба»

**Источник:** [`DISCUSSION-ARCHIVE-APR2026.md` стр. 15779–15864](../DISCUSSION-ARCHIVE-APR2026.md#L15779)

**Ключевые тезисы:**
- Сайзинг статичный (`user_settings.risk_pct/leverage` неизменны) — противоречит идее Куба (обучаемая система с feedback loop)
- Risk Intelligence — кандидат на **отдельную Сферу 3** (не расширение шины)

**Входы уже готовы на 19.04:**

| Вход | Статус |
|---|---|
| EMA avg_R по signal_type | ✅ DEV-177 |
| Sharpe / median_R / warnings | ✅ DEV-179 |
| OutcomePredictor P(win) | ✅ |
| MarketRegimeClassifier | ✅ с 05.03 |
| BTCRegimeProvider (ARCH-78) | ✅ |
| Entry Priority P1/P2/P3 | ⚠️ малая статистика |
| Circuit Breaker | ✅ |

**Концепт трёх ручек Куба:**

1. **`risk_pct_multiplier`** (0.3×–2.0×) — edge-based через fractional Kelly
2. **`leverage`** — функция от SL distance: `leverage = clamp(risk_pct / sl_distance_pct × safety_buffer, min, max)`
3. **`position_count_cap`** — regime-based: HIGH_VOL→2, RANGE→5, TREND→8

**Декомпозиция:**
- DEV-180 — v1 формульный (готово)
- DEV-181 — Leverage от SL distance + funding
- DEV-182 — ML-слой RandomForest (ждать 3-4 недели)
- DEV-183 — Position count cap + correlation

---

### 20.04.2026 — ARCH (oko.webdev): «Ответ по Risk Intelligence»

**Источник:** [`DISCUSSION-ARCHIVE-APR2026.md` стр. 15707–15777](../DISCUSSION-ARCHIVE-APR2026.md#L15707)

**Решения:**

| Вопрос | Решение |
|---|---|
| Сфера 3 или расширение шины? | **Отдельная Сфера 3** ✅ |
| Kelly или fixed-fraction? | **Fixed-fraction table v1** (Kelly на v2) ⚠️ |
| Leverage + funding? | **Разделить:** 181a (поле) → 181b (без funding) → 181c (с funding) |
| Shadow период? | **3 недели** (до ~10.05) |

**Архитектура (pure-core + I/O):**
- `core/trading/risk_engine.py` — pure-функции
- `core/trading/risk_applier.py` — I/O: читает PairCtx → decide → пишет `risk_decision` на шину

**Fixed-fraction table (предложена ARCH):**

| EMA avg_R | multiplier |
|---|---|
| [−0.5, 0) | 0.5 |
| [0, +0.2) | 0.8 |
| [+0.2, +0.5) | 1.0 |
| [+0.5, +1.0) | 1.3 |
| ≥ +1.0 | 1.5 |

Bool-guards: n<100 ×0.7, sharpe<0.5 ×0.7, heavy_tail ×0.7. Clamp [0.3, 2.0].

---

### 27.04.2026 — TRADER: позиция

**Источник:** [`DISCUSSION-ARCHIVE-APR2026.md` стр. 16419–16441](../DISCUSSION-ARCHIVE-APR2026.md#L16419)

**Ключевые аргументы:**
- a) Динамический сайзинг **усугубит проблему** при текущем отрицательном avg_R — сначала фикс TSL
- b) Fixed-fraction table **интерпретируем** для дашборда
- c) Shadow **4 недели** (не 3), не запускать пока TSL катастрофа не починена
- d) Leverage отделить от funding
- e) **DEV-183 (position cap) приоритетнее DEV-180** — 28 однотипных позиций в плохом режиме

**Резюме TRADER:**
- ✅ Сфера 3 отдельная
- ✅ Fixed-fraction v1, не Kelly
- ⚠️ Shadow 4 недели, не запускать пока TSL не починен
- 🔴 DEV-183 приоритетнее DEV-180

---

## 3. Что реализовано

### 3.1 Ядро: `core/intelligence/risk_intelligence.py`

**Класс `RiskIntelligenceV1`** — формульный контур. Принимает `RiskInputs`, выдаёт `RiskDecision`.

**Фактическая формула (НЕ fixed-fraction table, а перемножение факторов — победил подход DEV):**

```
risk_pct = base_risk_pct(1.0%) × pattern_quality × ema_r_factor × sharpe_factor × warning_factor × btc_regime_factor
→ clamp [0.3×, 2.0×]

leverage = ceil(risk_pct / sl_distance_pct × safety_buffer(2.0))
→ clamp [1, 20]x

allow_entry = (open_count < cap_per_regime) AND (correlation < max) AND (|funding| < 0.03%/8h)
```

**Множители:**

| Фактор | Диапазон | Логика |
|---|---|---|
| `pattern_quality` | 0.5–1.5 | `0.5 + stability_score` |
| `ema_r_factor` | 0.5–1.5 | n<30→0.7, иначе `1.0 + ema_r × 0.4 × confidence` |
| `sharpe_factor` | 0.5–1.5 | `0.7 + sharpe × 0.15` |
| `warnings_factor` | 0.2–1.0 | 0→1.0, 1→0.7, 2→0.4, 3+→0.2 |
| `btc_regime_factor` | 0.5–1.2 | LONG в bull=1.2, LONG в bear=0.5 (зеркально SHORT) |

**Gates (блокируют allow_entry):**
1. `open_positions_count >= cap_per_regime` — лимит одновременных позиций
2. `correlation > 0.7` — с уже открытыми того же направления
3. `funding > 0.03%` — экстремальный funding (LONG при positive, SHORT при negative)

**Статус:** логгирует решения в `risk_decisions_log`, **НЕ ПРИМЕНЯЕТ** (SHADOW).

### 3.2 DecisionFusion: `core/intelligence/decision_fusion.py`

**Класс `DecisionFusion`** — слияние v1 (формула) + v2 (LightGBM ML).

**Стратегии:**
- `v1_only` — baseline
- `vote_50_50` — оба agree
- `v2_with_v1_safeguard` **(рекомендуемая)** — v2 решает, v1 имеет veto при extreme risk

**Veto v1 срабатывает при:**
- `allow_entry = False` (hard gate)
- `risk_pct_multiplier < 0.5` (extreme penalty)

**V2MLPrediction:** `p_win`, `predicted_mfe_r`, `confidence`, `model_version`

### 3.3 Интеграция: `core/intelligence/arch104_signal_adapter.py`

Единая точка подключения цепочки для ARCH-104:

```
scan_one() → ARCH104SignalAdapter.process()
  ├─ 1. ARCH104Registry.find_matching() → matched patterns
  ├─ 2. RiskIntelligenceV1.evaluate() → risk_pct/leverage
  ├─ 3. DecisionFusion.fuse() (опц. с v2)
  ├─ 4. _apply_kill_switches_and_boosts() из risk_policies.yaml
  └─ 5. _log_decision() → risk_decisions_log
```

Вызывается из: `bot/loops/arch104_observer_loop.py`

### 3.4 Политики риска: `config/risk_policies.yaml`

Per-pattern конфигурация (пока только `S1_bos_premium`):
- **kill_switches** — факторы, БЛОКИРУЮЩИЕ сделку
- **boost_factors** — ×multiplier_bonus
- **penalty_factors** — ×multiplier_penalty

### 3.5 Позиционный сайзинг: `core/trading/position_sizer.py`

```python
qty = (deposit × risk_pct / 100) / sl_dist
margin_req = notional / leverage
```

Используется в `trade_router.py`, `scan_loop.py`, `monitoring.py`.

### 3.6 Статический риск (main path)

**Основной путь (НЕ ARCH-104) НЕ использует RiskIntelligence:**

| Файл | Источник риска |
|---|---|
| `bot/loops/scan_loop.py` | `config.trading.risk_pct` (статический) |
| `bot/monitoring.py` | `config.trading.risk_pct` (статический) |
| `core/trading/trade_router.py` | `get_risk_pct(config)` (статический) |
| `config.yaml:137` | `risk_pct: 1.0` |

### 3.7 База данных

| Таблица | Поля |
|---|---|
| `risk_decisions_log` | `risk_pct, leverage, allow_entry, abort_reasons, factors_json` |
| `simulated_trades.features_json` | `arch104_risk_pct` |
| `user_settings` | `risk_pct REAL NOT NULL DEFAULT 1.0` |

⚠️ Таблица `risk_decisions_log` создаётся в ДВУХ местах: `risk_intelligence.py:206` и `arch104_signal_adapter.py:257` (дублирование схемы).

### 3.8 Тесты

| Файл | Что |
|---|---|
| `tests/test_arch104_integration.py` | RiskIntelligenceV1 + DecisionFusion |
| `tests/unit/test_dry_helpers.py` | `get_risk_pct()`, `TradingSettings` |

### 3.9 UI / Дашборд

| Компонент | Что |
|---|---|
| `bot/menus/risk.py` | Меню управления риском |
| `web/dashboard_server.py:327` | `risk_exposure_pct` в API |
| `web/dashboard_server.py:1184` | `POST /api/settings` — deposit/risk_pct/leverage |
| `core/infra/config_loader.py:419` | `save_risk(deposit, risk_pct, leverage)` |

---

## 4. Статус задач

| ID | Статус | Описание |
|---|---|---|
| **DEV-180** | ✅ | Risk Intelligence v1 shadow (`risk_intelligence.py`) |
| **DEV-181** | ✅ | Leverage formula (`leverage = ceil(risk_pct / sl_distance_pct × safety_buffer)`) |
| **DEV-182** | ✅ | DecisionFusion + V2MLPrediction (LightGBM НЕ обучен — dataclass-заглушка) |
| **DEV-183** | 🔵 бэклог | Position count cap + correlation cap |
| **ARCH-98** | 🧊 FROZEN | Portfolio Manager Sphere (Сфера 16) |

---

## 5. Разрывы и проблемы

### 5.1 RiskIntelligence НЕ применяется в production (SHADOW)

`risk_intelligence.py` стр. 12: *«пока shadow only — НЕ применяется в production. Только логирует решения.»*

### 5.2 RI v1 не режет (99% apply)

Из [`memory/current_state.md`](../memory/current_state.md): *«RI v1 НЕ режет: 828/829 apply=1 (99%). 90% потерь — между risk_decisions_log и register_trade (router gates / dedup / strength).»*

### 5.3 Основной путь (не ARCH-104) игнорирует RiskIntelligence

Сигналы wt_signal, pivot_reversal, atr_change, divergence, liquidity_sweep используют **статический `risk_pct=1.0%`** из конфига — без учёта:
- EMA avgR по signal_type
- Sharpe ratio
- BTC regime
- Корреляции с открытыми позициями
- Количества одновременных позиций

### 5.4 Fixed-fraction table не реализована

Архитектурное решение ARCH (20.04) о fixed-fraction table было отвергнуто в коде — реализована мультипликативная формула DEV.

### 5.5 DEV-183 (position cap) не реализован

Это был **приоритет TRADER** (27.04): «ставит выше DEV-180/181 по приоритету». До сих пор в бэклоге.

### 5.6 LightGBM v2 не обучен

`V2MLPrediction` — dataclass-заглушка. Реального ML-движка нет. Требовалось n≥500 на signal_type (июнь 2026).

### 5.7 Дублирование создания таблицы

`risk_decisions_log` создаётся в двух независимых функциях с немного разными схемами — риск рассинхрона схемы.

### 5.8 Контекст не наполняется

В `arch104_signal_adapter.py:process()` context dict почти всегда пустой — EMA avgR, Sharpe, funding, correlation, open_positions_count передаются как 0/default.

---

## 6. Что нужно для production-активации

1. **Подключить RiskIntelligenceV1.evaluate() в trade_router/monitoring** для ВСЕХ сигнальных типов (не только arch104)
2. **Наполнить контекст** (ema_avg_r_30d, sharpe_30d, funding, correlation) из реальных данных
3. **Собрать shadow-статистику** сравнения `recommended_risk_pct` vs `actual_risk_pct`
4. **Заполнить `risk_policies.yaml`** для всех активных паттернов (сейчас только S1_bos_premium)
5. **Реализовать DEV-183** (position count cap) — приоритет TRADER
6. **Обучить LightGBM v2** при n≥500 на signal_type
7. **Устранить дублирование** создания таблицы `risk_decisions_log`
8. **Исправить RI v1 pass-through** (99% apply — не режет ничего)

---

## 7. Карта файлов

```
core/intelligence/
  risk_intelligence.py          — RiskIntelligenceV1 (338 строк)
  decision_fusion.py            — DecisionFusion v1+v2 (219 строк)
  arch104_signal_adapter.py     — Интеграция ARCH-104 (359 строк)
  pattern_lifecycle_manager.py  — PatternLifecycle check

core/trading/
  position_sizer.py             — Расчёт qty из risk_pct
  trade_router.py               — Статический get_risk_pct()

core/infra/
  trading_settings.py           — get_risk_pct(), get_leverage(), TradingSettings
  config_loader.py              — save_risk(deposit, risk_pct, leverage)

config/
  risk_policies.yaml            — Per-pattern kill/boost/penalty
  config.yaml                   — trading.risk_pct: 1.0, trading.leverage: 10

bot/
  loops/arch104_observer_loop.py  — Вызов ARCH104SignalAdapter
  loops/scan_loop.py              — Статический risk_pct
  monitoring.py                   — Статический risk_pct
  menus/risk.py                   — Меню управления риском

web/
  dashboard_server.py           — API: risk_exposure, /api/settings

tests/
  test_arch104_integration.py   — Тест RI v1 + DecisionFusion
  unit/test_dry_helpers.py      — Тест TradingSettings
```

---

## 8. Ссылки

- [DISCUSSION 19.04.2026 — Размышление DEV](../DISCUSSION-ARCHIVE-APR2026.md#L15779)
- [DISCUSSION 20.04.2026 — Ответ ARCH](../DISCUSSION-ARCHIVE-APR2026.md#L15707)
- [DISCUSSION 27.04.2026 — Позиция TRADER](../DISCUSSION-ARCHIVE-APR2026.md#L16419)
- [ARCH-104 Phase 6 — Risk Intelligence](../obsidian/Architecture/ARCH-104-Pattern-Mining-RiskIntel/ARCH-104-Phase-6-Risk-Intelligence.md)
- [TASKS.md — Risk Intelligence (#L224)](../TASKS.md#L224)
- [ENCYCLOPEDIA — Сфера 3](../docs/ENCYCLOPEDIA.md)
- [CURRENT_ARCHITECTURE — ARCH-104 Flow](../docs/CURRENT_ARCHITECTURE.md)
