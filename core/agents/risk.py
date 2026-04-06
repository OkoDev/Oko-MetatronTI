"""
RiskAgent — оценка риска перед входом.

Оценивает: correlation guard, regime, position sizing, open positions.
Phase 3: LLM-агент с доступом к portfolio state как tool.

TODO (ARCH Phase 3):
  - Correlation check: сколько открытых в том же направлении
  - Regime fitness: насколько сигнал подходит текущему режиму
  - Position sizing: Kelly criterion или fixed fraction
  - Drawdown check: не открывать при rolling WR < 30%
"""
import logging
from typing import Optional

from core.agents.base import BaseAgent, AgentContext, AgentResult

logger = logging.getLogger(__name__)


class RiskAgent(BaseAgent):
    """STUB: RiskAgent — оценка риска (Phase 3)."""

    def __init__(self, db_path: str = "subscriptions.db"):
        super().__init__("RiskAgent", db_path)

    async def run(self, ctx: AgentContext) -> Optional[AgentResult]:
        """
        STUB — Phase 3 реализация.

        Текущая логика (Phase 1-2):
          - Correlation Guard (DEV-14): max_positions_per_direction=5 в register_trade()
          - Rolling WR (DEV-27): wr_health_check_loop каждые 6ч
          - RR фильтр: min_rr_ratio=2.0 в register_trade()

        Phase 3: объединить в единый RiskAgent с LLM reasoning.

        TODO:
          1. Загрузить открытые позиции из БД
          2. Проверить корреляцию с текущим символом
          3. Вычислить оптимальный размер позиции
          4. Вернуть: {approved: bool, position_size_pct, reasoning}
        """
        logger.debug("RiskAgent.run: STUB для %s", ctx.symbol)
        return AgentResult(
            agent_name=self.name,
            action="pass",
            data={"approved": True, "position_size_pct": 1.0, "status": "not_implemented"},
            confidence=0.0,
            reasoning="RiskAgent реализуется в Phase 3",
        )
