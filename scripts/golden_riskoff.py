# -*- coding: utf-8 -*-
"""ПРОКСИ RISK-OFF из кэша (2024-26) + SHORT-родственник на полной истории.
Идея: когда альты падают СИНХРОННО — деньги уходят в стейблы = USDT.D↑ = risk-off.
Прокси = доля монет с ATRTrend↓ (breadth) + медианная 24ч доходность. Валидирую о настоящий usdtd (10 мес).
Затем: 4h SHORT-фейд (ATRTrend↓ + WT>+60) × режим прокси на ПОЛНОЙ истории. Причинно (сдвиг на бар)."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
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
def sim(i,H,L,C,side,sl,tp,ttl=18):
    e=C[i]; end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=sl:return(sl-e)/e*100-COST
            if H[j]>=tp:return(tp-e)/e*100-COST
        else:
            if H[j]>=sl:return(e-sl)/e*100-COST
            if L[j]<=tp:return(e-tp)/e*100-COST
    return side*(C[end]-e)/e*100-COST
def rep(name,rows,months):
    if len(rows)<25: print(f"  {name:30} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    y24=[x[1] for x in rows if x[0]==2024]; y25=[x[1] for x in rows if x[0]>=2025]
    b24=f"{np.median(y24):+.2f}" if len(y24)>15 else " ?  "; b25=f"{np.median(y25):+.2f}" if len(y25)>15 else " ?  "
    fr=len(r)/len(coins)/months
    ok=med>0.02 and srt[:-cut].sum()>0 and (len(y24)<15 or np.median(y24)>0) and (len(y25)<15 or np.median(y25)>0)
    print(f"  {name:30} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% безтоп10%{srt[:-cut].sum():+6.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:4.2f}сд/мес → **{fr*med:+.2f}%/мес** | 24:{b24} 25:{b25} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>2500 ORDER BY n DESC LIMIT 60",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)}")
# --- шаг 1: собираем панель тренда/WT + строим breadth-прокси
D={}
for s in syms:
    d=load(s,"4h",t0)
    if len(d)<400: continue
    D[s]=(d,wt(d),atrt(d))
idx=sorted(set().union(*[set(v[0].time.values) for v in D.values()]))
panel=pd.DataFrame(index=idx)
for s,(d,w,a) in D.items(): panel[s]=pd.Series(a,index=d.time.values)
breadth=(panel<0).sum(axis=1)/panel.notna().sum(axis=1)   # доля монет в даунтренде
breadth=breadth.shift(1)                                   # ПРИЧИННО: знаем только прошлый бар
print(f"breadth (доля монет в даунтренде): медиана {breadth.median():.2f}, 20%={breadth.quantile(0.2):.2f}, 80%={breadth.quantile(0.8):.2f}")
# --- шаг 2: валидация прокси о настоящий USDT.D
cu=sqlite3.connect(DB); du=pd.read_sql("SELECT time,close FROM usdtd ORDER BY time",cu); cu.close()
du["sma"]=du.close.rolling(20).mean(); du=du.dropna()
bd=breadth.dropna(); bser=pd.Series(bd.values,index=pd.to_datetime(bd.index,unit="ms")).resample("1D").mean()
user=pd.Series((du.close/du.sma).values,index=pd.to_datetime(du.time,unit="ms"))
j=pd.concat([bser.rename("breadth"),user.rename("usdtd_rel")],axis=1).dropna()
if len(j)>30: print(f"валидация прокси: corr(breadth, USDT.D/SMA20) = {j.breadth.corr(j.usdtd_rel):+.3f} на n={len(j)} дней")
# --- шаг 3: SHORT-родственник × режим прокси, полная история
hi=breadth.quantile(0.7); lo=breadth.quantile(0.3)
R={"risk-off (breadth высокий)":[],"середина":[],"risk-on (breadth низкий)":[]}
LNG={"risk-off (breadth высокий)":[],"risk-on (breadth низкий)":[]}
for s,(d,w,a) in D.items():
    H=d.high.values; L=d.low.values; C=d.close.values; T=d.time.values
    yr=pd.to_datetime(d.time,unit="ms").dt.year.values; b=breadth.reindex(T).values
    for i in range(60,len(d)-1):
        if np.isnan(b[i]): continue
        k="risk-off (breadth высокий)" if b[i]>=hi else("risk-on (breadth низкий)" if b[i]<=lo else "середина")
        y=int(yr[i])
        if a[i]<0 and w[i]>60 and w[i]<w[i-1]:              # SHORT-фейд
            sl=H[max(0,i-3):i+1].max()*1.003
            if sl>C[i]: R[k].append((y,sim(i,H,L,C,-1,sl,C[i]-(sl-C[i])),s))
        if a[i]>0 and w[i]<-60 and w[i]>w[i-1] and k in LNG: # LONG-ядро для сравнения по режиму
            sl=L[max(0,i-3):i+1].min()*0.997
            if sl<C[i]: LNG[k].append((y,sim(i,H,L,C,1,sl,C[i]+(C[i]-sl)),s))
print("\n═══ SHORT-фейд (4h ATRTrend↓ + WT>+60) × режим breadth, ПОЛНАЯ история ═══")
for k in ("risk-off (breadth высокий)","середина","risk-on (breadth низкий)"): rep(k,R[k],29.0)
print("\n═══ LONG-ядро в тех же режимах (проверка симметрии) ═══")
for k in LNG: rep("LONG "+k,LNG[k],29.0)
