# Memory & Obsidian Audit Plan

> Создан 2026-05-21 после двух запусков `/team-ask`:
> - `obsidian/Team-Discussions/2026-05-20-аудит-и-оптимизация-persistent-memory-для-ai-агент.md` (4/6 LLM + meta)
> - `obsidian/Team-Discussions/2026-05-20-автоматизация-поддержки-obsidian-vault-для-ai-аген.md` (4/6 LLM + meta)

## Контекст

- `C:\Users\yogoru\.claude\projects\e--MTF-BOT-CURSOR-crypto-volume-bot\memory\` — 34 файла, 140 KB
- `memory/MEMORY.md` — 36 KB, частично truncate-ится при загрузке (системный warning)
- Известные дубли: `feedback_russian_thinking + feedback_think_russian + feedback_say_command`, `feedback_metrics_hygiene + feedback_verify_metric_semantics`
- Recall failure кейс 2026-05-21: выдумал `subscription_manager.get_active_subscriptions()` хотя правило про grep-before-claim записано

## Консенсус роя (5/5 в обоих обсуждениях)

1. Hot (≤8 KB auto-load) / Cold (lazy load в Obsidian) split
2. YAML frontmatter с `id, triggers, priority, last_used`
3. Pre-flight checklists для повторяющихся task-классов
4. Triggers для recall (контекстные / событийные / временные)
5. Автоматизация cleanup (memory_lint + git hooks)

---

## A — Sweep памяти (приоритет 1, делегируем рою с файловым контекстом)

**Цель:** убрать дубли, устаревшее, сжать MEMORY.md под бюджет загрузки.

**Конкретные правки:**
1. Объединить: `feedback_russian_thinking` + `feedback_think_russian` + `feedback_say_command` → `feedback_language_and_tts.md`
2. Объединить: `feedback_metrics_hygiene` + `feedback_verify_metric_semantics` → `feedback_metrics_discipline.md`
3. Перенести в Obsidian: `bugs_march_2026.md`, `research_2026-05-08_classifier_cascade.md`, `arch_*.md` (старые архитектурные решения)
4. Удалить устаревшее: `project_cascade_sl_vision.md` (14.03, перекрыто ARCH-104)
5. Сжать `MEMORY.md` 36 KB → ≤15 KB (один-строчные триггеры + ссылки)

**Делегирование рою:** `tools/team_ask.py` с `--file memory_dump.md` — рой видит реальные файлы, даёт точечный план

## B — Архитектура hot/cold + триггеры (приоритет 2)

**Цель:** структурировать память для предсказуемого recall.

**Конкретные шаги:**
1. Layout:
   ```
   memory/
   ├── MEMORY.md          # индекс ≤15 KB
   ├── feedback_*.md      # hot rules
   ├── preflight_*.md     # NEW: чек-листы для task-классов
   └── current_state.md
   ```
2. Frontmatter в feedback_*.md: `triggers: [api_integration, new_loop, ...]`
3. Создать `memory/preflight_new_loop.md`, `preflight_new_detector.md`, `preflight_db_migration.md` (5-7 task-классов)
4. `obsidian/Meta/Memory-System.md` — карта моей памяти, что где живёт

**Делегирование рою:** нет, делаю руками после A

## C — memory_lint скрипт (приоритет 3)

**Цель:** автоматическая проверка состояния памяти.

**Скрипт `tools/memory_lint.py`:**
- Размер `MEMORY.md` ≤ X KB (warn)
- Дубли feedback файлов по `triggers:` или по схожести заголовков
- Untouched older than 90 дней
- Запуск: ручной + git pre-commit (опц.)

**Делегирование:** не нужно, ~30 мин руками

## D — Obsidian automation скрипты (приоритет 4, отдельный спринт)

Из роя 2 — 6 скриптов priority order:
1. `obsidian_status_sync.py` — frontmatter sync, git post-commit hook
2. `vault_health.py` → `Meta/HEALTH.md`, cron daily + on-demand
3. `obsidian_autolink.py` — wikilinks по ID, event-driven
4. `obsidian_weekly_digest.py` — LLM (Gemini), weekly cron
5. `obsidian_dedup_discussions.py` — LLM + механика, nightly cron
6. `obsidian_archive.py` — 90 дней без ссылок → `_archive/`, monthly cron

**Делегирование:** B+C сначала, потом D отдельным эпиком ARCH-XXX

---

## Execution order

1. [ ] **A** делегируется рою (этот sweep с реальными файлами)
2. [ ] Применить план роя по A (мои edit-ы)
3. [ ] **B** руками (~30 мин)
4. [ ] **C** руками (~30 мин)
5. [ ] **D** — отдельный спринт после A+B+C
