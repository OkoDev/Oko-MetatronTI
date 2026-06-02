---
name: llm-keys
description: Показать статус LLM-провайдеров (какие ключи загружены). АКТИВИРУЙ на "/llm-keys", "статус ключей", "llm keys", "какие провайдеры доступны".
---

# LLM-Keys — статус провайдеров

Запусти: `python tools/llm_ask.py --list-keys "x"`

Покажи результат as-is. Недоступные провайдеры — упомяни где получить ключ:
cerebras (cloud.cerebras.ai), mistral (console.mistral.ai), openrouter (openrouter.ai), gemini (aistudio.google.com), groq (console.groq.com), github_models (github PAT models:read), sambanova (cloud.sambanova.ai), deepseek (platform.deepseek.com — дирижёр роя).
