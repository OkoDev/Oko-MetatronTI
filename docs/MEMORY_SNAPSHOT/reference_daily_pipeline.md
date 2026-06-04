---
name: reference-daily-pipeline
description: Daily trade review + log digest + post-mortem — автозапуск при старте бота через Gemini
metadata: 
  node_type: memory
  type: reference
  originSessionId: 5125b728-fb4c-47f5-b019-176f112b7ee3
---

# Daily Pipeline (Gemini автоанализ при старте бота)

При каждом старте `bot_with_subscriptions.py` фоном (detached, не блокирует бот)
запускаются 4 скрипта если их output старше 6-18 часов.

## Скрипты

### 1. `tools/daily_trade_review.py`
**Что:** разбор закрытых сделок за последние 24ч из `subscriptions.db`.
**Output:**
- `memory/last_trade_review.md` — Claude читает
- `obsidian/Daily-Review/YYYY-MM-DD-review.md` — Obsidian

**Структура:** Главный вывод → Сводка → По signal_type → По regime → По direction → По strategy_type → TOP-3 winners → TOP-3 losers → Гипотезы → Что предложить TRADER/DEV.

**Ручной запуск:**
```powershell
$PY = "C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe"
& $PY tools/daily_trade_review.py             # за 24ч
& $PY tools/daily_trade_review.py --hours 12  # за 12ч
```

### 2. `tools/trade_postmortem.py`
**Что:** мини-разбор каждой сделки с `R < -2.0` (или другой threshold).
**Output:** `obsidian/Trades/<id>-<symbol>.md`

**Структура:** Краткая суть → Контекст входа → Что планировалось → Что случилось →
decision_trace/confirmations → **Главный диагноз** → Урок → Связано.

**Ручной запуск:**
```powershell
& $PY tools/trade_postmortem.py                    # все R<-2 за 24ч
& $PY tools/trade_postmortem.py --trade-id 12117   # конкретная сделка
& $PY tools/trade_postmortem.py --hours 48 --threshold -1.5
```

### 3. `tools/daily_log_digest.py`
**Что:** сжимает 1 ГБ `crypto_bot.log` в 5-10 строк.
**Стратегия:**
- Tail последних 10 000 строк (контекст)
- Сканирует **все WARN/ERR/CRITICAL** из последних 50 МБ лога
- Дедуплицирует одинаковые строки (timestamp/symbol → `<TIMESTAMP>`/`<SYMBOL>`)
- Top-30 уникальных по count → Gemini

**Output:**
- `memory/log_digest.md`
- `obsidian/Logs/YYYY-MM-DD-digest.md`

**Структура:** TOP-5 ошибок с counts → Подозрительные паттерны → Тренды → Что предложить DEV → Что ОК.

### 4. `tools/context_brief.py` (уже было)
Backup-запуск brief'а если SessionStart hook не сработал.

## Hook в боте

`bot_with_subscriptions.py:_spawn_llm_background_jobs()` — запускает все 4 скрипта
через `subprocess.Popen` с DETACHED_PROCESS флагом (Windows). Бот стартует параллельно.

Логи фоновых джоб: `logs/llm_hooks.log`.

## Лимиты Gemini

При текущей нагрузке: ~15-35 запросов/день к Gemini 2.5 Flash (лимит 250 RPD).
**Запас 7-15×.** Если расширяться — подключить OpenRouter / Cerebras / GitHub Models.

## Pattern: где использовать что

| Задача | Скрипт |
|---|---|
| «Что было вчера в торговле?» | `daily_trade_review` → читай `memory/last_trade_review.md` |
| «Почему #X сделка убыточна?» | `trade_postmortem --trade-id X` → читай `obsidian/Trades/X-*.md` |
| «Что в логах за 24ч?» | `daily_log_digest` → читай `memory/log_digest.md` |
| «Что изменилось за 7 дней?» | `context_brief` → читай `memory/session_brief.md` |
| «Вся история проекта» | `project_timeline` → читай `memory/project_timeline.md` |
| «История задачи DEV-X» | `obsidian_enrich DEV-X --force` → читай `obsidian/Tasks/DEV-X.md` |
| «Резюме файла X» | `llm_ask "..." --file X` |

## Связанные memory
- [[reference-llm-delegator]] — общий llm_ask.py
- [[reference-context-pipeline]] — A/B/C уровни памяти проекта
