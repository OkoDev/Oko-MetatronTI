"""
MTF WT STRATEGY — честный Walk-Forward (IS train / OOS verify)
SHORT: wt1h+15m > threshold → цель 3%, стоп 3%
WF: обучить optimal threshold на IS, проверить на OOS
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
        price=float(df15.iloc[i]["close"])
        t=df15.index[i]
        wt15=float(df15.iloc[i].get("wt1",np.nan))
        d1=df1h[df1h.index<=t]
        if len(d1)<50:continue
        wt1h=float(d1.iloc[-1].get("wt1",np.nan))
        if np.isnan(wt1h) or np.isnan(wt15):continue
        
        dir_=None
        if wt1h<-60 and wt15<-60:dir_="long"
        elif wt1h>60 and wt15>60:dir_="short"
        else:continue
        
        tp=price*(1+TARGET_PCT/100) if dir_=="long" else price*(1-TARGET_PCT/100)
        sl=price*0.97 if dir_=="long" else price*1.03
        
        for j in range(i+1,min(len(df15),i+200)):
            hi=float(df15.iloc[j]["high"]);lo=float(df15.iloc[j]["low"])
            if dir_=="long" and hi>=tp:
                trades.append({"net":TARGET_PCT-COST_PCT,"win":True,"dir":"long","ts":t,"wt1h":wt1h,"wt15":wt15});break
            elif dir_=="short" and lo<=tp:
                trades.append({"net":TARGET_PCT-COST_PCT,"win":True,"dir":"short","ts":t,"wt1h":wt1h,"wt15":wt15});break
            elif (dir_=="long" and lo<=sl) or (dir_=="short" and hi>=sl):
                trades.append({"net":-3.0-COST_PCT,"win":False,"dir":dir_,"ts":t,"wt1h":wt1h,"wt15":wt15});break
            elif j==min(len(df15),i+200)-1:
                lp=float(df15.iloc[j]["close"])
                net=(lp-price)/price*100-COST_PCT if dir_=="long" else (price-lp)/price*100-COST_PCT
                trades.append({"net":net,"win":net>0,"dir":dir_,"ts":t,"wt1h":wt1h,"wt15":wt15})
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
print(f"\nВсего: {len(all_tr)} трейдов")

# --- WALK-FORWARD: SHORT ---
short=[t for t in all_tr if t["dir"]=="short"]
print(f"SHORT: {len(short)}")
if len(short)<100:print("мало");exit()

# Сортируем по времени
short.sort(key=lambda x:x["ts"])
mid=len(short)//2
is_part=short[:mid]
oos_part=short[mid:]

print(f"\n{'='*60}")
print(f"WALK-FORWARD SHORT: IS (train) {len(is_part)} / OOS (verify) {len(oos_part)}")
print(f"{'='*60}")

# Сканируем пороги на IS
print(f"\n{'Training (IS) — поиск оптимального порога:':^60}")
print(f"{'Порог >':>10} {'n':>5} {'mean%':>8} {'sum%':>8} {'WR':>5}")
best_thresh, best_n, best_mean = 0, 0, -99
for th in range(50,86,1):
    ts=[t for t in is_part if t["wt1h"]>th and t["wt15"]>th]
    if len(ts)<5:continue
    ns=[t["net"] for t in ts];m=st.mean(ns)
    if m>best_mean:best_mean=m;best_thresh=th;best_n=len(ts)
    print(f"  wt > {th:>3} n={len(ts):>4} m={m:+.3f}% S={sum(ns):+.1f}% WR={sum(1 for t in ts if t['win'])/len(ts)*100:.0f}%")

print(f"\n>>> ОПТИМАЛЬНЫЙ ПОРОГ (IS): wt1h+15m > {best_thresh} (n={best_n}, mean={best_mean:+.3f}%)")

# Проверка на OOS
oos_ts=[t for t in oos_part if t["wt1h"]>best_thresh and t["wt15"]>best_thresh]
if oos_ts:
    oos_ns=[t["net"] for t in oos_ts]
    oos_wr=sum(1 for t in oos_ts if t["win"])/len(oos_ts)*100
    print(f"OOS (verification): n={len(oos_ts)} WR={oos_wr:.0f}% mean={st.mean(oos_ns):+.3f}% sum={sum(oos_ns):+.1f}%")
    if st.mean(oos_ns)>0:print(">>> WF ПРОЙДЕН! Edge подтверждён.")
    else:print(">>> WF ПРОВАЛЕН. IS edge не воспроизводится на OOS.")
else:print("OOS: n=0 — порог отсекает все сделки")

# Также проверим по всем порогам на OOS
print(f"\n{'Все пороги на OOS (verification):':^60}")
for th in range(60,86,5):
    ts=[t for t in oos_part if t["wt1h"]>th and t["wt15"]>th]
    if len(ts)<5:continue
    ns=[t["net"] for t in ts]
    print(f"  wt > {th:>3} n={len(ts):>4} mean={st.mean(ns):+.3f}% sum={sum(ns):+.1f}%")
