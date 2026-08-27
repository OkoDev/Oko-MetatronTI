# -*- coding: utf-8 -*-
"""MTF-КОНФЛЮЭНЦИЯ НА НАСТОЯЩЕМ SMC (Егор 05.08) — впервые: SMC участвует в бэктесте эджа.
База: BIG-FLUSH 15m (ATRTrend↑ + WT<-60 + стоп>4% → LONG TP1R), ликвидная половина, косты 0.25.
На КАЖДОМ сигнале причинно считаем (окно только до сигнала включительно):
  SMC 15m/1h/4h: активный бычий OB под ценой · бычий FVG · структурный тренд
  Пивоты: близость к недельной/дневной поддержке
Конфлюэнция как СКОР (жёсткий гейт уже опровергнут). Плюс вклад КАЖДОГО фактора отдельно."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
warnings.filterwarnings("ignore")
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
from core.smc.structure import detect_structure
from core.smc.order_blocks import detect_order_blocks
from core.smc.fvg import detect_fvg
DB="ohlcv_cache.db"; COST=0.25
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
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
def smc_flags(df_slice,price):
    """Причинно: окно ДО сигнала включительно. Возвращает (есть бычий OB под ценой, бычий FVG, тренд UP)."""
    out={"ob":0,"fvg":0,"up":0}
    try:
        st=detect_structure(df_slice)
        tr=str(getattr(st,"trend","") or "").upper()
        out["up"]=1 if ("UP" in tr or "BULL" in tr) else 0
        obs=detect_order_blocks(df_slice,st)
        for ob in (getattr(obs,"active_bull",None) or []):
            if ob.bottom<=price<=ob.top*1.02 or (0<price-ob.top<price*0.02):
                out["ob"]=1; break
    except Exception: pass
    try:
        fv=detect_fvg(df_slice)
        for g in (getattr(fv,"active_bull",None) or getattr(fv,"bullish",None) or []):
            top=getattr(g,"top",None); bot=getattr(g,"bottom",None)
            if top and bot and (bot<=price<=top*1.02 or 0<price-top<price*0.02):
                out["fvg"]=1; break
    except Exception: pass
    return out
def wk_piv(d1h):
    s=d1h.set_index(pd.to_datetime(d1h.time,unit="ms"))
    w=s.resample("W-MON",label="left",closed="left").agg({"high":"max","low":"min","close":"last"}).dropna()
    pp=(w.high+w.low+w.close)/3; s1=2*pp-w.high; s2=pp-(w.high-w.low)
    av=w.index+pd.Timedelta(days=7)
    return pd.DataFrame({"time":(av.astype("int64")//10**6).values,"pp":pp.values,"s1":s1.values,"s2":s2.values})
def rep(name,rows):
    if len(rows)<25: print(f"    {name:32} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    coins=set(x[2] for x in rows); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    ok=med>0.02 and srt[:-cut].sum()>0 and pf>1.05
    print(f"    {name:32} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:.2f} безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:2}/{len(coins):2} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2025,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? GROUP BY symbol HAVING n>25000 ORDER BY n DESC LIMIT 22",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · период 2025-01→2026-05 · SMC считается ПРИЧИННО на каждом сигнале\n")
ALL=[]; F={}; BYSCORE={}
for si,sym in enumerate(syms):
    d15=load(sym,"15m",t0); d1=load(sym,"1h",t0); d4=load(sym,"4h",t0)
    if len(d15)<3000 or len(d1)<800 or len(d4)<200: continue
    w=wt(d15); a=atrt(d15); H=d15.high.values; L=d15.low.values; C=d15.close.values; T=d15.time.values
    wp=wk_piv(d1)
    pv=pd.merge_asof(pd.DataFrame({"time":T}),wp,on="time",direction="backward")
    t1=d1.time.values; t4=d4.time.values
    n_sig=0
    for i in range(80,len(d15)-1):
        if not (a[i]>0 and w[i]<-60 and w[i]>w[i-1]): continue
        e=C[i]; sl=L[max(0,i-3):i+1].min()*0.997
        if not (sl<e and (e-sl)/e*100>4.0): continue
        pnl=sim(i,H,L,C,sl); n_sig+=1
        f15=smc_flags(d15.iloc[max(0,i-200):i+1],e)
        j1=int(np.searchsorted(t1,T[i]))-1; j4=int(np.searchsorted(t4,T[i]))-1
        f1=smc_flags(d1.iloc[max(0,j1-200):j1+1],e) if j1>60 else {"ob":0,"fvg":0,"up":0}
        f4=smc_flags(d4.iloc[max(0,j4-150):j4+1],e) if j4>60 else {"ob":0,"fvg":0,"up":0}
        pw=pv.iloc[i]
        near_piv=0
        for lv in ("pp","s1","s2"):
            v=pw.get(lv)
            if v and v>0 and abs(e-v)/e*100<1.0: near_piv=1; break
        fac={"OB 15m":f15["ob"],"OB 1h":f1["ob"],"OB 4h":f4["ob"],
             "FVG 1h":f1["fvg"],"FVG 4h":f4["fvg"],
             "структура 1h UP":f1["up"],"структура 4h UP":f4["up"],"у нед.пивота":near_piv}
        score=sum(fac.values())
        rec=(0,pnl,sym); ALL.append(rec)
        BYSCORE.setdefault(min(score,4),[]).append(rec)
        for k,v in fac.items(): F.setdefault((k,bool(v)),[]).append(rec)
    print(f"  [{si+1}/{len(syms)}] {sym.split('/')[0]:12} сигналов={n_sig} накоплено={len(ALL)}")
print(f"\n═══ БАЗА ═══"); rep("все сигналы",ALL)
print("\n═══ ПО КОНФЛЮЭНЦИИ (число совпавших факторов) ═══")
for k in sorted(BYSCORE): rep(f"скор {k}{'+' if k==4 else ''}",BYSCORE[k])
print("\n═══ ВКЛАД КАЖДОГО ФАКТОРА (есть vs нет) ═══")
for k in ("OB 15m","OB 1h","OB 4h","FVG 1h","FVG 4h","структура 1h UP","структура 4h UP","у нед.пивота"):
    rep(f"{k}: ЕСТЬ",F.get((k,True),[])); rep(f"{k}: нет",F.get((k,False),[]))
