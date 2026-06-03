"""
DS-317: Массовая миграция Obsidian frontmatter → v2.0
Применяет новую таксономию тегов ко всем старым файлам.
"""
import re, os
from pathlib import Path

OBSIDIAN = Path("e:/MTF BOT/CURSOR/crypto_volume_bot/obsidian")

# ── Таксономия v2.0 ──
TAG_MAP = {
    "session": "session",
    "brief": "brief",
    "performance": "#area/performance",
    "architecture": "#area/cube",
    "milestone": "#area/strategy",
    "task": "task",
    "auto-enriched": "auto",
    "auto": "auto",
    "guide": "guide",
    "maintenance": "#area/diagnostics",
    "obsidian": "#area/diagnostics",
    "trade": "#area/execution",
    "review": "#area/diagnostics",
}

ROLE_MAP = {
    "arch": "#role/arch",
    "dev": "#role/dev",
    "trader": "#role/trader",
    "ds": "#role/ds",
    "real": "#role/real",
}

STATUS_MAP = {
    "done": "#status/done",
    "active": "#status/active",
    "blocked": "#status/blocked",
    "shadow": "#status/shadow",
    "deprecated": "#status/deprecated",
    "planned": "#status/planned",
}


def migrate_frontmatter(text: str, file_type: str) -> str:
    """Обновить frontmatter под v2.0."""
    fm_match = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
    if not fm_match:
        # Нет frontmatter — создать
        return _create_frontmatter(file_type) + "\n" + text
    
    fm = fm_match.group(1)
    rest = text[fm_match.end():]
    
    # Парсим существующие поля
    tags_line = re.search(r'tags:\s*\[(.*?)\]', fm)
    type_line = re.search(r'type:\s*(.+)', fm)
    role_line = re.search(r'role:\s*(.+)', fm)
    status_line = re.search(r'status:\s*(.+)', fm)
    
    # Собираем новые теги
    tags = []
    if tags_line:
        old_tags = [t.strip().strip("'\"") for t in tags_line.group(1).split(",")]
        for t in old_tags:
            if t in TAG_MAP:
                mapped = TAG_MAP[t]
                if mapped not in tags:
                    tags.append(mapped)
            elif t.startswith("#"):
                if t not in tags:
                    tags.append(t)
            else:
                if t not in tags:
                    tags.append(t)
    
    # Добавляем role/area теги по типу файла
    if file_type == "session":
        if "#role/arch" not in tags: tags.append("#role/arch")
        if "#role/dev" not in tags: tags.append("#role/dev")
        if "#area/diagnostics" not in tags: tags.append("#area/diagnostics")
    elif file_type == "task":
        if role_line:
            role = role_line.group(1).strip().strip("'\"")
            mapped = ROLE_MAP.get(role, f"#role/{role}")
            if mapped not in tags: tags.append(mapped)
        if status_line:
            status = status_line.group(1).strip().strip("'\"")
            mapped = STATUS_MAP.get(status, f"#status/{status}")
            if mapped not in tags: tags.append(mapped)
    
    # Пересобираем frontmatter
    new_fm = fm
    
    # Заменяем tags
    new_tags = f"tags: [{', '.join(tags)}]"
    if tags_line:
        new_fm = new_fm.replace(tags_line.group(0), new_tags)
    else:
        new_fm = new_fm + f"\n{new_tags}"
    
    return "---\n" + new_fm + "\n---" + rest


def _create_frontmatter(file_type: str) -> str:
    """Создать frontmatter с нуля."""
    return f"""---
tags: [{', '.join(_default_tags(file_type))}]
type: {file_type}
parent: "[[Project-MOC]]"
---"""


def _default_tags(file_type: str) -> list:
    if file_type == "discussion":
        return ["discussion", "auto", "#area/strategy"]
    elif file_type == "concept":
        return ["concept", "reference", "#area/strategy"]
    return ["auto", "#area/diagnostics"]


def process_directory(subdir: str, file_type: str, dry_run: bool = True):
    """Обработать все .md файлы в поддиректории."""
    d = OBSIDIAN / subdir
    if not d.exists():
        return
    files = list(d.glob("*.md"))
    print(f"\n{'='*60}")
    print(f"{subdir}/ ({len(files)} files) — type={file_type}")
    print(f"{'='*60}")
    
    changed = 0
    for f in sorted(files):
        text = f.read_text(encoding="utf-8")
        new_text = migrate_frontmatter(text, file_type)
        if new_text != text:
            changed += 1
            if not dry_run:
                f.write_text(new_text, encoding="utf-8")
            print(f"  UPD: {f.name}")
    print(f"  Changed: {changed}/{len(files)}")
    return changed


if __name__ == "__main__":
    import sys
    dry = "--apply" not in sys.argv
    
    if dry:
        print("DRY RUN (для применения: --apply)")
    else:
        print("APPLYING CHANGES")
    
    total = 0
    total += process_directory("Sessions", "session", dry)
    total += process_directory("Discussions", "discussion", dry)
    total += process_directory("Concepts", "concept", dry)
    total += process_directory("Architecture", "architecture", dry)
    
    print(f"\n{'='*60}")
    print(f"TOTAL changes: {total}")
    if dry:
        print("Запусти с --apply для применения.")
