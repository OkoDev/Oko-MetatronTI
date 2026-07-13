"""ARCH-OBS-01 — Obsidian Status Sync.

Читает TASKS.md, извлекает статус каждой задачи (✅/🔄/🔴/🟡/🟢/⏸/🧊/🔵)
и обновляет frontmatter в obsidian/Tasks/<ID>.md.

Запуск:
  python tools/obsidian_status_sync.py              # все задачи
  python tools/obsidian_status_sync.py --dry-run    # только показать diff
  python tools/obsidian_status_sync.py DEV-199      # одна задача

Git hook (post-commit):
  .git/hooks/post-commit вызывает этот скрипт автоматически.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path
from typing import Optional

# Windows cp1251 консоль не умеет → / стрелки
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASKS_FILE = PROJECT_ROOT / "TASKS.md"
TASKS_DIR = PROJECT_ROOT / "obsidian" / "Tasks"

# Маппинг эмодзи-статусов TASKS.md → canonical status
EMOJI_TO_STATUS: dict[str, str] = {
    "✅": "done",
    "🔄": "active",
    "🔴": "critical",
    "🟡": "important",
    "🟢": "planned",
    "⏸": "blocked",
    "🧊": "frozen",
    "🔵": "backlog",
}

# Canonical status → obsidian tag
STATUS_TO_TAG: dict[str, str] = {
    "done":      "#status/done",
    "active":    "#status/active",
    "critical":  "#status/critical",
    "important": "#status/active",
    "planned":   "#status/planned",
    "blocked":   "#status/blocked",
    "frozen":    "#status/blocked",
    "backlog":   "#status/planned",
}

# Regex для строк таблицы: | [ID](#...) | EMOJI |  или  | ID | EMOJI |
_ROW_RE = re.compile(
    r"^\|\s*\[?([\w.\-]+)\]?(?:\(#[\w\-]+\))?\s*\|\s*([✅🔄🔴🟡🟢⏸🧊🔵])\s*\|"
)


def parse_tasks(content: str) -> dict[str, str]:
    """Возвращает {task_id: status} для всех задач из TASKS.md."""
    result: dict[str, str] = {}
    for line in content.splitlines():
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        task_id = m.group(1).strip()
        emoji = m.group(2)
        status = EMOJI_TO_STATUS.get(emoji)
        if status:
            result[task_id] = status
    return result


def find_task_file(task_id: str) -> Optional[Path]:
    """Ищет файл obsidian/Tasks/<ID>*.md (первое совпадение)."""
    candidates = list(TASKS_DIR.glob(f"{task_id}*.md"))
    if not candidates:
        # Попробуем case-insensitive (Windows)
        candidates = [
            p for p in TASKS_DIR.iterdir()
            if p.name.lower().startswith(task_id.lower()) and p.suffix == ".md"
        ]
    return candidates[0] if candidates else None


def read_frontmatter(text: str) -> tuple[dict[str, str], str, str]:
    """Парсит YAML frontmatter. Возвращает (fields, fm_block, body)."""
    fields: dict[str, str] = {}
    if not text.startswith("---"):
        return fields, "", text

    end = text.find("\n---", 3)
    if end == -1:
        return fields, "", text

    fm_block = text[3:end].strip()
    body = text[end + 4:]

    for line in fm_block.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()

    return fields, fm_block, body


def update_frontmatter(text: str, new_status: str) -> tuple[str, bool]:
    """Обновляет поля status/tags в frontmatter. Возвращает (новый текст, изменилось)."""
    if not text.startswith("---"):
        return text, False

    end = text.find("\n---", 3)
    if end == -1:
        return text, False

    fm_lines = text[3:end].splitlines()
    body = text[end + 4:]
    new_tag = STATUS_TO_TAG[new_status]

    changed = False
    new_fm_lines: list[str] = []
    has_status = False
    has_tags = False

    for line in fm_lines:
        stripped = line.strip()

        if stripped.startswith("status:"):
            old_val = stripped[len("status:"):].strip()
            if old_val != new_status:
                line = f"status: {new_status}"
                changed = True
            has_status = True

        elif stripped.startswith("tags:"):
            # Поддерживаем оба формата: tags: ['x', 'y'] и tags: [x, y]
            old_line = line
            line = _update_tags_line(line, new_tag)
            if line != old_line:
                changed = True
            has_tags = True

        new_fm_lines.append(line)

    if not has_status:
        new_fm_lines.append(f"status: {new_status}")
        changed = True

    if not has_tags:
        new_fm_lines.append(f"tags: ['{new_tag}']")
        changed = True

    if not changed:
        return text, False

    new_fm = "\n".join(new_fm_lines)
    return f"---\n{new_fm}\n---{body}", True


def _update_tags_line(line: str, new_tag: str) -> str:
    """Заменяет все #status/... теги на new_tag, добавляет если отсутствует."""
    # Извлекаем содержимое тегов
    m = re.search(r"tags:\s*\[(.+)\]", line)
    if not m:
        return line

    inner = m.group(1)
    # Нормализуем: убираем кавычки и пробелы из каждого тега
    items = [t.strip().strip("'\"") for t in inner.split(",") if t.strip()]

    # Удаляем старые status теги
    items = [t for t in items if not t.startswith("#status/")]

    # Добавляем новый
    items.append(new_tag)

    new_inner = ", ".join(f"'{t}'" for t in items)
    return line[: m.start()] + f"tags: [{new_inner}]" + line[m.end():]


def sync_task(task_id: str, status: str, dry_run: bool = False) -> str:
    """Обновляет один файл. Возвращает строку-лог."""
    task_file = find_task_file(task_id)
    if not task_file:
        return f"  SKIP {task_id}: файл не найден в obsidian/Tasks/"

    text = task_file.read_text(encoding="utf-8")
    new_text, changed = update_frontmatter(text, status)

    if not changed:
        return f"  OK   {task_id}: уже {status}"

    tag = STATUS_TO_TAG[status]
    if not dry_run:
        task_file.write_text(new_text, encoding="utf-8")
        return f"  UPD  {task_id}: → {status} ({tag})"
    else:
        return f"  DRY  {task_id}: → {status} ({tag})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync TASKS.md statuses → obsidian/Tasks/ frontmatter")
    parser.add_argument("task_ids", nargs="*", help="Конкретные ID (по умолчанию — все)")
    parser.add_argument("--dry-run", action="store_true", help="Только показать что изменится")
    parser.add_argument("--quiet", action="store_true", help="Не выводить OK строки (только UPD/ERR)")
    parser.add_argument("--tasks-file", default=str(TASKS_FILE), help="Путь к TASKS.md")
    args = parser.parse_args()

    tasks_path = Path(args.tasks_file)
    if not tasks_path.exists():
        print(f"ERROR: TASKS.md не найден: {tasks_path}", file=sys.stderr)
        sys.exit(1)

    content = tasks_path.read_text(encoding="utf-8")
    all_tasks = parse_tasks(content)

    if not all_tasks:
        print("WARNING: не найдено ни одной задачи в таблице TASKS.md")
        return

    target_ids = args.task_ids if args.task_ids else list(all_tasks.keys())

    mode = "[DRY-RUN] " if args.dry_run else ""
    print(f"{mode}Obsidian Status Sync — {len(target_ids)} задач из TASKS.md")

    updated = skipped = 0
    for tid in target_ids:
        status = all_tasks.get(tid)
        if not status:
            print(f"  WARN {tid}: нет в TASKS.md")
            skipped += 1
            continue

        result = sync_task(tid, status, dry_run=args.dry_run)
        if not args.quiet or "UPD" in result or "DRY" in result or "WARN" in result:
            print(result)
        if "UPD" in result or "DRY" in result:
            updated += 1
        else:
            skipped += 1

    print(f"\nИтого: {updated} обновлено, {skipped} без изменений / пропущено")


if __name__ == "__main__":
    main()
