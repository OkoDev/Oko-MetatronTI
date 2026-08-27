# -*- coding: utf-8 -*-
"""ШОРТ-РОДСТВЕННИК BIG-FLUSH × FUNDING — проверка СИММЕТРИИ механизма.
Если «толпа в шортах = топливо лонгу» верно, то зеркально «толпа в ЛОНГАХ (высокая ставка) =
топливо ШОРТУ». Сетап: 15m ATRTrend↓ + WT>+60 + шип >4% → SHORT TP1R. Ликвидная половина.
Контроль: тот же разрез для LONG (уже известен) — чтобы видеть зеркало в одной таблице."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
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
def rep(name,rows,months=29.0):
    if len(rows)<30: print(f"    {name:40} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    y=lambda yy:[x[1] for x in rows if x[0]==yy]; fmt=lambda a: f"{np.median(a):+.2f}" if len(a)>20 else " ?  "
    fr=len(r)/len(coins)/months; pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    ok=med>0.02 and srt[:-cut].sum()>0 and pf>1.05
    print(f"    {name:40} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% PF{pf:.2f} безтоп10%{srt[:-cut].sum():+7.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** | 24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT 40",(t0,)).fetchall()]; c.close()
turn={};DATA={}
for s in syms:
    d=load(s,"15m",t0)
    if len(d)>=5000: DATA[s]=d; turn[s]=float(np.nanmedian((d.close*d.volume).values))
mt=np.nanmedian(list(turn.values()))
print(f"монет {len(DATA)} (ликвидная половина: {sum(1 for s in DATA if turn[s]>=mt)}) · проверка СИММЕТРИИ funding\n")
R={}
for s,d in DATA.items():
    if turn[s]<mt: continue
    fr=fund(s,t0)
    if len(fr)<100: continue
    w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values; T=d.time.values
    yr=pd.to_datetime(d.time,unit="ms").dt.year.values
    fr["pct"]=fr["rate"].expanding(min_periods=50).rank(pct=True)
    fj=pd.merge_asof(pd.DataFrame({"time":T}),fr[["time","rate","pct"]],on="time",direction="backward")
    pct=fj["pct"].values
    for i in range(60,len(d)-1):
        e=C[i]; y=int(yr[i])
        if np.isnan(pct[i]): continue
        lo_f, hi_f = pct[i]<0.2, pct[i]>0.8
        # LONG (известен) — контроль зеркала
        if a[i]>0 and w[i]<-60 and w[i]>w[i-1]:
            sl=L[max(0,i-3):i+1].min()*0.997
            if sl<e and (e-sl)/e*100>4.0:
                p=sim(i,1,H,L,C,sl); R.setdefault("LONG всё",[]).append((y,p,s))
                if lo_f: R.setdefault("LONG + толпа в ШОРТАХ (fund низкий)",[]).append((y,p,s))
                if hi_f: R.setdefault("LONG + толпа в ЛОНГАХ (fund высокий)",[]).append((y,p,s))
        # SHORT — зеркало
        if a[i]<0 and w[i]>60 and w[i]<w[i-1]:
            sl=H[max(0,i-3):i+1].max()*1.003
            if sl>e and (sl-e)/e*100>4.0:
                p=sim(i,-1,H,L,C,sl); R.setdefault("SHORT всё",[]).append((y,p,s))
                if hi_f: R.setdefault("SHORT + толпа в ЛОНГАХ (fund высокий) ← ТОПЛИВО?",[]).append((y,p,s))
                if lo_f: R.setdefault("SHORT + толпа в ШОРТАХ (fund низкий)",[]).append((y,p,s))
print("  ═══ LONG (контроль, зеркало известно) ═══")
for k in ("LONG всё","LONG + толпа в ШОРТАХ (fund низкий)","LONG + толпа в ЛОНГАХ (fund высокий)"): rep(k,R.get(k,[]))
print("\n  ═══ SHORT (проверка симметрии) ═══")
for k in ("SHORT всё","SHORT + толпа в ЛОНГАХ (fund высокий) ← ТОПЛИВО?","SHORT + толпа в ШОРТАХ (fund низкий)"): rep(k,R.get(k,[]))
