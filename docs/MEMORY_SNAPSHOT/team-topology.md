---
name: team-topology
description: "Кто есть кто в мульти-агентной команде проекта — «DS-сессия» это Opus 4.8 (НЕ DeepSeek), DeepSeek = инструмент/подключаемый агент"
metadata: 
  node_type: memory
  type: project
  originSessionId: c30a06fd-6559-4f80-90a7-0cffea62483e
---

Мульти-агентная топология / РОСТЕР (зафиксировано 02.06.2026, ARCH-125/126). **НЕ путать «DS-сессию» с DeepSeek.**

### 🧠 Агенты (решения / код)
| Участник | Модель | Роль |
|---|---|---|
| **yogoru (пользователь)** | — | **ARCH** — владелец, арх-решения, приоритеты, финальное слово |
| **порт-сессия** | Claude **Opus 4.8** | бот-сторона AdvisorPort (`advisor_connector`/`advisor_loop`), ревью |
| **DS/swarm-сессия** | Claude **Opus 4.8** (peer) | swarm-сторона (`swarm_orchestrator`/`llm_ask`/`team_ask` + team-update). Подписи «Claude (Opus 4.8, swarm)». Поймала R1 (tuple) + timeout — **второй контур = peer-Opus, НЕ DeepSeek.** |
| **DeepCode** | DeepSeek **V4 Pro** | 🔌 **подключается** — внешний агент, роль «DS» (AGENTS.md), Anthropic-эндпоинт `api.deepseek.com/anthropic` |

### 🎛️ Инструмент-дирижёр
| | Модель | Роль |
|---|---|---|
| Дирижёр роя | DeepSeek **V4 Flash** (`deepseek-chat`) | режет контекст по моделям + синтез брифинга внутри `swarm_orchestrator` (ARCH-126), OpenAI-эндпоинт. ¥0.01/брифинг |

### 🐝 Рой — 7 голосов (опрашивает дирижёр)
cerebras `zai-glm-4.7` · gemini `gemini-3.5-flash` · groq `gpt-oss-120b` · mistral `magistral-medium` · openrouter `nemotron-3-super-120b`(free) · github_models `gpt-4.1-mini` · sambanova `DeepSeek-V3.2`. Резерв: nvidia NIM (РФ-блок регистрации). Детали → [[llm-swarm-config]].

### 📐 Ролевой каркас (шляпы в TASKS/DISCUSSION)
**ARCH** (ты) ставит → **DEV** берёт → **TRADER** валидирует. Opus-агенты надевают шляпы по задаче.

**Ключевой вывод:** «DS» в DISCUSSION-подписях/коммитах = Opus 4.8 swarm-инстанс. DeepSeek (flash-дирижёр + pro-DeepCode) — это инструменты/подключаемые агенты внутри. Команда расширяется **подключением через контракт** (AdvisorPort/Anthropic-эндпоинт), не встраиванием → [[arch125-metatron-kernel]].
