# -*- coding: utf-8 -*-
"""CROSS + ATR-TSL (Егор «cross wt / ATR / TSL внимательнее»): настоящая стрелка WT (wt1×wt2 в зоне)
+ ATR-трейлинг выход (ловит хвост). Сравнить: cross vs level вход; ATR-TSL vs фикс-TP1R."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df
def wtpair(df,n1=10,n2=21,sig=4):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    w1=((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0)
    w2=w1.rolling(sig).mean().fillna(0); return w1.values,w2.values
def atrt(df,period=43,factor=1.25):
    h,l,c=df.high,df.low,df.close; hl2=(h+l)/2
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean()
    up=(hl2-factor*atr).values; dn=(hl2+factor*atr).values; hv=hl2.values; tu=up.copy(); td=dn.copy(); tr_=np.ones(len(df))
    for i in range(1,len(df)):
        tu[i]=max(up[i],tu[i-1]) if hv[i-1]>tu[i-1] else up[i]; td[i]=min(dn[i],td[i-1]) if hv[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hv[i]>td[i-1] else(-1 if hv[i]<tu[i-1] else tr_[i-1])
    return tr_
def ATR(df,p=14):
    h,l,c=df.high,df.low,df.close; tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(p).mean().values
def sim_fixed(i,H,L,C,side,sl,tp,ttl):
    e=C[i]; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=sl:return(sl-e)/e*100-COST
            if H[j]>=tp:return(tp-e)/e*100-COST
        else:
            if H[j]>=sl:return(e-sl)/e*100-COST
            if L[j]<=tp:return(e-tp)/e*100-COST
    return side*(C[end]-e)/e*100-COST
def sim_tsl(i,H,L,C,atr,side,k,ttl):
    e=C[i]; end=min(i+ttl,len(C)-1)
    if side>0:
        stop=e-k*atr[i]
        for j in range(i+1,end+1):
            if L[j]<=stop:return(stop-e)/e*100-COST
            stop=max(stop,C[j]-k*atr[j])   # трейл вверх
        return(C[end]-e)/e*100-COST
    else:
        stop=e+k*atr[i]
        for j in range(i+1,end+1):
            if H[j]>=stop:return(e-stop)/e*100-COST
            stop=min(stop,C[j]+k*atr[j])
        return(e-C[end])/e*100-COST
def rep(name,rows):
    if len(rows)<20: print(f"  {name:34} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10)
    med=np.median(r); flag="🟢🟢" if(med>0.05 and srt[:-cut].sum()>0) else("🟡" if r.mean()>0 else "🔴")
    print(f"  {name:34} n={len(r):4} WR{100*(r>0).mean():2.0f}% МЕД{med:+.2f}% avg{r.mean():+.2f}% сум{r.sum():+.0f}% безтоп10%{srt[:-cut].sum():+.0f}% {flag}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT 60",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · WT-CROSS вход + ATR-TSL выход (4h, косты {COST})")
S={}
def add(k,y,n): S.setdefault(k,[]).append((y,n))
for sym in syms:
    d=load(sym,"4h",t0)
    if len(d)<400: continue
    d=d.reset_index(drop=True); w1,w2=wtpair(d); at=atrt(d); atr=ATR(d); H=d.high.values;L=d.low.values;C=d.close.values
    yr=pd.to_datetime(d.time,unit="ms").dt.year.values; N=len(d)
    for i in range(50,N-1):
        y=int(yr[i])
        crossup = w1[i]>w2[i] and w1[i-1]<=w2[i-1]     # стрелка вверх
        crossdn = w1[i]<w2[i] and w1[i-1]>=w2[i-1]
        # LONG: аптренд + перепродан + CROSS вверх
        if at[i]>0 and w1[i]<-55 and crossup:
            sl=L[max(0,i-3):i+1].min()*0.997; tp=C[i]+1.0*(C[i]-sl)
            add("LONG cross+TPfix",y,sim_fixed(i,H,L,C,1,sl,tp,18))
            add("LONG cross+ATR-TSL2",y,sim_tsl(i,H,L,C,atr,1,2.0,40))
            add("LONG cross+ATR-TSL3",y,sim_tsl(i,H,L,C,atr,1,3.0,40))
        # сравнение: LONG уровень БЕЗ cross (прошлый rangefade4h) + TPfix
        if at[i]>0 and w1[i]<-70:
            sl=L[max(0,i-3):i+1].min()*0.997; tp=C[i]+1.0*(C[i]-sl)
            add("LONG level(no cross)+TPfix",y,sim_fixed(i,H,L,C,1,sl,tp,18))
        # SHORT: даунтренд + перекуплен + CROSS вниз
        if at[i]<0 and w1[i]>55 and crossdn:
            sl=H[max(0,i-3):i+1].max()*1.003; tp=C[i]-1.0*(sl-C[i])
            add("SHORT cross+TPfix",y,sim_fixed(i,H,L,C,-1,sl,tp,18))
            add("SHORT cross+ATR-TSL2",y,sim_tsl(i,H,L,C,atr,-1,2.0,40))
for k in ["LONG cross+TPfix","LONG cross+ATR-TSL2","LONG cross+ATR-TSL3","LONG level(no cross)+TPfix","SHORT cross+TPfix","SHORT cross+ATR-TSL2"]:
    if k in S:
        print(f"\n{k}:"); rep("  ВСЕ",S[k]); rep("  2024",[x for x in S[k] if x[0]==2024]); rep("  2025-26",[x for x in S[k] if x[0]>=2025])
