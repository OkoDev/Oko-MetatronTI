"""Weekly Digest — автоматический недельный дайджест проекта Oko MTF.

Агрегирует за последние 7 дней:
  - Метрики из БД (avgR, WR, signal_type breakdown, аномалии)
  - Закрытые/открытые задачи из TASKS.md
  - Коммиты из git log
  - Открытые вопросы из session_brief.md

Output:
  obsidian/Digests/YYYY-WNN.md   ← читают агенты при старте сессии
  memory/last_weekly_digest.md   ← быстрый доступ

Запуск:
  python tools/weekly_digest.py
  python tools/weekly_digest.py --days 14   # расширить окно
  python tools/weekly_digest.py --out e:/tmp/digest.md
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "subscriptions.db"
OUTPUT_DIR = PROJECT_ROOT / "obsidian" / "Digests"
OUTPUT_MEMORY = PROJECT_ROOT / "memory" / "last_weekly_digest.md"

TASKS_FILE = PROJECT_ROOT / "TASKS.md"
BRIEF_FILE = PROJECT_ROOT / "memory" / "session_brief.md"
TRADE_REVIEW_FILE = PROJECT_ROOT / "memory" / "last_trade_review.md"


def week_label(dt: datetime) -> str:
    return f"{dt.year}-W{dt.isocalendar()[1]:02d}"


def get_db_metrics(since: datetime) -> dict:
    if not DB_PATH.exists():
        return {}
    since_str = since.strftime("%Y-%m-%d")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Общие метрики
    cur.execute("""
        SELECT COUNT(*), AVG(R_multiple),
               SUM(CASE WHEN R_multiple > 0 THEN 1 ELSE 0 END)
        FROM simulated_trades
        WHERE closed_at >= ? AND status IN ('TP','SL','TSL','EXPIRED')
          AND R_multiple IS NOT NULL
    """, (since_str,))
    row = cur.fetchone()
    n_closed = row[0] or 0
    avg_r = round(row[1], 3) if row[1] is not None else None
    n_win = row[2] or 0
    wr = round(n_win / n_closed * 100, 1) if n_closed > 0 else None

    # По signal_type
    cur.execute("""
        SELECT signal_type, COUNT(*), AVG(R_multiple)
        FROM simulated_trades
        WHERE closed_at >= ? AND status IN ('TP','SL','TSL','EXPIRED')
          AND R_multiple IS NOT NULL
        GROUP BY signal_type ORDER BY AVG(R_multiple) DESC
    """, (since_str,))
    by_signal = [(r[0], r[1], round(r[2], 3)) for r in cur.fetchall()]

    # Аномалии R < -1.5
    cur.execute("""
        SELECT id, symbol, signal_type, R_multiple, closed_at, direction
        FROM simulated_trades
        WHERE closed_at >= ? AND R_multiple < -1.5
        ORDER BY R_multiple ASC LIMIT 10
    """, (since_str,))
    anomalies = cur.fetchall()

    # Открытых сделок сейчас
    cur.execute("SELECT COUNT(*) FROM simulated_trades WHERE status='OPEN'")
    n_open = cur.fetchone()[0]

    # source_router breakdown (если поле есть)
    by_router = []
    try:
        cur.execute("""
            SELECT source_router, COUNT(*), AVG(R_multiple)
            FROM simulated_trades
            WHERE closed_at >= ? AND status IN ('TP','SL','TSL','EXPIRED')
              AND R_multiple IS NOT NULL AND source_router IS NOT NULL
            GROUP BY source_router ORDER BY COUNT(*) DESC
        """, (since_str,))
        by_router = [(r[0], r[1], round(r[2], 3) if r[2] is not None else None)
                     for r in cur.fetchall()]
    except Exception:
        pass

    con.close()
    return {
        "n_closed": n_closed, "avg_r": avg_r, "wr": wr, "n_open": n_open,
        "by_signal": by_signal, "anomalies": anomalies, "by_router": by_router,
    }


def get_git_log(days: int) -> list[str]:
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        r = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "log",
             f"--since={since}", "--oneline", "--no-merges", "-n", "50"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        return r.stdout.strip().splitlines() if r.returncode == 0 else []
    except Exception:
        return []


def extract_open_questions(brief_path: Path) -> list[str]:
    if not brief_path.exists():
        return []
    text = brief_path.read_text(encoding="utf-8", errors="replace")
    questions = []
    in_section = False
    for line in text.splitlines():
        if "открыт" in line.lower() and ("вопрос" in line.lower() or "##" in line):
            in_section = True
            continue
        if in_section:
            if line.startswith("##"):
                break
            if line.strip().startswith(("-", "*", "→", "•")):
                questions.append(line.strip().lstrip("-*→• "))
    return questions[:8]


def extract_active_tasks(tasks_path: Path) -> tuple[list[str], list[str]]:
    if not tasks_path.exists():
        return [], []
    text = tasks_path.read_text(encoding="utf-8", errors="replace")
    active, done_recent = [], []
    for line in text.splitlines():
        if "🔄" in line or "🔴" in line:
            m = re.search(r"\[?(DEV|ARCH|TR)-[\w\.\-]+\]?", line)
            desc = re.sub(r"\|+", " ", line).strip()
            desc = re.sub(r"\s+", " ", desc)
            if m and len(desc) > 5:
                active.append(f"{m.group(0)}: {desc[:100]}")
        if "✅" in line and re.search(r"(DEV|ARCH|TR)-\w+", line):
            m = re.search(r"(DEV|ARCH|TR)-[\w\.\-]+", line)
            if m:
                done_recent.append(m.group(0))
    return active[:8], done_recent[:6]


def build_digest(days: int) -> str:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    week = week_label(now)
    date_from = since.strftime("%Y-%m-%d")
    date_to = now.strftime("%Y-%m-%d")

    metrics = get_db_metrics(since)
    commits = get_git_log(days)
    questions = extract_open_questions(BRIEF_FILE)
    active_tasks, done_tasks = extract_active_tasks(TASKS_FILE)

    lines = []
    lines.append(f"---")
    lines.append(f"week: {week}")
    lines.append(f"period: {date_from} → {date_to}")
    lines.append(f"days: {days}")
    lines.append(f'parent: "[[Project-MOC]]"')
    month_str = now.strftime("%Y-%m")
    lines.append(f'month: "[[Months/{month_str}]]"')
    lines.append(f"tags: [digest, weekly, auto]")
    lines.append(f"generated: {now.strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"# Недельный дайджест {week} ({date_from} → {date_to})")
    lines.append(f"")

    # Метрики
    lines.append(f"## 📊 Метрики за {days} дней")
    if metrics.get("n_closed"):
        lines.append(f"- Закрыто сделок: **{metrics['n_closed']}**")
        lines.append(f"- avgR: **{metrics['avg_r']}**")
        lines.append(f"- WR: **{metrics['wr']}%**")
        lines.append(f"- Открытых сейчас: {metrics['n_open']}")
    else:
        lines.append("- Данных за период нет")
    lines.append("")

    # По signal_type
    if metrics.get("by_signal"):
        lines.append("## 📈 По signal_type")
        lines.append("| signal_type | n | avgR |")
        lines.append("|---|---|---|")
        for sig, n, avg in metrics["by_signal"]:
            emoji = "✅" if avg and avg > 0 else "❌"
            lines.append(f"| {sig} | {n} | {emoji} {avg} |")
        lines.append("")

    # По source_router
    if metrics.get("by_router"):
        lines.append("## 🔀 По source_router")
        lines.append("| router | n | avgR |")
        lines.append("|---|---|---|")
        for rtr, n, avg in metrics["by_router"]:
            emoji = "✅" if avg and avg > 0 else "❌"
            lines.append(f"| {rtr} | {n} | {emoji} {avg} |")
        lines.append("")

    # Аномалии
    if metrics.get("anomalies"):
        lines.append("## ⚠️ Аномалии (R < −1.5)")
        lines.append("| id | symbol | signal_type | R | dir | дата |")
        lines.append("|---|---|---|---|---|---|")
        for trade_id, sym, sig, r, dt, direction in metrics["anomalies"]:
            dt_short = str(dt)[:16] if dt else "?"
            lines.append(f"| {trade_id} | {sym} | {sig} | {round(r,2)} | {direction} | {dt_short} |")
        lines.append("")

    # Активные задачи
    if active_tasks:
        lines.append("## 🔄 В работе")
        for t in active_tasks:
            lines.append(f"- {t}")
        lines.append("")

    # Закрытые
    if done_tasks:
        lines.append("## ✅ Недавно закрыто")
        lines.append(", ".join(f"[[{t}]]" for t in done_tasks))
        lines.append("")

    # Открытые вопросы
    if questions:
        lines.append("## ❓ Открытые вопросы")
        for q in questions:
            lines.append(f"- {q}")
        lines.append("")

    # Коммиты
    if commits:
        lines.append("## 🔧 Коммиты за период")
        for c in commits[:15]:
            lines.append(f"- `{c}`")
        lines.append("")

    lines.append(f"---")
    lines.append(f"*Автогенерация `tools/weekly_digest.py` · {now.strftime('%Y-%m-%d %H:%M')} UTC*")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate weekly digest for Obsidian")
    parser.add_argument("--days", type=int, default=7, help="Окно в днях (default: 7)")
    parser.add_argument("--out", type=Path, help="Путь вывода (override)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    week = week_label(now)

    out_path = args.out or (OUTPUT_DIR / f"{week}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    digest = build_digest(args.days)

    out_path.write_text(digest, encoding="utf-8")
    OUTPUT_MEMORY.write_text(digest, encoding="utf-8")

    if not args.quiet:
        print(f"[weekly-digest] OK")
        print(f"  week:   {week}")
        print(f"  period: последние {args.days} дней")
        print(f"  -> {out_path}")
        print(f"  -> {OUTPUT_MEMORY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
