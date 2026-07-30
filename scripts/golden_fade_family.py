# -*- coding: utf-8 -*-
"""FADE FAMILY (Егор «trendfade живёт где-то») — вариации доказанного rangefade: SHORT-зеркало,
4h-версия, карта параметров. Прокурор: медиана+хрупкость+per-year. Низкий оверфит (вариации эджа)."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.10
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
def sim_multi(i,H,L,C,side,sl,tps,ttl):
    e=C[i]; end=min(i+ttl,len(C)-1); res=[None]*len(tps)
    for j in range(i+1,end+1):
        if side>0 and L[j]<=sl:
            for k in range(len(tps)):
                if res[k] is None: res[k]=(sl-e)/e*100
            break
        if side<0 and H[j]>=sl:
            for k in range(len(tps)):
                if res[k] is None: res[k]=(e-sl)/e*100
            break
        for k,tp in enumerate(tps):
            if res[k] is None:
                if side>0 and H[j]>=tp: res[k]=(tp-e)/e*100
                if side<0 and L[j]<=tp: res[k]=(e-tp)/e*100
        if all(x is not None for x in res): break
    for k in range(len(tps)):
        if res[k] is None: res[k]=side*(C[end]-e)/e*100
    return res
TPRS=[0.8,1.0,1.5]
def rep(name,rows,col):
    if len(rows)<20: print(f"  {name:34} n={len(rows)}"); return
    r=np.array([x[col]-COST-0.05 for x in rows])  # косты 0.15
    srt=np.sort(r); cut=max(1,len(r)//10)
    med=np.median(r); flag="🟢🟢" if(med>0.05 and srt[:-cut].sum()>0) else("🟡" if r.mean()>0 else "🔴")
    print(f"  {name:34} n={len(r):4} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% avg{r.mean():+.3f}% сум{r.sum():+.0f}% безтоп10%{srt[:-cut].sum():+.0f}% {flag}")

t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>10000 ORDER BY n DESC LIMIT 70",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · семейство фейда (косты 0.15) · медиана+хрупкость+годы")
store={}  # key -> list of (year, r08,r10,r15)
def add(k,y,r): store.setdefault(k,[]).append((y,)+tuple(r))
for sym in syms:
    for tf,ttl in (("1h",24),("4h",18)):
        d=load(sym,tf,t0)
        if len(d)<400: continue
        d=d.reset_index(drop=True); w=wt(d); at=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values
        yr=pd.to_datetime(d.time,unit="ms").dt.year.values
        for i in range(50,len(d)-1):
            y=int(yr[i])
            if at[i]>0 and w[i]<-50:  # LONG fade в аптренде
                sl=L[max(0,i-3):i+1].min()*0.997; tps=[C[i]+R*(C[i]-sl) for R in TPRS]
                add(f"{tf}_LONG_wt{int(w[i]//10*10)}",y,sim_multi(i,H,L,C,1,sl,tps,ttl))
            if at[i]<0 and w[i]>50:   # SHORT fade в даунтренде (зеркало)
                sl=H[max(0,i-3):i+1].max()*1.003; tps=[C[i]-R*(sl-C[i]) for R in TPRS]
                add(f"{tf}_SHORT_wt{int(w[i]//10*10)}",y,sim_multi(i,H,L,C,-1,sl,tps,ttl))
# агрегируем по TF/стороне/порогу WT
def bucket(tf,side,thr):
    return [x for k,v in store.items() if k.startswith(f"{tf}_{side}_") for x in v
            if abs(int(k.split('wt')[1]))>=abs(thr)]
for tf in ("1h","4h"):
    for side in ("LONG","SHORT"):
        print(f"\n═══ {tf} {side} (TP1R) ═══")
        for thr in (-50,-60,-70):
            b=bucket(tf,side,thr)
            rep(f"WT<{thr} ВСЕ",b,2)  # col2=r10 (index 2 в (year,r08,r10,r15)->0,1,2,3 → r10=2)
            rep(f"  2024",[x for x in b if x[0]==2024],2); rep(f"  2025-26",[x for x in b if x[0]>=2025],2)
