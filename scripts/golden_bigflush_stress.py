# -*- coding: utf-8 -*-
"""СТРЕСС BIG-FLUSH: (1) косты 0.15/0.25/0.35 (флеш=широкий спред!) (2) порог стопа 3/4/5/6% —
не «нож» ли 4%. Только ЛИКВИДНАЯ половина (то, что реально торгуем). 15m + 5m."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close,volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
def wt(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    return ((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0).values
def atrt(df,period=43,factor=1.25):
    h,l,c=df.high,df.low,df.close; hl2=((h+l)/2).values
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean().values
    up=hl2-factor*atr; dn=hl2+factor*atr; tu=up.copy(); td=dn.copy(); tr_=np.ones(len(hl2))
    for i in range(1,len(hl2)):
        tu[i]=max(up[i],tu[i-1]) if hl2[i-1]>tu[i-1] else up[i]; td[i]=min(dn[i],td[i-1]) if hl2[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hl2[i]>td[i-1] else(-1 if hl2[i]<tu[i-1] else tr_[i-1])
    return tr_
def raw(i,H,L,C,sl,tp,ttl):
    e=C[i]; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if L[j]<=sl:return(sl-e)/e*100
        if H[j]>=tp:return(tp-e)/e*100
    return (C[end]-e)/e*100
def rep(name,rows,months,cost):
    if len(rows)<30: print(f"    {name:26} n={len(rows)}"); return
    r=np.array([x[1] for x in rows])-cost; srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1]-cost for x in rows if x[2]==cn])>0)
    y=lambda yy:[x[1]-cost for x in rows if x[0]==yy]
    y25=y(2025); y26=y(2026)
    b25=f"{np.median(y25):+.2f}" if len(y25)>20 else " ?  "; b26=f"{np.median(y26):+.2f}" if len(y26)>20 else " ?  "
    fr=len(r)/len(coins)/months; ok=med>0.02 and srt[:-cut].sum()>0
    print(f"    {name:26} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% безтоп10%{srt[:-cut].sum():+7.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** | 25:{b25} 26:{b26} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
for tf,ttl,minbars,lim,M in (("15m",24,40000,40,29.0),("5m",36,60000,32,17.0)):
    c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?",(tf,t0,minbars,lim)).fetchall()]; c.close()
    turn={};DATA={}
    for s in syms:
        d=load(s,tf,t0)
        if len(d)>=1000: DATA[s]=d; turn[s]=float(np.nanmedian((d.close*d.volume).values))
    mt=np.nanmedian(list(turn.values()))
    BY={}   # порог → строки (RAW pnl, косты вычтем потом)
    for s,d in DATA.items():
        if turn[s]<mt: continue      # ТОЛЬКО ликвидная половина
        w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values
        yr=pd.to_datetime(d.time,unit="ms").dt.year.values
        for i in range(60,len(d)-1):
            if not (a[i]>0 and w[i]<-60 and w[i]>w[i-1]): continue
            e=C[i]; sl=L[max(0,i-3):i+1].min()*0.997
            if sl>=e: continue
            dist=(e-sl)/e*100
            p=raw(i,H,L,C,sl,e+(e-sl),ttl); rec=(int(yr[i]),p,s)
            for thr in (3,4,5,6):
                if dist>thr: BY.setdefault(thr,[]).append(rec)
    print(f"\n{'='*98}\n{tf} BIG-FLUSH, ЛИКВИДНАЯ половина ({sum(1 for s in DATA if turn[s]>=mt)} монет)")
    for cost in (0.15,0.25,0.35):
        print(f"  ── косты {cost}% ──")
        for thr in (3,4,5,6): rep(f"стоп>{thr}%",BY.get(thr,[]),M,cost)
