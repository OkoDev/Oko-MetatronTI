# -*- coding: utf-8 -*-
"""ЗАГАДКА РЕЖИМА, попытка 2: АВТОКОРРЕЛЯЦИЯ ДОХОДНОСТЕЙ на горизонте сделки.
ADX/ER/Choppiness опровергнуты — они меряют ИЗВИЛИСТОСТЬ ПУТИ. Стратегия же монетизирует
ВОЗВРАТНОСТЬ: если corr(r_t, r_{t+1}) < 0 — рынок откатывает (фейд живёт), > 0 — импульс (фейд мёртв).
Считаем кросс-секционно по 60 монетам, окно 14 дней, горизонт = удержание (6ч = 24 бара 15m).
ПРИЧИННО: окно только из прошлых баров, сдвиг. База: BIG-FLUSH 15m LONG, ликвид, косты 0.25."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
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
def sim(i,H,L,C,sl,ttl=24):
    e=C[i]; tp=e+(e-sl); end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if L[j]<=sl:return(sl-e)/e*100-COST
        if H[j]>=tp:return(tp-e)/e*100-COST
    return (C[end]-e)/e*100-COST
def rep(name,rows,months=29.0):
    if len(rows)<30: print(f"    {name:38} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    y=lambda yy:[x[1] for x in rows if x[0]==yy]; fmt=lambda a: f"{np.median(a):+.2f}" if len(a)>20 else " ?  "
    fr=len(r)/len(coins)/months; pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    ok=med>0.02 and srt[:-cut].sum()>0 and pf>1.05
    print(f"    {name:38} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% PF{pf:.2f} безтоп10%{srt[:-cut].sum():+7.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** | 24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>15000 ORDER BY n DESC LIMIT 60",(t0,)).fetchall()]; c.close()
print("строю кросс-секционную автокорреляцию 6ч-доходностей (окно 14д, causal) ...")
px={}
for s in syms:
    d=load(s,"1h",t0)
    if len(d)>3000: px[s]=pd.Series(d.close.values,index=d.time.values)
panel=pd.DataFrame(px).sort_index()
r6=panel.pct_change(6)                       # 6-часовая доходность (= горизонт удержания)
W=int(14*24)                                 # окно 14 дней в часах
ac=r6.rolling(W).corr(r6.shift(6)).mean(axis=1)   # средняя по монетам автокорреляция r6 c r6-лагом
ac=ac.shift(6)                                    # ПРИЧИННО (лаг горизонта)
idx=pd.to_datetime(ac.index,unit="ms")
by_year={y:ac[(idx.year==y)].median() for y in (2024,2025,2026)}
print(f"  автокорреляция 6ч-доходностей: медиана всего {ac.median():+.4f} · " +
      " · ".join(f"{y}: {v:+.4f}" for y,v in by_year.items()))
q=ac.quantile([0.33,0.67]).values
print(f"  пороги (терцили): {q[0]:+.4f} / {q[1]:+.4f}")
c=sqlite3.connect(DB); syms15=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT 40",(t0,)).fetchall()]; c.close()
turn={};DATA={}
for s in syms15:
    d=load(s,"15m",t0)
    if len(d)>=5000: DATA[s]=d; turn[s]=float(np.nanmedian((d.close*d.volume).values))
mt=np.nanmedian(list(turn.values()))
acdf=pd.DataFrame({"time":ac.index.values,"v":ac.values}).dropna()
R={}
for s,d in DATA.items():
    if turn[s]<mt: continue
    w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values; T=d.time.values
    yr=pd.to_datetime(d.time,unit="ms").dt.year.values
    av=pd.merge_asof(pd.DataFrame({"time":T}),acdf,on="time",direction="backward")["v"].values
    for i in range(60,len(d)-1):
        if not (a[i]>0 and w[i]<-60 and w[i]>w[i-1]): continue
        e=C[i]; sl=L[max(0,i-3):i+1].min()*0.997
        if not (sl<e and (e-sl)/e*100>4.0): continue
        p=sim(i,H,L,C,sl); y=int(yr[i]); R.setdefault("ВСЕ",[]).append((y,p,s))
        if np.isnan(av[i]): continue
        k=("возвратный рынок (AC низкая)" if av[i]<=q[0] else
           ("импульсный рынок (AC высокая)" if av[i]>=q[1] else "середина"))
        R.setdefault(k,[]).append((y,p,s))
print("\n  ═══ BIG-FLUSH LONG × автокорреляция доходностей (causal) ═══")
for k in ("ВСЕ","возвратный рынок (AC низкая)","середина","импульсный рынок (AC высокая)"): rep(k,R.get(k,[]))
