"""
Фоновый цикл трекинга открытых сделок: TSL, SL/TP, безубыток.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def trade_tracker_loop(bot) -> None:
    """Каждые 60 сек проверяет открытые сделки и закрывает их по SL/TP/TSL."""
    use_tsl = bot.config.get("trading.use_tsl", True)
    tsl_activation_r = bot.config.get("trading.tsl_activation_r", 1.0)
    use_breakeven = bot.config.get("trading.use_breakeven", True)
    breakeven_activation_r = bot.config.get("trading.breakeven_activation_r", 0.5)

    while True:
        try:
            await asyncio.sleep(60)
            closed = await bot.trade_simulator.check_open_trades_with_tsl(
                bot.data_collector,
                use_tsl=use_tsl,
                tsl_activation_r=tsl_activation_r,
                use_breakeven=use_breakeven,
                breakeven_activation_r=breakeven_activation_r,
            )
            if closed > 0:
                logger.info("TradeSimulator: закрыто сделок за цикл: %s", closed)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("TradeSimulator loop: %s", e)
