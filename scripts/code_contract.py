# -*- coding: utf-8 -*-
"""Ворота паспорта инструмента: что нового вошло в проект и по правилам ли (docs/TOOL_CONTRACT.md, ARCH-148).

Вид D (замер) по градации самого паспорта. Смотрит НОВЫЕ строки — то, что добавлено в этой ветке относительно
базы сравнения, — и проверяет два правила:
  • правило 2: новый файл боевого пути (`core/`, `bot/`) приходит с упоминанием в тестах;
  • правило 5: новый `except` не молчит (`pass` или только `logger.debug` — нарушение).

Режим «считаю»: печатает отчёт и выходит с кодом 0. `--strict` — выходить с кодом 1 при нарушениях (перевод в режим
«отказываю», когда накопленное разобрано). Нарушения, принятые осознанно, лежат в `tests/known_contract.txt`.

Запуск:  python scripts/code_contract.py [--base origin/main] [--strict] [--update]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "known_contract.txt"

LIVE_DIRS = ("core/", "bot/")
# Файлы боевого пути, которым тест не нужен: только описания и точки входа
SKIP_LIVE = re.compile(r"__init__\.py$|/stubs?/|_stub\.py$")
SILENT_EXCEPT = re.compile(r"^\+\s*except\b[^\n]*:\s*$")
PASS_LINE = re.compile(r"^\+\s*pass\s*$")
DEBUG_LINE = re.compile(r"^\+\s*logger\.debug\(")
LOUD = re.compile(r"logger\.(warning|error|exception)|raise\b")
# Молчать можно — но с объяснением в той же строке: «# молчим: <почему>». Без объяснения молчание = нарушение.
SILENT_OK = re.compile(r"#\s*молчим:")


def sh(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def base_ref(explicit: str | None) -> str:
    if explicit:
        return explicit
    for ref in ("origin/main", "main"):
        if sh("git", "rev-parse", "--verify", "--quiet", ref).strip():
            return ref
    return "HEAD~1"


def new_files(base: str) -> list[str]:
    out = sh("git", "diff", "--name-only", "--diff-filter=A", base)      # база → РАБОЧЕЕ ДЕРЕВО, а не ...HEAD:
    # ворота обязаны видеть то, что написано прямо сейчас, иначе свежую правку они пропустят (поймано 13.10)
    return [l.strip().replace("\\", "/") for l in out.splitlines() if l.strip().endswith(".py")]


def tests_text() -> str:
    return " ".join(p.read_text(encoding="utf-8", errors="replace") for p in (ROOT / "tests").rglob("*.py"))


def untested_live(base: str) -> list[str]:
    t = tests_text()
    out = []
    for f in new_files(base):
        if not f.startswith(LIVE_DIRS) or SKIP_LIVE.search(f):
            continue
        if Path(f).stem not in t:
            out.append(f)
    return out


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def silent_excepts(base: str) -> list[str]:
    """Новые молчащие `except`: в добавленных строках ищем except, за которым идёт только pass или logger.debug.

    🔴 Ключ записи — файл И НОМЕР СТРОКИ: без номера два разных `except` в одном файле давали одинаковую запись,
    и принятый в базовую линию старый маскировал новый (поймано на себе 13.10 в первый же час работы ворот).
    Номера строк плывут при правках выше по файлу — базовая линия обновляется вместе с разбором (`--update`)."""
    diff = sh("git", "diff", "-U2", base, "--", "core", "bot", "web", "scripts")
    out, cur_file, lines = [], "?", diff.splitlines()
    lineno = 0
    for i, l in enumerate(lines):
        if l.startswith("+++ b/"):
            cur_file, lineno = l[6:].strip(), 0
            continue
        m = HUNK.match(l)
        if m:
            lineno = int(m.group(1)) - 1
            continue
        if l.startswith(("+", " ")):                  # строка существует в новой версии файла
            lineno += 1
        if not SILENT_EXCEPT.match(l):
            continue
        tail = [x for x in lines[i + 1:i + 4] if x.startswith(("+", " "))]
        body = "\n".join(tail)
        if LOUD.search(body) or SILENT_OK.search(l) or SILENT_OK.search(body):
            continue
        if any(PASS_LINE.match(x) for x in tail[:2]) or any(DEBUG_LINE.match(x) for x in tail[:2]):
            out.append(f"{cur_file}:{lineno}: {l[1:].strip()}")
    return out


def read_baseline() -> set[str]:
    if not BASELINE.exists():
        return set()
    return {l.strip() for l in BASELINE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None, help="с чем сравнивать (по умолчанию origin/main)")
    ap.add_argument("--strict", action="store_true", help="выходить с кодом 1 при нарушениях")
    ap.add_argument("--update", action="store_true", help="принять текущие нарушения как базовую линию")
    a = ap.parse_args()

    base = base_ref(a.base)
    found = [f"нет теста: {f}" for f in untested_live(base)] + [f"молчащий except: {x}" for x in silent_excepts(base)]

    if a.update:
        BASELINE.write_text("# Принятые нарушения паспорта инструмента (docs/TOOL_CONTRACT.md).\n"
                            "# Обновить: python scripts/code_contract.py --update\n"
                            + "\n".join(sorted(found)) + "\n", encoding="utf-8")
        print(f"[контракт] базовая линия обновлена: {len(found)} записей")
        return 0

    known = read_baseline()
    fresh = [x for x in found if x not in known]
    print(f"[контракт] сравнение с {base} · нарушений {len(found)} (принятых ранее {len(found) - len(fresh)})")
    if not fresh:
        print("[контракт] новых нарушений нет")
        return 0
    print(f"[контракт] НОВЫХ нарушений: {len(fresh)}")
    for x in fresh:
        print("   ", x)
    print("   правила: docs/TOOL_CONTRACT.md (правило 2 — тест на новое боевое; правило 5 — отказ не молчит)")
    return 1 if a.strict else 0


if __name__ == "__main__":
    sys.exit(main())
