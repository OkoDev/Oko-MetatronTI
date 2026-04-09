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
    Retry 3 раза с паузой 2 сек: BingX иногда создаёт trigger-ордера за 3-5 сек.
    Запускается через asyncio.create_task() сразу после open_bracket().
    """
    for attempt in (1, 2, 3):
        await asyncio.sleep(2)
        try:
            sl_order_id = await bot.order_executor.get_sl_order_id(symbol, pos_side)
            if sl_order_id:
                bot.trade_simulator.set_exchange_sl_order_id(trade_id, sl_order_id)
                logger.info("[TSL-UPDATER] trade #%d %s %s → exchange_sl_order_id=%s (attempt %d)",
                            trade_id, symbol, pos_side, sl_order_id, attempt)
                return
        except Exception as e:
            logger.debug("[TSL-UPDATER] fetch_and_save_sl_order_id #%d attempt %d: %s", trade_id, attempt, e)
    logger.warning("[TSL-UPDATER] trade #%d %s: SL orderId не найден на бирже после 3 попыток", trade_id, symbol)


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
            real_qty = await om.get_position_qty(symbol, pos_side)
            # ORPHAN: симулятор держит OPEN, но позиции на бирже нет (qty=0)
            # → закрываем в симуляторе как EXPIRED с текущей ценой (нет данных о SL/TP)
            if not real_qty:
                try:
                    cur_price = await bot.data_collector.get_current_price(symbol)
                except Exception:
                    cur_price = None
                if cur_price is None or cur_price <= 0:
                    cur_price = float(item.get("new_sl_price") or item.get("old_sl_price") or 0)
                logger.warning(
                    "[TSL-UPDATER] #%d %s: ORPHAN на бирже qty=0 → close_trade(EXPIRED) @ %.6f",
                    trade_id, symbol, cur_price,
                )
                try:
                    ts.close_trade(trade_id, "EXPIRED", float(cur_price))
                except Exception as _ce:
                    logger.warning("[TSL-UPDATER] #%d close_trade EXPIRED error: %s", trade_id, _ce)
                continue
            if not qty:
                qty = real_qty

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
