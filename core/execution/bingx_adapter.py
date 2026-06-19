"""core.execution.bingx_adapter — BingXAdapter (Ф3.2 EXECUTION-REBUILD).

ТОНКАЯ обёртка (решение роя 4/4): реализует ExchangeAdapter, делегируя в существующие
OrderManager / AccountRouter / BingXClient / UserDataStream. БЕЗ переписи биржевых вызовов
([[principle_reuse_not_duplication]]). ccxt-rewrite — отдельный бэклог, корень не блокирует.

Что РЕАЛЬНО портируется здесь (не делегируется): `normalize_event` — единая точка парсинга
WS (ORDER_TRADE_UPDATE/ACCOUNT_UPDATE) → доменные ExecEvent. Добавляет поля, которые
exec_ws_integration сейчас НЕ использует: o.rp/o.n/o.o=LIQUIDATION/a.m=FUNDING_FEE/a.P[].mt
(дельта Ф4, см. docs/EXECUTION_SPHERE_DESIGN.md §5).

Аддитивно: НЕ подключён к живому боту (это делает Ф4). Команды/потоки финализируются там.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional

from core.exchange.bingx_client import from_bingx_symbol
from core.exchange.position_parser import parse_positions
from core.execution.adapter import ExchangeAdapter
from core.execution.domain import (
    CloseResult,
    EquityEvent,
    ExecEvent,
    Fill,
    FillEvent,
    LedgerEntry,
    LedgerEvent,
    ListenKeyExpiredEvent,
    LiquidationEvent,
    MarginModeEvent,
    OrderRequest,
    OrderResult,
    Position,
    PositionEvent,
)

logger = logging.getLogger(__name__)

# статусы ордера, означающие реальное исполнение (есть fill)
_FILL_STATUSES = {"FILLED", "PARTIALLY_FILLED"}


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class BingXAdapter(ExchangeAdapter):
    """BingX-реализация ExchangeAdapter поверх OrderManager (sticky account-routing).

    credentials: {account_id: (api_key, secret, is_vst)} — для open_user_stream.
    Команды/чтения route по symbol через AccountRouter (sticky) внутри OrderManager —
    это уже корректный мультиаккаунт-механизм (account из позиции, не из предположения).
    """

    name = "bingx"

    def __init__(self, order_manager, credentials: Optional[dict] = None):
        self._om = order_manager
        self._router = order_manager._get_router()
        self._credentials = credentials or {}

    # ── КОМАНДЫ (REST) ─────────────────────────────────────────────────────
    async def place_bracket(self, req: OrderRequest) -> OrderResult:
        br = await self._om.open_bracket(
            symbol=req.symbol, direction=req.direction,
            entry_price=req.entry_price, sl=req.sl, tp1=req.tp, tp2=None,
            qty=req.qty, leverage=req.leverage,
        )
        account = req.account if req.account is not None else self._route(req.symbol)
        return OrderResult(
            success=br.success, symbol=br.symbol, direction=br.direction, qty=br.qty,
            entry_price=br.entry_price, sl=br.sl, tp=br.tp1, account=account, mode=req.mode,
            order_id=br.order_id, sl_order_id=br.sl_order_id, tp_order_id=br.tp_order_id,
            leverage=br.leverage, notional_usdt=br.notional_usdt, error=br.error,
        )

    async def place_sl(self, symbol, side, sl, qty, account, position_id=None) -> Optional[str]:
        return await self._om.place_sl_order(symbol, side, sl, qty)

    async def place_tp(self, symbol, side, tp, qty, account, position_id=None) -> Optional[str]:
        return await self._om.place_tp_order(symbol, side, tp, qty)

    async def cancel(self, symbol, order_id, account) -> bool:
        return await self._om.cancel_order(symbol, order_id)

    async def close_reduce_only(self, symbol, side, qty, account, position_id=None) -> CloseResult:
        try:
            cli, pid = await self._om._resolve_position_client(symbol, side)
            close_side = "SELL" if str(side).upper() == "LONG" else "BUY"
            resp = await cli.close_position_market(symbol, close_side, qty,
                                                   position_id=pid or position_id)
            ok = resp.get("code", -1) == 0
            if not ok:
                # fallback one-click (как position_sync dust-close)
                resp2 = await cli.close_position_one_click(symbol)
                ok = resp2.get("code", -1) == 0
            return CloseResult(success=ok, symbol=symbol, position_id=pid or position_id,
                               status="MANUAL", error=None if ok else resp.get("msg", str(resp)))
        except Exception as e:
            logger.warning("[BingXAdapter] close_reduce_only %s %s: %s", symbol, side, e)
            return CloseResult(success=False, symbol=symbol, position_id=position_id,
                               status="MANUAL", error=str(e))

    async def set_leverage(self, symbol, side, leverage, account) -> int:
        # Standalone-сеттер не выделен в OrderManager (плечо ставит place_bracket_order).
        # Тонкая обёртка: если у клиента есть set_leverage — зовём; иначе clamp к max пары.
        cli = self._client(account, symbol)
        setter = getattr(cli, "set_leverage", None)
        if callable(setter):
            try:
                await setter(symbol, side, leverage)
                return leverage
            except Exception as e:
                logger.warning("[BingXAdapter] set_leverage %s: %s", symbol, e)
        pair_max = await self.get_max_leverage(symbol, side, account)
        return min(leverage, pair_max) if pair_max else leverage

    async def get_max_leverage(self, symbol, side, account) -> Optional[int]:
        cli = self._client(account, symbol)
        return await self._om._get_pair_max_leverage(cli, symbol, side)

    async def set_margin_mode(self, symbol, mode, account) -> bool:
        # Бот пока НЕ управляет margin-mode (margin-enforce кирпич — бэклог). Честно:
        # делегируем если у клиента есть сеттер, иначе False (не молча «ок»).
        cli = self._client(account, symbol)
        setter = getattr(cli, "set_margin_mode", None) or getattr(cli, "set_margin_type", None)
        if callable(setter):
            try:
                await setter(symbol, mode)
                return True
            except Exception as e:
                logger.warning("[BingXAdapter] set_margin_mode %s: %s", symbol, e)
        logger.info("[BingXAdapter] set_margin_mode(%s,%s) — не реализовано в клиенте (enforce-кирпич)", symbol, mode)
        return False

    # ── ХОЛОДНЫЙ СНИМОК / СВЕРКА (REST, read-only) ─────────────────────────
    async def get_positions(self, account) -> list[Position]:
        cli = self._router.client_for_account(account)
        if cli is None:
            return []
        raw = await cli.get_positions()
        out: list[Position] = []
        for pp in parse_positions(raw):
            r = pp.raw or {}
            out.append(Position(
                symbol=pp.symbol_our, side=pp.side, qty=pp.qty, account=account,
                entry=pp.entry, mark=pp.mark, upnl=pp.unrealized_pnl, leverage=pp.leverage,
                margin_mode=(r.get("marginType") or r.get("mt")),
                position_id=(str(r.get("positionId") or r.get("positionID") or "") or None),
                updated_ts=time.time(),
            ))
        return out

    async def get_filled(self, symbol, account, limit: int = 50) -> list[dict]:
        cli = self._router.client_for_account(account)
        if cli is None:
            return []
        return await cli.get_filled_orders(symbol, limit=limit)

    async def balances(self, account) -> dict:
        cli = self._router.client_for_account(account)
        if cli is None:
            return {}
        try:
            await cli.sync_time()
            r = await cli.get("/openApi/swap/v2/user/balance")
            bd = r.get("data", {}).get("balance", {}) if isinstance(r, dict) else {}
            return {
                "equity": _f(bd.get("equity")),
                "available": _f(bd.get("availableMargin")),
                "used_margin": _f(bd.get("usedMargin")),
                "unrealized_pnl": _f(bd.get("unrealizedProfit")),
            }
        except Exception as e:
            logger.warning("[BingXAdapter] balances acc=%s: %s", account, e)
            return {}

    # ── ИСТИНА СОСТОЯНИЯ (WS) ──────────────────────────────────────────────
    async def open_user_stream(self, account,
                              on_event: Callable[[int, ExecEvent], Awaitable[None]]) -> Any:
        creds = self._credentials.get(account)
        if not creds:
            raise ValueError(f"[BingXAdapter] нет credentials для account={account}")
        api_key, secret, is_vst = creds
        from core.exchange.user_data_ws import UserDataStream

        async def _handler(etype: str, msg: dict) -> None:
            for ev in self.normalize_event(msg, account):
                await on_event(account, ev)

        uds = UserDataStream(api_key, secret, is_vst=is_vst,
                             on_event=_handler, account_tag=f"acc{account}")
        return asyncio.create_task(uds.run())

    def normalize_event(self, raw: dict, account: int) -> list[ExecEvent]:
        """Сырой WS-msg → список ExecEvent. ЕДИНАЯ точка парсинга BingX WS.

        Покрывает (BINGX_WS_ACCOUNT_SPEC.md §2-3):
          ORDER_TRADE_UPDATE (o.*) → FillEvent (+LiquidationEvent если o.o=LIQUIDATION)
          ACCOUNT_UPDATE (a.*)     → EquityEvent(B.wb) · LedgerEvent(a.m=FUNDING_FEE) ·
                                     PositionEvent(P.pa) · MarginModeEvent(P.mt)
          listenKeyExpired         → ListenKeyExpiredEvent
        """
        if not isinstance(raw, dict):
            return []
        ts = (_f(raw.get("E")) / 1000.0) or time.time()
        events: list[ExecEvent] = []

        # listenKey истёк
        if raw.get("e") == "listenKeyExpired":
            return [ListenKeyExpiredEvent(account, raw.get("listenKey"))]

        # ── ORDER_TRADE_UPDATE (fill-события) ──
        o = raw.get("o")
        if isinstance(o, dict) and o:
            status = str(o.get("X", "")).upper()
            order_type = str(o.get("o", "")).upper()
            if status in _FILL_STATUSES or order_type == "LIQUIDATION":
                sym = from_bingx_symbol(str(o.get("s", "")))
                pos_side = str(o.get("ps", "")).upper()
                fill = Fill(
                    symbol=sym,
                    side=str(o.get("S", "")).upper(),
                    pos_side=pos_side,
                    order_id=str(o.get("i", "") or ""),
                    order_type=order_type,
                    status=status,
                    is_reduce_only=bool(o.get("ro", False)),
                    avg_price=_f(o.get("ap") or o.get("p")),
                    last_qty=_f(o.get("l")),
                    total_qty=_f(o.get("z") or o.get("q")),
                    realized_pnl=_f(o.get("rp")),
                    fee=_f(o.get("n")),
                    fee_asset=str(o.get("N", "") or ""),
                    position_id=(str(o.get("positionID") or o.get("positionId") or "") or None),
                )
                events.append(FillEvent(account, fill))
                if order_type == "LIQUIDATION":
                    events.append(LiquidationEvent(account, sym, pos_side, fill))
            return events

        # ── ACCOUNT_UPDATE (состояние/баланс) ──
        a = raw.get("a")
        if isinstance(a, dict) and a:
            # equity + funding из B[] (USDT)
            for b in (a.get("B") or []):
                if isinstance(b, dict) and b.get("a") == "USDT":
                    wb = _f(b.get("wb"))
                    if wb > 0:
                        events.append(EquityEvent(account, equity=wb))
                    if str(a.get("m", "")).upper() == "FUNDING_FEE":
                        events.append(LedgerEvent(account, LedgerEntry(
                            account=account, ts=ts, kind="FUNDING_FEE",
                            amount=_f(b.get("bc")), asset="USDT")))
                    break
            # позиции
            for p in (a.get("P") or []):
                if not isinstance(p, dict):
                    continue
                sym = from_bingx_symbol(str(p.get("s", "")))
                pos_side = str(p.get("ps", "")).upper()
                if not sym or pos_side not in ("LONG", "SHORT"):
                    continue
                pa = _f(p.get("pa"))
                mt = p.get("mt")
                events.append(PositionEvent(account, Position(
                    symbol=sym, side=pos_side, qty=abs(pa), account=account,
                    entry=(_f(p.get("ep")) or None), upnl=_f(p.get("up")),
                    margin_mode=mt, updated_ts=ts,
                )))
                if mt:
                    events.append(MarginModeEvent(account, sym, str(mt)))
        return events

    # ── helpers ────────────────────────────────────────────────────────────
    def _route(self, symbol: str) -> int:
        try:
            return self._router.route(symbol)
        except Exception:
            return 1

    def _client(self, account, symbol):
        cli = self._router.client_for_account(account)
        if cli is not None:
            return cli
        return self._router.get_client(symbol)
