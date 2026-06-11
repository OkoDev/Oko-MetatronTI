"""
test_vst_listenkey.py — проверка VST private user-data WS (12.06, OPS-06 / Execution Sphere).

Шаг 1: POST open-api-vst.bingx.com/openApi/user/auth/userDataStream → VST listenKey (REST).
Шаг 2: connect wss://open-api-ws.bingx.com/market?listenKey=<key> на ~15с (read-only).
        BingX сжимает сообщения gzip; на Ping отвечаем Pong.

ИЗОЛИРОВАН: свой REST/WS, не трогает боевой WsFeed/scan_loop. 1 соединение, read-only.
Запуск: python scripts/test_vst_listenkey.py
"""
import asyncio
import gzip
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv()

import aiohttp

VST_REST = "https://open-api-vst.bingx.com"
WS_BASE = "wss://open-api-ws.bingx.com/market?listenKey="


def _decode(data) -> str:
    if isinstance(data, (bytes, bytearray)):
        try:
            return gzip.GzipFile(fileobj=io.BytesIO(data)).read().decode("utf-8", "ignore")
        except Exception:
            return data.decode("utf-8", "ignore") if isinstance(data, bytes) else str(data)
    return str(data)


async def main():
    key = os.getenv("BINGX_VST_API_KEY") or os.getenv("BINGX_API_KEY") or ""
    if not key:
        print("[!] нет BINGX_VST_API_KEY в env")
        return

    async with aiohttp.ClientSession() as s:
        # ── Шаг 1: listenKey ─────────────────────────────────────────────
        print("=== Шаг 1: POST userDataStream (VST REST) ===")
        url = f"{VST_REST}/openApi/user/auth/userDataStream"
        listen_key = None
        try:
            async with s.post(url, headers={"X-BX-APIKEY": key}, timeout=aiohttp.ClientTimeout(total=15)) as r:
                txt = await r.text()
                print(f"  HTTP {r.status}: {txt[:250]}")
                try:
                    import json as _j
                    listen_key = _j.loads(txt).get("listenKey")
                except Exception:
                    pass
        except Exception as e:
            print(f"  [!] listenKey error: {type(e).__name__}: {e}")
            return

        if not listen_key:
            print("  [✗] listenKey не получен — VST private WS path НЕ подтверждён этим методом.")
            return
        print(f"  [✓] listenKey получен: {listen_key[:24]}...")

        # ── Шаг 2: WS проба ──────────────────────────────────────────────
        print("\n=== Шаг 2: WS connect (read-only, ~15с) ===")
        ws_url = WS_BASE + listen_key
        try:
            async with s.ws_connect(ws_url, timeout=aiohttp.ClientTimeout(total=15)) as ws:
                print(f"  [✓] WS подключён: {ws_url[:55]}...")
                got = 0
                end = asyncio.get_event_loop().time() + 15
                while asyncio.get_event_loop().time() < end and got < 5:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=8)
                    except asyncio.TimeoutError:
                        print("  [...] нет событий 8с (норма — позиции/ордера не менялись)")
                        continue
                    if msg.type in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                        decoded = _decode(msg.data)
                        if "Ping" in decoded:
                            await ws.send_str("Pong")
                            print(f"  [ping/pong] {decoded[:60]}")
                            continue
                        got += 1
                        print(f"  [событие #{got}] {decoded[:200]}")
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        print(f"  [WS закрыт/ошибка] {msg.type}")
                        break
                print(f"  [итог] получено событий: {got} (соединение работает = path подтверждён)")
        except Exception as e:
            print(f"  [!] WS error: {type(e).__name__}: {e}")

    print("\n[закрыто] REST+WS закрыты — боевой бот/scan_loop НЕ затронут.")


if __name__ == "__main__":
    asyncio.run(main())
