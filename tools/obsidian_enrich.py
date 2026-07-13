"""Obsidian Enrich — собирает полную историю задачи по ID для obsidian/Tasks/<ID>.md.

Скрипт grep'ает все упоминания ID (DEV-X, ARCH-Y, TR-Z) по проекту,
собирает контекст и через Gemini генерирует структурированное досье:
- кто инициировал, когда
- эволюция (что предлагали, что приняли, что отвергли)
- статус и метрики
- связанные задачи

Запуск:
  python tools/obsidian_enrich.py DEV-184
  python tools/obsidian_enrich.py ARCH-70 --force
  python tools/obsidian_enrich.py DEV-200 --out e:/tmp/dev200.md

Источники (grep по ID):
  - DISCUSSION.md, DISCUSSION-ARCHIVE-*.md
  - TASKS.md, TASKS-ARCHIVE.md
  - docs/TASKS_DETAILS.md
  - memory/*.md
  - git log --grep=<ID>

Output: obsidian/Tasks/<ID>.md (либо --out path).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
OUTPUT_DIR = PROJECT_ROOT / "obsidian" / "Tasks"

GEMINI_MODEL_PRIMARY = "gemini-2.5-flash"
GEMINI_MODEL_FALLBACK = "gemini-2.5-flash-lite"
MAX_OUTPUT_TOKENS = 8000

# Файлы и папки для поиска
SEARCH_FILES = [
    "DISCUSSION.md",
    "TASKS.md",
    "TASKS-ARCHIVE.md",
    "PROJECT-LOG.md",
    "ROADMAP.md",
    "docs/TASKS_DETAILS.md",
]
SEARCH_GLOBS = [
    "DISCUSSION-ARCHIVE-*.md",
    "memory/*.md",
    "docs/*.md",
]


ENRICH_PROMPT = """Ты — архивист проекта Oko MTF Bot. По упоминаниям задачи {task_id} собери ПОЛНОЕ ДОСЬЕ.

ОБЯЗАТЕЛЬНЫЙ ФОРМАТ (markdown, русский, ~200-500 строк):

# {task_id}

## 📌 Краткая суть
1-2 предложения: что это за задача, какую проблему решает.

## 👥 Роль / Инициатор
Кто поставил (ARCH/DEV/TRADER), когда (если есть дата).

## 🎯 Цель / Acceptance criteria
Что должно быть сделано чтобы считать задачу закрытой.

## 🗓️ Хронология
Хронологически по датам, что происходило:
- `[YYYY-MM-DD]` событие, решение, результат

## 🔍 Что выяснили в процессе
Гипотезы, бэктесты, аудиты, найденные баги.

## 🔧 Реализация
- Какие файлы тронуты (если упоминаются `core/...`, `bot/...`, `tools/...`)
- Ключевые коммиты (если упоминаются hash или сообщение)
- Параметры конфига (если упоминаются строки из config.yaml)

## 📊 Метрики / эффект
Числа: avgR, WR, n сделок, потери R, экономия R — если упоминаются.

## ⚠️ Проблемы / открытые вопросы
Что не решено, что блокирует, что обсуждается.

## 🔗 Связанные задачи
Список DEV-X, ARCH-Y, TR-Z которые упоминаются вместе с этой задачей (wikilinks `[[DEV-184]]`).

## 🧭 Текущий статус
- 🟢 closed / ✅ done / 🔄 в работе / ⏸ paused / 🧊 FROZEN
- Дата последнего упоминания
- Краткое резюме «где сейчас»

ПРАВИЛА:
- ТОЛЬКО факты из источника. Не выдумывай.
- Цитируй даты, ID, file:line, hash коммитов когда они упомянуты.
- Wikilinks `[[DEV-X]]` для связанных задач.
- Bullet-points. Краткие пункты.
- Только русский язык.
- НЕ ПОВТОРЯЙ одни и те же события.

ID задачи: {task_id}

УПОМИНАНИЯ:

{snippets}
"""


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def collect_files() -> list[Path]:
    files: list[Path] = []
    for rel in SEARCH_FILES:
        p = PROJECT_ROOT / rel
        if p.exists():
            files.append(p)
    for pat in SEARCH_GLOBS:
        files.extend(PROJECT_ROOT.glob(pat))
    return files


def find_mentions(task_id: str, files: list[Path]) -> list[tuple[Path, int, str]]:
    """Возвращает список (file, line_no, context_block) для всех упоминаний task_id.

    Контекст: ±3 строки вокруг найденной."""
    # точное вхождение слова task_id (DEV-184 не должно матчить DEV-1840)
    pattern = re.compile(rf"\b{re.escape(task_id)}\b")
    results = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if pattern.search(line):
                start = max(0, i - 3)
                end = min(len(lines), i + 4)
                block = "\n".join(lines[start:end])
                results.append((f, i + 1, block))
    return results


def collect_git_log(task_id: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "log",
             f"--grep={task_id}",
             "--pretty=format:%h %ad %s",
             "--date=short", "-n", "50"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        return ""
    except Exception:
        return ""


def format_snippets(mentions: list[tuple[Path, int, str]], git_log: str) -> str:
    parts = []
    # Группируем по файлу
    by_file: dict[Path, list[tuple[int, str]]] = {}
    for f, ln, block in mentions:
        by_file.setdefault(f, []).append((ln, block))

    for f, items in sorted(by_file.items()):
        rel = f.relative_to(PROJECT_ROOT).as_posix()
        parts.append(f"\n=== {rel} ({len(items)} упоминаний) ===\n")
        seen_blocks = set()
        for ln, block in items:
            # дедуп идентичных блоков (бывает при близких упоминаниях)
            if block in seen_blocks:
                continue
            seen_blocks.add(block)
            parts.append(f"[L{ln}]\n{block}\n---\n")
    if git_log:
        parts.append(f"\n=== git log --grep ===\n{git_log}\n")
    return "".join(parts)


def call_gemini(prompt: str) -> tuple[str, str]:
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY не задан в .env")

    client = genai.Client(api_key=key)
    cfg = types.GenerateContentConfig(
        temperature=0.3,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        system_instruction=(
            "Ты — архивист проекта. Только русский язык. "
            "Только факты из предоставленного источника. "
            "Заполни ВСЕ разделы досье полностью — не сокращай."
        ),
    )
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL_PRIMARY, contents=prompt, config=cfg,
        )
        return (resp.text or "").strip(), GEMINI_MODEL_PRIMARY
    except Exception as e:
        msg = str(e)
        if "503" in msg or "UNAVAILABLE" in msg:
            print(f"[enrich] 503 → fallback {GEMINI_MODEL_FALLBACK}", file=sys.stderr)
            resp = client.models.generate_content(
                model=GEMINI_MODEL_FALLBACK, contents=prompt, config=cfg,
            )
            return (resp.text or "").strip(), GEMINI_MODEL_FALLBACK
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate enriched Obsidian task dossier")
    parser.add_argument("task_id", help="ID задачи (DEV-184, ARCH-70, TR-001)")
    parser.add_argument("--out", type=Path, help="Куда писать (по умолчанию obsidian/Tasks/<ID>.md)")
    parser.add_argument("--force", action="store_true", help="Перезаписать если файл существует")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    load_env()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    task_id = args.task_id.strip().upper()
    if not re.match(r"^(DEV|ARCH|TR|TRADER)-[\w\-\.]+$", task_id):
        print(f"[enrich] ERROR: ID должен быть формата DEV-X / ARCH-Y / TR-Z, получено: {task_id}",
              file=sys.stderr)
        return 1

    out_path = args.out or (OUTPUT_DIR / f"{task_id}.md")
    if out_path.exists() and not args.force:
        print(f"[enrich] {out_path} уже существует, используй --force для перезаписи",
              file=sys.stderr)
        return 1

    files = collect_files()
    mentions = find_mentions(task_id, files)
    git_log = collect_git_log(task_id)

    if not mentions and not git_log:
        print(f"[enrich] {task_id}: 0 упоминаний в проекте", file=sys.stderr)
        return 1

    print(f"[enrich] {task_id}: {len(mentions)} упоминаний в {len(set(m[0] for m in mentions))} файлах",
          file=sys.stderr)

    snippets = format_snippets(mentions, git_log)
    prompt = ENRICH_PROMPT.format(task_id=task_id, snippets=snippets)
    in_tokens = int(len(prompt) / 3.5)

    if in_tokens > 200_000:
        # обрезаем: оставляем первые и последние блоки (так история сохраняется)
        # простой подход — взять snippets первый/последний по 80k символов
        half = 80_000
        snippets = snippets[:half] + f"\n\n[ОБРЕЗАНО: середина {len(snippets) - 2*half} символов]\n\n" + snippets[-half:]
        prompt = ENRICH_PROMPT.format(task_id=task_id, snippets=snippets)
        in_tokens = int(len(prompt) / 3.5)
        print(f"[enrich] {task_id}: input обрезан до ~{in_tokens} токенов", file=sys.stderr)
    print(f"[enrich] {task_id}: ~{in_tokens} input tokens → Gemini...", file=sys.stderr)

    try:
        dossier, used = call_gemini(prompt)
    except Exception as e:
        print(f"[enrich] ERROR: {e}", file=sys.stderr)
        return 1

    out_tokens = int(len(dossier) / 3.5)
    print(f"[enrich] {task_id}: ~{out_tokens} output tokens ({used})", file=sys.stderr)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = (
        "---\n"
        f"id: {task_id}\n"
        "tags: [task, auto-enriched, area/diagnostics, role/arch]\n"
        "type: task\n"
        f"enriched: {today}\n"
        'parent: "[[Project-MOC]]"\n'
        f'month: "[[Months/{today[:7]}]]"\n'
        f"model: {used}\n"
        "---\n\n"
        f"> Автогенерация Gemini (`tools/obsidian_enrich.py {task_id}`). "
        f"Источники: {len(mentions)} упоминаний.\n\n---\n\n"
    )
    out_path.write_text(header + dossier, encoding="utf-8")

    if args.quiet:
        print(f"[enrich] OK -> {out_path}", file=sys.stderr)
    else:
        print(f"[enrich] OK model={used}")
        print(f"  in:  ~{in_tokens} tokens")
        print(f"  out: ~{out_tokens} tokens")
        print(f"  -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
