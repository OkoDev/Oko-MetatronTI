"""
Параллельная загрузка TOP50 1h данных с Binance Vision.
Скачивает по 10 пар одновременно — должно занять 5-10 минут вместо 10 часов.
"""
import sys, io, asyncio, zipfile, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
from datetime import datetime, timedelta, timezone
import aiohttp
import pandas as pd

HISTORY_DIR = Path("E:/MTF BOT/CURSOR/crypto_volume_bot/data/history/1h")
BASE_URL    = "https://data.binance.vision/data/futures/um/daily/klines"
INTERVAL    = "1h"
START_DATE  = datetime(2024, 1, 1, tzinfo=timezone.utc)
END_DATE    = datetime(2026, 5, 17, tzinfo=timezone.utc)
CONCURRENT_SYMBOLS = 5     # сколько пар одновременно
CONCURRENT_DAYS    = 8     # сколько дней внутри пары одновременно

TOP50 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LTCUSDT", "LINKUSDT",
    "DOTUSDT", "UNIUSDT", "FILUSDT", "ETCUSDT", "TRXUSDT",
    "SHIBUSDT", "MATICUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
    "SUIUSDT", "PEPEUSDT", "1000BONKUSDT", "ENAUSDT", "INJUSDT",
    "WIFUSDT", "FLOKIUSDT", "MKRUSDT", "AAVEUSDT", "RENDERUSDT",
    "FETUSDT", "GRTUSDT", "KASUSDT", "SEIUSDT", "TIAUSDT",
    "STXUSDT", "JUPUSDT", "RUNEUSDT", "TNSRUSDT", "WLDUSDT",
    "MNTUSDT", "CRVUSDT", "APEUSDT", "GALAUSDT", "ZROUSDT",
    "DYDXUSDT", "ENSUSDT", "ATOMUSDT", "NEARUSDT", "TONUSDT",
]

COLUMNS = ["ts","open","high","low","close","volume","close_ts","quote_vol",
           "trades","taker_buy_vol","taker_buy_quote","ignore"]


async def fetch_day(session, symbol, date, sem):
    date_str = date.strftime("%Y-%m-%d")
    url = f"{BASE_URL}/{symbol}/{INTERVAL}/{symbol}-{INTERVAL}-{date_str}.zip"
    async with sem:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 404:
                    return None
                if r.status != 200:
                    return None
                data = await r.read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                with zf.open(zf.namelist()[0]) as f:
                    # Binance Vision новый формат — с заголовком
                    first = f.read(50)
                    f2 = io.BytesIO(first + f.read())
                    f2.seek(0)
                    try:
                        df = pd.read_csv(f2)
                        if "open_time" in df.columns:
                            df = df.rename(columns={
                                "open_time": "ts", "Open": "open", "High": "high",
                                "Low": "low", "Close": "close", "Volume": "volume"
                            })
                            df.columns = [c.lower() for c in df.columns]
                        if "ts" not in df.columns:
                            f2.seek(0)
                            df = pd.read_csv(f2, header=None, names=COLUMNS)
                    except Exception:
                        f2.seek(0)
                        df = pd.read_csv(f2, header=None, names=COLUMNS)
            return df[["ts","open","high","low","close","volume"]]
        except Exception:
            return None


async def fetch_symbol(session, symbol, sem_global):
    out_path = HISTORY_DIR / f"{symbol}.parquet"
    if out_path.exists() and out_path.stat().st_size > 100_000:
        return symbol, "skip", out_path.stat().st_size / 1024 / 1024

    sem_days = asyncio.Semaphore(CONCURRENT_DAYS)
    days = []
    d = START_DATE
    while d <= END_DATE:
        days.append(d)
        d += timedelta(days=1)

    async with sem_global:
        t0 = time.time()
        tasks = [fetch_day(session, symbol, d, sem_days) for d in days]
        results = await asyncio.gather(*tasks)
        dfs = [df for df in results if df is not None]
        if not dfs:
            return symbol, "fail", 0

        all_df = pd.concat(dfs, ignore_index=True)
        # ts может быть в ms или в datetime строке
        try:
            all_df["ts"] = pd.to_numeric(all_df["ts"], errors="coerce")
            all_df["ts"] = pd.to_datetime(all_df["ts"], unit="ms", utc=True)
        except Exception:
            all_df["ts"] = pd.to_datetime(all_df["ts"], utc=True, errors="coerce")
        all_df = all_df.dropna(subset=["ts"]).drop_duplicates("ts").sort_values("ts")
        all_df = all_df.set_index("ts")

        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        all_df.to_parquet(out_path, compression="snappy")
        elapsed = time.time() - t0
        size_mb = out_path.stat().st_size / 1024 / 1024
        return symbol, f"OK {elapsed:.0f}с", size_mb


async def main():
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    sem_global = asyncio.Semaphore(CONCURRENT_SYMBOLS)
    connector = aiohttp.TCPConnector(limit=50, ttl_dns_cache=300)

    print(f"Параллельная загрузка {len(TOP50)} пар × 1h × 2024-01-01–2026-05-17")
    print(f"Concurrency: {CONCURRENT_SYMBOLS} пар × {CONCURRENT_DAYS} дней одновременно\n")

    t0 = time.time()
    done = []
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_symbol(session, sym, sem_global) for sym in TOP50]
        for fut in asyncio.as_completed(tasks):
            sym, status, mb = await fut
            done.append((sym, status, mb))
            print(f"  [{len(done):>2}/{len(TOP50)}] {sym:<15} {status:<12} {mb:.1f} MB")

    total_t = time.time() - t0
    ok   = sum(1 for _,s,_ in done if s.startswith("OK") or s == "skip")
    fail = sum(1 for _,s,_ in done if s == "fail")
    total_mb = sum(mb for _,_,mb in done)

    print(f"\n{'='*55}")
    print(f"Готово: {ok} OK, {fail} fail")
    print(f"Время: {total_t/60:.1f} мин")
    print(f"Итого: {total_mb:.0f} MB")


if __name__ == "__main__":
    asyncio.run(main())
