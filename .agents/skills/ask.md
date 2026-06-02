---
name: ask
description: Спросить одну внешнюю LLM с auto-routing. АКТИВИРУЙ на "/ask", "спроси LLM", "ask llm", "задай вопрос модели". Аргумент — вопрос [--file path] [--image path] [--provider X] [--reasoning].
---

# Ask — один LLM (auto-routing)

Запусти: `python tools/llm_ask.py "<вопрос>" [флаги]`

Auto-routing провайдеров:
- `--image` → Gemini (multimodal)
- `--file` >200k токенов → Mistral; >100k → Gemini (1M ctx)
- `--reasoning` → OpenRouter/DeepSeek reasoning
- по умолчанию → Cerebras / Groq (быстро)

Покажи ответ. Это быстрая справка одним LLM (не рой).
