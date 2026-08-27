# -*- coding: utf-8 -*-
"""СИНТЕЗ: НАПРАВЛЕНИЕ по WPP (Егор, подтверждено: Δ5.5% медианы) + ВХОД по BIG-FLUSH (размер>4%).
WPP даёт сторону, флеш даёт тайминг (WR61% против 53% у флипа). Плюс ШОРТ-РОДСТВЕННИК:
4h ниже WPP + шип ВВЕРХ >4% (WT>+60, ATRTrend↓) → SHORT. Ликвидная половина отдельно.
Прокурор: медиана, PF, безтоп10%, охват, годы, частота. Косты 0.15 + стресс 0.25."""
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
def wpp_series(d1h):
    s=d1h.set_index(pd.to_datetime(d1h.time,unit="ms"))
    w=s.resample("W-MON",label="left",closed="left").agg({"high":"max","low":"min","close":"last"}).dropna()
    w["wpp"]=(w.high+w.low+w.close)/3; av=w.index+pd.Timedelta(days=7)
    return pd.DataFrame({"time":(av.astype("int64")//10**6).values,"wpp":w["wpp"].values})
def project(t_from,v_from,t_to,shift_ms):
    a=pd.DataFrame({"time":np.asarray(t_from)+shift_ms,"v":np.asarray(v_from)})
    return pd.merge_asof(pd.DataFrame({"time":np.asarray(t_to)}),a,on="time",direction="backward")["v"].values
def raw(i,side,H,L,C,sl,ttl):
    e=C[i]; tp=e+side*abs(e-sl); end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=sl:return(sl-e)/e*100
            if H[j]>=tp:return(tp-e)/e*100
        else:
            if H[j]>=sl:return(e-sl)/e*100
            if L[j]<=tp:return(e-tp)/e*100
    return side*(C[end]-e)/e*100
def rep(name,rows,months,cost):
    if len(rows)<30: print(f"    {name:30} n={len(rows)}"); return
    r=np.array([x[1] for x in rows])-cost; srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1]-cost for x in rows if x[2]==cn])>0)
    y=lambda yy:[x[1]-cost for x in rows if x[0]==yy]; fmt=lambda a: f"{np.median(a):+.2f}" if len(a)>20 else " ?  "
    fr=len(r)/len(coins)/months; pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    ok=med>0.02 and srt[:-cut].sum()>0 and pf>1.05
    print(f"    {name:30} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% PF{pf:.2f} сум{r.sum():+6.0f}% безтоп10%{srt[:-cut].sum():+7.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** | 24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT 40",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · 15m BIG-FLUSH (стоп>4%) × направление 4h vs WPP · LONG и SHORT\n")
turn={};DATA={}
for s in syms:
    d=load(s,"15m",t0)
    if len(d)>=5000: DATA[s]=d; turn[s]=float(np.nanmedian((d.close*d.volume).values))
mt=np.nanmedian(list(turn.values()))
R={}
for s,d in DATA.items():
    d4=load(s,"4h",t0); d1=load(s,"1h",t0)
    if len(d4)<300 or len(d1)<2000: continue
    wpp=wpp_series(d1)
    if len(wpp)<10: continue
    w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values; T=d.time.values
    yr=pd.to_datetime(d.time,unit="ms").dt.year.values
    c4=project(d4.time.values,d4.close.values,T,4*3600000)
    wv=pd.merge_asof(pd.DataFrame({"time":T}),wpp,on="time",direction="backward")["wpp"].values
    liq = turn[s]>=mt
    for i in range(60,len(d)-1):
        if np.isnan(c4[i]) or np.isnan(wv[i]): continue
        bias=1 if c4[i]>wv[i] else -1
        e=C[i]; y=int(yr[i])
        # LONG big-flush: аптренд 15m + глубокий WT + крупный стоп
        if a[i]>0 and w[i]<-60 and w[i]>w[i-1]:
            sl=L[max(0,i-3):i+1].min()*0.997
            if sl<e and (e-sl)/e*100>4.0:
                p=raw(i,1,H,L,C,sl,24); rec=(y,p,s)
                R.setdefault("LONG всё",[]).append(rec)
                R.setdefault("LONG + WPP↑ (по)" if bias>0 else "LONG против WPP",[]).append(rec)
                if liq and bias>0: R.setdefault("LONG + WPP↑ ЛИКВИД",[]).append(rec)
        # SHORT-родственник: даунтренд 15m + перекупленный WT + крупный стоп (шип вверх)
        if a[i]<0 and w[i]>60 and w[i]<w[i-1]:
            sl=H[max(0,i-3):i+1].max()*1.003
            if sl>e and (sl-e)/e*100>4.0:
                p=raw(i,-1,H,L,C,sl,24); rec=(y,p,s)
                R.setdefault("SHORT всё",[]).append(rec)
                R.setdefault("SHORT + WPP↓ (по)" if bias<0 else "SHORT против WPP",[]).append(rec)
                if liq and bias<0: R.setdefault("SHORT + WPP↓ ЛИКВИД",[]).append(rec)
for cost in (0.15,0.25):
    print(f"  ═══ косты {cost}% ═══")
    for k in ("LONG всё","LONG + WPP↑ (по)","LONG против WPP","LONG + WPP↑ ЛИКВИД",
              "SHORT всё","SHORT + WPP↓ (по)","SHORT против WPP","SHORT + WPP↓ ЛИКВИД"):
        if k in R: rep(k,R[k],29.0,cost)
    print()
