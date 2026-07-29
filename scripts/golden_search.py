# -*- coding: utf-8 -*-
"""GOLDEN SEARCH (Егор 30.07 «найди золотую стратегию») — дисциплинированный MTF-бэктест.
ЗАКОН: % net с костами · МЕДИАНА не среднее · хрупкость (топ-3 винера) · OOS-сплит.
Выход по КАСАНИЮ (стоп на линию=свип). Косты 0.10% round-trip."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")

DB="ohlcv_cache.db"; COST=0.10
def load(sym,tf,t0):
    c=sqlite3.connect(DB)
    df=pd.read_sql("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",
                   c,params=(sym,tf,t0)); c.close(); return df

def wt(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3
    esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    ci=(hlc-esa)/(0.015*d.replace(0,np.nan)); tci=ci.ewm(span=n2).mean()
    return tci.fillna(0)  # wt1

def atrtrend(df,period=43,factor=1.25):
    h,l,c=df.high,df.low,df.close; hl2=(h+l)/2
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.rolling(period).mean(); up=hl2-factor*atr; dn=hl2+factor*atr
    tu=up.copy(); td=dn.copy(); tr_=np.ones(len(df))
    up_v=up.values; dn_v=dn.values; hl2_v=hl2.values
    tuv=up_v.copy(); tdv=dn_v.copy()
    for i in range(1,len(df)):
        tuv[i]=max(up_v[i],tuv[i-1]) if hl2_v[i-1]>tuv[i-1] else up_v[i]
        tdv[i]=min(dn_v[i],tdv[i-1]) if hl2_v[i-1]<tdv[i-1] else dn_v[i]
        tr_[i]=1 if hl2_v[i]>tdv[i-1] else (-1 if hl2_v[i]<tuv[i-1] else tr_[i-1])
    return pd.Series(tr_,index=df.index)

def sim(entries, df1h, side, sl_arr, tp_arr, ttl=48):
    """entries=idx список. Выход по касанию low/high на след барах. → net% list."""
    H=df1h.high.values; L=df1h.low.values; C=df1h.close.values; res=[]
    for i,sl,tp in zip(entries,sl_arr,tp_arr):
        e=C[i]; end=min(i+ttl,len(df1h)-1); out=None
        for j in range(i+1,end+1):
            if side>0:
                if L[j]<=sl: out=(sl-e)/e; break
                if H[j]>=tp: out=(tp-e)/e; break
            else:
                if H[j]>=sl: out=(e-sl)/e; break
                if L[j]<=tp: out=(e-tp)/e; break
        if out is None: out=side*(C[end]-e)/e
        res.append(out*100-COST)
    return res

def report(name,r):
    if len(r)<20: print(f"  {name:34} n={len(r)} мало"); return None
    r=np.array(r); tot=r.sum(); med=np.median(r); avg=r.mean()
    wr=100*(r>0).mean(); srt=np.sort(r); frag=srt[:-3].sum() if len(srt)>3 else tot
    flag="🟢" if (med>0 and frag>0) else ("🟡" if avg>0 else "🔴")
    print(f"  {name:34} n={len(r):4} WR{wr:2.0f}% avg{avg:+.3f}% МЕД{med:+.3f}% сум{tot:+.0f}% без_топ3{frag:+.0f}% {flag}")
    return dict(n=len(r),med=med,avg=avg,frag=frag)

t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
split=int(dt.datetime(2025,7,1,tzinfo=dt.timezone.utc).timestamp()*1000)  # OOS: train<split, test>=split
c=sqlite3.connect(DB)
syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? GROUP BY symbol HAVING n>10000 ORDER BY n DESC LIMIT 60",(t0,)).fetchall()]; c.close()
print(f"монет: {len(syms)} · окно 2024-2026 · OOS-сплит 2025-07")

# копим сделки по гипотезам
H={"H1_cont_pullback_LONG":[], "H1_cont_pullback_SHORT":[], "H3_meanrev_LONG":[], "H3_meanrev_SHORT":[]}
Hoos={k:[] for k in H}
for sym in syms:
    d1=load(sym,"1h",t0); d4=load(sym,"4h",t0)
    if len(d1)<500 or len(d4)<200: continue
    d1=d1.reset_index(drop=True)
    w=wt(d1).values; at1=atrtrend(d1).values
    # 4h ATRTrend спроецировать на 1h по времени (merge_asof, causal)
    d4=d4.reset_index(drop=True); d4["at4"]=atrtrend(d4).values
    # ПРИЧИННЫЙ HTF (фикс класс-3 look-ahead): берём 4h бар, ЗАКРЫТЫЙ до текущего 1h.
    d4c=d4.copy(); d4c["time"]=d4c["time"]+4*3600*1000  # close-time 4h бара
    m=pd.merge_asof(d1[["time"]], d4c[["time","at4"]], on="time", direction="backward")
    at4=m["at4"].values
    C=d1.close.values; L=d1.low.values; Hh=d1.high.values; T=d1.time.values
    for i in range(50,len(d1)-1):
        oos = T[i]>=split
        # H1: континуация — 4h тренд UP, WT откатился<-35 и кросс вверх (w[i]>w[i-1] и w[i-1]<-35)
        if at4[i]>0 and w[i-1]<-35 and w[i]>w[i-1] and w[i]>-60:
            e=C[i]; sl=min(L[i-3:i+1])*0.999; tp=e+2*(e-sl)
            (Hoos if oos else H)["H1_cont_pullback_LONG"].append((sym,i,d1,1,sl,tp))
        if at4[i]<0 and w[i-1]>35 and w[i]<w[i-1] and w[i]<60:
            e=C[i]; sl=max(Hh[i-3:i+1])*1.001; tp=e-2*(sl-e)
            (Hoos if oos else H)["H1_cont_pullback_SHORT"].append((sym,i,d1,-1,sl,tp))
        # H3: мин-реверсия — WT очень перепродан <-65, 4h НЕ сильный вниз (at4>=0), цель 1R
        if w[i]<-65 and at4[i]>=0:
            e=C[i]; sl=min(L[i-5:i+1])*0.997; tp=e+1.0*(e-sl)
            (Hoos if oos else H)["H3_meanrev_LONG"].append((sym,i,d1,1,sl,tp))
        if w[i]>65 and at4[i]<=0:
            e=C[i]; sl=max(Hh[i-5:i+1])*1.003; tp=e-1.0*(sl-e)
            (Hoos if oos else H)["H3_meanrev_SHORT"].append((sym,i,d1,-1,sl,tp))

def run(store,label):
    print(f"\n=== {label} ===")
    for k,items in store.items():
        if not items: continue
        # группируем по df (симулируем на каждом df)
        r=[]
        bydf={}
        for sym,i,df,side,sl,tp in items: bydf.setdefault(id(df),(df,[])); bydf[id(df)][1].append((i,side,sl,tp))
        for _,(df,lst) in bydf.items():
            idx=[x[0] for x in lst]; sd=lst[0][1]; sls=[x[2] for x in lst]; tps=[x[3] for x in lst]
            r+=sim(idx,df,sd,sls,tps)
        report(k,r)

run(H,"IN-SAMPLE (train 2024..2025-06)")
run(Hoos,"OUT-OF-SAMPLE (test 2025-07..2026)")
