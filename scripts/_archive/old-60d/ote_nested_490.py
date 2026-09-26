"""
OTE-NESTED EDGE: проверить на 490 символах из ohlcv_cache.db
Стратегия: 4h CHoCH → OTE-зона → 1h слом → вход → TP@1R
"""
import sqlite3, sys, time, statistics as st
from pathlib import Path
import pandas as pd, numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.smc.ote_matrix import structure_trend, build_ote

COST_PCT = 0.2
DB = str(Path(__file__).resolve().parent.parent / "ohlcv_cache.db")

def find_sym(cur, base):
    for p in [f"{base}/USDT", f"binance:{base}/USDT", f"bingx:{base}/USDT:USDT"]:
        if cur.execute("SELECT 1 FROM ohlcv_cache WHERE symbol=? LIMIT 1",(p,)).fetchone(): return p
    return None

def load(c, s, tf, lim=3000):
    c.execute("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time DESC LIMIT ?",(s,tf,lim))
    r=c.fetchall()[::-1]
    if not r: return None
    df=pd.DataFrame(r,columns=["ts","open","high","low","close"])
    df["time"]=pd.to_datetime(df["ts"],unit="ms")
    return df.set_index("time")

def simulate(d4h, d1h):
    """4h CHoCH -> OTE зона -> 1h слом -> вход -> TP@1R"""
    if d4h is None or d1h is None or len(d4h)<100 or len(d1h)<200:
        return []
    trades=[]
    pos=None; last4_len=-1; cache=None
    
    for i in range(200, len(d1h)):
        t=d1h.index[i]; price=float(d1h.iloc[i]["close"])
        hi=float(d1h.iloc[i]["high"]); lo=float(d1h.iloc[i]["low"])
        
        if pos:
            dr=pos["dir"]; ex=None
            if dr=="long" and lo<=pos["sl"]: ex=pos["sl"]
            elif dr=="long" and hi>=pos["tp"]: ex=pos["tp"]
            elif dr=="short" and hi>=pos["sl"]: ex=pos["sl"]
            elif dr=="short" and lo<=pos["tp"]: ex=pos["tp"]
            if ex:
                sign=1 if dr=="long" else -1
                R=(ex-pos["entry"])/(pos["entry"]-pos["sl"])*sign
                net=(ex-pos["entry"])/pos["entry"]*100*sign-COST_PCT
                trades.append({"R":R,"net":net,"win":R>0,"dir":dr,"ts":t});pos=None
        
        # 4h структура
        d4=d4h[d4h.index<=t]
        if len(d4)<60: continue
        if len(d4)!=last4_len:
            try:
                st4=structure_trend(d4, lookback=100); last4_len=len(d4)
                if st4["trend"] and st4.get("break_level") and st4.get("extreme"):
                    ob=build_ote(st4["extreme"], st4["break_level"])
                    cache={"bias":st4["trend"],"lo":ob["ote"][0],"hi":ob["ote"][1],"lv":ob["levels"],"extreme":st4["extreme"],"break":st4["break_level"]}
                else: cache=None
            except: cache=None
        if not cache: continue
        bias,lo_z,hi_z,lv=cache["bias"],cache["lo"],cache["hi"],cache["lv"]
        if not(lo_z<=price<=hi_z): continue
        
        # 1h слом
        d1=d1h[:i+1]
        try: st1=structure_trend(d1, lookback=100)
        except: continue
        brk=st1.get("break_level")
        if not brk: continue
        if bias=="long" and brk<price: sl=brk*0.999
        elif bias=="short" and brk>price: sl=brk*1.001
        else: continue
        
        risk=abs(price-sl)
        if risk<=0 or risk/price*100>10: continue
        tp=price+risk if bias=="long" else price-risk  # TP@1R
        pos={"dir":bias,"entry":price,"sl":sl,"tp":tp,"ts":t}
    return trades

# --- Сканируем все символы ---
conn=sqlite3.connect(DB);cur=conn.cursor()
# Получить все символы
all_syms=[r[0] for r in cur.execute("SELECT DISTINCT symbol FROM ohlcv_cache ORDER BY symbol").fetchall()]
print(f"Всего символов в БД: {len(all_syms)}")

# Уникальные базы
bases=set()
for s in all_syms:
    b=s.replace("binance:","").replace("bingx:","").split("/")[0]
    if b and b!="USDT": bases.add(b)
bases=sorted(bases)
print(f"Уникальных баз: {len(bases)}")

results=[]; total_trades=[]
for base in bases:
    t0=time.time()
    f=find_sym(cur, base)
    if not f: continue
    d4h=load(cur, f, "4h", 2000); d1h=load(cur, f, "1h", 4000)
    if d4h is None or d1h is None: continue
    tr=simulate(d4h,d1h)
    if tr:
        nets=[t["net"] for t in tr]
        Rs=[t["R"] for t in tr]
        wrs=sum(1 for t in tr if t["win"])/len(tr)*100
        results.append((base,len(tr),st.mean(Rs),st.mean(nets),wrs,sum(nets)))
        total_trades.extend(tr)
    dt=time.time()-t0
    if len(results)%20==0:
        print(f"  [{len(results)}/{len(bases)}] {base}: {len(tr)} тр, среднее по R={st.mean([t['R'] for t in tr]):+.3f}" if tr else f"  [{len(results)}/{len(bases)}] {base}: нет тр", flush=True)

conn.close()
print(f"\n{'='*70}")
print(f"ВСЕГО: {len(total_trades)} трейдов на {len(results)} символах")
print(f"{'='*70}")

if not total_trades: print("Нет сделок"); exit()

Rs=[t["R"] for t in total_trades]; nets=[t["net"] for t in total_trades]
wr=sum(1 for t in total_trades if t["win"])/len(total_trades)*100
print(f"ALL {len(total_trades):>5} тр | avgR={st.mean(Rs):+.3f} | WR={wr:.0f}% | net/тр={st.mean(nets):+.3f}% | sumR={sum(Rs):+.1f} | sum$={sum(nets):+.1f}%")

# OOS split
ts=sorted(total_trades,key=lambda x:x["ts"]); mid=len(ts)//2
for l,p in [("IS ",ts[:mid]),("OOS",ts[mid:])]:
    rp=[t["R"] for t in p]; np=[t["net"] for t in p]
    wp=sum(1 for t in p if t["win"])/len(p)*100
    print(f"{l} {len(p):>5} тр | avgR={st.mean(rp):+.3f} | WR={wp:.0f}% | net={st.mean(np):+.3f}% | sumR={sum(rp):+.1f}")

# По направлениям
for d in ["long","short"]:
    ts_d=[t for t in total_trades if t["dir"]==d]
    if not ts_d: continue
    rd=[t["R"] for t in ts_d]; nd=[t["net"] for t in ts_d]
    wd=sum(1 for t in ts_d if t["win"])/len(ts_d)*100
    print(f"{d.upper():5} {len(ts_d):>5} тр | avgR={st.mean(rd):+.3f} | WR={wd:.0f}% | net={st.mean(nd):+.3f}%")

# Топ-символы
tops=sorted(results,key=lambda x:-x[1])[:15]
print(f"\nТОП-15 символов по числу трейдов:")
for base,n,R,net,wr,sum_ in tops:
    print(f"  {base:>6} {n:>4} тр | avgR={R:+.3f} | net={net:+.3f}% | WR={wr:.0f}%")
