# -*- coding: utf-8 -*-
"""1h WT<-70 + ATRChange (Егор): гаснет ли волатильность = безопасный фейд vs падающий нож.
Бакеты ATRChange на входе. Также 4h. Прокурор: медиана+годы+хрупкость."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
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
def atr_change(df,n=14,lag=8):
    h,l,c=df.high,df.low,df.close
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(n).mean()
    return (atr/atr.shift(lag)-1).fillna(0).values   # >0 расширение, <0 сжатие
def simTP(i,H,L,C,side,sl,tp,ttl=24):
    e=C[i]; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=sl:return(sl-e)/e*100-COST
            if H[j]>=tp:return(tp-e)/e*100-COST
    return side*(C[end]-e)/e*100-COST
def rep(name,rows):
    if len(rows)<15: print(f"  {name:28} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    flag="🟢🟢" if(med>0.05 and srt[:-cut].sum()>0) else("🟡" if r.mean()>0 else "🔴")
    y24=[x[1] for x in rows if x[0]==2024]; y25=[x[1] for x in rows if x[0]>=2025]
    b24="+" if(len(y24)>10 and np.median(y24)>0) else "-"; b25="+" if(len(y25)>10 and np.median(y25)>0) else "-"
    print(f"  {name:28} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% avg{r.mean():+.3f}% безтоп10%{srt[:-cut].sum():+.0f}% 24{b24}/25{b25} {flag}")
def run(tf,syms,t0):
    B={"расшир>0.3":[],"флэт":[],"сжатие<-0.1":[]}
    for sym in syms:
        d=load(sym,tf,t0)
        if len(d)<600: continue
        w=wt(d); a=atrt(d); ac=atr_change(d); H=d.high.values; L=d.low.values; C=d.close.values; yr=pd.to_datetime(d.time,unit="ms").dt.year.values; N=len(d)
        for i in range(60,N-1):
            if not (w[i]<-70 and w[i]>w[i-1]): continue
            y=int(yr[i]); lo=L[max(0,i-4):i+1].min()*0.997
            if lo>=C[i]: continue
            pnl=simTP(i,H,L,C,1,lo,C[i]+1.0*(C[i]-lo))
            k="расшир>0.3" if ac[i]>0.3 else("сжатие<-0.1" if ac[i]<-0.1 else "флэт")
            B[k].append((y,pnl))
    print(f"\n═══ {tf} WT<-70 × ATRChange (lag8) ═══")
    for k in ("расшир>0.3","флэт","сжатие<-0.1"): rep(k,B[k])
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>8000 ORDER BY n DESC LIMIT 55",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)}")
run("1h",syms,t0); run("4h",syms,t0)
