# -*- coding: utf-8 -*-
"""Догрузка свежих свечей по ОДНОМУ символу в ohlcv_cache.db.

Повод (03.09.2026): кэш HYPE обрывался 22 августа, а разбор шёл по графику до
3 сентября — волновой движок не видел самого пампа к новому максимуму, и вывод
о текущей волне был неполон.

Публичный OHLCV BingX, без ключей. Пишем ТОЛЬКО недостающие бары
(INSERT OR IGNORE по первичному ключу symbol+timeframe+time).

Запуск: python scripts/topup_symbol_cache.py HYPE/USDT 4h 1h 15m
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

DB = str(ROOT / "ohlcv_cache.db")
LIMIT = 1000          # BingX отдаёт до 1000 баров за запрос


def topup(symbol: str, tf: str) -> None:
    import ccxt

    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    con = sqlite3.connect(DB)
    row = con.execute(
        "SELECT MAX(time), COUNT(*) FROM ohlcv_cache WHERE symbol=? AND timeframe=?",
        (symbol, tf),
    ).fetchone()
    last, have = (row[0] or 0), (row[1] or 0)
    print(f"{symbol} {tf}: в кэше {have} баров, последний {last}")

    market = symbol if ":" in symbol else f"{symbol}:USDT"
    since = last + 1 if last else None
    added = 0
    for _ in range(20):                      # предохранитель от бесконечного цикла
        try:
            batch = ex.fetch_ohlcv(market, tf, since=since, limit=LIMIT)
        except Exception as e:               # noqa: BLE001
            print(f"  ошибка: {type(e).__name__}: {str(e)[:90]}")
            break
        if not batch:
            break
        new = [b for b in batch if b[0] > last]
        if not new:
            break
        con.executemany(
            "INSERT OR IGNORE INTO ohlcv_cache "
            "(symbol,timeframe,time,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?,?)",
            [(symbol, tf, int(b[0]), float(b[1]), float(b[2]),
              float(b[3]), float(b[4]), float(b[5])) for b in new],
        )
        con.commit()
        added += len(new)
        last = new[-1][0]
        since = last + 1
        if len(batch) < LIMIT:
            break
        time.sleep(0.3)

    import pandas as pd
    mx = con.execute(
        "SELECT MAX(time) FROM ohlcv_cache WHERE symbol=? AND timeframe=?", (symbol, tf)
    ).fetchone()[0]
    print(f"  добавлено {added} · теперь до {pd.to_datetime(mx, unit='ms')}")
    con.close()


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "HYPE/USDT"
    for t in (sys.argv[2:] or ["4h", "1h"]):
        topup(sym, t)
