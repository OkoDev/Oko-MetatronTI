"""
Параллельная загрузка 5m и 15m данных для LTF nested entry mining.

Источник: Binance Vision (data.binance.vision) — те же что и 1h.
Сохранение: data/history/5m/<SYMBOL>.parquet, data/history/15m/<SYMBOL>.parquet
"""
import sys, io, asyncio, zipfile, time
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from datetime import datetime, timedelta, timezone
import aiohttp
import pandas as pd

BASE_DIR    = Path("E:/MTF BOT/CURSOR/crypto_volume_bot/data/history")
BASE_URL    = "https://data.binance.vision/data/futures/um/daily/klines"
START_DATE  = datetime(2024, 1, 1, tzinfo=timezone.utc)
END_DATE    = datetime(2026, 5, 17, tzinfo=timezone.utc)
CONCURRENT_SYMBOLS = 5
CONCURRENT_DAYS    = 8

TOP_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LTCUSDT", "LINKUSDT",
    "DOTUSDT", "UNIUSDT", "FILUSDT", "ETCUSDT", "TRXUSDT",
    "SHIBUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
    "SUIUSDT", "PEPEUSDT", "1000BONKUSDT", "ENAUSDT", "INJUSDT",
    "WIFUSDT", "FLOKIUSDT", "MKRUSDT", "AAVEUSDT", "RENDERUSDT",
    "FETUSDT", "GRTUSDT", "KASUSDT", "SEIUSDT", "TIAUSDT",
    "STXUSDT", "JUPUSDT", "RUNEUSDT", "TNSRUSDT", "WLDUSDT",
    "CRVUSDT", "APEUSDT", "GALAUSDT", "ZROUSDT",
    "DYDXUSDT", "ENSUSDT", "ATOMUSDT", "NEARUSDT", "TONUSDT",
]


async def fetch_day(session, symbol, interval, date, sem):
    date_str = date.strftime("%Y-%m-%d")
    url = f"{BASE_URL}/{symbol}/{interval}/{symbol}-{interval}-{date_str}.zip"
    async with sem:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    return None
                data = await r.read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                with zf.open(zf.namelist()[0]) as f:
                    raw = f.read()
            df = pd.read_csv(io.BytesIO(raw))
            if "open_time" in df.columns:
                df = df.rename(columns={"open_time":"ts","Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
                df.columns = [c.lower() for c in df.columns]
            else:
                df = pd.read_csv(io.BytesIO(raw), header=None, names=[
                    "ts","open","high","low","close","volume","close_ts","quote_vol",
                    "trades","taker_buy_vol","taker_buy_quote","ignore"
                ])
            return df[["ts","open","high","low","close","volume"]]
        except Exception:
            return None


async def fetch_symbol(session, symbol, interval, sem_global, out_dir):
    out_path = out_dir / f"{symbol}.parquet"
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
        tasks = [fetch_day(session, symbol, interval, d, sem_days) for d in days]
        results = await asyncio.gather(*tasks)
        dfs = [df for df in results if df is not None]
        if not dfs:
            return symbol, "fail", 0

        all_df = pd.concat(dfs, ignore_index=True)
        try:
            all_df["ts"] = pd.to_numeric(all_df["ts"], errors="coerce")
            all_df["ts"] = pd.to_datetime(all_df["ts"], unit="ms", utc=True)
        except Exception:
            all_df["ts"] = pd.to_datetime(all_df["ts"], utc=True, errors="coerce")
        all_df = all_df.dropna(subset=["ts"]).drop_duplicates("ts").sort_values("ts")
        all_df = all_df.set_index("ts")

        out_dir.mkdir(parents=True, exist_ok=True)
        all_df.to_parquet(out_path, compression="snappy")
        elapsed = time.time() - t0
        size_mb = out_path.stat().st_size / 1024 / 1024
        return symbol, f"OK {elapsed:.0f}с", size_mb


async def fetch_interval(interval: str, symbols: list):
    out_dir = BASE_DIR / interval
    print(f"\n{'='*60}\nЗагрузка {interval} × {len(symbols)} пар\n{'='*60}")
    sem_global = asyncio.Semaphore(CONCURRENT_SYMBOLS)
    connector = aiohttp.TCPConnector(limit=50, ttl_dns_cache=300)

    t0 = time.time()
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_symbol(session, sym, interval, sem_global, out_dir) for sym in symbols]
        done = []
        for fut in asyncio.as_completed(tasks):
            sym, status, mb = await fut
            done.append((sym, status, mb))
            print(f"  [{len(done):>2}/{len(symbols)}] {sym:<15} {status:<12} {mb:.1f} MB")

    elapsed = time.time() - t0
    ok = sum(1 for _,s,_ in done if s.startswith("OK") or s == "skip")
    fail = sum(1 for _,s,_ in done if s == "fail")
    total = sum(mb for _,_,mb in done)
    print(f"  Готово: {ok} OK, {fail} fail | {elapsed/60:.1f} мин | {total:.0f} MB")


async def main():
    # Сначала 15m (легче), потом 5m
    await fetch_interval("15m", TOP_SYMBOLS)
    await fetch_interval("5m",  TOP_SYMBOLS)


if __name__ == "__main__":
    asyncio.run(main())
