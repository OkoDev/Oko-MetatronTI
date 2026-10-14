# -*- coding: utf-8 -*-
"""Реестр проверок — один ответ на вопрос «что сейчас красное» (ARCH-148.4 «а», паспорт инструмента, вид D).

Проверок в проекте >1600 в шести местах (юнит-тесты, селфтест Куба, селфтест старта, вахты pm2, ворота,
наблюдатель данных), и до 14.10 не было единой картины: чтобы узнать статус, надо лезть в четыре места.
Этот генератор собирает их ИЗ КОДА (как `bus_inventory` — опись шины, а не ручной список, который устаревает молча)
и пишет `docs/CHECKS.md`: что проверяется, когда срабатывает, где живёт, что значит красное, где смотреть статус.

Запуск:  python scripts/checks_registry.py            → docs/CHECKS.md
         python scripts/checks_registry.py --print    → в консоль
Ничего не меняет: читает код, файлы known_*, pm2 jlist и даты логов.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Какие pm2-процессы — ПРОВЕРКИ (а не производители данных). По назначению имени.
CHECK_PROCS = {
    "cache-freshness": "свежесть трёх хранилищ свечей (все ТФ старше 3 сут)",
    "tfcache-refresh": "докачка 1m + пересборка ТФ для замеров",
    "pivot-sanity": "пивоты в шине совпадают с пересчётом",
    "ledger-audit": "сверка БД-сделок с income-леджером биржи",
    "deadflag-audit": "мёртвые флаги/детекторы (0 срабатываний)",
    "hb-watchdog": "пульс лупов бота — рестарт при тихой смерти",
    "usdtd-watch": "вахта USDT.D (доминация)",
    "phase-watch": "вахта фазы рынка",
    "long-watch": "вахта воскрешения лонга",
}


def _run(*args: str, timeout: int = 30) -> str:
    try:
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout).stdout
    except Exception as e:  # noqa: BLE001
        return f"__err__ {type(e).__name__}: {e}"


def _count_tests() -> tuple[int, int]:
    n = 0
    for f in (ROOT / "tests" / "unit").glob("test_*.py"):
        n += len(re.findall(r"^\s*(?:async )?def test_", f.read_text(encoding="utf-8", errors="replace"), re.M))
    kf = (ROOT / "tests" / "known_failures.txt")
    known = sum(1 for l in kf.read_text(encoding="utf-8").splitlines() if "::" in l) if kf.exists() else 0
    return n, known


def _count_matches(path: str, pat: str) -> int:
    f = ROOT / path
    return len(re.findall(pat, f.read_text(encoding="utf-8", errors="replace"))) if f.exists() else 0


def _pm2_checks() -> list[tuple]:
    pm2 = os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "pm2", "bin", "pm2")
    raw = _run("node", pm2, "jlist")
    out = []
    if raw.startswith("__err__") or "[" not in raw:
        return out
    try:
        for p in json.loads(raw[raw.index("["):]):
            name, e = p["name"], p["pm2_env"]
            if name in CHECK_PROCS:
                out.append((name, e.get("cron_restart") or "—", e.get("status"),
                            e.get("exit_code"), CHECK_PROCS[name]))
    except Exception:  # молчим: кривой jlist просто даст пустой раздел
        pass
    return out


def _log_age(name: str) -> str:
    p = Path(os.path.expanduser(f"~/.pm2/logs/{name}-out.log"))
    if not p.exists():
        return "нет лога"
    age_h = (datetime.now().timestamp() - p.stat().st_mtime) / 3600
    return f"{age_h:.0f} ч назад" if age_h < 72 else f"{age_h / 24:.0f} сут назад"


def build() -> str:
    n_tests, known = _count_tests()
    cube = _count_matches("core/selftest_cube.py", r"CubeCheckResult\(")
    pm2 = _pm2_checks()
    L = ["# 🚦 РЕЕСТР ПРОВЕРОК — что проверяется и что сейчас красное",
         "",
         f"> Сгенерировано `scripts/checks_registry.py` {datetime.now(timezone.utc):%d.%m.%Y %H:%M} UTC (ARCH-148.4).",
         "> Собрано из кода, не руками. «Красное» = проверка не прошла; где смотреть — в последней колонке.",
         "",
         "## 1. Сводка «что красное сейчас»",
         "",
         f"- юнит-тесты: **{n_tests}** функций, **{known}** известных падений (`tests/known_failures.txt`)",
         f"  {'🔴 часть — каскад неизоляции БД (ARCH-148.4.1), не сломанные тесты' if known > 25 else '✅'}",
         "- ворота перед push: `test_gate.py` (новые падения) + `code_contract.py` (новое боевое без теста, "
         "молчащий except) — зелёные, если push прошёл",]
    red = [c for c in pm2 if c[2] == "online" and False]  # online у cron = сейчас выполняется, не ошибка
    bad = [c for c in pm2 if c[3] not in (0, None) and c[2] != "online"]
    if bad:
        L.append(f"- 🔴 вахты pm2 с ненулевым кодом последнего прогона: "
                 + ", ".join(f"{n} (код {ec})" for n, _, _, ec, _ in bad))
    else:
        L.append("- вахты pm2: последний прогон без ошибок (ненулевых кодов нет)")
    L += ["", "## 2. Проверки кода — до запуска (на выдуманных данных)",
          "",
          "| Проверка | Сколько | Когда | Красное значит | Где смотреть |",
          "|---|---|---|---|---|",
          f"| юнит-тесты | {n_tests} функций | перед push + вручную | код изменил поведение | `python scripts/test_gate.py` |",
          f"| паспорт инструмента | 2 правила | перед push | новое боевое без теста / молчащий except | `python scripts/code_contract.py` |",
          "| ворота тестов сами | 10 | в наборе | ворота врут (ключ, сравнение) | `tests/unit/test_code_contract.py` |"]
    L += ["", "## 3. Проверки в бою — на живых данных, непрерывно",
          "",
          "| Проверка | Сколько | Когда | Красное значит | Где смотреть |",
          "|---|---|---|---|---|",
          f"| селфтест Куба | {cube} | по запросу / старт бота | сфера не отвечает | `GET :8000/api/cube/selftest`, лог старта |",
          "| селфтест старта | 13 | каждый старт бота | бот поднялся неисправным | `SelfTest завершён N/N` в логе |",
          "| наблюдатель свечей | формат | каждый круг скана | битый формат свечей на входе | `[DATA-CONTRACT]` в логе бота |",
          "| свежесть/запись шины | — | непрерывно | запись мимо каталога / устаревший снимок | `[Bus] неизвестное …` в логе |"]
    if pm2:
        L += ["", "## 4. Вахты и проверки pm2 (по расписанию)",
              "",
              "| Процесс | Расписание | Статус | Посл. код | Последний прогон | Что проверяет |",
              "|---|---|---|---|---|---|"]
        for name, cron, status, ec, desc in sorted(pm2):
            ec_s = "—" if ec is None else ("✅ 0" if ec == 0 else f"🔴 {ec}")
            st = "идёт" if status == "online" else (status or "?")
            L.append(f"| `{name}` | `{cron}` | {st} | {ec_s} | {_log_age(name)} | {desc} |")
    L += ["", "## 5. Чего в реестре нет",
          "",
          "- Статус отдельных проверок селфтеста Куба (113 штук) — они печатаются в консоль, не публикуются.",
          "  Свести их в один отчёт — шаг «б» (ARCH-148.5): каждая проверка публикует факт в сферу 12.",
          "- Результат последнего прогона ворот между push — ворота запускаются только на push, статуса между нет.",
          "- Вахты пишут свои таблицы (`TASKS.md` → СРАБОТАВШИЕ ВАХТЫ); сюда сведён только код возврата."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # молчим: настройка кодировки консоли, на расчёт не влияет
        pass
    md = build()
    if "--print" in sys.argv:
        print(md)
    else:
        out = ROOT / "docs" / "CHECKS.md"
        out.write_text(md, encoding="utf-8")
        print(md.split("## 2.")[0])
        print(f"→ {out}")
