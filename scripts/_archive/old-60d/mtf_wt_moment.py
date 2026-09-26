"""
MTF WT MOMENT+STATE: 15m CROSS + 1h STATE
- LONG: 15m wt1 кросс ВВЕРХ из OS (пред < -60, тек > -60, выход из перепроданности) + 1h БЫЛ в OS (recent)
- SHORT: 15m wt1 кросс ВНИЗ из OB (пред > 60, тек < 60, выход из перекупленности) + 1h БЫЛ в OB (recent)
- Цель 3%, стоп 3%, costs 0.2%
"""
import sqlite3, sys, time, statistics as st
from pathlib import Path
import pandas as pd, numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.indicators.indicators import calculate_wt

COST_PCT, TARGET_PCT = 0.2, 3.0
DB = str(Path(__file__).resolve().parent.parent / "ohlcv_cache.db")
SYMS = ["XLM","GRT","SOL","ADA","DOGE","LINK","AVAX","DOT","TRX","LTC","ARB","OP","SUI","APT","NEAR","INJ","FIL","ATOM","RUNE","SEI","BNB","ETH","XRP","UNI","AAVE","ETC","BCH","ICP","TIA","WLD"]

def find_sym(c,b):
    for p in [f"{b}/USDT",f"binance:{b}/USDT",f"bingx:{b}/USDT:USDT"]:
        if c.execute("SELECT 1 FROM ohlcv_cache WHERE symbol=? LIMIT 1",(p,)).fetchone(): return p

def load(c,s,tf,lim=5000):
    c.execute("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time DESC LIMIT ?",(s,tf,lim))
    r=c.fetchall()[::-1]
    if not r:return None
    df=pd.DataFrame(r,columns=["ts","open","high","low","close"])
    df["time"]=pd.to_datetime(df["ts"],unit="ms")
    return df.set_index("time")

def simulate(d1h,d15):
    df1h=calculate_wt(d1h,10,21)
    df15=calculate_wt(d15,10,21)
    trades=[]
    for i in range(200,len(df15)):
        price=float(df15.iloc[i]["close"]); t=df15.index[i]
        wt_now=float(df15.iloc[i].get("wt1",np.nan))
        wt_prev=float(df15.iloc[i-1].get("wt1",np.nan))
        if np.isnan(wt_now) or np.isnan(wt_prev):continue
        
        d1=df1h[df1h.index<=t]
        if len(d1)<50:continue
        
        # 1h RECENT: последние 3 бара в зоне?
        w1h_vals=[float(d1.iloc[-k].get("wt1",np.nan)) for k in range(1,min(4,len(d1)))]
        w1h_clean=[w for w in w1h_vals if not np.isnan(w)]
        if not w1h_clean:continue
        htf_os=any(w<-60 for w in w1h_clean)
        htf_ob=any(w>60 for w in w1h_clean)
        
        # LONG: 15m кросс ВВЕРХ из OS + 1h RECENT в OS
        if wt_prev < -60 and wt_now > -60 and htf_os:
            tp=price*(1+TARGET_PCT/100); sl=price*0.97
            for j in range(i+1,min(len(df15),i+200)):
                hi=float(df15.iloc[j]["high"]);lo=float(df15.iloc[j]["low"])
                if hi>=tp:
                    trades.append({"net":TARGET_PCT-COST_PCT,"win":True,"dir":"long","ts":t});break
                elif lo<=sl:
                    trades.append({"net":-3.0-COST_PCT,"win":False,"dir":"long","ts":t});break
                elif j==min(len(df15),i+200)-1:
                    lp=float(df15.iloc[j]["close"])
                    trades.append({"net":(lp-price)/price*100-COST_PCT,"win":lp>price,"dir":"long","ts":t})
        
        # SHORT: 15m кросс ВНИЗ из OB + 1h RECENT в OB
        if wt_prev > 60 and wt_now < 60 and htf_ob:
            tp=price*(1-TARGET_PCT/100); sl=price*1.03
            for j in range(i+1,min(len(df15),i+200)):
                hi=float(df15.iloc[j]["high"]);lo=float(df15.iloc[j]["low"])
                if lo<=tp:
                    trades.append({"net":TARGET_PCT-COST_PCT,"win":True,"dir":"short","ts":t});break
                elif hi>=sl:
                    trades.append({"net":-3.0-COST_PCT,"win":False,"dir":"short","ts":t});break
                elif j==min(len(df15),i+200)-1:
                    lp=float(df15.iloc[j]["close"])
                    trades.append({"net":(price-lp)/price*100-COST_PCT,"win":lp<price,"dir":"short","ts":t})
    return trades

# --- Сбор ---
conn=sqlite3.connect(DB);cur=conn.cursor()
all_tr=[]
for s in SYMS:
    f=find_sym(cur,s)
    if not f:continue
    d1h=load(cur,f,"1h",5000);d15=load(cur,f,"15m",12000)
    if d1h is None or d15 is None:continue
    tr=simulate(d1h,d15);all_tr.extend(tr)
    print(f"  {s:5} {len(tr)} тр",flush=True)
conn.close()
print(f"\nВсего: {len(all_tr)} трейдов\n")

for d,label in [("long","LONG (15m cross OS + 1h OS)"),("short","SHORT (15m cross OB + 1h OB)")]:
    ts=[t for t in all_tr if t["dir"]==d]
    if len(ts)<20:print(f"{label}: n={len(ts)} — мало");continue
    nets=[t["net"] for t in ts]
    wr=sum(1 for t in ts if t["win"])/len(ts)*100
    
    # OOS split
    part=sorted(ts,key=lambda x:x["ts"])
    mid=len(part)//2
    is_ns=[t["net"] for t in part[:mid]]
    oos_ns=[t["net"] for t in part[mid:]]
    
    print(f"\n{label}")
    print(f"  ALL n={len(ts):>4} WR={wr:>3.0f}% mean={st.mean(nets):+.3f}% sum={sum(nets):+.1f}%")
    print(f"  IS  n={len(is_ns):>4} WR={sum(1 for t in part[:mid] if t['win'])/len(part[:mid])*100:>3.0f}% mean={st.mean(is_ns):+.3f}%")
    print(f"  OOS n={len(oos_ns):>4} WR={sum(1 for t in part[mid:] if t['win'])/len(part[mid:])*100:>3.0f}% mean={st.mean(oos_ns):+.3f}%")

print(f"\n{'='*50}")
print("ВЕРДИКТ:")
for d in ["long","short"]:
    ts=[t for t in all_tr if t["dir"]==d]
    if not ts:continue
    part=sorted(ts,key=lambda x:x["ts"]);mid=len(part)//2
    oos_ns=[t["net"] for t in part[mid:]]
    oos_m=st.mean(oos_ns) if oos_ns else 0
    print(f"  {d.upper():6} OOS mean={oos_m:+.3f}% {'✅ EDGE' if oos_m>0 else '❌ НЕТ'}")
