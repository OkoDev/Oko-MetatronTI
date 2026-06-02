# ADR-002 — DS-оркестратор роя за AdvisorPort (swarm-service внутреннее устройство)

- **Статус:** accepted (дизайн), реализация Phase 1
- **Дата:** 2026-06-02
- **Задача:** ARCH-125 (продолжение), ARCH-126 (новая — DS-оркестрация)
- **Контекст-док:** [../METATRON-KERNEL.md](../METATRON-KERNEL.md), [ADR-001](ADR-001-external-services-via-port.md), [../AGENT_ORCHESTRATION.md](../AGENT_ORCHESTRATION.md)

## Контекст

ARCH-125 / ADR-001: рой подключается к Кубу через `AdvisorPort` как standalone swarm-service. Открыт вопрос — **внутреннее устройство** сервиса.

Текущий рой (`tools/team_ask.py`): параллельный one-shot опрос. Каждая модель получает **обрезанный** контекст (`CONTEXT_BUDGET_CHARS`: github 10k, sambanova 60k — тупой truncate), отвечает независимо, mistral синтезирует — тоже на обрезках. Две доказанные слабости (DISCUSSION 01-02.06):
- **Контекст-слепота** (DEV-238): рой советует на неверной модели кода (не видит всего).
- **Данные-слепота** (DEV-240): гипотеза без проверки данными.

Появился ресурс, меняющий картину: **DeepSeek-v4, 1M контекста** — вмещает весь bundle проекта без нарезки.

## Решение

Внутри swarm-service — **DS-дирижёр** (deepseek 1M = голова, скрипт = руки). Сервис снаружи реализует `AdvisorPort.consult(AdvisoryRequest) → AdvisoryVerdict`; клиент (Куб/Claude) не знает про внутреннюю оркестрацию.

**Поток `consult()` (Phase 1, один раунд):**
```
AdvisoryRequest (snapshot + question + полный контекст)
  → DS-дирижёр (1M): план — РЕЛЕВАНТНАЯ выжимка под каждую из N моделей + под-вопрос
  → скрипт рассылает N моделей по плану DS (не truncate, а осмысленная нарезка)
  → ответы → DS-синтез на ПОЛНОМ контексте (заменяет mistral-meta)
  → AdvisoryVerdict(label, confidence, rationale, key_factors,
                    advisor_id="swarm-ds@v1", meta={по-модельные голоса, план DS})
```

**Phase 2 (позже, agentic):** DS после раунда 1 решает «нужны уточнения?» (противоречия моделей) → раунд 2 переспроса → финал. Дороже, делать если Phase 1 окупится.

**Состав роя на 02.06:** 7 рабочих (cerebras, mistral, openrouter, gemini, groq, github_models, sambanova) + deepseek-v4 (дирижёр). nvidia не активен.

## Альтернативы (отвергнуты)

- **A. Оставить mistral-meta на обрезках.** Отвергнуто: синтез на неполном контексте = та же контекст-слепота (DEV-238).
- **B. DS-агент (DeepCode) сам оркестрирует.** Отвергнуто: Claude не управляет окном DeepCode программно; у DeepCode нет tool «вызови другой LLM». DS-как-API = LLM-планировщик, исполняет скрипт.
- **C. Тупой truncate под лимиты (текущий).** Отвергнуто: случайный кусок ≠ релевантная выжимка; DS режет осмысленно.

## Последствия

**Плюсы:**
- Лечит контекст-слепоту: модели получают осмысленную выжимку, синтез на полной картине.
- DS-якорь в синтезе (видит реальный код/vault) корректирует галлюцинации.
- Чистая инкапсуляция за AdvisorPort — клиент не меняется.

**Минусы / плата:**
- Зависимость от deepseek API (платный баланс) → нужен graceful fallback на обычный `team_ask` (mistral-meta), если deepseek недоступен.
- **Данные-слепоту НЕ лечит** (DEV-240) — эмпирические гипотезы вердикта роя Claude валидирует данными всегда (правило AGENT_ORCHESTRATION).
- Latency ↑ (DS-план + рассылка + DS-синтез = 2 DS-вызова + N) — приемлемо для advisory (не торговый контур).

## План реализации

- **Phase 1:** `tools/swarm_orchestrator.py` — `SwarmOrchestrator.consult()` (DS-план → рассылка через team_ask-механизм → DS-синтез) + fallback. Флаг `team_ask.py --orchestrator deepseek`.
- **Phase 2:** многораундовые уточнения.
- **Миграция:** контракт-классы (`AdvisoryRequest/Verdict/AdvisorPort`) → будущий `metatron-core` (ARCH-125 playbook B). Пока определены локально.
