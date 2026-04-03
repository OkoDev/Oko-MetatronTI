"""
OrderManager — биржевой слой исполнения ордеров.

Знает только о бирже (BingX). Не знает о TradeSimulator, боте, Telegram.
Вызывается из monitoring.py, scan_loop.py — один вызов вместо 30 строк.

Режимы:
  SIM_ONLY — только логирует, биржу не трогает
  VST      — BingX VST sandbox
  LIVE     — реальные ордера
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from core.exchange.bingx_client import (
    BingXClient, BracketResult, PartialCloseResult,
    ExecutionMode, MIN_NOTIONAL, make_client,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Единственная точка взаимодействия с биржей.
    Все методы gracefully деградируют до SIM_ONLY если режим не live.
    """

    def __init__(self, config) -> None:
        self._cfg  = config
        self._mode = ExecutionMode(config.get("trading.execution_mode", "sim_only"))
        self._tp1_close_pct = float(config.get("trading.tp1_close_pct", 0.20))
        self._client: Optional[BingXClient] = None
        logger.info("[OrderManager] mode=%s", self._mode.value)

    def _get_client(self) -> BingXClient:
        if self._client is None:
            self._client = make_client(self._mode.value, self._cfg)
            if self._client is None:
                raise ValueError(f"[OrderManager] API ключ не найден для mode={self._mode.value}")
        return self._client

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    def is_live(self) -> bool:
        return self._mode in (ExecutionMode.VST, ExecutionMode.LIVE)

    # ── Баланс ──────────────────────────────────────────────────────────────

    async def get_available_balance(self) -> float:
        if not self.is_live():
            return float(self._cfg.get("trading.deposit_usdt", 1000.0))
        try:
            return await self._get_client().get_balance()
        except Exception as e:
            logger.warning("[OrderManager] get_balance error: %s", e)
            return float(self._cfg.get("trading.deposit_usdt", 1000.0))

    # ── Открытие позиции ────────────────────────────────────────────────────

    async def open_bracket(
        self,
        symbol:      str,
        direction:   str,
        entry_price: float,
        sl:          float,
        tp1:         float,
        tp2:         Optional[float] = None,
        qty:         float = 0.0,
    ) -> BracketResult:
        notional = qty * entry_price

        if qty <= 0:
            return BracketResult(
                success=False, mode=self._mode.value, symbol=symbol,
                direction=direction, qty=qty, entry_price=entry_price,
                sl=sl, tp1=tp1, tp2=tp2, error=f"qty={qty} <= 0", notional_usdt=notional,
            )
        if notional < MIN_NOTIONAL:
            return BracketResult(
                success=False, mode=self._mode.value, symbol=symbol,
                direction=direction, qty=qty, entry_price=entry_price,
                sl=sl, tp1=tp1, tp2=tp2,
                error=f"notional={notional:.2f} < {MIN_NOTIONAL} min", notional_usdt=notional,
            )

        if not self.is_live():
            logger.info("[OrderManager][SIM] %s %s qty=%.6f entry=%.6f SL=%.6f TP=%.6f notional=%.2f",
                        symbol, direction, qty, entry_price, sl, tp1, notional)
            return BracketResult(
                success=True, mode=ExecutionMode.SIM_ONLY.value,
                symbol=symbol, direction=direction, qty=qty,
                entry_price=entry_price, sl=sl, tp1=tp1, tp2=tp2,
                order_id="SIM", notional_usdt=notional,
            )

        try:
            client   = self._get_client()
            side     = "BUY" if direction == "LONG" else "SELL"
            leverage = int(self._cfg.get("trading.leverage", 5))
            resp     = await client.place_bracket_order(symbol=symbol, side=side, qty=qty,
                                                        sl=sl, tp=tp1, leverage=leverage)
            code = resp.get("code", -1)
            if code != 0:
                msg = resp.get("msg", str(resp))
                logger.error("[OrderManager][%s] %s ошибка: %s", self._mode.value, symbol, msg)
                return BracketResult(
                    success=False, mode=self._mode.value, symbol=symbol,
                    direction=direction, qty=qty, entry_price=entry_price,
                    sl=sl, tp1=tp1, tp2=tp2, error=msg, notional_usdt=notional,
                )

            order_data   = resp.get("data", {}).get("order", {})
            order_id     = str(order_data.get("orderId", ""))
            filled_price = float(order_data.get("avgPrice") or entry_price)
            logger.info("[OrderManager][%s] ✅ %s %s qty=%.6f entry=%.6f SL=%.6f TP=%.6f order_id=%s notional=%.2f",
                        self._mode.value.upper(), symbol, direction, qty,
                        filled_price, sl, tp1, order_id, notional)
            return BracketResult(
                success=True, mode=self._mode.value, symbol=symbol,
                direction=direction, qty=qty, entry_price=filled_price,
                sl=sl, tp1=tp1, tp2=tp2, order_id=order_id,
                notional_usdt=notional, metadata={"raw": resp},
            )
        except Exception as e:
            logger.error("[OrderManager] %s open_bracket exception: %s", symbol, e)
            return BracketResult(
                success=False, mode=self._mode.value, symbol=symbol,
                direction=direction, qty=qty, entry_price=entry_price,
                sl=sl, tp1=tp1, tp2=tp2, error=str(e), notional_usdt=notional,
            )

    # ── Частичная фиксация (TP1) ────────────────────────────────────────────

    async def close_partial(
        self, symbol: str, direction: str, qty: float, current_price: float,
    ) -> PartialCloseResult:
        close_qty = qty * self._tp1_close_pct
        if not self.is_live():
            logger.info("[OrderManager][SIM] close_partial %s %s qty=%.6f", symbol, direction, close_qty)
            return PartialCloseResult(success=True, symbol=symbol,
                                      close_qty=close_qty, close_price=current_price, order_id="SIM")
        try:
            side = "BUY" if direction == "LONG" else "SELL"
            resp = await self._get_client().close_position_market(symbol, side, close_qty)
            if resp.get("code", -1) != 0:
                return PartialCloseResult(success=False, symbol=symbol,
                                          close_qty=close_qty, close_price=current_price,
                                          error=resp.get("msg", str(resp)))
            oid = str(resp.get("data", {}).get("order", {}).get("orderId", ""))
            return PartialCloseResult(success=True, symbol=symbol,
                                      close_qty=close_qty, close_price=current_price, order_id=oid)
        except Exception as e:
            logger.error("[OrderManager] close_partial %s: %s", symbol, e)
            return PartialCloseResult(success=False, symbol=symbol,
                                      close_qty=close_qty, close_price=current_price, error=str(e))

    # ── TSL: обновление SL на бирже ─────────────────────────────────────────

    async def get_sl_order_id(self, symbol: str, pos_side: str) -> Optional[str]:
        """Находит STOP_MARKET orderId для позиции через GET openOrders."""
        if not self.is_live():
            return None
        try:
            orders = await self._get_client().get_open_orders(symbol)
            for o in orders:
                if (o.get("type") == "STOP_MARKET"
                        and o.get("positionSide", "").upper() == pos_side.upper()):
                    return str(o["orderId"])
            return None
        except Exception as e:
            logger.warning("[OrderManager] get_sl_order_id %s %s: %s", symbol, pos_side, e)
            return None

    async def get_position_qty(self, symbol: str, pos_side: str) -> float:
        """Возвращает qty открытой позиции с биржи."""
        if not self.is_live():
            return 0.0
        try:
            bx_sym = symbol.replace("/", "-").replace(":USDT", "")
            positions = await self._get_client().get_positions()
            for p in positions:
                if (p.get("symbol") == bx_sym
                        and p.get("positionSide", "").upper() == pos_side.upper()):
                    return float(p.get("positionAmt") or p.get("availableAmt") or 0)
        except Exception as e:
            logger.warning("[OrderManager] get_position_qty %s %s: %s", symbol, pos_side, e)
        return 0.0

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Отменяет ордер. False = ордер уже исполнен/не существует."""
        if not self.is_live():
            return True
        try:
            resp = await self._get_client().cancel_order(symbol, order_id)
            code = resp.get("code", -1)
            if code == 0:
                return True
            msg = resp.get("msg", "")
            if "not exist" in msg.lower() or "already" in msg.lower() or code in (80012, 80014):
                logger.info("[OrderManager] cancel_order %s #%s — уже закрыт: %s", symbol, order_id, msg)
                return False
            logger.warning("[OrderManager] cancel_order %s #%s: %s", symbol, order_id, resp)
            return True
        except Exception as e:
            logger.warning("[OrderManager] cancel_order %s #%s: %s", symbol, order_id, e)
            return True

    async def place_sl_order(
        self, symbol: str, pos_side: str, sl_price: float, qty: float
    ) -> Optional[str]:
        """Ставит новый STOP_MARKET ордер (SL) для существующей позиции."""
        if not self.is_live():
            return "SIM"
        try:
            side = "SELL" if pos_side.upper() == "LONG" else "BUY"
            resp = await self._get_client().place_stop_order(
                symbol=symbol, side=side, pos_side=pos_side.upper(),
                stop_price=sl_price, qty=qty,
            )
            if resp.get("code", -1) != 0:
                logger.warning("[OrderManager] place_sl_order %s %s sl=%.6f: %s",
                               symbol, pos_side, sl_price, resp.get("msg", resp))
                return None
            oid = str(resp.get("data", {}).get("order", {}).get("orderId", ""))
            logger.info("[OrderManager] ✅ новый SL %s %s sl=%.6f order_id=%s",
                        symbol, pos_side, sl_price, oid)
            return oid or None
        except Exception as e:
            logger.warning("[OrderManager] place_sl_order %s: %s", symbol, e)
            return None

    async def update_sl(
        self, symbol: str, pos_side: str, old_sl_order_id: str,
        new_sl_price: float, qty: float,
        old_sl_price: float = 0.0, min_move_pct: float = 0.1,
    ) -> Optional[str]:
        """Cancel + replace SL при движении TSL. Фильтр мелких движений."""
        if not self.is_live():
            return None
        if old_sl_price > 0:
            move_pct = abs(new_sl_price - old_sl_price) / old_sl_price * 100
            if move_pct < min_move_pct:
                logger.debug("[OrderManager] update_sl %s: движение %.3f%% < %.1f%% — пропуск",
                             symbol, move_pct, min_move_pct)
                return None
        exists = await self.cancel_order(symbol, old_sl_order_id)
        if not exists:
            return None   # позиция закрыта биржей — sync подхватит
        new_id = await self.place_sl_order(symbol, pos_side, new_sl_price, qty)
        logger.info("[OrderManager] TSL update %s %s: SL %.6f → %.6f order_id=%s",
                    symbol, pos_side, old_sl_price, new_sl_price, new_id)
        return new_id
