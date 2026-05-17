# What's Next — Handoff Document

> Последнее обновление: **2026-05-17 ~UTC** (Агент: TRADER/Sonnet).
> Предыдущая запись (09.05 ~17:30 UTC) — в разделе `<previous_session>` ниже.

---

<current_session>

<original_task>
Реализация TR-001: ежедневный Watch List с живыми свечами.

Запрос: расширить `tools/daily_trade_review.py` — топ-N символов из БД, fetch OHLCV (15m/1h/4h)
с BingX, composite PNG (15m/1h/4h), Gemini Vision анализ → вывод в TG + файлы.

Финал сессии: три улучшения к реализованному пайплайну:
1. Числовой TA снимок (wt1/zone/trend) как дополнительный контекст в vision промпт
2. Периодический запуск каждые 4ч через asyncio task в боте
3. Символы из `signal_drops` (последние 4ч) добавить в Watch List
</original_task>

<work_completed>

## 1. Полный rewrite `tools/daily_trade_review.py` (~900 строк)

**Двухфазный Gemini пайплайн:**

**Phase 1 (текст):**
- `fetch_trades(hours)` — SELECT из `simulated_trades`
- `fetch_watchlist_symbols(n)` — топ-N символов (7 дней) + signal_drops (4ч)
- `_fetch_all_ohlcv(symbols, tfs, limit)` — parallel fetch через ccxt.bingx (shared exchange)
- `compute_ta_snapshot(symbol, dfs)` — wt1/wt2/zone/trend по каждому TF
- `call_gemini()` — текстовый дайджест сделок + Watch List TA снимок
- Парсинг `TOP3: SYM1, SYM2, SYM3` из ответа Gemini

**Phase 2 (vision):**
- `build_composite_png(symbol, dfs)` — 3-panel PNG через `chart_builder._render` + PIL склейка
- `call_gemini_vision(png_bytes, symbol, ta_snapshot)` — Gemini Vision анализ с числовым снимком
- TG: фото + отдельное текстовое сообщение (Telegram limit: caption 1024 символа)

**Output:** `memory/last_trade_review.md` + `obsidian/Daily-Review/YYYY-MM-DD.md` + TG

**Запуск при старте бота:** `oko_mtf.py:106` — `[py, "tools/daily_trade_review.py", "--quiet", "--max-age-hours", "18"]`

## 2. Улучшение 1: TA снимок в vision промпт

**Файл:** `tools/daily_trade_review.py`

**Новая функция** `_fmt_ta_snapshot_line(ta_snapshot: dict | None) -> str`:
- Форматирует строку вида: `TA snapshot: 15m wt1=+12.3 zone=~ trend=UP · 1h wt1=-52.1 zone=OS trend=DN · 4h ...`
- Вставляется в vision промпт перед шаблоном через replace: `"Выжимка строго по шаблону."` → `"{snapshot_line}\n\nВыжимка строго по шаблону."`

**`call_gemini_vision`** теперь принимает `ta_snapshot: dict | None = None`

**В `main()`** при vision вызове передаётся snapshot нужного символа:
```python
sym_snapshot = next((s for s in snapshots if s["symbol"] == sym), None)
analysis = call_gemini_vision(png, sym, ta_snapshot=sym_snapshot)
```

## 3. Улучшение 2: Периодический запуск 4ч

**Новый файл:** `bot/loops/watchlist_loop.py`

```python
async def watchlist_loop(_bot) -> None:
    """Каждые 4ч запускает Watch List review → TG."""
    while True:
        await asyncio.sleep(4 * 3600)   # первый запуск через 4ч после старта
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "tools/daily_trade_review.py", "--quiet", ...
        )
        await asyncio.wait_for(proc.communicate(), timeout=300)
```

**`bot/core/bot.py`** — добавлены строки ~354 и ~379:
```python
from bot.loops.watchlist_loop import watchlist_loop
asyncio.create_task(watchlist_loop(self))   # Watch List: каждые 4ч
```

## 4. Улучшение 3: signal_drops в Watch List

**`fetch_watchlist_symbols`** теперь двухэтапный:
1. Топ-N символов из `simulated_trades` за 7 дней (как раньше)
2. +уникальные символы из `signal_drops` за последние 4ч
3. Объединяет, дедуплицирует, возвращает топ-N
4. Graceful fallback если `signal_drops` нет (старые инсталляции)
5. Логирует `[watch] +N символов из signal_drops`

## 5. Ключевые константы (daily_trade_review.py)

```python
WATCHLIST_N = 10
WATCHLIST_TFS = ["15m", "1h", "4h"]
WATCHLIST_OHLCV_LIMIT = 120        # дефолт для 15m/4h
WATCHLIST_TF_LIMITS = {"15m": 120, "1h": 530, "4h": 120}   # 1h = 530 для недельных пивотов
GEMINI_MODEL_PRIMARY = "gemini-2.5-flash"
MAX_OUTPUT_TOKENS = 10000
```

## 6. VISION_PROMPT (финальный формат, ~18 строк)

```
📡 {symbol}
📈 15m [↗/↘/→] · 1h [↗/↘/→] · 4h [↗/↘/→]
〰 WT
  15m [OS/OB/нейтрал] [↑/↓] [крест если есть]
  1h  [...]
  4h  [...]
🏛 Пивоты W: PP · S1/R1 · S2/R2 ← цена выше↑/ниже↓ W:PP
          D: PP · S1/R1 · S2/R2 ← ближайший уровень
🎯 [LONG/SHORT/Ждать: причина]
  Вход: / SL: / TP1: / TP2:
```

## 7. Пример финального вывода в TG (протестировано)

```
📡 TRB/USDT:USDT

📈 15m ↘ DN · 1h ↘ DN · 4h ↘ DN

〰 WT
  15m нейтрал ↓ крест ↓
  1h  OS ↓
  4h  OS ↓

🏛 Пивоты
  W: 20.263 · S1 19.34 · S2 18.463 ← цена ниже ↓ W:PP
  D: 17.45 · S1 17.04 · R1 18.06 ← ближайшая поддержка S1 17.04

🎯 Ждать: подтверждения разворота
  Вход:  17.04 - 17.20
  SL:    16.80 (1.4% за S1)
  TP1:   17.45 (D:PP)
  TP2:   18.06 (D:R1)
```

</work_completed>

<work_remaining>

## Протестировать три улучшения

Запустить тест вручную:
```
cd "e:\MTF BOT\CURSOR\crypto_volume_bot"
python e:\tmp\test_vision.py   # или запустить основной скрипт
python tools/daily_trade_review.py --quiet
```

Проверить в логах/TG:
1. Строка `TA snapshot: 15m wt1=... zone=... trend=...` появляется в консоли перед Gemini Vision вызовом
2. После 4ч работы бота в логах: `[watchlist_loop] старт Watch List review`
3. При наличии signal_drops: `[watch] +N символов из signal_drops`

## TR-003: TRADER валидация ConfirmationRegistry

Статус: ждёт накопления ATR change сделок.
Нужно: ≥30 composite сделок с `features_json.confirmations[]`.
Блокер: сделок с `atr_change` пока мало (бот работает с 17.05).

Как проверить:
```sql
SELECT id, symbol, signal_type, direction, R_multiple, created_at,
       json_extract(features_json, '$.confirmations') as confs
FROM simulated_trades
WHERE signal_type='atr_change' OR json_extract(features_json, '$.confirmations') IS NOT NULL
ORDER BY created_at DESC LIMIT 30;
```

## DEV-200: ConfirmationRegistry — главный блокер спринта

Статус по TASKS.md: 🔴 срочно. `core/confirmations/registry.py` существует, тесты 58/58 PASSED.
Acceptance: каждый детектор публикует Confirmation events.
Следующий шаг DEV — проверить что все 25 типов реально публикуются в live данных.

## DEV-201: SignalAggregator v2

`strength = Σ weight × confidence` — заменить хардкод формулу.
Проверить что `signal_mode` разнообразен у новых сделок.

## DEV-188: pivot_reversal SHORT TREND_DOWN

93 сделки avgR=−0.77, эффект −72R/10дн. Ещё не исправлено.
Нужно: проверка реального касания (wick через уровень) + объём.

## ARCH-95: Глобальное расследование "почему торгуем в минус"

6 аудит-скриптов (H1..H7). Пока не запущены.

## Коммиты (давно нужны)

Незакоммиченных файлов 25+. Стратегия:
1. `feat(TR-001): Watch List pipeline — composite PNG + Gemini Vision + периодический запуск 4ч`
2. `feat(TR-001): signal_drops в Watch List + TA снимок в vision промпт`

</work_remaining>

<attempted_approaches>

## Что пробовали и не сработало (в ходе разработки daily_trade_review.py)

### 1. 30 параллельных ccxt экземпляров → RequestTimeout
Каждый `ccxt.bingx()` при инициализации загружает `/contracts`. 30 параллельных → rate limit → timeout.
→ Фикс: один shared `exch = ccxt_async.bingx()` + `await exch.load_markets()` один раз + `Semaphore(5)`.

### 2. `Part.from_text()` без keyword → TypeError
Новая google-genai SDK требует keyword аргумент.
→ Фикс: `Part.from_text(text=VISION_PROMPT.format(...))` вместо `Part.from_text(VISION_PROMPT...)`.

### 3. TG caption обрезается на 1024 символах
Анализ (400+ символов) обрывался на середине предложения.
→ Фикс: `send_tg_photo(png, short_caption)` + отдельный `send_tg_text(full_analysis, parse_mode=None)`.

### 4. Markdown `**bold**` отображается как сырой текст
При `parse_mode=None` теги видны пользователю.
→ Фикс: в system_instruction добавлено "БЕЗ markdown разметки — никаких **, *, _, #".

### 5. Недельные пивоты "отсутствуют на графике"
120 свечей 1h = 5 дней. `_calc_pivot_levels` требует 3+ недели = 530 свечей.
→ Фикс: `WATCHLIST_TF_LIMITS = {"15m": 120, "1h": 530, "4h": 120}`.

### 6. MAX_TOKENS обрезка при `max_output_tokens=3000`
Gemini 2.5 Flash тратит thinking tokens на внутренние рассуждения — на output почти ничего.
→ Фикс: `ThinkingConfig(thinking_budget=0)`.

### 7. Слишком длинный анализ (2582 символа)
Структурированный, но избыточный — пользователю нужна выжимка.
→ VISION_PROMPT переписан в компактный шаблон с emoji, ограничен 18 строками.

</attempted_approaches>

<critical_context>

## WATCHLIST_TF_LIMITS — критически важно

`"1h": 530` свечей обязательно — `_calc_pivot_levels` в `chart_builder.py` требует 3+ полных недели
для вычисления недельных пивотов. Меньше → W: PP/S1/R1 просто не появятся на графике.
`"15m": 120`, `"4h": 120` — достаточно для отображения последних ~1-2 дней / ~3 недели соотв.

## ThinkingConfig(thinking_budget=0) — обязательно

Gemini 2.5 Flash имеет внутренний thinking budget. При `max_output_tokens=2000` без отключения
thinking — бюджет тратится на reasoning, на output почти ничего. Результат: обрезка на 50-100 символах.
`thinking_budget=0` отключает это, весь лимит идёт на output.

## send_tg_photo + send_tg_text раздельно

Telegram API: `sendPhoto` caption ≤ 1024 символа. Анализ Vision ~380-500 символов.
Сейчас: caption = короткий заголовок `📡 *SYMBOL* — 15m / 1h / 4h`, анализ — отдельный sendMessage.
`parse_mode=None` для текста vision — Gemini instructed не писать markdown.

## watchlist_loop — первый запуск через 4ч

При старте бота `_spawn_llm_background_jobs()` уже запускает daily_trade_review.py.
Поэтому `watchlist_loop` начинает с `await asyncio.sleep(4 * 3600)` — нет дублирования.

## signal_drops таблица — graceful fallback

`fetch_watchlist_symbols` оборачивает signal_drops запрос в `try/except` — таблица появилась
только после DEV-203 (09.05.2026). Старые инсталляции без неё не сломаются.

## build_composite_png — импорт из core/ui/chart_builder.py

Функции `_calculate_wt`, `_render`, `_calc_pivot_levels` — protected (underscore).
Используются напрямую т.к. публичный API `build_signal_chart` async и требует trade объект.
Если chart_builder.py изменится — нужно проверить эти 3 функции.

## Паттерн watchlist_loop по образцу obsidian_loop

Оба в `bot/loops/`, оба используют `asyncio.create_subprocess_exec`, timeout для subprocess.
`obsidian_loop` запускается в 00:05 UTC (фиксированное время), `watchlist_loop` — через 4ч интервал.

</critical_context>

<current_state>

## Файлы — статус

| Файл | Статус |
|------|--------|
| `tools/daily_trade_review.py` | ✅ реализован + 3 улучшения (сессия 17.05) |
| `bot/loops/watchlist_loop.py` | ✅ создан (новый файл) |
| `bot/core/bot.py` | ✅ watchlist_loop подключён |
| `core/signals/atr_change_detector.py` | ✅ (из предыдущей сессии) |
| `core/confirmations/registry.py` | ✅ (из предыдущей сессии) |
| `core/observability/decision_trace.py` | ✅ (из предыдущей сессии) |
| `bot/loops/scan_loop.py` | ✅ (из предыдущей сессии) |

## Пайплайн — статус

| Компонент | Статус |
|-----------|--------|
| Fetch OHLCV (ccxt shared + Semaphore) | ✅ протестировано, работает |
| TA snapshot (wt1/zone/trend) | ✅ протестировано |
| Composite PNG (PIL склейка 3 панелей) | ✅ протестировано |
| Gemini Vision анализ (~380 символов) | ✅ протестировано, качество норм |
| TG: фото + текст раздельно | ✅ протестировано |
| TA snapshot в vision промпт | ✅ реализовано (17.05, не протестировано в TG) |
| Периодический запуск 4ч | ✅ реализовано (17.05, не протестировано — нужен рестарт бота) |
| signal_drops в Watch List | ✅ реализовано (17.05, не протестировано) |

## Блокирующие задачи спринта

- **DEV-200** 🔴: ConfirmationRegistry — основной блокер спринта
- **DEV-201** 🔴: SignalAggregator v2
- **TR-003** 🟡: заблокирована — ждёт накопления ATR change сделок + фикс SL-выбора

## Коммиты

Незакоммиченных изменений: 25+ файлов (накопилось за несколько сессий 09.05–17.05).
Нужно сделать 2 коммита (см. `<work_remaining>`).

## Что нужно после рестарта бота

1. Через несколько минут: `[watchlist_loop] запланирован через 4 ч` в логах
2. Через 4ч: автоматический запуск Watch List → TG получит фото + анализ
3. Проверить signal_drops логирование: `[watch] +N символов из signal_drops`

</current_state>

</current_session>

---

<previous_session>

> Сессия 09.05.2026 ~17:30 UTC. ATR Change прямой вход + _select_optimal_sl_long + WsFeed фикс.
>
> Краткое: wiring `_execute_atr_change_signal` в scan_loop, SL из 3 кандидатов (trendup/swing_low_20/atr14_2x),
> WsFeed починен (watch_ticker публичный стрим — ключи вызывали 100413), 58/58 тестов.
> Бот перезапущен в 17:23 UTC. WsFeed: tickers=242 updates=71177 errors=0.

Полный handoff предыдущей сессии доступен в git history (`whats-next.md` до этого коммита).

</previous_session>
