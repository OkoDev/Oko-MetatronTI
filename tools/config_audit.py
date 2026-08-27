"""Аудит конфига: флаги-сироты и флаги-призраки (12.08.2026).

Повод — sed-инцидент 16.07: массовая правка выключила 5 чужих `enabled`,
из них 3 остались незамеченными на 27 дней (`memory/sed_incident_5_flags_off.md`).
Класс шире: «переключатель есть, поведения нет» и наоборот.

Ищет два перекоса между config.yaml и кодом:
  СИРОТА  — ключ есть в config.yaml, но НИКТО его не читает → правка ничего не меняет
  ПРИЗРАК — код читает ключ, которого НЕТ в config.yaml → молча берётся дефолт из кода

Read-only. Оба класса требуют глазами: часть сирот легитимна (данные, а не флаги).

Запуск:  python tools/config_audit.py [--only-flags]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".git", ".tmp", "__pycache__", "backups", "node_modules", ".venv", "venv", "tests"}

# config.get("a.b.c") / cfg.get('a.b') — dot-path
DOT = re.compile(r"""\.get\(\s*['"]([a-z0-9_]+(?:\.[a-z0-9_]+)+)['"]""", re.I)
# .get("trading", {}).get("verdict_gate", {}).get("enabled"  — цепочка
CHAIN = re.compile(r"""\.get\(\s*['"]([a-z0-9_]+)['"]\s*,\s*\{\}\s*\)""", re.I)


def leaf_paths(node, pre=""):
    """Все листовые пути конфига: trading.verdict_gate.enabled → значение."""
    out = {}
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{pre}.{k}" if pre else str(k)
            if isinstance(v, dict):
                out.update(leaf_paths(v, p))
            else:
                out[p] = v
    return out


def main():
    ap = argparse.ArgumentParser(description="Аудит config.yaml против кода")
    ap.add_argument("--only-flags", action="store_true",
                    help="только булевы ключи (enabled/shadow/use_*) — самый рискованный класс")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    paths = leaf_paths(cfg)

    # Всё, что код упоминает: dot-пути + отдельные сегменты цепочек + голые имена ключей
    dotted: set[str] = set()
    segments: set[str] = set()
    files = 0
    for p in ROOT.rglob("*.py"):
        if any(s in p.parts for s in SKIP):
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        files += 1
        for m in DOT.finditer(src):
            dotted.add(m.group(1))
        for m in CHAIN.finditer(src):
            segments.add(m.group(1))
        # голые строковые литералы — грубо, но ловит .get("enabled") внутри цепочки
        for m in re.finditer(r"""['"]([a-z][a-z0-9_]{2,})['"]""", src):
            segments.add(m.group(1))

    def mentioned(path: str) -> bool:
        if path in dotted:
            return True
        # префиксы: код мог взять поддерево config.get("trading.verdict_gate")
        parts = path.split(".")
        for i in range(1, len(parts)):
            if ".".join(parts[:i]) in dotted:
                return True
        # все сегменты встречаются как литералы (цепочечный доступ)
        return all(seg in segments for seg in parts)

    # 🔴 Проверка РАНТАЙМОМ, а не текстом. ConfigProxy маппит поддеревья на
    # pydantic-модель (`sl_tp_engine.*` доступен как `trading.*`), поэтому «ключ
    # не упомянут в коде» ЕЩЁ НЕ значит «не читается». Без этой проверки аудитор
    # сам становится прибором, который врёт — ровно тем, что чинили 12.08.
    import sys as _sys
    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))   # запуск из tools/ иначе не видит core/
    try:
        from core.infra.config_loader import config as _live
    except Exception as _e:
        # НЕ глушить молча: без рантайма аудит выдаёт горы ложных сирот
        print(f"🔴 РАНТАЙМ-ПРОВЕРКА НЕДОСТУПНА ({_e!r}) — список сирот НЕДОСТОВЕРЕН\n")
        _live = None

    def reachable(path: str, val) -> bool:
        """Отдаёт ли рантайм это значение — хоть по своему пути, хоть по чужому."""
        if _live is None:
            return False
        if str(_live.get(path, "\0__miss__")) == str(val):
            return True
        # то же имя в соседнем поддереве (типичный маппинг pydantic)
        leaf = path.split(".")[-1]
        for alt in ("trading", "sl_tp_engine", "performance", "signal_quality"):
            if str(_live.get(f"{alt}.{leaf}", "\0__miss__")) == str(val):
                return True
        return False

    orphans = []
    for path, val in sorted(paths.items()):
        if args.only_flags and not isinstance(val, bool):
            continue
        if mentioned(path) or reachable(path, val):
            continue
        orphans.append((path, val))

    ghosts = []
    for d in sorted(dotted):
        if d in paths:
            continue
        # поддерево конфига — не призрак
        if any(k.startswith(d + ".") for k in paths):
            continue
        # рантайм отдаёт значение (маппинг pydantic на соседнее поддерево) — не призрак
        if _live is not None and _live.get(d) is not None:
            continue
        ghosts.append(d)

    print(f"# Аудит конфига — {files} .py файлов, {len(paths)} листовых ключей\n")
    print(f"## СИРОТЫ: {len(orphans)} — ключ в config.yaml, но код его НЕ читает")
    print("   (правка такого ключа не меняет ничего — как выключенный event_bus, только тише)")
    for p, v in orphans[:40]:
        print(f"    {p:<55} = {v}")
    if len(orphans) > 40:
        print(f"    … ещё {len(orphans)-40}")
    print()
    print(f"## ПРИЗРАКИ: {len(ghosts)} — код читает, в config.yaml НЕТ (молча берётся дефолт)")
    for g in ghosts[:40]:
        print(f"    {g}")
    if len(ghosts) > 40:
        print(f"    … ещё {len(ghosts)-40}")
    print()
    print("Оба списка требуют глаз: эвристика по литералам даёт ложные срабатывания.")
    print("Смотреть в первую очередь БУЛЕВЫ сироты — это молчаливо мёртвые переключатели.")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
