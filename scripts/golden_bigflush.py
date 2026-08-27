# -*- coding: utf-8 -*-
"""BIG-FLUSH (30.07, Егор «частота живёт на меньших ТФ» — ПОДТВЕРЖДЕНО в форме РАЗМЕРА сетапа).
15m/5m ядро ATRTrend↑+WT<-60 + СТОП>4% (косты становятся 3% цели вместо 30%).
Решающая проверка: ликвидная vs неликвидная половина + срез 2026 (где 4h-ядро проваливалось)."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
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
def sim(i,H,L,C,sl,tp,ttl):
    e=C[i]; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if L[j]<=sl:return(sl-e)/e*100-COST
        if H[j]>=tp:return(tp-e)/e*100-COST
    return (C[end]-e)/e*100-COST
def rep(name,rows,months):
    if len(rows)<30: print(f"  {name:32} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    fr=len(r)/len(coins)/months
    ok=med>0.02 and srt[:-cut].sum()>0
    print(f"  {name:32} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% безтоп10%{srt[:-cut].sum():+7.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
for tf,ttl,minbars,lim in (("15m",24,40000,40),("5m",36,60000,32)):
    c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?",(tf,t0,minbars,lim)).fetchall()]; c.close()
    turn={}; DATA={}
    for s in syms:
        d=load(s,tf,t0)
        if len(d)<1000: continue
        DATA[s]=d; turn[s]=float(np.nanmedian((d.close*d.volume).values))
    mt=np.nanmedian(list(turn.values()))
    print(f"\n{'='*94}\n{tf} BIG-FLUSH (стоп>4%): монет {len(DATA)} · медианный оборот {mt:,.0f}")
    ALL=[];LIQ=[];ILL=[];Y={}
    for s,d in DATA.items():
        w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values
        yr=pd.to_datetime(d.time,unit="ms").dt.year.values
        for i in range(60,len(d)-1):
            if not (a[i]>0 and w[i]<-60 and w[i]>w[i-1]): continue
            e=C[i]; sl=L[max(0,i-3):i+1].min()*0.997
            if not (sl<e and (e-sl)/e*100>4.0): continue     # ТОЛЬКО крупный сетап
            p=sim(i,H,L,C,sl,e+(e-sl),ttl); y=int(yr[i]); rec=(y,p,s)
            ALL.append(rec); (LIQ if turn[s]>=mt else ILL).append(rec); Y.setdefault(y,[]).append(rec)
    M=29.0 if tf=="15m" else 17.0
    rep("ВСЕ",ALL,M); rep("ЛИКВИДНАЯ половина",LIQ,M/1); rep("неликвидная половина",ILL,M)
    print("  ── по годам ──")
    for y in sorted(Y): rep(f"{y}",Y[y],12.0 if y<2026 else 5.0)
