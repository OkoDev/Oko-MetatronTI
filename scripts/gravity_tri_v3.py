"""
DS-GRAVITY-TRI v3: полная триангуляция.
- SHORT-рецепт: 1h OTE + 15m слом + fib_-1.0
- Gravity-скоринг на каждом входе
- Бакеты 0/0-40/40-100/100+
- %% net measure
"""
import sqlite3, sys, time, statistics as st
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.smc.ote_matrix import structure_trend, build_ote

COST_PCT = 0.2
RISK_CAP = 6.0
DB = str(Path(__file__).resolve().parent.parent / "ohlcv_cache.db")

SYMBOLS = ["XLM", "GRT", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA", "WLD"]

ALPHA = 1.5
NEAR_PCT = 3.0
W = {"pivot": 2.0, "swing": 2.0, "fvg": 1.5, "ote": 2.5}
WTF = {"5m": 1.0, "15m": 1.5, "1h": 2.5, "4h": 3.5, "1d": 5.0, "1w": 7.0}

def find_symbol(cur, base):
    patterns = [f"{base}/USDT", f"binance:{base}/USDT", f"bingx:{base}/USDT:USDT"]
    for pat in patterns:
        if cur.execute("SELECT 1 FROM ohlcv_cache WHERE symbol=? LIMIT 1", (pat,)).fetchone():
            return pat
    return None

def load_tf(cur, sym, tf, limit=3000):
    cur.execute("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time DESC LIMIT ?", (sym, tf, limit))
    rows = cur.fetchall()[::-1]
    if not rows: return None
    df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["ts"], unit="ms")
    return df.set_index("time")

def calc_gravity(price, direction, store):
    """Gravity-скоринг. store = {tf: df}."""
    if price <= 0: return 0.0, 0
    typed = []
    for tf in ("1d", "1w"):
        df = store.get(tf)
        if df is not None and len(df) >= 2:
            H = df["high"].iloc[-2]; L = df["low"].iloc[-2]; C = df["close"].iloc[-2]
            PP = (H+L+C)/3
            for pv in [PP, 2*PP-L, 2*PP-H, PP+(H-L), PP-(H-L)]:
                typed.append((pv, "pivot", tf))
    for tf in ("5m", "15m", "1h", "4h"):
        try:
            from core.smc.smc_engine import zigzag_atr, ote_retest_setups
            df = store.get(tf)
            if df is None or len(df) < 60: continue
            for _ts, zp in zigzag_atr(df, 11, 3)[-6:]:
                typed.append((zp, "swing", tf))
            hh, ll = df["high"].values, df["low"].values
            for i in range(max(0,len(df)-30), len(df)-2):
                if ll[i+2] > hh[i]: typed.append(((ll[i+2]+hh[i])/2, "fvg", tf))
                elif hh[i+2] < ll[i]: typed.append(((hh[i+2]+ll[i])/2, "fvg", tf))
            for s in ote_retest_setups(df):
                if s["direction"] == direction:
                    lo, hi = s["ote"]; typed.append(((lo+hi)/2, "ote", tf)); break
        except: pass
    g = 0.0; cnt = 0
    for lp, typ, tf in typed:
        if lp <= 0: continue
        dist = abs(lp - price) / price * 100
        if dist <= NEAR_PCT:
            g += W.get(typ, 1.0) * WTF.get(tf, 1.0) / max(dist, 0.05) ** ALPHA
            cnt += 1
    return g, cnt

def run(base, d1h_raw, d15_raw, store_all):
    trades = []
    pos = None; last1_len = -1; cache = None
    d15 = d15_raw; d1h = d1h_raw

    for i in range(200, len(d15)):
        t = d15.index[i]; price = float(d15.iloc[i]["close"])
        hi = float(d15.iloc[i]["high"]); lo = float(d15.iloc[i]["low"])

        if pos:
            dr = pos["dir"]; ex = None
            if dr == "long" and (lo <= pos["sl"] or hi >= pos["tp"]):
                ex = pos["sl"] if lo <= pos["sl"] else pos["tp"]
            elif dr == "short" and (hi >= pos["sl"] or lo <= pos["tp"]):
                ex = pos["sl"] if hi >= pos["sl"] else pos["tp"]
            if ex:
                sign = 1 if dr == "long" else -1
                net = (ex - pos["entry"]) / pos["entry"] * 100 * sign - COST_PCT
                trades.append({"net": net, "win": net > 0, "ts": t, "dir": dr,
                               "gravity": pos.get("g", 0), "n_levels": pos.get("nl", 0)})
                pos = None

        d1 = d1h[d1h.index <= t]
        if len(d1) < 120: continue
        if len(d1) != last1_len:
            try:
                st1 = structure_trend(d1, lookback=250); last1_len = len(d1)
                if st1["trend"] and st1.get("break_level") and st1.get("extreme"):
                    ob = build_ote(st1["extreme"], st1["break_level"])
                    cache = {"bias": st1["trend"], "lo": ob["ote"][0], "hi": ob["ote"][1], "lv": ob["levels"]}
                else: cache = None
            except: cache = None
        if not cache: continue
        bias, lo_z, hi_z, lv = cache["bias"], cache["lo"], cache["hi"], cache["lv"]
        if not (lo_z <= price <= hi_z): continue
        if lo_z <= float(d15.iloc[i-1]["close"]) <= hi_z: continue

        try: st15 = structure_trend(d15.iloc[:i+1], lookback=250)
        except: continue
        brk15 = st15.get("break_level")
        if not brk15: continue
        entry = price
        if bias == "long" and brk15 < entry: sl = brk15 * 0.999
        elif bias == "short" and brk15 > entry: sl = brk15 * 1.001
        else: continue
        risk = abs(entry - sl)
        if risk <= 0 or risk/entry*100 > RISK_CAP: continue
        fib = lv.get(-1.0)
        if not fib: continue
        if (bias == "long" and fib <= entry) or (bias == "short" and fib >= entry): continue

        # Gravity на момент входа
        store_at = {}
        for tf, df in store_all.items():
            if df is None: store_at[tf] = None; continue
            s = df[df.index <= t]
            store_at[tf] = s.iloc[-300:] if len(s) >= 30 else None
        direction = bias
        grav, nl = calc_gravity(entry, direction, store_at)

        pos = {"dir": bias, "entry": entry, "sl": sl, "tp": fib, "ts": t, "g": grav, "nl": nl}
    return trades

def main():
    print("="*70); print("DS-GRAVITY-TRI v3: ПОЛНАЯ ТРИАНГУЛЯЦИЯ SHORT-РЕЦЕПТА"); print("="*70)

    conn = sqlite3.connect(DB); cur = conn.cursor()
    all_trades = []

    for sym in SYMBOLS:
        t0 = time.time()
        found = find_symbol(cur, sym)
        if not found: print(f"  {sym}: НЕТ"); continue

        d1h = load_tf(cur, found, "1h", 2000)
        d15 = load_tf(cur, found, "15m", 5000)
        d5m = load_tf(cur, found, "5m", 2000)
        d4h = load_tf(cur, found, "4h", 500)
        d1d = load_tf(cur, found, "1d", 200)
        if d1h is None or d15 is None: print(f"  {sym}: нет 1h/15m"); continue

        store_all = {"5m": d5m, "15m": d15, "1h": d1h, "4h": d4h, "1d": d1d, "1w": None}
        trades = run(sym, d1h, d15, store_all)
        all_trades.extend(trades)
        dt = time.time() - t0
        short_t = sum(1 for t in trades if t["dir"] == "short")
        long_t = sum(1 for t in trades if t["dir"] == "long")
        print(f"  {sym:5} | {found:<25} | {len(trades):>3} тр ({short_t}S/{long_t}L) | {dt:.0f}с", flush=True)
        if len(all_trades) >= 5000: print("лимит 5000"); break

    conn.close()
    print(f"\n{'='*70}\nИТОГО: {len(all_trades)} трейдов\n{'='*70}")

    if not all_trades: print("Нет сделок."); return

    # Разделяем SHORT
    short_trades = [t for t in all_trades if t["dir"] == "short"]
    print(f"SHORT: {len(short_trades)} трейдов")
    if short_trades:
        nets = [t["net"] for t in short_trades]
        wr = sum(1 for t in short_trades if t["win"]) / len(short_trades) * 100
        print(f"ALL SHORT: n={len(nets)} WR={wr:.0f}% mean={st.mean(nets):+.3f}% sum={sum(nets):+.1f}%")

        # Бакеты gravity
        buckets = [
            ("gravity 0", lambda g: g == 0),
            ("gravity 0-10", lambda g: 0 < g <= 10),
            ("gravity 10-40", lambda g: 10 < g <= 40),
            ("gravity 40-100", lambda g: 40 < g <= 100),
            ("gravity 100-200", lambda g: 100 < g <= 200),
            ("gravity 200+", lambda g: g > 200),
        ]
        print(f"\n{'Bucket':<20} {'n':>5} {'WR':>5} {'mean%':>8} {'sum%':>8}")
        print("-"*50)
        for name, fn in buckets:
            ts = [t for t in short_trades if fn(t["gravity"])]
            if not ts: continue
            ns = [t["net"] for t in ts]
            w = sum(1 for t in ts if t["win"]) / len(ts) * 100
            print(f"{name:<20} {len(ts):>5} {w:>4.0f}% {st.mean(ns):>+7.3f} {sum(ns):>+7.1f}")

        # Гранулярно
        print(f"\n{'Гранулярные бакеты (SHORT)':^50}")
        print(f"{'Gravity':<12} {'n':>5} {'mean%':>8}")
        for lo in range(0, 210, 10):
            hi = lo+10
            ts = [t for t in short_trades if lo <= t["gravity"] < hi]
            if len(ts) < 5: continue
            mn = st.mean([t["net"] for t in ts])
            print(f"{lo:>4}-{hi:<4} {len(ts):>5} {mn:+8.3f}%")

        # Поиск порога
        print(f"\n{'ПОРОГ gravity для >=0%/сделку':^50}")
        for g_thresh in range(0, 300, 5):
            ts = [t for t in short_trades if t["gravity"] >= g_thresh]
            if len(ts) < 5: continue
            mn = st.mean([t["net"] for t in ts])
            if mn >= 0:
                print(f"  gravity>={g_thresh:>3} n={len(ts):>4} mean={mn:+.2f}%")
                years = 4
                print(f"  >> сделок/день: {len(ts)/(years*365):.1f}")
                break

        # OOS split по SHORT
        sts = sorted(short_trades, key=lambda x: x["ts"])
        mid = len(sts)//2
        print(f"\n{'OOS-сплит SHORT':^50}")
        for lbl, part in [("IS", sts[:mid]), ("OOS", sts[mid:])]:
            ns = [t["net"] for t in part]
            w = sum(1 for t in part if t["win"]) / len(part) * 100
            print(f"  {lbl:5} n={len(part):>4} WR={w:>3.0f}% mean={st.mean(ns):+.3f}% sum={sum(ns):+.1f}%")

        # Корреляция gravity vs net
        if len(short_trades) > 10:
            gs = [t["gravity"] for t in short_trades]
            ns = [t["net"] for t in short_trades]
            try:
                import numpy as np
                corr = np.corrcoef(gs, ns)[0][1]
                print(f"\nКорреляция gravity vs net: {corr:.4f}")
            except: pass

if __name__ == "__main__":
    main()
