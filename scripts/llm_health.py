"""
llm_health.py — ВАХТА LLM-ЗАДАЧ: какие из них молча перестали выполняться.

Повод (Егор, 13.10.2026): «если мы меняем состав роя, выполнимые задачи не должны
МОЛЧА прекращать исполняться». В тот день аудит нашёл сразу пять таких случаев:
шесть Gemini-инструментов стояли 24 дня (fallback срабатывал только на 503, а приходил 429),
`message_composer` молча падал в статический словарь (пакет не установлен),
`news_sphere` до 02.10 две недели копил новости без разметки, советник 53 прогона подряд
отдавал заглушку. Общее у всех одно: процесс «зелёный», а задача не делается.

🔑 Проверяем НЕ журнал вызовов, а АРТЕФАКТ задачи (файл/строку в БД).
Журнал молчит про задачу, которую вообще перестали запускать, — артефакт не молчит никогда.

🔑 Свежести мало: советник пишет файл вовремя, но с заглушкой `swarm_raw`. Поэтому у задачи
есть необязательная проверка СОДЕРЖИМОГО — иначе вахта отрапортует «всё хорошо» над пустышкой.

Оповещение — через scripts/_alert.notify: Telegram (Oko-SYSTEM) + след в TASKS.md + шина Куба,
и только ПРИ СМЕНЕ состояния (ежечасное «всё по-прежнему» превращается в шум).

    python scripts/llm_health.py           # проверить и оповестить при изменении
    python scripts/llm_health.py --quiet   # без таблицы, только оповещение
    python scripts/llm_health.py --no-alert  # только показать, ничего не слать
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXTERNAL_DB = ROOT / "oko_feed" / "external_data.db"


# ── источники возраста ───────────────────────────────────────────────────────

def _age_file(rel: str) -> float | None:
    """Возраст файла-результата в часах. None = файла нет вовсе."""
    p = ROOT / rel
    if not p.exists():
        return None
    return (time.time() - p.stat().st_mtime) / 3600


def _age_glob(pattern: str) -> float | None:
    """Возраст САМОГО СВЕЖЕГО файла по маске — для задач с датой в имени (WEEKLY-2026-W42.md)."""
    files = [p for p in ROOT.glob(pattern) if p.is_file()]
    if not files:
        return None
    return (time.time() - max(p.stat().st_mtime for p in files)) / 3600


def _age_sql(db: Path, query: str) -> float | None:
    """Возраст самой свежей строки (query возвращает unixtime). None = нет строк/БД."""
    if not db.exists():
        return None
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10) as c:
            row = c.execute(query).fetchone()
        return (time.time() - row[0]) / 3600 if row and row[0] else None
    except Exception:                                    # noqa: BLE001
        return None


# ── проверки содержимого (свежий артефакт ≠ сделанная работа) ────────────────

def _advisor_is_real() -> tuple[bool, str]:
    """Советник пишет файл даже когда синтезировать вердикт некому: label=swarm_raw, conf 0.3."""
    p = ROOT / "memory" / "advisor_brief_log.jsonl"
    try:
        last = None
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last = json.loads(line)
        if not last:
            return False, "журнал пуст"
        if last.get("advisor_id", "").startswith("swarm-raw"):
            return False, "заглушка swarm_raw (синтезатор недоступен)"
        return True, ""
    except Exception as e:                               # noqa: BLE001
        return False, f"журнал не читается: {e}"


def _news_tone_share() -> tuple[bool, str]:
    """news_sphere: строки копятся всегда, а вот размечаются ли — отдельный вопрос."""
    try:
        with sqlite3.connect(f"file:{EXTERNAL_DB}?mode=ro", uri=True, timeout=10) as c:
            total, toned = c.execute(
                "SELECT COUNT(*), COUNT(tone) FROM news_items "
                "WHERE ts > strftime('%s','now')-21600").fetchone()
        if not total:
            return True, ""                              # новостей не было — не повод для тревоги
        share = toned / total
        return (share >= 0.05), f"за 6ч размечено {toned}/{total} ({share:.0%})"
    except Exception as e:                               # noqa: BLE001
        return False, f"БД не читается: {e}"


# ── реестр наблюдаемых задач ─────────────────────────────────────────────────
# (ключ, имя, как узнать возраст, предел в часах, чем чинить, доп. проверка содержимого)
WATCH: list[dict] = [
    {"key": "context_brief", "name": "Бриф сессии (хук SessionStart)",
     "age": lambda: _age_file("memory/session_brief.md"), "max_h": 72,
     "fix": "python tools/context_brief.py"},
    {"key": "trade_review", "name": "Разбор сделок за день",
     "age": lambda: _age_file("memory/last_trade_review.md"), "max_h": 48,
     "fix": "python tools/daily_trade_review.py"},
    {"key": "log_digest", "name": "Дайджест логов",
     "age": lambda: _age_file("memory/log_digest.md"), "max_h": 48,
     "fix": "python tools/daily_log_digest.py"},
    {"key": "advisor", "name": "Брифинг советника (рой)",
     "age": lambda: _age_file("memory/advisor_brief.md"), "max_h": 12,
     "fix": "см. bot/loops/advisor_loop.py; нужен живой синтезатор",
     "check": _advisor_is_real},
    {"key": "news_tone", "name": "Разметка новостей (news_sphere)",
     "age": lambda: _age_sql(EXTERNAL_DB, "SELECT MAX(ts) FROM news_items"), "max_h": 6,
     "fix": "pm2 logs news-sphere; роль classify_cheap в llm_ask.ROLES",
     "check": _news_tone_share},
    {"key": "weekly_digest", "name": "Недельный дайджест Obsidian",
     "age": lambda: _age_glob("obsidian/Index/WEEKLY-*.md"), "max_h": 192,
     "fix": "python tools/obsidian_weekly_digest.py"},
    {"key": "news_compass", "name": "Часовой компас",
     "age": lambda: _age_sql(EXTERNAL_DB, "SELECT MAX(ts) FROM compass_log"), "max_h": 4,
     "fix": "pm2 logs news-sphere"},
]


def check() -> list[dict]:
    out = []
    for w in WATCH:
        try:
            age = w["age"]()
        except Exception as e:                           # noqa: BLE001
            age, err = None, str(e)[:60]
        else:
            err = ""
        bad_content, why = False, ""
        if not err and age is not None and "check" in w:
            ok, why = w["check"]()
            bad_content = not ok
        stale = age is None or age > w["max_h"] or bad_content
        out.append({**w, "age_h": age, "stale": stale, "why": why or err,
                    "reason": ("артефакта нет" if age is None and not err else
                               "ошибка проверки" if err else
                               f"{age:.0f} ч назад (предел {w['max_h']})" if age and age > w["max_h"] else
                               why if bad_content else "")})
    return out


def main() -> int:
    quiet = "--quiet" in sys.argv
    rows = check()
    bad = [r for r in rows if r["stale"]]

    if not quiet:
        print(f"{'задача':34s} {'возраст':>10s}  состояние")
        for r in rows:
            age = "—" if r["age_h"] is None else f"{r['age_h']:.1f} ч"
            mark = "🔴" if r["stale"] else "✅"
            print(f"{mark} {r['name']:32s} {age:>10s}  {r['reason'] or 'ок'}")
        print(f"\nмолчат: {len(bad)} из {len(rows)}")

    if "--no-alert" in sys.argv:
        return 1 if bad else 0

    # состояние = отсортированный список молчащих. Меняется состав → одно сообщение.
    state = ",".join(sorted(r["key"] for r in bad)) or "OK"
    # Причина и команда — в обратных кавычках: там техничиские имена вроде `swarm_raw`,
    # а одиночное подчёркивание в Markdown-режиме Telegram роняет отправку в 400 (поймано 13.10).
    lines = [f"🔇 *Молчат LLM-задачи: {len(bad)}*" if bad else "✅ *LLM-задачи: все отвечают*"]
    for r in bad:
        lines.append(f"• *{r['name']}*\n  `{r['reason']}`\n  `{r['fix']}`")
    try:
        from scripts._alert import notify
        res = notify("llm_health", state, title="Вахта LLM-задач",
                     tg_text="\n".join(lines)[:3500],
                     task_detail=("молчат: " + ", ".join(r["key"] for r in bad)) if bad
                                 else "все LLM-задачи отвечают",
                     first_time=True)
        if not quiet:
            print(f"оповещение: смена состояния={res['prev']}→{res['state']}, tg={res['tg']}")
    except Exception as e:                               # noqa: BLE001
        print(f"[llm_health] оповестить не удалось: {e}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                    # noqa: BLE001
        pass
    sys.exit(main())
