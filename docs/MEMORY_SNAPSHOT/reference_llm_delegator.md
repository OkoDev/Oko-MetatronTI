---
name: reference-llm-delegator
description: "CLI `tools/llm_ask.py` — делегация задач во внешние LLM (Groq, Gemini) для экономии контекста Claude"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 5125b728-fb4c-47f5-b019-176f112b7ee3
---

# LLM-делегатор для разгрузки контекста

**Путь:** `tools/llm_ask.py`

## Когда использовать

Делегировать в Groq/Gemini рутинные задачи которые жгут много токенов в моём контексте:
- Резюме длинных файлов/логов (>3k токенов в файле)
- Парсинг JSON/CSV → выжимка
- Парсинг chart/PDF/screenshot → описание
- Перевод/форматирование текста
- Генерация commit-сообщения по большому diff

**НЕ делегировать:**
- Архитектурные решения (нужен глубокий контекст проекта)
- Code review с пониманием Куба Метатрона
- Debugging текущей сессии

## Как вызывать

```bash
PYTHON=C:/Users/yogoru/AppData/Local/Programs/Python/Python312/python.exe

# Простой вопрос (auto → groq)
$PYTHON tools/llm_ask.py "вопрос"

# Резюмировать файл (auto: >100k → gemini, иначе groq)
$PYTHON tools/llm_ask.py "резюмируй в 5 строк" --file path/to/file.md

# Большой файл → принудительно gemini
$PYTHON tools/llm_ask.py "выжимка" --file big.log --provider gemini

# Картинка/график → gemini
$PYTHON tools/llm_ask.py "опиши паттерн" --image chart.png

# Запись ответа в файл (вместо stdout — экономит мой контекст)
$PYTHON tools/llm_ask.py "..." --file X.md --out e:/tmp/summary.md
# → потом я читаю только summary.md
```

## Провайдеры и ключи

**Ключи в `.env` (за .gitignore):**
- `GROQ_API_KEY` — workhorse, ~100k токенов/день free
- `GEMINI_API_KEY` — для больших файлов и картинок

**Дефолтные модели (6 провайдеров, auto-fallback при 429/503):**
- groq: `llama-3.3-70b-versatile` (14 400 RPD, 100k TPD)
- cerebras: `gpt-oss-120b` (14 400 RPD, в 4-10× быстрее Groq)
- gemini: `gemini-2.5-flash` (20 RPD на free, 1M context, multimodal)
- mistral: `mistral-large-latest` (1B токенов/мес)
- openrouter: `nvidia/nemotron-3-super-120b-a12b:free` (50 RPD, доступ к 24+ free моделям)
- github_models: `openai/gpt-4o-mini` (требует scope `models:read` в PAT)

**Fallback-цепочка:** cerebras → groq → openrouter → mistral → github_models → gemini.
Если первый упал на 429/503 — автоматом следующий с доступным ключом.

**Спецфлаги:**
- `--reasoning` → openrouter `arcee-ai/trinity-large-thinking:free` (или fallback cerebras qwen-3-235b)
- `--list-keys` → показать какие из 6 ключей загружены
- `--no-fallback` → строго один провайдер

**Доступные Gemini модели в free tier:** `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-2.5-flash-lite`. Проверить список: `from google import genai; list(genai.Client(api_key=...).models.list())`.

## Лимиты

- **Groq free**: 100k токенов/день TPD, 30 RPM на Llama 3.3 70B
- **Gemini free**: зависит от модели, 1500 req/day на `gemini-2.5-flash`

**Шаринг с ботом:** Groq-ключ также жёт `core/trading/trade_analyzer.py` (DEV-151). Дневной лимит делится. Если упёрся в TPD на Groq — переключаюсь на Gemini.

## Pattern экономии

Без делегатора: я делаю `Read big_file.md` → +47k токенов в моём контексте.

С делегатором:
```bash
$PYTHON tools/llm_ask.py "выжимка" --file big_file.md --out e:/tmp/sum.md
# stderr: [llm_ask] provider=gemini ~in=47540 ~out=217
```
→ читаю только `e:/tmp/sum.md` (~200-500 токенов). **Экономия 95%+ контекста на одну задачу.**

## Связанная feedback-memory
- [[feedback-bash-auto]] — bash выполнять без подтверждения, делегирование через Bash тоже автоматом.
