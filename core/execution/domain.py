"""core.execution.domain — доменная модель Execution Sphere (биржа-агностик).

Дизайн: docs/EXECUTION_SPHERE_DESIGN.md §2. Тест чистоты (ARCH-96-HUB): ни одно имя
здесь не содержит «BingX». Биржевую специфику (positionId casing, one_click, 109400)
инкапсулирует BingXAdapter, наружу отдаёт эти dataclass'ы.

ExecMode значения совпадают с core.exchange.bingx_client.ExecutionMode (sim_only/vst/live) —
parity-тест (tests/test_execution_calc_parity.py) запрещает дрейф между двумя перечислениями
([[principle_reuse_not_duplication]]: один смысл — одни значения).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


class ExecMode(str, Enum):
    """Режим исполнения — ЕДИНСТВЕННЫЙ переключатель песочницы (эпик §7)."""
    SIM = "sim_only"   # research-слой: НЕ трогает биржу, пишет в sim.db
    VST = "vst"        # боевая песочница (бумажные деньги) = ИСТИНА, live.db
    LIVE = "live"      # реальные деньги


# ── Команды ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class OrderRequest:
    """Запрос на открытие. mode — единственное, чем sim отличается от vst/live."""
    symbol: str                         # 'XLM/USDT:USDT' (наш формат БД)
    direction: str                      # LONG | SHORT
    entry_price: float
    sl: float
    tp: float
    qty: float
    mode: ExecMode = ExecMode.VST
    leverage: Optional[int] = None      # None → глобал-fallback в adapter
    account: Optional[int] = None       # None → AccountRouter.route(symbol)
    source: str = ""                    # ote_nested / ... (policy/метрики)
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class OrderResult:
    """Результат открытия. entry_price = ФАКТ fill (o.ap), leverage = ФАКТ после клампа."""
    success: bool
    symbol: str
    direction: str
    qty: float
    entry_price: float
    sl: float
    tp: float
    account: int
    mode: ExecMode = ExecMode.VST
    order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    position_id: Optional[str] = None   # якорь жизни позиции (вход+SL+TP = один pid)
    leverage: Optional[int] = None
    notional_usdt: float = 0.0
    error: Optional[str] = None


@dataclass(frozen=True)
class CloseResult:
    success: bool
    symbol: str
    position_id: Optional[str] = None
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    status: str = "MANUAL"              # SL | TP | TSL | LIQUIDATION | MANUAL
    error: Optional[str] = None


# ── Состояние / события (из WS) ───────────────────────────────────────────────
@dataclass
class Position:
    """«Что реально на бирже СЕЙЧАС» — из WS (PositionStore), НЕ REST polling."""
    symbol: str
    side: str                           # LONG | SHORT
    qty: float                          # pa; 0 == флэт == удалить
    account: int
    entry: Optional[float] = None       # ep
    mark: Optional[float] = None
    upnl: Optional[float] = None
    leverage: Optional[int] = None
    margin_mode: Optional[str] = None   # mt: cross | isolated
    position_id: Optional[str] = None
    updated_ts: float = 0.0
    # cr из ACCOUNT_UPDATE: cumulative realized позиции (нетто, с fees/funding).
    # Валидировано 13.07: cr(pa=0) ≈ realized сделки (Δ от gross = комиссии); ORDI показал
    # сброс cr при новом цикле позиции → потребитель берёт ДЕЛЬТУ от последнего стеша.
    cum_realized: Optional[float] = None

    @property
    def is_flat(self) -> bool:
        return abs(self.qty) < 1e-12


@dataclass(frozen=True)
class Fill:
    """Из ORDER_TRADE_UPDATE (o.*). avg_price/realized_pnl/fee — нативная истина."""
    symbol: str
    side: str                           # BUY | SELL (o.S)
    pos_side: str                       # LONG | SHORT (o.ps)
    order_id: str
    order_type: str                     # MARKET/STOP/TAKE_PROFIT/LIQUIDATION/... (o.o)
    status: str                         # FILLED/PARTIALLY_FILLED/... (o.X)
    is_reduce_only: bool
    avg_price: float                    # o.ap — реальный fill (анти-fakeR)
    last_qty: float                     # o.l
    total_qty: float                    # o.z
    realized_pnl: float = 0.0           # o.rp — $-истина
    fee: float = 0.0                    # o.n
    fee_asset: str = ""                 # o.N
    position_id: Optional[str] = None

    @property
    def is_open_fill(self) -> bool:
        """MARKET FILLED = открытие позиции — различаем по side×pos_side, НЕ по reduceOnly.

        Находка shadow 19.06: хедж-retry close (bingx_client:699-707) СНИМАЕТ reduceOnly при
        109400/101205 → плоский MARKET FILLED ro=false, который ВЫГЛЯДИТ как открытие, но это
        CLOSE. Надёжный различитель в hedge-mode: открытие = BUY+LONG | SELL+SHORT; обратное
        (SELL+LONG | BUY+SHORT) = закрытие, даже если reduceOnly снят.
        """
        if self.status != "FILLED" or self.order_type != "MARKET" or self.is_reduce_only:
            return False
        s, ps = self.side.upper(), self.pos_side.upper()
        return (s == "BUY" and ps == "LONG") or (s == "SELL" and ps == "SHORT")


@dataclass(frozen=True)
class LedgerEntry:
    """Запись денежного леджера из WS (закрывает untracked funding/комиссии)."""
    account: int
    ts: float
    kind: str                           # REALIZED_PNL | COMMISSION | FUNDING_FEE | LIQUIDATION
    amount: float
    asset: str = "USDT"
    symbol: Optional[str] = None


# ── ExecEvent: нормализованные WS-события (adapter.normalize_event → эти) ──────
@dataclass(frozen=True)
class FillEvent:
    account: int
    fill: Fill


@dataclass(frozen=True)
class PositionEvent:
    account: int
    position: Position                  # qty=0 → флэт (единственный триггер close в БД)


@dataclass(frozen=True)
class LedgerEvent:
    account: int
    entry: LedgerEntry


@dataclass(frozen=True)
class LiquidationEvent:
    account: int
    symbol: str
    side: str
    fill: Optional[Fill] = None


@dataclass(frozen=True)
class MarginModeEvent:
    account: int
    symbol: str
    margin_mode: str                    # cross | isolated


@dataclass(frozen=True)
class EquityEvent:
    account: int
    equity: float
    available: Optional[float] = None
    used_margin: Optional[float] = None


@dataclass(frozen=True)
class ListenKeyExpiredEvent:
    account: int
    listen_key: Optional[str] = None


ExecEvent = Union[
    FillEvent,
    PositionEvent,
    LedgerEvent,
    LiquidationEvent,
    MarginModeEvent,
    EquityEvent,
    ListenKeyExpiredEvent,
]
