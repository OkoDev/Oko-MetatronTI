# -*- coding: utf-8 -*-
"""ATR-TSL ПРАВИЛЬНО (Егор «не отвергаем непроверенное»): на ПОБЕДНОМ входе 4h WT<-70, с АКТИВАЦИЕЙ
(трейл только после +act×ATR), разные k, структурный TSL, ГИБРИД (пол-TP1R+пол-раннер).
Runner=про сумму/хвост → мерю И медиану, И среднее, И сумму, И per-year честно."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df
def wt(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    return ((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0).values
def atrt(df,period=43,factor=1.25):
    h,l,c=df.high,df.low,df.close; hl2=(h+l)/2
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean()
    up=(hl2-factor*atr).values; dn=(hl2+factor*atr).values; hv=hl2.values; tu=up.copy(); td=dn.copy(); tr_=np.ones(len(df))
    for i in range(1,len(df)):
        tu[i]=max(up[i],tu[i-1]) if hv[i-1]>tu[i-1] else up[i]; td[i]=min(dn[i],td[i-1]) if hv[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hv[i]>td[i-1] else(-1 if hv[i]<tu[i-1] else tr_[i-1]); 
    return tr_
def ATR(df,p=14):
    h,l,c=df.high,df.low,df.close; return pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1).rolling(p).mean().values
def e_fixed(i,H,L,C,sl,tp,ttl):
    e=C[i]; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if L[j]<=sl:return(sl-e)/e*100-COST
        if H[j]>=tp:return(tp-e)/e*100-COST
    return(C[end]-e)/e*100-COST
def e_tsl(i,H,L,C,atr,k,act,ttl,init_sl):
    e=C[i]; end=min(i+ttl,len(C)-1); stop=init_sl; activated=False
    for j in range(i+1,end+1):
        if not activated and H[j]>=e+act*atr[i]: activated=True
        if activated: stop=max(stop,C[j]-k*atr[j])
        if L[j]<=stop:return(stop-e)/e*100-COST
    return(C[end]-e)/e*100-COST
def e_hybrid(i,H,L,C,atr,k,act,ttl,sl,tp1):
    """пол-позы на TP1R, пол-позы раннером ATR-TSL."""
    e=C[i]; end=min(i+ttl,len(C)-1); stop=sl; activated=False; half1=None; half2=None
    for j in range(i+1,end+1):
        if half1 is None:
            if L[j]<=sl: half1=(sl-e)/e*100; 
            elif H[j]>=tp1: half1=(tp1-e)/e*100
        if not activated and H[j]>=e+act*atr[i]: activated=True
        if activated: stop=max(stop,C[j]-k*atr[j])
        if half2 is None and L[j]<=stop: half2=(stop-e)/e*100
        if half1 is not None and half2 is not None: break
    if half1 is None: half1=(C[end]-e)/e*100
    if half2 is None: half2=(C[end]-e)/e*100
    return (half1+half2)/2-COST
def rep(name,rows):
    if len(rows)<20: print(f"  {name:24} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10)
    med=np.median(r); flag="🟢🟢" if(med>0.05 and srt[:-cut].sum()>0) else("🟡" if r.mean()>0 else "🔴")
    print(f"  {name:24} n={len(r):4} WR{100*(r>0).mean():2.0f}% МЕД{med:+.2f}% avg{r.mean():+.2f}% сум{r.sum():+.0f}% безтоп10%{srt[:-cut].sum():+.0f}% {flag}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT 60",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · ВХОД 4h WT<-70 (победный) · выходы: TP1R vs ATR-TSL(активация) vs гибрид")
S={}
def add(k,y,n): S.setdefault(k,[]).append((y,n))
for sym in syms:
    d=load(sym,"4h",t0)
    if len(d)<400: continue
    d=d.reset_index(drop=True); w=wt(d); at=atrt(d); atr=ATR(d); H=d.high.values;L=d.low.values;C=d.close.values
    yr=pd.to_datetime(d.time,unit="ms").dt.year.values; N=len(d)
    for i in range(50,N-1):
        if not(at[i]>0 and w[i]<-70): continue
        y=int(yr[i]); sl=L[max(0,i-3):i+1].min()*0.997; tp1=C[i]+1.0*(C[i]-sl)
        add("TP1R (база)",y,e_fixed(i,H,L,C,sl,tp1,18))
        for k in (1.5,2.0,3.0):
            add(f"TSL k{k} act1",y,e_tsl(i,H,L,C,atr,k,1.0,60,sl))
        add("TSL структурный",y,e_fixed(i,H,L,C,sl,C[i]+100*(C[i]-sl),18) if False else e_tsl(i,H,L,C,atr,2.5,0.5,60,sl))
        add("ГИБРИД TP1R+раннер",y,e_hybrid(i,H,L,C,atr,2.5,1.0,60,sl,tp1))
for k in ["TP1R (база)","TSL k1.5 act1","TSL k2.0 act1","TSL k3.0 act1","ГИБРИД TP1R+раннер"]:
    if k in S:
        print(f"\n{k}:"); rep("  ВСЕ",S[k]); rep("  2024",[x for x in S[k] if x[0]==2024]); rep("  2025-26",[x for x in S[k] if x[0]>=2025])
