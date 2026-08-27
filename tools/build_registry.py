# -*- coding: utf-8 -*-
"""РЕЕСТР ОБЪЕКТОВ ПРОЕКТА — каркас сплошной ревизии (12.08.2026).

Требование Егора: провести полную перепроверку так, чтобы НИ ОДИН инструмент, детектор,
сигнал, гипотеза или исследование не потерялись. Корпус замерен: ~393 000 строк
(проза 239k: obsidian 150.9k + DISCUSSION 41.3k + docs 24.7k + память 22k;
код 154.6k: scripts/core/bot/tools). Прочитать подряд невозможно — нужен ИНДЕКС.

Метод (согласован с DS 12.08): обход СНИЗУ ВВЕРХ — код исполняем, значит это единственный
источник правды. `ast.parse` даёт объектный скелет механически; заголовки md натягиваются
на него; DISCUSSION читается последним как хронология решений «почему убили».

Реестр в SQLite (не в markdown: запросы + отсутствие конфликтов слияния).
sha256 фиксирует содержимое — изменение объекта станет видно при повторном скане.

ТАКСОНОМИЯ (14 типов, DS): detector · hypothesis · strategy · feature · filter · param ·
code_module · verdict · research_note · external_source · formula · data_snapshot ·
pipeline · experiment. Объект, не попавший ни в один — новый тип, добавлять ЯВНО.

ЗАПУСК: python tools/build_registry.py [--rebuild]
ОТЧЁТ:  python tools/build_registry.py --report
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import os
import re
import sqlite3
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "registry.db"

CODE_DIRS = ["scripts", "core", "bot", "tools", "web", "oko_feed"]
DOC_DIRS = ["docs", "obsidian", "memory"]
DOC_ROOT_FILES = ["DISCUSSION.md", "ROADMAP.md", "TASKS.md", "BOT_SIGNAL_MAP.md", "START.md"]
SKIP_PARTS = {"node_modules", "__pycache__", ".obsidian", ".git", "backups", "cache"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    id             TEXT PRIMARY KEY,
    type           TEXT NOT NULL,      -- таксономия из 14 типов
    name           TEXT NOT NULL,
    source_path    TEXT NOT NULL,
    line_start     INTEGER,
    line_end       INTEGER,
    sha256         TEXT,               -- содержимое: правка объекта станет видна
    parent_id      TEXT,               -- модуль/родительский заголовок
    signature      TEXT,               -- сигнатура функции / уровень заголовка
    docline        TEXT,               -- первая строка докстринга или подзаголовка
    status         TEXT DEFAULT 'unknown',        -- active | dormant | killed | unknown
    verification   TEXT DEFAULT 'pending',        -- pending | verified | failed | running
    decision       TEXT,                          -- keep | merge | kill | investigate
    evidence       TEXT,                          -- ТОЛЬКО вывод скрипта или прямая цитата
    evidence_kind  TEXT,                          -- measured | quote | anecdotal
    notes          TEXT,
    scanned_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_obj_type   ON objects(type);
CREATE INDEX IF NOT EXISTS ix_obj_path   ON objects(source_path);
CREATE INDEX IF NOT EXISTS ix_obj_dec    ON objects(decision);
CREATE INDEX IF NOT EXISTS ix_obj_verif  ON objects(verification);
"""


def _skip(p: Path) -> bool:
    return any(part in SKIP_PARTS for part in p.parts)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def scan_code(rows: list) -> None:
    """AST-скелет: каждая функция и класс — объект типа code_module."""
    for d in CODE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if _skip(p):
                continue
            try:
                src = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src)
            except Exception:
                continue
            lines = src.splitlines()
            rel = _rel(p)
            mod_doc = (ast.get_docstring(tree) or "").strip().splitlines()
            rows.append(dict(
                id=f"mod::{rel}", type="code_module", name=p.name, source_path=rel,
                line_start=1, line_end=len(lines), sha256=_sha(src), parent_id=None,
                signature="module", docline=(mod_doc[0][:300] if mod_doc else None)))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                a, b = node.lineno, getattr(node, "end_lineno", node.lineno)
                body = "\n".join(lines[a - 1:b])
                doc = (ast.get_docstring(node) or "").strip().splitlines()
                if isinstance(node, ast.ClassDef):
                    sig = f"class {node.name}"
                else:
                    args = [x.arg for x in node.args.args]
                    sig = f"def {node.name}({', '.join(args)})"
                rows.append(dict(
                    id=f"fn::{rel}::{node.name}::{a}", type="code_module", name=node.name,
                    source_path=rel, line_start=a, line_end=b, sha256=_sha(body),
                    parent_id=f"mod::{rel}", signature=sig,
                    docline=(doc[0][:300] if doc else None)))


_H = re.compile(r"^(#{1,4})\s+(.+?)\s*$")


def scan_docs(rows: list) -> None:
    """Каждый заголовок md — объект research_note (тип уточняется при разметке)."""
    targets = []
    for d in DOC_DIRS:
        base = ROOT / d
        if base.exists():
            targets += [p for p in base.rglob("*.md") if not _skip(p)]
    for f in DOC_ROOT_FILES:
        p = ROOT / f
        if p.exists():
            targets.append(p)
    # авто-память Claude вне репозитория — тоже часть корпуса
    auto = Path(os.path.expanduser(
        "~/.claude/projects/e--MTF-BOT-CURSOR-crypto-volume-bot/memory"))
    if auto.exists():
        targets += list(auto.glob("*.md"))
    for p in targets:
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = _rel(p)
        lines = src.splitlines()
        rows.append(dict(
            id=f"doc::{rel}", type="research_note", name=p.name, source_path=rel,
            line_start=1, line_end=len(lines), sha256=_sha(src), parent_id=None,
            signature="document", docline=(lines[0][:300] if lines else None)))
        prev = None
        for i, ln in enumerate(lines, 1):
            m = _H.match(ln)
            if not m:
                continue
            lvl, title = len(m.group(1)), m.group(2).strip()
            if prev is not None:
                prev_i, prev_id = prev
                for r in rows:
                    if r["id"] == prev_id:
                        r["line_end"] = i - 1
                        break
            oid = f"sec::{rel}::{i}"
            rows.append(dict(
                id=oid, type="research_note", name=title[:200], source_path=rel,
                line_start=i, line_end=len(lines), sha256=_sha(title),
                parent_id=f"doc::{rel}", signature=f"h{lvl}", docline=None))
            prev = (i, oid)


def build(rebuild: bool) -> None:
    if rebuild and DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    rows: list = []
    scan_code(rows)
    scan_docs(rows)
    import datetime as dt
    now = dt.datetime.now().isoformat(timespec="seconds")
    cur = con.cursor()
    ins = upd = 0
    for r in rows:
        old = cur.execute("SELECT sha256 FROM objects WHERE id=?", (r["id"],)).fetchone()
        if old is None:
            cur.execute(
                "INSERT INTO objects (id,type,name,source_path,line_start,line_end,sha256,"
                "parent_id,signature,docline,scanned_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (r["id"], r["type"], r["name"], r["source_path"], r["line_start"],
                 r["line_end"], r["sha256"], r["parent_id"], r["signature"],
                 r["docline"], now))
            ins += 1
        elif old[0] != r["sha256"]:
            # содержимое изменилось → верификация сбрасывается, решение под вопросом
            cur.execute(
                "UPDATE objects SET sha256=?,line_start=?,line_end=?,signature=?,docline=?,"
                "verification='pending',scanned_at=? WHERE id=?",
                (r["sha256"], r["line_start"], r["line_end"], r["signature"],
                 r["docline"], now, r["id"]))
            upd += 1
    con.commit()
    print(f"реестр: +{ins} новых · {upd} изменённых · всего {cur.execute('SELECT COUNT(*) FROM objects').fetchone()[0]}")
    con.close()


def report() -> None:
    con = sqlite3.connect(DB)
    c = con.cursor()
    print("═══ РЕЕСТР ОБЪЕКТОВ ═══")
    total = c.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
    print(f"всего объектов: {total}\n")
    print("по типу:")
    for t, n in c.execute("SELECT type,COUNT(*) FROM objects GROUP BY type ORDER BY 2 DESC"):
        print(f"   {t:16} {n:6}")
    print("\nпо верификации:")
    for v, n in c.execute("SELECT verification,COUNT(*) FROM objects GROUP BY verification"):
        print(f"   {v:16} {n:6}")
    print("\nпо решению:")
    for d, n in c.execute("SELECT COALESCE(decision,'—'),COUNT(*) FROM objects GROUP BY 1"):
        print(f"   {d:16} {n:6}")
    print("\nтоп-10 файлов по числу объектов:")
    for p, n in c.execute("SELECT source_path,COUNT(*) FROM objects GROUP BY 1 ORDER BY 2 DESC LIMIT 10"):
        print(f"   {n:5}  {p}")
    print("\n── ЗАМЫКАНИЕ (критерий полноты) ──")
    fn = c.execute("SELECT COUNT(*) FROM objects WHERE type='code_module' AND signature LIKE 'def %'").fetchone()[0]
    cl = c.execute("SELECT COUNT(*) FROM objects WHERE type='code_module' AND signature LIKE 'class %'").fetchone()[0]
    mods = c.execute("SELECT COUNT(*) FROM objects WHERE signature='module'").fetchone()[0]
    docs = c.execute("SELECT COUNT(*) FROM objects WHERE signature='document'").fetchone()[0]
    secs = c.execute("SELECT COUNT(*) FROM objects WHERE signature LIKE 'h%'").fetchone()[0]
    print(f"   модулей {mods} · функций {fn} · классов {cl}")
    print(f"   документов {docs} · заголовков {secs}")
    und = c.execute("SELECT COUNT(*) FROM objects WHERE decision IS NULL").fetchone()[0]
    print(f"   БЕЗ РЕШЕНИЯ: {und} ({100*und/max(1,total):.0f}%) — ревизия завершена при 0")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="пересоздать реестр с нуля")
    ap.add_argument("--report", action="store_true", help="только отчёт")
    a = ap.parse_args()
    if a.report:
        report()
    else:
        build(a.rebuild)
        report()
