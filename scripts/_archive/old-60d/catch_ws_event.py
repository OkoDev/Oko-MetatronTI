"""
catch_ws_event.py — поймать ЖИВОЕ user-data WS событие через UserDataStream (EXEC-WS, 12.06).

Запускает кастомный WS на ~120с. Бот торгует (atr_change/ote) → придёт order/account событие.
Печатает СЫРОЙ формат (для парсера Этапа 2). Изолирован — свой WS, не трогает бот/scan_loop.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(message)s")

from core.exchange.user_data_ws import UserDataStream

DURATION = int(os.environ.get("CATCH_SEC", 120))


async def main():
    key = os.getenv("BINGX_VST_API_KEY") or os.getenv("BINGX_API_KEY") or ""
    if not key:
        print("[!] нет BINGX_VST_API_KEY")
        return
    caught = []

    async def on_ev(etype, msg):
        caught.append((etype, msg))
        print(f"\n[CAUGHT #{len(caught)}] type='{etype}'\n  {json.dumps(msg, ensure_ascii=False)[:500]}")

    uds = UserDataStream(key, is_vst=True, on_event=on_ev)
    task = asyncio.create_task(uds.run())
    print(f"Ловлю события {DURATION}с (бот торгует — ждём order/account)...")
    await asyncio.sleep(DURATION)
    await uds.stop()
    try:
        await asyncio.wait_for(task, timeout=10)   # даём run() завершиться штатно (без cancel)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass
    print(f"\n==== ИТОГ ==== поймано={len(caught)} stats={uds.stats}")


if __name__ == "__main__":
    asyncio.run(main())
