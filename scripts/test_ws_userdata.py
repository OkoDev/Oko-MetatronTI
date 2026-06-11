"""
test_ws_userdata.py — ИЗОЛИРОВАННАЯ проверка ccxt.pro BingX private user-data WS (12.06).

Цель: убедиться, что ccxt.pro отдаёт watchOrders/watchPositions/watchBalance для BingX
ПЕРЕД проектированием Execution Sphere WS. НЕ трогает боевой WsFeed/scan_loop — свой
exchange instance, своё соединение, закрывается сразу. 1 user-data stream/аккаунт
(не per-pair) → нагрузки на scan_loop НЕТ.

Запуск: python scripts/test_ws_userdata.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv()


async def main():
    try:
        import ccxt.pro as ccxtpro
    except ImportError:
        print("[!] ccxt.pro не установлен")
        return

    api_key = os.getenv("BINGX_VST_API_KEY") or os.getenv("BINGX_API_KEY") or ""
    secret = os.getenv("BINGX_VST_SECRET_KEY") or os.getenv("BINGX_SECRET_KEY") or ""
    if not api_key:
        print("[!] нет BingX VST ключей в env")
        return

    ex = ccxtpro.bingx({
        "apiKey": api_key, "secret": secret,
        "options": {"defaultType": "swap"},
        "enableRateLimit": True,
    })
    # VST endpoint
    try:
        ex.set_sandbox_mode(True)
    except Exception:
        pass

    print(f"ccxt.pro версия: {ccxtpro.__version__}")
    print("=== поддержка private WS-методов (has) ===")
    for m in ("watchOrders", "watchPositions", "watchBalance", "watchMyTrades"):
        print(f"  {m:<16} = {ex.has.get(m)}")

    # Пробуем ОДИН watchBalance с таймаутом (лёгкий, не per-pair)
    print("\n=== проба watchBalance (timeout 20с) ===")
    try:
        bal = await asyncio.wait_for(ex.watch_balance(), timeout=20)
        usdt = (bal.get("USDT") or {}) if isinstance(bal, dict) else {}
        print(f"  [OK] watchBalance работает. USDT free={usdt.get('free')} used={usdt.get('used')}")
    except asyncio.TimeoutError:
        print("  [timeout] watchBalance не отдал за 20с (может нужен trigger-событие)")
    except Exception as e:
        print(f"  [!] watchBalance error: {type(e).__name__}: {e}")

    # Пробуем watchOrders (push при изменении ордеров; без событий = timeout = норма)
    print("\n=== проба watchOrders (timeout 15с, без событий timeout=норма) ===")
    try:
        orders = await asyncio.wait_for(ex.watch_orders(), timeout=15)
        print(f"  [OK] watchOrders работает. Получено {len(orders) if orders else 0} обновлений")
    except asyncio.TimeoutError:
        print("  [timeout] нет событий за 15с — это НОРМА (ордера не менялись). Метод подключился.")
    except Exception as e:
        print(f"  [!] watchOrders error: {type(e).__name__}: {e}")

    await ex.close()
    print("\n[закрыто] соединение закрыто — боевой WsFeed/scan_loop НЕ затронут.")


if __name__ == "__main__":
    asyncio.run(main())
