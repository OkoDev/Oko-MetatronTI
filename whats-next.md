<original_task>
Стабилизационный спринт проекта Oko MTF Bot.
Цель: заморозить фичи, привести кодовую базу в порядок, создать защитные механизмы, задокументировать.
Принцип: ни одна строка логики не меняется. Только чистка, документация, защита.

План: Фазы 0-5 из файла `C:\Users\yogoru\.claude\plans\glowing-painting-koala.md`
</original_task>

<work_completed>

## Фаза 0 — Защита ✅ (предыдущая сессия)
- Git commit 161 файл: `52c4348` — "checkpoint: stabilization start"
- Бэкап БД: `backups/subscriptions_2026-03-27_XXXX.db` (7.3 MB)
- Авто-бэкап функция `_backup_database()` в `bot_with_subscriptions.py` — хранит 7 копий
- Git tag `v0.9-stable`

## Фаза 1 — Чистка мёртвого кода ✅ (предыдущая сессия)
- Commit `bc64698` — "stabilization: phase 1 — dead code archived"
- `domain/`, `infrastructure/`, `presentation/` → `_archive/skeleton/`
- 7 устаревших скриптов → `scripts/_archive/`
- Пустые папки docs/api/, docs/architecture/, docs/guides/ — удалены

## Фаза 2 — Дедупликация вычислений ✅ (текущая сессия)
**Файл:** `bot/loops/scan_loop.py`, строки 623-633

**Проблема:** В блоке divergences (строки 625-628) выполнялись повторные вызовы:
```python
_df15_t = calculate_trend(df_entry)
_df15_t = calculate_wt(_df15_t)
_df1h_t = calculate_trend(df_1h) if df_1h is not None and not df_1h.empty else None
```
Хотя ARCH-18 pre-compute (строки 421-435) уже вычислил эти колонки.

**Фикс:** Удалены повторные вызовы, MarketRegimeClassifier.classify_from_dataframes() теперь получает df_entry и df_1h напрямую.

**Остальное уже было правильно:**
- `trading_intelligence.py` строки 674-676: guard `if "cross_up" not in df_entry.columns` — не дублирует
- `trading_intelligence.py` строки 695-697: аналогичный guard — не дублирует
- `trading_intelligence.py` строка 1874: `_compute_atr` делегирует в `compute_atr` из indicators.py
- `trading_intelligence.py` строка 1795: отдельный `get_ohlcv` — ручной /intelligence запрос, норма

## Фаза 3 — Документация ✅ (текущая сессия)
**Файл:** `config.yaml` — добавлен header с реестром shadow/disabled параметров (строки 1-22):
- `ote_shadow_mode: true` → активировать ~09.04.2026
- `market_stress_gate.enabled: false` → shadow
- `weekly_bias_filter.enabled: false` → Фаза A
- `l3_checker.enabled: false` → shadow DEV-52
- `ml.use_outcome_predictor: false` → AUC<0.55
- `signals.mtf_alert_enabled: false` → убран насовсем DEV-31
- `confluence.4h_gate_enabled: false` → временно ARCH-26

**Обнаружено:** Все приоритетные модули уже имеют docstrings:
- `core/intelligence/ml_enhancer.py` ✅
- `core/intelligence/confidence_calculator.py` ✅
- `core/intelligence/decision_trace.py` ✅
- `core/intelligence/recommendation_generator.py` ✅
- `core/smc/deep_analysis.py` ✅
- `core/trading_intelligence.py` — section-комментарии `# ──` уже есть ✅

## Фаза 4 — Тесты ✅ (текущая сессия)
**Новые файлы:**

`tests/unit/test_funding_detector.py` — 9 тестов:
- TestFundingDetectorFilters: 4 теста (порог, None, мало баров, нет кросса)
- TestFundingDetectorSignal: 5 тестов (LONG, SHORT, shadow flag, strength scale, symbol/tf)

`tests/unit/test_liquidity_sweep_detector.py` — 8 тестов:
- TestLiquiditySweepFilters: 3 теста (мало баров, нет sweep, WT не в зоне)
- TestLiquiditySweepSignal: 5 тестов (LONG, SHORT, pivot bonus, data fields, symbol/tf)

Результат: **17/17 ✅**

**Ключевое открытие при разработке тестов:**
`detect_swing_points(period=5)` требует настоящий параболический паттерн (5+ баров выше/ниже с обеих сторон). Плоский df с одним "провалом" не работает. Решение: синусоидальный df через `np.linspace(0, 4*pi, n)`.

## Фаза 5 — Config freeze ✅ (текущая сессия)
- `config_snapshots/config_v0.9_2026-03-27.yaml` — снапшот текущей конфигурации
- `.gitignore`: добавлен `config_snapshots/`
- Финальный commit: `65676fb` — "stabilization: Фазы 2-5"
- Git tag `v1.0-stable` → `65676fb`

## Итоговые коммиты стабилизации
```
52c4348  checkpoint: stabilization start — all current work
bc64698  stabilization: phase 1 — dead code archived
b53cf05  feat: auto-backup DB at start, keep 7 copies
65676fb  stabilization: Фазы 2-5 — дедупликация, документация, тесты, config snapshot
```
Tags: `v0.9-stable` (52c4348), `v1.0-stable` (65676fb)

</work_completed>

<work_remaining>

## 🔴 Приоритет 1 — DEV-75 (КРИТИЧЕСКИЙ БАГ, не решён)
**Задача:** Инвертировать иерархию TP в `get_tp_by_hierarchy()`
**Проблема:** Текущий порядок 1D→1W→confluence→1M неверный, должен быть 1M→1W→1D
**Как найти:**
```bash
grep -rn "get_tp_by_hierarchy\|tp_hierarchy" core/
```
**Влияние:** Все новые сделки получают неправильный TP уровень

## 🟡 Приоритет 2 — DEV-81 вывод из shadow mode (~09.04.2026)
Через 2 недели после 26.03.2026:
1. В `bot/loops/scan_loop.py` блок `1a` добавить строку:
   ```python
   signals_to_broadcast.append(("funding_extreme", _funding_message(sym, _funding_sig), None))
   ```
2. В `config.yaml`: `ote_shadow_mode: false` (если OTE накопил достаточно данных)

## 🟡 Приоритет 3 — TR-008 (валидация после рестарта)
Проверить /scan + /intelligence после рестарта бота (ARCH-54 фаза 3).
Убедиться что stub-файлы правильно реэкспортируют новые модули.

## 🟢 Приоритет 4 — DEV-83 (ARCH-56 implementation)
MTF Interpreter v2 Phase B. Зависит от ARCH-56 спека (ARCH агент).

## 🟢 Приоритет 5 — DEV-84 (L3 Фаза C)
Ждёт накопления OTE shadow данных (~2 недели от 29.03.2026 = ~12.04.2026).

## 🟢 Приоритет 6 — DEV-77/78 (VST/LIVE trading)
DEV-77: OrderExecutor VST/SIM layer
DEV-78: PositionManager + PositionSizer + live_orders
UI для Trading Panel (DEV-80) уже готов.

## Технический долг (низкий приоритет, из плана стабилизации)
- Фаза 2 (неполная): `_compute_atr()` в `trading_intelligence.py` строка 1874 уже правильно делегирует в compute_atr из indicators.py — фактически закрыта
- test_market_regime.py и test_regime_strategy.py имеют ошибки коллекции (ещё до нашей работы)
- test_trade_simulator.py: 21+ тестов падали до нашей работы (не деградация от стабилизации)

## Проверить после рестарта бота
- Логи `[DEV-81 shadow]` при экстремальном funding
- Логи `[DEV-82-LIQSWEEP]` + TG сообщения при sweep паттернах
- `bot.signal_counters["funding_extreme"]` и `["liquidity_sweep"]` инкрементируются
- `/trading` страница открывается в браузере
- SIM mode badge в топбаре index.html работает

</work_remaining>

<attempted_approaches>

## Первая попытка fixtures для test_liquidity_sweep_detector.py
**Подход:** Создать df с явным "провалом" в lows:
```python
lows[swing_idx] = 0.950  # swing_low
lows[-1] = 0.940         # sweep
prices[-1] = 0.960       # recovery
```
**Результат:** `detect_swing_points(period=5)` вернул `lows: []` — не нашёл swing_low

**Причина:** period=5 требует 5 баров выше с обеих сторон. Плоский df (lows=0.999 везде кроме одного бара) не создаёт настоящий локальный минимум — соседние бары тоже 0.999 ≈ swing_low, нет явного доминирования.

**Фикс:** Синусоидальный паттерн через `np.sin(x)` при x∈[0, 4π] создаёт 2 реальных swing_low на баре 18 и 43 — оба находятся detect_swing_points.

## Попытка найти дублирования в trading_intelligence.py
**Ожидание:** Найдём многократные вызовы calculate_wt/trend без guard.
**Реальность:** Строки 674-676 и 695-697 уже имеют guard `if "cross_up" not in df_entry.columns` — правильный паттерн. Строка 1795 — это отдельный `get_ohlcv` с limit=60 для ручного /intelligence запроса (не дублирование scan_one).

</attempted_approaches>

<critical_context>

## Python версия
`C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe` — Python 3.12.
Единственная версия с aiogram. `.venv` / Python 3.13 — без aiogram.

## Git теги стабилизации
- `v0.9-stable` = `52c4348` — точка входа в стабилизацию (до чистки)
- `v1.0-stable` = `65676fb` — финал стабилизации

## ARCH-18 pre-compute в scan_loop.py
Строки 421-435: calculate_wt + calculate_trend вычисляются ОДИН РАЗ для df_entry, df_1h, df_3m, df_4h, df_1d. Все детекторы должны использовать guard `if "wt1" in df.columns` или `if "cross_up" not in df.columns` перед вычислением.

## ARCH-54: stub-файлы в core/
Старые импорты `from core.X import Y` работают через stubs в корне `core/`.
`core/message_builder.py` → `from core.ui.message_builder import *`
`core/indicators.py` → `from core.indicators.indicators import *`

## scan_loop.py структура блоков scan_one
```
1a  DEV-81 FUNDING (shadow)   — только _scan_tf == _etf
1b  DEV-82 LIQUIDITY_SWEEP    — только _scan_tf == _etf, broadcast в TG
1   Anomalies                  — только _scan_tf == _etf
2   WT signals
3   Confluence (SM / fallback)
5   WT-B (1h)
8   Divergences (каждые 3 цикла)
```

## Падающие тесты (до нашей работы)
- `tests/unit/test_market_regime.py` — ошибка коллекции (import error)
- `tests/unit/test_regime_strategy.py` — ошибка коллекции
- `tests/unit/test_trade_simulator.py` — 21+ упавших теста (не деградация)
Все эти тесты падали ДО стабилизации — подтверждено через `git stash`.

## DEV-81 shadow mode
Детектор намеренно не отправляет в TG 2 недели (с 26.03.2026).
Флаг: `data["shadow"] = True`. В scan_loop блок 1a нет строки broadcast.
Активировать: добавить `signals_to_broadcast.append(...)` ~09.04.2026.

## pivot_cache формат
```python
pivot_cache[symbol] = {"W:S1": 1.234, "W:R1": 1.456, ...}
```
Ключи Weekly: `"W:S1"`, `"W:S2"`, `"W:R1"`, `"W:R2"`.

## detect_swing_points требования
`detect_swing_points(df, period=5)` — ищет локальные min/max с period=5 барами с каждой стороны.
ВАЖНО: для теста нужен синусоидальный df, не плоский.

</critical_context>

<current_state>

## Статус стабилизационного плана

| Фаза | Статус | Коммит | Ключевые файлы |
|------|--------|--------|----------------|
| 0 — Защита | ✅ | 52c4348, b53cf05 | .gitignore, bot_with_subscriptions.py |
| 1 — Чистка | ✅ | bc64698 | _archive/skeleton/, scripts/_archive/ |
| 2 — Дедупликация | ✅ | 65676fb | bot/loops/scan_loop.py:623-633 |
| 3 — Документация | ✅ | 65676fb | config.yaml header |
| 4 — Тесты | ✅ | 65676fb | tests/unit/test_funding_detector.py, test_liquidity_sweep_detector.py |
| 5 — Config freeze | ✅ | 65676fb | config_snapshots/, .gitignore |

## Тест-результаты
- Наши новые тесты: **17/17 ✅** (funding + liquidity_sweep)
- Весь unit suite: 524 passed, 37 failed, 9 skipped
- Падения существовали ДО стабилизации (не регрессия)

## Git состояние
```
Branch: main (ahead of origin/main by 31 commits)
Tags: v0.9-stable (52c4348), v1.0-stable (65676fb)
Незакоммичены: DISCUSSION.md, TASKS.md, core/infra/api_engine.py, core/infra/data_collector.py
```

## Следующий шаг
**DEV-75** — критический баг иерархии TP в `get_tp_by_hierarchy()`.
Найти через: `grep -rn "get_tp_by_hierarchy\|tp_hierarchy" core/`

</current_state>
