"""
TriggerLoop — DEV-95 / ARCH-61. asyncio task, запускать рядом со scan_loop.

Лёгкий event-driven цикл: проверяет только «горячие» пары из PairContextBus.
Не дублирует полный скан — только OTE re-entry и Cascade триггеры.

DEV-129: PivotTouchTrigger — проверяет R1/R2/S1/S2 на 1D/1W для всех monitored пар.
Shadow mode — логирует WOULD_FIRE, не слать сигнал пока shadow=true.

Регистрация в боте (bot/core/bot.py):
    asyncio.create_task(run_trigger_loop(bot))
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger("trigger_loop")
TRIGGER_INTERVAL = 120  # 2 минуты


async def run_trigger_loop(bot) -> None:
    from core.context.trigger_bus import OteReentryTrigger, CascadeTrigger, PivotTouchTrigger
    cfg         = bot.config
    ctx         = getattr(bot, "pair_context", None)
    shadow_mode = bool(cfg.get("trigger_bus.shadow", True))
    min_cascade = int(cfg.get("trigger_bus.cascade_min", 3))
    # DEV-129: pivot touch threshold (default 0.3%)
    pivot_threshold = float(cfg.get("trigger_bus.pivot_touch_threshold_pct", 0.003))

    if ctx is None:
        logger.warning("[TriggerLoop] PairContextBus не инициализирован — loop не запущен")
        return

    pivot_trigger = PivotTouchTrigger(threshold_pct=pivot_threshold, cooldown_minutes=60)
    triggers = [OteReentryTrigger(), CascadeTrigger(min_cascade=min_cascade)]
    logger.info("[TriggerLoop] старт shadow=%s interval=%ds pivot_threshold=%.2f%%",
                shadow_mode, TRIGGER_INTERVAL, pivot_threshold * 100)

    while True:
        try:
            await _run_one_iteration(bot, ctx, triggers, pivot_trigger, shadow_mode)
        except asyncio.CancelledError:
            logger.info("[TriggerLoop] остановлен")
            break
        except Exception as e:
            logger.warning("[TriggerLoop] ошибка: %s", e)
        await asyncio.sleep(TRIGGER_INTERVAL)


async def _run_one_iteration(bot, ctx, triggers, pivot_trigger, shadow_mode: bool) -> None:
    # ── OTE/Cascade: только hot_symbols из PairContextBus ──────────────────
    hot_symbols = ctx.symbols_with_post_tsl()

    prices: dict[str, float] = {}
    if hot_symbols:
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

    # ── DEV-129: PivotTouchTrigger — все monitored пары ───────────────────
    await _check_pivot_touches(bot, ctx, pivot_trigger, shadow_mode)


async def _check_pivot_touches(bot, ctx, pivot_trigger, shadow_mode: bool) -> None:
    """
    DEV-129: проверяет R1/R2/S1/S2 на 1D/1W для всех мониторируемых пар.
    Pivot_snap берётся из кеша pivot_calculator (не делает лишних запросов к бирже).
    """
    pivot_calc = getattr(bot, "pivot_calculator", None)
    if pivot_calc is None:
        return

    # Берём все пары из pivot_cache (они уже прогреты scan_loop-ом)
    pivot_cache = getattr(pivot_calc, "pivot_cache", {})
    if not pivot_cache:
        return

    # Собираем уникальные символы из кеша
    symbols_in_cache = set()
    for key in pivot_cache:
        # Формат ключа: "BTC/USDT:USDT_1D" или "BTC/USDT_1W"
        parts = key.rsplit("_", 1)
        if len(parts) == 2 and parts[1] in ("1D", "1W", "1M"):
            symbols_in_cache.add(parts[0])

    if not symbols_in_cache:
        return

    # Ограничиваем: максимум 50 пар за итерацию (не создавать лавину запросов)
    symbols_to_check = list(symbols_in_cache)[:50]

    for sym in symbols_to_check:
        try:
            # Цена из data_collector (кешировано)
            ticker = await bot.data_collector.get_ticker(sym)
            if not ticker:
                continue
            current_price = float(ticker.get("last") or ticker.get("close") or 0)
            if current_price <= 0:
                continue

            # Собираем pivot_snap из кеша (нет лишних I/O)
            pivot_snap: Dict = {}
            for tf in ("1D", "1W"):
                cache_key = f"{sym}_{tf}"
                cached = pivot_cache.get(cache_key)
                if cached and isinstance(cached, dict):
                    pivot_snap[tf] = {
                        k: cached.get(k)
                        for k in ("R1", "R2", "R3", "S1", "S2", "S3", "PP")
                        if cached.get(k)
                    }

            if not pivot_snap:
                continue

            state = ctx.get(sym)
            result = pivot_trigger.check(sym, current_price, state, pivot_snap=pivot_snap)

            if result.fired:
                if shadow_mode:
                    logger.info(
                        "[TriggerLoop][DEV-129][SHADOW] %s PIVOT_TOUCH WOULD_FIRE: %s",
                        sym, result.reason,
                    )
                else:
                    logger.info(
                        "[TriggerLoop][DEV-129] %s PIVOT_TOUCH → analyze: %s",
                        sym, result.reason,
                    )
                    await _fire_analysis(bot, sym, "pivot_touch")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("[TriggerLoop][DEV-129] %s error: %s", sym, e)


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
