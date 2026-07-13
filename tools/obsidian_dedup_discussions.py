"""ARCH-OBS-05 — Obsidian Dedup Discussions.

Находит семантически похожие файлы в obsidian/Team-Discussions/
через LLM (Groq/Gemini) и помечает дубли для ручного ревью.

Этапы:
  1. Собираем заголовки + первые 200 строк каждого файла
  2. LLM группирует по смысловым кластерам
  3. Пишет отчёт obsidian/Meta/DEDUP-REPORT.md с кандидатами на удаление

Запуск:
  python tools/obsidian_dedup_discussions.py
  python tools/obsidian_dedup_discussions.py --apply   # помечать файлы deprecated тегом
  python tools/obsidian_dedup_discussions.py --dry-run # только отчёт, не трогать файлы
  python tools/obsidian_dedup_discussions.py --threshold 0.8  # порог схожести
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VAULT_ROOT = PROJECT_ROOT / "obsidian"
DISCUSSIONS_DIR = VAULT_ROOT / "Team-Discussions"
REPORT_FILE = VAULT_ROOT / "Meta" / "DEDUP-REPORT.md"
ENV_FILE = PROJECT_ROOT / ".env"

MAX_CHARS_PER_FILE = 300  # для контекста LLM


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def collect_discussions(folder: Path) -> list[dict]:
    """Собирает список {name, path, snippet} для всех файлов в папке."""
    docs: list[dict] = []
    for f in sorted(folder.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        # Первые N символов как snippet
        snippet = text[:MAX_CHARS_PER_FILE].strip()
        # Извлекаем заголовок H1 если есть
        title_m = re.search(r"^#\s+(.+)", text, re.MULTILINE)
        title = title_m.group(1).strip() if title_m else f.stem
        docs.append({"name": f.name, "path": f, "title": title, "snippet": snippet})
    return docs


def build_llm_prompt(docs: list[dict]) -> str:
    """Составляет промпт для LLM с индексом документов."""
    index_lines = []
    for i, doc in enumerate(docs):
        snippet_safe = doc["snippet"].replace("\n", " ")[:200]
        index_lines.append(f"{i+1}. [{doc['name']}] {doc['title']}\n   {snippet_safe}")

    index_text = "\n\n".join(index_lines)

    return f"""Ниже индекс из {len(docs)} файлов обсуждений (Team-Discussions).
Найди группы семантически похожих/дублирующих обсуждений.

Критерии дубля: обсуждают ту же тему, ту же задачу, тот же инцидент.
Не объединяй: разные решения одной задачи, разные периоды.

Для каждой группы дублей укажи:
- ГРУППА N: [номера файлов]
- ПРИЧИНА: (одно предложение)
- СОХРАНИТЬ: [номер] (самый полный/актуальный)
- УДАЛИТЬ: [номера через запятую]

Если дублей нет — напиши "Дублей не обнаружено".

---ДОКУМЕНТЫ---

{index_text}"""


def call_groq(prompt: str) -> str:
    """Быстрый вызов через Groq (llm_ask.py)."""
    try:
        import subprocess
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "llm_ask.py"),
                prompt,
                "--provider", "groq",
            ],
            capture_output=True, text=True, timeout=60, cwd=PROJECT_ROOT
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        # fallback: gemini
        result2 = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "llm_ask.py"),
                prompt,
                "--provider", "gemini",
            ],
            capture_output=True, text=True, timeout=90, cwd=PROJECT_ROOT
        )
        return result2.stdout.strip() or "(ошибка LLM)"
    except Exception as e:
        return f"(ошибка вызова LLM: {e})"


def parse_dedup_groups(llm_response: str, docs: list[dict]) -> list[dict]:
    """Парсит ответ LLM → список групп дублей."""
    groups: list[dict] = []

    # Ищем блоки вида "ГРУППА N: [1, 3, 5]"
    group_re = re.compile(
        r"ГРУППА\s+\d+\s*:\s*\[([^\]]+)\].*?"
        r"ПРИЧИНА\s*:\s*(.+?)\n.*?"
        r"СОХРАНИТЬ\s*:\s*\[?(\d+)\]?.*?"
        r"УДАЛИТЬ\s*:\s*\[([^\]]+)\]",
        re.DOTALL | re.IGNORECASE
    )

    for m in group_re.finditer(llm_response):
        try:
            all_nums = [int(x.strip()) for x in m.group(1).split(",") if x.strip().isdigit()]
            reason = m.group(2).strip()
            keep_num = int(m.group(3).strip())
            delete_nums = [int(x.strip()) for x in m.group(4).split(",") if x.strip().isdigit()]

            keep_doc = docs[keep_num - 1] if 1 <= keep_num <= len(docs) else None
            delete_docs = [docs[n - 1] for n in delete_nums if 1 <= n <= len(docs)]

            if keep_doc and delete_docs:
                groups.append({
                    "reason": reason,
                    "keep": keep_doc,
                    "delete": delete_docs,
                })
        except (ValueError, IndexError):
            continue

    return groups


def render_report(groups: list[dict], docs: list[dict], llm_raw: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "---",
        "tags: [dedup, meta, auto-generated]",
        "type: dedup-report",
        f"generated: {now}",
        "parent: \"[[Project-MOC]]\"",
        "---",
        "",
        f"# 🔁 Dedup Report — Team-Discussions — {now}",
        "",
        f"Проверено файлов: {len(docs)}",
        f"Найдено групп дублей: {len(groups)}",
        "",
    ]

    if not groups:
        lines.append("## ✅ Дублей не обнаружено")
        lines.append("")
    else:
        lines.append("## 🗑️ Кандидаты на удаление")
        lines.append("")
        lines.append("> ⚠️ Требует ручного ревью перед удалением!")
        lines.append("")
        for i, g in enumerate(groups, 1):
            lines.append(f"### Группа {i}: {g['reason']}")
            lines.append(f"**Сохранить:** `{g['keep']['name']}`")
            lines.append(f"**Удалить ({len(g['delete'])}):**")
            for d in g["delete"]:
                lines.append(f"  - `{d['name']}`")
            lines.append("")

    lines.append("## 🤖 Полный ответ LLM")
    lines.append("")
    lines.append("```")
    lines.append(llm_raw[:3000])
    lines.append("```")
    lines.append("")
    lines.append(f"---")
    lines.append(f"*Сгенерировано `tools/obsidian_dedup_discussions.py` · {now}*")

    return "\n".join(lines) + "\n"


def apply_deprecated_tag(doc_path: Path) -> None:
    """Добавляет #status/deprecated в frontmatter."""
    text = doc_path.read_text(encoding="utf-8", errors="replace")
    if "#status/deprecated" in text:
        return

    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            fm = text[3:end]
            # Добавляем тег в tags: если есть
            tags_m = re.search(r"tags\s*:\s*\[(.+?)\]", fm)
            if tags_m:
                inner = tags_m.group(1).rstrip("]").strip()
                new_inner = inner + ", '#status/deprecated'"
                fm = fm[:tags_m.start(1)] + new_inner + fm[tags_m.end(1):]
                text = f"---\n{fm}\n---\n" + text[end + 5:]
                doc_path.write_text(text, encoding="utf-8")
                return

    # Если нет frontmatter — добавить в начало
    doc_path.write_text(
        "---\ntags: [status/deprecated]\n---\n\n" + text,
        encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Dedup Team-Discussions через LLM")
    parser.add_argument("--apply", action="store_true", help="Пометить дубли #status/deprecated")
    parser.add_argument("--dry-run", action="store_true", help="Только отчёт, не трогать файлы")
    parser.add_argument("--dir", default=str(DISCUSSIONS_DIR), help="Папка с обсуждениями")
    args = parser.parse_args()

    load_env()
    folder = Path(args.dir)
    if not folder.exists():
        print(f"ERROR: папка не найдена: {folder}", file=sys.stderr)
        sys.exit(1)

    docs = collect_discussions(folder)
    if not docs:
        print("Нет файлов в папке Team-Discussions")
        return

    print(f"Dedup: {len(docs)} файлов в {folder.name}")

    if len(docs) < 3:
        print("Слишком мало файлов для анализа дублей (нужно >= 3)")
        return

    print("  Составляю промпт...", end=" ", flush=True)
    prompt = build_llm_prompt(docs)
    print(f"{len(prompt)} символов")

    print("  Вызываю LLM (Groq → Gemini)...", end=" ", flush=True)
    llm_response = call_groq(prompt)
    print("OK")

    groups = parse_dedup_groups(llm_response, docs)
    print(f"  Найдено групп дублей: {len(groups)}")

    report = render_report(groups, docs, llm_response)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(f"✅ Отчёт → {REPORT_FILE.relative_to(PROJECT_ROOT)}")

    if args.apply and groups and not args.dry_run:
        total_marked = 0
        for g in groups:
            for d in g["delete"]:
                apply_deprecated_tag(d["path"])
                total_marked += 1
        print(f"  Помечено deprecated: {total_marked} файлов")


if __name__ == "__main__":
    main()
