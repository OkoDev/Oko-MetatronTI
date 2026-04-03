"""
OrderExecutor — DEV-77.

Слой исполнения ордеров поверх TradeSimulator.
Режимы:
  SIM_ONLY — только симуляция (текущее поведение, default)
  VST      — BingX VST sandbox (виртуальные деньги, реальный API)
  LIVE     — реальные ордера (production BingX)

Не меняет TradeSimulator — параллельный слой.

VST: asset = "VST" (не USDT!), endpoint = open-api-vst.bingx.com
     balance: /openApi/swap/v2/user/balance → data.balance.availableMargin
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.data_collector import RealTimeData

logger = logging.getLogger(__name__)

MIN_NOTIONAL = 5.0          # BingX минимальный notional (в VST или USDT)
VST_BASE_URL = "https://open-api-vst.bingx.com"
LIVE_BASE_URL = "https://open-api.bingx.com"


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
    """Результат частичного закрытия (TP1 hit)."""
    success:     bool
    symbol:      str
    close_qty:   float
    close_price: float
    order_id:    Optional[str] = None
    error:       Optional[str] = None


class _BingXClient:
    """
    Минимальный HTTP-клиент для BingX Perpetual Futures API.
    Используется для VST и LIVE (ccxt не умеет корректно маппить VST asset).
    """

    def __init__(self, api_key: str, secret: str, base_url: str) -> None:
        self._api_key = api_key
        self._secret  = secret
        self._base    = base_url.rstrip("/")

    def _sign(self, params_str: str) -> str:
        return hmac.new(self._secret.encode(), params_str.encode(), hashlib.sha256).hexdigest()

    def _ts(self) -> str:
        return str(int(time.time() * 1000))

    async def _get(self, path: str, params: dict | None = None) -> dict:
        import aiohttp
        p = dict(params or {})
        p["timestamp"] = self._ts()
        qs = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
        sig = self._sign(qs)
        url = f"{self._base}{path}?{qs}&signature={sig}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers={"X-BX-APIKEY": self._api_key},
                             timeout=aiohttp.ClientTimeout(total=10)) as r:
                return await r.json()

    async def _post_raw(self, path: str, raw_qs: str, url_qs: str) -> dict:
        """POST с разделением: raw_qs для подписи, url_qs для URL (JSON значения URL-encoded)."""
        import aiohttp
        sig = self._sign(raw_qs)
        url = f"{self._base}{path}?{url_qs}&signature={sig}"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers={"X-BX-APIKEY": self._api_key},
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                return await r.json()

    async def _post(self, path: str, params: dict | None = None) -> dict:
        import aiohttp
        p = dict(params or {})
        p["timestamp"] = self._ts()
        qs = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
        sig = self._sign(qs)
        url = f"{self._base}{path}?{qs}&signature={sig}"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers={"X-BX-APIKEY": self._api_key},
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                return await r.json()

    async def _delete(self, path: str, params: dict | None = None) -> dict:
        import aiohttp
        p = dict(params or {})
        p["timestamp"] = self._ts()
        qs = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
        sig = self._sign(qs)
        url = f"{self._base}{path}?{qs}&signature={sig}"
        async with aiohttp.ClientSession() as s:
            async with s.delete(url, headers={"X-BX-APIKEY": self._api_key},
                                timeout=aiohttp.ClientTimeout(total=10)) as r:
                return await r.json()

    async def get_balance(self) -> float:
        """Возвращает availableMargin (VST или USDT)."""
        resp = await self._get("/openApi/swap/v2/user/balance")
        try:
            return float(resp["data"]["balance"]["availableMargin"])
        except Exception:
            logger.warning("[BingXClient] get_balance parse error: %s", resp)
            return 0.0

    async def place_order(
        self,
        symbol:    str,
        side:      str,      # "BUY" | "SELL"
        qty:       float,
        sl:        float,
        tp:        float,
        leverage:  int = 5,
    ) -> dict:
        """
        Открывает MARKET позицию с SL и TP через BingX Perpetual API.
        SL/TP передаются как JSON объекты (тип STOP_MARKET/TAKE_PROFIT_MARKET).
        """
        bx_symbol = symbol.replace("/", "-").replace(":USDT", "")
        pos_side = "LONG" if side == "BUY" else "SHORT"

        # 1. Установить плечо
        try:
            lev_resp = await self._post("/openApi/swap/v2/trade/leverage", {
                "symbol": bx_symbol, "side": pos_side, "leverage": str(leverage),
            })
            logger.debug("[BingXClient] leverage %s x%d: %s", bx_symbol, leverage, lev_resp)
        except Exception as e:
            logger.warning("[BingXClient] leverage error (продолжаем): %s", e)

        # 2. Открыть позицию
        # SL/TP: JSON объект с числовыми значениями (не строки)
        sl_obj = json.dumps({"type": "STOP_MARKET",        "stopPrice": sl, "price": 0, "workingType": "MARK_PRICE"}, separators=(",", ":"))
        tp_obj = json.dumps({"type": "TAKE_PROFIT_MARKET", "stopPrice": tp, "price": 0, "workingType": "MARK_PRICE"}, separators=(",", ":"))

        ts = self._ts()
        # Для подписи — RAW строка (JSON не URL-encoded)
        raw_qs = (
            f"positionSide={pos_side}&quantity={qty}&side={side}"
            f"&stopLoss={sl_obj}&symbol={bx_symbol}"
            f"&takeProfit={tp_obj}&timestamp={ts}&type=MARKET"
        )
        # Для URL — JSON URL-encoded
        url_qs = (
            f"positionSide={pos_side}&quantity={qty}&side={side}"
            f"&stopLoss={urllib.parse.quote(sl_obj)}&symbol={bx_symbol}"
            f"&takeProfit={urllib.parse.quote(tp_obj)}&timestamp={ts}&type=MARKET"
        )
        return await self._post_raw("/openApi/swap/v2/trade/order", raw_qs, url_qs)

    async def close_position(self, symbol: str, side: str, qty: float) -> dict:
        """Закрывает часть позиции (reduce-only MARKET)."""
        bx_symbol = symbol.replace("/", "-").replace(":USDT", "")
        close_side = "SELL" if side == "BUY" else "BUY"
        pos_side   = "LONG" if side == "BUY" else "SHORT"
        resp = await self._post("/openApi/swap/v2/trade/order", {
            "symbol":       bx_symbol,
            "side":         close_side,
            "positionSide": pos_side,
            "type":         "MARKET",
            "quantity":     str(qty),
            "reduceOnly":   "true",
        })
        return resp


class OrderExecutor:
    """
    Bracket-ордер + частичная фиксация при TP1.

    SIM_ONLY: только логирует, не трогает биржу.
    VST:      BingX VST sandbox (73k VST виртуальных, asset="VST").
    LIVE:     production BingX (реальные деньги).
    """

    def __init__(self, data_collector: "RealTimeData", config) -> None:
        self._dc     = data_collector
        self._cfg    = config
        self._mode   = ExecutionMode(config.get("trading.execution_mode", "sim_only"))
        self._tp1_close_pct = float(config.get("trading.tp1_close_pct", 0.20))
        self._client: Optional[_BingXClient] = None

    def _get_client(self) -> _BingXClient:
        """Лениво создаёт _BingXClient для VST или LIVE."""
        if self._client is None:
            if self._mode == ExecutionMode.VST:
                api_key = (os.environ.get("BINGX_VST_API_KEY")
                           or self._cfg.get("exchanges.api_keys.bingx_vst.api_key", ""))
                secret  = (os.environ.get("BINGX_VST_SECRET_KEY")
                           or self._cfg.get("exchanges.api_keys.bingx_vst.secret", ""))
                base_url = VST_BASE_URL
            else:  # LIVE
                api_key = (os.environ.get("BINGX_API_KEY")
                           or self._cfg.get("exchanges.api_keys.bingx.api_key", ""))
                secret  = (os.environ.get("BINGX_SECRET_KEY")
                           or self._cfg.get("exchanges.api_keys.bingx.secret", ""))
                base_url = LIVE_BASE_URL
            if not api_key:
                raise ValueError(f"API key не найден для режима {self._mode}")
            self._client = _BingXClient(api_key, secret, base_url)
            logger.info("[OrderExecutor] client инициализирован: mode=%s url=%s", self._mode.value, base_url)
        return self._client

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    def is_live(self) -> bool:
        return self._mode in (ExecutionMode.VST, ExecutionMode.LIVE)

    async def get_available_balance(self) -> float:
        """Возвращает доступный баланс (VST или USDT)."""
        if self._mode == ExecutionMode.SIM_ONLY:
            return float(self._cfg.get("trading.deposit_usdt", 1000.0))
        try:
            return await self._get_client().get_balance()
        except Exception as e:
            logger.warning("[OrderExecutor] get_balance error: %s", e)
            return float(self._cfg.get("trading.deposit_usdt", 1000.0))

    # ─────────────────────── Основной метод ────────────────────────────────

    async def open_bracket(
        self,
        symbol:      str,
        direction:   str,        # "LONG" | "SHORT"
        entry_price: float,
        sl:          float,
        tp1:         float,
        tp2:         Optional[float] = None,
        qty:         float = 0.0,
    ) -> BracketResult:
        """
        Открыть позицию с SL и TP.
        SIM_ONLY: только логирует.
        VST/LIVE: реальный ордер на бирже.
        """
        notional = qty * entry_price

        if qty <= 0:
            return BracketResult(
                success=False, mode=self._mode.value, symbol=symbol, direction=direction,
                qty=qty, entry_price=entry_price, sl=sl, tp1=tp1, tp2=tp2,
                error=f"qty={qty} <= 0", notional_usdt=notional,
            )
        if notional < MIN_NOTIONAL:
            return BracketResult(
                success=False, mode=self._mode.value, symbol=symbol, direction=direction,
                qty=qty, entry_price=entry_price, sl=sl, tp1=tp1, tp2=tp2,
                error=f"notional={notional:.2f} < {MIN_NOTIONAL} min",
                notional_usdt=notional,
            )

        if self._mode == ExecutionMode.SIM_ONLY:
            return await self._sim_bracket(symbol, direction, entry_price, sl, tp1, tp2, qty, notional)

        return await self._exchange_bracket(symbol, direction, entry_price, sl, tp1, tp2, qty, notional)

    # ─────────────────────── SIM_ONLY ──────────────────────────────────────

    async def _sim_bracket(self, symbol, direction, entry_price, sl, tp1, tp2, qty, notional) -> BracketResult:
        logger.info(
            "[OrderExecutor][SIM] %s %s qty=%.6f entry=%.6f SL=%.6f TP=%.6f notional=%.2f",
            symbol, direction, qty, entry_price, sl, tp1, notional,
        )
        return BracketResult(
            success=True, mode=ExecutionMode.SIM_ONLY.value,
            symbol=symbol, direction=direction, qty=qty,
            entry_price=entry_price, sl=sl, tp1=tp1, tp2=tp2,
            order_id="SIM", notional_usdt=notional,
        )

    # ─────────────────────── VST / LIVE ────────────────────────────────────

    async def _exchange_bracket(self, symbol, direction, entry_price, sl, tp1, tp2, qty, notional) -> BracketResult:
        """BingX VST/LIVE bracket через прямой API."""
        try:
            client = self._get_client()
            side = "BUY" if direction == "LONG" else "SELL"
            leverage = int(self._cfg.get("trading.leverage", 5))

            resp = await client.place_order(
                symbol=symbol, side=side, qty=qty,
                sl=sl, tp=tp1, leverage=leverage,
            )
            logger.debug("[OrderExecutor][%s] place_order response: %s", self._mode.value, resp)

            code = resp.get("code", -1)
            if code != 0:
                msg = resp.get("msg", str(resp))
                logger.error("[OrderExecutor][%s] %s ошибка: %s", self._mode.value, symbol, msg)
                return BracketResult(
                    success=False, mode=self._mode.value,
                    symbol=symbol, direction=direction, qty=qty,
                    entry_price=entry_price, sl=sl, tp1=tp1, tp2=tp2,
                    error=msg, notional_usdt=notional,
                )

            order_data = resp.get("data", {}).get("order", {})
            order_id = str(order_data.get("orderId", ""))
            filled_price = float(order_data.get("avgPrice") or entry_price)

            logger.info(
                "[OrderExecutor][%s] ✅ %s %s qty=%.6f entry=%.6f SL=%.6f TP=%.6f order_id=%s notional=%.2f",
                self._mode.value.upper(), symbol, direction, qty,
                filled_price, sl, tp1, order_id, notional,
            )
            return BracketResult(
                success=True, mode=self._mode.value,
                symbol=symbol, direction=direction, qty=qty,
                entry_price=filled_price, sl=sl, tp1=tp1, tp2=tp2,
                order_id=order_id, notional_usdt=notional,
                metadata={"raw": resp},
            )
        except Exception as e:
            logger.error("[OrderExecutor][%s] %s exception: %s", self._mode.value, symbol, e)
            return BracketResult(
                success=False, mode=self._mode.value,
                symbol=symbol, direction=direction, qty=qty,
                entry_price=entry_price, sl=sl, tp1=tp1, tp2=tp2,
                error=str(e), notional_usdt=notional,
            )

    # ─────────────────────── TSL: обновление SL на бирже ─────────────────────

    async def get_sl_order_id(self, symbol: str, pos_side: str) -> Optional[str]:
        """Возвращает orderId STOP_MARKET ордера для позиции (для последующего cancel+replace).
        pos_side: "LONG" | "SHORT"
        """
        if self._mode == ExecutionMode.SIM_ONLY:
            return None
        try:
            bx_symbol = symbol.replace("/", "-").replace(":USDT", "")
            client = self._get_client()
            resp = await client._get("/openApi/swap/v2/trade/openOrders", {"symbol": bx_symbol})
            orders = resp.get("data", {}).get("orders", []) or []
            for o in orders:
                if (o.get("type") == "STOP_MARKET"
                        and o.get("positionSide", "").upper() == pos_side.upper()):
                    return str(o["orderId"])
            return None
        except Exception as e:
            logger.warning("[OrderExecutor] get_sl_order_id %s %s: %s", symbol, pos_side, e)
            return None

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Отменяет ордер по orderId. Возвращает True если успешно или уже отсутствует."""
        if self._mode == ExecutionMode.SIM_ONLY:
            return True
        try:
            bx_symbol = symbol.replace("/", "-").replace(":USDT", "")
            client = self._get_client()
            resp = await client._delete("/openApi/swap/v2/trade/order", {
                "symbol": bx_symbol, "orderId": order_id,
            })
            code = resp.get("code", -1)
            if code == 0:
                return True
            msg = resp.get("msg", "")
            # Ордер уже исполнен/не существует — не ошибка
            if "not exist" in msg.lower() or "already" in msg.lower() or code in (80012, 80014):
                logger.info("[OrderExecutor] cancel_order %s #%s — уже закрыт: %s", symbol, order_id, msg)
                return False  # False = ордер не найден (позиция может быть закрыта биржей)
            logger.warning("[OrderExecutor] cancel_order %s #%s error: %s", symbol, order_id, resp)
            return True  # Попробуем поставить новый всё равно
        except Exception as e:
            logger.warning("[OrderExecutor] cancel_order %s #%s: %s", symbol, order_id, e)
            return True

    async def place_sl_order(
        self, symbol: str, pos_side: str, sl_price: float, qty: float
    ) -> Optional[str]:
        """Ставит новый STOP_MARKET ордер (SL) для существующей позиции.
        Возвращает orderId нового ордера или None при ошибке.
        """
        if self._mode == ExecutionMode.SIM_ONLY:
            return "SIM"
        try:
            bx_symbol = symbol.replace("/", "-").replace(":USDT", "")
            # reduceOnly SL: side противоположный positionSide
            side = "SELL" if pos_side.upper() == "LONG" else "BUY"
            client = self._get_client()
            resp = await client._post("/openApi/swap/v2/trade/order", {
                "symbol":       bx_symbol,
                "side":         side,
                "positionSide": pos_side.upper(),
                "type":         "STOP_MARKET",
                "quantity":     str(qty),
                "stopPrice":    str(sl_price),
                "workingType":  "MARK_PRICE",
                "reduceOnly":   "true",
            })
            code = resp.get("code", -1)
            if code != 0:
                logger.warning("[OrderExecutor] place_sl_order %s %s sl=%.6f: %s",
                               symbol, pos_side, sl_price, resp.get("msg", resp))
                return None
            order_id = str(resp.get("data", {}).get("order", {}).get("orderId", ""))
            logger.info("[OrderExecutor] ✅ новый SL %s %s sl=%.6f order_id=%s",
                        symbol, pos_side, sl_price, order_id)
            return order_id or None
        except Exception as e:
            logger.warning("[OrderExecutor] place_sl_order %s: %s", symbol, e)
            return None

    async def update_sl(
        self, symbol: str, pos_side: str, old_sl_order_id: str,
        new_sl_price: float, qty: float, min_move_pct: float = 0.1,
        old_sl_price: float = 0.0,
    ) -> Optional[str]:
        """Cancel + replace SL ордер при движении TSL.
        Обновляет только если движение > min_move_pct%.
        Возвращает новый orderId или None (ошибка / не обновлялся).
        """
        if self._mode == ExecutionMode.SIM_ONLY:
            return None
        # Фильтр мелких движений
        if old_sl_price > 0:
            move_pct = abs(new_sl_price - old_sl_price) / old_sl_price * 100
            if move_pct < min_move_pct:
                logger.debug("[OrderExecutor] update_sl %s: движение %.3f%% < %.1f%% — пропуск",
                             symbol, move_pct, min_move_pct)
                return None

        exists = await self.cancel_order(symbol, old_sl_order_id)
        if not exists:
            # Ордер не найден — позиция закрыта биржей, sync подхватит
            return None

        new_id = await self.place_sl_order(symbol, pos_side, new_sl_price, qty)
        logger.info("[OrderExecutor] TSL update %s %s: SL %.6f → %.6f order_id=%s",
                    symbol, pos_side, old_sl_price, new_sl_price, new_id)
        return new_id

    # ─────────────────────── Частичная фиксация ───────────────────────────

    async def close_partial(
        self,
        symbol:        str,
        direction:     str,
        qty:           float,
        current_price: float,
    ) -> PartialCloseResult:
        """TP1 hit → закрыть tp1_close_pct% позиции (default 20%)."""
        close_qty = qty * self._tp1_close_pct
        if self._mode == ExecutionMode.SIM_ONLY:
            logger.info("[OrderExecutor][SIM] close_partial %s %s qty=%.6f price=%.6f",
                        symbol, direction, close_qty, current_price)
            return PartialCloseResult(success=True, symbol=symbol,
                                      close_qty=close_qty, close_price=current_price, order_id="SIM")
        try:
            client = self._get_client()
            side = "BUY" if direction == "LONG" else "SELL"
            resp = await client.close_position(symbol, side, close_qty)
            code = resp.get("code", -1)
            if code != 0:
                return PartialCloseResult(success=False, symbol=symbol,
                                          close_qty=close_qty, close_price=current_price,
                                          error=resp.get("msg", str(resp)))
            order_id = str(resp.get("data", {}).get("order", {}).get("orderId", ""))
            return PartialCloseResult(success=True, symbol=symbol,
                                      close_qty=close_qty, close_price=current_price, order_id=order_id)
        except Exception as e:
            logger.error("[OrderExecutor] close_partial %s: %s", symbol, e)
            return PartialCloseResult(success=False, symbol=symbol,
                                      close_qty=close_qty, close_price=current_price, error=str(e))
