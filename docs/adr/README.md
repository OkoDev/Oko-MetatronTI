# Architecture Decision Records (ADR)

> Короткие записи об **архитектурных решениях**: контекст → решение → последствия.
> Введены 31.05.2026 (ARCH-125). Формат — облегчённый [MADR](https://adr.github.io/madr/).

## Зачем

Решения уровня «Куб» раньше жили в `DISCUSSION.md` и `memory/`. ADR даёт **неизменяемый след**: почему выбрано именно так, какие альтернативы отвергнуты. В отличие от `current_state.md` (что сделано), ADR фиксирует **почему**.

## Правила

- Один файл = одно решение. Имя: `ADR-NNN-kebab-slug.md`.
- Статусы: `proposed` → `accepted` → (`superseded by ADR-MMM` | `deprecated`).
- **ADR не редактируют** после `accepted` (кроме смены статуса). Передумали → новый ADR, старый помечают `superseded`.
- Линкуется из соответствующей задачи ARCH-NNN и из `docs/ENCYCLOPEDIA.md`.

## Индекс

| ADR | Решение | Статус | Задача |
|---|---|---|---|
| [ADR-001](ADR-001-external-services-via-port.md) | Внешние сервисы подключаются через Port, а не встраиваются | accepted | ARCH-125 |
| [ADR-002](ADR-002-swarm-ds-orchestrator.md) | DS-оркестратор роя за AdvisorPort (DeepSeek-дирижёр внутри swarm-service) | accepted | ARCH-126 |
