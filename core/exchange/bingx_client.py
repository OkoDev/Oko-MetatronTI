"""
BingX HTTP-клиент низкого уровня.

Всё биржевое начинается здесь: подпись запросов, константы, типы данных.
Ни SimulatorAdapter, ни TradeSimulator сюда не смотрят.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# ── Константы ──────────────────────────────────────────────────────────────
MIN_NOTIONAL  = 5.0
VST_BASE_URL  = "https://open-api-vst.bingx.com"
LIVE_BASE_URL = "https://open-api.bingx.com"


# ── Режим исполнения ────────────────────────────────────────────────────────
class ExecutionMode(str, Enum):
    SIM_ONLY = "sim_only"
    VST      = "vst"
    LIVE     = "live"


# ── Dataclasses результатов ─────────────────────────────────────────────────
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
    order_id:      Optional[str]  = None
    sl_order_id:   Optional[str]  = None
    tp_order_id:   Optional[str]  = None
    error:         Optional[str]  = None
    notional_usdt: float          = 0.0
    metadata:      dict           = field(default_factory=dict)


@dataclass
class PartialCloseResult:
    """Результат частичного закрытия (TP1 hit)."""
    success:     bool
    symbol:      str
    close_qty:   float
    close_price: float
    order_id:    Optional[str] = None
    error:       Optional[str] = None


# ── HTTP-клиент ─────────────────────────────────────────────────────────────
class BingXClient:
    """
    Минимальный HTTP-клиент для BingX Perpetual Futures API.
    Используется только для VST и LIVE режимов.
    Не знает ни о SimulatorAdapter, ни о TradeSimulator.
    """

    def __init__(self, api_key: str, secret: str, base_url: str) -> None:
        self._api_key = api_key
        self._secret  = secret
        self._base    = base_url.rstrip("/")

    def _sign(self, params_str: str) -> str:
        return hmac.new(self._secret.encode(), params_str.encode(), hashlib.sha256).hexdigest()

    def _ts(self) -> str:
        return str(int(time.time() * 1000))

    async def get(self, path: str, params: dict | None = None) -> dict:
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

    async def post(self, path: str, params: dict | None = None) -> dict:
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

    async def post_raw(self, path: str, raw_qs: str, url_qs: str) -> dict:
        """POST с разделением: raw_qs для подписи HMAC, url_qs для URL (JSON URL-encoded)."""
        import aiohttp
        sig = self._sign(raw_qs)
        url = f"{self._base}{path}?{url_qs}&signature={sig}"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers={"X-BX-APIKEY": self._api_key},
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                return await r.json()

    async def delete(self, path: str, params: dict | None = None) -> dict:
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

    # ── Высокоуровневые методы ──────────────────────────────────────────────

    async def get_balance(self) -> float:
        """Возвращает availableMargin (VST или USDT)."""
        resp = await self.get("/openApi/swap/v2/user/balance")
        try:
            return float(resp["data"]["balance"]["availableMargin"])
        except Exception:
            logger.warning("[BingXClient] get_balance parse error: %s", resp)
            return 0.0

    async def get_positions(self) -> list:
        """Возвращает список открытых позиций."""
        resp = await self.get("/openApi/swap/v2/user/positions")
        if resp.get("code") != 0:
            logger.warning("[BingXClient] get_positions error: %s", resp)
            return []
        return resp.get("data", []) or []

    async def get_open_orders(self, symbol: str | None = None) -> list:
        """Возвращает открытые ордера (опционально по символу)."""
        params = {}
        if symbol:
            params["symbol"] = symbol.replace("/", "-").replace(":USDT", "")
        resp = await self.get("/openApi/swap/v2/trade/openOrders", params or None)
        return resp.get("data", {}).get("orders", []) or []

    async def place_bracket_order(
        self, symbol: str, side: str, qty: float,
        sl: float, tp: float, leverage: int = 5,
    ) -> dict:
        """MARKET позиция с SL и TP (JSON-объекты, dual-signing)."""
        bx_symbol = symbol.replace("/", "-").replace(":USDT", "")
        pos_side  = "LONG" if side == "BUY" else "SHORT"

        try:
            lev_resp = await self.post("/openApi/swap/v2/trade/leverage", {
                "symbol": bx_symbol, "side": pos_side, "leverage": str(leverage),
            })
            logger.debug("[BingXClient] leverage %s x%d: %s", bx_symbol, leverage, lev_resp)
        except Exception as e:
            logger.warning("[BingXClient] leverage error (продолжаем): %s", e)

        sl_obj = json.dumps({"type": "STOP_MARKET",        "stopPrice": sl, "price": 0, "workingType": "MARK_PRICE"}, separators=(",", ":"))
        tp_obj = json.dumps({"type": "TAKE_PROFIT_MARKET", "stopPrice": tp, "price": 0, "workingType": "MARK_PRICE"}, separators=(",", ":"))

        ts = self._ts()
        raw_qs = (f"positionSide={pos_side}&quantity={qty}&side={side}"
                  f"&stopLoss={sl_obj}&symbol={bx_symbol}"
                  f"&takeProfit={tp_obj}&timestamp={ts}&type=MARKET")
        url_qs = (f"positionSide={pos_side}&quantity={qty}&side={side}"
                  f"&stopLoss={urllib.parse.quote(sl_obj)}&symbol={bx_symbol}"
                  f"&takeProfit={urllib.parse.quote(tp_obj)}&timestamp={ts}&type=MARKET")
        return await self.post_raw("/openApi/swap/v2/trade/order", raw_qs, url_qs)

    async def place_stop_order(
        self, symbol: str, side: str, pos_side: str,
        stop_price: float, qty: float,
    ) -> dict:
        """Ставит STOP_MARKET ордер (для нового SL при TSL)."""
        bx_symbol = symbol.replace("/", "-").replace(":USDT", "")
        return await self.post("/openApi/swap/v2/trade/order", {
            "symbol":       bx_symbol,
            "side":         side,
            "positionSide": pos_side,
            "type":         "STOP_MARKET",
            "quantity":     str(qty),
            "stopPrice":    str(stop_price),
            "workingType":  "MARK_PRICE",
            "reduceOnly":   "true",
        })

    async def cancel_order(self, symbol: str, order_id: str) -> dict:
        """Отменяет ордер."""
        bx_symbol = symbol.replace("/", "-").replace(":USDT", "")
        return await self.delete("/openApi/swap/v2/trade/order", {
            "symbol": bx_symbol, "orderId": order_id,
        })

    async def close_position_market(self, symbol: str, side: str, qty: float) -> dict:
        """Закрывает часть позиции (reduce-only MARKET)."""
        bx_symbol  = symbol.replace("/", "-").replace(":USDT", "")
        close_side = "SELL" if side == "BUY" else "BUY"
        pos_side   = "LONG" if side == "BUY" else "SHORT"
        return await self.post("/openApi/swap/v2/trade/order", {
            "symbol":       bx_symbol,
            "side":         close_side,
            "positionSide": pos_side,
            "type":         "MARKET",
            "quantity":     str(qty),
            "reduceOnly":   "true",
        })


# ── Фабрика клиента ─────────────────────────────────────────────────────────
def make_client(mode: str, config) -> BingXClient | None:
    """Создаёт BingXClient для VST или LIVE из env + config. None для SIM_ONLY."""
    import os
    if mode == "vst":
        api_key = os.environ.get("BINGX_VST_API_KEY") or config.get("exchanges.api_keys.bingx_vst.api_key", "")
        secret  = os.environ.get("BINGX_VST_SECRET_KEY") or config.get("exchanges.api_keys.bingx_vst.secret", "")
        base    = VST_BASE_URL
    elif mode == "live":
        api_key = os.environ.get("BINGX_API_KEY") or config.get("exchanges.api_keys.bingx.api_key", "")
        secret  = os.environ.get("BINGX_SECRET_KEY") or config.get("exchanges.api_keys.bingx.secret", "")
        base    = LIVE_BASE_URL
    else:
        return None
    if not api_key:
        logger.warning("[BingXClient] API key не найден для mode=%s", mode)
        return None
    return BingXClient(api_key, secret, base)
