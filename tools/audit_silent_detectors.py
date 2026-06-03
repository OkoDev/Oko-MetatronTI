"""Audit Silent Detectors — мониторинг 4 типов сигналов которые могут замолчать.

Контекст: bot-data-audit 16.05 нашёл что confluence/anomaly/wt_b_signal/divergence
могут тихо переставать давать сделки из-за разных причин (баг ключа, конфликт cooldown, гейты).

Что делает:
  - Находит время последнего рестарта бота (из logs/llm_hooks.log)
  - По 4 типам считает: всего, before_restart_24h, after_restart, last_trade, avgR, statuses
  - Печатает таблицу с before/after сравнением
  - --team: сразу шлёт результат в /team-ask для оценки

Запуск:
  python tools/audit_silent_detectors.py                # просто отчёт
  python tools/audit_silent_detectors.py --team         # + командное обсуждение
  python tools/audit_silent_detectors.py --since-hours 12   # окно "after" вручную
  python tools/audit_silent_detectors.py --types confluence,anomaly  # выборочно

Output:
  stdout — табличный отчёт
  memory/last_detectors_audit.md — для последующего использования
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "subscriptions.db"
LOG_HOOKS = PROJECT_ROOT / "logs" / "llm_hooks.log"
OUTPUT_MEMORY = PROJECT_ROOT / "memory" / "last_detectors_audit.md"

DEFAULT_TYPES = ["confluence", "anomaly", "wt_b_signal", "divergence"]

RESTART_RE = re.compile(r"^=== (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})[\.\d]* bot startup ===")


def find_last_restart() -> datetime | None:
    """Возвращает datetime последнего bot startup из llm_hooks.log."""
    if not LOG_HOOKS.exists():
        return None
    last = None
    with LOG_HOOKS.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = RESTART_RE.match(line.strip())
            if m:
                try:
                    # llm_hooks.log пишет local МСК (+3); created_at в БД — UTC.
                    # Парсим как МСК → конвертируем в UTC (feedback_db_query_utc).
                    # Баг до 03.06: помечалось tzinfo=utc без конверсии → якорь +3ч в будущее.
                    last = (datetime.fromisoformat(m.group(1))
                            .replace(tzinfo=timezone(timedelta(hours=3)))
                            .astimezone(timezone.utc))
                except ValueError:
                    continue
    return last


def stats_for_signal(conn, signal_type: str, restart_ts: datetime) -> dict:
    """Возвращает срез метрик для одного signal_type."""
    cur = conn.cursor()
    restart_str = restart_ts.strftime("%Y-%m-%d %H:%M:%S")
    before_24h_start = (restart_ts - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    def _count(cond: str, params: tuple) -> int:
        return cur.execute(f"SELECT COUNT(*) FROM simulated_trades WHERE signal_type=? {cond}",
                           (signal_type, *params)).fetchone()[0]

    total = _count("", ())
    n_before = _count("AND created_at >= ? AND created_at < ?", (before_24h_start, restart_str))
    n_after = _count("AND created_at >= ?", (restart_str,))

    last_row = cur.execute(
        "SELECT id, symbol, created_at, status, R_multiple, source_router "
        "FROM simulated_trades WHERE signal_type=? ORDER BY id DESC LIMIT 1",
        (signal_type,),
    ).fetchone()

    # avgR за всё время и after
    avgR_total = cur.execute(
        "SELECT AVG(R_multiple) FROM simulated_trades WHERE signal_type=? AND R_multiple IS NOT NULL",
        (signal_type,),
    ).fetchone()[0]
    avgR_after = cur.execute(
        "SELECT AVG(R_multiple) FROM simulated_trades WHERE signal_type=? AND R_multiple IS NOT NULL AND created_at >= ?",
        (signal_type, restart_str),
    ).fetchone()[0]

    # status distribution after
    statuses_after = dict(cur.execute(
        "SELECT status, COUNT(*) FROM simulated_trades WHERE signal_type=? AND created_at >= ? GROUP BY status",
        (signal_type, restart_str),
    ).fetchall())

    return {
        "total": total,
        "before_24h": n_before,
        "after_restart": n_after,
        "last_trade": last_row,
        "avgR_total": avgR_total,
        "avgR_after": avgR_after,
        "statuses_after": statuses_after,
    }


def render_report(restart_ts: datetime, results: dict, since_hours: float | None) -> str:
    lines = []
    now = datetime.now(timezone.utc)
    elapsed = (now - restart_ts).total_seconds() / 3600

    lines.append(f"# Audit Silent Detectors — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append(f"**Рестарт бота:** {restart_ts.strftime('%Y-%m-%d %H:%M:%S UTC')} ({elapsed:.1f}ч назад)")
    if since_hours:
        lines.append(f"**Окно `after` (override):** {since_hours:.1f}ч")
    lines.append("")
    lines.append("## Сводная таблица")
    lines.append("")
    lines.append("| Signal Type | Total all-time | Before (24ч до рестарта) | **After (с рестарта)** | Скорость after | Last trade | avgR after |")
    lines.append("|---|---:|---:|---:|---|---|---:|")

    for sig, s in results.items():
        last = s["last_trade"]
        last_str = f"#{last[0]} {last[1]} ({last[2][:16]})" if last else "—"
        speed = f"{s['after_restart'] / max(elapsed, 0.1):.1f}/ч" if s["after_restart"] > 0 else "0/ч"
        avgR_after = f"{s['avgR_after']:+.3f}" if s['avgR_after'] is not None else "—"
        mark = "🔴" if s["after_restart"] == 0 and elapsed >= 1 else "✅" if s["after_restart"] > 0 else "⏳"
        lines.append(f"| {mark} **{sig}** | {s['total']} | {s['before_24h']} | **{s['after_restart']}** | {speed} | {last_str} | {avgR_after} |")

    lines.append("")
    lines.append("## Распределение по status (after restart)")
    for sig, s in results.items():
        if s["statuses_after"]:
            stat_str = ", ".join(f"{k}={v}" for k, v in s["statuses_after"].items())
            lines.append(f"- **{sig}:** {stat_str}")

    lines.append("")
    lines.append("## Легенда")
    lines.append("- ✅ детектор работает (после рестарта есть сделки)")
    lines.append("- 🔴 детектор молчит >1ч после рестарта (потенциально проблема)")
    lines.append("- ⏳ слишком рано судить (<1ч с рестарта)")

    return "\n".join(lines)


def send_to_team(report: str, restart_ts: datetime) -> int:
    """Шлёт отчёт в /team-ask для оценки командой."""
    print("\n[audit] отправляю отчёт в команду через /team-ask...", file=sys.stderr)
    # Сохраним отчёт во временный файл для --file
    tmp = PROJECT_ROOT / "memory" / "last_detectors_audit.md"
    tmp.write_text(report, encoding="utf-8")

    question = (
        f"После рестарта бота {restart_ts.strftime('%H:%M UTC')} (16.05.2026) применены 2 фикса: "
        "(1) confluence ключ конфига (был баг — детектор отключён 4 дня), "
        "(2) anomaly per-signal_type cooldown (anomaly теперь игнорирует SL от wt_sideways). "
        "Оцените текущую динамику по 4 'тихим' типам (confluence/anomaly/wt_b_signal/divergence): "
        "(а) фиксы реально работают или есть скрытые блокеры; "
        "(б) что отслеживать в ближайшие 6-12 часов; "
        "(в) когда можно сказать что фиксы успешны."
    )

    cmd = [
        sys.executable, str(PROJECT_ROOT / "tools" / "team_ask.py"),
        question, "--file", str(tmp),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=300)
    print(result.stdout, file=sys.stderr)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Аудит 4 'тихих' детекторов после рестарта")
    parser.add_argument("--types", default=",".join(DEFAULT_TYPES),
                        help="Через запятую (default: confluence,anomaly,wt_b_signal,divergence)")
    parser.add_argument("--since-hours", type=float,
                        help="Override окна 'after' в часах (иначе берётся время рестарта)")
    parser.add_argument("--team", action="store_true", help="После отчёта запустить /team-ask")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not DB_PATH.exists():
        print(f"[audit] ERROR: {DB_PATH} не найден", file=sys.stderr)
        return 1

    # Время рестарта
    if args.since_hours:
        restart_ts = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
        print(f"[audit] окно override: с {restart_ts.isoformat()} ({args.since_hours}ч назад)", file=sys.stderr)
    else:
        restart_ts = find_last_restart()
        if restart_ts is None:
            print("[audit] WARN: не нашёл рестарт в logs/llm_hooks.log, fallback на -2ч",
                  file=sys.stderr)
            restart_ts = datetime.now(timezone.utc) - timedelta(hours=2)

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    print(f"[audit] анализ: {', '.join(types)}", file=sys.stderr)
    print(f"[audit] рестарт: {restart_ts.isoformat()}", file=sys.stderr)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        results = {sig: stats_for_signal(conn, sig, restart_ts) for sig in types}
    finally:
        conn.close()

    report = render_report(restart_ts, results, args.since_hours)
    print()
    print(report)

    OUTPUT_MEMORY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MEMORY.write_text(report, encoding="utf-8")
    print(f"\n[audit] → {OUTPUT_MEMORY}", file=sys.stderr)

    if args.team:
        return send_to_team(report, restart_ts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
