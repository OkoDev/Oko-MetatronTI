# -*- coding: utf-8 -*-
"""STRESS rangefade_L (эффективно): индикаторы раз/монету, 3 TP за проход, агрегация дёшево."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"
def load(sym,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",c,params=(sym,t0)); c.close(); return df
def wt(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    return ((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0)
def atrt(df,period=43,factor=1.25):
    h,l,c=df.high,df.low,df.close; hl2=(h+l)/2
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean()
    up=(hl2-factor*atr).values; dn=(hl2+factor*atr).values; hv=hl2.values; tu=up.copy(); td=dn.copy(); tr_=np.ones(len(df))
    for i in range(1,len(df)):
        tu[i]=max(up[i],tu[i-1]) if hv[i-1]>tu[i-1] else up[i]; td[i]=min(dn[i],td[i-1]) if hv[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hv[i]>td[i-1] else(-1 if hv[i]<tu[i-1] else tr_[i-1])
    return tr_
TPRS=[0.8,1.0,1.5]
def sim_multi(i,H,L,C,sl,tps,ttl=24):
    e=C[i]; end=min(i+ttl,len(C)-1); res=[None]*len(tps)
    for j in range(i+1,end+1):
        if L[j]<=sl:
            for k in range(len(tps)):
                if res[k] is None: res[k]=(sl-e)/e*100
            break
        for k,tp in enumerate(tps):
            if res[k] is None and H[j]>=tp: res[k]=(tp-e)/e*100
        if all(x is not None for x in res): break
    for k in range(len(tps)):
        if res[k] is None: res[k]=(C[end]-e)/e*100
    return res

t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>10000 ORDER BY n DESC LIMIT 90",(t0,)).fetchall()]; c.close()
rows=[]  # (sym,year,wt, r08,r10,r15)
for sym in syms:
    d=load(sym,t0)
    if len(d)<800: continue
    d=d.reset_index(drop=True); w=wt(d).values; at=atrt(d)
    H=d.high.values; L=d.low.values; C=d.close.values; yr=pd.to_datetime(d.time,unit="ms").dt.year.values
    for i in range(60,len(d)-1):
        if at[i]>0 and w[i]<-50:  # широкий порог, фильтруем потом
            sl=L[i-3:i+1].min()*0.997; e=C[i]
            tps=[e+R*(e-sl) for R in TPRS]
            r=sim_multi(i,H,L,C,sl,tps)
            rows.append((sym,int(yr[i]),float(w[i]),r[0],r[1],r[2]))
print(f"собрано входов (WT<-50, at>0): {len(rows)} на {len(syms)} монетах")
def agg(rs,col,cost):
    r=np.array([x[col]-cost for x in rs])
    if len(r)<20: return f"n={len(r)} мало"
    srt=np.sort(r); frag=srt[:-3].sum()
    return f"n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{np.median(r):+.3f}% avg{r.mean():+.3f}% сум{r.sum():+.0f}% безтоп3{frag:+.0f}%"
C10=3  # индекс r10 в кортеже (r08=3,r10=4,r15=5)
print("\n=== КОСТ-ЧУВСТВИТЕЛЬНОСТЬ (WT<-60, TP1R) ===")
sub=[x for x in rows if x[2]<-60]
for cost in (0.10,0.15,0.20,0.25): print(f"  косты {cost}%: {agg(sub,4,cost)}")
print("\n=== ПО ГОДАМ (WT<-60 TP1R косты0.15) ===")
for y in (2024,2025,2026): print(f"  {y}: {agg([x for x in sub if x[1]==y],4,0.15)}")
print("\n=== ПАРАМ-РОБАСТНОСТЬ (косты0.15) ===")
for thr in (-50,-60,-70):
    s=[x for x in rows if x[2]<thr]
    print(f"  WT<{thr}: TP0.8 {agg(s,3,0.15)[:38]} | TP1.0 {agg(s,4,0.15)[:38]} | TP1.5 {agg(s,5,0.15)[:38]}")
print("\n=== PER-COIN (WT<-60 TP1R косты0.15) ===")
from collections import defaultdict
bc=defaultdict(list)
for x in sub: bc[x[0]].append(x[4]-0.15)
good=[(s,np.median(v),len(v)) for s,v in bc.items() if len(v)>=15]
pos=sum(1 for _,m,_ in good if m>0)
print(f"  монет n≥15: {len(good)} · плюс-медиана: {pos} ({100*pos/max(len(good),1):.0f}%)")
print("  топ-5 монет:", sorted([(s,round(m,2)) for s,m,_ in good],key=lambda x:-x[1])[:5])
