---
name: arch125-metatron-kernel
description: "ARCH-125 — выделение архитектуры Куба в переносимый скелет metatron-core + примитив AdvisorPort (подключение, не встраивание)"
metadata: 
  node_type: memory
  type: project
  originSessionId: c30a06fd-6559-4f80-90a7-0cffea62483e
---

ARCH-125 (зафиксировано 31.05.2026, уровень ВЫСШИЙ) — видение: архитектура «Куб Метатрона» переросла торговый бот, выделяется в **переносимый скелет** для любых проектов пользователя.

**Три разведённые вещи:**
1. **Metatron Kernel** (`metatron-core`) — чистые абстракции Bus/Sphere/SubCube/Port/Connector, **ноль доменной логики**.
2. **AdvisorPort** — НОВЫЙ примитив (Hexagonal/Ports&Adapters): Куб **подключает** недетерминированные/переиспользуемые сервисы (LLM-рой, внешний ML), а НЕ встраивает их синхронно как обычные Sub-кубы. Контракт: `consult(AdvisoryRequest)→AdvisoryVerdict|None` + `health()`. На стороне Куба `AdvisorConnector` (timeout+circuit breaker) → `advisor_snap` в Bus = **опциональный** сигнал (нет советника → базовая логика). Живёт на уровне Додекаэдр/Эфир.
3. **Рой → standalone `swarm-service`** — мини-Куб (LLM-провайдеры=сферы, meta-синтез=центр) + свой API + team-update («по событию», версионируемо). Бот Oko MTF = первый клиент. Основа: рой сам выбрал 6/7 за независимый сервис.

**Почему «подключение, а не встраивание»:** LLM недетерминирован, latency 1-3с, недопустим в торговом контуре 24/7; переиспользуемость; независимый деплой. (Mistral — единственный голос за встраивание.)

**Артефакты:** `docs/METATRON-KERNEL.md` (reference-arch), `docs/adr/ADR-001-external-services-via-port.md` (accepted, заведена ADR-конвенция в `docs/adr/`), запись в TASKS.md (ARCH-125 🟢), инвариант в ENCYCLOPEDIA.

**Playbook «сохранить скелет»:** A=reference-arch+ADR (✅ сделано) → B=kernel-библиотека → C=template-репо (cookiecutter/copier). Делается по порядку.

**Дальше (отдельные задачи):** извлечь metatron-core; рой в swarm-service; порт в scan_loop; template. Связано с [[llm-swarm-config]] (рой = первый адаптер порта).
