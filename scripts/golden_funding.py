# -*- coding: utf-8 -*-
"""FUNDING: (A) как СТОИМОСТЬ удержания — влияет ли на уже найденные вердикты (корректность!)
(B) как ПРИЗНАК ДИСЛОКАЦИИ — экстремальный funding = толпа не на той стороне = топливо фейду.
Данные: funding_rates 450 монет 2022-2026 (1.56M строк) — реальная история, не форвард.
База: BIG-FLUSH 15m (ATRTrend↑ + WT<-60 + стоп>4% → LONG TP1R), ликвидная половина."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.25
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close,volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
def fund(sym,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,rate,interval_hours FROM funding_rates WHERE symbol=? AND time>=? ORDER BY time",c,params=(sym,t0)); c.close(); return df.reset_index(drop=True)
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
def sim(i,H,L,C,sl,ttl):
    """возвращает (pnl%, баров в позиции) БЕЗ костов"""
    e=C[i]; tp=e+(e-sl); end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if L[j]<=sl: return (sl-e)/e*100, j-i
        if H[j]>=tp: return (tp-e)/e*100, j-i
    return (C[end]-e)/e*100, end-i
def rep(name,rows,months=29.0):
    if len(rows)<30: print(f"    {name:34} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    y=lambda yy:[x[1] for x in rows if x[0]==yy]; fmt=lambda a: f"{np.median(a):+.2f}" if len(a)>20 else " ?  "
    fr=len(r)/len(coins)/months; pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    ok=med>0.02 and srt[:-cut].sum()>0 and pf>1.05
    print(f"    {name:34} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% PF{pf:.2f} безтоп10%{srt[:-cut].sum():+7.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** | 24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT 40",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · BIG-FLUSH 15m × funding (история 2022-2026)\n")
turn={};DATA={}
for s in syms:
    d=load(s,"15m",t0)
    if len(d)>=5000: DATA[s]=d; turn[s]=float(np.nanmedian((d.close*d.volume).values))
mt=np.nanmedian(list(turn.values()))
R={}; fund_stats=[]
for s,d in DATA.items():
    if turn[s]<mt: continue                     # только ликвидная половина
    fr=fund(s,t0)
    if len(fr)<100: continue
    w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values; T=d.time.values
    yr=pd.to_datetime(d.time,unit="ms").dt.year.values
    # текущая ставка + её процентиль по монете (causal: расширяющееся окно)
    fr["pct"]=fr["rate"].expanding(min_periods=50).rank(pct=True)
    fj=pd.merge_asof(pd.DataFrame({"time":T}),fr[["time","rate","pct","interval_hours"]],on="time",direction="backward")
    rate=fj["rate"].values; pct=fj["pct"].values; ivl=fj["interval_hours"].fillna(8).values
    for i in range(60,len(d)-1):
        if not (a[i]>0 and w[i]<-60 and w[i]>w[i-1]): continue
        e=C[i]; sl=L[max(0,i-3):i+1].min()*0.997
        if not (sl<e and (e-sl)/e*100>4.0): continue
        pnl,bars=sim(i,H,L,C,sl,24); y=int(yr[i])
        hours=bars*0.25
        fcost=0.0
        if not np.isnan(rate[i]) and ivl[i]>0:
            fcost=abs(rate[i])*100*(hours/ivl[i])*np.sign(rate[i])   # лонг платит при rate>0
        R.setdefault("A) база (косты 0.25)",[]).append((y,pnl-COST,s))
        R.setdefault("A) + funding как стоимость",[]).append((y,pnl-COST-fcost,s))
        fund_stats.append((fcost,hours))
        if not np.isnan(pct[i]):
            k=("B) funding НИЗКИЙ (<20%: шорты платят)" if pct[i]<0.2 else
               ("B) funding ВЫСОКИЙ (>80%: лонги платят)" if pct[i]>0.8 else "B) funding середина"))
            R.setdefault(k,[]).append((y,pnl-COST-fcost,s))
if fund_stats:
    fc=np.array([x[0] for x in fund_stats]); hh=np.array([x[1] for x in fund_stats])
    print(f"  стоимость фондирования на сделку: медиана {np.median(fc):+.4f}%, ср {fc.mean():+.4f}%, "
          f"макс {fc.max():+.3f}% · медиана удержания {np.median(hh):.1f}ч\n")
print("  ═══ A) FUNDING КАК СТОИМОСТЬ (меняет ли вердикт?) ═══")
for k in ("A) база (косты 0.25)","A) + funding как стоимость"): rep(k,R.get(k,[]))
print("\n  ═══ B) FUNDING КАК ПРИЗНАК ДИСЛОКАЦИИ (процентиль по монете, causal) ═══")
for k in ("B) funding НИЗКИЙ (<20%: шорты платят)","B) funding середина","B) funding ВЫСОКИЙ (>80%: лонги платят)"): rep(k,R.get(k,[]))
