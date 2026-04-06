## 🔴 СТАРТ КАЖДОЙ СЕССИИ

## Язык
Thinking всегда (думать) на русском языке. Документацию пиши на русском.

## Общение
После завершения задачи или подзадачи, кратко изложите, что вы сделали, что произошло и что дальше. Затем озвучьте это через PowerShell TTS (Windows):
```powershell
# Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.SelectVoice('Microsoft Irina Desktop'); $s.Speak('текст')
```

---

## 🔴 СТАРТ КАЖДОЙ СЕССИИ — обязательное чтение MD

**Алгоритм подключения — строго по порядку:**

```
1. DISCUSSION.md           ← ПЕРВЫМ. Живой диалог агентов. Найти вопросы → своя роль: ответить сразу.
2. TASKS.md                ← задачи всех ролей (DEV/ARCH/TRADER), статусы, приоритеты
3. whats-next.md           ← handoff от предыдущей сессии (что сделано, что осталось)
4. memory/MEMORY.md        ← архитектурные решения, известные баги, паттерны
── по необходимости ──
5. docs/ENCYCLOPEDIA.md    ← 🔴 ОБЯЗАТЕЛЬНО если задача архитектурная или новый модуль
                              Раздел "Куб Метатрона" — основная концепция проекта.
                              Любое решение должно соответствовать Кубу.
6. ROADMAP.md              ← этапы проекта (читать если непонятен контекст задачи)
7. BOT_SIGNAL_MAP.md       ← сигнальный пайплайн (читать если задача касается сигналов)
```

**Без прочтения DISCUSSION.md и TASKS.md нельзя начинать реализацию.**
Это защищает от: пропуска вопросов от других ролей, повторной работы, нарушения архитектурных решений.

**🔴 АРХИТЕКТУРНОЕ ПРАВИЛО — Куб Метатрона:**
Любая новая задача должна соответствовать одному из вопросов:
1. Это строит/улучшает одну из 12 сфер Куба?
2. Это усиливает Shared Context Bus (центральная сфера)?
3. Это добавляет связь между сферами (новое ребро)?
4. Это feedback loop (одна сфера обучается от другой)?
Подробно: `docs/ENCYCLOPEDIA.md` → раздел "Архитектурная концепция: Куб Метатрана"

После прочтения — кратко подтвердить:
`"Прочитал: DISCUSSION (последнее: X, вопросов ко мне: Y), TASKS (в работе: Z)."`

---

## 🔴 ОБЯЗАТЕЛЬНО ДЛЯ КАЖДОГО АГЕНТА — Ведение MD-документации

Это правило **не опционально** и применяется ко всем агентам (Architect, Developer, любые).

### В ходе сессии
После каждой завершённой задачи или подзадачи:
- Обновить `memory/current_state.md` — отметить что сделано, что изменилось
- Если изменился паттерн/архитектура/конфиг — обновить соответствующий раздел в `memory/MEMORY.md`

### При завершении сессии (явный выход или пауза)
Перед тем как остановить работу:
1. Обновить `memory/current_state.md` (что сделано / незакоммиченные изменения / известные проблемы / следующие задачи)
2. Обновить разделы `memory/MEMORY.md` которые затронула работа сессии

### При компакте контекста (context compaction)
Система автоматически сжимает контекст при приближении к лимиту. **До компакта** агент обязан:
1. Записать в `memory/current_state.md` промежуточный статус — что сделано, что в процессе, на чём остановился
2. Добавить раздел `## В ПРОЦЕССЕ (прерван компактом)` с деталями незавершённой задачи
3. После компакта — прочитать `current_state.md` и продолжить с того места

### Формат отметки прогресса в current_state.md
```markdown
## [ЧЧ:ММ UTC] Агент: <Developer|Architect>
- ✅ Сделано: <краткое описание>
- 🔄 В процессе: <если не завершено>
- ⚠️ Проблемы: <если есть>
```

---

## Проект: Oko MTF TG Bot

Telegram-бот для технического анализа крипторынка с симуляцией сделок и самообучением.
Биржа: BingX (через ccxt). Таймфрейм по умолчанию: 15m.

**Запуск:** `C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe bot_with_subscriptions.py`
**Дашборд:** `http://localhost:8000` (aiohttp, запускается автоматически с ботом)
**БД:** `subscriptions.db` (SQLite) — основная таблица `simulated_trades`

**Зависимости:** aiogram==3.4.1, ccxt==4.2.85, aiohttp==3.9.3, pandas, numpy, scikit-learn, pyyaml, python-dotenv

---

## Структура проекта

→ **Полная структура:** `docs/ENCYCLOPEDIA.md` → раздел "Структура проекта"

```
bot_with_subscriptions.py   ← точка входа
config.yaml                 ← конфигурация
core/                       ← бизнес-логика (infra/ indicators/ signals/ pivots/ mtf/ trading/ ml/ ui/ db/ smc/ intelligence/ agents/)
bot/                        ← UI-слой aiogram (handlers/ menus/ filters/)
web/                        ← aiohttp дашборд (dashboard_server.py)
```

**Важно:** ARCH-54 (29.03.2026) — файлы разбиты по подпапкам core/. Старые импорты работают через stub-файлы. Новый импорт: `from core.<папка>.<модуль> import Y`

---

## БД и схема simulated_trades

→ Полная схема: `memory/MEMORY.md` → раздел "simulated_trades schema"

Статусы: `OPEN` / `TP` / `SL` / `TSL` / `EXPIRED`

Ключевые поля: `features_json`, `regime`, `tsl_activated`, `sl_source`, `tp_source`, `max_R_possible`, `captured_R_pct`

**Как добавлять поля:** CREATE TABLE в `subscription_manager.py` + ALTER TABLE миграция + INSERT в `trade_simulator.py`

---

## Архитектурные решения

→ Подробно: `docs/ENCYCLOPEDIA.md` → "Куб Метатрона" + "Сигнальный поток"
→ Известные проблемы: `memory/MEMORY.md` → раздел "Баги и фиксы"

**Сигнальный поток кратко:**
`DataCollector → 6 детекторов → TradingIntelligence.analyze_symbol() → TradeSimulator.register_trade_async()`

**Адаптивные веса:** `update_signal_weights()` — `new_weight = base_weight × clamp(1.0 + avg_R × 0.4, 0.5, 2.0)`, порог 20 сделок.

**TSL:** активируется после +1R, следит за `trenddown`/`trendup` из `calculate_trend()`. Параметры в `config.yaml` → `trading.tsl_*`

**Фильтры качества:** `config.yaml` → `signal_quality`: min_volume_usd, sl_cooldown_hours, dedup_minutes, min_strength (50 для TG), min_strength_register (40 для БД)

---

## Отладка

```bash
# Статистика по сделкам
python -c "from core.performance_engine import PerformanceEngine; pe = PerformanceEngine('subscriptions.db'); print(pe.summary())"

# Дашборд
http://localhost:8000
```
