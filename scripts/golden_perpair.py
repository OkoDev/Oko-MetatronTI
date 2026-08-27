# -*- coding: utf-8 -*-
"""ТРИ ТЕСТА (30.07): A) per-pair ATRTrend от нормированной волатильности (DeepSeek, причинно)
B) survivorship-прокси (ликвидные vs неликвидные + виртуальный делистинг)
C) SHORT-родственник × режим USDT.D (предохранитель по доминации).
Ядро: 4h ATRTrend + WT-порог → TP1R. Косты 0.15. Прокурор: медиана+годы+безтоп10%+охват+частота."""
import sqlite3, sys, math, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15; rng=np.random.default_rng(7)
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close,volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
def wt(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    return ((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0).values
def atr_n(df,n=14):
    h,l,c=df.high,df.low,df.close
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return (tr.rolling(n).mean()/c).values      # НОРМИРОВАННЫЙ ATR (%) — сравним между монетами
def atrt(df,period,factor):
    h,l,c=df.high,df.low,df.close; hl2=((h+l)/2).values
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(int(period)).mean().values
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
def rep(name,rows,months=None):
    if len(rows)<25: print(f"  {name:30} n={len(rows)}"); return None
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    y24=[x[1] for x in rows if x[0]==2024]; y25=[x[1] for x in rows if x[0]>=2025]
    b24=f"{np.median(y24):+.2f}" if len(y24)>15 else " ?  "; b25=f"{np.median(y25):+.2f}" if len(y25)>15 else " ?  "
    ok=med>0.02 and srt[:-cut].sum()>0
    extra=""
    if months: extra=f" | {len(r)/len(coins)/months:4.2f} сд/мес → {len(r)/len(coins)/months*med:+.2f}%/мес"
    print(f"  {name:30} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% безтоп10%{srt[:-cut].sum():+6.0f}% "
          f"монет+{pos:2}/{len(coins):2}{extra} | 24:{b24} 25:{b25} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
    return med
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>2500 ORDER BY n DESC LIMIT 60",(t0,)).fetchall()]; c.close()
btc=[s for s in syms if "BTC/" in s]; btc=btc[0] if btc else syms[0]
db=load(btc,"4h",t0); TRAIN=90*6   # 90 дней = 540 баров 4h — окно калибровки (потом только OOS)
atrn_btc=np.nanmedian(atr_n(db)[:TRAIN])
print(f"монет {len(syms)} · эталон {btc} нормATR={atrn_btc:.4f} · калибровка на первых 90д, торговля ПОСЛЕ (OOS)\n")
FIX=[];PP=[];LIQ={"ликвидные":[],"неликвидные":[]};SH={"USDTD↑ risk-off":[],"USDTD↓ risk-on":[]}
# режим USDT.D (дневной, причинно: сравнение с SMA20 по ЗАКРЫТЫМ дням)
cu=sqlite3.connect(DB); du=pd.read_sql("SELECT time,close FROM usdtd ORDER BY time",cu); cu.close()
du["sma"]=du.close.rolling(20).mean(); du["up"]=(du.close>du.sma).astype(int)
du["time"]=du["time"]+24*3600000     # доступно только со следующего дня
turn={}
for sym in syms:
    d=load(sym,"4h",t0)
    if len(d)<TRAIN+300: continue
    turn[sym]=float(np.nanmedian((d.close*d.volume).values))
med_turn=np.nanmedian(list(turn.values()))
for sym in syms:
    d=load(sym,"4h",t0)
    if len(d)<TRAIN+300 or sym not in turn: continue
    an=atr_n(d); atrn_i=np.nanmedian(an[:TRAIN])
    if not (atrn_i>0): continue
    ratio=atrn_i/atrn_btc
    period=int(min(100,max(10,round(43*(atrn_btc/atrn_i))))); factor=min(2.0,max(0.8,1.25*(1+math.log(ratio))))
    w=wt(d); a_fix=atrt(d,43,1.25); a_pp=atrt(d,period,factor)
    H=d.high.values; L=d.low.values; C=d.close.values; yr=pd.to_datetime(d.time,unit="ms").dt.year.values
    reg=pd.merge_asof(d[["time"]],du[["time","up"]],on="time",direction="backward")["up"].values
    liq="ликвидные" if turn[sym]>=med_turn else "неликвидные"
    for i in range(TRAIN,len(d)-1):
        y=int(yr[i]); sl_l=L[max(0,i-3):i+1].min()*0.997; sl_s=H[max(0,i-3):i+1].max()*1.003
        deep=w[i]<-60 and w[i]>w[i-1]
        if deep and sl_l<C[i]:
            tp=C[i]+(C[i]-sl_l)
            if a_fix[i]>0:
                p=sim(i,H,L,C,1,sl_l,tp); FIX.append((y,p,sym)); LIQ[liq].append((y,p,sym))
            if a_pp[i]>0: PP.append((y,sim(i,H,L,C,1,sl_l,tp),sym))
        # C) SHORT-родственник: даунтренд + WT перекуплен, разрез по режиму USDT.D
        if a_fix[i]<0 and w[i]>60 and w[i]<w[i-1] and sl_s>C[i] and not np.isnan(reg[i]):
            p=sim(i,H,L,C,-1,sl_s,C[i]-(sl_s-C[i]))
            SH["USDTD↑ risk-off" if reg[i]==1 else "USDTD↓ risk-on"].append((y,p,sym))
M=29.0
print("═══ A) PER-PAIR ATRTrend (DeepSeek: period=43·ATRbtc/ATRi, factor=1.25·(1+ln ratio)) ═══")
m1=rep("фикс 43/1.25 (эталон)",FIX,M); m2=rep("per-pair (от волатильности)",PP,M)
if m1 and m2: print(f"  → вклад per-pair: {m2-m1:+.3f}% медианы ({'ЛУЧШЕ' if m2>m1 else 'ХУЖЕ'})")
print("\n═══ B) SURVIVORSHIP-ПРОКСИ (разрез по обороту) ═══")
ml=rep("ликвидная половина",LIQ["ликвидные"],M); mi=rep("НЕликвидная половина",LIQ["неликвидные"],M)
if ml and mi:
    print(f"  → разрыв ликвидность: {ml-mi:+.3f}% медианы = нижняя оценка раздувания на выживших")
    ill=[x[1] for x in LIQ["неликвидные"]]
    kill=rng.choice(len(ill),max(1,len(ill)//10),replace=False)
    stressed=[(-100.0 if k in set(kill) else v) for k,v in enumerate(ill)]
    print(f"  → виртуальный делистинг 10% неликвида: сумма {sum(ill):+.0f}% → {sum(stressed):+.0f}% "
          f"(медиана {np.median(ill):+.2f}% → {np.median(stressed):+.2f}%)")
print("\n═══ C) SHORT-РОДСТВЕННИК × РЕЖИМ USDT.D (данные с 09.2025) ═══")
for k in SH: rep(k,SH[k],10.0)
