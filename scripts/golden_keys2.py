# -*- coding: utf-8 -*-
"""КЛЮЧ ДИВЕРГЕНЦИИ по-честному (Егор): regular-bull на глубоком OS — сила+цепочка+зона.
Тест на 1h И 4h WT<-70. + фикс выравнивания (дебаг проекции). Прокурор: медиана+годы+хрупкость."""
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
def wt_pivot_lows(w,p=5):
    """локальные минимумы WT (pivot lows, окно p) → список (idx, val)."""
    out=[]; n=len(w)
    for i in range(p,n-p):
        if w[i]==min(w[i-p:i+p+1]) and w[i]<w[i-1]: out.append((i,w[i]))
    return out
def project(d_from,v_from,d_to,closed_ms):
    df=pd.DataFrame({"time":d_from["time"].values+closed_ms,"v":v_from})
    return pd.merge_asof(d_to[["time"]],df,on="time",direction="backward")["v"].fillna(0).values
def simTP(i,H,L,C,side,sl,tp,ttl=24):
    e=C[i]; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=sl:return(sl-e)/e*100-COST
            if H[j]>=tp:return(tp-e)/e*100-COST
    return side*(C[end]-e)/e*100-COST
def rep(name,rows):
    if len(rows)<15: print(f"  {name:24} n={len(rows)}"); return
    r=np.array(rows); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    flag="🟢🟢" if(med>0.05 and srt[:-cut].sum()>0) else("🟡" if r.mean()>0 else "🔴")
    print(f"  {name:24} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% avg{r.mean():+.3f}% сум{r.sum():+.0f}% безтоп10%{srt[:-cut].sum():+.0f}% {flag}")
def run_tf(entry_tf,syms,t0,htf,htf_ms):
    BASE=[];DIV=[];DIVS=[];CHAIN=[];AL=[]; dbg=[0,0,0]
    for sym in syms:
        de=load(sym,entry_tf,t0)
        if len(de)<600: continue
        w=wt(de); a=atrt(de); H=de.high.values; L=de.low.values; C=de.close.values; yr=pd.to_datetime(de.time,unit="ms").dt.year.values; N=len(de)
        dh=load(sym,htf,t0); ah=project(dh,atrt(dh),de,htf_ms) if len(dh)>50 else np.zeros(N)
        piv=wt_pivot_lows(w,5); pv_idx=np.array([p[0] for p in piv]); pv_val=np.array([p[1] for p in piv])
        for i in range(60,N-1):
            if not (w[i]<-70 and w[i]>w[i-1]): continue
            y=int(yr[i]); lo=L[max(0,i-4):i+1].min()*0.997
            if lo>=C[i]: continue
            pnl=simTP(i,H,L,C,1,lo,C[i]+1.0*(C[i]-lo))
            BASE.append((y,pnl))
            # выравнивание: entry-TF trend up + htf up (дебаг)
            if a[i]>0: dbg[0]+=1
            if ah[i]>0: dbg[1]+=1
            if a[i]>0 and ah[i]>0: dbg[2]+=1; AL.append((y,pnl))
            # ДИВЕРГЕНЦИЯ: предыдущее WT-дно в OS в окне 15..100, WT выше, цена ниже
            mask=(pv_idx<i-8)&(pv_idx>i-100)&(pv_val<-60)
            if mask.any():
                j=pv_idx[mask][-1]; wj=pv_val[mask][-1]
                if w[i]>wj+3 and L[i]<L[j]:   # regular bullish div
                    DIV.append((y,pnl))
                    if w[i]<-70 and wj<-70: DIVS.append((y,pnl))  # оба в глубоком OS = сильная
                    # цепочка: ≥2 более старых дна ниже
                    older=pv_val[(pv_idx<j)&(pv_idx>i-160)]
                    if (older<wj).sum()>=1: CHAIN.append((y,pnl))
    print(f"\n═══ {entry_tf} WT<-70 · HTF={htf} ({'выравн'} дебаг: entryUP={dbg[0]} htfUP={dbg[1]} обаUP={dbg[2]}) ═══")
    for nm,d in [("база",BASE),("+выравн(entry+htf↑)",AL),("+дивергенция",DIV),("+дивер СИЛЬНАЯ(оба<-70)",DIVS),("+дивер ЦЕПОЧКА",CHAIN)]:
        rep(nm,[x[1] for x in d])
        if len(d)>=40 and nm!="база":
            rep(f"  {nm[:12]} 2024",[x[1] for x in d if x[0]==2024]); rep(f"  {nm[:12]} 2025-26",[x[1] for x in d if x[0]>=2025])
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>2500 ORDER BY n DESC LIMIT 55",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)}")
run_tf("4h",syms,t0,"1d",24*3600000)
run_tf("1h",syms,t0,"4h",4*3600000)
