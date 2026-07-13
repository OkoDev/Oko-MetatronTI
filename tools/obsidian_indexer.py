"""Obsidian Indexer — генерирует Index/TIMELINE.md по всем задачам и сессиям.

Сканирует:
  - obsidian/Tasks/*.md      → frontmatter (id, enriched, status)
  - obsidian/Sessions/*.md   → frontmatter (date)
  - obsidian/Digests/*.md    → frontmatter (week, period)

Генерирует:
  - obsidian/Index/TIMELINE.md   ← хронология всех событий

Запуск:
  python tools/obsidian_indexer.py
  python tools/obsidian_indexer.py --quiet
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OBSIDIAN_DIR = PROJECT_ROOT / "obsidian"
OUTPUT_DIR = OBSIDIAN_DIR / "Index"


def parse_frontmatter(text: str) -> dict:
    """Извлекает YAML frontmatter из markdown файла."""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    fm_text = text[3:end]
    result = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def collect_tasks() -> list[dict]:
    tasks_dir = OBSIDIAN_DIR / "Tasks"
    if not tasks_dir.exists():
        return []
    items = []
    for f in sorted(tasks_dir.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        fm = parse_frontmatter(text)
        task_id = fm.get("id") or f.stem
        enriched = fm.get("enriched", "")
        # Статус из тела файла
        status_emoji = "✅" if "✅ done" in text or "closed" in text.lower()[:500] else "🔄"
        if "FROZEN" in text[:500]:
            status_emoji = "🧊"
        items.append({
            "date": enriched or "2026-01-01",
            "type": "task",
            "id": task_id,
            "status": status_emoji,
            "file": f"Tasks/{f.name}",
        })
    return items


def collect_sessions() -> list[dict]:
    sessions_dir = OBSIDIAN_DIR / "Sessions"
    if not sessions_dir.exists():
        return []
    items = []
    for f in sorted(sessions_dir.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        fm = parse_frontmatter(text)
        date = fm.get("date") or re.search(r"\d{4}-\d{2}-\d{2}", f.stem)
        if hasattr(date, "group"):
            date = date.group(0)
        items.append({
            "date": str(date) if date else "2026-01-01",
            "type": "session",
            "id": f.stem,
            "file": f"Sessions/{f.name}",
        })
    return items


def collect_digests() -> list[dict]:
    digests_dir = OBSIDIAN_DIR / "Digests"
    if not digests_dir.exists():
        return []
    items = []
    for f in sorted(digests_dir.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        fm = parse_frontmatter(text)
        period = fm.get("period", f.stem)
        week = fm.get("week", f.stem)
        items.append({
            "date": period.split("→")[0].strip() if "→" in period else "2026-01-01",
            "type": "digest",
            "id": week,
            "file": f"Digests/{f.name}",
        })
    return items


def build_timeline(items: list[dict]) -> str:
    # Сортируем по дате (DESC)
    def sort_key(x: dict) -> str:
        return x.get("date", "2000-01-01")

    items_sorted = sorted(items, key=sort_key, reverse=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    lines = [
        "---",
        'parent: "[[Project-MOC]]"',
        "tags: [index, timeline, auto]",
        f"generated: {now} UTC",
        "---",
        "",
        "# Index / TIMELINE",
        "",
        f"> Автогенерация `tools/obsidian_indexer.py` · {now} UTC",
        f"> Всего: {len(items_sorted)} записей",
        "",
    ]

    # Группируем по месяцу
    current_month = None
    for item in items_sorted:
        date = item["date"]
        month = date[:7] if len(date) >= 7 else "—"
        if month != current_month:
            current_month = month
            lines.append(f"")
            lines.append(f"## {month}")
            lines.append("")

        itype = item["type"]
        item_id = item["id"]
        fpath = item["file"]

        if itype == "task":
            status = item.get("status", "🔄")
            lines.append(f"- `{date}` {status} [[{item_id}]] → [{item_id}]({fpath})")
        elif itype == "session":
            lines.append(f"- `{date}` 📋 [Session: {item_id}]({fpath})")
        elif itype == "digest":
            lines.append(f"- `{date}` 📊 [Digest: {item_id}]({fpath})")

    return "\n".join(lines)


def main() -> int:
    quiet = "--quiet" in sys.argv

    all_items = collect_tasks() + collect_sessions() + collect_digests()

    timeline = build_timeline(all_items)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "TIMELINE.md"
    out_path.write_text(timeline, encoding="utf-8")

    if not quiet:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        n_tasks = sum(1 for i in all_items if i["type"] == "task")
        n_sess = sum(1 for i in all_items if i["type"] == "session")
        n_dig = sum(1 for i in all_items if i["type"] == "digest")
        print(f"[obsidian-indexer] OK")
        print(f"  tasks={n_tasks} sessions={n_sess} digests={n_dig}")
        print(f"  -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
