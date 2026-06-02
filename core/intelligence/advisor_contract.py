"""AdvisorPort контракт — зерно metatron-core (ARCH-125 §B, ADR-001/002).

🔒 FROZEN (02.06.2026): лёгкий контракт, НОЛЬ зависимостей. Импортируют обе стороны:
  - swarm-сторона: `tools/swarm_orchestrator.py` (реализация — DS-дирижёр роя)
  - бот-сторона:   `core/intelligence/advisor_connector.py` (порт + circuit breaker)

Эволюция полей — ТОЛЬКО через `schema_version` + новый ADR, не молча (ломает импорт
на обеих сторонах). Это первый извлечённый лист metatron-core: контракт стабилен,
ядро Bus/Sphere остаётся gated до §B.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AdvisoryRequest:
    """Запрос Куба/клиента к внешнему советнику."""
    snapshot: dict                  # проекция состояния: пара (trade_decision) / рынок+портфель (market_brief)
    intent: str = "free_question"   # "trade_decision" | "market_brief" | "audit" | "free_question"
    question: Optional[str] = None  # конкретный вопрос; None для авто-режима
    deadline_ms: int = 60000        # advisor-домен канон (LLM-рой медленный); trade_decision → 5000
    schema_version: int = SCHEMA_VERSION
    meta: dict = field(default_factory=dict)  # host-специфика (symbol, timeframe, cycle_id, ...)


@dataclass(frozen=True)
class AdvisoryVerdict:
    """Ответ советника. Ложится в Bus как advisor_snap."""
    label: str                      # домен-вердикт ("RISK_ON"/"HOLD"/"BLOCK"/...)
    confidence: float               # 0.0..1.0
    rationale: str                  # 1-3 предложения
    key_factors: list = field(default_factory=list)
    advisor_id: str = "unknown"     # "swarm-ds@v1", "ml-service@v1", ...
    latency_ms: int = 0
    meta: dict = field(default_factory=dict)  # сырьё: по-модельные голоса, план дирижёра


class AdvisorPort(Protocol):
    """Исходящий порт к советнику (реализуется адаптером сервиса)."""

    def consult(self, req: AdvisoryRequest) -> Optional[AdvisoryVerdict]:
        """Вердикт или None (не уверен / нет данных). В норме не бросает —
        сетевые/таймаут ошибки ловит AdvisorConnector выше."""
        ...

    def health(self) -> bool:
        """Жив ли сервис (circuit breaker / preflight)."""
        ...
