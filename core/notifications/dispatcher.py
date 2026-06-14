"""
NotificationDispatcher — единый вход для всех SMC-уведомлений.

scan_loop → await bot.notif_dispatcher.on_smc_snap(sym, snap)   # 1 строка
                  │
    ┌─────────────┼──────────────┐
    ▼             ▼              ▼
FvgListener  FvgTouchListener  (ObListener / OteListener / ChochListener — будущие)

Добавить новое уведомление:
  1. Правило в config/notifications.yaml → enabled: true
  2. Новый Listener(BaseListener) в этом файле → 20-30 строк
  3. Зарегистрировать в NotificationDispatcher.__init__
  scan_loop НЕ меняется.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bot.notifications.sender import notify

logger = logging.getLogger(__name__)


# ─── Base ──────────────────────────────────────────────────────────────────────

class BaseListener:
    """Интерфейс listener'а. Реализует check(bot, symbol, snap, rule)."""

    async def check(self, bot: Any, symbol: str, snap: dict, rule: dict) -> None:
        raise NotImplementedError


# ─── FVG listeners ─────────────────────────────────────────────────────────────

class FvgDetectedListener(BaseListener):
    """fvg_detected: шлёт уведомление при появлении нового FVG (не было в прошлом цикле)."""

    async def check(self, bot: Any, symbol: str, snap: dict, rule: dict) -> None:
        _prev_key = f"_prev_fvg_ids_{symbol}"
        prev_ids: set = getattr(bot, _prev_key, set())
        new_ids: set = set()

        for fvg_list, direction, emoji in [
            (snap.get("bull_fvg_active", []), "LONG", "\U0001f7e2"),
            (snap.get("bear_fvg_active", []), "SHORT", "\U0001f534"),
        ]:
            for fvg in fvg_list:
                top = fvg.get("top", 0)
                bottom = fvg.get("bottom", 0)
                if abs(top - bottom) < 1e-10:
                    continue
                fid = (round(bottom, 8), round(top, 8), fvg.get("tf", ""))
                new_ids.add(fid)
                if fid not in prev_ids:
                    asyncio.create_task(notify(
                        bot, "fvg_detected", symbol,
                        direction=direction, tf=fvg.get("tf", ""),
                        bottom=bottom, top=top, dir_emoji=emoji,
                    ))

        setattr(bot, _prev_key, new_ids)


class FvgTouchListener(BaseListener):
    """fvg_touch: цена вошла внутрь активной FVG-зоны."""

    async def check(self, bot: Any, symbol: str, snap: dict, rule: dict) -> None:
        current_price = snap.get("_current_price")
        if not (current_price and current_price > 0):
            return

        for fvg_list, direction, emoji in [
            (snap.get("bull_fvg_active", []), "LONG", "\U0001f7e2"),
            (snap.get("bear_fvg_active", []), "SHORT", "\U0001f534"),
        ]:
            for fvg in fvg_list:
                top = fvg.get("top", 0)
                bottom = fvg.get("bottom", 0)
                if top <= 0 or bottom <= 0 or top <= bottom:
                    continue
                if bottom <= current_price <= top:
                    asyncio.create_task(notify(
                        bot, "fvg_touch", symbol,
                        direction=direction, tf=fvg.get("tf", ""),
                        bottom=bottom, top=top, price=current_price, dir_emoji=emoji,
                    ))


# ─── Dispatcher ────────────────────────────────────────────────────────────────

class NotificationDispatcher:
    """Единый вход. scan_loop вызывает on_smc_snap — dispatcher маршрутизирует по listener'ам."""

    def __init__(self, bot: Any):
        self.bot = bot
        self._listeners: dict[str, BaseListener] = {
            "fvg_detected": FvgDetectedListener(),
            "fvg_touch":    FvgTouchListener(),
            # TIER-2 будущие: ObListener, OteListener, ChochListener, PivotListener
        }

    async def on_smc_snap(self, symbol: str, snap: dict) -> None:
        """Вызывается из scan_loop 1 раз на пару после compute_and_publish SMC snap."""
        from core.notifications.notif_config import notif_config
        notif_cfg = notif_config.get("notifications", {})
        if not notif_cfg.get("enabled", False):
            return

        rules = notif_cfg.get("rules", {})
        for name, listener in self._listeners.items():
            rule = rules.get(name, {})
            if not rule.get("enabled", False):
                continue
            try:
                await listener.check(self.bot, symbol, snap, rule)
            except Exception as e:
                logger.debug("[NOTIF] listener %s %s: %s", name, symbol, e)
