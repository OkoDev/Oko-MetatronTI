# -*- coding: utf-8 -*-
"""КОМБИНАЦИЯ найденного (05.08): объём-взрыв × сессия × кластер.
Одиночно: объём>4× PF7.10 · ASIA PF5.49 · кластер≥2 PF2.24 · LONDON PF0.45 (ЯД).
Вопрос: независимы ли они, что даёт пересечение, и не убивает ли частоту.
Плюс OOS-контроль по годам и стресс-косты."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")
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
def raw(i,H,L,C,sl,ttl=24):
    e=C[i]; tp=e+(e-sl); end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if L[j]<=sl:return(sl-e)/e*100
        if H[j]>=tp:return(tp-e)/e*100
    return (C[end]-e)/e*100
def rep(name,rows,cost,months=29.0):
    if len(rows)<25: print(f"    {name:40} n={len(rows)}"); return
    r=np.array([x[1] for x in rows])-cost; srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1]-cost for x in rows if x[2]==cn])>0)
    y=lambda yy:[x[1]-cost for x in rows if x[0]==yy]; fmt=lambda a: f"{np.median(a):+.2f}" if len(a)>15 else " ?  "
    fr=len(r)/len(coins)/months
    ok=med>0.02 and srt[:-cut].sum()>0 and pf>1.05
    print(f"    {name:40} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} безтоп10%{srt[:-cut].sum():+7.0f}% "
          f"монет+{pos:2}/{len(coins):2} {fr:5.2f}сд/мес→{fr*med:+6.2f}%/мес 24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT 40",(t0,)).fetchall()]; c.close()
turn={};DATA={}
for s in syms:
    d=load(s,"15m",t0)
    if len(d)>=5000: DATA[s]=d; turn[s]=float(np.nanmedian((d.close*d.volume).values))
mt=np.nanmedian(list(turn.values()))
def sess(ms):
    h=dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).hour
    return "ASIA" if h<8 else ("LONDON" if h<14 else ("NY" if h<21 else "OFF"))
ev=defaultdict(list); recs=[]
for s,d in DATA.items():
    if turn[s]<mt: continue
    w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values; T=d.time.values; V=d.volume.values
    vma=pd.Series(V).rolling(96).mean().values
    yr=pd.to_datetime(d.time,unit="ms").dt.year.values
    for i in range(100,len(d)-1):
        if not (a[i]>0 and w[i]<-60 and w[i]>w[i-1]): continue
        e=C[i]; sl=L[max(0,i-3):i+1].min()*0.997
        if not (sl<e and (e-sl)/e*100>4.0): continue
        vr=V[i]/vma[i] if vma[i]>0 else 1.0
        r=dict(y=int(yr[i]),p=raw(i,H,L,C,sl),sym=s,ts=int(T[i]),vr=vr,ss=sess(T[i]))
        recs.append(r); ev[int(T[i])].append(r)
for r in recs: r["cl"]=len(ev[r["ts"]])
def sel(f): return [(r["y"],r["p"],r["sym"]) for r in recs if f(r)]
for cost in (0.25,0.35):
    print(f"\n{'='*118}\n═══ КОСТЫ {cost}% ═══")
    rep("БАЗА (всё)",sel(lambda r:True),cost)
    print("  ── одиночные фильтры ──")
    rep("объём >4×",sel(lambda r:r["vr"]>4),cost)
    rep("сессия ASIA+OFF",sel(lambda r:r["ss"] in("ASIA","OFF")),cost)
    rep("кластер ≥2",sel(lambda r:r["cl"]>=2),cost)
    print("  ── попарно ──")
    rep("объём>4× + ASIA/OFF",sel(lambda r:r["vr"]>4 and r["ss"] in("ASIA","OFF")),cost)
    rep("объём>4× + кластер≥2",sel(lambda r:r["vr"]>4 and r["cl"]>=2),cost)
    rep("ASIA/OFF + кластер≥2",sel(lambda r:r["ss"] in("ASIA","OFF") and r["cl"]>=2),cost)
    print("  ── ВСЁ ВМЕСТЕ ──")
    rep("объём>4× + ASIA/OFF + кластер≥2",sel(lambda r:r["vr"]>4 and r["ss"] in("ASIA","OFF") and r["cl"]>=2),cost)
    print("  ── мягче: объём>2× ──")
    rep("объём>2× + ASIA/OFF + кластер≥2",sel(lambda r:r["vr"]>2 and r["ss"] in("ASIA","OFF") and r["cl"]>=2),cost)
    rep("объём>2× + ASIA/OFF",sel(lambda r:r["vr"]>2 and r["ss"] in("ASIA","OFF")),cost)
    print("  ── что выбрасываем (яд) ──")
    rep("LONDON/NY (исключаемое)",sel(lambda r:r["ss"] in("LONDON","NY")),cost)
