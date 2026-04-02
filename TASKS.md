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
> **Статусы:** 🔴 срочно | 🟡 важно | 🟢 в плане | 🔵 бэклог | 🔄 в работе | ✅ выполнено

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
| [TR-009](#tr-009) | ✅ | R-gradient де-эскалация TSL: ARCH одобрил → DEV-91 | TRADER→ARCH |
| [TR-010](#tr-010) | ✅ | Post-TSL OTE Re-entry: ARCH одобрил → DEV-92 + DEV-93 | TRADER→ARCH |
| [TR-011](#tr-011) | ✅ | SMC shadow валидация: ВЕРДИКТ — LONG+SMC антисигнал, SHORT нейтрально → DEV action | TRADER |
| [DEV-91](#dev-91) | ✅ | TR-009: `_r_gradient_drop` shadow trigger в cascade TSL — реализован | DEV |
| [DEV-92](#dev-92) | ✅ | TR-010 Фаза 1: `_post_tsl_queue` в TradeSimulator — реализовано 29.03 | DEV |
| [DEV-93](#dev-93) | ✅ | PairContextBus: `core/context/pair_context.py` — реализовано 29.03 | DEV |
| [ARCH-60](#arch-60) | ✅ | PostTradeAnalyser спек готов 29.03 → DEV-94 реализует (ждёт DEV-93) | ARCH |
| [DEV-94](#dev-94) | ✅ | PostTradeAnalyser реализация: `core/trading/post_trade_analyser.py` — 29.03 | DEV |
| [ARCH-61](#arch-61) | ✅ | TriggerBus Фаза 1 спек: OTE Re-entry trigger + trigger_loop.py — готов 29.03 | ARCH |
| [ARCH-62](#arch-62) | 🔵 | TSL Pipeline рефакторинг: индикаторы в scan_loop, симулятор = тупой трекер | ARCH |
| [DEV-95](#dev-95) | ✅ | TriggerBus реализация: trigger_bus.py + trigger_loop.py + bot интеграция — 29.03 | DEV |
| [DEV-96](#dev-96) | ✅ | SMC флаги: 4 направленных флага в to_features() — реализовано 29.03 | DEV |
| [DEV-97](#dev-97) | 🔵 | weekly_bias gate: pivot_reversal aligned штраф -10 (после DEV-96) | DEV |
| [DEV-99](#dev-99) | ✅ | Скан 534 пар >70 сек: scan_semaphore 10→20, min_volume_usd 0→1M — 29.03 | DEV |
| [DEV-100](#dev-100) | 🟡 | chart_builder: try/except + blacklist для малоликвидных пар (GAIB, BANANA) | DEV |
| [ARCH-65](#arch-65) | ✅ | Exchange Health Guard спек: health check + TG alert + dead-man timer для LIVE — 30.03 | ARCH |
| [DEV-103](#dev-103) | ✅ | Exchange Health Loop + TG алерт (Слои 1+2 ARCH-65) — реализован 02.04 | DEV |
| [DEV-104](#dev-104) | 🔵 | Dead-Man Timer: emergency close all (Слой 3 ARCH-65) — только перед LIVE | DEV |
| [ARCH-63](#arch-63) | ✅ | Bear market filter: BTC 4h gate спек готов 30.03 → DEV-111 реализует | ARCH |
| [DEV-111](#dev-111) | ✅ | BTC 4h market gate shadow: `_get_btc_4h_regime()` + gate в monitoring.py — 02.04 | DEV |
| [DEV-101](#dev-101) | ✅ | WS Фаза 1: _log_ws_stats_after_warmup + pre-filter в trade_tracker — 29.03 | DEV |
| [DEV-102](#dev-102) | 🟡 | chart_builder: blacklist малоликвидных пар + try/except без ERROR спама | DEV |
| [ARCH-64](#arch-64) | 🔵 | pivot_reversal daily bias: штраф -20 / near W_S1/S2 → -10 — спек готов 29.03 | ARCH |
| [DEV-98](#dev-98) | ✅ | Guard 4: pivot_reversal strength≥80 → skip (Находка 2 ARCH, WR=4.5%) — 29.03 | DEV |
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
| [ARCH-58](#arch-58) | ✅ | TP Architecture: get_tp_by_hierarchy() для всех путей — реализовано 29.03 | ARCH |
| [DEV-77](#dev-77) | ✅ | OrderExecutor: core/trading/order_executor.py — SIM/VST/LIVE + bracket + partial close 29.03 | DEV |
| [DEV-78](#dev-78) | ✅ | PositionManager + PositionSizer + live_orders table + OrderReconciler — 29.03 | DEV |
| [DEV-79](#dev-79) | ✅ | Trading Panel: web/static/ рефакторинг (HTML/CSS/JS из dashboard_server.py) | DEV |
| [DEV-80](#dev-80) | ✅ | Trading Panel: /trading page + Position Sizer UI + badge SIM/VST/LIVE | DEV |
| [DEV-81](#dev-81) | ✅ | FUNDING_EXTREME detector: core/signals/funding_detector.py | DEV |
| [DEV-82](#dev-82) | ✅ | LIQUIDITY_SWEEP detector: core/signals/liquidity_sweep_detector.py | DEV |
| [DEV-83](#dev-83) | ✅ | ARCH-56 реализация: phase_detector + zone_cascade + avoid_reason + named_pattern | DEV |
| [DEV-84](#dev-84) | ✅ | L3 Фаза C: FVG/OB + OTE shadow logging — реализовано 28.03 | DEV |
| [DEV-85](#dev-85) | ✅ | OTE v2: Step0 stale-invalidation + Step1 wide [0.705-0.786] + ATR-trend gate | DEV |
| [DEV-86](#dev-86) | ✅ | `get_tp_by_hierarchy()`: убрать R4–R5/S4–S5 расширенные уровни | DEV |
| [DEV-87](#dev-87) | 🟢 | OTE backtest v2: проверить WR после Step0+Step1 фильтров (ждёт shadow данных ~11.04) | DEV |
| [ARCH-59](#arch-59) | ✅ | Market Regime v2: спек готов 28.03 → DEV-90 реализует | ARCH |
| [DEV-88](#dev-88) | ✅ | Market Regime патч: Fix1 (avg 3 ATR) + Fix3 (spike guard 5 bars) в classify_from_ohlcv() | DEV |
| [DEV-89](#dev-89) | ✅ | Cascade TSL: OR-логика 4h+1h WT + weekly pivot touch trigger — реализовано 28.03 | DEV |
| [DEV-90](#dev-90) | ✅ | ARCH-59 реализация: classify_v2() shadow mode + config.yaml — реализовано 29.03 | DEV |
| [DEV-106](#dev-106) | ✅ | Pivot Touch Fast Exit: W/M pivot touch + R≥2.0 → force 15m TSL (анализ 512 сделок, +2.44R avg) | DEV |
| [DEV-107](#dev-107) | ✅ | CASCADE_TFS.index(df_tsl) баг: всегда raises ValueError → cascade деэскалация по WT никогда не работала | DEV |
| [DEV-108](#dev-108) | ✅ | dynamic_os активирован только в RANGE: mean±0.8std как реальный gate (не shadow) | DEV |
| [DEV-109](#dev-109) | ✅ | RANGE: confluence разблокирован (WR=63.6% SHORT, avg_R=+2.67R) — pivot_reversal в RANGE уже был заблокирован в DEV-64B | DEV |
| [ARCH-66](#arch-66) | ✅ | RANGE BOUNCE спек готов 30.03: SL/TP от пивотов, entry ≤2% от края, TP_R≥3.5 | ARCH |
| [DEV-110](#dev-110) | 🟡 | RANGE BOUNCE реализация: `calc_range_bounce_sl_tp()` в sl_tp_calculator.py | DEV |
| [DEV-111](#dev-111) | ✅ | BTC 4h market gate shadow mode — реализован 02.04, commit caa3311 | DEV |
| [DEV-113](#dev-113) | ✅ | Dashboard VST P1: auto-refresh 30s + BTC 4h badge + cascade badge в open trades | DEV |
| [DEV-114](#dev-114) | ✅ | Dashboard VST P1: Risk Exposure карточка + Open P&L сегодня (R и USDT) | DEV |
| [DEV-115](#dev-115) | ✅ | Dashboard VST P1: текущий R live в open trades + cap%/MFE в closed trades | DEV |
| [DEV-120](#dev-120) | ✅ | Параллельный broadcast: asyncio.gather + TG semaphore 25 msg/sec (DEV-120, масштабирование) | DEV |
| [DEV-116](#dev-116) | 🔵 | Dashboard P2: Session heatmap + R-distribution + per-signal P&L bar chart | DEV |
| [DEV-117](#dev-117) | 🔵 | Dashboard P3: страница `/performance` + drill-down `/pair/:symbol` + SSE endpoint | DEV |
| [DEV-118](#dev-118) | ✅ | Фикс двойного analyze_symbol: best signal_type выбирается по приоритету, один analyze_symbol — 30.03 | DEV |
| [DEV-119](#dev-119) | ✅ | TRIPLE_TP_TSL убран, DUAL_TP переработан: TP1=пивот, TP2=следующий пивот, RANGE→SINGLE — 30.03 | DEV |
| [DEV-120](#dev-120) | ✅ | DUAL_TSL: TREND 70% на TP1 + 30% под TSL; взвешенный R в close_trade() — 30.03 | DEV |
| [ARCH-62](#arch-62-detail) | 🔥 | Trade Simulator рефакторинг: exit_manager + cascade_tsl + levels_calculator + strategy_resolver | ARCH |
| [DEV-121](#dev-121) | 🟢 | Self-diagnostics suite: скрипты глубокой проверки всех ключевых узлов системы | DEV |
| [ARCH-67](#arch-67) | 🔵 | USDT.D macro gate: CoinGecko API + shadow mode — бэклог май (после накопления данных BTC gate) | ARCH |
| [ARCH-68](#arch-68) | 🟢 | Куб Метатрона Фаза 2: MTF WT Specialist + MTF SMC Specialist + Reversal Mode + Narrative Builder | ARCH |
| [DEV-122](#dev-122) | ✅ | tsl_activation_r_range=0.7 (RANGE) + tp_pivot_min_r_range=1.2 — 02.04.2026 | DEV |
| [DEV-123](#dev-123) | ✅ | anti-degradation gate: R >= 5R → skip degradation в cascade_tsl.py — 02.04.2026 | DEV |
| [DEV-124](#dev-124) | ✅ | EXPIRED extension: max_R_possible >= 5R → 120h вместо 48h — 02.04.2026 | DEV |
| [DEV-91-v2](#dev-91-v2) | ✅ | R-gradient drop: убран shadow, теперь реальный gate де-эскалации — 02.04.2026 | DEV |

---

### DEV-88 — Market Regime патч 🔴
**Статус:** 🔴 Срочно
**Агент:** DEV
**Источник:** TRADER 28.03.2026, ARCH-ответ 28.03.2026

**Файл:** `core/indicators/market_regime.py` → метод `classify_from_ohlcv()`

**Fix 1 — avg ATR (было: last bar):**
```python
# Было:
if last_atr > 1.8 * median_atr:
    return "HIGH_VOL"

# Стало:
recent_atr_avg = float(atr_vals.iloc[-3:].mean())
if recent_atr_avg > 1.5 * median_atr:
    return "HIGH_VOL"
```

**Fix 3 — spike guard (новое):**
```python
# После HIGH_VOL check:
recent_ranges = (df["high"] - df["low"]).iloc[-5:]
median_range = (df["high"] - df["low"]).median()
if (recent_ranges > 3 * median_range).any():
    return "HIGH_VOL"
```

**Тест:** кейс 4/USDT 28.03.2026 10:10 — после спайка должен вернуть HIGH_VOL вместо TREND_DOWN.

---

### DEV-89 — Cascade TSL: OR-логика + weekly pivot touch 🟡
**Статус:** 🟡
**Агент:** DEV
**Источник:** TRADER 28.03.2026, ARCH-ответ 28.03.2026

**Файл:** `core/trading/trade_simulator.py` — блок cascade TSL (~строка 1055-1080)

**Изменение 1 — OR логика (фикс бага):**
```python
# Фетч 1h WT (df_lower уже нужен для _is_tighter, переставить выше):
_df_1h = await dc.get_ohlcv(symbol, "1h", limit=50)
_df_1h_wt = calculate_wt(_df_1h)
_wt_1h = float(_df_1h_wt["wt1"].iloc[-1])

# Было: только 4h WT
_wt_exhausted = (direction == "SHORT" and _wt_4h < _wt_os)

# Стало: 4h ИЛИ 1h WT
_wt_exhausted = (
    direction == "SHORT" and (_wt_4h < _wt_os or _wt_1h < _wt_os)
) or (
    direction == "LONG" and (_wt_4h > _wt_ob or _wt_1h > _wt_ob)
)
```

**Изменение 2 — weekly pivot touch (новое условие):**
```python
# R-порог: 2.5R (общий, без разделения)
# Только weekly (не monthly)
_near_weekly = False
if weekly_pivots and current_r >= 2.5:
    def _within(lvl, pct=0.015):
        return lvl and abs(current_price - lvl) / current_price <= pct
    if direction == "SHORT":
        _near_weekly = (_within(weekly_pivots.get("S1")) or _within(weekly_pivots.get("S2"))
                        or _within(weekly_pivots.get("S3")) or _within(weekly_pivots.get("PP")))
    else:
        _near_weekly = (_within(weekly_pivots.get("R1")) or _within(weekly_pivots.get("R2"))
                        or _within(weekly_pivots.get("R3")) or _within(weekly_pivots.get("PP")))

de_escalate = (current_r >= 2.5) and (_wt_exhausted or _near_weekly)
```

**Изменение 3 — лог обоих значений:**
```python
logger.info("[%s] TSL cascade wt=(4h=%.1f, 1h=%.1f) near_weekly=%s", symbol, _wt_4h, _wt_1h, _near_weekly)
```

---

### ARCH-59 — Market Regime v2: гибридный classify_v2() ✅
**Статус:** ✅ спек готов 28.03.2026 → DEV-90 реализует
**Агент:** ARCH → DEV
**Источник:** TRADER 28.03.2026 (разбор кейса 4/USDT)
**Зависит от:** DEV-88 ✅ (Фаза 1 завершена)

**Контекст:** DEV-88 — быстрый патч (avg ATR + spike guard). ARCH-59 — правильное решение долгосрочно: замена ADX-based режима на структурный + MTF.

**Архитектура (3 слоя):**
```
Слой 1: Spike Guard (мгновенный, из DEV-88)
  avg(ATR last 3 bars) > 1.5 × median_atr  →  HIGH_VOL  (уже реализовано)

Слой 2: Structural режим (1h, основной — новый)
  detect_structural_regime(df_1h) из structure_detector.py:
    последние 2 пика:  H[-1] > H[-2] (HH) + последние 2 впадины: L[-1] > L[-2] (HL) → TREND_UP
    последние 2 пика:  H[-1] < H[-2] (LH) + последние 2 впадины: L[-1] < L[-2] (LL) → TREND_DOWN
    иначе → RANGE
  Требует ≥ 4 swing point (2 highs + 2 lows)
  Fallback если < 4 точек → Слой 3 без Слоя 2

Слой 3: MTF подтверждение (существующий)
  classify_from_dataframes(df_15m, df_1h):
    согласован со Слоем 2 → подтверждаем режим
    конфликт → RANGE (консервативно)
```

**Финальная логика classify_v2():**
```python
def classify_v2(df_15m, df_1h) -> str:
    # Слой 1: spike guard (немедленный override)
    if _is_spike(df_15m):
        return "HIGH_VOL"

    # Слой 2: структурный режим на 1h
    structural = detect_structural_regime(df_1h)  # новая функция

    # Слой 3: MTF подтверждение
    mtf = classify_from_dataframes(df_15m, df_1h)  # существующий

    if structural == mtf:
        return structural  # согласованы → доверяем
    if structural != "RANGE" and mtf == "HIGH_VOL":
        return "HIGH_VOL"   # HIGH_VOL всегда приоритет
    return "RANGE"          # конфликт → консервативно
```

**Файлы:**
1. `core/signals/structure_detector.py` — новая функция `detect_structural_regime(df, period=5) -> str`
2. `core/indicators/market_regime.py` — новый метод `classify_v2(df_15m, df_1h) -> str`
3. `core/trading/trade_simulator.py` — опционально: переключить `register_trade_async` на `classify_v2` если `df_1h` доступен

**Задачи DEV (DEV-90):**
```
Шаг 1: structure_detector.py — добавить detect_structural_regime(df, period=5):
  - вызывает detect_swing_highs_lows(df, period)
  - берёт последние 2 highs + 2 lows
  - классифицирует HH/HL → TREND_UP, LH/LL → TREND_DOWN, иначе RANGE
  - если меньше 4 swing points → return None (недостаточно данных)

Шаг 2: market_regime.py — добавить classify_v2(df_15m, df_1h):
  - реализует 3-слойную логику выше
  - экспортировать рядом с classify_from_dataframes

Шаг 3: Shadow mode — логировать classify_v2 рядом с текущим classify_from_ohlcv:
  logger.debug("[regime_v2] %s: old=%s new=%s", symbol, old_regime, v2_regime)
  НЕ заменять текущий вызов, только сравнивать.
  Переключить в production через config.yaml: market_regime.use_v2: false

Шаг 4: config.yaml — добавить market_regime.use_v2: false
```

**Критерий готовности:**
- Shadow mode работает ≥ 2 недели без ошибок
- Сравнение: `use_v2=true` vs `use_v2=false` — меньше HIGH_VOL false negatives (кейс 4/USDT)
- DEV-88 остаётся как постоянный патч внутри classify_from_ohlcv (не убираем)

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
**Последний разбор:** 30.03.2026 | 60 открытых | avg_R=−0.072R (улучшение vs −0.38R) | TSL LONG avgR=+4.12R (DAM +9.73R!), TSL SHORT +2.10R | ANKR SHORT TP+2.17R ✅ | 🚨 51% SL SHORT видели ≥+1R перед SL (avg_maxR=2.27R) → нужна диагностика DEV | WL 31.03: ME/APE SHORT TREND_DOWN★, IDOL str=100 🛡 | → memory/trader_analyses/2026-03-30.md
**Следующий:** 31.03.2026 (последний день квартала)

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

### TR-009 — R-gradient де-эскалация TSL ✅
**Статус:** ✅ реализован — shadow mode (DEV-91, 29.03.2026)
**Агент:** TRADER → ARCH → DEV
**Источник:** TRADER 28.03.2026, бэктест на 2286 не-топ парах

**Идея:** третий триггер cascade TSL де-эскалации — откат от пика.

```python
max_r_achieved = (max_price - entry) / sl_dist   # LONG (аналогично SHORT)
_r_gradient_drop = (
    max_r_achieved >= 3.0               # пик был значимым
    and current_r >= 2.0                # ещё в прибыли
    and current_r < max_r_achieved * 0.55  # откатили >45%
)
de_escalate = _wt_exhausted or _near_weekly or _r_gradient_drop
```

**Бэктест (TSL+TP, не-топ пары, n=645):**
- Консервативный (trigger<55%, peak≥3R): 172 сделки, **+2.18R/сделку**, +722R итого
- Умеренный (trigger<65%, peak≥2R): 300 сделок, +1.60R/сделку, +978R итого
- 46.5% побед имеют Cap<65% → помогаем им; 45.1% — уже ОК, не трогаем

**Данные уже доступны:** `max_price`/`min_price` трекируются в реальном времени.

**→ ARCH:** одобрить архитектуру (третий триггер рядом с DEV-89) + выбрать threshold?
**→ DEV:** после ARCH апрува — реализовать как DEV-91, начать в shadow mode (логировать без активации).

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
- [x] ✅ 29.03 — **Weekly Bias (ARCH-48) валидация** (n=249, период 25-29.03):
  - **confluence LONG aligned** (BULLISH): WR=34%, avgR=+0.13R ✓ работает
  - **confluence LONG contra** (BEARISH): WR=21%, avgR=-0.46R ❌ плохо → блокировать правильно
  - **pivot_reversal LONG contra** (BEARISH): WR=56%, avgR=+0.28R ✅ исключение ARCH-48 подтверждено данными
  - **pivot_reversal LONG aligned** (BULLISH): WR=17%, avgR=-0.54R ⚠️ неожиданно — pivot_reversal хуже при aligned. ARCH: нужно ли исключить pivot_reversal из weekly gate вообще?
  - **Contra SHORT** (SHORT при BULLISH, ctx_score=0-1): WR=64%, avgR=+0.73R ✅ контр-тренд у resistance работает
  - **Context score**: 0-1 = contra допустима, score≥2 = четкий антисигнал. Порог ARCH-48 на score≥2 правильный.
  - Phase B blocked=0 записей — поле `weekly_bias_blocked` не пишется в features_json → DEV: добавить запись для мониторинга
- [x] ✅ 29.03 — **SMC-структура как фильтр (TR-011)**: вердикт готов раньше срока (n=3593). LONG+BOS/CHoCH/FVG = антисигнал (WR≈18%, avgR≈-0.45R vs baseline WR=28%). SHORT нейтрально. SMC НЕ готово в production. Действие → DEV: разбить smc_has_bos на направленный флаг. Подробности в DISCUSSION 29.03.

**Статус очереди:** ✅ 29.03 выполнены. Следующая активация: когда DEV закроет DEV-92/93 (TR-010 фаза 1) → TRADER проверяет _post_tsl_queue логи.

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

### ARCH-58 — TP Architecture: get_tp_by_hierarchy() для всех путей 🔄
**Статус:** 🔄 в работе — спек уточнён 28.03.2026
**Агент:** ARCH → DEV
**Источник:** TRADER (повторно поднималось 5+ раз в дискуссиях с 03.2026)
**Приоритет:** высокий — влияет на качество tp_source во всех новых сделках

**Уточнённая картина (аудит DEV 28.03.2026):**

Детекторы в `core/signals/` уже возвращают только `entry + SL`. TP считается в
`recommendation_generator.py:219-230` как ATR fallback (`atr_fallback_rr_3.0`).
`get_tp_by_hierarchy()` в `monitoring.py` перезаписывает его только для ЧАСТИ путей.

**Принцип:**
TP = ближайший пивот (1D/1W/confluence) на пути цены.
Если пивот не найден → ATR fallback с явной меткой `"atr_fallback"`.
Fib extension убран (бэктест: hit rate 5-15% на 15m — нецелесообразно, 28.03.2026).

**Задачи DEV (3 шага):**
1. **Аудит** `bot/monitoring.py` + `bot/scan_loop.py` — выявить все пути где `get_tp_by_hierarchy()` НЕ вызывается. Зафиксировать конкретные строки в DISCUSSION.
2. **Патч** — вызывать `get_tp_by_hierarchy()` во всех пропущенных путях.
3. **tp_source контроль** — новые записи должны иметь `"pivot_1D_R1"` (не `"atr_rr_3.0:4.2%"`). Переименовать fallback в `"atr_fallback"`.

**Критерий готовности:** `tp_source LIKE 'pivot_%'` > 60% новых сделок (остальные — явный atr_fallback)

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

### DEV-91 — TR-009: R-gradient де-эскалация TSL (shadow mode) ✅
**Статус:** ✅ реализован 29.03.2026 — shadow logging, НЕ де-эскалирует
**Агент:** DEV
**Источник:** TRADER 28.03.2026 (TR-009 бэктест), ARCH одобрил 29.03.2026
**Файл:** `core/trading/trade_simulator.py` — блок cascade TSL (~строка 1075, рядом с `_wt_exhausted`)

**Суть:** третий триггер де-эскалации — откат >45% от пика при пике ≥ 3R.

```python
# Вычислить max_r_achieved (max_price/min_price уже есть в MFE трекинге):
if direction == "LONG" and max_price and sl_dist:
    max_r_achieved = (float(max_price) - entry_price) / sl_dist
elif direction == "SHORT" and min_price and sl_dist:
    max_r_achieved = (entry_price - float(min_price)) / sl_dist
else:
    max_r_achieved = 0.0

# Консервативный триггер:
_r_gradient_drop = (
    max_r_achieved >= 3.0
    and current_r >= 2.0
    and current_r < max_r_achieved * 0.55
)

# Shadow mode — ТОЛЬКО логировать, НЕ де-эскалировать:
if _r_gradient_drop:
    logger.info("[TSL_GRAD][SHADOW] %s: peak=%.1fR cur=%.1fR ratio=%.0f%% → would_deescalate",
                symbol, max_r_achieved, current_r, current_r / max_r_achieved * 100)
```

**Критерий готовности:** 2 недели shadow логов. Подсчитать: сколько раз сработало, на каких парах, что происходило дальше (продолжение или разворот).

---

### DEV-92 — TR-010 Фаза 1: `_post_tsl_queue` в TradeSimulator 🟡
**Статус:** 🟡 к реализации
**Агент:** DEV
**Источник:** TRADER 28.03.2026 (TR-010), ARCH одобрил 29.03.2026
**Файл:** `core/trading/trade_simulator.py`

**Шаг 1** — добавить `self._post_tsl_queue: dict[str, dict] = {}` в `__init__()`.

**Шаг 2** — заполнять в `close_trade()` при STATUS_TSL. `max_price_db`/`min_price_db` уже читаются из DB в том же блоке (строка ~689):

```python
if status == STATUS_TSL:
    self._post_tsl_queue[symbol] = {
        "direction": direction,
        "exit_price": exit_price,
        "impulse_high": float(max_price_db) if max_price_db else None,
        "impulse_low":  float(min_price_db) if min_price_db else None,
        "exit_time": datetime.now(timezone.utc),
        "ttl_hours": 8,
    }
    logger.info("[POST_TSL_QUEUE] %s: добавлен direction=%s impulse=[%.4f, %.4f]",
                symbol, direction,
                self._post_tsl_queue[symbol]["impulse_low"] or 0,
                self._post_tsl_queue[symbol]["impulse_high"] or 0)
```

**Шаг 3** — инвалидация при трекинге: в цикле трекинга проверять TTL и пробой impulse:
```python
q = self._post_tsl_queue.get(symbol)
if q:
    age_h = (datetime.now(UTC) - q["exit_time"]).total_seconds() / 3600
    if age_h > q["ttl_hours"]:
        del self._post_tsl_queue[symbol]
    elif q["direction"] == "SHORT" and current_price > q["impulse_high"]:
        del self._post_tsl_queue[symbol]   # тренд сломан
    elif q["direction"] == "LONG" and current_price < q["impulse_low"]:
        del self._post_tsl_queue[symbol]
```

**Критерий готовности:** в логах появляется `[POST_TSL_QUEUE]` при TSL закрытии. Очередь корректно инвалидируется.

---

### DEV-93 — PairContextBus: `core/context/pair_context.py` 🟡
**Статус:** 🟡 к реализации
**Агент:** DEV
**Источник:** ARCH 29.03.2026 — основа Reactive Graph (Куб Метатрона Фаза 1)
**Файл:** `core/context/pair_context.py` + `core/context/__init__.py`

**Суть:** singleton in-memory хранилище состояния по паре. Основа для PostTradeAnalyser и TriggerBus.

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class PairState:
    symbol: str
    cascade_count: int = 0                    # последовательных TSL в одном направлении
    last_direction: Optional[str] = None      # SHORT/LONG последней закрытой сделки
    last_close_status: Optional[str] = None   # TSL/SL/TP
    last_close_time: Optional[datetime] = None
    avg_r_cascade: float = 0.0                # средний R по cascade серии
    post_tsl_data: Optional[dict] = None      # ссылка на _post_tsl_queue запись

class PairContextBus:
    def __init__(self):
        self._states: dict[str, PairState] = {}

    def get(self, symbol: str) -> PairState:
        if symbol not in self._states:
            self._states[symbol] = PairState(symbol=symbol)
        return self._states[symbol]

    def update(self, symbol: str, **kwargs) -> None:
        s = self.get(symbol)
        for k, v in kwargs.items():
            setattr(s, k, v)

    def all_symbols(self) -> list[str]:
        return list(self._states.keys())
```

Инициализировать singleton в `bot_with_subscriptions.py` при старте: `bot.pair_context = PairContextBus()`.
Обновлять из `close_trade()` через callback или прямым вызовом из monitoring.

**Критерий готовности:** `bot.pair_context.get("BTC/USDT")` возвращает актуальный PairState после закрытия сделки. Проверить через dashboard или лог.

---

### TR-011 — SMC shadow валидация 🟡
**Статус:** 🟡
**Агент:** TRADER
**Источник:** ARCH 29.03.2026 — Фаза 0 "Фундамент"

**Задача:** проанализировать shadow логи SMC компонентов — понять реальный WR по каждому типу сигнала.

**Что смотреть:**
- `smc_h4` / `smc_d1` в MTFSMCSnapshot логах — как часто BOS/CHoCH совпадает с прибыльными сделками?
- OTE shadow (DEV-84 логи) — сколько входов попало в OTE зону `[0.705-0.786]`?
- FVG confluence логи (ARCH-28) — бонус к strength помогает или шумит?

**Критерий:** TRADER даёт вердикт: "SMC компоненты дают сигнал → включаем в production" или "нужна доработка".

---

### ARCH-60 — PostTradeAnalyser спек ✅
**Статус:** ✅ спек готов 29.03.2026 → DEV-94 реализует после DEV-93
**Агент:** ARCH
**Источник:** ARCH 29.03.2026 — Куб Метатрона Фаза 2
**Зависит от:** DEV-93 (PairContextBus) — интерфейс уже определён, реализация параллельна

---

#### Архитектура

**Файл:** `core/trading/post_trade_analyser.py`

**Принцип:** отдельный класс, единственная ответственность — реагировать на закрытие сделок. TradeSimulator вызывает callback. PostTradeAnalyser обновляет PairContextBus и логирует паттерны.

**Конструктор:**
```python
class PostTradeAnalyser:
    def __init__(self, pair_context: PairContextBus, data_collector=None):
        self._ctx = pair_context
        self._dc  = data_collector   # для проверки дивергенций (опционально)
        self.logger = logging.getLogger("PostTradeAnalyser")
```

**Основной метод — callback от TradeSimulator:**
```python
async def on_trade_closed(
    self,
    trade_id:    int,
    status:      str,          # TSL / SL / TP / EXPIRED
    symbol:      str,
    direction:   str,          # LONG / SHORT
    r_multiple:  float,
    entry_price: float,
    sl_dist:     float,
    max_price:   Optional[float],
    min_price:   Optional[float],
    entry_tf:    str = "15m",
) -> None:
```

---

#### Сценарий 1 — STATUS_SL

```python
if status == STATUS_SL:
    # Сброс cascade (SL = направление не работало)
    ctx.update(symbol,
        last_close_status=STATUS_SL,
        last_close_time=now,
        cascade_count=0,
        last_direction=direction,
    )
    # Shadow: проверяем дивергенции для потенциального reversal
    if self._dc:
        try:
            df = await self._dc.get_ohlcv(symbol, entry_tf, limit=50)
            if df is not None:
                from core.signals.divergence_detector import detect_divergences
                divs = detect_divergences(df)
                rev_dir = "LONG" if direction == "SHORT" else "SHORT"
                bullish = [d for d in divs if d.div_type == "bullish"]
                bearish = [d for d in divs if d.div_type == "bearish"]
                relevant = bullish if rev_dir == "LONG" else bearish
                self.logger.info(
                    "[PTA][SL][SHADOW] %s: dir=%s r=%.2f div_relevant=%d → "
                    "would_add_WL direction=%s",
                    symbol, direction, r_multiple, len(relevant), rev_dir
                )
        except Exception:
            pass
```

---

#### Сценарий 2 — STATUS_TSL

```python
if status == STATUS_TSL:
    # Cascade: тот же direction → count++, иначе reset
    state = ctx.get(symbol)
    if state.last_direction == direction and state.last_close_status in (STATUS_TSL, STATUS_TP):
        new_cascade = state.cascade_count + 1
        new_avg_r   = (state.avg_r_cascade * state.cascade_count + r_multiple) / new_cascade
    else:
        new_cascade = 1
        new_avg_r   = r_multiple

    # OTE зона для re-entry (по спеку TR-010)
    post_tsl_data = None
    if max_price and min_price:
        impulse_h = max_price if direction == "SHORT" else entry_price
        impulse_l = min_price if direction == "LONG"  else entry_price
        impulse   = impulse_h - impulse_l
        if impulse > 0:
            if direction == "SHORT":
                ote_top = impulse_h - impulse * 0.705
                ote_bot = impulse_h - impulse * 0.786
            else:
                ote_bot = impulse_l + impulse * 0.705
                ote_top = impulse_l + impulse * 0.786
            post_tsl_data = {
                "direction":    direction,
                "ote_top":      ote_top,
                "ote_bot":      ote_bot,
                "impulse_high": impulse_h,
                "impulse_low":  impulse_l,
                "exit_time":    datetime.now(timezone.utc),
                "ttl_hours":    8,
            }

    ctx.update(symbol,
        last_close_status=STATUS_TSL,
        last_close_time=datetime.now(timezone.utc),
        last_direction=direction,
        cascade_count=new_cascade,
        avg_r_cascade=new_avg_r,
        post_tsl_data=post_tsl_data,
    )
    self.logger.info(
        "[PTA][TSL] %s: r=%.2fR cascade=%d avg_r=%.2f OTE=%s",
        symbol, r_multiple, new_cascade, new_avg_r,
        f"[{ote_bot:.4f}, {ote_top:.4f}]" if post_tsl_data else "None"
    )
```

---

#### Сценарий 3 — STATUS_TP

```python
if status == STATUS_TP:
    state = ctx.get(symbol)
    if state.last_direction == direction and state.last_close_status in (STATUS_TSL, STATUS_TP):
        new_cascade = state.cascade_count + 1
        new_avg_r   = (state.avg_r_cascade * state.cascade_count + r_multiple) / new_cascade
    else:
        new_cascade = 1
        new_avg_r   = r_multiple

    ctx.update(symbol,
        last_close_status=STATUS_TP,
        last_close_time=datetime.now(timezone.utc),
        last_direction=direction,
        cascade_count=new_cascade,
        avg_r_cascade=new_avg_r,
        post_tsl_data=None,   # TP = impulse завершён, OTE не нужен
    )
    self.logger.info(
        "[PTA][TP] %s: r=%.2fR cascade=%d avg_r=%.2f",
        symbol, r_multiple, new_cascade, new_avg_r
    )
```

---

#### Регистрация callback в TradeSimulator

В `TradeSimulator.__init__()`:
```python
self._post_trade_callback: Optional[Callable] = None

def set_post_trade_callback(self, cb: Callable) -> None:
    self._post_trade_callback = cb
```

В `close_trade()` после успешного UPDATE:
```python
if self._post_trade_callback:
    asyncio.create_task(self._post_trade_callback(
        trade_id=trade_id, status=status, symbol=symbol,
        direction=direction, r_multiple=r_multiple,
        entry_price=entry, sl_dist=abs(entry - sl) if sl else 0,
        max_price=max_price_db, min_price=min_price_db,
        entry_tf=entry_tf_db or "15m",
    ))
```

В `bot_with_subscriptions.py` при старте:
```python
bot.pair_context  = PairContextBus()
bot.post_analyser = PostTradeAnalyser(bot.pair_context, bot.data_collector)
bot.trade_simulator.set_post_trade_callback(bot.post_analyser.on_trade_closed)
```

---

#### Shadow mode — первые 2 недели

Все сценарии логируют `[SHADOW]` — не добавляют в WL, не меняют поведение скана.
Переключение на production: убрать `[SHADOW]` из логов + раскомментировать WL-вызовы.

---

#### Критерий готовности DEV-94

- После каждого TSL/SL/TP в логах появляется `[PTA][TSL/SL/TP]` запись
- `bot.pair_context.get("BTC/USDT").cascade_count` корректно растёт при серии TSL
- OTE зона вычисляется корректно (проверить на тестовых данных A2Z/PIPPIN)
- Нет исключений при `max_price=None` (старые сделки без MFE)

---

### DEV-94 — PostTradeAnalyser реализация 🔵
**Статус:** 🔵 бэклог — ждёт ARCH-60 + DEV-93
**Агент:** DEV
**Зависит от:** ARCH-60 (спек) + DEV-93 (PairContextBus)

Реализация по спеку ARCH-60. Файл: `core/trading/post_trade_analyser.py`.

---

### ARCH-61 — TriggerBus Фаза 1 спек ✅
**Статус:** ✅ спек готов 29.03.2026
**Агент:** ARCH
**Источник:** ARCH 29.03.2026 — Куб Метатрона Фаза 3
**Зависит от:** DEV-93 ✅ + DEV-94 ✅

---

#### Концепция

TriggerBus — лёгкий event-driven цикл, параллельный `scan_loop`.
Не дублирует полный скан — проверяет только «горячие» пары из PairContextBus.

```
trigger_loop (каждые 2 мин)
    ↓
PairContextBus.symbols_with_post_tsl()   ← «горячие» пары
    ↓
Для каждого символа:
    OteReentryTrigger.check() → hit? → analyze_symbol() → register_trade
    CascadeTrigger.check()    → hit? → analyze_symbol() → register_trade
    TTLGuard                  → expired? → ctx.update(post_tsl_data=None)
```

---

#### Файл 1: `core/context/trigger_bus.py`

```python
"""TriggerBus — DEV-95 / ARCH-61 / Куб Метатрона Фаза 3."""
from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.context.pair_context import PairState


class TriggerResult:
    def __init__(self, fired: bool, reason: str = ""):
        self.fired  = fired
        self.reason = reason


class Trigger(ABC):
    name: str = "base"

    @abstractmethod
    def check(self, symbol: str, current_price: float, state: "PairState") -> TriggerResult: ...


class OteReentryTrigger(Trigger):
    """TR-010: цена вошла в OTE зону [ote_bot, ote_top] из post_tsl_data."""
    name = "ote_reentry"

    def check(self, symbol: str, current_price: float, state: "PairState") -> TriggerResult:
        d = state.post_tsl_data
        if not d:
            return TriggerResult(False)
        elapsed_h = (datetime.now(timezone.utc) - d["exit_time"]).total_seconds() / 3600
        if elapsed_h > d["ttl_hours"]:
            return TriggerResult(False, reason="ttl_expired")
        if d["ote_bot"] <= current_price <= d["ote_top"]:
            return TriggerResult(
                True,
                reason=f"price={current_price:.4f} in OTE [{d['ote_bot']:.4f},{d['ote_top']:.4f}] dir={d['direction']}"
            )
        return TriggerResult(False)


class CascadeTrigger(Trigger):
    """Пара с cascade_count >= min_cascade → горячая, запустить полный анализ."""
    name = "cascade"

    def __init__(self, min_cascade: int = 3):
        self.min_cascade = min_cascade

    def check(self, symbol: str, current_price: float, state: "PairState") -> TriggerResult:
        if state.cascade_count >= self.min_cascade and state.last_close_status in ("TSL", "TP"):
            return TriggerResult(
                True,
                reason=f"cascade={state.cascade_count} dir={state.last_direction} avg_r={state.avg_r_cascade:.2f}"
            )
        return TriggerResult(False)
```

---

#### Файл 2: `bot/loops/trigger_loop.py`

```python
"""TriggerLoop — DEV-95 / ARCH-61. asyncio task, запускать рядом со scan_loop."""
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("trigger_loop")
TRIGGER_INTERVAL = 120  # 2 минуты


async def run_trigger_loop(bot) -> None:
    from core.context.trigger_bus import OteReentryTrigger, CascadeTrigger
    cfg         = bot.config
    ctx         = getattr(bot, "pair_context", None)
    shadow_mode = bool(cfg.get("trigger_bus.shadow", True))
    min_cascade = int(cfg.get("trigger_bus.cascade_min", 3))

    if ctx is None:
        logger.warning("[TriggerLoop] PairContextBus не инициализирован — loop не запущен")
        return

    triggers = [OteReentryTrigger(), CascadeTrigger(min_cascade=min_cascade)]
    logger.info("[TriggerLoop] старт shadow=%s interval=%ds", shadow_mode, TRIGGER_INTERVAL)

    while True:
        try:
            await _run_one_iteration(bot, ctx, triggers, shadow_mode)
        except asyncio.CancelledError:
            logger.info("[TriggerLoop] остановлен"); break
        except Exception as e:
            logger.warning("[TriggerLoop] ошибка: %s", e)
        await asyncio.sleep(TRIGGER_INTERVAL)


async def _run_one_iteration(bot, ctx, triggers, shadow_mode: bool) -> None:
    hot_symbols = ctx.symbols_with_post_tsl()
    if not hot_symbols:
        return

    # Цены пакетом
    prices: dict[str, float] = {}
    for sym in hot_symbols:
        try:
            ticker = await bot.data_collector.get_ticker(sym)
            if ticker and ticker.get("last"):
                prices[sym] = float(ticker["last"])
        except Exception:
            pass

    fired_count = 0
    for sym in hot_symbols:
        price = prices.get(sym)
        if price is None:
            continue
        state = ctx.get(sym)

        for trigger in triggers:
            # TTL инвалидация
            if trigger.name == "ote_reentry" and state.post_tsl_data:
                d = state.post_tsl_data
                elapsed_h = (datetime.now(timezone.utc) - d["exit_time"]).total_seconds() / 3600
                if elapsed_h > d["ttl_hours"]:
                    ctx.update(sym, post_tsl_data=None)
                    logger.info("[TriggerLoop] %s OTE TTL expired (%.1fh)", sym, elapsed_h)
                    continue

            result = trigger.check(sym, price, state)
            if result.fired:
                fired_count += 1
                if shadow_mode:
                    logger.info("[TriggerLoop][SHADOW] %s trigger=%s %s → would_analyze",
                                sym, trigger.name, result.reason)
                else:
                    logger.info("[TriggerLoop] %s trigger=%s %s → analyze",
                                sym, trigger.name, result.reason)
                    await _fire_analysis(bot, sym, trigger.name)
                break  # Guardrail: один trigger за итерацию на символ


async def _fire_analysis(bot, symbol: str, trigger_name: str) -> None:
    try:
        from bot.monitoring import analyze_and_send
        await analyze_and_send(bot, symbol, context=f"trigger:{trigger_name}")
    except Exception as e:
        logger.warning("[TriggerLoop] _fire_analysis %s: %s", symbol, e)
```

---

#### Конфигурация (`config.yaml`)

```yaml
trigger_bus:
  shadow: true          # true=только логи (дефолт), false=production
  cascade_min: 3        # мин. cascade_count для CascadeTrigger
  interval_sec: 120     # интервал цикла в секундах
```

---

#### Регистрация в боте (`bot_with_subscriptions.py`)

```python
# После инициализации pair_context + post_analyser:
from bot.loops.trigger_loop import run_trigger_loop
bot.trigger_task = asyncio.create_task(run_trigger_loop(bot))
```

---

#### Shadow plan

| Неделя | Действие |
|--------|----------|
| 1–2 | shadow=true: собираем логи, считаем OTE/Cascade hits |
| 3 | Анализ логов: какой % hits дал бы реальный сигнал, какой avg_r? |
| 4+ | Если EV > 0 и нет ложных срабатываний → shadow=false (production) |

---

#### Guardrails

1. **Один trigger за итерацию** — `break` после первого `fired` на символ
2. **TTL 8h** — OTE зона инвалидируется автоматически
3. **Shadow default** — `shadow: true` из коробки
4. **Нет рекурсии** — `_fire_analysis` → `analyze_and_send` → тот же `dedup_minutes` guard
5. **Цены пакетом** — один `get_ticker` per symbol per iteration

---

#### Открытые вопросы к DEV перед реализацией

→ **DEV:** Функция `analyze_and_send(bot, symbol, context=...)` существует в `bot/monitoring.py`?
Если нет — нужно создать тонкую обёртку над существующим `analyze_symbol + register_trade` потоком.
Уточни интерфейс — ARCH адаптирует спек если нужно.

---

### DEV-95 — TriggerBus реализация ✅
**Статус:** ✅ реализовано 29.03.2026
**Агент:** DEV
**Зависит от:** ARCH-61 (спек) + DEV-93 + DEV-94

Реализация по спеку ARCH-61. Файлы: `core/context/trigger_bus.py` + `bot/loops/trigger_loop.py`.

Интеграция в `bot/core/bot.py`: PairContextBus + PostTradeAnalyser + trigger_loop task. Shadow mode по умолчанию (`trigger_bus.shadow: true`).

---

### DEV-96 — SMC флаги: направленные BOS/CHoCH 🟡
**Статус:** 🟡 к реализации
**Агент:** DEV
**Источник:** TRADER TR-011 (29.03.2026) + ARCH ответ 29.03
**Файл:** `core/smc/` + `bot/monitoring.py` (блок `extra["smc_*"]`)

**Задача:** разбить нейтральные флаги на направленные. Проверить как `smc_has_bos`/`smc_has_choch` формируются в `core/smc/` — есть ли там направление (bearish/bullish). Если нет — добавить. Разделить на 4 флага: `smc_has_bearish_bos`, `smc_has_bullish_bos`, `smc_has_bearish_choch`, `smc_has_bullish_choch`. Старые поля оставить для совместимости.

**Критерий:** в новых `features_json` появляются 4 раздельных флага.

---

### DEV-97 — weekly_bias gate: pivot_reversal aligned штраф 🔵
**Статус:** 🔵 бэклог — ждёт накопления данных (n≥30 aligned pivot_reversal)
**Агент:** DEV
**Источник:** ARCH ответ TR-007 (29.03.2026)
**Файл:** `core/trading_intelligence.py` — блок weekly_bias gate

Мягкий штраф `-10` для `pivot_reversal` при aligned weekly направлении (не блок). Contra pivot_reversal исключение (ARCH-48) остаётся без изменений.

**Критерий:** n≥30 новых aligned pivot_reversal → TRADER проверяет WR повторно.

---

### ARCH-62 — TSL Pipeline рефакторинг 🔵
**Статус:** 🔵 бэклог — перед VST→LIVE переходом
**Агент:** ARCH → DEV
**Источник:** DEV 29.03.2026 — диагностика спама в логах (PivotCalculatorFixed × N сделок)

**Проблема (текущее состояние):**
`TradeSimulator.check_open_trades_with_tsl()` (~400 строк) делает всё сам:
- fetch OHLCV для 3+ таймфреймов на каждую открытую сделку
- `calculate_trend()`, `calculate_wt()` — вычисление индикаторов
- решение об эскалации/де-эскалации TSL TF
- создание `PivotCalculatorFixed` инстансов (баг, исправлен 29.03)

Симулятор = торговый движок + трекер в одном. Нарушение SRP.

**Целевая архитектура:**
```
scan_loop (уже имеет OHLCV + индикаторы для каждого символа)
  └→ для символов с открытыми сделками:
        ├─ определить best_tsl_tf (эскалация/де-эскалация) — на готовых данных
        ├─ вычислить tsl_price
        └─ UPDATE simulated_trades SET tsl_price=?, tsl_tf=? WHERE symbol=? AND status='OPEN'

trade_tracker_loop (каждые 60 сек) — только трекинг:
  └→ SELECT open trades
        ├─ current_price vs tsl_price (из БД) → закрыть если пробит
        ├─ current_price vs stop_loss → закрыть SL
        └─ current_price vs take_profit → закрыть TP
```

**Что нужно сделать:**
1. Добавить колонки `tsl_price REAL`, `tsl_tf TEXT` в `simulated_trades` (миграция)
2. Создать `core/trading/tsl_calculator.py` — чистая функция:
   `calc_tsl(symbol, direction, df_by_tf, cascade_tfs, current_r, config) → (tsl_price, best_tf)`
3. Вызывать `tsl_calculator` из `scan_loop` для активных сделок → писать в БД
4. `check_open_trades_with_tsl()` — оставить только сравнение цены с `tsl_price`/`stop_loss`/`take_profit`
5. Удалить `self._pivot_calc` из `TradeSimulator` (станет не нужен)

**Блокирует:** переход VST → LIVE (в LIVE симулятор не нужен, но архитектура трекера переиспользуется)
**Не блокирует:** текущий SIM и VST режимы — работают с монолитом

---

### DEV-99 — Оптимизация цикла скана >70 сек 🔴
**Статус:** 🔴 срочно — блокирует VST
**Агент:** DEV
**Источник:** DEV 29.03.2026 — аудит логов (4848 превышений за сессию)

**Проблема:** 534 пары × полный анализ = цикл 70–120+ сек.
`scan_loop` генерирует алерт каждый второй цикл.

**Варианты решения:**
1. Увеличить semaphore (сейчас 20) + RPS лимит — риск бана BingX
2. **Разделить пары на батчи** — N пар в цикле, остальные в следующем (ротация)
3. **Приоритетный список** — топ-100 пар по объёму сканировать каждый цикл, остальные раз в 3 цикла
4. Убрать полный анализ для пар без сигнала — только быстрый pre-filter (WT zonal check)

**Рекомендация:** вариант 3 + 4 вместе. Реализовать в `scan_loop.py`.

---

### DEV-100 — chart_builder blacklist малоликвидных пар 🟡
**Статус:** 🟡 низкий приоритет
**Агент:** DEV

Пары GAIB/USDT, BANANA/USDT падают в mplfinance. Добавить:
1. `try/except` с логом WARNING (не ERROR)
2. `_chart_blacklist` set — пара добавляется при ошибке, не пробуется снова до рестарта

---

### ARCH-63 — Bear market filter: BTC 4h Market Gate ✅
**Статус:** ✅ спек готов 30.03.2026 → DEV-111 реализует
**Агент:** ARCH → DEV
**Источник:** DEV 29.03.2026 — WR LONG=10.2% за медвежий день

**Данные:**
```
29.03.2026 (медвежий день):
LONG: WR=10.2%, avgR=−0.249 — 44 SL, 5 TP
SHORT: WR=28.6%, avgR=+0.871 — 40 SL, 16 TP
RANGE + LONG SL = 53 из 73 всех SL (73%)
```

**Решение:** полный спек в DISCUSSION.md [30.03.2026] ARCH — ARCH-63 спек.

Суть: новый gate `btc_market_gate` в `trading_intelligence.analyze_symbol()`.
BTC 4h TREND_DOWN → блок LONG (shadow mode сначала).
Исключение: pivot_reversal + weekly_bias=BULLISH.

**→ DEV-111:** реализовать shadow mode (не блокирует, только логирует WOULD_BLOCK).

---

### DEV-101 — WsFeed активация (Фаза 1) 🔥

**Статус:** 🔥 срочно
**Агент:** DEV
**Источник:** WebSocket оптимизация (WsFeed написан, не подключён)

**Что сделать:**
1. Убедиться что `bot._start_ws_feed()` запускается и `ws_feed.is_alive()` = True
2. Добавить в дашборд `/settings` → статус WsFeed (active_tickers, uptime)
3. В `trade_simulator` pre-filter: если `ws_feed.get_price(symbol)` доступен → проверить dist до SL/TP → если далеко (>10%) → пропустить REST OHLCV для TSL расчёта

**Ожидаемый эффект:** -40-60% REST запросов от trade_tracker_loop при 90+ открытых сделках.

---

### DEV-102 — chart_builder blacklist 🟡

**Статус:** 🟡 некритично
**Агент:** DEV

**Проблема:** GAIB/USDT, BANANA/USDT — mplfinance падает на нестандартных свечах → ERROR спам в логах.

**Решение:** добавить в `config.yaml` список `chart_builder.blacklist_symbols` + try/except с уровнем DEBUG вместо ERROR для игнорируемых пар.

---

### ARCH-64 — pivot_reversal daily bias блок 🔵

**Статус:** 🔵 бэклог
**Агент:** ARCH

**Данные:** pivot_reversal LONG WR=0% (9 SL / 0 TP) за медвежий день 29.03.2026.

**Вопрос → TRADER:** стоит ли полностью блокировать pivot_reversal LONG если daily bias = BEARISH? Или только снижать strength?

---

### ARCH-65 — Exchange Health Guard спек ✅

**Статус:** ✅ спек готов 30.03.2026 → DEV-103 + DEV-104 реализуют
**Агент:** ARCH → DEV

Полный спек в DISCUSSION.md [30.03.2026] ARCH — ARCH-65.

**Три слоя:**
1. `bot/loops/health_loop.py` — ping каждые 30 сек, статус HEALTHY/DEGRADED/DOWN
2. TG алерт: DEGRADED >60 сек → WARNING, DOWN >5 мин → CRITICAL, восстановление → ✅
3. Dead-man timer: только LIVE, DOWN >30 мин → аварийное закрытие всех позиций

**→ DEV-103:** Слои 1+2 (health loop + TG алерт) — нужно для SIM/VST
**→ DEV-104:** Слой 3 (dead-man timer) — только перед включением LIVE

---

### DEV-103 — Exchange Health Loop + TG алерт 🔥

**Статус:** 🔥 срочно (нужно перед VST)
**Агент:** DEV
**Зависит от:** ARCH-65 спек ✅

**Файлы:**
- Создать `bot/loops/health_loop.py` — `ExchangeHealth`, `health_check_loop()`, `_ping_exchange()`
- `bot/core/bot.py` — добавить `asyncio.create_task(health_check_loop(self))` + поля
- `bot/loops/scan_loop.py` — проверка `bot.exchange_health == DOWN` → skip cycle
- `web/dashboard_server.py` — badge статуса биржи в топбаре

---

### DEV-104 — Dead-Man Timer (только LIVE) 🔵

**Статус:** 🔵 бэклог — только перед включением LIVE
**Агент:** DEV
**Зависит от:** DEV-103

DOWN >30 мин + execution_mode=LIVE → `_emergency_close_all()` через `OrderExecutor`.

---

### DEV-111 — BTC 4h Market Gate Shadow Mode 🟡

**Статус:** 🟡 важно — после DEV-103
**Агент:** DEV
**Зависит от:** ARCH-63 спек ✅ (DISCUSSION.md 30.03.2026)

**Суть:** shadow-мониторинг — сколько сделок было бы заблокировано BTC 4h gate. Не блокирует реально, только логирует.

**Файлы:**

| Файл | Что делать |
|---|---|
| `bot/core/bot.py` | Добавить `self._btc_4h_regime_cache: dict \| None = None` |
| `bot/monitoring.py` | Добавить `_get_btc_4h_regime(bot)` рядом с `_get_btc_regime()` |
| `bot/loops/scan_loop.py` | Получать `_btc_4h = await _get_btc_4h_regime(bot)` перед вызовом analyze_symbol |
| `core/trading_intelligence.py` | Добавить параметр `btc_market_regime: str \| None = None` в analyze_symbol(), новый блок ARCH-63 |
| `config.yaml` | Добавить секцию `trading.btc_market_gate` (см. спек) |

**Точный код:** в DISCUSSION.md [30.03.2026] ARCH — ARCH-63 спек.

**Config начальный:**
```yaml
trading:
  btc_market_gate:
    enabled: true
    shadow_mode: true
    block_short_in_uptrend: false
```

**Проверка результата:** через 5-7 дней смотреть логи `ARCH-63 SHADOW WOULD_BLOCK` — сколько LONG было бы заблокировано при BTC 4h TREND_DOWN. Если WR заблокированных < 25% → переключить `shadow_mode: false`.

---

### DEV-110 — RANGE BOUNCE SL/TP Calculator 🟡

**Статус:** 🟡 важно — после DEV-103 + DEV-111
**Агент:** DEV
**Зависит от:** ARCH-66 спек ✅ (DISCUSSION.md 30.03.2026)

**Суть:** в RANGE режиме на 15m использовать пивотные уровни для SL/TP вместо ATR-based. Только confluence и watch_list_breach.

**Файлы:**

| Файл | Что делать |
|---|---|
| `core/smc/sl_tp_calculator.py` | Новая функция `calc_range_bounce_sl_tp(direction, entry, pivots, cfg)` |
| `core/trading/trade_simulator.py` | Вызов RANGE BOUNCE перед стандартным SL/TP в `register_trade_async()` |
| `config.yaml` | Секция `trading.range_bounce` (см. спек) |

**Алгоритм:** в DISCUSSION.md [30.03.2026] ARCH — ARCH-66 спек.

**Config начальный:**
```yaml
trading:
  range_bounce:
    enabled: false          # включить после первичного теста
    sl_buffer_pct: 0.003
    min_tp_r: 3.5
    max_sl_dist_pct: 0.02
    timeframes: ["15m"]
```

**Ожидаемый эффект:** при корректной реализации WR по confluence+WL_breach в RANGE вырастет с 22-37% до 40%+ за счёт правильного SL/TP.

---

### ARCH-66 — RANGE BOUNCE стратегия ✅

**Статус:** ✅ спек готов 30.03.2026 → DEV-110 реализует
**Агент:** ARCH → DEV

Полный спек в DISCUSSION.md [30.03.2026] ARCH — ARCH-66 спек.

Ключевые параметры:
- regime=RANGE + signal IN (confluence, watch_list_breach) + 15m
- SL = ближайший пивот по ту сторону от entry + 0.3% буфер
- TP = противоположный пивот
- Фильтры: entry ≤2% от SL-пивота, TP_R ≥ 3.5R

---

### DEV-113 — Dashboard VST P1: auto-refresh + BTC 4h badge + cascade badge 🔥

**Статус:** 🔥 срочно (нужно для VST)
**Агент:** DEV
**Источник:** TRADER 29.03 Приоритет 1 + ARCH аудит 29.03

**Файлы:** `web/static/index.html` + `web/dashboard_server.py`

**Что сделать:**

1. **Auto-refresh 30 сек** — в JS главной страницы добавить `setInterval(loadData, 30000)`. Уже есть функция `loadData()` — просто добавить вызов по таймеру.

2. **BTC 4h badge в шапке** — отдельный span рядом с существующим BTC 1h.
   - API: в `_handle_stats` добавить поле `btc_4h_regime` из `bot._btc_4h_regime_cache["regime"]` (если есть, иначе null).
   - Цвет: TREND_DOWN=красный, TREND_UP=зелёный, RANGE=серый.

3. **Cascade badge в таблице открытых позиций** — новая колонка `Cascade`.
   - Данные: `features_json.cascade_level` (если есть в JSON — строки типа `"4h"`, `"1h"`, `"15m"`).
   - Если cascade_level отсутствует — пустая ячейка.
   - Если есть — colored badge: `4h`=зелёный, `1h`=желтый, `15m`=серый.

---

### DEV-114 — Dashboard VST P1: Risk Exposure + Open P&L сегодня 🔥

**Статус:** 🔥 срочно (нужно для VST)
**Агент:** DEV
**Источник:** TRADER 29.03 Приоритет 1

**Файлы:** `web/static/index.html` + `web/dashboard_server.py` + `core/performance_engine.py`

**Что сделать:**

1. **Risk Exposure карточка** — % депозита под риском по всем открытым позициям.

   Формула:
   ```
   deposit_usdt = user_settings.deposit_usdt (или 1000 по умолчанию)
   risk_pct = user_settings.risk_pct (или 1.0% по умолчанию)
   total_risk_usdt = count(OPEN trades) × deposit_usdt × risk_pct / 100
   total_risk_pct = total_risk_usdt / deposit_usdt × 100
   ```
   Показывать крупно: `4.3%` (от депозита), ниже: `$43.00 / $1000`.
   Цвет: < 5% = зелёный, 5-10% = жёлтый, > 10% = красный.

2. **Open P&L сегодня** — сумма нереализованного P&L открытых позиций.

   Данные: поле `unrealized_r` уже считается в `_handle_stats` для каждой сделки.
   Суммировать все `unrealized_r` → показать `+2.3R` / `-1.5R` рядом с Risk Exposure.

3. **API изменения в `_handle_stats`:**
   - Добавить `risk_exposure_pct`, `risk_exposure_usdt`, `open_pnl_r` в JSON ответ.
   - Читать `deposit_usdt` и `risk_pct` из `user_settings` таблицы (дефолт 1000 USDT и 1%).

---

### DEV-115 — Dashboard VST P1: live R в open trades + cap%/MFE в closed 🟡

**Статус:** 🟡 важно (VST улучшение)
**Агент:** DEV
**Источник:** TRADER 29.03 Приоритет 1 + ARCH аудит

**Файлы:** `web/static/index.html`

**Что сделать:**

1. **Текущий R в open trades** — добавить колонку `Current R` в таблицу открытых позиций.
   - Данные: `unrealized_r` уже есть в `_handle_stats` → просто отобразить.
   - Цвет: > 0 = зелёный, < 0 = красный, null = серый.

2. **cap% колонка в closed trades** — `captured_R_pct` уже есть в БД (MFE данные).
   - Добавить колонку `Cap%` в таблицу закрытых сделок.
   - null = прочерк (старые сделки до MFE).

3. **MFE колонка в closed trades** — `max_R_possible` → показать как `Max R`.

4. **Сортировка по колонкам** — JS: click на заголовок → sort asc/desc.

---

### DEV-116 — Dashboard P2: Аналитические графики 🔵

**Статус:** 🔵 бэклог
**Агент:** DEV
**Источник:** ARCH аудит 29.03

Реализовывать после P1 задач (DEV-113/114/115).

- Session heatmap: ASIA/LONDON/NY × WR% (UTC-18 = ASIA, UTC 8-16 = LONDON, UTC 13-22 = NY)
- R-distribution histogram (Chart.js)
- Per-signal P&L bar chart: signal_type → avg R
- MFE vs Exit R scatter: выявляет недобор TSL
- P&L Calendar: понедельный heatmap (зелёный/красный день)

---

### DEV-117 — Dashboard P3: страницы /performance + /pair/:symbol + SSE 🔵

**Статус:** 🔵 бэклог
**Агент:** DEV
**Источник:** ARCH аудит 29.03

Реализовывать в VST фазе.

Новая структура страниц:
```
/                   → Live Monitor (открытые позиции + risk exposure)
/performance        → Аналитика (equity, heatmaps, scatter)
/trades             → Таблица закрытых с фильтрами
/pair/:symbol       → Drill-down по паре
/settings           → настройки (существует)
```

- `/api/events` SSE endpoint — live push без polling через aiohttp
- `web/static/performance.html` — новая страница аналитики
- Rolling WR (last 50) с цветовым индикатором деградации сигнала

---

### DEV-118 — Выбор лучшего сигнала: один analyze_symbol на пару за цикл 🟡

**Статус:** 🟡 важно
**Агент:** DEV
**Источник:** ARCH диагностика 30.03.2026 по логам DYDX

**Проблема:**
`scan_loop.py` строка 780: `create_task(_broadcast_intelligence_alert)` вызывается для каждого элемента `signals_to_broadcast`. Если у DYDX за один цикл нашли `confluence` + `wt_signal` — создаются два task, каждый делает полный `analyze_symbol` (~27 сек + ~19 сек CPU зря).

Нужно **не блокировать второй**, а **выбрать лучший signal_type** и запустить ОДИН `_broadcast_intelligence_alert`. При этом `pre_signals` (all_scan_signals) передаётся полным — все сигналы как контекст анализа.

**Решение — приоритетный выбор в `scan_one()` перед broadcast:**

```python
# Приоритет signal_type (убывает): чем выше — тем сильнее сигнал
_SIGNAL_PRIORITY = {
    "confluence":      100,
    "wt_b":            90,
    "wt_signal":       80,
    "liquidity_sweep": 70,
    "anomaly":         50,
    # остальные: 0
}

# Вместо:
for sig_type, raw_text, fallback_rec in signals_to_broadcast:
    asyncio.create_task(_broadcast_intelligence_alert(...))

# Стало:
if signals_to_broadcast:
    # Выбрать один — с наивысшим приоритетом
    best = max(
        signals_to_broadcast,
        key=lambda x: _SIGNAL_PRIORITY.get(x[0], 0)
    )
    sig_type, raw_text, fallback_rec = best
    if len(signals_to_broadcast) > 1:
        skipped = [s[0] for s in signals_to_broadcast if s is not best]
        logger.info("[%s] DEV-118: best=%s, пропущены=%s", sym, sig_type, skipped)
    asyncio.create_task(
        _broadcast_intelligence_alert(bot, sym, raw_text, sig_type,
                                     fallback_rec=fallback_rec, pre_signals=pre,
                                     pre_fetched_dfs=_pre_dfs)
    )
```

**Важно:** `pre_signals` (all_scan_signals) содержит **все** найденные сигналы (confluence + wt_signal + ...) и передаётся как контекст в `analyze_symbol`. Выбор одного signal_type влияет только на то, какой текст сообщения отправить в TG и какой dedup-ключ использовать — не на качество анализа.

**Ожидаемый эффект:**
- analyze_symbol вызывается 1 раз вместо N на пару за цикл
- CPU нагрузка от AI-анализа снижается пропорционально числу "дублей"
- Качество анализа не страдает — все сигналы в pre_collected_signals

**Файл:** `bot/loops/scan_loop.py` — только блок `signals_to_broadcast` (~строки 780-785)

---

### DEV-121 — Self-Diagnostics Suite 🟢

**Статус:** 🟢 в плане
**Агент:** DEV
**Источник:** ARCH 30.03.2026 — "скрипты глубокой самодиагностики для всех основных узлов"

**Цель:** Периодически запускаемый набор скриптов, подтверждающий стабильность работы системы и корректность её логики — без поднятия бота и биржи.

**Узлы для проверки:**

| Узел | Скрипт | Что проверяем |
|---|---|---|
| SL/TP/TSL логика | `scripts/diag_exit_logic.py` | Эталонные кейсы: LONG hit_SL, LONG hit_TP, LONG TSL cascade, DUAL_TP tp1_hit→tp2, bounce TSL-only |
| Market Regime | `scripts/diag_regime.py` | TREND_UP/DOWN/RANGE/HIGH_VOL на синтетических OHLCV с известным ADX/ATR/EMA |
| Cascade TSL | `scripts/diag_cascade_tsl.py` | Эскалация 15m→1h→4h, де-эскалация по WT, pivot touch force-15m |
| Pivot Levels | `scripts/diag_pivots.py` | S1/R1/S2/R2 для Woodie/Standard/Camarilla — сравнение с эталоном |
| WT Scanner | `scripts/diag_wt_scanner.py` | dynamic_os=false не пробрасывает RANGE сигналы; OS/OB пороги |
| R_multiple calc | `scripts/diag_r_calc.py` | DUAL_TP: tp1_fix_pct=20 + 80% TSL → правильный взвешенный R |
| features_json | `scripts/diag_features.py` | Все ключи present: htf_wt1_1h_aligned, wt1_value, session, regime_v2 и др. |

**Формат вывода:**
```
[✅ PASS] SL/TP: LONG hit_SL → R=-1.00
[✅ PASS] SL/TP: LONG DUAL_TP tp1_hit tp1_fix_pct=20 → R_weighted=3.40
[❌ FAIL] Cascade TSL: de-escalate 4h→1h WT exhausted — expected best_tsl_tf='1h', got '4h'
[⚠️ WARN] R_multiple: tsl_tf default='15m' should be '1h' for 15m entry
```

**Запуск:**
```bash
python scripts/run_diagnostics.py          # запускает все скрипты
python scripts/run_diagnostics.py --quick  # только SL/TP + Regime (30 сек)
```

**Дополнительно — интеграция в dashboard:**
- `/api/diagnostics` endpoint → запускает quick тест → JSON статус каждого узла
- Бейдж "Система OK / ⚠️ N проблем" в шапке дашборда

**Зависит от:** ARCH-62 (exit_manager) — после рефакторинга unit-тесты станут чище; но диагностику можно начать уже сейчас на текущем коде.

---


### DEV-122 — cascade_tsl.py: вынести + cap_tf при tp1_hit 🟡

**Статус:** 🟡 важно — после DEV-111
**Агент:** DEV
**Источник:** TRADER+DEV DISCUSSION 01.04.2026, подтверждён ARCH 02.04.2026

**Проблема:** Два бага в каскадном TSL:
1. `tsl_tf TEXT DEFAULT '15m'` в БД → TSL стартует с тесного 15m если сигнал не несёт `entry_tf`
2. После tp1_hit каскад может эскалировать до 4h → слишком широкий → cap%=33% вместо ~55%

**Решение:** новый модуль `core/trading/cascade_tsl.py` с интерфейсом:
```python
def resolve_tsl_tf(
    symbol, direction, current_r, prev_tsl_tf,
    df_map: dict,   # {"15m": df, "1h": df, "4h": df}
    tp1_hit: bool,  # True → cap_tf = "1h"
    cfg,
) -> tuple[str, DataFrame]:   # (new_tsl_tf, df_tsl)
```

Логика:
- `tp1_hit=False` → обычный каскад: 15m → 1h → 4h
- `tp1_hit=True` → `cap_tf="1h"`: максимум 1h, не поднимаемся до 4h

**Что перенести из trade_simulator.py:**
- ВСЯ логика TSL: эскалация / деэскалация / R-gradient drop (DEV-91) / pivot_touch fast exit (DEV-106) / WT exhaustion / cascade degraded

**Файлы:**
| Файл | Что делать |
|---|---|
| `core/trading/cascade_tsl.py` | Новый модуль — вся каскадная логика |
| `core/trading/trade_simulator.py` | Заменить ~300 строк на вызов `cascade_tsl.resolve_tsl_tf()` |

**Ожидаемый эффект:** cap% DUAL_TP tp1_hit: 33% → ~55-60%

---

### DEV-123 — TP reliability query 🟡

**Статус:** 🟡 быстрая задача (~15 мин)
**Агент:** DEV
**Источник:** TRADER DISCUSSION 01.04.2026

**SQL:**
```sql
SELECT strategy_type,
       tp1_hit_at IS NULL as tp1_missing,
       status,
       COUNT(*) as n,
       ROUND(AVG(R_multiple), 3) as avg_R
FROM simulated_trades
WHERE strategy_type IN ('DUAL_TP','DUAL_TSL')
  AND status != 'OPEN'
GROUP BY strategy_type, tp1_missing, status
ORDER BY strategy_type, status
```

**Ожидаемый результат:** понять — бывают ли `status=TP` при `tp1_hit_at IS NULL`? Если да — TP2 закрывает напрямую (нормально), если нет — нужен дополнительный анализ.

→ **DEV:** результат вставить в DISCUSSION.

---

### ARCH-68 — Куб Метатрона Фаза 2: ML Специалисты + Narrative Builder 🟢

**Статус:** 🟢 в плане (после Фазы 1 — ARCH-62 + DEV-121)
**Агент:** ARCH → DEV
**Источник:** TRADER 02.04.2026 — концепция Куба Метатрона
**Документация:** `docs/ENCYCLOPEDIA.md` → раздел "Архитектурная концепция: Куб Метатрона"

---

#### Состав Фазы 2

**Сфера 3 — MTF WT Specialist (`core/ml/mtf_wt_specialist.py`)**

ML модель обученная исключительно на MTF WT + ATR-trend данных.

Входные признаки (35): 7 TF × 5 признаков
```
TF: 1d, 4h, 1h, 45m, 15m, 5m, 3m
Признаки per TF:
  wt1 (float)         — значение WaveTrend 1
  wt2 (float)         — значение WaveTrend 2
  zone (-1/0/1)       — OS / Normal / OB
  wt_cross (-1/0/1)   — медвежий / нет / бычий кросс
  atr_trend (1/-1)    — направление ATR-тренда (calculate_trend()) ← НЕ ЗАБЫТЬ
```
Выход: `TREND_CONTINUATION / REVERSAL_SETUP / EXHAUSTION / UNCLEAR`
+ confidence 0.0-1.0

Обучение:
- X = wt_snap из features_json (per trade)
- y = TP=1 / SL=0
- Переобучается в ml_loop как OutcomePredictor

**Сфера 4 — MTF SMC Specialist (`core/ml/mtf_smc_specialist.py`)**

Признаки (36): 4 TF × 9 признаков
```
TF: 1d, 4h, 1h, 15m
  ob_bull (bool)          — бычий Order Block активен
  ob_distance_pct (float) — расстояние до OB в %
  fvg_open (bool)         — незакрытый Fair Value Gap
  choch (bool)            — CHoCH (последние N баров)
  bos (bool)              — BOS
  ote_zone (bool)         — цена в OTE [0.705-0.786]
  eqh_near (bool)         — Equal Highs в радиусе 1% (ликвидность сверху)
  eql_near (bool)         — Equal Lows в радиусе 1% (ликвидность снизу)
  liquidity_above (bool)  — пул ликвидности выше цены
```
Выход: `STRONG_BULL_ZONE / WEAK_ZONE / STRONG_BEAR_ZONE / NEUTRAL`

EQH/EQL важность:
- Equal Highs = уровни ликвидности которые маркетмейкер sweep
- EQH на 1h + OTE 15m = stop hunt setup → SHORT
- EQL на 1h + OTE 15m = liquidity grab → LONG
- Детектор EQH/EQL: добавить в `core/smc/liquidity.py`

**Сфера 6 расширение — Reversal Mode Detector**

В `core/indicators/market_regime.py` добавить поле `mode`:
```
mode = TREND    когда: ADX растёт + WT не в OS/OB + нет CHoCH
mode = REVERSAL когда: WT 4h в OS/OB (< -60 или > 60)
                    AND ADX 1h снижается 3+ бара
                    AND CHoCH на 1h или 15m
```
Влияние на Decision Core:
- mode=TREND    → confluence +0, pivot_reversal -20 strength
- mode=REVERSAL → pivot_reversal +0, confluence -20 strength

Данные подтверждают: 27-29.03 (TREND) confluence avg+0.49R / 01.04 (REVERSAL) pivot_reversal +0.81R WR=41.7%

**Сфера 9 — Narrative Builder (`core/intelligence/narrative_builder.py`)**

Читает из SharedContextBus:
- mtf_wt_verdict + mtf_smc_verdict
- режим (TREND/REVERSAL) + макро (BTC/USDT.D)
- все активные сигналы
- cascade_count + post_tsl_data

Строит TradingNarrative:
```python
@dataclass
class TradingNarrative:
    text: str            # человекочитаемый нарратив для TG
    action: str          # BUY/SELL/HOLD/WATCH
    strategy: str        # SINGLE/DUAL_TP/DUAL_TSL
    confidence: float    # итоговая уверенность
    p_win: float         # P(win) взвешенно от всех ML
    key_factors: list    # топ-3 фактора решения
    mode: str            # TREND/REVERSAL
```

**Shared Context Bus расширение**

`core/context/pair_context.py` → добавить pub/sub:
```python
def publish(symbol, event_type, data)  # публикация события
def subscribe(event_type, handler)      # подписка модуля
def get_state(symbol) → PairFullState  # полное состояние пары
```

---

#### Зависимости
- Фаза 1 (ARCH-62 Exit Manager) — до начала Фазы 2
- DEV-121 Self-Diagnostics — параллельно
- Накопление данных с wt_snap в features_json — для обучения специалистов

---
