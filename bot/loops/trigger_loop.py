"""
TriggerLoop — DEV-95 / ARCH-61. asyncio task, запускать рядом со scan_loop.

Лёгкий event-driven цикл: проверяет только «горячие» пары из PairContextBus.
Не дублирует полный скан — только OTE re-entry и Cascade триггеры.

Регистрация в боте (bot/core/bot.py):
    asyncio.create_task(run_trigger_loop(bot))
"""
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("trigger_loop")
TRIGGER_INTERVAL = 120  # 2 минуты


async def run_trigger_loop(bot) -> None:
    from core.context.trigger_bus import OteReentryTrigger, CascadeTrigger
    cfg         = bot.config
    ctx         = getattr(bot, "pair_context", None)
    shadow_mode = bool(cfg.get("trigger_bus.shadow", True))
    min_cascade = int(cfg.get("trigger_bus.cascade_min", 3))

    if ctx is None:
        logger.warning("[TriggerLoop] PairContextBus не инициализирован — loop не запущен")
        return

    triggers = [OteReentryTrigger(), CascadeTrigger(min_cascade=min_cascade)]
    logger.info("[TriggerLoop] старт shadow=%s interval=%ds", shadow_mode, TRIGGER_INTERVAL)

    while True:
        try:
            await _run_one_iteration(bot, ctx, triggers, shadow_mode)
        except asyncio.CancelledError:
            logger.info("[TriggerLoop] остановлен")
            break
        except Exception as e:
            logger.warning("[TriggerLoop] ошибка: %s", e)
        await asyncio.sleep(TRIGGER_INTERVAL)


async def _run_one_iteration(bot, ctx, triggers, shadow_mode: bool) -> None:
    hot_symbols = ctx.symbols_with_post_tsl()
    if not hot_symbols:
        return

    # Цены пакетом (один get_ticker на символ за итерацию)
    prices: dict[str, float] = {}
    for sym in hot_symbols:
        try:
            ticker = await bot.data_collector.get_ticker(sym)
            if ticker and ticker.get("last"):
                prices[sym] = float(ticker["last"])
        except Exception:
            pass

    for sym in hot_symbols:
        price = prices.get(sym)
        if price is None:
            continue
        state = ctx.get(sym)

        for trigger in triggers:
            # TTL инвалидация OTE зоны
            if trigger.name == "ote_reentry" and state.post_tsl_data:
                d = state.post_tsl_data
                elapsed_h = (datetime.now(timezone.utc) - d["exit_time"]).total_seconds() / 3600
                if elapsed_h > d["ttl_hours"]:
                    ctx.update(sym, post_tsl_data=None)
                    logger.info("[TriggerLoop] %s OTE TTL expired (%.1fh)", sym, elapsed_h)
                    continue

            result = trigger.check(sym, price, state)
            if result.fired:
                if shadow_mode:
                    logger.info("[TriggerLoop][SHADOW] %s trigger=%s %s → would_analyze",
                                sym, trigger.name, result.reason)
                else:
                    logger.info("[TriggerLoop] %s trigger=%s %s → analyze",
                                sym, trigger.name, result.reason)
                    await _fire_analysis(bot, sym, trigger.name)
                break  # Guardrail: один trigger за итерацию на символ


async def _fire_analysis(bot, symbol: str, trigger_name: str) -> None:
    """
    Тонкая обёртка: analyze_symbol → register_trade_async.
    Не дублирует broadcast — только регистрирует сделку если сигнал actionable.
    """
    try:
        recommendation = await bot.trading_intelligence.analyze_symbol(symbol)
        if recommendation is None:
            return
        action = getattr(recommendation, "action", "WATCH")
        strength = getattr(recommendation, "overall_strength", 0)
        direction = getattr(recommendation.direction, "value", "NEUTRAL") if recommendation.direction else "NEUTRAL"
        min_str = int(bot.config.get("signal_quality.min_strength", 50))
        if action in ("BUY", "SELL") and direction != "NEUTRAL" and strength >= min_str:
            trade_id = await bot.trade_simulator.register_trade_async(
                recommendation, bot.data_collector,
                extra_features={"trigger_source": trigger_name},
            )
            if trade_id:
                logger.info("[TriggerLoop] %s trigger=%s → trade_id=%d strength=%d",
                            symbol, trigger_name, trade_id, strength)
    except Exception as e:
        logger.warning("[TriggerLoop] _fire_analysis %s: %s", symbol, e)
