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


LIVE_CORE = ["BTC", "ETH", "SOL", "GRT", "DOGE", "XRP", "LINK", "AVAX"]


def live_radar(threshold_pct: float = 0.5) -> list[dict]:
    """ОПЕРАТИВНЫЙ радар (5m-гранулярность, ядро монет): |ΔOI 10мин| >= порога → событие.
    Классификация: OI↑ = build (грузятся, настоящий интерес) · OI↓ = unwind/СКВИЗ (закрытия).
    События пишутся в onchain_events (kind='oi_spike') → видны во вкладке Feed."""
    from ..store import add_onchain_event
    events = []
    c = conn(); _ensure(c)
    for sym in LIVE_CORE:
        try:
            h = _get(f"https://fapi.binance.com/futures/data/openInterestHist"
                     f"?symbol={sym}USDT&period=5m&limit=4")
            if len(h) < 3:
                continue
            rows = [(sym, int(x["timestamp"]) // 1000, float(x["sumOpenInterest"]),
                     float(x["sumOpenInterestValue"])) for x in h]
            c.executemany("INSERT OR REPLACE INTO oi_snapshots VALUES (?,?,?,?)", rows)
            c.commit()
            prev, cur = rows[-3][2], rows[-1][2]     # ~10 минут
            d_pct = (cur / prev - 1) * 100 if prev else 0
            if abs(d_pct) >= threshold_pct:
                kind_dir = "build" if d_pct > 0 else "unwind_squeeze"
                add_onchain_event(rows[-1][1], "oi_spike", "binance_oi", f"{sym} {d_pct:+.2f}%/10m",
                                  rows[-1][3], kind_dir, "")
                events.append({"sym": sym, "d10m_pct": round(d_pct, 2), "dir": kind_dir})
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    c.close()
    return events


if __name__ == "__main__":
    r = collect()
    print("[oi] Δ24ч %:", r)
    print("[oi] live radar:", live_radar())
