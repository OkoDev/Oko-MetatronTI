# -*- coding: utf-8 -*-
"""Дымовой тест спутников pm2 — ловит «молчит уже две недели» и «падает» (ARCH-148.6, паспорт инструмента, вид B/D).

Зачем. Тень волн молчала 14 дней, сбор ленты сделок — 20, а pm2 всё это время показывал процесс `online`:
демон жив, но давно ничего не производит. У cron-процессов обратное — `joint-daily` стоит с exit=1, и это
видно только если специально заглянуть в `pm2 list`. Единого ответа «кто из 44 процессов молчит или упал» не было.

Что делает. Берёт список процессов ИЗ pm2 (jlist, как `checks_registry`), не руками, и для КАЖДОГО судит:
  • cron/one-shot (autorestart=False): FAILED если последний прогон вышел с ненулевым кодом;
    STALE если out-лог не обновлялся дольше тройного интервала cron (ждём прогон — молчит);
  • демон (вечный луп): FAILED если pm2-статус не `online`; STALE если out-лог молчит дольше порога (по умолчанию
    24 ч) — демон «жив», но давно не писал (ровно случай тени волн и ленты сделок).
Сводка печатается таблицей и уходит фактом `satellite_smoke` в сферу 12 (как селфтест Куба — ARCH-148.5).

Активный прогон (по запросу, не в кроне): реально запускает процесс как pm2 — один цикл, проверяет exit 0 +
непустой вывод без Traceback. Тяжёлые 4 (качают данные / минуты) по умолчанию пропускаются, нужен `--heavy`.

Запуск:
    python scripts/pm2_smoke.py                 # пассивный аудит всех процессов → таблица + факт в сферу 12
    python scripts/pm2_smoke.py --print         # то же, без публикации факта
    python scripts/pm2_smoke.py --run NAME       # активно прогнать один процесс (цикл+выход)
    python scripts/pm2_smoke.py --run-all [--heavy]  # активно прогнать все лёгкие (с --heavy — и тяжёлые)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # для core.context.cube_client (факт в сферу 12)

# Тяжёлые: ходят в сеть / качают данные / идут минуты. В --run-all без --heavy пропускаются.
HEAVY = {"tfcache-refresh", "accum-scan", "forward-machine", "joint-daily"}

DAEMON_MAX_AGE_SEC = 24 * 3600  # демон, не писавший в лог дольше этого, подозрителен (silent death)
RUN_TIMEOUT_SEC = 180          # на активный прогон одного процесса


# ───────────────────── чистая логика (покрыта тестами) ─────────────────────
def reconstruct_cmd(pm_exec_path: str, args, exec_interpreter: str | None) -> list[str]:
    """Собирает команду запуска из полей pm2_env так же, как её запускает pm2.

    Два формата: `pm2 start x.py --interpreter python` (pm_exec_path=x.py, интерпретатор отдельно) и
    `pm2 start python -- scripts/x.py ...` (pm_exec_path=python, скрипт в args). Различаем по basename."""
    args = list(args or [])
    base = os.path.basename(pm_exec_path or "").lower()
    if base.startswith("python") or base in ("node.exe", "node"):
        return [pm_exec_path, *args]
    interp = exec_interpreter or sys.executable
    return [interp, pm_exec_path, *args]


def cron_period_seconds(cron: str | None) -> int | None:
    """Ожидаемый период cron в секундах (грубо, для порога свежести). None — не cron."""
    if not cron:
        return None
    f = cron.split()
    if len(f) != 5:
        return None
    minute, hour, _dom, _mon, dow = f
    if minute.startswith("*/"):
        return int(minute[2:]) * 60
    if minute == "*":
        return 60
    if hour.startswith("*/"):
        return int(hour[2:]) * 3600
    if hour == "*":
        return 3600          # каждый час в фикс. минуту
    if dow != "*":
        return 7 * 86400     # фиксированный день недели → раз в неделю
    return 86400             # фикс. час → раз в сутки


def fmt_age(sec: float | None) -> str:
    if sec is None:
        return "—"
    if sec < 3600:
        return f"{sec/60:.0f} мин"
    if sec < 86400:
        return f"{sec/3600:.1f} ч"
    return f"{sec/86400:.1f} сут"


def classify_proc(is_cron: bool, status: str, exit_code, log_age_sec: float | None,
                  period_sec: int | None, daemon_max_sec: int = DAEMON_MAX_AGE_SEC) -> tuple[str, str]:
    """Вердикт по одному процессу: (уровень, причина). Уровни: OK · FAILED · STALE · NOLOG."""
    if is_cron:
        if exit_code not in (0, None):
            return "FAILED", f"последний прогон exit={exit_code}"
        if log_age_sec is None:
            return "NOLOG", "нет out-лога"
        thr = max(period_sec * 3, 3600) if period_sec else 3 * 86400
        if log_age_sec > thr:
            return "STALE", f"лог молчит {fmt_age(log_age_sec)} (ждём ≤ {fmt_age(thr)})"
        return "OK", ""
    # демон
    if status != "online":
        return "FAILED", f"демон не online: {status}"
    if log_age_sec is None:
        return "NOLOG", "нет out-лога"
    if log_age_sec > daemon_max_sec:
        return "STALE", f"демон молчит {fmt_age(log_age_sec)} (порог {fmt_age(daemon_max_sec)})"
    return "OK", ""


def active_verdict(exit_code: int, stdout: str, timed_out: bool) -> tuple[str, str]:
    """Вердикт активного прогона: цикл прошёл, вывод есть, нет трейсбека."""
    if timed_out:
        return "TIMEOUT", f"не завершился за {RUN_TIMEOUT_SEC} с"
    if exit_code != 0:
        return "FAILED", f"exit={exit_code}"
    if "Traceback (most recent call last)" in stdout:
        return "FAILED", "Traceback в выводе"
    if not stdout.strip():
        return "SILENT", "пустой вывод (ни строки итога)"
    return "OK", ""


# ───────────────────── ввод-вывод (тонкие обёртки) ─────────────────────
def _pm2_jlist() -> list[dict]:
    pm2 = os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "pm2", "bin", "pm2")
    raw = subprocess.run(["node", pm2, "jlist"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=30).stdout
    return json.loads(raw[raw.index("["):])


def freshest_log_age(paths: list[str | None]) -> float | None:
    """Возраст самого свежего из логов процесса. Пустые (size 0) и отсутствующие пропускаем: часть демонов
    пишет только в out, часть — только в err (проверено 14.10: oko-api пишет в err, out пустой 103 сут).
    None — ни одного непустого лога."""
    ages = []
    for p in paths:
        if p and os.path.exists(p) and os.path.getsize(p) > 0:
            ages.append(time.time() - os.path.getmtime(p))
    return min(ages) if ages else None


SELF_NAME = "pm2-smoke"  # сам смоук из аудита исключаем: он выходит exit=1, КОГДА находит красный,
                         # иначе следующий прогон пометил бы FAILED его самого (ложная самоссылка)


def collect() -> list[dict]:
    """Список процессов с полями для аудита и активного прогона."""
    out = []
    for p in _pm2_jlist():
        if p["name"] == SELF_NAME:
            continue
        e = p["pm2_env"]
        is_cron = bool(e.get("cron_restart")) or e.get("autorestart") is False
        out.append({
            "name": p["name"],
            "is_cron": is_cron,
            "cron": e.get("cron_restart"),
            "status": e.get("status"),
            "exit_code": e.get("exit_code"),
            "cmd": reconstruct_cmd(e.get("pm_exec_path", ""), e.get("args"), e.get("exec_interpreter")),
            "cwd": e.get("pm_cwd") or str(ROOT),
            "logs": [e.get("pm_out_log_path"), e.get("pm_err_log_path")],
        })
    return sorted(out, key=lambda x: x["name"])


def audit() -> dict:
    procs = collect()
    rows = []
    for p in procs:
        level, reason = classify_proc(p["is_cron"], p["status"], p["exit_code"],
                                      freshest_log_age(p["logs"]), cron_period_seconds(p["cron"]))
        rows.append({"name": p["name"], "kind": "cron" if p["is_cron"] else "демон",
                     "level": level, "reason": reason})
    red = [f'{r["name"]}: {r["reason"]}' for r in rows if r["level"] in ("FAILED", "STALE", "NOLOG")]
    return {
        "total": len(rows),
        "ok": sum(r["level"] == "OK" for r in rows),
        "failed": sum(r["level"] == "FAILED" for r in rows),
        "stale": sum(r["level"] == "STALE" for r in rows),
        "nolog": sum(r["level"] == "NOLOG" for r in rows),
        "red_list": red[:40],
        "rows": rows,
    }


def run_one(p: dict, timeout: int = RUN_TIMEOUT_SEC) -> dict:
    t0 = time.time()
    timed_out = False
    try:
        r = subprocess.run(p["cmd"], cwd=p["cwd"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        exit_code, stdout = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        timed_out, exit_code, stdout = True, -1, ""
    level, reason = active_verdict(exit_code, stdout, timed_out)
    return {"name": p["name"], "level": level, "reason": reason,
            "dur": time.time() - t0, "exit": exit_code}


def publish(summary: dict, mode: str) -> bool:
    try:
        from core.context import cube_client
        from core.context.pair_context import SphereEvent
        from datetime import datetime, timezone
        data = {k: summary[k] for k in ("total", "ok", "failed", "stale", "nolog", "red_list")}
        data["mode"] = mode
        data["ts"] = datetime.now(timezone.utc).isoformat()
        return cube_client.publish(SphereEvent.SATELLITE_SMOKE, "*SATELLITES*", data, producer="pm2-smoke")
    except Exception as ex:  # молчим: хаб недоступен — факт не уйдёт, но таблица уже напечатана
        print(f"(факт в сферу 12 не ушёл: {type(ex).__name__}: {ex})")
        return False


_MARK = {"OK": "✅", "FAILED": "🔴", "STALE": "🟡", "NOLOG": "⚪", "TIMEOUT": "⏱", "SILENT": "🟡"}


def _print_audit(s: dict) -> None:
    print("🚦 Дымовой аудит спутников pm2 (пассивный — без запуска)\n")
    for r in s["rows"]:
        tail = f" — {r['reason']}" if r["reason"] else ""
        print(f"  {_MARK.get(r['level'],'?')} {r['name']:<20} [{r['kind']}]{tail}")
    print(f"\nИтог: {s['total']} процессов · ✅ {s['ok']} · 🔴 {s['failed']} · 🟡 {s['stale']} · ⚪ {s['nolog']}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # молчим: настройка кодировки консоли, на результат не влияет
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="не публиковать факт в сферу 12")
    ap.add_argument("--run", metavar="NAME", help="активно прогнать один процесс (цикл+выход)")
    ap.add_argument("--run-all", action="store_true", help="активно прогнать все лёгкие процессы")
    ap.add_argument("--heavy", action="store_true", help="с --run-all: включить тяжёлые (сеть/минуты)")
    args = ap.parse_args()

    if args.run or args.run_all:
        procs = {p["name"]: p for p in collect()}
        if args.run:
            if args.run not in procs:
                print(f"🔴 нет процесса '{args.run}' в pm2")
                return 1
            targets = [procs[args.run]]
        else:
            targets = [p for n, p in sorted(procs.items()) if p["is_cron"] and (args.heavy or n not in HEAVY)]
        print(f"⚙️ Активный прогон: {len(targets)} процессов (таймаут {RUN_TIMEOUT_SEC} с/шт)\n")
        res = [run_one(p) for p in targets]
        for r in res:
            tail = f" — {r['reason']}" if r["reason"] else ""
            print(f"  {_MARK.get(r['level'],'?')} {r['name']:<20} {r['dur']:.0f}с{tail}")
        bad = sum(r["level"] not in ("OK",) for r in res)
        print(f"\nИтог: {len(res)} прогнано · 🔴 {bad} не прошли")
        return 1 if bad else 0

    s = audit()
    _print_audit(s)
    if not args.print:
        publish(s, mode="passive")
    # exit 1 только на ЖЁСТКОМ (упал/демон не online). STALE и NOLOG — advisory (⚪ «нет улик»):
    # сразу после общего рестарта логи пусты, падать на этом = шуметь каждый раз.
    return 1 if s["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
