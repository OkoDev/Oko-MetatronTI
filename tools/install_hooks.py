#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Ставит git-хуки проекта из tools/hooks в .git/hooks.

Зачем отдельный скрипт: .git/hooks не версионируется, поэтому у каждого клона
(и у параллельной сессии) хуков нет, пока их не поставят. Здесь они лежат в репо
и ставятся одной командой.

Запуск:  python tools/install_hooks.py [--force]
Проверка: python tools/install_hooks.py --check
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tools" / "hooks"


def _hooks_dir() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--git-path", "hooks"],
                             cwd=ROOT, capture_output=True, text=True, timeout=30)
        p = Path((out.stdout or "").strip() or ".git/hooks")
    except Exception:                                # noqa: BLE001
        p = Path(".git/hooks")
    return p if p.is_absolute() else ROOT / p


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="перезаписать, даже если хук отличается")
    ap.add_argument("--check", action="store_true", help="только проверить, ничего не менять")
    a = ap.parse_args()

    dst_dir = _hooks_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    rc = 0
    for src in sorted(SRC.glob("*")):
        if src.is_dir():
            continue
        dst = dst_dir / src.name
        if not dst.exists():
            state = "ОТСУТСТВУЕТ"
        elif filecmp.cmp(src, dst, shallow=False):
            state = "совпадает"
        else:
            state = "ОТЛИЧАЕТСЯ"
        if a.check:
            print(f"  {src.name:<12} {state}")
            if state != "совпадает":
                rc = 1
            continue
        if state == "совпадает":
            print(f"  {src.name:<12} уже стоит")
            continue
        if state == "ОТЛИЧАЕТСЯ" and not a.force:
            # 🔴 Чужой хук не затираем молча: в этом репозитории на post-commit уже
            # висят obsidian-sync и graphify — потерять их было бы дороже ворот.
            print(f"  {src.name:<12} ОТЛИЧАЕТСЯ от установленного — пропущен (--force чтобы заменить)")
            rc = 1
            continue
        shutil.copyfile(src, dst)
        dst.chmod(0o755)
        print(f"  {src.name:<12} установлен")
    if not a.check and rc == 0:
        print("\nхуки на месте")
    return rc


if __name__ == "__main__":
    sys.exit(main())
