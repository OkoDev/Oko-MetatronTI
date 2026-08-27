# -*- coding: utf-8 -*-
"""СЛЕДОВАНИЕ ТРЕНДУ (Егор 30.07): 4h цена выше/ниже WPP = НАПРАВЛЕНИЕ;
каждый флип ATRTrend (=atr_change) на 1h/15m ПО направлению = вход; выход по TSL (линия ATRTrend).
Обобщает единственного многолетнего выжившего (флип 4h + cl<WPP → S2, +0.471%/сд).
Контроли: (а) без WPP-гейта — нужен ли он (б) выход TP1R вместо TSL — лучше ли TSL.
Причинно: WPP из ЗАКРЫТОЙ недели, bias с ЗАКРЫТОГО 4h-бара. Косты 0.15."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
def atrt_line(df,period=43,factor=1.25):
    """ATRTrend: тренд +1/-1 + ЛИНИЯ TSL (нижняя полоса в аптренде / верхняя в даунтренде)."""
    h,l,c=df.high,df.low,df.close; hl2=((h+l)/2).values
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean().values
    up=hl2-factor*atr; dn=hl2+factor*atr; tu=up.copy(); td=dn.copy(); tr_=np.ones(len(hl2)); line=up.copy()
    for i in range(1,len(hl2)):
        tu[i]=max(up[i],tu[i-1]) if hl2[i-1]>tu[i-1] else up[i]
        td[i]=min(dn[i],td[i-1]) if hl2[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hl2[i]>td[i-1] else(-1 if hl2[i]<tu[i-1] else tr_[i-1])
        line[i]=tu[i] if tr_[i]>0 else td[i]
    return tr_,line
def wpp_series(d1h):
    """Weekly Pivot Point из ЗАКРЫТОЙ недели (Пн-Вс): (H+L+C)/3. Причинно."""
    s=d1h.set_index(pd.to_datetime(d1h.time,unit="ms"))
    w=s.resample("W-MON",label="left",closed="left").agg({"high":"max","low":"min","close":"last"}).dropna()
    w["wpp"]=(w.high+w.low+w.close)/3
    w["avail"]=w.index+pd.Timedelta(days=7)      # известен только со следующей недели
    return pd.DataFrame({"time":(w["avail"].astype("int64")//10**6).values,"wpp":w["wpp"].values})
def project(t_from,v_from,t_to,shift_ms):
    a=pd.DataFrame({"time":np.asarray(t_from)+shift_ms,"v":np.asarray(v_from)})
    return pd.merge_asof(pd.DataFrame({"time":np.asarray(t_to)}),a,on="time",direction="backward")["v"].values
def exit_tsl(i,side,C,line,ttl):
    e=C[i]; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if side>0 and C[j]<line[j]: return (C[j]-e)/e*100-COST
        if side<0 and C[j]>line[j]: return (e-C[j])/e*100-COST
    return side*(C[end]-e)/e*100-COST
def exit_tp1r(i,side,H,L,C,line,ttl):
    e=C[i]; sl=line[i]; r=abs(e-sl)
    if r<=0: return None
    tp=e+side*r; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=sl: return (sl-e)/e*100-COST
            if H[j]>=tp: return (tp-e)/e*100-COST
        else:
            if H[j]>=sl: return (e-sl)/e*100-COST
            if L[j]<=tp: return (e-tp)/e*100-COST
    return side*(C[end]-e)/e*100-COST
def rep(name,rows,months):
    if len(rows)<30: print(f"    {name:30} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    y=lambda yy:[x[1] for x in rows if x[0]==yy]
    y24,y25,y26=y(2024),y(2025),y(2026)
    fmt=lambda a: f"{np.median(a):+.2f}" if len(a)>20 else " ?  "
    fr=len(r)/len(coins)/months; pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    ok=med>0.02 and srt[:-cut].sum()>0
    print(f"    {name:30} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% PF{pf:.2f} сум{r.sum():+6.0f}% безтоп10%{srt[:-cut].sum():+7.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** | 24:{fmt(y24)} 25:{fmt(y25)} 26:{fmt(y26)} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>15000 ORDER BY n DESC LIMIT 45",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · 4h vs WPP = направление · флип ATRTrend на 1h/15m = вход · выход TSL\n")
RES={}
for etf,ttl,months in (("1h",200,29.0),("15m",300,29.0)):
    for s in syms:
        d4=load(s,"4h",t0); d1=load(s,"1h",t0); de=load(s,etf,t0) if etf!="1h" else d1
        if len(d4)<300 or len(d1)<2000 or len(de)<2000: continue
        tr4,_=atrt_line(d4)
        wpp=wpp_series(d1)
        if len(wpp)<10: continue
        tre,line=atrt_line(de)
        H=de.high.values; L=de.low.values; C=de.close.values; T=de.time.values
        yr=pd.to_datetime(de.time,unit="ms").dt.year.values
        c4=project(d4.time.values,d4.close.values,T,4*3600000)      # ЗАКРЫТЫЙ 4h close
        wv=pd.merge_asof(pd.DataFrame({"time":T}),wpp,on="time",direction="backward")["wpp"].values
        for i in range(60,len(de)-1):
            if tre[i]==tre[i-1]: continue                            # только ФЛИП (=atr_change)
            side=1 if tre[i]>0 else -1
            if np.isnan(c4[i]) or np.isnan(wv[i]): continue
            bias=1 if c4[i]>wv[i] else -1                            # 4h выше/ниже WPP
            y=int(yr[i])
            p_tsl=exit_tsl(i,side,C,line,ttl); p_tp=exit_tp1r(i,side,H,L,C,line,ttl)
            RES.setdefault((etf,"TSL, БЕЗ WPP-гейта"),[]).append((y,p_tsl,s))
            if side==bias:
                RES.setdefault((etf,"TSL + WPP по направлению"),[]).append((y,p_tsl,s))
                if p_tp is not None: RES.setdefault((etf,"TP1R + WPP по направлению"),[]).append((y,p_tp,s))
                RES.setdefault((etf,f"TSL+WPP {'LONG' if bias>0 else 'SHORT'}"),[]).append((y,p_tsl,s))
            else:
                RES.setdefault((etf,"TSL ПРОТИВ WPP (контроль)"),[]).append((y,p_tsl,s))
    print(f"  ═══ вход по флипу на {etf} (выход TSL, ttl {ttl} баров) ═══")
    for k in ("TSL, БЕЗ WPP-гейта","TSL + WPP по направлению","TSL ПРОТИВ WPP (контроль)","TP1R + WPP по направлению","TSL+WPP LONG","TSL+WPP SHORT"):
        if (etf,k) in RES: rep(k,RES[(etf,k)],months)
    print()
