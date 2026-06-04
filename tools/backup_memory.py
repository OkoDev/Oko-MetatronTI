#!/usr/bin/env python3
"""Бэкап auto-memory Claude → git-проект (docs/MEMORY_SNAPSHOT/).

Правило `feedback_memory_persistence.md`: auto-memory лежит ВНЕ git
(`C:/Users/<user>/.claude/projects/<project-id>/memory/`) → при переносе проекта/сбросе
`.claude` пропадёт. Git = единственный надёжный переносимый носитель.

Запуск:  python tools/backup_memory.py            # снапшот в docs/MEMORY_SNAPSHOT/
         python tools/backup_memory.py --restore  # обратно: snapshot → auto-memory (на новой машине)

После снапшота закоммить:
    git add docs/MEMORY_SNAPSHOT/ && git commit -m "chore: memory snapshot YYYY-MM-DD"
"""
import argparse, shutil, sys
from pathlib import Path
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PROJECT_ID = "e--MTF-BOT-CURSOR-crypto-volume-bot"
AUTO_MEMORY = Path.home() / ".claude" / "projects" / PROJECT_ID / "memory"
SNAPSHOT = Path(__file__).resolve().parents[1] / "docs" / "MEMORY_SNAPSHOT"


def backup() -> int:
    if not AUTO_MEMORY.exists():
        print(f"[backup_memory] ❌ auto-memory не найдена: {AUTO_MEMORY}")
        return 1
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    mds = sorted(AUTO_MEMORY.glob("*.md"))
    for f in mds:
        shutil.copy2(f, SNAPSHOT / f.name)
    total = sum((SNAPSHOT / f.name).stat().st_size for f in mds)
    print(f"[backup_memory] ✅ {len(mds)} MD → {SNAPSHOT} ({total // 1024} KB), снапшот {date.today()}")
    print("[backup_memory] закоммить: git add docs/MEMORY_SNAPSHOT/ && "
          f'git commit -m "chore: memory snapshot {date.today()}"')
    return 0


def restore() -> int:
    if not SNAPSHOT.exists():
        print(f"[backup_memory] ❌ снапшот не найден: {SNAPSHOT}")
        return 1
    AUTO_MEMORY.mkdir(parents=True, exist_ok=True)
    mds = [f for f in sorted(SNAPSHOT.glob("*.md")) if f.name != "_SNAPSHOT_README.md"]
    for f in mds:
        shutil.copy2(f, AUTO_MEMORY / f.name)
    print(f"[backup_memory] ♻️  восстановлено {len(mds)} MD → {AUTO_MEMORY}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Бэкап/восстановление auto-memory ↔ git")
    ap.add_argument("--restore", action="store_true", help="snapshot → auto-memory (новая машина)")
    args = ap.parse_args()
    sys.exit(restore() if args.restore else backup())
