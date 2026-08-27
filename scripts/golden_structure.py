# -*- coding: utf-8 -*-
"""GOLDEN STRUCTURE (Егор 30.07) — MTF сломы структуры + ATRTrend + WT + структурный TSL, ПРИЧИННО.
Гипотеза (метод Егора): HTF структура-тренд + LTF свежий CHoCH в сторону HTF → вход, TSL за свинг.
Свинги fractal(k), CHoCH/BOS causal (свинг подтверждён через k баров). Прокурор: сумма/PF/хвост/OOS."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.10
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df
def wt(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    return ((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0).values
def structure(df,k=4):
    """Causal: возвращает trend[+1/-1], choch[bar->±1 при свежем сломе], last_sl/last_sh (для TSL)."""
    H=df.high.values;L=df.low.values;C=df.close.values;n=len(df)
    trend=np.zeros(n,int); choch=np.zeros(n,int)
    lsh=np.full(n,np.nan); lsl=np.full(n,np.nan)  # последний ПОДТВЕРЖДЁННЫЙ свинг-хай/лоу на этот бар
    csh=None; csl=None; t=0
    for i in range(n):
        # подтверждаем свинг с задержкой k (causal): свинг на баре i-k
        j=i-k
        if j>=k:
            if H[j]==H[j-k:j+k+1].max(): csh=H[j]
            if L[j]==L[j-k:j+k+1].min(): csl=L[j]
        lsh[i]=csh if csh is not None else np.nan; lsl[i]=csl if csl is not None else np.nan
        # BOS/CHoCH по закрытию относительно подтверждённых свингов
        if csh is not None and C[i]>csh:
            if t<=0: choch[i]=1     # слом вверх из даун/флэт = CHoCH up
            t=1
        elif csl is not None and C[i]<csl:
            if t>=0: choch[i]=-1
            t=-1
        trend[i]=t
    return trend,choch,lsh,lsl
def rep(name,rows):
    if len(rows)<15: print(f"  {name:30} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10)
    wins=r[r>0]; loss=r[r<=0]; pf=(wins.sum()/abs(loss.sum())) if len(loss) and loss.sum() else 9
    med=np.median(r); flag="🟢🟢" if(r.sum()>0 and srt[:-cut].sum()>0 and pf>1.15) else("🟡" if r.sum()>0 else "🔴")
    print(f"  {name:30} n={len(r):4} WR{100*(r>0).mean():2.0f}% МЕД{med:+.2f}% сум{r.sum():+.0f}% PF{pf:.2f} безтоп10%{srt[:-cut].sum():+.0f}% {flag}")

t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>10000 ORDER BY n DESC LIMIT 50",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · 1h вход(CHoCH) + 4h HTF-тренд + TSL за свинг")
# гипотезы
A=[]; B=[]; Cc=[]  # A=nested cont (HTF+LTF choch, TSL), B=+WT timing, Cc=reversal (LTF choch против HTF на экстремуме)
for sym in syms:
    d1=load(sym,"1h",t0); d4=load(sym,"4h",t0)
    if len(d1)<800 or len(d4)<200: continue
    d1=d1.reset_index(drop=True); d4=d4.reset_index(drop=True)
    tr1,ch1,lsh1,lsl1=structure(d1,4); w=wt(d1)
    tr4,ch4,_,_=structure(d4,4)
    d4c=d4.copy(); d4c["t4"]=tr4; d4c["time"]=d4c["time"]+4*3600*1000  # causal HTF
    m=pd.merge_asof(d1[["time"]],d4c[["time","t4"]],on="time",direction="backward"); T4=m["t4"].fillna(0).values
    C=d1.close.values; L=d1.low.values; H=d1.high.values; yr=pd.to_datetime(d1.time,unit="ms").dt.year.values; N=len(d1)
    def ride(i,side,trailarr):
        e=C[i]; j=i+1
        while j<min(i+200,N):
            if side>0 and C[j]<trailarr[j]: break
            if side<0 and C[j]>trailarr[j]: break
            j+=1
        j=min(j,N-1); return (side*(C[j]-e)/e*100-COST)
    for i in range(30,N-1):
        y=int(yr[i])
        # A: nested continuation — 4h тренд UP + 1h свежий CHoCH UP → LONG, TSL=последний свинг-лоу
        if T4[i]>0 and ch1[i]==1:
            A.append((y,ride(i,1,lsl1)))
        if T4[i]<0 and ch1[i]==-1:
            A.append((y,ride(i,-1,lsh1)))
        # B: + WT-тайминг (вход на откате: WT в сторону вопреки, т.е. не перекуплен)
        if T4[i]>0 and ch1[i]==1 and w[i]<40:
            B.append((y,ride(i,1,lsl1)))
        if T4[i]<0 and ch1[i]==-1 and w[i]>-40:
            B.append((y,ride(i,-1,lsh1)))
        # C: reversal — 1h CHoCH ПРОТИВ 4h на WT-экстремуме (лови разворот), TSL за свинг
        if T4[i]<0 and ch1[i]==1 and w[i]<-50:
            Cc.append((y,ride(i,1,lsl1)))
        if T4[i]>0 and ch1[i]==-1 and w[i]>50:
            Cc.append((y,ride(i,-1,lsh1)))
for lbl,rows in [("A nested-cont ВСЕ",A),("  2024",[x for x in A if x[0]==2024]),("  2025-26",[x for x in A if x[0]>=2025]),
                 ("B +WT-тайминг ВСЕ",B),("  2024 ",[x for x in B if x[0]==2024]),("  2025-26 ",[x for x in B if x[0]>=2025]),
                 ("C reversal ВСЕ",Cc),("  2024  ",[x for x in Cc if x[0]==2024]),("  2025-26  ",[x for x in Cc if x[0]>=2025])]:
    rep(lbl,rows)
