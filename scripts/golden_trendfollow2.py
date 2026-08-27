# -*- coding: utf-8 -*-
"""СЛЕДОВАНИЕ ТРЕНДУ v2 — ЧЕСТНО (v1 был невалиден: стоп на ЛИНИИ индикатора + TSL без активации).
Егор: 4h выше/ниже WPP = направление · флип ATRTrend на 4h/1h/15m по направлению = вход · выход TSL.
ИСПРАВЛЕНО по фактам проекта: SL = swing12 (ЗАКОН «стоп за структуру»), TSL активируется ПОСЛЕ +1R
(как в боте), разрез по ДИСТАНЦИИ СТОПА (линза размера — косты это доля цели).
КОНТРОЛЬ: 4h-флип должен воспроизвести известный плюс (atr_change S2 +0.471%/сд) — иначе харнесс врёт."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
def atrt_line(df,period=43,factor=1.25):
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
    s=d1h.set_index(pd.to_datetime(d1h.time,unit="ms"))
    w=s.resample("W-MON",label="left",closed="left").agg({"high":"max","low":"min","close":"last"}).dropna()
    w["wpp"]=(w.high+w.low+w.close)/3; av=w.index+pd.Timedelta(days=7)
    return pd.DataFrame({"time":(av.astype("int64")//10**6).values,"wpp":w["wpp"].values})
def project(t_from,v_from,t_to,shift_ms):
    a=pd.DataFrame({"time":np.asarray(t_from)+shift_ms,"v":np.asarray(v_from)})
    return pd.merge_asof(pd.DataFrame({"time":np.asarray(t_to)}),a,on="time",direction="backward")["v"].values
def run_exit(i,side,H,L,C,line,sl0,ttl,mode):
    """mode='tp1r' — фикс TP1R от структурного SL. mode='tsl' — SL структурный, после +1R трейл по линии."""
    e=C[i]; r=abs(e-sl0)
    if r<=0: return None
    tp=e+side*r; end=min(i+ttl,len(C)-1); act=False; stop=sl0
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=stop: return (stop-e)/e*100-COST
            if mode=="tp1r" and H[j]>=tp: return (tp-e)/e*100-COST
            if mode=="tsl":
                if not act and H[j]>=tp: act=True                  # активация после +1R
                if act: stop=max(stop,line[j]) if line[j]<C[j] else stop
        else:
            if H[j]>=stop: return (e-stop)/e*100-COST
            if mode=="tp1r" and L[j]<=tp: return (e-tp)/e*100-COST
            if mode=="tsl":
                if not act and L[j]<=tp: act=True
                if act: stop=min(stop,line[j]) if line[j]>C[j] else stop
    return side*(C[end]-e)/e*100-COST
def rep(name,rows,months):
    if len(rows)<30: print(f"    {name:28} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    y=lambda yy:[x[1] for x in rows if x[0]==yy]; fmt=lambda a: f"{np.median(a):+.2f}" if len(a)>20 else " ?  "
    fr=len(r)/len(coins)/months; pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    ok=med>0.02 and srt[:-cut].sum()>0
    print(f"    {name:28} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% PF{pf:.2f} сум{r.sum():+7.0f}% безтоп10%{srt[:-cut].sum():+8.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:6.2f}сд/мес → **{fr*med:+.2f}%/мес** | 24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
def bkt(d): return "стоп<1%" if d<1 else("стоп1-2%" if d<2 else("стоп2-4%" if d<4 else "стоп>4%"))
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>15000 ORDER BY n DESC LIMIT 45",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · SL=swing12 (структура) · TSL после +1R · разрез по размеру стопа\n")
for etf,ttl,shift in (("4h",120,4*3600000),("1h",200,3600000),("15m",300,15*60000)):
    R={}
    for s in syms:
        d4=load(s,"4h",t0); d1=load(s,"1h",t0)
        de=d4 if etf=="4h" else (d1 if etf=="1h" else load(s,etf,t0))
        if len(d4)<300 or len(d1)<2000 or len(de)<1000: continue
        wpp=wpp_series(d1)
        if len(wpp)<10: continue
        tre,line=atrt_line(de); H=de.high.values; L=de.low.values; C=de.close.values; T=de.time.values
        yr=pd.to_datetime(de.time,unit="ms").dt.year.values
        c4=project(d4.time.values,d4.close.values,T,4*3600000)
        wv=pd.merge_asof(pd.DataFrame({"time":T}),wpp,on="time",direction="backward")["wpp"].values
        for i in range(60,len(de)-1):
            if tre[i]==tre[i-1]: continue
            side=1 if tre[i]>0 else -1
            if np.isnan(c4[i]) or np.isnan(wv[i]): continue
            if side!=(1 if c4[i]>wv[i] else -1): continue            # ТОЛЬКО по направлению WPP
            e=C[i]; y=int(yr[i])
            sl0=(L[max(0,i-12):i+1].min()*0.997) if side>0 else (H[max(0,i-12):i+1].max()*1.003)
            dist=abs(e-sl0)/e*100
            if not (0<dist<50): continue
            for mode in ("tp1r","tsl"):
                p=run_exit(i,side,H,L,C,line,sl0,ttl,mode)
                if p is None: continue
                R.setdefault((mode,"ВСЕ"),[]).append((y,p,s)); R.setdefault((mode,bkt(dist)),[]).append((y,p,s))
    print(f"  ═══ вход по флипу {etf} + WPP-направление · SL swing12 ═══")
    for mode,lbl in (("tp1r","TP1R"),("tsl","TSL после +1R")):
        print(f"   ── выход {lbl} ──")
        for k in ("ВСЕ","стоп<1%","стоп1-2%","стоп2-4%","стоп>4%"):
            if (mode,k) in R: rep(k,R[(mode,k)],29.0)
    print()
