"""
OrderReconciler — DEV-78.

Запускается при старте бота. Сверяет live_orders с биржей и разрешает расхождения.

Использование (bot/core/bot.py):
    await bot.order_reconciler.reconcile()
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.trading.position_manager import PositionManager
    from core.data_collector import RealTimeData

logger = logging.getLogger(__name__)


class OrderReconciler:
    """
    Reconciliation при рестарте: находит ORPHAN позиции и логирует для ревью.

    SIM_ONLY: только логирует, не трогает биржу.
    VST/LIVE: вызывает PositionManager.sync_with_exchange().
    """

    def __init__(
        self,
        position_manager: "PositionManager",
        data_collector:   "RealTimeData",
        execution_mode:   str = "sim_only",
    ) -> None:
        self._pm   = position_manager
        self._dc   = data_collector
        self._mode = execution_mode

    async def reconcile(self) -> dict:
        """
        Запускает синхронизацию.

        Returns:
            {"ok": N, "orphan": M, "mode": str}
        """
        if self._mode == "sim_only":
            # SIM: orphan не бывает (нет реальных ордеров)
            orphans = self._pm.get_orphans()
            if orphans:
                logger.warning("[OrderReconciler][SIM] %d orphan записей в БД — очистите вручную",
                               len(orphans))
            open_cnt = len(self._pm.get_open_positions())
            logger.debug("[OrderReconciler][SIM] open_positions=%d", open_cnt)
            return {"ok": open_cnt, "orphan": len(orphans), "mode": self._mode}

        # VST / LIVE
        logger.info("[OrderReconciler][%s] синхронизация с биржей...", self._mode.upper())
        stats = await self._pm.sync_with_exchange(self._dc)
        stats["mode"] = self._mode

        orphans = self._pm.get_orphans()
        if orphans:
            logger.warning(
                "[OrderReconciler] %d ORPHAN позиций — закрыты пока бот был offline: %s",
                len(orphans),
                [f"{o.symbol} id={o.id}" for o in orphans],
            )
        return stats
