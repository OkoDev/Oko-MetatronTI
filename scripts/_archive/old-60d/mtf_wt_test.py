"""
MTF WT STRATEGY TEST: 1h + 15m OS/OB → LONG/SHORT с целью 3%
- LONG: WT OS на 1h И 15m → цель +3%
- SHORT: WT OB на 1h И 15m → цель -3%
- Мера: % net (доход% - costs 0.2%)
"""
import sqlite3, sys, time, statistics as st
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.indicators.indicators import calculate_wt

COST_PCT = 0.2
TARGET_PCT = 3.0
OS_THRESH = -60
OB_THRESH = 60
DB = str(Path(__file__).resolve().parent.parent / "ohlcv_cache.db")

SYMBOLS = ["XLM","GRT","SOL","ADA","DOGE","LINK","AVAX","DOT","TRX","LTC",
           "ARB","OP","SUI","APT","NEAR","INJ","FIL","ATOM","RUNE","SEI",
           "BNB","ETH","XRP","UNI","AAVE","ETC","BCH","ICP","TIA","WLD"]

def find_symbol(cur, base):
    for pat in [f"{base}/USDT", f"binance:{base}/USDT", f"bingx:{base}/USDT:USDT"]:
        if cur.execute("SELECT 1 FROM ohlcv_cache WHERE symbol=? LIMIT 1", (pat,)).fetchone():
            return pat
    return None

def load_tf(cur, sym, tf, limit=4000):
    cur.execute("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time DESC LIMIT ?", (sym, tf, limit))
    rows = cur.fetchall()[::-1]
    if not rows: return None
    df = pd.DataFrame(rows, columns=["ts","open","high","low","close"])
    df["time"] = pd.to_datetime(df["ts"], unit="ms")
    return df.set_index("time")

def run(base, d1h, d15):
    """Симуляция MTF WT стратегии."""
    df1h = calculate_wt(d1h, 10, 21)   # добавляет wt1, wt2, cross, zone...
    df15 = calculate_wt(d15, 10, 21)
    
    trades = []
    
    # Идём по 15m (входной ТФ)
    for i in range(200, len(df15)):
        t = df15.index[i]
        price = float(df15.iloc[i]["close"])
        wt15 = float(df15.iloc[i].get("wt1", np.nan))
        
        # Находим ближайший 1h бар
        ts_i = df15.iloc[i]["ts"] if "ts" in df15.columns else None
        # По времени — ищем бар 1h, который <= t
        d1 = df1h[df1h.index <= t]
        if len(d1) < 50: continue
        wt1h = float(d1.iloc[-1].get("wt1", np.nan))
        
        if np.isnan(wt1h) or np.isnan(wt15):
            continue
        
        # LONG: 1h OS + 15m OS
        if wt1h < OS_THRESH and wt15 < OS_THRESH:
            # Проверяем, не в позиции
            tp = price * (1 + TARGET_PCT / 100)
            sl = price * 0.97  # стоп -3%
            
            # Смотрим вперёд до цели или стопа
            for j in range(i+1, min(len(df15), i + 200)):
                future_hi = float(df15.iloc[j]["high"])
                future_lo = float(df15.iloc[j]["low"])
                if future_hi >= tp:
                    net = TARGET_PCT - COST_PCT
                    trades.append({"net": net, "win": True, "dir": "long", "ts": t, "wt1h": wt1h, "wt15": wt15})
                    break
                elif future_lo <= sl:
                    net = -3.0 - COST_PCT
                    trades.append({"net": net, "win": False, "dir": "long", "ts": t, "wt1h": wt1h, "wt15": wt15})
                    break
                elif j == min(len(df15), i+200) - 1:
                    # Таймаут
                    last_px = float(df15.iloc[j]["close"])
                    net = (last_px - price)/price*100 - COST_PCT
                    trades.append({"net": net, "win": net > 0, "dir": "long", "ts": t, "wt1h": wt1h, "wt15": wt15})
        
        # SHORT: 1h OB + 15m OB
        elif wt1h > OB_THRESH and wt15 > OB_THRESH:
            tp = price * (1 - TARGET_PCT / 100)
            sl = price * 1.03  # стоп +3%
            
            for j in range(i+1, min(len(df15), i + 200)):
                future_lo = float(df15.iloc[j]["low"])
                future_hi = float(df15.iloc[j]["high"])
                if future_lo <= tp:
                    net = TARGET_PCT - COST_PCT
                    trades.append({"net": net, "win": True, "dir": "short", "ts": t, "wt1h": wt1h, "wt15": wt15})
                    break
                elif future_hi >= sl:
                    net = -3.0 - COST_PCT
                    trades.append({"net": net, "win": False, "dir": "short", "ts": t, "wt1h": wt1h, "wt15": wt15})
                    break
                elif j == min(len(df15), i+200) - 1:
                    last_px = float(df15.iloc[j]["close"])
                    net = (price - last_px)/price*100 - COST_PCT
                    trades.append({"net": net, "win": net > 0, "dir": "short", "ts": t, "wt1h": wt1h, "wt15": wt15})
    
    return trades


def main():
    print("="*65)
    print("MTF WT 1h+15m: OS/OB -> LONG/SHORT, цель 3%")
    print("="*65)

    conn = sqlite3.connect(DB); cur = conn.cursor()
    all_trades = []

    for sym in SYMBOLS:
        t0 = time.time()
        found = find_symbol(cur, sym)
        if not found: continue
        d1h = load_tf(cur, found, "1h", 4000)
        d15 = load_tf(cur, found, "15m", 8000)
        if d1h is None or d15 is None: continue
        
        trades = run(sym, d1h, d15)
        all_trades.extend(trades)
        lng = sum(1 for t in trades if t["dir"]=="long")
        sht = sum(1 for t in trades if t["dir"]=="short")
        print(f"  {sym:5} {found:<25} {len(trades)} тр ({lng}L/{sht}S) {time.time()-t0:.0f}с", flush=True)

    conn.close()
    print(f"\nИТОГО: {len(all_trades)} трейдов\n")
    
    if not all_trades: print("Нет"); return
    
    for direction in ["long", "short", "all"]:
        ts = [t for t in all_trades if direction=="all" or t["dir"]==direction]
        if not ts: continue
        nets = [t["net"] for t in ts]
        wr = sum(1 for t in ts if t["win"])/len(ts)*100
        
        print(f"{direction.upper():6} n={len(ts):>4} WR={wr:>4.0f}% mean={st.mean(nets):+.3f}% sum={sum(nets):+.1f}%")
        if len(ts) > 10:
            part = sorted(ts, key=lambda x: x["ts"])
            mid = len(part)//2
            is_ns = [t["net"] for t in part[:mid]]
            oos_ns = [t["net"] for t in part[mid:]]
            is_wr = sum(1 for t in part[:mid] if t["win"])/len(part[:mid])*100
            oos_wr = sum(1 for t in part[mid:] if t["win"])/len(part[mid:])*100
            print(f"    IS  n={len(is_ns):>3} WR={is_wr:>3.0f}% mean={st.mean(is_ns):+.3f}%")
            print(f"    OOS n={len(oos_ns):>3} WR={oos_wr:>3.0f}% mean={st.mean(oos_ns):+.3f}%")
    
    # По WT-порогам
    print(f"\nПо уровням WT (LONG):")
    for thresh in [-50, -55, -60, -65, -70, -75, -80]:
        ts = [t for t in all_trades if t["dir"]=="long" and t["wt1h"] < thresh and t["wt15"] < thresh]
        if len(ts) < 5: continue
        print(f"  wt1h+15m < {thresh:>4}: n={len(ts):>3} mean={st.mean([t['net'] for t in ts]):+.3f}%")

    print(f"\nПо уровням WT (SHORT):")
    for thresh in [50, 55, 60, 65, 70, 75, 80]:
        ts = [t for t in all_trades if t["dir"]=="short" and t["wt1h"] > thresh and t["wt15"] > thresh]
        if len(ts) < 5: continue
        print(f"  wt1h+15m > {thresh:>4}: n={len(ts):>3} mean={st.mean([t['net'] for t in ts]):+.3f}%")

if __name__ == "__main__":
    main()
