"""ARCH-OBS-04 — Obsidian Weekly Digest через Gemini.

Собирает за последние 7 дней:
  - Новые Discussion записи из DISCUSSION.md
  - Закрытые/открытые задачи из TASKS.md
  - Git коммиты за период
  - Метрики из БД (avgR, WR, signal_type breakdown)
  - Активные эпики из TASKS.md (ARCH-104 и др.)

Через Gemini генерирует структурированный дайджест.
Output: obsidian/Index/WEEKLY-<YYYY-WNN>.md

Запуск:
  python tools/obsidian_weekly_digest.py
  python tools/obsidian_weekly_digest.py --days 14
  python tools/obsidian_weekly_digest.py --dry-run   # только собрать контекст, не вызывать Gemini
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VAULT_ROOT = PROJECT_ROOT / "obsidian"
OUTPUT_DIR = VAULT_ROOT / "Index"
DB_PATH = PROJECT_ROOT / "subscriptions.db"
TASKS_FILE = PROJECT_ROOT / "TASKS.md"
DISCUSSION_FILE = PROJECT_ROOT / "DISCUSSION.md"
ENV_FILE = PROJECT_ROOT / ".env"

GEMINI_MODEL = "gemini-2.5-flash"
# 13.10: своя квота у каждой модели (free-tier 20 запросов/СУТКИ НА МОДЕЛЬ), поэтому запасная
# живёт, когда основная уже отдаёт 429 — как у остальных шести инструментов.
GEMINI_MODEL_FALLBACK = "gemini-2.5-flash-lite"


# ── ENV ──────────────────────────────────────────────────────────────────────

def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


# ── DATA COLLECTION ──────────────────────────────────────────────────────────

def collect_discussions(since: datetime, max_chars: int = 8000) -> str:
    """Извлекает блоки Discussion за период."""
    if not DISCUSSION_FILE.exists():
        return ""
    text = DISCUSSION_FILE.read_text(encoding="utf-8", errors="replace")

    # Ищем датированные блоки вида "### [DD.MM.YYYY]"
    block_re = re.compile(r"(###\s*\[(\d{2})\.(\d{2})\.(\d{4})\].*?)(?=###\s*\[|\Z)", re.DOTALL)
    relevant: list[str] = []
    for m in block_re.finditer(text):
        day, month, year = int(m.group(2)), int(m.group(3)), int(m.group(4))
        try:
            dt = datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt >= since:
            relevant.append(m.group(1).strip())

    result = "\n\n---\n\n".join(relevant)
    return result[:max_chars] if len(result) > max_chars else result


def collect_tasks_delta(since: datetime) -> str:
    """Извлекает строки задач закрытых/открытых за период (по git blame или просто строки с ✅)."""
    if not TASKS_FILE.exists():
        return ""

    lines = TASKS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    active: list[str] = []
    done: list[str] = []

    for line in lines:
        if "|" not in line:
            continue
        if "✅" in line:
            done.append(line.strip())
        elif any(s in line for s in ["🔴", "🟡", "🔄"]):
            active.append(line.strip())

    parts = []
    if done[:20]:
        parts.append("**Завершённые задачи:**\n" + "\n".join(done[:20]))
    if active[:15]:
        parts.append("**Активные/критичные задачи:**\n" + "\n".join(active[:15]))

    return "\n\n".join(parts)


def collect_git_log(since: datetime) -> str:
    """Git log за период."""
    since_str = since.strftime("%Y-%m-%d")
    try:
        result = subprocess.run(
            ["git", "log", f"--since={since_str}", "--oneline", "--no-merges", "--max-count=30"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=10
        )
        return result.stdout.strip() or "(нет коммитов за период)"
    except Exception:
        return "(git недоступен)"


def collect_db_metrics(since: datetime) -> str:
    """Метрики из БД за период."""
    if not DB_PATH.exists():
        return "(БД недоступна)"

    since_str = since.strftime("%Y-%m-%d %H:%M:%S")
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()

        cur.execute("""
            SELECT COUNT(*), AVG(R_multiple),
                   SUM(CASE WHEN R_multiple > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*)
            FROM simulated_trades
            WHERE status != 'OPEN' AND created_at >= ?
        """, (since_str,))
        row = cur.fetchone()
        total, avg_r, wr = (row[0] or 0), (row[1] or 0), (row[2] or 0)

        cur.execute("""
            SELECT signal_type, COUNT(*), AVG(R_multiple)
            FROM simulated_trades
            WHERE status != 'OPEN' AND created_at >= ?
            GROUP BY signal_type ORDER BY COUNT(*) DESC LIMIT 8
        """, (since_str,))
        by_type = cur.fetchall()
        con.close()

        lines = [f"Всего сделок: {total} | avgR={avg_r:.3f} | WR={wr:.1f}%", ""]
        lines.append("По типу сигнала:")
        for stype, cnt, avg in by_type:
            lines.append(f"  {stype}: n={cnt} avgR={avg:.3f}")

        return "\n".join(lines)
    except Exception as e:
        return f"(ошибка БД: {e})"


# ── GEMINI CALL ───────────────────────────────────────────────────────────────

def call_gemini(prompt: str, context: str) -> str:
    """Дайджест от Gemini. 🔴 При неудаче БРОСАЕТ исключение, а не возвращает текст ошибки.

    13.10: раньше здесь возвращалась строка «(ошибка Gemini: …)», она уходила в файл дайджеста,
    и инструмент печатал «✅». Внешне — свежий артефакт, по сути — пустая страница; ровно тот
    класс, из-за которого шесть инструментов простояли 24 дня незамеченными. Отказ должен быть
    виден: пусть лучше файла не будет, тогда вахта scripts/llm_health.py его хватится.
    """
    # Старый SDK google-generativeai объявлен прекращённым («All support has ended»),
    # поэтому здесь тот же google-genai, что у остальных инструментов.
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не найден в .env")

    # Google считает наш VPN-выход RU → 400; LLM_PROXY (.env) — как в tools/llm_ask.py
    _px = os.environ.get("LLM_PROXY")
    client = genai.Client(api_key=api_key,
                          http_options=types.HttpOptions(client_args={"proxy": _px}) if _px else None)
    cfg = types.GenerateContentConfig(
        temperature=0.3,
        max_output_tokens=4000,
        system_instruction=(
            "Ты ассистент проекта Oko MTF Trading Bot. "
            "Создавай структурированные дайджесты на русском языке. "
            "БЕЗ markdown разметки кроме заголовков ## и ###. "
            "Используй wikilinks [[DEV-XXX]] для задач. "
            "Будь конкретным — приводи числа, ключевые решения, не пересказывай."
        ),
    )
    full_prompt = f"{prompt}\n\n---КОНТЕКСТ---\n\n{context}"
    try:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=full_prompt, config=cfg)
        return (resp.text or "").strip()
    except Exception as e:                                    # noqa: BLE001
        msg = str(e)
        if not any(s in msg for s in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")):
            raise
        print(f"[weekly_digest] {msg[:40]} → fallback {GEMINI_MODEL_FALLBACK}", file=sys.stderr)
        resp = client.models.generate_content(model=GEMINI_MODEL_FALLBACK, contents=full_prompt, config=cfg)
        return (resp.text or "").strip()


# ── RENDER ────────────────────────────────────────────────────────────────────

def week_label(dt: datetime) -> str:
    return f"{dt.year}-W{dt.isocalendar()[1]:02d}"


def build_obsidian_page(week: str, digest_text: str, since: datetime, now: datetime) -> str:
    since_str = since.strftime("%Y-%m-%d")
    now_str = now.strftime("%Y-%m-%d")
    month_link = f"[[Months/{now.strftime('%Y-%m')}]]"

    return f"""---
tags: [digest, weekly, auto-generated]
type: weekly-digest
week: "{week}"
period: "{since_str} / {now_str}"
generated: "{now.strftime('%Y-%m-%d %H:%M UTC')}"
parent: "[[Project-MOC]]"
month: "{month_link}"
---

# 📅 Weekly Digest — {week}

> Период: {since_str} → {now_str}
> Сгенерировано `tools/obsidian_weekly_digest.py`

{digest_text}

---
*Gemini {GEMINI_MODEL} · {now.strftime('%Y-%m-%d %H:%M UTC')}*
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Obsidian Weekly Digest через Gemini")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true", help="Собрать контекст, не вызывать Gemini")
    parser.add_argument("--out", help="Путь к выходному файлу (по умолчанию obsidian/Index/)")
    args = parser.parse_args()

    load_env()
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.days)
    week = week_label(now)

    print(f"Weekly Digest {week} ({since.strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d')})")

    print("  Собираю Discussion...", end=" ", flush=True)
    discussions = collect_discussions(since)
    print(f"{len(discussions)} символов")

    print("  Собираю Tasks...", end=" ", flush=True)
    tasks_delta = collect_tasks_delta(since)
    print(f"{len(tasks_delta)} символов")

    print("  Git log...", end=" ", flush=True)
    git_log = collect_git_log(since)
    print(f"{git_log.count(chr(10))+1} коммитов")

    print("  DB метрики...", end=" ", flush=True)
    db_metrics = collect_db_metrics(since)
    print("OK")

    context = f"""## Git commits (последние {args.days} дней)
{git_log}

## DB метрики
{db_metrics}

## Tasks (active/done)
{tasks_delta[:3000]}

## Discussion (новые записи)
{discussions[:6000]}
"""

    if args.dry_run:
        print("\n--- КОНТЕКСТ (dry-run) ---")
        print(context[:2000])
        print("...")
        return 0

    print("  Вызываю Gemini...", end=" ", flush=True)
    prompt = f"""Создай структурированный недельный дайджест проекта Oko MTF Bot за период {since.strftime('%d.%m')}–{now.strftime('%d.%m.%Y')}.

Структура:
## 🏆 Ключевые достижения недели
(3-5 пунктов: что завершено, какие числа улучшились)

## 🔴 Активные задачи и риски
(топ-3 срочных + риски)

## 📊 Торговые метрики
(avgR, WR, что изменилось, какие сигналы лучше/хуже)

## 🔧 Архитектурные изменения
(новые модули, фиксы, рефакторинг)

## 📅 Следующая неделя
(3-4 приоритета)

Используй wikilinks [[DEV-XXX]] для задач. Приводи конкретные числа из контекста."""

    # 13.10: отказ громкий и БЕЗ записи файла — иначе страница с текстом ошибки выглядит
    # свежим артефактом, и вахта llm_health считает задачу выполненной.
    try:
        digest = call_gemini(prompt, context)
    except Exception as e:                                    # noqa: BLE001
        print("FAIL")
        print(f"[weekly_digest] ОШИБКА: дайджест не создан, файл не записан: {e}", file=sys.stderr)
        return 1
    if not digest:
        print("FAIL")
        print("[weekly_digest] ОШИБКА: модель вернула пустой текст, файл не записан", file=sys.stderr)
        return 1
    print("OK")

    output_text = build_obsidian_page(week, digest, since, now)

    out_path = Path(args.out) if args.out else OUTPUT_DIR / f"WEEKLY-{week}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output_text, encoding="utf-8")
    print(f"✅ → {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
