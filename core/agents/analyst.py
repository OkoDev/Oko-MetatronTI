"""
AnalystAgent — LLM-разбор закрытых сделок.

Тонкая обёртка над TradeAnalyzer (DEV-15).
Phase 3: расширить до weekly digest, pattern recognition, рекомендаций.

TODO (ARCH Phase 3):
  - Собирать SL-сделки за неделю → batch анализ
  - Выявлять паттерны: "каждый понедельник SHORT при RANGE бьёт SL"
  - Генерировать рекомендации по корректировке конфига
"""
import logging
from typing import Optional

from core.agents.base import BaseAgent, AgentContext, AgentResult

logger = logging.getLogger(__name__)


class AnalystAgent(BaseAgent):
    """Обёртка над TradeAnalyzer (DEV-15) как агент."""

    def __init__(self, db_path: str = "subscriptions.db"):
        super().__init__("AnalystAgent", db_path)
        self._analyzer = None

    def _get_analyzer(self):
        if self._analyzer is None:
            try:
                from core.trade_analyzer import TradeAnalyzer
                self._analyzer = TradeAnalyzer(self.db_path)
            except Exception as e:
                logger.debug("AnalystAgent: TradeAnalyzer недоступен — %s", e)
        return self._analyzer

    async def run(self, ctx: AgentContext) -> Optional[AgentResult]:
        """Анализирует SL-сделку если trade_id передан в ctx.state."""
        trade_id = ctx.state.get("trade_id")
        if not trade_id:
            return None

        analyzer = self._get_analyzer()
        if analyzer is None:
            return AgentResult(
                agent_name=self.name,
                action="pass",
                data={"error": "TradeAnalyzer недоступен"},
                confidence=0.0,
            )

        analysis = await analyzer.analyze_sl_trade(trade_id)
        if analysis:
            return AgentResult(
                agent_name=self.name,
                action="analysis",
                data={"trade_id": trade_id, "analysis": analysis},
                confidence=0.8,
                reasoning=analysis[:200],
            )
        return None
