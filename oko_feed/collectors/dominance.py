"""Коллектор доминаций (CoinGecko /global): USDT.D, BTC.D → oko_feed.store.dominance.

Standalone: python -m oko_feed.collectors.dominance   (один замер; в cron/цикл — снаружи)
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

from ..store import upsert_dominance

_URL = "https://api.coingecko.com/api/v3/global"


def collect() -> dict[str, float] | None:
    try:
        r = json.load(urllib.request.urlopen(_URL, timeout=15))
        pct = r["data"]["market_cap_percentage"]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out = {}
        for asset in ("usdt", "btc", "eth"):
            if asset in pct:
                upsert_dominance(asset, today, float(pct[asset]))
                out[asset] = float(pct[asset])
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[dominance] error: {e}")
        return None


if __name__ == "__main__":
    print(collect())
