"""Живой скан вселенной BingX: свежие пятёрки ядра 4h (вершина ≤ 48 ч) — кандидаты для пачки разборов, как NEAR 22.09.
python find_fresh_fifths.py [часов] → G:/oko_lab/out/fresh_fifths.csv"""
import sys, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot"); sys.path.insert(0, str(ROOT))
import logging; logging.disable(logging.CRITICAL)
import ccxt
from core.waves import mark_impulse, WaveParams
from core.waves.bingx_klines import fetch_closed
H = float(sys.argv[1]) if len(sys.argv) > 1 else 48
NOW = pd.Timestamp.utcnow(); P = WaveParams()
ex = ccxt.bingx({"options": {"defaultType": "swap"}})
tk = ex.fetch_tickers()
syms = sorted({k.split("/")[0] for k, v in tk.items() if k.endswith(":USDT") and (v.get("quoteVolume") or 0) > 1e6
               and not re.match(r"^(NC|FX|IDX)", k)})
print("монет:", len(syms), flush=True)


def one(b):
    try:
        dh = fetch_closed(b, "4h", 1000, now=NOW)
        if len(dh) < 400:
            return []
        st = mark_impulse(dh, NOW, P, "4h", lookback=int(H / 4))
        return [{"sym": b, "side": s["side"], "top": s["top_time"], "age_h": round((NOW - pd.Timestamp(s["top_time"]).tz_localize("UTC") if pd.Timestamp(s["top_time"]).tzinfo is None else NOW - pd.Timestamp(s["top_time"])).total_seconds() / 3600, 1),
                 "imp": s["imp_pct"], "core": s["core"], "core_full": s["core_full"], "depth5": s["depth5"], "p5": s["p5"], "price": float(dh.close.iloc[-1]),
                 "vol24": (tk.get(f"{b}/USDT:USDT") or {}).get("quoteVolume")} for s in st if (NOW - (pd.Timestamp(s["top_time"]).tz_localize("UTC") if pd.Timestamp(s["top_time"]).tzinfo is None else pd.Timestamp(s["top_time"]))).total_seconds() / 3600 <= H]
    except Exception:
        return []


rows = []
with ThreadPoolExecutor(6) as pool:
    for r in pool.map(one, syms):
        rows += r
d = pd.DataFrame(rows)
if len(d):
    d["от пятой %"] = ((d.price / d.p5 - 1) * 100).round(2)
    d = d.sort_values(["side", "core_full", "age_h"], ascending=[True, False, True])
    d.to_csv("G:/oko_lab/out/fresh_fifths.csv", index=False)
    pd.set_option("display.width", 220); print(d.to_string(index=False))
else:
    print("свежих пятёрок нет")
