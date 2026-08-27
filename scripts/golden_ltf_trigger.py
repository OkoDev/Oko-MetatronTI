# -*- coding: utf-8 -*-
"""РАННЕЕ ПОДТВЕРЖДЕНИЕ (Егор: «ранние подтверждения для входа во MTF матрицам»).
4h-зона (ATRTrend↑ + WT<-60) = ВЗВЕДЁННОЕ ОКНО. Вход НЕ по закрытию 4h, а по 1h WT-кроссу внутри окна.
Бьёт в 2 цели: ЧАСТОТА (несколько триггеров на зону) + КАЧЕСТВО ВХОДА (корень «вход съедает эдж»).
SL: структурный 4h-лоу (по ЗАКОНУ) vs тугой 1h-лоу. Причинно. Прокурор полный."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
def wt2(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    w1=((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0)
    return w1.values, w1.rolling(4).mean().fillna(0).values      # wt1, wt2(sma4)
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
def rep(name,rows,months=29.0):
    if len(rows)<25: print(f"  {name:34} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    y24=[x[1] for x in rows if x[0]==2024]; y25=[x[1] for x in rows if x[0]>=2025]
    b24=f"{np.median(y24):+.2f}" if len(y24)>15 else " ?  "; b25=f"{np.median(y25):+.2f}" if len(y25)>15 else " ?  "
    fr=len(r)/len(coins)/months
    ok=med>0.02 and srt[:-cut].sum()>0 and (len(y24)<15 or np.median(y24)>0) and (len(y25)<15 or np.median(y25)>0)
    print(f"  {name:34} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% безтоп10%{srt[:-cut].sum():+6.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:4.2f}сд/мес → **{fr*med:+.2f}%/мес** | 24:{b24} 25:{b25} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>15000 ORDER BY n DESC LIMIT 50",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · 4h-зона взводит окно 24ч → вход по 1h WT-кроссу внутри окна\n")
BASE=[];LTF_S=[];LTF_T=[];LTF_FIRST=[]
for sym in syms:
    d4=load(sym,"4h",t0); d1=load(sym,"1h",t0)
    if len(d4)<400 or len(d1)<2000: continue
    w4,_=wt2(d4); a4=atrt(d4); H4=d4.high.values; L4=d4.low.values; C4=d4.close.values
    w1,w1s=wt2(d1); H1=d1.high.values; L1=d1.low.values; C1=d1.close.values
    t4=d4.time.values; t1=d1.time.values; yr4=pd.to_datetime(d4.time,unit="ms").dt.year.values
    for i in range(60,len(d4)-1):
        if not (a4[i]>0 and w4[i]<-60 and w4[i]>w4[i-1]): continue
        y=int(yr4[i]); sl4=L4[max(0,i-3):i+1].min()*0.997
        # эталон: вход по закрытию 4h
        if sl4<C4[i]: BASE.append((y,sim(i,H4,L4,C4,sl4,C4[i]+(C4[i]-sl4),18),sym))
        # окно 24ч на 1h: ищем WT-кроссы вверх (wt1 пересёк wt2)
        j0=int(np.searchsorted(t1,t4[i]+3600000)); j1=int(np.searchsorted(t1,t4[i]+24*3600000))
        first=True
        for j in range(max(j0,5),min(j1,len(d1)-1)):
            if not (w1[j]>w1s[j] and w1[j-1]<=w1s[j-1]): continue     # кросс вверх на 1h
            e=C1[j]
            if sl4<e:      # структурный SL (4h-лоу, ЗАКОН: стоп за структуру)
                p=sim(j,H1,L1,C1,sl4,e+(e-sl4),72,); LTF_S.append((y,p,sym))
                if first: LTF_FIRST.append((y,p,sym))
            slt=L1[max(0,j-3):j+1].min()*0.997                        # тугой SL (1h-лоу)
            if slt<e: LTF_T.append((y,sim(j,H1,L1,C1,slt,e+(e-slt),72),sym))
            first=False
print("═══ ВХОД: закрытие 4h (эталон) vs 1h-кросс внутри зоны ═══")
rep("эталон: закрытие 4h",BASE)
rep("1h-кросс, SL структурный 4h",LTF_S)
rep("1h-кросс, SL тугой 1h",LTF_T)
rep("1h-кросс ПЕРВЫЙ, SL 4h",LTF_FIRST)
