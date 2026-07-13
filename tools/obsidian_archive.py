"""ARCH-OBS-06 — Obsidian Archive.

Файлы старше 90 дней БЕЗ входящих wikilinks → obsidian/_archive/
(не удаляет — только перемещает).

Запуск:
  python tools/obsidian_archive.py --dry-run    # показать что будет перемещено
  python tools/obsidian_archive.py              # переместить кандидатов
  python tools/obsidian_archive.py --days 180   # другой порог
  python tools/obsidian_archive.py --restore    # вернуть из _archive/ обратно

Исключения (никогда не архивируются):
  - индексные файлы (Tasks.md, Discussions.md, Project-MOC.md и т.д.)
  - файлы с тегом #status/active или #status/critical
  - файлы из папок Meta/, Architecture/, Concepts/
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VAULT_ROOT = PROJECT_ROOT / "obsidian"
ARCHIVE_DIR = VAULT_ROOT / "_archive"

NEVER_ARCHIVE_STEMS = {
    "Tasks", "Discussions", "Architecture", "Strategies", "Concepts",
    "Project-MOC", "MEMORY", "QUICK-START", "OBSIDIAN-RULES", "TEMPLATES",
    "HEALTH", "DEDUP-REPORT", "Memory-System",
}

NEVER_ARCHIVE_FOLDERS = {
    "Meta", "Architecture", "Concepts", "Strategies", "Code-Map",
    "Months", "Index", "_archive",
}

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*)?\]\]")
_ACTIVE_TAG_RE = re.compile(r"#status/(active|critical|important)")


def collect_files(vault: Path) -> list[Path]:
    return [p for p in vault.rglob("*.md") if "_archive" not in p.parts]


def build_incoming(files: list[Path], vault: Path) -> dict[str, list[str]]:
    """stem → [источники] для входящих wikilinks."""
    stem_set = {f.stem for f in files}
    incoming: dict[str, list[str]] = defaultdict(list)
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in _WIKILINK_RE.finditer(text):
            target = Path(m.group(1)).stem
            if target in stem_set:
                incoming[target].append(f.stem)
    return incoming


def is_protected(path: Path) -> bool:
    """Возвращает True если файл нельзя архивировать."""
    # Индексные имена
    if path.stem in NEVER_ARCHIVE_STEMS:
        return True
    # Защищённые папки
    parts = set(path.relative_to(VAULT_ROOT).parts[:-1])
    if parts & NEVER_ARCHIVE_FOLDERS:
        return True
    # Активный тег в frontmatter
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if _ACTIVE_TAG_RE.search(text[:500]):
            return True
    except Exception:
        pass
    return False


def file_age_days(path: Path) -> float:
    mtime = path.stat().st_mtime
    age = datetime.now(timezone.utc).timestamp() - mtime
    return age / 86400


def find_candidates(vault: Path, max_age_days: int) -> list[Path]:
    files = collect_files(vault)
    incoming = build_incoming(files, vault)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    candidates: list[Path] = []
    for f in files:
        if is_protected(f):
            continue
        if f.stem in incoming:
            continue
        age = file_age_days(f)
        if age >= max_age_days:
            candidates.append(f)

    return candidates


def archive_file(path: Path, vault: Path, dry_run: bool = False) -> str:
    rel = path.relative_to(vault)
    dest = ARCHIVE_DIR / rel
    if dry_run:
        return f"  DRY  {rel} → _archive/{rel}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return f"  MOV  {rel} → _archive/{rel}"


def restore_archive(vault: Path, dry_run: bool = False) -> None:
    """Возвращает все файлы из _archive/ на исходные позиции."""
    if not ARCHIVE_DIR.exists():
        print("_archive/ не существует")
        return

    archived = list(ARCHIVE_DIR.rglob("*.md"))
    print(f"Restore: {len(archived)} файлов из _archive/")

    for f in archived:
        rel = f.relative_to(ARCHIVE_DIR)
        dest = vault / rel
        if dry_run:
            print(f"  DRY  _archive/{rel} → {rel}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest))
            print(f"  RES  {rel}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Obsidian Archive — старые orphan файлы → _archive/")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=90, help="Порог в днях (default: 90)")
    parser.add_argument("--restore", action="store_true", help="Вернуть из _archive/")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.restore:
        restore_archive(VAULT_ROOT, dry_run=args.dry_run)
        return

    print(f"Archive: ищу файлы старше {args.days} дней без входящих ссылок...")
    candidates = find_candidates(VAULT_ROOT, args.days)

    if not candidates:
        print(f"  Кандидатов нет. Vault чист (порог {args.days} дней).")
        return

    mode = "[DRY-RUN] " if args.dry_run else ""
    print(f"{mode}{len(candidates)} файлов → _archive/")

    moved = 0
    for f in candidates:
        result = archive_file(f, VAULT_ROOT, dry_run=args.dry_run)
        if not args.quiet or "MOV" in result:
            print(result)
        if "MOV" in result:
            moved += 1

    if not args.dry_run:
        print(f"\nПеремещено: {moved} файлов → {ARCHIVE_DIR.relative_to(PROJECT_ROOT)}")
    else:
        print(f"\nDry-run: {len(candidates)} кандидатов (запустите без --dry-run для применения)")


if __name__ == "__main__":
    main()
