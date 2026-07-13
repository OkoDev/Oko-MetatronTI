"""D-066 Phase B Diagnostic: standalone test ccxt.pro BingX watch_ohlcv.

Цель: понять почему watch_ohlcv даёт 1 update и замолкает.
Изолированно от бота — никаких external dependencies кроме ccxt.pro.

Usage:
    python tools/diag_bingx_ws_ohlcv.py [duration_sec=120]

Output: каждый callback с timestamp + bar count + bar diff vs prev.
"""
import asyncio
import sys
import time
from datetime import datetime


async def watch_one_symbol(exchange, symbol: str, duration: float) -> None:
    """Подписывается на watch_ohlcv для одного символа N секунд."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] START watch_ohlcv {symbol} 15m", flush=True)

    started = time.monotonic()
    call_count = 0
    update_count = 0
    last_bar_ts = None
    last_close = None

    while (time.monotonic() - started) < duration:
        try:
            call_count += 1
            t_call = time.monotonic()
            candles = await asyncio.wait_for(
                exchange.watch_ohlcv(symbol, '15m'),
                timeout=30.0,
            )
            elapsed = time.monotonic() - t_call
            if not candles:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] #{call_count} EMPTY candles (await {elapsed:.2f}s)", flush=True)
                continue

            last = candles[-1]
            bar_ts = int(last[0])
            close = float(last[4])
            count = len(candles)

            # Что изменилось?
            if last_bar_ts is None:
                change = "INIT"
            elif bar_ts == last_bar_ts:
                if close == last_close:
                    change = "NO_CHANGE(same_ts_same_close)"
                else:
                    change = f"REPLACE(close {last_close} -> {close})"
            elif bar_ts > last_bar_ts:
                change = f"NEW_BAR(ts {last_bar_ts} -> {bar_ts})"
            else:
                change = f"STALE(ts {bar_ts} < {last_bar_ts})"

            update_count += 1
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] #{call_count} "
                f"await {elapsed:.2f}s, candles={count}, "
                f"last_bar_ts={bar_ts}, close={close}, {change}",
                flush=True,
            )
            last_bar_ts = bar_ts
            last_close = close

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t_call
            print(f"[{datetime.now().strftime('%H:%M:%S')}] #{call_count} TIMEOUT after {elapsed:.1f}s", flush=True)
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] #{call_count} ERROR {type(e).__name__}: {e}", flush=True)

    print(f"\n=== SUMMARY {symbol} ===", flush=True)
    print(f"  Duration:    {duration}s", flush=True)
    print(f"  Total calls: {call_count}", flush=True)
    print(f"  Updates:     {update_count}", flush=True)


async def ticker_loop(exchange, symbol: str, duration: float, counter: dict) -> None:
    """Параллельный ticker watcher для симуляции ситуации в боте."""
    started = time.monotonic()
    while (time.monotonic() - started) < duration:
        try:
            await exchange.watch_ticker(symbol)
            counter['ticks'] = counter.get('ticks', 0) + 1
        except Exception as e:
            counter['ticker_err'] = counter.get('ticker_err', 0) + 1


async def main():
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    mode = sys.argv[2] if len(sys.argv) > 2 else 'single'  # single | with_ticker
    symbol = sys.argv[3] if len(sys.argv) > 3 else 'ETH/USDT:USDT'

    print(f"=== D-066 Phase B Diagnostic ===", flush=True)
    print(f"Duration: {duration}s", flush=True)
    print(f"Mode: {mode}", flush=True)
    print(f"Symbol: {symbol}", flush=True)
    print(f"TF: 15m", flush=True)
    print(f"", flush=True)

    import ccxt.pro as ccxtpro
    print(f"ccxt.pro version: {ccxtpro.__version__ if hasattr(ccxtpro, '__version__') else 'unknown'}", flush=True)

    # Отдельный instance для OHLCV (как сейчас в Phase C)
    ohlcv_ex = ccxtpro.bingx({
        "options": {"defaultType": "swap"},
        "enableRateLimit": False,
    })

    tasks = [watch_one_symbol(ohlcv_ex, symbol, duration)]
    ticker_ex = None
    ticker_counter = {}

    if mode == 'with_ticker':
        # Параллельный ticker на ДРУГОМ instance — как в боте
        ticker_ex = ccxtpro.bingx({
            "options": {"defaultType": "swap"},
            "enableRateLimit": False,
        })
        print(f"[MODE=with_ticker] параллельно подписываемся на ticker {symbol} на ОТДЕЛЬНОМ instance", flush=True)
        tasks.append(ticker_loop(ticker_ex, symbol, duration, ticker_counter))

    try:
        await asyncio.gather(*tasks)
    finally:
        for ex in (ohlcv_ex, ticker_ex):
            if ex is None:
                continue
            try:
                await ex.close()
            except Exception as e:
                print(f"[CLOSE] error: {e}", flush=True)
        if mode == 'with_ticker':
            print(f"[TICKER COUNTS] {ticker_counter}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
