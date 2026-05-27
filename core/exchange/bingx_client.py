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
import math
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


# ── Symbol format conversions ─────────────────────────────────────────────
# Наш формат (ccxt-style): "BTC/USDT:USDT" — base/quote:settle
# BingX REST формат:       "BTC-USDT"      — base-quote (settle всегда USDT)
# Эти 2 функции — единственная правда о конверсии между форматами.

def to_bingx_symbol(symbol_our: str) -> str:
    """'BTC/USDT:USDT' → 'BTC-USDT' (формат BingX REST API)."""
    return (symbol_our or "").replace("/", "-").replace(":USDT", "")


def from_bingx_symbol(symbol_bx: str) -> str:
    """'BTC-USDT' → 'BTC/USDT:USDT' (наш ccxt-like формат)."""
    s = (symbol_bx or "").strip()
    if not s:
        return ""
    return s.replace("-", "/") + ":USDT"


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
        # DEV-145: time_offset корректирует расхождение local clock с BingX (ms)
        self._time_offset_ms: int = 0
        self._time_synced: bool = False
        self._time_synced_at: float = 0.0  # монотонное время последней синхронизации
        # Кэш precision контрактов: bx_symbol → {"qty": int, "price": int, "min_qty": float}
        # Загружается один раз через _load_contracts() при первом quantize_qty().
        self._contracts_cache: dict[str, dict] = {}
        self._contracts_loaded: bool = False

    async def sync_time(self) -> int:
        """
        DEV-145: Получает время BingX-сервера и вычисляет offset с учётом RTT.
        offset = local_mid - server, где local_mid = (t_before + t_after) / 2.
        Возвращает offset в миллисекундах (local - server).

        D-071 Quick Win #3 (26.05): throttle — не чаще раз в 60 сек.
        При активном рынке BingX медленный → timestamp invalid → sync_time → timeout → retry...
        Throttle разрывает порочный круг.
        """
        # Throttle: успешный sync → 60s, неудачный → 30s между попытками (BingX лагает).
        _now = time.monotonic()
        if self._time_synced and (_now - self._time_synced_at) < 60.0:
            return self._time_offset_ms
        if not self._time_synced and self._time_synced_at and (_now - self._time_synced_at) < 30.0:
            return self._time_offset_ms  # soft-fail throttle
        import aiohttp
        try:
            url = f"{self._base}/openApi/swap/v2/server/time"
            t_before = int(time.time() * 1000)
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    data = await r.json()
            t_after = int(time.time() * 1000)
            rtt = t_after - t_before
            server_ts = (
                data.get("data", {}).get("serverTime")
                or data.get("serverTime")
            )
            if server_ts:
                local_mid = (t_before + t_after) // 2
                self._time_offset_ms = local_mid - int(server_ts)
                self._time_synced = True
                self._time_synced_at = time.monotonic()
                level = "WARNING" if abs(self._time_offset_ms) > 5000 else "INFO"
                logger.log(
                    logging.WARNING if level == "WARNING" else logging.INFO,
                    "[BingXClient] time sync: offset=%+dms rtt=%dms%s",
                    self._time_offset_ms, rtt,
                    " ⚠️ БОЛЬШОЙ DRIFT — синхронизируй системные часы!" if abs(self._time_offset_ms) > 5000 else "",
                )
        except Exception as e:
            # Soft-fail: throttle retry на 30s даже при ошибке.
            # Windows clock синхронизирован через w32tm (offset ~0) — offset_ms=0 работает.
            # При реальном дрейфе поймаем 109400 → exception handler там сделает resync.
            self._time_synced_at = time.monotonic()  # throttle 30s
            self._time_synced = False  # но _synced=False чтобы при следующем вызове через 30s попробовать снова
            logger.warning("[BingXClient] sync_time failed: %s (%s) — fallback offset_ms=%d, retry через 30s",
                           e or "(timeout)", type(e).__name__, self._time_offset_ms)
        return self._time_offset_ms

    async def _load_contracts(self) -> None:
        """Загружает precision для всех контрактов один раз. Публичный endpoint без подписи."""
        import aiohttp
        if self._contracts_loaded:
            return
        try:
            url = f"{self._base}/openApi/swap/v2/quote/contracts"
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    data = await r.json()
            items = data.get("data", []) or []
            for item in items:
                bx_symbol = item.get("symbol", "")
                if not bx_symbol:
                    continue
                self._contracts_cache[bx_symbol] = {
                    "qty":     int(item.get("quantityPrecision") or 2),
                    "price":   int(item.get("pricePrecision") or 4),
                    "min_qty": float(item.get("tradeMinQuantity") or 0),
                }
            self._contracts_loaded = True
            logger.info("[BingXClient] contracts precision loaded: %d symbols", len(self._contracts_cache))
        except Exception as e:
            logger.warning("[BingXClient] _load_contracts failed: %s — fallback precision=4", e)
            self._contracts_loaded = True  # не ретраить бесконечно

    async def quantize_qty(self, symbol: str, qty: float) -> float:
        """Floor qty к precision контракта. Fallback: 4 знака после запятой."""
        if qty <= 0:
            return 0.0
        await self._load_contracts()
        bx_symbol = to_bingx_symbol(symbol)
        info = self._contracts_cache.get(bx_symbol)
        prec = int(info["qty"]) if info else 4
        factor = 10 ** prec
        return math.floor(qty * factor) / factor

    async def quantize_price(self, symbol: str, price: float) -> float:
        """Round price к precision контракта. Fallback: 6 знаков."""
        if price <= 0:
            return 0.0
        await self._load_contracts()
        bx_symbol = to_bingx_symbol(symbol)
        info = self._contracts_cache.get(bx_symbol)
        prec = int(info["price"]) if info else 6
        factor = 10 ** prec
        return round(price * factor) / factor

    def _sign(self, params_str: str) -> str:
        return hmac.new(self._secret.encode(), params_str.encode(), hashlib.sha256).hexdigest()

    def _ts(self) -> str:
        # DEV-145: корректируем local time на offset чтобы совпало с BingX
        corrected = int(time.time() * 1000) - self._time_offset_ms
        return str(corrected)

    async def get(self, path: str, params: dict | None = None) -> dict:
        import aiohttp
        p = dict(params or {})
        p["timestamp"] = self._ts()
        qs = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
        sig = self._sign(qs)
        url = f"{self._base}{path}?{qs}&signature={sig}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers={"X-BX-APIKEY": self._api_key},
                             timeout=aiohttp.ClientTimeout(total=30)) as r:
                resp = await r.json()
        # DEV-145 авто-ресинхронизация: при timestamp drift ресинхронизируем и ретраим
        if resp.get("code") == 109400 and "timestamp" in str(resp.get("msg", "")).lower():
            logger.warning("[BingXClient] timestamp is invalid — ресинхронизация и retry")
            await self.sync_time()
            p["timestamp"] = self._ts()
            qs2 = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
            sig2 = self._sign(qs2)
            url2 = f"{self._base}{path}?{qs2}&signature={sig2}"
            async with aiohttp.ClientSession() as s:
                async with s.get(url2, headers={"X-BX-APIKEY": self._api_key},
                                 timeout=aiohttp.ClientTimeout(total=30)) as r:
                    resp = await r.json()
        return resp

    async def post(self, path: str, params: dict | None = None) -> dict:
        import aiohttp
        p = dict(params or {})
        p["timestamp"] = self._ts()
        qs = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
        sig = self._sign(qs)
        url = f"{self._base}{path}?{qs}&signature={sig}"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers={"X-BX-APIKEY": self._api_key},
                              timeout=aiohttp.ClientTimeout(total=30)) as r:
                resp = await r.json()
        # 27.05.2026: timestamp drift retry — асимметрия с GET (там был, в POST нет → 2 wl_breach в SIM)
        if resp.get("code") == 109400 and "timestamp" in str(resp.get("msg", "")).lower():
            logger.warning("[BingXClient] POST timestamp is invalid — ресинхронизация и retry")
            await self.sync_time()
            p["timestamp"] = self._ts()
            qs2 = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
            sig2 = self._sign(qs2)
            url2 = f"{self._base}{path}?{qs2}&signature={sig2}"
            async with aiohttp.ClientSession() as s:
                async with s.post(url2, headers={"X-BX-APIKEY": self._api_key},
                                  timeout=aiohttp.ClientTimeout(total=30)) as r:
                    resp = await r.json()
        return resp

    async def post_raw(self, path: str, raw_qs: str, url_qs: str) -> dict:
        """POST с разделением: raw_qs для подписи HMAC, url_qs для URL (JSON URL-encoded).
        ВНИМАНИЕ: timestamp внутри raw_qs/url_qs — caller должен сам ресинкать при 109400."""
        import aiohttp
        sig = self._sign(raw_qs)
        url = f"{self._base}{path}?{url_qs}&signature={sig}"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers={"X-BX-APIKEY": self._api_key},
                              timeout=aiohttp.ClientTimeout(total=30)) as r:
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
                                timeout=aiohttp.ClientTimeout(total=30)) as r:
                resp = await r.json()
        if resp.get("code") == 109400 and "timestamp" in str(resp.get("msg", "")).lower():
            logger.warning("[BingXClient] DELETE timestamp is invalid — ресинхронизация и retry")
            await self.sync_time()
            p["timestamp"] = self._ts()
            qs2 = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
            sig2 = self._sign(qs2)
            url2 = f"{self._base}{path}?{qs2}&signature={sig2}"
            async with aiohttp.ClientSession() as s:
                async with s.delete(url2, headers={"X-BX-APIKEY": self._api_key},
                                    timeout=aiohttp.ClientTimeout(total=30)) as r:
                    resp = await r.json()
        return resp

    # ── Высокоуровневые методы ──────────────────────────────────────────────

    async def get_balance(self) -> Optional[float]:
        """Возвращает availableMargin (VST или USDT)."""
        resp = await self.get("/openApi/swap/v2/user/balance")
        if resp.get("code") != 0:
            if "timestamp is invalid" in str(resp.get("msg", "")).lower():
                logger.warning("[BingXClient] get_balance timestamp invalid, resync and retry")
                await self.sync_time()
                resp = await self.get("/openApi/swap/v2/user/balance")
            if resp.get("code") != 0:
                code = resp.get("code")
                import re as _re
                msg_str = str(resp.get("msg", ""))
                if code == 100410:
                    # Rate-limit ban: парсим время разблокировки из msg
                    srv_ts = resp.get("timestamp", 0)
                    m = _re.search(r'after\s+(\d+)', msg_str)
                    if m and srv_ts:
                        ban_sec = (int(m.group(1)) - int(srv_ts)) / 1000
                        logger.warning(
                            "[BingX RATE-LIMIT 100410] /user/balance banned for %.0fs — слишком частые REST calls",
                            ban_sec,
                        )
                    else:
                        logger.warning("[BingX RATE-LIMIT 100410] /user/balance: %s", resp)
                elif code == 109429:
                    # Бан за 20+ timestamp ошибок: парсим retry-after
                    m = _re.search(r'retry after time:\s*(\d+)', msg_str)
                    if m:
                        retry_ts = int(m.group(1))
                        ban_sec = max(0, (retry_ts - int(resp.get("timestamp", retry_ts))) / 1000)
                        logger.warning(
                            "[BingX TIMESTAMP-BAN 109429] /user/balance banned for %.0fs "
                            "— 20+ ошибок 109400. ИСПРАВЬ СИСТЕМНЫЕ ЧАСЫ WINDOWS!", ban_sec,
                        )
                    else:
                        logger.warning("[BingX TIMESTAMP-BAN 109429] /user/balance: %s", resp)
                else:
                    logger.warning("[BingXClient] get_balance error code=%s: %s", code, resp)
                return None

        balance = resp.get("data", {}).get("balance", {}) or {}
        for key in ("availableMargin", "availableBalance", "available", "balance"):
            raw = balance.get(key)
            if raw in (None, ""):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                return value

        logger.warning("[BingXClient] get_balance parse error: %s", resp)
        return None

    async def get_positions(self) -> list:
        """Возвращает список открытых позиций.
        ВАЖНО: при ошибке API бросает RuntimeError — вызывающий код обязан её поймать.
        Возврат [] при ошибке недопустим: position_sync трактует это как "позиций нет"
        и ложно закрывает все tracked сделки (инцидент 2026-04-07 21:47 UTC).
        """
        resp = await self.get("/openApi/swap/v2/user/positions")
        code = resp.get("code")
        if code != 0:
            msg = resp.get("msg", "unknown")
            logger.warning("[BingXClient] get_positions error: %s", resp)
            raise RuntimeError(f"get_positions API error code={code} msg={msg}")
        return resp.get("data", []) or []

    async def get_open_orders(self, symbol: str | None = None) -> list:
        """Возвращает открытые ордера (опционально по символу)."""
        params = {}
        if symbol:
            params["symbol"] = to_bingx_symbol(symbol)
        resp = await self.get("/openApi/swap/v2/trade/openOrders", params or None)
        return resp.get("data", {}).get("orders", []) or []

    async def get_filled_orders(self, symbol: str, limit: int = 50) -> list:
        """Возвращает последние исполненные ордера по символу.
        Используется в position_sync для определения реального exit price и статуса (SL/TP).
        BingX endpoint: GET /openApi/swap/v2/trade/allOrders
        """
        bx_symbol = to_bingx_symbol(symbol)
        resp = await self.get("/openApi/swap/v2/trade/allOrders", {
            "symbol": bx_symbol,
            "limit":  str(limit),
        })
        if resp.get("code") != 0:
            logger.warning("[BingXClient] get_filled_orders %s error: %s", symbol, resp)
            return []
        orders = resp.get("data", {}).get("orders", []) or []
        # Фильтруем только FILLED ордера
        return [o for o in orders if o.get("status") == "FILLED"]

    async def place_bracket_order(
        self, symbol: str, side: str, qty: float,
        sl: float, tp: float, leverage: int = 5,
        sl_limit_buffer_pct: float = 0.0,
    ) -> dict:
        """MARKET позиция с SL и TP (JSON-объекты, dual-signing).

        sl_limit_buffer_pct > 0 → SL как STOP (Stop-Limit) вместо STOP_MARKET.
        Для LONG: limit_price = sl * (1 - buf/100). Для SHORT: sl * (1 + buf/100).
        """
        bx_symbol = to_bingx_symbol(symbol)
        pos_side  = "LONG" if side == "BUY" else "SHORT"

        try:
            lev_resp = await self.post("/openApi/swap/v2/trade/leverage", {
                "symbol": bx_symbol, "side": pos_side, "leverage": str(leverage),
            })
            logger.debug("[BingXClient] leverage %s x%d: %s", bx_symbol, leverage, lev_resp)
        except Exception as e:
            logger.warning("[BingXClient] leverage error (продолжаем): %s", e)

        if sl_limit_buffer_pct > 0:
            sl_limit = sl * (1.0 - sl_limit_buffer_pct / 100.0) if pos_side == "LONG" \
                else sl * (1.0 + sl_limit_buffer_pct / 100.0)
            sl_obj = json.dumps({"type": "STOP", "stopPrice": sl, "price": round(sl_limit, 8), "workingType": "MARK_PRICE"}, separators=(",", ":"))
            logger.info("[BingXClient] bracket STOP-LIMIT %s %s sl=%.6f limit=%.6f (buf=%.2f%%)",
                        symbol, pos_side, sl, sl_limit, sl_limit_buffer_pct)
        else:
            sl_obj = json.dumps({"type": "STOP_MARKET", "stopPrice": sl, "price": 0, "workingType": "MARK_PRICE"}, separators=(",", ":"))
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
        limit_price: float | None = None,
    ) -> dict:
        """Ставит STOP_MARKET или STOP (Limit) ордер (для нового SL при TSL).

        Если limit_price задан → тип STOP (Stop-Limit): исполняется не хуже limit_price.
        Иначе → STOP_MARKET: исполняется по рыночной цене (возможен slippage).

        DEV-175: STOP (Limit) рекомендуется для VST через sl_limit_buffer_pct в config.
        """
        bx_symbol = to_bingx_symbol(symbol)
        params: dict = {
            "symbol":       bx_symbol,
            "side":         side,
            "positionSide": pos_side,
            "quantity":     str(qty),
            "stopPrice":    str(stop_price),
            "workingType":  "MARK_PRICE",
        }
        if limit_price is not None:
            params["type"]  = "STOP"
            params["price"] = str(limit_price)
        else:
            params["type"]  = "STOP_MARKET"
        return await self.post("/openApi/swap/v2/trade/order", params)

    async def place_tp_order(
        self, symbol: str, side: str, pos_side: str,
        stop_price: float, qty: float,
    ) -> dict:
        """Ставит TAKE_PROFIT_MARKET ордер (для восстановления TP при потере)."""
        bx_symbol = to_bingx_symbol(symbol)
        params = {
            "symbol":       bx_symbol,
            "side":         side,
            "positionSide": pos_side,
            "type":         "TAKE_PROFIT_MARKET",
            "quantity":     str(qty),
            "stopPrice":    str(stop_price),
            "workingType":  "MARK_PRICE",
        }
        return await self.post("/openApi/swap/v2/trade/order", params)

    async def cancel_order(self, symbol: str, order_id: str) -> dict:
        """Отменяет ордер."""
        bx_symbol = to_bingx_symbol(symbol)
        return await self.delete("/openApi/swap/v2/trade/order", {
            "symbol": bx_symbol, "orderId": order_id,
        })

    async def close_position_market(self, symbol: str, side: str, qty: float) -> dict:
        """Закрывает часть позиции (reduce-only MARKET)."""
        bx_symbol  = to_bingx_symbol(symbol)
        close_side = "SELL" if side == "BUY" else "BUY"
        pos_side   = "LONG" if side == "BUY" else "SHORT"
        payload = {
            "symbol":       bx_symbol,
            "side":         close_side,
            "positionSide": pos_side,
            "type":         "MARKET",
            "quantity":     str(qty),
            "reduceOnly":   "true",
        }
        resp = await self.post("/openApi/swap/v2/trade/order", payload)
        code = resp.get("code")
        msg = str(resp.get("msg", ""))
        # Hedge mode: reduceOnly=true ломается двумя кодами:
        #   109400 "ReduceOnly ... Hedge mode"
        #   101205 "No position to close" (reduceOnly не видит позицию противоположной стороны)
        if code == 109400 and "ReduceOnly" in msg and "Hedge mode" in msg:
            payload.pop("reduceOnly", None)
            return await self.post("/openApi/swap/v2/trade/order", payload)
        if code == 101205 and payload.get("reduceOnly") == "true":
            logger.info("[BingXClient] close_position_market %s: 101205 → retry без reduceOnly (hedge)", symbol)
            payload.pop("reduceOnly", None)
            return await self.post("/openApi/swap/v2/trade/order", payload)
        return resp

    async def close_position_one_click(self, symbol: str) -> dict:
        """BingX one-click close — закрывает всю позицию по символу (для dust)."""
        bx_symbol = to_bingx_symbol(symbol)
        return await self.post("/openApi/swap/v2/trade/closeAllPositions", {
            "symbol": bx_symbol,
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
