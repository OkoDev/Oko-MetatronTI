<original_task>
Продолжение разработки торгового бота Oko MTF (Telegram + BingX).
Текущая сессия:
1. Проверка открытых сделок в БД
2. "Делай всё что нужно для совершенствования проекта" — свободный карт-бланш
3. Настройка двух Claude-агентов для параллельной работы над проектом
</original_task>

<work_completed>

## Фиксы и улучшения (коммит `bddb51b`)

### 1. conflict_ratio — баг-фикс (core/trading_intelligence.py, строки ~460-477)
**Проблема:** Предыдущий порог 0.15 не исправлял проблему A3.
70 LONG vs 60 SHORT → ratio = abs(70-60)/70 = 0.143 < 0.15 → по-прежнему NEUTRAL.
Даже комментарий в коде описывал ПОЛОМАННОЕ поведение как норму.

**Исправление:** Порог снижен 0.15 → **0.05**:
- ratio < 0.05 → NEUTRAL (почти равные стороны, например 70 vs 68)
- 0.05 ≤ ratio < 0.30 → штраф confidence × (0.6 + ratio), direction сохраняется
- ratio ≥ 0.30 → без штрафа

Теперь: 70 vs 60 = ratio 0.143 → BUY с умеренным штрафом ✅

### 2. RPredictor MIN_SAMPLES (core/r_predictor.py, строка 19)
**Изменение:** 100 → **75**
**Причина:** В БД 84 закрытые сделки с max_R_possible > 0 (достаточно для обучения).
При следующем запуске бота RPredictor автоматически обучится в `_ml_training_loop`.

### 3. Kelly sizing footer в TG-алертах (bot/monitoring.py)
**Добавлено:**
- Функция `_get_kelly_footer(bot)` — на уровне модуля перед `_broadcast_intelligence_alert`
- Кеш 30 минут (`_kelly_stats_cache: dict = {}`) → один SQL-запрос на весь период
- Читает из БД: total, wins (TP+TSL), avg_R
- Вызывает `RPredictor.kelly_fraction(win_rate, avg_r)` → % депозита
- Пустая строка если RPredictor не обучен или avg_r <= 0

**Результат в TG-сообщении при is_actionable=True:**
```
─────────────
💾 Сделка зарегистрирована в симуляторе
📐 Kelly: 12.5% депозита (WR=42%, R̄=1.93)
```

### 4. Настройка двух Claude-агентов

#### Созданные/обновлённые файлы (НЕ закоммичены):
- `.claude-config/agents.md` — обновлён: аккаунты (yogoru / oko.webdev), workflow, правила
- `TASKS.md` — файл координации задач между агентами (Architect / Developer)
- `launch-agent2.bat` — скрипт запуска второго агента без Docker

#### `launch-agent2.bat` (корень проекта) — суть:
```batch
set USERPROFILE=C:\ClaudeAgents\agent2
set HOME=C:\ClaudeAgents\agent2
set APPDATA=C:\ClaudeAgents\agent2\AppData\Roaming
cd /d "e:\MTF BOT\CURSOR\crypto_volume_bot"
claude --dangerously-skip-permissions
```
При первом запуске нужно: `claude login` → oko.webdev@gmail.com

## Ранее (предыдущие сессии)
- `/settings` дашборд полный: `00b5ef1`, `80572c0`
- Разделение порогов min_strength/min_strength_register: `ff407d4`
- RPredictor в ML-петле: `7c7310e`
- Pivot TP (Этап 6): `63209be`, `19d9814`
- BTC-фильтр, еженедельный отчёт: `a69dfcd`

</work_completed>

<work_remaining>

## Двойной агент — завершить настройку

### Вариант A (если BIOS помог): Docker
```cmd
"C:\Program Files\Docker\Docker\resources\bin\docker.exe" compose build
"C:\Program Files\Docker\Docker\resources\bin\docker.exe" compose up -d claude_architect claude_developer
docker exec -it crypto_bot_architect bash → claude login (yogoru@gmail.com)
docker exec -it crypto_bot_developer bash → claude login (oko.webdev@gmail.com)
```

### Вариант B (если Docker не заработал): launch-agent2.bat
1. Запустить `launch-agent2.bat` в отдельном терминале
2. При первом запуске: `claude login` → oko.webdev@gmail.com
3. Проверить: `C:\ClaudeAgents\agent2\.claude.json` должен содержать oko.webdev email
4. Обновить `.claude-config/agents.md` — указать выбранный вариант

## Закоммитить новые файлы
- `launch-agent2.bat` — новый файл
- `TASKS.md` — новый файл
- `.claude-config/agents.md` — обновлён

## Этап 7 (Kelly) — ожидает запуска бота
**Код уже готов.** Нужно запустить бот:
```bash
python bot_with_subscriptions.py
```
Через 5 мин после старта в логах должно появиться:
`RPredictor обучен: 84 сделок, CV RMSE=X.XX`
После этого в TG-алертах будет показываться 📐 Kelly: X.X% депозита

Проверить готовность:
```sql
SELECT COUNT(*) FROM simulated_trades WHERE status != 'OPEN' AND max_R_possible > 0
-- Нужно ≥ 75. Сейчас = 84 ✅
```

## Этап 8 — Рефакторинг монолитов (задачи в TASKS.md)

### [ARCH-01] bot_with_subscriptions.py (1540+ строк)
Разбить на:
- `bot/core/bot.py` — класс OkoBot
- `bot/loops/scan_loop.py` — scan_all_pairs, scan_one
- `bot/loops/ml_loop.py` — _ml_training_loop
- `bot/loops/trade_tracker.py` — check_open_trades loop

### [ARCH-02] trading_intelligence.py (1850+ строк)
Разбить на:
- `core/intelligence/signal_aggregator.py` — _analyze_signals_advanced
- `core/intelligence/confidence_calculator.py` — _calculate_advanced_confidence
- `core/intelligence/recommendation_generator.py` — _generate_recommendation
- `core/intelligence/ml_enhancer.py` — _enhance_analysis_with_ml

## Этап 9 — SMC (задача [DEV-01] в TASKS.md)
- `core/structure_detector.py` — Swing High/Low, CHoCH/BOS
- Order Block finder + Fibonacci 0.618 entry
- signal_type = "smc_signal", вес ~0.25

## Оптимизация сигнальной цепочки (план serialized-floating-graham.md — пока НЕ реализован)
- A1: Dedup ключ (symbol, signal_type) вместо symbol
- B1: Дивергенции раз в 3 цикла вместо каждые 60 сек
- B3: WT strength адаптивный по глубине зоны (сейчас всегда 70)
- 3.1: pre_collected_signals в analyze_symbol (устранить дублирование API)

</work_remaining>

<attempted_approaches>

## Docker Desktop — не запустился
**Ошибка:** "Virtualization support not detected" + "Engine stopped"
**Причина:** Виртуализация (Intel VT-x / AMD-V) отключена в BIOS.
**Статус:** Пользователь пробует включить в BIOS.
Если не получится → использовать `launch-agent2.bat`.

## conflict_ratio — исходная реализация с порогом 0.15
Предыдущая сессия снизила порог с 0.30 до 0.15 — казалось фиксом.
Проблема: 70 vs 60 = ratio 0.143 < 0.15 → ВСЁ ЕЩЁ NEUTRAL.
Комментарий в коде буквально описывал это как "70 vs 60 = 0.14 → NEUTRAL" — ПОЛОМАННОЕ поведение.
Исправлено в текущей сессии: 0.15 → 0.05.

## plan mode "File has not been read yet"
При Write в план-файл без предварительного Read → ошибка.
Обход: Read(limit=5) перед Write.

</attempted_approaches>

<critical_context>

## База данных
- `subscriptions.db` — SQLite, 303 сделки
- Статусы: OPEN=20, SL=157, TP=96, TSL=22, EXPIRED=4
- `max_R_possible` заполнен для **84** закрытых сделок (с 05.03.2026)
- **RPredictor порог снижен до 75** → активируется при следующем запуске бота автоматически

## Аккаунты агентов
- Agent 1 (Architect): **yogoru@gmail.com** — текущий, VSCode
- Agent 2 (Developer): **oko.webdev@gmail.com** — второй аккаунт

## Claude Code конфиг на Windows (ключевое!)
Хранится в ДВУХ местах (оба зависят от USERPROFILE):
- `%USERPROFILE%\.claude\` — credentials.json, settings
- `%USERPROFILE%\.claude.json` — oauthAccount, userID (ГЛАВНЫЙ)
Переопределения только CLAUDE_CONFIG_DIR недостаточно — нужен полный USERPROFILE.

## Docker PATH на Windows
Не в системном PATH. Полный путь:
`"C:\Program Files\Docker\Docker\resources\bin\docker.exe"`

## Python для бота
Только Python 3.12 имеет aiogram:
`C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe`
В bash достаточно просто `python`.

## Координация агентов
`TASKS.md` в корне проекта — задачи ARCH-* (Architect) и DEV-* (Developer).
Правило: не редактировать один файл одновременно.

## Важные паттерны
- Всегда `open(file, encoding='utf-8')` — Windows cp1251 ломает utf-8
- TSL читает config каждый раз → hot-reload корректен
- После save_* методов config_loader.reload() вызывается автоматически

</critical_context>

<current_state>

## Статус этапов
| Этап | Статус | Коммит |
|------|--------|--------|
| 1-4 | ✅ Готово | — |
| 5.1-5.3 | ✅ Готово | `265289f`, `a69dfcd` |
| 6 (pivot TP) | ✅ Готово | `63209be`, `19d9814` |
| 7 (RPredictor обучение) | ✅ Код готов | `7c7310e` |
| 7 (Kelly sizing footer) | ✅ Реализован | `bddb51b` |
| conflict_ratio фикс | ✅ Исправлен (0.05) | `bddb51b` |
| /settings полный | ✅ Готово | `00b5ef1`, `80572c0` |
| Двойной агент Docker | ⏳ BIOS настройка | — |
| Двойной агент bat | ✅ launch-agent2.bat готов | не закоммичен |
| 8 (масштаб) | 🔜 Следующий этап | TASKS.md: ARCH-01, ARCH-02 |
| 9 (SMC) | 🔜 После Этапа 8 | TASKS.md: DEV-01 |

## Git
- Ветка: `main`, последний коммит: `bddb51b`
- Незакоммиченные новые файлы: `launch-agent2.bat`, `TASKS.md`, `.claude-config/agents.md`

## Следующие действия по порядку
1. Дождаться результата BIOS → запустить Docker (A) или использовать bat (B)
2. Закоммитить новые файлы агентов
3. Запустить бот → проверить Kelly footer в TG-алертах
4. Начать Этап 8: рефакторинг bot_with_subscriptions.py

</current_state>
