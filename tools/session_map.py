"""Карта проекта для агента — компактная, без сети и без LLM.

🔴 ЗАЧЕМ (Егор, 13.10.2026): «каждый раз мне приходится напоминать, что в проекте есть и чем мы можем
пользоваться. Агент забывает кусок, и часто очень большой. Память куда-то исчезает, а сессии длинные.»

Механизмы для этого существовали, но не работали:
  · `SessionStart` → `tools/context_brief.py` зависит от Gemini и с 19.09 падает с 429 (квота) —
    сводка не подавалась почти месяц, молча;
  · `PreCompact` → `tools/session_hooks.py` вписывает в current_state.md ПУСТОЙ шаблон «заполнить после»:
    из 26 компактов 24 шаблона остались незаполненными (92%) — он требует ручного действия ровно тогда,
    когда контекст уже сжимается.

Поэтому здесь: НИКАКИХ внешних вызовов, только чтение файлов репозитория. Карта отвечает на один вопрос —
«что у нас есть и чем пользоваться», то есть даёт ИМЕНА инструментов и карт, а не их содержание.
Подробности агент дочитает сам по имени; забыть о существовании — хуже, чем не помнить деталь.

Запуск:
    python tools/session_map.py              # markdown в stdout
    python tools/session_map.py --json        # для hookSpecificOutput.additionalContext
    python tools/session_map.py --max-kb 8    # ограничить размер
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")


def _read(rel: str, limit: int = 400_000) -> str:
    p = ROOT / rel
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def tools_from_registry() -> list[str]:
    """Имена инструментов из таблиц docs/REGISTRY.md и TOOLS.md: `scripts/x.py` · `core/y/` · скиллы."""
    text = _read("docs/REGISTRY.md") + "\n" + _read("TOOLS.md")
    names: dict[str, str] = {}
    for m in re.finditer(r"\|\s*\*{0,2}`([^`]+)`\*{0,2}[^|]*\|\s*([^|]{0,120})", text):
        name, what = m.group(1).strip(), m.group(2).strip()
        if not name or name in names:
            continue
        # только код: модуль .py или путь внутри core/ scripts/ tools/.
        # Голые папки (`logs/`, `backups/`, `data/`) — из автоинвентаря TOOLS.md, инструментами не являются.
        if not (name.endswith(".py") or name.startswith(("core/", "scripts/", "tools/"))):
            continue
        what = re.sub(r"\*\*|🔴|🔑|⭐|🧾|🌊|📊", "", what).strip(" .·—")
        names[name] = what[:95]
    for m in re.finditer(r"скилл\s+`([a-z-]+)`", text):
        names.setdefault(f"скилл {m.group(1)}", "")
    return [f"`{k}` — {v}" if v else f"`{k}`" for k, v in names.items()]


def live_now() -> list[str]:
    """Что в бою: pm2-процессы online. Факт, а не документация."""
    try:
        out = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=25,
                             shell=True).stdout
        data = json.loads(out[out.find("["):])
        online = sorted(p["name"] for p in data if p["pm2_env"].get("status") == "online")
        other = sorted(f'{p["name"]}({p["pm2_env"].get("status")})' for p in data
                       if p["pm2_env"].get("status") != "online")
        res = [f"online ({len(online)}): " + " · ".join(online)]
        if other:
            res.append(f"НЕ online ({len(other)}): " + " · ".join(other[:12]))
        return res
    except Exception as e:                                  # noqa: BLE001
        return [f"pm2 недоступен ({type(e).__name__}) — смотреть `pm2 list` руками"]


def hot_tasks(limit: int = 22) -> list[str]:
    """Строки задач со статусом 🔴 и 🔄 из TASKS.md — что горит сейчас.

    🔴 Привязанное ко времени идёт ПЕРВЫМ. Проверено 13.10: горящих строк 68, а в карту влезает два
    десятка — контрольная проверка с датой (ARCH-149.3) в хвост не попадала, и напоминание не работало бы.
    """
    rows = []
    for line in _read("TASKS.md").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[1] not in ("🔴", "🔄"):
            continue
        rid = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cells[0]).strip("* ")
        text = cells[2]
        dated = bool(re.search(r"ПРОВЕРК|КОНТРОЛ|наблюдат", text))
        rows.append((dated, f"{cells[1]} {rid} — {text[:88]}"))

    # Порядок в файле — он и есть приоритет: свежие эпики лежат сверху. Сортировать по статусу нельзя:
    # проверено 13.10 — наверх вылезают незакрытые 🔴 из июля и выдавливают ARCH-145 «вход на домен».
    head = [r for _, r in rows[:limit]]
    # Отдельно — то, у чего есть СРОК (контрольная проверка, наблюдение): такие строки теряться не должны,
    # иначе напоминание не работает (горящих строк 68, в карту влезает два десятка).
    timed = [r for d, r in rows[limit:] if d][:6]
    return head + (["— со сроком (ниже по файлу):"] + timed if timed else [])


def last_handoff() -> list[str]:
    """Заголовки свежих записей handoff'а — чем занимались в последние сессии."""
    recs = re.split(r"(?m)^(?=## \[)", _read("memory/current_state.md"))[1:]
    return [r.split("\n", 1)[0].replace("## ", "")[:110] for r in recs[:4]]


def memory_sections() -> list[str]:
    """Разделы индекса памяти — куда идти за законами и измеренным."""
    mem = Path.home() / ".claude/projects/e--MTF-BOT-CURSOR-crypto-volume-bot/memory/MEMORY.md"
    try:
        text = mem.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    return [l.replace("## ", "").strip() for l in text.splitlines() if l.startswith("## ")]


def git_state() -> list[str]:
    def run(*a):
        try:
            return subprocess.run(a, capture_output=True, text=True, timeout=20,
                                  cwd=ROOT).stdout.strip()
        except Exception:
            return ""
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    dirty = [l for l in run("git", "status", "--porcelain").splitlines() if l.strip()]
    log = run("git", "log", "--oneline", "-3").splitlines()
    res = [f"ветка `{branch}` · незакоммичено файлов: {len(dirty)}"]
    if dirty:
        res.append("  изменены: " + " · ".join(l[3:][:34] for l in dirty[:8]))
    res += ["  " + l[:100] for l in log]
    return res


def build(max_kb: float) -> str:
    L: list[str] = []
    L.append("# 🧭 КАРТА ПРОЕКТА (собрана автоматически, `tools/session_map.py`)")
    L.append("")
    L.append("Это напоминание о том, ЧТО В ПРОЕКТЕ ЕСТЬ. Подробности — в названном файле; "
             "🔴 порядок поиска: память → граф `graphify-out` → `obsidian/Research/` → реестры → grep последним.")
    L.append("")

    L.append("## 🔬 Чем пользоваться (не писать заново)")
    for t in tools_from_registry()[:34]:
        L.append(f"- {t}")
    L.append("")

    L.append("## ⚙️ Что в бою сейчас")
    for x in live_now():
        L.append(f"- {x}")
    L.append("")

    L.append("## 🔴 Горит в задачах (🔴/🔄 из TASKS.md)")
    for x in hot_tasks():
        L.append(f"- {x}")
    L.append("")

    L.append("## 📋 Последние сессии (memory/current_state.md)")
    for x in last_handoff():
        L.append(f"- {x}")
    L.append("")

    L.append("## 🧠 Разделы индекса памяти (где искать измеренное)")
    secs = memory_sections()
    if secs:
        L.append("- " + " · ".join(secs))
    L.append("")

    L.append("## 🌿 Git")
    for x in git_state():
        L.append(f"- {x}")
    L.append("")

    L.append("## 📚 Карты, которые надо читать, а не пересказывать")
    L.append("- `docs/REGISTRY.md` (реестр инструментов) · `TOOLS.md` (карта инструментов) · "
             "`docs/ENCYCLOPEDIA.md` (Куб Метатрона) · `docs/SIGNAL_BUS_CUBE_MAP.md` (шина и сферы) · "
             "`docs/BUS_CATALOG.md` + `docs/BUS_INVENTORY.md` (поля шины, кто читает) · "
             "`obsidian/Project-MOC.md` (хаб знаний) · `DISCUSSION.md` (диалог ролей)")

    text = "\n".join(L).rstrip() + "\n"
    cap = int(max_kb * 1024)
    if len(text.encode("utf-8")) > cap:
        while len(text.encode("utf-8")) > cap and "\n" in text:
            text = text[: text.rfind("\n")]
        text += "\n… (обрезано по --max-kb)\n"
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="вывести как hookSpecificOutput для хука")
    ap.add_argument("--max-kb", type=float, default=9.0)
    a = ap.parse_args()
    text = build(a.max_kb)
    if a.json:
        print(json.dumps({"hookSpecificOutput": {"additionalContext": text}}, ensure_ascii=False))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
