"""Daily Pipeline — генерирует ежедневный хаб Sessions/YYYY-MM-DD.md.

Агрегирует за последние 24 часа:
  - Метрики из БД (avgR, WR, signal_type breakdown, аномалии)
  - Обсуждения из DISCUSSION.md (новые записи за сутки)
  - Открытые вопросы из session_brief.md
  - Коммиты из git log
  - Изменения архитектурных файлов (arch_diff)

Output:
  obsidian/Sessions/YYYY-MM-DD.md

Запуск:
  python tools/daily_pipeline.py              # сегодня
  python tools/daily_pipeline.py --date 2026-05-15   # конкретный день
  python tools/daily_pipeline.py --hours 48   # последние 48ч
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
OUTPUT_DIR = PROJECT_ROOT / "obsidian" / "Sessions"
DISCUSSION_FILE = PROJECT_ROOT / "DISCUSSION.md"
BRIEF_FILE = PROJECT_ROOT / "memory" / "session_brief.md"


def get_db_metrics(since: datetime) -> dict:
    if not DB_PATH.exists():
        return {}
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
        SELECT COUNT(*), AVG(R_multiple),
               SUM(CASE WHEN R_multiple > 0 THEN 1 ELSE 0 END)
        FROM simulated_trades
        WHERE closed_at >= ? AND status IN ('TP','SL','TSL','EXPIRED')
          AND R_multiple IS NOT NULL
    """, (since_str,))
    row = cur.fetchone()
    n, avg_r, n_win = row[0] or 0, row[1], row[2] or 0
    wr = round(n_win / max(n, 1) * 100, 1) if n > 0 else None

    cur.execute("""
        SELECT signal_type, COUNT(*), AVG(R_multiple)
        FROM simulated_trades
        WHERE closed_at >= ? AND status IN ('TP','SL','TSL','EXPIRED')
          AND R_multiple IS NOT NULL
        GROUP BY signal_type ORDER BY AVG(R_multiple) DESC
    """, (since_str,))
    by_signal = [(r[0], r[1], round(r[2], 3)) for r in cur.fetchall()]

    cur.execute("""
        SELECT id, symbol, signal_type, R_multiple, direction, closed_at
        FROM simulated_trades
        WHERE closed_at >= ? AND R_multiple < -2.0
        ORDER BY R_multiple ASC LIMIT 8
    """, (since_str,))
    anomalies = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM simulated_trades WHERE status='OPEN'")
    n_open = cur.fetchone()[0]

    con.close()
    return {
        "n": n, "avg_r": round(avg_r, 3) if avg_r else None,
        "wr": wr, "n_open": n_open,
        "by_signal": by_signal, "anomalies": anomalies,
    }


def extract_discussion_entries(since: datetime) -> list[str]:
    if not DISCUSSION_FILE.exists():
        return []
    text = DISCUSSION_FILE.read_text(encoding="utf-8", errors="replace")
    entries = []
    # Ищем заголовки записей с датой/временем
    date_pattern = re.compile(
        r"###\s*\[(\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2})[^\]]*\]"
    )
    lines = text.splitlines()
    current_date = None
    current_block = []

    for line in lines:
        m = date_pattern.match(line)
        if m:
            # Сохраняем предыдущий блок
            if current_date and current_block:
                try:
                    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
                        try:
                            dt = datetime.strptime(current_date, fmt).replace(tzinfo=timezone.utc)
                            break
                        except ValueError:
                            continue
                    if dt >= since:
                        entries.append(f"**[{current_date}]** " + " ".join(current_block[:3]))
                except Exception:
                    pass
            date_str = m.group(1)
            current_date = date_str
            current_block = []
        elif current_date and line.strip() and not line.startswith("---"):
            current_block.append(line.strip()[:100])

    return entries[-10:]


def get_arch_diff(since: datetime) -> list[str]:
    """Коммиты затронувшие архитектурные файлы."""
    try:
        since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "log",
             f"--since={since_str}", "--oneline", "--no-merges",
             "--", "docs/ARCHITECTURE.md", "docs/ENCYCLOPEDIA.md",
             "core/", "bot/loops/", "bot/core/"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        return result.stdout.strip().splitlines() if result.returncode == 0 else []
    except Exception:
        return []


def get_git_commits(since: datetime) -> list[str]:
    try:
        since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "log",
             f"--since={since_str}", "--oneline", "--no-merges", "-n", "20"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        return result.stdout.strip().splitlines() if result.returncode == 0 else []
    except Exception:
        return []


def build_session(date: datetime, hours: int) -> str:
    since = date - timedelta(hours=hours)
    date_str = date.strftime("%Y-%m-%d")
    since_str = since.strftime("%Y-%m-%d %H:%M")

    metrics = get_db_metrics(since)
    discussions = extract_discussion_entries(since)
    arch_commits = get_arch_diff(since)
    all_commits = get_git_commits(since)

    lines = [
        "---",
        f"date: {date_str}",
        f"hours: {hours}",
        f"since: {since_str}",
    ]
    if metrics.get("avg_r") is not None:
        lines.append(f"avgR: {metrics['avg_r']}")
    if metrics.get("wr") is not None:
        lines.append(f"WR: {metrics['wr']}")
    lines += [
        f'parent: "[[Project-MOC]]"',
        f'month: "[[Months/{date.strftime("%Y-%m")}]]"',
        "tags: [session, daily, auto]",
        f"generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
        "---",
        "",
        f"# Session {date_str}",
        f"> Период: последние {hours}ч (с {since_str} UTC)",
        "",
    ]

    # Метрики
    lines.append("## 📊 Метрики")
    if metrics.get("n"):
        avg_r = metrics["avg_r"]
        emoji = "✅" if avg_r and avg_r > 0 else "❌"
        lines += [
            f"- Закрыто: **{metrics['n']}** | avgR: **{emoji} {avg_r}** | WR: **{metrics['wr']}%**",
            f"- Открытых: {metrics['n_open']}",
        ]
    else:
        lines.append("- Нет закрытых сделок за период")
    lines.append("")

    # По signal_type
    if metrics.get("by_signal"):
        lines.append("## 📈 По signal_type")
        lines.append("| signal_type | n | avgR |")
        lines.append("|---|---|---|")
        for sig, n, avg in metrics["by_signal"]:
            e = "✅" if avg > 0 else "❌"
            lines.append(f"| {sig} | {n} | {e} {avg} |")
        lines.append("")

    # Аномалии
    if metrics.get("anomalies"):
        lines.append("## ⚠️ Аномалии (R < −2.0)")
        lines.append("| id | symbol | signal_type | R | dir |")
        lines.append("|---|---|---|---|---|")
        for tid, sym, sig, r, direction, _ in metrics["anomalies"]:
            lines.append(f"| {tid} | {sym} | {sig} | {round(r, 2)} | {direction} |")
        lines.append("")

    # Архитектурные изменения
    if arch_commits:
        lines.append("## 🏗️ Архитектурные изменения")
        for c in arch_commits[:8]:
            lines.append(f"- `{c}`")
        lines.append("")

    # Обсуждения
    if discussions:
        lines.append("## 🗣️ Обсуждения")
        for d in discussions:
            lines.append(f"- {d}")
        lines.append("")

    # Все коммиты
    if all_commits:
        lines.append("## 🔧 Коммиты")
        for c in all_commits[:10]:
            lines.append(f"- `{c}`")
        lines.append("")

    lines.append("---")
    lines.append(f"*Автогенерация `tools/daily_pipeline.py` · "
                 f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC*")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate daily Obsidian session hub")
    parser.add_argument("--date", help="Дата YYYY-MM-DD (default: сегодня)")
    parser.add_argument("--hours", type=int, default=24, help="Окно в часах (default: 24)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.date:
        date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        date = datetime.now(timezone.utc)

    date_str = date.strftime("%Y-%m-%d")
    out_path = OUTPUT_DIR / f"{date_str}.md"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    session = build_session(date, args.hours)
    out_path.write_text(session, encoding="utf-8")

    if not args.quiet:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        print(f"[daily-pipeline] OK")
        print(f"  date:  {date_str}")
        print(f"  hours: {args.hours}")
        print(f"  -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
