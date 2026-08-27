# -*- coding: utf-8 -*-
"""ЧАСТОТА НА МЛАДШИХ ТФ — честно (Егор: «частота наверняка живёт на меньших тф»).
Гипотеза о причине смерти 15m: не ТФ виноват, а РАЗМЕР сетапа против костов (SL 0.3% и косты 0.15%
= 30-50% цели). Тест: ядро 15m/5m × дистанция стопа в % (бакеты) × узкий/широкий SL × TP 1R/2R.
Прокурор: медиана net%, частота, %/мес, безтоп10%, охват монет, оба года."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
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
    if len(rows)<40: print(f"    {name:30} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    y24=[x[1] for x in rows if x[0]==2024]; y25=[x[1] for x in rows if x[0]>=2025]
    b24=f"{np.median(y24):+.2f}" if len(y24)>20 else " ?  "; b25=f"{np.median(y25):+.2f}" if len(y25)>20 else " ?  "
    fr=len(r)/len(coins)/months
    ok=med>0.02 and srt[:-cut].sum()>0 and (len(y24)<20 or np.median(y24)>0) and (len(y25)<20 or np.median(y25)>0)
    print(f"    {name:30} n={len(r):6} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% безтоп10%{srt[:-cut].sum():+7.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:6.2f}сд/мес → **{fr*med:+.2f}%/мес** | 24:{b24} 25:{b25} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
def bucket(d):
    return "<0.5%" if d<0.5 else("0.5-1%" if d<1 else("1-2%" if d<2 else("2-4%" if d<4 else ">4%")))
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
for tf,ttl_n,ttl_w,minbars,months,lim in (("15m",24,96,40000,29.0,32),("5m",36,144,60000,17.0,28)):
    c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?",(tf,t0,minbars,lim)).fetchall()]; c.close()
    print(f"\n{'='*100}\n{tf}: монет {len(syms)} · ядро ATRTrend↑ + WT<-60 → LONG · костЫ {COST}%")
    NAR={}; WID={}; W2={}
    for sym in syms:
        d=load(sym,tf,t0)
        if len(d)<1000: continue
        w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values
        yr=pd.to_datetime(d.time,unit="ms").dt.year.values; N=len(d)
        for i in range(60,N-1):
            if not (a[i]>0 and w[i]<-60 and w[i]>w[i-1]): continue
            y=int(yr[i]); e=C[i]
            sl_n=L[max(0,i-3):i+1].min()*0.997          # узкий (как раньше)
            sl_w=L[max(0,i-16):i+1].min()*0.997         # широкий (структурный, 16 баров)
            if sl_n<e:
                dn=(e-sl_n)/e*100
                NAR.setdefault(bucket(dn),[]).append((y,sim(i,H,L,C,sl_n,e+(e-sl_n),ttl_n),sym))
            if sl_w<e:
                dw=(e-sl_w)/e*100
                WID.setdefault(bucket(dw),[]).append((y,sim(i,H,L,C,sl_w,e+(e-sl_w),ttl_w),sym))
                W2.setdefault(bucket(dw),[]).append((y,sim(i,H,L,C,sl_w,e+2*(e-sl_w),ttl_w),sym))
    ORD=["<0.5%","0.5-1%","1-2%","2-4%",">4%"]
    print(f"  ── УЗКИЙ SL (3 бара), TP1R, ttl {ttl_n} ──")
    for b in ORD: rep(f"стоп {b}",NAR.get(b,[]),months)
    print(f"  ── ШИРОКИЙ SL (16 баров), TP1R, ttl {ttl_w} ──")
    for b in ORD: rep(f"стоп {b}",WID.get(b,[]),months)
    print(f"  ── ШИРОКИЙ SL, TP2R, ttl {ttl_w} ──")
    for b in ORD: rep(f"стоп {b}",W2.get(b,[]),months)
