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
  cerebras → groq → openrouter → mistral → github_models → sambanova → nvidia → gemini

Провайдеры (модели проверены живьём 30.05.2026):
  groq           — gpt-oss-120b (быстро, ~14 400 RPD, 30 RPM)
  cerebras       — GLM-4.7 thinking (30 RPM, 1M tok/day; отдаёт только gpt-oss-120b + zai-glm-4.7)
  gemini         — Gemini 3.5 Flash (250 RPD, 1M context, multimodal)
  mistral        — Magistral Medium (1B токенов/мес, 1 req/s, reasoning)
  openrouter     — Nemotron-3 Super 120B free (стабилен; deepseek-v4/minimax/kimi часто 429)
  github_models  — DeepSeek-R1 (≈аналог Opus, ~50 RPD, 10 RPM; нет бесплатного Claude)
  sambanova      — DeepSeek-V3.2 (persistent free tier ✅ активен; cloud.sambanova.ai)
  nvidia         — NVIDIA NIM (⚠️ регистрация заблокирована из РФ; scaffolding без ключа)

Свободного Claude (Opus/Sonnet) для API НЕТ: OpenRouter free его не отдаёт,
GitHub Models inference тоже. Ближайшие free-аналоги — DeepSeek-R1 / GLM-4.7 / Nemotron.

Ключи в .env:
  GROQ_API_KEY, GEMINI_API_KEY, CEREBRAS_API_KEY, MISTRAL_API_KEY,
  OPENROUTER_API_KEY, GITHUB_MODELS_TOKEN, SAMBANOVA_API_KEY, NVIDIA_API_KEY

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

# Дефолтные модели по провайдеру (проверено живьём 30.05.2026 через models.list + smoke-test)
# Cerebras free: gpt-oss-120b, zai-glm-4.7  (qwen-3-235b УДАЛЁН → 404; только эти две сейчас)
# OpenRouter free: nemotron-3-super-120b (стабилен), deepseek-v4-flash/minimax-m2.5/kimi-k2.6/
#   qwen3-next-80b — часто 429/503 upstream → НЕ дефолт. gpt-oss-120b:free, hermes-405b:free, glm-4.5-air:free.
# GitHub Models: /models list → 404, но конкретные ID работают. Доступны deepseek/DeepSeek-R1,
#   openai/gpt-4.1-mini, openai/gpt-4o. (grok-3-mini → unknown_model)
# Gemini: gemini-3.5-flash (GA), gemini-3.1-flash-lite, gemini-2.5-flash/pro.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",                               # 120B reasoner на скорости Groq (было llama-4-scout-17b)
    # 🔴 18.08: cerebras МЁРТВ для нас — zai-glm-4.7 архивирован (404), а весь каталог
    # (gpt-oss-120b, gemma-4-31b) отвечает 402 Payment required: free-tier аккаунта закрыт.
    "cerebras": "gpt-oss-120b",                                  # единственная живая модель каталога — заработает, если оплатят биллинг
    "gemini": "gemini-3.5-flash",                                # upd 30.05.2026 (было 2.5-flash)
    "mistral": "magistral-medium-latest",                        # reasoning/synthesis voice
    "openrouter": "nvidia/nemotron-3-ultra-550b-a55b:free",      # 13.08: апгрейд super-120B → ultra-550B (1M ctx, 1.7с, тот же ключ, бесплатно)
    "github_models": "openai/gpt-4.1-mini",                      # чистый/надёжный (было gpt-4o-mini). DeepSeek-R1 → --reasoning (течёт <think> в swarm)
    # --- новые провайдеры (активируются при наличии ключа; см. ENV_KEYS) ---
    # 18.08: DeepSeek-V3.2/V3.1 и Llama-3.3-70B на этом ключе отдают 429 «high demand» КАЖДЫЙ
    # прогон (голос терялся). MiniMax-M2.7 из того же каталога ответил за 7.3с → он и дефолт.
    # Бонусом MiniMax — семейство, которого в рою больше нигде нет.
    "sambanova": "MiniMax-M2.7",                                 # каталог: DeepSeek-V3.1/V3.2, MiniMax-M2.7, Meta-Llama-3.3-70B, gemma-4-31B, gpt-oss-120b
    "nvidia": "deepseek-ai/deepseek-r1",                         # ⚠️ НЕ проверено: NVIDIA NIM (build.nvidia.com) блокирует регистрацию из РФ (+7). Без ключа неактивен.
    "omniroute": "auto/best-chat",                               # 12.08: локальный gateway (338 провайдеров, auto-fallback). Ключ НЕ нужен.
    "deepseek": "deepseek-chat",                                 # ПРЯМОЙ api.deepseek.com (платный, дёшево ~$0.3/1M, 1M ctx). v4 non-thinking. Активен при DEEPSEEK_API_KEY. Сильный голос ≈Opus для роя.
    # --- 13.08: ДОПОЛНИТЕЛЬНЫЕ СЕМЕЙСТВА через УЖЕ ИМЕЮЩИЙСЯ ключ OpenRouter ---
    # Задача Егора: «все самые сильные и без подписок для сохранения бюджета».
    # Это НЕ новые ключи и НЕ подписки — тот же OPENROUTER_API_KEY, модели с суффиксом :free.
    # Берём РАЗНЫЕ компании: рою нужны разные подходы, а не клоны одного семейства.
    # gpt-oss-20b намеренно НЕ берём — groq уже даёт gpt-oss-120b (то же семейство, сильнее).
    "or_cohere": "cohere/north-mini-code:free",                  # Cohere — семейства нет больше нигде в рое
    "or_poolside": "poolside/laguna-s-2.1:free",                 # Poolside — новое семейство
    # 18.08: or_gemma снят — 429 upstream у Google КАЖДЫЙ прогон, и это дубль семейства Gemma.
    # Замена: Dots Studio — самое свежее семейство из 15 живых :free на OpenRouter, 512k ctx.
    "or_dots": "dots-studio/dots-3-note-preview:free",           # Dots Studio (512k ctx) — 8.4с на боевом промпте
    # 18.08: замена мёртвому cerebras. Qwen/Alibaba — семейства в рою нет; ключ Groq уже есть.
    # ⚠️ делит квоту Groq с голосом `groq` (gpt-oss-120b): 30 RPM / ~14 400 RPD на двоих.
    "groq_qwen": "qwen/qwen3.6-27b",                             # Qwen 3.6 27B — 6.8с, 70% кириллицы на боевом промпте
    # --- 18.08: добор роя до 12 ЖИВЫХ (задача Егора). Честная оговорка: НОВЫХ СЕМЕЙСТВ
    # в доступе больше НЕТ — из 16 проверенных кандидатов выжили только клоны уже имеющихся.
    # Взяты двое, что дают иной РЕЖИМ работы (агент с инструментами), а не только имя:
    "groq_compound": "groq/compound",                            # агентная надстройка Groq (инструменты/поиск) — 5.7с, 1085 симв.
    "ag_gemini_agent": "antigravity/gemini-pro-agent",           # агентный Gemini; ЕДИНСТВЕННАЯ модель Antigravity с живой квотой — 27.7с
    # --- 13.08: Antigravity OAuth (Егор подключил личным Google-аккаунтом) → 30 моделей БЕСПЛАТНО ---
    # Идут через локальный шлюз, но это НЕ клоны felo/oc: настоящие Gemini 3.x Pro и Claude 4.6.
    # Проверены боевым промптом (не «60−26»: felo/hy3 именно так и обманули — верно на коротком, пусто на длинном).
    "ag_gemini_pro": "antigravity/gemini-3.1-pro-low",           # Gemini 3.1 Pro — сильнее нашего прямого gemini-3.5-flash
    "ag_opus": "antigravity/claude-opus-4-6-thinking",           # Claude Opus 4.6 thinking — сильнейший бесплатный reasoner
}

# Модели для --reasoning (специализированные thinking-модели; проверено 30.05.2026)
REASONING_MODELS = {
    "github_models": "deepseek/DeepSeek-R1",                     # самый надёжный reasoner (не флакает как OpenRouter)
    "openrouter": "deepseek/deepseek-v4-flash:free",             # native reasoning 1M ctx (arcee-trinity → 404, убрано)
    "cerebras": "gpt-oss-120b",                                  # 18.08: qwen-3-235b и zai-glm-4.7 → 404; из живого каталога это единственный reasoner
    "sambanova": "DeepSeek-V3.2",                                # R1 на free-tier SambaNova недоступен
    "nvidia": "deepseek-ai/deepseek-r1",
    "omniroute": "auto/best-reasoning",                          # авто-выбор лучшего reasoner среди живых провайдеров
    "deepseek": "deepseek-reasoner",                             # v4 thinking-режим (нативный reasoning, 1M ctx)
}

# Base URLs для OpenAI-совместимых провайдеров
OPENAI_COMPAT_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "github_models": "https://models.github.ai/inference",
    "sambanova": "https://api.sambanova.ai/v1",                  # ключ: https://cloud.sambanova.ai (persistent free tier)
    "nvidia": "https://integrate.api.nvidia.com/v1",            # ключ: https://build.nvidia.com (40 RPM free)
    "omniroute": "http://127.0.0.1:20128/v1",                   # локальный OmniRoute (npm i -g omniroute; omniroute serve)
    "deepseek": "https://api.deepseek.com",                     # ключ: https://platform.deepseek.com (платный). OpenAI-совместимый.
    "or_cohere": "https://openrouter.ai/api/v1",                # псевдо-провайдеры: тот же OpenRouter,
    "or_poolside": "https://openrouter.ai/api/v1",              # но ДРУГИЕ семейства моделей (см. DEFAULT_MODELS)
    "or_dots": "https://openrouter.ai/api/v1",
    "groq_qwen": "https://api.groq.com/openai/v1",              # тот же Groq, но семейство Qwen вместо gpt-oss
    "groq_compound": "https://api.groq.com/openai/v1",          # тот же Groq, агентный режим
    "ag_gemini_agent": "http://127.0.0.1:20128/v1",             # через локальный OmniRoute (Antigravity OAuth)
    "ag_gemini_pro": "http://127.0.0.1:20128/v1",           # через локальный OmniRoute (OAuth-подключение Antigravity)
    "ag_opus": "http://127.0.0.1:20128/v1",
}

# ENV-имена ключей
ENV_KEYS = {
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "github_models": "GITHUB_MODELS_TOKEN",
    "sambanova": "SAMBANOVA_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "omniroute": "OMNIROUTE_API_KEY",                            # опционален: локальный сервер работает без ключа
    "or_cohere": "OPENROUTER_API_KEY",                           # все три — ТОТ ЖЕ ключ OpenRouter, новых регистраций не нужно
    "or_poolside": "OPENROUTER_API_KEY",
    "or_dots": "OPENROUTER_API_KEY",
    "groq_qwen": "GROQ_API_KEY",                                 # тот же ключ Groq, что и у голоса `groq`
    "groq_compound": "GROQ_API_KEY",
    "ag_gemini_agent": "OMNIROUTE_API_KEY",
    "ag_gemini_pro": "OMNIROUTE_API_KEY",
    "ag_opus": "OMNIROUTE_API_KEY",
}

# Провайдеры, которым ключ НЕ обязателен (локальные шлюзы)
KEYLESS = {"omniroute"}

# ─── OmniRoute ПО ТРЕБОВАНИЮ (18.08, Егор: «бот обрастает процессами») ───
# Шлюз держал 350 MB круглосуточно (pm2 показывал 46 MB — это launcher, воркер ещё 304 MB),
# хотя нужен только на время прогона роя: ag_* голоса + запасные входы при 429.
# Ни один фоновый процесс от него не зависит (news_sphere ходит к API напрямую),
# поэтому держать его под pm2 24/7 не нужно — поднимаем на прогон и гасим.
# Провайдеры, которые ходят ЧЕРЕЗ локальный шлюз (и требуют его поднятым).
# Одно множество на все три места (stream=False · автоподъём в CLI · маршрутизация),
# иначе при добавлении нового ag_*-голоса легко забыть одно из них.
GATEWAY_PROVIDERS = {"omniroute", "ag_gemini_pro", "ag_opus", "ag_gemini_agent"}
GATEWAY_HOST, GATEWAY_PORT = "127.0.0.1", 20128
GATEWAY_BIN = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "omniroute" / "bin" / "omniroute.mjs"


def gateway_alive(timeout: float = 1.0) -> bool:
    """Слушает ли шлюз порт. Дёшево — обычный connect, без HTTP."""
    import socket
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex((GATEWAY_HOST, GATEWAY_PORT)) == 0


def ensure_gateway(wait_sec: int = 45):
    """Поднимает OmniRoute, если порт молчит.
    → Popen, если подняли МЫ (значит нам же и гасить), или None (уже был жив / нет бинаря)."""
    if gateway_alive():
        return None
    if not GATEWAY_BIN.exists():
        print(f"[gateway] не найден {GATEWAY_BIN} — ag_*/spare будут недоступны", file=sys.stderr)
        return None
    import subprocess, time
    print("[gateway] OmniRoute не запущен → поднимаю на время прогона...", file=sys.stderr)
    # --no-open ОБЯЗАТЕЛЕН: `serve` по умолчанию открывает браузер на /home. Под pm2 это
    # случалось раз в сутки и не мешало, а при подъёме на каждый прогон — вкладка на КАЖДЫЙ
    # запрос к рою (Егор поймал 18.08). --no-tray заодно убирает иконку в трее.
    proc = subprocess.Popen(
        ["node", str(GATEWAY_BIN), "serve", "--no-open", "--no-tray"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=str(PROJECT_ROOT),          # чтобы шлюз подхватил .env проекта, как под pm2
    )
    for _ in range(wait_sec * 2):
        time.sleep(0.5)
        if gateway_alive():
            print(f"[gateway] готов за ~{_ * 0.5:.1f}с (pid {proc.pid})", file=sys.stderr)
            return proc
    print(f"[gateway] не поднялся за {wait_sec}с — гашу", file=sys.stderr)
    stop_gateway(proc)
    return None


def stop_gateway(proc) -> None:
    """Гасит шлюз, поднятый нами. ⚠️ launcher ФОРКАЕТ воркер (он и держит 304 MB),
    поэтому убивать надо ДЕРЕВО: одиночный kill оставит воркер висеть на порту."""
    if proc is None:
        return
    import subprocess
    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        print(f"[gateway] остановлен (pid {proc.pid} + дочерние)", file=sys.stderr)
    except Exception as e:
        print(f"[gateway] не удалось остановить: {e}", file=sys.stderr)

# Цепочка fallback при 429/503 (sambanova/nvidia в конце — активны только при наличии ключа)
FALLBACK_ORDER = ["cerebras", "groq", "openrouter", "mistral", "github_models",
                  "sambanova", "deepseek", "nvidia", "gemini"]


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
    # Локальные шлюзы (omniroute) ключа не требуют — считаем доступными всегда.
    # KEYLESS объявлен ниже по файлу, поэтому берём через globals() с запасным множеством.
    if provider in globals().get("KEYLESS", {"omniroute"}):
        return True
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

    # 2. Reasoning → deepseek (v4 нативный reasoner, 1M ctx) → github_models (R1) → sambanova → openrouter → gemini
    if reasoning:
        for p in ["deepseek", "github_models", "sambanova", "openrouter"]:
            if has_key(p):
                return p
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
        if provider in KEYLESS:
            key = "local"          # локальный шлюз не проверяет ключ
        else:
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
    # OmniRoute по умолчанию отдаёт SSE-поток — просим обычный JSON
    if provider in GATEWAY_PROVIDERS:
        kwargs["stream"] = False
    # OpenRouter поддерживает usage stats
    if provider == "openrouter":
        kwargs["extra_headers"] = {
            "HTTP-Referer": "https://github.com/local/oko-mtf",
            "X-Title": "Oko MTF Bot",
        }
    resp = client.chat.completions.create(**kwargs)
    # OmniRoute за `auto/*` подставляет РАЗНЫЕ модели от запроса к запросу (проверено 13.08:
    # big-pickle → felo-chat → hy3-free). Без этой строки в протоколе роя не видно, кто голосовал.
    actual = getattr(resp, "model", None)
    if provider == "omniroute" and actual and actual != model:
        print(f"[llm_ask] omniroute: {model} → РЕАЛЬНО {actual}", file=sys.stderr)
    msg = resp.choices[0].message
    content = msg.content
    # Reasoning-модели (GLM-4.7, DeepSeek-R1) при finish_reason=length могут вернуть content=None
    # (весь бюджет ушёл в thinking) — пробуем reasoning_content, иначе понятная ошибка вместо краша.
    if content is None:
        content = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
        if not content:
            finish = getattr(resp.choices[0], "finish_reason", "?")
            raise RuntimeError(
                f"{provider}/{model}: пустой ответ (content=None, finish_reason={finish}) — "
                f"reasoning-модель не уложилась в max_tokens={max_tokens}"
            )
    # Reasoning-модели (DeepSeek-R1 и др.) вшивают <think>...</think> прямо в текст —
    # берём финальный ответ после закрывающего тега (если он есть).
    if isinstance(content, str) and "</think>" in content:
        content = content.split("</think>")[-1].strip()
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
        # 12.08: "deepseek" был в MODELS/BASES/KEYS (прямой api.deepseek.com), но НЕ выведен
        # в choices — прямой путь к DS был недоступен из CLI при живом ключе. Добавлен.
        # `--reasoning` даёт deepseek-reasoner (thinking-режим).
        choices=["auto", "groq", "cerebras", "gemini", "mistral", "openrouter",
                 "github_models", "sambanova", "deepseek", "nvidia", "omniroute",
                 # 13.08: доп. семейства через тот же ключ OpenRouter — иначе CLI их не примет
                 # 18.08: or_gemma → or_dots (429 upstream + дубль Gemma); +groq_qwen на ключе Groq
                 "or_cohere", "or_poolside", "or_dots", "groq_qwen",
                 "groq_compound", "ag_gemini_pro", "ag_opus", "ag_gemini_agent"],
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
        for p in ["groq", "groq_qwen", "cerebras", "gemini", "mistral", "openrouter",
                  "or_cohere", "or_poolside", "or_dots",
                  "github_models", "sambanova", "nvidia", "deepseek"]:
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

    # --reasoning без явной --model → берём thinking-модель провайдера
    if args.reasoning and not args.model and provider in REASONING_MODELS:
        args.model = REASONING_MODELS[provider]

    # Шлюз больше не висит под pm2 (18.08) → поднимаем его сам, если просят модель за ним.
    # Гасим через atexit, и только если подняли МЫ: чужой запущенный шлюз не трогаем.
    if provider in GATEWAY_PROVIDERS:
        _gw = ensure_gateway()
        if _gw is not None:
            import atexit
            atexit.register(stop_gateway, _gw)

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
