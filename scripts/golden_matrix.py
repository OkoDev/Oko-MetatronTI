# -*- coding: utf-8 -*-
"""РАСШИФРОВКА МАТРИЦЫ (Егор скрин OKO Suite): эдж как функция СИЛЫ MTF-выравнивания тренда.
Ключ-гипотеза: чем больше ТФ согласны в тренде + младший WT-экстремум ПРОТИВ = сильнее фейд.
Причинно (HTF closed-bar). Прокурор: медиана+годы+частота. Вход 4h WT<-70(LONG)/>70(SHORT)."""
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
def project(d_from, tr_from, d_to, closed_ms):
    df=d_from.copy(); df["v"]=tr_from; df["time"]=df["time"]+closed_ms
    return pd.merge_asof(d_to[["time"]],df[["time","v"]],on="time",direction="backward")["v"].fillna(0).values
def simTP(i,H,L,C,side,sl,tp,ttl=18):
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
    if len(rows)<20: print(f"  {name:20} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10)
    med=np.median(r); flag="🟢🟢" if(med>0.05 and srt[:-cut].sum()>0) else("🟡" if r.mean()>0 else "🔴")
    print(f"  {name:20} n={len(r):4} WR{100*(r>0).mean():2.0f}% МЕД{med:+.2f}% avg{r.mean():+.2f}% сум{r.sum():+.0f}% безтоп10%{srt[:-cut].sum():+.0f}% {flag}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT 60",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · эдж vs сила MTF-выравнивания (15m/1h/4h тренд) · вход 4h WT<-70/>70")
L={0:[],1:[],2:[],3:[]}; Sh={0:[],1:[],2:[],3:[]}
for sym in syms:
    d15=load(sym,"15m",t0); d1=load(sym,"1h",t0); d4=load(sym,"4h",t0)
    if len(d4)<400 or len(d1)<800 or len(d15)<2000: continue
    d15=d15.reset_index(drop=True); d1=d1.reset_index(drop=True); d4=d4.reset_index(drop=True)
    a15=project(d15,atrt(d15),d4,15*60000); a1=project(d1,atrt(d1),d4,3600000); a4=atrt(d4)
    w4=wt(d4); H=d4.high.values; L4=d4.low.values; C=d4.close.values; yr=pd.to_datetime(d4.time,unit="ms").dt.year.values; N=len(d4)
    for i in range(50,N-1):
        y=int(yr[i])
        up=int(a15[i]>0)+int(a1[i]>0)+int(a4[i]>0)   # сколько ТФ ВВЕРХ (0..3)
        dn=int(a15[i]<0)+int(a1[i]<0)+int(a4[i]<0)
        if a4[i]>0 and w4[i]<-70:  # LONG-фейд, ключ: сколько ТФ согласны ВВЕРХ
            sl=L4[max(0,i-3):i+1].min()*0.997; tp=C[i]+1.0*(C[i]-sl)
            L[up].append((y,simTP(i,H,L4,C,1,sl,tp)))
        if a4[i]<0 and w4[i]>70:   # SHORT-фейд, ключ: сколько ТФ согласны ВНИЗ
            sl=H[max(0,i-3):i+1].max()*1.003; tp=C[i]-1.0*(sl-C[i])
            Sh[dn].append((y,simTP(i,H,L4,C,-1,sl,tp)))
print("\n═══ LONG-фейд по СИЛЕ выравнивания ВВЕРХ (0..3 ТФ) ═══")
for k in (1,2,3): rep(f"выровнено {k}/3↑",L[k])
print("\n═══ SHORT-фейд по СИЛЕ выравнивания ВНИЗ ═══")
for k in (1,2,3): rep(f"выровнено {k}/3↓",Sh[k])
print("\n═══ ЛУЧШИЙ (3/3 выравнивание) по годам ═══")
rep("LONG 3/3↑ 2024",[x for x in L[3] if x[0]==2024]); rep("LONG 3/3↑ 2025-26",[x for x in L[3] if x[0]>=2025])
rep("SHORT 3/3↓ 2024",[x for x in Sh[3] if x[0]==2024]); rep("SHORT 3/3↓ 2025-26",[x for x in Sh[3] if x[0]>=2025])
