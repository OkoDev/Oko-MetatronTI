"""
ScoutAgent — поиск торговых сетапов.

Оборачивает существующий пайплайн analyze_symbol() как агент.
Phase 3: заменить на LLM-агент с MTFContext + сигналы как инструменты.

TODO (ARCH Phase 3):
  - Принимать список символов, параллельно сканировать
  - Использовать claude_agent_sdk.tool для вызова check_wt_signals, check_pivot_signals
  - Возвращать ранжированный список сетапов по strength + confidence
"""
import logging
from typing import Optional

from core.agents.base import BaseAgent, AgentContext, AgentResult

logger = logging.getLogger(__name__)


class ScoutAgent(BaseAgent):
    """STUB: ScoutAgent — поиск сетапов (Phase 3)."""

    def __init__(self, db_path: str = "subscriptions.db"):
        super().__init__("ScoutAgent", db_path)

    async def run(self, ctx: AgentContext) -> Optional[AgentResult]:
        """
        STUB — Phase 3 реализация.

        Текущая логика (Phase 1-2): analyze_symbol() в TradingIntelligence.
        Phase 3: этот агент заменит прямые вызовы — добавит LLM reasoning.

        TODO:
          1. Вызвать check_wt_signals, check_pivot_signals как tools
          2. Передать MTFContext в LLM prompt
          3. Получить structured output: {setup_quality, entry_zone, invalidation}
        """
        logger.debug("ScoutAgent.run: STUB для %s", ctx.symbol)
        return AgentResult(
            agent_name=self.name,
            action="pass",
            data={"status": "not_implemented", "phase": 3},
            confidence=0.0,
            reasoning="ScoutAgent реализуется в Phase 3",
        )
