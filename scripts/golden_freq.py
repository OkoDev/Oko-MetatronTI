# -*- coding: utf-8 -*-
"""ЧАСТЫЕ ПОВТОРЕНИЯ (Егор 30.07 «чем чаще повторение тем ближе цель»).
Ядро (ATRTrend↑ + глубокий WT-откат → LONG TP1R) на БЫСТРЫХ ТФ: 15m/1h/4h × порог WT.
Метрика цели: ОЖИДАЕМЫЙ %/мес = частота(сд/монету/мес) × медиана net%. Косты 0.15 (на 15m кусают сильнее).
Прокурор: медиана, оба года, безтоп10%, охват монет, частота."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
BARS={"15m":15,"1h":60,"4h":240}
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
def wt(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    return ((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0).values
def atrt(df,period=43,factor=1.25):
    h,l,c=df.high,df.low,df.close; hl2=((h+l)/2).values
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean()
    up=(hl2-factor*atr.values); dn=(hl2+factor*atr.values); tu=up.copy(); td=dn.copy(); tr_=np.ones(len(hl2))
    for i in range(1,len(hl2)):
        tu[i]=max(up[i],tu[i-1]) if hl2[i-1]>tu[i-1] else up[i]; td[i]=min(dn[i],td[i-1]) if hl2[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hl2[i]>td[i-1] else(-1 if hl2[i]<tu[i-1] else tr_[i-1])
    return tr_
def simTP(i,H,L,C,sl,tp,ttl):
    e=C[i]; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if L[j]<=sl: return (sl-e)/e*100-COST
        if H[j]>=tp: return (tp-e)/e*100-COST
    return (C[end]-e)/e*100-COST
def rep(name,rows,months):
    if len(rows)<30: print(f"  {name:22} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    freq=len(r)/len(coins)/months           # сделок на монету в месяц
    exp_m=freq*med                          # ОЖИДАЕМЫЙ % в месяц на монету
    y24=[x[1] for x in rows if x[0]==2024]; y25=[x[1] for x in rows if x[0]>=2025]
    b24=f"{np.median(y24):+.2f}" if len(y24)>15 else "  ?  "; b25=f"{np.median(y25):+.2f}" if len(y25)>15 else "  ?  "
    ok=med>0.02 and srt[:-cut].sum()>0 and (len(y24)<15 or np.median(y24)>0) and (len(y25)<15 or np.median(y25)>0)
    flag="🟢🟢" if ok else("🟡" if r.mean()>0 else "🔴")
    print(f"  {name:22} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% безтоп10%{srt[:-cut].sum():+6.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {freq:5.2f} сд/мес → **{exp_m:+.2f}%/мес** | 24:{b24} 25:{b25} {flag}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
MONTHS=29.0   # янв2024 → май2026
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? GROUP BY symbol HAVING n>60000 ORDER BY n DESC LIMIT 45",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · ЯДРО на разных ТФ × порог WT · цель = ЧАСТОТА × МЕДИАНА\n")
for tf,ttl in (("15m",24),("1h",18),("4h",18)):
    res={}
    for sym in syms:
        d=load(sym,tf,t0)
        if len(d)<2000: continue
        w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values
        yr=pd.to_datetime(d.time,unit="ms").dt.year.values; N=len(d)
        for thr in (-50,-60,-70):
            key=f"WT<{thr}"; res.setdefault(key,[])
            for i in range(60,N-1):
                if not (a[i]>0 and w[i]<thr and w[i]>w[i-1]): continue
                sl=L[max(0,i-3):i+1].min()*0.997
                if sl>=C[i]: continue
                res[key].append((int(yr[i]),simTP(i,H,L,C,sl,C[i]+(C[i]-sl),ttl),sym))
    print(f"═══ {tf} (TTL {ttl} баров) ═══")
    for k in (f"WT<{t}" for t in (-50,-60,-70)): rep(k,res.get(k,[]),MONTHS)
    print()
