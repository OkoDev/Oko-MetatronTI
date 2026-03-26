<original_task>
Продолжение предыдущей сессии. Пять задач:
1. Добавить Stop hook с AGENT_ROLE=DEVELOPER в ~/.claude/settings.json (рядом с существующим TRADER)
2. DEV-79: web/static/ рефакторинг — вынести 4 HTML-константы из dashboard_server.py в статические файлы
3. DEV-80: Trading Panel — новая страница /trading с Position Sizer UI
4. DEV-81: FUNDING_EXTREME detector (shadow mode, только лог, не в TG)
5. DEV-82: LIQUIDITY_SWEEP detector (broadcast в TG)
</original_task>

<work_completed>

## 1. Stop hooks в ~/.claude/settings.json ✅
Файл: `C:/Users/yogoru/.claude/settings.json`
- Добавлен второй Stop hook с AGENT_ROLE=DEVELOPER рядом с существующим TRADER
- Итоговая структура hooks.Stop: два entry — DEVELOPER + TRADER, оба вызывают
  `scripts/check_tasks.py` с разным env var AGENT_ROLE

## 2. DEV-79: web/static/ рефакторинг ✅
- `web/dashboard_server.py`: 3266 → 985 строк (потом 1038 после DEV-80)
  - Удалены 4 HTML-константы: `_HTML`, `_SETTINGS_HTML`, `_BACKTEST_HTML`, `_DASHBOARD_HTML`
  - Handlers переключены на `web.FileResponse(Path(__file__).parent / "static/X.html")`
  - Добавлен `app.router.add_static("/static", Path(__file__).parent / "static")`
- Созданы статические файлы:
  - `web/static/index.html` (56734 байт)
  - `web/static/settings.html` (36461 байт)
  - `web/static/backtest.html` (18801 байт)
  - `web/static/operations.html` (9180 байт)
- В `web/static/index.html` добавлена ссылка "Trading Panel" в sidebar footer
- В `web/static/index.html` добавлен SIM mode badge в topbar (подгружает /api/trading/status)

## 3. DEV-80: Trading Panel ✅
`web/static/trading.html` (18119 байт) — новый файл:
- Position Sizer форма: Symbol, Deposit, Risk%, Leverage, Entry, SL
- Автозаполнение из `/api/settings`
- Таблица TP: 1R / 2R / 3R / 5R с ценами и прибылью в USDT
- `GET /api/trading/instrument_info?symbol=...` для min_notional (lazy, при blur)
- Предупреждение при марже > 50%

Новые маршруты в `web/dashboard_server.py`:
```
GET  /trading                        → _handle_trading_page
GET  /api/trading/status             → _handle_trading_status
GET  /api/trading/instrument_info    → _handle_trading_instrument_info
```

## 4. DEV-81: FUNDING_EXTREME detector ✅

### Детектор (создан в прошлой сессии)
`core/signals/funding_detector.py`:
- `detect_funding_extreme(symbol, df, funding_rate, cfg) → Optional[SignalData]`
- Порог: `|funding_rate| > 0.0005` (0.05% / 8h)
- Условие: WT cross в OS (<-40) / OB (>+40) зоне
- Shadow mode: `data["shadow"] = True`
- Strength: `min(100, int(50 + ratio * 15))`

### get_funding_rate() добавлен в data_collector
`core/infra/data_collector.py`:
- Строка 8: `import time as _time`
- Строки 9-10: `_FUNDING_CACHE_TTL = 1800`
- Строка ~38: `self._funding_cache: dict = {}` в `__init__`
- Строки ~190-213: `async def get_funding_rate(symbol) -> float | None`
  - TTL-кеш 30 мин: `{normalized: (rate, fetched_at)}`
  - `exchange.fetch_funding_rate(normalized)["fundingRate"]`

### Интеграция в scan_loop.py
`bot/loops/scan_loop.py`, блок `1a` (вставлен перед `# 2. WT`, ~строки 502-519):
- Только на `_scan_tf == _etf`
- **Shadow mode**: добавляется в `all_scan_signals` + счётчик `funding_extreme`, НО НЕ в `signals_to_broadcast`

### Форматтер
`core/ui/message_builder.py`: функция `funding_extreme_message(symbol, sig)`

## 5. DEV-82: LIQUIDITY_SWEEP detector ✅

### Детектор (создан в прошлой сессии)
`core/signals/liquidity_sweep_detector.py`:
- `detect_liquidity_sweep(symbol, df, pivot_cache, cfg) → Optional[SignalData]`
- LONG: `bar.low < swing_low AND bar.close > swing_low AND wt1 < -40`
- SHORT: `bar.high > swing_high AND bar.close < swing_high AND wt1 > +40`
- `detect_swing_points(df.iloc[:-1], period=5)` — без последнего бара
- Pivot bonus +15 при совпадении с W:S1/R1 (±0.5%)
- Base strength: `55 + min(20, sweep_depth*5) + wt_bonus`

### Интеграция в scan_loop.py
`bot/loops/scan_loop.py`, блок `1b` (~строки 520-535):
- `pivot_cache = getattr(getattr(bot, "pivot_calculator", None), "pivot_cache", {})`
- **Broadcast в TG**: `signals_to_broadcast.append(("liquidity_sweep", _sweep_message(...), None))`

### Форматтер
`core/ui/message_builder.py`: функция `liquidity_sweep_message(symbol, sig)`

## 6. signal_models.py обновлён ✅
`core/signals/signal_models.py`:
```python
FUNDING_EXTREME = "funding_extreme"   # DEV-81
LIQUIDITY_SWEEP = "liquidity_sweep"   # DEV-82
```

## 7. Синтаксис проверен ✅
```
OK: core/infra/data_collector.py
OK: core/ui/message_builder.py
OK: bot/loops/scan_loop.py
```

## 8. TASKS.md + current_state.md обновлены ✅
DEV-81, DEV-82: `🟢/🟡` → `✅ ВЫПОЛНЕНО 26.03.2026`
</work_completed>

<work_remaining>

## 🔴 Приоритет 1 — DEV-75 (КРИТИЧЕСКИЙ БАГ)
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
2. Убрать комментарий `# shadow mode` при желании

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

## Проверить после рестарта бота
- Логи `[DEV-81 shadow]` при экстремальном funding
- Логи `[DEV-82-LIQSWEEP]` + TG сообщения при sweep паттернах
- `bot.signal_counters["funding_extreme"]` и `["liquidity_sweep"]` инкрементируются
- `/trading` страница открывается в браузере
- SIM mode badge в топбаре index.html работает

</work_remaining>

<attempted_approaches>

## Регулярное выражение для извлечения HTML констант
**Проблема:** `_HTML` — подстрока `_SETTINGS_HTML`. Паттерн `_HTML = """.*?"""` матчил внутри `_SETTINGS_HTML = """` на суффиксе `_HTML`.
**Результат:** Артефакты в dashboard_server.py: `# _SETTINGS# _HTML moved to web/static/`
**Фикс:** Ручная правка через Edit tool.

## Python скрипт для add_static route
**Проблема:** `src.replace()` с одиночными кавычками не совпал с оригинальным кодом (двойные кавычки).
**Фикс:** Добавлен route напрямую через Edit tool.

## Синтаксическая ошибка в funding_detector.py
**Проблема:** `from datetime import datetime, timezone` попала внутрь сигнатуры функции.
**Фикс:** Перенесён import на уровень модуля.

</attempted_approaches>

<critical_context>

## Python версия
`C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe` — Python 3.12.
Единственная версия с aiogram. `.venv` / Python 3.13 — без aiogram.

## ARCH-54: stub-файлы в core/
Старые импорты `from core.X import Y` работают через stubs в корне `core/`.
`core/message_builder.py` — stub с `from core.ui.message_builder import *` → новые функции подхватятся автоматически.

## scan_loop.py: структура блоков scan_one
```
1a  DEV-81 FUNDING (shadow)     ← новый, только_if _scan_tf == _etf
1b  DEV-82 LIQUIDITY_SWEEP      ← новый, только если _scan_tf == _etf
1   Anomalies                    ← только _scan_tf == _etf
2   WT signals
3   Confluence (SM / fallback)
5   WT-B (1h)
8   Divergences (каждые 3 цикла)
```

## DEV-81 shadow mode intent
Детектор намеренно не отправляет в TG — нужно накопить 2 недели логов для анализа качества.
Флаг: `data["shadow"] = True`. В scan_loop.py блок 1a — нет строки broadcast.

## pivot_cache формат
```python
pivot_cache[symbol] = {"W:S1": 1.234, "W:R1": 1.456, ...}
```
Ключи Weekly: `"W:S1"`, `"W:S2"`, `"W:R1"`, `"W:R2"`.

## detect_swing_points зависимость
`core/smc/swing_points.py` — файл существует. Возвращает объект с `.lows` и `.highs`
(списки SwingPoint с `.index` и `.value`).
ВАЖНО: детектор вызывает `detect_swing_points(df.iloc[:-1], period=5)` — **без последнего бара**.

## get_funding_rate: не все пары поддерживают funding
BingX может не возвращать funding для некоторых пар. Метод возвращает `None` при ошибке — детектор пропускается.

## web/static/ файлы не в git (вероятно)
Проверить что `web/static/` не в `.gitignore`. Файлы скорее всего `??` (untracked).

</critical_context>

<current_state>

## Статус всех deliverables

| Задача | Статус | Ключевые файлы |
|--------|--------|----------------|
| Stop hooks DEVELOPER+TRADER | ✅ | `~/.claude/settings.json` |
| DEV-79: web/static/ | ✅ | `web/dashboard_server.py`, `web/static/*.html` |
| DEV-80: Trading Panel | ✅ | `web/static/trading.html` + 3 новых route |
| DEV-81: FUNDING_EXTREME | ✅ (shadow) | `core/signals/funding_detector.py`, `core/infra/data_collector.py`, `bot/loops/scan_loop.py:502-519` |
| DEV-82: LIQUIDITY_SWEEP | ✅ (broadcast) | `core/signals/liquidity_sweep_detector.py`, `bot/loops/scan_loop.py:520-535` |

## Что работает
- Синтаксис всех файлов проверен через `ast.parse` ✅
- Stub в `core/message_builder.py` автоматически реэкспортирует новые форматтеры ✅
- TASKS.md: DEV-79/80/81/82 = `✅ ВЫПОЛНЕНО` ✅

## Что НЕ проверено (требует рестарта бота)
- Реальный `get_funding_rate()` на BingX
- `[DEV-81 shadow]` логи
- `[DEV-82-LIQSWEEP]` логи + TG broadcast
- Trading Panel `/trading` в браузере
- SIM badge в index.html topbar

## Незакоммиченные изменения
Новые файлы: `web/static/*.html` (5 шт), `core/signals/funding_detector.py`, `core/signals/liquidity_sweep_detector.py`
Изменённые: `web/dashboard_server.py`, `core/infra/data_collector.py`, `core/ui/message_builder.py`, `core/signals/signal_models.py`, `bot/loops/scan_loop.py`, `TASKS.md`, `memory/current_state.md`

## Следующий шаг
1. Рестарт бота → проверка логов DEV-81/82
2. Git commit
3. DEV-75 🔴 (критический баг иерархии TP)
</current_state>
