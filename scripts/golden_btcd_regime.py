# -*- coding: utf-8 -*-
"""ЗАГАДКА РЕЖИМА: почему фейд мёртв в 2024 и жив в 2025-26?
Гипотеза DeepSeek: Δ доминации BTC за 7д. BTC.D исторически нет → строю ПРОКСИ из кэша:
  rel_btc_7d = доходность BTC за 7д − МЕДИАННАЯ доходность альтов за 7д.
  >0 = капитал в BTC (risk-off, чоп) → фейд работает. <0 = альт-сезон (тренды) → фейд мёртв.
Причинно: считается по ЗАКРЫТЫМ барам, сдвиг на 1 бар. База: BIG-FLUSH 15m LONG, ликвид, косты 0.25."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.25
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
def sim(i,H,L,C,sl,ttl=24):
    e=C[i]; tp=e+(e-sl); end=min(i+ttl,len(C)-1)
    for j in range(i+1,end+1):
        if L[j]<=sl:return(sl-e)/e*100-COST
        if H[j]>=tp:return(tp-e)/e*100-COST
    return (C[end]-e)/e*100-COST
def rep(name,rows,months=29.0):
    if len(rows)<30: print(f"    {name:36} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    y=lambda yy:[x[1] for x in rows if x[0]==yy]; fmt=lambda a: f"{np.median(a):+.2f}" if len(a)>20 else " ?  "
    fr=len(r)/len(coins)/months; pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    ok=med>0.02 and srt[:-cut].sum()>0 and pf>1.05
    print(f"    {name:36} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% PF{pf:.2f} безтоп10%{srt[:-cut].sum():+7.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** | 24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>15000 ORDER BY n DESC LIMIT 80",(t0,)).fetchall()]; c.close()
# ── строим прокси доминации BTC на 1h-панели
print("строю прокси BTC.D: доходность BTC 7д − медианная доходность альтов 7д ...")
px={}
for s in syms:
    d=load(s,"1h",t0)
    if len(d)>2000: px[s]=pd.Series(d.close.values,index=d.time.values)
panel=pd.DataFrame(px).sort_index()
btc=[s for s in panel.columns if s.startswith("BTC/")]
if not btc: print("нет BTC"); sys.exit()
btc=btc[0]
ret7=panel.pct_change(168)                      # 7 дней = 168 часов
alt=ret7.drop(columns=[btc]).median(axis=1)
rel=(ret7[btc]-alt)*100                          # % опережения BTC
rel=rel.shift(1)                                 # ПРИЧИННО: знаем только прошлый бар
print(f"  прокси: медиана {rel.median():+.2f}%, 2024 {rel[rel.index<1735689600000].median():+.2f}%, "
      f"2025+ {rel[rel.index>=1735689600000].median():+.2f}%")
# ── тест big-flush по режиму
c=sqlite3.connect(DB); syms15=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT 40",(t0,)).fetchall()]; c.close()
turn={};DATA={}
for s in syms15:
    d=load(s,"15m",t0)
    if len(d)>=5000: DATA[s]=d; turn[s]=float(np.nanmedian((d.close*d.volume).values))
mt=np.nanmedian(list(turn.values()))
R={}
for s,d in DATA.items():
    if turn[s]<mt: continue
    w=wt(d); a=atrt(d); H=d.high.values; L=d.low.values; C=d.close.values; T=d.time.values
    yr=pd.to_datetime(d.time,unit="ms").dt.year.values
    rv=pd.merge_asof(pd.DataFrame({"time":T}),pd.DataFrame({"time":rel.index.values,"v":rel.values}).dropna(),
                     on="time",direction="backward")["v"].values
    for i in range(60,len(d)-1):
        if not (a[i]>0 and w[i]<-60 and w[i]>w[i-1]): continue
        e=C[i]; sl=L[max(0,i-3):i+1].min()*0.997
        if not (sl<e and (e-sl)/e*100>4.0): continue
        p=sim(i,H,L,C,sl); y=int(yr[i])
        R.setdefault("ВСЕ",[]).append((y,p,s))
        if np.isnan(rv[i]): continue
        k=("BTC опережает >+2% (risk-off)" if rv[i]>2 else
           ("альты опережают <-2% (альт-сезон)" if rv[i]<-2 else "нейтрально ±2%"))
        R.setdefault(k,[]).append((y,p,s))
        R.setdefault("порог DS: BTC>+0.5%" if rv[i]>0.5 else "порог DS: BTC<+0.5%",[]).append((y,p,s))
print("\n  ═══ BIG-FLUSH LONG × режим доминации BTC (прокси, causal) ═══")
for k in ("ВСЕ","BTC опережает >+2% (risk-off)","нейтрально ±2%","альты опережают <-2% (альт-сезон)"): rep(k,R.get(k,[]))
print("\n  ── порог DeepSeek (±0.5%) ──")
for k in ("порог DS: BTC>+0.5%","порог DS: BTC<+0.5%"): rep(k,R.get(k,[]))
