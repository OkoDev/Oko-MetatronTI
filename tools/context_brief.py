"""Context Brief — генератор краткой выжимки для следующей сессии Claude.

Собирает источники проекта (DISCUSSION, TASKS, current_state, git log)
и просит Gemini сформировать структурированный brief.

Брим экономит контекст Claude: вместо чтения 3000+ строк DISCUSSION.md
читается ~500 строк выжимки. Покрывает 90% случаев старта новой сессии.

Запуск:
  python tools/context_brief.py             # обновить brief
  python tools/context_brief.py --quiet     # для hook (минимум вывода)
  python tools/context_brief.py --days 14   # шире окно git log

Источники (в порядке приоритета):
  1. DISCUSSION.md (последние 200 записей)
  2. TASKS.md (полностью)
  3. memory/current_state.md (полностью)
  4. git log --oneline -n 100 за N дней
  5. memory/MEMORY.md (индекс — для контекста правил)

Output:
  memory/session_brief.md                              ← Claude читает
  obsidian/Sessions/YYYY-MM-DD-brief.md               ← Obsidian граф
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

DISCUSSION_FILE = PROJECT_ROOT / "DISCUSSION.md"
TASKS_FILE = PROJECT_ROOT / "TASKS.md"
CURRENT_STATE_FILE = PROJECT_ROOT / "memory" / "current_state.md"
MEMORY_INDEX = PROJECT_ROOT / "memory" / "MEMORY.md"

OUTPUT_MEMORY = PROJECT_ROOT / "memory" / "session_brief.md"
OUTPUT_OBSIDIAN_DIR = PROJECT_ROOT / "obsidian" / "Sessions"

GEMINI_MODEL_PRIMARY = "gemini-2.5-flash"
GEMINI_MODEL_FALLBACK = "gemini-2.5-flash-lite"
MAX_OUTPUT_TOKENS = 12000


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def read_truncated(path: Path, max_chars: int = 80_000) -> str:
    if not path.exists():
        return f"[ФАЙЛ ОТСУТСТВУЕТ: {path.name}]"
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[ОБРЕЗАНО: показано {max_chars}/{len(text)} символов]"


def _parse_record_date(record_text: str):
    """Парсит дату из заголовка записи: `### [DD.MM.YYYY]` или `### [YYYY-MM-DD]`.

    Возвращает datetime.date или None.
    """
    import re as _re
    from datetime import date

    # ищем первое вхождение шаблона [DD.MM.YYYY] или [YYYY-MM-DD] в первых 500 символов
    head = record_text[:500]
    # формат [DD.MM.YYYY]
    m = _re.search(r"\[(\d{2})\.(\d{2})\.(\d{4})\]", head)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    # формат [YYYY-MM-DD]
    m = _re.search(r"\[(\d{4})-(\d{2})-(\d{2})\]", head)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def collect_discussion(max_records: int = 60, recent_days: int = 7) -> str:
    """Фильтрует DISCUSSION.md по дате (последние N дней) + ограничивает N записей.

    Так модель видит только релевантные записи и не пытается включать старые
    в раздел "Открытые вопросы".
    """
    if not DISCUSSION_FILE.exists():
        return "[DISCUSSION.md отсутствует]"
    text = DISCUSSION_FILE.read_text(encoding="utf-8", errors="replace")
    parts = text.split("\n---\n")

    # Фильтр по дате: оставляем записи за recent_days
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    cutoff = (_dt.now(_tz.utc) - _td(days=recent_days)).date()

    fresh = []
    no_date = []
    for p in parts:
        d = _parse_record_date(p)
        if d is None:
            no_date.append(p)
            continue
        if d >= cutoff:
            fresh.append((d, p))

    # сортируем свежие от старых к новым (для естественного чтения)
    fresh.sort(key=lambda x: x[0])
    fresh_records = [p for _, p in fresh]

    if not fresh_records:
        # fallback: если за recent_days ничего — отдадим последние max_records чтобы модель не упала
        tail = parts[-max_records:]
        return f"[ВНИМАНИЕ: за {recent_days} дней записей с датами не найдено. Показано последние {len(tail)} записей.]\n\n---\n" + "\n---\n".join(tail)

    # ограничиваем количеством max_records если очень много
    if len(fresh_records) > max_records:
        fresh_records = fresh_records[-max_records:]

    header = f"[Записи за последние {recent_days} дней (с {cutoff.isoformat()}), всего {len(fresh_records)} записей]\n\n"
    return header + "---\n" + "\n---\n".join(fresh_records)


def collect_git_log(days: int) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "log",
             f"--since={days}.days.ago",
             "--pretty=format:%h %ad %s",
             "--date=short", "-n", "150"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        return f"[git log пуст или error: {result.stderr.strip()}]"
    except Exception as e:
        return f"[git log failed: {e}]"


def collect_git_diff_stat() -> str:
    """Незакоммиченные изменения с числом изменённых строк (--stat)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "diff", "--stat", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            return out if out else "[нет незакоммиченных изменений]"
        return f"[git diff error: {result.stderr.strip()}]"
    except Exception as e:
        return f"[git diff failed: {e}]"


BRIEF_PROMPT = """Ты делаешь brief для Claude который начинает новую сессию работы над торговым ботом.
Цель: за 30 секунд Claude поймёт где проект и что важно. Сегодня: {date}.

ФОРМАТ (markdown, русский, ~300-500 строк). РАЗДЕЛЫ СТРОГО В ПОРЯДКЕ НИЖЕ.

# Session Brief — {date}

## 🧭 Контекст фазы проекта
3-5 строк: фаза (стабилизация/новый модуль/рефакторинг), главный конфликт, куда движется.
Это САМОЕ ВАЖНОЕ — для быстрого включения.

## 🔥 Открытые вопросы между агентами
Источник DISCUSSION содержит ВСЕ записи (свежие + старые).
НО: вопрос СЧИТАЕТСЯ ОТКРЫТЫМ только если связанная задача в TASKS.md имеет 🔄 или 🔴.
Задача ✅ в TASKS → вопрос закрыт → НЕ включай.

Алгоритм:
1. Нашёл вопрос в DISCUSSION (например «→ DS: итерация-3 ARCH-127»)
2. Найди ID задачи (DS-311, ARCH-127, ...) в TASKS.md
3. Если статус ✅ → ПРОПУСТИ
4. Если статус 🔄/🔴 → включи в «Открытые вопросы»

ФОРМАТ: `- [ID задачи] → КОМУ:` суть. Статус из TASKS.

## 🚧 Что сейчас в работе
**Активные (🔄 в TASKS.md):** ID + строка статуса.

**Git diff --stat HEAD:** дословно из источника (имена файлов и числа). Не выдумывай.

**Последняя сессия (current_state.md):** 3-5 пунктов что сделано/осталось.

## ⚠️ Недавно ломалось / проблемы
6-8 пунктов за 7 дней. Проблема → root cause → статус. Старые исправленные — НЕ включай.

## ✅ Что недавно решили / закрыли — СГРУППИРОВАТЬ ПО ТЕМАМ

### Execution / Order Management
SL/TP, position_sync, slippage, exchange API.

### Strategies
wt_signal / pivot_reversal / atr_change / mtf_bias / OTE / wt_sideways / wt_b_signal / etc.

### Architecture / Куб Метатрона
ARCH-X, EventBus, ConfirmationRegistry, новые сферы.

### ML / Analytics / Risk
OutcomePredictor, classify_v2, gates, regime-блоки, time_gate, circuit_breaker, dashboard.

### Infrastructure / Tooling
DecisionTrace, observability, scripts, tools/.

В категории нет пунктов → пропускай категорию.
МАКС 4-5 пунктов в категории, с ID. Только за 7 дней.

## 📊 Ключевые числа / метрики
avgR, WR, n сделок, gates — за 7 дней. Старые — не надо.

## 🎯 Приоритеты на 1-3 дня
🔴 в TASKS.md + последние просьбы TRADER. 6-8 пунктов с ID.

ПРАВИЛА:
- Только факты из источника. Цитируй ID и даты.
- Bullet-points. Не повторяйся.
- Только русский.
- ВАЖНО: все ID задач (ARCH-X, DEV-Y, TR-Z, DS-N) оборачивай в wikilink: [[ARCH-113]].
- Упоминаешь концепт (SMC, FVG, OTE, WT) — ставь wikilink если есть файл в Concepts/.
- Упоминаешь файл кода — wikilink на Code-Map/: [[Code-Map/core.smc.smc_engine]].

🔴 ПРАВИЛО ОТКРЫТЫХ ВОПРОСОВ (КРИТИЧНО):
- Берёшь вопрос из DISCUSSION ТОЛЬКО если связанная задача в TASKS.md имеет статус 🔄 или 🔴 (НЕ ✅).
- Если задача ✅ в TASKS — вопрос ЗАКРЫТ, не включай в «Открытые вопросы».
- Если задача упоминается в DISCUSSION но её нет в TASKS — проверь TASKS-ARCHIVE.
- ЛУЧШЕ пропустить старый вопрос, чем выдать закрытый как открытый.

ИСТОЧНИКИ:

=== DISCUSSION.md (живой диалог агентов, последние 60 записей) ===
{discussion}

=== TASKS.md (открытые задачи) ===
{tasks}

=== memory/current_state.md (последние сессии) ===
{current_state}

=== git log за последние {days} дней ===
{git_log}

=== git diff --stat HEAD (незакоммиченные изменения) ===
{git_diff}

=== memory/MEMORY.md (индекс правил) ===
{memory_index}
"""


def generate_brief(days: int) -> tuple[str, dict]:
    """Возвращает (brief_text, stats)."""
    sources = {
        "discussion": collect_discussion(max_records=60, recent_days=days),
        "tasks": read_truncated(TASKS_FILE, max_chars=30_000),
        "current_state": read_truncated(CURRENT_STATE_FILE, max_chars=30_000),
        "git_log": collect_git_log(days),
        "git_diff": collect_git_diff_stat(),
        "memory_index": read_truncated(MEMORY_INDEX, max_chars=15_000),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "days": days,
    }

    prompt = BRIEF_PROMPT.format(**sources)

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("Установи: pip install google-genai")

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY не задан в .env")

    client = genai.Client(api_key=key)

    def _call(model_name: str):
        # ThinkingConfig: отключаем reasoning у Gemini 2.5, чтобы все токены ушли в output.
        # Для brief'а структурированная выжимка важнее «глубокого размышления».
        cfg_kwargs = dict(
            temperature=0.2,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            system_instruction=(
                "Ты — лаконичный ассистент. Только русский язык. "
                "Только факты из источника. Не повторяй контекст. "
                "ЗАПРЕЩЕНО повторять одну и ту же запись дважды. "
                "Если поймал себя на повторении — закрывай раздел и переходи к следующему."
            ),
        )
        try:
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass  # старый SDK без поддержки thinking_config
        return client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(**cfg_kwargs),
        )

    used_model = GEMINI_MODEL_PRIMARY
    try:
        resp = _call(GEMINI_MODEL_PRIMARY)
    except Exception as e:
        msg = str(e)
        if "503" in msg or "UNAVAILABLE" in msg or "overload" in msg.lower():
            print(f"[context_brief] {GEMINI_MODEL_PRIMARY} 503 → fallback на {GEMINI_MODEL_FALLBACK}", file=sys.stderr)
            used_model = GEMINI_MODEL_FALLBACK
            resp = _call(GEMINI_MODEL_FALLBACK)
        else:
            raise

    brief = (resp.text or "").strip()
    in_chars = len(prompt)
    out_chars = len(brief)
    stats = {
        "model": used_model,
        "in_tokens_approx": int(in_chars / 3.5),
        "out_tokens_approx": int(out_chars / 3.5),
        "in_chars": in_chars,
        "out_chars": out_chars,
    }
    return brief, stats


def write_outputs(brief: str, days: int, used_model: str) -> tuple[Path, Path]:
    OUTPUT_MEMORY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    obsidian_file = OUTPUT_OBSIDIAN_DIR / f"{today}-brief.md"

    # ── Obsidian frontmatter 2.0 (DS-317) ──
    today_dt = datetime.now(timezone.utc)
    today_iso = today_dt.strftime("%Y-%m-%d")
    today_month = today_dt.strftime("%Y-%m")
    
    # Авто-извлечение упомянутых ID из brief текста
    import re
    mentioned = set(re.findall(r'(?:ARCH|DEV|DS|TR)-\d+', brief))
    related = " ".join(f"[[{m}]]" for m in sorted(mentioned)[:20]) if mentioned else ""
    
    obsidian_header = (
        "---\n"
        f"tags: [session, brief, auto, role/arch, role/dev, area/diagnostics]\n"
        f"type: session-brief\n"
        f"date: {today_iso}\n"
        f"parent: \"[[Project-MOC]]\"\n"
        f"month: \"[[Months/{today_month}]]\"\n"
        f"model: {used_model}\n"
    )
    if related:
        obsidian_header += f"related: [{related}]\n"
    obsidian_header += "---\n\n"
    
    # memory/ вариант — без obsidian frontmatter
    memory_header = (
        f"# Session Brief\n\n"
        f"> Автогенерация: {today_dt.strftime('%Y-%m-%d %H:%M UTC')} • "
        f"источник: DISCUSSION.md + TASKS.md + git log {days}d • "
        f"модель: `{used_model}` • "
        f"скрипт: `tools/context_brief.py`\n\n---\n\n"
    )
    OUTPUT_MEMORY.write_text(memory_header + brief, encoding="utf-8")

    # obsidian/ вариант — v2.0 frontmatter (DS-317)
    obsidian_header_v2 = (
        "---\n"
        f"tags: [session, brief, auto, role/arch, role/dev, area/diagnostics]\n"
        "type: session-brief\n"
        f"date: {today}\n"
        'parent: "[[Project-MOC]]"\n'
        f'month: "[[Months/{today[:7]}]]"\n'
        f"model: {used_model}\n"
    )
    if related:
        obsidian_header_v2 += f'related: "{related}"\n'
    obsidian_header_v2 += (
        "---\n\n"
        f"# Brief за {today}\n\n"
        f"> Автогенерация Gemini (`tools/context_brief.py`).\n\n---\n\n"
    )
    obsidian_file.write_text(obsidian_header_v2 + brief, encoding="utf-8")

    return OUTPUT_MEMORY, obsidian_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate session brief via Gemini")
    parser.add_argument("--days", type=int, default=7, help="Окно git log (дней)")
    parser.add_argument("--quiet", action="store_true", help="Минимум вывода (для hook)")
    parser.add_argument("--max-age-hours", type=float, default=0,
                        help="Скипнуть генерацию если brief свежее (для hook). 0 = всегда генерировать.")
    args = parser.parse_args()

    # Проверка свежести (для hook): если brief обновлялся недавно — скип.
    if args.max_age_hours > 0 and OUTPUT_MEMORY.exists():
        from datetime import timedelta
        age = datetime.now(timezone.utc).timestamp() - OUTPUT_MEMORY.stat().st_mtime
        if age < args.max_age_hours * 3600:
            age_min = int(age / 60)
            print(f"[context_brief] SKIP: brief свежий ({age_min} мин < {args.max_age_hours}ч)",
                  file=sys.stderr)
            return 0

    load_env()

    try:
        brief, stats = generate_brief(args.days)
    except Exception as e:
        print(f"[context_brief] ERROR: {e}", file=sys.stderr)
        return 1

    memory_path, obsidian_path = write_outputs(brief, args.days, stats["model"])

    # Принудительно UTF-8 для stdout/stderr — Windows console часто cp1251
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if args.quiet:
        print(f"[context_brief] OK model={stats['model']} ~in={stats['in_tokens_approx']} ~out={stats['out_tokens_approx']}",
              file=sys.stderr)
    else:
        print(f"[context_brief] OK model={stats['model']}")
        print(f"  in:  ~{stats['in_tokens_approx']} tokens ({stats['in_chars']} chars)")
        print(f"  out: ~{stats['out_tokens_approx']} tokens ({stats['out_chars']} chars)")
        print(f"  -> {memory_path}")
        print(f"  -> {obsidian_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
