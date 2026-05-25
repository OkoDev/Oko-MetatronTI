"""LLM-делегатор v2: 6 провайдеров с auto-routing и fallback-цепочкой.

Использование:
  python tools/llm_ask.py "вопрос"
  python tools/llm_ask.py "резюмируй" --file path/to/file.md
  python tools/llm_ask.py "разбери" --file big.log --provider mistral
  python tools/llm_ask.py "опиши паттерн" --image chart.png
  python tools/llm_ask.py "вопрос" --provider cerebras
  python tools/llm_ask.py "вопрос" --provider github_models --model gpt-4o-mini
  python tools/llm_ask.py "сложный анализ" --provider openrouter --model deepseek/deepseek-r1:free

Auto-routing (--provider auto):
  - есть --image                     → gemini (multimodal)
  - --file и > 200k токенов          → mistral (1B/мес лимит, большой контекст)
  - --file и > 100k токенов          → gemini (1M context)
  - --reasoning                       → openrouter (DeepSeek R1 free)
  - быстрая короткая задача          → cerebras (если ключ есть, иначе groq)
  - дефолт                            → groq

Auto-fallback при 429/503:
  cerebras → groq → openrouter → mistral → github_models → gemini

Провайдеры:
  groq           — Llama 3.3 70B (14 400 RPD, 30 RPM, ~500 tok/s)
  cerebras       — Llama 3.3 70B (14 400 RPD, 30 RPM, 2200 tok/s)
  gemini         — Gemini 2.5 Flash (250 RPD, 1M context, multimodal)
  mistral        — Mistral Large 3 (1B токенов/мес, 1 req/s)
  openrouter     — DeepSeek R1 / Llama 3.3 free (50 RPD, 20 RPM)
  github_models  — GPT-4o / Claude 3.5 Sonnet (50-150 RPD, 10-15 RPM)

Ключи в .env:
  GROQ_API_KEY, GEMINI_API_KEY, CEREBRAS_API_KEY,
  MISTRAL_API_KEY, OPENROUTER_API_KEY, GITHUB_MODELS_TOKEN

Возвращает: текст ответа на stdout. Лог провайдера в stderr.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# Дефолтные модели по провайдеру
# Cerebras free: zai-glm-4.7, gpt-oss-120b, llama3.1-8b, qwen-3-235b-a22b-instruct-2507
# OpenRouter free (актуально 25.05.2026): deepseek/deepseek-v4-flash:free, openai/gpt-oss-120b:free,
#   nvidia/nemotron-3-super-120b-a12b:free, nousresearch/hermes-3-llama-3.1-405b:free
# GitHub Models: /models endpoint → 404 (API изменился, gpt-4o-mini оставляем)
DEFAULT_MODELS = {
    "groq": "meta-llama/llama-4-scout-17b-16e-instruct",         # Llama 4 Scout MoE (upd 25.05.2026)
    "cerebras": "gpt-oss-120b",                                  # стабильнее Qwen 235B (та часто 429)
    "gemini": "gemini-2.5-flash",
    "mistral": "magistral-medium-latest",                        # reasoning/synthesis (upd 25.05.2026)
    "openrouter": "nvidia/nemotron-3-super-120b-a12b:free",      # nemotron 120B стабильно (deepseek-v4 402)
    "github_models": "openai/gpt-4o-mini",
}

# Модели для --reasoning (специализированные thinking-модели)
REASONING_MODELS = {
    "openrouter": "arcee-ai/trinity-large-thinking:free",
    "cerebras": "qwen-3-235b-a22b-instruct-2507",
}

# Base URLs для OpenAI-совместимых провайдеров
OPENAI_COMPAT_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "github_models": "https://models.github.ai/inference",
}

# ENV-имена ключей
ENV_KEYS = {
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "github_models": "GITHUB_MODELS_TOKEN",
}

# Цепочка fallback при 429/503
FALLBACK_ORDER = ["cerebras", "groq", "openrouter", "mistral", "github_models", "gemini"]


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def has_key(provider: str) -> bool:
    return bool(os.environ.get(ENV_KEYS.get(provider, "")))


def approx_tokens(text: str) -> int:
    return int(len(text) / 3.5)


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def auto_route(file_text: Optional[str], has_image: bool, reasoning: bool) -> str:
    """Выбирает провайдера по характеристикам задачи и доступным ключам."""
    # 1. Картинка → только gemini (multimodal)
    if has_image:
        return "gemini"

    # 2. Reasoning → openrouter (DeepSeek R1 free) или gemini как backup
    if reasoning:
        if has_key("openrouter"):
            return "openrouter"
        return "gemini"

    # 3. Гигантский файл (>200k токенов) → mistral (1B/мес, большой контекст)
    if file_text and approx_tokens(file_text) > 200_000:
        if has_key("mistral"):
            return "mistral"
        return "gemini"

    # 4. Большой файл (>100k токенов) → gemini (1M context)
    if file_text and approx_tokens(file_text) > 100_000:
        return "gemini"

    # 5. По умолчанию — самый быстрый из доступных
    for p in ["cerebras", "groq"]:
        if has_key(p):
            return p
    return "gemini"


def ask_openai_compat(provider: str, prompt: str, model: str, max_tokens: int,
                      reasoning_model: bool = False) -> str:
    """Универсальный вызов для OpenAI-совместимых API (groq/cerebras/mistral/openrouter/github_models)."""
    from openai import OpenAI

    key = os.environ.get(ENV_KEYS[provider])
    if not key:
        raise RuntimeError(f"{ENV_KEYS[provider]} не задан в .env")

    base_url = OPENAI_COMPAT_URLS[provider]
    client = OpenAI(api_key=key, base_url=base_url)

    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        temperature=0.2,
        messages=[
            {"role": "system", "content": "Отвечай кратко и по существу. Только русский язык."},
            {"role": "user", "content": prompt},
        ],
    )
    # OpenRouter поддерживает usage stats
    if provider == "openrouter":
        kwargs["extra_headers"] = {
            "HTTP-Referer": "https://github.com/local/oko-mtf",
            "X-Title": "Oko MTF Bot",
        }
    resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content
    # Thinking-модели (magistral, deepseek-r1 и др.) возвращают content как список блоков
    if isinstance(content, list):
        # Сначала ищем text-блоки верхнего уровня
        text_parts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if text_parts:
            return " ".join(text_parts).strip()
        # Magistral: только thinking-блоки — извлекаем из вложенного thinking[]
        for b in content:
            if isinstance(b, dict) and b.get("type") == "thinking":
                inner = b.get("thinking") or []
                inner_parts = [t["text"] for t in inner if isinstance(t, dict) and t.get("type") == "text"]
                if inner_parts:
                    return " ".join(inner_parts).strip()
        return ""
    return content.strip()


def ask_gemini(prompt: str, model: str, image_path: Optional[Path]) -> str:
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY не задан в .env")

    client = genai.Client(api_key=key)
    contents = []
    if image_path:
        mime = "image/png" if image_path.suffix.lower() in (".png",) else "image/jpeg"
        contents.append(
            types.Part.from_bytes(data=image_path.read_bytes(), mime_type=mime)
        )
    contents.append(prompt)

    cfg_kwargs = dict(
        temperature=0.2,
        system_instruction="Отвечай кратко и по существу. Только русский язык.",
    )
    try:
        cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass

    resp = client.models.generate_content(
        model=model, contents=contents,
        config=types.GenerateContentConfig(**cfg_kwargs),
    )
    return (resp.text or "").strip()


def call_provider(provider: str, prompt: str, model: Optional[str], max_tokens: int,
                  image_path: Optional[Path]) -> str:
    """Вызов одного провайдера. Бросает исключение при ошибке."""
    if provider == "gemini":
        return ask_gemini(prompt, model or DEFAULT_MODELS["gemini"], image_path)
    if provider in OPENAI_COMPAT_URLS:
        return ask_openai_compat(provider, prompt, model or DEFAULT_MODELS[provider], max_tokens)
    raise RuntimeError(f"Неизвестный provider: {provider}")


def call_with_fallback(primary: str, prompt: str, model: Optional[str], max_tokens: int,
                       image_path: Optional[Path], no_fallback: bool = False) -> tuple[str, str]:
    """Пробует primary, при 429/503 — следующий из FALLBACK_ORDER. Возвращает (answer, used_provider)."""
    tried = [primary]
    try:
        return call_provider(primary, prompt, model, max_tokens, image_path), primary
    except Exception as e:
        msg = str(e)
        is_rate_limit = "429" in msg or "RESOURCE_EXHAUSTED" in msg or "rate_limit" in msg.lower()
        is_unavail = "503" in msg or "UNAVAILABLE" in msg or "overload" in msg.lower()
        if no_fallback or not (is_rate_limit or is_unavail):
            raise

        # multimodal требует gemini — fallback не сработает если есть image
        if image_path:
            raise RuntimeError(f"{primary} fallback невозможен с --image: {e}")

        for nxt in FALLBACK_ORDER:
            if nxt in tried or nxt == primary:
                continue
            if not has_key(nxt) and nxt != "gemini":
                continue
            if nxt == "gemini" and not has_key("gemini"):
                continue
            tried.append(nxt)
            print(f"[llm_ask] {primary} {('429' if is_rate_limit else '503')} → fallback {nxt}",
                  file=sys.stderr)
            try:
                # для fallback модель не передаём — берётся дефолтная провайдера
                return call_provider(nxt, prompt, None, max_tokens, image_path), nxt
            except Exception as e2:
                print(f"[llm_ask] {nxt} тоже упал: {e2}", file=sys.stderr)
                continue
        raise RuntimeError(f"Все провайдеры упали. Tried: {tried}. Last: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM-делегатор v2 (6 провайдеров)")
    parser.add_argument("prompt", help="Текст запроса")
    parser.add_argument("--file", type=Path, help="Файл, его содержимое добавится в запрос")
    parser.add_argument("--image", type=Path, help="Картинка (только gemini)")
    parser.add_argument(
        "--provider",
        choices=["auto", "groq", "cerebras", "gemini", "mistral", "openrouter", "github_models"],
        default="auto",
        help="LLM-провайдер (по умолчанию auto)",
    )
    parser.add_argument("--model", help="Конкретная модель провайдера")
    parser.add_argument("--max-tokens", type=int, default=4000, help="Лимит output токенов")
    parser.add_argument("--reasoning", action="store_true",
                        help="Использовать reasoning-модель (DeepSeek R1 через openrouter)")
    parser.add_argument("--no-fallback", action="store_true",
                        help="Не делать fallback при 429/503")
    parser.add_argument("--out", type=Path, help="Записать ответ в файл вместо stdout")
    parser.add_argument("--list-keys", action="store_true",
                        help="Показать какие ключи доступны и выйти")
    args = parser.parse_args()

    load_env()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if args.list_keys:
        print("Available keys:")
        for p in ["groq", "cerebras", "gemini", "mistral", "openrouter", "github_models"]:
            mark = "[+]" if has_key(p) else "[ ]"
            print(f"  {mark} {p:15s} ({ENV_KEYS[p]})")
        return 0

    file_text: Optional[str] = None
    if args.file:
        if not args.file.exists():
            print(f"ERROR: файл не найден: {args.file}", file=sys.stderr)
            return 1
        file_text = read_file(args.file)

    if args.image and not args.image.exists():
        print(f"ERROR: картинка не найдена: {args.image}", file=sys.stderr)
        return 1

    provider = args.provider
    if provider == "auto":
        provider = auto_route(file_text, has_image=bool(args.image), reasoning=args.reasoning)

    if not has_key(provider):
        print(f"ERROR: ключ для {provider} не задан ({ENV_KEYS[provider]} в .env)", file=sys.stderr)
        return 1

    if args.image and provider != "gemini":
        print(f"WARNING: --image игнорируется при provider={provider} (только gemini multimodal)",
              file=sys.stderr)

    full_prompt = args.prompt
    if file_text is not None:
        full_prompt = f"{args.prompt}\n\n=== Содержимое файла {args.file.name} ===\n{file_text}"

    try:
        answer, used = call_with_fallback(
            provider, full_prompt, args.model, args.max_tokens, args.image,
            no_fallback=args.no_fallback,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    in_tokens = approx_tokens(full_prompt)
    out_tokens = approx_tokens(answer)
    print(f"[llm_ask] provider={used} ~in={in_tokens} ~out={out_tokens}", file=sys.stderr)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(answer, encoding="utf-8")
        print(str(args.out))
    else:
        print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
