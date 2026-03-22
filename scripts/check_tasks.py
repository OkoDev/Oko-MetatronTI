#!/usr/bin/env python3
"""
Stop hook для Архитектора — мониторинг TASKS.md.
Когда Claude собирается остановиться, этот скрипт проверяет
есть ли новые задачи в очереди. Если есть — блокирует остановку
и сообщает Архитектору какую задачу взять.

Используется как Stop hook в ~/.claude/settings.json Архитектора.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

TASKS_FILE = os.path.join(os.path.dirname(__file__), '..', 'TASKS.md')
SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), 'trader_schedule.json')
AGENT_ROLE = os.environ.get('AGENT_ROLE', 'ARCHITECT').upper()
PERIODIC_INTERVAL_HOURS = 24

# Какие задачи берёт каждый агент
AGENT_TASK_PREFIX = {
    'ARCHITECT': 'ARCH-',
    'DEVELOPER': 'DEV-',
    'TRADER': 'TR-',
}


def parse_backlog_tasks(content: str) -> list[dict]:
    """Парсит задачи ARCH/DEV из текущего формата TASKS.md.

    Поддерживает формат:
      ### DEV-36 — Title 🟡
      **Статус:** 🟢 в плане ...

    Задача считается в очереди если статус содержит 🟢 или 🟡 (не ✅, не 🔄).
    """
    tasks = []

    STATUS_TO_PRIORITY = {'🔴': 'Высокий', '🟡': 'Средний', '🟢': 'Низкий'}

    # Разбиваем на блоки по заголовкам ### DEV-XX или ### ARCH-XX
    task_blocks = re.split(r'(?=\n### (?:DEV|ARCH)-)', content)

    for block in task_blocks:
        # ID и название задачи: ### DEV-36 — Title 🟡  или ### DEV-WL-BREACH — Title
        id_match = re.search(r'### ((?:DEV|ARCH)-[\w-]+)\s*(?:—\s*(.+?))?(?:\s*[🔴🟡🟢])?\s*\n', block)
        if not id_match:
            continue

        task_id = id_match.group(1)
        title = (id_match.group(2) or '').strip().rstrip('🔴🟡🟢 ')

        # Статус задачи
        status_match = re.search(r'\*\*Статус:\*\*\s*(.+)', block)
        if not status_match:
            continue
        status_line = status_match.group(1).strip()

        # Пропустить выполненные (✅) и периодические (🔄)
        if '✅' in status_line or '🔄' in status_line:
            continue
        # Пропустить заблокированные и "в работе"
        if any(s in status_line for s in ('В РАБОТЕ', 'ЗАБЛОКИРОВАНО', 'Ждёт', '🔥')):
            continue
        # Брать только "в плане" (🟢) или "важно" (🟡) или "срочно" (🔴)
        if not any(emoji in status_line for emoji in ('🟢', '🟡', '🔴')):
            continue

        # Определяем приоритет из статус-строки
        priority = 'Низкий'
        for emoji, prio in STATUS_TO_PRIORITY.items():
            if emoji in status_line:
                priority = prio
                break

        tasks.append({
            'id': task_id,
            'title': title or task_id,
            'agent': 'DEVELOPER' if task_id.startswith('DEV') else 'ARCHITECT',
            'priority': priority,
        })

    return tasks


def get_in_progress_tasks(content: str) -> list[str]:
    """Возвращает ID задач которые уже В РАБОТЕ."""
    in_progress_match = re.search(
        r'## 🔥 В РАБОТЕ \(In Progress\)(.*?)(?=## 📥|## ✅|\Z)',
        content,
        re.DOTALL
    )
    if not in_progress_match:
        return []

    ids = re.findall(r'### \[([A-Z]+-\d+)\]', in_progress_match.group(1))
    return ids


def load_schedule() -> dict:
    """Загружает расписание последних запусков периодических задач."""
    if not os.path.exists(SCHEDULE_FILE):
        return {}
    with open(SCHEDULE_FILE, encoding='utf-8') as f:
        return json.load(f)


def save_schedule(schedule: dict) -> None:
    with open(SCHEDULE_FILE, 'w', encoding='utf-8') as f:
        json.dump(schedule, f, indent=2, ensure_ascii=False)


def is_periodic_due(task_id: str, schedule: dict) -> bool:
    """Возвращает True если периодическая задача готова к запуску (прошло >= 24ч)."""
    last_run = schedule.get(task_id)
    if not last_run:
        return True
    last_dt = datetime.fromisoformat(last_run)
    return datetime.now() - last_dt >= timedelta(hours=PERIODIC_INTERVAL_HOURS)


def parse_trader_tasks(content: str) -> list[dict]:
    """Парсит задачи из секции ## 🎯 Задачи TRADER."""
    tasks = []

    STATUS_PRIORITY = {'🔴': 'Высокий', '🟡': 'Средний', '🟢': 'Низкий'}
    schedule = load_schedule()

    # Ищем TR-блоки по всему файлу (не привязываемся к секции — структура может меняться)
    task_blocks = re.split(r'(?=\n### TR-\d+)', content)

    for block in task_blocks:
        id_match = re.search(r'### (TR-\d+)', block)
        if not id_match:
            continue

        task_id = id_match.group(1)

        # Пропустить выполненные
        if '**Статус:** ✅' in block:
            continue

        # Периодические задачи — только если прошло >= 24ч
        is_periodic = '**Статус:** 🔄' in block
        if is_periodic and not is_periodic_due(task_id, schedule):
            continue

        title_match = re.search(r'### TR-\d+ — (.+)', block)
        title = title_match.group(1).strip() if title_match else 'Без названия'

        priority = 'Средний'  # 🔄 = Средний по умолчанию
        for emoji, prio in STATUS_PRIORITY.items():
            if f'**Статус:** {emoji}' in block:
                priority = prio
                break

        tasks.append({
            'id': task_id,
            'title': title,
            'agent': 'TRADER',
            'priority': priority,
            'periodic': is_periodic,
        })

    return tasks


def priority_order(p: str) -> int:
    return {'Высокий': 0, 'Средний': 1, 'Низкий': 2}.get(p, 99)


def main():
    if not os.path.exists(TASKS_FILE):
        # Файл не найден — позволяем остановиться
        print(json.dumps({"decision": "approve"}))
        return

    with open(TASKS_FILE, encoding='utf-8') as f:
        content = f.read()

    in_progress = get_in_progress_tasks(content)

    if AGENT_ROLE == 'TRADER':
        backlog = parse_trader_tasks(content)
    else:
        backlog = parse_backlog_tasks(content)

    # Фильтр: задачи для текущего агента, не в работе, нет зависимостей
    prefix = AGENT_TASK_PREFIX.get(AGENT_ROLE, 'ARCH-')
    available = [
        t for t in backlog
        if t['id'].startswith(prefix)
        and t['id'] not in in_progress
        and 'Зависимость' not in t.get('title', '')  # упрощённая проверка
    ]

    if not available:
        print(json.dumps({"decision": "approve"}))
        return

    # Взять задачу с наивысшим приоритетом
    available.sort(key=lambda t: priority_order(t['priority']))
    next_task = available[0]

    if AGENT_ROLE == 'TRADER':
        reason = (
            f"📊 Торговая задача: [{next_task['id']}] {next_task['title']} "
            f"(Приоритет: {next_task['priority']})\n\n"
            f"Прочитай TASKS.md, найди задачу [{next_task['id']}] в секции '🎯 Задачи TRADER' "
            f"и выполни её. Результат опубликуй в Discussion как пост TRADER."
        )
    else:
        reason = (
            f"📋 Новая задача в очереди: [{next_task['id']}] {next_task['title']} "
            f"(Приоритет: {next_task['priority']})\n\n"
            f"Прочитай TASKS.md, найди задачу [{next_task['id']}] и возьми её в работу. "
            f"Перемести в секцию '🔥 В РАБОТЕ' и начни реализацию."
        )

    # Для периодических задач — записать время запуска
    if next_task.get('periodic'):
        schedule = load_schedule()
        schedule[next_task['id']] = datetime.now().isoformat()
        save_schedule(schedule)

    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == '__main__':
    main()
