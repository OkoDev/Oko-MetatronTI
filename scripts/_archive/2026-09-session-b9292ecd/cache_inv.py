# -*- coding: utf-8 -*-
"""Что реально лежит в кэше баров: таблицы, таймфреймы, покрытие."""
import sqlite3

DB = r"e:\MTF BOT\CURSOR\crypto_volume_bot\ohlcv_cache.db"
c = sqlite3.connect(DB)

tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("таблицы:", tables)

for t in tables:
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
    print(f"\n{t}: {cols}")
    if "timeframe" in cols:
        q = (f"SELECT timeframe, COUNT(DISTINCT symbol), COUNT(*), "
             f"MIN(time), MAX(time) FROM {t} GROUP BY timeframe")
        for tf, sym, n, lo, hi in c.execute(q):
            import datetime as dt
            f = lambda ms: dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")
            print(f"  {tf:>4}: символов {sym:>4}  баров {n:>12,}  {f(lo)} → {f(hi)}")

