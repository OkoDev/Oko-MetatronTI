# -*- coding: utf-8 -*-
"""Опись шины (ARCH-142.1, 13.10.2026): что в ней есть, кто пишет, кто читает, чего нет и кто считает мимо.

Повод — Егор 13.10: «данных в шине нет — это упущение, которое ведёт к новым дублям в скриптах и логиках».
Каталог `core/context/bus_catalog.py` знает ПОЛЕ и ПИСАТЕЛЯ. Здесь к нему добавлено то, чего в нём нет:
  1) читатели каждого поля (по упоминаниям в коде — оценка, не доказательство);
  2) сверка с живым хабом: какие поля реально приходят и есть ли у снимков отметка времени (урок F01:
     снимок структуры 10 часов отдавался старым, и читатель не мог этого увидеть);
  3) чего в шине нет, хотя это считают и показывают;
  4) кто считает структуру / волны / пивоты сам, мимо шины.

Запуск:  python scripts/bus_inventory.py            → docs/BUS_INVENTORY.md
         python scripts/bus_inventory.py --print    → только в консоль
Ничего не меняет в боте и в шине: читает код и один GET к хабу.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.context import bus_catalog  # noqa: E402

HUB = "http://127.0.0.1:8020"
SCAN_DIRS = ("core", "bot", "web", "scripts")
SKIP = ("_archive", "__pycache__", "tests", "bus_catalog.py", "pair_context.py", "bus_inventory.py")

# Чего в шине НЕТ (проверено 13.10.2026 по живому состоянию BTC и по PairState) и кому это нужно.
MISSING = [
    ("недельный ТФ в структуре", "smc_snap считает 3m…1d", "карточка зон (глобальный взгляд)"),
    ("точки импульса 0–5 по каскаду ТФ", "в шине только нога origin→ext и счётчики свингов", "карточка, разбор волн, гипотезы"),
    ("ABC после импульса", "нет", "карточка, гипотезы"),
    ("профиль объёма (POC, узлы)", "нет", "карточка зон"),
    ("полный список ордер-блоков", "в smc_snap только ближайшие бычий и медвежий", "карточка зон, цели"),
    ("зоны схождения факторов", "нет — это результат карточки", "терминал, анализ по запросу, /moment"),
    ("гипотезы (подтверждение, цель, отмена, переход)", "нет", "разбор волн, карточка"),
    ("пивоты квартала и года", "pivot_snap содержит 1D / 1W / 1M", "карточка зон (глобальный взгляд)"),
]

# Импорт этих модулей = «считаю сам» структуру, волны или пивоты.
DETECTOR_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(core\.structure(?:\.\w+)?|core\.smc\.(?:oko_sm_engine|smc_engine|impulse_assembly|dc_legs|sub_cube)"
    r"|core\.waves\.(?:wave5_core|wave_analyst|wave_progress)|core\.pivots\.\w+)\b"
    r"|calculate_pivot_points", re.M)
HISTORY_NAME = re.compile(r"(_lab|_bt|backtest|research|audit|verify|_sim|calib|parity|backfill|replay|dataset|train|miner|forward)", re.I)
# Производители шины и ядро: им считать положено.
PRODUCERS = ("bot/loops/scan_loop.py", "bot/loops/wave_loop.py", "core/intelligence/wave_service.py",
             "core/smc/", "core/structure/", "core/waves/", "core/pivots/", "core/indicators/")


def py_files():
    for d in SCAN_DIRS:
        for f in (ROOT / d).rglob("*.py"):
            rel = f.relative_to(ROOT).as_posix()
            if not any(s in rel for s in SKIP):
                yield rel, f


def readers(fields: list[str]) -> dict[str, list[str]]:
    """Файлы, где поле упоминается как атрибут или строковый ключ. Грубая оценка: общие слова дают шум."""
    pats = {f: re.compile(r"(?:\.|[\"'])" + re.escape(f) + r"\b") for f in fields}
    out = defaultdict(list)
    for rel, f in py_files():
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, p in pats.items():
            if name in src and p.search(src):
                out[name].append(rel)
    return out


def live_state(sym: str = "BTC/USDT:USDT") -> dict:
    try:
        st = json.load(urllib.request.urlopen(f"{HUB}/state/" + urllib.parse.quote(sym, safe=""), timeout=5))
        return st.get("state", st) or {}
    except Exception as e:  # noqa: BLE001
        print(f"[опись] хаб недоступен ({type(e).__name__}) — раздел живой сверки пропущен")
        return {}


def snapshot_time_keys(v) -> list[str]:
    return [k for k in v if re.search(r"(^ts$|time|timestamp|updated)", str(k), re.I)] if isinstance(v, dict) else []


def pm2_scripts() -> set[str]:
    """Скрипты, которые pm2 запускает напрямую, — они работают «на сейчас». pm2 недоступен → пусто."""
    import os
    import subprocess
    try:
        pm2 = os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "pm2", "bin", "pm2")
        raw = subprocess.run(["node", pm2, "jlist"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=30, shell=False).stdout
        out = set()
        for p in json.loads(raw[raw.index("["):]):
            e = p["pm2_env"]
            for c in [e.get("pm_exec_path", "")] + [a for a in (e.get("args") or []) if isinstance(a, str)]:
                if c.endswith(".py"):
                    f = Path(c) if Path(c).is_absolute() else Path(e.get("pm_cwd", ".")) / c
                    try:
                        out.add(f.resolve().relative_to(ROOT).as_posix())
                    except ValueError:
                        pass
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[опись] pm2 недоступен ({type(e).__name__}) — признак «работает сейчас» только по папке")
        return set()


def self_computers() -> tuple[list[tuple[str, list[str]]], int]:
    """Кандидаты «считает мимо шины»: импортирует детектор, не производитель и не замер на истории."""
    cand, hist = [], 0
    for rel, f in py_files():
        if any(rel.startswith(p) or rel == p for p in PRODUCERS):
            continue
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        mods = sorted({m.group(1) or "calculate_pivot_points" for m in DETECTOR_IMPORT.finditer(src)})
        if not mods:
            continue
        if HISTORY_NAME.search(Path(rel).name):
            hist += 1
            continue
        cand.append((rel, mods))
    return sorted(cand), hist


def build() -> str:
    cat = bus_catalog.catalog()
    pair = cat["pair_state_L1"]
    names = [p["name"] for p in pair]
    rd = readers(names)
    live = live_state()
    L = ["# 🧾 ОПИСЬ ШИНЫ — кто пишет, кто читает, чего нет, кто считает мимо",
         "",
         f"> Сгенерировано `scripts/bus_inventory.py` {datetime.now(timezone.utc):%d.%m.%Y %H:%M} UTC (ARCH-142.1).",
         "> Писатели — из `core/context/bus_catalog.py`. Читатели — по упоминаниям имени поля в коде: это ОЦЕНКА,",
         "> у общих слов (`regime`, `watchlist`) она завышена. Правило ARCH-142: всё, что нужно «на сейчас», читается",
         "> из шины; считать самому можно только замер на истории — теми же функциями ядра.",
         ""]
    miss = bus_catalog.validate()
    L += ["## 1. Сводка",
          "",
          f"- полей пары в коде: **{len(names)}** · без описания в каталоге: **{len([m for m in miss if m.startswith('PairState')])}**",
          f"- полей без единого упоминания вне определения: **{sum(1 for n in names if not rd.get(n))}**"]
    if live:
        lk = {k for k in live if not k.startswith("_")} - {"symbol"}
        L += [f"- в живом хабе у BTC полей: **{len(lk)}** · есть в коде, но не пришло: "
              f"{', '.join(sorted(set(names) - lk)) or 'нет'} · пришло, но нет в коде: {', '.join(sorted(lk - set(names))) or 'нет'}",
              f"- возраст состояния BTC в хабе: {live.get('_age_sec')} с"]
    L += ["", "## 2. Снимки и отметка времени (урок F01)",
          "",
          "Снимок без отметки времени читатель не может проверить на свежесть.",
          "",
          "| Поле-снимок | Ключи времени внутри | Отдельное поле времени |",
          "|---|---|---|"]
    for n in names:
        v = live.get(n)
        if isinstance(v, dict) and v:
            sib = [x for x in names if x != n and re.search(r"(time|updated_at|_ts)$", x) and x.split("_")[0] == n.split("_")[0]]
            inner = snapshot_time_keys(v)
            L.append(f"| `{n}` | {', '.join(inner) or '**нет**'} | {', '.join('`' + s + '`' for s in sib) or '—'} |")
    L += ["", "## 3. Поля пары: писатель и читатели",
          "",
          "| Поле | Писатель | Упоминается в файлах | Где (до 3) |",
          "|---|---|---|---|"]
    for p in pair:
        r = rd.get(p["name"], [])
        L.append(f"| `{p['name']}` | {p['source']} | {len(r)} | {', '.join(r[:3]) or '**никто**'} |")
    L += ["", "## 4. Чего в шине нет",
          "",
          "| Чего нет | Что есть вместо | Кому нужно |",
          "|---|---|---|"]
    L += [f"| {a} | {b} | {c} |" for a, b, c in MISSING]
    cand, hist = self_computers()
    pm2 = pm2_scripts()
    live_now = [(r, m) for r, m in cand if r in pm2 or not r.startswith("scripts/")]
    rest = [(r, m) for r, m in cand if (r, m) not in live_now]
    L += ["", "## 5. Кто считает структуру, волны или пивоты сам",
          "",
          f"Детекторы напрямую импортируют **{len(cand)}** файлов вне производителей шины (ещё {hist} отсеяны как замеры на",
          f"истории по имени файла). Из них **работают «на сейчас»** — под pm2, в боте, вебе или ядре — **{len(live_now)}**;",
          f"остальные {len(rest)} лежат в `scripts/` и запускаются руками: это в основном исследования, но имя файла — слабый",
          "признак, разбирать по одному. Не всё здесь дубль: теневой журнал или терминал со своим источником свечей",
          "считать вправе. Вопрос к каждому один — лежит ли уже в шине то, что он считает.",
          "",
          "### 5.1. Работают «на сейчас»",
          "",
          "| Файл | Под pm2 | Что считает сам |",
          "|---|---|---|"]
    L += [f"| `{rel}` | {'да' if rel in pm2 else '—'} | {', '.join(m.replace('core.', '') for m in mods)} |" for rel, mods in live_now]
    L += ["", "### 5.2. Скрипты ручного запуска",
          "",
          ", ".join(f"`{Path(r).name}`" for r, _ in rest)]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    md = build()
    if "--print" in sys.argv:
        print(md)
    else:
        out = ROOT / "docs" / "BUS_INVENTORY.md"
        out.write_text(md, encoding="utf-8")
        head = md.split("## 2.")[0]
        print(head)
        print(f"→ {out}")
