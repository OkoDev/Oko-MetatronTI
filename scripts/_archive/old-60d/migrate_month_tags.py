#!/usr/bin/env python3
"""
Миграция: заменить теги #month/YYYY-MM на wikilinks [[Months/YYYY-MM]].

Правильный подход в Obsidian:
- Теги (status, role, area, priority) → для фильтрации
- Wikilinks ([[Months/YYYY-MM]]) → для связи в графе

Что делает:
1. Находит все теги #month/YYYY-MM в frontmatter и body
2. Удаляет их из frontmatter (tags: [...])
3. Если в body нет [[Months/YYYY-MM]] — добавляет в раздел "Связь" / parent

Запуск:
    python3 scripts/migrate_month_tags.py [--dry-run]
"""

import re
import sys
from pathlib import Path

VAULT = Path("/workspace/obsidian")
MONTH_TAG_PATTERN = re.compile(r"#?month/(\d{4}-\d{2})")
DRY_RUN = "--dry-run" in sys.argv


def process_file(md_file: Path) -> tuple[bool, set[str]]:
    """Обрабатывает файл. Возвращает (изменён, найденные_месяцы)."""
    try:
        content = md_file.read_text(encoding="utf-8")
    except Exception:
        return False, set()

    original = content
    months = set()

    # 1. Найти все месяцы
    for match in MONTH_TAG_PATTERN.finditer(content):
        months.add(match.group(1))

    if not months:
        return False, set()

    # 2. Убрать теги #month/YYYY-MM из tags: [...]
    # Шаблоны для разных форматов tags:
    # tags: [..., '#month/2026-04', ...]
    # tags: [..., 'month/2026-04', ...]
    # tags: [..., #month/2026-04, ...]
    for month in months:
        # tags в формате с кавычками
        content = re.sub(
            rf",\s*['\"]#?month/{month}['\"]",
            "",
            content,
        )
        content = re.sub(
            rf"['\"]#?month/{month}['\"],?\s*",
            "",
            content,
        )
        # tags без кавычек
        content = re.sub(
            rf",\s*#?month/{month}",
            "",
            content,
        )
        content = re.sub(
            rf"#?month/{month},?\s*",
            "",
            content,
        )

    # 3. Чистим пустые tags: [] или tags: [, , ]
    content = re.sub(r"tags:\s*\[\s*,?\s*\]", "tags: []", content)
    content = re.sub(r"\[\s*,", "[", content)
    content = re.sub(r",\s*\]", "]", content)
    content = re.sub(r",\s*,", ",", content)

    # 4. Добавить wikilink [[Months/YYYY-MM]] в frontmatter (поле month: или в body)
    for month in months:
        wikilink = f"[[Months/{month}]]"
        if wikilink not in content:
            # Добавляем в frontmatter после parent или в начале body
            if "parent:" in content:
                content = re.sub(
                    r"(parent:\s*\"[^\"]+\")",
                    rf'\1\nmonth: "{wikilink}"',
                    content,
                    count=1,
                )
            else:
                # Добавляем после --- (frontmatter end)
                content = re.sub(
                    r"^(---\n.*?\n---)",
                    rf'\1\n\n> Месяц: {wikilink}',
                    content,
                    count=1,
                    flags=re.DOTALL,
                )

    if content != original and not DRY_RUN:
        md_file.write_text(content, encoding="utf-8")

    return content != original, months


def main():
    print(f"🔍 Сканирование vault: {VAULT}")
    print(f"   Режим: {'DRY-RUN (без записи)' if DRY_RUN else 'ЗАПИСЬ'}")
    print()

    changed = 0
    total = 0
    all_months = set()

    for md_file in VAULT.rglob("*.md"):
        # Пропускаем сами хабы Months/
        if "Months/" in str(md_file):
            continue
        total += 1
        was_changed, months = process_file(md_file)
        if was_changed:
            changed += 1
            all_months.update(months)
            if changed <= 5:
                print(f"  ✏️  {md_file.relative_to(VAULT)} ({', '.join(months)})")

    if changed > 5:
        print(f"  ... и ещё {changed - 5} файлов")

    print()
    print(f"📊 ИТОГО:")
    print(f"   Просмотрено: {total} файлов")
    print(f"   Изменено: {changed} файлов")
    print(f"   Месяцев найдено: {sorted(all_months)}")
    print()
    if DRY_RUN:
        print("💡 Для применения изменений запустите без --dry-run")
    else:
        print("✅ Миграция завершена")


if __name__ == "__main__":
    main()
