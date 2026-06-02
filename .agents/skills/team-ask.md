---
name: team-ask
description: Командное обсуждение свободного вопроса роем 7 LLM + meta-синтез. АКТИВИРУЙ на "/team-ask", "спроси команду", "вопрос рою", "team ask", "обсуди с роем". Аргумент — свободный вопрос.
---

# Team-Ask — рой LLM на свободный вопрос

Запусти: `python tools/team_ask.py "<вопрос>" [--file path] [--providers ...] [--no-context]`

Что делает:
- 7 провайдеров (cerebras/mistral/openrouter/gemini/groq/github_models/sambanova) получают контекст проекта + твой вопрос
- Каждый отвечает независимо; mistral делает meta-синтез (консенсус/споры/синтез-ответ)
- Output: `obsidian/Team-Discussions/<date>-<slug>.md` + `memory/last_team_discussion.md`

NB: рой = ГИПОТЕЗЫ, не истина — перепроверяй grep'ом (код) и данными (эмпирику). См. `docs/AGENT_ORCHESTRATION.md`. Для оркестрированного режима с DeepSeek-дирижёром: `python tools/swarm_orchestrator.py "<вопрос>"`.

После: покажи синтез-ответ (3-5 строк) + интересные расхождения, не вываливай весь файл.
