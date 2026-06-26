"""core.execution.adapter — ExchangeAdapter ABC (граница multi-exchange).

Дизайн: docs/EXECUTION_SPHERE_DESIGN.md §3. ExecutionSphere зовёт ТОЛЬКО этот
интерфейс; биржевая специфика (BingX positionId casing, one_click 109400, listenKey)
живёт в конкретном адаптере (Ф3.2 BingXAdapter). Новая биржа = новый Adapter,
Sphere не меняется.

Тест чистоты (ARCH-96-HUB): сигнатуры описаны БЕЗ слова «BingX».
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Optional

from core.execution.domain import (
    CloseResult,
    ExecEvent,
    OrderRequest,
    OrderResult,
    Position,
)


class ExchangeAdapter(ABC):
    """Изолирует биржу. Команды (REST) + cold-start снимок (REST) + WS-истина."""

    name: str = "abstract"

    # ── КОМАНДЫ (REST) ─────────────────────────────────────────────────────
    @abstractmethod
    async def place_bracket(self, req: OrderRequest) -> OrderResult:
        """Market entry + SL + TP. Внутри: set_leverage, кламп к max пары, SL-safety кап,
        guards (min_sl_dist/sl_direction/min_notional) через ExecutionCalc.
        Сейчас эквивалент order_manager.open_bracket:383-541."""
        ...

    @abstractmethod
    async def place_sl(self, symbol: str, side: str, sl: float, qty: float,
                       account: int, position_id: Optional[str] = None) -> Optional[str]:
        ...

    @abstractmethod
    async def place_tp(self, symbol: str, side: str, tp: float, qty: float,
                       account: int, position_id: Optional[str] = None) -> Optional[str]:
        ...

    @abstractmethod
    async def cancel(self, symbol: str, order_id: str, account: int) -> bool:
        ...

    @abstractmethod
    async def close_reduce_only(self, symbol: str, side: str, qty: float, account: int,
                                position_id: Optional[str] = None) -> CloseResult:
        """reduceOnly market; fallback one_click. КОРЕНЬ hedge-close 101205 =
        account + position_id ИЗ позиции, не из предположения main."""
        ...

    @abstractmethod
    async def set_leverage(self, symbol: str, side: str, leverage: int, account: int) -> int:
        """→ фактическое плечо (может быть склампано биржей к max пары)."""
        ...

    @abstractmethod
    async def get_max_leverage(self, symbol: str, side: str, account: int) -> Optional[int]:
        ...

    @abstractmethod
    async def set_margin_mode(self, symbol: str, mode: str, account: int) -> bool:
        """ENFORCE isolated перед открытием (margin-enforce кирпич бэклога)."""
        ...

    # ── ХОЛОДНЫЙ СНИМОК / СВЕРКА (REST, read-only) ─────────────────────────
    @abstractmethod
    async def get_positions(self, account: int) -> list[Position]:
        """Cold-start снимок состояния (PositionStore.init) + verify-flat сторожа."""
        ...

    @abstractmethod
    async def get_filled(self, symbol: str, account: int, limit: int = 50) -> list[dict]:
        """Резерв: статус закрытия при cold-start (когда WS-истории нет)."""
        ...

    @abstractmethod
    async def get_income(self, symbol: str, account: int, start_ms: int, end_ms: int) -> float:
        """CUTOVER-fallback: realized $ по symbol в окне [start_ms,end_ms] из income-ledger
        ($-истина биржи). Когда WS closing-fill o.rp не пойман (pa=0 без fill) — последний
        авторитетный источник realized. 0.0 если записей нет."""
        ...

    @abstractmethod
    async def balances(self, account: int) -> dict:
        """equity/available/used_margin/unrealized_pnl одного аккаунта."""
        ...

    # ── ИСТИНА СОСТОЯНИЯ (WS) ──────────────────────────────────────────────
    @abstractmethod
    async def open_user_stream(self, account: int,
                              on_event: Callable[[int, ExecEvent], Awaitable[None]]) -> Any:
        """listenKey lifecycle + keepalive + reconnect. Сырьё нормализуется через
        normalize_event и передаётся в on_event(account, ExecEvent).
        Сейчас эквивалент user_data_ws.UserDataStream + start_exec_ws."""
        ...

    @abstractmethod
    def normalize_event(self, raw: dict, account: int) -> list[ExecEvent]:
        """Сырой ORDER_TRADE_UPDATE/ACCOUNT_UPDATE → доменные ExecEvent.
        ВСЯ парсинг-специфика биржи (o./a. поля, casing positionID) — ЗДЕСЬ.
        account передаётся явно — его нет в WS-payload (известен per-stream)."""
        ...
