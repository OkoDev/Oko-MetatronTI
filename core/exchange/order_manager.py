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

import json
import logging
import math
import traceback
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

    async def _get_client_synced(self) -> BingXClient:
        """DEV-145: Возвращает клиент с синхронизированным временем.
        Ресинхронизируется раз в 5 минут чтобы предотвратить накопление drift."""
        import time as _time
        client = self._get_client()
        needs_sync = (
            not client._time_synced
            or (_time.monotonic() - client._time_synced_at) > 300
        )
        if needs_sync:
            await client.sync_time()
        return client

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    def is_live(self) -> bool:
        return self._mode in (ExecutionMode.VST, ExecutionMode.LIVE)

    # ── Баланс ──────────────────────────────────────────────────────────────

    async def get_available_balance(self) -> float:
        if not self.is_live():
            return float(self._cfg.get("trading.deposit_usdt", 1000.0))
        fallback = float(self._cfg.get("trading.deposit_usdt", 1000.0))
        try:
            raw_balance = await (await self._get_client_synced()).get_balance()
            if raw_balance is None:
                logger.warning("[OrderManager] get_balance unavailable, fallback to config deposit %.2f",
                               fallback)
                return fallback
            balance = float(raw_balance)
            if math.isfinite(balance) and balance >= 0:
                return balance
            logger.warning("[OrderManager] get_balance returned non-finite %.8f, fallback to config deposit %.2f",
                           balance, fallback)
            return fallback
        except Exception as e:
            logger.warning("[OrderManager] get_balance error: %s", e)
            return fallback

    async def get_exchange_snapshot(self) -> dict:
        """Возвращает баланс + позиции с биржи (для /api/live дашборда).
        В SIM_ONLY режиме возвращает заглушку без API-запроса.
        """
        if not self.is_live():
            return {"balance": None, "positions": [], "error": "SIM_ONLY mode"}
        try:
            client = await self._get_client_synced()
            balance_resp = await client.get("/openApi/swap/v2/user/balance")
            positions = await client.get_positions()
            bd = balance_resp.get("data", {}).get("balance", {})
            return {
                "balance": {
                    "available":      float(bd.get("availableMargin", 0) or 0),
                    "equity":         float(bd.get("equity", 0) or 0),
                    "unrealized_pnl": float(bd.get("unrealizedProfit", 0) or 0),
                    "used_margin":    float(bd.get("usedMargin", 0) or 0),
                },
                "positions": positions,
                "error": None,
            }
        except Exception as e:
            logger.warning("[OrderManager] get_exchange_snapshot: %s", e)
            return {"balance": None, "positions": [], "error": str(e)}

    # ── Открытие позиции ────────────────────────────────────────────────────

    async def has_open_position(self, symbol: str) -> bool:
        """True если на бирже уже есть открытая позиция по символу (VST/LIVE)."""
        if not self.is_live():
            return False
        try:
            bx_sym = symbol.replace("/", "-").replace(":USDT", "")
            positions = await (await self._get_client_synced()).get_positions()
            for p in positions:
                if (p.get("symbol") == bx_sym
                        and abs(float(p.get("positionAmt") or p.get("availableAmt") or 0)) > 0):
                    return True
            return False
        except Exception as e:
            logger.warning("[OrderManager] has_open_position %s: %s", symbol, e)
            return False  # при ошибке не блокируем

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

        # DEV-164: guard — SL должен быть достаточно далеко от цены входа (мин. дистанция)
        # Аналог guard в trade_simulator.py — защищает VST/LIVE path от аномально близких SL
        if entry_price > 0 and sl > 0:
            _sl_dist_pct = abs(entry_price - sl) / entry_price * 100
            try:
                from core.infra.config_loader import config as _cfg_sl
                _min_sl_dist = float(_cfg_sl.get("trading.min_sl_dist_pct", 0.1))
            except Exception:
                _min_sl_dist = 0.1
            if _sl_dist_pct < _min_sl_dist:
                err = (f"DEV-164 SL too close: {_sl_dist_pct:.4f}% < {_min_sl_dist:.2f}% "
                       f"(entry={entry_price:.6g} sl={sl:.6g})")
                logger.warning("[OrderManager] %s: %s", symbol, err)
                return BracketResult(
                    success=False, mode=self._mode.value, symbol=symbol,
                    direction=direction, qty=qty, entry_price=entry_price,
                    sl=sl, tp1=tp1, tp2=tp2, error=err, notional_usdt=notional,
                )

        # DEV-159: guard — SL должен быть в правильном направлении от цены входа
        # LONG: SL < entry (стоп ниже), SHORT: SL > entry (стоп выше)
        sl_direction_ok = (sl < entry_price) if direction == "LONG" else (sl > entry_price)
        if not sl_direction_ok:
            err = f"SL direction error: {direction} entry={entry_price:.6g} sl={sl:.6g}"
            logger.error("[OrderManager] DEV-159 %s: %s", symbol, err)
            return BracketResult(
                success=False, mode=self._mode.value, symbol=symbol,
                direction=direction, qty=qty, entry_price=entry_price,
                sl=sl, tp1=tp1, tp2=tp2, error=err, notional_usdt=notional,
            )

        if notional < MIN_NOTIONAL:
            return BracketResult(
                success=False, mode=self._mode.value, symbol=symbol,
                direction=direction, qty=qty, entry_price=entry_price,
                sl=sl, tp1=tp1, tp2=tp2,
                error=f"notional={notional:.2f} < {MIN_NOTIONAL} min", notional_usdt=notional,
            )

        # Дедупликация: не открывать если позиция уже есть на бирже
        if self.is_live() and await self.has_open_position(symbol):
            logger.info("[OrderManager] %s — позиция уже открыта, пропуск", symbol)
            return BracketResult(
                success=False, mode=self._mode.value, symbol=symbol,
                direction=direction, qty=qty, entry_price=entry_price,
                sl=sl, tp1=tp1, tp2=tp2,
                error="position_already_open", notional_usdt=notional,
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
            client   = await self._get_client_synced()
            side     = "BUY" if direction == "LONG" else "SELL"
            leverage = int(self._cfg.get("trading.leverage", 5))
            sl_buf   = float(self._cfg.get("trading.sl_limit_buffer_pct", 0) or 0)
            resp     = await client.place_bracket_order(symbol=symbol, side=side, qty=qty,
                                                        sl=sl, tp=tp1, leverage=leverage,
                                                        sl_limit_buffer_pct=sl_buf)
            code = resp.get("code", -1)
            if code != 0:
                msg = resp.get("msg", str(resp))
                logger.error("[OrderManager][%s] %s ошибка: %s", self._mode.value, symbol, msg)
                return BracketResult(
                    success=False, mode=self._mode.value, symbol=symbol,
                    direction=direction, qty=qty, entry_price=entry_price,
                    sl=sl, tp1=tp1, tp2=tp2, error=msg, notional_usdt=notional,
                )

            # BUGFIX 24.04: защита от BingX API возвращающего JSON-строки вместо dict
            data_obj = resp.get("data", {})
            if isinstance(data_obj, str):
                try: data_obj = json.loads(data_obj)
                except Exception: data_obj = {}
            order_data = data_obj.get("order", {}) if isinstance(data_obj, dict) else {}
            if isinstance(order_data, str):
                try: order_data = json.loads(order_data)
                except Exception: order_data = {}
            if not isinstance(order_data, dict):
                logger.error("[OrderManager] %s bracket resp malformed: %s", symbol, resp)
                order_data = {}
            order_id     = str(order_data.get("orderId", ""))
            filled_price = float(order_data.get("avgPrice") or entry_price)
            tp_field = order_data.get("takeProfit") or {}
            if isinstance(tp_field, str):
                try: tp_field = json.loads(tp_field)
                except Exception: tp_field = {}
            sl_field = order_data.get("stopLoss") or {}
            if isinstance(sl_field, str):
                try: sl_field = json.loads(sl_field)
                except Exception: sl_field = {}
            tp_oid = str(tp_field.get("orderId") or "") if isinstance(tp_field, dict) else ""
            sl_oid = str(sl_field.get("orderId") or "") if isinstance(sl_field, dict) else ""
            tp_oid = tp_oid or None
            sl_oid = sl_oid or None
            logger.info("[OrderManager][%s] ✅ %s %s qty=%.6f entry=%.6f SL=%.6f TP=%.6f order_id=%s tp_oid=%s sl_oid=%s notional=%.2f",
                        self._mode.value.upper(), symbol, direction, qty,
                        filled_price, sl, tp1, order_id, tp_oid, sl_oid, notional)
            return BracketResult(
                success=True, mode=self._mode.value, symbol=symbol,
                direction=direction, qty=qty, entry_price=filled_price,
                sl=sl, tp1=tp1, tp2=tp2, order_id=order_id,
                tp_order_id=tp_oid, sl_order_id=sl_oid,
                notional_usdt=notional, metadata={"raw": resp},
            )
        except Exception as e:
            logger.error(
                "[OrderManager] %s open_bracket exception: %s\nTRACEBACK:\n%s\nRAW RESP: %r",
                symbol, e, traceback.format_exc(), locals().get("resp", "<no resp>"),
            )
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
            resp = await (await self._get_client_synced()).close_position_market(symbol, side, close_qty)
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
        """Находит SL orderId (STOP_MARKET ИЛИ STOP Limit) для позиции.

        Bug fix 20.04: раньше искал только STOP_MARKET → при `sl_limit_buffer_pct > 0`
        SL создаётся как STOP (DEV-175) → get_sl_order_id возвращал None →
        repair_missing_sl каждые 60с ставил новый SL → накопление 20-30 ордеров.

        Если найдено несколько SL того же pos_side — возвращаем самый свежий,
        остальные отменяем (анти-накопление).
        """
        if not self.is_live():
            return None
        try:
            orders = await (await self._get_client_synced()).get_open_orders(symbol)
            sl_orders = [
                o for o in orders
                if o.get("type") in ("STOP_MARKET", "STOP")
                and o.get("positionSide", "").upper() == pos_side.upper()
            ]
            if not sl_orders:
                return None
            # Самый свежий по времени (BingX orderTime мс)
            sl_orders.sort(key=lambda o: int(o.get("time") or o.get("updateTime") or 0), reverse=True)
            keep = sl_orders[0]
            extras = sl_orders[1:]
            if extras:
                logger.warning(
                    "[OrderManager] %s %s: найдено %d SL-ордеров, оставляем #%s, отменяем %d дубликатов",
                    symbol, pos_side, len(sl_orders), keep.get("orderId"), len(extras),
                )
                for o in extras:
                    await self.cancel_order(symbol, str(o["orderId"]))
            return str(keep["orderId"])
        except Exception as e:
            logger.warning("[OrderManager] get_sl_order_id %s %s: %s", symbol, pos_side, e)
            return None

    async def get_tp_order_id(self, symbol: str, pos_side: str) -> Optional[str]:
        """Находит TP orderId (TAKE_PROFIT_MARKET или TAKE_PROFIT) для позиции.

        По аналогии с get_sl_order_id: если найдено несколько TP того же pos_side —
        возвращаем самый свежий, остальные отменяем (анти-накопление).
        """
        if not self.is_live():
            return None
        try:
            orders = await (await self._get_client_synced()).get_open_orders(symbol)
            tp_orders = [
                o for o in orders
                if o.get("type") in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT")
                and o.get("positionSide", "").upper() == pos_side.upper()
            ]
            if not tp_orders:
                return None
            tp_orders.sort(key=lambda o: int(o.get("time") or o.get("updateTime") or 0), reverse=True)
            keep = tp_orders[0]
            extras = tp_orders[1:]
            if extras:
                logger.warning(
                    "[OrderManager] %s %s: найдено %d TP-ордеров, оставляем #%s, отменяем %d дубликатов",
                    symbol, pos_side, len(tp_orders), keep.get("orderId"), len(extras),
                )
                for o in extras:
                    await self.cancel_order(symbol, str(o["orderId"]))
            return str(keep["orderId"])
        except Exception as e:
            logger.warning("[OrderManager] get_tp_order_id %s %s: %s", symbol, pos_side, e)
            return None

    async def place_tp_order(
        self, symbol: str, pos_side: str, tp_price: float, qty: float
    ) -> Optional[str]:
        """Ставит TAKE_PROFIT_MARKET для существующей позиции."""
        if not self.is_live():
            return "SIM"
        try:
            side = "SELL" if pos_side.upper() == "LONG" else "BUY"
            client = await self._get_client_synced()
            qty_floor = await client.quantize_qty(symbol, qty)
            if qty_floor <= 0:
                logger.warning(
                    "[OrderManager] place_tp_order %s: qty=%.8f округлилось в 0 — skip",
                    symbol, qty,
                )
                return None

            # Анти-дубликат: отменяем существующие TP того же pos_side перед новым.
            try:
                existing = await client.get_open_orders(symbol)
                existing_tp = [
                    o for o in existing
                    if o.get("type") in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT")
                    and o.get("positionSide", "").upper() == pos_side.upper()
                ]
                if existing_tp:
                    logger.warning(
                        "[OrderManager] place_tp_order %s %s: уже есть %d TP — отменяю перед новым",
                        symbol, pos_side, len(existing_tp),
                    )
                    for o in existing_tp:
                        await self.cancel_order(symbol, str(o["orderId"]))
            except Exception as _e_clean:
                logger.debug("[OrderManager] place_tp_order precheck %s: %s", symbol, _e_clean)

            resp = await client.place_tp_order(
                symbol=symbol, side=side, pos_side=pos_side.upper(),
                stop_price=tp_price, qty=qty_floor,
            )
            if resp.get("code", -1) != 0:
                msg = resp.get("msg", "")
                if "must be less than the available amount" in msg:
                    real_qty = await self.get_position_qty(symbol, pos_side)
                    if real_qty and real_qty > 0:
                        qty_retry = await client.quantize_qty(symbol, real_qty)
                        resp = await client.place_tp_order(
                            symbol=symbol, side=side, pos_side=pos_side.upper(),
                            stop_price=tp_price, qty=qty_retry,
                        )
                        if resp.get("code", -1) == 0:
                            oid = str(resp.get("data", {}).get("order", {}).get("orderId", ""))
                            logger.info("[OrderManager] ✅ новый TP %s %s tp=%.6f order_id=%s (retry qty)",
                                        symbol, pos_side, tp_price, oid)
                            return oid or None
                logger.warning("[OrderManager] place_tp_order %s %s tp=%.6f: %s",
                               symbol, pos_side, tp_price, msg or resp)
                return None
            oid = str(resp.get("data", {}).get("order", {}).get("orderId", ""))
            logger.info("[OrderManager] ✅ новый TP %s %s tp=%.6f order_id=%s",
                        symbol, pos_side, tp_price, oid)
            return oid or None
        except Exception as e:
            logger.warning("[OrderManager] place_tp_order %s: %s", symbol, e)
            return None

    async def get_position_qty(self, symbol: str, pos_side: str) -> float:
        """Возвращает qty открытой позиции с биржи."""
        if not self.is_live():
            return 0.0
        try:
            bx_sym = symbol.replace("/", "-").replace(":USDT", "")
            positions = await (await self._get_client_synced()).get_positions()
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
            resp = await (await self._get_client_synced()).cancel_order(symbol, order_id)
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
        """Ставит STOP_MARKET или STOP (Limit) ордер (SL) для существующей позиции.

        DEV-175: если sl_limit_buffer_pct > 0 в config → STOP (Limit) с буфером.
        Для LONG SL: limit_price = sl_price * (1 - buffer).
        Для SHORT SL: limit_price = sl_price * (1 + buffer).
        Буфер 0 (default) → STOP_MARKET (старое поведение).
        """
        if not self.is_live():
            return "SIM"
        try:
            side = "SELL" if pos_side.upper() == "LONG" else "BUY"
            client = await self._get_client_synced()
            # Dynamic precision из /openApi/swap/v2/quote/contracts (кэш на весь процесс).
            qty_floor = await client.quantize_qty(symbol, qty)
            if qty_floor <= 0:
                logger.warning(
                    "[OrderManager] place_sl_order %s: qty=%.8f округлилось в 0 (precision?) — skip",
                    symbol, qty,
                )
                return None

            # Bug fix 20.04: анти-дубликат перед place_sl_order.
            # Если на бирже уже есть SL того же pos_side (race: fetch_and_save + repair) —
            # отменяем их, чтобы не накапливать. После cancel → place нового.
            try:
                existing = await client.get_open_orders(symbol)
                existing_sl = [
                    o for o in existing
                    if o.get("type") in ("STOP_MARKET", "STOP")
                    and o.get("positionSide", "").upper() == pos_side.upper()
                ]
                if existing_sl:
                    logger.warning(
                        "[OrderManager] place_sl_order %s %s: уже есть %d SL — отменяю перед новым",
                        symbol, pos_side, len(existing_sl),
                    )
                    for o in existing_sl:
                        await self.cancel_order(symbol, str(o["orderId"]))
            except Exception as _e_clean:
                logger.debug("[OrderManager] place_sl_order precheck %s: %s", symbol, _e_clean)

            # DEV-175: STOP-LIMIT если sl_limit_buffer_pct > 0
            limit_price: float | None = None
            try:
                from core.infra.config_loader import config as _cfg_sl
                _buf = float(_cfg_sl.get("trading.sl_limit_buffer_pct", 0) or 0)
                if _buf > 0:
                    if pos_side.upper() == "LONG":
                        limit_price = sl_price * (1.0 - _buf / 100.0)
                    else:
                        limit_price = sl_price * (1.0 + _buf / 100.0)
                    logger.info("[OrderManager] STOP-LIMIT %s %s sl=%.6f limit=%.6f (buf=%.2f%%)",
                                 symbol, pos_side, sl_price, limit_price, _buf)
            except Exception:
                pass

            resp = await client.place_stop_order(
                symbol=symbol, side=side, pos_side=pos_side.upper(),
                stop_price=sl_price, qty=qty_floor, limit_price=limit_price,
            )
            if resp.get("code", -1) != 0:
                msg = resp.get("msg", "")
                # "order size must be less than available amount X TOKEN"
                # → реальный qty с биржи отличается от сохранённого (частичное закрытие / округление)
                if "must be less than the available amount" in msg:
                    real_qty = await self.get_position_qty(symbol, pos_side)
                    if real_qty and real_qty > 0:
                        qty_retry = await client.quantize_qty(symbol, real_qty)
                        logger.info(
                            "[OrderManager] place_sl_order %s: qty mismatch (%.8f→%.8f), retry",
                            symbol, qty_floor, qty_retry,
                        )
                        resp = await client.place_stop_order(
                            symbol=symbol, side=side, pos_side=pos_side.upper(),
                            stop_price=sl_price, qty=qty_retry,
                        )
                        if resp.get("code", -1) == 0:
                            oid = str(resp.get("data", {}).get("order", {}).get("orderId", ""))
                            logger.info("[OrderManager] ✅ новый SL %s %s sl=%.6f order_id=%s (retry qty)",
                                        symbol, pos_side, sl_price, oid)
                            return oid or None
                logger.warning("[OrderManager] place_sl_order %s %s sl=%.6f: %s",
                               symbol, pos_side, sl_price, msg or resp)
                return None
            oid = str(resp.get("data", {}).get("order", {}).get("orderId", ""))
            logger.info("[OrderManager] ✅ новый SL %s %s sl=%.6f order_id=%s",
                        symbol, pos_side, sl_price, oid)
            # Post-write verification (19.04 fix B3): через 3 сек проверяем что ордер
            # реально есть в open_orders. Если нет — логируем алерт, возвращаем None.
            if oid:
                import asyncio as _asyncio
                await _asyncio.sleep(3.0)
                try:
                    _verify = await client.get_open_orders(symbol)
                    _found = any(str(o.get("orderId", "")) == oid for o in _verify)
                    if not _found:
                        logger.error(
                            "[OrderManager] ⚠️ SL VERIFY FAIL %s %s order_id=%s — ордер не найден через 3с!",
                            symbol, pos_side, oid,
                        )
                        return None
                except Exception as _ve:
                    logger.warning("[OrderManager] SL verify %s: %s (считаем OK)", symbol, _ve)
            return oid or None
        except Exception as e:
            logger.warning("[OrderManager] place_sl_order %s: %s", symbol, e)
            return None

    async def update_sl(
        self, symbol: str, pos_side: str, old_sl_order_id: str,
        new_sl_price: float, qty: float,
        old_sl_price: float = 0.0, min_move_pct: float = 0.1,
    ) -> Optional[str]:
        """Cancel ALL open STOP_MARKET по символу + place one new SL при движении TSL.
        DEV-147: вместо cancel-by-ID — отменяем все STOP_MARKET по pos_side,
        чтобы не накапливать ордера при таймаутах place_sl_order.
        """
        if not self.is_live():
            return None

        # DEV-160: TSL guard — не двигать SL если новый уровень "за ценой" (хуже текущего)
        # LONG: SL может только расти (trailing вверх). Если new < old → откат → пропуск.
        # SHORT: SL может только падать (trailing вниз). Если new > old → откат → пропуск.
        if old_sl_price > 0:
            is_long = pos_side.upper() == "LONG"
            if is_long and new_sl_price <= old_sl_price:
                logger.debug("[OrderManager] DEV-160 %s LONG TSL: new_sl=%.6g <= old_sl=%.6g — пропуск (откат)",
                             symbol, new_sl_price, old_sl_price)
                return None
            if not is_long and new_sl_price >= old_sl_price:
                logger.debug("[OrderManager] DEV-160 %s SHORT TSL: new_sl=%.6g >= old_sl=%.6g — пропуск (откат)",
                             symbol, new_sl_price, old_sl_price)
                return None

        if old_sl_price > 0:
            move_pct = abs(new_sl_price - old_sl_price) / old_sl_price * 100
            if move_pct < min_move_pct:
                logger.debug("[OrderManager] update_sl %s: движение %.3f%% < %.1f%% — пропуск",
                             symbol, move_pct, min_move_pct)
                return None

        # Отменяем ВСЕ STOP / STOP_MARKET по символу+pos_side (атомарная очистка накопленных ордеров)
        # Bug fix 19.04: type="STOP" (Stop-Limit, DEV-175) раньше не ловился → ордера накапливались
        try:
            orders = await (await self._get_client_synced()).get_open_orders(symbol)
            sl_orders = [
                o for o in orders
                if o.get("type") in ("STOP_MARKET", "STOP")
                and o.get("positionSide", "").upper() == pos_side.upper()
            ]
            if sl_orders:
                logger.info("[OrderManager] update_sl %s %s: отменяем %d SL ордеров (STOP_MARKET+STOP)",
                            symbol, pos_side, len(sl_orders))
                for o in sl_orders:
                    await self.cancel_order(symbol, str(o["orderId"]))
            else:
                logger.info("[OrderManager] update_sl %s %s: открытых SL нет — ставим напрямую",
                            symbol, pos_side)
        except Exception as e:
            logger.warning("[OrderManager] update_sl %s: ошибка get_open_orders: %s — fallback cancel by ID", symbol, e)
            await self.cancel_order(symbol, old_sl_order_id)

        new_id = await self.place_sl_order(symbol, pos_side, new_sl_price, qty)
        logger.info("[OrderManager] TSL update %s %s: SL %.6f → %.6f order_id=%s",
                    symbol, pos_side, old_sl_price, new_sl_price, new_id)
        return new_id
