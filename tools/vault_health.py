"""ARCH-OBS-02 — Vault Health Report.

Анализирует состояние obsidian vault и генерирует obsidian/Meta/HEALTH.md:
  - orphans %: файлы без входящих wikilinks
  - broken links %: [[wikilink]] которые ни на что не ссылаются
  - untagged %: файлы task-типа без #status/* тегов
  - средний размер файла (строк)
  - топ-10 orphans (кандидаты на удаление/архив)
  - топ-10 broken links

Запуск:
  python tools/vault_health.py           # пишет HEALTH.md
  python tools/vault_health.py --stdout  # только в консоль
  python tools/vault_health.py --check   # exit 1 если orphans > 30%
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VAULT_ROOT = PROJECT_ROOT / "obsidian"
HEALTH_FILE = VAULT_ROOT / "Meta" / "HEALTH.md"

# Wikilink: [[Target]] или [[Target|Alias]] или [[Folder/Target]]
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*)?\]\]")
# Frontmatter tags строка
_TAGS_RE = re.compile(r"^\s*tags\s*:", re.MULTILINE)
_STATUS_TAG_RE = re.compile(r"#status/\w+")


def collect_files(vault: Path) -> list[Path]:
    return [p for p in vault.rglob("*.md") if not p.name.startswith(".")]


def file_id(path: Path, vault: Path) -> str:
    """Ключ файла: stem (без расширения) как в wikilink."""
    return path.stem


def parse_wikilinks(text: str) -> list[str]:
    return _WIKILINK_RE.findall(text)


def extract_frontmatter_tags(text: str) -> list[str]:
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return []
    fm = text[3:end]
    tags_match = re.search(r"tags\s*:\s*\[(.+?)\]", fm, re.DOTALL)
    if not tags_match:
        # Многострочный YAML список
        lines = fm.splitlines()
        in_tags = False
        tags: list[str] = []
        for line in lines:
            if re.match(r"^\s*tags\s*:", line):
                in_tags = True
                continue
            if in_tags:
                m = re.match(r"^\s*-\s*(.+)", line)
                if m:
                    tags.append(m.group(1).strip().strip("'\""))
                else:
                    break
        return tags
    inner = tags_match.group(1)
    return [t.strip().strip("'\"") for t in inner.split(",") if t.strip()]


def is_task_file(path: Path) -> bool:
    name = path.stem.upper()
    return bool(re.match(r"(DEV|ARCH|TR|D)-\d+", name))


def analyze(vault: Path) -> dict:
    files = collect_files(vault)
    total = len(files)

    # id → файл (stem → Path, первый выигрывает при дублях)
    stem_map: dict[str, Path] = {}
    for f in files:
        stem = f.stem
        if stem not in stem_map:
            stem_map[stem] = f

    # Строим граф входящих ссылок
    incoming: dict[str, list[str]] = defaultdict(list)  # stem → [упоминающие stems]
    broken: list[tuple[str, str]] = []  # (source_stem, target_stem)

    # Placeholders которые не считаем broken: DEV-XXX, ARCH-XX, YYYY-MM, NNN и т.д.
    _PLACEHOLDER_RE = re.compile(r"[XNY]{2,}|YYYY|NNN|ZZZ", re.IGNORECASE)

    total_links = 0
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        links = parse_wikilinks(text)
        for link in links:
            total_links += 1
            target_stem = Path(link).stem
            if target_stem in stem_map:
                incoming[target_stem].append(f.stem)
            elif not _PLACEHOLDER_RE.search(target_stem):
                broken.append((f.stem, target_stem))

    # Orphans: нет входящих ссылок (кроме индексных файлов)
    index_names = {"Tasks", "Discussions", "Architecture", "Project-MOC", "MEMORY", "QUICK-START", "OBSIDIAN-RULES"}
    orphans = [
        f for f in files
        if f.stem not in incoming and f.stem not in index_names
    ]

    # Untagged task files
    task_files = [f for f in files if is_task_file(f)]
    untagged_tasks: list[Path] = []
    for f in task_files:
        text = f.read_text(encoding="utf-8", errors="replace")
        tags = extract_frontmatter_tags(text)
        if not any(t.startswith("#status/") or t.startswith("status/") for t in tags):
            untagged_tasks.append(f)

    # Средний размер
    sizes = [len(f.read_text(encoding="utf-8", errors="replace").splitlines()) for f in files]
    avg_size = sum(sizes) / len(sizes) if sizes else 0

    # Дубли stems (разные папки, одинаковое имя)
    seen_stems: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        seen_stems[f.stem].append(f)
    duplicates = {s: ps for s, ps in seen_stems.items() if len(ps) > 1}

    # Broken links: уникальные пары
    unique_broken = list(dict.fromkeys(broken))

    return {
        "total": total,
        "total_links": total_links,
        "orphans": orphans,
        "orphans_pct": len(orphans) / total * 100 if total else 0,
        "broken": unique_broken,
        "broken_pct": len(unique_broken) / max(total_links, 1) * 100,
        "untagged_tasks": untagged_tasks,
        "untagged_pct": len(untagged_tasks) / len(task_files) * 100 if task_files else 0,
        "task_total": len(task_files),
        "avg_size": avg_size,
        "duplicates": duplicates,
    }


def render_report(data: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "---",
        "tags: [health, meta, auto-generated]",
        "type: health-report",
        f"generated: {now}",
        "parent: \"[[Project-MOC]]\"",
        "---",
        "",
        f"# 🏥 Vault Health Report — {now}",
        "",
        "## 📊 Сводка",
        "",
        f"| Метрика | Значение | Порог |",
        f"|---|---|---|",
        f"| Всего файлов | {data['total']} | — |",
        f"| Orphans (нет входящих ссылок) | {len(data['orphans'])} ({data['orphans_pct']:.1f}%) | < 30% |",
        f"| Broken wikilinks | {len(data['broken'])} / {data['total_links']} ({data['broken_pct']:.1f}%) | < 5% |",
        f"| Untagged task-файлы | {len(data['untagged_tasks'])} / {data['task_total']} ({data['untagged_pct']:.1f}%) | < 10% |",
        f"| Средний размер файла | {data['avg_size']:.0f} строк | — |",
        f"| Дубли (одинаковый stem) | {len(data['duplicates'])} | 0 |",
        "",
    ]

    # Статус-индикатор
    warnings = []
    if data["orphans_pct"] > 30:
        warnings.append(f"⚠️ Orphans {data['orphans_pct']:.0f}% > 30% — много несвязанных файлов")
    if data["broken_pct"] > 5:
        warnings.append(f"⚠️ Broken links {data['broken_pct']:.0f}% > 5% — нужна чистка wikilinks")
    if data["untagged_pct"] > 10:
        warnings.append(f"⚠️ Untagged {data['untagged_pct']:.0f}% > 10% — задачи без статусов")
    if data["duplicates"]:
        warnings.append(f"⚠️ {len(data['duplicates'])} дублирующихся stem'ов")

    if warnings:
        lines.append("## ⚠️ Предупреждения")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")
    else:
        lines.append("## ✅ Vault в порядке")
        lines.append("")

    # Топ-10 orphans
    if data["orphans"]:
        lines.append("## 🔍 Топ-10 Orphans (кандидаты на архив)")
        lines.append("")
        orphans_sorted = sorted(data["orphans"], key=lambda p: p.stat().st_mtime)[:10]
        for p in orphans_sorted:
            rel = p.relative_to(PROJECT_ROOT / "obsidian")
            lines.append(f"- `{rel}` — нет входящих ссылок")
        lines.append("")

    # Топ-10 broken links
    if data["broken"]:
        lines.append("## 💔 Топ-10 Broken Wikilinks")
        lines.append("")
        for src, tgt in data["broken"][:10]:
            lines.append(f"- `[[{tgt}]]` в файле `{src}`")
        lines.append("")

    # Дубли
    if data["duplicates"]:
        lines.append("## 🔁 Дубли (одинаковый stem, разные папки)")
        lines.append("")
        for stem, paths in list(data["duplicates"].items())[:10]:
            paths_str = " / ".join(str(p.relative_to(PROJECT_ROOT / "obsidian")) for p in paths)
            lines.append(f"- `{stem}`: {paths_str}")
        lines.append("")

    lines.append("---")
    lines.append(f"*Сгенерировано `tools/vault_health.py` в {now}*")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Vault Health Report → obsidian/Meta/HEALTH.md")
    parser.add_argument("--stdout", action="store_true", help="Только в консоль, не писать файл")
    parser.add_argument("--check", action="store_true", help="exit 1 если orphans > 30%")
    args = parser.parse_args()

    print("Vault Health: анализ...", file=sys.stderr)
    data = analyze(VAULT_ROOT)
    report = render_report(data)

    if args.stdout:
        print(report)
    else:
        HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEALTH_FILE.write_text(report, encoding="utf-8")
        print(f"✅ Отчёт → {HEALTH_FILE.relative_to(PROJECT_ROOT)}", file=sys.stderr)
        print(f"   {data['total']} файлов | orphans {data['orphans_pct']:.1f}% | broken {data['broken_pct']:.1f}%", file=sys.stderr)

    if args.check and data["orphans_pct"] > 30:
        sys.exit(1)


if __name__ == "__main__":
    main()
