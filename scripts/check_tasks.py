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

TASKS_FILE = os.path.join(os.path.dirname(__file__), '..', 'TASKS.md')
AGENT_ROLE = os.environ.get('AGENT_ROLE', 'ARCHITECT').upper()

# Какие задачи берёт каждый агент
AGENT_TASK_PREFIX = {
    'ARCHITECT': 'ARCH-',
    'DEVELOPER': 'DEV-',
}


def parse_backlog_tasks(content: str) -> list[dict]:
    """Парсит задачи из секции ## 📥 ОЧЕРЕДЬ (Backlog)."""
    tasks = []

    # Найти секцию Backlog
    backlog_match = re.search(
        r'## 📥 ОЧЕРЕДЬ \(Backlog\)(.*?)(?=## ✅|## 📏|\Z)',
        content,
        re.DOTALL
    )
    if not backlog_match:
        return tasks

    backlog_text = backlog_match.group(1)

    # Найти все задачи вида ### [ARCH-XX] или ### [DEV-XX]
    task_blocks = re.split(r'(?=### \[(?:ARCH|DEV)-\d+\])', backlog_text)

    for block in task_blocks:
        # ID задачи
        id_match = re.search(r'### \[([A-Z]+-\d+)\]', block)
        if not id_match:
            continue

        task_id = id_match.group(1)

        # Пропустить выполненные (содержат ✅)
        if '✅' in block:
            continue

        # Название
        title_match = re.search(r'### \[[A-Z]+-\d+\]\s+(.+)', block)
        title = title_match.group(1).strip() if title_match else 'Без названия'

        # Агент
        agent_match = re.search(r'\*\*Агент:\*\*\s+(\w+)', block)
        agent = agent_match.group(1).upper() if agent_match else ''

        # Приоритет
        priority_match = re.search(r'\*\*Приоритет:\*\*\s+(\S+)', block)
        priority = priority_match.group(1) if priority_match else 'Средний'

        tasks.append({
            'id': task_id,
            'title': title,
            'agent': agent,
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

    reason = (
        f"📋 Новая задача в очереди: [{next_task['id']}] {next_task['title']} "
        f"(Приоритет: {next_task['priority']})\n\n"
        f"Прочитай TASKS.md, найди задачу [{next_task['id']}] и возьми её в работу. "
        f"Перемести в секцию '🔥 В РАБОТЕ' и начни реализацию."
    )

    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == '__main__':
    main()
