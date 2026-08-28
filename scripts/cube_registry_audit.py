"""
cube_registry_audit.py — СВЕРКА КУБА: визуализация ↔ единая карта ↔ КОД (29.08.2026).

Повод (Егор): «нужно наводить порядок внутренний по кубу и сферам, на localhost:3000
похоже неактуальная визуализация».

Три источника правды разошлись, и разошлись молча:
  · `oko-dashboard/lib/oko-data.ts` — то, что видит глаз;
  · `docs/SIGNAL_BUS_CUBE_MAP.md` — единая карта (сведена после четырёх противоречащих
    нумераций, [[cube_map_unified_one_source]]);
  · сам КОД — единственная настоящая истина.

Скрипт печатает расхождения, а не «всё хорошо»: каждый путь из визуализации
проверяется на существование, номера сфер сверяются с картой.

🔴 Молчаливый отказ, который это ловит: панель показывает `core/intelligence/
wave_service.py` и «Sphere 14», а файла НЕТ и номер 14 занят Execution Sphere.
Глаз видит работающую сферу там, где её нет вовсе.

    python scripts/cube_registry_audit.py
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT.parent / "oko-dashboard" / "lib" / "oko-data.ts"
MAP = ROOT / "docs" / "SIGNAL_BUS_CUBE_MAP.md"
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:      # noqa: BLE001
    pass

NODE = re.compile(
    r'\{\s*id:\s*"(?P<id>[^"]+)",\s*label:\s*"(?P<label>[^"]+)"'
    r'.*?metric:\s*"(?P<metric>[^"]*)"'
    r'.*?path:\s*"(?P<path>[^"]*)"', re.S)


def dashboard_nodes() -> list[dict]:
    if not DASH.exists():
        return []
    txt = DASH.read_text(encoding="utf-8", errors="ignore")
    return [m.groupdict() for m in NODE.finditer(txt)]


def map_spheres() -> dict[int, str]:
    """
    Номера СФЕР из единой карты.

    🔴 Первая версия парсера читала таблицы по всему файлу и выдала «S14 = FUNDING_EXTREME» —
    а это ДЕТЕКТОР из сводной таблицы, не сфера. Ложный конфликт нумерации.
    Само по себе это часть беспорядка: префикс `S` в проекте обозначает и сферу
    (S14 Execution), и сигнал/детектор (S14 FUNDING_EXTREME). Читаем СТРОГО две секции.
    """
    if not MAP.exists():
        return {}
    lines = MAP.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: dict[int, str] = {}
    inside = False
    for ln in lines:
        if ln.startswith("## "):
            inside = ("Текущие сферы" in ln) or ("Сферы S13+" in ln)
            continue
        if not inside:
            continue
        m = re.match(r"\|\s*\*{0,2}(\d{1,2})\??\*{0,2}\s*\|\s*\*{0,2}([^|*]+?)\*{0,2}\s*\|", ln)
        if m:
            out.setdefault(int(m.group(1)), m.group(2).strip())
    return out


def subcube_audit() -> list[tuple[str, str, str]]:
    """
    Суб-кубы — вторая, ВЛОЖЕННАЯ решётка Куба (принцип фрактальности), и её тоже надо
    сверять: у каждого суб-куба своя таблица «Внутренние сферы» с файлом на сферу.

    Забыть про них легко: панель рисует вложенные узлы (поле `sub:` в `oko-data.ts`),
    и на глаз суб-куб выглядит существующим ровно так же, как главная сфера.
    """
    doc = ROOT / "docs" / "CUBE_SUBCUBES.md"
    if not doc.exists():
        print("  🔴 docs/CUBE_SUBCUBES.md не найден")
        return []
    dead: list[tuple[str, str, str]] = []
    cube = ""
    in_tab = False
    for ln in doc.read_text(encoding="utf-8", errors="ignore").splitlines():
        if ln.startswith("## Sub-куб"):
            cube = ln.replace("##", "").strip()
            print(f"\n  ▸ {cube}")
            in_tab = False
            continue
        if ln.startswith("### "):
            in_tab = "Внутренние сферы" in ln
            continue
        if not in_tab or not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("Сфера", "-------", "") or set(cells[0]) <= {"-"}:
            continue
        sphere = cells[0]
        m = re.search(r"`([^`]+\.py)`", cells[1])
        if not m:
            continue
        path, note = m.group(1), cells[1]
        exists = (ROOT / path).exists()
        tag = "новый" if "новый" in note else ("рефактор" if "рефактор" in note
                                               else "расширить" if "расширить" in note else "")
        if not exists:
            dead.append((cube.split(":")[-1].strip()[:16], sphere, path))
        print(f"    {'✅' if exists else '🔴 НЕТ'}  {sphere:<16} {path:<44} {tag}")
    return dead


def main() -> int:
    nodes = dashboard_nodes()
    spheres = map_spheres()

    print("=" * 100)
    print("СВЕРКА КУБА: визуализация ↔ единая карта ↔ код")
    print("=" * 100)
    print(f"визуализация: {DASH if DASH.exists() else 'НЕ НАЙДЕНА'}")
    print(f"узлов в ней: {len(nodes)} · сфер в карте: {len(spheres)}\n")

    print("── 1. ПУТИ ИЗ ВИЗУАЛИЗАЦИИ: существуют ли ──")
    dead = []
    for n in nodes:
        p = n["path"]
        exists = (ROOT / p).exists() if p else False
        mark = "✅" if exists else "🔴 НЕТ"
        if not exists:
            dead.append(n)
        print(f"  {mark:<7} {n['label']:<10} {n['metric']:<18} {p}")

    print(f"\n  битых путей: {len(dead)}")

    print("\n── 2. НОМЕРА СФЕР: что обещает панель против карты ──")
    conflicts = []
    for n in nodes:
        m = re.search(r"S(\d{1,2})", n["metric"] or "")
        if not m:
            continue
        num = int(m.group(1))
        canon = spheres.get(num, "— в карте нет —")
        ok = n["label"].lower() in canon.lower() or canon.lower() in n["label"].lower()
        if not ok:
            conflicts.append((n["label"], num, canon))
        print(f"  {'✅' if ok else '🔴'} панель: {n['label']:<8} = S{num:<3} "
              f"| карта: S{num} = {canon}")
    print(f"\n  конфликтов нумерации: {len(conflicts)}")

    print("\n── 3. ЧТО В КАРТЕ, НО НЕ ПОКАЗАНО В ПАНЕЛИ ──")
    labels = " ".join(n["label"].lower() for n in nodes)
    missing = [(k, v) for k, v in sorted(spheres.items())
               if k >= 13 and not any(w in labels for w in v.lower().split()[:2])]
    for k, v in missing:
        print(f"  S{k:<3} {v}")
    if not missing:
        print("  — нет —")

    print("\n── 4. СУБ-КУБЫ (`docs/CUBE_SUBCUBES.md`) ──")
    sub_dead = subcube_audit()

    print("\n" + "=" * 100)
    print("ИТОГ")
    print("=" * 100)
    if sub_dead:
        print(f"🔴 {len(sub_dead)} внутренних сфер суб-кубов указывают на несуществующий файл:")
        for cube, sphere, path in sub_dead:
            print(f"     {cube:<16} {sphere:<16} → {path}")
    if dead:
        print(f"🔴 {len(dead)} узлов показывают НЕСУЩЕСТВУЮЩИЙ файл:")
        for n in dead:
            print(f"     {n['label']:<10} → {n['path']}")
        print("   Панель рисует сферу как рабочую там, где кода нет вовсе.")
    if conflicts:
        print(f"🔴 {len(conflicts)} конфликтов номера:")
        for lbl, num, canon in conflicts:
            print(f"     панель зовёт S{num} «{lbl}», карта — «{canon}»")
    print("\n🔑 Истина = КОД. Порядок правок: код → карта → панель, не наоборот.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
