# What's Next — Handoff Document

> Последнее обновление: **2026-05-18 ~00:00 UTC** (Агент: TRADER/Sonnet).
> Предыдущая запись (17.05 вечер) — в разделе `<previous_session>` ниже.

---

<current_session>

<original_task>
Аналитическая сессия (короткая): вопросы по работе watchlist + пивоты TAIKO/USDT.
Код не менялся — только анализ и запись в DISCUSSION.md.
</original_task>

<work_completed>

## 1. Разобрали механику action=WATCH

- `action=WATCH` → **добавляется в SignalWatchList**, не теряется ([monitoring.py:1230-1252](bot/monitoring.py))
- `pivot_level = recommendation.stop_loss` — граница аннулирования идеи
- Эскалация WATCH→BUY: score+5, новая дивергенция, MTF NEUTRAL→совпал
- Пробой pivot_level вниз (LONG) → запись удаляется. Пробой вверх → `_handle_wl_breach_entry`
- TTL 4 часа, `cleanup_expired()` каждый цикл

## 2. Реальные пивоты TAIKO/USDT (через PivotCalculatorFixed)

Цена 0.11000 (17.05 ~19:30 UTC):

| Уровень | Цена | Расстояние |
|---|---|---|
| D:PP | 0.11007 | +0.06% ← цена здесь |
| D:R1 | 0.11160 | +1.46% |
| W:source_low | 0.11220 | +2.00% |
| D:S1 | 0.10766 | -2.12% |
| W:S2 | 0.10680 | -2.91% |
| W:PP | 0.12180 | +10.73% |

**Конфлюенции:** W:S1/D:R3=0.116 (0.20%), D:R1/W:source_low=0.112 (0.53%), W:S2/D:S1=0.107 (0.80%)

## 3. Применили таблицу WPP-магнита к TAIKO

Дистанция до W:PP = 9.7% → строка >5% в таблице. Вероятность <2%, avgR при промахе ≈-1.5R.
→ W:PP как TP нельзя. TP только D:R1/D:R2 (1.5-4.2% от входа).

## 4. Записано в DISCUSSION.md

Блок `[17.05.2026] TRADER — TAIKO/USDT: анализ пивотов и позиции относительно WPP`.

</work_completed>

<work_remaining>

## 🔴 ПРИОРИТЕТ 1: Три действия роя (ждут 24ч наблюдения с момента pivot_cache fix)

Нужно проверить логи: появились ли FVG+pivot confluence бонусы?
```sql
SELECT signal_type, direction, COUNT(*), AVG(R_multiple)
FROM simulated_trades
WHERE created_at > datetime('now', '-24 hours')
GROUP BY signal_type, direction;
```

**Три действия (утверждены 5/5):**
1. `pivot_reversal: min_strength: 100` или `enabled: false` — avgR<0 везде n=3136
2. `atr_change LONG = off` + SHORT только в TREND_DOWN
3. `confluence W_UP + D_above_PP: strength += 20`

## 🔴 ПРИОРИТЕТ 2: Этап 1.Е TradeRouter

Cleanup дублей gates в `trade_simulator.py`. **Не ранее 18.05.2026 ~12:39 UTC** (48ч стабильности).

## 🟡 Коммиты (36+ файлов)

```
fix(pivot_cache): get(symbol_1W) в 4 местах — FVG+pivot confluence fix
fix(DEV-215): datetime timezone + market_stress + sl_cooldown + monitoring
fix(DEV-213): wt_sideways off (-131R/24ч)
fix(DEV-214): swing SL в pivot_reversal
feat(TradeRouter): этапы 1.А–1.Г
feat(TR-001): Watch List pipeline + Gemini Vision + watchlist_loop 4ч
```

## 🟡 Открытые atr_change LONG позиции

24 позиции. Mistral: закрыть → ~17R. Nemotron: дать доживать. Решение пользователя не принято.

## 🟢 TAIKO watchlist

Пара добавлена в WL с pivot_level=0.10827, TTL 4ч. Проверить эскалировала ли.

</work_remaining>

<critical_context>

## Ключевые числа (аудит)

| Сигнал | n | avgR | Решение |
|---|---|---|---|
| pivot_reversal (все) | 3136 | -0.168..-1.584 | ОТКЛЮЧИТЬ |
| atr_change LONG | 80 | -0.711 WR=8.8% | ОТКЛЮЧИТЬ |
| atr_change SHORT | 87 | +0.302 WR=63.2% | ТОЛЬКО TREND_DOWN |
| atr_change SHORT @ W:S1 | ~10 | +0.637 WR=80% | PREMIUM бонус |
| confluence W_UP+D_above_PP | 888 | +0.978 WR=32.7% | УСИЛИТЬ +20 |

## WPP-магнит (таблица из DISCUSSION)

TP на W:PP валиден **только если entry в зоне 0-3% от WPP**.
Дальше 3% → вероятность <8%, EV отрицательный.

## pivot_cache fix (17.05)

До фикса FVG+pivot confluence НИКОГДА не применялся (баг в 4 местах `pivot_reversal.py`).
Все исторические avgR confluence занижены — данные ненадёжны до накопления post-fix.

</critical_context>

</current_session>

---

---

<current_session>

<original_task>
Расследование пропущенных трейдов (FHE +7.9%, KAITO +14%) + "Парадокс дна" + два раунда роя.
Финал: 24ч наблюдения из-за pivot_cache bug (FVG+pivot confluence начинает работать впервые).
</original_task>

<work_completed>

## 1. Расследованы root cause пропущенных трейдов

**FHE +7.9%:** новый листинг, 111 баров < 160 MIN_BARS для divergence → scan_loop пропустил пару. Не баг.

**KAITO +14%:** TriggerLoop видел PIVOT_TOUCH → None (pre_collected=False) → далее zone_enter_os с MTF SHORT 3/3 + HIGH_VOL → DEV-44 HARD BLOCK.

**register_returned_none (88 случаев/24ч):** DEV-44 HIGH_VOL HARD block. Корректное поведение.

## 2. "Парадокс дна" (системная проблема)

У любого дна (W:S2/S1) контекст ВСЕГДА медвежий → тренд-следящий бот не входит.
KAITO: отбой от W:S2 +14%. FHE: аналогично.

## 3. pivot_cache bug исправлен

4 места: `pivot_cache.get(symbol)` → `pivot_cache.get(f"{symbol}_1W")`.
**FVG+pivot confluence bonus НИКОГДА не работал до сегодня.**
После рестарта бонус начнёт применяться.

## 4. Два раунда роя

**Раунд 1:** HIGH_VOL exception для W:S1/S2 + WT OS → консенсус 5/5 (shadow 2 недели).

**Раунд 2** (с данными DISCUSSION.md — отменяет раунд 1):
- pivot_reversal убыточен везде n=3136 (avgR -0.168 до -1.584)
- atr_change LONG = -56.9R/7дн WR=8.8% = катастрофа
- atr_change SHORT = +26.3R WR=63.2%, @ W:S1 = WR=80% PREMIUM
- confluence W_UP+D_above_PP = avgR+0.978 n=888 = лучший сигнал бота
- Консенсус 5/5: три действия (не реализованы — ждут 24ч)

</work_completed>

<work_remaining>

## 🔴 ПРИОРИТЕТ 1: Наблюдение 24ч (отсчёт с рестарта бота после pivot_cache fix)

**Что наблюдать:**
- Появились ли `FVG+pivot confluence` бонусы в логах? (раньше никогда не применялись)
- Как изменился strength у confluence сигналов?
- atr_change LONG/SHORT статистика за сутки

**Как проверить:**
```sql
SELECT signal_type, direction, COUNT(*), AVG(R_multiple), AVG(strength)
FROM simulated_trades
WHERE created_at > datetime('now', '-24 hours')
GROUP BY signal_type, direction;
```

## 🔴 ПРИОРИТЕТ 2: Три действия роя (после 24ч данных)

**Действие 1:** pivot_reversal отключить
```yaml
# config.yaml
# Вариант А (мягко): min_strength: 100 (никогда не достигается)
# Вариант Б (чисто): enabled: false
```
**Данные:** n=3136, avgR<0 во ВСЕХ 4 контекстах. DEV-188 в TASKS.md.

**Действие 2:** atr_change LONG = off
```python
# В config.yaml или code: блок на atr_change LONG
# SHORT только в TREND_DOWN режиме
# Бонус: near_S1 (±1% от W:S1) → strength += 15
```
**Данные:** LONG -56.9R WR=8.8% / SHORT +26.3R WR=63.2% за 7 дней.

**Действие 3:** confluence W_UP + D_above_PP boost
```python
# В core/trading_intelligence.py или confluence detector:
# if weekly_bias == UP and price > daily_pp:
#     strength += 20
```
**Данные:** avgR=+0.978 n=888 WR=32.7% — ЛУЧШИЙ сигнал бота.

## 🟡 Решить: 24 открытых atr_change LONG

Mistral: закрыть → сохранить ~17R.
Nemotron: дать доживать, новые LONG блокировать.
Пользователь должен принять решение.

## 🟡 TAIKO BUY порог

str=94 MTF=68% WATCH. Рассмотреть снижение MTF порога с 70% до 65%.
A/B тест: shadow режим с порогом 65% на 7 дней.

## 🟡 Коммиты (37+ файлов накопилось)

Группировать по задачам:
1. `fix(pivot_cache): get(symbol_1W) в 4 местах — FVG+pivot confluence fix`
2. `fix(DEV-215): datetime timezone + market_stress + sl_cooldown + monitoring`
3. `fix(DEV-213): wt_sideways off (-131R/24ч)`
4. `fix(DEV-214): swing SL в pivot_reversal`
5. `feat(TradeRouter): этапы 1.А–1.Г`
6. `feat(TR-001): Watch List pipeline + vision + периодический запуск`

## 🟢 DEV-200/201: ConfirmationRegistry в live данных

Проверить что все 25 типов confirmations публикуются:
```sql
SELECT json_extract(features_json, '$.confirmations') FROM simulated_trades
WHERE created_at > datetime('now', '-24 hours') LIMIT 10;
```

</work_remaining>

<critical_context>

## Ключевые числа (проверены на данных БД)

| Сигнал | n | avgR | Решение |
|--------|---|------|---------|
| pivot_reversal (все контексты) | 3136 | -0.168 до -1.584 | ОТКЛЮЧИТЬ |
| atr_change LONG | 80 | -0.711 WR=8.8% | ОТКЛЮЧИТЬ |
| atr_change SHORT | 87 | +0.302 WR=63.2% | ОСТАВИТЬ ТОЛЬКО TREND_DOWN |
| atr_change SHORT @ W:S1 | ~10 | +0.637 WR=80% | PREMIUM → бонус |
| confluence W_UP+D_above_PP | 888 | +0.978 WR=32.7% | УСИЛИТЬ +20 |

## pivot_cache fix — важно для интерпретации данных

До сегодняшнего дня `FVG+pivot confluence` НИКОГДА не применялся (баг в 4 местах).
Все исторические данные по confluence — БЕЗ этого бонуса.
После рестарта с фиксом → новые сигналы начнут получать бонус.
**Это значит: исторические avgR confluence могут быть занижены.**

## DEV-44 HIGH_VOL HARD block — намеренно

`trading.blocked_regimes: [HIGH_VOL]` в config.yaml (строка 153).
88 случаев register_returned_none/24ч = корректное поведение, не утечка.
"Парадокс дна" — системная ограниченность тренд-следящего бота.
Пока нет решения без данных о качестве W:S1/S2 сигналов в HIGH_VOL.

## Следующий старт сессии

1. Прочитать `memory/current_state.md`
2. Проверить логи после рестарта: pivot_cache fix применился?
3. SQL статистика atr_change LONG/SHORT за 24ч
4. Принять решение по трём действиям роя
5. Решить по открытым atr_change LONG (закрыть или нет)

</critical_context>

<current_state>

## Статус бота

- Рестарт нужен для применения pivot_cache fix (4 места исправлены сегодня)
- Если рестарт был: FVG+pivot confluence начал применяться
- Если нет: нужно сделать первым делом

## Незакоммиченное (37+ файлов)

Накопилось за сессии 14.05–17.05. Список в `current_state.md`. Не критично — файлы на диске.

## Ожидаем данные 24ч (с момента рестарта)

Без данных: действия роя не реализуем (pivot_reversal off, atr_change LONG off, confluence boost).

</current_state>

</current_session>

---

<previous_session>

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

> Сессия 09.05–17.05 дневная. Watch List pipeline + TR-001 + swing SL + pivot_cache fix.
>
> Краткое: wiring `_execute_atr_change_signal` в scan_loop, SL из 3 кандидатов (trendup/swing_low_20/atr14_2x),
> WsFeed починен (watch_ticker публичный стрим — ключи вызывали 100413), 58/58 тестов.
> Бот перезапущен в 17:23 UTC. WsFeed: tickers=242 updates=71177 errors=0.

Полный handoff предыдущей сессии доступен в git history (`whats-next.md` до этого коммита).

</previous_session>
