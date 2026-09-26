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

🔴 Мелкие ТФ (1m) в SQLite НЕ КЛАСТЬ: замерено 98.4 байта/бар против 26.4 в parquet+zstd
(×3.7). Вся вселенная 1m за 57 мес = 82 ГБ в sqlite против 22 ГБ в parquet.
Для них режим --out parquet: пишет в data/history/{tf}/{SYM}.parquet (конвенция проекта —
DatetimeIndex 'ts' UTC + ohlcv), резюмируемо по уже покрытым месяцам, хвост текущего
месяца добирается ДНЕВНЫМИ архивами (месячный публикуется только после конца месяца).
  python scripts/fetch_binance_vision.py --out parquet --tfs 1m --since 2024-01
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
BASE_DAILY = "https://data.binance.vision/data/futures/um/daily/klines"

# Дефолтные окна (с какого месяца тянуть) по ТФ — баланс глубина/объём
DEFAULT_SINCE = {"1m": "2024-01", "3m": "2024-01", "5m": "2025-01", "15m": "2024-01",
                 "1h": "2022-01", "4h": "2022-01", "1d": "2022-01"}
DEFAULT_TFS = ["5m", "15m", "1h", "4h"]
PARQUET_DIR = ROOT / "data" / "history"

_lock = None  # sqlite write-lock (ThreadPool)


def _months(since: str, until: str | None = None) -> list[str]:
    y, m = map(int, since.split("-"))
    now = datetime.now(timezone.utc)
    end = tuple(map(int, until.split("-"))) if until else (now.year, now.month)
    out = []
    while (y, m) <= end:
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


def _universe_from_cache() -> list[str]:
    """Вся вселенная кэша баров (шире, чем торговавшиеся): 514 симв. → 471 есть на Binance."""
    c = sqlite3.connect(CACHE_DB)
    rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM ohlcv_cache")]
    c.close()
    return sorted({s.replace(":USDT", "").replace("/USDT", "") + "USDT" for s in rows if s})


def _days(since_day: str) -> list[str]:
    """Дни YYYY-MM-DD от since по ВЧЕРА включительно (сегодняшний архив ещё не готов)."""
    from datetime import date, timedelta
    y, m, d = map(int, since_day.split("-"))
    cur, last = date(y, m, d), datetime.now(timezone.utc).date() - timedelta(days=1)
    out = []
    while cur <= last:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _download_day(sym: str, tf: str, day: str) -> list[tuple] | None:
    """
    Качает 1 ДНЕВНОЙ zip. Нужен для ТЕКУЩЕГО месяца: месячный архив публикуется
    только после его окончания, поэтому без daily кэш всегда отстаёт на 1-31 день.
    🔴 22-24.08: из-за этого кэш стоял на 31.07, и августовские сигналы молча
    выпадали из замеров — слепой тест «июль→август» стал невозможен.
    """
    url = f"{BASE_DAILY}/{sym}/{tf}/{sym}-{tf}-{day}.zip"
    return _fetch_zip(url)


def _download_month(sym: str, tf: str, month: str) -> list[tuple] | None:
    """Качает 1 месячный zip → список (open_time_ms, o,h,l,c,v) или None (404/ошибка)."""
    url = f"{BASE}/{sym}/{tf}/{sym}-{tf}-{month}.zip"
    return _fetch_zip(url)


def _fetch_zip(url: str) -> list[tuple] | None:
    """Общий загрузчик zip-CSV (месячный и дневной форматы идентичны)."""
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


def _rows_to_df(rows: list[tuple]):
    """(ms,o,h,l,c,v) → DataFrame в конвенции data/history: DatetimeIndex 'ts' UTC + ohlcv."""
    import pandas as pd
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("time").sort_values("time")
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.index.name = "ts"
    return df.drop(columns=["time"]).astype("float64")


def _covered_months(path: Path) -> tuple[set, object]:
    """Какие месяцы в файле уже ПОЛНЫЕ. Последний месяц полным не считаем — он мог
    качаться дневными архивами и обрываться на середине."""
    import pandas as pd
    if not path.exists():
        return set(), None
    try:
        have = pd.read_parquet(path)
    except Exception:
        return set(), None
    if not len(have):
        return set(), None
    per = have.index.tz_localize(None).to_period("M")   # to_period ругается на tz
    last = per.max()
    return {str(p) for p in per.unique() if p != last}, have


def _sync_parquet(sym: str, tf: str, months: list[str], path: Path, workers: int) -> int:
    """Догружает недостающие месяцы + дни ТЕКУЩЕГО месяца, дописывает в parquet."""
    import pandas as pd
    covered, have = _covered_months(path)
    need = [m for m in months if m not in covered]
    cur_month = datetime.now(timezone.utc).strftime("%Y-%m")
    need_m = [m for m in need if m < cur_month]
    parts = []
    if need_m:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for rows in ex.map(lambda m: _download_month(sym, tf, m), need_m):
                if rows:
                    parts.append(rows)
    if cur_month in need:       # текущий месяц — только дневными архивами
        days = _days(cur_month + "-01")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for rows in ex.map(lambda d: _download_day(sym, tf, d), days):
                if rows:
                    parts.append(rows)
    if not parts:
        return 0
    df = _rows_to_df([r for p in parts for r in p])
    if have is not None:
        df = pd.concat([have, df])
        df = df[~df.index.duplicated(keep="last")].sort_index()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, compression="zstd")
    return len(df)


def _run_parquet(syms: list[str], tfs: list[str], since: str | None,
                 outdir: Path, workers: int, until: str | None = None) -> int:
    """Паркет-режим: файл на символ+ТФ. Память не копит — символы идут по одному."""
    for tf in tfs:
        months = _months(since or DEFAULT_SINCE.get(tf, "2023-01"), until)
        d = outdir / tf
        print(f"[vision] {tf}: {len(syms)} пар × {len(months)} мес → {d}", flush=True)
        got = skipped = 0
        for i, sym in enumerate(syms, 1):
            path = d / f"{sym}.parquet"
            try:
                n = _sync_parquet(sym, tf, months, path, workers)
            except Exception as e:
                print(f"[vision] {sym} {tf}: ОШИБКА {e}", flush=True)
                continue
            if n:
                got += 1
            else:
                skipped += 1
            if i % 25 == 0:
                mb = sum(f.stat().st_size for f in d.glob("*.parquet")) / 1048576
                print(f"[vision] {tf} {i}/{len(syms)} | файлов {got} | "
                      f"пусто {skipped} | {mb:.0f} МБ", flush=True)
        mb = sum(f.stat().st_size for f in d.glob("*.parquet")) / 1048576 if d.exists() else 0
        print(f"[vision] {tf} ГОТОВО: файлов {got}, пусто {skipped}, {mb:.0f} МБ", flush=True)
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", help="базы (BTC ETH); по умолч. — вселенная из БД")
    ap.add_argument("--tfs", nargs="*", default=DEFAULT_TFS)
    ap.add_argument("--since", help="YYYY-MM (один для всех ТФ); иначе per-TF дефолт")
    ap.add_argument("--until", help="YYYY-MM включительно; иначе по текущий месяц "
                                    "(нужно для старых окон, напр. бычий 2020-2021)")
    ap.add_argument("--since-day", help="YYYY-MM-DD: докачать ДНЕВНЫМИ архивами "
                                        "(текущий месяц; месячного архива ещё нет)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", choices=["sqlite", "parquet"], default="sqlite",
                    help="parquet — для мелких ТФ (1m): ×3.7 компактнее sqlite")
    ap.add_argument("--outdir", default=str(PARQUET_DIR), help="корень для --out parquet")
    ap.add_argument("--universe", choices=["trades", "cache"], default="trades",
                    help="trades — торговавшиеся за 30д (по умолч.); cache — всё из ohlcv_cache")
    args = ap.parse_args()

    if args.symbols:
        syms = [s.upper().replace("/USDT", "").replace("USDT", "") + "USDT" for s in args.symbols]
    elif args.universe == "cache":
        syms = _universe_from_cache()
    else:
        syms = _universe_from_db()
    print(f"[vision] пар: {len(syms)} | ТФ: {args.tfs}", flush=True)

    if args.out == "parquet":
        return _run_parquet(syms, args.tfs, args.since, Path(args.outdir), args.workers,
                            args.until)

    # задания (sym, tf, период). daily — для текущего месяца, monthly — для истории
    jobs = []
    if args.since_day:
        for tf in args.tfs:
            for sym in syms:
                for day in _days(args.since_day):
                    jobs.append((sym, tf, day, "day"))
        print(f"[vision] ДНЕВНОЙ режим · заданий (sym×tf×day): {len(jobs)}", flush=True)
    else:
        for tf in args.tfs:
            since = args.since or DEFAULT_SINCE.get(tf, "2023-01")
            for sym in syms:
                for mon in _months(since, args.until):
                    jobs.append((sym, tf, mon, "month"))
        print(f"[vision] заданий (sym×tf×month): {len(jobs)}", flush=True)

    conn = sqlite3.connect(CACHE_DB, timeout=60)
    _ensure_schema(conn)

    done = bars = miss = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_download_day if kind == "day" else _download_month, s, t, m): (s, t, m)
                for (s, t, m, kind) in jobs}
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
