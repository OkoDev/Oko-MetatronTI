"""Сканер молчаливых мёртвых путей (12.08.2026).

Ищет код, который ИСПОЛНЯЕТСЯ и выглядит рабочим, но решение не принимает НИКОГДА.
Класс подтверждён четырьмя находками за одну сессию:
  1. enum→строка:  direction=str(SignalDirection.LONG) сравнивается с "LONG" → никогда
  2. порог выше максимума величины: conf >= 0.65 при физическом максимуме 0.552
  3. взаимоисключающие условия: label==STRONG_BEAR (⟺ p<0.35) И conf(=p) >= 0.65
  4. getattr на несуществующий атрибут → молча False/0

Read-only. Печатает кандидатов с файлом:строкой — каждый требует ручной проверки.

Запуск:  python tools/deadpath_scan.py [--dir core] [--verbose]
"""
from __future__ import annotations

import argparse
import ast
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".tmp", "__pycache__", "backups", "node_modules", ".venv", "venv"}

# Имена, за которыми обычно стоит вероятность/доля в [0,1]
PROBA_HINTS = ("conf", "proba", "prob", "p_win", "score", "ratio", "pct_rank")
# Источники, гарантирующие диапазон [0,1]
PROBA_SOURCES = ("predict_proba", "sigmoid", "softmax", "random.random")


def iter_py(base: Path):
    for p in base.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


class Finder(ast.NodeVisitor):
    def __init__(self, path: Path, src: str):
        self.path = path
        self.lines = src.split("\n")
        self.hits: list[tuple[str, int, str]] = []

    def _add(self, kind: str, node, msg: str):
        self.hits.append((kind, getattr(node, "lineno", 0), msg))

    # ── 1. except, который молча глотает (pass / logger.debug) ──────────
    def visit_ExceptHandler(self, node):
        body = node.body
        silent = True
        detail = ""
        for st in body:
            if isinstance(st, ast.Pass):
                detail = "pass"
                continue
            if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
                f = st.value.func
                name = getattr(f, "attr", getattr(f, "id", ""))
                if name in ("debug",):
                    detail = "logger.debug"
                    continue
            silent = False
            break
        if silent and body:
            # интересны только те, что глушат ШИРОКИЙ except
            t = node.type
            broad = t is None or (isinstance(t, ast.Name) and t.id == "Exception")
            if broad:
                self._add("SILENT_EXCEPT", node,
                          f"широкий except глушит через {detail} — отказ невидим при уровне INFO")
        self.generic_visit(node)

    # ── 2. сравнение со строковым литералом ВЕРХНЕГО регистра ──────────
    #     кандидат на enum-ловушку (str(enum) != enum.value)
    def visit_Compare(self, node):
        for op, cmp in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(cmp, ast.Constant) \
                    and isinstance(cmp.value, str):
                v = cmp.value
                if v and v.isupper() and len(v) > 1 and "_" not in v[:1]:
                    left = node.left
                    # str(x) == "LONG" — прямая ловушка
                    if isinstance(left, ast.Call) and getattr(left.func, "id", "") == "str":
                        self._add("ENUM_STR_CMP", node,
                                  f'str(...) == "{v}" — str(enum) даёт "Class.NAME", не "{v}"')
                    elif isinstance(left, ast.Name):
                        self._add("UPPER_STR_CMP", node,
                                  f'{left.id} == "{v}" — проверить, что слева .value, а не str(enum)')
            # ── 3. порог для величины-вероятности ──────────────────────
            if isinstance(op, (ast.GtE, ast.Gt)) and isinstance(cmp, ast.Constant) \
                    and isinstance(cmp.value, (int, float)) and not isinstance(cmp.value, bool):
                left = node.left
                nm = getattr(left, "id", getattr(left, "attr", "")) or ""
                if any(h in nm.lower() for h in PROBA_HINTS) and 0 < float(cmp.value) < 1:
                    if float(cmp.value) >= 0.6:
                        self._add("PROBA_THRESHOLD", node,
                                  f"{nm} >= {cmp.value} — сверить с ФАКТИЧЕСКИМ максимумом величины")
        self.generic_visit(node)

    # ── 4. getattr(obj, "литерал", default) ────────────────────────────
    def visit_Call(self, node):
        if getattr(node.func, "id", "") == "getattr" and len(node.args) >= 2:
            a1 = node.args[1]
            if isinstance(a1, ast.Constant) and isinstance(a1.value, str):
                has_default = len(node.args) >= 3
                if has_default:
                    self._add("GETATTR_DEFAULT", node,
                              f'getattr(..., "{a1.value}", default) — опечатка в имени вернёт default МОЛЧА')
        self.generic_visit(node)


def main():
    ap = argparse.ArgumentParser(description="Сканер молчаливых мёртвых путей")
    ap.add_argument("--dir", default="core", help="каталог (по умолчанию core)")
    ap.add_argument("--verbose", "-v", action="store_true", help="печатать все GETATTR_DEFAULT")
    args = ap.parse_args()

    base = ROOT / args.dir
    by_kind: dict[str, list[str]] = defaultdict(list)
    files = 0

    for p in iter_py(base):
        try:
            src = p.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
        except Exception:
            continue
        files += 1
        f = Finder(p, src)
        f.visit(tree)
        rel = p.relative_to(ROOT).as_posix()
        for kind, line, msg in f.hits:
            by_kind[kind].append(f"{rel}:{line}  {msg}")

    order = ["ENUM_STR_CMP", "PROBA_THRESHOLD", "SILENT_EXCEPT", "UPPER_STR_CMP", "GETATTR_DEFAULT"]
    print(f"# Сканер мёртвых путей — {files} файлов в {args.dir}/\n")
    for kind in order:
        rows = by_kind.get(kind, [])
        cap = None if (args.verbose or kind in ("ENUM_STR_CMP", "PROBA_THRESHOLD")) else 15
        print(f"## {kind}: {len(rows)}")
        for r in rows[:cap]:
            print("   ", r)
        if cap and len(rows) > cap:
            print(f"    … ещё {len(rows)-cap} (--verbose)")
        print()

    print("ENUM_STR_CMP и PROBA_THRESHOLD — смотреть В ПЕРВУЮ ОЧЕРЕДЬ:")
    print("  оба класса уже дали подтверждённые мёртвые гейты (verdict_gate, 12.08).")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
