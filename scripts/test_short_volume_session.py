# -*- coding: utf-8 -*-
"""БЛОК 2 (карта #29, #1, #21): за один проход по свечам —
  A) SHORT big-flush + КЛАСТЕР-ГЕЙТ (шорт мёртв PF0.72, но кластер переворачивал LONG — проверяем зеркало)
  B) ОБЪЁМ как сигнал (ни разу не тестировался как сигнал, только как оборот)
  C) СЕССИИ для нашего фейда (для radar смотрел, для big-flush ноль)
Причинно, ликвидная половина, косты 0.25."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.25
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
def sim(i,side,H,L,C,sl,ttl=24):
    e=C[i]; tp=e+side*abs(e-sl); end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=sl:return(sl-e)/e*100-COST
            if H[j]>=tp:return(tp-e)/e*100-COST
        else:
            if H[j]>=sl:return(e-sl)/e*100-COST
            if L[j]<=tp:return(e-tp)/e*100-COST
    return side*(C[end]-e)/e*100-COST
def rep(name,rows):
    if len(rows)<25: print(f"    {name:36} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    coins=set(x[2] for x in rows); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    ok=med>0.02 and srt[:-cut].sum()>0 and pf>1.05
    print(f"    {name:36} n={len(r):5} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:.2f} безтоп10%{srt[:-cut].sum():+8.0f}% монет+{pos:2}/{len(coins):2} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT 40",(t0,)).fetchall()]; c.close()
turn={};DATA={}
for s in syms:
    d=load(s,"15m",t0)
    if len(d)>=5000: DATA[s]=d; turn[s]=float(np.nanmedian((d.close*d.volume).values))
mt=np.nanmedian(list(turn.values()))
print(f"монет {len(DATA)}, ликвидных {sum(1 for s in DATA if turn[s]>=mt)}\n")
evL=defaultdict(list); evS=defaultdict(list)   # время → сигналы (для кластера)
VOL=defaultdict(list); SESS=defaultdict(list); SESS_S=defaultdict(list)
def sess(ms):
    h=dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).hour
    return "ASIA 00-08" if h<8 else ("LONDON 08-14" if h<14 else ("NY 14-21" if h<21 else "OFF 21-24"))
for s,d in DATA.items():
    if turn[s]<mt: continue
    w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values; T=d.time.values; V=d.volume.values
    vma=pd.Series(V).rolling(96).mean().values     # средний объём за сутки (96×15m)
    for i in range(100,len(d)-1):
        vr=V[i]/vma[i] if vma[i]>0 else 1.0
        if a[i]>0 and w[i]<-60 and w[i]>w[i-1]:
            e=C[i]; sl=L[max(0,i-3):i+1].min()*0.997
            if sl<e and (e-sl)/e*100>4.0:
                p=sim(i,1,H,L,C,sl); rec=(0,p,s)
                evL[int(T[i])].append(rec)
                VOL[("объём <1×" if vr<1 else ("1-2×" if vr<2 else ("2-4×" if vr<4 else ">4× (взрыв)")))].append(rec)
                SESS[sess(T[i])].append(rec)
        if a[i]<0 and w[i]>60 and w[i]<w[i-1]:
            e=C[i]; sl=H[max(0,i-3):i+1].max()*1.003
            if sl>e and (sl-e)/e*100>4.0:
                p=sim(i,-1,H,L,C,sl); rec=(0,p,s)
                evS[int(T[i])].append(rec); SESS_S[sess(T[i])].append(rec)
def flat(ev,f): 
    out=[]
    for ts,lst in ev.items():
        if f(len(lst)): out.extend(lst)
    return out
print("═══ A) SHORT big-flush × КЛАСТЕР-ГЕЙТ (зеркало главной находки) ═══")
rep("SHORT всё",flat(evS,lambda n:True))
rep("SHORT одиночный (идиосинкразия)",flat(evS,lambda n:n==1))
rep("SHORT кластер ≥2",flat(evS,lambda n:n>=2))
rep("SHORT кластер ≥4 (залив)",flat(evS,lambda n:n>=4))
print("\n  ── контроль: LONG теми же ведрами ──")
rep("LONG всё",flat(evL,lambda n:True))
rep("LONG одиночный",flat(evL,lambda n:n==1))
rep("LONG кластер ≥2",flat(evL,lambda n:n>=2))
print("\n═══ B) ОБЪЁМ как сигнал (впервые) ═══")
for k in ("объём <1×","1-2×","2-4×",">4× (взрыв)"): rep(k,VOL.get(k,[]))
print("\n═══ C) СЕССИИ для LONG-фейда (впервые) ═══")
for k in ("ASIA 00-08","LONDON 08-14","NY 14-21","OFF 21-24"): rep(k,SESS.get(k,[]))
print("\n  ── сессии для SHORT ──")
for k in ("ASIA 00-08","LONDON 08-14","NY 14-21","OFF 21-24"): rep(k,SESS_S.get(k,[]))
