"""SL-гипотеза для atr_change/arch104: их минус = тугой SL (как было у ote_nested) или пустой сигнал?
Пересимуляция фактических сделок с РАСШИРЕННЫМ SL (×1/×2/×3) + tp1 на реальных барах.
Если широкий SL → +R (WR↑) — SL-болезнь, edge есть. Если все минус — сигнал пустой."""
import os, sys, sqlite3
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import pandas as pd
from collections import defaultdict

CACHE = "ohlcv_cache.db"; RT = 0.10; MAXHOLD = 500
_c = {}
def load(conn, sym_db, tf):
    # БД symbol "GRT/USDT:USDT" → cache "binance:GRT/USDT"/"bingx:GRT/USDT"
    base = sym_db.split(":")[0]  # GRT/USDT
    k = (base, tf)
    if k in _c: return _c[k]
    df = None
    for pref in ("binance:", "bingx:", ""):
        try:
            d = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
                                  conn, params=(pref + base, tf))
            if d is not None and len(d) > 50: df = d; break
        except Exception: pass
    if df is not None:
        df["ts"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df = df.set_index("ts")[["open","high","low","close"]].astype(float)
    _c[k] = df; return df

def walk(D, entry, sl, lo, hi, ei, x_end):
    risk = abs(entry - sl); fee = RT / (risk / entry * 100)
    tp = entry + risk if D == "long" else entry - risk
    for j in range(ei, x_end + 1):
        if (hi[j] >= sl) if D == "short" else (lo[j] <= sl): return -1.0 - fee
        if (lo[j] <= tp) if D == "short" else (hi[j] >= tp): return 1.0 - fee
    return -fee  # не закрылось → ~0

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    db = sqlite3.connect("subscriptions.db"); cc = sqlite3.connect(CACHE, timeout=60)
    for src in ("atr_change", "arch104"):
        rows = db.execute(f"""SELECT symbol,direction,entry_price,stop_loss,created_at FROM simulated_trades
            WHERE source_router='{src}' AND status!='OPEN' AND entry_price>0 AND stop_loss>0
            AND created_at>='2026-05-01' AND created_at<='2026-05-28' ORDER BY id""").fetchall()
        res = defaultdict(lambda: {"n":0,"w":0,"r":0.0,"pct":0.0})
        used = 0
        for sym, d, e, sldb, ts in rows:
            D = d.lower()
            df = load(cc, sym, "15m")
            if df is None: continue
            created = pd.to_datetime(ts, utc=True)
            seg = df[df.index > created]
            if len(seg) < 5: continue
            lo = seg["low"].values; hi = seg["high"].values; n = len(seg)
            rb = abs(e - sldb)
            if rb <= 0: continue
            used += 1
            for k in (1, 2, 3):
                sl_k = e - k*rb if D == "long" else e + k*rb
                R = walk(D, e, sl_k, lo, hi, 0, min(MAXHOLD, n-1))
                a = res[k]; a["n"] += 1; a["w"] += R > 0; a["r"] += R
                a["pct"] += R * (k*rb/e*100)   # %net = R × (1R в %)
        print(f"\n=== {src} (использовано {used} сделок, 15m, бары из cache) ===")
        for k in (1, 2, 3):
            a = res[k]
            if not a["n"]: continue
            print(f"  SL×{k}: WR={round(100*a['w']/a['n'])}% avgR={a['r']/a['n']:+.3f} sum%net={a['pct']:+.1f}%")
    db.close(); cc.close()

if __name__ == "__main__":
    main()
