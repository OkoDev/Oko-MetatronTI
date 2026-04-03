"""
Фоновый цикл трекинга открытых сделок: TSL, SL/TP, безубыток.
VST/LIVE: sync_vst_positions() — синхронизирует с биржей каждые 60 сек.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def fetch_and_save_sl_order_id(bot, trade_id: int, symbol: str, pos_side: str) -> None:
    """После открытия bracket-ордера — получаем SL orderId и сохраняем в БД.
    Вызывается async через create_task, ждём 2 сек чтобы биржа успела создать ордер.
    """
    await asyncio.sleep(2)
    try:
        sl_order_id = await bot.order_executor.get_sl_order_id(symbol, pos_side)
        if sl_order_id:
            bot.trade_simulator.set_exchange_sl_order_id(trade_id, sl_order_id)
            logger.info("[VST-TSL] trade #%d %s %s → exchange_sl_order_id=%s",
                        trade_id, symbol, pos_side, sl_order_id)
        else:
            logger.warning("[VST-TSL] trade #%d %s: SL orderId не найден на бирже", trade_id, symbol)
    except Exception as e:
        logger.warning("[VST-TSL] fetch_and_save_sl_order_id #%d: %s", trade_id, e)


async def _update_tsl_on_exchange(bot, tsl_moved: list) -> None:
    """Обновляет SL-ордера на бирже при движении TSL (cancel + replace)."""
    oe = bot.order_executor
    ts = bot.trade_simulator
    tsl_min_move_pct = float(bot.config.get("trading.tsl_min_move_pct", 0.1))

    for item in tsl_moved:
        trade_id   = item["trade_id"]
        symbol     = item["symbol"]
        direction  = item["direction"]
        new_sl     = item["new_sl_price"]
        old_sl     = item["old_sl_price"]
        sl_oid     = item.get("exchange_sl_order_id")
        pos_side   = "LONG" if direction == "LONG" else "SHORT"

        try:
            if not sl_oid:
                # exchange_sl_order_id ещё не получен — попробуем получить сейчас
                sl_oid = await oe.get_sl_order_id(symbol, pos_side)
                if sl_oid:
                    ts.set_exchange_sl_order_id(trade_id, sl_oid)
                else:
                    logger.warning("[VST-TSL] #%d %s: нет SL orderId — пропуск", trade_id, symbol)
                    continue

            # qty нужен для нового ордера — берём из позиции на бирже
            qty = item.get("qty") or 0.0
            if not qty:
                # Запросим qty из open positions
                try:
                    from core.trading.order_executor import VST_BASE_URL, LIVE_BASE_URL
                    import os
                    mode = bot.config.get("trading.execution_mode", "sim_only")
                    if mode == "vst":
                        from core.trading.order_executor import _BingXClient
                        api_key = os.environ.get("BINGX_VST_API_KEY", "")
                        secret  = os.environ.get("BINGX_VST_SECRET_KEY", "")
                        base    = VST_BASE_URL
                    else:
                        from core.trading.order_executor import _BingXClient
                        api_key = os.environ.get("BINGX_API_KEY", "")
                        secret  = os.environ.get("BINGX_SECRET_KEY", "")
                        base    = LIVE_BASE_URL
                    client = _BingXClient(api_key, secret, base)
                    bx_sym = symbol.replace("/", "-").replace(":USDT", "")
                    pos_resp = await client._get("/openApi/swap/v2/user/positions")
                    for p in (pos_resp.get("data") or []):
                        if p.get("symbol") == bx_sym and p.get("positionSide", "").upper() == pos_side:
                            qty = float(p.get("positionAmt") or p.get("availableAmt") or 0)
                            break
                except Exception as _e:
                    logger.warning("[VST-TSL] #%d get qty error: %s", trade_id, _e)

            if not qty:
                logger.warning("[VST-TSL] #%d %s: qty=0, пропуск", trade_id, symbol)
                continue

            new_id = await oe.update_sl(
                symbol=symbol,
                pos_side=pos_side,
                old_sl_order_id=sl_oid,
                new_sl_price=new_sl,
                qty=qty,
                min_move_pct=tsl_min_move_pct,
                old_sl_price=old_sl,
            )
            if new_id:
                ts.set_exchange_sl_order_id(trade_id, new_id)
                logger.info("[VST-TSL] ✅ #%d %s: SL %.6f → %.6f (order_id=%s)",
                            trade_id, symbol, old_sl, new_sl, new_id)

        except Exception as e:
            logger.warning("[VST-TSL] _update_tsl_on_exchange #%d %s: %s", trade_id, symbol, e)


async def _sync_vst_positions(bot) -> None:
    """
    VST/LIVE sync: получаем открытые позиции с биржи и закрываем
    симулятор если позиция уже закрылась на бирже (SL/TP hit).
    """
    try:
        from core.trading.order_executor import _BingXClient, VST_BASE_URL, LIVE_BASE_URL
        import os
        mode = bot.config.get("trading.execution_mode", "sim_only")
        if mode == "vst":
            api_key = os.environ.get("BINGX_VST_API_KEY", "")
            secret  = os.environ.get("BINGX_VST_SECRET_KEY", "")
            base    = VST_BASE_URL
        else:
            api_key = os.environ.get("BINGX_API_KEY", "")
            secret  = os.environ.get("BINGX_SECRET_KEY", "")
            base    = LIVE_BASE_URL
        if not api_key:
            return

        client = _BingXClient(api_key, secret, base)

        # Получаем все открытые позиции с биржи
        resp = await client._get("/openApi/swap/v2/user/positions")
        if resp.get("code") != 0:
            logger.warning("[VST-SYNC] get positions error: %s", resp)
            return

        positions = resp.get("data", []) or []
        # Символы с ненулевым позиционным qty на бирже
        open_on_exchange = {}
        for p in positions:
            sym_raw = p.get("symbol", "")   # "BTC-USDT"
            qty = float(p.get("positionAmt") or p.get("availableAmt") or 0)
            if qty != 0:
                # Конвертируем обратно в наш формат
                sym_our = sym_raw.replace("-", "/") + ":USDT"
                open_on_exchange[sym_our] = p

        # Проверяем ТОЛЬКО сделки с реальным exchange_order_id (VST/LIVE ордера)
        # SIM-сделки (exchange_order_id IS NULL) синхронизировать не нужно
        open_sim = bot.trade_simulator.get_open_trades()
        synced = 0
        for trade in open_sim:
            # Пропускаем чистые SIM-сделки без реального ордера на бирже
            if not trade.get("exchange_order_id"):
                continue
            sym = trade.get("symbol", "")
            trade_id = trade.get("id")
            if sym not in open_on_exchange:
                # Позиции нет на бирже — значит закрылась по SL/TP
                # Получаем последнюю цену для записи exit_price
                try:
                    cur_price = await bot.data_collector.get_current_price(sym) or float(trade.get("entry_price", 0))
                    # Определяем статус: если цена ушла за SL → SL, иначе TP
                    entry  = float(trade.get("entry_price") or 0)
                    sl     = float(trade.get("stop_loss") or 0)
                    direction = trade.get("direction", "LONG")
                    if entry and sl and cur_price:
                        if direction == "LONG":
                            status = "SL" if cur_price <= sl * 1.002 else "TP"
                        else:
                            status = "SL" if cur_price >= sl * 0.998 else "TP"
                    else:
                        status = "TP"
                    bot.trade_simulator.close_trade(trade_id, status, cur_price)
                    logger.info("[VST-SYNC] #%d %s %s → %s @ %.6f (биржа закрыла)",
                                trade_id, sym, direction, status, cur_price)
                    synced += 1
                except Exception as e:
                    logger.warning("[VST-SYNC] close_trade #%d error: %s", trade_id, e)

        if synced:
            logger.info("[VST-SYNC] синхронизировано %d закрытых позиций", synced)

    except Exception as e:
        logger.warning("[VST-SYNC] ошибка синхронизации: %s", e)


async def trade_tracker_loop(bot) -> None:
    """Каждые 60 сек проверяет открытые сделки и закрывает их по SL/TP/TSL."""
    use_tsl = bot.config.get("trading.use_tsl", True)
    tsl_activation_r = bot.config.get("trading.tsl_activation_r", 1.0)
    use_breakeven = bot.config.get("trading.use_breakeven", False)
    breakeven_activation_r = bot.config.get("trading.breakeven_activation_r", 0.5)
    use_be_after_tp1 = bot.config.get("trading.use_be_after_tp1", False)
    cascade_tsl = bot.config.get("trading.cascade_tsl", True)

    _mode = bot.config.get("trading.execution_mode", "sim_only")
    _is_live = _mode in ("vst", "live")

    while True:
        try:
            await asyncio.sleep(60)

            # VST/LIVE: сначала синхронизируем с биржей
            if _is_live:
                await _sync_vst_positions(bot)

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
                logger.info("TradeSimulator: закрыто сделок за цикл: %s", closed)

            # VST/LIVE: обновляем SL на бирже при движении TSL (Вариант A)
            if _is_live and tsl_moved and hasattr(bot, "order_executor"):
                await _update_tsl_on_exchange(bot, tsl_moved)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("TradeSimulator loop: %s", e)
