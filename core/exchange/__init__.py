"""
core/exchange — биржевой слой (BingX VST/LIVE).

Структура:
  bingx_client.py   — HTTP клиент, константы, dataclasses
  order_manager.py  — OrderManager: open/close/update ордеров
  position_sync.py  — sync_positions: синхронизация биржи → симулятор
  tsl_updater.py    — update_tsl_on_exchange: TSL cancel+replace SL

Импортируй отсюда — не из подмодулей напрямую.
"""
from core.exchange.bingx_client import (
    BingXClient, BracketResult, PartialCloseResult,
    ExecutionMode, MIN_NOTIONAL, VST_BASE_URL, LIVE_BASE_URL, make_client,
)
from core.exchange.order_manager import OrderManager
from core.exchange.position_sync import sync_positions
from core.exchange.tsl_updater import update_tsl_on_exchange, fetch_and_save_sl_order_id, fetch_and_save_tp_order_id

__all__ = [
    "BingXClient", "BracketResult", "PartialCloseResult",
    "ExecutionMode", "MIN_NOTIONAL", "VST_BASE_URL", "LIVE_BASE_URL", "make_client",
    "OrderManager",
    "sync_positions",
    "update_tsl_on_exchange", "fetch_and_save_sl_order_id", "fetch_and_save_tp_order_id",
]
