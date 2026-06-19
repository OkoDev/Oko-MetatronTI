"""core.execution — единый слой исполнения (Execution Sphere).

Ф3.1 каркас эпика EXECUTION-REBUILD (см. docs/EXECUTION_SPHERE_DESIGN.md).
Биржа/account-агностичный контракт: бизнес-код зовёт ТОЛЬКО ExecutionSphere,
биржевая специфика изолирована за ExchangeAdapter.

Состав (по фазам):
  Ф3.1 (этот шаг): domain (доменная модель) · adapter (ExchangeAdapter ABC) · calc (ExecutionCalc)
  Ф3.2: BingXAdapter (обёртка над BingXClient/order_manager/user_data_ws)
  Ф3.3: PositionStore (WS-истина) · ExecutionLedger (o.rp/o.n/funding)
  Ф3.4: ExecutionRepo (live.db/sim.db split)
  Ф4:   ExecutionSphere (open/close/on_event/adjust_sl/state)

🔴 ИНВАРИАНТЫ:
  1. WS = единственный источник истины состояния позиции (close в БД только по pa=0).
  2. account + exchange = ПАРАМЕТРЫ, не хардкод.
  3. Один калькулятор (ExecutionCalc reuse PositionSizer + r_math, без дубля).
"""
from __future__ import annotations

from core.execution.domain import (
    ExecMode,
    OrderRequest,
    OrderResult,
    Position,
    Fill,
    CloseResult,
    LedgerEntry,
    ExecEvent,
    FillEvent,
    PositionEvent,
    LedgerEvent,
    LiquidationEvent,
    MarginModeEvent,
    EquityEvent,
    ListenKeyExpiredEvent,
)
from core.execution.adapter import ExchangeAdapter
from core.execution import calc
from core.execution.position_store import PositionStore, ExitInfo, classify_exit
# NB: ExecutionLedger (DS) и BingXAdapter импортируются напрямую из своих модулей —
# не тянем их в пакет-инит (агностичное ядро + раздельное владение файлами).

__all__ = [
    "ExecMode",
    "OrderRequest",
    "OrderResult",
    "Position",
    "Fill",
    "CloseResult",
    "LedgerEntry",
    "ExecEvent",
    "FillEvent",
    "PositionEvent",
    "LedgerEvent",
    "LiquidationEvent",
    "MarginModeEvent",
    "EquityEvent",
    "ListenKeyExpiredEvent",
    "ExchangeAdapter",
    "calc",
    "PositionStore",
    "ExitInfo",
    "classify_exit",
]
