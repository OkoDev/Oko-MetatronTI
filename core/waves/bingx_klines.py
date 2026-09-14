"""Закрытые свечи BingX swap через v3 klines с пагинацией по endTime — общий загрузчик для тени, аналитика и терминала.

🔴 14.09: ccxt fetch_ohlcv для мелких монет отдавал битые 4h (SOLV — 180 уникальных закрытий на 1000 баров,
один и тот же бар с мая по сентябрь; RECALL — 817), а v3 (тот же, что у терминала :8010) — чистый.
`now` берётся на каждом вызове: процесс может жить сутками (терминал, тень), фиксировать его при импорте нельзя."""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Optional

import pandas as pd

from core.trading.source_registry import _TF_MIN as TF_MIN

KL_URL = "https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={s}-USDT&interval={tf}&limit={n}"


def fetch_closed(sym: str, tf: str, n: int, now: Optional[pd.Timestamp] = None, retries: int = 3) -> pd.DataFrame:
    """До n последних ЗАКРЫТЫХ баров (DatetimeIndex UTC, open/high/low/close/volume). sym: «SOLV», «SOLV/USDT» или «SOLV/USDT:USDT»."""
    now = now or pd.Timestamp.utcnow()
    base = sym.split("/")[0].split(":")[0]
    out, end = [], None
    while len(out) < n:
        url = KL_URL.format(s=base, tf=tf, n=min(1000, n - len(out) + 1)) + (f"&endTime={end}" if end else "")
        d = None
        for i in range(retries):
            try:
                d = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "oko"}), timeout=20).read())
                break
            except Exception:
                time.sleep(2 + 2 * i)
        raw = (d or {}).get("data") or []
        if not raw:
            break
        chunk = [[int(b["time"]), float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]), float(b["volume"])] for b in raw]
        out = chunk + out if end else chunk
        oldest = min(r[0] for r in chunk)
        if len(raw) < 2 or (end is not None and oldest >= end):
            break
        end = oldest - 1
    if not out:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(out, columns=["time", "open", "high", "low", "close", "volume"]).drop_duplicates("time").sort_values("time")
    df["ts"] = pd.to_datetime(df.time, unit="ms", utc=True)
    df = df.set_index("ts")[["open", "high", "low", "close", "volume"]]
    return df[df.index + pd.Timedelta(minutes=TF_MIN[tf]) <= now].iloc[-n:]
