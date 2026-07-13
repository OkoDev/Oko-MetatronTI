# DeepSeek Local LLM → Oko MTF: архитектура интеграции

> **Старший AI-архитектор** | 11.06.2026
> Проект: Oko MTF (Куб Метатрона). Биржа: BingX VST. Стек: Python 3.12, aiogram, aiohttp.
> Оборудование: 2× GPU (GTX 1080 8GB + GTX 1070 8GB = 16 GB VRAM).

---

## 1. Выбор модели и системные требования

### 1.1 Матрица моделей под 16 GB VRAM

| Модель | Параметры | Q4_K_M VRAM | Q5_K_M VRAM | Скорость* | Качество** |
|---|---|---|---|---|---|
| **DeepSeek-R1-Distill-Llama-8B** | 8B | ~5.5 GB | ~6.5 GB | 45-55 t/s | ★★★★ |
| **DeepSeek-R1:14b** | 14B | ~8.5 GB | ~10 GB | 20-35 t/s | ★★★★★ |
| **DeepSeek-Coder-V2:16b** | 16B | ~9.5 GB | ~11.5 GB | 18-30 t/s | ★★★★★ |
| **DeepSeek-V3-Lite** | ~20B | ~12 GB | ~14 GB | 12-20 t/s | ★★★★★ |
| DeepSeek-R1-Distill-Qwen-32B | 32B | ~19 GB | ~22 GB | 5-8 t/s | ★★★★★★ |

> *Скорость на 2×GPU (1080+1070) через llama.cpp CUDA-сплит. t/s = токенов/сек.
> **Качество рассуждений относительно задачи «анализ трейда + генерация паттернов».

### 1.2 Рекомендация: двухмодельная архитектура

```
┌─────────────────────────────────────────┐
│  GPU 0 (GTX 1080, 8 GB)                 │
│  DeepSeek-R1:14b Q5_K_M (~10 GB)        │
│  → Тактик / Стратег / Архивариус        │
│  → CoT-рассуждения, глубокий анализ     │
├─────────────────────────────────────────┤
│  GPU 1 (GTX 1070, 8 GB)                 │
│  DeepSeek-Coder-V2:16b Q4_K_M (~9.5 GB) │
│  → Быстрый анализ, кодогенерация        │
│  → Интерактивные запросы (15-20 сек)    │
└─────────────────────────────────────────┘
```

**Почему не одна модель на двух картах:**
- Сплит слоёв между GPU с разной скоростью (1080 > 1070) создаёт bottleneck — 1070 тормозит всю цепочку
- Две независимые модели на разных картах = нет ожидания, параллельная обработка
- R1 для CoT, Coder-V2 для быстрых задач — разделение по latency-профилю

### 1.3 Квантование: Q5_K_M как стандарт

| Формат | VRAM R1:14b | Качество vs FP16 | Скорость | Вердикт |
|---|---|---|---|---|
| Q4_K_M | ~8.5 GB | −2-4% точности | Макс. | Эконом. Для 8 GB карт |
| **Q5_K_M** | **~10 GB** | **−1-2%** | **Высокая** | **Золотая середина ★** |
| Q6_K | ~13 GB | −0.5-1% | Средняя | На 2×GPU ок, но мало места под контекст |
| Q8_0 | ~15 GB | −0-0.5% | Низкая | Весь VRAM съеден, контекст не влезет |
| EXL2 4.5bpw | ~9.5 GB | −1-2% | Высокая | Только для GPTQ-совместимых движков |

**Выбор: Q5_K_M через llama.cpp (Ollama).** EXL2 (TabbyAPI) быстрее на 10-15%, но сложнее в настройке и не поддерживает все модели DeepSeek. Для первой итерации — Ollama.

### 1.4 Движки инференса

| Движок | Пропускная способность | API | DeepSeek-R1 | Сплит GPU | Сложность |
|---|---|---|---|---|---|
| **Ollama** | ★★★ | REST (порт 11434) | ✅ | Авто | Минимальная |
| **llama.cpp** | ★★★★ | C++ / Python bindings | ✅ | Ручной `-ngl` | Средняя |
| **vLLM** | ★★★★★ | OpenAI-compatible | ⚠️ частично | Тензорный параллелизм | Высокая |
| **TensorRT-LLM** | ★★★★★ | Triton / C++ | ❌ (NVIDIA-only оптимизации) | Нативный | Максимальная |
| **TabbyAPI (exllamav2)** | ★★★★ | OpenAI-compatible | ⚠️ не все кванты | Через exllamav2 | Средняя |

**Рекомендация: Ollama для старта → llama.cpp для продакшена.**

Ollama даёт: авто-сплит GPU, REST API, встроенное кэширование промптов, совместимость с `openai` Python-клиентом. Проект УЖЕ использует Ollama в `trade_analyzer.py`.

Переход на llama.cpp (через `llama-cpp-python`) когда нужна максимальная скорость: прямой доступ к тензорам, батчинг, кастомный KV-кэш.

---

## 2. Сценарии применения

### 2.1 Что делегировать LLM ✅

#### Тактик (каждые 1-2 часа, R1:14b)
```python
ВХОД: пакет из 20-40 закрытых сделок + features_json + рыночный контекст
ЗАДАЧА: найти аномалии и предложить точечные улучшения
ВЫХОД: JSON {"insights": [{"type": "anomaly", "signal": "ote_nested",
        "finding": "3/4 SHORT SL при ema50>ema200. Предложен gate.",
        "suggested_gate": {...}, "expected_impact_r": 0.4}]}
```
**Латентность:** 30-60 сек. Не блокирует торговлю — результат публикуется в Bus асинхронно.

#### Стратег (каждые 4-6 часов, R1:14b)
```python
ВХОД: статистика стратегий за 6ч × рыночные фазы × фичи снимка
ЗАДАЧА: сравнить стратегии, найти новые комбо-паттерны
ВЫХОД: "wt_sideways SHORT в RANGE + wt_os_4h даёт avgR +0.7 (n=15).
       Проверить на 50+ сделках. Предложить как DS-паттерн."
```
**Латентность:** 60-120 сек. Ночью или в периоды низкой волатильности.

#### Архивариус (раз в сутки, R1:14b)
```python
ВХОД: ВСЕ сделки за 24ч + PIVOT-CONTEXT + волновые фазы
ЗАДАЧА: дрейф рынка, деградация паттернов, глобальные тренды
ВЫХОД: отчёт «что изменилось за неделю, какие паттерны умирают»
```

#### Быстрый аналитик (интерактивно, Coder-V2:16b)
```python
ВХОД: вопрос трейдера + контекст из памяти проекта
ЗАДАЧА: ответить на вопрос, найти причину
ВЫХОД: текстовый ответ
```
**Латентность:** 15-25 сек. Через `scripts/ds_r1_analyzer.py`.

#### Генератор сигналов (Coder-V2:16b)
```python
ВХОД: описание нового индикатора на естественном языке
ЗАДАЧА: сгенерировать Python-код индикатора
ВЫХОД: валидный Python с импортами и тестовым примером
```

### 2.2 Что НЕ делегировать LLM ❌

| Задача | Почему нельзя | Кто делает |
|---|---|---|
| **Генерация ордеров** | Галлюцинация = потеря денег. Нет гарантий валидности | `order_manager.py` |
| **Расчёт SL/TP** | LLM не умеет считать ATR/уровни точнее чем код | `sl_tp_engine.py` |
| **Регистрация сделок** | INSERT в БД должен быть детерминированным | `register_trade()` |
| **Исполнение на бирже** | API-ключи никогда не покидают ядро | `bingx_client.py` |
| **Gate-решения в реальном времени** | >500 мс latency = просроченный сигнал | `gates/` модули |

### 2.3 Принцип Air-Gap

```
┌─────────────────────────────┐     ┌──────────────────────┐
│  ЯДРО БОТА                  │     │  AI-СФЕРА            │
│  (API-ключи, ордера, БД)   │────▶│  (R1 + Coder-V2)     │
│                             │     │                      │
│  Посылает:                  │     │  Получает:            │
│  - агрегированную статистику│     │  - обезличенные данные│
│  - features_json (без ключей)│    │  - только R-метрики   │
│                             │     │                      │
│  Получает:                  │     │  Отвечает:            │
│  - инсайты, паттерны        │◀────│  - JSON-отчёты        │
│  - рекомендации             │     │  - без цен/ордеров    │
│                             │     │                      │
│  Валидирует перед применением│    │  НЕТ доступа к:       │
│  - schema check              │     │  - API-ключам        │
│  - gate logic                │     │  - БД                │
│  - НЕ автоприменяет          │     │  - бирже             │
└─────────────────────────────┘     └──────────────────────┘
```

---

## 3. Архитектура интеграции

### 3.1 Сфера AI-Аналитик в Кубе Метатрона

```
                    Shared Context Bus
                    ┌───────┴───────┐
                    │               │
              ┌─────▼─────┐  ┌──────▼──────┐
              │ Сфера 1-13│  │ Сфера N     │
              │ (боевые)  │  │ AI-Аналитик │
              └───────────┘  └──────┬──────┘
                                    │
                          ┌─────────┴─────────┐
                          │                   │
                    ┌─────▼─────┐      ┌──────▼──────┐
                    │ R1:14b    │      │ Coder-V2:16b│
                    │ (CoT)     │      │ (fast)      │
                    │ GPU 0     │      │ GPU 1       │
                    └─────┬─────┘      └──────┬──────┘
                          │                   │
                    Тактик/Стратег       Быстрый анализ
                    Архивариус           Генерация кода
```

### 3.2 Поток данных

```python
# core/intelligence/ai_analyst.py (новая сфера)

class AIAnalystSphere:
    """
    Сфера AI-Аналитик. Отдельный процесс или asyncio-task.
    НЕ блокирует scan_loop. Публикует инсайты в Shared Context Bus.
    """
    
    def __init__(self, bus, db_path, ollama_url="http://localhost:11434"):
        self.bus = bus
        self.db = db_path
        self.ollama = ollama_url
        self.r1_model = "deepseek-r1:14b"
        self.fast_model = "deepseek-coder-v2:16b"
    
    async def tactical_cycle(self):
        """Тактик: каждые 1-2 часа"""
        closed = self._fetch_closed_since(hours=2)
        context = self._build_context(closed, mode="tactical")
        insight = await self._call_llm(self.r1_model, context)
        if self._validate_insight(insight):
            self.bus.publish("ai_insight", insight)
    
    async def strategic_cycle(self):
        """Стратег: каждые 6 часов"""
        stats = self._fetch_strategy_stats(hours=6)
        context = self._build_context(stats, mode="strategic")
        report = await self._call_llm(self.r1_model, context)
        self.bus.publish("ai_strategy_report", report)
    
    async def quick_ask(self, question: str) -> str:
        """Быстрый вопрос → Coder-V2"""
        context = build_project_context(question)  # RAG
        return await self._call_llm(self.fast_model, context + question)
```

### 3.3 Промптинг: JSON-контракт

```python
TACTICAL_PROMPT = """Ты — AI-аналитик торгового бота Oko MTF.

КОНТЕКСТ:
{context}

ЗАДАЧА: Найди аномалии, слабые паттерны, предложи улучшения.

ФОРМАТ ОТВЕТА — СТРОГО JSON. Без текста вне JSON:
```json
{{
  "period": "{period}",
  "market_phase": "TREND_UP|TREND_DOWN|RANGE",
  "insights": [
    {{
      "severity": "critical|warning|info",
      "signal_type": "ote_nested|arch104|pivot_reversal|...",
      "finding": "конкретная находка с цифрами",
      "evidence": {{"n": 12, "bad_n": 4, "bad_avgR": -1.2}},
      "root_cause": "причина",
      "suggestion": "что делать",
      "expected_impact_r": 0.4
    }}
  ],
  "new_patterns_found": [
    {{
      "description": "комбинация условий",
      "n_observed": 8,
      "avgR": 1.5,
      "confidence": "low|medium|high"
    }}
  ],
  "dying_patterns": ["список паттернов с падающим avgR"],
  "summary": "1-2 предложения"
}}
```

ВАЛИДАЦИЯ ОТВЕТА:
- Все avgR/n/expected_impact_r — числа, не строки
- severity ∈ {critical, warning, info}
- confidence ∈ {low, medium, high}
"""
```

### 3.4 RAG-слой: память проекта

```python
# Упрощённый RAG без векторной БД (для 14B модели достаточно)
PROJECT_MEMORY = {
    "architecture": "docs/ENCYCLOPEDIA.md",      # Куб, сферы, Bus
    "current_state": "memory/session_brief.md",   # последняя сессия
    "trade_review": "memory/last_trade_review.md",# статистика сделок
    "tasks": "TASKS.md",                          # активные задачи
    "discussion": "DISCUSSION.md",                # диалог агентов
    "patterns": "config/arch104_patterns.yaml",   # активные паттерны
}

def build_context(question: str, mode: str, db_path: str) -> str:
    """Собирает релевантный контекст под вопрос."""
    parts = []
    
    # 1. Память проекта (первые 200 строк ключевых файлов)
    for name, path in PROJECT_MEMORY.items():
        parts.append(f"=== {name} ===\n{read_head(path, 200)}")
    
    # 2. Данные из БД (авто-SQL по ключевым словам)
    parts.append(f"=== БД: статистика ===\n{query_stats(db_path, mode)}")
    
    # 3. Правила
    parts.append(SYSTEM_RULES)
    
    return "\n\n".join(parts)[:18000]  # ~6K токенов для R1
```

### 3.5 Валидация ответа LLM перед применением

```python
def validate_insight(insight: dict) -> bool:
    """Жёсткая валидация. Ни один инсайт не применяется без проверки."""
    required = ["severity", "signal_type", "finding", "evidence", "suggestion"]
    
    # Schema check
    if not all(k in insight for k in required):
        return False
    
    # Типы данных
    if not isinstance(insight.get("evidence", {}).get("n"), (int, float)):
        return False
    if insight["severity"] not in ("critical", "warning", "info"):
        return False
    
    # Санкционированные signal_type
    valid_signals = {"ote_nested", "arch104", "pivot_reversal", "wt_signal",
                     "wt_sideways", "divergence", "confluence", "wt_b_signal",
                     "liquidity_sweep", "atr_change", "watch_list_breach"}
    if insight["signal_type"] not in valid_signals:
        return False
    
    # Не даём LLM менять gates напрямую
    if "gate" in str(insight.get("suggestion", "")).lower():
        insight["requires_claude_approval"] = True
    
    return True
```

---

## 4. Задержки и производительность

### 4.1 LLM latency vs Trading Timeframes

| Стратегия | Цикл | Допустимая задержка | LLM fit |
|---|---|---|---|
| Скальпинг (1m/3m) | 5-60 сек | <500 мс | ❌ Несовместимо |
| Интрадей (15m) | 15 мин | <60 сек | 🟡 Только Coder-V2 (15 сек) |
| Свинг (4h) | 4 часа | <5 мин | ✅ R1 (60-120 сек) |
| Позиционная (1d) | 24 часа | <30 мин | ✅ R1 идеально |

### 4.2 Асинхронная архитектура

```
scan_loop (60с цикл)
    │
    ├──▶ detection (синхронно, <8 сек)
    ├──▶ gates (синхронно)
    ├──▶ execution (синхронно)
    │
    └──▶ ai_analyst.submit_async(packet)  ← НЕ ЖДЁМ
              │
              ▼
         asyncio.create_task()
              │
              ▼
         HTTP POST → Ollama (не блокирует event loop)
              │
              ▼ (30-120 сек спустя)
         callback → validate → bus.publish("ai_insight")
```

**Ключевое:** `aiohttp` async HTTP-клиент → Ollama REST API. Event loop свободен.

### 4.3 Бенчмарки (прогноз)

| Модель | TTFT* | Полный ответ (500 tok) | Полный ответ (2000 tok CoT) |
|---|---|---|---|
| Coder-V2:16b Q4 | 0.5-1 сек | 15-20 сек | 40-50 сек |
| R1:14b Q5 | 1-2 сек | 25-35 сек | 60-90 сек |

> *TTFT = Time-To-First-Token

---

## 5. Безопасность и риски

### 5.1 Галлюцинации → guardrails

```python
# Три уровня защиты
GUARDRAILS = {
    "schema":   "JSON Schema validation. Не тот формат → reject.",
    "domain":   "signal_type ∈ известный список. Левое → reject.",
    "numeric":  "avgR > 100? n < 0? → clamp + warn в лог.",
    "pattern":  "Есть 3 инсайта с одинаковым signal_type? → duplicate check.",
    "gate":     "Любое предложение с 'gate' → флаг requires_claude_approval.",
}
```

### 5.2 Air-Gap: модель не видит API-ключи

```python
# АРХИТЕКТУРНОЕ ПРАВИЛО
# AIAnalystSphere НЕ импортирует: bingx_client, order_manager, exchange
# AIAnalystSphere имеет доступ ТОЛЬКО к:
#   - Shared Context Bus (read-only для публикации инсайтов)
#   - БД (read-only: simulated_trades, features_json)
#   - Ollama REST API
#   - Файлам памяти проекта
#
# НИКОГДА:
#   - .env / config.yaml секция api_keys не попадает в промпт
#   - LLM не получает order_id, exchange_order_id
#   - LLM не получает реальный баланс / equity с биржи
```

### 5.3 Отказоустойчивость

```python
class AIAnalystSphere:
    async def _call_llm(self, model, prompt, retries=2):
        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(f"{self.url}/api/generate",
                        json={"model": model, "prompt": prompt,
                              "stream": False, "format": "json"},
                        timeout=aiohttp.ClientTimeout(total=180)) as r:
                        return await r.json()
            except asyncio.TimeoutError:
                if attempt == retries - 1:
                    logger.warning("LLM timeout после %d попыток", retries)
                    return None
            except Exception:
                continue
        return None
    
    async def tactical_cycle(self):
        insight = await self._call_llm(...)
        if insight is None:
            # Degradation: без LLM бот продолжает торговать
            logger.info("AI-аналитик недоступен — пропуск цикла")
            return
        ...
```

---

## 6. Дорожная карта внедрения

### Фаза 0 — Инфраструктура (1-2 часа)

```bash
ollama pull deepseek-r1:14b
ollama pull deepseek-coder-v2:16b
python scripts/setup_r1.py                     # проверка
python scripts/ds_r1_analyzer.py "тест"        # первый запрос
```

### Фаза 1 — Быстрый аналитик (2-4 часа)

- ✅ `scripts/ds_r1_analyzer.py` — уже готов
- Добавить `--mode fast` для Coder-V2
- Интеграция с `TradeAnalyzer`: переключить `config.yaml` на Ollama

### Фаза 2 — Сфера AI-Аналитик (8-12 часов)

- `core/intelligence/ai_analyst.py` — новый модуль
- Тактик: цикл каждые 1-2 часа, пакетная обработка SL-сделок
- Публикация инсайтов в Shared Context Bus
- Валидация + guardrails

### Фаза 3 — Стратег + Архивариус (4-6 часов)

- Стратег: сравнение стратегий, поиск новых паттернов
- Архивариус: дрейф рынка, деградация
- RAG-слой: авто-сбор контекста из памяти проекта + БД

### Фаза 4 — Генератор кода (4-6 часов)

- Coder-V2: генерация Python-индикаторов по описанию
- Валидация кода перед применением
- Sandbox-исполнение

---

## 7. Сводная таблица рекомендаций

| Домен | Рекомендация |
|---|---|
| **Модели** | R1:14b Q5_K_M (GPU 0) + Coder-V2:16b Q4_K_M (GPU 1) |
| **Движок** | Ollama (старт) → llama-cpp-python (продакшен) |
| **API** | REST (порт 11434) через aiohttp |
| **Промптинг** | JSON-контракт со schema validation |
| **Память** | RAG через авто-сбор контекста (файлы + БД) |
| **Безопасность** | Air-gap: модель не видит ключи/ордера. Валидация ответов |
| **Латентность** | Async через asyncio.create_task(). Не блокирует scan_loop |
| **Граница зон** | DS: инфраструктура/сфера. Claude: gates/применение инсайтов |
