#!/usr/bin/env python3
"""
Build Obsidian Vault from project history.

Генератор 870+ заметок Obsidian из TASKS, DISCUSSION, PROJECT-LOG.
- Парсит TASKS.md, TASKS-ARCHIVE.md, PROJECT-LOG.md, DISCUSSION-*.md
- Генерирует задачи, обсуждения, индексы с кросс-ссылками
- Идемпотентен: можно перезапускать при обновлении источников

Запуск:
    python scripts/build_obsidian_vault.py [--sample] [--clean]

--sample: генерирует только 10 задач + 5 обсуждений для проверки
--clean: полностью переписывает obsidian/ (с бэкапом)
"""

import re
import os
import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict
import shutil

# === Конфиги ===

WORKSPACE_ROOT = Path("/workspace")
OBSIDIAN_ROOT = WORKSPACE_ROOT / "obsidian"
TASKS_FILE = WORKSPACE_ROOT / "TASKS.md"
TASKS_ARCHIVE_FILE = WORKSPACE_ROOT / "TASKS-ARCHIVE.md"
PROJECT_LOG_FILE = WORKSPACE_ROOT / "PROJECT-LOG.md"
DISCUSSION_FILES = [
    WORKSPACE_ROOT / "DISCUSSION.md",
    WORKSPACE_ROOT / "DISCUSSION-ARCHIVE-MAR2026.md",
    WORKSPACE_ROOT / "DISCUSSION-ARCHIVE-APR2026.md",
]

TASK_PATTERN = re.compile(r"(DEV|ARCH|TR|REAL|CUBE|TRADER-AUDIT)-(\d+)([a-zA-Z])?")
CODE_PATTERN = re.compile(r"([a-zA-z_/]+\.py)")
DATE_PATTERN = re.compile(r"\[(\d{2})\.(\d{2})\.(\d{4})\]")


# === Структуры данных ===

@dataclass
class Task:
    id: str
    date_short: str  # "25.03"
    date_full: str  # "2026-03-25"
    description: str
    role: str  # DEV, ARCH, TR
    status: str  # done, active, shadow, blocked, archived
    in_project_log: List[str] = None  # даты где упомянута в PROJECT-LOG
    in_discussions: List[str] = None  # даты где упомянута в DISCUSSION
    related_tasks: List[str] = None  # другие задачи упомянутые в описании

    def __post_init__(self):
        if self.in_project_log is None:
            self.in_project_log = []
        if self.in_discussions is None:
            self.in_discussions = []
        if self.related_tasks is None:
            self.related_tasks = []


@dataclass
class DiscussionEntry:
    date: str  # "2026-03-25"
    date_short: str  # "25.03.2026"
    seq: int  # порядковый номер записи в этот день
    title: str
    text: str
    mentioned_tasks: List[str]
    mentioned_codes: List[str]


@dataclass
class ProjectLogEntry:
    date: str  # "2026-04-06"
    date_short: str
    title: str
    problem: str
    solution: str
    result: str
    mentioned_tasks: List[str]


# === Парсеры ===

def parse_date_short_to_full(date_short: str, year: int = 2026) -> str:
    """25.03 -> 2026-03-25"""
    try:
        day, month = map(int, date_short.split("."))
        return f"{year:04d}-{month:02d}-{day:02d}"
    except:
        return ""


def parse_date_full(date_str: str) -> str:
    """[25.03.2026] -> 2026-03-25"""
    m = DATE_PATTERN.search(date_str)
    if m:
        day, month, year = m.groups()
        return f"{year}-{month}-{day}"
    return ""


def extract_task_ids(text: str) -> List[str]:
    """Вытаскивает все DEV-XX, ARCH-XX и т.п. из текста"""
    ids = []
    for m in TASK_PATTERN.finditer(text):
        task_id = m.group(0)
        if task_id not in ids:
            ids.append(task_id)
    return ids


def extract_code_refs(text: str) -> List[str]:
    """Вытаскивает упоминания файлов кода"""
    codes = set()
    for m in CODE_PATTERN.finditer(text):
        codes.add(m.group(1))
    return sorted(list(codes))


def parse_tasks_archive() -> Dict[str, Task]:
    """Парсит TASKS-ARCHIVE.md в таблице"""
    tasks = {}
    content = TASKS_ARCHIVE_FILE.read_text(encoding="utf-8")
    lines = content.split("\n")

    in_table = False
    for line in lines:
        if "| ID | Дата | Описание |" in line:
            in_table = True
            continue
        if in_table and line.startswith("|"):
            # Парсим строку таблицы: | ID | Дата | Описание |
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and parts[1] and not parts[1].startswith("---"):
                task_id = parts[1]
                date_short = parts[2]
                desc = parts[3]

                m = TASK_PATTERN.match(task_id)
                if m:
                    role = m.group(1)
                    date_full = parse_date_short_to_full(date_short)
                    task = Task(
                        id=task_id,
                        date_short=date_short,
                        date_full=date_full,
                        description=desc,
                        role=role,
                        status="done",
                        related_tasks=extract_task_ids(desc)
                    )
                    tasks[task_id] = task

    return tasks


def parse_active_tasks() -> Dict[str, Task]:
    """Парсит TASKS.md для активных задач"""
    tasks = {}
    content = TASKS_FILE.read_text(encoding="utf-8")
    lines = content.split("\n")

    in_table = False
    for line in lines:
        if "| ID | Ст | Описание |" in line or "| ID | Статус |" in line:
            in_table = True
            continue
        if in_table and line.startswith("|") and not line.startswith("| --- |"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and parts[1]:
                task_id = parts[1]
                status_emoji = parts[2] if len(parts) > 2 else ""
                desc = parts[3] if len(parts) > 3 else ""

                m = TASK_PATTERN.match(task_id)
                if m:
                    role = m.group(1)

                    # Определяем статус по эмодзи
                    if "🔄" in status_emoji:
                        status = "in_progress"
                    elif "🔴" in status_emoji:
                        status = "critical"
                    elif "🟡" in status_emoji:
                        status = "important"
                    elif "🟢" in status_emoji:
                        status = "planned"
                    elif "🔵" in status_emoji:
                        status = "backlog"
                    elif "✅" in status_emoji:
                        status = "done"
                    else:
                        status = "active"

                    task = Task(
                        id=task_id,
                        date_short="",
                        date_full="",
                        description=desc,
                        role=role,
                        status=status,
                        related_tasks=extract_task_ids(desc)
                    )
                    tasks[task_id] = task

    return tasks


def parse_project_log() -> List[ProjectLogEntry]:
    """Парсит PROJECT-LOG.md"""
    entries = []
    content = PROJECT_LOG_FILE.read_text(encoding="utf-8")

    # Делим на секции по ### [ДД.ММ.ГГГГ]
    pattern = re.compile(r"^### \[(\d{2}\.\d{2}\.\d{4})\] (.+?)(?=^###|\Z)", re.MULTILINE | re.DOTALL)

    for match in pattern.finditer(content):
        date_str = match.group(1)
        title = match.group(2).strip().split("\n")[0]
        text = match.group(2)

        # Ищем блоки Проблема/Решение/Результат
        problem = ""
        solution = ""
        result = ""

        if "**Проблема:**" in text:
            problem = text.split("**Проблема:**")[1].split("**")[0].strip()
        if "**Решение:**" in text:
            solution = text.split("**Решение:**")[1].split("**")[0].strip()
        if "**Результат:**" in text:
            result = text.split("**Результат:**")[1].split("###")[0].strip()

        date_full = parse_date_full(f"[{date_str}]")
        if not date_full:
            day, month, year = date_str.split(".")
            date_full = f"{year}-{month}-{day}"

        entry = ProjectLogEntry(
            date=date_full,
            date_short=date_str,
            title=title,
            problem=problem,
            solution=solution,
            result=result,
            mentioned_tasks=extract_task_ids(text)
        )
        entries.append(entry)

    return entries


def parse_discussions() -> List[DiscussionEntry]:
    """Парсит DISCUSSION-*.md"""
    entries = []
    seq_by_date = defaultdict(int)

    for file_path in DISCUSSION_FILES:
        if not file_path.exists():
            continue

        content = file_path.read_text(encoding="utf-8")
        pattern = re.compile(r"^### \[(\d{2}\.\d{2}\.\d{4})\] (.+?)(?=^###|\Z)", re.MULTILINE | re.DOTALL)

        for match in pattern.finditer(content):
            date_str = match.group(1)
            title = match.group(2).strip().split("\n")[0]
            text = match.group(2)

            date_full = parse_date_full(f"[{date_str}]")
            if not date_full:
                day, month, year = date_str.split(".")
                date_full = f"{year}-{month}-{day}"

            seq_by_date[date_full] += 1

            entry = DiscussionEntry(
                date=date_full,
                date_short=date_str,
                seq=seq_by_date[date_full],
                title=title,
                text=text,
                mentioned_tasks=extract_task_ids(text),
                mentioned_codes=extract_code_refs(text)
            )
            entries.append(entry)

    return entries


# === Генератор заметок ===

def generate_task_note(task: Task, all_discussions: List[DiscussionEntry],
                      all_log_entries: List[ProjectLogEntry]) -> str:
    """Генерирует Obsidian-заметку для задачи"""

    # Теги по ролям, статусу, области
    tags = [f"#role/{task.role.lower()}", f"#status/{task.status}"]

    # Определяем область по ID/описанию
    areas = set()
    if "TSL" in task.description or "trailing" in task.description.lower():
        areas.add("strategy")
    if "cube" in task.description.lower() or "ARCH-68" in task.description:
        areas.add("cube")
    if "dashboard" in task.description.lower():
        areas.add("dashboard")
    if "ML" in task.description or "model" in task.description.lower():
        areas.add("ml")
    if "risk" in task.description.lower() or "leverage" in task.description.lower():
        areas.add("risk")

    if areas:
        tags.extend([f"#area/{a}" for a in sorted(areas)])

    # Месяц используется как wikilink, не как тег (избегаем "звёздного" тег-узла в графе)
    month_link = ""
    if task.date_full:
        month = task.date_full[:7]
        month_link = f'\nmonth: "[[Months/{month}]]"'

    # YAML frontmatter
    frontmatter = f"""---
tags: {tags}
id: {task.id}
role: {task.role}
status: {task.status}
created: {task.date_full or "unknown"}
type: task
parent: "[[Project-MOC]]"{month_link}
---

"""

    # Заголовок
    content = f"# {task.id} — {task.description}\n\n"

    # Дата
    if task.date_full:
        content += f"> **Дата:** {task.date_full}\n"
    if task.date_short:
        content += f"> **Дата (короткая):** {task.date_short}\n"

    content += f"> **Статус:** {task.status}\n"
    content += f"> **Роль:** {task.role}\n\n"

    # Связанные задачи в описании
    if task.related_tasks:
        content += f"## 🔗 Упомянутые задачи\n\n"
        for rel_id in sorted(set(task.related_tasks)):
            content += f"- [[{rel_id}]]\n"
        content += "\n"

    # Упоминания в PROJECT-LOG
    log_mentions = [e for e in all_log_entries if task.id in e.mentioned_tasks]
    if log_mentions:
        content += f"## 📋 Упоминания в PROJECT-LOG\n\n"
        for entry in log_mentions:
            content += f"- [[Project-Log/{entry.date}|{entry.date_short}]] — {entry.title}\n"
        content += "\n"

    # Упоминания в DISCUSSION
    disc_mentions = [e for e in all_discussions if task.id in e.mentioned_tasks]
    if disc_mentions:
        content += f"## 💬 Упоминания в DISCUSSION\n\n"
        for entry in sorted(set((e.date, e.date_short, e.title) for e in disc_mentions)):
            content += f"- [[Discussions/{entry[0]}-{entry[1].replace('.', '')}|{entry[1]}]] — {entry[2]}\n"
        content += "\n"

    content += f"## 📂 Парент\n\n"
    content += f"- [[Project-MOC]]\n"

    return frontmatter + content


def generate_discussion_note(entry: DiscussionEntry) -> str:
    """Генерирует Obsidian-заметку для обсуждения"""

    tags = ["#type/discussion", "#status/archived"]
    month = entry.date[:7]
    # Месяц используется как wikilink в frontmatter, не как тег

    # Определяем роли из текста
    roles = set()
    if "ARCH →" in entry.text or "ARCH:" in entry.text or "**ARCH**" in entry.text:
        roles.add("arch")
    if "DEV →" in entry.text or "DEV:" in entry.text or "**DEV**" in entry.text:
        roles.add("dev")
    if "TRADER" in entry.text or "**TRADER**" in entry.text:
        roles.add("trader")

    for role in roles:
        tags.append(f"#role/{role}")

    frontmatter = f"""---
tags: {tags}
date: {entry.date}
seq: {entry.seq}
type: discussion
parent: "[[Discussions/Discussions]]"
month: "[[Months/{month}]]"
---

"""

    content = f"# {entry.date_short} — {entry.title}\n\n"
    content += f"> Запись #{entry.seq} за день {entry.date_short}\n\n"

    if entry.mentioned_tasks:
        content += f"## 🔗 Упомянутые задачи\n\n"
        for task_id in sorted(set(entry.mentioned_tasks)):
            content += f"- [[{task_id}]]\n"
        content += "\n"

    if entry.mentioned_codes:
        content += f"## 💻 Файлы кода\n\n"
        for code_ref in entry.mentioned_codes:
            content += f"- `{code_ref}`\n"
        content += "\n"

    content += f"## 📝 Текст\n\n"
    # Обрезаем первый ### строку
    text_lines = entry.text.strip().split("\n")[1:]
    content += "\n".join(text_lines)

    return frontmatter + content


def generate_task_index(tasks: Dict[str, Task]) -> str:
    """Генерирует индекс задач по месяцам и ролям"""
    frontmatter = """---
tags: [index, tasks]
type: index
parent: "[[Project-MOC]]"
---

# 📋 Task Index

## По месяцам

"""

    by_month = defaultdict(list)
    for task in tasks.values():
        if task.date_full:
            month = task.date_full[:7]
            by_month[month].append(task)

    def safe_desc(text: str, max_len: int = 100) -> str:
        """Безопасно обрезает описание для Obsidian:
        - до max_len символов
        - не режет слово посередине
        - заменяет < и > на безопасные символы (избегает HTML-тегов)
        - балансирует скобки ()
        """
        # Заменяем < и > на безопасные unicode-варианты
        text = text.replace("<", "‹").replace(">", "›")
        # Обрезка по границе слова
        if len(text) > max_len:
            text = text[:max_len].rsplit(" ", 1)[0] + "…"
        # Балансировка скобок: если открыта но не закрыта - убираем последнюю открытую
        opens = text.count("(") - text.count(")")
        if opens > 0:
            # Удаляем последние открытые скобки и текст после них
            for _ in range(opens):
                idx = text.rfind("(")
                if idx > 0:
                    text = text[:idx].rstrip()
        return text

    content = frontmatter
    for month in sorted(by_month.keys()):
        content += f"### {month}\n\n"
        for task in sorted(by_month[month], key=lambda t: t.id):
            status_icon = "✅" if task.status == "done" else "🔄" if task.status == "in_progress" else "🟢"
            content += f"- {status_icon} [[{task.id}]] — {safe_desc(task.description)}\n"
        content += "\n"

    content += "## По ролям\n\n"
    by_role = defaultdict(list)
    for task in tasks.values():
        by_role[task.role].append(task)

    for role in sorted(by_role.keys()):
        content += f"### {role}\n\n"
        for task in sorted(by_role[role], key=lambda t: t.id):
            content += f"- [[{task.id}]] — {safe_desc(task.description)}\n"
        content += "\n"

    return content


def generate_discussion_index(entries: List[DiscussionEntry]) -> str:
    """Генерирует индекс обсуждений по датам"""
    frontmatter = """---
tags: [index, discussions]
type: index
parent: "[[Project-MOC]]"
---

# 💬 Discussions Index

> {len(entries)} recorded entries from project history.

## Хронология

"""

    content = frontmatter
    by_date = defaultdict(list)
    for entry in entries:
        by_date[entry.date].append(entry)

    for date in sorted(by_date.keys(), reverse=True):
        entries_on_day = by_date[date]
        content += f"### {date}\n\n"
        for entry in entries_on_day:
            content += f"- [[Discussions/{date}|#{entry.seq}]] {entry.title}\n"
        content += "\n"

    return content


# === Main ===

def main(sample: bool = False, clean: bool = False):
    """Главная функция генератора"""

    print("🔵 Начало генерации Obsidian vault...")
    print(f"  Workspace: {WORKSPACE_ROOT}")
    print(f"  Output: {OBSIDIAN_ROOT}")

    # Backup
    if OBSIDIAN_ROOT.exists() and clean:
        backup_dir = WORKSPACE_ROOT / f".obsidian-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        print(f"  📦 Backup → {backup_dir}")
        shutil.move(str(OBSIDIAN_ROOT), str(backup_dir))

    # Парсим источники
    print("📖 Parsing...")
    all_tasks = {**parse_tasks_archive(), **parse_active_tasks()}
    all_log = parse_project_log()
    all_disc = parse_discussions()

    print(f"  Tasks: {len(all_tasks)}")
    print(f"  Log entries: {len(all_log)}")
    print(f"  Discussions: {len(all_disc)}")

    # Если sample, берём только первые N
    if sample:
        all_tasks = dict(sorted(all_tasks.items())[:10])
        all_disc = all_disc[:5]
        all_log = all_log[:3]
        print(f"  📊 SAMPLE MODE: {len(all_tasks)} tasks, {len(all_disc)} disc, {len(all_log)} log")

    # Создаём папки
    print("📁 Creating directories...")
    (OBSIDIAN_ROOT / "Tasks").mkdir(parents=True, exist_ok=True)
    (OBSIDIAN_ROOT / "Discussions").mkdir(parents=True, exist_ok=True)
    (OBSIDIAN_ROOT / "Project-Log").mkdir(parents=True, exist_ok=True)

    # Генерируем Task-заметки
    print("✍️  Generating task notes...")
    for task_id, task in all_tasks.items():
        note = generate_task_note(task, all_disc, all_log)
        file_path = OBSIDIAN_ROOT / "Tasks" / f"{task_id}.md"
        file_path.write_text(note, encoding="utf-8")
    print(f"  ✅ {len(all_tasks)} task notes")

    # Генерируем Discussion-заметки
    print("✍️  Generating discussion notes...")
    for entry in all_disc:
        note = generate_discussion_note(entry)
        # Filename: 2026-03-25-0003-title.md
        safe_title = re.sub(r"[^\w\s-]", "", entry.title).replace(" ", "-")[:20]
        file_path = OBSIDIAN_ROOT / "Discussions" / f"{entry.date}-{entry.seq:03d}-{safe_title}.md"
        file_path.write_text(note, encoding="utf-8")
    print(f"  ✅ {len(all_disc)} discussion notes")

    # Генерируем индексы
    print("✍️  Generating indexes...")
    index_task = generate_task_index(all_tasks)
    (OBSIDIAN_ROOT / "Tasks" / "Tasks.md").write_text(index_task, encoding="utf-8")

    index_disc = generate_discussion_index(all_disc)
    (OBSIDIAN_ROOT / "Discussions" / "Discussions.md").write_text(index_disc, encoding="utf-8")
    print(f"  ✅ Tasks.md + Discussions.md")

    print(f"\n✅ Готово! Создано {len(all_tasks) + len(all_disc) + 2} заметок")
    print(f"📂 {OBSIDIAN_ROOT}")


if __name__ == "__main__":
    import sys
    sample = "--sample" in sys.argv
    clean = "--clean" in sys.argv
    main(sample=sample, clean=clean)
