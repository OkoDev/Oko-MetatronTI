# Metatron Kernel — переносимый скелет архитектуры

> **Задача:** ARCH-125 | **Статус:** 🟢 видение зафиксировано (31.05.2026) | **Уровень:** ВЫСШИЙ
> **Основа:** рой-обсуждение «кем быть рою» (6/7 за независимый сервис, [[memory/last_team_discussion]]) + фрактальный Sub-куб ([CUBE_SUBCUBES.md](CUBE_SUBCUBES.md)) + Hexagonal (Ports & Adapters)
> **ADR:** [adr/ADR-001-external-services-via-port.md](adr/ADR-001-external-services-via-port.md)

---

## 0. Зачем этот документ

Архитектура «Куб Метатрона» переросла один проект. Цель ARCH-125 — **выделить переносимый скелет** (kernel), на котором можно строить ЛЮБОЙ проект, а торговый бот Oko MTF и LLM-рой сделать двумя независимыми клиентами этого ядра.

Три отдельные вещи, которые нельзя путать:

| # | Что | Где живёт |
|---|---|---|
| **1. Kernel** | Чистые абстракции (Bus, Sphere, SubCube, Port, Connector) — **ноль доменной логики** | пакет `metatron-core` |
| **2. AdvisorPort** | Новый примитив: Куб **подключает** внешний сервис, а не встраивает его | `core/intelligence/` бота |
| **3. Рой как продукт** | LLM-рой = мини-Куб на том же ядре + свой API + team-update | отдельный репо `swarm-service` |

Этот документ фиксирует **1 и контракт 2**. Реализация роя (3) и порта в боте — последующие задачи.

---

## 1. Принцип: подключение, а не встраивание

Текущие Sub-кубы ([CUBE_SUBCUBES.md](CUBE_SUBCUBES.md)) **вкомпилированы** в процесс бота — `SubCube.compute_and_publish()` вызывается синхронно в `scan_loop`. Это правильно для доменной логики (SMC, Pivot, WT), которая обязана быть быстрой и детерминированной.

Но **недетерминированные / тяжёлые / переиспользуемые** сервисы (LLM-рой, внешний ML, чужой аналитический сервис) встраивать НЕЛЬЗЯ — ровно по аргументам, которые сам рой привёл в Варианте Б:

- LLM галлюцинирует, имеет latency 1-3с и может упасть → недопустимо в торговом контуре 24/7.
- Сервис переиспользуем в других проектах → жёсткая связь убивает переиспользование.
- Сервис эволюционирует своим темпом → деплой не должен останавливать бота.

**Решение — Hexagonal / Ports & Adapters:**

```
       ┌──────────────────────────── КУБ (host) ────────────────────────────┐
       │                                                                     │
       │   Shared Context Bus  ──► AdvisorConnector ──► AdvisorPort (контракт)│
       │         ▲                    (resilience:          │                │
       │         │                     timeout, breaker)    │                │
       │   advisor_snap ◄─────────────────────────────────┘                 │
       └─────────────────────────────────────────────────────│──────────────┘
                                                              │ (process/network boundary)
                                              ┌───────────────▼───────────────┐
                                              │  Адаптер внешнего сервиса      │
                                              │  SwarmAdvisorAdapter           │  ← рой (первый)
                                              │  MLServiceAdapter (завтра)     │
                                              │  AnyAnalystAdapter (послезавтра)│
                                              └────────────────────────────────┘
```

Куб знает только **контракт `AdvisorPort`**. Что за сервис на том конце — не знает и не зависит. Сервис недоступен → `AdvisorConnector` ловит timeout/ошибку → возвращает `None` → Куб работает по базовой логике (circuit breaker). Это и есть **«Куб, готовый к подключению сторонних сервисов»**.

Логически порт живёт на уровне **Додекаэдр/Эфир — AI и Аналитика** ([ENCYCLOPEDIA.md](ENCYCLOPEDIA.md) → 5 Платоновых тел).

---

## 2. Контракт AdvisorPort (keystone-примитив)

> Это **контракт**, а не реализация. Версионируется (`schema_version`). И бот, и рой зависят от него — поэтому он фиксируется первым.

```python
# metatron-core/ports/advisor.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, Optional

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AdvisoryRequest:
    """Запрос Куба к внешнему советнику."""
    snapshot: dict                  # проекция состояния (PairFullState/домен-контекст)
    intent: str                     # "trade_decision" | "audit" | "free_question"
    question: Optional[str] = None  # конкретный вопрос (для LLM-роя); None для авто-режима
    deadline_ms: int = 5000         # бюджет времени; советник обязан уложиться
    schema_version: int = SCHEMA_VERSION
    meta: dict = field(default_factory=dict)  # host-специфика (symbol, timeframe, ...)


@dataclass(frozen=True)
class AdvisoryVerdict:
    """Ответ советника. Ложится в Bus как результат сферы (advisor_snap)."""
    label: str                      # домен-специфичный вердикт ("STRONG_BULL"/"HOLD"/"BLOCK"/...)
    confidence: float               # 0.0..1.0
    rationale: str                  # человекочитаемое обоснование (1-3 предложения)
    key_factors: list[str] = field(default_factory=list)
    advisor_id: str = "unknown"     # кто ответил: "swarm@v3", "ml-service@v1"
    latency_ms: int = 0
    meta: dict = field(default_factory=dict)  # сырьё: по-модельные голоса роя, meta-синтез и т.п.


class AdvisorPort(Protocol):
    """Исходящий порт Куба к внешнему советнику (реализуется адаптером сервиса)."""

    def consult(self, req: AdvisoryRequest) -> Optional[AdvisoryVerdict]:
        """Вернуть вердикт или None (если не уверен / нет данных). Не должен бросать
        в норме — сетевые/таймаут ошибки ловит AdvisorConnector выше."""
        ...

    def health(self) -> bool:
        """Жив ли сервис (для circuit breaker / preflight)."""
        ...
```

### Сторона Куба — AdvisorConnector (resilience-обёртка)

```python
# core/intelligence/advisor_connector.py (в боте, НЕ в kernel)
class AdvisorConnector:
    """Оборачивает AdvisorPort: timeout, circuit breaker, публикация в Bus.
    Падение советника НЕ останавливает торговый контур."""

    def consult_and_publish(self, sym: str, req: AdvisoryRequest, bus) -> Optional[AdvisoryVerdict]:
        if not self._breaker.allow():
            return None                         # breaker открыт → базовая логика
        try:
            verdict = self._port.consult(req)   # с таймаутом req.deadline_ms
        except Exception:
            self._breaker.record_failure()
            return None
        self._breaker.record_success()
        if verdict:
            bus.update(sym, {"advisor_snap": verdict.__dict__,
                             "advisor_verdict": verdict.label,
                             "advisor_conf": verdict.confidence})
        return verdict
```

**Инвариант:** `advisor_snap` в Bus — опциональный сигнал. Ни одна execute-функция не должна *требовать* его наличия. Нет советника → Куб торгует как раньше.

---

## 3. Kernel — переносимые абстракции (ноль доменной логики)

Пакет `metatron-core`. Всё доменное (детекторы, SMC, торговля) остаётся в проекте-клиенте.

| Абстракция | Роль | Уже есть в Oko как |
|---|---|---|
| `Context` / `SharedContextBus` | pub/sub-хранилище состояния по сущности (symbol) | `core/.../shared_context_bus` + `PairFullState` |
| `Sphere` (Protocol) | домен-модуль: `compute(...)` → `publish(bus)` | детекторы, специалисты |
| `SubCube` | композиция сфер + центр-агрегатор; снаружи = `Sphere` | `SMCSubCube` |
| `Port` / `Adapter` | граница к внешнему сервису (hexagonal) | **новое (ARCH-125)** |
| `Connector` | обёртка порта: timeout, circuit breaker, retry | `ApiEngine`/`CircuitBreaker` (частично) |

```python
# metatron-core/bus.py — суть, без проектной специфики
class SharedContextBus:
    def update(self, key: str, patch: dict) -> None: ...
    def get_state(self, key: str): ...
    def subscribe(self, topic: str, handler) -> None: ...   # mesh, не конвейер


class Sphere(Protocol):
    def compute(self, *inputs): ...
    def publish(self, key: str, bus: SharedContextBus) -> None: ...


class SubCube(Sphere, Protocol):
    """Снаружи = одна Sphere. Внутри = набор сфер + свой центр-агрегатор."""
```

**Инварианты ядра** (переносятся в любой проект — это и есть «скелет»):
1. **Mesh, не конвейер** — сферы общаются через Bus, не вызывают друг друга цепочкой ([ENCYCLOPEDIA.md](ENCYCLOPEDIA.md) → Mesh-связность).
2. **Фрактальность** — любая сфера может быть Sub-кубом без изменения внешнего интерфейса.
3. **Порты наружу** — недетерминированное/переиспользуемое подключается через Port, не встраивается.
4. **Единый источник правды** — состояние в Bus, персистенция отдельным слоем (ИНВАРИАНТ ARCH-118).
5. **Один калькулятор на признак** — нет двух независимых путей расчёта (ИНВАРИАНТ ARCH-118).

---

## 4. Рой как первый External Sub-куб

Рой = **мини-Куб Метатрона** на том же ядре:

```
swarm-service (отдельный репо, metatron-core как зависимость)
│
├── LLM-сферы:  CerebrasSphere, GeminiSphere, GroqSphere, MistralSphere,
│               OpenRouterSphere, GithubSphere, SambaNovaSphere
│                   каждая: consult(snapshot, question) → SphereOpinion
│
├── Центр (meta-bus):  MetaSynthesizer  → AdvisoryVerdict
│                       (где согласны / спорят / синтез — текущий meta-синтез)
│
├── api/        порт роя наружу (REST/gRPC) — host-agnostic
├── adapters/   SwarmAdvisorAdapter implements metatron-core AdvisorPort
└── team_update/  смена состава моделей/весов «по событию» (см. §5)
```

Снаружи рой выглядит как `AdvisorPort` — бот подключает его как любой внешний советник. Внутри — полноценный фрактальный Куб. Бот Oko MTF = **первый клиент**; завтра тот же рой подключается к другому проекту.

Текущие [tools/llm_ask.py](../tools/llm_ask.py) + [tools/team_ask.py](../tools/team_ask.py) — прото-ядро роя (провайдеры = сферы, meta-синтез = центр). Извлечение = рефакторинг этого в пакет.

---

## 5. team-update — самообновление роя (по событию)

То, что рой просил у себя сам (5/7 за «по событию»). Живёт внутри `swarm-service`:

- **Триггеры:** выход новой модели у провайдера, дрейф качества голоса, ручная команда `/team-update`.
- **Версионируемость:** состав моделей + веса голосов = версия (`swarm@v3`), пишется в `advisor_id` каждого вердикта → воспроизводимость.
- **НЕ на каждый запрос** — иначе экспертные заключения теряют сопоставимость (лучший уникальный довод SambaNova).

---

## 6. «Сохранить скелет» — как это делают (playbook)

Три стандартных способа, по нарастанию усилий. Делаем по порядку:

| Этап | Способ | Артефакт | Когда |
|---|---|---|---|
| **A** | **Reference Architecture + ADR** | этот документ + `docs/adr/` | ✅ сейчас (ARCH-125) |
| **B** | **Kernel-библиотека** | пакет `metatron-core` (Bus/Sphere/SubCube/Port/Connector) | когда абстракции стабильны |
| **C** | **Template-репо** | cookiecutter/copier → `metatron new <project>` (готовая шина + пустые сферы) | когда нужно плодить проекты |

Целевая картина:

```
              metatron-core  (kernel — переносимый скелет, §3)
               /          \
        Oko MTF Bot       swarm-service
        (главный Куб)     (мини-Куб LLM)
               \          /
              AdvisorPort  (§2 — Куб подключает рой как внешний адаптер)
```

---

## 7. Что НЕ решается этим документом (отложено)

- Транспорт порта (REST vs gRPC vs stdio) — решается при реализации роя.
- Точная схема `snapshot` для `intent="trade_decision"` — проекция `PairFullState`, детализируется отдельной задачей.
- Извлечение `metatron-core` (этап B) и template (этап C).
- Подключение порта в `scan_loop` бота — после готовности роя-сервиса.

---

## 8. Соответствие Кубу (4 вопроса)

1. **Строит сферу?** — Да: формализует External Sub-куб как новый класс сферы.
2. **Усиливает Bus?** — Да: `advisor_snap` — новый домен в Bus.
3. **Добавляет ребро?** — Да: ребро Куб ⟷ внешний советник через Port.
4. **Feedback loop?** — Да: вердикты советника → Bus → (в будущем) обучение Сферы 11.
