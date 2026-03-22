"""
BaseAgent — базовый интерфейс для всех агентов Multi-Agent System.

Каждый агент:
  - получает контекст (symbol, market data, state)
  - производит действие (сигнал, решение, анализ)
  - логирует reasoning для observability

Интеграция с Claude Agent SDK (Phase 3):
  from claude_agent_sdk import Agent
  class ScoutAgent(BaseAgent, Agent): ...
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """Общий контекст для всех агентов."""
    symbol: str
    timestamp: datetime = field(default_factory=datetime.now)
    market_data: Dict[str, Any] = field(default_factory=dict)
    state: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Результат работы агента."""
    agent_name: str
    action: str                        # "signal", "pass", "alert", "analysis"
    data: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    reasoning: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


class BaseAgent(ABC):
    """Базовый класс агента. Все агенты наследуют этот интерфейс."""

    def __init__(self, name: str, db_path: str = "subscriptions.db"):
        self.name = name
        self.db_path = db_path
        self._enabled = True

    @abstractmethod
    async def run(self, ctx: AgentContext) -> Optional[AgentResult]:
        """Основной метод агента. Получает контекст, возвращает результат."""
        ...

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled
