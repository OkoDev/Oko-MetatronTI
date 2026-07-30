# -*- coding: utf-8 -*-
"""GOLDEN REGIME-SWITCH (Егор 30.07) — тренд+rangefade по причинному режиму. Цель: + в ОБА года.
Режим = Efficiency Ratio (Kaufman) causal: |Δclose_n|/Σ|Δclose| — высок=тренд, низк=чоп.
Тренд-режим→континуация с трейлинг-выходом; чоп-режим→rangefade. ATRTrend params тюнибл (Егор)."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.10
def load(sym,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",c,params=(sym,t0)); c.close(); return df
def wt(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    return ((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0).values
def atrt(df,period,factor):
    h,l,c=df.high,df.low,df.close; hl2=(h+l)/2
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean()
    up=(hl2-factor*atr).values; dn=(hl2+factor*atr).values; hv=hl2.values; tu=up.copy(); td=dn.copy(); tr_=np.ones(len(df)); tl=up.copy()
    for i in range(1,len(df)):
        tu[i]=max(up[i],tu[i-1]) if hv[i-1]>tu[i-1] else up[i]; td[i]=min(dn[i],td[i-1]) if hv[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hv[i]>td[i-1] else(-1 if hv[i]<tu[i-1] else tr_[i-1]); tl[i]=tu[i] if tr_[i]>0 else td[i]
    return tr_,tl
def ER(close,n=48):
    c=pd.Series(close); chg=c.diff(n).abs(); vol=c.diff().abs().rolling(n).sum()
    return (chg/vol.replace(0,np.nan)).fillna(0).values

def bt(syms,t0):
    trend=[]; rf=[]  # (year, net%)
    for sym in syms:
        d=load(sym,t0)
        if len(d)<800: continue
        d=d.reset_index(drop=True); C=d.close.values; L=d.low.values; H=d.high.values
        w=wt(d); er=ER(C,48); tr_,tl=atrt(d,10,2.0); at1,_=atrt(d,43,1.25)  # at1=режимный тренд (свой ТФ)
        yr=pd.to_datetime(d.time,unit="ms").dt.year.values; N=len(d)
        i=60
        while i<N-1:
            # ТРЕНД-режим (ER>0.5): вход по тренду ATRTrend на откате (WT<0 и разворот), трейл-выход по tl
            if er[i]>0.5 and tr_[i]>0 and w[i]<0 and w[i]>w[i-1] and C[i]>tl[i]:
                e=C[i]; j=i+1
                while j<N-1 and C[j]>tl[j]: j+=1   # трейл: держим пока close>трейл-линия
                trend.append((int(yr[i]),(C[j]-e)/e*100-COST)); i=j+1; continue
            if er[i]>0.5 and tr_[i]<0 and w[i]>0 and w[i]<w[i-1] and C[i]<tl[i]:
                e=C[i]; j=i+1
                while j<N-1 and C[j]<tl[j]: j+=1
                trend.append((int(yr[i]),(e-C[j])/e*100-COST)); i=j+1; continue
            # ЧОП-режим (ER<0.35): rangefade — at1↑ + WT<-60 → LONG TP1R
            if er[i]<0.35 and at1[i]>0 and w[i]<-60:
                e=C[i]; sl=L[max(0,i-3):i+1].min()*0.997; tp=e+1.0*(e-sl); r=None
                for j in range(i+1,min(i+24,N)):
                    if L[j]<=sl: r=(sl-e)/e*100; break
                    if H[j]>=tp: r=(tp-e)/e*100; break
                if r is None: r=(C[min(i+24,N-1)]-e)/e*100
                rf.append((int(yr[i]),r-COST))
            i+=1
    return trend,rf
def rep(name,rows):
    if len(rows)<15: print(f"  {name:22} n={len(rows)} мало"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10)
    wins=r[r>0]; loss=r[r<=0]; pf=(wins.sum()/abs(loss.sum())) if len(loss) and loss.sum() else 9
    flag="🟢🟢" if(r.sum()>0 and srt[:-cut].sum()>0 and pf>1.1) else("🟡" if r.sum()>0 else "🔴")
    print(f"  {name:22} n={len(r):4} WR{100*(r>0).mean():2.0f}% сум{r.sum():+.0f}% PF{pf:.2f} безтоп10%{srt[:-cut].sum():+.0f}% {flag}")

t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>10000 ORDER BY n DESC LIMIT 70",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · режим=ER48 (тренд>0.5 / чоп<0.35) · тренд:трейл-выход · чоп:rangefade")
trend,rf=bt(syms,t0)
for lbl,rows in [("ТРЕНД все",trend),("  2024",[x for x in trend if x[0]==2024]),("  2025-26",[x for x in trend if x[0]>=2025]),
                 ("RANGEFADE все",rf),("  2024 ",[x for x in rf if x[0]==2024]),("  2025-26 ",[x for x in rf if x[0]>=2025]),
                 ("КОМБО все",trend+rf),("  2024  ",[x for x in trend+rf if x[0]==2024]),("  2025-26  ",[x for x in trend+rf if x[0]>=2025])]:
    rep(lbl,rows)
