#!/usr/bin/env python3
"""Тест: bracket-ордер на BingX VST — что реально создаётся на бирже?

Открывает минимальную позицию с SL+TP, сразу читает open_orders, печатает все типы.
Затем закрывает позицию и отменяет оставшиеся ордера.
"""
from __future__ import annotations
import asyncio, os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONIOENCODING"] = "utf-8"

from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager


async def main():
    # Тестовая пара — дешёвая и ликвидная
    SYMBOL = "DOGE/USDT:USDT"
    DIRECTION = "LONG"  # BUY
    SIDE = "BUY"
    POS_SIDE = "LONG"

    om = OrderManager(config)
    if not om.is_live():
        print("FAIL: не в VST/LIVE режиме")
        return
    client = await om._get_client_synced()

    # 1. Текущая цена через публичный endpoint BingX
    price_resp = await client.get("/openApi/swap/v2/quote/price", {"symbol": SYMBOL.replace("/", "-").replace(":USDT", "")})
    price = float(price_resp.get("data", {}).get("price") or 0)
    if price <= 0:
        print(f"FAIL: не смог получить цену {SYMBOL}: {price_resp}")
        return
    print(f"=== Price {SYMBOL} = {price}")

    # 2. Расчёт SL/TP
    sl = round(price * 0.98, 6)   # −2%
    tp = round(price * 1.02, 6)   # +2%
    qty = 50.0                    # минимум для DOGE (~5 USDT notional при price=0.1)

    # 3. Открываем bracket с обоими buffer_pct режимами
    for buf_label, buf in (("STOP_MARKET (buf=0)", 0.0), ("STOP-LIMIT (buf=0.3)", 0.3)):
        print(f"\n==== TEST: {buf_label} ====")
        print(f"Place bracket: {SYMBOL} {DIRECTION} qty={qty} entry={price} SL={sl} TP={tp}")
        resp = await client.place_bracket_order(
            symbol=SYMBOL, side=SIDE, qty=qty,
            sl=sl, tp=tp, leverage=5,
            sl_limit_buffer_pct=buf,
        )
        code = resp.get("code", -1)
        order_data = resp.get("data", {}).get("order", {})
        oid = str(order_data.get("orderId", ""))
        print(f"bracket resp: code={code} msg={resp.get('msg','')} order_id={oid}")

        # 4. Ждём 3 сек
        await asyncio.sleep(3)

        # 5. Читаем open_orders
        open_orders = await client.get_open_orders(SYMBOL)
        print(f"open_orders after bracket ({len(open_orders)} items):")
        for o in open_orders:
            print(f"  type={o.get('type')!r:20s} side={o.get('side'):5s} posSide={o.get('positionSide'):5s} stopPrice={o.get('stopPrice')} price={o.get('price')} status={o.get('status')} orderId={o.get('orderId')}")

        # 6. Собираем статистику по типам
        types_count: dict[str, int] = {}
        for o in open_orders:
            t = o.get("type", "?")
            types_count[t] = types_count.get(t, 0) + 1
        print(f"SUMMARY types: {types_count}")

        # 7. Отменяем все ордера и закрываем позицию
        for o in open_orders:
            try:
                await client.cancel_order(SYMBOL, str(o.get("orderId")))
            except Exception as e:
                print(f"  cancel error: {e}")
        # Закрыть позицию
        try:
            close_resp = await client.close_position_market(SYMBOL, "SELL", qty)
            print(f"close_position: code={close_resp.get('code')} msg={close_resp.get('msg','')}")
        except Exception as e:
            print(f"close_position error: {e}")

        await asyncio.sleep(2)

    print("\n=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
