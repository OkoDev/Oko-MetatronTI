"""
OrderReconciler — DEV-145.

Запускается при старте бота. Сверяет live_orders с биржей через BingXClient.

Использование (bot/core/bot.py):
    await bot.order_reconciler.reconcile()
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.trading.position_manager import PositionManager
    from core.exchange.order_manager import OrderManager

logger = logging.getLogger(__name__)


class OrderReconciler:
    """
    Reconciliation при рестарте: находит позиции закрытые пока бот был offline.

    SIM_ONLY: только логирует кол-во OPEN записей, биржу не трогает.
    VST/LIVE: вызывает PositionManager.sync_with_exchange(order_manager).
    """

    def __init__(
        self,
        position_manager: "PositionManager",
        order_manager:    "OrderManager",
        execution_mode:   str = "sim_only",
    ) -> None:
        self._pm   = position_manager
        self._om   = order_manager
        self._mode = execution_mode

    async def reconcile(self) -> dict:
        """
        Запускает синхронизацию live_orders с биржей.

        Returns:
            {"ok": N, "closed": M, "mode": str}
        """
        if self._mode == "sim_only":
            open_cnt = len(self._pm.get_open_positions())
            logger.debug("[OrderReconciler][SIM] open_positions=%d", open_cnt)
            return {"ok": open_cnt, "closed": 0, "mode": self._mode}

        # VST / LIVE
        logger.info("[OrderReconciler][%s] синхронизация live_orders с биржей...", self._mode.upper())
        stats = await self._pm.sync_with_exchange(self._om)
        stats["mode"] = self._mode

        if stats.get("closed", 0):
            logger.warning(
                "[OrderReconciler] %d позиций закрыты пока бот был offline — "
                "статус SL/TP будет уточнён при следующем цикле position_sync",
                stats["closed"],
            )
        return stats
