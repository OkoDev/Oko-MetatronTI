"""
position_sync.py — синхронизация биржевых позиций с TradeSimulator.

Правильный подход (DEV-145):
  Не угадываем статус по цене — читаем реальный статус исполненного ордера через
  GET /allOrders → ищем FILLED STOP_MARKET (→ SL) или TAKE_PROFIT_MARKET (→ TP/TSL),
  берём avgPrice как exit_price.

  TSL NOTE: наш TSL двигает обычный STOP ордер (cancel+replace), поэтому при срабатывании
  он возвращается как STOP_MARKET → "SL". После _resolve_exit проверяем tsl_activated=1
  и корректируем статус на "TSL".

  Если filled ордер не найден (редкая ситуация: позиция закрыта вручную или API лаг)
  — используем текущую mark_price с биржи (не угадываем статус, ставим EXPIRED).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Тип ордера → статус сделки в симуляторе
_ORDER_TYPE_TO_STATUS = {
    "STOP_MARKET":          "SL",
    "STOP":                 "SL",
    "TAKE_PROFIT_MARKET":   "TP",
    "TAKE_PROFIT":          "TP",
    "TRAILING_STOP_MARKET": "TSL",
}


async def _resolve_exit(client, symbol: str, direction: str, mark_price: float | None) -> tuple[str, float | None]:
    """
    Определяет статус (SL/TP/TSL/EXPIRED) и exit_price через filled orders на бирже.

    Returns:
        (status, exit_price)  — exit_price может быть None если данных нет.
    """
    try:
        filled = await client.get_filled_orders(symbol, limit=50)  # DEV-148: 20→50 (TP с R<0 баг)
        # Ищем последний STOP/TP ордер в нужном направлении
        # LONG закрывается SELL-ордером, SHORT — BUY-ордером
        close_side = "SELL" if direction == "LONG" else "BUY"
        for o in filled:
            order_type = o.get("type", "")
            order_side = o.get("side", "")
            avg_price  = o.get("avgPrice") or o.get("stopPrice") or o.get("price")
            if order_side.upper() == close_side and order_type in _ORDER_TYPE_TO_STATUS:
                status     = _ORDER_TYPE_TO_STATUS[order_type]
                exit_price = float(avg_price) if avg_price else mark_price
                logger.debug("[POSITION-SYNC] %s %s: filled %s @ %.6f → %s",
                             symbol, direction, order_type, exit_price or 0, status)
                return status, exit_price
    except Exception as e:
        logger.debug("[POSITION-SYNC] get_filled_orders %s: %s", symbol, e)

    # Fallback: позиция закрыта вручную или данных нет — ставим EXPIRED с mark_price
    return "EXPIRED", mark_price


async def _emergency_close_check(bot, sym: str, trade: dict, position: dict) -> bool:
    """
    DEV-185.2 (27.04.2026): Emergency watchdog для STOP-LIMIT non-execution.

    Сценарий: STOP-LIMIT trigger срабатывает, но limit-ордер не fill из-за gap
    (цена ушла >buffer за trigger). Позиция остаётся открытой → продолжает терять.
    Пример: #8010 APE 26.04 — overshoot 32.7%, R=-11.83 за 3 часа.

    Алгоритм:
      1. Текущая цена ушла за stop_loss > overshoot_threshold (default 0.5%)
      2. Прошло > dwell_seconds (default 300=5 мин) с момента первого нарушения
      3. → emergency market close, лог STOP_LIMIT_EMERGENCY_FILL

    Возвращает True если выполнили emergency close (вызывающий должен пропустить trade).
    """
    cfg = bot.config
    if not cfg.get("trading.dev185_2_emergency_enabled", True):
        return False

    trade_id = trade.get("id")
    direction = trade.get("direction", "LONG")
    sl = float(trade.get("stop_loss") or 0)
    entry = float(trade.get("entry_price") or 0)
    if sl <= 0 or entry <= 0:
        return False

    overshoot_threshold = float(cfg.get("trading.dev185_2_overshoot_threshold_pct", 0.5))
    dwell_seconds = int(cfg.get("trading.dev185_2_dwell_seconds", 300))

    # Текущая цена — из position data (markPrice) или с тикера
    cur_price = 0.0
    try:
        cur_price = float(position.get("markPrice") or position.get("avgPrice") or 0)
    except Exception:
        pass
    if cur_price <= 0:
        try:
            cur_price = await bot.data_collector.get_current_price(sym)
        except Exception:
            return False

    # Считаем overshoot (положительный = цена ушла за SL в плохую для нас сторону)
    if direction == "LONG":
        overshoot_pct = (sl - cur_price) / entry * 100  # cur_price ниже SL → overshoot >0
    else:
        overshoot_pct = (cur_price - sl) / entry * 100  # cur_price выше SL → overshoot >0

    # State: dict {trade_id: first_seen_ts} в bot
    dwell_state = getattr(bot, "_emergency_dwell_state", None)
    if dwell_state is None:
        dwell_state = {}
        bot._emergency_dwell_state = dwell_state

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    if overshoot_pct < overshoot_threshold:
        # Норма — очищаем state если был
        if trade_id in dwell_state:
            del dwell_state[trade_id]
        return False

    # Цена за SL > threshold
    first_seen = dwell_state.get(trade_id)
    if first_seen is None:
        dwell_state[trade_id] = now
        logger.info(
            "[DEV-185.2] %s #%d: overshoot %.2f%% > %.2f%% — start dwell timer (%ds)",
            sym, trade_id, overshoot_pct, overshoot_threshold, dwell_seconds,
        )
        return False

    elapsed = (now - first_seen).total_seconds()
    if elapsed < dwell_seconds:
        return False

    # Триггер emergency close
    qty = float(trade.get("qty") or 0)
    if qty <= 0:
        try:
            qty = float(position.get("positionAmt") or position.get("availableAmt") or 0)
            qty = abs(qty)
        except Exception:
            pass
    if qty <= 0:
        logger.warning(
            "[DEV-185.2][EMERGENCY] %s #%d: qty неизвестен — не могу закрыть market",
            sym, trade_id,
        )
        return False

    try:
        order_mgr = getattr(bot, "order_executor", None)
        if order_mgr is None or not order_mgr.is_live():
            return False
        client = await order_mgr._get_client_synced()
        side_close = "SELL" if direction == "LONG" else "BUY"
        logger.warning(
            "[DEV-185.2][EMERGENCY][STOP_LIMIT_EMERGENCY_FILL] %s #%d %s: "
            "overshoot %.2f%% за %.0fс — market close qty=%s",
            sym, trade_id, direction, overshoot_pct, elapsed, qty,
        )
        resp = await client.close_position_market(sym, side_close, qty)
        code = resp.get("code", 0) if isinstance(resp, dict) else 0
        if code != 0:
            # Fallback: one-click
            resp2 = await client.close_position_one_click(sym)
            logger.warning(
                "[DEV-185.2][EMERGENCY] %s #%d one-click fallback: code=%s",
                sym, trade_id, resp2.get("code") if isinstance(resp2, dict) else "?",
            )
        # Удаляем из state — следующий цикл sync_positions подхватит закрытие
        if trade_id in dwell_state:
            del dwell_state[trade_id]
        return True
    except Exception as e:
        logger.warning("[DEV-185.2][EMERGENCY] %s #%d ошибка: %s", sym, trade_id, e)
        return False


async def sync_positions(bot) -> None:
    """
    Сравнивает открытые сделки в симуляторе с реальными позициями на бирже.
    Если сделка есть в симуляторе (с exchange_order_id), но позиции нет на бирже
    — читаем filled orders, определяем статус и exit_price.

    Вызывается только в VST/LIVE режиме из exchange_loop каждые 60 сек.
    SIM-сделки (exchange_order_id IS NULL) не трогает.
    """
    try:
        # DEV-145: используем OrderManager с синхронизированным временем
        order_mgr = getattr(bot, "order_executor", None)
        if order_mgr is None or not order_mgr.is_live():
            return
        client = await order_mgr._get_client_synced()

        # Получаем открытые позиции на бирже
        # FAIL-CLOSED: если get_positions() бросает — пропускаем весь цикл.
        # Пустой список из-за ошибки API нельзя считать "нет позиций" —
        # это приводит к массовому ложному закрытию tracked сделок.
        try:
            positions = await client.get_positions()
        except Exception as _pos_err:
            logger.warning(
                "[POSITION-SYNC] get_positions failed → пропуск синхронизации: %s", _pos_err
            )
            return

        open_on_exchange: dict = {}   # sym_our → position_data
        for p in positions:
            sym_raw = p.get("symbol", "")   # "BTC-USDT"
            qty = float(p.get("positionAmt") or p.get("availableAmt") or 0)
            margin = float(p.get("margin") or p.get("initialMargin") or p.get("isolatedMargin") or 0)
            # BingX fallback: if no margin field, estimate from qty × price
            if margin == 0 and qty != 0:
                avg_price = float(p.get("avgPrice") or p.get("entryPrice") or p.get("markPrice") or 0)
                leverage = float(p.get("leverage") or 5)
                margin = abs(qty) * avg_price / leverage if avg_price else 999  # assume valid if no price
            if qty != 0 and abs(margin) >= 0.01:
                sym_our = sym_raw.replace("-", "/") + ":USDT"
                open_on_exchange[sym_our] = p
            elif qty != 0 and abs(margin) < 0.01:
                sym_our = sym_raw.replace("-", "/") + ":USDT"
                logger.info(
                    "[POSITION-SYNC] %s dust position (margin=%.6f qty=%.8f) — closing on exchange",
                    sym_our, margin, qty,
                )
                # Auto-close dust on exchange
                try:
                    side = "BUY" if qty > 0 else "SELL"  # positionAmt > 0 = LONG
                    resp = await client.close_position_market(sym_our, side, abs(qty))
                    if resp.get("code", 0) != 0:
                        # Market order failed (qty too small) — try one-click close
                        resp2 = await client.close_position_one_click(sym_our)
                        logger.info("[POSITION-SYNC] %s dust one-click close: %s", sym_our, resp2.get("code"))
                    else:
                        logger.info("[POSITION-SYNC] %s dust closed on exchange OK", sym_our)
                except Exception as _dust_err:
                    logger.warning("[POSITION-SYNC] %s dust close failed: %s", sym_our, _dust_err)

        # DEV-149: защита от API-сбоя — пропускаем синхронизацию только если
        # snapshot был пустой ДВА цикла подряд. Одиночное пустое значение может
        # быть реальным (все закрылись). Две подряд — почти наверняка API-сбой.
        open_sim_count = sum(
            1 for t in bot.trade_simulator.get_open_trades()
            if t.get("exchange_order_id")
        )
        _prev_empty = getattr(bot, "_position_sync_prev_empty", False)
        _now_empty  = len(open_on_exchange) == 0 and open_sim_count > 0
        bot._position_sync_prev_empty = _now_empty
        if _now_empty and _prev_empty:
            logger.warning(
                "[POSITION-SYNC] snapshot пустой 2-й цикл подряд (tracked=%d) — пропуск",
                open_sim_count,
            )
            return

        open_sim = bot.trade_simulator.get_open_trades()
        synced = 0

        # DEV-185.2: emergency watchdog — перед основным циклом закрытия проверяем
        # "висящие" позиции (STOP-LIMIT trigger сработал, но limit не fill из-за gap).
        for trade in open_sim:
            if not trade.get("exchange_order_id"):
                continue
            sym_w = trade.get("symbol", "")
            pos_w = open_on_exchange.get(sym_w)
            if pos_w is None:
                continue  # позиции на бирже нет — обработается основным циклом
            try:
                await _emergency_close_check(bot, sym_w, trade, pos_w)
            except Exception as _ew:
                logger.debug("[DEV-185.2] watchdog error %s: %s", sym_w, _ew)

        for trade in open_sim:
            if not trade.get("exchange_order_id"):
                continue  # SIM-сделка — не трогаем

            sym       = trade.get("symbol", "")
            trade_id  = trade.get("id")
            direction = trade.get("direction", "LONG")

            if sym in open_on_exchange:
                continue  # позиция ещё открыта — всё нормально

            # Позиции нет на бирже → закрылась (SL/TP/TSL/вручную)
            # Читаем mark_price из данных позиции (если была) или из тикера
            mark_price: float | None = None
            try:
                mark_price = await bot.data_collector.get_current_price(sym)
            except Exception:
                pass

            status, exit_price = await _resolve_exit(client, sym, direction, mark_price)

            # TSL реализован через STOP ордер (cancel+replace), поэтому на бирже он
            # срабатывает как STOP_MARKET → _resolve_exit возвращает "SL".
            # Критерий TSL-exit: original_sl != stop_loss (SL реально двигался TSL'ом).
            # Это надёжнее tsl_activated (флаг ставится при +1R, но SL мог не двинуться).
            if status == "SL":
                _orig_sl = trade.get("original_sl")
                _curr_sl = float(trade.get("stop_loss") or 0)
                if (
                    _orig_sl is not None
                    and _curr_sl > 0
                    and abs(_curr_sl - float(_orig_sl)) / float(_orig_sl) > 0.0001
                ):
                    status = "TSL"
                    logger.info(
                        "[POSITION-SYNC] #%d %s: SL→TSL (orig_sl=%.6f → curr_sl=%.6f)",
                        trade_id, sym, float(_orig_sl), _curr_sl,
                    )

            if exit_price is None:
                exit_price = float(trade.get("entry_price", 0))
                logger.warning("[POSITION-SYNC] #%d %s: exit_price неизвестен, используем entry", trade_id, sym)

            # ── SANITY CHECK: exit_price не должен давать аномальный R ──────
            # Если position_sync получил текущую цену (а не реальный fill),
            # цена могла уйти далеко от SL/TP → аномальный R.
            # Fix: используем SL/TP цену как exit если status определён.
            _entry = float(trade.get("entry_price", 0))
            _sl = float(trade.get("stop_loss") or 0)
            _tp = float(trade.get("take_profit") or 0)
            _one_r = abs(_entry - _sl) if _sl and _entry != _sl else 0

            if _one_r > 0 and exit_price:
                if direction == "LONG":
                    _r_calc = (exit_price - _entry) / _one_r
                else:
                    _r_calc = (_entry - exit_price) / _one_r

                # SL не может дать R > 3 (или profit > entry×3%). Если даёт — exit_price ложный.
                if status == "SL" and _r_calc > 3:
                    logger.warning(
                        "[POSITION-SYNC] #%d %s: SANITY FAIL — SL exit=%.6f даёт R=%.1f "
                        "(>3). Заменяем на SL-цену %.6f",
                        trade_id, sym, exit_price, _r_calc, _sl,
                    )
                    exit_price = _sl

                # DEV-175: SL с огромным slippage — exit намного хуже SL (gap на бирже).
                # Реальные деньги VST — exit_price НЕ меняем, только логируем для аудита.
                # Root cause: STOP_MARKET на малоликвидных монетах, slippage > 2R → orphan R.
                if status == "SL" and _r_calc < -2.0:
                    _orig_sl = float(trade.get("original_sl") or 0)
                    _orig_r = (_r_calc * _one_r) / abs(_entry - _orig_sl) if _orig_sl and abs(_entry - _orig_sl) > 0 else _r_calc
                    logger.warning(
                        "[POSITION-SYNC] #%d %s: SLIPPAGE — SL exit=%.6f R=%.1f (<-2). "
                        "SL на бирже=%.6f, orig_sl=%.6f. STOP_MARKET gap %.2f%%",
                        trade_id, sym, exit_price, _r_calc, _sl, _orig_sl,
                        abs(exit_price - (_orig_sl or _sl)) / _entry * 100 if _entry else 0,
                    )

                # TP не может дать R < -1. Если даёт — exit_price ложный.
                if status == "TP" and _r_calc < -1 and _tp:
                    logger.warning(
                        "[POSITION-SYNC] #%d %s: SANITY FAIL — TP exit=%.6f даёт R=%.1f "
                        "(<-1). Заменяем на TP-цену %.6f",
                        trade_id, sym, exit_price, _r_calc, _tp,
                    )
                    exit_price = _tp

                # EXPIRED с огромным R — текущая цена ушла далеко от входа
                if status == "EXPIRED" and abs(_r_calc) > 10 and _sl:
                    logger.warning(
                        "[POSITION-SYNC] #%d %s: EXPIRED exit=%.6f даёт R=%.1f "
                        "(>10). Заменяем на SL-цену %.6f",
                        trade_id, sym, exit_price, _r_calc, _sl,
                    )
                    exit_price = _sl
                    status = "SL"

            try:
                bot.trade_simulator.close_trade(trade_id, status, exit_price)
                logger.info("[POSITION-SYNC] #%d %s %s → %s @ %.6f",
                            trade_id, sym, direction, status, exit_price)
                synced += 1
            except Exception as e:
                logger.warning("[POSITION-SYNC] close_trade #%d error: %s", trade_id, e)

        if synced:
            logger.info("[POSITION-SYNC] синхронизировано %d закрытых позиций", synced)

    except Exception as e:
        logger.warning("[POSITION-SYNC] ошибка: %s", e)


async def fix_zero_r_trades(bot, dry_run: bool = True) -> int:
    """
    DEV-145: Чистка исторических VST сделок с exit_price = entry_price (R=0).

    Для каждой такой сделки:
      1. Пытается найти реальный exit через get_filled_orders() API.
      2. Если находит — обновляет exit_price и status.
      3. Если нет — помечает status='UNKNOWN' чтобы не искажать статистику.

    dry_run=True (по умолчанию) — только логирует, не меняет БД.
    Возвращает количество найденных / обновлённых записей.

    Запуск:
        import asyncio
        from core.exchange.position_sync import fix_zero_r_trades
        asyncio.run(fix_zero_r_trades(bot, dry_run=False))
    """
    import sqlite3

    order_mgr = getattr(bot, "order_executor", None)
    if order_mgr is None or not order_mgr.is_live():
        logger.warning("[fix_zero_r] OrderManager недоступен или режим SIM")
        return 0

    client = await order_mgr._get_client_synced()

    # Ищем VST-сделки (exchange_order_id есть) с exit ≈ entry (R=0)
    try:
        with sqlite3.connect(bot.trade_simulator.db_path, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout=10000")  # DEV-148
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, symbol, direction, entry_price, stop_loss, exit_price, status
                FROM simulated_trades
                WHERE status IN ('TP', 'SL', 'TSL')
                  AND exchange_order_id IS NOT NULL
                  AND exchange_order_id != ''
                  AND exit_price IS NOT NULL
                  AND ABS(exit_price - entry_price) < 0.000001
                ORDER BY closed_at DESC
                LIMIT 200
            """).fetchall()
    except Exception as e:
        logger.error("[fix_zero_r] БД ошибка: %s", e)
        return 0

    logger.info("[fix_zero_r] найдено %d сделок с exit_price=entry_price (R=0)", len(rows))
    updated = 0

    for row in rows:
        trade_id  = row["id"]
        sym       = row["symbol"]
        entry     = float(row["entry_price"] or 0)
        direction = row["direction"]

        new_exit: float | None = None
        new_status: str | None = None

        # Ищем реальный exit в filled orders
        try:
            filled = await client.get_filled_orders(sym, limit=50)
            filled = sorted(
                filled,
                key=lambda o: int(o.get("updateTime") or o.get("time") or 0),
                reverse=True,
            )
            close_side = "SELL" if direction == "LONG" else "BUY"
            for o in filled:
                o_type  = (o.get("type") or "").upper()
                o_side  = (o.get("side") or "").upper()
                o_price = float(o.get("avgPrice") or o.get("price") or 0)
                if o_side == close_side and o_price > 0 and abs(o_price - entry) > entry * 0.0001:
                    new_exit   = o_price
                    new_status = _ORDER_TYPE_TO_STATUS.get(o_type)
                    if new_status is None:
                        sl = float(row["stop_loss"] or 0)
                        if sl:
                            new_status = "SL" if (
                                (direction == "LONG" and o_price <= sl * 1.002) or
                                (direction == "SHORT" and o_price >= sl * 0.998)
                            ) else "TP"
                        else:
                            new_status = "TP"
                    break
        except Exception as e:
            logger.debug("[fix_zero_r] %s filled_orders error: %s", sym, e)

        if new_exit is None:
            # Реальных данных нет — помечаем UNKNOWN
            new_status = "UNKNOWN"
            new_exit   = entry

        if dry_run:
            logger.info("[fix_zero_r][DRY] #%d %s %s: %s→%s exit=%.8f",
                        trade_id, sym, direction, row["status"], new_status, new_exit)
        else:
            try:
                with sqlite3.connect(bot.trade_simulator.db_path, timeout=10) as conn:
                    conn.execute("PRAGMA busy_timeout=10000")  # DEV-148
                    conn.execute(
                        "UPDATE simulated_trades SET exit_price=?, status=?, R_multiple=NULL WHERE id=?",
                        (new_exit, new_status, trade_id),
                    )
                logger.info("[fix_zero_r] #%d %s: %s→%s exit=%.8f",
                            trade_id, sym, row["status"], new_status, new_exit)
                updated += 1
            except Exception as e:
                logger.warning("[fix_zero_r] update #%d: %s", trade_id, e)

    total = len(rows)
    logger.info("[fix_zero_r] итог: %s %d/%d",
                "dry_run" if dry_run else "обновлено", updated if not dry_run else total, total)
    return updated if not dry_run else total
