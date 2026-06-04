---
name: memory-persistence-git-backup
description: "🔴 ПРАВИЛО ХРАНЕНИЯ ПАМЯТИ: auto-memory (.claude/projects/.../memory/) ВНЕ git → пропадёт при переносе/сбросе проекта. Git = единственный надёжный носитель. Дублируй знания в git-доки + периодически снапшоть всю auto-memory в docs/MEMORY_SNAPSHOT/. Цель: открыть проект на ЛЮБОЙ машине в любой момент и продолжить без потерь. Правило пользователя 04.06.2026."
metadata:
  node_type: memory
  type: feedback
  triggers:
    - крупная находка / research / выводы сессии
    - закрытие сессии / пауза / компакт контекста
    - запись в auto-memory (новый topic-файл)
    - перенос проекта / новая машина / клон репо
    - пользователь просит "сохранить знания / не потерять"
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# Правило: память должна жить в git (переносимость + неубиваемость)

**Проблема:** auto-memory лежит в `C:/Users/yogoru/.claude/projects/<project-id>/memory/` — это
ВНЕ git-репозитория проекта. При переносе проекта на другую машину, клоне репо, сбросе или
переустановке `.claude` — вся накопленная память (research, находки, feedback-правила) ПРОПАДЁТ.
Придётся учиться заново. Пользователь 04.06: «важно чтобы ничего не утекло, и при переносе проекта
можно было открыть в любой момент и продолжить».

**Why:** знания, добытые часами research (OTE-куб n=786, формула, эталонные параметры, что НЕ
работает), невосстановимы из кода/git-истории — они живут только в memory MD. Git — единственное
надёжное, переносимое хранилище. Auto-memory = рабочий слой (быстрый recall), но эфемерный.

**How to apply:**
1. **Два слоя хранения, всегда оба:**
   - Auto-memory (`.claude/.../memory/`) — рабочий recall между сессиями (как сейчас).
   - **Git-зеркало** — `docs/MEMORY_SNAPSHOT/` (полный снапшот всех *.md auto-memory) +
     `docs/RESEARCH_*.md` (интерпретация) + `data/research/<date>/` (сырьё: логи+скрипты).
2. **Снапшот auto-memory → git** при триггерах (находка/закрытие сессии/по запросу):
   ```bash
   cp "C:/Users/yogoru/.claude/projects/e--MTF-BOT-CURSOR-crypto-volume-bot/memory"/*.md docs/MEMORY_SNAPSHOT/
   git add docs/MEMORY_SNAPSHOT/ && git commit -m "chore: memory snapshot <date>"
   ```
   Или скрипт `tools/backup_memory.py` (если создан).
3. **Сырьё research НЕ в /tmp** — `/tmp` (`e:/tmp`, `%TEMP%`) чистится. Копируй логи+скрипты в
   `data/research/<date>--<topic>/{raw,scripts}/` + README-карта (что в каком логе).
4. **Дублируй ценное в git-доки сразу** — не только в auto-memory: важные выводы → `docs/` (ENCYCLOPEDIA,
   RESEARCH, BOT_SIGNAL_MAP). Auto-memory может исчезнуть, docs/ в git — нет.
5. **Восстановление на новой машине:** `cp docs/MEMORY_SNAPSHOT/*.md` → auto-memory путь → recall жив.
6. **Коммить знания регулярно** (не копить незакоммиченным) — git history = машина времени.

**Иерархия надёжности:** git-доки (вечно) > git MEMORY_SNAPSHOT (вечно, но снапшот-дата) >
auto-memory (быстро, но эфемерно) > /tmp (чистится, НИКОГДА не оставлять важное).

Связь: [[ote-nested-mtf-strategy]] (пример research, который нельзя терять),
`docs/MEMORY_SNAPSHOT/_SNAPSHOT_README.md` (инструкция бэкап/восстановление),
`data/research/2026-06-04--ote-cube/README.md` (карта сырья). [[feedback-session-close-checklist]].
