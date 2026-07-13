# -*- coding: utf-8 -*-
"""PIVOT-SANITY (11.07, после ARB-пивот-бага: дневные пивоты 642 пар сутки жили от
частичной свечи из протухшего кэша — Егор поймал глазом по TW).

Ежедневная сверка: N случайных пар из pivot_cache (1D) → честный пересчёт от СВЕЖИХ
BingX-свечей НАПРЯМУЮ (urllib, мимо data_collector/ApiEngine-кэша — виновником был НАШ
кэш, не биржа; Егор: «мы не Binance!» — та же биржа, что торговля и его TW) →
расхождение PP > tol% = 🔴 TG SYSTEM-алерт.

pm2 cron: 00:25 UTC ежедневно (после пересчёта пивотов новым днём).
Тест: python scripts/pivot_sanity.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import json
import random
import sqlite3
import urllib.request
import datetime as dt

N_CHECK = 12
TOL_PCT = 0.05          # |PP_бд − PP_честный| / PP, % — та же биржа, должно сходиться почти точно
DB = "subscriptions.db"


def _bingx_prev_day(sym_db: str):
    """Вчерашняя UTC-свеча с BingX НАПРЯМУЮ (мимо кэшей бота). sym_db='ARB/USDT:USDT'."""
    base = sym_db.split("/")[0]
    url = (f"https://open-api.bingx.com/openApi/swap/v2/quote/klines"
           f"?symbol={base}-USDT&interval=1d&limit=3")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req, timeout=15))
    ks = d.get("data") or []
    today = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_ms = int(today.timestamp() * 1000)
    prev = [k for k in ks if int(k.get("time", 0)) < today_ms]
    if not prev:
        return None
    k = max(prev, key=lambda x: int(x["time"]))
    return float(k["high"]), float(k["low"]), float(k["close"])


def main() -> None:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT symbol, pp, r1, s1, period_label FROM pivot_cache "
                     "WHERE timeframe='1D' AND pp > 0").fetchall()
    if not rows:
        print("[PIVOT-SANITY] pivot_cache пуст — нечего сверять")
        return
    sample = random.sample(rows, min(N_CHECK, len(rows)))
    bad, checked = [], 0
    for r in sample:
        try:
            hlc = _bingx_prev_day(str(r["symbol"]))
        except Exception:
            continue
        if not hlc:
            continue
        h, l, cl = hlc
        pp_true = (h + l + cl) / 3
        pp_db = float(r["pp"])
        diff_pct = abs(pp_db - pp_true) / pp_true * 100
        checked += 1
        mark = "🔴" if diff_pct > TOL_PCT else "✓"
        print(f"  {mark} {r['symbol']:22} PP_бд={pp_db:.6g} PP_true={pp_true:.6g} Δ={diff_pct:.3f}%")
        if diff_pct > TOL_PCT:
            bad.append((r["symbol"], pp_db, pp_true, diff_pct))
    print(f"[PIVOT-SANITY] сверено {checked}, расхождений {len(bad)}")
    if bad:
        try:
            from oko_feed.alerts import send_tg
            lines = "\n".join(f"• <code>{s}</code>: БД {a:.6g} vs факт {b:.6g} (Δ{d:.2f}%)"
                              for s, a, b, d in bad[:8])
            send_tg(f"🔴 <b>PIVOT-SANITY</b> — дневные пивоты разошлись с фактом "
                    f"({len(bad)}/{checked}):\n{lines}\n"
                    f"<i>класс ARB-бага 11.07 — проверить кэш свечей</i>\n\n#SYSTEM",
                    channel="system")
        except Exception as e:
            print(f"[PIVOT-SANITY] TG err: {e}")


if __name__ == "__main__":
    main()
