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
                 router=None, ledger=None, on_close: Optional[CloseCallback] = None,
                 pid_resolver=None):
        self._adapter = adapter
        self._store = store
        self._router = router
        self._ledger = ledger
        self._on_close = on_close          # None → SHADOW (close-path выключен)
        self._pid_resolver = pid_resolver  # (acc,sym,side)→positionId из БД (WS pid не даёт; БД 100%)
        self._equity: dict[int, float] = {}
        self._reconcile_streak: dict = {}  # (acc,sym,side)→циклов подряд флэт-на-бирже (watchdog §6)

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
    async def close(self, position_id: str, reason: str = "manual", *,
                    symbol: str = "", side: str = "", qty: float = 0.0,
                    account: int | None = None) -> CloseResult:
        """Закрыть позицию. Store — основной путь, биржа — фолбэк.

        🔴 20.08: store наполняется ТОЛЬКО из WS-событий и одного cold_start при запуске.
        Позиция, открытая до старта или пропущенная при разрыве WS, в него не попадает —
        и закрыть её было НЕЧЕМ: 53 975 отказов «position not found in store» в логе,
        записи висели до 22 суток при TTL 2. Для impulse_fib это критично: выход по
        времени даёт 37% филов и три четверти прибыли механики.

        Фолбэк зовёт `close_reduce_only`, который резолвит позицию НАПРЯМУЮ С БИРЖИ
        (`_resolve_position_client`), минуя память. Вызывающему достаточно знать
        symbol и side — они есть в БД.
        """
        pos = self._store.by_position_id(position_id)
        if pos is not None:
            return await self._adapter.close_reduce_only(pos.symbol, pos.side, pos.qty,
                                                          pos.account, position_id)
        if symbol and side:
            logger.info("[Sphere] close(%s): нет в store → фолбэк на биржу %s %s",
                        position_id, symbol, side)
            return await self._adapter.close_reduce_only(symbol, str(side).upper(), qty,
                                                          account, position_id)
        return CloseResult(success=False, symbol="", position_id=position_id,
                           error="position not found in store")

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
                # ГОНКА fill↔pa=0 (13.07, консилиум): ПЕРВИЧНЫЙ резолв = Δcr из САМОГО
                # события pa=0 (cumulative realized позиции) — детерминизм, ноль REST,
                # ноль ожидания. Чинит класс AVAAI: REST/income в T+1мс пусты → был rp=0
                # → мисс-класс «TP @ entry». Грейс-ожидание отклонено (латентность).
                exit_info = self._exit_from_cr_delta(account, flat, ev)
            if exit_info is None:
                # cr не пришёл в событии → дотянуть закрывающий fill по positionId (REST,
                # детерминированно — как _resolve_exit positionID-якорь). Только на гонке.
                exit_info = await self._resolve_exit_via_rest(account, flat)
            if exit_info is None:
                # CUTOVER-fallback (22.06): fill не пойман И REST-резолв пуст (one-click 101205/
                # ликвидация без positionId) → realized из income-ledger ($-истина биржи, всегда
                # есть). Поднимает o.rp-захват с ~65% к ~100% → CUTOVER флип безопасен.
                exit_info = await self._resolve_exit_via_income(account, flat)
            if exit_info is not None and exit_info.order_type != "CR_DELTA":
                # цикл позиции завершён не-cr путём → почистить cr-стеш (иначе старая база
                # протечёт в следующий цикл символа при закрытии без промежуточных pa>0)
                self._store.take_cr_delta(account, flat.symbol, flat.side, None)
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

    def backfill_position_ids(self, db_trades) -> int:
        """Backfill positionId в store из БД-сделок (simulated_trades.position_id = 100% покрытие
        via tsl_updater; WS pid НЕ даёт — ни open-fill, ни ACCOUNT_UPDATE, проверено 20.06).
        db_trades: iterable dict с symbol/direction/position_id. Без pid close при гонке = «?»."""
        n = 0
        for t in db_trades:
            try:
                pid = t.get("position_id")
                sym = t.get("symbol")
                side = (t.get("direction") or "").upper()
            except AttributeError:
                continue
            if pid and sym and self._store.set_position_id_match(sym, side, pid):
                n += 1
        return n

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
        # BACKFILL positionId в store: WS open-fill/ACCOUNT_UPDATE его НЕ несут (20.06), только
        # REST-снимок. Без pid close при гонке fill↔pa=0 = «?» → CUTOVER оставил бы строку OPEN.
        # Тянем из уже-фетченного снимка (0 лишних REST), каждый watchdog-цикл (~2мин).
        for _p in exch:
            if _p.position_id and not _p.is_flat:
                self._store.set_position_id(account, _p.symbol, _p.side, _p.position_id)
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

    async def reconcile_watchdog(self, account: int, min_cycles: int = 2) -> list[CloseIntent]:
        """§6 bounded-staleness: позиции store-open, но биржа-флэт min_cycles ЦИКЛОВ ПОДРЯД →
        escalate (страховка для пропущенного WS-закрытия / «?»-exit).

        НЕ закрывает биржу (она уже флэт) — это ДО-закрытие БД-строки: резолвит exit из REST
        (закрытие уже произошло, ищем его fill по positionId) и снимает позицию из store.
        Возвращает escalated CloseIntent (с дотянутым exit) — вызывающий логирует/закрывает БД.
        Транзиентный флэт (<min_cycles, WS-лаг) НЕ эскалирует. Возврат позиции в строй → сброс.
        """
        candidates = await self.reconcile_account(account)
        cur = {(account, c.symbol, c.side) for c in candidates}
        # сброс счётчиков для позиций, переставших быть кандидатами (вернулись/уже сняты)
        for k in [k for k in list(self._reconcile_streak) if k[0] == account and k not in cur]:
            del self._reconcile_streak[k]
        escalated: list[CloseIntent] = []
        for c in candidates:
            k = (account, c.symbol, c.side)
            self._reconcile_streak[k] = self._reconcile_streak.get(k, 0) + 1
            if self._reconcile_streak[k] < min_cycles:
                continue   # транзиент — ждём подтверждения
            pos = self._store.get(account, c.symbol, c.side)
            exit_info = await self._resolve_exit_via_rest(account, pos) if pos is not None else None
            self._store.drop(account, c.symbol, c.side)   # биржа-флэт подтверждена → снять из истины
            self._reconcile_streak.pop(k, None)
            escalated.append(replace(c, exit=exit_info))
        return escalated

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

    def _exit_from_cr_delta(self, account: int, flat: Position,
                            ev: PositionEvent) -> Optional[ExitInfo]:
        """Гонка fill↔pa=0, первичный резолв: realized = Δcr из закрывающего ACCOUNT_UPDATE.

        Валидация 13.07 (shadow-логи vs БД): cr(pa=0) ≈ realized сделки нетто (Δ от gross =
        fees: AVAAI −0.17, RIVER −0.15, UAI −0.18); ORDI показал сброс cr при новом цикле →
        дельта от последнего стеша (store.take_cr_delta). exit_price восстановлен из
        realized+entry+qty (цену cr не даёт; настоящую цену несёт fill — он в приоритете
        через take_exit). Статус по знаку rp (classify_exit); SL→TSL уточняет db_writer.
        Возврат None (cr отсутствует/цена невосстановима) → каскад REST→income.
        """
        cr_final = ev.position.cum_realized
        if cr_final is None:
            return None
        delta = self._store.take_cr_delta(account, flat.symbol, flat.side, cr_final)
        if delta is None:
            return None
        exit_price = 0.0
        if flat.entry and flat.qty:
            d = 1.0 if flat.side == "LONG" else -1.0
            exit_price = flat.entry + d * delta / flat.qty
        if exit_price <= 0:
            return None   # без entry/qty цену не восстановить — не гадаем, каскад дальше
        logger.info("[Sphere] exit via CR-DELTA (гонка fill↔pa=0): %s %s acc=%d Δcr=%.4g exit~%.8g",
                    flat.symbol, flat.side, account, delta, exit_price)
        return ExitInfo(symbol=flat.symbol, side=flat.side, account=account,
                        exit_price=float(exit_price), realized_pnl=float(delta),
                        status=classify_exit("CR_DELTA", delta), order_type="CR_DELTA",
                        position_id=flat.position_id, ts=time.time())

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
        if pid is None and self._pid_resolver is not None:
            # store не имеет pid (WS его НЕ даёт — ни open-fill, ни ACCOUNT_UPDATE) → дотянуть из БД
            # (simulated_trades.position_id = 100% via tsl_updater). Закрывает «?»-coverage гонки.
            try:
                _rpid = self._pid_resolver(account, pos.symbol, pos.side)
                if _rpid:
                    pid = str(_rpid)
                    logger.info("[Sphere] pid дотянут из БД: %s %s pid=%s", pos.symbol, pos.side, pid)
            except Exception as _pre:
                logger.debug("[Sphere] pid_resolver %s: %s", pos.symbol, _pre)
        if pid is None:
            # CUTOVER pid-fix (б): без positionId матч by symbol+side хватает ЧУЖОЙ/старый
            # close-ордер → инверсия TP↔SL (fake-R класс: ATH new TP@0.004937 vs факт SL@0.004773).
            # НЕ угадываем цену — возврат None → эскалация verify-flat/reconcile-watchdog.
            logger.info("[Sphere] exit НЕ резолвим без positionId: %s %s — эскалация (не гадаем)",
                        pos.symbol, pos.side)
            return None
        close_side = "SELL" if pos.side == "LONG" else "BUY"
        cands = [
            o for o in filled
            if str(o.get("side", "")).upper() == close_side
            and str(o.get("positionID") or o.get("positionId") or "") == pid
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

    async def _resolve_exit_via_income(self, account: int, pos: Position) -> Optional[ExitInfo]:
        """CUTOVER-fallback #2 (22.06): fill не пойман И REST order-резолв пуст (one-click 101205/
        ликвидация без positionId) → realized из income-ledger (REALIZED_PNL+ликвидация, $-истина).
        exit_price восстановлен из realized+entry+qty (income цену не даёт, но realized=факт биржи).
        Поднимает o.rp-захват ~65%→~100% без угадывания (income авторитетен). Окно — последние 5 мин.
        """
        now_ms = int(time.time() * 1000)
        try:
            realized = await self._adapter.get_income(pos.symbol, account, now_ms - 5 * 60 * 1000, now_ms)
        except Exception as e:
            logger.debug("[Sphere] income-fallback %s: %s", pos.symbol, e)
            return None
        if not realized:   # 0.0 или None → записей нет, не резолвим (эскалация verify-flat)
            logger.info("[Sphere] income-fallback %s %s: realized=0 (нет записей) — не резолвим",
                        pos.symbol, pos.side)
            return None
        # exit_price из realized: long realized=(exit-entry)*qty → exit=entry+realized/qty; short зеркально
        exit_price = pos.entry or pos.mark or 0.0
        if pos.entry and pos.qty:
            d = 1.0 if pos.side == "LONG" else -1.0
            exit_price = pos.entry + d * realized / pos.qty
        status = "LIQUIDATION" if realized < 0 and abs(realized) > 0 and not pos.entry else ("TP" if realized >= 0 else "SL")
        logger.info("[Sphere] exit via INCOME-ledger (fill+REST пусто): %s %s acc=%d realized=%.4g exit~%.8g",
                    pos.symbol, pos.side, account, realized, exit_price)
        return ExitInfo(symbol=pos.symbol, side=pos.side, account=account,
                        exit_price=float(exit_price), realized_pnl=float(realized),
                        status=status, order_type="INCOME_FALLBACK",
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
