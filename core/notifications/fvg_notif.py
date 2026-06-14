"""
FVG уведомления: fvg_detected (новый FVG) + fvg_touch (цена в зоне).
Вызывается из scan_loop после build_smc_snapshot.
"""
import asyncio
from typing import Any, Optional

from bot.notifications.sender import notify


async def maybe_notify_fvg(bot: Any, symbol: str, smc_snap: dict,
                            current_price: Optional[float] = None) -> None:
    """fvg_detected (новые FVG) + fvg_touch (цена внутри зоны).

    symbol — ccxt-формат ("XLM/USDT:USDT"), evaluate нормализует в "XLM-USDT".
    """
    if not smc_snap:
        return

    # ── fvg_detected: отслеживаем новые FVG по сравнению с прошлым циклом ─
    _prev_key = f"_prev_fvg_ids_{symbol}"
    prev_ids: set = getattr(bot, _prev_key, set())
    new_ids: set = set()

    for fvg_list, direction, emoji in [
        (smc_snap.get("bull_fvg_active", []), "LONG", "🟢"),
        (smc_snap.get("bear_fvg_active", []), "SHORT", "🔴"),
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

    # ── fvg_touch: текущая цена внутри FVG-зоны ──────────────────────────
    if not (current_price and current_price > 0):
        return

    for fvg_list, direction, emoji in [
        (smc_snap.get("bull_fvg_active", []), "LONG", "🟢"),
        (smc_snap.get("bear_fvg_active", []), "SHORT", "🔴"),
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
