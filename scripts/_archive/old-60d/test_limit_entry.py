#!/usr/bin/env python3
"""Тест: LIMIT-вход (Фаза 1) на BingX VST — принимает ли биржа type=LIMIT + привязанные SL/TP.

Ставит LIMIT-ордер на покупку НИЖЕ рынка (не исполнится сразу, повиснет) с SL/TP,
читает open_orders, проверяет что создан LIMIT + SL/TP, затем отменяет всё. Без исполнения.
"""
from __future__ import annotations
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONIOENCODING"] = "utf-8"

from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager


async def main():
    SYMBOL = "DOGE/USDT:USDT"
    SIDE = "BUY"  # LONG

    om = OrderManager(config)
    if not om.is_live():
        print("FAIL: не в VST/LIVE режиме")
        return
    client = await om._get_client_synced()

    price_resp = await client.get("/openApi/swap/v2/quote/price",
                                  {"symbol": SYMBOL.replace("/", "-").replace(":USDT", "")})
    price = float(price_resp.get("data", {}).get("price") or 0)
    if price <= 0:
        print(f"FAIL: нет цены {SYMBOL}: {price_resp}")
        return
    print(f"=== Price {SYMBOL} = {price}")

    # LIMIT LONG ниже рынка на 5% (не исполнится — висит как ждущий откат)
    entry = round(price * 0.95, 6)
    sl = round(entry * 0.98, 6)   # ниже лимита
    tp = round(entry * 1.05, 6)   # выше
    qty = 50.0
    print(f"Place LIMIT bracket: {SYMBOL} LONG qty={qty} entry(limit)={entry} (рынок {price}) SL={sl} TP={tp}")

    resp = await client.place_bracket_order(
        symbol=SYMBOL, side=SIDE, qty=qty, sl=sl, tp=tp, leverage=5,
        sl_limit_buffer_pct=0.0, order_type="LIMIT", entry_price=entry,
    )
    code = resp.get("code", -1)
    order_data = resp.get("data", {}).get("order", {})
    oid = str(order_data.get("orderId", ""))
    print(f"LIMIT bracket resp: code={code} msg={resp.get('msg','')} order_id={oid}")
    if code != 0:
        print("FAIL: биржа отвергла LIMIT-ордер ^^^")
        return

    await asyncio.sleep(3)
    open_orders = await client.get_open_orders(SYMBOL)
    print(f"open_orders ({len(open_orders)}):")
    has_limit = False
    for o in open_orders:
        t = o.get("type")
        if t == "LIMIT":
            has_limit = True
        print(f"  type={t!r:18s} side={o.get('side'):5s} posSide={o.get('positionSide'):5s} price={o.get('price')} stopPrice={o.get('stopPrice')} status={o.get('status')} oid={o.get('orderId')}")

    print(f"\n{'[OK] LIMIT-ордер создан' if has_limit else '[!] LIMIT не найден в open_orders'}; SL/TP привязка видна выше")

    # Отменяем всё (ничего не исполнилось — позиции нет)
    for o in open_orders:
        try:
            await client.cancel_order(SYMBOL, str(o.get("orderId")))
            print(f"  cancelled oid={o.get('orderId')}")
        except Exception as e:
            print(f"  cancel error: {e}")
    print("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
