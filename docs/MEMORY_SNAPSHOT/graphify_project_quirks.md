---
name: graphify-project-quirks
description: "graphify в этом репо: 🔴 ИСКАТЬ ПО КОДУ НАЧИНАТЬ С graphify-out/graph.json (Егор 04.10) — обновлять ТОЛЬКО через tools/graphify_refresh.py (DEV-242); почему руками нельзя: склейка extract, хук, spawn-воркеры, cluster-only"
metadata:
  node_type: memory
  type: reference
  originSessionId: 3418cd9a-c6a9-433f-b8d1-ebba3d1894a2
  modified: 2026-10-04T00:10:55.498Z
---

🔴 **ПОИСК ПО КОДУ НАЧИНАТЬ С ГРАФА** (Егор 04.10: «для поиска по коду не забывай про graphify-out»).
`graphify-out/graph.json` (04.10: 19 855 узлов, 34 511 связей в ключе **`links`**, не `edges`; хук post-commit
держит его свежим). Он отвечает на то, что грепом видно плохо: КТО ссылается на модуль
(`[l for l in links if l['target'].startswith('context_pair_context')]` → 121 источник), где функция
используется, что в сообществе файла. Узел = `<папка>_<файл>_<класс/функция>` в нижнем регистре,
у доков — `memory_current_state_<дата>_…`; `_rationale_<строка>` — комментарии-обоснования.
✅ Проверено пользой 04.10: при сборке карты Куба граф показал три работающие сферы (13 фаза, 19 Market Data,
20 Wave Service), которых НЕТ в `/api/cube/selftest` — грепом по именам сфер я бы их не нашёл.
Граф — навигатор, истина — код: нашёл узел → подтверди Read/grep.

**Обновлять граф: `python tools/graphify_refresh.py [--docs|--labels|--all]`** (DEV-242, 29.09, проверен прогонами). Без флагов — код бесплатно; `--all` — доки (Gemini через `LLM_PROXY`, `gemini-3.1-flash-lite`) → код → имена заглушкам. Граф 29.09: 19 320 узлов, 42 гиперребра, 1427 сообществ — все названы.

**Почему руками нельзя (всё зашито в инструмент):**
- 🔴 Инкрементальная склейка `graphify extract` ломает граф трижды: теряет AST-узлы (код + .md-структура, ~2 тыс.), выбрасывает гиперрёбра даже НЕпереразобранных доков (16 из 38), перенумеровывает сообщества → имена прилипают к чужим (#69 «Session Handoff» стал «CCXT API…»). Инструмент после extract возвращает прежние номера, потерянные AST-узлы и гиперрёбра, затем `update --force`.
- 🔴 `graphify cluster-only` ВСЕГДА перекластеризует → каждый раз 1–2 новых мелких сообщества без имени. Инструмент пишет отчёт с подменённым `graphify.cluster.cluster` («вернуть текущие»).
- 🔴 Чистка графа — только по правилам самого `.graphifyignore` + файл удалён. НЕ по «вне корпуса detect»: семантика законно ссылается на `subscriptions.db`, `core/smc/`, `*.pine`, `obsidian/` (5 ложных удалений в первой версии).
- 🔴 Гонка с хуком post-commit: чужой коммит во время ручной пересборки перезаписал её (28.09). Хук инкрементален и исключённое не вычищает. Инструмент предупреждает, если graph.json изменён извне между шагами.
- 🔴 Обёртка над `graphify.__main__.main()` без `if __name__ == "__main__"` → Windows spawn-воркеры (16) запускают по extract каждый → шквал 429 (26.09). Сироты — базовым Python313, искать по `parent_pid=`. Инструмент зовёт graphify отдельным процессом `python -m graphify`.
- Gemini: без `LLM_PROXY` (Сингапур) → 400 location (VPN-выход VDSka Google считает запрещённым). Чанки 30k — без минутных 429. `gemini-3.5-flash` 20 RPD; `3-flash-preview` кончается за ~10 чанков. Прокси бывает рвётся (`Connection error`) — упавшие доки доберёт следующий прогон, кэш не даёт платить дважды.
- Имена Groq `gpt-oss-120b` (если Gemini нет): `GRAPHIFY_MAX_OUTPUT_TOKENS=3000` (reasoning съедает бюджет `64+24·N`), пачки 30, пауза 40 с; суточный лимит ~2 полных прогона.
- `.graphifyignore` (в git, `14ff6a4`): `.agents/`, `.claude/skills/bingx-*/` и `.continue/skills/` (junction-ссылки на `.agents/skills/`), `archive/` (любой глубины — задевает и `config/archive/`), `scripts/_archive/`. `detect` читает и `.gitignore` → `obsidian/` в корпус не входит.
- Семантика только по докам; код всегда AST. ~1300 из ~1400 сообществ = один файл (70% рёбер внутрифайловые) — структура, LLM не лечит. Граф — для `query/path/explain`, не источник истины.
- Хук стоит и работает, но путь «MTF BOT» с пробелом → `_PINNED=''`, нужен python с graphify в PATH. `graphify-out/.graphify_python` с UTF-8 BOM. `graphify-out/` в .gitignore — так и надо.
- Мёртвые LLM для этого (26.09): DeepSeek 402, Mistral 429, SambaNova 402, OpenRouter free (~50/сутки, reasoning → пустота).
