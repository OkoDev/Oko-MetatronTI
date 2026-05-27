"""
trade_tracker_loop — фоновый цикл трекинга открытых сделок.

Отвечает ТОЛЬКО за симуляторную логику: TSL, SL/TP, безубыток.
Весь биржевой код живёт в core/exchange/:
  - position_sync.py  → sync_positions
  - tsl_updater.py    → update_tsl_on_exchange
"""
import asyncio
import logging

from core.exchange.position_sync import sync_positions
from core.exchange.tsl_updater import update_tsl_on_exchange, repair_missing_sl, repair_missing_tp
from core.infra.trading_settings import is_live as _is_live_fn

logger = logging.getLogger(__name__)


async def trade_tracker_loop(bot) -> None:
    """Каждые 60 сек:
    1. VST/LIVE: sync биржи → симулятор (position_sync)
    2. Симулятор: TSL/SL/TP/BE трекинг (check_open_trades_with_tsl)
    3. VST/LIVE: обновить SL на бирже если TSL двинулся (tsl_updater)
    """
    use_tsl                = bot.config.get("trading.use_tsl", True)
    tsl_activation_r       = bot.config.get("trading.tsl_activation_r", 1.0)
    use_breakeven          = bot.config.get("trading.use_breakeven", False)
    breakeven_activation_r = bot.config.get("trading.breakeven_activation_r", 0.5)
    use_be_after_tp1       = bot.config.get("trading.use_be_after_tp1", False)
    cascade_tsl            = bot.config.get("trading.cascade_tsl", True)

    _is_live = _is_live_fn(bot.config)

    while True:
        try:
            await asyncio.sleep(60)

            # ── Шаг 1: биржевой sync (VST/LIVE only) ──────────────────────
            if _is_live:
                await sync_positions(bot)

            # ── Шаг 1.5: repair — поставить SL/TP на бирже для сделок без него
            if _is_live and hasattr(bot, "order_executor"):
                await repair_missing_sl(bot)
                await repair_missing_tp(bot)

            # ── Шаг 2: симуляторный трекинг ───────────────────────────────
            closed, tsl_moved = await bot.trade_simulator.check_open_trades_with_tsl(
                bot.data_collector,
                use_tsl=use_tsl,
                tsl_activation_r=tsl_activation_r,
                use_breakeven=use_breakeven,
                breakeven_activation_r=breakeven_activation_r,
                use_be_after_tp1=use_be_after_tp1,
                cascade_tsl=cascade_tsl,
            )
            if closed > 0:
                logger.info("TradeSimulator: закрыто сделок за цикл: %d", closed)

            # ── Шаг 3: обновить SL на бирже (VST/LIVE only) ───────────────
            if _is_live and tsl_moved and hasattr(bot, "order_executor"):
                await update_tsl_on_exchange(bot, tsl_moved)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("trade_tracker_loop: %s", e)
