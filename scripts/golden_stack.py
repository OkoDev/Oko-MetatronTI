# -*- coding: utf-8 -*-
"""ЗОЛОТОЙ СТЕК (30.07) — все выжившие ключи вместе + гибрид-выход.
Ключи: 4h WT<-70 (ядро) + ATRChange расширение (чистит мусор) + MTF-выравнивание (матрица Егора).
Выход: TP1R vs ГИБРИД (½ банк + ½ каскадный раннер). Прокурор: медиана, годы, OOS, хрупкость, охват монет."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
def wt(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    return ((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0).values
def atrt(df,period=43,factor=1.25):
    h,l,c=df.high,df.low,df.close; hl2=(h+l)/2
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean()
    up=(hl2-factor*atr).values; dn=(hl2+factor*atr).values; hv=hl2.values; tu=up.copy(); td=dn.copy(); tr_=np.ones(len(df))
    for i in range(1,len(df)):
        tu[i]=max(up[i],tu[i-1]) if hv[i-1]>tu[i-1] else up[i]; td[i]=min(dn[i],td[i-1]) if hv[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hv[i]>td[i-1] else(-1 if hv[i]<tu[i-1] else tr_[i-1])
    return tr_
def atr_series(df,n=14):
    h,l,c=df.high,df.low,df.close
    return pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1).rolling(n).mean().values
def atr_change(df,n=14,lag=8):
    a=pd.Series(atr_series(df,n)); return (a/a.shift(lag)-1).fillna(0).values
def project(d_from,v_from,d_to,closed_ms):
    df=pd.DataFrame({"time":d_from["time"].values+closed_ms,"v":v_from})
    return pd.merge_asof(d_to[["time"]],df,on="time",direction="backward")["v"].fillna(0).values
def e_tp1r(i,H,L,C,sl,ttl=18):
    e=C[i]; tp=e+(e-sl); end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if L[j]<=sl: return (sl-e)/e*100-COST
        if H[j]>=tp: return (tp-e)/e*100-COST
    return (C[end]-e)/e*100-COST
def e_hybrid(i,H,L,C,A,sl,k=2.0,ttl=40):
    """½ на TP1R (банк) + ½ раннер: активация после +1R, трейл k*ATR от максимума (каскад-подобно)."""
    e=C[i]; R=e-sl; tp=e+R; end=min(i+ttl,len(C)-1)
    half1=None; peak=e; trail=sl; act=False
    for j in range(i+1,end+1):
        if half1 is None and L[j]<=sl: return (sl-e)/e*100-COST   # оба стопа до TP1
        if half1 is None and H[j]>=tp:
            half1=(tp-e)/e*100; act=True; peak=max(peak,H[j]); trail=max(trail,e)  # безубыток раннеру
            continue
        if half1 is not None:
            peak=max(peak,H[j]); trail=max(trail,peak-k*(A[j] if not np.isnan(A[j]) else R))
            if L[j]<=trail: return (half1+(trail-e)/e*100)/2-COST
    if half1 is None: return (C[end]-e)/e*100-COST
    return (half1+(C[end]-e)/e*100)/2-COST
def rep(name,rows,show_years=True):
    if len(rows)<15: print(f"  {name:34} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=set(x[2] for x in rows); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    flag="🟢🟢" if(med>0.05 and srt[:-cut].sum()>0) else("🟡" if r.mean()>0 else "🔴")
    print(f"  {name:34} n={len(r):4} WR{100*(r>0).mean():2.0f}% МЕД{med:+.2f}% avg{r.mean():+.2f}% сум{r.sum():+.0f}% безтоп10%{srt[:-cut].sum():+.0f}% монет+{pos}/{len(coins)} {flag}")
    if show_years:
        for lbl,f in [("2024",lambda y:y==2024),("2025-26",lambda y:y>=2025)]:
            sub=[x for x in rows if f(x[0])]
            if len(sub)>=15:
                rr=np.array([x[1] for x in sub]); ss=np.sort(rr); cc=max(1,len(rr)//10)
                print(f"      {lbl:30} n={len(rr):4} WR{100*(rr>0).mean():2.0f}% МЕД{np.median(rr):+.2f}% сум{rr.sum():+.0f}% безтоп10%{ss[:-cc].sum():+.0f}%")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>2500 ORDER BY n DESC LIMIT 70",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · ЗОЛОТОЙ СТЕК: 4h WT<-70 + ATRChange + выравнивание · TP1R vs ГИБРИД\n")
K={k:[] for k in ("base","ac","al","ac_al","ac_hyb","ac_al_hyb")}
for sym in syms:
    d4=load(sym,"4h",t0); d1=load(sym,"1h",t0); d15=load(sym,"15m",t0)
    if len(d4)<400 or len(d1)<1500: continue
    w=wt(d4); a4=atrt(d4); ac=atr_change(d4); A=atr_series(d4)
    a1=project(d1,atrt(d1),d4,3600000); a15=project(d15,atrt(d15),d4,15*60000) if len(d15)>2000 else np.zeros(len(d4))
    H=d4.high.values; L=d4.low.values; C=d4.close.values; yr=pd.to_datetime(d4.time,unit="ms").dt.year.values; N=len(d4)
    for i in range(60,N-1):
        if not (a4[i]>0 and w[i]<-70): continue
        sl=L[max(0,i-3):i+1].min()*0.997
        if sl>=C[i]: continue
        y=int(yr[i]); p1=e_tp1r(i,H,L,C,sl); ph=e_hybrid(i,H,L,C,A,sl)
        expand=ac[i]>0.3; align=(a15[i]>0)+(a1[i]>0)>=1   # 15m/1h согласны с 4h (4h уже ↑)
        K["base"].append((y,p1,sym))
        if expand: K["ac"].append((y,p1,sym)); K["ac_hyb"].append((y,ph,sym))
        if align: K["al"].append((y,p1,sym))
        if expand and align: K["ac_al"].append((y,p1,sym)); K["ac_al_hyb"].append((y,ph,sym))
print("═══ ЯДРО и ключи (TP1R) ═══")
rep("база 4h WT<-70",K["base"]); rep("+ATRChange расшир",K["ac"]); rep("+выравнивание",K["al"]); rep("+ATRChange+выравн",K["ac_al"])
print("\n═══ ГИБРИД-ВЫХОД (½ банк + ½ раннер) ═══")
rep("ATRChange · ГИБРИД",K["ac_hyb"]); rep("ATRChange+выравн · ГИБРИД",K["ac_al_hyb"])
print("\n═══ OOS-СПЛИТ (train ≤2025-06 / test >2025-06) ═══")
cut_ms=int(dt.datetime(2025,7,1,tzinfo=dt.timezone.utc).timestamp()*1000)
for nm in ("ac","ac_hyb"):
    rows=K[nm]
    tr=[x for x in rows if x[0]<=2024 or (x[0]==2025)]; te=[x for x in rows if x[0]>=2026]
    rep(f"{nm} 2024-25 (train)",tr,show_years=False); rep(f"{nm} 2026 (test)",te,show_years=False)
