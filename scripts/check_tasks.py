#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stop hook — СЛУШАТЕЛЬ DISCUSSION.md для агентов (Даат / DS).

Когда агент собирается остановиться:
1. Ищет в DISCUSSION.md записи, АДРЕСОВАННЫЕ текущей роли (или ALL/РОЙ), на которые
   ещё нет ответа (нет нашей более новой записи выше).
2. Если есть — блокирует остановку и показывает запрос.

Формат записей (НЕ меняем — приятен к прочтению):
    ### [ДД.ММ.ГГГГ чч:мм UTC] Автор → Адресат — Суть
Адресат берётся из заголовка (Автор → Адресат), а не из тела.

Роль задаётся env AGENT_ROLE: DAAT (по умолчанию) | DS.
ARCH/DEV/TRADER оставлены как алиасы (в отпуске — не активны, но распознаются).

Подключение (settings.json):
    "Stop": [{"matcher": "*", "hooks": [{"type":"command",
      "command": "python scripts/check_tasks.py"}]}]
Для DS — то же с env AGENT_ROLE=DS.
"""
import json
import os
import re
import sys

# Windows: stdout по умолчанию cp1251 → emoji/кириллица в JSON падают. Форсим UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DISCUSSION_FILE = os.path.join(os.path.dirname(__file__), "..", "DISCUSSION.md")
TASKS_FILE = os.path.join(os.path.dirname(__file__), "..", "TASKS.md")
BACKLOG_FILE = os.path.join(os.path.dirname(__file__), "..", "docs", "BACKLOG_CONSOLIDATED.md")
def _resolve_role() -> str:
    """Роль: CLI --role > env AGENT_ROLE > .agent_role файл > DAAT.

    Дизайн (16.06.2026): оба агента (Даат=Claude Code, DS=DeepCode) исполняют ОДИН
    проектный хук `.claude/settings.json` БЕЗ `--role`. Различие роли — через env:
      • DS (DeepCode): `AGENT_ROLE=DS` в `~/.deepcode/settings.json` (секция env) — перебивает .agent_role.
      • Даат (Claude Code): env не задан → берётся `.agent_role` (=DAAT, дефолт) → DAAT.
    `.agent_role` в git держит ДЕФОЛТ (DAAT), НЕ DS (иначе перетирал бы роль Даата).
    `--role` оставлен для ручного запуска/отладки (python check_tasks.py --role DS).
    """
    if "--role" in sys.argv:
        try:
            return sys.argv[sys.argv.index("--role") + 1].strip().upper()
        except (IndexError, AttributeError):
            pass
    env_role = os.environ.get("AGENT_ROLE", "").strip().upper()
    if env_role:
        return env_role
    role_file = os.path.join(os.path.dirname(__file__), "..", ".agent_role")
    if os.path.exists(role_file):
        with open(role_file, encoding="utf-8") as f:
            file_role = f.read().strip().upper()
            if file_role:
                return file_role
    return "DAAT"

AGENT_ROLE = _resolve_role()

# Алиасы ролей (как пишутся в заголовках "Автор → Адресат")
ROLE_ALIASES = {
    "DAAT":    ["даат", "daat"],
    "DS":      ["ds"],
    # в отпуске, но распознаются:
    "ARCH":    ["arch"],
    "DEV":     ["dev"],
    "TRADER":  ["trader"],
}
# Адресаты "всем" — считаются обращением к каждому
BROADCAST = ["all", "все", "рой", "swarm"]


def _aliases(role: str) -> list[str]:
    return ROLE_ALIASES.get(role, [role.lower()])


def parse_discussion(content: str, role: str) -> list[dict]:
    """Записи, адресованные role (или ALL), без нашего ответа выше (newest-first).

    Заголовок: '### [дата] АВТОР → АДРЕСАТ — суть'. Файл newest-first: меньший idx = новее.
    Неотвечено = есть запись (адресат=role/ALL, автор≠role) и НЕТ нашей записи с меньшим idx.
    """
    my = _aliases(role)
    # Разбить на секции по заголовкам '### ['
    sections = re.split(r"(?=^### \[)", content, flags=re.M)

    hdr_re = re.compile(r"^### \[(.*?)\]\s*(.+?)\s*→\s*([^—\n]+?)(?:\s*—|\s*$|\n)", re.M)

    our_idx: list[int] = []
    addressed: list[tuple[int, str, str, str]] = []  # (idx, date, author, header_line)

    for idx, sec in enumerate(sections):
        m = hdr_re.match(sec)
        if not m:
            continue
        date_s, author, addressee = m.group(1), m.group(2).strip().lower(), m.group(3).strip().lower()
        author_is_me = any(a in author for a in my)
        if author_is_me:
            our_idx.append(idx)
            continue
        addressed_to_me = any(a in addressee for a in my) or any(b in addressee for b in BROADCAST)
        if addressed_to_me:
            # без "### " префикса — заголовок уже содержит дату
            first_line = sec.split("\n", 1)[0].lstrip("# ").strip()
            addressed.append((idx, date_s, author, first_line))

    unanswered = []
    for idx, date_s, author, header in addressed:
        # отвечено, если есть наша запись НОВЕЕ (меньший idx)
        if any(o < idx for o in our_idx):
            continue
        unanswered.append({"date": date_s, "author": author.upper(), "header": header})
    return unanswered


_ROLE_CELL = re.compile(r"^(arch|dev|trader|ds|даат|daat)(/(arch|dev|trader|ds))*$")


def parse_tasks_table(content: str, role: str) -> list[str]:
    """Незакрытые задачи роли из табличного TASKS.md (главный реестр ролей).

    Формат: | [ID](#anchor) | СТАТУС | описание | РОЛЬ |
    Берём строки где последняя колонка — РОВНО роль (не «DS 13.06»/коммит из
    секционных таблиц эпиков, где 4-я колонка = «Детали»). Не-✅, роль совпадает.
    """
    my = _aliases(role)
    out = []
    row_re = re.compile(r"^\|\s*\[?([A-Z][\w-]+)\]?[^|]*\|\s*([🔴🟡🟢🔵🔄⏸🧊])\s*\|.*\|\s*([^|]+?)\s*\|\s*$")
    for line in content.splitlines():
        m = row_re.match(line)
        if not m:
            continue
        tid, status, trole = m.group(1), m.group(2), m.group(3).strip().lower()
        if not _ROLE_CELL.match(trole):
            continue  # 4-я колонка — не роль (секционная таблица «Детали»)
        parts = trole.split("/")
        if any(a in parts for a in my):
            out.append(f"[{tid}] {status}")
    return out[:6]


def tasks_mess_count() -> int:
    """Сколько строк-задач TASKS.md нарушают формат (ячейка >200 символов = простыня).

    Триггер еженедельной гигиены: hook подсказывает `tasks_tidy.py` когда копится бардак.
    """
    if not os.path.exists(TASKS_FILE):
        return 0
    n = 0
    with open(TASKS_FILE, encoding="utf-8") as f:
        for line in f:
            if not line.lstrip().startswith("|"):
                continue
            for cell in line.split("|"):
                if len(cell.strip()) > 200:
                    n += 1
                    break
    return n


def backlog_open() -> list[str]:
    """Топ незакрытых пунктов из BACKLOG_CONSOLIDATED (🔴/🟠 не ✅) — подсказка что взять."""
    if not os.path.exists(BACKLOG_FILE):
        return []
    out = []
    with open(BACKLOG_FILE, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"\|\s*(\d+)\s*\|\s*(🔴|🟠)\s*\|\s*\*\*(.+?)\*\*", line)
            if m:
                out.append(f"#{m.group(1)} {m.group(3)}")
    return out[:5]


def main():
    role = AGENT_ROLE if AGENT_ROLE in ROLE_ALIASES else "DAAT"

    if os.path.exists(DISCUSSION_FILE):
        with open(DISCUSSION_FILE, encoding="utf-8") as f:
            content = f.read()
        unanswered = parse_discussion(content, role)
        if unanswered:
            lines = [f"  {q['header']}" for q in unanswered[:6]]
            reason = (
                f"💬 В DISCUSSION.md есть записи к {role}, без твоего ответа:\n"
                + "\n".join(lines)
                + "\n\nПрочитай DISCUSSION.md и ответь (или отметь ✅ выполнение). "
                "Новые записи — СВЕРХУ."
            )
            print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
            return

    # DISCUSSION чист → подсказка по BACKLOG + задачам роли в TASKS (approve, не блок)
    hints = []
    bl = backlog_open()
    if bl:
        hints.append("BACKLOG: " + " · ".join(bl))
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, encoding="utf-8") as f:
            my_tasks = parse_tasks_table(f.read(), role)
        if my_tasks:
            hints.append(f"TASKS({role}): " + " · ".join(my_tasks))
    mess = tasks_mess_count()
    if mess:
        hints.append(f"🧹 TASKS: {mess} простыней >200 симв → python scripts/tasks_tidy.py --apply (гигиена: DS)")
    if hints:
        print(json.dumps({
            "decision": "approve",
            "reason": "📋 DISCUSSION чист. " + " | ".join(hints),
        }, ensure_ascii=False))
        return

    print(json.dumps({"decision": "approve"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
