"""
WT-PCT P5/200b HONEST NET: честный перепрогон на прод-SL 0.5% + комиссия 0.1%
- WT процентиль P5 (скользящий, окно 200 баров)
- LONG: wt1 пересекает P5 снизу вверх (выход из OS)
- SHORT: wt1 пересекает P95 сверху вниз (выход из OB)
- SL=0.5%, TP=3%, комиссия=0.1%
- Мера: % net
"""
import sqlite3, sys, time, statistics as st
from pathlib import Path
import pandas as pd, numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.indicators.indicators import calculate_wt

PROD_SL = 0.5    # честный прод-SL в %
TP_PCT = 3.0     # цель
COST_PCT = 0.1   # комиссия
PCT_WINDOW = 200 # окно процентиля
PCT_LOW = 5      # P5 — нижние 5%

DB = str(Path(__file__).resolve().parent.parent / "ohlcv_cache.db")
SYMS = ["XLM","GRT","SOL","ADA","DOGE","LINK","AVAX","DOT","TRX","LTC","ARB","OP","SUI","APT","NEAR","INJ","FIL","ATOM","RUNE","SEI","BNB","ETH","XRP","UNI","AAVE","ETC","BCH","ICP","TIA","WLD"]

def find_sym(c,b):
    for p in [f"{b}/USDT",f"binance:{b}/USDT",f"bingx:{b}/USDT:USDT"]:
        if c.execute("SELECT 1 FROM ohlcv_cache WHERE symbol=? LIMIT 1",(p,)).fetchone(): return p

def load(c,s,tf,lim=5000):
    c.execute("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time DESC LIMIT ?",(s,tf,lim))
    r=c.fetchall()[::-1]
    if not r: return None
    df=pd.DataFrame(r,columns=["ts","open","high","low","close"])
    df["time"]=pd.to_datetime(df["ts"],unit="ms")
    return df.set_index("time")

def rolling_pct(arr, window, low):
    """Скользящий процентиль P<low> по окну window."""
    n=len(arr)
    out=np.full(n, np.nan)
    for i in range(window-1, n):
        out[i]=np.percentile(arr[i-window+1:i+1], low)
    return out

def simulate(df):
    """WT-PCT P5/200b стратегия."""
    df=calculate_wt(df, 10, 21)
    if len(df)<PCT_WINDOW+50: return []
    
    wt1=df["wt1"].values
    p5=rolling_pct(wt1, PCT_WINDOW, PCT_LOW)  # нижние 5%
    p95=rolling_pct(wt1, PCT_WINDOW, 100-PCT_LOW)  # верхние 5%
    
    trades=[]
    in_long=False; in_short=False
    long_entry=0; short_entry=0
    
    for i in range(PCT_WINDOW+10, len(df)-1):
        price=float(df.iloc[i]["close"])
        wi=wt1[i]; wip=wt1[i-1]
        p5i=p5[i]; p95i=p95[i]; p5p=p5[i-1]; p95p=p95[i-1]
        
        if np.isnan(wi) or np.isnan(p5i) or np.isnan(p95i):
            continue
        
        # Проверяем выходы
        if in_long:
            sl=long_entry*(1-PROD_SL/100); tp=long_entry*(1+TP_PCT/100)
            hi=float(df.iloc[i]["high"]); lo=float(df.iloc[i]["low"])
            if lo<=sl:
                trades.append({"net":-PROD_SL-COST_PCT,"win":False,"dir":"long","ts":df.index[i]})
                in_long=False
            elif hi>=tp:
                trades.append({"net":TP_PCT-COST_PCT,"win":True,"dir":"long","ts":df.index[i]})
                in_long=False
        
        if in_short:
            sl=short_entry*(1+PROD_SL/100); tp=short_entry*(1-TP_PCT/100)
            hi=float(df.iloc[i]["high"]); lo=float(df.iloc[i]["low"])
            if hi>=sl:
                trades.append({"net":-PROD_SL-COST_PCT,"win":False,"dir":"short","ts":df.index[i]})
                in_short=False
            elif lo<=tp:
                trades.append({"net":TP_PCT-COST_PCT,"win":True,"dir":"short","ts":df.index[i]})
                in_short=False
        
        # Сигналы: кросс P5 вверх (LONG) / кросс P95 вниз (SHORT)
        if not in_long and not in_short:
            if wip<p5p and wi>p5i:
                in_long=True; long_entry=price
            elif wip>p95p and wi<p95i:
                in_short=True; short_entry=price
    
    return trades

# --- Сбор ---
conn=sqlite3.connect(DB);cur=conn.cursor()
all_tr=[]
for s in SYMS:
    f=find_sym(cur,s)
    if not f: continue
    df=load(cur, f, "15m", 8000)
    if df is None: continue
    tr=simulate(df)
    all_tr.extend(tr)
    lng=sum(1 for t in tr if t["dir"]=="long")
    sht=sum(1 for t in tr if t["dir"]=="short")
    print(f"  {s:5} {len(tr)} тр ({lng}L/{sht}S)", flush=True)
conn.close()

print(f"\n{'='*60}")
print(f"WT-PCT P5/{PCT_WINDOW}b: прод-SL={PROD_SL}% TP={TP_PCT}% cost={COST_PCT}%")
print(f"Всего: {len(all_tr)} трейдов")
print(f"{'='*60}")

if not all_tr: print("Нет сделок"); exit()

for d,label in [("long","LONG"),("short","SHORT"),("all","ALL")]:
    ts=[t for t in all_tr if d=="all" or t["dir"]==d]
    if len(ts)<10: continue
    nets=[t["net"] for t in ts]
    wr=sum(1 for t in ts if t["win"])/len(ts)*100
    
    part=sorted(ts,key=lambda x:x["ts"]); mid=len(part)//2
    is_ns=[t["net"] for t in part[:mid]]
    oos_ns=[t["net"] for t in part[mid:]]
    is_wr=sum(1 for t in part[:mid] if t["win"])/len(part[:mid])*100 if part[:mid] else 0
    oos_wr=sum(1 for t in part[mid:] if t["win"])/len(part[mid:])*100 if part[mid:] else 0
    
    print(f"\n{label}")
    print(f"  ALL n={len(ts):>4} WR={wr:>3.0f}% mean={st.mean(nets):+.3f}% sum={sum(nets):+.1f}%")
    print(f"  IS  n={len(is_ns):>4} WR={is_wr:>3.0f}% mean={st.mean(is_ns):+.3f}%")
    if oos_ns: print(f"  OOS n={len(oos_ns):>4} WR={oos_wr:>3.0f}% mean={st.mean(oos_ns):+.3f}%")

print(f"\nВЕРДИКТ:")
for d in ["long","short"]:
    ts=[t for t in all_tr if t["dir"]==d]
    if not ts: continue
    part=sorted(ts,key=lambda x:x["ts"]); mid=len(part)//2
    oos_ns=[t["net"] for t in part[mid:]]
    oos_m=st.mean(oos_ns) if oos_ns else 0
    print(f"  {d.upper():6} OOS={oos_m:+.3f}% {'EDGE' if oos_m>0.1 else 'SHUM' if oos_m>0 else 'NET'}")
