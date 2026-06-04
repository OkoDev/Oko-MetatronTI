---
name: llm-swarm-config
description: "Конфигурация роя LLM (tools/llm_ask.py + team_ask.py), free-провайдеры/модели и факт об отсутствии бесплатного Claude API"
metadata: 
  node_type: memory
  type: reference
  originSessionId: c30a06fd-6559-4f80-90a7-0cffea62483e
---

Рой LLM проекта — `tools/llm_ask.py` (DEFAULT_MODELS / REASONING_MODELS / ENV_KEYS) + `tools/team_ask.py` (ALL_PROVIDERS, фильтрует по has_key).

**Активные дефолты (проверено живьём 30.05.2026):**
- groq → `openai/gpt-oss-120b`
- cerebras → `zai-glm-4.7` (Cerebras отдаёт ТОЛЬКО gpt-oss-120b + zai-glm-4.7; qwen-3-235b удалён → 404)
- gemini → `gemini-3.5-flash` (есть и gemini-3.1/3-preview)
- mistral → `magistral-medium-latest`
- openrouter → `nvidia/nemotron-3-super-120b-a12b:free` (единственный стабильный free; deepseek-v4/minimax-m2.5/kimi-k2.6/qwen3-next часто 429/503 upstream)
- github_models → `openai/gpt-4.1-mini` (list-эндпоинт 404, но конкретные ID работают; есть deepseek/DeepSeek-R1, gpt-4o)

**Новые провайдеры:**
- sambanova → `https://api.sambanova.ai/v1`, `SAMBANOVA_API_KEY` — ✅ **АКТИВЕН (ключ в .env с 31.05.2026)**. Дефолт `DeepSeek-V3.2`. Free-каталог: DeepSeek-V3.1/V3.2, Llama-4-Maverick-17B, Meta-Llama-3.3-70B, gemma-3/4, gpt-oss-120b. ⚠️ DeepSeek-R1 и MiniMax-M2.7 — ПЛАТНЫЕ (402).
- nvidia NIM → `https://integrate.api.nvidia.com/v1`, `NVIDIA_API_KEY` — ⚠️ **недоступен из РФ** (build.nvidia.com блокирует регистрацию по +7). Scaffolding есть, без ключа неактивен, модель не проверена.

**Рой = 7 активных голосов** (groq, cerebras, gemini, mistral, openrouter, github_models, sambanova) + nvidia в резерве.

**🔴 Свободного Claude (Opus/Sonnet) для API НЕТ** (на 30.05.2026): OpenRouter free его не отдаёт, GitHub Models inference тоже (Claude доступен только как Copilot coding-agent на github.com, не через API, и с марта 2026 убран из self-select на free/student). Ближайшие бесплатные аналоги Opus-класса для reasoning — **DeepSeek-R1**, GLM-4.7, Nemotron-3 Super 120B.

**Грабли:** reasoning-модели (DeepSeek-R1) вшивают `<think>...</think>` прямо в текст ответа → в ask_openai_compat есть срез по `</think>`. Reasoning-модель при низком max_tokens возвращает content=None (всё ушло в thinking) → нужен max_tokens ≥ ~800.

**DeepSeek платный (api.deepseek.com, ключ DEEPSEEK_API_KEY в .env) — дирижёр роя (ARCH-126):** спеки 02.06.2026:
- Модели: `deepseek-chat` = **v4-flash** (non-thinking, наш дефолт, concurrency 2500), `deepseek-reasoner` = thinking-режим. Тир `v4-pro` ×3 дороже (concurrency 500) — для критичного синтеза.
- Контекст **1M**, max output **384K** → дирижёру нарезка контекста НЕ нужна (только мелким моделям роя).
- 🔥 **Кэш промпта = ×50:** input cache-hit **$0.0028**/1M vs cache-miss **$0.14**/1M (output $0.28/1M). Часовой брифинг шлёт почти один контекст → кэширование статичного префикса (project bundle) почти обнуляет стоимость. Оптимизация на DS-стороне (swarm_orchestrator).
- Реальная стоимость одного DS-брифинга (2 запроса, 11425 токенов) = **¥0.01** (~$0.0014). Часовой цикл ≈ копейки/месяц.
- Есть **Anthropic-format** эндпоинт `https://api.deepseek.com/anthropic` (на будущее).
- Экономика подтвердила высоту B+C: глобальный брифинг 1/цикл vs per-pair ×240 = разница в сотни раз. → [[arch125-metatron-kernel]]
