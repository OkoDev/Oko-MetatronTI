"""Task Linker — автосвязь задач DEV/ARCH/TR с сделками в БД.

Логика: авто по signal_type + дате.
  1. Парсит TASKS.md + TASKS-ARCHIVE.md → список задач с датой и описанием
  2. Keyword matching описания → signal_type (atr_change, wt_signal, pivot_reversal, ...)
  3. Запрашивает БД: сделки с этим signal_type после даты задачи
  4. Дописывает секцию "## 📊 Связанные сделки" в obsidian/Tasks/<ID>.md

Запуск:
  python tools/task_linker.py              # все задачи с досье
  python tools/task_linker.py DEV-199      # конкретная задача
  python tools/task_linker.py --dry-run    # только вывод, без записи
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "subscriptions.db"
TASKS_FILES = [PROJECT_ROOT / "TASKS.md", PROJECT_ROOT / "TASKS-ARCHIVE.md"]
OBSIDIAN_TASKS_DIR = PROJECT_ROOT / "obsidian" / "Tasks"

# Keyword → signal_type маппинг (порядок важен: более специфичные — первыми)
SIGNAL_KEYWORDS: list[tuple[list[str], str]] = [
    (["atr_change_15m", "ote zone", "ote trigger", "15m.*ote", "ote.*15m"], "atr_change"),
    (["atr.change", "atr trend change", "atr_change", "supertrend", "trend change"], "atr_change"),
    (["wt_sideways", "wt sideways", "sideways.*wt", "волновой трейд"], "wt_sideways"),
    (["wt_signal", "wt signal", "wt_b", "wt_b_signal", "волновой сигнал"], "wt_signal"),
    (["pivot_reversal", "pivot reversal", "pivot.*reversal", "разворот.*пивот"], "pivot_reversal"),
    (["watch_list_breach", "wl_breach", "watch list breach", "watchlist"], "watch_list_breach"),
    (["confluence", "multi.signal", "multi signal"], "confluence"),
    (["mtf_bias", "mtf bias", "multi.*timeframe.*bias"], "mtf_bias"),
    (["divergence", "дивергенц"], "divergence"),
]

# Задачи которые связаны с SL/risk, не с signal_type
RISK_TASK_KEYWORDS = ["slippage", "stop.loss", "stop_loss", "sl_limit", "overshoot",
                      "catastrophic", "watchdog", "volume whitelist", "sl_cooldown"]


def parse_task_date(context: str) -> datetime | None:
    """Ищет дату в тексте задачи: [DD.MM.YYYY] или [YYYY-MM-DD] или (ДД.ММ)."""
    patterns = [
        r"\[(\d{4}-\d{2}-\d{2})\]",
        r"\[(\d{2}\.\d{2}\.\d{4})\]",
        r"(\d{2}\.\d{2}\.2026)",
        r"(\d{4}-\d{2}-\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, context)
        if m:
            s = m.group(1)
            for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%Y"):
                try:
                    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
    return None


def detect_signal_type(text: str) -> str | None:
    text_lower = text.lower()
    for keywords, sig in SIGNAL_KEYWORDS:
        for kw in keywords:
            if re.search(kw, text_lower):
                return sig
    return None


def is_risk_task(text: str) -> bool:
    text_lower = text.lower()
    return any(re.search(kw, text_lower) for kw in RISK_TASK_KEYWORDS)


def parse_tasks(files: list[Path]) -> list[dict]:
    """Возвращает список {id, description, date, signal_type}."""
    tasks = []
    task_pattern = re.compile(
        r"\|\s*\[?(DEV|ARCH|TR|TRADER)-([\w\.\-]+)\]?\s*\|([^|]+)\|([^|]+)\|"
    )
    for fpath in files:
        if not fpath.exists():
            continue
        text = fpath.read_text(encoding="utf-8", errors="replace")
        for m in task_pattern.finditer(text):
            role, num, desc, _ = m.group(1), m.group(2), m.group(3), m.group(4)
            task_id = f"{role}-{num}"
            desc = desc.strip()

            # Контекст вокруг задачи (±300 символов)
            start = max(0, m.start() - 300)
            ctx = text[start: m.end() + 300]

            date = parse_task_date(ctx)
            sig = detect_signal_type(desc + " " + ctx)

            tasks.append({
                "id": task_id,
                "description": desc[:200],
                "date": date,
                "signal_type": sig,
                "is_risk": is_risk_task(desc),
            })
    # Дедупликация по ID — берём первое вхождение (обычно из TASKS.md)
    seen = set()
    result = []
    for t in tasks:
        if t["id"] not in seen:
            seen.add(t["id"])
            result.append(t)
    return result


def get_related_trades(signal_type: str, since: datetime | None, limit: int = 20) -> list[dict]:
    if not DB_PATH.exists():
        return []
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    since_str = since.strftime("%Y-%m-%d") if since else "2026-01-01"
    cur.execute("""
        SELECT id, symbol, direction, R_multiple, status, created_at, closed_at
        FROM simulated_trades
        WHERE signal_type = ? AND created_at >= ?
        ORDER BY id DESC LIMIT ?
    """, (signal_type, since_str, limit))
    rows = cur.fetchall()

    # Агрегат
    cur.execute("""
        SELECT COUNT(*), AVG(R_multiple),
               SUM(CASE WHEN R_multiple > 0 THEN 1 ELSE 0 END),
               COUNT(CASE WHEN status='OPEN' THEN 1 END)
        FROM simulated_trades
        WHERE signal_type = ? AND created_at >= ?
          AND status IN ('TP','SL','TSL','EXPIRED','OPEN')
    """, (signal_type, since_str))
    agg = cur.fetchone()
    con.close()

    return {
        "rows": rows,
        "n": agg[0] or 0,
        "avg_r": round(agg[1], 3) if agg[1] is not None else None,
        "n_win": agg[2] or 0,
        "n_open": agg[3] or 0,
    }


def build_trades_section(signal_type: str, data: dict, since: datetime | None) -> str:
    since_str = since.strftime("%Y-%m-%d") if since else "—"
    n, avg_r, n_win = data["n"], data["avg_r"], data["n_win"]
    wr = round(n_win / max(n, 1) * 100, 1)
    emoji = "✅" if avg_r and avg_r > 0 else "❌"

    lines = [
        f"",
        f"## 📊 Связанные сделки (авто: `{signal_type}` после {since_str})",
        f"",
        f"- n = **{n}** | avgR = **{emoji} {avg_r}** | WR = **{wr}%** | open = {data['n_open']}",
        f"",
    ]
    if data["rows"]:
        lines.append("| id | symbol | dir | R | status | дата |")
        lines.append("|---|---|---|---|---|---|")
        for row_id, sym, direction, r, status, created, _ in data["rows"][:15]:
            r_str = str(round(r, 2)) if r is not None else "—"
            lines.append(f"| {row_id} | {sym} | {direction} | {r_str} | {status} | {str(created)[:10]} |")
    lines.append("")
    lines.append(f"*Автосвязь `tools/task_linker.py` · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC*")
    return "\n".join(lines)


def update_dossier(task_id: str, section: str, dry_run: bool) -> bool:
    dossier_path = OBSIDIAN_TASKS_DIR / f"{task_id}.md"
    if not dossier_path.exists():
        return False

    text = dossier_path.read_text(encoding="utf-8", errors="replace")

    # Удаляем старую секцию если есть
    marker = "## 📊 Связанные сделки"
    if marker in text:
        idx = text.index(marker)
        # Ищем следующий ## заголовок или конец файла
        next_section = re.search(r"\n## ", text[idx + 1:])
        if next_section:
            text = text[:idx] + text[idx + 1 + next_section.start():]
        else:
            text = text[:idx]
        text = text.rstrip() + "\n"

    text = text.rstrip() + "\n" + section + "\n"

    if not dry_run:
        dossier_path.write_text(text, encoding="utf-8")
    return True


def process_task(task: dict, dry_run: bool, verbose: bool, quiet: bool = False) -> bool:
    sig = task["signal_type"]
    if not sig:
        if verbose:
            print(f"  [{task['id']}] нет signal_type → пропуск")
        return False

    data = get_related_trades(sig, task["date"])
    if data["n"] == 0:
        if verbose:
            print(f"  [{task['id']}] 0 сделок по {sig} → пропуск")
        return False

    section = build_trades_section(sig, data, task["date"])
    updated = update_dossier(task["id"], section, dry_run)

    if updated:
        if not quiet:
            avg_r = data["avg_r"]
            sign = "+" if avg_r and avg_r > 0 else ""
            action = "[dry-run]" if dry_run else "->"
            print(f"  {task['id']}: {sig} n={data['n']} avgR={sign}{avg_r} {action} dossier")
        return True
    elif verbose and not quiet:
        print(f"  [{task['id']}] досье не найдено в obsidian/Tasks/")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Link tasks to related trades in Obsidian")
    parser.add_argument("task_id", nargs="?", help="Конкретная задача (DEV-199). По умолчанию — все.")
    parser.add_argument("--dry-run", action="store_true", help="Только вывод, без записи")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Минимум вывода (для hook)")
    args = parser.parse_args()

    tasks = parse_tasks(TASKS_FILES)

    if args.task_id:
        task_id = args.task_id.strip().upper()
        tasks = [t for t in tasks if t["id"] == task_id]
        if not tasks:
            print(f"[task-linker] {task_id} не найден в TASKS.md", file=sys.stderr)
            return 1

    if not args.quiet:
        print(f"[task-linker] tasks={len(tasks)}, dry_run={args.dry_run}")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    updated = 0
    for task in tasks:
        if process_task(task, args.dry_run, args.verbose, args.quiet):
            updated += 1

    if not args.quiet:
        print(f"[task-linker] updated={updated}/{len(tasks)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
