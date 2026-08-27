# -*- coding: utf-8 -*-
"""FADE: SHORT-родственники (регим-условные) + MTF ранние подтверждения (WT-разворот/LTF CHoCH).
Егор «ищи short и ранние подтверждения во MTF матрицах/SMC». Прокурор: медиана+хрупкость+годы."""
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
        tr_[i]=1 if hv[i]>td[i-1] else(-1 if hv[i]<tu[i-1] else tr_[i-1])
    return tr_
def choch(df,k=4):  # causal 1h CHoCH direction на каждый бар (последний слом)
    H=df.high.values;L=df.low.values;C=df.close.values;n=len(df); ch=np.zeros(n,int); csh=csl=None;t=0
    for i in range(n):
        j=i-k
        if j>=k:
            if H[j]==H[j-k:j+k+1].max(): csh=H[j]
            if L[j]==L[j-k:j+k+1].min(): csl=L[j]
        if csh is not None and C[i]>csh: t=1
        elif csl is not None and C[i]<csl: t=-1
        ch[i]=t
    return ch
def simTP(i,H,L,C,side,sl,tp,ttl):
    e=C[i]; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=sl: return (sl-e)/e*100-COST
            if H[j]>=tp: return (tp-e)/e*100-COST
        else:
            if H[j]>=sl: return (e-sl)/e*100-COST
            if L[j]<=tp: return (e-tp)/e*100-COST
    return side*(C[end]-e)/e*100-COST
def rep(name,rows):
    if len(rows)<20: print(f"  {name:32} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10)
    med=np.median(r); flag="🟢🟢" if(med>0.05 and srt[:-cut].sum()>0) else("🟡" if r.mean()>0 else "🔴")
    print(f"  {name:32} n={len(r):4} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% avg{r.mean():+.3f}% сум{r.sum():+.0f}% безтоп10%{srt[:-cut].sum():+.0f}% {flag}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT 60",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · SHORT-родня + MTF ранние подтверждения (косты {COST})")
S={}  # key->[(year,net)]
def add(k,y,n): S.setdefault(k,[]).append((y,n))
for sym in syms:
    d4=load(sym,"4h",t0); d1=load(sym,"1h",t0)
    if len(d4)<400 or len(d1)<800: continue
    d4=d4.reset_index(drop=True); d1=d1.reset_index(drop=True)
    w4=wt(d4); at4=atrt(d4); H=d4.high.values; L=d4.low.values; C=d4.close.values
    ema200=pd.Series(C).ewm(span=200).mean().values
    ch1=choch(d1,4); m=pd.merge_asof(d4[["time"]],d1.assign(ch1=ch1)[["time","ch1"]],on="time",direction="backward"); ch1_4=m["ch1"].fillna(0).values
    yr=pd.to_datetime(d4.time,unit="ms").dt.year.values; N=len(d4)
    for i in range(50,N-1):
        y=int(yr[i])
        # SHORT-родня: 4h WT>70 + ATRTrend вниз
        if at4[i]<0 and w4[i]>70:
            sl=H[max(0,i-3):i+1].max()*1.003; tp=C[i]-1.0*(sl-C[i]); r=simTP(i,H,L,C,-1,sl,tp,18)
            add("SHORT baseWT70",y,r)
            if C[i]<ema200[i]: add("SHORT +ниже200EMA",y,r)          # down-режим
            if w4[i]>78: add("SHORT глубже WT78",y,r)
            if ch1_4[i]<0: add("SHORT +1h CHoCH↓ (ранн подтв)",y,r)  # LTF структура подтверждает
        # LONG база (сиблинг) + ранние подтверждения
        if at4[i]>0 and w4[i]<-70:
            sl=L[max(0,i-3):i+1].min()*0.997; tp=C[i]+1.0*(C[i]-sl); r=simTP(i,H,L,C,1,sl,tp,18)
            add("LONG base(4h WT-70)",y,r)
            if w4[i]>w4[i-1]: add("LONG +WT разворот↑",y,r)          # ранний: отскок начался
            if ch1_4[i]>0: add("LONG +1h CHoCH↑ (ранн подтв)",y,r)   # LTF структура вверх
            if w4[i]>w4[i-1] and ch1_4[i]>0: add("LONG +WT↑ И 1h CHoCH↑",y,r)
for k in ["SHORT baseWT70","SHORT +ниже200EMA","SHORT глубже WT78","SHORT +1h CHoCH↓ (ранн подтв)",
          "LONG base(4h WT-70)","LONG +WT разворот↑","LONG +1h CHoCH↑ (ранн подтв)","LONG +WT↑ И 1h CHoCH↑"]:
    if k in S:
        print(f"\n{k}:"); rep("  ВСЕ",S[k]); rep("  2024",[x for x in S[k] if x[0]==2024]); rep("  2025-26",[x for x in S[k] if x[0]>=2025])
