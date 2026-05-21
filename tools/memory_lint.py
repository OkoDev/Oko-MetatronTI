"""Memory lint — health check для Claude Code persistent memory.

Read-only проверка состояния `~/.claude/projects/<project>/memory/`:
  - MEMORY.md ≤ MAX_INDEX_KB (бюджет загрузки)
  - Все feedback_*.md имеют `triggers:` frontmatter
  - Дубли triggers между разными файлами
  - Stale файлы (mtime > STALE_DAYS дней, не упомянуты в MEMORY.md)

Запуск:
    python tools/memory_lint.py [--verbose]

Output: pretty-printed report + exit code 1 если есть критичные проблемы.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import yaml

# ─── Конфигурация ────────────────────────────────────────────────────────

MEMORY_DIR = Path(
    os.path.expanduser(
        r"~\.claude\projects\e--MTF-BOT-CURSOR-crypto-volume-bot\memory"
    )
)
MAX_INDEX_KB = 15  # MEMORY.md target
STALE_DAYS = 90    # файлы старше N дней без упоминания в MEMORY.md — кандидаты в Obsidian


# ─── Helpers ──────────────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    """Возвращает (frontmatter dict, body). Использует PyYAML, понимает вложенность."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None, text
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None, text
    return fm if isinstance(fm, dict) else None, text[m.end():]


def extract_triggers(fm: dict | None) -> list[str]:
    """Triggers могут жить top-level или внутри metadata.triggers."""
    if not fm:
        return []
    t = fm.get("triggers") or (fm.get("metadata") or {}).get("triggers")
    if not t:
        return []
    return [str(x) for x in t] if isinstance(t, list) else []


def days_since_mtime(p: Path) -> int:
    mt = datetime.fromtimestamp(p.stat().st_mtime)
    return (datetime.now() - mt).days


# ─── Checks ───────────────────────────────────────────────────────────────

def check_index_size(memory_dir: Path) -> list[str]:
    """MEMORY.md под бюджетом?"""
    warnings = []
    idx = memory_dir / "MEMORY.md"
    if not idx.exists():
        return ["❌ MEMORY.md отсутствует"]
    size_kb = idx.stat().st_size / 1024
    if size_kb > MAX_INDEX_KB:
        warnings.append(
            f"⚠️ MEMORY.md = {size_kb:.1f} KB (бюджет {MAX_INDEX_KB} KB). "
            f"Перенесите длинные блоки в topic файлы или Obsidian."
        )
    else:
        warnings.append(f"✅ MEMORY.md = {size_kb:.1f} KB / {MAX_INDEX_KB} KB")
    return warnings


def check_triggers_coverage(memory_dir: Path) -> list[str]:
    """Все feedback_*.md должны иметь triggers."""
    warnings = []
    missing = []
    ok_count = 0
    for fb in sorted(memory_dir.glob("feedback_*.md")):
        fm, _ = parse_frontmatter(fb.read_text(encoding="utf-8"))
        if not extract_triggers(fm):
            missing.append(fb.name)
        else:
            ok_count += 1
    if missing:
        warnings.append(
            f"⚠️ feedback файлы без triggers ({len(missing)}):"
            + "\n    " + "\n    ".join(missing)
        )
    else:
        warnings.append(f"✅ Triggers coverage: {ok_count}/{ok_count} feedback файлов")
    return warnings


def check_duplicate_triggers(memory_dir: Path) -> list[str]:
    """Триггеры пересекаются между файлами?"""
    warnings = []
    trigger_to_files: dict[str, list[str]] = defaultdict(list)
    for fb in memory_dir.glob("feedback_*.md"):
        fm, _ = parse_frontmatter(fb.read_text(encoding="utf-8"))
        for t in extract_triggers(fm):
            trigger_to_files[t.lower()].append(fb.name)
    dups = {t: files for t, files in trigger_to_files.items() if len(files) > 1}
    if dups:
        warnings.append(f"⚠️ Дублированные triggers ({len(dups)}):")
        for t, files in sorted(dups.items())[:10]:
            warnings.append(f"    '{t}' → {', '.join(files)}")
        if len(dups) > 10:
            warnings.append(f"    ... +{len(dups) - 10} ещё")
    else:
        warnings.append("✅ Нет дублированных triggers")
    return warnings


def check_stale_files(memory_dir: Path) -> list[str]:
    """Файлы старше STALE_DAYS дней не упомянутые в MEMORY.md."""
    warnings = []
    idx_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    stale = []
    for f in sorted(memory_dir.glob("*.md")):
        if f.name in ("MEMORY.md", "current_state.md", "memory_audit_plan.md"):
            continue
        if f.name.startswith("last_") or f.name.startswith("session_"):
            continue  # daily pipeline output — meaningfully ephemeral
        age = days_since_mtime(f)
        if age > STALE_DAYS and f.name not in idx_text:
            stale.append((f.name, age))
    if stale:
        warnings.append(f"⚠️ Stale файлы (mtime > {STALE_DAYS}d, не в MEMORY.md):")
        for name, age in stale:
            warnings.append(f"    {name} ({age}d)")
    else:
        warnings.append(f"✅ Нет stale файлов (старше {STALE_DAYS}d вне индекса)")
    return warnings


def inventory(memory_dir: Path, verbose: bool = False) -> list[str]:
    """Сводка по содержимому."""
    if not memory_dir.exists():
        return [f"❌ Memory directory не найден: {memory_dir}"]
    files = sorted(memory_dir.glob("*.md"))
    total_kb = sum(f.stat().st_size for f in files) / 1024
    by_prefix: dict[str, int] = defaultdict(int)
    for f in files:
        prefix = f.name.split("_")[0] if "_" in f.name else f.stem
        by_prefix[prefix] += 1
    lines = [
        f"📊 Inventory: {len(files)} файлов, {total_kb:.1f} KB",
        "    " + ", ".join(f"{k}={v}" for k, v in sorted(by_prefix.items())),
    ]
    if verbose:
        lines.append("\n📁 Все файлы:")
        for f in files:
            size_kb = f.stat().st_size / 1024
            age = days_since_mtime(f)
            lines.append(f"    {f.name:<50} {size_kb:>6.1f} KB  {age:>3}d")
    return lines


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Memory health check (read-only)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Полный список файлов")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not MEMORY_DIR.exists():
        print(f"❌ Memory directory не найден: {MEMORY_DIR}")
        sys.exit(2)

    print(f"# Memory Lint — {MEMORY_DIR}\n")

    sections = [
        ("Inventory",       inventory(MEMORY_DIR, verbose=args.verbose)),
        ("Index size",      check_index_size(MEMORY_DIR)),
        ("Triggers cover",  check_triggers_coverage(MEMORY_DIR)),
        ("Duplicate trig",  check_duplicate_triggers(MEMORY_DIR)),
        ("Stale files",     check_stale_files(MEMORY_DIR)),
    ]

    critical = 0
    for title, lines in sections:
        print(f"## {title}")
        for line in lines:
            print(line)
            if line.startswith("❌") or "⚠️ MEMORY.md =" in line:
                critical += 1
        print()

    if critical:
        print(f"⚠️ {critical} критичных предупреждений — рассмотрите sweep")
        sys.exit(1)
    print("✅ Memory health: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
