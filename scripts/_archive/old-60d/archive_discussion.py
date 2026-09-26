#!/usr/bin/env python3
"""
archive_discussion.py — автоматическая архивация DISCUSSION.md

Логика:
- Если DISCUSSION.md > THRESHOLD_LINES строк → архивировать записи,
  оставляя только последние KEEP_ENTRIES записей в основном файле
- Старые записи → DISCUSSION-ARCHIVE-{MMMYYYY}.md (по месяцу старейшей записи)
- Заголовок DISCUSSION.md обновляется со ссылками на архивы

Запуск:
  python3 scripts/archive_discussion.py              # авто (только если > THRESHOLD_LINES)
  python3 scripts/archive_discussion.py --force      # принудительно
  python3 scripts/archive_discussion.py --dry-run    # показать что будет архивировано
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

WORKSPACE = Path(__file__).parent.parent
DISCUSSION_FILE = WORKSPACE / "DISCUSSION.md"

THRESHOLD_LINES = 1500  # строк — порог для автоархивации
KEEP_ENTRIES = 40       # сколько записей (### [дата]) оставить в основном файле

MONTHS_RU = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR",
    5: "MAY", 6: "JUN", 7: "JUL", 8: "AUG",
    9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}

HEADER_RE = re.compile(r"^### \[(\d{2})\.(\d{2})\.(\d{4})")


def parse_date(day: str, month: str, year: str) -> datetime:
    return datetime(int(year), int(month), int(day), tzinfo=timezone.utc)


def format_date_short(dt: datetime) -> str:
    return f"{dt.day:02d}.{dt.month:02d}.{dt.year}"


def split_into_entries(lines: list) -> list:
    """
    Разбивает строки на блоки (дата | None, список строк).
    Первый блок (шапка файла) имеет дату=None.
    """
    entries = []
    current_date = None
    current_block = []

    for line in lines:
        m = HEADER_RE.match(line)
        if m:
            if current_block:
                entries.append((current_date, current_block))
            current_date = parse_date(m.group(1), m.group(2), m.group(3))
            current_block = [line]
        else:
            current_block.append(line)

    if current_block:
        entries.append((current_date, current_block))

    return entries


def build_archive_filename(year: int, month: int) -> str:
    return f"DISCUSSION-ARCHIVE-{MONTHS_RU[month]}{year}.md"


def rebuild_header(header_lines: list, archive_refs: list) -> list:
    """
    Перестраивает шапку DISCUSSION.md: заменяет ссылки на архивы.
    archive_refs: [(filename, date_from_str, date_to_str), ...]
    """
    new_lines = []
    ref_inserted = False

    for line in header_lines:
        is_archive_ref = line.startswith("> Записи") and "ARCHIVE" in line
        if is_archive_ref:
            if not ref_inserted:
                for fname, d_from, d_to in archive_refs:
                    new_lines.append(f"> Записи {d_from}–{d_to} → [{fname}]({fname})\n")
                ref_inserted = True
            # старые строки пропускаем
        else:
            new_lines.append(line)

    return new_lines


def archive(force: bool = False, dry_run: bool = False) -> int:
    """Возвращает количество заархивированных записей (0 = ничего не сделано)."""
    if not DISCUSSION_FILE.exists():
        print(f"[archive_discussion] Файл не найден: {DISCUSSION_FILE}")
        return 0

    content = DISCUSSION_FILE.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    line_count = len(lines)

    if not force and line_count <= THRESHOLD_LINES:
        print(f"[archive_discussion] {line_count} строк ≤ {THRESHOLD_LINES} — архивация не нужна")
        return 0

    print(f"[archive_discussion] {line_count} строк — начинаю (keep_entries={KEEP_ENTRIES})")

    entries = split_into_entries(lines)

    header_entry = entries[0] if entries[0][0] is None else None
    dated_entries = [(dt, blk) for dt, blk in entries if dt is not None]

    if len(dated_entries) <= KEEP_ENTRIES:
        print(f"[archive_discussion] Всего {len(dated_entries)} записей ≤ {KEEP_ENTRIES} — нечего архивировать")
        return 0

    # Файл хранит записи от новых к старым: первые KEEP_ENTRIES оставляем
    keep = dated_entries[:KEEP_ENTRIES]
    to_archive = dated_entries[KEEP_ENTRIES:]

    print(f"[archive_discussion] Оставляем: {len(keep)}, архивируем: {len(to_archive)}")

    if dry_run:
        oldest = min(dt for dt, _ in to_archive)
        newest = max(dt for dt, _ in to_archive)
        print(f"[dry-run] Будет архивировано: {format_date_short(newest)} – {format_date_short(oldest)}")
        for dt, blk in to_archive[:10]:
            print(f"  {format_date_short(dt)}: {blk[0].strip()[:80]}")
        if len(to_archive) > 10:
            print(f"  ... и ещё {len(to_archive) - 10}")
        return len(to_archive)

    # Группируем по месяцу (год, месяц)
    by_month = defaultdict(list)
    for dt, blk in to_archive:
        by_month[(dt.year, dt.month)].append((dt, blk))

    # Читаем существующие ссылки из шапки
    archive_refs = []
    if header_entry:
        for line in header_entry[1]:
            m = re.search(r"\[(DISCUSSION-ARCHIVE-\w+\.md)\]", line)
            dm = re.search(r"Записи (\S+)–(\S+)", line)
            if m and dm:
                archive_refs.append((m.group(1), dm.group(1), dm.group(2)))

    # Записываем в архивные файлы
    for (year, month), month_entries in sorted(by_month.items()):
        fname = build_archive_filename(year, month)
        archive_path = WORKSPACE / fname

        # Сортируем от новых к старым
        month_entries_sorted = sorted(month_entries, key=lambda x: x[0], reverse=True)
        oldest_dt = min(dt for dt, _ in month_entries_sorted)
        newest_dt = max(dt for dt, _ in month_entries_sorted)

        if archive_path.exists():
            existing = archive_path.read_text(encoding="utf-8")
            # Обновляем диапазон дат в заголовке архива
            dm = re.search(r"> Архив записей (\S+)–(\S+)", existing)
            if dm:
                try:
                    ex_oldest = datetime.strptime(dm.group(1), "%d.%m.%Y").replace(tzinfo=timezone.utc)
                    ex_newest = datetime.strptime(dm.group(2), "%d.%m.%Y").replace(tzinfo=timezone.utc)
                    oldest_dt = min(oldest_dt, ex_oldest)
                    newest_dt = max(newest_dt, ex_newest)
                    existing = existing.replace(
                        dm.group(0),
                        f"> Архив записей {format_date_short(oldest_dt)}–{format_date_short(newest_dt)}",
                    )
                except ValueError:
                    pass
            new_content = existing.rstrip("\n") + "\n\n"
            for _, blk in month_entries_sorted:
                new_content += "".join(blk)
        else:
            header = (
                f"## 💬 Discussion Archive — {MONTHS_RU[month]} {year}\n\n"
                f"> Архив записей {format_date_short(oldest_dt)}–{format_date_short(newest_dt)}\n\n"
                "---\n\n"
            )
            new_content = header + "".join("".join(blk) for _, blk in month_entries_sorted)

        archive_path.write_text(new_content, encoding="utf-8")
        print(f"[archive_discussion] {'Дописано в' if archive_path.exists() else 'Создан'} {fname}: {len(month_entries)} записей")

        # Обновляем список ссылок
        ref = (fname, format_date_short(oldest_dt), format_date_short(newest_dt))
        updated = False
        for i, (rf, _, _) in enumerate(archive_refs):
            if rf == fname:
                archive_refs[i] = ref
                updated = True
                break
        if not updated:
            archive_refs.append(ref)

    # Сортируем ссылки по дате (старые сначала)
    def ref_sort_key(r):
        try:
            return datetime.strptime(r[1], "%d.%m.%Y")
        except ValueError:
            return datetime.min

    archive_refs.sort(key=ref_sort_key)

    # Перестраиваем DISCUSSION.md
    new_lines = []
    if header_entry:
        new_lines.extend(rebuild_header(header_entry[1], archive_refs))
    for _, blk in keep:
        new_lines.extend(blk)

    DISCUSSION_FILE.write_text("".join(new_lines), encoding="utf-8")

    new_count = len(new_lines)
    print(
        f"[archive_discussion] Готово: {line_count} → {new_count} строк "
        f"({line_count - new_count} строк перемещено в архив)"
    )
    return len(to_archive)


if __name__ == "__main__":
    force = "--force" in sys.argv
    dry_run = "--dry-run" in sys.argv
    archive(force=force, dry_run=dry_run)
