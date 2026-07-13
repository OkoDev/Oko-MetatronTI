"""Проверка глубины исторических данных у BingX через ccxt."""
import sys, asyncio
sys.stdout.reconfigure(encoding='utf-8')

async def main():
    import ccxt.async_support as ccxt
    from dotenv import load_dotenv
    import os, datetime

    load_dotenv()
    exchange = ccxt.bingx({
        'apiKey': os.getenv('BINGX_API_KEY', ''),
        'secret': os.getenv('BINGX_SECRET', ''),
        'enableRateLimit': True,
    })

    # Тест: BTC на разных TF
    symbol = 'BTC/USDT:USDT'
    for tf in ['15m', '1h', '4h', '1d']:
        try:
            # Запрашиваем с самого начала (limit=1000)
            since_ts = exchange.parse8601('2023-01-01T00:00:00Z')
            ohlcv = await exchange.fetch_ohlcv(symbol, tf, since=since_ts, limit=1000)
            if ohlcv:
                first_dt = datetime.datetime.utcfromtimestamp(ohlcv[0][0] / 1000)
                last_dt  = datetime.datetime.utcfromtimestamp(ohlcv[-1][0] / 1000)
                print(f"  {tf:>4}: {len(ohlcv):>5} свечей | first={first_dt:%Y-%m-%d} last={last_dt:%Y-%m-%d}")
            else:
                print(f"  {tf}: нет данных")
        except Exception as e:
            print(f"  {tf}: ошибка — {e}")

    # Сколько нужно запросов для 2 лет на 15m?
    candles_2yr_15m = 2 * 365 * 24 * 4  # 70080
    print(f"\nДля 2 лет на 15m нужно: {candles_2yr_15m} свечей")
    print(f"Запросов по 1000: {candles_2yr_15m // 1000 + 1}")
    print(f"На 500 пар: {500 * (candles_2yr_15m // 1000 + 1)} запросов")

    # Для 1d — сколько свечей за 2 года?
    candles_2yr_1d = 2 * 365
    print(f"\nДля 2 лет на 1d: {candles_2yr_1d} свечей — 1 запрос на пару")

    await exchange.close()

asyncio.run(main())
