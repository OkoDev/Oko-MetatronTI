"""Project Timeline — долговременная память проекта (двухпроходный pipeline).

ПРОХОД 1 (per-month):
  Для каждого DISCUSSION-ARCHIVE-<MONTH>.md → Gemini → кратко выжимаем месяц
  → memory/_timeline_parts/<MONTH>.md (промежуточное)

ПРОХОД 2 (merge):
  Все per-month + TASKS-ARCHIVE → Gemini → финальная хронология
  → memory/project_timeline.md
  → obsidian/Project-Log/<DATE>-timeline.md

Так обходим лимит 250k input токенов/мин: каждый запрос ~80-120k.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

OUTPUT_MEMORY = PROJECT_ROOT / "memory" / "project_timeline.md"
OUTPUT_OBSIDIAN_DIR = PROJECT_ROOT / "obsidian" / "Project-Log"
PARTS_DIR = PROJECT_ROOT / "memory" / "_timeline_parts"

GEMINI_MODEL_PRIMARY = "gemini-2.5-flash"
GEMINI_MODEL_FALLBACK = "gemini-2.5-flash-lite"
MAX_OUTPUT_TOKENS_MONTH = 8000
MAX_OUTPUT_TOKENS_MERGE = 16000


MONTH_PROMPT = """Ты — историк проекта Oko MTF (торговый бот).

Тебе дан АРХИВ обсуждений агентов (DEV, ARCH, TRADER) за ОДИН МЕСЯЦ.
Сделай ПЛОТНУЮ выжимку этого месяца — максимум 600-800 строк.

ФОРМАТ (markdown, русский):

# Месяц: {month_name}

## 🎯 Главные темы и фазы
3-7 главных направлений работы в этом месяце. Что строили, что чинили.

## 🏆 Принятые архитектурные решения (ARCH)
По дате: `[YYYY-MM-DD] ARCH-X — суть. Почему важно.`

## 🔬 Изменения в стратегиях
Какие стратегии трогали (wt_signal, pivot_reversal, atr_change, mtf_bias, OTE, confluence,
range_bounce, multi_signal, wt_b_signal, watch_list_breach, mtf_smc):
- параметры пробовали
- что сработало / что отвалилось

## ⚠️ Главные баги/инциденты
Что ломалось, root cause, как чинили, потери (в R если упоминается).

## 📊 Ключевые цифры
avgR, WR, n сделок, если упоминаются по этому месяцу.

## 🧠 Уроки месяца
3-5 главных принципов / выводов которые проект усвоил.

ПРАВИЛА:
- Цитируй ID (DEV-XXX, ARCH-XXX, TR-XXX) и даты.
- Только факты из источника. Не повторяйся.
- Bullet-points, не абзацы.
- Только русский.

ИСТОЧНИК:

{archive_text}
"""


MERGE_PROMPT = """Ты — историк проекта Oko MTF (торговый бот для крипторынка).
Тебе даны ВЫЖИМКИ за разные месяцы + архив задач. Создай ФИНАЛЬНУЮ ХРОНОЛОГИЮ проекта
для будущих сессий Claude (долговременная память).

ФОРМАТ (markdown, русский, 1500-2500 строк МАКСИМУМ):

# Project Timeline — Oko MTF Bot

## 🎯 Главные фазы проекта (по времени)
Раздели всю историю на 4-7 ФАЗ. Для каждой:
- Название фазы (короткое)
- Период (даты)
- Цель
- Что получилось / что пошло не так
- Урок фазы

## 🏆 Архитектурная эволюция
Хронологически: ARCH-X решения с группировкой по темам
(Куб Метатрона, Execution, ML, EventBus, Risk Intelligence, MTF, ...).

## 🔬 Эволюция стратегий
Для каждой стратегии: появление → эволюция → текущий статус.
Стратегии: wt_signal, pivot_reversal, wt_b_signal, atr_change, mtf_bias, OTE C1,
confluence, multi_signal, range_bounce, watch_list_breach, mtf_smc, sideways.

## ⚠️ Самые болезненные баги и фиксы
ТОП-10 инцидентов: что было, потери (R), root cause, фикс, урок.

## 📊 Динамика метрик по месяцам
avgR, WR, n trades — март/апрель/май.
Главные победы и провалы каждого месяца.

## 🧠 Главные уроки проекта (метаразумные)
5-10 принципов которые проект усвоил кровью:
- Принцип
- Что произошло чтобы это понять
- Когда применять

## 👥 Роли и эволюция
DEV / ARCH / TRADER — как роли работали, ключевые персонажи (Claude TRADER, oko.webdev).

## 🗺️ Куда движется проект
Текущая фаза, открытые направления, гипотезы будущего (Predictive Setup Engine,
Куб Метатрона Сферы 14-18, etc).

ПРАВИЛА:
- Только факты из источников. Цитируй ID и даты.
- ЗАПРЕЩЕНО повторение. Если поймал петлю — закрывай раздел.
- Bullet-points. Только русский.
- Группируй по смыслу, не сваливай в кучу.

ВЫЖИМКИ ПО МЕСЯЦАМ:

{months}

=== TASKS-ARCHIVE.md ===
{tasks_archive}
"""


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def call_gemini(prompt: str, max_tokens: int, system: str) -> tuple[str, str]:
    """Возвращает (text, used_model)."""
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY не задан в .env")

    client = genai.Client(api_key=key)
    cfg = types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=max_tokens,
        system_instruction=system,
    )

    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL_PRIMARY, contents=prompt, config=cfg,
            )
            return (resp.text or "").strip(), GEMINI_MODEL_PRIMARY
        except Exception as e:
            msg = str(e)
            if "429" in msg and "retryDelay" in msg:
                # Извлекаем retry delay
                m = re.search(r'retryDelay["\']\s*:\s*["\'](\d+)s', msg)
                delay = int(m.group(1)) + 2 if m else 25
                print(f"[timeline] 429 attempt {attempt+1}/3, sleep {delay}s", file=sys.stderr)
                time.sleep(delay)
                continue
            if "503" in msg or "UNAVAILABLE" in msg:
                print(f"[timeline] 503 → fallback {GEMINI_MODEL_FALLBACK}", file=sys.stderr)
                resp = client.models.generate_content(
                    model=GEMINI_MODEL_FALLBACK, contents=prompt, config=cfg,
                )
                return (resp.text or "").strip(), GEMINI_MODEL_FALLBACK
            raise
    raise RuntimeError("3 attempts failed with 429")


def process_month(archive_path: Path) -> Path:
    """Обрабатывает один DISCUSSION-ARCHIVE-<MONTH>.md → PARTS_DIR/<MONTH>.md."""
    PARTS_DIR.mkdir(parents=True, exist_ok=True)
    # DISCUSSION-ARCHIVE-MAR2026.md → MAR2026
    m = re.search(r"DISCUSSION-ARCHIVE-([A-Z]+\d{4})\.md", archive_path.name)
    month_name = m.group(1) if m else archive_path.stem
    out_file = PARTS_DIR / f"{month_name}.md"

    # Кеширование: если выжимка моложе самого архива → пропускаем
    if out_file.exists() and out_file.stat().st_mtime > archive_path.stat().st_mtime:
        print(f"[timeline] {month_name}: cached ({out_file.name})", file=sys.stderr)
        return out_file

    archive_text = archive_path.read_text(encoding="utf-8", errors="replace")
    prompt = MONTH_PROMPT.format(month_name=month_name, archive_text=archive_text)
    in_tokens = int(len(prompt) / 3.5)

    print(f"[timeline] {month_name}: ~{in_tokens} input tokens → Gemini...", file=sys.stderr)
    text, used = call_gemini(
        prompt, MAX_OUTPUT_TOKENS_MONTH,
        system=(
            "Ты — историк проекта. Только русский. ЗАПРЕЩЕНО повторение. "
            "Если поймал петлю — закрывай раздел."
        ),
    )
    out_tokens = int(len(text) / 3.5)
    print(f"[timeline] {month_name}: ~{out_tokens} output tokens ({used})", file=sys.stderr)

    out_file.write_text(
        f"<!-- month={month_name} model={used} in_tokens={in_tokens} out_tokens={out_tokens} -->\n\n{text}",
        encoding="utf-8",
    )
    return out_file


def merge_months(part_files: list[Path]) -> tuple[str, dict]:
    """Объединяет все per-month выжимки в финальный timeline."""
    parts = []
    for f in sorted(part_files):
        text = f.read_text(encoding="utf-8", errors="replace")
        parts.append(f"\n=== {f.stem} ===\n{text}\n")
    months_block = "".join(parts)

    tasks_path = PROJECT_ROOT / "TASKS-ARCHIVE.md"
    tasks_text = tasks_path.read_text(encoding="utf-8", errors="replace") if tasks_path.exists() else "[нет TASKS-ARCHIVE.md]"

    prompt = MERGE_PROMPT.format(months=months_block, tasks_archive=tasks_text)
    in_tokens = int(len(prompt) / 3.5)
    print(f"[timeline] MERGE: ~{in_tokens} input tokens → Gemini...", file=sys.stderr)

    text, used = call_gemini(
        prompt, MAX_OUTPUT_TOKENS_MERGE,
        system=(
            "Ты — историк проекта Oko MTF. Только русский. ЗАПРЕЩЕНО повторение. "
            "Группируй по смыслу. Цитируй ID задач и даты."
        ),
    )
    out_tokens = int(len(text) / 3.5)
    return text, {"model": used, "in_tokens": in_tokens, "out_tokens": out_tokens,
                  "in_chars": len(prompt), "out_chars": len(text)}


def write_outputs(timeline: str, stats: dict) -> tuple[Path, Path]:
    OUTPUT_MEMORY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    obsidian_file = OUTPUT_OBSIDIAN_DIR / f"{today}-timeline.md"

    memory_header = (
        f"# Project Timeline (long-memory)\n\n"
        f"> Автогенерация: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} • "
        f"источник: DISCUSSION-ARCHIVE-*.md + TASKS-ARCHIVE.md • "
        f"модель: `{stats['model']}` • "
        f"скрипт: `tools/project_timeline.py` (двухпроходный)\n\n---\n\n"
    )
    OUTPUT_MEMORY.write_text(memory_header + timeline, encoding="utf-8")

    obsidian_header = (
        "---\n"
        "tags: [timeline, project-log, auto]\n"
        "type: project-timeline\n"
        f"date: {today}\n"
        'parent: "[[Project-MOC]]"\n'
        f'month: "[[Months/{today[:7]}]]"\n'
        f"model: {stats['model']}\n"
        "---\n\n"
        f"# Project Timeline {today}\n\n"
        f"> Автогенерация Gemini (`tools/project_timeline.py`).\n\n---\n\n"
    )
    obsidian_file.write_text(obsidian_header + timeline, encoding="utf-8")

    return OUTPUT_MEMORY, obsidian_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate project timeline (per-month then merge)")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--force", action="store_true", help="Перегенерировать per-month кеш")
    args = parser.parse_args()

    load_env()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    archives = sorted(PROJECT_ROOT.glob("DISCUSSION-ARCHIVE-*.md"))
    if not archives:
        print("[timeline] ERROR: нет DISCUSSION-ARCHIVE-*.md", file=sys.stderr)
        return 1

    if args.force:
        for p in PARTS_DIR.glob("*.md") if PARTS_DIR.exists() else []:
            p.unlink()
        print("[timeline] FORCE: per-month кеш очищен", file=sys.stderr)

    print(f"[timeline] Pass 1: обработка {len(archives)} архивов...", file=sys.stderr)
    part_files = []
    for arch in archives:
        try:
            part_files.append(process_month(arch))
            time.sleep(2)  # пауза между запросами для rate-limit
        except Exception as e:
            print(f"[timeline] {arch.name} ERROR: {e}", file=sys.stderr)
            return 1

    print(f"[timeline] Pass 2: merge {len(part_files)} per-month выжимок...", file=sys.stderr)
    try:
        timeline, stats = merge_months(part_files)
    except Exception as e:
        print(f"[timeline] merge ERROR: {e}", file=sys.stderr)
        return 1

    memory_path, obsidian_path = write_outputs(timeline, stats)

    if args.quiet:
        print(f"[timeline] OK model={stats['model']} ~in={stats['in_tokens']} ~out={stats['out_tokens']}",
              file=sys.stderr)
    else:
        print(f"[timeline] OK model={stats['model']}")
        print(f"  merge in:  ~{stats['in_tokens']} tokens ({stats['in_chars']} chars)")
        print(f"  merge out: ~{stats['out_tokens']} tokens ({stats['out_chars']} chars)")
        print(f"  -> {memory_path}")
        print(f"  -> {obsidian_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
