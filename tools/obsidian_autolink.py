"""ARCH-OBS-03 — Obsidian Autolink.

Сканирует Markdown файлы проекта и заменяет голые ID (DEV-XXX, ARCH-XX, TR-X, D-XXX)
на wikilinks [[ID]] — если файл с таким ID существует в obsidian/Tasks/.

Покрывает ~80% связей через regex (Priority 2).

Запуск:
  python tools/obsidian_autolink.py                   # все файлы vault
  python tools/obsidian_autolink.py --dry-run          # только показать
  python tools/obsidian_autolink.py --file path.md     # один файл
  python tools/obsidian_autolink.py --scope project    # TASKS.md + DISCUSSION.md

Git hook (post-merge):
  .git/hooks/post-merge вызывает этот скрипт.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VAULT_ROOT = PROJECT_ROOT / "obsidian"
TASKS_DIR = VAULT_ROOT / "Tasks"

# Паттерн для ID задач: DEV-199, ARCH-104, TR-003, D-047, DEV-185.2
_TASK_ID_RE = re.compile(r"\b((?:DEV|ARCH|TR|D)-[\d]+(?:\.\d+)?(?:-\w+)?)\b")

# Уже является wikilink — пропустить
_ALREADY_LINKED = re.compile(r"\[\[([^\]]+)\]\]")
# Frontmatter-блок — пропустить
_FM_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)

# Строки которые не трогаем: заголовки `# DEV-`, код-блоки, already linked
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def build_known_ids(tasks_dir: Path) -> set[str]:
    """Строит множество известных ID из имён файлов obsidian/Tasks/."""
    known: set[str] = set()
    for f in tasks_dir.glob("*.md"):
        # Stem может быть "DEV-199", "ARCH-101 (Mesh шины)", "DEV-185.2"
        stem = f.stem
        # Извлекаем ID-часть из начала имени
        m = _TASK_ID_RE.match(stem)
        if m:
            known.add(m.group(1))
    return known


def autolink_text(text: str, known_ids: set[str]) -> tuple[str, int]:
    """Добавляет wikilinks к голым ID. Возвращает (новый текст, кол-во замен)."""
    # Сохраняем frontmatter без изменений
    fm_end = 0
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            fm_end = end + 5

    pre = text[:fm_end]
    body = text[fm_end:]

    # Собираем spans которые уже внутри [[...]] — не трогаем
    protected: list[tuple[int, int]] = []
    for m in _ALREADY_LINKED.finditer(body):
        protected.append((m.start(), m.end()))
    # Код-блоки тоже не трогаем
    for m in _CODE_FENCE_RE.finditer(body):
        protected.append((m.start(), m.end()))

    def is_protected(start: int, end: int) -> bool:
        return any(ps <= start and end <= pe for ps, pe in protected)

    replacements: list[tuple[int, int, str]] = []
    for m in _TASK_ID_RE.finditer(body):
        task_id = m.group(1)
        if task_id not in known_ids:
            continue
        if is_protected(m.start(), m.end()):
            continue
        replacements.append((m.start(), m.end(), f"[[{task_id}]]"))

    if not replacements:
        return text, 0

    # Применяем замены с конца чтобы не сбивать позиции
    new_body = body
    for start, end, replacement in reversed(replacements):
        new_body = new_body[:start] + replacement + new_body[end:]

    return pre + new_body, len(replacements)


def process_file(path: Path, known_ids: set[str], dry_run: bool = False) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    new_text, count = autolink_text(text, known_ids)

    if count == 0:
        return f"  OK   {path.name}: без изменений"

    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
        return f"  UPD  {path.name}: +{count} wikilinks"
    else:
        return f"  DRY  {path.name}: +{count} wikilinks (не записано)"


def collect_target_files(scope: str, file_arg: str | None) -> list[Path]:
    if file_arg:
        return [Path(file_arg)]

    if scope == "vault":
        return [p for p in VAULT_ROOT.rglob("*.md") if not p.name.startswith(".")]
    elif scope == "project":
        targets = []
        for name in ("TASKS.md", "DISCUSSION.md", "TASKS-ARCHIVE.md", "whats-next.md"):
            p = PROJECT_ROOT / name
            if p.exists():
                targets.append(p)
        return targets
    else:
        return [p for p in VAULT_ROOT.rglob("*.md") if not p.name.startswith(".")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Obsidian Autolink — добавить [[wikilinks]] по ID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--file", dest="file_arg", help="Один конкретный файл")
    parser.add_argument("--scope", choices=["vault", "project", "all"], default="vault",
                        help="vault — только obsidian/, project — TASKS/DISCUSSION, all — оба")
    args = parser.parse_args()

    known_ids = build_known_ids(TASKS_DIR)
    if not known_ids:
        print("ERROR: нет файлов в obsidian/Tasks/ — known_ids пуст", file=sys.stderr)
        sys.exit(1)

    if args.scope == "all":
        files = collect_target_files("vault", None) + collect_target_files("project", None)
    else:
        files = collect_target_files(args.scope, args.file_arg)

    mode = "[DRY-RUN] " if args.dry_run else ""
    print(f"{mode}Autolink: {len(known_ids)} known IDs, {len(files)} файлов")

    updated = total_links = 0
    for f in files:
        result = process_file(f, known_ids, dry_run=args.dry_run)
        if not args.quiet or "UPD" in result or "DRY" in result:
            print(result)
        if "UPD" in result or "DRY" in result:
            updated += 1
            m = re.search(r"\+(\d+) wikilinks", result)
            if m:
                total_links += int(m.group(1))

    print(f"\nИтого: {updated} файлов обновлено, +{total_links} wikilinks")


if __name__ == "__main__":
    main()
