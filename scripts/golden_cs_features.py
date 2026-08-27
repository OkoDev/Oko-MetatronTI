# -*- coding: utf-8 -*-
"""КРОСС-СЕКЦИЯ ПО НАШИМ ПРИЗНАКАМ (Егор: «у нас ведь есть все признаки и детекторы»).
Классический CSM по сырой доходности мёртв. Но наш эдж — сам по себе отбор. Вопрос:
когда НЕСКОЛЬКО монет дают BIG-FLUSH ОДНОВРЕМЕННО, помогает ли брать САМЫЕ экстремальные?
Меряем: внутри каждой временной метки ранжируем сработавшие монеты по каждому фактору
(глубина WT / размер стопа / funding / комбо) и сравниваем ранг-1 против остальных.
Это и есть кросс-секционный отбор на наших детекторах, а не на доходности."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.25
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close,volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
def fund(sym,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,rate FROM funding_rates WHERE symbol=? AND time>=? ORDER BY time",c,params=(sym,t0)); c.close(); return df.reset_index(drop=True)
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
def sim(i,H,L,C,sl,ttl=24):
    e=C[i]; tp=e+(e-sl); end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if L[j]<=sl:return(sl-e)/e*100-COST
        if H[j]>=tp:return(tp-e)/e*100-COST
    return (C[end]-e)/e*100-COST
def rep(name,vals):
    if len(vals)<30: print(f"    {name:40} n={len(vals)}"); return
    r=np.array(vals); srt=np.sort(r); cut=max(1,len(r)//10)
    pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    ok=np.median(r)>0.02 and srt[:-cut].sum()>0 and pf>1.05
    print(f"    {name:40} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{np.median(r):+.3f}% ср{r.mean():+.3f}% "
          f"PF{pf:.2f} безтоп10%{srt[:-cut].sum():+7.0f}% {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT 40",(t0,)).fetchall()]; c.close()
turn={};DATA={}
for s in syms:
    d=load(s,"15m",t0)
    if len(d)>=5000: DATA[s]=d; turn[s]=float(np.nanmedian((d.close*d.volume).values))
mt=np.nanmedian(list(turn.values()))
events=defaultdict(list)   # время → [(sym, pnl, wt, stop_pct, fund_pct), ...]
for s,d in DATA.items():
    if turn[s]<mt: continue
    fr=fund(s,t0); fpct=None
    if len(fr)>100:
        fr["pct"]=fr["rate"].expanding(min_periods=50).rank(pct=True)
    w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values; T=d.time.values
    fj=pd.merge_asof(pd.DataFrame({"time":T}),fr[["time","pct"]],on="time",direction="backward")["pct"].values if len(fr)>100 else np.full(len(T),np.nan)
    for i in range(60,len(d)-1):
        if not (a[i]>0 and w[i]<-60 and w[i]>w[i-1]): continue
        e=C[i]; sl=L[max(0,i-3):i+1].min()*0.997
        if not (sl<e and (e-sl)/e*100>4.0): continue
        events[int(T[i])].append((s,sim(i,H,L,C,sl),float(w[i]),(e-sl)/e*100,float(fj[i]) if not np.isnan(fj[i]) else 0.5))
sizes=[len(v) for v in events.values()]
print(f"временных меток с сигналом: {len(events)} · одиночных: {sum(1 for x in sizes if x==1)} · "
      f"кластеров ≥2: {sum(1 for x in sizes if x>=2)} · макс одновременно: {max(sizes)}")
print(f"всего сигналов: {sum(sizes)} · доля в кластерах: {100*sum(x for x in sizes if x>=2)/sum(sizes):.0f}%\n")
BASE=[]; R={}
for ts,ev in events.items():
    for x in ev: BASE.append(x[1])
    if len(ev)<2: continue
    for tag,key,rev in (("глубина WT (самый OS)",2,False),("размер стопа (самый крупный)",3,True),
                        ("funding (самый низкий)",4,False)):
        srt=sorted(ev,key=lambda x:x[key],reverse=rev)
        R.setdefault(f"ранг-1 по: {tag}",[]).append(srt[0][1])
        for x in srt[1:]: R.setdefault(f"остальные: {tag}",[]).append(x[1])
    # комбо-скор: чем глубже WT, крупнее стоп и ниже funding — тем выше
    sc=sorted(ev,key=lambda x:(-x[2])+x[3]*10+(1-x[4])*20,reverse=True)
    R.setdefault("ранг-1 по: КОМБО-СКОР",[]).append(sc[0][1])
    for x in sc[1:]: R.setdefault("остальные: КОМБО-СКОР",[]).append(x[1])
print("  ═══ БАЗА: все сигналы (текущее правило — брать всех прошедших порог) ═══")
rep("все сигналы",BASE)
print("\n  ═══ КРОСС-СЕКЦИЯ: внутри кластера берём ЛУЧШУЮ монету ═══")
for tag in ("глубина WT (самый OS)","размер стопа (самый крупный)","funding (самый низкий)","КОМБО-СКОР"):
    rep(f"ранг-1 по: {tag}",R.get(f"ранг-1 по: {tag}",[]))
    rep(f"остальные: {tag}",R.get(f"остальные: {tag}",[]))
    print()

# ── КОНТРОЛЬ: разделяем одиночные сигналы, ранг-1 и остальных (иначе confound)
SINGLE=[]; RANK1=[]; REST=[]; CLUST=[]
for ts,ev in events.items():
    if len(ev)==1: SINGLE.append(ev[0][1]); continue
    sc=sorted(ev,key=lambda x:(-x[2])+x[3]*10+(1-x[4])*20,reverse=True)
    RANK1.append(sc[0][1]); REST.extend(x[1] for x in sc[1:]); CLUST.extend(x[1] for x in ev)
print("\n  ═══ КОНТРОЛЬ: откуда берётся улучшение? ═══")
rep("одиночные сигналы",SINGLE)
rep("кластеры целиком",CLUST)
rep("кластеры БЕЗ ранга-1 (комбо)",REST)
rep("только ранг-1 (комбо)",RANK1)
rep("ВСЁ кроме ранга-1 (одиночные+остальные)",SINGLE+REST)
import numpy as _np
b=_np.array(BASE); nr=_np.array(SINGLE+REST)
print(f"\n  Δ от исключения ранга-1: медиана {_np.median(nr)-_np.median(b):+.3f}% · "
      f"сделок {len(nr)} против {len(b)} (теряем {100*(1-len(nr)/len(b)):.0f}%)")
