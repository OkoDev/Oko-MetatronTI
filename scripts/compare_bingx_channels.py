# -*- coding: utf-8 -*-
"""Канон BingX для хранилища рынка (BACKLOG N15, решение Егора 28.09: BingX по умолчанию, паркеты, ТФ от 3m).

Сверяет два канала закрытых баров на одних монетах и ТФ:
  ccxt  — как качает бот (ccxt bingx fetch_ohlcv, swap);
  v3    — core/waves/bingx_klines.fetch_closed (заведён 14.09: у ccxt битые 4h мелких монет).
Считает: сколько баров совпало по времени, сколько расходится по OHLCV, сколько «застывших» баров
(подряд одинаковый close при ненулевом объёме соседей — симптом бага 14.09).

python scripts/compare_bingx_channels.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.waves.bingx_klines import fetch_closed  # noqa: E402

TFS = ["3m", "5m", "15m", "1h", "4h", "1d"]
LIQUID = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "AVAX", "SUI", "WIF", "ADA"]
N = 300
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def small_caps(k: int = 10) -> list[str]:
    import ccxt
    ex = ccxt.bingx({"options": {"defaultType": "swap"}})
    tk = ex.fetch_tickers()
    rows = [(v.get("quoteVolume") or 0, s.split("/")[0]) for s, v in tk.items()
            if s.endswith(":USDT") and (v.get("quoteVolume") or 0) > 50_000]
    rows.sort()
    picks = ["SOLV", "RECALL"] + [b for _, b in rows if b not in ("SOLV", "RECALL")][: k - 2]
    return picks


def via_ccxt(ex, base: str, tf: str) -> pd.DataFrame:
    raw = ex.fetch_ohlcv(f"{base}/USDT:USDT", tf, limit=N)
    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"]).drop_duplicates("time")
    df["ts"] = pd.to_datetime(df.time, unit="ms", utc=True)
    df = df.set_index("ts")[["open", "high", "low", "close", "volume"]]
    step = pd.Timedelta(tf.replace("m", "min").replace("1d", "1D"))
    return df[df.index + step <= pd.Timestamp.utcnow()]


def stale(df: pd.DataFrame) -> int:
    c = df.close.to_numpy()
    return int(np.sum(c[1:] == c[:-1]))


def main():
    import ccxt
    ex = ccxt.bingx({"options": {"defaultType": "swap"}})
    rows = []
    for group, bases in (("ликвидные", LIQUID), ("мелкие", small_caps())):
        for b in bases:
            for tf in TFS:
                try:
                    a, v = via_ccxt(ex, b, tf), fetch_closed(b, tf, N)
                except Exception as e:  # noqa: BLE001
                    rows.append({"группа": group, "монета": b, "ТФ": tf, "ошибка": str(e)[:60]})
                    continue
                common = a.index.intersection(v.index)
                diff = (~np.isclose(a.loc[common].to_numpy(), v.loc[common].to_numpy(), rtol=1e-9, atol=0)).any(axis=1)
                rows.append({"группа": group, "монета": b, "ТФ": tf, "ccxt": len(a), "v3": len(v),
                             "общих": len(common), "расходятся": int(diff.sum()),
                             "застыл ccxt": stale(a), "застыл v3": stale(v),
                             "ccxt уник.close": a.close.nunique(), "v3 уник.close": v.close.nunique()})
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 300)
    print(R.to_string(index=False))
    ok = R.dropna(subset=["общих"])
    print("\n=== сводка по ТФ и группам ===")
    print(ok.groupby(["группа", "ТФ"]).agg(пар=("монета", "size"), общих=("общих", "sum"),
                                           расходятся=("расходятся", "sum"),
                                           застыл_ccxt=("застыл ccxt", "sum"), застыл_v3=("застыл v3", "sum")).to_string())
    R.to_csv("G:/oko_lab/out/compare_bingx_channels.csv", index=False, encoding="utf-8")


if __name__ == "__main__":
    main()
