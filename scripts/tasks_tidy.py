# -*- coding: utf-8 -*-
"""Наведение порядка в TASKS.md (Архив ✅ + косметика).

Безопасные операции:
  1. Удаление пустых строк ВНУТРИ markdown-таблиц (рвут рендеринг).
  2. Перенос уверенно-закрытых (✅) задач в TASKS-ARCHIVE.md полными карточками.
     Консервативно: переносим ТОЛЬКО если статус-ячейка == ✅ и "выглядит как статус".
     При любой неоднозначности — строка ОСТАЁТСЯ в TASKS (не прячем активную).

Строки копируются ЦЕЛИКОМ (без пересборки по '|') → текст ячеек не искажается,
literal '|' внутри текста не ломает результат.

Запуск:
  python scripts/tasks_tidy.py          # dry-run (ничего не пишет)
  python scripts/tasks_tidy.py --apply  # запись
"""
from __future__ import annotations
import sys, datetime

sys.stdout.reconfigure(encoding="utf-8")

TASKS = "TASKS.md"
ARCHIVE = "TASKS-ARCHIVE.md"
APPLY = "--apply" in sys.argv

STATUS_EMOJI = set("✅🔴🟡🟢🔵🔄⏸🧊⏳🚀🔍❓💀⚙️")

def is_row(l: str) -> bool:
    return l.lstrip().startswith("|")

def cells(l: str):
    p = l.split("|")
    if p and p[0].strip() == "": p = p[1:]
    if p and p[-1].strip() == "": p = p[:-1]
    return p

def is_header(cs) -> bool:
    return bool(cs) and cs[0].strip().strip("*").lower() == "id"

def is_separator(cs) -> bool:
    return set("".join(cs)).issubset(set("-: "))

def status_col_index(header_cells):
    """Индекс статус-колонки в этой таблице (или None)."""
    for k, c in enumerate(header_cells):
        cl = c.strip().lower()
        if cl in ("ст", "статус") or "верифик" in cl or cl.startswith("статус"):
            return k
    return None

def looks_like_status(cell: str) -> bool:
    """Ячейка похожа на статус: короткая, есть статус-эмодзи, нет markdown/текста-описания."""
    c = cell.replace("~~", "").strip()
    if not c or len(c) > 16:
        return False
    if "**" in c or "`" in c or "[" in c:
        return False
    return any(ch in STATUS_EMOJI for ch in c)

def main():
    raw = open(TASKS, encoding="utf-8").read()
    lines = raw.split("\n")

    out = []                 # новые строки TASKS.md
    archived = []            # (section, role_or_file, full_line)
    ambiguous = []           # (lineno, id, reason)
    done_list = []           # (lineno, id, section)

    cur_section = "(без секции)"
    hdr_cells = None
    st_idx = None
    in_table = False

    n = len(lines)
    for i, l in enumerate(lines):
        s = l.strip()
        nxt = lines[i + 1] if i + 1 < n else ""

        # заголовки секций трекаем
        if s.startswith("## "):
            cur_section = s.lstrip("# ").strip()

        if not is_row(l):
            # пустая строка внутри таблицы → выкинуть
            if s == "" and in_table and is_row(nxt):
                continue
            in_table = False
            out.append(l)
            continue

        cs = cells(l)

        if is_header(cs):
            hdr_cells = cs
            st_idx = status_col_index(cs)
            in_table = True
            out.append(l)
            continue
        if is_separator(cs):
            in_table = True
            out.append(l)
            continue
        # подзаголовок-разделитель внутри таблицы: ≤1 непустая ячейка
        nonempty = [c for c in cs if c.strip() != ""]
        if len(nonempty) <= 1:
            in_table = True
            # трекаем как под-секцию для архива
            if nonempty:
                cur_section = nonempty[0].strip().strip("*")
            out.append(l)
            continue

        in_table = True
        # --- task row: классификация ---
        rid = cs[0].strip()
        ncols = len(hdr_cells) if hdr_cells else None
        scell = None
        if st_idx is not None and st_idx < len(cs):
            scell = cs[st_idx]
        is_done = False
        # переносим ТОЛЬКО при совпадении числа колонок (нет literal-| сдвига)
        # и чистой статус-ячейке, начинающейся с ✅
        if (scell is not None and ncols is not None and len(cs) == ncols
                and looks_like_status(scell)
                and scell.replace("~~", "").strip().startswith("✅")):
            is_done = True
        elif scell is not None and "✅" in scell and not is_done:
            # ✅ есть, но строку оставляем (горячая / с пояснением / literal-| сдвиг)
            ambiguous.append((i + 1, rid, "✅ оставлен в TASKS"))

        if is_done:
            role = cs[-1].strip() if len(cs) >= 2 else ""
            archived.append((cur_section, role, l))
            done_list.append((i + 1, rid, cur_section))
        else:
            out.append(l)

    # отчёт
    print(f"=== DRY-RUN ===" if not APPLY else "=== APPLY ===")
    print(f"исходно строк: {len(lines)} | задач-строк всего: 303 (по анализу)")
    print(f"в архив (уверенно ✅): {len(done_list)}")
    print(f"осталось строк в TASKS: {len(out)}")
    print(f"неоднозначных (оставлены в TASKS): {len(ambiguous)}")
    print("\n--- ПЕРЕНОСИМ В АРХИВ ---")
    for ln, rid, sec in done_list:
        print(f"  L{ln:<4} {rid:<24} | {sec[:50]}")
    print("\n--- НЕОДНОЗНАЧНЫЕ (НЕ переносим, проверь) ---")
    for ln, rid, why in ambiguous:
        print(f"  L{ln:<4} {rid:<24} | {why}")

    # проверка: ключевые активные НЕ должны попасть в архив
    done_ids = {rid for _, rid, _ in done_list}
    must_stay = ["REGIME-V2", "ARCH-129-FLOW", "ARCH-96-MULTIACCT", "ARCH-96-HUB",
                 "WAVE-SERVICE", "WAVE-FLAGMAN", "OPS-05", "DS-326", "PROXY-NODE"]
    leaked = [m for m in must_stay if any(m == d.strip("*[]") or m in d for d in done_ids)]
    print("\n--- SANITY: ключевые активные, ошибочно унесённые в архив ---")
    print("  " + ("НЕТ — чисто ✅" if not leaked else "🔴 УТЕЧКА: " + ", ".join(leaked)))

    if not APPLY:
        print("\n(dry-run — файлы не изменены; запусти с --apply)")
        return
    if leaked:
        print("\n🔴 ОТМЕНА записи — обнаружена утечка активных. Поправь логику.")
        return

    # --- бэкап + запись TASKS.md ---
    open(TASKS + ".bak", "w", encoding="utf-8").write(raw)
    open(TASKS, "w", encoding="utf-8").write("\n".join(out))

    # --- дозапись в архив, сгруппировано по секции ---
    today = datetime.date.today().strftime("%d.%m.%Y")
    blocks = []
    by_sec = {}
    order = []
    for sec, role, line in archived:
        if sec not in by_sec:
            by_sec[sec] = []
            order.append(sec)
        by_sec[sec].append(line)
    chunk = [f"\n---\n\n## ✅ Перенесено из TASKS.md {today} (полные карточки)\n"]
    for sec in order:
        chunk.append(f"\n### {sec}\n")
        chunk.append("| ID | Ст | Описание | Роль |")
        chunk.append("|---|---|---|---|")
        chunk.extend(by_sec[sec])
    with open(ARCHIVE, "a", encoding="utf-8") as f:
        f.write("\n".join(chunk) + "\n")

    print(f"\nЗаписано: TASKS.md ({len(out)} строк), архив +{len(archived)} карточек.")

if __name__ == "__main__":
    main()
