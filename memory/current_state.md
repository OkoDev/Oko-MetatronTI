# Current State

> Последние 3 сессии. Старые записи удалены — история в git log.

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
