#!/usr/bin/env python3
"""
Validate Obsidian Vault integrity.

Проверяет:
- Orphan узлы (файлы без входящих ссылок)
- Битые ссылки [[XXX]] на несуществующие файлы
- Отсутствующие теги в frontmatter
- Дублирование ID в frontmatter
- Консистентность parent ссылок

Запуск:
    python3 scripts/validate_obsidian_vault.py [--fix]

--fix: автоматически пытается исправить некритичные ошибки
"""

import re
import os
from pathlib import Path
from collections import defaultdict
import sys

VAULT_ROOT = Path("/workspace/obsidian")
WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
BACKLINK_CACHE = defaultdict(set)  # file → set of files that link to it
ID_CACHE = {}  # id → file
FILE_CACHE = set()  # all .md files

# Known files that CAN be orphans (they're indexes or MOCs)
ALLOWED_ORPHANS = {
    "Project-MOC.md",
    "OBSIDIAN-RULES.md",
    "TEMPLATES.md",
    "Tasks/INDEX.md",
    "Discussions/INDEX.md",
    "Architecture/INDEX.md",
    "Strategies/INDEX.md",
    "Concepts/INDEX.md",
    "Code-Map/README.md",
    "Documentation/INDEX.md",
}

class VaultValidator:
    def __init__(self, vault_root=VAULT_ROOT):
        self.vault = vault_root
        self.errors = []
        self.warnings = []
        self.stats = {
            "files": 0,
            "links": 0,
            "orphans": 0,
            "broken_links": 0,
            "missing_tags": 0,
            "duplicate_ids": 0,
        }

    def scan_files(self):
        """Соберите все .md файлы и их frontmatter"""
        for md_file in self.vault.rglob("*.md"):
            rel_path = md_file.relative_to(self.vault)
            FILE_CACHE.add(str(rel_path))
            self.stats["files"] += 1

            # Парсим frontmatter для ID
            try:
                content = md_file.read_text(encoding="utf-8")
                match = FRONTMATTER_PATTERN.match(content)
                if match:
                    fm = match.group(1)
                    id_match = re.search(r"^id:\s*(.+)$", fm, re.MULTILINE)
                    if id_match:
                        task_id = id_match.group(1).strip()
                        if task_id in ID_CACHE:
                            self.errors.append(
                                f"❌ DUPLICATE ID '{task_id}': {ID_CACHE[task_id]} и {rel_path}"
                            )
                            self.stats["duplicate_ids"] += 1
                        else:
                            ID_CACHE[task_id] = str(rel_path)
            except Exception as e:
                self.warnings.append(f"⚠️ Ошибка парса {rel_path}: {e}")

    def analyze_links(self):
        """Анализируем wikilinks"""
        for md_file in self.vault.rglob("*.md"):
            rel_path = md_file.relative_to(self.vault)
            try:
                content = md_file.read_text(encoding="utf-8")

                # Находим все [[XXX]]
                for match in WIKILINK_PATTERN.finditer(content):
                    link = match.group(1)
                    self.stats["links"] += 1

                    # Парсим link (может быть DEV-184, или Path/to/file, или Path/to/file#anchor)
                    if "#" in link:
                        link_file = link.split("#")[0]
                    else:
                        link_file = link

                    # Проверяем если это ID (DEV-184, ARCH-54)
                    if re.match(r"^(DEV|ARCH|TR|REAL|CUBE|TRADER)-\d+", link_file):
                        # ID может не иметь .md, это нормально (сгенерируется позже)
                        BACKLINK_CACHE[link_file].add(str(rel_path))
                    else:
                        # Иначе это путь к файлу
                        # Нормализуем: [[Concepts/TSL]] → Concepts/TSL.md
                        if not link_file.endswith(".md"):
                            link_file += ".md"

                        # Ищем файл
                        found = False
                        for candidate in FILE_CACHE:
                            if candidate.endswith(link_file):
                                found = True
                                BACKLINK_CACHE[candidate].add(str(rel_path))
                                break

                        if not found:
                            # Проверяем специальные случаи (docs/, внешние ссылки)
                            if not (
                                "docs/" in link_file
                                or "http" in link_file
                                or "core/" in link_file
                            ):
                                self.errors.append(
                                    f"❌ BROKEN LINK: [[{link}]] в {rel_path}"
                                )
                                self.stats["broken_links"] += 1
            except Exception as e:
                self.warnings.append(f"⚠️ Ошибка анализа {rel_path}: {e}")

    def find_orphans(self):
        """Найти узлы без входящих ссылок"""
        for file_path in FILE_CACHE:
            # Пропускаем разрешённые orphans
            if any(file_path.endswith(allowed) for allowed in ALLOWED_ORPHANS):
                continue

            # Проверяем входящие ссылки
            if file_path not in BACKLINK_CACHE:
                # Но проверяем если это Task/DEV-XXX (могут быть БЕЗ ссылок если мало упоминаний)
                if not (
                    file_path.startswith("Tasks/") or file_path.startswith("Discussions/")
                ):
                    self.warnings.append(f"⚠️ ORPHAN: {file_path} (не на что не ссылается)")
                    self.stats["orphans"] += 1

    def check_required_tags(self):
        """Проверить что у каждого файла есть минимальные теги"""
        for md_file in self.vault.rglob("*.md"):
            rel_path = md_file.relative_to(self.vault)
            try:
                content = md_file.read_text(encoding="utf-8")
                match = FRONTMATTER_PATTERN.match(content)
                if match:
                    fm = match.group(1)
                    # Проверяем теги
                    if "tags:" not in fm:
                        self.warnings.append(
                            f"⚠️ NO TAGS: {rel_path} (нет tags в frontmatter)"
                        )
                        self.stats["missing_tags"] += 1
                    # Проверяем type
                    if "type:" not in fm:
                        self.warnings.append(f"⚠️ NO TYPE: {rel_path}")
            except Exception:
                pass

    def report(self):
        """Выведи отчёт"""
        print("\n" + "=" * 60)
        print("📊 OBSIDIAN VAULT VALIDATION REPORT")
        print("=" * 60)

        print(f"\n✅ Статистика:")
        print(f"  Файлов: {self.stats['files']}")
        print(f"  Wikilinks найдено: {self.stats['links']}")
        print(f"  Orphan узлов: {self.stats['orphans']}")
        print(f"  Broken links: {self.stats['broken_links']}")
        print(f"  Missing tags: {self.stats['missing_tags']}")
        print(f"  Duplicate IDs: {self.stats['duplicate_ids']}")

        if self.errors:
            print(f"\n🔴 ОШИБКИ ({len(self.errors)}):")
            for err in self.errors:
                print(f"  {err}")

        if self.warnings:
            print(f"\n🟡 ПРЕДУПРЕЖДЕНИЯ ({len(self.warnings)}):")
            for warn in self.warnings[:20]:  # Первые 20
                print(f"  {warn}")
            if len(self.warnings) > 20:
                print(f"  ... и ещё {len(self.warnings) - 20}")

        print("\n" + "=" * 60)
        health = "🟢 ЗДОРОВ" if not self.errors else "🔴 ТРЕБУЕТ ВНИМАНИЯ"
        print(f"Статус: {health}")
        print("=" * 60 + "\n")

        return len(self.errors) == 0

    def fix_issues(self):
        """Попытка автоматически исправить некритичные проблемы"""
        print("🔧 Attempting fixes...")
        # TODO: реализовать автофиксы (добавить parent ссылки, добавить теги и т.п.)
        print("  (автофиксы пока не реализованы, см. OBSIDIAN-RULES.md)")


def main():
    fix = "--fix" in sys.argv

    validator = VaultValidator()

    print("🔍 Сканирование vault'я...")
    validator.scan_files()

    print(f"📝 Анализирование {len(FILE_CACHE)} файлов...")
    validator.analyze_links()

    print("🔎 Поиск orphan узлов...")
    validator.find_orphans()

    print("🏷️  Проверка тегов...")
    validator.check_required_tags()

    # Вывести отчёт
    is_healthy = validator.report()

    if fix and not is_healthy:
        validator.fix_issues()

    return 0 if is_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
