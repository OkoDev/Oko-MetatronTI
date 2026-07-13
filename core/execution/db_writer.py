"""core.execution.db_writer — close-applier для ExecutionSphere (Ф4.1, close-path).

Мост CloseIntent → trade_simulator.close_trade. Это `on_close`-колбэк, который Sphere
зовёт при pa=0 (§6). РЕАЛЬНАЯ цена/статус берутся из ExitInfo (WS o.ap/o.rp/o.o) —
БЕЗ REST _resolve_exit (корень fake-R убран: WS уже несёт истину).

🔴 close-path: подключать к живому боту (Sphere(on_close=...)) ТОЛЬКО после теста на
копии БД (инцидент 2026-04-07). Здесь — чистая логика + lookup, протестирована на
реальной схеме (tests/unit/test_db_writer_closepath.py).

Маппинг статусов (close_trade принимает только TP/SL/TSL/EXPIRED):
  SL/TP/TSL  → как есть
  LIQUIDATION → SL  (ликвидация = убыток-закрытие; отдельного статуса в БД нет)
  MANUAL/прочее → TP если realized>=0 иначе SL
Нет ExitInfo (reconcile_ws_drop, WS-событие потеряно) ИЛИ цены<=0 → НЕ закрываем
(не угадываем цену — иначе вернём fake-R). Такой случай эскалирует отдельно (verify-flat).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from core.execution.sphere import CloseIntent

logger = logging.getLogger(__name__)

# статусы, которые принимает trade_simulator.close_trade
_VALID_DB_STATUS = {"TP", "SL", "TSL"}


def intent_to_close_args(intent: CloseIntent) -> Optional[tuple[str, float]]:
    """CloseIntent → (status, exit_price) для close_trade, либо None если закрыть нельзя."""
    ex = intent.exit
    if ex is None:
        return None                      # WS-drop: нет данных закрытия — не угадываем
    price = float(ex.exit_price or 0)
    if price <= 0:
        return None
    status = (ex.status or "").upper()
    if status == "LIQUIDATION":
        status = "SL"
    elif status not in _VALID_DB_STATUS:
        status = "TP" if (ex.realized_pnl or 0) >= 0 else "SL"
    return status, price


def find_open_exchange_trade(db_path: str, symbol: str, direction: str) -> Optional[int]:
    """OPEN биржевая (не SIM-only) сделка по symbol+direction → trade_id (или None).

    Зеркало exec_ws_integration._find_exchange_trade: execution_mode != 'SIM' ИЛИ реальный
    exchange_order_id. Hedge-aware (symbol+direction). Последняя по id."""
    try:
        with sqlite3.connect(db_path, timeout=5) as conn:
            row = conn.execute(
                """SELECT id FROM simulated_trades
                   WHERE symbol=? AND direction=? AND status='OPEN'
                     AND (execution_mode != 'SIM' OR
                          (exchange_order_id IS NOT NULL AND exchange_order_id != ''
                           AND exchange_order_id != 'SIM'))
                   ORDER BY id DESC LIMIT 1""",
                (symbol, direction),
            ).fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.warning("[db_writer] find_open_exchange_trade %s %s: %s", symbol, direction, e)
        return None


def build_close_applier(trade_simulator):
    """Возвращает async on_close(intent) для ExecutionSphere(on_close=...).

    Закрывает OPEN биржевую сделку в БД по CloseIntent. Идемпотентно: нет OPEN-строки
    (уже закрыта) → no-op. close_trade сам защищён от concurrent close (_close_in_progress).
    """
    db_path = trade_simulator.db_path

    async def on_close(intent: CloseIntent) -> None:
        args = intent_to_close_args(intent)
        if args is None:
            logger.warning("[db_writer] %s %s acc=%s (%s) — нет валидного exit (price/status) → НЕ закрываю (эскалация verify-flat)",
                           intent.symbol, intent.side, intent.account, intent.reason)
            return
        status, exit_price = args
        trade_id = find_open_exchange_trade(db_path, intent.symbol, intent.side)
        if trade_id is None:
            logger.info("[db_writer] %s %s — OPEN биржевой строки нет (уже закрыта/SIM) — no-op",
                        intent.symbol, intent.side)
            return
        # SL→TSL коррекция (перенос из exec_ws 2b, copy-DB тест 13.07: AGLD-класс): наш TSL
        # двигает обычный STOP (cancel+replace) → закрытие приходит как «SL»/по знаку rp.
        # original_sl != stop_loss = стоп реально двигался → это TSL. Применяем к статусам
        # без нативного типа ордера (SL, и TP от знаковой классификации CR_DELTA/INCOME —
        # профитный подтянутый стоп закрывается именно так); нативный TAKE_PROFIT не трогаем.
        _knows_order = (intent.exit.order_type or "").upper() not in ("CR_DELTA", "INCOME_FALLBACK", "")
        if status == "SL" or (status == "TP" and not _knows_order):
            try:
                with sqlite3.connect(db_path, timeout=5) as _c:
                    _r = _c.execute("SELECT original_sl, stop_loss FROM simulated_trades WHERE id=?",
                                    (trade_id,)).fetchone()
                if _r and _r[0] and _r[1] and float(_r[0]) > 0 and \
                        abs(float(_r[1]) - float(_r[0])) / float(_r[0]) > 0.0001:
                    logger.info("[db_writer] #%d %s: %s→TSL (orig_sl=%.6g → curr_sl=%.6g, стоп двигался)",
                                trade_id, intent.symbol, status, float(_r[0]), float(_r[1]))
                    status = "TSL"
            except Exception as _tsle:
                logger.debug("[db_writer] SL→TSL lookup #%d: %s", trade_id, _tsle)
        try:
            ok = trade_simulator.close_trade(trade_id, status, exit_price)
            logger.info("[db_writer] #%d %s %s → %s @ %.8g (intent=%s ok=%s)",
                        trade_id, intent.symbol, intent.side, status, exit_price, intent.reason, ok)
        except Exception as e:
            logger.warning("[db_writer] close_trade #%d error: %s", trade_id, e)

    return on_close
