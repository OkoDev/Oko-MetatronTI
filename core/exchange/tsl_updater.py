"""
tsl_updater.py — обновление SL-ордеров на бирже при движении TSL.

Отвечает за один вопрос: "TradeSimulator сказал что TSL двинулся — обновить SL на бирже."
Вариант A: cancel старый SL-ордер + place новый STOP_MARKET.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def fetch_and_save_sl_order_id(bot, trade_id: int, symbol: str, pos_side: str) -> None:
    """
    После открытия bracket-ордера — получаем SL orderId с биржи и сохраняем в БД.
    Ждём 2 сек: биржа асинхронно создаёт trigger-ордера после MARKET fill.
    Запускается через asyncio.create_task() сразу после open_bracket().
    """
    await asyncio.sleep(2)
    try:
        sl_order_id = await bot.order_executor.get_sl_order_id(symbol, pos_side)
        if sl_order_id:
            bot.trade_simulator.set_exchange_sl_order_id(trade_id, sl_order_id)
            logger.info("[TSL-UPDATER] trade #%d %s %s → exchange_sl_order_id=%s",
                        trade_id, symbol, pos_side, sl_order_id)
        else:
            logger.warning("[TSL-UPDATER] trade #%d %s: SL orderId не найден на бирже", trade_id, symbol)
    except Exception as e:
        logger.warning("[TSL-UPDATER] fetch_and_save_sl_order_id #%d: %s", trade_id, e)


async def update_tsl_on_exchange(bot, tsl_moved: list) -> None:
    """
    Для каждой сделки из tsl_moved (TradeSimulator сообщил о движении TSL):
      1. Берём exchange_sl_order_id (или запрашиваем с биржи если нет)
      2. cancel_order → place_sl_order (через OrderManager)
      3. Сохраняем новый sl_order_id в БД
    Фильтр мелких движений: tsl_min_move_pct из config (default 0.15%).
    """
    om  = bot.order_executor    # OrderManager
    ts  = bot.trade_simulator   # TradeSimulator
    min_move_pct = float(bot.config.get("trading.tsl_min_move_pct", 0.15))

    for item in tsl_moved:
        trade_id  = item["trade_id"]
        symbol    = item["symbol"]
        direction = item["direction"]
        new_sl    = item["new_sl_price"]
        old_sl    = item["old_sl_price"]
        sl_oid    = item.get("exchange_sl_order_id")
        pos_side  = "LONG" if direction == "LONG" else "SHORT"

        try:
            # Шаг 1: получаем SL orderId если нет
            if not sl_oid:
                sl_oid = await om.get_sl_order_id(symbol, pos_side)
                if sl_oid:
                    ts.set_exchange_sl_order_id(trade_id, sl_oid)
                else:
                    logger.warning("[TSL-UPDATER] #%d %s: нет SL orderId — пропуск", trade_id, symbol)
                    continue

            # Шаг 2: qty для нового ордера
            qty = float(item.get("qty") or 0)
            if not qty:
                qty = await om.get_position_qty(symbol, pos_side)
            if not qty:
                logger.warning("[TSL-UPDATER] #%d %s: qty=0 — пропуск", trade_id, symbol)
                continue

            # Шаг 3: cancel + replace
            new_id = await om.update_sl(
                symbol=symbol, pos_side=pos_side,
                old_sl_order_id=sl_oid, new_sl_price=new_sl, qty=qty,
                old_sl_price=old_sl, min_move_pct=min_move_pct,
            )
            if new_id:
                ts.set_exchange_sl_order_id(trade_id, new_id)
                logger.info("[TSL-UPDATER] ✅ #%d %s: SL %.6f → %.6f (order_id=%s)",
                            trade_id, symbol, old_sl, new_sl, new_id)

        except Exception as e:
            logger.warning("[TSL-UPDATER] #%d %s: %s", trade_id, symbol, e)
