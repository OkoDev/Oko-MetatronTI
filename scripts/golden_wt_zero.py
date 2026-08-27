# -*- coding: utf-8 -*-
"""WT >0< НУЛЕВАЯ ЛИНИЯ (Егор: «не забывай про WT >0<») — я гонял только экстремумы ±60/70.
Ноль WT = смена импульса. Тест в подтверждённой рамке WPP-направления (Δ5.5% медианы):
  A) вход по КРОССУ WT через 0 в сторону WPP (следование тренду — может быть сильнее флипа WR53%)
  B) вход по флипу ATRTrend, но с ГЕЙТОМ состояния WT>0 (лонг) / WT<0 (шорт)
  C) состояние WT>0/<0 как разделитель для big-flush фейда
SL=swing12 структурный, коридор стопа 2-6%, выходы TP1R и TSL после +1R. Косты 0.15."""
import sqlite3, sys, numpy as np, pandas as pd, datetime as dt
sys.path.insert(0,"."); sys.stdout.reconfigure(encoding="utf-8")
DB="ohlcv_cache.db"; COST=0.15
def load(sym,tf,t0):
    c=sqlite3.connect(DB); df=pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",c,params=(sym,tf,t0)); c.close(); return df.reset_index(drop=True)
def wt_(df,n1=10,n2=21):
    hlc=(df.high+df.low+df.close)/3; esa=hlc.ewm(span=n1).mean(); d=(hlc-esa).abs().ewm(span=n1).mean()
    return ((hlc-esa)/(0.015*d.replace(0,np.nan))).ewm(span=n2).mean().fillna(0).values
def atrt_line(df,period=43,factor=1.25):
    h,l,c=df.high,df.low,df.close; hl2=((h+l)/2).values
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(period).mean().values
    up=hl2-factor*atr; dn=hl2+factor*atr; tu=up.copy(); td=dn.copy(); tr_=np.ones(len(hl2)); line=up.copy()
    for i in range(1,len(hl2)):
        tu[i]=max(up[i],tu[i-1]) if hl2[i-1]>tu[i-1] else up[i]
        td[i]=min(dn[i],td[i-1]) if hl2[i-1]<td[i-1] else dn[i]
        tr_[i]=1 if hl2[i]>td[i-1] else(-1 if hl2[i]<tu[i-1] else tr_[i-1])
        line[i]=tu[i] if tr_[i]>0 else td[i]
    return tr_,line
def wpp_series(d1h):
    s=d1h.set_index(pd.to_datetime(d1h.time,unit="ms"))
    w=s.resample("W-MON",label="left",closed="left").agg({"high":"max","low":"min","close":"last"}).dropna()
    w["wpp"]=(w.high+w.low+w.close)/3; av=w.index+pd.Timedelta(days=7)
    return pd.DataFrame({"time":(av.astype("int64")//10**6).values,"wpp":w["wpp"].values})
def ex(i,side,H,L,C,line,sl0,ttl,mode):
    e=C[i]; r=abs(e-sl0)
    if r<=0: return None
    tp=e+side*r; end=min(i+ttl,len(C)-1); act=False; stop=sl0
    for j in range(i+1,end+1):
        if side>0:
            if L[j]<=stop: return (stop-e)/e*100-COST
            if mode=="tp1r" and H[j]>=tp: return (tp-e)/e*100-COST
            if mode=="tsl":
                if not act and H[j]>=tp: act=True
                if act and line[j]<C[j]: stop=max(stop,line[j])
        else:
            if H[j]>=stop: return (e-stop)/e*100-COST
            if mode=="tp1r" and L[j]<=tp: return (e-tp)/e*100-COST
            if mode=="tsl":
                if not act and L[j]<=tp: act=True
                if act and line[j]>C[j]: stop=min(stop,line[j])
    return side*(C[end]-e)/e*100-COST
def rep(name,rows,months=29.0):
    if len(rows)<30: print(f"    {name:32} n={len(rows)}"); return
    r=np.array([x[1] for x in rows]); srt=np.sort(r); cut=max(1,len(r)//10); med=np.median(r)
    coins=sorted(set(x[2] for x in rows)); pos=sum(1 for cn in coins if np.median([x[1] for x in rows if x[2]==cn])>0)
    y=lambda yy:[x[1] for x in rows if x[0]==yy]; fmt=lambda a: f"{np.median(a):+.2f}" if len(a)>20 else " ?  "
    fr=len(r)/len(coins)/months; pf=(r[r>0].sum()/abs(r[r<0].sum())) if (r<0).any() else 9.9
    ok=med>0.02 and srt[:-cut].sum()>0 and pf>1.05
    print(f"    {name:32} n={len(r):5} WR{100*(r>0).mean():2.0f}% МЕД{med:+.3f}% PF{pf:.2f} сум{r.sum():+6.0f}% безтоп10%{srt[:-cut].sum():+7.0f}% "
          f"монет+{pos:2}/{len(coins):2} | {fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** | 24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} {'🟢🟢' if ok else('🟡' if r.mean()>0 else '🔴')}")
t0=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
c=sqlite3.connect(DB); syms=[r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? GROUP BY symbol HAVING n>2500 ORDER BY n DESC LIMIT 60",(t0,)).fetchall()]; c.close()
print(f"монет {len(syms)} · WT нулевая линия в рамке WPP · 4h · SL swing12 коридор 2-6%\n")
R={}
for s in syms:
    d4=load(s,"4h",t0); d1=load(s,"1h",t0)
    if len(d4)<300 or len(d1)<2000: continue
    wpp=wpp_series(d1)
    if len(wpp)<10: continue
    w=wt_(d4); tre,line=atrt_line(d4); H=d4.high.values; L=d4.low.values; C=d4.close.values; T=d4.time.values
    yr=pd.to_datetime(d4.time,unit="ms").dt.year.values
    wv=pd.merge_asof(pd.DataFrame({"time":T}),wpp,on="time",direction="backward")["wpp"].values
    for i in range(60,len(d4)-1):
        if np.isnan(wv[i]): continue
        bias=1 if C[i]>wv[i] else -1; e=C[i]; y=int(yr[i])
        zx_up = w[i]>0 and w[i-1]<=0        # КРОСС нуля вверх
        zx_dn = w[i]<0 and w[i-1]>=0        # КРОСС нуля вниз
        flip  = tre[i]!=tre[i-1]
        for side,is_zx,zstate in ((1,zx_up,w[i]>0),(-1,zx_dn,w[i]<0)):
            sl0=(L[max(0,i-12):i+1].min()*0.997) if side>0 else (H[max(0,i-12):i+1].max()*1.003)
            dist=abs(e-sl0)/e*100
            if not (2.0<=dist<=6.0): continue
            aligned = side==bias
            for mode,ml in (("tp1r","TP1R"),("tsl","TSL")):
                p=ex(i,side,H,L,C,line,sl0,120,mode)
                if p is None: continue
                rec=(y,p,s)
                if is_zx:
                    R.setdefault((f"A) кросс WT нуля {ml}","всё"),[]).append(rec)
                    R.setdefault((f"A) кросс WT нуля {ml}","по WPP" if aligned else "против WPP"),[]).append(rec)
                if flip and aligned:
                    R.setdefault((f"B) флип+WPP {ml}","гейт WT нуля" if zstate else "WT против"),[]).append(rec)
for key in ("A) кросс WT нуля TP1R","A) кросс WT нуля TSL","B) флип+WPP TP1R","B) флип+WPP TSL"):
    subs=[k[1] for k in R if k[0]==key]
    if not subs: continue
    print(f"  ═══ {key} ═══")
    for sub in ("всё","по WPP","против WPP","гейт WT нуля","WT против"):
        if (key,sub) in R: rep(sub,R[(key,sub)])
    print()
