"""
DC-AGENT: DeepCode trading agent. VST LIMIT orders via ds_signals table.
Reads Cube bus (HTTP API) + applies research rules → writes signals.
Polled by ds_advisor_loop (pm2, 30s) → trade_router.submit(source='ds_advisor')
"""
import sqlite3, json, time, math, statistics as st
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)   # [Даат fix] pm2-лог был пуст: буферизация
except Exception:
    pass
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from pathlib import Path
from typing import Optional, Dict, List

# Config
BUS_URL = "http://127.0.0.1:8000/api/cube"
DB = str(Path(__file__).resolve().parent.parent / "subscriptions.db")
POLL_SEC = 60
MAX_OPEN = 5
MIN_CONFLUENCE = 2  # at least 2 of {SMC, WT, Pivot}
SL_MIN_PCT = 0.5
SL_MAX_PCT = 3.0
TP_R_MULT = 2.0

# [Даат fix 25.07, Егор «почему не все доступные?»] ВЕСЬ поток шины: динамический список
# GET /api/cube/pairs?active=1 (только наполненные стейты). Fallback = топ-29 DC.
FALLBACK_PAIRS = [
    "BTC","ETH","SOL","WLD","GRT","LINK","AVAX","DOT","ARB","OP",
    "SUI","APT","NEAR","INJ","FIL","ATOM","RUNE","SEI","LTC","XRP",
    "AAVE","ETC","BCH","TIA","UNI","ADA","DOGE","TRX","BNB"
]


def get_watch_pairs() -> List[str]:
    try:
        import urllib.request
        with urllib.request.urlopen(f"{BUS_URL}/pairs?active=1", timeout=8) as r:
            d = json.loads(r.read())
        pairs = d.get("pairs") or []
        if len(pairs) >= 10:
            return pairs                      # полные символы 'X/USDT:USDT' — fetch их поймёт
    except Exception:
        pass
    return FALLBACK_PAIRS

def moon_phase(date: datetime) -> float:
    y,m = date.year, date.month
    if m <= 2: y -= 1; m += 12
    A = y // 100; B = 2 - A + A // 4
    jd = int(365.25*(y+4716)) + int(30.6001*(m+1)) + date.day + B - 1524.5
    return ((jd - 2451550.1) / 29.53058867) % 1.0

def is_first_quarter(dt: datetime) -> bool:
    p = moon_phase(dt)
    return 0.185 <= p <= 0.315

def count_open(conn) -> int:
    # [Даат fix 25.07] sqlite3: fetchone у КУРСОРА (Connection.execute возвращает cursor).
    # + кап по РЕАЛЬНО открытым сделкам ds_advisor, не по необработанным сигналам.
    cur = conn.execute(
        "SELECT (SELECT COUNT(*) FROM ds_signals WHERE processed=0) + "
        "(SELECT COUNT(*) FROM simulated_trades WHERE status IN ('OPEN','PENDING_ENTRY') "
        " AND signal_type='ds_advisor')")
    return cur.fetchone()[0]

def already_signaled(conn, symbol: str, direction: str, minutes: int = 120) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    cur = conn.execute(   # [Даат fix 25.07] cursor
        "SELECT COUNT(*) FROM ds_signals WHERE symbol=? AND direction=? AND created_at>?",
        (symbol, direction, cutoff))
    return cur.fetchone()[0] > 0

def fetch_pair_state(symbol: str) -> Optional[Dict]:
    try:
        import urllib.request, ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        import urllib.parse   # [Даат fix 25.07] ключи шины = 'BTC/USDT:USDT' (encoded)
        full = symbol if "/" in symbol else f"{symbol}/USDT:USDT"
        url = f"{BUS_URL}/context/{urllib.parse.quote(full, safe='')}"
        req = urllib.request.Request(url)
        req.add_header("X-SOURCE-KEY", "dc-agent")
        with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
            return json.loads(r.read())
    except Exception as e:
        return None

def analyze_pair(symbol: str) -> Optional[Dict]:
    state = fetch_pair_state(symbol)
    if not state:
        return None
    
    signals = {"symbol": symbol, "conf_score": 0, "reasons": [], "direction": None, 
               "entry": None, "sl": None, "tp": None, "confidence": 0.0}
    
    # --- SMC check ---
    # [Даат fix 25.07] РЕАЛЬНЫЙ формат шины (scan_loop SMC_SNAP): ПЛОСКИЙ dict:
    #   last_choch={'direction':'UP'/'DOWN',...} · last_bos={...} · nearest_bull_ob/bear_ob ·
    #   price_in_ote · smc_verdict. Per-TF ['4h'].choch НЕ существует.
    smc = state.get("smc_snap", {}) or {}
    choch_dir = (smc.get("last_choch") or {}).get("direction")   # 'UP' | 'DOWN' | None
    bos_dir = (smc.get("last_bos") or {}).get("direction")
    if choch_dir in ("UP", "DOWN"):
        signals["conf_score"] += 1
        signals["reasons"].append(f"CHoCH {choch_dir}")
        signals["direction"] = "LONG" if choch_dir == "UP" else "SHORT"
    if bos_dir in ("UP", "DOWN"):
        signals["conf_score"] += 1
        signals["reasons"].append(f"BOS {bos_dir}")
        if not signals["direction"]:
            signals["direction"] = "LONG" if bos_dir == "UP" else "SHORT"
    
    # --- WT check ---
    wt = state.get("wt_snap", {}) or {}
    htf_wt = {k: v for k, v in wt.items() if k in ["4h"]} if isinstance(wt, dict) else {}
    if htf_wt:
        for tf, snap in htf_wt.items():
            wt1 = snap.get("wt1", 0)
            if wt1 > 60 and signals.get("direction") == "SHORT":
                signals["conf_score"] += 1
                signals["reasons"].append(f"WT OB on {tf} (wt1={wt1:.0f})")
            elif wt1 < -60 and signals.get("direction") == "LONG":
                signals["conf_score"] += 1
                signals["reasons"].append(f"WT OS on {tf} (wt1={wt1:.0f})")
    
    # --- Pivot check ---
    pivots = state.get("pivot_snap", {}) or {}
    pp = pivots.get("1D", {}) if isinstance(pivots, dict) else {}
    if pp:
        price = state.get("tick_price", 0) or 0
        r1 = pp.get("r1", 0)
        r3 = pp.get("r3", 0)
        s3 = pp.get("s3", 0)
        if price > r1 and price > 0:
            signals["conf_score"] += 1
            signals["reasons"].append(f"Above R1 (R1={r1})")
        if price < r3 and price > 0:
            signals["conf_score"] -= 1  # below R3 = penalty (99% trades!)
    
    if signals["conf_score"] < MIN_CONFLUENCE:
        return None
    
    # --- Entry / SL / TP ---
    price = state.get("tick_price", 0) or 0
    if price <= 0:
        return None
    
    signals["entry"] = round(price, 4)
    sl_pct = max(SL_MIN_PCT, min(SL_MAX_PCT, 2.0))
    
    if signals["direction"] == "LONG":
        signals["sl"] = round(price * (1 - sl_pct / 100), 4)
        signals["tp"] = round(price * (1 + sl_pct * TP_R_MULT / 100), 4)
    else:
        signals["sl"] = round(price * (1 + sl_pct / 100), 4)
        signals["tp"] = round(price * (1 - sl_pct * TP_R_MULT / 100), 4)
    
    signals["confidence"] = min(0.9, signals["conf_score"] / 5.0 + 0.3)
    signals["reasons"].append(f"SL={sl_pct}% TP=2R")
    
    return signals

def write_signal(conn, sig: Dict):
    thesis = "; ".join(sig["reasons"])
    ttl = 2880  # 48h
    conn.execute(
        """INSERT INTO ds_signals (symbol, direction, entry_price, stop_loss, take_profit, ttl_min, thesis, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (sig["symbol"], sig["direction"], sig["entry"], sig["sl"], sig["tp"],
         ttl, thesis, round(sig["confidence"], 2)))
    conn.commit()

def main():
    print(f"DC-AGENT starting. Bus: {BUS_URL} Poll: {POLL_SEC}s Max open: {MAX_OPEN}")
    print(f"Watching: DYNAMIC (все пары шины, fallback {len(FALLBACK_PAIRS)})")
    print()
    
    while True:
        conn = sqlite3.connect(DB)
        open_count = count_open(conn)
        
        if open_count >= MAX_OPEN:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] OPEN={open_count} (max), skipping")
            conn.close()
            time.sleep(POLL_SEC)
            continue
        
        now = datetime.now(timezone.utc)
        if is_first_quarter(now):
            print(f"[{now.strftime('%H:%M:%S')}] 1st Quarter moon - PAUSE")
            conn.close()
            time.sleep(POLL_SEC * 5)
            continue
        
        watch = get_watch_pairs()   # [Даат fix] весь поток шины, каждый цикл свежий
        signals_found = 0
        for symbol in watch:
            if count_open(conn) >= MAX_OPEN:
                break
            
            # Dedup [Даат fix 25.07]: обе стороны (было только LONG — SHORT не дедупился)
            if already_signaled(conn, symbol, "LONG") or already_signaled(conn, symbol, "SHORT"):
                continue
            
            sig = analyze_pair(symbol)
            if sig and sig["conf_score"] >= MIN_CONFLUENCE:
                # Check opposite direction not recently signaled
                opp = "SHORT" if sig["direction"] == "LONG" else "LONG"
                if not already_signaled(conn, symbol, opp, 60):
                    write_signal(conn, sig)
                    signals_found += 1
                    print(f"[{now.strftime('%H:%M:%S')}] SIGNAL: {symbol} {sig['direction']} "
                          f"@ {sig['entry']} SL={sig['sl']} TP={sig['tp']} "
                          f"conf={sig['confidence']} | {sig['reasons']}")
        
        if signals_found == 0:
            print(f"[{now.strftime('%H:%M:%S')}] No signals ({len(watch)} pairs scanned). Open: {open_count}")
        
        conn.close()
        time.sleep(POLL_SEC)

if __name__ == "__main__":
    main()
