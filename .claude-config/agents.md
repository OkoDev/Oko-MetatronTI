# 🤖 Duo Claude Agents для Oko MTF Bot

## 🏗️ Agent 1: Architect (claude_architect)

**Роль:** Архитектор системы — планирование, анализ, code review
**Аккаунт:** yogoru@gmail.com
**Контейнер:** `crypto_bot_architect`

**Зоны ответственности:**
- ✅ Анализ архитектуры и планирование фич
- ✅ Code Review (проверяет что написал Developer)
- ✅ Рефакторинг монолитов (Этап 8)
- ✅ Разработка сложной логики (TradingIntelligence, ML)
- ✅ Документация

**Запуск:**
```bash
docker exec -it crypto_bot_architect bash
# Первый раз: claude login → yogoru@gmail.com
claude --dangerously-skip-permissions
```

---

## 💻 Agent 2: Developer (claude_developer)

**Роль:** Разработчик-исполнитель — код, тесты, оптимизация
**Аккаунт:** oko.webdev@gmail.com
**Контейнер:** `crypto_bot_developer`

**Зоны ответственности:**
- ✅ Написание тестов (tests/)
- ✅ Реализация новых индикаторов/детекторов
- ✅ Оптимизация производительности
- ✅ Мелкие фиксы по задачам от Architect
- ✅ SMC компоненты (Этап 9)

**Запуск:**
```bash
docker exec -it crypto_bot_developer bash
# Первый раз: claude login → oko.webdev@gmail.com
claude --dangerously-skip-permissions
```

---

## 📊 Workflow координации

### Как агенты взаимодействуют

Координация через файл `TASKS.md` в корне проекта:

```
Architect → создаёт задачу в TASKS.md → Developer забирает и реализует → Architect делает review
```

### Пример workflow (Этап 8 — рефакторинг)

**Architect** (Окно 1):
```
Разбей bot_with_subscriptions.py на модули:
- bot/core/bot.py — класс OkoBot
- bot/loops/scan_loop.py — scan_all_pairs
- bot/loops/ml_loop.py — _ml_training_loop
```

**Developer** (Окно 2):
```
Реализую разбивку согласно плану от Architect.
Пишу тесты для каждого нового модуля.
```

### Правило одновременной работы

⚠️ **Никогда не редактировать один файл одновременно!**

- Architect работает в: `core/trading_intelligence.py`, `core/signal_checkers.py`, `bot/monitoring.py`
- Developer работает в: `tests/`, `core/divergence_detector.py`, `core/structure_detector.py`

---

## 🚀 Команды

```bash
# DOCKER PATH (Windows)
DOCKER="C:\Program Files\Docker\Docker\resources\bin\docker.exe"

# Сборка
docker compose build claude_architect claude_developer

# Запуск
docker compose up -d claude_architect claude_developer

# Вход в контейнеры
docker exec -it crypto_bot_architect bash
docker exec -it crypto_bot_developer bash

# Логи
docker logs crypto_bot_architect
docker logs crypto_bot_developer

# Стоп
docker compose stop claude_architect claude_developer
```

---

## 📋 Текущие задачи по агентам

| Задача | Агент | Статус |
|--------|-------|--------|
| Этап 8: рефакторинг bot_with_subscriptions.py | Architect | 🔜 |
| Этап 8: рефакторинг trading_intelligence.py | Architect | 🔜 |
| Этап 9: core/structure_detector.py (Swing H/L, CHoCH/BOS) | Developer | 🔜 |
| Тесты для signal_checkers.py | Developer | 🔜 |
| Тесты для divergence_detector.py | Developer | 🔜 |
