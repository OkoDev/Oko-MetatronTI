---
name: team
description: Коллективный аудит проекта роем 5-6 LLM + meta-синтез. АКТИВИРУЙ на "/team", "аудит проекта роем", "team verdict", "вердикт команды". Без аргумента — дефолтный аудит.
---

# Team — коллективный аудит проекта

Запусти: `python tools/team_verdict.py [--providers ...] [--skip-meta]`

- 5-6 LLM получают одинаковый контекст (brief + timeline + trade_review + log_digest + TASKS) → независимые вердикты
- Mistral: meta-summary (консенсус high-confidence / споры / синтез-рекомендации)
- Output: `obsidian/Verdicts/<date>-team-verdict.md` + `memory/last_team_verdict.md`

После: прочитай `memory/last_team_verdict.md` секцию META-VERDICT, покажи топ-3 единогласных + топ-3 рекомендации (5-7 строк). Это фиксированный аудит; для своего вопроса — `/team-ask`.
