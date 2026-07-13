"""TASKS.md рефакторинг — пустые строки + перенос длинных описаний."""
import sys, os, re

TASKS = "TASKS.md"
DETAILS = os.path.join("docs", "DISCUSSION-TASKS-DETAILS.md")
BAK = TASKS + ".bak2"

def main(apply: bool = False):
    if not os.path.exists(TASKS):
        print("TASKS.md not found"); return

    with open(TASKS, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    details_entries = []  # [(id, short_desc, full_desc)]
    shortened = []
    blank_added = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Разделитель |---| или пустая строка или заголовок
        if not stripped or stripped.startswith("|---") or stripped.startswith("#"):
            new_lines.append(line)
            i += 1
            continue

        # Проверка: строка таблицы? (начинается с | и имеет >=3 ячеек)
        if not stripped.startswith("|"):
            new_lines.append(line)
            i += 1
            continue

        cells = [c.strip() for c in stripped.split("|")]
        # Убираем пустые ячейки по краям
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]

        # Должно быть 3-5 ячеек для строки задачи
        if len(cells) < 3:
            new_lines.append(line)
            i += 1
            continue

        # Проверяем вторую ячейку (статус) — должна содержать эмодзи ✅/🟡/🔴/🟢/🔵
        status_cell = cells[1] if len(cells) > 1 else ""
        is_task_row = any(emoji in status_cell for emoji in ["✅", "🟡", "🔴", "🟢", "🔵", "🟠", "❌", "⚠️", "☑️"])

        if not is_task_row:
            new_lines.append(line)
            i += 1
            continue

        # Это строка задачи
        desc = cells[2] if len(cells) > 2 else ""

        if len(desc) > 120:
            # Найти точку разрыва для краткого описания
            short = desc[:80]
            # Ищем разрыв по . или —
            for sep in [". ", " — ", "; ", "  "]:
                idx = short.rfind(sep)
                if idx > 40:
                    short = short[:idx]
                    break
            short = short.strip().rstrip(".").rstrip(",")
            short += "…"
            # Убрать ведущие ** если есть
            short = re.sub(r"^\*\*", "", short)

            cells[2] = short
            task_id = cells[0].strip()
            details_entries.append((task_id, short, desc))
            shortened.append(task_id)

        # Собрать строку
        new_line = "| " + " | ".join(cells) + " |\n"
        new_lines.append(new_line)
        # Пустая строка после задачи (если следующая не пустая)
        if i + 1 < len(lines) and lines[i + 1].strip():
            new_lines.append("\n")
            blank_added += 1

        i += 1

    # Отчёт dry-run
    print(f"=== DRY-RUN ===" if not apply else "=== APPLY ===")
    print(f"Задач с пустой строкой: {blank_added}")
    print(f"Укорочено описаний:    {len(shortened)}")
    if shortened:
        print(f"ID укороченных: {', '.join(shortened[:20])}{'...' if len(shortened) > 20 else ''}")

    if apply:
        os.rename(TASKS, BAK)
        print(f"Бэкап: {BAK}")
        with open(TASKS, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"TASKS.md записан ({len(new_lines)} строк)")

        # Записать детали
        if details_entries:
            if os.path.exists(DETAILS):
                with open(DETAILS, "a", encoding="utf-8") as f:
                    f.write("\n")
                    for tid, short, full in details_entries:
                        f.write(f"## ID: {tid} — {short}\n\n{full}\n\n---\n")
            else:
                with open(DETAILS, "w", encoding="utf-8") as f:
                    f.write("# TASKS — Полные описания задач\n\n")
                    f.write("> Перенесено из TASKS.md при рефакторинге 13.06.2026.\n")
                    f.write("> Краткие якоря → TASKS.md; детали → здесь.\n\n---\n\n")
                    for tid, short, full in details_entries:
                        f.write(f"## ID: {tid} — {short}\n\n{full}\n\n---\n")
            print(f"DISCUSSION-TASKS-DETAILS.md: {len(details_entries)} записей")


if __name__ == "__main__":
    apply_flag = "--apply" in sys.argv
    main(apply=apply_flag)
