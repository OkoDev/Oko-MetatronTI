# -*- coding: utf-8 -*-
"""Bulk-загрузчик funding rates с data.binance.vision → ohlcv_cache.db (таблица funding_rates).

FUNDING-DATA (03.07.2026): ортогональный фактор для бэктестов — funding-перекос = систематическое
давление (высокий +rate = лонги платят = перегрев). По образцу fetch_binance_vision.py.

URL: https://data.binance.vision/data/futures/um/monthly/fundingRate/{SYM}/{SYM}-fundingRate-{YYYY-MM}.zip
CSV: calc_time(ms), funding_interval_hours, last_funding_rate. 404 → тихо пропускаем.

Запуск:
  python scripts/fetch_binance_funding.py                     # символы из ohlcv_cache, с 2022-01
  python scripts/fetch_binance_funding.py --symbols BTC ETH --since 2024-01
"""
import argparse
import io
import sqlite3
import sys
import urllib.request
import urllib.error
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parent.parent
CACHE_DB = ROOT / "ohlcv_cache.db"
BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"

_lock = Lock()


def _months(since: str) -> list[str]:
    y, m = map(int, since.split("-"))
    now = datetime.now(timezone.utc)
    out = []
    while (y, m) <= (now.year, now.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1; y += 1
    return out


def _ensure_schema(conn: sqlite3.Connection):
    conn.execute("""CREATE TABLE IF NOT EXISTS funding_rates (
        symbol TEXT NOT NULL, time INTEGER NOT NULL,
        interval_hours INTEGER, rate REAL NOT NULL)""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_funding_uniq
        ON funding_rates(symbol, time)""")
    conn.commit()


def _symbols_from_cache(conn) -> list[str]:
    rows = conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='4h'").fetchall()
    return sorted({r[0].split("/")[0] for r in rows})


def _fetch_month(sym_base: str, month: str) -> list[tuple] | None:
    sym = f"{sym_base}USDT"
    url = f"{BASE}/{sym}/{sym}-fundingRate-{month}.zip"
    try:
        data = urllib.request.urlopen(url, timeout=60).read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        lines = z.read(z.namelist()[0]).decode().splitlines()
    except Exception:
        return None
    out = []
    for ln in lines:
        parts = ln.split(",")
        if len(parts) < 3 or parts[0] == "calc_time":
            continue
        try:
            out.append((f"{sym_base}/USDT", int(parts[0]), int(parts[1]), float(parts[2])))
        except ValueError:
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--since", default="2022-01")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    conn = sqlite3.connect(CACHE_DB, check_same_thread=False)
    _ensure_schema(conn)
    symbols = args.symbols or _symbols_from_cache(conn)
    months = _months(args.since)
    jobs = [(s, m) for s in symbols for m in months]
    print(f"символов: {len(symbols)}, месяцев: {len(months)}, задач: {len(jobs)}")

    done = miss = rows_total = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(_fetch_month, s, m): (s, m) for s, m in jobs}
        for fut in as_completed(futs):
            s, m = futs[fut]
            try:
                rows = fut.result()
            except Exception as e:
                print(f"  ! {s} {m}: {e}"); continue
            if not rows:
                miss += 1; continue
            with _lock:
                conn.executemany(
                    "INSERT OR IGNORE INTO funding_rates(symbol,time,interval_hours,rate) VALUES (?,?,?,?)",
                    rows)
                conn.commit()
            done += 1; rows_total += len(rows)
            if done % 50 == 0:
                print(f"  … {done} месяцев загружено, {rows_total} строк")
    n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT symbol) FROM funding_rates").fetchone()
    print(f"ГОТОВО: загружено {done} сим-месяцев (404: {miss}), в таблице {n[0]} строк, {n[1]} символов")
    conn.close()


if __name__ == "__main__":
    main()
