"""
function_map.py — AST-граф вызовов для проекта Oko MTF Bot.

Строит карту: какие функции в каких файлах определены,
и кто кого вызывает (в пределах проекта).

Использование:
    python scripts/function_map.py              # полный отчёт
    python scripts/function_map.py --calls      # только граф вызовов
    python scripts/function_map.py --file core/trading_intelligence.py  # один файл
"""

import ast
import sys
import os
from pathlib import Path
from collections import defaultdict

# Принудительный UTF-8 для Windows-консоли
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent

# Файлы для анализа (исключаем тесты и скрипты)
INCLUDE_DIRS = ["core", "bot", "web"]
EXCLUDE_DIRS = {"__pycache__", ".venv", "tests"}


def get_py_files(dirs):
    files = []
    for d in dirs:
        p = ROOT / d
        if not p.exists():
            continue
        for f in p.rglob("*.py"):
            if not any(ex in f.parts for ex in EXCLUDE_DIRS):
                files.append(f)
    # Добавить bot_with_subscriptions.py
    main_file = ROOT / "bot_with_subscriptions.py"
    if main_file.exists():
        files.append(main_file)
    return sorted(files)


def parse_file(path):
    """Возвращает (functions, calls): списки определённых функций и вызываемых имён."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except SyntaxError:
        return [], []

    functions = []
    calls = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.current_func = None

        def visit_FunctionDef(self, node):
            self.current_func = node.name
            functions.append(node.name)
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name and self.current_func:
                calls.append((self.current_func, name))
            self.generic_visit(node)

    Visitor().visit(tree)
    return functions, calls


def relative(path):
    return str(path.relative_to(ROOT)).replace("\\", "/")


def build_map():
    files = get_py_files(INCLUDE_DIRS)
    # func_name → [file] (может быть в нескольких файлах)
    func_locations = defaultdict(list)
    # file → [func_name]
    file_funcs = {}
    # (caller_func, callee_func) — внутрипроектные вызовы
    call_edges = []

    all_calls_by_file = {}

    for f in files:
        funcs, calls = parse_file(f)
        rel = relative(f)
        file_funcs[rel] = funcs
        for fn in funcs:
            func_locations[fn].append(rel)
        all_calls_by_file[rel] = calls

    # Строим граф: только вызовы функций, определённых в проекте
    project_funcs = set(func_locations.keys())
    for rel, calls in all_calls_by_file.items():
        for caller, callee in calls:
            if callee in func_locations:
                call_edges.append((rel, caller, callee, func_locations[callee]))

    return file_funcs, func_locations, call_edges


def print_full_report(file_funcs, func_locations, call_edges):
    print("=" * 70)
    print("OKO MTF BOT — КАРТА ФУНКЦИЙ")
    print("=" * 70)

    total_funcs = sum(len(v) for v in file_funcs.values())
    print(f"\nФайлов: {len(file_funcs)}  |  Функций: {total_funcs}  |  Внутренних вызовов: {len(call_edges)}\n")

    print("─" * 70)
    print("ФУНКЦИИ ПО ФАЙЛАМ")
    print("─" * 70)
    for filepath, funcs in sorted(file_funcs.items()):
        if funcs:
            print(f"\n📄 {filepath} ({len(funcs)} функций)")
            for fn in funcs:
                marker = "🔗" if len(func_locations.get(fn, [])) > 1 else "  "
                print(f"  {marker} {fn}")

    print("\n" + "─" * 70)
    print("ГРАФ ВЫЗОВОВ (внутрипроектные)")
    print("─" * 70)
    # Группируем по файлу-источнику
    by_source = defaultdict(list)
    for src_file, caller, callee, callee_files in call_edges:
        by_source[src_file].append((caller, callee, callee_files))

    for src_file in sorted(by_source.keys()):
        edges = by_source[src_file]
        print(f"\n📄 {src_file}")
        for caller, callee, callee_files in sorted(set((c, e, tuple(f)) for c, e, f in edges)):
            targets = ", ".join(callee_files)
            print(f"  {caller}() → {callee}()  [{targets}]")


def print_calls_only(call_edges):
    """Только граф вызовов — компактный формат для быстрого чтения."""
    print("ГРАФ ВЫЗОВОВ (внутрипроектные)")
    print("─" * 60)
    by_callee = defaultdict(list)
    for src_file, caller, callee, callee_files in call_edges:
        by_callee[callee].append(f"{src_file}::{caller}")

    for callee in sorted(by_callee.keys()):
        callers = sorted(set(by_callee[callee]))
        print(f"\n{callee}()  ← вызывается из:")
        for c in callers:
            print(f"  {c}")


def print_file_report(target_file, file_funcs, func_locations, call_edges):
    """Отчёт по одному файлу: что определено и что вызывает."""
    # Найти по части пути
    matched = [k for k in file_funcs if target_file in k]
    if not matched:
        print(f"Файл не найден: {target_file}")
        return

    for filepath in matched:
        funcs = file_funcs[filepath]
        print(f"\n📄 {filepath}")
        print(f"Функций: {len(funcs)}")
        for fn in funcs:
            print(f"  • {fn}")

        # Исходящие вызовы
        outgoing = [(caller, callee, files)
                    for src, caller, callee, files in call_edges if src == filepath]
        if outgoing:
            print(f"\nИсходящие вызовы ({len(outgoing)}):")
            for caller, callee, files in sorted(set((c, e, tuple(f)) for c, e, f in outgoing)):
                print(f"  {caller}() → {callee}()  [{', '.join(files)}]")

        # Входящие вызовы
        incoming = [(src, caller, callee)
                    for src, caller, callee, files in call_edges if filepath in files]
        if incoming:
            print(f"\nВходящие вызовы (кто вызывает функции из этого файла) ({len(incoming)}):")
            for src, caller, callee in sorted(set(incoming)):
                print(f"  {src}::{caller}() → {callee}()")


if __name__ == "__main__":
    args = sys.argv[1:]

    file_funcs, func_locations, call_edges = build_map()

    if "--file" in args:
        idx = args.index("--file")
        target = args[idx + 1] if idx + 1 < len(args) else ""
        print_file_report(target, file_funcs, func_locations, call_edges)
    elif "--calls" in args:
        print_calls_only(call_edges)
    else:
        print_full_report(file_funcs, func_locations, call_edges)
