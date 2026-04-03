"""
order_executor.py — backward-compatibility stub.

Весь код переехал в core/exchange/.
Этот файл нужен только чтобы старые импорты продолжали работать.

  from core.trading.order_executor import OrderExecutor   → OrderManager
  from core.trading.order_executor import _BingXClient    → BingXClient
  from core.trading.order_executor import VST_BASE_URL    → const
"""
from core.exchange.bingx_client import (
    BingXClient as _BingXClient,          # старое имя с underscore
    BracketResult, PartialCloseResult,
    ExecutionMode, MIN_NOTIONAL,
    VST_BASE_URL, LIVE_BASE_URL,
)
from core.exchange.order_manager import OrderManager as OrderExecutor

__all__ = [
    "_BingXClient", "BracketResult", "PartialCloseResult",
    "ExecutionMode", "MIN_NOTIONAL", "VST_BASE_URL", "LIVE_BASE_URL",
    "OrderExecutor",
]
