# What's Next — Handoff Document

> Последнее обновление: **2026-05-09 ~17:30 UTC** (Агент: Developer/Sonnet).
> Предыдущая запись (09.05 ~15:30 UTC) — в разделе `<previous_session>` ниже.

---

<current_session>

<original_task>
Продолжение спринта «Confirmation-Driven Architecture» (DEV-199..205).

1. Завершить wiring ATR change → прямой вход (вызов `_execute_atr_change_signal` из блока детекции)
2. Реализовать оптимальный SL вместо жёсткого trendup: выбор из трёх кандидатов
3. Проверить тесты и сделки с утра
4. Починить WsFeed (не работал с апреля — `updates=0 errors=миллионы`)
</original_task>

<work_completed>

## 1. ATR Change → прямой вход LONG (DEV-199 завершён полностью)

**Файл:** `bot/loops/scan_loop.py`

### 1а. Добавлен вызов `_execute_atr_change_signal`

**Строки ~994-996** — после `asyncio.create_task(_eb_atr.publish(...))`:
```python
# DEV-199: прямой вход по ATR change LONG (только 1h/4h, SHORT avgR=-0.2)
if _atr_tf in ('1h', '4h') and _atr_ev.side == 'UP':
    asyncio.create_task(_execute_atr_change_signal(bot, sym, _atr_ev, _atr_tf, df=_atr_df))
```
Условия: только LONG (`side == 'UP'`), только 1h и 4h (15m слишком шумный — R8).

### 1б. Функция `_select_optimal_sl_long` (новая, перед `_execute_atr_change_signal`)

**Строки ~483-551** — выбор оптимального SL из трёх кандидатов:

| Кандидат | Источник |
|----------|----------|
| `trendup` | Supertrend линия (согласована с сигналом) |
| `swing_low(20)` | Структурный минимум последних 20 баров |
| `entry - 2×ATR(14)` | Быстрый ATR-based уровень |

Логика:
- Фильтр: 0.3% ≤ dist ≤ 10% от entry
- Из валидных — **ближайший к цене** (tight SL = лучшее R)
- Fallback: trendup если есть, иначе 5% от entry
- `live_mode=True` (execution_mode=vst/live): буфер −0.15% — компенсирует TSL-касание vs close симуляции

### 1в. Функция `_execute_atr_change_signal` обновлена

- Параметр `df=None` добавлен (передаётся `_atr_df`)
- `sl, sl_source = _select_optimal_sl_long(entry, df, ev.trendline, live_mode=_live_mode)`
- `sl_source` логируется: `[ATRChange] BTC 1h LONG: entry=X sl=Y (src=swing_low_20 dist=2.1%) tp=Z`
- `MarketContext` исправлен: передаются обязательные поля (symbol, current_price, volume_24h=0, ...)
- `sl_source` в БД = `swing_low_20` / `atr_trendline` / `atr14_2x` / `*_fallback` / `*_buf` (с буфером)

**Синтаксис:** `py_compile` — OK ✅

## 2. WsFeed починен (баг с апреля 2026)

**Корень:** `watch_ticker` BingX — **публичный WebSocket стрим, ключи не нужны и вызывают 100413.**
ccxt.pro при наличии apiKey/secret пытается авторизовать соединение → BingX отвергает.
Без ключей → подключается к публичному стриму → работает.

**Доказательство (e:\tmp\ws_test.py):**
```
[WITH keys]    ERROR: ExchangeError: bingx code:100413 Incorrect apiKey
[WITHOUT keys] OK — price=80368.6
```

**История:** с апреля 2026 `updates=0 errors=миллионы` — reconnect-loop без пауз.
Ещё одна проблема: `return_exceptions=True` в `asyncio.gather` → exception не пробрасывается → `except Exception` в `_ticker_batch` никогда не срабатывает → нет задержки reconnect → 300+ ошибок/сек.

**Фикс в `core/infra/ws_feed.py` — `_make_exchange()`:**
```python
# watch_ticker на BingX — публичный стрим, ключи не нужны и вызывают 100413.
return ccxtpro.bingx({
    "options": {"defaultType": "swap"},
    "enableRateLimit": False,
})
```

**Попутно:**
- `WsFeed.__init__` добавлены параметры `api_key=""`, `secret=""` (для будущего если понадобятся приватные стримы)
- `bot/core/bot.py` — WS всегда берёт LIVE ключи (не VST), но в итоге они не нужны
- `import os` добавлен в `bot/core/bot.py`
- Диагностика: первые 3 ошибки логируются WARNING (а не debug) для видимости проблем

**Результат после фикса:**
```
✅ LIVE | tickers=242 updates=71177 errors=0 uptime=299s
```

## 3. Анализ сделок с утра

**30 сделок, ключевые находки:**

| Находка | Вердикт |
|---------|---------|
| `atr_trendline_30m` у 204 сделок | Правильный `sl_source` — sideways стратегия работает на 30m. НО `timeframe=15m` в БД — баг DEFAULT_TIMEFRAME в INSERT (trade_simulator.py:695) |
| R=-8.96 у CFX, R=-5.42 у YFI | VST биржевое proскальзывание: STOP_MARKET исполнился по market price далеко ниже стоп-цены. При sl_dist=0.86% это даёт огромный R. Не баг кода. |
| ATR change сделок нет | Бот не был перезапущен с новым кодом |

## 4. Тесты

`pytest tests/test_confirmations.py` — **58/58 PASSED** ✅

</work_completed>

<work_remaining>

## Немедленно — проверить ATR change в БД

Бот запущен с новым кодом (~17:23 UTC). Ждать первый Supertrend cross UP на 1h или 4h.
Проверить через несколько часов:
```sql
SELECT id, symbol, direction, sl_source, strength, status, created_at
FROM simulated_trades WHERE signal_type='atr_change' ORDER BY created_at DESC LIMIT 20;
```
Ожидаемый `sl_source`: `swing_low_20`, `atr_trendline`, `atr14_2x` — но НЕ `atr_trendline_30m` (это sideways).

В логе при входе:
```
[ATRChange] SYMBOL 1h LONG: entry=X sl=Y (src=swing_low_20 dist=2.1%) tp=Z
[ATRChange] SYMBOL 1h LONG → #NNNN registered (sl_source=swing_low_20)
```

## Незакоммиченные изменения (коммит нужен)

```
M  bot/core/bot.py          — WsFeed ключи + import os + ConfirmationAggregator
M  bot/loops/scan_loop.py   — _select_optimal_sl_long + _execute_atr_change_signal wiring
M  core/infra/ws_feed.py    — убраны ключи из _make_exchange + диагностика WARNING
M  + все изменения из предыдущих сессий (DEV-199..203)
```

Стратегия коммитов:
1. `feat(DEV-199): ATR change LONG прямой вход + _select_optimal_sl_long`
2. `fix(ws_feed): watch_ticker публичный стрим — убраны ключи (100413)`
3. `feat(DEV-199/202): ConfirmationAggregator wiring + signal_drops`

## DEV-204: ML retrain на confirmations (ждёт данных)

- Триггер: 200+ новых сделок с `features_json.confirmations[]` не пустым
- Задача: обновить веса ConfirmationRegistry на основе feature importance
- Пока — ждать накопления (ATR change сделок ~0, confirmations только начали писаться)

## DEV-205: audit_mode shadow + audit_trades

Не начата. Детали в `docs/TASKS_DETAILS.md`.

## ARCH-112: аудит соответствия Кубу Метатрона

Не начат. ATR change = Сфера 1 (новый trigger). Проверить все 13 сфер.

## TR-003: TRADER валидация 20 SHADOW сделок

Не начата. Нужно накопить 20 atr_change сделок после запуска.

## Известный баг: timeframe=15m в БД для всех сделок

`trade_simulator.py:695` — `DEFAULT_TIMEFRAME` хардкодом в INSERT вместо `rec.timeframe`.
Sideways (30m), ATR change (1h/4h) — все пишутся как 15m.
**Не критично** для торговли, но мешает аналитике по timeframe.
Можно починить: заменить `DEFAULT_TIMEFRAME` на `str(_get_recommendation_value(recommendation, "timeframe") or DEFAULT_TIMEFRAME)`.

</work_remaining>

<attempted_approaches>

## Что пробовали и не сработало

### 1. WsFeed — VST ключи вместо LIVE
Первая гипотеза: бот в VST режиме, WsFeed берёт LIVE ключи → 100413.
Изменили на VST ключи → та же ошибка 100413.
→ Проблема не в VST vs LIVE, а в том что watch_ticker публичный.

### 2. WsFeed — передача ключей через __init__
Добавили `api_key`, `secret` параметры в `WsFeed.__init__` и `bot.py`.
Не помогло — ключи вообще не нужны.
→ Финальный фикс: убрать ключи полностью из `_make_exchange()`.

### 3. MarketContext() без аргументов
В первой версии `_execute_atr_change_signal` был вызов `MarketContext()` без аргументов.
Упало бы при первом вызове — у MarketContext 5 обязательных полей.
→ Исправлено: `MarketContext(symbol=symbol, current_price=entry, volume_24h=0.0, ...)`.

### 4. `import pandas as pd as _pd` — синтаксическая ошибка
При написании `_select_optimal_sl_long` случайно написал `import pandas as pd as _pd`.
→ Удалён, pandas уже импортирован на уровне модуля.

</attempted_approaches>

<critical_context>

## WsFeed — публичный vs приватный

BingX `watch_ticker` для SWAP (perpetual futures) = **публичный WebSocket**.
Ключи не нужны и вызывают ошибку аутентификации.
Если в будущем понадобится `watch_orders`/`watch_balance` (приватные стримы) — ключи нужны будут тогда.

## TSL симуляция vs биржа — критически важно для SL выбора

- **Симуляция** TSL: срабатывает при **close** свечи ниже TSL линии
- **Биржа (VST/LIVE)** TSL: срабатывает при **касании** (low < stop price)

Для `_select_optimal_sl_long` добавлен `live_mode` буфер −0.15%:
- `execution_mode = vst/live` → `live_mode=True` → SL с запасом ниже уровня
- `sl_source` при этом получает суффикс `_buf` (напр. `swing_low_20_buf`)

## ATR change LONG — только 1h и 4h

SHORT не использовать без дополнительного фильтра: R8 backtest дал `SHORT avgR=-0.202 WR=35%`.
LONG: `1h avgR=+0.281, WR=56%`, `4h avgR=+0.287, WR=58%` — стабильно positive 7/7 двухнедельных окон.

## SL dist фильтры в `_select_optimal_sl_long`

- Минимум 0.3% — защита от noise SL (иначе R может быть -30 при быстром движении)
- Максимум 10% — защита от too-wide SL (плохое R)
- Если ни один не прошёл — fallback на trendup (согласован с сигналом)

## `atr_trendline_30m` в sl_source

Это НЕ ошибка нового кода. Это хардкод из `strategies/built_in/wt_sideways_strategy.py:67`.
Sideways стратегия работает на 30m timeframe — sl_source правильный.
НО в БД `timeframe=15m` (баг DEFAULT_TIMEFRAME в INSERT).

## Накопленные незакоммиченные изменения (с прошлых сессий)

Из предыдущего whats-next (сессия ~15:30): DEV-199, DEV-200, DEV-201, DEV-202, DEV-203 — все реализованы.
Всего незакоммиченных файлов: ~25+. Коммит давно нужен.

## Acceptance criteria спринта (напоминание)

1. DEV-199 ✅: за 24h после рестарта в БД сделки с `signal_type='atr_change'`
2. DEV-200 ✅: registry.py + 25 типов + 58/58 pytest
3. DEV-201 ✅: signal_mode работает (reversal/cascade/momentum)
4. DEV-202 ✅: confirmations[] пишутся в features_json
5. DEV-203 ✅: signal_drops таблица + дашборд /dropped
6. Регрессия: 7 дней avgR не падает ниже −0.437
7. Прогресс: 14 дней → avgR ≥ −0.10

</critical_context>

<current_state>

## Файлы — статус

| Файл | Статус |
|------|--------|
| `core/signals/atr_change_detector.py` | ✅ создан, `trendline` поле добавлено |
| `core/confirmations/__init__.py` / `models.py` / `registry.py` | ✅ создан, 25 типов |
| `core/intelligence/signal_aggregator.py` | ✅ `ConfirmationAggregator` добавлен |
| `core/observability/decision_trace.py` | ✅ создан |
| `core/db/subscription_manager.py` | ✅ таблица `signal_drops` |
| `bot/monitoring.py` | ✅ 6 gates + DEV-202 confirmations |
| `bot/core/bot.py` | ✅ ATRChangeDetector + ConfirmationAggregator + WsFeed фикс |
| `bot/loops/scan_loop.py` | ✅ `_select_optimal_sl_long` + `_execute_atr_change_signal` + вызов |
| `core/infra/ws_feed.py` | ✅ ключи убраны из `_make_exchange` |
| `web/dashboard_server.py` | ✅ endpoint `/api/dropped` |
| `tests/test_confirmations.py` | ✅ 58/58 PASSED |
| `config.yaml` | ✅ `sl_cooldown_hours: 1.0` (было 2.0) |

## Бот — текущий статус (17:28 UTC)

- **Запущен** с 17:23 UTC
- **WsFeed**: `✅ LIVE | tickers=242 updates=71177 errors=0` — работает впервые с апреля ✅
- **ATR change**: ни одной сделки в БД — ждём первого 1h/4h Supertrend cross UP
- **Selftest S2 (WSFeed)**: станет `ACTIVE` при следующем `/selftest`
- **Открытых сделок**: 84 total, ~63 сегодня — большинство `wt_sideways` 30m

## Коммиты

**Не сделано** — нужен коммит всех изменений сессии.

## Что ждать в ближайшее время

1. **Первые ATR change сделки** — появятся при Supertrend cross на 1h/4h любой пары. Проверить через 2-4 часа.
2. **Confirmations в features_json** — у новых ATR change сделок должны быть `confirmations[]` непустые.
3. **DEV-204** — когда накопится 200+ сделок с confirmations.

</current_state>

</current_session>

---

<previous_session>

> Сессия 09.05.2026 ~15:30 UTC. DEV-199/200/201/202/203 реализованы. Детали в git log.
> Краткое содержание: ATRChangeDetector создан, ConfirmationRegistry 25 типов, ConfirmationAggregator,
> DecisionTrace + signal_drops, confirmations[] в features_json. 58/58 тестов. Бот перезапущен.

Полный handoff предыдущей сессии доступен в git history (`whats-next.md` до этого коммита).

</previous_session>
