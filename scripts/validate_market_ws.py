"""MARKET-WS ч.1: валидация WS-свеча == REST-свеча на закрытых барах."""
import asyncio, gzip, io, json, sys, time, uuid
from collections import defaultdict
import aiohttp, ccxt, pandas as pd, numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WS = "wss://open-api-swap.bingx.com/swap-market"
SYMS = ["BTC-USDT","ETH-USDT","SOL-USDT","BNB-USDT","XRP-USDT","DOGE-USDT","ADA-USDT","AVAX-USDT","LINK-USDT","DOT-USDT"]
TFS = ["5m","15m"]
LISTEN_SEC = 120

def _decode(data):
    if isinstance(data, (bytes, bytearray)):
        try:
            return gzip.GzipFile(fileobj=io.BytesIO(data)).read().decode("utf-8", "ignore")
        except:
            return bytes(data).decode("utf-8", "ignore")
    return str(data)

async def collect_ws():
    ws_candles = defaultdict(list)  # (sym, tf) -> [{t,o,h,l,c,v,closed}]
    subs = []
    for sym in SYMS:
        for tf in TFS:
            subs.append({"id": str(uuid.uuid4()), "reqType": "sub", "dataType": f"{sym}@kline_{tf}"})

    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(WS) as ws:
            # Subscribe
            for sub in subs:
                await ws.send_json(sub)
            await asyncio.sleep(1)  # wait for subscription ack

            print(f"Listening {LISTEN_SEC}s...")
            t0 = time.monotonic()
            msg_count = 0
            while time.monotonic() - t0 < LISTEN_SEC:
                try:
                    ws_msg = await asyncio.wait_for(ws.receive(), timeout=5)
                    raw_data = ws_msg.data
                    msg = json.loads(_decode(raw_data))
                    if isinstance(msg, dict):
                        dt = msg.get("dataType", "")
                        if "@kline_" in dt and "data" in msg:
                            klines = msg["data"] if isinstance(msg["data"], list) else [msg["data"]]
                            for k in klines:
                                if isinstance(k, dict) and "T" in k:
                                    # BingX: поле T = int ms, o/h/l/c/v = СТРОКИ
                                    norm = {"t": k["T"], "o": float(k["o"]), "h": float(k["h"]),
                                            "l": float(k["l"]), "c": float(k["c"]), "v": float(k["v"])}
                                    ws_candles[dt].append(norm)
                                    msg_count += 1
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    pass

    print(f"WS: {msg_count} candles received in {LISTEN_SEC}s")
    return ws_candles

def fetch_rest():
    ex = ccxt.bingx({"enableRateLimit": True, "timeout": 10000})
    rest_candles = {}
    for sym in SYMS:
        bingx_sym = sym.replace("-", "/") + ":USDT"
        for tf in TFS:
            try:
                bars = ex.fetch_ohlcv(bingx_sym, tf, limit=10)
                key = f"{sym}@kline_{tf}"
                rest_candles[key] = [{"t": b[0], "o": b[1], "h": b[2], "l": b[3], "c": b[4], "v": b[5]} for b in bars]
            except Exception as e:
                print(f"  REST error {sym} {tf}: {e}")
    return rest_candles

def validate(ws_candles, rest_candles):
    print("\n=== VALIDATION ===")
    total_matched = 0
    total_mismatched = 0
    total_ws_only = 0

    for key in ws_candles:
        ws_list = ws_candles[key]
        rest_list = rest_candles.get(key, [])

        # Build REST index by timestamp
        rest_by_ts = {r["t"]: r for r in rest_list}

        matched = 0; mismatched = 0
        for w in ws_list:
            ts = w["t"]
            if ts in rest_by_ts:
                r = rest_by_ts[ts]
                # Compare OHLCV with tolerance
                diffs = []
                for field in ["o","h","l","c"]:
                    wv = float(w[field]); rv = float(r[field])
                    if rv > 0:
                        diff = abs(wv - rv) / rv * 100
                        if diff > 0.01:
                            diffs.append(f"{field}:{diff:.3f}%")
                if diffs:
                    mismatched += 1
                    if mismatched <= 3:
                        print(f"  MISMATCH {key} t={ts}: {', '.join(diffs)}")
                else:
                    matched += 1
            else:
                # WS has candle REST doesn't (current open candle)
                pass

        if matched + mismatched > 0:
            match_rate = matched / (matched + mismatched) * 100
            print(f"  {key:25s}: matched={matched} mismatched={mismatched} ({match_rate:.0f}%)")
            total_matched += matched
            total_mismatched += mismatched

    if total_matched + total_mismatched > 0:
        print(f"\n  TOTAL: matched={total_matched} mismatched={total_mismatched} ({total_matched/(total_matched+total_mismatched)*100:.1f}%)")

    # Coverage: how many REST candles have WS data
    for key in rest_candles:
        rest_list = rest_candles[key]
        ws_ts = {w["t"] for w in ws_candles.get(key, [])}
        rest_ts = {r["t"] for r in rest_list}
        covered = rest_ts & ws_ts
        print(f"  COVERAGE {key:25s}: {len(covered)}/{len(rest_ts)} REST candles covered by WS")

async def main():
    ws_data = await collect_ws()
    rest_data = fetch_rest()
    validate(ws_data, rest_data)

asyncio.run(main())
