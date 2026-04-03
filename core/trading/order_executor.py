"""
OrderExecutor — DEV-77.

Слой исполнения ордеров поверх TradeSimulator.
Режимы:
  SIM_ONLY — только симуляция (текущее поведение, default)
  VST      — BingX sandbox (виртуальные деньги, реальный API)
  LIVE     — реальные ордера

Не меняет TradeSimulator — параллельный слой.

Использование:
    executor = OrderExecutor(data_collector, config)
    result = await executor.open_bracket(symbol, direction, entry_price, sl, tp1, tp2, qty)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.data_collector import RealTimeData

logger = logging.getLogger(__name__)

MIN_NOTIONAL_USDT = 5.0  # BingX минимальный размер позиции


class ExecutionMode(str, Enum):
    SIM_ONLY = "sim_only"
    VST      = "vst"
    LIVE     = "live"


@dataclass
class BracketResult:
    """Результат открытия bracket-ордера."""
    success:       bool
    mode:          str
    symbol:        str
    direction:     str
    qty:           float
    entry_price:   float
    sl:            float
    tp1:           float
    tp2:           Optional[float]
    order_id:      Optional[str]    = None
    sl_order_id:   Optional[str]    = None
    tp_order_id:   Optional[str]    = None
    error:         Optional[str]    = None
    notional_usdt: float            = 0.0
    metadata:      dict             = field(default_factory=dict)


@dataclass
class PartialCloseResult:
    """Результат частичного закрытия (TP1 hit → 20%)."""
    success:     bool
    symbol:      str
    close_qty:   float
    close_price: float
    order_id:    Optional[str] = None
    error:       Optional[str] = None


class OrderExecutor:
    """
    Bracket-ордер + частичная фиксация при TP1.

    TP1 hit → закрыть 20% позиции (tp1_close_pct из конфига).
    Оставшиеся 80% продолжают с TSL.
    """

    def __init__(self, data_collector: "RealTimeData", config) -> None:
        self._dc     = data_collector
        self._cfg    = config
        self._mode   = ExecutionMode(config.get("trading.execution_mode", "sim_only"))
        self._tp1_close_pct = float(config.get("trading.tp1_close_pct", 0.20))
        self._vst_exchange = None  # инициализируется лениво при первом VST вызове

    def _get_exchange(self):
        """Возвращает exchange объект: VST sandbox или production."""
        if self._mode == ExecutionMode.VST:
            if self._vst_exchange is None:
                try:
                    import os
                    import ccxt
                    # Ключи из .env (приоритет) или config.yaml (fallback)
                    _vk = (os.environ.get("BINGX_VST_API_KEY")
                           or self._cfg.get("exchanges.api_keys.bingx_vst.api_key", ""))
                    _vs = (os.environ.get("BINGX_VST_SECRET_KEY")
                           or self._cfg.get("exchanges.api_keys.bingx_vst.secret", ""))
                    if not _vk:
                        raise ValueError("VST API key не найден (BINGX_VST_API_KEY в .env)")
                    self._vst_exchange = ccxt.bingx({
                        "apiKey": _vk,
                        "secret": _vs,
                        "enableRateLimit": True,
                        "options": {"defaultType": "future"},
                        "urls": {
                            "api": {
                                "public":  "https://open-api-vst.bingx.com",
                                "private": "https://open-api-vst.bingx.com",
                            }
                        },
                    })
                    logger.info("[OrderExecutor] VST exchange инициализирован (BingX sandbox)")
                except Exception as e:
                    logger.error("[OrderExecutor] Ошибка инициализации VST exchange: %s", e)
                    raise
            return self._vst_exchange
        # LIVE — используем production exchange из data_collector
        return self._dc.exchange

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    def is_live(self) -> bool:
        return self._mode in (ExecutionMode.VST, ExecutionMode.LIVE)

    # ─────────────────────── Основной метод ────────────────────────────────

    async def open_bracket(
        self,
        symbol:      str,
        direction:   str,          # "LONG" | "SHORT"
        entry_price: float,
        sl:          float,
        tp1:         float,
        tp2:         Optional[float] = None,
        qty:         float = 0.0,  # в базовой валюте (BTC, ETH, ...)
    ) -> BracketResult:
        """
        Открыть bracket-ордер (MARKET entry + SL + TP).

        SIM_ONLY: только логирует, возвращает результат без биржи.
        VST/LIVE: отправляет ордер через ccxt BingX.
        """
        notional = qty * entry_price

        # Валидация
        if qty <= 0:
            return BracketResult(
                success=False, mode=self._mode.value, symbol=symbol, direction=direction,
                qty=qty, entry_price=entry_price, sl=sl, tp1=tp1, tp2=tp2,
                error=f"qty={qty} <= 0", notional_usdt=notional,
            )
        if notional < MIN_NOTIONAL_USDT:
            return BracketResult(
                success=False, mode=self._mode.value, symbol=symbol, direction=direction,
                qty=qty, entry_price=entry_price, sl=sl, tp1=tp1, tp2=tp2,
                error=f"notional={notional:.2f} USDT < {MIN_NOTIONAL_USDT} USDT min",
                notional_usdt=notional,
            )

        if self._mode == ExecutionMode.SIM_ONLY:
            return await self._sim_bracket(symbol, direction, entry_price, sl, tp1, tp2, qty, notional)

        return await self._exchange_bracket(symbol, direction, entry_price, sl, tp1, tp2, qty, notional)

    # ─────────────────────── SIM_ONLY ──────────────────────────────────────

    async def _sim_bracket(
        self, symbol, direction, entry_price, sl, tp1, tp2, qty, notional
    ) -> BracketResult:
        logger.info(
            "[OrderExecutor][SIM] %s %s qty=%.4f entry=%.4f sl=%.4f tp1=%.4f tp2=%s notional=%.2f USDT",
            symbol, direction, qty, entry_price, sl, tp1,
            f"{tp2:.4f}" if tp2 else "N/A", notional,
        )
        return BracketResult(
            success=True, mode=ExecutionMode.SIM_ONLY.value,
            symbol=symbol, direction=direction, qty=qty,
            entry_price=entry_price, sl=sl, tp1=tp1, tp2=tp2,
            order_id="SIM", notional_usdt=notional,
        )

    # ─────────────────────── VST / LIVE ────────────────────────────────────

    async def _exchange_bracket(
        self, symbol, direction, entry_price, sl, tp1, tp2, qty, notional
    ) -> BracketResult:
        """BingX bracket-ордер через ccxt (VST sandbox или LIVE)."""
        try:
            exchange = self._get_exchange()
            side = "buy" if direction == "LONG" else "sell"
            params: dict = {
                "stopLoss":   {"type": "MARKET", "triggerPrice": sl},
                "takeProfit": {"type": "MARKET", "triggerPrice": tp1},
            }
            order = await exchange.create_order(
                symbol, "MARKET", side, qty, params=params
            )
            order_id = str(order.get("id", ""))
            logger.info(
                "[OrderExecutor][%s] %s %s qty=%.4f entry=%.4f order_id=%s",
                self._mode.value.upper(), symbol, direction, qty, entry_price, order_id,
            )
            return BracketResult(
                success=True, mode=self._mode.value,
                symbol=symbol, direction=direction, qty=qty,
                entry_price=float(order.get("price") or entry_price),
                sl=sl, tp1=tp1, tp2=tp2, order_id=order_id,
                notional_usdt=notional,
                metadata={"raw_order": order},
            )
        except Exception as e:
            logger.error("[OrderExecutor][%s] open_bracket %s: %s", self._mode.value, symbol, e)
            return BracketResult(
                success=False, mode=self._mode.value,
                symbol=symbol, direction=direction, qty=qty,
                entry_price=entry_price, sl=sl, tp1=tp1, tp2=tp2,
                error=str(e), notional_usdt=notional,
            )

    # ─────────────────────── Частичная фиксация ───────────────────────────

    async def close_partial(
        self,
        symbol:      str,
        direction:   str,
        qty:         float,
        current_price: float,
    ) -> PartialCloseResult:
        """
        TP1 hit → закрыть tp1_close_pct% позиции (default 20%).

        SIM_ONLY: только логирует.
        VST/LIVE: market reduce-only ордер.
        """
        close_qty = qty * self._tp1_close_pct

        if self._mode == ExecutionMode.SIM_ONLY:
            logger.info(
                "[OrderExecutor][SIM] partial_close %s %s %.4f (%.0f%% of %.4f) @ ~%.4f",
                symbol, direction, close_qty, self._tp1_close_pct * 100, qty, current_price,
            )
            return PartialCloseResult(
                success=True, symbol=symbol, close_qty=close_qty,
                close_price=current_price, order_id="SIM",
            )

        # VST / LIVE
        try:
            exchange = self._dc.exchange
            side = "sell" if direction == "LONG" else "buy"
            params = {"reduceOnly": True}
            order = await exchange.create_order(
                symbol, "MARKET", side, close_qty, params=params
            )
            order_id = str(order.get("id", ""))
            fill_price = float(order.get("price") or current_price)
            logger.info(
                "[OrderExecutor][%s] partial_close %s qty=%.4f fill=%.4f order_id=%s",
                self._mode.value.upper(), symbol, close_qty, fill_price, order_id,
            )
            return PartialCloseResult(
                success=True, symbol=symbol, close_qty=close_qty,
                close_price=fill_price, order_id=order_id,
            )
        except Exception as e:
            logger.error("[OrderExecutor][%s] partial_close %s: %s", self._mode.value, symbol, e)
            return PartialCloseResult(
                success=False, symbol=symbol, close_qty=close_qty,
                close_price=current_price, error=str(e),
            )

    # ─────────────────────── Cancel / Close ────────────────────────────────

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Отменить ордер (SL/TP) на бирже. SIM: всегда True."""
        if self._mode == ExecutionMode.SIM_ONLY:
            logger.debug("[OrderExecutor][SIM] cancel_order %s %s", symbol, order_id)
            return True
        try:
            await self._dc.exchange.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            logger.warning("[OrderExecutor] cancel_order %s %s: %s", symbol, order_id, e)
            return False
