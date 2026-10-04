#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Ворота юнит-тестов: падать только на НОВЫХ падениях.

Зачем. Аудит 26.09 зафиксировал «959 ok / 50 fail, CI нет». 04.10 перемерили —
стало 1185 / 58: падений прибавилось, и никто этого не заметил, потому что
«тесты и так красные». Чинить все разом нереально, но дать им расти нельзя.

Как работает. Прогоняет `tests/unit`, сравнивает список павших с базовой линией
`tests/known_failures.txt`:
  • появилось новое падение  → exit 1 и список (это регрессия, её и ловим);
  • старое падение исчезло   → exit 0 и подсказка обновить базу (кто-то починил);
  • совпало                  → exit 0.

Запуск:
    python scripts/test_gate.py              # проверить
    python scripts/test_gate.py --update     # перезаписать базовую линию
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "known_failures.txt"
FAILED_RE = re.compile(r"^FAILED (tests/unit/\S+)")


def run_tests() -> tuple[set[str], str]:
    """Возвращает (множество id павших тестов, хвост вывода)."""
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit", "-q", "--tb=no", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (p.stdout or "") + (p.stderr or "")
    failed = {m.group(1) for line in out.splitlines() if (m := FAILED_RE.match(line))}
    tail = "\n".join(l for l in out.splitlines() if " passed" in l or " failed" in l)[-400:]
    return failed, tail


def read_baseline() -> set[str]:
    if not BASELINE.exists():
        return set()
    return {l.strip() for l in BASELINE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def write_baseline(failed: set[str]) -> None:
    head = ("# Известные падения юнит-тестов — базовая линия для scripts/test_gate.py.\n"
            "# Ворота падают только на НОВЫХ падениях: список чинится постепенно,\n"
            "# но расти ему не дают. Обновлять: python scripts/test_gate.py --update\n")
    BASELINE.write_text(head + "\n".join(sorted(failed)) + "\n", encoding="utf-8")


def main() -> int:
    # консоль Windows по умолчанию cp1251 — стрелки и галочки роняли бы сам скрипт
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="перезаписать базовую линию текущим прогоном")
    args = ap.parse_args()

    failed, tail = run_tests()
    print(tail or "(прогон не дал сводки)")

    if args.update:
        write_baseline(failed)
        print(f"\nБазовая линия обновлена: {len(failed)} известных падений → {BASELINE.relative_to(ROOT)}")
        return 0

    known = read_baseline()
    new = sorted(failed - known)
    fixed = sorted(known - failed)

    if fixed:
        print(f"\n✅ Починено с прошлого раза: {len(fixed)}")
        for t in fixed[:20]:
            print("   ", t)
        print("   Обнови базу: python scripts/test_gate.py --update")

    if new:
        print(f"\n🔴 НОВЫЕ падения: {len(new)} — это регрессия")
        for t in new:
            print("   ", t)
        return 1

    print(f"\nНовых падений нет (известных {len(failed)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
