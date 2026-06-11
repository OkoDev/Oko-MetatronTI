"""
exec_ws_integration — интеграция UserDataStream в бот (EXEC-WS Этап 2).

on_event(WS) → действия БД:
  ЭТАП 2a (write_exch_id): ORDER_TRADE_UPDATE FILLED MARKET ro=false (открытие позиции)
     → найти свежую OPEN-сделку symbol+direction с exch_id=None → записать orderId.
     Лечит баг-семью exchange_order_id=None (orphan/фантомные SIM-only).
  ЭТАП 2b (sync_close): ACCOUNT_UPDATE P[].pa=0 (позиция закрыта на бирже)
     → [позже] sync БД close. Пока только лог.

Всё за config-флагами trading.exec_ws.* (default false). SHADOW: если флаг off → лог «would …».
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _ws_to_db_symbol(sym_ws: str) -> str:
    """'XLM-USDT' → 'XLM/USDT:USDT' (формат БД simulated_trades)."""
    parts = sym_ws.split("-")
    if len(parts) != 2:
        return sym_ws
    base, quote = parts[0], parts[1]
    return f"{base}/{quote}:{quote}"


def _write_exch_id(bot, symbol: str, direction: str, order_id: str, dry: bool) -> bool:
    """Записать exchange_order_id в свежую OPEN-сделку symbol+direction без exch_id."""
    db_path = bot.trade_simulator.db_path
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout=10000")
            row = conn.execute(
                """SELECT id FROM simulated_trades
                   WHERE symbol=? AND direction=? AND status='OPEN'
                     AND (exchange_order_id IS NULL OR exchange_order_id='')
                   ORDER BY id DESC LIMIT 1""",
                (symbol, direction),
            ).fetchone()
            if not row:
                return False
            tid = row[0]
            if dry:
                logger.info("[EXEC-WS][2a] would write exch_id=%s → #%d %s %s (SHADOW)",
                            order_id, tid, symbol, direction)
                return True
            conn.execute(
                "UPDATE simulated_trades SET exchange_order_id=? WHERE id=? AND status='OPEN'",
                (order_id, tid),
            )
            conn.commit()
            logger.info("[EXEC-WS][2a] exch_id=%s → #%d %s %s (WS real-time)",
                        order_id, tid, symbol, direction)
            return True
    except Exception as e:
        logger.warning("[EXEC-WS][2a] write_exch_id error %s %s: %s", symbol, direction, e)
        return False


def make_event_handler(bot):
    cfg = bot.config

    async def on_event(etype: str, msg: dict) -> None:
        et = (etype or "").upper()
        # ── ЭТАП 2a: запись exch_id при FILLED MARKET открытии ──
        if "ORDER" in et and "TRADE" in et:
            o = msg.get("o") or {}
            if not isinstance(o, dict):
                return
            if o.get("X") == "FILLED" and o.get("o") == "MARKET" and not o.get("ro", False):
                order_id = str(o.get("i", "") or "")
                symbol = _ws_to_db_symbol(str(o.get("s", "")))
                direction = str(o.get("ps", "")).upper()   # LONG/SHORT
                if order_id and symbol and direction in ("LONG", "SHORT"):
                    dry = not bool(cfg.get("trading.exec_ws.write_exch_id", False))
                    _write_exch_id(bot, symbol, direction, order_id, dry)
            return
        # ── ЭТАП 2b: позиция закрыта (pa=0) — пока лог (sync_close позже) ──
        if et == "ACCOUNT_UPDATE":
            a = msg.get("a") or {}
            for p in (a.get("P") or []):
                if isinstance(p, dict) and str(p.get("pa", "")).strip("0.") == "":
                    sym = _ws_to_db_symbol(str(p.get("s", "")))
                    if bool(cfg.get("trading.exec_ws.sync_close", False)):
                        logger.info("[EXEC-WS][2b] %s %s закрыта (pa=0) — sync_close TODO",
                                    sym, p.get("ps"))

    return on_event


def start_exec_ws(bot) -> Optional[object]:
    """Запуск UserDataStream если trading.exec_ws.enabled. Возвращает asyncio.Task или None."""
    import asyncio
    cfg = bot.config
    if not bool(cfg.get("trading.exec_ws.enabled", False)):
        return None
    is_vst = str(cfg.get("trading.execution_mode", "vst")).lower() == "vst"
    import os
    key = (os.getenv("BINGX_VST_API_KEY") if is_vst else os.getenv("BINGX_API_KEY")) or ""
    secret = (os.getenv("BINGX_VST_SECRET_KEY") if is_vst else os.getenv("BINGX_SECRET_KEY")) or ""
    if not key:
        logger.warning("[EXEC-WS] enabled, но нет ключей (is_vst=%s) — не запускаю", is_vst)
        return None
    from core.exchange.user_data_ws import UserDataStream
    uds = UserDataStream(key, secret, is_vst=is_vst, on_event=make_event_handler(bot), account_tag="acc1")
    bot._exec_ws = uds
    task = asyncio.create_task(uds.run())
    logger.info("[EXEC-WS] запущен (is_vst=%s, write_exch_id=%s)",
                is_vst, cfg.get("trading.exec_ws.write_exch_id", False))
    return task
