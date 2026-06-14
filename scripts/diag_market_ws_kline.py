# -*- coding: utf-8 -*-
"""
diag_market_ws_kline (14.06) — тест MARKET-WS рычага разгрузки loop.

Проверяем: можно ли получать 5m/15m свечи по МНОГИМ парам через КАСТОМНЫЙ aiohttp WS
(не ccxt.pro, который дал плато 750s). Если push идёт → рычаг 4 жизнеспособен:
свечи push→кэш, scan_loop читает без REST-polling.

Public swap market WS (без listenKey): wss://open-api-swap.bingx.com/swap-market
subscribe: {"id":uuid,"reqType":"sub","dataType":"<SYM>@kline_<tf>"}
Запуск: python scripts/diag_market_ws_kline.py
"""
from __future__ import annotations
import asyncio, gzip, io, json, sys, time, uuid
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import aiohttp

WS = "wss://open-api-swap.bingx.com/swap-market"
PAIRS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT",
         "DOGE-USDT", "ADA-USDT", "AVAX-USDT", "LINK-USDT", "DOT-USDT"]
TFS = ["5m", "15m"]
LISTEN_SEC = 90


def _decode(data) -> str:
    if isinstance(data, (bytes, bytearray)):
        try:
            return gzip.GzipFile(fileobj=io.BytesIO(data)).read().decode("utf-8", "ignore")
        except Exception:
            return bytes(data).decode("utf-8", "ignore")
    return str(data)


async def main():
    n_subs = len(PAIRS) * len(TFS)
    print(f"подписок: {n_subs} ({len(PAIRS)} пар x {len(TFS)} ТФ), окно {LISTEN_SEC}s")
    kline = Counter()       # dataType -> кол-во апдейтов
    first_seen = {}
    other = Counter()
    t0 = time.time()
    deadline = t0 + LISTEN_SEC
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(WS, timeout=aiohttp.ClientTimeout(total=20), heartbeat=30) as ws:
            print("connected, отправляю subscribe...")
            for p in PAIRS:
                for tf in TFS:
                    dt = f"{p}@kline_{tf}"
                    await ws.send_str(json.dumps({"id": str(uuid.uuid4()),
                                                  "reqType": "sub", "dataType": dt}))
            print("subscribe отправлены, слушаю...")
            async for m in ws:
                if time.time() > deadline:
                    break
                if m.type not in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                    continue
                dec = _decode(m.data)
                if dec == "Ping" or '"ping"' in dec.lower():
                    try:
                        await ws.send_str("Pong")
                    except Exception:
                        pass
                    continue
                try:
                    msg = json.loads(dec)
                except Exception:
                    continue
                if not isinstance(msg, dict):
                    continue
                dt = msg.get("dataType", "")
                if "@kline_" in dt:
                    kline[dt] += 1
                    if dt not in first_seen:
                        first_seen[dt] = round(time.time() - t0, 1)
                elif msg.get("msg") == "SUCCESS":
                    other["sub_ack"] += 1
                else:
                    other[str(msg.get("dataType") or msg.get("msg") or "?")[:30]] += 1
    print("\n" + "=" * 60)
    print(f"ИТОГ за {LISTEN_SEC}s:")
    print(f"  уникальных kline-потоков с данными: {len(kline)} / {n_subs} подписок")
    print(f"  всего kline-апдейтов: {sum(kline.values())}")
    print(f"  sub_ack/прочее: {dict(other)}")
    print("\n  по потокам (поток: апдейтов, первый через Nс):")
    for dt in sorted(kline):
        print(f"    {dt:24s} {kline[dt]:4d}  (first @ {first_seen.get(dt)}s)")
    miss = [f"{p}@kline_{tf}" for p in PAIRS for tf in TFS if f"{p}@kline_{tf}" not in kline]
    if miss:
        print(f"\n  БЕЗ данных ({len(miss)}): {miss[:10]}")
    print("\nВЕРДИКТ: если потоки с данными ~= подписок → кастомный market-WS kline РАБОТАЕТ")
    print("  (рычаг 4 жизнеспособен: push свечи → кэш → scan без REST).")


if __name__ == "__main__":
    asyncio.run(main())
