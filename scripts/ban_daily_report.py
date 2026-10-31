# -*- coding: utf-8 -*-
"""Суточный замер банов BingX (ARCH-153, п.4 «г»): сколько 100410 и где — одним числом.

Зачем: после правок (хранилище старших ТФ, ожидание прокси, локальная сборка записи, карантин
внутри бана) нужен не «на глаз», а регулярный срез: глобальных пауз быть не должно, фоновые
бан-события — в пределах августовской нормы (1–30/сутки).

Читает pm2-логи бота (`oko-bot-out.log` + дневные ротации), к бирже НЕ ходит, нагрузку не даёт.
Классифицирует три вида строк:
  · «ГЛОБАЛЬНАЯ пауза» — бан DIRECT-адреса: останавливает ВСЕ данные (цель: 0);
  · «забанен ОДИН прокси» — бан одного выхода, пул продолжает (фон);
  · «[LIMIT]» терминала :8010 — отдельный процесс, отдельный счёт.

Использование:
    python scripts/ban_daily_report.py                 # последние 24 ч
    python scripts/ban_daily_report.py --hours 6
    python scripts/ban_daily_report.py --day 2026-10-30
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LOG_DIR = Path.home() / ".pm2" / "logs"
BOT = "oko-bot-out"
TERM = "structure-term-out"
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2})")
_TF = re.compile(r"\b(1m|3m|5m|15m|45m|1h|4h|1d|1w)\b")

# Норма августа (замер ARCH-153): 1–30 бан-событий в сутки, глобальных — ноль.
TARGET_BG_PER_DAY = 30


def _files(stem: str) -> list[Path]:
    """Все логи процесса по ВОЗРАСТУ (ротации + текущий): иначе «первое/последнее» врёт."""
    if not LOG_DIR.exists():
        return []
    return sorted(LOG_DIR.glob(f"{stem}*.log"), key=lambda p: p.stat().st_mtime)


def collect(stem: str, day: str | None, hours: int | None) -> dict:
    """Считает события по строкам лога: {'global', 'proxy', 'limit'} + разбивка по часам и ТФ."""
    events: list[tuple[str, str, list[str], str]] = []          # (час, вид, ТФ, строка)
    for path in _files(stem):
        try:
            fh = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if "100410" not in line and "[LIMIT]" not in line:
                    continue
                m = _TS.match(line)
                if not m:
                    continue
                d, hh = m.group(1), m.group(2)
                if day and d != day:
                    continue
                kind = "limit" if "[LIMIT]" in line else ("global" if "ГЛОБАЛЬНАЯ" in line else "proxy")
                events.append((f"{d} {hh}", kind, _TF.findall(line), line.rstrip()))
    out = {"global": 0, "proxy": 0, "limit": 0, "by_tf": Counter(), "by_hour": Counter(),
           "first": None, "last": None, "lines": []}
    if hours and not day and events:
        keep = set(sorted({e[0] for e in events})[-hours:])     # окно = последние N часовых ключей
        events = [e for e in events if e[0] in keep]
    for hour_key, kind, tfs, line in events:
        out[kind] += 1
        out["by_hour"][hour_key] += 1
        for tf in tfs:
            out["by_tf"][tf] += 1
        out["first"] = out["first"] or hour_key
        out["last"] = hour_key
        if kind != "proxy":
            out["lines"].append(line[:180])
    return out


def report(bot: dict, term: dict, label: str) -> int:
    total = bot["global"] + bot["proxy"]
    print(f"=== Баны BingX · {label} ===")
    print(f"боевой бот: всего {total} · ГЛОБАЛЬНЫХ {bot['global']} · на один прокси {bot['proxy']}")
    if bot["by_tf"]:
        print("по ТФ: " + " · ".join(f"{tf} {n}" for tf, n in bot["by_tf"].most_common()))
    if bot["by_hour"]:
        print("по часам: " + " · ".join(f"{h} {n}" for h, n in sorted(bot["by_hour"].items())))
    if bot["first"]:
        print(f"первое: {bot['first']} · последнее: {bot['last']}")
    print(f"терминал :8010 [LIMIT]: {term['limit']}")
    for line in bot["lines"][-5:]:
        print(f"  ⚠ {line}")
    verdict, code = [], 0
    if bot["global"]:
        verdict.append(f"🔴 ГЛОБАЛЬНЫЕ паузы {bot['global']} при цели 0 — данные встают целиком")
        code = 2
    if total > TARGET_BG_PER_DAY:
        verdict.append(f"🟡 фоновых {total} при августовской норме ≤{TARGET_BG_PER_DAY}/сутки")
        code = max(code, 1)
    if not verdict:
        verdict.append("✅ в пределах цели: глобальных 0, фоновый фон в августовской норме")
    print("\n".join(verdict))
    return code


def main() -> int:
    ap = argparse.ArgumentParser(description="суточный замер банов BingX (ARCH-153 п.4)")
    ap.add_argument("--hours", type=int, default=24, help="окно в часах (по умолчанию 24)")
    ap.add_argument("--day", default=None, help="конкретный день, формат 2026-10-30")
    args = ap.parse_args()
    label = args.day or f"последние {args.hours} ч"
    return report(collect(BOT, args.day, args.hours), collect(TERM, args.day, args.hours), label)


if __name__ == "__main__":
    raise SystemExit(main())
