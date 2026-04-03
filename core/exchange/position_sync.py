"""
position_sync.py — синхронизация биржевых позиций с TradeSimulator.

Отвечает за один вопрос: "Какие позиции закрылись на бирже пока бот не смотрел?"
Единственный модуль, который одновременно смотрит на биржу и на симулятор.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.exchange.bingx_client import make_client

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def sync_positions(bot) -> None:
    """
    Сравнивает открытые позиции на бирже с открытыми сделками в симуляторе.
    Если сделка есть в симуляторе (с exchange_order_id), но позиции нет на бирже
    — значит биржа закрыла позицию по SL/TP. Закрываем и в симуляторе.

    Вызывается только в VST/LIVE режиме из exchange_loop каждые 60 сек.
    SIM-сделки (exchange_order_id IS NULL) не трогает.
    """
    try:
        mode = bot.config.get("trading.execution_mode", "sim_only")
        client = make_client(mode, bot.config)
        if client is None:
            return

        # Получаем открытые позиции на бирже
        positions = await client.get_positions()
        open_on_exchange: dict = {}
        for p in positions:
            sym_raw = p.get("symbol", "")  # "BTC-USDT"
            qty = float(p.get("positionAmt") or p.get("availableAmt") or 0)
            if qty != 0:
                sym_our = sym_raw.replace("-", "/") + ":USDT"
                open_on_exchange[sym_our] = p

        # Проверяем только сделки с реальным ордером на бирже
        open_sim = bot.trade_simulator.get_open_trades()
        synced = 0

        for trade in open_sim:
            if not trade.get("exchange_order_id"):
                continue  # SIM-сделка — не трогаем

            sym      = trade.get("symbol", "")
            trade_id = trade.get("id")

            if sym not in open_on_exchange:
                # Позиции нет на бирже — закрылась по SL/TP
                try:
                    cur_price = (await bot.data_collector.get_current_price(sym)
                                 or float(trade.get("entry_price", 0)))

                    # Определяем статус по текущей цене vs SL
                    entry     = float(trade.get("entry_price") or 0)
                    sl        = float(trade.get("stop_loss")   or 0)
                    direction = trade.get("direction", "LONG")

                    if entry and sl and cur_price:
                        if direction == "LONG":
                            status = "SL" if cur_price <= sl * 1.002 else "TP"
                        else:
                            status = "SL" if cur_price >= sl * 0.998 else "TP"
                    else:
                        status = "TP"

                    bot.trade_simulator.close_trade(trade_id, status, cur_price)
                    logger.info("[POSITION-SYNC] #%d %s %s → %s @ %.6f (биржа закрыла)",
                                trade_id, sym, direction, status, cur_price)
                    synced += 1
                except Exception as e:
                    logger.warning("[POSITION-SYNC] close_trade #%d error: %s", trade_id, e)

        if synced:
            logger.info("[POSITION-SYNC] синхронизировано %d закрытых позиций", synced)

    except Exception as e:
        logger.warning("[POSITION-SYNC] ошибка: %s", e)
