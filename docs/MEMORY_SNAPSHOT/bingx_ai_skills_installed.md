---
name: bingx-ai-skills-installed
description: Официальный BingX Claude Code skill-пакет установлен (.agents/skills/bingx-*) — полная API-reference для EXECUTION-REBUILD
metadata: 
  node_type: memory
  type: reference
  originSessionId: e1eb8efb-69a9-4475-b5f1-98909243217d
---

**BingX-API/api-ai-skills установлен 19.06.2026** (`npx skills add BingX-API/api-ai-skills`, EXIT=0). 27 skills в `.agents/skills/bingx-*`, symlink → Claude Code/Continue, доступны как Skill tool.

**Зачем:** официальная структурированная API-reference (НЕ docs-v3 SPA, которая WebFetch'ем не берётся). Решение запроса юзера «документацию полноценно не читали — там всё есть». Основа Ф1 эпика [[exec_sim_split_epic]] / EXECUTION-REBUILD.

**Ключевые для исполнения (каждый = `SKILL.md` + `api-reference.md`):**
- `bingx-swap-trade` (1149 стр) — place/cancel/leverage/margin-mode
- `bingx-swap-account` (305 стр) — positions/balance/**income (funding/commission/realized fund-flow)**
- `bingx-swap-ws-account` (236 стр) — listenKey + ORDER_TRADE_UPDATE + ACCOUNT_UPDATE → спека выжата в `docs/BINGX_WS_ACCOUNT_SPEC.md`
- `bingx-swap-market`, `bingx-swap-ws-market`

**Бонус-паттерны (готовые стратегии-агенты):** `bingx-maker-entry` (лимитки на входе → срезать entry-taker-комиссии), `bingx-dynamic-sl-tp` (ATR/trailing), `bingx-rsi-bottom-hunter`, `bingx-trade-review` (PnL/winrate $), `bingx-technical-analysis` (78 индикаторов + 62 паттерна локально, pandas-ta).

**⚠️ Предупреждение BingX:** skills запускаются с full agent permissions — review перед автономным использованием. Для нас сейчас = reference (читать api-reference.md), не автоторговля.

**Git:** `.agents/` НЕ в .gitignore (только `.claude/agents/`) → bingx-* untracked. Решить: добавить в .gitignore ИЛИ закоммитить как reference. Связь: [[bus_catalog_data_menu]] (меню API), feedback_read_bingx_docs.
