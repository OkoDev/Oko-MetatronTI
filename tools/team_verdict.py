"""Team Verdict — коллективный аудит проекта 5 LLM провайдерами параллельно.

Идея:
  Один и тот же контекст (brief + timeline + trade_review + log_digest + проблемы)
  скармливается каждому из 5 провайдеров (cerebras / mistral / openrouter / gemini / groq).
  Каждый возвращает независимый «вердикт» по проекту.
  Затем — meta-summary где модели согласны, где спорят.

Output:
  obsidian/Verdicts/<DATE>-team-verdict.md
  memory/last_team_verdict.md

Запуск:
  python tools/team_verdict.py                    # все доступные провайдеры
  python tools/team_verdict.py --providers cerebras,mistral
  python tools/team_verdict.py --skip-meta        # без финального meta-summary
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Импортируем функции из llm_ask.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm_ask import (  # noqa: E402
    load_env, has_key, ENV_KEYS, DEFAULT_MODELS,
    call_provider,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Источники для bundle
SRC_FILES = [
    PROJECT_ROOT / "memory" / "session_brief.md",
    PROJECT_ROOT / "memory" / "project_timeline.md",
    PROJECT_ROOT / "memory" / "last_trade_review.md",
    PROJECT_ROOT / "memory" / "log_digest.md",
    PROJECT_ROOT / "TASKS.md",
]

OUTPUT_OBSIDIAN_DIR = PROJECT_ROOT / "obsidian" / "Verdicts"
OUTPUT_MEMORY = PROJECT_ROOT / "memory" / "last_team_verdict.md"

# Все провайдеры в порядке предпочтения
ALL_PROVIDERS = ["cerebras", "mistral", "openrouter", "gemini", "groq", "github_models"]


VERDICT_PROMPT = """Ты — независимый эксперт-аудитор. Тебе дан полный контекст торгового бота Oko MTF
(criptовалютная биржа BingX, симуляция + live, 24/7).

Твоя задача — ВЫНЕСТИ ВЕРДИКТ по текущему состоянию бота.
Будь критичен. Тебя сравнивают с 4 другими LLM-моделями. Дай СВОЙ независимый взгляд.

ОБЯЗАТЕЛЬНЫЙ ФОРМАТ (markdown, русский, 200-400 строк):

# Вердикт: {model_name}

## ⚖️ Главный вывод (1-2 предложения)
В каком состоянии бот? Прибылен / убыточен / стабилизация? Куда движется?

## 🩺 Диагноз (3-5 ключевых проблем)
Каждая проблема:
- Что: суть
- Тяжесть: 🔴 critical / 🟡 important / 🟢 minor
- Аргументы: цитируй конкретные числа из контекста
- Решено / в работе / открыто

## 💪 Сильные стороны проекта
Что бот делает ХОРОШО? Какая инфраструктура заслуживает похвалы?

## 🚨 Главные риски (top-3)
Что может убить бот в ближайшие 1-3 месяца если не исправить?
Будь конкретен — цитируй реальные риски из контекста.

## 🎯 ЧТО ДЕЛАТЬ В ПЕРВУЮ ОЧЕРЕДЬ (top-3 действия)
Конкретные действия с приоритетом:
1. [🔴/🟡/🟢] Что → почему → ожидаемый эффект
2. ...
3. ...

## 🔮 Прогноз на 30 дней
Если выполнить top-3 действия — выйдет ли бот в плюс?
Оптимистичный / реалистичный / пессимистичный сценарий.

## 🏛️ Архитектурное мнение
Соответствует ли проект концепции «Куб Метатрона» которую упоминают агенты?
Что в архитектуре сильно/слабо?

## ⚠️ Что меня смущает
1-3 пункта из контекста где ты не уверен или подозреваешь что что-то не так.

ПРАВИЛА:
- Только факты из контекста. Не выдумывай.
- Будь КРИТИЧЕН — это аудит а не похвала.
- Цитируй конкретные ID (DEV-X, ARCH-Y) и числа (avgR, WR, R-multiple).
- Тебе ОК сказать «не знаю / недостаточно данных».
- Только русский. Bullet-points.

КОНТЕКСТ ПРОЕКТА:

{context}
"""


META_PROMPT = """Тебе даны ВЕРДИКТЫ 5 разных LLM по одному и тому же торговому боту.
Твоя задача — meta-анализ: где модели СОГЛАСНЫ, где СПОРЯТ, и какой синтезированный вывод.

ФОРМАТ (markdown, русский, 200-400 строк):

# Meta-Verdict (синтез 5 моделей)

## 🤝 Где модели СОГЛАСНЫ (high confidence)
Если ≥3 моделей сошлись в каком-то выводе — это сильный сигнал. Перечисли:
- Утверждение
- Сколько моделей подтвердили (X/5)
- Цитаты (имена моделей и фрагменты)

## ⚔️ Где модели СПОРЯТ (interesting)
Где есть расхождение — это интересно для отдельного разбора:
- Утверждение vs Контр-утверждение
- Кто за / кто против
- Кто, на ваш взгляд, прав и почему

## 🎯 СИНТЕЗ-РЕКОМЕНДАЦИИ (топ-5 действий)
На основе консенсуса И качественных аргументов из споров:
1. Действие → почему → у кого взято
2. ...

## 🌟 Лучшее уникальное наблюдение
Какое наблюдение есть только у ОДНОЙ модели но оно ценное? (новый ракурс).

## 📊 Кто из моделей дал самый качественный вердикт?
Субъективная оценка: какая модель лучше всех справилась? Почему?

ВЕРДИКТЫ:

{verdicts_block}
"""


def collect_context() -> str:
    """Собирает все source-файлы в один текст."""
    parts = []
    for f in SRC_FILES:
        if f.exists():
            text = f.read_text(encoding="utf-8", errors="replace")
            # обрезаем очень большие
            if len(text) > 60_000:
                text = text[:60_000] + f"\n\n[... обрезано {len(text) - 60_000} символов ...]"
            parts.append(f"\n=== {f.relative_to(PROJECT_ROOT).as_posix()} ===\n{text}\n")
        else:
            parts.append(f"\n=== {f.name} (отсутствует) ===\n")
    return "".join(parts)


def get_verdict(provider: str, prompt: str) -> tuple[str, str, str]:
    """Возвращает (provider, model, text). Не падает — ошибки возвращает в text."""
    model = DEFAULT_MODELS.get(provider, "")
    try:
        text = call_provider(provider, prompt, None, max_tokens=6000, image_path=None)
        return (provider, model, text)
    except Exception as e:
        return (provider, model, f"❌ ERROR: {str(e)[:500]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Team Verdict — коллективный аудит через LLM ансамбль")
    parser.add_argument("--providers", help="Список через запятую (по умолчанию все доступные)")
    parser.add_argument("--skip-meta", action="store_true", help="Не делать финальный meta-summary")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    load_env()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # Выбираем провайдеров
    if args.providers:
        providers = [p.strip() for p in args.providers.split(",")]
    else:
        providers = [p for p in ALL_PROVIDERS if has_key(p)]

    if len(providers) < 2:
        print(f"[team] недостаточно провайдеров с ключами: {providers}", file=sys.stderr)
        return 1

    print(f"[team] участники: {', '.join(providers)}", file=sys.stderr)

    # Собираем контекст
    context = collect_context()
    in_chars = len(context)
    print(f"[team] контекст: {in_chars} символов (~{int(in_chars/3.5)} токенов)", file=sys.stderr)

    # Параллельный запуск
    results: list[tuple[str, str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers)) as ex:
        futures = {}
        for p in providers:
            prompt = VERDICT_PROMPT.format(
                model_name=f"{p} ({DEFAULT_MODELS.get(p, '?')})",
                context=context,
            )
            futures[ex.submit(get_verdict, p, prompt)] = p

        for fut in concurrent.futures.as_completed(futures):
            provider, model, text = fut.result()
            results.append((provider, model, text))
            preview = text[:120].replace("\n", " ")
            print(f"[team] ✓ {provider} ({model}): {preview}...", file=sys.stderr)

    # Сохраняем все вердикты в один файл
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    OUTPUT_OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
    out_obsidian = OUTPUT_OBSIDIAN_DIR / f"{today}-team-verdict.md"

    sections = []
    sections.append(
        "---\n"
        "tags: [verdict, audit, team, auto, area/diagnostics, role/arch, role/dev]\n"
        "type: team-verdict\n"
        f"date: {today}\n"
        f"providers: [{', '.join(p for p, _, _ in results)}]\n"
        'parent: "[[Project-MOC]]"\n'
        "---\n\n"
        f"# Team Verdict — {today}\n\n"
        f"> Коллективный аудит {len(results)} LLM-провайдерами. "
        f"Контекст: {in_chars // 1024}K символов.\n\n---\n"
    )

    for provider, model, text in sorted(results):
        sections.append(f"\n# 🤖 {provider.upper()} — `{model}`\n\n{text}\n\n---\n")

    # Meta-summary (на самом надёжном провайдере = mistral, если доступен)
    if not args.skip_meta and len(results) >= 2:
        verdicts_block = "\n\n".join(
            f"### {p} ({m})\n{t[:8000]}"  # каждый вердикт обрезаем до 8k символов
            for p, m, t in sorted(results) if not t.startswith("❌")
        )
        meta_prompt = META_PROMPT.format(verdicts_block=verdicts_block)
        # выбираем для meta самого «крупного»: mistral → openrouter → cerebras
        meta_provider = next((p for p in ["mistral", "openrouter", "cerebras", "gemini"]
                              if p in [r[0] for r in results] and not next(r[2] for r in results if r[0] == p).startswith("❌")), None)
        if meta_provider:
            print(f"[team] meta-summary через {meta_provider}...", file=sys.stderr)
            try:
                meta_text = call_provider(
                    meta_provider, meta_prompt, None, max_tokens=8000, image_path=None,
                )
                sections.append(f"\n# 🧠 META-VERDICT (синтез через {meta_provider})\n\n{meta_text}\n")
            except Exception as e:
                sections.append(f"\n# 🧠 META-VERDICT\n\n❌ Не удалось сгенерировать: {e}\n")

    out_obsidian.write_text("".join(sections), encoding="utf-8")

    # И копию в memory/
    OUTPUT_MEMORY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MEMORY.write_text("".join(sections), encoding="utf-8")

    if args.quiet:
        print(f"[team] OK n={len(results)} -> {out_obsidian}", file=sys.stderr)
    else:
        ok_count = sum(1 for _, _, t in results if not t.startswith("❌"))
        print(f"\n[team] OK: {ok_count}/{len(results)} провайдеров ответили")
        for p, m, t in sorted(results):
            mark = "❌" if t.startswith("❌") else "✅"
            print(f"  {mark} {p:15s} ({m})")
        print(f"\n  -> {out_obsidian}")
        print(f"  -> {OUTPUT_MEMORY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
