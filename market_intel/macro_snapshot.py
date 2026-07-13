"""market_intel/macro_snapshot.py — макро-снимок рынка одним запуском.

BTC + USDT.D + топ-5 альтов + фандинг + объёмы + XLM OTE (опционально).

Использование:
    python market_intel/macro_snapshot.py              # всё + XLM
    python market_intel/macro_snapshot.py --no-xlm     # без XLM
    python market_intel/macro_snapshot.py --btc-only   # только BTC
"""
import sys, os, argparse, json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ccxt, pandas as pd, numpy as np

EX = ccxt.binance({"enableRateLimit": True, "timeout": 15000})

TOP_5 = ["ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT"]
FUNDING_PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XLM/USDT:USDT"]

# ═══════════════════════════════════════════════════════════════════════════════

def fetch_btc():
    t = EX.fetch_ticker("BTC/USDT")
    ob = EX.fetch_order_book("BTC/USDT", 10)
    bb, ba = ob["bids"][0], ob["asks"][0]
    mid = (bb[0] + ba[0]) / 2
    return {
        "price": t["last"],
        "change_24h": round(t.get("percentage", t.get("change", 0)), 2),
        "high_24h": t["high"], "low_24h": t["low"],
        "volume_24h": t["baseVolume"],
        "bid": bb[0], "ask": ba[0], "spread": (ba[0] - bb[0]) / mid * 100,
    }


def fetch_dominance():
    """BTC.D и USDT.D через coinmarketcap proxy (бесплатный API)."""
    try:
        # BTC dominance — через coinlore (бесплатно, без ключа)
        import urllib.request
        url = "https://api.coinlore.net/api/global/"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        btc_d = float(data[0].get("btc_d", "0"))
        # USDT dominance — coinmarketcap proxy через coincap
        url2 = "https://api.coincap.io/v2/assets/bitcoin"
        req2 = urllib.request.Request(url2, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            btc_data = json.loads(resp2.read())
        btc_mcap = float(btc_data["data"]["marketCapUsd"])
        # Total market cap from coinlore
        total_mcap = float(data[0].get("total_mcap", "0"))
        usdt_d = 100 - btc_d - (100 - btc_d) * 0.35  # rough estimate
        return {"btc_dominance": round(btc_d, 1), "total_mcap_b": round(total_mcap / 1e9, 1)}
    except Exception as e:
        return {"btc_dominance": None, "total_mcap_b": None, "error": str(e)}


def fetch_top5():
    results = []
    for pair in TOP_5:
        try:
            t = EX.fetch_ticker(pair)
            sym = pair.split("/")[0]
            results.append({
                "symbol": sym, "price": t["last"],
                "change_24h": round(t.get("percentage", 0), 2),
                "volume_24h": t["baseVolume"],
            })
        except Exception as e:
            results.append({"symbol": pair, "error": str(e)})
    return results


def fetch_funding():
    results = {}
    for pair in FUNDING_PAIRS:
        try:
            sym = pair.split(":")[0].split("/")[0]
            fr = EX.fetch_funding_rate(pair)
            rate = float(fr.get("fundingRate", fr.get("rate", 0))) * 100
            results[sym] = round(rate, 4)
        except Exception as e:
            results[pair] = f"err: {e}"
    return results


def fetch_xlm_ote():
    """Быстрый OTE-снапшот для XLM."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from core.smc.smc_snapshot import build_smc_snapshot
        bars = EX.fetch_ohlcv("XLM/USDT", "1h", limit=200)
        df = pd.DataFrame(bars, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df.set_index("ts", inplace=True)
        snap = build_smc_snapshot(df)
        if snap:
            ote = snap.get("price_in_ote")
            ote_dir = snap.get("ote_direction")
            ote_tf = snap.get("ote_tf")
            return {"in_ote": ote, "direction": ote_dir, "tf": ote_tf}
    except Exception as e:
        return {"error": str(e)}
    return {"in_ote": False}


# ═══════════════════════════════════════════════════════════════════════════════

def print_report(data):
    print(f"\\n{'='*60}")
    print(f"  MACRO SNAPSHOT  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    btc = data["btc"]
    print(f"\\n  BTC:  ${btc['price']:,.0f}  ({btc['change_24h']:+.1f}%)")
    print(f"        24h: ${btc['high_24h']:,.0f} / ${btc['low_24h']:,.0f}  "
          f"Vol: {btc['volume_24h']:,.0f} BTC")
    print(f"        Spread: {btc['spread']:.4f}%")

    dom = data["dominance"]
    if dom.get("btc_dominance"):
        print(f"\\n  BTC.D: {dom['btc_dominance']}%  "
              f"Market Cap: ${dom.get('total_mcap_b', '?')}B")

    print(f"\\n  TOP-5 ALTS:")
    for a in data["top5"]:
        if "error" in a:
            print(f"    {a['symbol']}: ERROR {a['error']}")
        else:
            vol_m = a['volume_24h'] / 1e6 if a['volume_24h'] else 0
            print(f"    {a['symbol']:6s}  ${a['price']:>10.4f}  "
                  f"{a['change_24h']:>+7.2f}%  Vol: {vol_m:.1f}M")

    print(f"\\n  FUNDING (BingX):")
    for sym, rate in data["funding"].items():
        bull = "BULLISH" if rate < 0 else ("BEARISH" if rate > 0.05 else "NEUTRAL")
        print(f"    {sym:6s}  {rate:>+8.4f}%  {bull}")

    if "xlm_ote" in data:
        x = data["xlm_ote"]
        print(f"\\n  XLM OTE: in_zone={x.get('in_ote')} dir={x.get('direction')} tf={x.get('tf')}")

    print(f"\\n{'='*60}\\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--btc-only", action="store_true")
    ap.add_argument("--no-xlm", action="store_true")
    args = ap.parse_args()

    data = {}
    data["btc"] = fetch_btc()

    if not args.btc_only:
        data["dominance"] = fetch_dominance()
        data["top5"] = fetch_top5()
        data["funding"] = fetch_funding()

        if not args.no_xlm:
            data["xlm_ote"] = fetch_xlm_ote()

    print_report(data)


if __name__ == "__main__":
    main()
