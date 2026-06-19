"""core.execution.sphere — ExecutionSphere (Ф4, оркестратор единого слоя исполнения).

Дизайн: docs/EXECUTION_SPHERE_DESIGN.md §4. Связывает ExchangeAdapter + PositionStore +
ExecutionLedger + ExecutionCalc. Бизнес-код зовёт ТОЛЬКО Sphere.

🔴 ПРАВИЛО-ИСТИНА ЗАКРЫТИЯ (§6): close в БД метит ТОЛЬКО on_event(PositionEvent pa=0).
Реальную запись в БД делает инъектируемый `on_close` (Ф4.1 wiring); пока None → SHADOW-лог
(«would close»). Это держит close-path выключенным до теста на копии БД (инцидент 2026-04-07).
Sphere сам БД не трогает (как и position_store) — только решает и отдаёт CloseIntent.

Ledger duck-typed (on_fill_event/on_ledger_event/set_initial_equity) — Sphere не зависит от
конкретного класса DS, остаётся коммитируемым отдельно.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Awaitable, Callable, Optional

from core.execution import calc
from core.execution.adapter import ExchangeAdapter
from core.execution.domain import (
    CloseResult,
    EquityEvent,
    ExecEvent,
    ExecMode,
    FillEvent,
    LedgerEvent,
    ListenKeyExpiredEvent,
    LiquidationEvent,
    MarginModeEvent,
    OrderRequest,
    OrderResult,
    Position,
    PositionEvent,
)
from core.execution.position_store import ExitInfo, PositionStore, classify_exit

logger = logging.getLogger(__name__)

CloseCallback = Callable[["CloseIntent"], Awaitable[None]]


@dataclass(frozen=True)
class CloseIntent:
    """Намерение закрыть сделку в БД (единственный авторитетный путь — из pa=0/reconcile)."""
    account: int
    symbol: str
    side: str
    position_id: Optional[str]
    exit: Optional[ExitInfo]            # цена/realized/статус из закрывающего fill (если был)
    reason: str                         # ws_pa0 | reconcile_ws_drop | manual


class ExecutionSphere:
    """Единый оркестратор: open / close / on_event / adjust_sl / state / cold_start / reconcile."""

    def __init__(self, adapter: ExchangeAdapter, store: PositionStore, *,
                 router=None, ledger=None, on_close: Optional[CloseCallback] = None):
        self._adapter = adapter
        self._store = store
        self._router = router
        self._ledger = ledger
        self._on_close = on_close          # None → SHADOW (close-path выключен)
        self._equity: dict[int, float] = {}

    # ── OPEN ───────────────────────────────────────────────────────────────
    async def open(self, req: OrderRequest) -> OrderResult:
        account = req.account if req.account is not None else self._route(req.symbol)
        ok, err = calc.validate_entry(req.direction, req.entry_price, req.sl, req.qty)
        if not ok:
            return OrderResult(success=False, symbol=req.symbol, direction=req.direction,
                               qty=req.qty, entry_price=req.entry_price, sl=req.sl, tp=req.tp,
                               account=account, mode=req.mode, error=err,
                               notional_usdt=req.qty * req.entry_price)
        # SIM = research: НЕ трогаем биржу (единственное отличие режима, §7)
        if req.mode == ExecMode.SIM:
            logger.info("[Sphere][SIM] %s %s qty=%.6f — research (без биржи)", req.symbol, req.direction, req.qty)
            return OrderResult(success=True, symbol=req.symbol, direction=req.direction,
                               qty=req.qty, entry_price=req.entry_price, sl=req.sl, tp=req.tp,
                               account=account, mode=ExecMode.SIM, order_id=None,
                               notional_usdt=req.qty * req.entry_price)
        return await self._adapter.place_bracket(replace(req, account=account))

    # ── CLOSE (авторитетная команда; реальный флэт подтвердит WS pa=0) ─────
    async def close(self, position_id: str, reason: str = "manual") -> CloseResult:
        pos = self._store.by_position_id(position_id)
        if pos is None:
            return CloseResult(success=False, symbol="", position_id=position_id,
                               error="position not found in store")
        return await self._adapter.close_reduce_only(pos.symbol, pos.side, pos.qty,
                                                      pos.account, position_id)

    # ── WS-ИСТИНА (единственный вход для всех событий всех аккаунтов) ──────
    async def on_event(self, account: int, ev: ExecEvent) -> Optional[CloseIntent]:
        if isinstance(ev, FillEvent):
            self._store.apply_fill(ev)
            self._ledger_call("on_fill_event", ev)
            return None

        if isinstance(ev, PositionEvent):
            flat = self._store.apply_position(ev)
            if flat is None:
                return None
            # pa=0 по отслеживаемой позиции = ЕДИНСТВЕННЫЙ авторитетный триггер close
            exit_info = self._store.take_exit(account, flat.symbol, flat.side)
            if exit_info is None:
                # ГОНКА fill↔pa=0: pa=0 пришёл раньше закрывающего ORDER_TRADE_UPDATE →
                # ExitInfo не застешился. Дотянуть закрывающий fill по positionId (REST,
                # детерминированно — как _resolve_exit positionID-якорь). Только на гонке.
                exit_info = await self._resolve_exit_via_rest(account, flat)
            intent = CloseIntent(account=account, symbol=flat.symbol, side=flat.side,
                                 position_id=flat.position_id, exit=exit_info, reason="ws_pa0")
            await self._fire_close(intent)
            return intent

        if isinstance(ev, LedgerEvent):
            self._ledger_call("on_ledger_event", ev)
            return None

        if isinstance(ev, LiquidationEvent):
            # realized ликвидации приходит через FillEvent.realized_pnl; здесь — алерт
            logger.warning("[Sphere] LIQUIDATION acc=%s %s %s", account, ev.symbol, ev.side)
            return None

        if isinstance(ev, MarginModeEvent):
            if str(ev.margin_mode).lower() == "cross":
                logger.warning("[Sphere] cross-margin дрейф acc=%s %s (ожидается isolated)",
                               account, ev.symbol)
            return None

        if isinstance(ev, EquityEvent):
            self._equity[account] = ev.equity
            return None

        if isinstance(ev, ListenKeyExpiredEvent):
            logger.warning("[Sphere] listenKey expired acc=%s — нужен reconnect", account)
            return None

        return None

    # ── TRACK ──────────────────────────────────────────────────────────────
    async def adjust_sl(self, position_id: str, new_sl: float) -> bool:
        pos = self._store.by_position_id(position_id)
        if pos is None:
            return False
        oid = await self._adapter.place_sl(pos.symbol, pos.side, new_sl, pos.qty,
                                           pos.account, position_id)
        return oid is not None

    # ── STATE (для дашборда/сайзинга — из WS-снимка, НЕ REST polling) ───────
    def state(self, account: Optional[int] = None) -> list[Position]:
        return self._store.positions(account)

    def equity(self, account: int) -> Optional[float]:
        return self._equity.get(account)

    # ── COLD-START (init Store + Ledger из REST-снимка, §10) ───────────────
    async def cold_start(self, account: int) -> list[Position]:
        positions = await self._adapter.get_positions(account)
        self._store.init_account(account, positions)
        try:
            bal = await self._adapter.balances(account)
            eq = bal.get("equity") if isinstance(bal, dict) else None
            if eq:
                self._equity[account] = float(eq)
                self._ledger_call_equity(account, float(eq))
        except Exception as e:
            logger.warning("[Sphere] cold_start balances acc=%s: %s", account, e)
        logger.info("[Sphere] cold_start acc=%s: %d позиций", account, len(positions))
        return positions

    # ── WATCHDOG (§6, страховка от потерянного WS pa=0 — read-only кандидаты) ─
    async def reconcile_account(self, account: int) -> list[CloseIntent]:
        """REST-сверка: позиции, которые Store считает OPEN, а биржа показывает ФЛЭТ.

        Возвращает КАНДИДАТЫ на close (НЕ закрывает сам). Эскалацию (bounded-staleness:
        N циклов подряд → Sphere.close) решает вызывающий цикл за флагом. Возврата
        close-by-price НЕТ — цена в решении не участвует, только факт флэта на бирже.
        """
        exch = await self._adapter.get_positions(account)
        exch_keys = {(p.symbol, p.side) for p in exch if not p.is_flat}
        intents: list[CloseIntent] = []
        for p in self._store.positions(account):
            if (p.symbol, p.side) not in exch_keys:
                intents.append(CloseIntent(account=account, symbol=p.symbol, side=p.side,
                                           position_id=p.position_id, exit=None,
                                           reason="reconcile_ws_drop"))
        return intents

    def staleness(self, account: int) -> Optional[float]:
        return self._store.staleness(account)

    # ── helpers ────────────────────────────────────────────────────────────
    async def _fire_close(self, intent: CloseIntent) -> None:
        if self._on_close is None:
            # SHADOW: close-path выкл. Наблюдаемость в WS-врезке (тег [SPHERE-SHADOW]) — здесь debug,
            # чтобы не дублировать при прогоне через exec_ws_integration.
            logger.debug("[Sphere][SHADOW] would close %s %s acc=%s (%s) exit=%s — on_close=None",
                         intent.symbol, intent.side, intent.account, intent.reason,
                         (intent.exit.status if intent.exit else "?"))
            return
        await self._on_close(intent)

    async def _resolve_exit_via_rest(self, account: int, pos: Position) -> Optional[ExitInfo]:
        """Гонка fill↔pa=0: pa=0 без застешенного fill → дотянуть закрывающий fill из REST.

        Матч по positionId (casing positionID/positionId) + close-side, последний по updateTime —
        доказанный positionID-якорь (_resolve_exit, fake-R фикс). Возврат None если не нашли
        (db_writer тогда НЕ закроет — не угадываем; эскалация verify-flat). REST только на гонке.
        """
        try:
            filled = await self._adapter.get_filled(pos.symbol, account, limit=20)
        except Exception as e:
            logger.debug("[Sphere] _resolve_exit_via_rest get_filled %s: %s", pos.symbol, e)
            return None
        if not filled:
            return None
        pid = str(pos.position_id) if pos.position_id else None
        close_side = "SELL" if pos.side == "LONG" else "BUY"
        cands = [
            o for o in filled
            if str(o.get("side", "")).upper() == close_side
            and (pid is None or str(o.get("positionID") or o.get("positionId") or "") == pid)
        ]
        if not cands:
            return None
        o = max(cands, key=lambda x: int(x.get("updateTime") or x.get("time") or 0))
        avg = o.get("avgPrice") or o.get("stopPrice") or o.get("price")
        if not avg:
            return None
        try:
            exit_price = float(avg)
        except (TypeError, ValueError):
            return None
        otype = str(o.get("type", "")).upper()
        try:
            rp = float(o.get("profit") or o.get("realizedPnl") or 0)
        except (TypeError, ValueError):
            rp = 0.0
        logger.info("[Sphere] exit дотянут REST (гонка fill↔pa=0): %s %s %s @ %.8g pid=%s",
                    pos.symbol, pos.side, otype or "?", exit_price, pid)
        return ExitInfo(symbol=pos.symbol, side=pos.side, account=account,
                        exit_price=exit_price, realized_pnl=rp,
                        status=classify_exit(otype, rp), order_type=otype,
                        position_id=pos.position_id, ts=time.time())

    def _route(self, symbol: str) -> int:
        if self._router is not None:
            try:
                return self._router.route(symbol)
            except Exception:
                pass
        return 1

    def _ledger_call(self, method: str, ev) -> None:
        if self._ledger is None:
            return
        fn = getattr(self._ledger, method, None)
        if callable(fn):
            try:
                fn(ev)
            except Exception as e:
                logger.debug("[Sphere] ledger.%s: %s", method, e)

    def _ledger_call_equity(self, account: int, equity: float) -> None:
        if self._ledger is None:
            return
        fn = getattr(self._ledger, "set_initial_equity", None)
        if callable(fn):
            try:
                fn(account, equity)
            except Exception as e:
                logger.debug("[Sphere] ledger.set_initial_equity: %s", e)
