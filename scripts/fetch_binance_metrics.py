# -*- coding: utf-8 -*-
"""Загрузчик истории ПОЗИЦИОНИРОВАНИЯ Binance USDT-M с data.binance.vision → паркет на монету (HYP-7, BACKLOG N14).

Слой, которого нет в OHLCV и который не надо копить самим (27.09.2026: архив есть с 2021-12 до вчера):
  sum_open_interest / sum_open_interest_value — открытый интерес (контракты / $), шаг 5 мин;
  count_toptrader_long_short_ratio            — топ-трейдеры: счета лонг/шорт;
  sum_toptrader_long_short_ratio              — топ-трейдеры: позиции лонг/шорт;
  count_long_short_ratio                      — все счета лонг/шорт;
  sum_taker_long_short_vol_ratio              — объём агрессивных покупок / продаж (прокси CVD).

URL: https://data.binance.vision/data/futures/um/daily/metrics/{SYM}/{SYM}-metrics-{YYYY-MM-DD}.zip
Месячных архивов нет (404) — только дневные. 404 = дня нет (до листинга / после делистинга) → пропуск.

Выход: C:/oko_data/history/metrics/{BASE}USDT.parquet (как 1m-паркеты рядом). Докачка: продолжает с дня
после последнего сохранённого. Монеты — из 1m-истории, порядок — по 24ч-обороту Binance (ликвидные первыми),
старт монеты — с первого фандинга в ohlcv_cache.funding_rates (прокси листинга), но не раньше --since.

  python scripts/fetch_binance_metrics.py                    # все монеты 1m-истории
  python scripts/fetch_binance_metrics.py --top 50           # 50 самых ликвидных
  python scripts/fetch_binance_metrics.py --symbols BTC ETH --since 2024-01-01
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HIST_1M = Path("C:/oko_data/history/1m")
OUT = Path("C:/oko_data/history/metrics")
BASE = "https://data.binance.vision/data/futures/um/daily/metrics"
COLS = ["sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio",
        "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass


def _day(sym: str, d: date) -> pd.DataFrame | None:
    url = f"{BASE}/{sym}/{sym}-metrics-{d:%Y-%m-%d}.zip"
    for attempt in range(3):
        try:
            data = urllib.request.urlopen(url, timeout=30).read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"{sym} {d}: не скачалось за 3 попытки")
    z = zipfile.ZipFile(io.BytesIO(data))
    df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))
    df["time"] = pd.to_datetime(df.create_time).astype("int64") // 1_000_000       # UTC, мс
    for c in COLS:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    return df[["time"] + COLS]


def _universe(top: int | None, only: list[str] | None) -> list[str]:
    bases = sorted(p.stem[:-4] for p in HIST_1M.glob("*USDT.parquet")) if not only else only
    try:
        t = json.load(urllib.request.urlopen("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=20))
        vol = {x["symbol"][:-4]: float(x["quoteVolume"]) for x in t if x["symbol"].endswith("USDT")}
    except Exception as e:  # noqa: BLE001
        print(f"оборот недоступен ({e}) — порядок алфавитный")
        vol = {}
    bases.sort(key=lambda b: -vol.get(b, -1))
    return bases[:top] if top else bases


def _first_funding() -> dict[str, date]:
    c = sqlite3.connect(ROOT / "ohlcv_cache.db", timeout=60)
    rows = c.execute("SELECT symbol, MIN(time) FROM funding_rates GROUP BY symbol").fetchall()
    c.close()
    return {s.split("/")[0]: datetime.fromtimestamp(t / 1000, timezone.utc).date() for s, t in rows}


def fetch_symbol(base: str, start: date, end: date, workers: int) -> tuple[int, int, int]:
    """Докачать монету до end включительно. Возврат: (новых дней, 404, строк в файле)."""
    out = OUT / f"{base}USDT.parquet"
    old = pd.read_parquet(out) if out.exists() else None
    if old is not None and len(old):
        start = max(start, datetime.fromtimestamp(old.time.max() / 1000, timezone.utc).date() + timedelta(days=1))
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if not days:
        return 0, 0, 0 if old is None else len(old)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        got = list(pool.map(lambda d: _day(f"{base}USDT", d), days))
    new = [g for g in got if g is not None and len(g)]
    miss = sum(g is None for g in got)
    if not new:
        return 0, miss, 0 if old is None else len(old)
    df = pd.concat(([old] if old is not None else []) + new, ignore_index=True)
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    tmp = out.with_suffix(".tmp")
    df.to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(out)                                                   # атомарно: обрыв не портит файл
    return len(new), miss, len(df)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--top", type=int)
    ap.add_argument("--since", default="2022-01-01")
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    since = date.fromisoformat(a.since)
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    first = _first_funding()
    bases = _universe(a.top, [s.upper() for s in a.symbols] if a.symbols else None)
    print(f"монет {len(bases)} · {since} → {end} · выход {OUT}")
    t0 = time.time()
    for i, b in enumerate(bases, 1):
        start = max(since, first.get(b, since))
        try:
            n, miss, rows = fetch_symbol(b, start, end, a.workers)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(bases)}] {b}: ОШИБКА {e}")
            continue
        print(f"[{i}/{len(bases)}] {b}: +{n} дн · 404 {miss} · строк {rows:,} · {time.time() - t0:.0f} с")
    print("ГОТОВО")


if __name__ == "__main__":
    main()
