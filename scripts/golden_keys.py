# -*- coding: utf-8 -*-
"""КЛЮЧИ от 1h WT<-70 (Егор 30.07): база → +выравнивание → +ДИВЕРГЕНЦИЯ → +CHOP-режим (DeepSeek).
Вклад КАЖДОГО ключа отдельно. Причинно, прокурор (медиана+годы+хрупкость+частота)."""
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
def chop(df,n=14):
    h,l,c=df.high,df.low,df.close
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    trn=tr.rolling(n).sum(); rng=h.rolling(n).max()-l.rolling(n).min()
    return (100*np.log10((trn/rng.replace(0,np.nan)))/np.log10(n)).fillna(50).values
def project(d_from,v_from,d_to,closed_ms):
    df=d_from.copy(); df["v"]=v_from; df["time"]=df["time"]+closed_ms
    return pd.merge_asof(d_to[["time"]],df[["time","v"]],on="time",direction="backward")["v"].fillna(0).values
def bull_div(w,c,i,win=40):
    """Бычья дивергенция на глубоком OS: цена LL, WT HL относительно предыдущего WT-дна."""
    lo=max(1,i-win); prev=None
    for k in range(i-2,lo,-1):
        if w[k]<-55 and w[k]<w[k-1] and w[k]<w[k+1]:  # локальный WT-минимум
            prev=k; break
    if prev is None: return False
    return c[i]<=c[prev]*1.002 and w[i]>w[prev]+2  # цена не выше, WT выше = ослабление импульса
def simTP(i,H,L,C,side,sl,tp,ttl=24):
    e=C[i]; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=sl:return(sl-e)/e*100-COST
            if H[j]>=tp:return(tp-e)/e*100-COST
        else:
            if H[j]>=sl:return(e-sl)/e*100-COST
            if L[j]<=tp:return(e-tp)/e*100-COST
    return side*(C[end]-e)/e*100-COST
def rep(name,rows):
    if len(rows)<20: print(f"  {name:26} n={len(rows)}"); return
    r=np.array(rows); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    flag="🟢🟢" if(med>0.05 and srt[:-cut].sum()>0) else("🟡" if r.mean()>0 else "🔴")
    print(f"  {name:26} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% avg{r.mean():+.3f}% сум{r.sum():+.0f}% безтоп10%{srt[:-cut].sum():+.0f}% {flag}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>10000 ORDER BY n DESC LIMIT 55",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · вход 1h WT<-70 (реакция вверх) · ключи аддитивно\n")
BASE=[];AL=[];DV=[];ALDV=[];CH=[];CH_TR=[]
for sym in syms:
    d15=load(sym,"15m",t0); d1=load(sym,"1h",t0); d4=load(sym,"4h",t0)
    if len(d1)<3000 or len(d4)<400 or len(d15)<8000: continue
    w=wt(d1); a1=atrt(d1); ch1=chop(d1); H=d1.high.values; L=d1.low.values; C=d1.close.values; yr=pd.to_datetime(d1.time,unit="ms").dt.year.values; N=len(d1)
    a4=project(d4,atrt(d4),d1,4*3600000); a15=project(d15,atrt(d15),d1,15*60000)
    for i in range(60,N-1):
        if not (w[i]<-70 and w[i]>w[i-1]): continue   # глубокий OS + реакция вверх
        y=int(yr[i]); lo=L[max(0,i-4):i+1].min()*0.997
        if lo>=C[i]: continue
        tp=C[i]+1.0*(C[i]-lo); pnl=simTP(i,H,L,C,1,lo,tp)
        align=(a15[i]>0)+(a1[i]>0)+(a4[i]>0)  # 0..3
        div=bull_div(w,C,i); ch=ch1[i]
        BASE.append(pnl)
        if align>=2: AL.append(pnl)
        if div: DV.append(pnl)
        if align>=2 and div: ALDV.append(pnl)
        if ch>=58: CH.append(pnl)         # чоп-режим (DeepSeek: rangefade зона)
        if ch<42: CH_TR.append(pnl)       # трендовый режим
print("═══ ВКЛАД КЛЮЧЕЙ (1h WT<-70 LONG TP1R) ═══")
rep("база WT<-70",BASE); rep("+выравнивание≥2/3↑",AL); rep("+ДИВЕРГЕНЦИЯ",DV); rep("+выравн+дивер",ALDV)
rep("+CHOP≥58 (чоп)",CH); rep("+CHOP<42 (тренд)",CH_TR)
print("\n═══ ЛУЧШИЙ КЛЮЧ по годам ═══")
# определим лучший по медиане из непустых
cands={"выравн+дивер":ALDV,"дивергенция":DV,"выравн≥2":AL,"CHOP≥58":CH}
best=max((k for k in cands if len(cands[k])>=40), key=lambda k:np.median(cands[k]), default=None)
if best:
    print(f"лучший ключ: {best}")
