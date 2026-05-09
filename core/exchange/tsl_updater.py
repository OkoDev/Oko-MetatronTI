"""
tsl_updater.py — обновление SL-ордеров на бирже при движении TSL.

Отвечает за один вопрос: "TradeSimulator сказал что TSL двинулся — обновить SL на бирже."
Вариант A: cancel старый SL-ордер + place новый STOP_MARKET.
"""
from __future__ import annotations

import asyncio
import logging

from core.trading.tsl_engine import is_side_valid

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
    # SL orderId не найден — bracket не создал SL. Ставим отдельным ордером.
    logger.warning("[TSL-UPDATER] trade #%d %s: SL orderId не найден → создаю SL-ордер вручную", trade_id, symbol)
    try:
        om = bot.order_executor
        trade = next((t for t in bot.trade_simulator.get_open_trades() if t.get("id") == trade_id), None)
        if trade:
            sl_price = float(trade.get("stop_loss") or 0)
            direction = trade.get("direction", "LONG")
            real_qty = await om.get_position_qty(symbol, pos_side)
            if sl_price > 0 and real_qty and real_qty > 0:
                sl_oid = await om.place_sl_order(symbol, pos_side, sl_price, real_qty)
                if sl_oid:
                    bot.trade_simulator.set_exchange_sl_order_id(trade_id, sl_oid)
                    logger.info("[TSL-UPDATER] trade #%d %s: SL-ордер создан вручную, order_id=%s", trade_id, symbol, sl_oid)
                    return
    except Exception as e:
        logger.warning("[TSL-UPDATER] trade #%d %s: ручное создание SL failed: %s", trade_id, symbol, e)


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
            # TSL-engine guard: проверяем new_sl до любых биржевых действий.
            # Защита от перевёрнутого SL (REAL #7264).
            try:
                _cur = await bot.data_collector.get_current_price(symbol)
            except Exception:
                _cur = None
            if _cur and not is_side_valid(direction, new_sl, float(_cur)):
                logger.warning(
                    "[TSL-UPDATER] #%d %s %s: skip — new_sl=%.6f на неверной стороне от price=%.6f",
                    trade_id, symbol, pos_side, new_sl, float(_cur),
                )
                continue

            # Шаг 1: получаем SL orderId если нет
            if not sl_oid:
                sl_oid = await om.get_sl_order_id(symbol, pos_side)
                if sl_oid:
                    ts.set_exchange_sl_order_id(trade_id, sl_oid)
                else:
                    # SL-ордер отсутствует — создаём новый
                    real_qty = await om.get_position_qty(symbol, pos_side)
                    if real_qty and real_qty > 0:
                        new_oid = await om.place_sl_order(symbol, pos_side, new_sl, real_qty)
                        if new_oid:
                            ts.set_exchange_sl_order_id(trade_id, new_oid)
                            logger.info("[TSL-UPDATER] #%d %s: SL создан (не было) sl=%.6f order_id=%s",
                                        trade_id, symbol, new_sl, new_oid)
                        else:
                            logger.warning("[TSL-UPDATER] #%d %s: не удалось создать SL", trade_id, symbol)
                    else:
                        logger.warning("[TSL-UPDATER] #%d %s: нет SL orderId и qty=0 — ORPHAN", trade_id, symbol)
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
            else:
                # update_sl не вернул ID — возможны 2 случая:
                #   (a) DEV-160 guard / min_move_pct skip — старый SL жив, ID в DB корректный
                #   (b) cancel прошёл, place_sl_order упал — старый SL мёртв, DB держит stale ID
                # Проверяем биржу: если SL там есть — просто лог, иначе чистим DB
                # чтобы repair_missing_sl восстановил на следующем цикле.
                live_oid = await om.get_sl_order_id(symbol, pos_side)
                if not live_oid:
                    ts.set_exchange_sl_order_id(trade_id, "")
                    logger.warning(
                        "[TSL-UPDATER] #%d %s: update_sl вернул None и SL отсутствует на бирже — "
                        "DB exchange_sl_order_id очищен (repair восстановит)",
                        trade_id, symbol,
                    )
                elif live_oid != sl_oid:
                    ts.set_exchange_sl_order_id(trade_id, live_oid)

        except Exception as e:
            logger.warning("[TSL-UPDATER] #%d %s: %s", trade_id, symbol, e)


async def repair_missing_tp(bot) -> None:
    """
    Находит OPEN VST-сделки без exchange_tp_order_id и ставит TAKE_PROFIT_MARKET на бирже.
    Вызывается каждый цикл trade_tracker (60 сек), по аналогии с repair_missing_sl.

    Причина: BingX placeOrder response НЕ возвращает TP orderId даже при bracket-ордере
    (проверено по офиц. docs 24.04.2026). TP-ордера создаются биржей, но их ID
    в нашу БД не попадают → нужно подбирать post-factum через get_open_orders.
    Без этого сделка доходит до TP, но не фиксирует прибыль на бирже.
    """
    om = bot.order_executor
    ts = bot.trade_simulator

    for trade in ts.get_open_trades():
        if not trade.get("exchange_order_id"):
            continue  # SIM-only

        trade_id = trade["id"]
        symbol = trade.get("symbol", "")
        direction = trade.get("direction", "LONG")
        tp_price = float(trade.get("take_profit") or 0)
        pos_side = "LONG" if direction == "LONG" else "SHORT"
        db_tp_oid = trade.get("exchange_tp_order_id") or ""

        if tp_price <= 0:
            continue

        try:
            live_tp_oid = await om.get_tp_order_id(symbol, pos_side)
            if live_tp_oid:
                if live_tp_oid != db_tp_oid:
                    ts.set_exchange_tp_order_id(trade_id, live_tp_oid)
                    logger.info("[REPAIR-TP] #%d %s: TP синхронизирован DB→%s (было %s)",
                                trade_id, symbol, live_tp_oid, db_tp_oid or "∅")
                continue

            # На бирже TP нет. Если в DB был stale ID — чистим.
            if db_tp_oid:
                ts.set_exchange_tp_order_id(trade_id, "")
                logger.warning("[REPAIR-TP] #%d %s: stale exchange_tp_order_id=%s (на бирже TP отсутствует)",
                               trade_id, symbol, db_tp_oid)

            real_qty = await om.get_position_qty(symbol, pos_side)
            if not real_qty or real_qty <= 0:
                logger.debug("[REPAIR-TP] #%d %s: qty=0 на бирже — orphan, пропуск", trade_id, symbol)
                continue

            # Sanity: TP должен быть по верной стороне от текущей цены.
            try:
                cur_price = await bot.data_collector.get_current_price(symbol)
            except Exception:
                cur_price = None
            if cur_price:
                cp = float(cur_price)
                wrong_side = (direction == "LONG" and tp_price <= cp) or (direction == "SHORT" and tp_price >= cp)
                if wrong_side:
                    logger.warning(
                        "[REPAIR-TP] #%d %s %s: skip place_tp_order — TP=%.6f уже пройден ценой %.6f",
                        trade_id, symbol, pos_side, tp_price, cp,
                    )
                    continue

            new_oid = await om.place_tp_order(symbol, pos_side, tp_price, real_qty)
            if new_oid:
                ts.set_exchange_tp_order_id(trade_id, new_oid)
                logger.info("[REPAIR-TP] #%d %s %s: TP создан @ %.6f order_id=%s",
                            trade_id, symbol, pos_side, tp_price, new_oid)
            else:
                logger.warning("[REPAIR-TP] #%d %s: place_tp_order вернул None", trade_id, symbol)
        except Exception as e:
            logger.warning("[REPAIR-TP] #%d %s: %s", trade_id, symbol, e)


async def repair_missing_sl(bot) -> None:
    """
    Находит OPEN VST-сделки без exchange_sl_order_id и ставит SL-ордер на бирже.
    Вызывается каждый цикл trade_tracker (60 сек).
    """
    om = bot.order_executor
    ts = bot.trade_simulator

    for trade in ts.get_open_trades():
        if not trade.get("exchange_order_id"):
            continue  # SIM-only

        trade_id = trade["id"]
        symbol = trade.get("symbol", "")
        direction = trade.get("direction", "LONG")
        sl_price = float(trade.get("stop_loss") or 0)
        pos_side = "LONG" if direction == "LONG" else "SHORT"
        db_sl_oid = trade.get("exchange_sl_order_id") or ""

        if sl_price <= 0:
            continue

        try:
            # Биржа — источник истины. Не доверяем DB exchange_sl_order_id
            # (может указывать на уже отменённый ордер после неудачного TSL update).
            live_sl_oid = await om.get_sl_order_id(symbol, pos_side)
            if live_sl_oid:
                # На бирже SL есть. Синхронизируем DB если ID разошёлся.
                if live_sl_oid != db_sl_oid:
                    ts.set_exchange_sl_order_id(trade_id, live_sl_oid)
                    logger.info("[REPAIR-SL] #%d %s: SL синхронизирован DB→%s (было %s)",
                                trade_id, symbol, live_sl_oid, db_sl_oid or "∅")
                continue

            # На бирже SL нет. Если в DB был stale ID — чистим, чтобы не вводить в заблуждение.
            if db_sl_oid:
                ts.set_exchange_sl_order_id(trade_id, "")
                logger.warning("[REPAIR-SL] #%d %s: stale exchange_sl_order_id=%s (на бирже SL отсутствует)",
                               trade_id, symbol, db_sl_oid)

            real_qty = await om.get_position_qty(symbol, pos_side)
            if not real_qty or real_qty <= 0:
                logger.debug("[REPAIR-SL] #%d %s: qty=0 на бирже — orphan, пропуск", trade_id, symbol)
                continue

            # TSL-engine guard: не шлём перевёрнутый SL на биржу.
            # REAL #7264 (19.04.2026): SHORT SL записывался ниже entry → биржа отвергала
            # `Stop Loss price should be greater than the current price`.
            try:
                cur_price = await bot.data_collector.get_current_price(symbol)
            except Exception:
                cur_price = None
            if cur_price and not is_side_valid(direction, sl_price, float(cur_price)):
                logger.warning(
                    "[REPAIR-SL] #%d %s %s: skip place_sl_order — SL=%.6f на неверной стороне от price=%.6f",
                    trade_id, symbol, pos_side, sl_price, float(cur_price),
                )
                continue

            new_oid = await om.place_sl_order(symbol, pos_side, sl_price, real_qty)
            if new_oid:
                ts.set_exchange_sl_order_id(trade_id, new_oid)
                logger.info("[REPAIR-SL] #%d %s %s: SL создан @ %.6f order_id=%s",
                            trade_id, symbol, pos_side, sl_price, new_oid)
            else:
                logger.warning("[REPAIR-SL] #%d %s: place_sl_order вернул None", trade_id, symbol)
        except Exception as e:
            logger.warning("[REPAIR-SL] #%d %s: %s", trade_id, symbol, e)
