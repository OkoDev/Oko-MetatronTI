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

Выход: C:/oko_data/history/metrics/{BASE}USDT.parquet (как 1m-паркеты рядом). Докачка: качает ВСЕ дни,
которых нет в файле (хвост и дыры); день, не скачавшийся за 5 попыток, не роняет монету — повторный запуск
его доберёт. Монеты — из 1m-истории, порядок — по 24ч-обороту Binance (ликвидные первыми),
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


class DayFailed(Exception):
    """День не скачался после всех попыток — монета сохраняется без него, докачка доберёт."""


def _day(sym: str, d: date) -> pd.DataFrame | None:
    url = f"{BASE}/{sym}/{sym}-metrics-{d:%Y-%m-%d}.zip"
    err = ""
    for attempt in range(5):
        try:
            data = urllib.request.urlopen(url, timeout=30).read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        time.sleep(2 ** attempt)
    else:
        raise DayFailed(f"{d} ({err})")
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


def fetch_symbol(base: str, start: date, end: date, workers: int) -> tuple[int, int, int, list[str]]:
    """Докачать ВСЕ отсутствующие в файле дни [start, end] (и дыры внутри, и хвост).
    Возврат: (новых дней, 404, строк в файле, дни-сбои)."""
    out = OUT / f"{base}USDT.parquet"
    old = pd.read_parquet(out) if out.exists() else None
    have = set() if old is None else set(pd.to_datetime(old.time, unit="ms").dt.date.unique())
    days = [d for d in (start + timedelta(days=i) for i in range((end - start).days + 1)) if d not in have]
    if not days:
        return 0, 0, 0 if old is None else len(old), []

    def one(d):
        try:
            return _day(f"{base}USDT", d)
        except DayFailed as e:
            return e

    with ThreadPoolExecutor(max_workers=workers) as pool:
        got = list(pool.map(one, days))
    failed = [str(g) for g in got if isinstance(g, DayFailed)]
    new = [g for g in got if isinstance(g, pd.DataFrame) and len(g)]
    miss = sum(g is None for g in got)
    if not new:
        return 0, miss, 0 if old is None else len(old), failed
    df = pd.concat(([old] if old is not None else []) + new, ignore_index=True)
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    tmp = out.with_suffix(".tmp")
    df.to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(out)                                                   # атомарно: обрыв не портит файл
    return len(new), miss, len(df), failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--top", type=int)
    ap.add_argument("--since", default="2022-01-01")
    ap.add_argument("--workers", type=int, default=24)   # 48 → сбои соединений у CDN (28.09)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    since = date.fromisoformat(a.since)
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    first = _first_funding()
    bases = _universe(a.top, [s.upper() for s in a.symbols] if a.symbols else None)
    print(f"монет {len(bases)} · {since} → {end} · выход {OUT}")
    t0, fails = time.time(), 0
    for i, b in enumerate(bases, 1):
        start = max(since, first.get(b, since))
        try:
            n, miss, rows, failed = fetch_symbol(b, start, end, a.workers)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(bases)}] {b}: ОШИБКА {e}")
            continue
        fails += len(failed)
        tail = f" · СБОЙ {len(failed)} дн (перезапуск доберёт): {failed[:2]}" if failed else ""
        print(f"[{i}/{len(bases)}] {b}: +{n} дн · 404 {miss} · строк {rows:,} · {time.time() - t0:.0f} с{tail}")
    print(f"ГОТОВО · дней-сбоев всего {fails}" + (" → запустить ещё раз, докачка заполнит дыры" if fails else ""))


if __name__ == "__main__":
    main()
