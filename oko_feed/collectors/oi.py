"""Open Interest коллектор — Binance futures data (бесплатно, 1h-гранулярность, 30 дней истории).

OI = третье измерение к цене и funding:
  OI↑ + цена в пиле у уровня = обе стороны грузятся → импульсный выход (ликвидационное топливо)
  OI↑ + цена↓ = шорты давят (тренд подтверждён) · OI↓ на движении = сквиз/фиксация

Standalone: python -m oko_feed.collectors.oi
Пишет в external_data.db: oi_snapshots(symbol, ts, oi_coins, oi_usd).
"""
from __future__ import annotations

import json
import time
import urllib.request

from ..store import conn

CORE_SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "LINK", "AVAX", "GRT",
                "DOT", "LTC", "OP", "ARB", "NEAR", "ATOM", "TRX", "SAND", "MANA"]


def _ensure(c):
    c.execute("""CREATE TABLE IF NOT EXISTS oi_snapshots (
        symbol TEXT NOT NULL, ts INTEGER NOT NULL,
        oi_coins REAL, oi_usd REAL, PRIMARY KEY (symbol, ts))""")


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 oko-feed"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def collect(symbols: list[str] | None = None, period: str = "1h", limit: int = 24) -> dict:
    """Тянет OI-историю по ядру символов (idempotent: PK symbol+ts). → счётчики/дельты."""
    c = conn(); _ensure(c)
    out = {}
    for sym in symbols or CORE_SYMBOLS:
        try:
            h = _get(f"https://fapi.binance.com/futures/data/openInterestHist"
                     f"?symbol={sym}USDT&period={period}&limit={limit}")
            rows = [(sym, int(x["timestamp"]) // 1000, float(x["sumOpenInterest"]),
                     float(x["sumOpenInterestValue"])) for x in h]
            c.executemany("INSERT OR REPLACE INTO oi_snapshots VALUES (?,?,?,?)", rows)
            c.commit()
            if len(rows) >= 2:
                out[sym] = round((rows[-1][2] / rows[0][2] - 1) * 100, 2)
        except Exception as e:  # noqa: BLE001
            out[sym] = f"err {str(e)[:40]}"
        time.sleep(0.3)
    c.close()
    return out


def oi_change_pct(symbol: str, hours: int = 24) -> float | None:
    """Δ OI % за N часов из копилки (для гейтов/feed)."""
    c = conn()
    cutoff = int(time.time()) - hours * 3600
    rows = c.execute("SELECT ts, oi_coins FROM oi_snapshots WHERE symbol=? AND ts>? ORDER BY ts",
                     (symbol, cutoff)).fetchall()
    c.close()
    if len(rows) < 2 or not rows[0][1]:
        return None
    return round((rows[-1][1] / rows[0][1] - 1) * 100, 2)


if __name__ == "__main__":
    r = collect()
    print("[oi] Δ24ч %:", r)
