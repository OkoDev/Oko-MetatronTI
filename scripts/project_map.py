"""
project_map.py — АВТОКАРТА ПРОЕКТА. Обновляет раздел «АВТОИНВЕНТАРЬ» в TOOLS.md.

Повод (Егор, 21.08.2026): «даже про graphify-out приходится напоминать!»
Корень: карта строилась ПО ПАМЯТИ агента, а память дырявая. Инвентаризация
показала, что вслепую было ~60% проекта: graphify-out (42МБ граф кода),
obsidian (1664 файла), AGENTS.md, RESEARCH.md, .agents/, logs/ на 2.2ГБ.

Решение: карта СКАНИРУЕТСЯ, а не вспоминается. Новое попадает в неё само.

    python scripts/project_map.py            # показать
    python scripts/project_map.py --write    # вписать в TOOLS.md

Что помечается:
  🔴 устаревшее (>60 дней) · 💾 тяжёлое (>100МБ) · ⚙️ боевое (в pm2)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", ".pytest_cache", "node_modules"}
STALE_DAYS = 60
HEAVY_MB = 100

# Назначение директорий — единственное, что задано вручную; неизвестные
# всё равно попадут в карту с пометкой «назначение не описано».
PURPOSE = {
    "core": "бизнес-логика (smc/ pivots/ indicators/ calculators/ trading/ exchange/)",
    "bot": "UI aiogram + лупы стратегий (loops/)",
    "scripts": "скрипты: боевые в pm2 + разовые исследования",
    "tools": "рой LLM (team_ask), оркестрация",
    "memory": "handoff между сессиями (current_state.md)",
    "docs": "ENCYCLOPEDIA.md (Куб Метатрона), ARCHITECTURE.md",
    "obsidian": "граф знаний: задачи, обсуждения, концепции (Project-MOC.md — хаб)",
    "graphify-out": "ГРАФ КОДА: graph.json, GRAPH_REPORT.md — связность модулей",
    "web": "aiohttp дашборд",
    "strategies": "встроенные стратегии (registry)",
    "tests": "тесты",
    "data": "исторические данные",
    "cache": "кэш расчётов",
    "logs": "логи (растут — чистить)",
    "models": "обученные ML-модели",
    "oko_feed": "фид рыночных данных",
    "config": "конфигурации подсистем",
    ".agents": "скиллы агентов (bingx-*)",
    ".claude": "CLAUDE.md — правила проекта, читается автоматически",
}


def _size_mb(p: Path) -> float:
    try:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1048576
    except Exception:  # noqa: BLE001
        return 0.0


def _age_days(p: Path) -> int:
    try:
        newest = max((f.stat().st_mtime for f in p.rglob("*") if f.is_file()), default=0)
        return int((time.time() - newest) / 86400) if newest else 999
    except Exception:  # noqa: BLE001
        return 999


def pm2_scripts() -> dict[str, str]:
    """Какие скрипты реально в бою."""
    try:
        out = subprocess.run(["pm2", "jlist"], capture_output=True, text=True,
                             shell=True, timeout=30).stdout
        data = json.loads(out)
    except Exception:  # noqa: BLE001
        return {}
    res = {}
    for p in data:
        path = p["pm2_env"].get("pm_exec_path", "")
        if path:
            res[Path(path).name] = f"{p['name']} ({p['pm2_env'].get('cron_restart') or 'постоянно'})"
    return res


def scan() -> str:
    live = pm2_scripts()
    L = ["<!-- АВТОИНВЕНТАРЬ: обновляется `python scripts/project_map.py --write`. Не править руками. -->",
         "",
         f"Собрано автоматически {time.strftime('%d.%m.%Y %H:%M')}. "
         f"🔴 = не менялось >{STALE_DAYS} дней · 💾 = тяжелее {HEAVY_MB} МБ · ⚙️ = в pm2",
         "",
         "### Директории",
         "",
         "| путь | файлов | размер | назначение |",
         "|---|---|---|---|"]
    dirs = sorted([d for d in ROOT.iterdir()
                   if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith(".git")],
                  key=lambda x: -_size_mb(x))
    for d in dirs:
        mb, age = _size_mb(d), _age_days(d)
        n = sum(1 for _ in d.rglob("*") if _.is_file())
        marks = ("💾 " if mb > HEAVY_MB else "") + ("🔴 " if age > STALE_DAYS else "")
        purpose = PURPOSE.get(d.name, "_назначение не описано — дополнить в PURPOSE_")
        L.append(f"| `{d.name}/` | {n} | {mb:.0f} МБ | {marks}{purpose} |")

    L += ["", "### Документы в корне", "", "| файл | строк | возраст | "]
    L += ["|---|---|---|"]
    for f in sorted(ROOT.glob("*.md")):
        try:
            lines = sum(1 for _ in f.open(encoding="utf-8", errors="ignore"))
        except Exception:  # noqa: BLE001
            lines = 0
        age = int((time.time() - f.stat().st_mtime) / 86400)
        mark = "🔴 " if age > STALE_DAYS else ""
        L.append(f"| `{f.name}` | {lines} | {mark}{age} дн |")

    if live:
        L += ["", "### ⚙️ Боевые скрипты (pm2)", "", "| скрипт | процесс |", "|---|---|"]
        for scr, proc in sorted(live.items()):
            L.append(f"| `{scr}` | {proc} |")

    # что весит и стоит почистить
    junk = []
    for pat, what in ((("scratch_*.pkl",), "временные данные исследований"),
                      (("*.bak.*",), "бэкапы правок"),
                      (("*.log",), "логи в корне")):
        files = [p for g in pat for p in ROOT.glob(g)]
        if files:
            mb = sum(p.stat().st_size for p in files) / 1048576
            junk.append(f"| {what} | {len(files)} | {mb:.0f} МБ |")
    if junk:
        L += ["", "### 🧹 Кандидаты на уборку (корень)", "",
              "| что | файлов | размер |", "|---|---|---|"] + junk
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Автокарта проекта")
    ap.add_argument("--write", action="store_true", help="вписать в TOOLS.md")
    a = ap.parse_args()
    body = scan()
    if not a.write:
        print(body); return 0
    tools = ROOT / "TOOLS.md"
    text = tools.read_text(encoding="utf-8") if tools.exists() else "# 🧰 КАРТА ИНСТРУМЕНТОВ\n"
    marker = "## 📊 АВТОИНВЕНТАРЬ"
    head = text.split(marker)[0].rstrip()
    tools.write_text(f"{head}\n\n{marker}\n\n{body}\n", encoding="utf-8")
    print(f"TOOLS.md обновлён ({len(body.splitlines())} строк автоинвентаря)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
