# -*- coding: utf-8 -*-
"""Bulk-загрузчик истории с data.binance.vision (USDT-M futures klines) → ohlcv_cache.db.

НЕ постранично (ccxt), а готовые МЕСЯЧНЫЕ zip-CSV с CDN Binance → в разы быстрее для глубокой
истории. Основание для OTE-RE-MINE (Track 2). Резюмируемый (INSERT OR IGNORE + uniq-index).

URL: https://data.binance.vision/data/futures/um/monthly/klines/{SYM}/{tf}/{SYM}-{tf}-{YYYY-MM}.zip
  SYM = BTCUSDT (без слеша). CSV: open_time(ms),open,high,low,close,volume,close_time,...
Несуществующие пары/месяцы → 404 → тихо пропускаются (BingX-экзотика отсеется сама).

Запуск:
  python scripts/fetch_binance_vision.py                 # вселенная из БД, дефолт-окна
  python scripts/fetch_binance_vision.py --symbols BTC ETH --tfs 5m 1h --since 2025-01
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

ROOT = Path(__file__).resolve().parent.parent
CACHE_DB = ROOT / "ohlcv_cache.db"
SUBS_DB = ROOT / "subscriptions.db"
BASE = "https://data.binance.vision/data/futures/um/monthly/klines"

# Дефолтные окна (с какого месяца тянуть) по ТФ — баланс глубина/объём
DEFAULT_SINCE = {"5m": "2025-01", "15m": "2024-01", "1h": "2022-01", "4h": "2022-01"}
DEFAULT_TFS = ["5m", "15m", "1h", "4h"]

_lock = None  # sqlite write-lock (ThreadPool)


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
    conn.execute("""CREATE TABLE IF NOT EXISTS ohlcv_cache
        (symbol TEXT, timeframe TEXT, time INTEGER, open REAL, high REAL,
         low REAL, close REAL, volume REAL)""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_ohlcv_uniq
        ON ohlcv_cache(symbol, timeframe, time)""")
    conn.commit()


def _universe_from_db() -> list[str]:
    """Активные пары за 30д → нормализ. 'X/USDT' → vision-символ 'XUSDT'."""
    c = sqlite3.connect(SUBS_DB)
    rows = [r[0] for r in c.execute(
        "SELECT DISTINCT symbol FROM simulated_trades WHERE created_at>='2026-05-22'")]
    c.close()
    out = []
    for s in rows:
        base = s.replace(":USDT", "").replace("/USDT", "")
        if base:
            out.append(base + "USDT")
    return sorted(set(out))


def _download_month(sym: str, tf: str, month: str) -> list[tuple] | None:
    """Качает 1 месячный zip → список (open_time_ms, o,h,l,c,v) или None (404/ошибка)."""
    url = f"{BASE}/{sym}/{tf}/{sym}-{tf}-{month}.zip"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "oko-remine/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        return None
    except Exception:
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        raw = zf.read(zf.namelist()[0]).decode("utf-8", "replace")
    except Exception:
        return None
    rows = []
    for line in raw.splitlines():
        parts = line.split(",")
        if len(parts) < 6:
            continue
        if not parts[0].lstrip("-").isdigit():   # header row
            continue
        try:
            t = int(parts[0])
            rows.append((t, float(parts[1]), float(parts[2]), float(parts[3]),
                         float(parts[4]), float(parts[5])))
        except Exception:
            continue
    return rows


def _store(conn, cache_symbol: str, tf: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    conn.executemany(
        "INSERT OR IGNORE INTO ohlcv_cache(symbol,timeframe,time,open,high,low,close,volume)"
        " VALUES (?,?,?,?,?,?,?,?)",
        [(cache_symbol, tf, t, o, h, l, c, v) for (t, o, h, l, c, v) in rows])
    return len(rows)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", help="базы (BTC ETH); по умолч. — вселенная из БД")
    ap.add_argument("--tfs", nargs="*", default=DEFAULT_TFS)
    ap.add_argument("--since", help="YYYY-MM (один для всех ТФ); иначе per-TF дефолт")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    if args.symbols:
        syms = [s.upper().replace("/USDT", "").replace("USDT", "") + "USDT" for s in args.symbols]
    else:
        syms = _universe_from_db()
    print(f"[vision] пар: {len(syms)} | ТФ: {args.tfs}", flush=True)

    # задания (sym, tf, month)
    jobs = []
    for tf in args.tfs:
        since = args.since or DEFAULT_SINCE.get(tf, "2023-01")
        for sym in syms:
            for mon in _months(since):
                jobs.append((sym, tf, mon))
    print(f"[vision] заданий (sym×tf×month): {len(jobs)}", flush=True)

    conn = sqlite3.connect(CACHE_DB, timeout=60)
    _ensure_schema(conn)

    done = bars = miss = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_download_month, s, t, m): (s, t, m) for (s, t, m) in jobs}
        for fut in as_completed(futs):
            s, t, m = futs[fut]
            rows = fut.result()
            done += 1
            if rows:
                cache_sym = s[:-4] + "/USDT"   # BTCUSDT -> BTC/USDT (формат кэша)
                bars += _store(conn, cache_sym, t, rows)
                if done % 200 == 0:
                    conn.commit()
            else:
                miss += 1
            if done % 500 == 0:
                print(f"[vision] {done}/{len(jobs)} | баров+{bars} | 404/пусто {miss}", flush=True)
    conn.commit()
    conn.close()
    print(f"[vision] ГОТОВО: {done} заданий, +{bars} баров, {miss} пропущено(404)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
