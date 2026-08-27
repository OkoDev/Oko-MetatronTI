# -*- coding: utf-8 -*-
"""ОТВЕТ НА ВОПРОС ЕГОРА «фейд умирает — торгуем продолжение?»
Автокорреляция 6ч-доходностей (causal) разделила фейд: импульсный рынок PF3.73 / возвратный PF1.36.
Проверяю, что делать в СЛАБОМ для фейда режиме: работает ли там ПРОДОЛЖЕНИЕ (наш трендовый сетап:
4h флип ATRTrend + направление WPP + гейт WT>0, SL swing12 коридор 2-6%, TP1R) — или надо сидеть вне рынка."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.25
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
def wt_(df,n1=10,n2=21):
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
def wpp_series(d1h):
    s=d1h.set_index(pd.to_datetime(d1h.time,unit="ms"))
    w=s.resample("W-MON",label="left",closed="left").agg({"high":"max","low":"min","close":"last"}).dropna()
    w["wpp"]=(w.high+w.low+w.close)/3; av=w.index+pd.Timedelta(days=7)
    return pd.DataFrame({"time":(av.astype("int64")//10**6).values,"wpp":w["wpp"].values})
def sim(i,side,H,L,C,sl,ttl):
    e=C[i]; tp=e+side*abs(e-sl); end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=sl:return(sl-e)/e*100-COST
            if H[j]>=tp:return(tp-e)/e*100-COST
        else:
            if H[j]>=sl:return(e-sl)/e*100-COST
            if L[j]<=tp:return(e-tp)/e*100-COST
    return side*(C[end]-e)/e*100-COST
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
px={}
for s in syms:
    d=load(s,"1h",t0)
    if len(d)>3000: px[s]=pd.Series(d.close.values,index=d.time.values)
panel=pd.DataFrame(px).sort_index(); r6=panel.pct_change(6); W=14*24
ac=(r6.rolling(W).corr(r6.shift(6)).mean(axis=1)).shift(6)
q=ac.quantile([0.33,0.67]).values
acdf=pd.DataFrame({"time":ac.index.values,"v":ac.values}).dropna()
print(f"пороги AC: {q[0]:+.4f} / {q[1]:+.4f}\n")
c=sqlite3.connect(DB); s4=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>2500 ORDER BY n DESC LIMIT 60",(t0,)).fetchall()]; c.close()
R={}
for s in s4:
    d4=load(s,"4h",t0); d1=load(s,"1h",t0)
    if len(d4)<300 or len(d1)<2000: continue
    wpp=wpp_series(d1)
    if len(wpp)<10: continue
    w=wt_(d4); tre=atrt(d4); H=d4.high.values; L=d4.low.values; C=d4.close.values; T=d4.time.values
    yr=pd.to_datetime(d4.time,unit="ms").dt.year.values
    wv=pd.merge_asof(pd.DataFrame({"time":T}),wpp,on="time",direction="backward")["wpp"].values
    av=pd.merge_asof(pd.DataFrame({"time":T}),acdf,on="time",direction="backward")["v"].values
    for i in range(60,len(d4)-1):
        if tre[i]==tre[i-1]: continue                      # ФЛИП = вход продолжения
        side=1 if tre[i]>0 else -1
        if np.isnan(wv[i]) or np.isnan(av[i]): continue
        if side!=(1 if C[i]>wv[i] else -1): continue       # по направлению WPP
        if not ((side>0 and w[i]>0) or (side<0 and w[i]<0)): continue   # гейт WT нуля
        e=C[i]; sl=(L[max(0,i-12):i+1].min()*0.997) if side>0 else (H[max(0,i-12):i+1].max()*1.003)
        dist=abs(e-sl)/e*100
        if not (2.0<=dist<=6.0): continue
        p=sim(i,side,H,L,C,sl,120); y=int(yr[i])
        R.setdefault("ПРОДОЛЖЕНИЕ: всё",[]).append((y,p,s))
        k=("ПРОДОЛЖЕНИЕ: возвратный рынок (AC низкая)" if av[i]<=q[0] else
           ("ПРОДОЛЖЕНИЕ: импульсный рынок (AC высокая)" if av[i]>=q[1] else "ПРОДОЛЖЕНИЕ: середина"))
        R.setdefault(k,[]).append((y,p,s))
print("  ═══ ПРОДОЛЖЕНИЕ (флип+WPP+WT>0) × режим автокорреляции ═══")
for k in ("ПРОДОЛЖЕНИЕ: всё","ПРОДОЛЖЕНИЕ: возвратный рынок (AC низкая)","ПРОДОЛЖЕНИЕ: середина","ПРОДОЛЖЕНИЕ: импульсный рынок (AC высокая)"): rep(k,R.get(k,[]))
