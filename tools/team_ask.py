"""Team Ask — командное обсуждение конкретного вопроса 5-6 LLM провайдерами.

Отличие от team_verdict.py:
  team_verdict — фиксированный аудит проекта (5 разделов, дефолтный промпт)
  team_ask     — твой свободный вопрос + контекст проекта

Каждая модель отвечает независимо. Затем — meta-синтез через Mistral:
где согласны, где спорят, какой синтезированный ответ.

Запуск:
  python tools/team_ask.py "Стоит ли отключать wt_sideways полностью?"
  python tools/team_ask.py "Что главное за ночь?" --file memory/last_trade_review.md
  python tools/team_ask.py "Разбери проблему" --providers cerebras,mistral
  python tools/team_ask.py "Краткий ответ" --no-context  # без bundle проекта
  python tools/team_ask.py "..." --skip-meta              # без meta-синтеза

Output:
  obsidian/Team-Discussions/<DATE>-<slug>.md
  memory/last_team_discussion.md
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm_ask import (load_env, has_key, ENV_KEYS, DEFAULT_MODELS, call_provider,  # noqa: E402
                     ensure_gateway, stop_gateway)


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Источники для bundle (как team_verdict)
SRC_FILES = [
    PROJECT_ROOT / "memory" / "session_brief.md",
    PROJECT_ROOT / "memory" / "project_timeline.md",
    PROJECT_ROOT / "memory" / "last_trade_review.md",
    PROJECT_ROOT / "memory" / "log_digest.md",
    PROJECT_ROOT / "TASKS.md",
]

OUTPUT_OBSIDIAN_DIR = PROJECT_ROOT / "obsidian" / "Team-Discussions"
OUTPUT_MEMORY = PROJECT_ROOT / "memory" / "last_team_discussion.md"

# Порядок = все известные провайдеры; main() оставляет только те, у кого есть ключ (has_key).
# sambanova/nvidia активируются автоматически при добавлении SAMBANOVA_API_KEY / NVIDIA_API_KEY в .env.
# NB: deepseek НЕ в списке голосов (R5) — он платный + используется как ДИРИЖЁР в
# swarm_orchestrator (ARCH-126), не как один из голосов. Обычный /team-ask бесплатен.
# 12.08: + omniroute — локальный шлюз (338 провайдеров, auto-fallback). Ключа не требует,
# has_key() возвращает True всегда. Добавлен как ЗАПАСНОЙ голос: рой стабильно давал 5/7
# (github_models 410 retirement, sambanova timeout, openrouter 404 на reasoning), а
# omniroute сам перебирает живых провайдеров. ⚠️ компрессия у него должна быть выключена —
# наши брифы это таблицы чисел, искажение = ложный вердикт.
# github_models УБРАН 13.08: отдаёт 410 `github_models_retirement_brownout` — сервис
# закрывается, это не временный сбой. Держать в составе = гарантированный ❌ в каждом прогоне.
# `omniroute` УБРАН из состава голосов 13.08, но ОСТАЁТСЯ запасным входом (OMNIROUTE_SPARE ниже):
#   1) `auto/*` — лотерея: 6 одинаковых запросов дали big-pickle / felo-chat / hy3-free,
#      и felo на боевом промпте возвращает "...." → пустой голос при HTTP 200;
#   2) его лучшая модель `oc/nemotron-3-ultra-free` ДУБЛИРУЕТ `openrouter` (nemotron-ultra-550B),
#      а рою нужны разные подходы, а не клоны.
# 🔴 18.08: `cerebras` УБРАН из состава голосов — весь его каталог отдаёт 402 Payment required
# (free-tier аккаунта закрыт), а прежняя модель zai-glm-4.7 ещё и архивирована → 404.
# Причина та же, по которой 13.08 убрали github_models: гарантированный ❌ в каждом прогоне.
# Провайдер остаётся в llm_ask (--provider cerebras) — оживёт, если оплатят биллинг.
# Замены подобраны боевым промптом 18.08 (длина ≥200 симв. + кириллица + арифметика):
#   cerebras → groq_qwen (Qwen 3.6 27B, 6.8с) — новое семейство Alibaba на имеющемся ключе Groq
#   or_gemma → or_dots   (Dots3-Note, 8.4с)   — новейшее семейство, 512k ctx, ключ OpenRouter
# GLM восстановить НЕ удалось: zai-glm-5-2 в каталоге Mistral отдаёт 429 Rate limit.
# 🔴 18.08 (добор до 12 ЖИВЫХ): из состава убраны два слота, которые не могли ответить в принципе —
#   `nvidia`   — ключа нет и не будет (build.nvidia.com блокирует регистрацию из РФ);
#   `ag_opus`  — Antigravity отдаёт 429 «All antigravity accounts have…» на ВСЮ линейку Claude
#                (проверены opus-4-6-thinking, sonnet-4-6, gpt-oss-120b-medium). Квота выбрана.
# Оба остаются в llm_ask (`--provider …`) и вернутся в состав, если появится ключ/квота.
# ⚠️ ЧЕСТНАЯ ОГОВОРКА: новых СЕМЕЙСТВ в бесплатном доступе не осталось. Из 16 кандидатов,
# прогнанных боевым промптом, выжили 4, и все — клоны уже представленных в рою.
# Взяты двое с иным РЕЖИМОМ работы (агенты с инструментами), а не просто другой размер:
#   groq_compound   — агентная надстройка Groq, 5.7с
#   ag_gemini_agent — агентный Gemini, единственная модель Antigravity с живой квотой, 27.7с
# Цена: перекос семейств. Gemini теперь ТРИ голоса (gemini · ag_gemini_pro · ag_gemini_agent),
# Groq — ТРИ (groq · groq_qwen · groq_compound). Клоны склонны голосовать согласованно →
# консенсус и Borda-ранг смещаются в их сторону. Читая отчёт роя, считать не голоса, а СЕМЕЙСТВА.
ALL_PROVIDERS = ["mistral", "openrouter", "gemini", "groq",
                 "sambanova", "groq_compound", "ag_gemini_agent",
                 # 13.08: +3 семейства через УЖЕ имеющийся ключ OpenRouter (Cohere/Poolside/Gemma).
                 # Без подписок и новых регистраций — задача Егора «самые сильные и без подписок».
                 "or_cohere", "or_poolside", "or_dots", "groq_qwen",
                 # 13.08: Antigravity OAuth (Google-аккаунт Егора) → Gemini 3.1 Pro и Claude Opus 4.6.
                 # Первые ДЕЙСТВИТЕЛЬНО новые семейства верхнего уровня в рое, и бесплатно.
                 "ag_gemini_pro",
                 # 26.09: ag_opus возвращён — 403/429 были из-за VPN-выхода, который Google считает RU.
                 # Через LLM_PROXY (Сингапур) — 200, боевой промпт 3/3 (79с, самый медленный голос).
                 "ag_opus"]

# Запасной вход через локальный OmniRoute: при 429/503 голос НЕ теряется (13.08).
# Раньше рой звал call_provider напрямую и упавший провайдер просто выпадал из состава —
# так 13.08 потеряли gemini (429 квота) и sambanova (429 high demand) → 5/8 вместо 7/8.
# Модели ФИКСИРОВАННЫЕ, не `auto/*`: шлюз за auto подставляет случайную модель
# (проверено — 6 запросов дали big-pickle / felo-chat / hy3-free), и голос невоспроизводим.
# Из 115 моделей шлюза отвечают только эти четыре (tllm/* → 403, aug/* → 502, ddgw → 418).
# Каждому провайдеру своя запасная — иначе два упавших дали бы один и тот же голос.
# 🔴 felo/* и oc/hy3-free ИСКЛЮЧЕНЫ: на коротком тесте отвечают, на боевом промпте роя
# возвращают "...." / 3 символа при HTTP 200 — формально голос есть, по сути пустой.
# Такой голос ХУЖЕ отказа: он считается как ✅ и врёт статистикой состава.
# Содержательно держит структуру промпта только nemotron-ultra (2963 симв. в прогоне 13.08).
SPARE_MIN_CHARS = 200          # короче — считаем провалом, а не голосом
OMNIROUTE_SPARE = {
    # 13.08: gemini падает по 429 КАЖДЫЙ прогон (квота API исчерпана). Запасной — ТОТ ЖЕ Gemini,
    # но через OAuth-канал Antigravity: другая квота, родное семейство вместо клона nemotron.
    "gemini": "antigravity/gemini-3.6-flash-high",
    "sambanova": "oc/nemotron-3-ultra-free",
    "groq": "oc/nemotron-3-ultra-free",
    "mistral": "oc/nemotron-3-ultra-free",
    # 18.08: cerebras выбыл из состава голосов → его запасной вход убран.
    # groq_qwen делит квоту с `groq`: если Groq упрётся в RPM, оба уйдут на запасной вход,
    # поэтому здесь ДРУГАЯ модель шлюза — иначе два голоса стали бы одним и тем же.
    "groq_qwen": "oc/mimo-v2.5-free",
}

# Бюджет символов на КОНТЕКСТ-блок по провайдеру (входной лимит модели/free-tier).
# Перепроверено 31.05.2026: полный bundle (~101k символов) валит github_models/sambanova/groq.
# Не перечисленные (gemini 1M, cerebras, mistral, openrouter 120B) — переваривают много → DEFAULT.
CONTEXT_BUDGET_CHARS = {
    "github_models": 10_000,   # free tier ~8k токенов на запрос (вход+выход вместе)
    "sambanova": 60_000,       # лимит модели 32k токенов (~2.6 символа/токен на кириллице)
    "groq": 18_000,            # free TPM лимит
    "groq_qwen": 18_000,       # 18.08: тот же ключ и тот же TPM-лимит Groq, что у `groq`
    "groq_compound": 18_000,   # тот же TPM-лимит Groq (третий голос на этом ключе)
    "cerebras": 35_000,        # (вне состава голосов с 18.08 — 402; бюджет оставлен на случай оплаты)
    "deepseek": 600_000,       # 1M ctx (~170k токенов на кириллице) → весь bundle проекта без нарезки
}
DEFAULT_CONTEXT_BUDGET = 200_000

# Выходной лимит токенов по провайдеру.
# github free очень мал → меньше; cerebras GLM-4.7 — тяжёлый reasoner (thinking ест бюджет, но TPM-лимит) → среднее.
OUTPUT_TOKENS = {"github_models": 2000, "cerebras": 6000}
DEFAULT_OUTPUT_TOKENS = 4000

# Маркеры ошибок «запрос/контекст слишком большой» → триггер ужатия контекста и retry.
SIZE_ERR_MARKERS = ("413", "too large", "max_len", "tokens_limit", "tokens_limit_reached",
                    "context_length", "string too long", "maximum context", "context window")


ASK_PROMPT = """Ты — независимый эксперт по торговому боту Oko MTF (BingX, симуляция + live, 24/7).
Тебе дан контекст проекта + ВОПРОС от пользователя.

ТВОЯ ЗАДАЧА: ответить на вопрос пользователя ИСПОЛЬЗУЯ контекст.
Тебя сравнивают с 4-5 другими LLM-моделями. Дай СВОЙ независимый взгляд.

ФОРМАТ ОТВЕТА (markdown, русский, 100-300 строк):

# Ответ: {model_name}

## ⚖️ Главный тезис (1-2 предложения)
Прямой ответ на вопрос. Без воды.

## 🔍 Аргументация (3-5 пунктов)
Каждый пункт:
- Утверждение
- Доказательство из контекста (цитируй конкретные числа, ID задач, даты)

## ⚠️ Что я НЕ знаю / в чём не уверен
Будь честен: где данных мало, где гипотеза, где субъективное мнение.

## 🎯 Конкретные действия (если применимо)
Если вопрос подразумевает «что делать» — top-3 действия с обоснованием.

## 💡 Альтернативная точка зрения
Если возможен другой ответ — упомяни его и почему ты выбрал свой.

ПРАВИЛА:
- Цитируй ID задач (DEV-X, ARCH-Y, TR-Z) и числа из контекста.
- Bullet-points. Без воды.
- Тебе ОК сказать «недостаточно данных» если так.
- Только русский.

ВОПРОС ПОЛЬЗОВАТЕЛЯ:
{question}

КОНТЕКСТ ПРОЕКТА:
{context}
"""


META_ASK_PROMPT = """Ты meta-эксперт. Тебе даны ответы 5 разных LLM на ОДИН вопрос.

ИСХОДНЫЙ ВОПРОС ПОЛЬЗОВАТЕЛЯ:
{question}

ОТВЕТЫ МОДЕЛЕЙ:
{answers_block}

Сделай meta-анализ. ФОРМАТ (markdown, русский, 150-300 строк):

# Meta-Ответ (синтез 5 моделей)

## 🤝 Где модели СОГЛАСНЫ (консенсус)
Утверждения которые поддержали ≥3 моделей.
Формат: утверждение → сколько моделей (X/5) → цитаты.

## ⚔️ Где модели СПОРЯТ
Если есть разные позиции — покажи:
- Позиция A: кто, аргумент
- Позиция B: кто, аргумент
- Твоё мнение: кто ближе к истине и почему

## 🎯 СИНТЕЗ-ОТВЕТ (главное)
Финальный ответ на исходный вопрос на основе консенсуса + лучших аргументов из споров.
Не «среднее арифметическое», а взвешенный синтез.

## 🌟 Лучший уникальный аргумент
Какое замечание есть только у ОДНОЙ модели но оно сильное?

## 📊 Кто ответил лучше всех?
Субъективно: чья аргументация была сильнее. Почему.

ПРАВИЛА:
- Не повторяй контекст.
- Цитируй ID и числа.
- Только русский.
"""


# Stage 2 (по llm-council, karpathy): каждый голос ранжирует АНОНИМНЫЕ ответы остальных.
# Анонимизация (Model A/B/C вместо имён провайдеров) убирает брендовый фаворитизм —
# судья не знает, чей ответ, и не может «играть в любимчиков» (в т.ч. свой собственный).
RANK_PROMPT = """Ты — беспристрастный судья в совете LLM. Ниже {n} АНОНИМНЫХ ответов
(Model A, B, ...) на один вопрос. Кто какой написал — НЕ известно (намеренно, против фаворитизма).
Суди ТОЛЬКО по содержанию.

КРИТЕРИИ: точность (опора на данные/числа/ID, нет выдумок), глубина (неочевидные инсайты),
честность (признаёт неуверенность), польза (конкретные действия).

ВОПРОС:
{question}

АНОНИМНЫЕ ОТВЕТЫ:
{anon_block}

ФОРМАТ (русский, кратко):
## Разбор
2-5 предложений: чьи ответы (по буквам Model X) сильнее/слабее и почему.
## Ранжирование
ПОСЛЕДНЕЙ СТРОКОЙ строго машинно-читаемо, от ЛУЧШЕГО к худшему, через ' > ':
RANKING: A > B > C
"""


# Stage 3 chairman на АНОНИМНЫХ ответах + итог ранга совета (тоже без имён → синтез без перекоса).
META_RANKED_PROMPT = """Ты — председатель (chairman) совета LLM. Даны АНОНИМНЫЕ ответы {n} моделей
на вопрос + итог анонимного перекрёстного ранжирования совета.

ВОПРОС:
{question}

АНОНИМНЫЕ ОТВЕТЫ:
{anon_block}

РАНЖИРОВАНИЕ СОВЕТА (Borda — больше очков = выше оценён коллегами, анонимно):
{ranking_summary}

Синтезируй ФИНАЛ. ФОРМАТ (markdown, русский, 150-300 строк):

# Meta-Ответ (совет {n} моделей + анонимный ранг)

## 🤝 Консенсус
Тезисы, поддержанные ≥половиной. Формат: тезис → сколько моделей.

## ⚔️ Споры
Разные позиции (по буквам Model X): аргументы сторон + кто ближе к истине.

## 🎯 Синтез-ответ
Взвешенный финал. ВЕС выше у ответов с высоким рангом совета. Не среднее — синтез.

## 🌟 Лучший уникальный аргумент
Сильное замечание, которое есть только у одной модели.

ПРАВИЛА: цитируй числа/ID, только русский, ссылайся на ответы по буквам (Model A/B…).
"""


def collect_context() -> str:
    parts = []
    for f in SRC_FILES:
        if f.exists():
            text = f.read_text(encoding="utf-8", errors="replace")
            if len(text) > 60_000:
                text = text[:60_000] + f"\n\n[... обрезано {len(text) - 60_000} символов ...]"
            parts.append(f"\n=== {f.relative_to(PROJECT_ROOT).as_posix()} ===\n{text}\n")
    return "".join(parts) or "[нет контекстных файлов]"


def slugify(text: str, max_len: int = 50) -> str:
    """Превращает вопрос в slug для имени файла."""
    s = re.sub(r"[^\w\s\-а-яА-ЯёЁ]", "", text.lower())
    s = re.sub(r"\s+", "-", s.strip())
    return s[:max_len] or "discussion"


def _trim_context(context: str, budget_chars: int) -> str:
    """Ужимает контекст до budget_chars, сохраняя начало (brief) и хвост (TASKS.md)."""
    if len(context) <= budget_chars:
        return context
    head = int(budget_chars * 0.7)
    tail = budget_chars - head
    cut = len(context) - budget_chars
    return (context[:head]
            + f"\n\n[... вырезано {cut} символов под лимит модели ...]\n\n"
            + context[-tail:])


def get_answer(provider: str, question: str, context: str) -> tuple[str, str, str]:
    """Возвращает (provider, model, text). Не падает — ошибки возвращает в text.
    Контекст ужимается под бюджет провайдера; при size-ошибке бюджет режется вдвое и retry."""
    model = DEFAULT_MODELS.get(provider, "")
    out_tokens = OUTPUT_TOKENS.get(provider, DEFAULT_OUTPUT_TOKENS)
    budget = CONTEXT_BUDGET_CHARS.get(provider, DEFAULT_CONTEXT_BUDGET)
    last_err = ""
    for attempt in range(4):
        ctx = _trim_context(context, budget)
        prompt = ASK_PROMPT.format(
            model_name=f"{provider} ({model})", question=question, context=ctx,
        )
        try:
            text = call_provider(provider, prompt, None, max_tokens=out_tokens, image_path=None)
            # HTTP 200 ≠ ответ: felo/hy3 за шлюзом возвращают "...." / 5 символов.
            # Пустой голос ХУЖЕ отказа — он считается как ✅ и льёт пустоту в синтез.
            if len((text or "").strip()) < SPARE_MIN_CHARS:
                return (provider, model,
                        f"❌ ERROR: пустой ответ ({len((text or '').strip())} симв.)")
            return (provider, model, text)
        except Exception as e:
            last_err = str(e)
            msg = last_err.lower()
            is_size = any(m in msg for m in SIZE_ERR_MARKERS)
            if is_size and attempt < 3 and budget > 4_000:
                budget = max(4_000, budget // 2)
                print(f"[team-ask] {provider}: size-error → ужимаю контекст до {budget} симв. "
                      f"(попытка {attempt + 2}/4)", file=sys.stderr)
                continue
            # 429/503 — провайдер жив, но занят. Не теряем голос: берём запасной вход
            # через локальный OmniRoute с фиксированной моделью.
            spare = OMNIROUTE_SPARE.get(provider)
            is_busy = any(m in msg for m in ("429", "503", "rate limit", "quota",
                                             "resource_exhausted", "high demand"))
            if spare and is_busy:
                try:
                    text = call_provider("omniroute", prompt, spare,
                                         max_tokens=out_tokens, image_path=None)
                    if len((text or "").strip()) < SPARE_MIN_CHARS:
                        raise RuntimeError(
                            f"запасной вернул {len((text or '').strip())} симв. — пустой голос")
                    print(f"[team-ask] {provider}: занят → запасной {spare}", file=sys.stderr)
                    return (provider, f"{model} → {spare}", text)
                except Exception as e2:
                    print(f"[team-ask] {provider}: запасной {spare} тоже упал ({str(e2)[:80]})",
                          file=sys.stderr)
            return (provider, model, f"❌ ERROR: {last_err[:500]}")
    return (provider, model, f"❌ ERROR: не уложился в лимит контекста. {last_err[:300]}")


def anonymize(good: list, rng) -> tuple[dict, str]:
    """good: list[(provider, model, text)] без ошибок → (label_map, anon_block).
    label_map: {'A': (provider, model, text), ...} в ПЕРЕМЕШАННОМ порядке (буква не выдаёт провайдера)."""
    shuffled = list(good)
    rng.shuffle(shuffled)
    label_map = {chr(ord("A") + i): trip for i, trip in enumerate(shuffled)}
    anon_block = "\n\n".join(
        f"### Model {lab}\n{t[:3500]}" for lab, (_p, _m, t) in label_map.items()
    )
    return label_map, anon_block


def parse_ranking(text: str, valid_labels: set) -> list:
    """Из ответа судьи достаёт 'RANKING: A > B > C' → ['A','B','C']. Фоллбэк: буквы по всему тексту."""
    m = re.search(r"RANKING:\s*([A-Z][A-Z\s,>\.\-]*)", text)
    seq = m.group(1) if m else text
    order: list[str] = []
    for ch in re.findall(r"[A-Z]", seq):
        if ch in valid_labels and ch not in order:
            order.append(ch)
    return order


def get_ranking(provider: str, question: str, anon_block: str, n: int, valid_labels: set) -> tuple:
    """Судья ранжирует анонимные ответы. → (provider, text, order). Не падает."""
    prompt = RANK_PROMPT.format(n=n, question=question, anon_block=anon_block)
    try:
        text = call_provider(provider, prompt, None, max_tokens=1500, image_path=None)
    except Exception as e:
        return (provider, f"❌ ERROR: {str(e)[:300]}", [])
    return (provider, text, parse_ranking(text, valid_labels))


def aggregate_rankings(rankings: list, label_map: dict) -> list:
    """Borda: позиция i (0=лучший) в ранге судьи → (N-1-i) очков, сумма по судьям.
    → leaderboard list[(label, provider, model, score, n_votes)] по убыванию очков."""
    n = len(label_map)
    score = {lab: 0 for lab in label_map}
    votes = {lab: 0 for lab in label_map}
    for _p, _t, order in rankings:
        for i, lab in enumerate(order):
            if lab in score:
                score[lab] += (n - 1 - i)
                votes[lab] += 1
    board = [(lab, p, m, score[lab], votes[lab]) for lab, (p, m, _t) in label_map.items()]
    board.sort(key=lambda x: x[3], reverse=True)
    return board


def main() -> int:
    parser = argparse.ArgumentParser(description="Командное обсуждение свободного вопроса")
    parser.add_argument("question", help="Твой вопрос команде")
    parser.add_argument("--file", type=Path, help="Доп. файл с контекстом (добавится к bundle)")
    parser.add_argument("--providers", help="Список через запятую (по умолчанию все доступные)")
    parser.add_argument("--no-context", action="store_true", help="Без bundle проекта (только вопрос)")
    parser.add_argument("--skip-meta", action="store_true", help="Без финального meta-синтеза")
    parser.add_argument("--skip-rank", action="store_true", help="Без анонимного peer-ranking (Stage 2)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    load_env()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # Провайдеры
    if args.providers:
        providers = [p.strip() for p in args.providers.split(",")]
    else:
        providers = [p for p in ALL_PROVIDERS if has_key(p)]

    if len(providers) < 2:
        print(f"[team-ask] недостаточно провайдеров: {providers}", file=sys.stderr)
        return 1

    print(f"[team-ask] участники: {', '.join(providers)}", file=sys.stderr)
    print(f"[team-ask] вопрос: {args.question[:100]}", file=sys.stderr)

    # 18.08: шлюз нужен ТОЛЬКО на прогон (ag_* голоса + запасные входы при 429), поэтому
    # он больше не висит под pm2 круглосуточно на 350 MB. Поднимаем сами, если молчит.
    # atexit, а не try/finally: гасим и при исключении, и при sys.exit, без переиндентации main.
    # stop_gateway вызовется ТОЛЬКО если шлюз подняли мы — чужой (pm2/ручной) не трогаем.
    gw = ensure_gateway()
    if gw is not None:
        import atexit
        atexit.register(stop_gateway, gw)

    # Контекст
    context_parts = []
    if not args.no_context:
        context_parts.append(collect_context())
    if args.file:
        if not args.file.exists():
            print(f"[team-ask] ERROR: файл не найден: {args.file}", file=sys.stderr)
            return 1
        extra = args.file.read_text(encoding="utf-8", errors="replace")
        context_parts.append(f"\n=== ДОП. ФАЙЛ: {args.file.name} ===\n{extra}\n")
    context = "".join(context_parts) or "[без контекста]"

    in_chars = len(context) + len(args.question)
    print(f"[team-ask] контекст: {in_chars} символов (~{int(in_chars/3.5)} токенов)",
          file=sys.stderr)

    # Параллельный запуск
    results: list[tuple[str, str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers)) as ex:
        futures = {}
        for p in providers:
            futures[ex.submit(get_answer, p, args.question, context)] = p

        for fut in concurrent.futures.as_completed(futures):
            provider, model, text = fut.result()
            results.append((provider, model, text))
            preview = text[:120].replace("\n", " ")
            print(f"[team-ask] ✓ {provider} ({model}): {preview}...", file=sys.stderr)

    # Сборка отчёта
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = slugify(args.question)
    OUTPUT_OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
    out_obsidian = OUTPUT_OBSIDIAN_DIR / f"{today}-{slug}.md"

    sections = []
    sections.append(
        "---\n"
        "tags: [discussion, team, ask, auto]\n"
        "type: team-discussion\n"
        f"date: {today}\n"
        f"providers: [{', '.join(p for p, _, _ in results)}]\n"
        'parent: "[[Project-MOC]]"\n'
        "---\n\n"
        f"# Команда обсуждает: «{args.question}»\n\n"
        f"> Дата: {today} • Провайдеров: {len(results)} • Контекст: {in_chars // 1024}K символов.\n\n"
        f"## ❓ Исходный вопрос\n\n{args.question}\n\n---\n"
    )

    for provider, model, text in sorted(results):
        sections.append(f"\n# 🤖 {provider.upper()} — `{model}`\n\n{text}\n\n---\n")

    # ─── Stage 2: анонимный peer-ranking (llm-council) + Stage 3: meta-синтез ───
    good = [r for r in results if not r[2].startswith("❌")]
    label_map: dict = {}
    leaderboard: list = []
    anon_block = ""

    # Stage 2 — каждый голос ранжирует АНОНИМНЫЕ ответы (нужно ≥3, иначе ранг тривиален)
    if not args.skip_rank and len(good) >= 3:
        rng = random.Random(42)  # детерминированная анонимизация → воспроизводимый отчёт
        label_map, anon_block = anonymize(good, rng)
        valid_labels = set(label_map)
        n = len(label_map)
        rankers = [p for p, _m, _t in good]  # судят все, кто ответил (на анон-наборе, включая свой)
        print(f"[team-ask] анонимный peer-ranking ({len(rankers)} судей)...", file=sys.stderr)
        rankings: list = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(rankers)) as ex:
            rfuts = {ex.submit(get_ranking, p, args.question, anon_block, n, valid_labels): p
                     for p in rankers}
            for fut in concurrent.futures.as_completed(rfuts):
                rankings.append(fut.result())
        leaderboard = aggregate_rankings(rankings, label_map)

        # Отчёт: leaderboard (раскрываем имена) + вердикты судей (ответы по буквам)
        lb = ["\n# 🏆 PEER-RANKING (анонимный, Borda)\n",
              "| # | Ответ | Провайдер | Очки | Голосов |",
              "|---|---|---|---|---|"]
        for rank, (lab, p, m, sc, vt) in enumerate(leaderboard, 1):
            lb.append(f"| {rank} | Model {lab} | {p} (`{m}`) | {sc} | {vt} |")
        lb.append("\n> Судьи видели ответы как Model A/B/C без имён (анти-фаворитизм).\n")
        sections.append("\n".join(lb))
        for p, t, order in sorted(rankings, key=lambda x: x[0]):
            seq = " > ".join(order) if order else "—"
            sections.append(f"\n## ⚖️ Судья {p}: `{seq}`\n\n{t}\n")

    # Stage 3 — chairman/meta-синтез
    if not args.skip_meta and len(good) >= 2:
        if leaderboard:  # есть ранг → анонимный взвешенный синтез (без брендового перекоса)
            ranking_summary = "\n".join(
                f"Model {lab}: {sc} очк. ({vt} голосов судей)"
                for lab, _p, _m, sc, vt in leaderboard
            )
            meta_prompt = META_RANKED_PROMPT.format(
                n=len(label_map), question=args.question,
                anon_block=anon_block, ranking_summary=ranking_summary,
            )
        else:  # фоллбэк: старый именованный синтез (--skip-rank или <3 голосов)
            answers_block = "\n\n".join(
                f"### {p} ({m})\n{t[:6000]}" for p, m, t in sorted(good)
            )
            meta_prompt = META_ASK_PROMPT.format(
                question=args.question, answers_block=answers_block,
            )
        # ФОЛБЭК: ранг съедает free-tier бюджет (×2 вызовов) → meta часто ловит 429.
        # Пробуем мета-провайдеров по очереди, пока один не ответит.
        meta_candidates = [p for p in ["mistral", "openrouter", "gemini", "groq"]
                           if p in [r[0] for r in good]]
        meta_done = False
        for meta_provider in meta_candidates:
            print(f"[team-ask] meta-синтез через {meta_provider}...", file=sys.stderr)
            try:
                meta_text = call_provider(
                    meta_provider, meta_prompt, None, max_tokens=6000, image_path=None,
                )
                if label_map:  # раскрываем буквы → провайдеры в подвале синтеза
                    legend = " · ".join(f"Model {lab}={p}" for lab, (p, _m, _t) in label_map.items())
                    meta_text += f"\n\n---\n*Расшифровка меток: {legend}*"
                sections.append(f"\n# 🧠 META-СИНТЕЗ (через {meta_provider})\n\n{meta_text}\n")
                meta_done = True
                break
            except Exception as e:
                print(f"[team-ask] meta {meta_provider} failed: {str(e)[:80]} → fallback",
                      file=sys.stderr)
        if not meta_done:
            sections.append("\n# 🧠 META-СИНТЕЗ\n\n❌ Все meta-провайдеры недоступны (rate-limit?). "
                            "Ответы моделей + ранг выше валидны.\n")

    out_obsidian.write_text("".join(sections), encoding="utf-8")
    OUTPUT_MEMORY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MEMORY.write_text("".join(sections), encoding="utf-8")

    if args.quiet:
        print(f"[team-ask] OK n={len(results)} -> {out_obsidian}", file=sys.stderr)
    else:
        ok = sum(1 for _, _, t in results if not t.startswith("❌"))
        print(f"\n[team-ask] OK: {ok}/{len(results)} провайдеров ответили")
        for p, m, t in sorted(results):
            mark = "❌" if t.startswith("❌") else "✅"
            print(f"  {mark} {p:15s} ({m})")
        print(f"\n  -> {out_obsidian}")
        print(f"  -> {OUTPUT_MEMORY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
