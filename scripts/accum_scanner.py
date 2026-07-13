# -*- coding: utf-8 -*-
"""ACCUM-SCANNER (11.07, Егор по XPIN: «можем находить такие явные накопления?» —
63 дня флэта → +47%). Скринер МАКРО-накоплений по дневкам: многонедельный сжатый
боковик на низкой базе с живым объёмом = кандидат на памп. Пружина ловит загрузку
за МИНУТЫ до движения, этот — за НЕДЕЛИ (watch-список, не сигнал на вход).

Критерии v1.1 (ретро-валидировано на XPIN@01.07: коридор 20%, пол 0.24, vol 0.74;
«сужение треугольником» v1 НЕ ловило — реальное накопление = долгий СТАБИЛЬНЫЙ коридор):
  1. НЕ тренд: |close/close[-60д] − 1| < 20%
  2. Узкий коридор: (p90 − p10 закрытий за 45д) / медиана < 0.25 (перцентили — фитили не мешают)
  3. Низкая база: close в нижней половине диапазона 180д
  4. Объём жив: avg(vol 15д) ≥ 0.7 × avg(vol 60д)  и  vol 24ч ≥ $1M
Скоринг = узость + объём-тренд + близость к полу. Отчёт топ-10 → FEED, копилка
accum_candidates (oko_feed БД) для форвард-оценки детектора.

pm2 cron: 07:40 UTC ежедневно.
Тест:  python scripts/accum_scanner.py --test XPINUSDT --asof 2026-07-01
Разово: python scripts/accum_scanner.py --once
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import argparse
import json
import time
import urllib.request
import datetime as dt

BASE = "https://fapi.binance.com"
# стейблы/товарные синтетики — «вечный флэт», не накопление (шум первого скана 11.07)
STOPLIST = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDE", "BUSD",
            "XAUT", "PAXG", "NATGAS", "XPD", "XPT", "XAG", "USO", "WTI"}
MIN_VOL24_USD = 1e6
TREND_MAX_PCT = 20.0
CORRIDOR_MAX = 0.25     # (p90−p10)/median закрытий 45д
FLOOR_HALF = 0.5
VOL_ALIVE = 0.7
TOP_N = 10


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def _klines_1d(symbol: str, limit: int = 200, end_ms: int | None = None):
    url = f"{BASE}/fapi/v1/klines?symbol={symbol}&interval=1d&limit={limit}"
    if end_ms:
        url += f"&endTime={end_ms}"
    ks = _get(url)
    return [(int(k[0]), float(k[2]), float(k[3]), float(k[4]), float(k[7])) for k in ks]
    # (open_ts, high, low, close, quote_volume)


def analyze(symbol: str, end_ms: int | None = None) -> dict | None:
    """→ dict с метриками если кандидат-накопление, иначе None."""
    try:
        ks = _klines_1d(symbol, 200, end_ms)
    except Exception:
        return None
    if len(ks) < 90:
        return None
    ks = ks[:-1]                                        # без текущей незакрытой свечи
    closes = [k[3] for k in ks]
    highs, lows, qvols = [k[1] for k in ks], [k[2] for k in ks], [k[4] for k in ks]
    c = closes[-1]
    if c <= 0:
        return None
    # 4а. объём 24ч (последняя закрытая дневка)
    if qvols[-1] < MIN_VOL24_USD:
        return None
    # 1. не тренд за 60д
    trend_pct = (c / closes[-60] - 1) * 100 if closes[-60] else 999
    if abs(trend_pct) > TREND_MAX_PCT:
        return None
    # 2. узкий стабильный коридор 45д (перцентили закрытий — фитили не искажают)
    w = sorted(closes[-45:])
    p10, p90, med = w[len(w) // 10], w[len(w) * 9 // 10], w[len(w) // 2]
    if med <= 0:
        return None
    corridor = (p90 - p10) / med
    if corridor > CORRIDOR_MAX:
        return None
    # 3. низкая база: близко к полу диапазона 180д
    lo180, hi180 = min(lows[-180:]), max(highs[-180:])
    if hi180 <= lo180:
        return None
    pos180 = (c - lo180) / (hi180 - lo180)
    if pos180 > FLOOR_HALF:
        return None
    # 4б. объём жив
    v15 = sum(qvols[-15:]) / 15
    v60 = sum(qvols[-60:]) / 60
    if v60 <= 0 or v15 / v60 < VOL_ALIVE:
        return None
    tightness = 1 - corridor / CORRIDOR_MAX             # 0..1 (уже коридор = выше)
    score = round(tightness * 40 + min(v15 / v60, 2.0) * 20 + (1 - pos180) * 40, 1)
    return {"symbol": symbol, "score": score, "trend60_pct": round(trend_pct, 1),
            "corridor": round(corridor, 3), "pos180": round(pos180, 2),
            "vol_ratio": round(v15 / v60, 2), "vol24_usd": qvols[-1], "price": c}


def universe() -> list[str]:
    arr = _get(f"{BASE}/fapi/v1/ticker/24hr")
    out = []
    for t in arr:
        s = str(t.get("symbol", ""))
        if not s.endswith("USDT") or s[:-4] in STOPLIST:
            continue
        if float(t.get("quoteVolume") or 0) >= MIN_VOL24_USD:
            out.append(s)
    return out


def run_scan() -> None:
    syms = universe()
    print(f"[ACCUM] вселенная: {len(syms)} пар (vol24 >= ${MIN_VOL24_USD/1e6:.0f}M)")
    found = []
    for i, s in enumerate(syms):
        r = analyze(s)
        if r:
            found.append(r)
            print(f"  🧊 {s:16} score={r['score']} corridor={r['corridor']} "
                  f"pos180={r['pos180']} volx={r['vol_ratio']}")
        time.sleep(0.12)                                # ~90с на всю вселенную, вежливо
    found.sort(key=lambda x: -x["score"])
    top = found[:TOP_N]
    print(f"[ACCUM] кандидатов: {len(found)}, топ-{len(top)}")
    # копилка для форвард-оценки
    try:
        from oko_feed.store import conn
        c = conn()
        c.execute("CREATE TABLE IF NOT EXISTS accum_candidates "
                  "(ts INTEGER, symbol TEXT, score REAL, price REAL, meta TEXT)")
        now = int(time.time())
        for r in found:
            c.execute("INSERT INTO accum_candidates VALUES (?,?,?,?,?)",
                      (now, r["symbol"], r["score"], r["price"], json.dumps(r)))
        c.commit()
    except Exception as e:
        print(f"[ACCUM] store err: {e}")
    if top:
        try:
            from oko_feed.alerts import send_tg
            lines = "\n".join(
                f"• <code>{r['symbol'][:-4]}</code> score {r['score']} · коридор {r['corridor']:.0%} "
                f"· пол {r['pos180']:.0%} · vol×{r['vol_ratio']}" for r in top)
            send_tg("🧊 <b>НАКОПЛЕНИЯ</b> — многонедельный сжатый флэт на низкой базе "
                    f"(watch, не вход):\n{lines}\n"
                    "<i>прорыв объёмом из этого списка = кандидат дня (HOT-LIST подхватит)</i>"
                    "\n\n#ACCUM", channel="feed")
        except Exception as e:
            print(f"[ACCUM] tg err: {e}")


def run_test(symbol: str, asof: str) -> None:
    end_ms = int(dt.datetime.fromisoformat(asof).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    r = analyze(symbol, end_ms)
    print(f"[ACCUM-TEST] {symbol} на {asof}: {r if r else 'НЕ кандидат'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test")
    ap.add_argument("--asof", default=dt.date.today().isoformat())
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    if a.test:
        run_test(a.test, a.asof)
    else:
        run_scan()
