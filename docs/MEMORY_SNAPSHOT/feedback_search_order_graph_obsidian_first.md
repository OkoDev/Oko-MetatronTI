---
name: feedback_search_order_graph_obsidian_first
description: "🔴 ЕГОР 04.10: «каждый раз производишь новый поиск по проекту, не ходишь в обсидиан и не пользуешься graphify-out». Порядок: auto-memory → graphify query → obsidian/Research → REGISTRY/TOOLS → и только потом grep"
metadata:
  node_type: memory
  type: feedback
  triggers:
    - где это
    - что у нас есть
    - мерили ли
    - найди в проекте
    - поиск
    - graphify
    - обсидиан
  originSessionId: b9292ecd-40bf-480f-b583-11c47310bf19
  modified: 2026-10-04T18:00:58.210Z
---

04.10.2026, Егор: «каждый раз при возникновении вопросов ты почему-то производишь новый поиск
по проекту(((  не ходишь в исследования обсидиан и не пользуешься для памяти graphify-out.
как исправить это?»

**Цена привычки за ОДНУ сессию (всё уже существовало):**
- мерил спред VST заново — он измерен **дважды**: 14.08 (VST 0.299% против LIVE 0.089%,
  [[backlog_vst_spread_poisons_forward]]) и 28.08 (налог платят ТОЛЬКО рыночные входы: 43.6%
  против 1.4% у лимитных, [[vst_spread_measured_market_only]]);
- писал сверку филлов с рынком, хотя есть готовый `scripts/vst_actual_fill_slippage.py`;
- не знал, что накоплено **44 358** снимков стакана (`oko_feed/external_data.db::depth_snap`),
  **176 569** строк `orderflow_1m` и 1 033 снимка в момент сделки (`depth_snapshots`) —
  и взял klines как «нижнюю границу» коста, хотя стакан точнее.

**Почему не ходил — три причины, все устранены:**
1. **`graphify-out` не упоминался в CLAUDE.md вообще.** Скилл graphify описывает «fast path:
   есть graph.json → сразу query», но подключается только по `/graphify`, то есть правило
   лежало в неактивном месте. → Добавлен раздел «🔍 ПОРЯДОК ПОИСКА» в `.claude/CLAUDE.md`.
2. **Путь в `graphify-out/.graphify_python` был с BOM** — наивный вызов
   `"$(cat ...)" -m graphify` падал с «No such file or directory». → BOM убран, команды
   записаны в CLAUDE.md в рабочем виде.
3. Я решил, что граф пустой: `graph.json` даёт `nodes=19979`, а `d["edges"]` = 0 — но рёбра
   лежат не в этом ключе, и `graphify query` их отдаёт (с пометками EXTRACTED/INFERRED).
   **Проверять инструмент запуском, а не чтением его файла.**

**Порядок поиска (CLAUDE.md, раздел «ПОРЯДОК ПОИСКА»):**
1. auto-memory (уже в контексте) → topic-файл;
2. `"$(cat graphify-out/.graphify_python)" -m graphify query "…"` — где живёт, что с чем связано
   (граф пересобирается АВТОМАТИЧЕСКИ хуком post-commit, всегда свежий; есть `path` и `explain`);
3. `obsidian/Research/` — сырые данные прошлых замеров, `Tasks/`, `Concepts/`, `Project-MOC.md`;
4. `docs/REGISTRY.md` + `TOOLS.md` — реестр готовых инструментов;
5. grep/Read — ПОСЛЕДНИМИ: точная строка под правку либо верификация утверждения.

⚖️ **ГРАНИЦА ПРИМЕНИМОСТИ (проверено 04.10 запуском, а не предположением):**
граф силён на ТЕМАХ и СВЯЗЯХ («спред VST и налог» → узлы ExecutionSphere / EXEC-SIM-SPLIT /
CUTOVER), слаб на ТОЧНОМ ИМЕНИ поля: запрос «кто пишет actual_entry_price» увёл в
`bot/loops/ote_observer_loop.py`, тогда как писали `core/exchange/exec_ws_integration.py`
и `core/exchange/position_sync.py`.
**Граф — для ориентирования, grep — для точки.** Обещать, что граф заменит grep везде, нельзя.

**How to apply:** вопрос «мерили ли / что у нас есть / где считается» НЕ начинать с grep.
Сначала память, граф, Research. grep остаётся обязательным для «grep before claim», но это
проверка утверждения, а не способ поиска.
Связано: [[research_data_goes_to_obsidian_research]], [[strategy_registry_read_first]],
[[research_harness_single_entry]], [[graphify_project_quirks]], [[feedback_rules_table]].
