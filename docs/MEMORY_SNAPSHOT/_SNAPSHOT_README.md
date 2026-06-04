# Memory Snapshot — бэкап auto-memory в git

> 📦 Снапшот **auto-memory** (`C:/Users/yogoru/.claude/projects/.../memory/`) в git-проект.
> Зачем: auto-memory ВНЕ git → при сбросе/переустановке `.claude` пропадёт. Git = надёжное хранилище.
> **Последний снапшот: 2026-06-04** (58 файлов, 392K).

## Что здесь
Все накопленные знания Claude между сессиями:
- **Research-находки:** `ote_nested_mtf_strategy.md` (OTE-куб), `market_three_directions.md`, `arch128_*.md`, `reference_oko_sm_indicator.md`
- **Аудиты:** `arch124_regime_audit.md`, `arch117_wt_audit.md`
- **Feedback-правила** (как работать): `feedback_*.md`
- **Reference** (инфра/пайплайны): `reference_*.md`
- **Индекс:** `MEMORY.md` (hot-индекс), `current_state.md` (handoff)

## ⚠️ Это СНАПШОТ — устаревает
Живая память — в auto-memory. Этот снапшот = копия на дату. Обновлять перед важными коммитами:
```bash
cp "C:/Users/yogoru/.claude/projects/e--MTF-BOT-CURSOR-crypto-volume-bot/memory"/*.md docs/MEMORY_SNAPSHOT/
git add docs/MEMORY_SNAPSHOT/ && git commit -m "chore: memory snapshot YYYY-MM-DD"
```

## Восстановление (если auto-memory пропала)
```bash
cp docs/MEMORY_SNAPSHOT/*.md "C:/Users/yogoru/.claude/projects/e--MTF-BOT-CURSOR-crypto-volume-bot/memory/"
```

## Связь
- Сырьё research: `data/research/2026-06-04--ote-cube/` (логи+скрипты)
- Сводка OTE-куб: `docs/RESEARCH_OTE_CUBE_2026-06-03.md`
- Obsidian vault (генерится роем, не трогать руками): `obsidian/`
