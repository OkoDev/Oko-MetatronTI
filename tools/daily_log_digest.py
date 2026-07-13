"""Daily Log Digest — сжимает crypto_bot.log в 5-10 строк через Gemini.

Лог огромный (1 ГБ). Стратегия:
  1. Tail последних N строк (default 10000) — для контекста
  2. ALL ERROR/CRITICAL/WARNING из последних N MB лога — для аномалий
  3. Дедупликация повторяющихся (одна и та же строка ×100 → 1 строка + count)
  4. Передаём в Gemini → digest

Output:
  memory/log_digest.md — Claude читает
  obsidian/Logs/<DATE>-digest.md — Obsidian

Запуск:
  python tools/daily_log_digest.py                # дефолт (10k tail + ERROR/WARNING из 50MB)
  python tools/daily_log_digest.py --tail 5000    # короче tail
  python tools/daily_log_digest.py --quiet
  python tools/daily_log_digest.py --max-age-hours 18
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
LOG_FILE = PROJECT_ROOT / "logs" / "crypto_bot.log"

OUTPUT_MEMORY = PROJECT_ROOT / "memory" / "log_digest.md"
OUTPUT_OBSIDIAN_DIR = PROJECT_ROOT / "obsidian" / "Logs"

GEMINI_MODEL_PRIMARY = "gemini-2.5-flash"
GEMINI_MODEL_FALLBACK = "gemini-2.5-flash-lite"
MAX_OUTPUT_TOKENS = 6000

# Сколько MB из конца лога сканируем на ERROR/WARNING
SCAN_TAIL_MB = 50
# Сколько последних строк (любого уровня) передаём для контекста
DEFAULT_TAIL_LINES = 10000

LEVEL_RE = re.compile(r"\s(ERROR|CRITICAL|WARNING)\b")
# Нормализация для дедупликации: убираем timestamp/число/path-specific части
NORMALIZE_RES = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\.,]\d+"), "<TIMESTAMP>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"), "<TIMESTAMP>"),
    (re.compile(r"[A-Z]{2,10}/USDT:?USDT?"), "<SYMBOL>"),
    (re.compile(r"#\d{4,}"), "#<TRADE_ID>"),
    (re.compile(r"\b0x[a-f0-9]{4,}\b"), "<HEX>"),
    (re.compile(r"\b\d{6,}\b"), "<BIG_NUM>"),
    (re.compile(r"\b\d+\.\d+e[-+]?\d+\b"), "<SCI>"),
    (re.compile(r"\b\d+\.\d{4,}\b"), "<FLOAT>"),
]


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def normalize(line: str) -> str:
    for rx, sub in NORMALIZE_RES:
        line = rx.sub(sub, line)
    return line.strip()


def tail_log(path: Path, n_lines: int) -> list[str]:
    """Берём последние n_lines строк лога (читаем с конца файла блоками)."""
    if not path.exists():
        return []
    size = path.stat().st_size
    block = 1024 * 1024  # 1 MB
    lines: list[str] = []
    with path.open("rb") as f:
        pos = size
        leftover = b""
        while pos > 0 and len(lines) < n_lines * 2:
            chunk_size = min(block, pos)
            pos -= chunk_size
            f.seek(pos)
            chunk = f.read(chunk_size) + leftover
            chunk_lines = chunk.split(b"\n")
            leftover = chunk_lines[0]
            lines = chunk_lines[1:] + lines  # type: ignore[assignment]
            if pos == 0:
                lines = [leftover] + lines  # type: ignore[assignment]
                break
    decoded = []
    for b in lines[-n_lines:]:
        if isinstance(b, bytes):
            try:
                decoded.append(b.decode("utf-8", errors="replace"))
            except Exception:
                continue
        else:
            decoded.append(b)
    return decoded


def scan_warnings_errors(path: Path, scan_mb: int) -> tuple[Counter, dict[str, list[str]]]:
    """Сканирует последние scan_mb МБ файла и собирает все WARNING/ERROR/CRITICAL.

    Возвращает:
      - Counter нормализованных строк (для дедупликации)
      - dict норм_строка → [пример1, пример2] (raw примеры, до 2 шт)
    """
    if not path.exists():
        return Counter(), {}
    size = path.stat().st_size
    start = max(0, size - scan_mb * 1024 * 1024)
    counter: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    with path.open("rb") as f:
        f.seek(start)
        # пропускаем первую (возможно обрезанную) строку
        f.readline()
        for raw in f:
            try:
                line = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
            if not LEVEL_RE.search(line):
                continue
            norm = normalize(line)
            counter[norm] += 1
            if len(examples[norm]) < 2:
                examples[norm].append(line.strip())
    return counter, dict(examples)


DIGEST_PROMPT = """Ты — DevOps-аналитик, разбираешь лог торгового бота Oko MTF за день.
Тебе даны (а) топ-30 уникальных WARNING/ERROR/CRITICAL с counts, (б) tail последних строк лога.

ФОРМАТ (markdown, русский, 100-300 строк МАКСИМУМ):

# Log Digest — {date}

## 🚨 Главные ошибки / алармы (top-5)
Для каждой:
- **[NN раз]** Что: суть ошибки (без timestamp/symbol)
- Где: модуль/функция если виден
- Возможная причина: 1 строка
- Приоритет: 🔴/🟡/🟢

## ⚠️ Подозрительные паттерны
2-5 пунктов: повторяющиеся WARNING'и которые не похожи на норму.

## 📈 Тренды (что изменилось)
Если в tail видно изменение поведения относительно "обычного" — отметь.
Например: "сегодня X было 100 раз, обычно <10" — это аномалия.

## 🧪 Что предложить DEV
2-3 конкретных действия (добавить guard, fix exception, рефакторинг).

## 🟢 Что ОК
Что в логе подсказывает что система работает нормально (DB writes, scan_loop, EventBus).

ПРАВИЛА:
- ТОЛЬКО факты из источника. Не выдумывай.
- Игнорируй обычный noise (HTTP 200, simple INFO).
- Цитируй имена методов / классов когда видны.
- Bullet-points. Только русский.

ИСТОЧНИК:

=== TOP-30 уникальных WARNING/ERROR/CRITICAL (нормализованные, с counts) ===
{top_errors}

=== TAIL последних {tail_lines} строк лога (для контекста) ===
{tail_block}
"""


def call_gemini(prompt: str) -> tuple[str, str]:
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY не задан в .env")

    client = genai.Client(api_key=key)
    cfg_kwargs = dict(
        temperature=0.2,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        system_instruction=(
            "Ты — DevOps-аналитик. Только русский. Только факты из источника. "
            "Игнорируй INFO-шум. Будь конкретен."
        ),
    )
    try:
        cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass

    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL_PRIMARY, contents=prompt,
            config=types.GenerateContentConfig(**cfg_kwargs),
        )
        return (resp.text or "").strip(), GEMINI_MODEL_PRIMARY
    except Exception as e:
        if "503" in str(e) or "UNAVAILABLE" in str(e):
            print(f"[log_digest] 503 → fallback {GEMINI_MODEL_FALLBACK}", file=sys.stderr)
            resp = client.models.generate_content(
                model=GEMINI_MODEL_FALLBACK, contents=prompt,
                config=types.GenerateContentConfig(**cfg_kwargs),
            )
            return (resp.text or "").strip(), GEMINI_MODEL_FALLBACK
        raise


def write_outputs(text: str, used_model: str, stats: dict) -> tuple[Path, Path]:
    OUTPUT_MEMORY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    obsidian_file = OUTPUT_OBSIDIAN_DIR / f"{today}-digest.md"

    memory_header = (
        f"# Log Digest\n\n"
        f"> Автогенерация: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} • "
        f"scan {SCAN_TAIL_MB}MB, tail {stats['tail_lines']} строк, "
        f"уникальных WARN/ERR: {stats['unique_alarms']} • модель: `{used_model}` • "
        f"скрипт: `tools/daily_log_digest.py`\n\n---\n\n"
    )
    OUTPUT_MEMORY.write_text(memory_header + text, encoding="utf-8")

    obsidian_header = (
        "---\n"
        "tags: [log, digest, auto]\n"
        "type: log-digest\n"
        f"date: {today}\n"
        f"unique_alarms: {stats['unique_alarms']}\n"
        f"total_alarms: {stats['total_alarms']}\n"
        'parent: "[[Project-MOC]]"\n'
        f"model: {used_model}\n"
        "---\n\n"
        f"# Log Digest {today}\n\n"
        f"> Автогенерация Gemini.\n\n---\n\n"
    )
    obsidian_file.write_text(obsidian_header + text, encoding="utf-8")
    return OUTPUT_MEMORY, obsidian_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily log digest via Gemini")
    parser.add_argument("--tail", type=int, default=DEFAULT_TAIL_LINES, help="Сколько последних строк лога взять")
    parser.add_argument("--scan-mb", type=int, default=SCAN_TAIL_MB, help="Сколько MB лога сканировать на ERROR/WARN")
    parser.add_argument("--max-age-hours", type=float, default=0,
                        help="Skip если digest свежий")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.max_age_hours > 0 and OUTPUT_MEMORY.exists():
        age = datetime.now(timezone.utc).timestamp() - OUTPUT_MEMORY.stat().st_mtime
        if age < args.max_age_hours * 3600:
            print(f"[log_digest] SKIP: digest свежий ({int(age/60)} мин)", file=sys.stderr)
            return 0

    load_env()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not LOG_FILE.exists():
        print(f"[log_digest] ERROR: {LOG_FILE} не найден", file=sys.stderr)
        return 1

    print(f"[log_digest] tail {args.tail} строк...", file=sys.stderr)
    tail_lines = tail_log(LOG_FILE, args.tail)
    tail_text = "".join(tail_lines)

    print(f"[log_digest] scan {args.scan_mb} MB на WARN/ERR...", file=sys.stderr)
    counter, examples = scan_warnings_errors(LOG_FILE, args.scan_mb)
    top30 = counter.most_common(30)

    if not top30 and not tail_lines:
        print("[log_digest] лог пуст или нет WARN/ERR", file=sys.stderr)
        return 0

    # Формируем top_errors block с примерами
    top_lines = []
    for norm, cnt in top30:
        top_lines.append(f"[{cnt}x] {norm[:300]}")
        if examples.get(norm):
            top_lines.append(f"     пример: {examples[norm][0][:300]}")
    top_errors_block = "\n".join(top_lines) or "[нет уникальных WARN/ERR]"

    # Обрезаем tail если очень большой (>120k символов)
    if len(tail_text) > 120_000:
        tail_text = "[...обрезано...]\n" + tail_text[-120_000:]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = DIGEST_PROMPT.format(
        date=today, tail_lines=args.tail,
        top_errors=top_errors_block, tail_block=tail_text,
    )
    in_tokens = int(len(prompt) / 3.5)
    print(f"[log_digest] ~{in_tokens} input tokens → Gemini...", file=sys.stderr)

    try:
        text, used = call_gemini(prompt)
    except Exception as e:
        print(f"[log_digest] ERROR: {e}", file=sys.stderr)
        return 1

    out_tokens = int(len(text) / 3.5)
    stats = {
        "tail_lines": args.tail,
        "unique_alarms": len(top30),
        "total_alarms": sum(c for _, c in top30),
    }
    memory_path, obsidian_path = write_outputs(text, used, stats)

    if args.quiet:
        print(f"[log_digest] OK ~in={in_tokens} ~out={out_tokens}", file=sys.stderr)
    else:
        print(f"[log_digest] OK model={used}")
        print(f"  unique WARN/ERR: {stats['unique_alarms']}, total: {stats['total_alarms']}")
        print(f"  in:  ~{in_tokens} tokens")
        print(f"  out: ~{out_tokens} tokens")
        print(f"  -> {memory_path}")
        print(f"  -> {obsidian_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
