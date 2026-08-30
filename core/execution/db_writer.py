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

# ретрай закрытия строки (30.08): единственный `database is locked` терял закрытие навсегда
_CLOSE_RETRIES = 4
_CLOSE_RETRY_DELAY_SEC = 0.5      # с линейным ростом: 0.5 / 1.0 / 1.5с


def _exit_to_close_args(ex) -> Optional[tuple[str, float]]:
    """ExitInfo → (status, exit_price) для close_trade, либо None если закрыть нельзя."""
    if ex is None:
        return None                      # WS-drop: нет данных закрытия — не угадываем
    price = float(getattr(ex, "exit_price", 0) or 0)
    if price <= 0:
        return None
    status = (getattr(ex, "status", "") or "").upper()
    if status == "LIQUIDATION":
        status = "SL"
    elif status not in _VALID_DB_STATUS:
        status = "TP" if (getattr(ex, "realized_pnl", 0) or 0) >= 0 else "SL"
    return status, price


def intent_to_close_args(intent: CloseIntent) -> Optional[tuple[str, float]]:
    """CloseIntent → (status, exit_price) для close_trade, либо None если закрыть нельзя."""
    return _exit_to_close_args(intent.exit)


def _is_still_open(db_path: str, trade_id: int) -> bool:
    """Строка всё ещё OPEN? Различает «ok=False потому что уже закрыта» и «db-lock/сбой»."""
    try:
        with sqlite3.connect(db_path, timeout=5) as conn:
            row = conn.execute("SELECT status FROM simulated_trades WHERE id=?",
                               (trade_id,)).fetchone()
        return bool(row and str(row[0]) == "OPEN")
    except Exception as e:
        logger.debug("[db_writer] _is_still_open #%d: %s", trade_id, e)
        return True    # не смогли проверить → считаем открытой, пусть ретрай попробует


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


async def apply_exit_to_trade(trade_simulator, trade_id: int, exit_info, *,
                              symbol: str, side: str, reason: str) -> bool:
    """Закрывает КОНКРЕТНУЮ строку simulated_trades по резолвленному exit.

    Общая точка для двух путей: WS-close (on_close ниже, ищет строку по symbol+side) и
    DB-reconcile (position_sync, id известен точно). Второй ОБЯЗАН адресовать строку по id:
    find_open_exchange_trade берёт последнюю по symbol+direction, а при двух OPEN одной
    стороны (MYX SHORT #58595 impulse_fib_15m + #58605 choch_wavec, 30.08) это закрыло бы
    не ту запись и оставило вторую зомби.

    🔴 30.08 РЕТРАЙ НА `database is locked`. Раньше единственная попытка теряла закрытие
    НАВСЕГДА: Sphere уже сделала store.drop, второго pa=0 не будет
    (`[db_writer] #58702 ACU → SL ok=False` — запись висела OPEN сутки). Замер того же дня:
    400 `database is locked` за 7.5ч лога, 2 из них попали прямо в close_trade.
    """
    import asyncio as _aio

    db_path = trade_simulator.db_path
    args = _exit_to_close_args(exit_info)
    if args is None:
        logger.warning("[db_writer] #%s %s %s (%s) — нет валидного exit (price/status) → "
                       "НЕ закрываю (эскалация verify-flat)", trade_id, symbol, side, reason)
        return False
    status, exit_price = args
    # SL→TSL коррекция (перенос из exec_ws 2b, copy-DB тест 13.07: AGLD-класс): наш TSL
    # двигает обычный STOP (cancel+replace) → закрытие приходит как «SL»/по знаку rp.
    # original_sl != stop_loss = стоп реально двигался → это TSL. Применяем к статусам
    # без нативного типа ордера (SL, и TP от знаковой классификации CR_DELTA/INCOME —
    # профитный подтянутый стоп закрывается именно так); нативный TAKE_PROFIT не трогаем.
    _knows_order = (getattr(exit_info, "order_type", "") or "").upper() not in (
        "CR_DELTA", "INCOME_FALLBACK", "")
    if status == "SL" or (status == "TP" and not _knows_order):
        try:
            with sqlite3.connect(db_path, timeout=5) as _c:
                _r = _c.execute("SELECT original_sl, stop_loss FROM simulated_trades WHERE id=?",
                                (trade_id,)).fetchone()
            if _r and _r[0] and _r[1] and float(_r[0]) > 0 and \
                    abs(float(_r[1]) - float(_r[0])) / float(_r[0]) > 0.0001:
                logger.info("[db_writer] #%d %s: %s→TSL (orig_sl=%.6g → curr_sl=%.6g, стоп двигался)",
                            trade_id, symbol, status, float(_r[0]), float(_r[1]))
                status = "TSL"
        except Exception as _tsle:
            logger.debug("[db_writer] SL→TSL lookup #%d: %s", trade_id, _tsle)
    for _attempt in range(1, _CLOSE_RETRIES + 1):
        try:
            ok = trade_simulator.close_trade(trade_id, status, exit_price)
        except Exception as e:
            logger.warning("[db_writer] close_trade #%d error: %s", trade_id, e)
            return False
        if ok:
            logger.info("[db_writer] #%d %s %s → %s @ %.8g (intent=%s ok=True попытка %d)",
                        trade_id, symbol, side, status, exit_price, reason, _attempt)
            return True
        # ok=False — либо строка уже не OPEN (закрыл другой путь), либо db-lock/сбой.
        if not _is_still_open(db_path, trade_id):
            logger.info("[db_writer] #%d %s — строка уже не OPEN (закрыта другим путём) — no-op",
                        trade_id, symbol)
            return False
        if _attempt < _CLOSE_RETRIES:
            logger.warning("[db_writer] #%d %s: close_trade вернул False, строка ещё OPEN → "
                           "повтор %d/%d через %.1fs", trade_id, symbol, _attempt + 1,
                           _CLOSE_RETRIES, _CLOSE_RETRY_DELAY_SEC * _attempt)
            await _aio.sleep(_CLOSE_RETRY_DELAY_SEC * _attempt)
    logger.error("[db_writer] #%d %s %s → %s @ %.8g: НЕ ЗАКРЫТА за %d попыток — строка останется "
                 "OPEN (зомби). Причина обычно `database is locked`.",
                 trade_id, symbol, side, status, exit_price, _CLOSE_RETRIES)
    return False


def build_close_applier(trade_simulator):
    """Возвращает async on_close(intent) для ExecutionSphere(on_close=...).

    Закрывает OPEN биржевую сделку в БД по CloseIntent. Идемпотентно: нет OPEN-строки
    (уже закрыта) → no-op. close_trade сам защищён от concurrent close (_close_in_progress).
    """
    db_path = trade_simulator.db_path

    async def on_close(intent: CloseIntent) -> None:
        if intent_to_close_args(intent) is None:
            logger.warning("[db_writer] %s %s acc=%s (%s) — нет валидного exit (price/status) → НЕ закрываю (эскалация verify-flat)",
                           intent.symbol, intent.side, intent.account, intent.reason)
            return
        trade_id = find_open_exchange_trade(db_path, intent.symbol, intent.side)
        if trade_id is None:
            logger.info("[db_writer] %s %s — OPEN биржевой строки нет (уже закрыта/SIM) — no-op",
                        intent.symbol, intent.side)
            return
        await apply_exit_to_trade(trade_simulator, trade_id, intent.exit,
                                  symbol=intent.symbol, side=intent.side, reason=intent.reason)

    return on_close
